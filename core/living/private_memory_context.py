"""Native final selection for independent private feature generation.

The existing Memory store remains the source of truth. This policy has no
store, retriever, provider, task or sender. Core blocks remain owner-managed
data; their text cannot change the host's permissions, persona or safety rules.
Ordinary inbound chat must keep the existing single unified context outlet.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import html
import math
import re
import unicodedata

from .feature_context import normalize_kind
from .memory_context import NativeMemoryContextPolicy
from .models import plain, private_scope

_PROFILE = frozenset({'user_profile', 'user_preference', 'user_habit', 'relationship_claim'})
_FACT = frozenset({'manual_memory', 'explicit_memory', 'living_observation', 'tool_memory'})
_REVIEWED = frozenset({'manual', 'approved', 'confirmed'})
_CORE_KINDS = frozenset({'rule', 'boundary', 'preference', 'profile', 'fact', 'state'})
_SECRET = re.compile(r'(?i)(?:密码|口令|验证码|password|passcode|api[ _-]?key|token|cookie|密钥|秘钥)'
                     r'\s*(?::|：|=|是|为|is\b)\s*[^；，。！？!?\n]{1,160}')
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,160}')
_SCHEDULE = re.compile(r'日程|安排|提醒|催|主动|打扰|联系|作息|睡|起床|吃饭|饮食|工作|上班|下班|学习|运动|时间|早上|晚上|schedule|sleep|remind', re.I)
_OUTFIT = re.compile(r'穿搭|衣服|服装|颜色|配色|裙|外套|上衣|裤|鞋|饰品|自拍|造型|outfit|clothing|colour|color|shirt|dress', re.I)
_STOP = frozenset({'的记', '记忆', '用户', '当前', '现在', '信息', '什么', '关于', '需要', '相关',
                   '长期', '资料', '偏好', '明确', '稳定', '主要', '最近', '之前', '已经', '如何',
                   'feature', 'private', 'companion', 'context', 'user', 'the', 'and', 'for'})


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _terms(value):
    value = _normal(value)
    # Remove whole generic CJK phrases before creating overlapping bigrams;
    # otherwise a template such as "明确偏好" leaves a spurious "确偏" hit.
    for term in _STOP:
        if any('\u3400' <= char <= '\u9fff' for char in term):
            value = value.replace(term, ' ')
    terms = set(re.findall(r'[a-z0-9]{3,}', value))
    for text in re.findall(r'[\u3400-\u9fff]+', value):
        terms.update(text[index:index+2] for index in range(len(text)-1))
    return terms - _STOP


def _time(value):
    if type(value) in (float, int) and math.isfinite(value) and value >= 0:
        return float(value)
    if isinstance(value, str) and 0 < len(value) <= 80:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            result = parsed.timestamp()
            if math.isfinite(result) and result >= 0:
                return result
    raise ValueError('explicit timestamp required')


class NativePrivateMemoryContextPolicy:
    """Bounded owner-managed core and relevant private facts, with no cache."""
    version = 'tls.private_memory_context.v1'

    def __init__(self, *, max_candidates=64, max_items=6, max_core_items=3):
        if type(max_candidates) is not int or not 1 <= max_candidates <= 64:
            raise ValueError('invalid private candidate capacity')
        if type(max_items) is not int or not 1 <= max_items <= 8:
            raise ValueError('invalid private item capacity')
        if type(max_core_items) is not int or not 1 <= max_core_items <= max_items:
            raise ValueError('invalid core item capacity')
        self.max_candidates, self.max_items = max_candidates, max_items
        self.max_core_items = max_core_items

    @staticmethod
    def _core(row, scope, now):
        if row.get('source_id') == 'tls.core.tool':
            # A conversational tool does not acquire panel confirmation or
            # user-fact provenance by supplying model-authored parameters.
            from .native_core_tools import tool_core_contract, PROVENANCE
            if not tool_core_contract(row,scope) or row.get('private_context_metadata'):
                return None,'invalid_tool_core_contract'
            metadata=row['metadata']
            if (metadata['enabled'] is not True or row.get('lifecycle')!='stable_memory'
                    or row.get('validity_status')!='active'):
                return None,'inactive_tool_core'
            try:
                occurred=_time(row['occurred_at'])
                since=_time(row['valid_from']) if row.get('valid_from') not in (None,'') else occurred
                endings=[_time(row[key]) for key in ('expires_at','valid_to') if row.get(key) not in (None,'')]
                if occurred>now or since>now or any(until<=now or until<=since or until<=occurred for until in endings):
                    return None,'expired_or_future_tool_core'
            except (ValueError,TypeError,OverflowError,KeyError):return None,'invalid_tool_core_time'
            content=_normal(row['content'])
            return dict(identity=row['id'],text=PROVENANCE+html.escape(' '.join(row['content'].split()),quote=False),
                kind='action_result',expires_at=min(endings) if endings else None,
                priority=metadata['core_priority'],revision=row['revision'],trust_tier=1,
                claim=('ai_tool_material',metadata['core_kind'],_normal(metadata['title'])),content=content),''
        metadata = dict(row.get('metadata', {}), **row.get('private_context_metadata', {}))
        if not isinstance(metadata, dict):
            return None, 'invalid_metadata'
        if (row.get('owner_bot_id') != scope['bot_id']
                or row.get('persona_id') != scope['character_id']):
            return None, 'scope_mismatch'
        actors = (row.get('subject'), row.get('object'))
        if any(not isinstance(actor, dict) for actor in actors):
            return None, 'invalid_actor'
        if any((actor.get('kind') == 'user' and actor.get('id') != scope['user_id'])
               or (actor.get('kind') == 'bot' and actor.get('id') != scope['bot_id'])
               or actor.get('kind') not in {'user', 'bot'} for actor in actors):
            return None, 'actor_mismatch'
        native = (row.get('source_plugin') == 'texas_living_system'
            and row.get('source_id') == 'tls.personal.panel')
        if native:
            required = {'schema','managed_by','personal_kind','title','tags','enabled',
                'core_kind','core_priority','evidence_kind'}
            if (set(metadata) != required or row.get('private_context_metadata')
                    or metadata.get('schema') != 'tls.native.personal.v1'
                    or metadata.get('managed_by') != 'tls_material_panel'
                    or metadata.get('personal_kind') != 'core'
                    or metadata.get('enabled') is not True
                    or metadata.get('evidence_kind') != 'user_reported'
                    or row.get('evidence_kind') != 'user_reported'
                    or row.get('reality_level') != 'real_user_fact'
                    or row.get('scope') != 'private' or row.get('visibility') != 'private_pair'
                    or row.get('platform') != scope['platform']
                    or row.get('session_id') != scope['session_id']
                    or row.get('subject') != {'kind':'user','id':scope['user_id']}
                    or row.get('object') != {'kind':'bot','id':scope['bot_id']}):
                return None, 'unmanaged_or_inactive_native_core'
            tags = metadata.get('tags')
            if (not isinstance(tags,list) or len(tags)>12
                    or any(not isinstance(tag,str) or not 1<=len(tag)<=24
                        or any(ord(char)<32 for char in tag) for tag in tags)
                    or len(set(tags))!=len(tags)):
                return None, 'invalid_native_core_tags'
            core_scope='private'
        else:
            core_scope = metadata.get('core_scope')
        if not native and core_scope == 'private':
            if (row.get('scope') != 'private' or row.get('visibility') != 'private_pair'
                    or row.get('platform') != scope['platform']
                    or row.get('session_id') not in ('', scope['session_id'])
                    or metadata.get('target_id') != scope['user_id']
                    or not any(actor.get('kind') == 'user' and actor.get('id') == scope['user_id'] for actor in actors)):
                return None, 'scope_mismatch'
        elif not native and core_scope == 'global':
            if (row.get('scope') != 'global' or row.get('visibility') != 'bot_self'
                    or row.get('platform') not in ('', scope['platform'])
                    or metadata.get('target_id') not in ('', None)
                    or any(actor.get('kind') != 'bot' for actor in actors)):
                return None, 'global_core_scope_mismatch'
        elif not native:
            return None, 'unsupported_core_scope'
        if ((not native and (metadata.get('core_memory') is not True
                    or metadata.get('core_enabled') is not True
                    or metadata.get('managed_by') != 'memory_panel'
                    or row.get('source_plugin') != 'memory_companion_core'
                    or row.get('reality_level') != 'explicit_user_statement'))
                or row.get('review_status') not in _REVIEWED
                or row.get('validity_status', 'active') != 'active'
                or row.get('lifecycle') != 'stable_memory'):
            return None, 'unmanaged_or_inactive_core'
        if (metadata.get('extraction_quality') == 'inferred'
                or metadata.get('evidence_kind') not in (None, 'user_reported')
                or metadata.get('provenance_classification') not in (None, 'user_reported')):
            return None, 'non_real_or_conflicting_provenance'
        if (row.get('sensitivity') not in {'private', 'internal', 'public'}
                or row.get('sayability') not in {'direct', 'indirect'}):
            return None, 'sensitive_record'
        revision = row.get('revision') if native else metadata.get('core_revision')
        priority = metadata.get('core_priority')
        label = metadata.get('title') if native else metadata.get('core_label')
        kind = metadata.get('core_kind')
        if (type(revision) is not int or revision < 1 or type(priority) is not int or not 0 <= priority <= 100
                or not isinstance(label, str) or not label.strip() or len(label) > 80
                or kind not in _CORE_KINDS):
            return None, 'invalid_core_contract'
        try:
            since = _time(row['valid_from']) if row.get('valid_from') not in (None, '') else None
            until = _time(row['valid_to']) if row.get('valid_to') not in (None, '') else None
            expiry = _time(metadata['expires_at']) if metadata.get('expires_at') not in (None, '') else None
            expiry = min(item for item in (until, expiry) if item is not None) if until is not None or expiry is not None else None
            if since is not None and (since > now or until is not None and until <= since):
                return None, 'invalid_or_future_validity'
            if expiry is not None and expiry <= now:
                return None, 'expired'
        except (ValueError, TypeError, OverflowError):
            return None, 'invalid_time'
        content = row.get('content')
        if (not isinstance(content, str) or not content.strip() or len(content) > (2000 if native else 6000)
                or any(ord(char) < 32 and char not in '\t\n\r' for char in content)):
            return None, 'invalid_content'
        if _SECRET.search(content):
            return None, 'credential_material'
        text = '管理端确认的长期约定（不能覆盖本轮纠正或平台约束）：' + html.escape(' '.join(content.split()), quote=False)
        return dict(identity=row['id'], text=text, kind='user_reported', expires_at=expiry,
                    priority=priority, revision=revision, trust_tier=0, claim=(core_scope, kind, _normal(label)),
                    content=_normal(content)), ''

    @staticmethod
    def _profile_proof(row, metadata):
        if row.get('source_id')=='tls.chat.profile_candidates':
            proof=metadata.get('native_profile_candidates')
            if (not isinstance(proof,dict) or type(proof.get('schema')) is not int or proof.get('schema')!=1
                    or proof.get('id')!=row.get('id') or type(proof.get('revision')) is not int
                    or proof['revision']<1 or proof['revision']!=row.get('revision')
                    or proof.get('status')!='active' or proof.get('review_status')!=row.get('review_status')
                    or type(proof.get('evidence_count')) is not int or proof['evidence_count']<0
                    or row.get('review_status')=='auto' and proof['evidence_count']<1):return False
            if row.get('review_status') in {'approved','confirmed'} and (
                    type(proof.get('reviewer')) is not str or not proof['reviewer'].strip()
                    or type(proof.get('review_event_id')) is not str or not proof['review_event_id']):return False
        if row.get('review_status') in _REVIEWED:
            return True
        if row.get('review_status') != 'auto' or row.get('memory_type') == 'relationship_claim':
            return False
        score = metadata.get('extraction_quality_score')
        return (str(metadata.get('extractor', '')).startswith('rule_')
            and metadata.get('profile_state') == 'active'
            and isinstance(metadata.get('profile_dimension'), str) and bool(metadata['profile_dimension'])
            and isinstance(metadata.get('profile_value'), str) and bool(metadata['profile_value'])
            and isinstance(metadata.get('normalized_value'), str)
            and _normal(metadata['normalized_value']) == _normal(metadata['profile_value'])
            and metadata.get('extraction_quality') in {'explicit', 'confirmed', 'corroborated'}
            and metadata.get('evidence_strength') in {'direct_statement', 'user_confirmed', 'multiple_independent_evidence', 'independent_evidence'}
            and metadata.get('quality_gate_passed') is True
            and type(score) in (int, float) and math.isfinite(score) and .75 <= score <= 1)

    def select(self, rows, *, scope, query='', kind='ability', now, max_chars=900):
        scope = private_scope(scope)
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('invalid policy clock')
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('invalid private query')
        if not isinstance(kind, str) or len(kind) > 64:
            raise ValueError('invalid private context kind')
        if type(max_chars) is not int or not 160 <= max_chars <= 2400:
            raise ValueError('invalid private context budget')
        if not isinstance(rows, list) or len(rows) > self.max_candidates:
            raise ValueError('invalid private candidate batch')
        kind = normalize_kind(kind)
        cores, factual, rejected, validated_facts = [], [], [], []
        for raw in rows:
            identity = raw.get('id', '') if isinstance(raw, dict) else ''
            identity = identity if isinstance(identity, str) and _ID.fullmatch(identity) else ''
            try:
                row = plain(raw, 32768)
                if not isinstance(row, dict) or not identity:
                    raise ValueError('invalid record')
                metadata = row.get('metadata', {})
                private_metadata = row.get('private_context_metadata', {})
                if not isinstance(metadata, dict) or not isinstance(private_metadata, dict):
                    raise ValueError('invalid metadata')
                if any(metadata[key] != value for key, value in private_metadata.items() if key in metadata):
                    rejected.append({'id': identity, 'reason': 'conflicting_metadata'})
                    continue
                metadata = dict(metadata, **private_metadata)
                if (metadata.get('evidence_kind') is not None and metadata.get('provenance_classification') is not None
                        and metadata['evidence_kind'] != metadata['provenance_classification']):
                    rejected.append({'id': identity, 'reason': 'non_real_or_conflicting_provenance'})
                    continue
                if row.get('memory_type') == 'core_memory':
                    item, reason = self._core(row, scope, now)
                    if item is not None:
                        cores.append(item)
                    else:
                        rejected.append({'id': identity, 'reason': reason})
                    continue
                record_type = row.get('memory_type')
                if record_type not in _PROFILE | _FACT:
                    rejected.append({'id': identity, 'reason': 'unsupported_private_type'})
                    continue
                if any(isinstance(actor, dict) and actor.get('kind') == 'bot'
                       and actor.get('id') not in ('', scope['bot_id'])
                       for actor in (row.get('subject'), row.get('object'))):
                    rejected.append({'id': identity, 'reason': 'actor_mismatch'})
                    continue
                if record_type in _PROFILE and not self._profile_proof(row, metadata):
                    rejected.append({'id': identity, 'reason': 'profile_review_proof_required'})
                    continue
                if metadata.get('profile_state') not in (None, '', 'active'):
                    rejected.append({'id': identity, 'reason': 'inactive_profile'})
                    continue
                content = row.get('content')
                if not isinstance(content, str):
                    raise ValueError('invalid content')
                relevant = bool(query.strip() and _terms(query) & _terms(content))
                if record_type in _PROFILE and kind in {'schedule', 'outfit'}:
                    relevant = bool((_SCHEDULE if kind == 'schedule' else _OUTFIT).search(content))
                if not relevant:
                    rejected.append({'id': identity, 'reason': 'not_relevant'})
                    continue
                row = deepcopy(row)
                row['metadata'] = deepcopy(metadata)
                if record_type in _PROFILE and row.get('review_status') == 'auto':
                    # Proven native explicit-profile proof, not a source write.
                    row['review_status'] = 'approved'
                candidate, reason = NativeMemoryContextPolicy._candidate(row, scope, now)
                if candidate is None:
                    rejected.append({'id': identity, 'reason': reason})
                    continue
                validated_facts.append((row, candidate))
            except (ValueError, TypeError, OverflowError, RecursionError):
                rejected.append({'id': identity, 'reason': 'invalid_record'})
        fact_groups, fact_contents = {}, {}
        for row, candidate in validated_facts:
            fact_groups.setdefault(candidate.identity, []).append((row, candidate))
        for identity, items in fact_groups.items():
            signatures = {(row['memory_type'], candidate.content, candidate.kind, candidate.occurred_at,
                candidate.expires_at, candidate.claim_key, candidate.confidence, candidate.importance,
                candidate.utterance, row.get('reality_level')) for row, candidate in items}
            if len(signatures) != 1:
                rejected.append({'id': identity, 'reason': 'conflicting_identity'})
                continue
            # An existing retrieval rank is not a second fact revision. The
            # raw snapshot has no score; reuse the highest verified rank when
            # the very same record is also returned by the public retriever.
            row, candidate = max(items, key=lambda item: item[1].score)
            factual.append(row)
            fact_contents[identity] = candidate.value
            if len(items) > 1:
                rejected.append({'id': identity, 'reason': 'duplicate_identity'})
        by_identity, by_claim = {}, {}
        for item in cores:
            by_identity.setdefault(item['identity'], []).append(item)
        for identity, items in by_identity.items():
            tier=min(item['trust_tier'] for item in items)
            if any(item['trust_tier']!=tier for item in items):
                rejected.append({'id':identity,'reason':'lower_authority_core_source'})
                items=[item for item in items if item['trust_tier']==tier]
            signatures = {(item['claim'], item['content'], item['priority'], item['revision'], item['expires_at']) for item in items}
            if len(signatures) != 1:
                rejected.append({'id': identity, 'reason': 'conflicting_identity'})
            else:
                by_claim.setdefault(items[0]['claim'], []).append(items[0])
                if len(items) > 1:
                    rejected.append({'id': identity, 'reason': 'duplicate_identity'})
        resolved = []
        for items in by_claim.values():
            if len({item['content'] for item in items}) != 1:
                rejected.extend({'id': item['identity'], 'reason': 'unresolved_core_conflict'} for item in items)
            else:
                ordered = sorted(items, key=lambda item: (-item['priority'], item['identity']))
                resolved.append(ordered[0])
                rejected.extend({'id': item['identity'], 'reason': 'duplicate_content'} for item in ordered[1:])
        fact_result = NativeMemoryContextPolicy(max_candidates=self.max_candidates,
            max_items=self.max_items).select(factual, scope=scope, query=query, now=now, max_chars=2400)
        # IDs are global in the source SQLite store. A concurrent stale raw
        # view and recall may not turn one ID into both a core block and fact.
        # Compare only validated/selected candidates, so an invalid foreign
        # row cannot poison an independently authorized record with that ID.
        collisions = {item['identity'] for item in resolved} & set(fact_groups)
        if collisions:
            resolved = [item for item in resolved if item['identity'] not in collisions]
            kept = [(identity, section) for identity, section in zip(
                fact_result['selected_ids'], fact_result['sections']) if identity not in collisions]
            fact_result['selected_ids'] = [identity for identity, _ in kept]
            fact_result['sections'] = [section for _, section in kept]
            rejected.extend({'id': identity, 'reason': 'conflicting_identity'} for identity in sorted(collisions))
        sections, selected, used, seen = [], [], 0, set()
        # A model-arranged tool parameter cannot displace administrator/user
        # confirmed constraints, even with a higher numeric priority or label.
        for item in sorted(resolved, key=lambda item: (item['trust_tier'], -item['priority'], item['identity'])):
            if item['content'] in seen:
                rejected.append({'id': item['identity'], 'reason': 'duplicate_content'})
                continue
            seen.add(item['content'])
            if len(sections) >= self.max_core_items or used + len(item['text']) > max_chars:
                rejected.append({'id': item['identity'], 'reason': 'context_budget'})
                continue
            sections.append({'id': 'private_memory.'+hashlib.sha256(item['identity'].encode()).hexdigest()[:24],
                'text': item['text'], 'source': 'tls.private_memory', 'evidence_kind': item['kind'],
                'expires_at': item['expires_at'],
                'content_key': hashlib.sha256(item['content'].encode()).hexdigest()})
            selected.append(item['identity'])
            used += len(item['text'])
        if factual:
            # Reuse Stage 6 native fact validation/conflict resolution, not a
            # second retriever or the old Memory final-expression composer.
            rejected.extend(fact_result['rejected'])
            for identity, section in zip(fact_result['selected_ids'], fact_result['sections']):
                content = fact_contents[identity]
                if content in seen:
                    rejected.append({'id': identity, 'reason': 'duplicate_content'})
                    continue
                seen.add(content)
                if len(sections) >= self.max_items or used + len(section['text']) > max_chars:
                    rejected.append({'id': identity, 'reason': 'context_budget'})
                    continue
                section = dict(section, id='private_memory.'+hashlib.sha256(identity.encode()).hexdigest()[:24],
                    source='tls.private_memory', content_key=hashlib.sha256(content.encode()).hexdigest())
                sections.append(section)
                selected.append(identity)
                used += len(section['text'])
        return {'version': self.version, 'sections': sections, 'selected_ids': selected,
                'rejected': rejected, 'chars': used, 'budget_unit': 'unicode_characters_not_billed_tokens',
                'old_composer_calls': 0, 'writes': 0, 'retriever_calls': 0, 'provider_calls': 0,
                'schedules': 0, 'sends': 0}
