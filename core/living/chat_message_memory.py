"""Saved-message provenance and separately labelled scoped lexical memory search.

No generated facts, QQ identity adoption, or separate memory DB. Related search
never establishes provenance. The SDK event UUID is joined to a saved USER row
only by its real checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from .chat_expressions import ChatExpressions
from .models import canonical, scope_key
from .native_explicit_memory import _SENSITIVE, _FICTION
from .native_memory import NativeMemoryConflict
from .memory_context import NativeMemoryContextPolicy

SOURCE_NAMESPACE = 'tls.chat.message.source.v1'
CANDIDATE_NAMESPACE = 'tls.chat.message.candidate.v1'
IMPORTANT_SOURCE = 'tls.chat.message.important'
ASSOCIATION_LIMIT = 100


def _record_view(memory, scope, row):
    """Current stored revision, with fact-recall eligibility kept separate from storage."""
    metadata = row.get('metadata') or {}
    selected, reason = NativeMemoryContextPolicy._candidate(row, scope, memory.clock())
    kind = row['evidence_kind']
    return dict(id=row['id'], content=row['content'], revision=row['revision'],
        source_id=row['source_id'], evidence_kind=kind, memory_type=row['memory_type'],
        reality_level=row.get('reality_level'), review_status=row.get('review_status'),
        lifecycle=row.get('lifecycle'), created_at=row.get('created_at'), updated_at=row.get('updated_at'),
        source='app_native_memory', editable=row.get('lifecycle') != 'deleted',
        original_text=metadata.get('original_text'), saved_role=metadata.get('saved_role'),
        explicitly_saved=row['source_id'] == IMPORTANT_SOURCE,
        retention=('explicit_long_term' if row['source_id'] == IMPORTANT_SOURCE else
                   'conversation_utterance' if row['memory_type'] == 'utterance' else 'native_record'),
        real_recall_eligible=selected is not None, real_recall_reason=reason or None,
        retrieval_lane=('roleplay' if kind == 'roleplay_event' else
                        'inference' if kind == 'model_inference' else 'real'),
        corrected=bool(isinstance(metadata.get('original_text'), str)
            and metadata['original_text'].strip() != row['content']))


def _require_current(current):
    if current() is not True:
        raise PermissionError('current owned message-memory authority required')


def _content_kind(source, text):
    return ('roleplay_event' if source['mode'] == 'roleplay' or _FICTION.search(text)
            else 'model_inference' if source['role'] == 'assistant' else 'user_reported')


def _validate_text(text):
    if (type(text) is not str or not text.strip() or len(text) > 6000
            or any(ord(char) < 32 and char not in '\t\r\n' for char in text)
            or any(rule.search(text) for rule in _SENSITIVE)):
        raise ValueError('message has no safe bounded text to save')
    # The original evidence also resides in NativeMemoryStore's bounded
    # metadata. Admit a candidate only when that unchanged text can fit there.
    if len(text.encode('utf8')) > 12000:
        raise ValueError('message source exceeds native memory evidence size')


def _candidate_key(message_id):
    return hashlib.sha256(str(message_id).encode()).hexdigest()


def _important_occurrence(scope, source):
    return hashlib.sha256(canonical([scope, source['message_id'], source['role']]).encode()).hexdigest()


def _public_candidate(record):
    if record is None:
        return None
    return dict({key: record['data'].get(key) for key in ('message_id', 'original_text', 'source',
        'evidence_kind', 'status', 'memory_id', 'created_at')},
        revision=record['revision'], updated_at=record['updated_at'],
        last_operation=({key: record['data']['operations'][-1][key] for key in ('request_id', 'action')}
                        if record['data'].get('operations') else None),
        source_kind='saved_message_pending_candidate', recall_eligible=False)


def message_candidate(journal, username, session_id, message_id, *, current):
    with journal._lock:
        _require_current(current)
        record = journal.fetch(CANDIDATE_NAMESPACE, _candidate_key(message_id),
            ChatExpressions.message_scope(username, session_id))
        _require_current(current)
        return _public_candidate(record)


def operate_candidate(journal, username, session_id, memory, native_scope, source, text, *,
                      action, request_id, expected_revision, confirm=False, current):
    """Pending preview in existing checkpoints; explicit confirmation writes memory.

    Candidate checkpoints are never consumed by context/recall or a classifier.
    Request receipts make exact repeats read-only, even with an older revision.
    Native-memory and Journal commits retain their own original authorities;
    an ambiguous outcome is reconciled by GET against both durable sources.
    """
    if action not in {'propose', 'confirm', 'reject'}:
        raise ValueError('invalid candidate action')
    if (type(request_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', request_id)
            or type(expected_revision) is not int or expected_revision < 0
            or type(confirm) is not bool or action == 'confirm' and confirm is not True
            or action != 'confirm' and confirm is not False):
        raise ValueError('stable request ID, exact revision and explicit confirmation required')
    _validate_text(text)
    key, scope = _candidate_key(source['message_id']), ChatExpressions.message_scope(username, session_id)
    fingerprint = hashlib.sha256(canonical([action, expected_revision, confirm, source, text]).encode()).hexdigest()
    # Use the Journal's existing lock across this one user's read/check/write.
    # put() retains its own transaction and before/after authority checks.
    with journal._lock:
        _require_current(current)
        previous = journal.fetch(CANDIDATE_NAMESPACE, key, scope)
        old = previous['data'] if previous else None
        for operation in old.get('operations', []) if old else []:
            if operation['request_id'] == request_id:
                if operation['fingerprint'] != fingerprint:
                    raise NativeMemoryConflict('candidate request reused with changed input')
                _require_current(current)
                return _public_candidate(previous)
        revision = previous['revision'] if previous else 0
        if revision != expected_revision:
            raise NativeMemoryConflict('candidate revision changed')
        if old and (old['original_text'] != text or old['source'] != source):
            raise NativeMemoryConflict('saved source changed since candidate proposal')
        if old and len(old.get('operations', [])) >= 32:
            raise ValueError('candidate operation capacity reached')
        if action == 'propose':
            if old and old['status'] in {'pending', 'confirmed'}:
                _require_current(current)
                return _public_candidate(previous)
            value = dict(message_id=source['message_id'], original_text=text, source=source,
                evidence_kind=_content_kind(source, text), status='pending', memory_id=None,
                created_at=old['created_at'] if old else journal.clock(),
                operations=list(old.get('operations', [])) if old else [])
        else:
            if old is None or old['status'] != 'pending':
                raise ValueError('a current pending candidate is required')
            value = dict(old, operations=list(old.get('operations', [])))
            if action == 'reject':
                # Native confirmation can commit before its Journal receipt.
                # Keep that real record authoritative, including corrections
                # and deletion history; rejecting a checkpoint never undoes it.
                with memory.store._lock:
                    _require_current(current)
                    committed = memory.store.get(native_scope,
                        'important_' + _important_occurrence(native_scope, old['source']), include_deleted=True)
                    _require_current(current)
                    if committed is not None:
                        raise NativeMemoryConflict('important memory already persisted; reconcile confirmation')
                value['status'] = 'rejected'
            else:
                # The original candidate evidence is used unchanged. There is
                # no promotion of a native profile candidate or other source.
                saved = save_important(memory, native_scope, old['source'], old['original_text'], current=current)
                value.update(status='confirmed', memory_id=saved['id'])
        value['operations'].append(dict(request_id=request_id, action=action, fingerprint=fingerprint))
        _require_current(current)
        stored = journal.put(CANDIDATE_NAMESPACE, key, scope, value,
            expected_revision=revision, authorize=lambda: current() is True)
        _require_current(current)
        return _public_candidate(stored)


def _source_key(checkpoint):
    if type(checkpoint) is not str:
        return None
    try:
        return uuid.UUID(checkpoint).hex
    except (ValueError, AttributeError):
        return None


def bind_event_source(journal, username, session_id, payload, *, mode, current):
    key = _source_key(payload.get('llm_checkpoint_id'))
    identity = payload.get('message_id')
    if (key is None or type(identity) is not str or not 0 < len(identity) <= 256
            or any(ord(char) < 32 for char in identity)):
        return
    _require_current(current)
    scope = ChatExpressions.message_scope(username, session_id)
    previous = journal.fetch(SOURCE_NAMESPACE, key, scope)
    if previous:
        if previous['data'].get('message_id') != identity:
            raise NativeMemoryConflict('SDK checkpoint source changed')
        return  # A mode change never reclassifies the original occurrence.
    journal.put(SOURCE_NAMESPACE, key, scope,
        dict(message_id=identity, checkpoint_id=payload['llm_checkpoint_id'], mode=mode,
             source='actual_sdk_webchat_payload'), expected_revision=0, authorize=current)


def source_for_saved(journal, expressions, username, session_id, saved):
    """Only an actual owned SDK record supplied by the authenticated handler."""
    content = saved.content
    role = 'user' if content.get('type') == 'user' else 'assistant'
    identity = str(saved.id)
    scope = ChatExpressions.message_scope(username, session_id)
    checkpoint = getattr(saved, 'llm_checkpoint_id', None)
    key = _source_key(checkpoint)
    link = journal.fetch(SOURCE_NAMESPACE, key, scope) if key else None
    source = link['data'] if link else {}
    mode = source.get('mode')
    submission = expressions.checkpoint_submission(scope, checkpoint) if checkpoint else None
    if mode is None and submission:
        mode = (submission.get('expression_context') or {}).get('mode')
    ids = {identity}
    # Bot and user can share a checkpoint, but this UUID denotes the incoming
    # user occurrence. Never attribute its captured/profile facts to the bot.
    if role == 'user' and source.get('source') == 'actual_sdk_webchat_payload':
        ids.add(source['message_id'])
    return dict(message_id=identity, role=role, source_message_ids=sorted(ids),
                source_linked=bool(link), mode=mode or 'unknown')


def _associated(metadata, identities):
    if not isinstance(metadata, dict):
        return False
    for field in ('message_id', 'source_message_id', 'saved_message_id'):
        if type(metadata.get(field)) in (str, int) and str(metadata[field]) in identities:
            return True
    values = metadata.get('source_message_ids')
    return isinstance(values, list) and any(type(value) in (str, int) and str(value) in identities for value in values)


def associated_memory(memory, scope, source, *, current):
    """Exact-ID associations; filter in SQLite before decoding bounded result rows.

    This still examines scoped metadata in SQLite (there is no new index/schema),
    but no longer materializes the whole scope or reads every candidate's evidence.
    The extra sentinel row distinguishes exactly 100 matches from truncation.
    """
    store, identities = memory.store, tuple(sorted(set(source['source_message_ids'])))
    if not identities or len(identities) > 8 or any(type(value) is not str or len(value) > 256 for value in identities):
        raise ValueError('bounded saved-message identities required')
    records, candidates = [], []
    with store._lock:
        store._check_open()
        _require_current(current)
        key = scope_key(scope)
        marks = ','.join('?' for _ in identities)
        direct = ' OR '.join(
            "(json_type(data,'$.metadata." + field + "') IN ('text','integer') AND "
            "CAST(json_extract(data,'$.metadata." + field + "') AS TEXT) IN (" + marks + '))'
            for field in ('message_id', 'source_message_id', 'saved_message_id'))
        array = ("(json_type(data,'$.metadata.source_message_ids')='array' AND EXISTS "
            "(SELECT 1 FROM json_each(data,'$.metadata.source_message_ids') j "
            "WHERE j.type IN ('text','integer') AND CAST(j.value AS TEXT) IN (" + marks + ')))')
        encoded = store._db.execute('SELECT data FROM tls_native_memories WHERE scope=? AND (' +
            direct + ' OR ' + array + ') ORDER BY occurred DESC,id LIMIT ?',
            (key, *identities, *identities, *identities, *identities, ASSOCIATION_LIMIT + 1)).fetchall()
        records_limited = len(encoded) > ASSOCIATION_LIMIT
        for raw in encoded[:ASSOCIATION_LIMIT]:
            row = json.loads(raw[0])
            records.append(_record_view(memory, scope, row))
        # The canonical explicitly-saved row must remain visible even when
        # newer automatically captured associations fill the result page.
        important = store.get(scope, 'important_' + _important_occurrence(scope, source), include_deleted=True)
        if (important is not None and important['source_id'] == IMPORTANT_SOURCE
                and _associated(important.get('metadata'), identities)
                and not any(row['id'] == important['id'] for row in records)):
            records.insert(0, _record_view(memory, scope, important))
            if len(records) > ASSOCIATION_LIMIT:
                records.pop()
                records_limited = True
        profiles = memory.profile_candidates
        candidates_limited = False
        if profiles is not None:
            if profiles.store is not store or profiles.active is not True:
                raise PermissionError('native profile source changed')
            encoded = store._db.execute('''SELECT c.data FROM tls_native_profile_candidates c
                JOIN (SELECT DISTINCT id FROM tls_native_profile_evidence WHERE scope=? AND message_id IN ('''
                + marks + ''')) e ON e.id=c.id WHERE c.scope=?
                ORDER BY c.updated DESC,c.id LIMIT ?''', (key, *identities, key, ASSOCIATION_LIMIT + 1)).fetchall()
            candidates_limited = len(encoded) > ASSOCIATION_LIMIT
            for raw in encoded[:ASSOCIATION_LIMIT]:
                row = json.loads(raw[0])
                matched = store._db.execute('SELECT DISTINCT source_text FROM tls_native_profile_evidence '
                    'WHERE scope=? AND id=? AND message_id IN (' + marks + ') ORDER BY rowid',
                    (key, row['id'], *identities)).fetchall()
                candidates.append(dict(id=row['id'], content=row['content'], revision=row['revision'],
                    source_id=row['source_id'], status=row['status'], review_status=row['review_status'],
                    source='native_profile_candidates', editable=False,
                    source_texts=[part[0] for part in matched], evidence_kind='user_reported',
                    recall_eligible=row['status'] == 'active',
                    recall_note='active_profile_policy_still_applies' if row['status'] == 'active' else 'not_active'))
        _require_current(current)
    important = next((row for row in records if row['explicitly_saved']), None)
    return dict(records=records, candidates=candidates, important_saved=bool(important),
        important_state=important['lifecycle'] if important else 'not_saved',
        association='exact_saved_or_sdk_source_id', limited=records_limited or candidates_limited,
        limits=dict(records=ASSOCIATION_LIMIT, candidates=ASSOCIATION_LIMIT,
                    records_limited=records_limited, candidates_limited=candidates_limited),
        state='associated' if records or candidates else 'no_exact_association',
        bookmark_is_memory=False)


def search_related_memory(memory, scope, query, *, include_roleplay=False, current):
    """Read the existing lexical index; related is never exact message provenance.

    Only the current proven full APP scope is accepted here. The HTTP handler
    may separately project the existing explicitly bound QQ read source; it
    must not enumerate other users/sessions or merge fiction into fact recall.
    """
    if (type(query) is not str or not 1 <= len(query.strip()) <= 200
            or any(ord(char) < 32 for char in query) or type(include_roleplay) is not bool):
        raise ValueError('bounded memory query and explicit roleplay flag required')
    query = query.strip()
    store = memory.store
    with store._lock:
        store._check_open()
        _require_current(current)
        kinds = ('user_reported', 'real_observation') + (('roleplay_event',) if include_roleplay else ())
        rows = store.search(scope, query, limit=32, evidence_kinds=kinds)
        profiles = memory.profile_candidates
        if profiles is not None:
            if profiles.store is not store or profiles.active is not True:
                raise PermissionError('native profile source changed')
            dimensions = profiles.active_single_dimensions(scope)
            rows = [row for row in rows if not (row.get('memory_type') in
                {'user_profile', 'user_preference', 'user_habit'}
                and row.get('source_id') != 'tls.chat.profile_candidates'
                and (row.get('metadata') or {}).get('profile_dimension') in dimensions)]
            rows = profiles.search(scope, query, limit=16) + rows
        result, seen = [], set()
        for row in sorted(rows, key=lambda item: item.get('score', 0), reverse=True):
            if row['id'] in seen:
                continue
            selected, _ = NativeMemoryContextPolicy._candidate(row, scope, memory.clock())
            roleplay = row['evidence_kind'] == 'roleplay_event' and include_roleplay
            if selected is None and not roleplay:
                continue
            value = _record_view(memory, scope, row)
            value['association'] = 'lexical_related_not_message_provenance'
            # Native profiles are reviewed through the existing candidate
            # workflow, not the ordinary memory correction endpoint.
            if row['source_id'] == 'tls.chat.profile_candidates':
                value.update(source='native_profile_candidates', editable=False)
            result.append(value)
            seen.add(row['id'])
        _require_current(current)
        return dict(records=result[:24], limited=len(result) > 24, limit=24,
            query=query, include_roleplay=include_roleplay, read_only=True,
            association='lexical_related_not_message_provenance',
            scope='current_proven_app', writes=0, model_calls=0)


def save_important(memory, scope, source, text, *, current):
    """Explicit user action, replay-safe write through existing native memory.

    Saving assistant words retains model inference; RP retains fiction. This
    operation never reviews or promotes an unrelated profile candidate.
    """
    _validate_text(text)
    role, mode = source['role'], source['mode']
    kind = _content_kind(source, text)
    occurrence = _important_occurrence(scope, source)
    with memory.store.transaction():
        _require_current(current)
        row = memory.store.write(scope, text, source_id=IMPORTANT_SOURCE,
            evidence_kind=kind, memory_type='explicit_memory', event_id='important.' + occurrence,
            record_id='important_' + occurrence, canonical_key='chat-message:' + occurrence,
            confidence=1. if role == 'user' else .5, importance=.8,
            metadata=dict(capture='explicit_saved_message', saved_message_id=source['message_id'],
                source_message_ids=source['source_message_ids'], original_text=text,
                saved_role=role, source_mode=mode, explicit_user_action=True,
                inference_is_fact=False, creates_send_permission=False))
        _require_current(current)  # Revocation rolls back before COMMIT.
    return row
