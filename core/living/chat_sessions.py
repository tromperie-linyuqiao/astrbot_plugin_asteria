"""Small APP session presentation settings in the existing LivingJournal.

AstrBot still owns conversations/history/LLM state. These settings neither
grant QQ access nor create real-time Presence identities.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import time

from astrbot.core.agent.message import TextPart

from .chat_expressions import ChatExpressions, ChatExpressionError
from .journal import JournalConflict

NAMESPACE = 'tls.chat.session.state'
PREFERENCE_DEFAULTS = {'reply_style': 'inherit', 'reply_length': 'inherit', 'rp_intensity': 'inherit'}
PREFERENCE_OPTIONS = {'reply_style': {'inherit', 'natural', 'warm', 'direct'},
                      'reply_length': {'inherit', 'short', 'balanced', 'detailed'},
                      'rp_intensity': {'inherit', 'light', 'balanced', 'immersive'}}
MODEL_ROUTE_DEFAULTS = {'model_provider_id': '', 'model_fallback_provider_id': ''}
DEFAULTS = {'archived': False, 'mode': 'chat', 'scene': '', 'reply_format': 'auto', **PREFERENCE_DEFAULTS,
            **MODEL_ROUTE_DEFAULTS}
MODES = {'chat', 'roleplay', 'technical'}


def session_preference_context(state):
    """Finite, bounded prompt hints. Inherit contributes no extra instruction."""
    hints = {'reply_style': {'natural': '语气自然连贯。', 'warm': '语气温和体贴，避免刻意奉承。',
                            'direct': '直接说明重点，减少客套。'},
             'reply_length': {'short': '优先简短回复；复杂问题保留必要信息。',
                              'balanced': '回复长度适中，解释到足以理解。',
                              'detailed': '需要时充分解释，并使用具体例子；避免重复。'},
             'rp_intensity': {'light': '虚构互动轻量点到为止，少量动作描写。',
                              'balanced': '虚构互动中平衡动作描写与对话。',
                              'immersive': '虚构互动保持场景连续和沉浸感，不把剧情当作现实观察。'}}
    return '\n'.join(hints[key][state[key]] for key in hints
        if state.get(key) in hints[key] and (key != 'rp_intensity' or state.get('mode') == 'roleplay'))


def touch_catalog(plugin):
    """The configured TLS body role and its real words/parts, not Persona aliases."""
    from .. import events
    if (getattr(plugin, '_stopping', False) or not hasattr(plugin, '_cfg_bool')
            or not plugin._cfg_bool('vb_enabled', True) or getattr(plugin, '_store', None) is None):
        return {'available': False, 'reason': 'TLS触觉尚未启用', 'verbs': [], 'parts': []}
    character = plugin._default_character()
    profile = plugin._profiles.get(character)
    if not profile or profile.get('enabled') is False:
        return {'available': False, 'reason': '没有已启用的TLS身体角色', 'verbs': [], 'parts': []}
    parts = []
    for part in profile.get('parts', []):
        if not part.get('id'):
            continue
        aliases = list(part.get('aliases') or [])
        if any(word in {'腹部', '肚子', '肚皮'} for word in [part.get('label'), *aliases]) and '肚皮' not in aliases:
            aliases.append('肚皮')
        parts.append({'id': part['id'], 'label': part.get('label') or part['id'], 'aliases': aliases})
    # The original parser decides valid pairs. This is a display-only copy;
    # APP aliases never change the role configuration or QQ parser vocabulary.
    aliases = {part['id']: part['aliases'] for part in parts}
    parse_profile = dict(profile, parts=[dict(part, aliases=aliases.get(part.get('id'), []))
                                         for part in profile.get('parts', [])])
    verbs = [{'word': word, 'part_ids': [part['id'] for part in parts
              if any(event['part'] == part['id'] for event in events.extract_events(word + part['label'], parse_profile))]}
             for word in events._action_words(profile)]
    return {'available': True, 'character': character, 'name': profile.get('name') or character,
            'verbs': verbs,
            'parts': parts}


def validate_touch(catalog, value):
    if (not isinstance(value, dict) or set(value) != {'character', 'verb', 'part'}
            or any(not isinstance(value[key], str) for key in ('character', 'verb', 'part'))
            or not catalog.get('available') or value['character'] != catalog.get('character')
            or value['verb'] not in {row['word'] for row in catalog['verbs']}
            or value['part'] not in {row['id'] for row in catalog['parts']}):
        raise ChatExpressionError('触觉动作或部位已变化，请刷新后重新选择')
    verb = next(row for row in catalog['verbs'] if row['word'] == value['verb'])
    if 'part_ids' in verb and value['part'] not in verb['part_ids']:
        raise ChatExpressionError('原生触觉未支持这个动作与部位组合，请重新选择')
    return dict(value)


def _touch_session(username, session_id):
    # APP body state is private to its actual owned conversation. It never
    # borrows a QQ sender ID, body history, binding, or execution lease.
    return 'webchat-' + hashlib.sha256(json.dumps([username, session_id], ensure_ascii=False).encode()).hexdigest()


def apply_chat_touch(plugin, username, session_id, parts):
    """One explicit submit, through the original TLS parser/advance/store."""
    from .. import events
    selected = [part for part in parts if part.get('type') == 'action' and part.get('source') == 'user_action']
    # Compatibility for callers already holding a server-validated native part.
    selected += [part for part in parts if part.get('native_touch') and part not in selected]
    if not selected:
        return None
    catalog = touch_catalog(plugin)
    if not catalog.get('available'):
        if any(part.get('native_touch') for part in selected):
            raise ChatExpressionError(catalog.get('reason') or 'TLS触觉未接入')
        return {'state': 'roleplay_input', 'applied': 0, 'scope': 'owned_webchat', 'source': 'user_action',
                'results': [{'fragment_id': part.get('fragment_id'), 'action_id': part.get('action_id'),
                    'state': 'roleplay_input', 'applied': 0, 'parts': [], 'verb': None} for part in selected]}
    profile = plugin._profiles.get(catalog.get('character'))
    # The APP's display aliases apply only to this parse. Never modify the
    # configured profile or the free-text QQ observer's vocabulary.
    aliases = {part['id']: part['aliases'] for part in catalog['parts']}
    profile = dict(profile, parts=[dict(part, aliases=aliases.get(part.get('id'), part.get('aliases', [])))
                                   for part in profile.get('parts', [])])
    evs, action_results = [], []
    for part in selected:
        if part.get('native_touch'):
            value = validate_touch(catalog, part['native_touch'])
            target = next(row for row in catalog['parts'] if row['id'] == value['part'])
            parsed = [event for event in events.extract_events(value['verb'] + target['label'], profile)
                      if event['part'] == value['part']]
            if not parsed:
                raise ChatExpressionError('原生触觉解析器没有接受这个组合')
        else:
            # The action ID/description came from the owned server action bank.
            # Reuse the original parser; unmatched scene actions stay RP input.
            description = part.get('description') or ''
            # The configured role's possessive name is a target, not distance
            # between verb and part ("戳一下德克萨斯的肚皮"). Keep the original
            # quote/negation/question filters and the QQ parser unchanged.
            role_name = catalog.get('name')
            if isinstance(role_name, str) and role_name:
                description = description.replace(role_name + '的', '')
            parsed = events.extract_events(description, profile)
        evs.extend(parsed)
        action_results.append({'fragment_id': part.get('fragment_id'), 'action_id': part.get('action_id'),
            'state': 'native_touch_applied' if parsed else 'roleplay_input', 'applied': len(parsed),
            'parts': list(dict.fromkeys(event['part'] for event in parsed)),
            'verb': part['native_touch']['verb'] if part.get('native_touch') else None})
    if not evs:
        return {'state': 'roleplay_input', 'applied': 0, 'scope': 'owned_webchat', 'source': 'user_action',
                'results': action_results}
    now = time.time()
    for event in evs:
        event['t'] = now
    result = plugin._advance_session(catalog['character'], _touch_session(username, session_id), evs, now)
    if result is None:
        raise ChatExpressionError('TLS身体服务正在更新，互动未确认')
    # _advance_session returns only after the original BodyStore save. Read its
    # timestamp rather than inventing a state revision or claiming every event
    # necessarily increased a value (cooldowns/phase rules may suppress it).
    load = getattr(plugin._store, 'load', None)
    stored = load(catalog['character'], _touch_session(username, session_id)) if callable(load) else None
    return {'state': 'native_touch_applied', 'character': catalog['character'], 'applied': len(evs),
            'scope': 'owned_webchat', 'source': 'user_action', 'applied_at': now,
            'body_updated_at': stored.get('updated_at') if isinstance(stored, dict) else None,
            'results': action_results}


def chat_body_snapshot(plugin, username, session_id):
    """Read the actual private APP state without advancing it or calling a model."""
    catalog = touch_catalog(plugin)
    if not catalog.get('available'):
        return dict(catalog, initialized=False, updated_at=None, parts=[])
    stored = plugin._store.load(catalog['character'], _touch_session(username, session_id))
    profile = plugin._profiles[catalog['character']]
    parts = []
    for meta in profile.get('parts') or []:
        current = (stored.get('parts') or {}).get(meta['id']) if stored else None
        parts.append({'id': meta['id'], 'label': meta.get('label') or meta['id'],
            'sensitivity': meta.get('sens'), 'sensitivity_boost': current.get('sens_boost') if current else None,
            'value': current.get('value') if current else None,
            'last_event_at': current.get('last_event_at') if current else None,
            'tier': current.get('last_react_tier') if current else None})
    result = {'available': True, 'initialized': stored is not None, 'character': catalog['character'],
              'name': catalog['name'], 'updated_at': stored.get('updated_at') if stored else None,
              'parts': parts, 'scope': 'owned_webchat'}
    for key in ('phase', 'phase_until', 'arousal', 'verbal_arousal', 'tolerance'):
        result[key] = stored.get(key) if stored else None
    return result


def chat_touch_context(plugin, username, session_id):
    from .. import inject
    catalog = touch_catalog(plugin)
    if not catalog.get('available'):
        return ''
    stored = plugin._store.load(catalog['character'], _touch_session(username, session_id))
    if not stored:
        return ''
    plugin._advance_session(catalog['character'], _touch_session(username, session_id), [], time.time())
    stored = plugin._store.load(catalog['character'], _touch_session(username, session_id))
    value = inject.render(stored, plugin._profiles[catalog['character']], max_chars=900, show_numbers=False)
    return '[当前APP对话的TLS原生身体状态，来自用户明确发起的虚构互动；不是现实感知]\n' + value if value else ''


class ChatSessionState:
    def __init__(self, journal, *, current):
        self.journal, self.current = journal, current

    def get(self, username, session_id):
        scope = ChatExpressions.message_scope(username, session_id)
        record = self.journal.fetch(NAMESPACE, 'settings', scope)
        return dict(DEFAULTS, **(record['data'] if record else {}),
                    session_id=session_id, revision=record['revision'] if record else 0)

    def save(self, username, session_id, changes, *, expected_revision=None, reset_preferences=False):
        if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
            raise ChatExpressionError('会话设置含不支持的字段')
        if type(reset_preferences) is not bool or reset_preferences and set(changes) & set(PREFERENCE_DEFAULTS):
            raise ChatExpressionError('恢复继承不能同时指定回复偏好')
        for key, options in PREFERENCE_OPTIONS.items():
            if key in changes and (not isinstance(changes[key], str) or changes[key] not in options):
                raise ChatExpressionError('会话回复偏好无效')
        for key in MODEL_ROUTE_DEFAULTS:
            if key in changes and (not isinstance(changes[key], str) or len(changes[key]) > 160
                    or changes[key] != changes[key].strip() or any(ord(c) < 32 for c in changes[key])):
                raise ChatExpressionError('会话模型编号无效')
        if 'archived' in changes and type(changes['archived']) is not bool:
            raise ChatExpressionError('归档状态须为开关')
        if 'mode' in changes and changes['mode'] not in MODES:
            raise ChatExpressionError('会话模式须为日常、角色扮演或讨论')
        if 'reply_format' in changes and changes['reply_format'] not in {'auto','text','structured'}:
            raise ChatExpressionError('表达格式须为自动、普通文字或动作与话语')
        if 'scene' in changes and (not isinstance(changes['scene'], str)
                or len(changes['scene']) > 3000 or '\x00' in changes['scene']):
            raise ChatExpressionError('剧情简介最多 3000 字')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ChatExpressionError('会话设置版本无效')
        old = self.get(username, session_id)
        value = {key: changes.get(key, old[key]) for key in DEFAULTS}
        if value['model_provider_id'] and value['model_provider_id'] == value['model_fallback_provider_id']:
            raise ChatExpressionError('会话首选与备选模型不能相同')
        if reset_preferences:
            value.update(PREFERENCE_DEFAULTS)
        self.journal.put(NAMESPACE, 'settings', ChatExpressions.message_scope(username, session_id),
                         value, expected_revision=old['revision'] if expected_revision is None else expected_revision,
                         authorize=self.current)
        return self.get(username, session_id)


async def inject_chat_session_context(plugin, event, req):
    """Use only an actual SDK WebChat envelope; never synthesize an event."""
    if getattr(plugin, '_stopping', False) or event.get_platform_name() != 'webchat':
        return
    raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
    if not isinstance(raw, tuple) or len(raw) != 3:
        return
    username, session_id, payload = raw
    if (not isinstance(username, str) or not isinstance(session_id, str)
            or username != str(event.get_sender_id() or '') or not isinstance(payload, dict)):
        return
    host = getattr(getattr(plugin, '_presence', None), 'living_host', None)
    runtime = getattr(host, 'runtime', None)
    assets = getattr(runtime, 'expression_assets', None)
    journal = getattr(assets, 'journal', None)
    if journal is None or not getattr(assets, 'active', False):
        return
    def current():
        return (not getattr(plugin, '_stopping', False) and not getattr(host, '_closed', True)
                and getattr(host, 'runtime', None) is runtime and getattr(runtime, 'expression_assets', None) is assets
                and assets.active and not journal._closed)
    state = await asyncio.to_thread(ChatSessionState(journal, current=current).get, username, session_id)
    if not current() or state['archived']:
        return
    # Bind the real SDK occurrence to its server checkpoint. Saved DB IDs and
    # SDK event UUIDs differ; later quickviews use this exact link, never text.
    from .chat_message_memory import bind_event_source
    try:
        await asyncio.to_thread(bind_event_source, journal, username, session_id, payload,
                                mode=state['mode'], current=current)
    except (RuntimeError, OSError, ValueError, JournalConflict, PermissionError):
        # Optional provenance may be unavailable (including Journal capacity).
        # The quickview then reports no exact link; generation keeps its hints.
        pass
    if not current():
        return
    event.set_extra('tls_chat_session_mode',dict(schema=1,mode=state['mode'],session_id=session_id,
        username=username,revision=state['revision'],source='tls.chat.session_state'))
    # User-maintained conversation context, not an observation or a rewrite of
    # Persona. Existing TLS RP/memory assembly remains responsible for its data.
    mode_text = {'chat': '自然日常聊天，回复连贯', 'roleplay': '沿用当前角色进行连续的虚构剧情互动',
                 'technical': '清晰讨论和解释问题，避免无关表情与机械分段'}[state['mode']]
    block = '[Texas Chat 当前会话设置，来自用户明确维护]\n' + mode_text
    preferences = session_preference_context(state)
    if preferences:
        block += '\n本会话回复偏好（仅影响后续表达）：\n' + preferences
    block += '\n用户的聊天表情和互动动作是交流表达。自然回应其情绪与动作，不将表情称为上传照片、发图或识图；普通图片附件仍按实际内容处理。'
    if state['scene']:
        block += '\n本会话剧情/讨论简介（用户设定，不是现实观察）：' + json.dumps(state['scene'], ensure_ascii=False)
    from .structured_reply import enabled, PROTOCOL
    if enabled(state):
        block += '\n[Texas Chat表达协议，仅规定回复格式，不改变人格与权限]\n' + PROTOCOL
    # Preserve the Persona's system instructions. This is user-maintained
    # conversational context, carried by the SDK's existing typed user parts.
    req.extra_user_content_parts.append(TextPart(text=block).mark_as_temp())
    body_context = chat_touch_context(plugin, username, session_id)
    if body_context:
        req.extra_user_content_parts.append(TextPart(text=body_context).mark_as_temp())
