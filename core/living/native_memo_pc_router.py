"""Single-PC-entry router for the native nonreminder one-off memo slice.

No SDK registration and no PC mutation. A durable PC adapter must retain this
contract across TLS reloads and fail protected operations closed without it.
The integration proves exact current PC/source/session/lease and old drain.
"""
from __future__ import annotations

import json
import inspect
import re

from .native_memo_notes import NativeMemoNotes, NAMESPACE, RECEIPTS, BOUNDARY
from .native_memo_tool_ownership import NativeMemoToolOwnership, OWNERS, CLAIMS, _scope
from .native_memo_tools import NativeMemoTools, _ACTIONS, _eligible_create, occurrence
from .native_memo_legacy_origin import LegacyMemoOriginProof, SOURCE_SHA256
from .models import scope_key


class NativeMemoPCRouter:
    protocol = 'tls.native.memo_tool.pc_router.v1'

    def __init__(self, notes, *, scope_for_event, authorize_scope, source_current,
                 lease_current, old_drained, pc_current, binding_sha256, native_identity,
                 legacy_origin=None, timeout_seconds=5.):
        callbacks = (scope_for_event, authorize_scope, source_current, lease_current, old_drained, pc_current, native_identity)
        if (type(notes) is not NativeMemoNotes or any(not callable(cb) for cb in callbacks)
                or type(binding_sha256) is not str or re.fullmatch('[a-f0-9]{64}', binding_sha256) is None):
            raise ValueError('current native notes, synchronous proofs and fixed PC binding required')
        self.notes, self.journal, self.binding_sha256 = notes, notes.journal, binding_sha256
        self.scope_for_event, self.authorize_scope = scope_for_event, authorize_scope
        self.source_current, self.lease_current = source_current, lease_current
        self.old_drained, self.pc_current = old_drained, pc_current
        if legacy_origin is not None and not callable(legacy_origin): raise ValueError('typed legacy origin callback required')
        self.native_identity, self.legacy_origin = native_identity, legacy_origin
        self._bindings = (notes, notes.journal, notes.authorize, notes.clock, *callbacks, legacy_origin)
        self._legacy_inflight = self._native_inflight = 0
        self.active = True
        self.ownership = NativeMemoToolOwnership(self.journal, authorize_scope=self._authorize,
            source_current=self._source, lease_current=self._lease, drained=self._drained)
        self.tools = NativeMemoTools(notes, scope_for_event=self._scope_event,
            authorize_scope=self._authorize, owner_for_scope=self.ownership.owner_for_scope,
            current_service=self._current_service, native_identity=native_identity, timeout_seconds=timeout_seconds)

    @staticmethod
    def _proof(callback, *args):
        value = callback(*args)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value): value.close()
            return False
        return value is True

    def _resources(self):
        return (self.active and self.notes.active and all(a is b for a, b in zip(self._bindings,
            (self.notes, self.journal, self.notes.authorize, self.notes.clock, self.scope_for_event,
             self.authorize_scope, self.source_current, self.lease_current, self.old_drained, self.pc_current, self.native_identity, self.legacy_origin))))

    def _legacy_history_clear(self, domain):
        """Locked bounded read across characters, including orphan receipts.

        A scope is taken only from a validated stored row, never manufactured
        from the event. Any unknown/truncated/corrupt history blocks admission.
        """
        from .native_memo_legacy_origin import LegacyMemoIdentityDomain
        if type(domain) is not LegacyMemoIdentityDomain or not self._resources(): return False
        with self.journal._lock:
            self.journal._ensure_open()
            namespaces = (OWNERS, CLAIMS, NAMESPACE, RECEIPTS)
            # The aggregate CTE contains one metadata row. The join never
            # materializes note/receipt text when its total byte/row budget
            # is exceeded. Both budget and payload use one SQLite read
            # statement; this is not a transaction covering the old await.
            rows = self.journal._db.execute(
                'WITH budget AS (SELECT COUNT(*) AS row_count, '
                'COALESCE(SUM(length(CAST(data AS BLOB))),0) AS byte_count '
                'FROM checkpoints WHERE namespace IN (?,?,?,?)) '
                'SELECT budget.row_count,budget.byte_count,c.namespace,c.key,c.scope,c.revision,c.updated,c.data '
                'FROM budget LEFT JOIN checkpoints AS c ON '
                'budget.row_count<=10000 AND budget.byte_count<=? AND c.namespace IN (?,?,?,?) '
                'ORDER BY c.namespace,c.scope,c.key LIMIT 10001',
                (*namespaces, 8*1024**2, *namespaces)).fetchall()
            if not rows: return False
            count, byte_count = rows[0]['row_count'], rows[0]['byte_count']
            if (type(count) is not int or type(byte_count) is not int
                    or not 0 <= count <= 10000 or not 0 <= byte_count <= 8*1024**2): return False
            if count == 0:
                return len(rows) == 1 and rows[0]['data'] is None and self._resources()
            if len(rows) != count or any(row['data'] is None for row in rows): return False
            scopes = {}
            decoded = []
            try:
                for row in rows:
                    data = json.loads(row['data'])
                    if type(data) is not dict or type(row['revision']) is not int or row['revision'] < 1: return False
                    if row['namespace'] != RECEIPTS:
                        scope = _scope(data.get('scope'))
                        if row['scope'] != scope_key(scope): return False
                        if row['scope'] in scopes and scopes[row['scope']] != scope: return False
                        scopes[row['scope']] = scope
                        if row['namespace'] == OWNERS:
                            if row['key'] != 'owner' or self.ownership._read_owner(self.journal._db, scope) != data: return False
                        elif row['namespace'] == CLAIMS:
                            if self.ownership._claim(self.journal._db, scope, row['key']) != data: return False
                        else: self.notes._decode(row, scope)
                    decoded.append((row, data))
                for row, data in decoded:
                    scope = scopes.get(row['scope'])
                    if scope is None: return False
                    matches = all(scope[key] == value for key,value in (
                        ('platform',domain.platform_id),('bot_id',domain.bot_id),
                        ('user_id',domain.user_id),('session_id',domain.session_id)))
                    if row['namespace'] == RECEIPTS:
                        # Receipt payload has no full scope. Only a co-stored
                        # validated scope can bind it; historical/unknown forms
                        # remain blocking rather than being guessed away.
                        if (re.fullmatch('[a-f0-9]{64}',row['key']) is None or row['revision'] != 1
                                or type(data.get('signature')) is not str or re.fullmatch('[a-f0-9]{64}',data['signature']) is None
                                or any(data.get(key) is not flag for key,flag in BOUNDARY.items())):return False
                        action=data.get('action')
                        if action in {'complete','reopen','update_from_tool'}:
                            expected={'signature','record_id','action','revision'}|set(BOUNDARY)
                            if (set(data)-expected-{'expected_revision'} or not expected<=set(data)
                                    or type(data['record_id']) is not str or re.fullmatch(r'memo\.[a-f0-9]{64}',data['record_id']) is None
                                    or type(data['revision']) is not int or data['revision']<1
                                    or 'expected_revision' not in data or type(data['expected_revision']) is not int
                                    or data['expected_revision']<1):return False
                        elif action in {'import','rollback_import'}:
                            fields={'created_ids','existing_ids'} if action=='import' else {'archived_ids','deleted_ids'}
                            expected={'id','signature','action'}|fields|set(BOUNDARY)
                            if action=='rollback_import':expected.add('original_source_unchanged')
                            if set(data)!=expected or data['id']!=row['key']:return False
                            if action=='rollback_import' and data['original_source_unchanged'] is not True:return False
                            if any(type(data[key]) is not list or len(data[key])>200
                                    or any(type(item) is not str or re.fullmatch(r'memo\.[a-f0-9]{64}',item) is None for item in data[key])
                                    for key in fields):return False
                        else:return False
                        if matches: return False
                    elif matches and (row['namespace'] in {OWNERS,CLAIMS}
                            or data.get('provenance',{}).get('kind') == 'user_requested_ai_tool'): return False
                return self._resources()
            except Exception: return False

    def _internal_legacy_admit(self, pc, event):
        # Caller holds this same journal/admission lock until the full legacy
        # coroutine count has been incremented. Proof itself grants no permit.
        if self.legacy_origin is None or not self._resources() or not self._pc(pc): return False
        proof = self.legacy_origin(event, native_history_clear=self._legacy_history_clear)
        if inspect.isawaitable(proof):
            if inspect.iscoroutine(proof): proof.close()
            return False
        if (type(proof) is not LegacyMemoOriginProof or proof.source_sha256 != SOURCE_SHA256
                or proof.execution_authorized is not False or proof.legacy_fallback_authorized is not False
                or proof.identity.bot_id != proof.identity.user_id
                or str(event.get_self_id() or '') != proof.identity.bot_id
                or str(event.get_sender_id() or '') != proof.identity.user_id
                or event.unified_msg_origin != proof.identity.session_id
                or self._proof(self.native_identity,event) or not self._resources() or not self._pc(pc)):
            return False
        self._legacy_inflight += 1
        return True

    def _authorize(self, scope):
        return (self._resources() and self._proof(self.authorize_scope, dict(scope))
                and self._proof(self.notes.authorize, dict(scope)) and self._resources())

    def _source(self, scope, binding):
        return (self._resources() and (binding is None or binding == self.binding_sha256)
                and self._proof(self.source_current, dict(scope), binding) and self._resources())

    def _lease(self, scope):
        return self._resources() and self._proof(self.lease_current, dict(scope)) and self._resources()

    def _scope_event(self, event):
        if not self._resources():
            raise PermissionError('memo router stopped or replaced')
        return self.scope_for_event(event)

    def _current_service(self):
        return self.notes if self._resources() else None

    def _drained(self, scope, side):
        if not self._resources(): return False
        if side == 'legacy':
            return self._legacy_inflight == 0 and self._proof(self.old_drained, dict(scope))
        if side == 'native':
            return self._native_inflight == 0 and self.tools.diagnostics()['pending_operations'] == 0
        return False

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

    @classmethod
    def _denied(cls, code, *, status='unavailable'):
        return cls._json(dict(status=status, saved=False, storage='tls_native_memo_notes', code=code,
            schedules_reminder=False, external_completion_confirmed=False, legacy_fallback=False))

    def _pc(self, pc):
        return self._proof(self.pc_current, pc)

    async def _legacy(self, pc, event, payload, legacy_callable):
        # Counts cover the real coroutine, including its old _data_lock wait.
        with self.journal._lock:
            if not self._pc(pc):
                return self._denied('current_pc_instance_required')
            self._legacy_inflight += 1
        try:
            return await legacy_callable(event, **payload)
        finally:
            with self.journal._lock:
                self._legacy_inflight -= 1

    async def _native(self, event, payload, *, native_only=False):
        with self.journal._lock:
            if not self._resources():
                return dict(handled=True, response=dict(status='unavailable', saved=False,
                            code='native_memo_router_unavailable'))
            self._native_inflight += 1
        try:
            return await self.tools.handle(event, payload, native_only=native_only)
        finally:
            with self.journal._lock:
                self._native_inflight -= 1

    async def _listing(self, pc, event, payload, legacy_callable):
        old = await self._legacy(pc, event, payload, legacy_callable)
        try:
            old = json.loads(old)
            if type(old) is not dict: raise ValueError
        except (TypeError, ValueError):
            old = dict(status='unknown', code='legacy_memo_result_not_structured')
        try:
            if not self._pc(pc) or not self._resources(): raise PermissionError
            native = await self._native(event, payload, native_only=True)
            if native.get('handled') is not True:
                native = dict(status='unavailable', code='native_memo_owner_not_active', scope_of_list='native_nonreminder_oneoff_only')
            else:
                native = native['response']
        except Exception:
            native = dict(status='unknown', code='genuine_native_scope_or_owner_unavailable')
        return self._json(dict(status='success' if 'success' in (old.get('status'), native.get('status')) else 'partial',
            action='list', list_scope='legacy_and_native_partitioned', legacy_section=old, native_section=native,
            partial=old.get('status') != 'success' or native.get('status') != 'success',
            numbering_scope='legacy_section_only', native_selectors='exact_tls_id_only',
            combined_count=None, snapshot_atomic=False,
            legacy_scope='original_pc_records', native_scope='native_nonreminder_oneoff_only'))

    async def dispatch(self, pc, event, payload, legacy_callable):
        if type(payload) is not dict or not callable(legacy_callable):
            return self._denied('typed_memo_dispatch_required', status='invalid')
        selector = payload.get('selector', '')
        native_id = type(selector) is str and selector.startswith('memo.')
        raw_action = payload.get('action', 'list')
        action = _ACTIONS.get(raw_action.strip().lower()) if type(raw_action) is str else None
        eligible_create = action == 'create' and _eligible_create(payload)
        if not native_id and action == 'list':
            return await self._listing(pc, event, payload, legacy_callable)
        if not native_id and not eligible_create:
            # Original IDs, reminder definitions, recurrence and delete tokens
            # retain the original implementation and original authorization.
            return await self._legacy(pc, event, payload, legacy_callable)
        if not native_id and eligible_create:
            admitted = False
            try:
                with self.journal._lock:
                    admitted = self._internal_legacy_admit(pc,event)
                if admitted: return await legacy_callable(event,**payload)
            except Exception:
                return self._denied('internal_legacy_origin_or_history_unknown')
            finally:
                if admitted:
                    with self.journal._lock: self._legacy_inflight -= 1
        legacy_admitted = False
        try:
            if not self._pc(pc) or not self._resources(): raise PermissionError
            try:
                scope = self.tools._scope(event)
            except (ValueError, TypeError, AttributeError) as exc:
                raise PermissionError('genuine memo scope unavailable') from exc
            normalized = self.tools._payload(payload, action)
            request_id, _, _ = occurrence(event, scope, normalized)
            with self.journal._lock:
                if not self._pc(pc) or not self._resources(): raise PermissionError
                route = self.ownership.routing(scope, request_id)
                if route['route'] == 'legacy' and not native_id:
                    # No await between owner read and legacy admission count.
                    self._legacy_inflight += 1
                    legacy_admitted = True
                elif route['owner']['mode'] == 'native':
                    if action not in {'get', 'list'}:
                        self.ownership.admit_native(scope, request_id,
                            expected_generation=route['owner']['generation'])
                elif route['route'] != 'claimed':
                    return self._denied('native_memo_owner_closed')
            result = await self._native(event, payload)
            if result.get('handled') is True:
                return self._json(result['response'])
            if not legacy_admitted or route['route'] == 'claimed' or native_id:
                return self._denied('claimed_native_request_never_uses_legacy')
            with self.journal._lock:
                # Prepare may have closed admission while the read-only tool
                # request awaited its worker. Do not start an old operation.
                if (not self._pc(pc) or not self._resources()
                        or self.ownership.routing(scope, request_id)['route'] != 'legacy'):
                    return self._denied('legacy_memo_admission_changed')
            return await legacy_callable(event, **payload)
        except ValueError:
            return self._denied('native_memo_request_rejected', status='invalid')
        except PermissionError:
            return self._denied('genuine_memo_scope_source_or_lease_required', status='forbidden')
        except Exception:
            return self._denied('memo_dispatch_result_unknown', status='unknown')
        finally:
            if legacy_admitted:
                with self.journal._lock:
                    self._legacy_inflight -= 1

    def prepare(self, scope, *, expected_generation, transition_id):
        with self.journal._lock:
            return self.ownership.prepare(scope, expected_generation=expected_generation,
                transition_id=transition_id, binding_sha256=self.binding_sha256)

    def activate(self, scope, *, expected_generation, transition_id):
        with self.journal._lock:
            return self.ownership.activate(scope, expected_generation=expected_generation, transition_id=transition_id)

    def close(self, scope, *, expected_generation, transition_id):
        with self.journal._lock:
            return self.ownership.close(scope, expected_generation=expected_generation, transition_id=transition_id)

    def rollback_legacy(self, scope, *, expected_generation, transition_id):
        with self.journal._lock:
            return self.ownership.rollback_legacy(scope, expected_generation=expected_generation, transition_id=transition_id)

    def stop(self):
        with self.journal._lock:
            self.active = False
            self.tools.stop()
            self.ownership.stop()

    def diagnostics(self):
        with self.journal._lock:
            return dict(protocol=self.protocol, active=self.active, legacy_inflight=self._legacy_inflight,
                native_inflight=self._native_inflight, pending_operations=self.tools.diagnostics()['pending_operations'],
                registers_tool=False, patches_pc=False, creates_private_scope=False,
                schedules_reminder=False, external_completion_confirmed=False)
