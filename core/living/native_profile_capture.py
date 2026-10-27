"""Capture one genuine selected classifier batch into the shared candidates.

This has no extractor, model, scheduler, new database or historical mapping.
The fence supplies complete actual dataclass snapshots and a current sealed
batch gate. Root supplies the independent profile-write flag/full scope there.
"""
from __future__ import annotations

import hashlib
import inspect

from .models import canonical, plain, private_scope
from .native_explicit_memory import _event_snapshot, _SENSITIVE
from .native_memory_adapter import NativeMemoryAdapter


class NativeProfileCapture:
    def __init__(self, adapter, candidates, *, branch_gate=None):
        from .native_profile_candidates import NativeProfileCandidates
        if (type(adapter) is not NativeMemoryAdapter or type(candidates) is not NativeProfileCandidates
                or candidates.store is not adapter.store
                or branch_gate is not None and (not callable(branch_gate)
                    or inspect.iscoroutinefunction(branch_gate))):
            raise ValueError('shared native candidate store and synchronous batch gate required')
        self.adapter, self.candidates, self.store = adapter, candidates, adapter.store
        self.branch_gate = branch_gate if branch_gate is not None else lambda event, scope, records: False
        self.active = True
        self.generation = 1

    def _allowed(self, event, scope, records, snapshot, generation):
        if (not self.active or self.generation != generation or self.adapter.store is not self.store
                or self.candidates.store is not self.store or self.candidates.active is not True or self.store._closed
                or not self.adapter.allowed(scope) or _event_snapshot(event, scope) != snapshot):
            return False
        value = self.branch_gate(event, dict(scope), records)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            return False
        return (value is True and self.active and self.generation == generation
                and self.candidates.active is True and self.candidates.store is self.store
                and self.adapter.store is self.store and not self.store._closed
                and self.adapter.allowed(scope) and _event_snapshot(event, scope) == snapshot)

    async def capture_event(self, event, scope, records):
        scope = private_scope(scope)
        generation = self.generation
        try:
            snapshot = _event_snapshot(event, scope)
            frozen = plain(records, 65536)
            if (snapshot is None or type(frozen) is not list or not 1 <= len(frozen) <= 16
                    or any(type(row) is not dict or row.get('memory_type') not in
                           {'user_profile', 'user_preference', 'user_habit'}
                           or type(row.get('metadata')) is not dict
                           or not row['metadata'].get('profile_dimension') for row in frozen)
                    or any(pattern.search(snapshot[-1]) for pattern in _SENSITIVE)
                    or not self._allowed(event, scope, frozen, snapshot, generation)):
                return dict(ok=False, state='profile_branch_closed', creates_send_permission=False)
        except Exception:
            return dict(ok=False, state='profile_branch_closed', creates_send_permission=False)
        event_id = 'profile.' + hashlib.sha256(canonical([scope, snapshot[-2]]).encode('utf8')).hexdigest()
        digest = hashlib.sha256(canonical(frozen).encode('utf8')).hexdigest()

        def authorized():
            return (hashlib.sha256(canonical(frozen).encode('utf8')).hexdigest() == digest
                    and self._allowed(event, scope, frozen, snapshot, generation))

        def save(current_scope):
            if not authorized():
                raise PermissionError('profile branch changed before observe')
            return self.candidates.observe(current_scope, frozen, event_id=event_id,
                source_text=snapshot[-1], message_id=snapshot[-2], authorize=authorized)

        result = await self.adapter._operation(scope, save)
        if not authorized():
            raise PermissionError('profile branch changed after observe; reconcile original event')
        return result

    def stop(self):
        self.active = False
        self.generation += 1

    close = stop
