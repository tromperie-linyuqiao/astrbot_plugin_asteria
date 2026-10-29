"""Chat expressions over the existing manual asset files and LivingJournal.

The library is the existing AstrBot administrator-managed image collection.
An owned WebChat conversation is not treated as a QQ identity or execution
lease. Preferences, action definitions and typed presentation records carry
their own authenticated WebChat owner; no extra model or sender is created.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
import uuid

from PIL import Image

from ..state import _atomic_json
from .models import private_scope, scope_key
from .journal import JournalConflict
from .native_expression_assets import NativeExpressionAssets, NAMESPACE as ASSET_NAMESPACE, _terms


PREFERENCES = 'tls.chat.expression.preferences'
SEMANTICS = 'tls.chat.expression.semantics'
ACTIONS = 'tls.chat.expression.actions'
SETTINGS = 'tls.chat.expression.settings'
USER_PROFILE = 'tls.chat.user.profile'
SETTING_DEFAULTS = {'frequency': 'expressive', 'per_unit': True,
    'mode_policies': {'chat': 'semantic', 'roleplay': 'paragraph', 'technical': 'text_only'},
    'cooldown_seconds': 60, 'fragment_display': 'semantic'}
_LOCK = threading.RLock()
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_CLIENT_ID = re.compile(r'[A-Za-z0-9_.:-]{8,128}\Z')
DEFAULT_ACTIONS = (
    {'id': 'headpat', 'label': '摸头', 'description': '轻轻摸摸德克萨斯的头', 'enabled': True, 'quick': True, 'order': 0},
    {'id': 'poke', 'label': '轻戳', 'description': '轻轻戳一下德克萨斯，想引起她的注意', 'enabled': True, 'quick': True, 'order': 1},
    {'id': 'hold_hands', 'label': '牵手', 'description': '伸手牵住德克萨斯的手，陪她待一会儿', 'enabled': True, 'quick': True, 'order': 2},
    {'id': 'lean', 'label': '靠一会儿', 'description': '轻轻靠着德克萨斯休息一会儿', 'enabled': True, 'quick': True, 'order': 3},
)
USER_DEFAULT = {'favorite': False, 'liked': False, 'disliked': False, 'hidden': False, 'quick_send': False, 'quick_order': 0,
                'last_used': None, 'use_count': 0}
TEXAS_DEFAULT = {'weight': 0, 'contexts': [], 'last_used': None, 'use_count': 0, 'cooldown_seconds': 60}
_EMOTIONS = {
    '开心': ('开心', '高兴', '好耶', '哈哈', '嘿嘿', '笑', '太好了', '愉快', 'happy', 'great'),
    '喜欢': ('喜欢', '想你', '爱你', '爱着', '抱抱', '亲亲', '心动', '牵手', 'love', 'miss you'),
    '害羞': ('害羞', '脸红', '不好意思', '别逗', '羞', '心跳', 'shy'),
    '关心': ('担心', '照顾', '好好休息', '记得吃', '喝水', '别太累', '辛苦', '陪着', 'care'),
    '安心': ('没关系', '放心', '我在', '安心', '别怕', '不会离开', '没事的', 'safe'),
    '难过': ('难过', '委屈', '伤心', '哭', '抱歉', '对不起', '寂寞', 'sad', 'sorry'),
    '生气': ('生气', '讨厌', '哼', '不许', '烦', '气死', 'angry'),
    '无奈': ('无奈', '叹气', '真是', '拿你没办法', '唉', '无语'),
    '困倦': ('困', '晚安', '睡觉', '休息', '打哈欠', '累了', 'sleep'),
    '疑惑': ('疑惑', '为什么', '怎么回事', '什么意思', '不明白', '好奇', '嗯？', 'what'),
    '鼓励': ('加油', '可以的', '做得好', '相信你', '继续努力', '厉害', '棒', 'well done'),
    '思考': ('思考', '想一想', '想想看', '琢磨', '考虑一下', '让我想想', 'thinking'),
    '惊讶': ('惊讶', '震惊', '没想到', '居然', '竟然', '真的吗', 'surprised'),
    '得意': ('得意', '自豪', '果然', '那当然', '早就知道', 'proud'),
    '音乐': ('听歌', '听音乐', '配乐', '旋律', '背景音乐', 'bgm', 'music'),
}
_GENERIC_TAGS = {'德克萨斯', 'texas', '表情', '表情包', '图片', '日常', '聊天'}
_GENERIC_TERMS = _terms('德克萨斯表情图片使用这个时候可以现在今天一下这里我们你们')


class ChatExpressionError(ValueError):
    pass


def avatar_source(data_url):
    """Normalize one explicitly selected image; SDK attachments own its file."""
    if not isinstance(data_url, str) or len(data_url) > 1024 * 1024 or not re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+', data_url):
        raise ChatExpressionError('请选择不超过512KiB的头像图片')
    try:
        raw = base64.b64decode(data_url.split(',', 1)[1], validate=True)
        if not 0 < len(raw) <= 512 * 1024:
            raise ValueError('size')
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 16_000_000 or max(image.size) > 8192:
                raise ValueError('dimensions')
            image.load();image = image.convert('RGB');image.thumbnail((1280, 1280))
            for quality in (88, 80, 72, 64, 56, 48, 40):
                output = BytesIO();image.save(output, format='JPEG', quality=quality)
                if output.tell() <= 512 * 1024:
                    return output.getvalue()
            raise ValueError('output_size')
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise ChatExpressionError('头像图片不可读取或过大') from exc


def avatar_crop(value):
    value = value if isinstance(value, dict) else {}
    if set(value) - {'x', 'y', 'zoom'}:
        raise ChatExpressionError('头像裁剪参数无效')
    result = {'x': value.get('x', 0.5), 'y': value.get('y', 0.5), 'zoom': value.get('zoom', 1.0)}
    for key, number in result.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not (1 <= number <= 3 if key == 'zoom' else 0 <= number <= 1):
            raise ChatExpressionError('头像裁剪位置或缩放无效')
    return result


def avatar_preview(raw, crop):
    crop = avatar_crop(crop)
    with Image.open(BytesIO(raw)) as image:
        side = min(image.size) / crop['zoom']
        left = (image.width - side) * crop['x'];top = (image.height - side) * crop['y']
        picture = image.convert('RGB').crop((left, top, left + side, top + side)).resize((256, 256), Image.Resampling.LANCZOS)
        output = BytesIO();picture.save(output, format='JPEG', quality=90)
    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()


class ChatUserProfile:
    def __init__(self, journal, *, current):
        self.journal, self.current = journal, current

    def get(self, username):
        row = self.journal.fetch(USER_PROFILE, 'profile', ChatExpressions.message_scope(username, 'user-profile'))
        return dict(row['data'] if row else {'avatar': None, 'crop': avatar_crop({}), 'updated_at': None}, revision=row['revision'] if row else 0)

    def save(self, username, avatar, crop, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ChatExpressionError('请重新读取头像版本再保存')
        value = {'avatar': avatar, 'crop': avatar_crop(crop), 'updated_at': time.time()}
        self.journal.put(USER_PROFILE, 'profile', ChatExpressions.message_scope(username, 'user-profile'), value,
                         expected_revision=expected_revision, authorize=self.current)
        return self.get(username)


def _text(value, name, limit, *, blank=False):
    if (not isinstance(value, str) or len(value) > limit or '\x00' in value
            or (not blank and not value.strip())):
        raise ChatExpressionError(name + '无效')
    return value.strip()


def _list_text(values, name, *, maximum=24, length=48):
    if not isinstance(values, list) or len(values) > maximum:
        raise ChatExpressionError(name + '数量无效')
    return list(dict.fromkeys(_text(item, name, length) for item in values))


def _normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def _positive_contains(text, phrase):
    """Small lexical evidence, not sentiment inference or another model call.

    A literal negated label is not affirmative evidence for that expression.
    Unknown or double-negated phrasing can stay text-only.
    """
    if not phrase:
        return False
    offset = 0
    while (at := text.find(phrase, offset)) >= 0:
        head = text[max(0, at - 8):at]
        end = at + len(phrase)
        word_boundary = not (re.match(r'[a-z0-9]', phrase[:1]) and at and re.match(r'[a-z0-9]', text[at - 1])) \
            and not (re.match(r'[a-z0-9]', phrase[-1:]) and end < len(text) and re.match(r'[a-z0-9]', text[end]))
        negated = re.search(r'(?:不|没|没有|并不|并没有|别|不要|不再|不是|并非|谈不上)(?:太|很|那么|怎么)?\s*$', head) \
            or re.search(r'\b(?:not|never|no)(?:\s+(?:very|really))?\s+$', text[max(0, at - 18):at])
        if word_boundary and not negated:
            return True
        offset = at + len(phrase)
    return False


def semantic_units(text):
    """Keep paragraphs and natural sentence groups; join tiny interjections.

    Punctuation alone is not a reason to create another bubble. Long passages
    are grouped; text with no usable image stays a speech fragment.
    """
    text = str(text or '')
    if '```' in text:
        return [text] if text else []
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', text) if part.strip()]
    units = []
    for paragraph in paragraphs:
        paragraph_start = len(units)
        if re.search(r'https?://\S+', paragraph):
            units.append(paragraph)
            continue
        sentences = re.findall(r'.*?(?:[。！？!?]+[”」』"]*|$)', paragraph, flags=re.S)
        pending = ''
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            pending += sentence
            if len(pending) >= 24 or (len(pending) >= 10 and sentence[-1:] in {'！', '!', '？', '?'}):
                units.append(pending)
                pending = ''
        if pending:
            if len(units) > paragraph_start and len(pending) < 8 and len(units[-1]) + len(pending) < 140:
                units[-1] += pending
            else:
                units.append(pending)
    if len(units) > 12:
        units = units[:11] + ['\n\n'.join(units[11:])]
    return units or ([text] if text else [])


class ChatExpressions:
    def __init__(self, journal, assets, *, current, attachments_dir, touch_catalog=None):
        self.journal, self.assets, self.current = journal, assets, current
        self.attachments_dir = Path(attachments_dir).resolve()
        self.touch_catalog = touch_catalog or (lambda: {'available': False, 'verbs': [], 'parts': []})

    def _check(self):
        if self.current() is not True or getattr(self.journal, '_closed', True) or not self.assets.active:
            raise RuntimeError('共享表情服务正在更新')

    @staticmethod
    def preference_scope(username, persona_id):
        # An administration-owned storage key, never passed to Presence or a
        # protected sender as a real-time permission / QQ binding.
        persona_id = persona_id if isinstance(persona_id, str) and persona_id else 'default'
        return private_scope({'platform': 'webchat', 'bot_id': 'astrbot-webchat',
            'user_id': username, 'character_id': persona_id, 'session_id': 'expression-preferences', 'private': True})

    @staticmethod
    def message_scope(username, session_id):
        return private_scope({'platform': 'webchat', 'bot_id': 'astrbot-webchat',
            'user_id': username, 'character_id': 'webchat', 'session_id': session_id, 'private': True})

    def _admin_assets(self):
        return NativeExpressionAssets(self.journal, assets_root=self.assets._root,
            authorize=lambda scope: self.current() is True and self.assets.active is True,
            clock=self.assets.clock)

    def _catalog(self, *, include_disabled=False):
        self._check()
        service = self._admin_assets()
        try:
            with self.journal._lock:
                self.journal._ensure_open()
                rows = self.journal._db.execute(
                    'SELECT data FROM checkpoints WHERE namespace=? ORDER BY scope,key LIMIT ?',
                    (ASSET_NAMESPACE, min(self.journal.max_records, 50000) + 1)).fetchall()
            result = []
            for value in rows:
                record = json.loads(value[0])
                scope = private_scope(record['scope'])
                row = service.get(scope, record['id'])
                if row is None or (not include_disabled and not row['enabled']):
                    continue
                identity = hashlib.sha256((scope_key(scope) + ':' + row['id']).encode()).hexdigest()
                extras = self.journal.fetch(SEMANTICS, row['id'], scope)
                extra = extras['data'] if extras else {}
                result.append({'id': identity, 'asset_id': identity, 'name': extra.get('name') or row['caption'][:32] or '表情 ' + row['id'][:6],
                    'meaning': row['caption'], 'tags': row['tags'],
                    'scenarios': extra.get('scenarios', []), 'pairing': extra.get('pairing', ''),
                    'enabled': row['enabled'], 'mime_type': row['media_type'], 'revision': row['revision'],
                    'width': row['width'], 'height': row['height'], 'resource_ref': identity,
                    '_scope': scope, '_asset_id': row['id']})
            self._check()
            return result
        finally:
            service.stop()

    def asset(self, identity, *, allow_disabled=False):
        if not isinstance(identity, str) or not _HEX.fullmatch(identity):
            raise ChatExpressionError('表情编号无效')
        row = next((row for row in self._catalog(include_disabled=allow_disabled) if row['id'] == identity), None)
        if row is None:
            raise KeyError('表情不存在或已停用')
        return row

    def _preference(self, scope, identity, actor):
        key = actor + ':' + identity
        record = self.journal.fetch(PREFERENCES, key, scope)
        return dict(USER_DEFAULT if actor == 'user' else TEXAS_DEFAULT, **(record['data'] if record else {}))

    def list(self, scope, *, query='', filter_name='all'):
        if filter_name not in {'all', 'favorites', 'recent', 'hidden', 'disliked', 'frequent', 'disabled'}:
            raise ChatExpressionError('表情筛选无效')
        query = _normalize(_text(query, '搜索内容', 160, blank=True))
        result = []
        for row in self._catalog(include_disabled=True):
            user, texas = self._preference(scope, row['id'], 'user'), self._preference(scope, row['id'], 'texas')
            if filter_name == 'disabled' and row['enabled']:
                continue
            if filter_name not in {'all', 'disabled', 'hidden'} and not row['enabled']:
                continue
            if query and query not in _normalize(' '.join([row['name'], row['meaning'], *row['tags'], *row['scenarios']])):
                continue
            if filter_name not in {'all', 'hidden', 'disabled'} and user['hidden']:
                continue
            if filter_name == 'favorites' and not user['favorite']:
                continue
            if filter_name == 'hidden' and not user['hidden']:
                continue
            if filter_name == 'disliked' and not user['disliked']:
                continue
            if filter_name in {'recent', 'frequent'} and not user['last_used']:
                continue
            public = {key: value for key, value in row.items() if not key.startswith('_')}
            public.update(user_preference=user, texas_preference=texas,
                          last_used=max(user['last_used'] or 0, texas['last_used'] or 0) or None)
            result.append(public)
        if filter_name == 'recent':
            result.sort(key=lambda row: row['user_preference']['last_used'] or 0, reverse=True)
        elif filter_name == 'frequent':
            result.sort(key=lambda row: row['user_preference']['use_count'], reverse=True)
        else:
            result.sort(key=lambda row: (row['user_preference']['quick_order'], not row['user_preference']['favorite'], row['name']))
        return {'items': result, 'total': len(result), 'shared_library': 'existing_tls_manual_assets',
                'preference_scope': {'owner': scope['user_id'], 'persona_id': scope['character_id']},
                'preference_separation': ['user', 'texas']}

    def preview(self, identity):
        row = self.asset(identity, allow_disabled=True)
        assets = self._admin_assets()
        try:
            raw = assets.read_bytes(row['_scope'], row['_asset_id'], expected_revision=row['revision'])
        finally:
            assets.stop()
        # A transient preview is derived in memory, not another maintained asset.
        with Image.open(BytesIO(raw)) as image:
            image.seek(0)
            image = image.convert('RGBA')
            image.thumbnail((320, 320), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format='PNG', optimize=True)
        self._check()
        return {'asset_id': identity, 'name': row['name'], 'mime_type': 'image/png',
                'data_url': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')}

    def preference(self, scope, identity, actor, changes):
        self.asset(identity, allow_disabled=True)
        if actor not in {'user', 'texas'} or not isinstance(changes, dict) or not changes:
            raise ChatExpressionError('偏好参数无效')
        allowed = {'favorite', 'liked', 'disliked', 'hidden', 'quick_send', 'quick_order'} if actor == 'user' else {'weight', 'contexts', 'cooldown_seconds'}
        if set(changes) - allowed:
            raise ChatExpressionError('不能修改另一方偏好或伪造使用记录')
        if actor == 'user':
            if any(type(value) is not bool for key, value in changes.items() if key != 'quick_order'):
                raise ChatExpressionError('用户偏好须为开关')
            if 'quick_order' in changes and (type(changes['quick_order']) is not int or not -1000 <= changes['quick_order'] <= 1000):
                raise ChatExpressionError('快捷排序需为 -1000 到 1000')
        else:
            if 'weight' in changes and (type(changes['weight']) not in (int, float) or not math.isfinite(changes['weight']) or not -3 <= changes['weight'] <= 3):
                raise ChatExpressionError('角色偏好权重需为 -3 到 3')
            if 'cooldown_seconds' in changes and (type(changes['cooldown_seconds']) is not int or not 0 <= changes['cooldown_seconds'] <= 86400):
                raise ChatExpressionError('重复冷却需为 0 到 86400 秒')
            if 'contexts' in changes:
                changes = dict(changes, contexts=_list_text(changes['contexts'], '适用语境', maximum=16))
        with _LOCK:
            value = dict(self._preference(scope, identity, actor), **changes)
            self.journal.put(PREFERENCES, actor + ':' + identity, scope, value, authorize=self.current)
        return {'asset_id': identity, 'actor': actor, 'preference': value}

    def metadata(self, identity, changes):
        row = self.asset(identity, allow_disabled=True)
        if not isinstance(changes, dict) or not changes or set(changes) - {'name', 'meaning', 'tags', 'scenarios', 'pairing', 'enabled'}:
            raise ChatExpressionError('素材语义参数无效')
        current = self.journal.fetch(SEMANTICS, row['_asset_id'], row['_scope'])
        values = dict(current['data'] if current else {})
        shared_patch = {}
        for key, value in changes.items():
            if key == 'enabled':
                if type(value) is not bool:
                    raise ChatExpressionError('素材启用状态须为开关')
                shared_patch['enabled'] = value
                continue
            normalized = (_list_text(value, '标签/场景', maximum=16, length=32) if key in {'tags', 'scenarios'}
                          else _text(value, key, 300 if key in {'meaning', 'pairing'} else 64, blank=key != 'name'))
            if key in {'meaning', 'tags'}:
                shared_patch['caption' if key == 'meaning' else 'tags'] = normalized
            else:
                values[key] = normalized
        if shared_patch:
            assets = self._admin_assets()
            try:
                assets.update(row['_scope'], row['_asset_id'], shared_patch, expected_revision=row['revision'])
            finally:
                assets.stop()
        if values or current is not None:
            self.journal.put(SEMANTICS, row['_asset_id'], row['_scope'], values, authorize=self.current)
        return {'asset_id': identity, 'metadata': {**values, **{key: changes[key] for key in ('meaning', 'tags', 'enabled') if key in changes}}}

    def _used(self, scope, identity, actor):
        value = self._preference(scope, identity, actor)
        value.update(last_used=float(time.time()), use_count=value['use_count'] + 1)
        self.journal.put(PREFERENCES, actor + ':' + identity, scope, value, authorize=self.current)

    def actions(self, scope):
        record = self.journal.fetch(ACTIONS, 'definitions', scope)
        items = deepcopy(record['data']['items'] if record else list(DEFAULT_ACTIONS))
        return {'items': sorted(items, key=lambda row: (row['order'], row['id'])), 'revision': record['revision'] if record else 0,
                'native_touch': self.touch_catalog(), 'defaults': deepcopy(list(DEFAULT_ACTIONS))}

    def save_action(self, scope, op, record, request_id=None, expected_revision=None):
        if op not in {'create', 'update', 'delete', 'import'} or not isinstance(record, dict):
            raise ChatExpressionError('动作操作无效')
        with _LOCK:
            snapshot = self.actions(scope)
            if expected_revision is not None:
                if type(expected_revision) is not int or expected_revision < 0:
                    raise ChatExpressionError('请先读取当前动作版本')
                if expected_revision != snapshot['revision']:
                    raise JournalConflict('动作已在其他位置修改，请重新读取后再保存')
            rows = {row['id']: row for row in snapshot['items']}
            if op == 'import':
                values = record.get('items')
                if not isinstance(values, list) or not 1 <= len(values) <= 64:
                    raise ChatExpressionError('每批导入1至64个动作组合')
                for value in values:
                    if not isinstance(value, dict):
                        raise ChatExpressionError('动作组合格式无效')
                    existing = rows.get(value.get('id')) if isinstance(value.get('id'), str) else None
                    value = self._action_record(value, len(rows), existing=existing)
                    rows[value['id']] = value
                if len(rows) > 256:
                    raise ChatExpressionError('最多保存256个动作组合')
                self.journal.put(ACTIONS, 'definitions', scope, {'items': list(rows.values())},
                    expected_revision=snapshot['revision'], authorize=self.current)
                return self.actions(scope)
            identity = record.get('id')
            if op == 'create' and not identity:
                identity = 'action-' + (hashlib.sha256(str(request_id).encode()).hexdigest()[:24] if request_id else uuid.uuid4().hex)
            identity = _text(identity, '动作编号', 80)
            if not re.fullmatch(r'[A-Za-z0-9_.:-]+', identity):
                raise ChatExpressionError('动作编号无效')
            if op == 'delete':
                rows.pop(identity, None)
            else:
                if op == 'update' and identity not in rows:
                    raise KeyError('动作不存在')
                value = {**rows.get(identity, {}), **record, 'id': identity}
                value['label'] = _text(value.get('label'), '动作名称', 32)
                value['description'] = _text(value.get('description'), '动作含义', 500)
                for key in ('enabled', 'quick'):
                    value.setdefault(key, True)
                    if type(value[key]) is not bool:
                        raise ChatExpressionError('动作启用与快捷栏状态须为开关')
                value.setdefault('order', len(rows))
                if type(value['order']) is not int or not -1000 <= value['order'] <= 1000:
                    raise ChatExpressionError('动作排序无效')
                value = self._action_record(value, len(rows), existing=rows.get(identity) if op == 'update' else None)
                if op == 'create' and identity in rows and rows[identity] != value:
                    raise ChatExpressionError('动作编号已存在')
                rows[identity] = value
            if len(rows) > 256:
                raise ChatExpressionError('最多保存256个动作')
            self.journal.put(ACTIONS, 'definitions', scope, {'items': list(rows.values())},
                expected_revision=snapshot['revision'], authorize=self.current)
        return self.actions(scope)

    def _action_record(self, value, order, *, existing=None):
        identity = _text(value.get('id'), '动作编号', 80)
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+', identity):
            raise ChatExpressionError('动作编号无效')
        result = dict(id=identity, label=_text(value.get('label'), '动作名称', 32),
            description=_text(value.get('description'), '动作含义', 500),
            enabled=value.get('enabled', True), quick=value.get('quick', True), order=value.get('order', order))
        if any(type(result[key]) is not bool for key in ('enabled', 'quick')) or type(result['order']) is not int or not -1000 <= result['order'] <= 1000:
            raise ChatExpressionError('动作启用或排序无效')
        if value.get('native_touch') is not None:
            if (existing is not None and existing.get('id') == identity
                    and existing.get('native_touch') == value['native_touch']):
                # Maintaining an unchanged saved binding is not permission to
                # execute it. user_parts still validates against the live
                # catalogue without this maintenance-only existing record.
                result['native_touch'] = deepcopy(existing['native_touch'])
            else:
                from .chat_sessions import validate_touch
                result['native_touch'] = validate_touch(self.touch_catalog(), value['native_touch'])
        return result

    def settings_get(self, scope, session_id):
        self._check()
        if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
            raise ChatExpressionError('会话编号无效')
        role = self.journal.fetch(SETTINGS, 'role', scope)
        session = self.journal.fetch(SETTINGS, 'session:' + hashlib.sha256(session_id.encode()).hexdigest(), scope)
        role_values, session_values = (role['data'] if role else {}), (session['data'] if session else {})
        effective = deepcopy(SETTING_DEFAULTS)
        effective.update(role_values)
        effective.update(session_values)
        sources = {key: 'session' if key in session_values else 'role' if key in role_values else 'default' for key in SETTING_DEFAULTS}
        return {'defaults': deepcopy(SETTING_DEFAULTS), 'role': role_values, 'session': session_values,
            'effective': effective, 'sources': sources, 'overridden': list(session_values),
            'role_revision': role['revision'] if role else 0,
            'session_revision': session['revision'] if session else 0}

    def settings_save(self, scope, session_id, *, level='session', changes=None, reset=False, expected_revision=None):
        if level not in {'session', 'role'} or type(reset) is not bool:
            raise ChatExpressionError('设置层级或恢复参数无效')
        snapshot = self.settings_get(scope, session_id)
        if reset:
            value = {}
        else:
            if not isinstance(changes, dict) or not changes or set(changes) - set(SETTING_DEFAULTS):
                raise ChatExpressionError('表达设置字段无效')
            value = dict(snapshot[level], **changes)
            if value.get('frequency', 'expressive') not in {'off', 'low', 'balanced', 'expressive'}:
                raise ChatExpressionError('表情频率无效')
            if 'per_unit' in value and type(value['per_unit']) is not bool:
                raise ChatExpressionError('语义单元配图须为开关')
            if 'cooldown_seconds' in value and (type(value['cooldown_seconds']) is not int or not 0 <= value['cooldown_seconds'] <= 86400):
                raise ChatExpressionError('重复冷却需为 0 到 86400 秒')
            if value.get('fragment_display', 'semantic') not in {'semantic', 'compact'}:
                raise ChatExpressionError('片段展示方式无效')
            if 'mode_policies' in value:
                policies = value['mode_policies']
                if (not isinstance(policies, dict) or set(policies) != {'chat', 'roleplay', 'technical'}
                        or any(policy not in {'semantic', 'paragraph', 'single', 'text_only'} for policy in policies.values())):
                    raise ChatExpressionError('模式配图策略无效')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ChatExpressionError('设置版本无效')
        key = 'role' if level == 'role' else 'session:' + hashlib.sha256(session_id.encode()).hexdigest()
        revision = snapshot[level + '_revision'] if expected_revision is None else expected_revision
        self.journal.put(SETTINGS, key, scope, value, expected_revision=revision, authorize=self.current)
        return self.settings_get(scope, session_id)

    @staticmethod
    def identified(parts, seed):
        values = []
        seen = set()
        for index, part in enumerate(parts):
            part = dict(part)
            fragment = part.get('fragment_id')
            if not isinstance(fragment, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', fragment) or fragment in seen:
                raw = json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                fragment = 'part-' + hashlib.sha256((str(seed) + ':' + str(index) + ':' + raw).encode()).hexdigest()[:24]
            seen.add(fragment)
            part.update(fragment_id=fragment, order=index)
            values.append(part)
        return values

    def user_parts(self, scope, parts, message, *, references=None, attachments=None):
        if parts is None:
            parts = [{'type': 'text', 'text': message}] if message.strip() else []
        if not isinstance(parts, list) or len(parts) > 24:
            raise ChatExpressionError('组合消息最多 24 个片段')
        result, projection = [], []
        actions = {row['id']: row for row in self.actions(scope)['items'] if row['enabled']}
        action_count = sticker_count = attachment_count = reference_count = 0
        for part in parts:
            if not isinstance(part, dict):
                raise ChatExpressionError('消息片段无效')
            kind = part.get('type')
            fragment = part.get('fragment_id')
            if kind in {'text', 'speech', 'plain'}:
                _text(part.get('text'), '消息文字', 16000, blank=True)
                text = part['text']
                if text.strip():
                    result.append({'type': 'text', 'text': text, 'source': 'user_speech', 'fragment_id': fragment})
                    projection.append(text)
            elif kind == 'action':
                identity = part.get('action_id', part.get('id'))
                action = actions.get(identity)
                if action is None:
                    raise ChatExpressionError('动作不存在或已停用，请刷新动作面板')
                action_count += 1
                result.append({'type': 'action', 'action_id': identity, 'label': action['label'],
                    'description': action['description'], 'source': 'user_action', 'fragment_id': fragment,
                    **({'native_touch': self._action_record(action, 0)['native_touch']} if action.get('native_touch') else {})})
                projection.append('【用户角色互动输入（非现实感知）：' + action['label'] + '】' + action['description'])
            elif kind == 'sticker':
                asset = self.asset(part.get('asset_id'))
                user = self._preference(scope, asset['id'], 'user')
                if user['hidden']:
                    raise ChatExpressionError('这个表情已隐藏，请先恢复')
                sticker_count += 1
                result.append({'type': 'sticker', 'asset_id': asset['id'], 'label': asset['name'],
                    'source': 'user_sticker', 'fragment_id': fragment})
                projection.append('【用户表情：' + asset['name'] + '】' + asset['meaning'])
            elif kind == 'reference':
                reference = (references or {}).get(str(part.get('message_id')))
                if reference is None:
                    raise ChatExpressionError('引用消息不存在或不属于当前会话')
                reference_count += 1
                result.append(dict(reference, type='reference', fragment_id=fragment))
                projection.append('【引用当前会话消息】' + reference['text'])
            elif kind in {'attachment', 'image', 'file', 'record', 'video'}:
                media = (attachments or {}).get(part.get('attachment_id'))
                if media is None:
                    raise ChatExpressionError('附件需要先上传并验证归属')
                attachment_count += 1
                result.append(dict(media, fragment_id=fragment, source='user_attachment'))
            else:
                raise ChatExpressionError('不支持这个消息片段类型')
        if action_count > 4 or sticker_count > 4 or attachment_count > 4 or reference_count > 2:
            raise ChatExpressionError('每条最多 4 个动作、4 张表情、4 个附件和 2 条引用')
        if not any(part['type'] == 'text' for part in result) and message.strip():
            result.insert(0, {'type': 'text', 'text': message, 'source': 'user_speech'})
            projection.insert(0, message)
        projected = '\n'.join(projection)
        if len(projected) > 20000:
            raise ChatExpressionError('组合消息过长')
        return self.identified(result, 'user-composition'), projected

    def _sidecar_dir(self, scope, *, create=False):
        self._check()
        root = self.attachments_dir / '.tls-chat-expression-parts'
        directory = root / scope_key(scope)
        if root.is_symlink() or directory.is_symlink():
            raise RuntimeError('聊天表达记录目录无效')
        if create:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.resolve().parent != root.resolve() or root.resolve().parent != self.attachments_dir:
            raise RuntimeError('聊天表达记录目录无效')
        return directory

    def begin(self, scope, client_id, parts, *, request_digest):
        if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
            raise ChatExpressionError('组合消息需要稳定 client_message_id')
        key = hashlib.sha256((scope_key(scope) + ':' + client_id).encode()).hexdigest()[:32]
        directory = self._sidecar_dir(scope, create=True)
        path = directory / ('request-' + key + '.json')
        checkpoint = str(uuid.UUID(key))
        value = {'schema': 1, 'client_message_id': client_id, 'scope': scope, 'parts': parts,
                 'checkpoint_id': checkpoint, 'request_digest': request_digest, 'status': 'started', 'created_at': time.time()}
        with _LOCK:
            try:
                with path.open('x', encoding='utf-8') as output:
                    json.dump(value, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
            except FileExistsError:
                if path.is_symlink():
                    raise RuntimeError('聊天表达记录不可为链接')
                old = json.loads(path.read_text(encoding='utf-8'))
                if old.get('request_digest') != request_digest:
                    raise ChatExpressionError('同一消息编号不能用于不同内容')
                return dict(old, duplicate=True)
        return dict(value, duplicate=False)

    def _record_path(self, scope, role, record_id):
        key = hashlib.sha256(str(record_id).encode()).hexdigest()
        return self._sidecar_dir(scope, create=True) / (role + '-' + key + '.json')

    def saved_parts(self, scope, role, record_id):
        path = self._record_path(scope, role, record_id)
        if not path.exists():
            return None
        if path.is_symlink():
            raise RuntimeError('聊天表达记录不可为链接')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('scope') != scope or data.get('record_id') != str(record_id) or data.get('role') != role:
            raise RuntimeError('聊天表达归属记录不一致')
        return data['parts']

    def save_parts(self, scope, role, record_id, parts):
        path = self._record_path(scope, role, record_id)
        with _LOCK:
            current = self.saved_parts(scope, role, record_id)
            if current is not None:
                return current
            parts = self.identified(parts, role + ':' + str(record_id))
            value = {'schema': 1, 'scope': scope, 'record_id': str(record_id), 'role': role,
                     'parts': parts, 'created_at': time.time()}
            _atomic_json(str(path), value, compact=True)
        return parts

    def bind_user(self, message_scope, preference_scope, submission, record_id, attachments=()):
        parts = [dict(part) for part in submission['parts']]
        # This receipt came from the original parser/BodyStore before SDK send,
        # not from a submitted client field. Persist it with the actual saved
        # user row so reconnect/history does not lose the interaction outcome.
        receipt = submission.get('native_touch')
        if not isinstance(receipt, dict):
            actual = self.checkpoint_submission(message_scope, submission['checkpoint_id'])
            receipt = actual.get('native_touch') if actual else None
        if isinstance(receipt, dict):
            results = {row.get('fragment_id'): row for row in receipt.get('results', [])
                       if isinstance(row, dict) and row.get('fragment_id')}
            for part in parts:
                result = results.get(part.get('fragment_id'))
                if part.get('type') == 'action' and part.get('source') == 'user_action' and result is not None:
                    part['native_result'] = {key: result.get(key) for key in ('state', 'applied', 'parts', 'verb')}
                    part['native_result'].update(source='tls.chat.native_touch',
                        character=receipt.get('character'), applied_at=receipt.get('applied_at'),
                        body_updated_at=receipt.get('body_updated_at'))
        included = {part.get('attachment_id') for part in parts if part.get('attachment_id')}
        parts.extend(dict(part) for part in attachments if part.get('attachment_id') not in included)
        with _LOCK:
            self.mark_submission(message_scope, submission, status='user_saved', user_record_id=str(record_id))
            previous = self.saved_parts(message_scope, 'user', record_id)
            if previous is not None:
                return previous
            saved = self.save_parts(message_scope, 'user', record_id, parts)
            for part in parts:
                if part.get('type') == 'sticker':
                    self._used(preference_scope, part['asset_id'], 'user')
        return saved

    def mark_submission(self, scope, submission, **changes):
        key = hashlib.sha256((scope_key(scope) + ':' + submission['client_message_id']).encode()).hexdigest()[:32]
        path = self._sidecar_dir(scope) / ('request-' + key + '.json')
        with _LOCK:
            if path.is_symlink():
                raise RuntimeError('聊天表达记录不可为链接')
            current = json.loads(path.read_text(encoding='utf-8'))
            if current.get('scope') != scope or current.get('checkpoint_id') != submission['checkpoint_id']:
                raise RuntimeError('聊天表达提交记录不一致')
            current.update(changes, updated_at=time.time())
            _atomic_json(str(path), current, compact=True)

    def checkpoint_submission(self, scope, checkpoint_id):
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            return None
        try:
            key = uuid.UUID(checkpoint_id).hex
        except (ValueError, AttributeError):
            return None
        path = self._sidecar_dir(scope) / ('request-' + key + '.json')
        if not path.is_file() or path.is_symlink():
            return None
        record = json.loads(path.read_text(encoding='utf-8'))
        return record if record.get('scope') == scope and record.get('checkpoint_id') == checkpoint_id else None

    def assistant_parts(self, message_scope, preference_scope, record_id, content, *, context=None):
        with _LOCK:
            saved = self.saved_parts(message_scope, 'assistant', record_id)
            if saved is not None:
                return saved
            originals = content.get('message', []) if isinstance(content, dict) else []
            from .structured_reply import parse as parse_expression
            expanded=[]
            for original in originals:
                structured=(parse_expression(original.get('text','')) if isinstance(original,dict)
                    and original.get('type')=='plain' and original.get('chain_type')not in {'reasoning','tool_call','tool_call_result'} else None)
                if structured is None:expanded.append(original)
                else:
                    expanded.extend({'type':'tls_narrative'if p['type']=='action'else'plain','text':p['text']}for p in structured)
            originals=expanded
            result, used = [], set()
            context = context if isinstance(context, dict) else {}
            settings = self.settings_get(preference_scope, message_scope['session_id'])['effective']
            mode = context.get('mode', 'roleplay' if context.get('roleplay') else 'chat')
            policy = settings['mode_policies'].get(mode, 'semantic')
            catalog = self._catalog()
            unit_index = 0
            for part in originals:
                if not isinstance(part, dict):
                    continue
                if part.get('type')=='tls_narrative':
                    result.append({'type':'action','label':'德克萨斯的动作','description':part['text'],
                        'source':'assistant_narrative'})
                    continue
                if part.get('type') != 'plain':
                    if part.get('type') in {'image', 'file', 'record', 'video'}:
                        result.append({key: value for key, value in part.items() if key not in {'path', 'file_path'}})
                    continue
                if part.get('chain_type') in {'reasoning', 'tool_call', 'tool_call_result'}:
                    continue
                raw_text = part.get('text', '')
                if policy in {'single', 'text_only'} or settings['fragment_display'] == 'compact':
                    units = [raw_text] if raw_text else []
                elif policy == 'paragraph':
                    units = [text.strip() for text in re.split(r'\n\s*\n', raw_text) if text.strip()]
                else:
                    units = semantic_units(raw_text)
                if len(units) > 8:
                    units = units[:7] + ['\n\n'.join(units[7:])]
                for unit in units:
                    result.append({'type': 'speech', 'text': unit, 'source': 'assistant_speech'})
                    spacing = {'off': 0, 'low': 3, 'balanced': 2, 'expressive': 1}[settings['frequency']]
                    eligible = spacing and unit_index % spacing == 0 and policy != 'text_only'
                    if used and (not settings['per_unit'] or policy == 'single'):
                        eligible = False
                    selected = self._select(preference_scope, unit, catalog, used,
                        context=context, cooldown=settings['cooldown_seconds']) if eligible else None
                    unit_index += 1
                    if selected:
                        used.add(selected['id'])
                        result.append({'type': 'sticker', 'asset_id': selected['id'], 'label': selected['name'], 'source': 'assistant_expression'})
            saved = self.save_parts(message_scope, 'assistant', record_id, result)
            for identity in used:
                self._used(preference_scope, identity, 'texas')
            return saved

    def _select(self, scope, text, catalog, used, *, context=None, cooldown=60):
        if '```' in text or re.search(r'https?://\S+', text):
            return None
        query = _normalize(text)
        terms = _terms(query) - _GENERIC_TERMS
        emotions = {emotion for emotion, triggers in _EMOTIONS.items()
                    if any(_positive_contains(query, word) for word in triggers)}
        context = context if isinstance(context, dict) else {}
        surroundings = _normalize(' '.join(str(context.get(key) or '') for key in
            ('persona_id', 'scene', 'input_text', 'conversation_text')))[-5000:]
        now, ranked = time.time(), []
        for row in catalog:
            if row['id'] in used or not row['enabled']:
                continue
            user, texas = self._preference(scope, row['id'], 'user'), self._preference(scope, row['id'], 'texas')
            if user['hidden'] or user['disliked'] or texas['weight'] <= -3:
                continue
            if texas['last_used'] and now - texas['last_used'] < max(cooldown, texas['cooldown_seconds']):
                continue
            tags = [_normalize(tag) for tag in row['tags'] if _normalize(tag) not in _GENERIC_TAGS]
            meaning = _normalize(row['meaning'])
            score = sum(10 for tag in tags if len(tag) > 1 and _positive_contains(query, tag))
            score += sum(9 for emotion in emotions if any(emotion in tag for tag in tags) or emotion in meaning)
            overlap = {term for term in terms & (_terms(meaning) - _GENERIC_TERMS)
                       if _positive_contains(query, term)}
            # Two incidental bigrams used to be enough to pick an unrelated
            # reaction. Require a label/emotion hit or at least three concrete
            # lexical overlaps; preferences never manufacture semantic evidence.
            if score == 0 and len(overlap) < 3:
                continue
            score += min(6, len(overlap))
            preference_score = (3 if user['favorite'] else 0) + (2 if user.get('liked') else 0)
            preference_score += texas['weight'] * 2
            preference_score += sum(3 for scenario in [*row['scenarios'], *texas['contexts']]
                if _normalize(scenario) and _normalize(scenario) in query + ' ' + surroundings)
            # Context is a tie-breaker only. It cannot turn an unrelated image
            # into a match or override the user's hide/dislike or the cooldown.
            # Prefer an equally relevant asset that has not been used recently.
            ranked.append((score, preference_score, -(texas['last_used'] or 0), row['id'], row))
        return max(ranked, key=lambda item: item[:4])[4] if ranked else None
