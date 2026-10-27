"""Native App rule editor over the current configuration and phone executor."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import re
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.native_app_rules import NativeAppRules, parse_rule_config
from .core.living.native_phone_companion import NativePhoneCompanion
from .core.living.native_phone_messages import NativePhoneMessages
from .memory_web_api import SCOPE_FIELDS, _scope
from .phone_web_api import NativePhoneWebApi

PREFIX = '/astrbot_plugin_virtual_body/page/app-rules'
KEY = 'living_app_rules'
LABELS = {'com.hypergryph.arknights': '明日方舟', 'com.hypergryph.arknights.bilibili': '明日方舟 · 渠道服',
          'com.tencent.tmgp.sgame': '王者荣耀', 'tv.danmaku.bili': '哔哩哔哩',
          'com.netease.cloudmusic': '网易云音乐'}


def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
class RulesConflict(RuntimeError): pass


class NativeAppRulesWebApi:
    def __init__(self, plugin):
        self.plugin = plugin
        self.phone_api = NativePhoneWebApi(plugin)
        self.lock = self.phone_api.lock

    def register_routes(self):
        for path, handler, method in [('config', self.config, 'GET'), ('config/save', self.save, 'POST'),
                                      ('preview', self.preview, 'POST')]:
            self.plugin.context.register_web_api(PREFIX+'/'+path, handler, [method], 'TLS native App rules '+path)

    def _host(self, scope, *, management=False):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        if (host is None or getattr(self.plugin, '_stopping', False)
                or getattr(host, '_closed', False)):
            raise RuntimeError('current App rule host unavailable')
        if host.authorized_scope(scope) is True:
            return host
        if management:
            runtime = getattr(host, 'runtime', None)
            memory = getattr(runtime, 'memory', None)
            resolve = getattr(self.plugin, '_resolve_session', None)
            selected = resolve(scope['user_id']) if callable(resolve) else None
            if (getattr(runtime, 'active', False) is True
                    and isinstance(selected, tuple) and selected[0] == scope['character_id']):
                # Existing complete records establish historical ownership;
                # a configured role alone cannot invent the other four axes.
                rows = NativeAppRules(parse_rule_config(self.plugin.config.get(KEY, '[]'))).list(scope)
                store = getattr(memory, 'store', None)
                known = bool(rows)
                if (not known and getattr(memory, 'backend', None) == 'native'
                        and getattr(memory, 'active', False) is True
                        and callable(getattr(store, 'stats', None))):
                    known = store.stats(scope)['total'] > 0
                if known:
                    if getattr(getattr(self.plugin, '_presence', None), 'living_host', None) is not host:
                        raise RuntimeError('App rule host replaced')
                    return host
        if host.authorized_scope(scope) is not True:
            raise PermissionError('complete private scope unavailable')
        return host

    def _library_snapshot(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        companion = getattr(getattr(host, 'runtime', None), 'phone_companion', None)
        if isinstance(companion, NativePhoneCompanion) and companion.active:
            return deepcopy(companion.messages.export()['config']), companion
        return {'custom_lines': deepcopy(self.plugin._cfg('living_phone_custom_lines', []))}, None

    def _snapshot(self, scope, library_config):
        host = self._host(scope, management=True)
        with self.lock:
            config = self.plugin.config
            document, file_digest = self.phone_api._persisted_document()
            if any(key not in config or config[key] != value for key, value in document.items()):
                raise RulesConflict('configuration changed outside owner')
            raw = config.get(KEY, '[]')
            if raw != document.get(KEY, '[]'): raise RuntimeError('App rule persistence differs')
            rules = NativeAppRules(parse_rule_config(raw))
            library = NativePhoneMessages(**library_config)
            # Use the current whole configuration, not a frontend enabled flag.
            sources = {}
            for row in library.list(include_disabled=True):
                item = sources.setdefault(row['package'], {'package': row['package'],
                    'label': LABELS.get(row['package'], row['package']), 'kind': 'configured_app',
                    'connection_state': 'not_observed', 'message_count': 0})
                item['message_count'] += 1
            for row in rules.list(scope):
                sources.setdefault(row['package'], {'package': row['package'],
                    'label': LABELS.get(row['package'], row['package']), 'kind': 'configured_app',
                    'connection_state': 'not_connected', 'message_count': 0})
            result = {'scope': scope, 'rules': rules.list(scope), 'sources': list(sources.values()),
                'revision': digest([scope, rules.revision, file_digest]),
                'writable': callable(getattr(config, 'save_config', None)), 'persisted_verified': True,
                'capability': {'id': 'phone_companion', 'label': 'App 图文陪伴', 'trigger': 'app_enter'},
                'limits': {'app_cooldown_minutes': self.plugin._cfg('living_phone_app_cooldown_minutes', 120),
                           'shared_cooldown_minutes': self.plugin._cfg('living_phone_shared_cooldown_minutes', 10)},
                'image_policy': 'fresh_required',
                'access': 'authenticated_administrator',
                'authority': 'historical_administrator_materials',
                'live_scope_available': host.authorized_scope(scope) is True,
                'creates_send_permission': False,
                'boundary': '仅配置进入应用后的现有图文能力；保存规则不发送、不建立新定时器。未观测来源不等于已连接。'}
            if self._host(scope, management=True) is not host:
                raise RuntimeError('App rule host replaced')
            return result

    def _save(self, scope, body, library_config):
        if (not isinstance(body, dict) or set(body) != {'scope', 'rules', 'expected_revision'}
                or not isinstance(body['expected_revision'], str)
                or not re.fullmatch('[a-f0-9]{64}', body['expected_revision'])):
            raise ValueError('current configuration revision required')
        with self.lock:
            current = self._snapshot(scope, library_config)
            if current['revision'] != body['expected_revision']: raise RulesConflict('rules changed')
            if not current['writable']: raise RuntimeError('configuration save unavailable')
            config = self.plugin.config
            rules = NativeAppRules(parse_rule_config(config.get(KEY, '[]')))
            rules.replace_for_scope(scope, body['rules'])
            value = canonical(rules.export()['rules'])
            if len(value.encode()) > 65536: raise ValueError('App rule capacity')
            self._host(scope, management=True)
            existed = KEY in config; before = config.get(KEY)
            try:
                config[KEY] = value; config.save_config()
                persisted, _ = self.phone_api._persisted_document()
                if persisted.get(KEY, '[]') != value:
                    raise RuntimeError('App rule persistence reread differs')
                result = self._snapshot(scope, library_config)
                if result['rules'] != rules.list(scope): raise RuntimeError('saved App rules differ')
                return result
            except BaseException:
                if existed: config[KEY] = before
                else: config.pop(KEY, None)
                raise

    async def _preview(self, scope, body, library_config, companion):
        if (not isinstance(body, dict) or set(body)-{'scope', 'event', 'rule_id'}
                or not {'scope', 'event'} <= set(body)):
            raise ValueError('App sample and complete scope required')
        self._host(scope)
        # The executor supplies read-only real candidate and scheduling checks.
        # A missing executor cannot turn a configured rule into permission.
        if companion is not None and callable(getattr(companion, 'preview_rules', None)):
            result = await companion.preview_rules(scope, body['event'], rule_id=body.get('rule_id'))
        else:
            config = self.plugin.config
            rules = NativeAppRules(parse_rule_config(config.get(KEY, '[]')))
            from datetime import datetime, timezone, timedelta
            hour = datetime.now(timezone(timedelta(hours=8))).hour
            result = await asyncio.to_thread(rules.preview, scope, body['event'], NativePhoneMessages(**library_config),
                hour=hour, rule_id=body.get('rule_id'),
                app_cooldown_minutes=self.plugin._cfg('living_phone_app_cooldown_minutes', 120),
                shared_cooldown_minutes=self.plugin._cfg('living_phone_shared_cooldown_minutes', 10))
        self._host(scope)
        return result

    async def _handle(self, action):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('请先登录 AstrBot 管理后台', status_code=401)
        try:
            if action == 'config':
                query = dict(getattr(request, 'query', None) or {})
                if set(query)-set(SCOPE_FIELDS): raise ValueError('unexpected query fields')
                scope = _scope(dict(query)); body = None
            else:
                body = await request.json(default=None)
                if not isinstance(body, dict): raise ValueError('JSON object required')
                scope = _scope(body.get('scope'))
            self._host(scope, management=action != 'preview')
            library_config, companion = self._library_snapshot()
            if action == 'preview': result = await self._preview(scope, body, library_config, companion)
            else:
                result = await asyncio.to_thread(self._save, scope, body, library_config) if action == 'save' else await asyncio.to_thread(self._snapshot, scope, library_config)
            self._host(scope, management=action != 'preview')
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except PermissionError:
            return error_response('实际预览需当前真实私聊授权；资料编辑需已配置角色及可确证的完整历史范围', status_code=403)
        except RulesConflict:
            return error_response('配置已变更，请刷新后保存', status_code=409)
        except (ValueError, TypeError, KeyError):
            return error_response('应用规则参数无效，请检查来源、会话和冷却', status_code=400)
        except (RuntimeError, OSError, sqlite3.Error):
            return error_response('应用规则暂不可用，请稍后重试', status_code=503)

    async def config(self): return await self._handle('config')
    async def save(self): return await self._handle('save')
    async def preview(self): return await self._handle('preview')
