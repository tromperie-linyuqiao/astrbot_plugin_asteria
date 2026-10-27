"""Native, side-effect-free selection of retrieved private memory material.

The public memory bridge remains an optional retrieval adapter.  No legacy
composer, store, provider or entrypoint is imported here.  The caller owns
authorization and the single context outlet; this policy neither persists
memory nor changes a persona prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
import math
import re
import unicodedata

from .models import plain, private_scope

_PROFILE_TYPES = frozenset({'user_profile', 'user_preference', 'user_habit'})
_REALITY = {'real_user_fact': 'user_reported', 'observed_utterance': 'user_reported',
            'external_observation': 'real_observation'}
_DIRECT = frozenset({'mention', 'direct'})
_SECRET = re.compile(
    r'(?i)(?:密码|口令|验证码|password|passcode|api[ _-]?key|token|cookie|密钥|秘钥)'
    r'\s*(?::|：|=|是|为|is\b)\s*[^；，。！？!?\n]{1,160}')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,160}')


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _epoch(value):
    if type(value) in (float, int):
        if math.isfinite(value) and value >= 0:
            return float(value)
        raise ValueError('invalid timestamp')
    if isinstance(value, str) and 0 < len(value) <= 80:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timezone required')
        result = parsed.timestamp()
        if math.isfinite(result) and result >= 0:
            return result
    raise ValueError('invalid timestamp')


def _score(value, default):
    if value is None:
        return default
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('invalid score')
    return float(value)


def _history_review(row, metadata, scope, kind):
    """Keep an administrator's historical review distinct from user speech.

    This checks the existing adoption contract; it does not revisit an archive,
    infer historical ownership or turn the original material into observation.
    """
    proof = metadata.get('history_adoption')
    fields = {'schema', 'archive_id', 'raw_hash', 'source_hash', 'snapshot_hash',
              'legacy_record_id', 'original', 'hold_reasons', 'assignment', 'review',
              'created_request_ref'}
    if (row.get('source_id') != 'history.reviewed' or kind != 'user_reported'
            or row.get('memory_type') not in {'utterance', 'fact', 'preference', 'event'}
            or row.get('reality_level') != ('observed_utterance' if row.get('memory_type') == 'utterance' else 'real_user_fact')
            or not isinstance(proof, dict) or set(proof) != fields
            or proof.get('schema') != 'tls.native_history_adoption.v1'):
        return ''
    if (not isinstance(proof['archive_id'], str)
            or not re.fullmatch(r'ha_[a-f0-9]{64}', proof['archive_id'])
            or any(not isinstance(proof[key], str) or not re.fullmatch(r'[a-f0-9]{64}', proof[key])
                   for key in ('raw_hash', 'source_hash', 'snapshot_hash', 'created_request_ref'))
            or not isinstance(proof['legacy_record_id'], str) or not proof['legacy_record_id'].strip()
            or len(proof['legacy_record_id']) > 2048
            or not isinstance(proof['original'], dict)
            or set(proof['original']) != {'memory_type', 'reality_level', 'evidence'}
            or not isinstance(proof['original']['evidence'], dict)
            or not isinstance(proof['hold_reasons'], list)
            or any(not isinstance(reason, str) for reason in proof['hold_reasons'])):
        return ''
    assignment, review = proof['assignment'], proof['review']
    if (not isinstance(assignment, dict) or set(assignment) != {'scope', 'statement', 'basis'}
            or not isinstance(assignment['scope'], dict) or assignment['scope'].get('private') is not True
            or assignment['scope'] != scope
            or assignment['basis'] != 'explicit_administrator_assignment'
            or not isinstance(assignment['statement'], str) or not assignment['statement'].strip()
            or len(assignment['statement']) > 300
            or not isinstance(review, dict)
            or set(review) != {'basis', 'memory_type', 'evidence_kind', 'confirmed', 'real_world_confirmed'}
            or review['basis'] != 'explicit_review' or review['confirmed'] is not True
            or review['memory_type'] != row['memory_type'] or review['evidence_kind'] != kind
            or type(review['real_world_confirmed']) is not bool):
        return ''
    if row['memory_type'] == 'utterance':
        return 'unconfirmed_history_material' if not review['real_world_confirmed'] else ''
    return 'confirmed_historical_user_report' if review['real_world_confirmed'] else ''


@dataclass(frozen=True)
class _Candidate:
    identity: str
    content: str
    kind: str
    occurred_at: float | None
    expires_at: float | None
    claim_key: str
    value: str
    score: float
    confidence: float
    importance: float
    utterance: bool
    import_review: str = ''


class NativeMemoryContextPolicy:
    """Bounded, deterministic policy with per-call diagnostics and no cache.

    It replaces only final *real private memory* selection and rendering.
    Group ACLs, cross-window summaries, extraction, embedding/reranking and
    review workflows remain outside this slice.  Conflicts need an explicit
    canonical key; the policy never guesses semantic contradictions.
    """
    version = 'tls.memory_context.v1'

    def __init__(self, *, max_candidates=32, max_items=5):
        if type(max_candidates) is not int or not 1 <= max_candidates <= 64:
            raise ValueError('invalid candidate capacity')
        if type(max_items) is not int or not 1 <= max_items <= 8:
            raise ValueError('invalid memory item capacity')
        self.max_candidates, self.max_items = max_candidates, max_items

    @staticmethod
    def _candidate(row, scope, now):
        if not isinstance(row, dict):
            return None, 'invalid_record'
        try:
            row = plain(row, 32768)
        except (TypeError, ValueError, RecursionError):
            return None, 'invalid_record'
        # Owner-managed core records have one dedicated bounded outlet.
        # Even disabled or malformed rows cannot fall back into generic recall.
        if (row.get('source_plugin') == 'texas_living_system'
                and row.get('source_id') == 'tls.personal.panel'
                and row.get('memory_type') == 'core_memory'):
            return None, 'native_core_uses_private_outlet'
        identity = row.get('id')
        if not isinstance(identity, str) or not _IDENTIFIER.fullmatch(identity):
            return None, 'invalid_identity'
        if (row.get('scope') != 'private' or row.get('visibility') != 'private_pair'
                or row.get('owner_bot_id') != scope['bot_id']
                or row.get('persona_id') != scope['character_id']
                or row.get('session_id') != scope['session_id']
                or row.get('platform', scope['platform']) != scope['platform']):
            return None, 'scope_mismatch'
        actors = (row.get('subject'), row.get('object'))
        if not any(isinstance(actor, dict) and actor.get('kind') == 'user'
                   and actor.get('id') == scope['user_id'] for actor in actors):
            return None, 'actor_mismatch'
        # A row about another user must not borrow the current user's presence
        # in the other actor position to become their personal fact.
        def default_placeholder(actor):
            # MemoryRecord's optional EntityRef defaults to an empty user
            # actor (role unknown); the public serializer retains that shape.
            # An actual name, identity or meaningful role is not a placeholder.
            return (actor.get('id') == '' and actor.get('name') == ''
                    and actor.get('role') in {'', 'unknown'})
        if any(isinstance(actor, dict) and actor.get('kind') == 'user'
               and actor.get('id') != scope['user_id'] and not default_placeholder(actor)
               for actor in actors):
            return None, 'third_party_actor'
        metadata = row.get('metadata', {})
        if not isinstance(metadata, dict):
            return None, 'invalid_metadata'
        kind = _REALITY.get(row.get('reality_level'))
        declared = metadata.get('evidence_kind', metadata.get('provenance_classification'))
        if kind is None or declared not in (None, kind):
            return None, 'non_real_or_conflicting_provenance'
        import_review = ''
        historical = 'history_adoption' in metadata or row.get('source_id') == 'history.reviewed'
        if historical:
            if 'memory_transfer' in metadata:
                return None, 'ambiguous_import_provenance'
            import_review = _history_review(row, metadata, scope, kind)
            if not import_review:
                return None, 'invalid_history_import_provenance'
        if 'memory_transfer' in metadata or row.get('source_id') == 'memory.imported':
            transfer = metadata.get('memory_transfer')
            fields = {'schema', 'basis', 'created_request_ref', 'source_label', 'source_updated_at',
                      'explicitly_confirmed', 'real_world_confirmed'}
            if (row.get('source_id') != 'memory.imported' or kind != 'user_reported'
                    or row.get('memory_type') not in {'utterance', 'fact', 'preference', 'event'}
                    or not isinstance(transfer, dict) or set(transfer) != fields
                    or transfer.get('schema') != 'tls.native_memory_transfer.v1'
                    or transfer.get('basis') != 'user_provided_material'
                    or transfer.get('explicitly_confirmed') is not True
                    or type(transfer.get('real_world_confirmed')) is not bool
                    or not isinstance(transfer.get('created_request_ref'), str)
                    or not re.fullmatch(r'[a-f0-9]{64}', transfer['created_request_ref'])
                    or not isinstance(transfer.get('source_label'), str) or len(transfer['source_label']) > 128
                    or any(ord(char) < 32 and char not in '\t\r\n' for char in transfer['source_label'])):
                return None, 'invalid_import_provenance'
            try:
                if transfer['source_updated_at'] is not None:
                    _epoch(transfer['source_updated_at'])
            except (ValueError, TypeError, OverflowError):
                return None, 'invalid_import_provenance'
            confirmed = transfer['real_world_confirmed'] and row['memory_type'] in {'fact', 'preference', 'event'}
            if row['memory_type'] != 'utterance' and not confirmed:
                return None, 'unconfirmed_import_fact'
            import_review = 'confirmed_user_report' if confirmed else 'unconfirmed_material'
        if metadata.get('extraction_quality') == 'inferred':
            return None, 'inference_not_fact'
        tags = row.get('tags', [])
        if not isinstance(tags, list) or len(tags) > 64 or any(not isinstance(tag, str) for tag in tags):
            return None, 'invalid_tags'
        if (metadata.get('claim_domain') == 'system_catalog_metadata'
                or 'catalog_metadata_only' in tags):
            return None, 'catalog_is_not_personal_memory'
        if (row.get('validity_status', 'active') != 'active'
                or row.get('lifecycle') in {'archived', 'deleted', 'superseded', 'quarantined'}
                or row.get('review_status') in {'pending', 'rejected'}
                or metadata.get('profile_state') in {'candidate', 'pending', 'rejected', 'superseded', 'archived'}):
            return None, 'inactive_or_unreviewed'
        # Public serialization omits the rule extractor's quality evidence.
        # Never promote an auto-reviewed profile when that proof is absent.
        if row.get('source_id')=='tls.chat.profile_candidates':
            from .private_memory_context import NativePrivateMemoryContextPolicy
            if not NativePrivateMemoryContextPolicy._profile_proof(row,metadata):
                return None,'native_profile_review_proof_required'
        if row.get('memory_type') in _PROFILE_TYPES and row.get('review_status') not in {'manual', 'approved', 'confirmed'}:
            if row.get('source_id')!='tls.chat.profile_candidates' or row.get('review_status')!='auto':
                return None, 'profile_review_proof_required'
        if row.get('sensitivity', 'private') not in {'public', 'private'}:
            return None, 'sensitive_record'
        if row.get('sayability', 'direct') not in {'direct', 'indirect'}:
            return None, 'not_sayable'
        reason = row.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 2000:
            return None, 'invalid_expression'
        expressions = re.findall(r'(?:^|;)expression=([^;]+)', reason)
        if expressions and (len(expressions) != 1 or expressions[0].strip() not in _DIRECT):
            # Tone-only content is omitted, rather than leaked inside a hint.
            return None, 'expression_not_direct'
        policy = row.get('mention_policy', metadata.get('mention_policy', ''))
        if policy not in {'', 'direct', 'soft_echo'}:
            return None, 'mention_policy_requires_explicit_request'
        try:
            confidence = _score(row.get('confidence'), .5)
            importance = _score(row.get('importance'), .3)
            score = row.get('score', 0)
            # The existing lexical retrieval score is not a probability and
            # routinely exceeds 1. Preserve ordering without treating it as
            # epistemic confidence.
            if type(score) not in (float, int) or not math.isfinite(score) or abs(score) > 1e6:
                raise ValueError('invalid retrieval score')
            if confidence < .75:
                return None, 'low_confidence'
            since = _epoch(row['valid_from']) if row.get('valid_from') not in (None, '') else None
            until = _epoch(row['valid_to']) if row.get('valid_to') not in (None, '') else None
            expiry = metadata.get('expires_at', row.get('expires_at'))
            expiry = _epoch(expiry) if expiry is not None else None
            expires_at = min(t for t in (until, expiry) if t is not None) if any(
                t is not None for t in (until, expiry)) else None
            occurred = row.get('occurred_at')
            occurred = _epoch(occurred) if occurred not in (None, '') else None
        except (TypeError, ValueError, OverflowError):
            return None, 'invalid_time_or_score'
        if since is not None and until is not None and until <= since:
            return None, 'invalid_validity_window'
        if since is not None and since > now or occurred is not None and occurred > now:
            return None, 'future_record'
        if expires_at is not None and expires_at <= now:
            return None, 'expired'
        content = row.get('content')
        if (not isinstance(content, str) or not content.strip() or len(content) > 6000
                or any(ord(char) < 32 and char not in '\t\r\n' for char in content)):
            return None, 'invalid_content'
        if _SECRET.search(content):
            return None, 'credential_material'
        content = ' '.join(content.split())
        claim_key = row.get('canonical_key', '')
        if not isinstance(claim_key, str) or len(claim_key) > 240:
            return None, 'invalid_claim_key'
        return _Candidate(identity, content, kind, occurred, expires_at,
            claim_key, _normal(content), score, confidence, importance,
            row.get('reality_level') == 'observed_utterance', import_review), ''

    def select(self, rows, *, scope, query='', now, max_chars=900):
        """Return typed data sections for the existing ContextAssembler.

        ``query`` is accepted for the stable API but relevance belongs to the
        authorized retrieval adapter.  No keyword/emotion inference happens
        here.  Character limits are Unicode characters, not billed tokens.
        """
        scope = private_scope(scope)
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('invalid policy clock')
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('invalid query')
        if type(max_chars) is not int or not 120 <= max_chars <= 2400:
            raise ValueError('invalid memory context budget')
        if not isinstance(rows, list) or len(rows) > self.max_candidates:
            raise ValueError('invalid memory candidate batch')
        candidates, rejected = [], []
        for row in rows:
            try:
                item, reason = self._candidate(row, scope, now)
            except (TypeError, ValueError, OverflowError):
                # A JSON-compatible but wrongly typed field must not prevent
                # an independent valid candidate from reaching the assembler.
                item, reason = None, 'invalid_record'
            if item is None:
                raw_id = row.get('id', '') if isinstance(row, dict) else ''
                safe_id = raw_id if isinstance(raw_id, str) and _IDENTIFIER.fullmatch(raw_id) else ''
                rejected.append({'id': safe_id, 'reason': reason})
            else:
                candidates.append(item)
        # Same ID with different content/provenance is corrupt, not two facts.
        by_id = {}
        for item in candidates:
            by_id.setdefault(item.identity, []).append(item)
        unique = []
        for identity, items in by_id.items():
            if len(set(items)) != 1:
                rejected.append({'id': identity, 'reason': 'conflicting_identity'})
            else:
                unique.append(items[0])
                if len(items) > 1:
                    rejected.append({'id': identity, 'reason': 'duplicate_identity'})
        # Keys are supplied by storage, never generated by guessing semantics.
        groups = {}
        for item in unique:
            groups.setdefault(item.claim_key or 'id:' + item.identity, []).append(item)
        resolved = []
        for items in groups.values():
            values = {(item.kind, item.value) for item in items}
            if len(values) == 1:
                resolved.extend(items)
                continue
            dated = all(item.occurred_at is not None for item in items)
            latest = max(items, key=lambda item: item.occurred_at or 0) if dated else None
            unique_latest = bool(latest and sum(item.occurred_at == latest.occurred_at for item in items) == 1)
            # New explicit user statements may correct an old fact. A sensor
            # result cannot silently negate the user's own earlier statement.
            if unique_latest and (latest.kind == 'user_reported' or len({item.kind for item in items}) == 1):
                resolved.append(latest)
                rejected.extend({'id': item.identity, 'reason': 'superseded_in_context'}
                                for item in items if item is not latest)
            else:
                rejected.extend({'id': item.identity, 'reason': 'unresolved_conflict'} for item in items)
        seen, sections, selected, used = set(), [], [], 0
        for item in sorted(resolved, key=lambda value: (-value.score, -value.importance,
                -value.confidence, -(value.occurred_at or 0), value.identity)):
            digest = (item.kind, item.value)
            if digest in seen:
                rejected.append({'id': item.identity, 'reason': 'duplicate_content'})
                continue
            seen.add(digest)
            if item.import_review == 'unconfirmed_material':
                prefix = '人工导入资料（来源文本，未经事实确认）'
            elif item.import_review == 'confirmed_user_report':
                prefix = '人工导入资料（人工确认的用户报告，未经系统事实核实）'
            elif item.import_review == 'unconfirmed_history_material':
                prefix = '人工复核历史资料（来源文本，未经事实确认）'
            elif item.import_review == 'confirmed_historical_user_report':
                prefix = '人工复核历史资料（人工确认的用户报告，未经系统事实核实）'
            else:
                prefix = '用户曾明确说过（不代表现在仍如此）' if item.utterance else '历史记忆资料'
            text = prefix + '：' + html.escape(item.content, quote=False)
            if len(sections) >= self.max_items or used + len(text) > max_chars:
                rejected.append({'id': item.identity, 'reason': 'context_budget'})
                continue  # Never cut a sentence and accidentally negate it.
            identifier = 'memory.' + hashlib.sha256(item.identity.encode()).hexdigest()[:24]
            sections.append({'id': identifier, 'text': text, 'evidence_kind': item.kind,
                             'expires_at': item.expires_at})
            selected.append(item.identity)
            used += len(text)
        return {'version': self.version, 'sections': sections, 'selected_ids': selected,
                'rejected': rejected, 'chars': used,
                'budget_unit': 'unicode_characters_not_billed_tokens',
                'old_composer_calls': 0, 'writes': 0, 'schedules': 0, 'sends': 0}
