"""Pure, fail-closed attribution preview for historical schedule records.

This module does not query a database or grant visibility. A definite result is
an identity attribution, never permission to execute or inject the schedule.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from collections.abc import Mapping, Sequence


VERSION = 'tls.schedule.attribution.v1'
_ID = re.compile(r'[A-Za-z0-9_.:@-]{1,220}')
_SHA = re.compile(r'[a-f0-9]{64}')
_TYPES = frozenset({'schedule_fragment', 'persona_life'})
_MAX_ROWS = 10000


def digest(value):
    """Digest the complete JSON value, including fields not used by the policy."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _identity(value, *, optional=False, limit=220):
    if value == '' and optional:
        return ''
    if not isinstance(value, str) or len(value) > limit or not _ID.fullmatch(value) or value in {'self', 'unknown', 'default'}:
        raise ValueError('invalid explicit identity')
    return value


def _metadata(row):
    raw = row.get('metadata', {})
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False)) > 64000:
        raise ValueError('invalid metadata')
    return value


@dataclass(frozen=True)
class VerifiedHistoricalBinding:
    """An exact binding from authenticated history or an explicit operator claim.

    A JSON file is not an authenticated reader. The bundled CLI can create only
    the separately labelled operator_assertion kind, never archive verification.
    """
    node_id: str
    database_sha256: str
    record_id: str
    record_sha256: str
    bot_id: str
    persona_id: str
    source_artifact_sha256: str
    session_id: str = ''
    platform: str = ''
    evidence_origin: str = 'authenticated_archive'

    def validate(self):
        for value in (self.node_id, self.record_id):
            _identity(value)
        for value in (self.bot_id, self.persona_id):
            _identity(value, limit=120)
        for value in (self.session_id, self.platform):
            _identity(value, optional=True)
        for value in (self.database_sha256, self.record_sha256, self.source_artifact_sha256):
            if not isinstance(value, str) or not _SHA.fullmatch(value):
                raise ValueError('invalid evidence digest')
        if self.evidence_origin not in {'authenticated_archive', 'operator_assertion'}:
            raise ValueError('invalid evidence origin')


class ScheduleAttributionPlanner:
    """Return definite, ambiguous and unresolved records without changing input.

    Existing complete owner/persona fields are the only automatic evidence.
    Exact, reviewed historical bindings can be supplied through the typed
    boundary, retaining authenticated_archive/operator_assertion provenance.
    Generic session names, provider IDs, dates, node names,
    content similarity and the current persona are never attribution evidence.
    """
    def preview(self, rows, *, node_id, database_sha256, bindings=()):
        _identity(node_id)
        if not isinstance(database_sha256, str) or not _SHA.fullmatch(database_sha256):
            raise ValueError('invalid database digest')
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) > _MAX_ROWS:
            raise ValueError('invalid record population')
        if not isinstance(bindings, Sequence) or len(bindings) > _MAX_ROWS:
            raise ValueError('invalid evidence population')
        by_id = {}
        for binding in bindings:
            if not isinstance(binding, VerifiedHistoricalBinding):
                raise ValueError('unverified binding')
            binding.validate()
            by_id.setdefault(binding.record_id, []).append(binding)
        records, seen, serialized_bytes = [], set(), 0
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError('invalid record')
            raw = dict(row)
            identity = raw.get('id', '')
            _identity(identity)
            if identity in seen:
                raise ValueError('duplicate record identity')
            seen.add(identity)
            row_size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            serialized_bytes += row_size
            if row_size > 128000 or serialized_bytes > 16 * 1024 * 1024:
                raise ValueError('record budget exceeded')
            fingerprint = digest(raw)
            item = dict(record_id=identity, record_sha256=fingerprint,
                status='unresolved', reason='missing_identity_evidence', patch={}, evidence=[])
            if raw.get('memory_type') not in _TYPES:
                item['reason'] = 'not_schedule'
                records.append(item)
                continue
            try:
                metadata = _metadata(raw)
                owners = {v for v in (raw.get('owner_bot_id', ''), metadata.get('owner_bot_id', ''))
                    if v not in ('', 'self', None)}
                personas = {v for v in (raw.get('persona_id', ''), metadata.get('persona_id', ''))
                    if v not in ('', None)}
                for value in owners | personas:
                    _identity(value, limit=120)
                for prefix in ('subject', 'object'):
                    if raw.get(prefix + '_kind') == 'bot' and raw.get(prefix + '_id') not in ('', 'self', None):
                        owners.add(_identity(raw[prefix + '_id'], limit=120))
                if len(owners) > 1 or len(personas) > 1:
                    item.update(status='ambiguous', reason='conflicting_embedded_identity')
                    records.append(item)
                    continue
                targets, origins = set(), set()
                if owners and personas:
                    targets.add((next(iter(owners)), next(iter(personas))))
                    item['evidence'].append('embedded_explicit_identity')
                    origins.add('embedded_explicit_identity')
                stale = False
                for binding in by_id.get(identity, ()):
                    if binding.node_id != node_id or binding.database_sha256 != database_sha256 or binding.record_sha256 != fingerprint:
                        stale = True
                        continue
                    if binding.session_id and binding.session_id != raw.get('session_id', ''):
                        stale = True
                        continue
                    if binding.platform and binding.platform != raw.get('platform', ''):
                        stale = True
                        continue
                    if (owners and binding.bot_id not in owners) or (personas and binding.persona_id not in personas):
                        item.update(status='ambiguous', reason='historical_identity_conflict')
                        break
                    targets.add((binding.bot_id, binding.persona_id))
                    item['evidence'].append(binding.source_artifact_sha256)
                    origins.add(binding.evidence_origin)
                else:
                    if stale:
                        item['reason'] = 'stale_or_foreign_evidence'
                    if len(targets) > 1:
                        item.update(status='ambiguous', reason='multiple_exact_bindings')
                    elif targets:
                        owner, persona = next(iter(targets))
                        item.update(status='definite', reason='exact_identity', patch={
                            'owner_bot_id': owner, 'persona_id': persona})
                        if origins == {'operator_assertion'}:
                            item['reason'] = 'operator_asserted_exact_identity'
                        item['evidence_origin'] = sorted(origins)
                    records.append(item)
                    continue
                records.append(item)
            except (TypeError, ValueError, json.JSONDecodeError):
                item.update(reason='invalid_metadata_or_identity', patch={}, evidence=[])
                records.append(item)
        counts = {state: sum(r['status'] == state for r in records)
                  for state in ('definite', 'ambiguous', 'unresolved')}
        result = dict(version=VERSION, node_id=node_id, database_sha256=database_sha256,
            records=records, counts=counts, row_count=len(records))
        result['preview_sha256'] = digest(result)
        return result


def safe_summary(preview):
    """Public report: no Bot/persona/session, paths, contents, or raw record IDs."""
    if preview.get('version') != VERSION:
        raise ValueError('invalid preview')
    return dict(version=VERSION, database_sha256=preview['database_sha256'],
        preview_sha256=preview['preview_sha256'], row_count=preview['row_count'],
        counts=dict(preview['counts']), records=[dict(record_ref=digest(r['record_id']),
            status=r['status'], reason=r['reason'], evidence_origin=r.get('evidence_origin', []))
            for r in preview['records']])
