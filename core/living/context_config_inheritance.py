"""Inherited display settings in the existing TLS journal.

These records configure rendering only. They are not private conversation
registrations, data-access grants, or sending authority.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
import hashlib
import json

from .journal import LivingJournal, JournalConflict
from .models import canonical, private_scope

DEFAULTS = {'presence_context_enabled': True, 'presence_context_max_chars': 420,
            'presence_repeat_seconds': 300}
LIMITS = {'presence_context_max_chars': (160, 1200), 'presence_repeat_seconds': (30, 3600)}
LEVELS = ('global', 'platform', 'role', 'session')
LABELS = {'default': '默认值', 'global': '全局', 'platform': '当前平台与机器人',
          'role': '当前平台角色', 'session': '当前私聊会话'}
NAMESPACE = 'tls.context_config.inheritance.v1'
STORAGE_SCOPE = 'configuration'  # Never interpreted as a Presence scope/lease.


def validate(changes):
    if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
        raise ValueError('仅支持背景显示开关、字数和重述间隔')
    for key, value in changes.items():
        if key in LIMITS:
            low, high = LIMITS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{key} 必须为 {low}–{high} 的整数')
        elif type(value) is not bool:
            raise ValueError('背景开关必须为布尔值')
    return deepcopy(changes)


def _global_value(key, value):
    default = DEFAULTS[key]
    if value is None:
        return default
    if key in LIMITS:
        try:
            parsed = default if isinstance(value, bool) else int(value)
        except (ValueError, TypeError, OverflowError):
            return default
        low, high = LIMITS[key]
        return parsed if low <= parsed <= high else default
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {'false', '0', 'off', 'no', ''}:
            return False
        if token in {'true', '1', 'on', 'yes'}:
            return True
        return default
    return bool(value)


def selector(level, scope):
    if level not in LEVELS:
        raise ValueError('配置层级无效')
    if level == 'global':
        return {}
    scope = private_scope(scope)
    fields = ('platform', 'bot_id') if level == 'platform' else (
        ('platform', 'bot_id', 'character_id') if level == 'role' else
        ('platform', 'bot_id', 'user_id', 'character_id', 'session_id'))
    return {key: scope[key] for key in fields}


def _key(level, scope):
    return hashlib.sha256(canonical({'level': level, 'selector': selector(level, scope)}).encode()).hexdigest()


def journal_for(plugin):
    host = getattr(getattr(plugin, '_presence', None), 'living_host', None)
    runtime = getattr(host, 'runtime', None)
    journal = getattr(runtime, 'journal', None)
    return journal if (isinstance(journal, LivingJournal) and not journal._closed
        and getattr(runtime, 'active', False)) else None


class ContextConfigInheritance:
    def __init__(self, config, journal=None):
        self.config, self.journal = config, journal

    def _read(self, level, scope):
        if level == 'global':
            return {'values': {key: self.config[key] for key in DEFAULTS if key in self.config}, 'revision': 0}
        if self.journal is None:
            return {'values': {}, 'revision': 0}
        row = self.journal._db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
            (NAMESPACE, _key(level, scope), STORAGE_SCOPE)).fetchone()
        if row is None:
            return {'values': {}, 'revision': 0}
        data = json.loads(row['data'])
        if data.get('level') != level or data.get('selector') != selector(level, scope):
            raise ValueError('配置范围记录不一致')
        return {'values': validate(data['values']), 'revision': row['revision']}

    def _snapshot(self, scope, level):
        selected = selector(level, scope)
        chain = LEVELS[:LEVELS.index(level) + 1]
        effective, sources = deepcopy(DEFAULTS), {key: 'default' for key in DEFAULTS}
        layers = []
        for name in chain:
            row = self._read(name, scope)
            values = ({key: _global_value(key, value) for key, value in row['values'].items()}
                if name == 'global' else validate(row['values']))
            for key, value in values.items():
                effective[key], sources[key] = value, name
            layers.append({'level': name, 'label': LABELS[name], **row, 'values': values})
        current = layers[-1]['values']
        fingerprint = {'level': level, 'selector': selected, 'layers': layers}
        revision = hashlib.sha256(canonical(fingerprint).encode()).hexdigest()
        return {'level': level, 'level_label': LABELS[level], 'selector': selected,
            'defaults': deepcopy(DEFAULTS), 'values': effective, 'overrides': deepcopy(current),
            'sources': {key: {'level': value, 'label': LABELS[value]} for key, value in sources.items()},
            'fields': [{'key': key, 'default': DEFAULTS[key], 'value': effective[key],
                        'source': sources[key], 'source_label': LABELS[sources[key]],
                        'overridden': key in current, 'override': current.get(key)} for key in DEFAULTS],
            'layers': layers, 'revision': revision,
            'writable': callable(getattr(self.config, 'save_config', None)) if level == 'global' else self.journal is not None,
            'scope_required': level != 'global',
            'boundary': '仅背景显示配置；不登记会话、不授予来源读取或消息发送权限。'}

    def snapshot(self, scope=None, level='global'):
        if self.journal is None:
            return self._snapshot(scope, level)
        with self.journal._lock:
            self.journal._ensure_open()
            return self._snapshot(scope, level)

    def _changes(self, body):
        changes = validate(body.get('changes', {}))
        restore = body.get('restore', [])
        if (not isinstance(restore, list)
                or any(not isinstance(key, str) or key not in DEFAULTS for key in restore)
                or len(set(restore)) != len(restore)
                or set(changes) & set(restore) or not (changes or restore)):
            raise ValueError('修改与恢复继承字段无效')
        revision = body.get('expected_revision')
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
            raise ValueError('需要读取时的配置版本')
        return changes, restore, revision

    def save(self, body, scope=None, level='global'):
        changes, restore, expected = self._changes(body)
        selector(level, scope)
        if level == 'global':
            if not callable(getattr(self.config, 'save_config', None)):
                raise RuntimeError('配置持久化不可用')
            if self.snapshot(scope, level)['revision'] != expected:
                raise JournalConflict('configuration changed')
            old = {key: (key in self.config, deepcopy(self.config.get(key))) for key in set(changes) | set(restore)}
            try:
                self.config.update(changes)
                for key in restore:
                    self.config.pop(key, None)
                self.config.save_config()
            except BaseException:
                for key, (existed, value) in old.items():
                    if existed:
                        self.config[key] = value
                    else:
                        self.config.pop(key, None)
                raise
            return self.snapshot(scope, level)
        journal = self.journal
        if journal is None:
            raise RuntimeError('TLS配置存储尚未挂载')
        with journal._transaction() as db:
            current = self._snapshot(scope, level)
            if current['revision'] != expected:
                raise JournalConflict('configuration changed')
            row = self._read(level, scope)
            values = row['values']
            values.update(changes)
            for key in restore:
                values.pop(key, None)
            identity = _key(level, scope)
            if row['revision'] == 0:
                count = db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=?', (NAMESPACE,)).fetchone()[0]
                total = db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
                if count >= 256 or total >= journal.max_records:
                    raise RuntimeError('配置覆盖记录容量已满')
            data = canonical({'level': level, 'selector': selector(level, scope), 'values': values})
            # Keep an empty tombstone with an advanced revision after restore.
            db.execute('INSERT INTO checkpoints(namespace,key,scope,revision,updated,data) VALUES(?,?,?,?,?,?) '
                'ON CONFLICT(namespace,key,scope) DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
                (NAMESPACE, identity, STORAGE_SCOPE, row['revision'] + 1, float(journal.clock()), data))
            return self._snapshot(scope, level)

    def any_local_context_enabled(self):
        if self.journal is None:
            return False
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self.journal._db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? LIMIT 256',
                (NAMESPACE, STORAGE_SCOPE))
            return any(json.loads(row['data']).get('values', {}).get('presence_context_enabled') is True for row in rows)


def effective_context_values(plugin, scope=None):
    with getattr(plugin, '_native_console_config_lock', None) or nullcontext():
        store = ContextConfigInheritance(plugin.config, journal_for(plugin))
        return store.snapshot(scope, 'session' if scope is not None else 'global')['values']


def any_context_enabled(plugin):
    with getattr(plugin, '_native_console_config_lock', None) or nullcontext():
        store = ContextConfigInheritance(plugin.config, journal_for(plugin))
        return store.snapshot()['values']['presence_context_enabled'] or store.any_local_context_enabled()
