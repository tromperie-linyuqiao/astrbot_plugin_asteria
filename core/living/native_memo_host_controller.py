"""Host lifecycle and explicit administrator intent for native memo tools.

Arm persists intent only. Only a currently authorized genuine scope observed by
the Host can prepare/activate ownership. No session, lease, Presence, worker or
old-plugin permission is created by this controller or its management API.
"""
from __future__ import annotations

import hashlib
import json
import re

from .journal import JournalConflict, LivingJournal
from .models import canonical, scope_key
from .native_memo_notes import NativeMemoNotes
from .native_memo_tool_ownership import NativeMemoToolOwnership, _scope, _hash
from .native_memo_pc_router import NativeMemoPCRouter
from .native_memo_runtime_bridge import NativeMemoRuntimeBridge

INTENTS = 'tls.native.memo_tools.intent.v1'


class NativeMemoHostController:
    protocol = NativeMemoPCRouter.protocol

    def __init__(self, plugin, host):
        self.plugin, self.host = plugin, host
        self.context = plugin.context
        self.active = True
        self.bridge = self.router = self._child_resources = None
        self._last_error = None
        self._ensure_child()

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        runtime = getattr(self.host, 'runtime', None)
        notes = getattr(runtime, 'memo_notes', None)
        journal = getattr(self.host, 'journal', None)
        installed = getattr(self.plugin, '_native_memo_tool_router', self)
        if (not self.active or installed is not self or getattr(presence, 'living_host', None) is not self.host
                or getattr(self.plugin, '_stopping', False) or getattr(self.host, '_closed', True)
                or getattr(self.host, 'context', None) is not self.context
                or getattr(runtime, 'active', False) is not True or type(notes) is not NativeMemoNotes
                or notes.active is not True or not isinstance(journal, LivingJournal)
                or notes.journal is not journal or getattr(runtime, 'journal', None) is not journal
                or journal._closed is not False):
            raise RuntimeError('current memo host resources unavailable')
        return self.host, runtime, notes, journal

    def _same(self, resources):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise RuntimeError('memo host resources changed')

    def _stop_child(self):
        if self.router is not None: self.router.stop()
        if self.bridge is not None: self.bridge.stop()
        self.router = self.bridge = self._child_resources = None

    def _ensure_child(self):
        try:
            resources = self._resources()
            if (self.router is not None and self.router.active and self.bridge is not None
                    and self.bridge.source_current() is True
                    and all(old is new for old, new in zip(self._child_resources, resources))):
                return True
            self._stop_child()
            bridge = NativeMemoRuntimeBridge(self.context, self.plugin)
            try:
                bridge.bind()
                router = NativeMemoPCRouter(resources[2], scope_for_event=self._scope_event,
                    authorize_scope=self._live_allowed, source_current=self._source_current,
                    lease_current=self._live_allowed, old_drained=bridge.old_drained,
                    pc_current=bridge.pc_current, binding_sha256=bridge.binding_sha256,
                    native_identity=bridge.native_identity_domain,legacy_origin=bridge.legacy_origin)
            except BaseException:
                bridge.stop()
                raise
            self.bridge, self.router, self._child_resources = bridge, router, resources
            self._last_error = None
            return True
        except Exception:
            self._last_error = 'memo_runtime_binding_unavailable'
            self._stop_child()
            return False

    def _read_intent(self, db, scope):
        row = db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                         (INTENTS, 'intent', scope_key(scope))).fetchone()
        if row is None: return None
        value = json.loads(row['data'])
        if (type(value) is not dict or set(value) != {'schema','scope','binding_sha256','request_id','enabled'}
                or type(value['schema']) is not int or value['schema'] != 1 or value['scope'] != scope
                or type(value['enabled']) is not bool or type(row['revision']) is not int or row['revision'] < 1
                or type(value['request_id']) is not str or re.fullmatch('[A-Za-z0-9_.:-]{1,128}', value['request_id']) is None):
            raise RuntimeError('invalid persistent memo tool intent')
        if value['binding_sha256'] is not None: _hash(value['binding_sha256'])
        elif value['enabled']: raise RuntimeError('enabled memo intent requires exact binding')
        return dict(value, revision=row['revision'])

    def _write_intent(self, db, scope, value, revision):
        if (db.execute('SELECT 1 FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                (INTENTS, 'intent', scope_key(scope))).fetchone() is None
                and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.host.journal.max_records):
            raise RuntimeError('memo intent capacity reached')
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
            (INTENTS, 'intent', scope_key(scope), revision, self.host.journal.clock(), canonical(value)))
        return dict(value, revision=revision)

    def _live_allowed(self, scope):
        try:
            resources = self._resources()
            if (self.router is None or self.bridge is None or self._child_resources is None
                    or any(old is not new for old, new in zip(resources, self._child_resources))
                    or self.host._native_memory_allowed(scope) is not True): return False
            with resources[3]._lock:
                intent = self._read_intent(resources[3]._db, _scope(scope))
            return (intent is not None and intent['enabled'] is True
                    and intent['binding_sha256'] == self.bridge.binding_sha256)
        except Exception:
            return False

    def _source_current(self, scope, binding):
        try:
            self._resources()
            return (self.bridge is not None and self.bridge.source_current() is True
                    and (binding is None or binding == self.bridge.binding_sha256))
        except Exception:
            return False

    def _scope_event(self, event):
        self._resources()
        if self.bridge is None or self.bridge.native_identity_domain(event) is not True:
            raise PermissionError('genuine native identity domain required')
        return self.host.presence.scope_for_event(event)

    @staticmethod
    def _intent_args(expected_revision, request_id):
        if type(expected_revision) is not int or not 0 <= expected_revision < 2**53:
            raise ValueError('exact memo intent revision required')
        if type(request_id) is not str or re.fullmatch('[A-Za-z0-9_.:-]{1,128}', request_id) is None:
            raise ValueError('stable bounded memo intent request required')

    @staticmethod
    def _operation_allowed(authorize_operation, scope):
        if not callable(authorize_operation) or authorize_operation(dict(scope)) is not True:
            raise PermissionError('current administrator memo operation required')

    def arm(self, scope, *, expected_revision, request_id, binding_sha256, authorize_operation):
        scope = _scope(scope); self._intent_args(expected_revision, request_id); _hash(binding_sha256)
        resources = self._resources()
        value = dict(schema=1, scope=scope, binding_sha256=binding_sha256, request_id=request_id, enabled=True)
        with resources[3]._transaction() as db:
            self._same(resources); self._operation_allowed(authorize_operation, scope)
            old = self._read_intent(db, scope)
            if old is not None and old['request_id'] == request_id:
                if {key: item for key, item in old.items() if key != 'revision'} != value:
                    raise JournalConflict('memo intent request reused with different content')
                result = old
            else:
                if (old['revision'] if old else 0) != expected_revision:
                    raise JournalConflict('memo intent revision changed')
                result = self._write_intent(db, scope, value, expected_revision + 1)
            self._same(resources); self._operation_allowed(authorize_operation, scope)
        return dict(intent=result, owner_changed=False, awaits_genuine_observation=True,
                    creates_private_scope=False, grants_runtime_authority=False)

    def close(self, scope, *, expected_revision, request_id, authorize_operation):
        """Cancel arm and close owner atomically, with close-only admin authority."""
        scope = _scope(scope); self._intent_args(expected_revision, request_id)
        resources = self._resources()
        def allowed(candidate):
            self._same(resources)
            self._operation_allowed(authorize_operation, scope)
            return candidate == scope
        view = NativeMemoToolOwnership(resources[3], authorize_scope=allowed,
            source_current=lambda *_: False, lease_current=lambda *_: False, drained=lambda *_: False)
        try:
            with resources[3]._transaction() as db:
                allowed(scope)
                old = self._read_intent(db, scope)
                owner = view._read_owner(db, scope)
                if old is not None and old['request_id'] == request_id:
                    if old['enabled'] is not False: raise JournalConflict('memo intent request conflict')
                    result = old
                else:
                    if (old['revision'] if old else 0) != expected_revision:
                        raise JournalConflict('memo intent revision changed')
                    binding = old['binding_sha256'] if old else owner['binding_sha256'] if owner else None
                    result = self._write_intent(db, scope, dict(schema=1, scope=scope,
                        binding_sha256=binding, request_id=request_id, enabled=False), expected_revision + 1)
                if owner is not None and owner['state'] != 'closed':
                    generation = owner['generation'] + 1
                    if generation >= 2**53: raise ValueError('memo owner generation exhausted')
                    owner = dict(owner, state='closed', generation=generation)
                    view._write(db, 'tls.native.memo_tool.owners.v1', 'owner', scope, owner, generation)
                    view._audit(db, scope, 'closed', generation, owner['transition_id'])
                allowed(scope)
            return dict(intent=result, owner=owner, creates_private_scope=False,
                        grants_runtime_authority=False, restores_legacy_permission=False)
        finally:
            view.stop()

    def status(self, scope, *, authorize_operation):
        scope = _scope(scope); resources = self._resources()
        self._operation_allowed(authorize_operation, scope)
        view = NativeMemoToolOwnership(resources[3], authorize_scope=lambda s: s == scope,
            source_current=lambda *_: False, lease_current=lambda *_: False, drained=lambda *_: False)
        try:
            with resources[3]._lock:
                intent = self._read_intent(resources[3]._db, scope)
                stored = view.inspect(scope)
            genuine = self.host._native_memory_allowed(scope) is True
            source = self._source_current(scope, stored.get('binding_sha256'))
            effective = dict(mode='closed', generation=stored['generation'])
            if self.router is not None and self._live_allowed(scope):
                effective = self.router.ownership.owner_for_scope(scope)
            self._same(resources); self._operation_allowed(authorize_operation, scope)
            return dict(intent=intent, persistent_owner=stored, effective_owner=effective,
                binding_sha256=self.bridge.binding_sha256 if self.bridge is not None else None,
                actual_private_lease=genuine, source_current=source, child_available=self.router is not None,
                last_error=self._last_error, creates_private_scope=False, grants_runtime_authority=False,
                snapshot_atomic=False)
        finally:
            view.stop()

    def observe(self, scope):
        """Only called after Host's genuine session authorization; no lease writes."""
        try:
            scope = _scope(scope)
            if self.host._native_memory_allowed(scope) is not True or not self._ensure_child():
                return dict(state='awaiting_genuine_scope_or_runtime')
            resources = self._resources()
            with resources[3]._lock:
                intent = self._read_intent(resources[3]._db, scope)
                if (intent is None or intent['enabled'] is not True
                        or intent['binding_sha256'] != self.bridge.binding_sha256):
                    return dict(state='not_armed_or_binding_changed')
                transition = hashlib.sha256(canonical(['memo_tool_arm', scope, intent['request_id'], intent['revision'], intent['binding_sha256']]).encode()).hexdigest()
                owner = self.router.ownership.inspect(scope)
                if owner.get('state') == 'native' and owner.get('transition_id') == transition:
                    return dict(state='native', generation=owner['generation'])
                if owner['state'] in {'native', 'pending', 'legacy'} and owner.get('generation', 0) > 0 and owner.get('transition_id') != transition:
                    owner = self.router.close(scope, expected_generation=owner['generation'], transition_id=owner['transition_id'])
                if owner['state'] != 'pending':
                    owner = self.router.prepare(scope, expected_generation=owner['generation'], transition_id=transition)
                if self.bridge.old_drained(scope) is not True:
                    return dict(state='awaiting_old_drain', generation=owner['generation'])
                owner = self.router.activate(scope, expected_generation=owner['generation'], transition_id=transition)
                return dict(state='native', generation=owner['generation'])
        except (PermissionError, JournalConflict):
            return dict(state='waiting_for_current_authority')
        except Exception:
            return dict(state='runtime_unavailable')

    def ready_for_event(self, event):
        try:
            if (getattr(event, 'private_companion_proactive_framework', False)
                    or getattr(event, 'private_companion_internal_generation', False)):
                return False
            scope = self.router.tools._scope(event) if self.router is not None else None
            return (scope is not None and self._live_allowed(scope) and self.bridge.source_current() is True
                    and self.router.ownership.owner_for_scope(scope)['mode'] == 'native')
        except Exception:
            return False

    async def dispatch(self, pc, event, payload, legacy_callable):
        if not self._ensure_child() or self.bridge.pc_current(pc) is not True:
            return NativeMemoPCRouter._denied('memo_controller_runtime_unavailable')
        try:
            if self.bridge.native_identity_domain(event) is True:
                scope = self.host.presence.scope_for_event(event)
                if self.host._native_memory_allowed(scope) is True: self.observe(scope)
        except Exception:
            pass
        return await self.router.dispatch(pc, event, payload, legacy_callable)

    async def native_call(self, event, payload):
        async def disabled_legacy(_event, **_payload):
            return json.dumps(dict(status='disabled', saved=False, action=_payload.get('action', ''),
                code='original_pc_memo_business_retained', original_legacy_executed=False,
                message='旧 ID、提醒和周期仍由原便签功能处理。'), ensure_ascii=False)
        if not self._ensure_child():
            return NativeMemoPCRouter._denied('memo_controller_runtime_unavailable')
        return await self.dispatch(self.bridge.pc, event, payload, disabled_legacy)

    def stop(self):
        self.active = False
        self._stop_child()
