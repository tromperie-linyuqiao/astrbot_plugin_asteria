"""Opt-in scoped note completion on the existing reminder ACK outbox.

This is a trusted backend contract, not an adapter for legacy delete-by-ID.
The backend must own every writer to its notes, atomically compare immutable
identity/revision/linkage, retain the source record and persist an idempotent
receipt in that same transaction. No production backend is registered here.
Unknown outcomes are reconciled by receipt lookup, never a second mutation.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from typing import Protocol

from .delivery_store import DeliveryConflict, _identity
from .models import canonical, private_scope, scope_key

NAMESPACE = 'tls.note_completion.binding'
_HASH = re.compile(r'^[0-9a-f]{64}$')
_SNAPSHOT_KEYS = frozenset({'note_id', 'entity_id', 'revision', 'content_hash',
    'occurrence_id', 'occurrence_revision', 'scope', 'node'})
REQUIRED_CAPABILITIES = frozenset({'atomic_compare_complete', 'durable_receipts',
    'single_note_authority', 'scoped_immutable_identity', 'retained_source_record'})


def request_hash(request):
    return hashlib.sha256(canonical(request).encode()).hexdigest()


class NoteCompletionBackend(Protocol):
    """Trusted implementation; capabilities are declarations, not attestation.

    Both methods are async. `authorize` is synchronous and must be checked in
    the backend's transaction immediately before committing/querying. Receipt
    lookup must never call compare_and_complete or mutate a source note. A
    cancelled request may have committed; its receipt must remain queryable.
    The caller closes backend resources separately after draining reminder work.
    """
    contract_version: int
    capabilities: frozenset[str]

    async def compare_and_complete(self, request: dict, *, authorize): ...
    async def lookup_completion(self, request: dict, *, authorize): ...


class SafeNoteCompletionPort:
    """Bind a reviewed source-note snapshot to one immutable completion.

    Uses the reminder journal's existing bounded CAS checkpoints and outbox;
    creates no task database, scheduler, writer discovery or default factory.
    Note IDs and reminder IDs alone never grant access. The snapshot and backend
    must come from a trusted operator/integration, never an untrusted LLM tool.
    """
    def __init__(self, service, backend: NoteCompletionBackend):
        if (type(getattr(backend, 'contract_version', None)) is not int
                or backend.contract_version != 1
                or not REQUIRED_CAPABILITIES.issubset(getattr(backend, 'capabilities', ()))
                or not inspect.iscoroutinefunction(getattr(backend, 'compare_and_complete', None))
                or not inspect.iscoroutinefunction(getattr(backend, 'lookup_completion', None))):
            raise ValueError('trusted atomic scoped note backend contract required')
        self.service, self.backend = service, backend

    def _outbox(self, db, scope, completion_id):
        _identity(completion_id, 'completion id')
        scope = private_scope(scope)
        if not self.service.active:
            raise PermissionError('reminder service stopped')
        row = db.execute('SELECT * FROM tls_reminder_completions WHERE id=?', (completion_id,)).fetchone()
        if not row:
            raise KeyError('completion absent')
        data = json.loads(row['data'])
        if data['scope'] != scope or not self.service._completion_valid(db, data):
            raise PermissionError('completion binding or authority changed')
        return row['state'], data

    def _snapshot(self, snapshot, data):
        if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_KEYS:
            raise ValueError('complete reviewed note snapshot required')
        value = json.loads(canonical(snapshot))
        value['scope'] = private_scope(value['scope'])
        for key in ('note_id', 'entity_id', 'node', 'occurrence_id'):
            _identity(value[key], key)
        for key in ('revision', 'occurrence_revision'):
            if type(value[key]) is not int or not 1 <= value[key] <= 2**53:
                raise ValueError('positive exact note/occurrence revision required')
        if not isinstance(value['content_hash'], str) or not _HASH.fullmatch(value['content_hash']):
            raise ValueError('reviewed note content hash required')
        if any(value[key] != data[target] for key, target in (
                ('scope', 'scope'), ('node', 'node'), ('note_id', 'note_id'),
                ('occurrence_id', 'occurrence_id'), ('occurrence_revision', 'revision'))):
            raise PermissionError('source note mapping mismatch')
        return value

    async def bind(self, scope, completion_id, snapshot):
        """Persist one reviewed mapping; a conflicting rebind is never allowed."""
        scope = private_scope(scope)
        def write():
            with self.service.journal._transaction() as db:
                state, data = self._outbox(db, scope, completion_id)
                target = self._snapshot(snapshot, data)
                request = dict(schema=1, action='complete_linked_note',
                    idempotency_key=completion_id, completion=data, target=target)
                old = self.service.journal.fetch(NAMESPACE, completion_id, scope)
                if old:
                    if old['data'] != request:
                        raise DeliveryConflict('immutable note completion mapping conflict')
                    return request_hash(request)
                if state != 'pending':
                    raise DeliveryConflict('only pending completion may receive a mapping')
                # Reuse the checkpoint capacity/CAS contract without a nested
                # transaction; all outbox/mapping checks stay under this lock.
                if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.service.journal.max_records:
                    raise RuntimeError('checkpoint capacity reached')
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                    (NAMESPACE, completion_id, scope_key(scope), 1,
                     self.service.clock(), canonical(request)))
                return request_hash(request)
        return await self.service._run(write)

    def _request(self, scope, completion_id):
        with self.service.journal._lock:
            state, data = self._outbox(self.service.journal._db, scope, completion_id)
            record = self.service.journal.fetch(NAMESPACE, completion_id, scope)
            if not record or record['revision'] != 1:
                raise DeliveryConflict('reviewed immutable note mapping missing')
            request = record['data']
            if (set(request) != {'schema', 'action', 'idempotency_key', 'completion', 'target'}
                    or type(request['schema']) is not int or request['schema'] != 1
                    or request['action'] != 'complete_linked_note'
                    or request['idempotency_key'] != completion_id or request['completion'] != data):
                raise DeliveryConflict('note completion mapping changed')
            self._snapshot(request['target'], data)
            return state, request

    def _authorized(self, request):
        try:
            _, current = self._request(request['completion']['scope'], request['idempotency_key'])
            return current == request
        except (PermissionError, ValueError, KeyError, DeliveryConflict, RuntimeError):
            return False

    @staticmethod
    def _receipt(request, result):
        target, data = request['target'], request['completion']
        expected = dict(schema=1, request_hash=request_hash(request),
            operation_key=request['idempotency_key'], state='completed',
            entity_id=target['entity_id'], note_id=target['note_id'],
            scope_hash=scope_key(data['scope']), node=data['node'],
            occurrence_id=data['occurrence_id'], occurrence_revision=data['revision'],
            prior_revision=target['revision'], completed_revision=target['revision'] + 1)
        # Strict types prevent True comparing equal to integer schema/revisions.
        if canonical(result) != canonical(expected):
            raise DeliveryConflict('external completion receipt does not prove exact source mutation')
        return expected

    async def __call__(self, data):
        """Existing ReminderService port hook; errors/cancellation propagate."""
        state, request = self._request(data.get('scope'), data.get('idempotency_key'))
        expected_data = dict(request['completion'], idempotency_key=request['idempotency_key'])
        if data != expected_data or state != 'unknown':
            raise DeliveryConflict('only claimed immutable outbox may execute a note action')
        result = await self.backend.compare_and_complete(request, authorize=lambda: self._authorized(request))
        proof = self._receipt(request, result)
        # The legacy generic hook's strict-True ACK is deliberately NOT our
        # permission boundary: perform the scoped proof CAS ourselves first.
        # Its subsequent unknown->confirmed update then has no rows to alter.
        return await self._acknowledge(data['scope'], request['idempotency_key'], request, proof)

    async def complete(self, scope, completion_id):
        """Pending -> existing action hook; unknown/confirmed -> lookup only."""
        scope = private_scope(scope)
        state, _ = self._request(scope, completion_id)
        if state in {'unknown', 'confirmed'}:
            return await self.reconcile(scope, completion_id)
        if state != 'pending':
            raise DeliveryConflict('unsupported completion state')
        return await self.service.complete_linked_note(scope, completion_id, self)

    async def reconcile(self, scope, completion_id):
        """Read the SAME durable external receipt; never repeat a mutation."""
        if not self.service.active:
            raise PermissionError('reminder service stopped')
        current = asyncio.current_task()
        self.service._completion_tasks.add(current)
        try:
            return await self._reconcile(scope, completion_id)
        finally:
            self.service._completion_tasks.discard(current)

    async def _reconcile(self, scope, completion_id):
        scope = private_scope(scope)
        state, request = self._request(scope, completion_id)
        if state not in {'unknown', 'confirmed'}:
            raise DeliveryConflict('only attempted completion can be reconciled')
        result = await asyncio.wait_for(
            self.backend.lookup_completion(request, authorize=lambda: self._authorized(request)),
            self.service.policy.timeout_seconds)
        if result is None:
            return False
        proof = self._receipt(request, result)
        return await self._acknowledge(scope, completion_id, request, proof)

    async def _acknowledge(self, scope, completion_id, request, proof):
        def acknowledge():
            with self.service.journal._transaction() as db:
                current_state, current = self._request(scope, completion_id)
                if current != request or current_state not in {'unknown', 'confirmed'}:
                    raise DeliveryConflict('local completion changed before reconciliation')
                # Strict matching proof remains an input, not permission to
                # override a revoked consent, owner generation or scope.
                self._receipt(current, proof)
                if current_state == 'unknown':
                    changed = db.execute("UPDATE tls_reminder_completions SET state='confirmed' WHERE id=? AND state='unknown' AND data=?",
                        (completion_id, canonical(request['completion']))).rowcount
                    if changed != 1:
                        raise DeliveryConflict('local outbox acknowledgement raced')
                return True
        return await self.service._run(acknowledge)
