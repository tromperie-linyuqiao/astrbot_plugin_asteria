"""Native selection of schedule/media/action material; no composer or side effects.

The optional bridge supplies ACL-filtered serialized records. This policy checks
the final private binding again, labels evidence, and never fetches media bytes.
"""
from __future__ import annotations

from datetime import date, datetime, time as day_time, timedelta, timezone
import hashlib
import html
import math
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import plain, private_scope
from .memory_context import _SECRET

_SCHEDULE = frozenset({'schedule_fragment', 'persona_life', 'companion_note'})
_MEDIA = frozenset({'image_action', 'media_index', 'reading_memory', 'search_action', 'creative_work'})
_ACTIONS = _SCHEDULE | _MEDIA | frozenset({'self_action', 'proactive_message', 'qzone_action'})
_KINDS = {'persona_life': 'roleplay_event', 'fictional_content': 'roleplay_event',
          'model_inference': 'model_inference', 'inference': 'model_inference',
          'bot_action': 'action_result', 'external_observation': 'real_observation',
          'real_user_fact': 'user_reported', 'observed_utterance': 'user_reported'}
_LABEL = {'roleplay_event': '虚构角色记录，非现实经历', 'model_inference': '未确认推断',
          'action_result': '已记录工具/角色操作，不等同物理经历',
          'real_observation': '外部观测', 'user_reported': '用户明确陈述'}
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,160}')
_MEDIA_QUERY = re.compile(r'音乐|听歌|歌曲|网易云|视频|图片|照片|穿搭|衣服|自拍|电影|阅读|书|media|song|music|photo|video|outfit', re.I)
_SCHEDULE_QUERY = re.compile(r'日程|安排|计划|提醒|时间表|几点|生日|纪念日|重要日期|便签|待办|待做|memo|todo|schedule|calendar|plan|birthday|anniversary', re.I)
_ACTION_QUERY = re.compile(r'最近.*(?:做|行动|发|看)|能力|工具|做过|读过|搜索|发布|说说|ability|action|recent', re.I)
_OUTFIT_QUERY = re.compile(r'穿搭|衣服|穿的?什么|自拍|outfit', re.I)
_STATE_QUERY = re.compile(r'在干嘛|在做什么|吃了什么|吃的?什么|几点吃|什么时候吃|吃饭|进食|在哪里|在哪儿|当前位置|今天状态|现在状态', re.I)


def normalize_kind(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError('invalid feature kind')
    if value in {'continuity', 'schedule', 'outfit', 'media', 'ability'}:
        return value
    if value == 'daily_outfit_photo':
        return 'outfit'
    if value in {'daily_plan', 'daily_detail', 'segment', 'segment_detail', 'schedule_detail'} or 'schedule' in value:
        return 'schedule'
    if re.search(r'photo|image|media|video|music', value):
        return 'media'
    return 'ability'


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _timestamp(value, zone):
    if type(value) in (int, float):
        if math.isfinite(value) and value >= 0:
            return float(value)
        raise ValueError('invalid timestamp')
    if not isinstance(value, str) or not 0 < len(value) <= 80:
        raise ValueError('invalid timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        # Legacy local schedules need their declared/default time zone. Reject
        # DST gaps and repeated wall times rather than guessing an occurrence.
        first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError('ambiguous or missing local time')
        if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != parsed:
            raise ValueError('missing local time')
        parsed = first
    result = parsed.timestamp()
    if not math.isfinite(result) or result < 0:
        raise ValueError('invalid timestamp')
    return result


class NativeFeatureContextPolicy:
    version = 'tls.feature_context.v1'

    def __init__(self, *, max_candidates=64, max_items=5):
        if type(max_candidates) is not int or not 1 <= max_candidates <= 120:
            raise ValueError('invalid candidate capacity')
        if type(max_items) is not int or not 1 <= max_items <= 8:
            raise ValueError('invalid item capacity')
        self.max_candidates, self.max_items = max_candidates, max_items

    def _candidate(self, row, scope, kind, now, *, revision_only=False):
        if not isinstance(row, dict):
            return None, 'invalid_record'
        try:
            row = plain(row, 32768)
        except (TypeError, ValueError, RecursionError):
            return None, 'invalid_record'
        identity, content = row.get('id'), row.get('content')
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            return None, 'invalid_identity'
        if not isinstance(content, str) or not content.strip() or len(content) > 4000 or _SECRET.search(content):
            return None, 'invalid_content'
        if row.get('owner_bot_id') != scope['bot_id']:
            return None, 'other_or_ambiguous_bot'
        if row.get('persona_id') != scope['character_id']:
            return None, 'other_or_ambiguous_persona'
        if row.get('platform') not in ('', None, scope['platform']):
            return None, 'other_platform'
        if row.get('scope') == 'private' and row.get('session_id') != scope['session_id']:
            return None, 'other_session'
        if row.get('scope') not in {'private', 'unknown'}:
            return None, 'other_scope'
        if row.get('visibility') != 'bot_self':
            return None, 'not_bot_material'
        for name in ('subject', 'object'):
            actor = row.get(name)
            if not isinstance(actor, dict):
                return None, 'missing_actor'
            actor_id = actor.get('id', '')
            # The actual legacy PC writer used one fixed global schedule
            # container. It is neither a third party nor a user/Bot identity.
            # Attribution must already be explicit and match the current scope
            # above; this exception never supplies missing Bot/persona fields.
            subject = row.get('subject')
            legacy_schedule_container = (name == 'object'
                and row.get('memory_type') == 'schedule_fragment'
                and row.get('scope') == 'unknown'
                and row.get('source_plugin') == 'private_companion'
                and actor.get('kind') == 'session'
                and actor_id == 'private_companion:schedule'
                and not actor.get('name')
                and isinstance(subject, dict) and subject.get('kind') == 'bot'
                and subject.get('id') in {'self', scope['bot_id']})
            if legacy_schedule_container:
                continue
            if actor.get('kind') == 'user' and actor_id and actor_id != scope['user_id']:
                return None, 'other_actor'
            if actor.get('kind') == 'bot' and actor_id not in {'', 'self', scope['bot_id']}:
                return None, 'other_actor'
            if actor.get('kind') not in {'bot', 'user'} or (not actor_id and actor.get('name')):
                return None, 'ambiguous_actor'
        if not revision_only and (row.get('lifecycle') == 'archived' or row.get('validity_status', 'active') != 'active'):
            return None, 'inactive'
        if row.get('review_status') not in {'auto', 'manual', 'approved', 'confirmed'} or row.get('sensitivity') in {'restricted', 'secret', 'internal'}:
            return None, 'not_reviewed_or_sensitive'
        if row.get('sayability') not in {'direct', 'indirect'}:
            return None, 'expression_restricted'
        if row.get('mention_policy') in {'avoid_unless_asked', 'forbidden', 'never', 'tone'}:
            return None, 'expression_restricted'
        confidence = row.get('confidence')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not .75 <= confidence <= 1:
            return None, 'low_confidence'
        evidence = _KINDS.get(row.get('reality_level'))
        if evidence is None:
            return None, 'unknown_provenance'
        record_type = row.get('memory_type')
        if record_type not in _ACTIONS:
            return None, 'unsupported_record_type'
        if revision_only and (record_type != 'schedule_fragment'
                or row.get('source_plugin') != 'private_companion'
                or evidence != 'roleplay_event' or not row.get('updated_at')
                or not isinstance(row.get('canonical_key'), str)
                or not 0 < len(row['canonical_key']) <= 300 or not row['canonical_key'].strip()
                or row.get('validity_status', 'active') not in
                    {'active', 'archived', 'deleted', 'superseded', 'expired', 'quarantined'}):
            return None, 'unverified_revision'
        tags = row.get('tags') if isinstance(row.get('tags'), list) else []
        outfit = any(isinstance(tag, str) and tag in {'daily_outfit', 'outfit', 'clothing', '今日穿搭', '每日穿搭'} for tag in tags)
        outfit = outfit or '每日穿搭图' in content or '穿搭提示摘要' in content
        if not revision_only and kind == 'schedule' and record_type not in _SCHEDULE:
            return None, 'irrelevant'
        if not revision_only and kind == 'outfit':
            clothing = re.search(r'穿搭|衣服|服装|全身照|半身照|造型|outfit|cloth|selfie', content, re.I)
            environment = re.search(r'天气|气温|降温|下雨|下雪|出门|外出|室外|运动|上班|聚会|约会|散步|旅行|weather|rain|outdoor', content, re.I)
            if not (outfit or (record_type == 'image_action' and clothing) or (record_type in _SCHEDULE and environment)):
                return None, 'irrelevant'
        if not revision_only and kind == 'media' and record_type not in _MEDIA:
            return None, 'irrelevant'
        metadata = row.get('context_metadata', {})
        if not isinstance(metadata, dict):
            return None, 'invalid_metadata'
        memo = metadata.get('native_memo')
        native_memo = (row.get('source_plugin') == 'tls_native_memo_notes'
            and record_type == 'companion_note' and row.get('scope') == 'private'
            and evidence == 'action_result' and row.get('canonical_key') == identity
            and re.fullmatch(r'memo\.[a-f0-9]{64}', identity) is not None
            and isinstance(memo, dict) and set(memo) == {'schema', 'id', 'revision', 'status', 'has_reminder_authority', 'origin'}
            and type(memo.get('schema')) is int and memo['schema'] == 1
            and memo.get('id') == identity and type(memo.get('revision')) is int and memo['revision'] > 0
            and memo.get('status') == 'active' and memo.get('has_reminder_authority') is False
            and memo.get('origin') in {'user_explicit', 'user_requested_ai_tool'})
        if row.get('source_plugin') == 'tls_native_memo_notes':
            if not native_memo or revision_only:
                return None, 'invalid_native_memo'
            if kind != 'schedule':
                return None, 'irrelevant'
        if not revision_only and metadata.get('status') in {'cancelled', 'canceled', 'deleted', 'stopped', 'failed'}:
            return None, 'inactive'
        bounds = row.get('time_range', {})
        if not isinstance(bounds, dict):
            return None, 'invalid_time_range'
        zone_name = metadata.get('timezone') or bounds.get('timezone') or 'Asia/Shanghai'
        try:
            zone = ZoneInfo(zone_name) if isinstance(zone_name, str) and len(zone_name) <= 80 else None
            if zone is None:
                raise ValueError('invalid timezone')
            occurred = _timestamp(row.get('occurred_at') or row.get('created_at'), zone)
            updated = _timestamp(row.get('updated_at') or row.get('occurred_at') or row.get('created_at'), zone)
            if occurred > now + 300 or updated > now + 300:
                return None, 'future_record'
            if revision_only and (occurred > now or updated > now):
                return None, 'future_revision'
            expires = []
            for value in (row.get('valid_to'), metadata.get('expires_at')):
                if value not in (None, ''):
                    expires.append(_timestamp(value, zone))
            if row.get('valid_from') not in (None, '') and _timestamp(row['valid_from'], zone) > now:
                return None, 'not_yet_valid'
            start_value = metadata.get('start_at') or bounds.get('start_at')
            end_value = metadata.get('end_at') or bounds.get('end_at')
            start = _timestamp(start_value, zone) if start_value else None
            end = _timestamp(end_value, zone) if end_value else None
            if end is not None:
                if start is not None and end <= start:
                    return None, 'invalid_time_range'
                expires.append(end)
            event_date = metadata.get('date')
            if event_date and record_type in _SCHEDULE:
                event_day = date.fromisoformat(event_date)
                day_start = datetime.combine(event_day, day_time.min, zone).timestamp()
                day_end = datetime.combine(event_day + timedelta(days=1), day_time.min, zone).timestamp()
                if start is None:
                    start = day_start
                if end is None:
                    end = day_end
                expires.append(day_end)
            # The raw action is historical, not proof that a device is currently
            # playing or an image's depicted contents were actually inspected.
            # A TLS-owned future plan is not a historical schedule action.
            # Preserve its real created_at; only this closed origin shape may
            # use its explicit due bound instead of the legacy seven-day age.
            native = metadata.get('native_plan')
            native_plan = (row.get('source_plugin')=='tls_native_agenda'
                and record_type=='companion_note' and row.get('scope')=='private'
                and evidence=='action_result' and row.get('canonical_key')==identity
                and re.fullmatch(r'tls\.agenda\.[a-f0-9]{64}',identity) is not None
                and isinstance(native,dict) and set(native)=={'schema','source_id','occurrence_id','revision','due_at'}
                and type(native.get('schema')) is int and native['schema']==1
                and native.get('source_id')==identity and isinstance(native.get('occurrence_id'),str)
                and re.fullmatch(r'[a-f0-9]{64}',native['occurrence_id']) is not None
                and type(native.get('revision')) is int and native['revision']>0
                and type(native.get('due_at')) in (int,float) and math.isfinite(native['due_at'])
                and start==native['due_at'] and end==start+1
                and row.get('valid_to')==native['due_at'] and occurred<start<=occurred+366*86400)
            if native_memo:
                # A pending entry is current administrative state, not an old
                # completed action or a scheduled reminder. The real provider
                # rechecks its revision; each emitted fragment has a short TTL.
                if (row.get('valid_to') is None or start is not None or end is not None
                        or not now < _timestamp(row['valid_to'], zone) <= now + 300):
                    return None, 'invalid_native_memo_expiry'
            elif not native_plan:
                expires.append(occurred + (7 * 86400 if record_type in _SCHEDULE else 30 * 86400))
            expiry = min(expires)
            if expiry <= now and not revision_only:
                return None, 'expired'
        except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError):
            return None, 'invalid_time'
        temporal = '即将到来的记录' if start is not None and start > now else '当前有效日程记录' if start is not None and end is not None and record_type in _SCHEDULE else '历史记录，未确认当前仍在发生'
        if native_memo:
            temporal = ('用户请求、AI整理的待办定义；不是用户逐字原话；未安排提醒，不证明已经完成'
                if memo.get('origin') == 'user_requested_ai_tool'
                else '用户登记的未完成便签；未安排提醒，不证明已经完成')
        extras = []
        if record_type in _MEDIA:
            extras.append('仅有资料/操作元数据，未读取媒体内容；不据此声称用户正在播放、角色看过画面或亲历其中')
            for name, label in (('title', '标题'), ('artist', '作者/艺人'), ('album', '专辑')):
                value = metadata.get(name)
                if isinstance(value, str) and 0 < len(value) <= 200 and not _SECRET.search(value):
                    extras.append(label + '：' + value)
        text = f'{_LABEL[evidence]}；{temporal}：{content.strip()}'
        if extras:
            text += '\n' + '；'.join(extras)
        text = html.escape(text, quote=False)
        # Canonical keys identify explicit updates. No semantic contradiction
        # classifier is introduced here; both original records remain intact.
        claim = row.get('canonical_key') or metadata.get('media_id') or identity
        if not isinstance(claim, str) or len(claim) > 300:
            return None, 'invalid_claim_key'
        return {'identity': identity, 'text': text, 'evidence': evidence, 'expires': expiry,
                'updated': updated, 'claim': claim, 'content': _normal(content),
                'occurred': occurred, 'start': start,
                'revision_domain': (row.get('scope'), row.get('session_id'), row.get('platform'),
                    row.get('source_plugin'), record_type, row.get('owner_bot_id'), row.get('persona_id'))}, None

    def select(self, rows, *, scope, kind='continuity', query='', now, max_chars=900):
        scope = private_scope(scope)
        kind = normalize_kind(kind)
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('invalid clock')
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('invalid query')
        if type(max_chars) is not int or not 0 <= max_chars <= 6000:
            raise ValueError('invalid context budget')
        if not isinstance(rows, list) or len(rows) > self.max_candidates:
            raise ValueError('invalid candidate rows')
        if kind == 'continuity':
            kind = ('schedule' if _SCHEDULE_QUERY.search(query) else 'outfit' if _OUTFIT_QUERY.search(query)
                    else 'media' if _MEDIA_QUERY.search(query) else 'ability' if _ACTION_QUERY.search(query) or _STATE_QUERY.search(query) else None)
        result = {'version': self.version, 'sections': [], 'selected_ids': [],
                  'rejected': [], 'chars': 0, 'budget_unit': 'unicode_characters'}
        if kind is None:
            return result
        candidates, barriers = [], {}
        for row in rows:
            candidate, reason = self._candidate(row, scope, kind, now)
            if candidate:
                candidates.append(candidate)
            else:
                identity = row.get('id', '') if isinstance(row, dict) else ''
                result['rejected'].append({'id': identity if isinstance(identity, str) and _ID.fullmatch(identity) else '', 'reason': reason})
                if reason in {'inactive', 'expired'}:
                    revision, _ = self._candidate(row, scope, kind, now, revision_only=True)
                    if revision:
                        key = (revision['evidence'], revision['claim'], revision['revision_domain'])
                        barriers[key] = max(barriers.get(key, -1), revision['updated'])
        # A newer explicit cancelled/expired revision must not resurrect an
        # older active plan. Only the exact authenticated record domain and
        # explicit canonical key can block it; later active revisions recover.
        active = []
        for item in candidates:
            key = (item['evidence'], item['claim'], item['revision_domain'])
            if item['updated'] <= barriers.get(key, -1):
                result['rejected'].append({'id': item['identity'], 'reason': 'inactive_revision'})
            else:
                active.append(item)
        candidates = active
        # One opaque record id must not emit two fragments with different
        # canonical keys or evidence classes, even if an adapter is malformed.
        identities = {}
        for item in candidates:
            identities.setdefault(item['identity'], []).append(item)
        candidates = []
        for values in identities.values():
            if len({(item['evidence'], item['claim']) for item in values}) > 1:
                result['rejected'].extend({'id': item['identity'], 'reason': 'conflicting_identity'} for item in values)
                continue
            candidates.extend(values)
        groups = {}
        for item in candidates:
            groups.setdefault((item['evidence'], item['claim']), []).append(item)
        resolved = []
        for values in groups.values():
            latest = max(item['updated'] for item in values)
            newest = [item for item in values if item['updated'] == latest]
            if len({item['content'] for item in newest}) != 1:
                result['rejected'].extend({'id': item['identity'], 'reason': 'conflicting_revision'} for item in values)
                continue
            winner = min(newest, key=lambda item: item['identity'])
            resolved.append(winner)
            result['rejected'].extend({'id': item['identity'], 'reason': 'superseded_or_duplicate'} for item in values if item is not winner)
        seen = set()
        for item in sorted(resolved, key=lambda item: (-item['updated'], item['identity'])):
            digest = (item['evidence'], item['content'])
            if digest in seen:
                result['rejected'].append({'id': item['identity'], 'reason': 'duplicate_content'})
                continue
            seen.add(digest)
            cost = len(item['text']) + (1 if result['sections'] else 0)
            if len(result['sections']) >= self.max_items or result['chars'] + cost > max_chars:
                result['rejected'].append({'id': item['identity'], 'reason': 'budget_or_capacity'})
                continue
            identity = 'feature.' + hashlib.sha256((item['identity'] + '\0' + item['evidence']).encode()).hexdigest()[:24]
            result['sections'].append({'id': identity, 'text': item['text'], 'source': 'tls.feature',
                'evidence_kind': item['evidence'], 'expires_at': item['expires']})
            result['selected_ids'].append(item['identity'])
            result['chars'] += cost
        return result
