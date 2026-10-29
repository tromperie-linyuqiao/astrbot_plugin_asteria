"""Small typed routing and bounded summary preparation on the existing MC store.

This does not authorize a write, call a model, own a worker or infer an identity.
Raw utterances stay in the original timeline. Only the established classifier
can produce stable facts; a temporary user statement never becomes a profile.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

VERSION = 'tls.memory.routing.v1'
DEFAULTS = {
    'living_memory_strategy_enabled': True,
    'living_memory_working_ttl_minutes': 120,
    'living_memory_summary_filter_low_value': True,
    'living_memory_summary_dedupe': True,
}
_SMALLTALK = re.compile(r'^(?:嗯+|哦+|啊+|好(?:的|吧|呀)?|行|可以|知道了|收到|谢谢(?:你)?|不客气|哈哈+|嘿嘿+|早(?:安|上好)?|午安|晚安|你好|您好|嗨|哈喽|hi|hello|ok|okay|晚点聊|拜拜|再见)[\s!！?？。,.，~～…]*$', re.I)
_WORKING = re.compile(r'(?:我(?:现在|正在|刚刚|刚才)(?:正在|在|准备|要去|忙|吃|睡|等|开会|上课|下课|到家)|(?:今天|今晚|这会儿|目前)(?:我)?(?:在|正|要去|准备|忙|需要先)|我(?:在路上|到家了|刚下课|正在上课|正在开会|准备睡|刚吃完))')
_DURABLE_SIGNAL = re.compile(r'记住|生日|毕业|通过|考过|第一次|约定|承诺|决定|以后|一直|习惯|喜欢|讨厌')
_RP = frozenset({'roleplay', 'roleplay_event', 'roleplay_summary', 'fictional', 'fictional_event'})
_PROFILE = frozenset({'user_profile', 'user_habit', 'user_preference'})
_MANUAL = frozenset({'manual_memory', 'core_memory'})
_FILTER_REASONS = frozenset({'low_value', 'duplicate_in_window', 'working_not_long_term'})


def validate_settings(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError('memory strategy requires exactly the declared settings')
    result = dict(values)
    for key in DEFAULTS:
        if key == 'living_memory_working_ttl_minutes':
            if type(result[key]) is not int or not 5 <= result[key] <= 1440:
                raise ValueError('工作记忆有效期必须为 5–1440 分钟的整数')
        elif type(result[key]) is not bool:
            raise ValueError('记忆策略开关必须为布尔值')
    return result


def settings_for(context=None):
    reader = getattr(context, '_tls_memory_strategy_settings', None)
    if callable(reader):
        return validate_settings(reader())
    return dict(DEFAULTS)


def _value(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def metadata(value):
    value = _value(value, 'metadata', {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = {}
    return value if isinstance(value, dict) else {}


def normalize(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def low_value(text):
    text = normalize(text)
    return not text or bool(_SMALLTALK.fullmatch(text))


def temporary_statement(text):
    text = normalize(text)
    return bool(_WORKING.search(text)) and not _DURABLE_SIGNAL.search(text) and not low_value(text)


def capture_mode(ctx, event):
    """Read only Root's authenticated current WebChat session-state projection."""
    raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
    getter = getattr(event, 'get_extra', None)
    if (getattr(ctx, 'platform', '') != 'webchat' or getattr(ctx, 'scope', '') != 'private'
            or not isinstance(raw, tuple) or len(raw) != 3 or not isinstance(raw[2], dict)
            or not callable(getter) or raw[0] != getattr(ctx, 'user_id', None)
            or getattr(event, 'unified_msg_origin', None) != getattr(ctx, 'session_id', None)):
        return 'chat'
    info = getter('tls_chat_session_mode')
    if (not isinstance(info, dict) or info.get('schema') != 1
            or info.get('source') != 'tls.chat.session_state'
            or info.get('username') != raw[0] or info.get('session_id') != raw[1]
            or type(info.get('revision')) is not int or info['revision'] < 0):
        return 'chat'
    return 'roleplay' if info.get('mode') == 'roleplay' else 'chat'


def is_roleplay_record(value):
    """Read explicit stored provenance, including records predating the router.

    Text, names and the current conversation mode cannot establish the source
    of a historical record. Existing typed RP markers remain authoritative
    even when the record has no newer ``memory_routing`` metadata.
    """
    meta = metadata(value)
    routing = meta.get('memory_routing')
    return (str(_value(value, 'reality_level', '')) in _RP
            or str(_value(value, 'memory_type', '') or _value(value, 'event_type', '')) in _RP
            or str(meta.get('evidence_kind', '')) in _RP
            or meta.get('roleplay') is True
            or isinstance(routing, dict) and routing.get('bucket') == 'roleplay')


def route(value, *, now=None, ttl_minutes=120):
    """Route existing typed facts, not a regex substitute for profile quality."""
    meta = metadata(value)
    kind = str(_value(value, 'memory_type', '') or _value(value, 'event_type', ''))
    text = _value(value, 'evidence', '') or _value(value, 'content', '')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if kind in _MANUAL or meta.get('admin_action') or meta.get('manual') is True:
        bucket, reason = 'manual', 'explicit_manual_authority'
    elif is_roleplay_record(value):
        bucket, reason = 'roleplay', 'typed_fictional_source'
    elif kind == 'explicit_memory':
        bucket, reason = 'explicit', 'existing_explicit_classifier'
    elif kind == 'relationship_claim':
        bucket, reason = 'relationship', 'user_statement_not_verified_relationship'
    elif kind in _PROFILE or meta.get('profile_dimension'):
        bucket = 'preference' if kind == 'user_preference' else 'user_fact'
        reason = 'existing_profile_quality_and_conflict_flow'
    elif kind == 'working_memory' or temporary_statement(text):
        bucket, reason = 'working', 'temporary_user_statement'
    elif low_value(text):
        bucket, reason = 'smalltalk', 'no_durable_fact'
    else:
        bucket, reason = 'event', 'utterance_not_promoted_to_fact'
    result = {'schema': VERSION, 'bucket': bucket, 'reason': reason,
              'summary_eligible': bucket not in {'smalltalk', 'working'},
              'evidence_status': 'user_reported' if bucket in {'explicit', 'relationship', 'preference', 'user_fact', 'working'} else 'source_preserved'}
    if bucket == 'working':
        result['expires_at'] = (current + timedelta(minutes=ttl_minutes)).astimezone(timezone.utc).isoformat(timespec='seconds')
    return result


def route_derived(records, *, settings=None, now=None):
    values = validate_settings(settings or dict(DEFAULTS))
    if not values['living_memory_strategy_enabled']:
        return list(records)
    result, seen = [], set()
    for record in records:
        existing = metadata(record)
        decision = route(record, now=now, ttl_minutes=values['living_memory_working_ttl_minutes'])
        fingerprint = (str(_value(record, 'memory_type', '')), normalize(_value(record, 'content', '')),
                       str(existing.get('profile_dimension', '')))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        # Preserve the original source_memory_id/evidence/profile conflict keys.
        record.metadata = {**existing, 'memory_routing': decision}
        if decision['bucket'] == 'working':
            record.valid_to = decision['expires_at']
            record.lifecycle, record.durability = 'short_term_candidate', 'short'
            record.reality_level, record.review_status = 'observed_utterance', 'auto'
        result.append(record)
    return result


def working_expired(record, *, now=None):
    info = metadata(record).get('memory_routing')
    if not isinstance(info, dict) or info.get('bucket') != 'working':
        return False
    raw = _value(record, 'valid_to', '') or info.get('expires_at')
    try:
        expiry = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            return True
        return (now or datetime.now(timezone.utc)) >= expiry
    except (ValueError, TypeError):
        return True


def summary_plan(rows, *, settings=None):
    """Incremental existing window, keeping reality domains and original rows.

    Deterministically filtered rows get an explicit skip reason in the store;
    deferred reality domains are untouched and remain for the existing worker.
    No generic prose similarity merges conflicts or deletes manual material.
    """
    values = validate_settings(settings or dict(DEFAULTS))
    selected, filtered, deferred, seen = [], {}, [], set()
    domain = None
    for row in rows:
        event_id = str(row.get('id') or '')
        info = metadata(row).get('memory_routing')
        info = info if isinstance(info, dict) and info.get('schema') == VERSION else route(row)
        bucket = info.get('bucket', 'event')
        if bucket == 'working':
            filtered[event_id] = 'working_not_long_term'
            continue
        if values['living_memory_strategy_enabled'] and values['living_memory_summary_filter_low_value'] and bucket == 'smalltalk':
            filtered[event_id] = 'low_value'
            continue
        fingerprint = (str(row.get('subject_id') or ''), str(row.get('event_type') or ''), normalize(row.get('content')))
        if values['living_memory_strategy_enabled'] and values['living_memory_summary_dedupe'] and fingerprint in seen:
            filtered[event_id] = 'duplicate_in_window'
            continue
        current_domain = 'roleplay' if is_roleplay_record(row) else 'real_conversation'
        if domain is not None and domain != current_domain:
            deferred.append(event_id)
            continue
        domain = current_domain
        seen.add(fingerprint)
        selected.append(row)
    source_ids = [str(row.get('id') or '') for row in selected]
    return {'rows': selected, 'filtered': {k: v for k, v in filtered.items() if k},
            'deferred_ids': deferred, 'domain': domain or 'real_conversation',
            'schema': VERSION, 'source_count': len(selected),
            'source_digest': hashlib.sha256(json.dumps(source_ids, separators=(',', ':')).encode()).hexdigest(),
            'incremental': True, 'original_timeline_preserved': True}


def public_contract():
    return {'schema': VERSION, 'routes': ['smalltalk', 'working', 'event', 'explicit', 'preference', 'user_fact', 'relationship', 'roleplay', 'manual'],
            'working_ttl_unit': 'minutes', 'stable_fact_source': 'existing_typed_classifier_and_profile_quality',
            'manual_overwrite': False, 'additional_model_calls_per_turn': 0,
            'summary': {'input': 'next_unsummarized_owned_timeline_window', 'output': 'evidence_checked_new_summary_version',
                        'failure': 'retain_raw_input_and_existing_valid_versions', 'incremental': True}}
