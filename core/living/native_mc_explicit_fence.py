"""Selective RAM fence for the reviewed MC explicit-memory capture branch.

Only two instance slots change: service._capture_async and that service's
classifier.derived_user_memories.  The real classifier runs once, including its
profile precedence.  Only its actual selected explicit/relationship result is withheld from the old
capture loop; timeline, other records, portraits and summary keep their original
path.  The native write follows the original capture tail, not the LLM request.

Root supplies the independent write switch, current full scope and authority.
Context/core ownership, a matching phrase, and this install are not permission.
Closing leaves a fence; restoration is explicit, drained and exact-CAS only.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import asdict, replace
import hashlib
import inspect
from pathlib import Path
import sys
import threading
from types import MethodType, ModuleType

from . import native_core_handoff as audit
from .models import private_scope
from .native_explicit_memory import NativeExplicitMemory
from .native_profile_capture import NativeProfileCapture


SLOT = '_tls_native_mc_explicit_fence'
EXTRA_SOURCES = {
    'classifier': 'e0064564ad7d3dba664adc8f1a448dcb70e076ca54f71b531ff5d7402ff815ff',
    'models': '89f1aaad1cea14e635119642ec6d2eb3690a5ae261dd345ce0e4c2722ec7e7a3',
    'profile_quality': 'd07efef2ceb94a4951c04e5e97ca737b5a3779d068fb793bd6035e1e655583e3',
    'identity': 'bd68f2eaa61d9a75282033271a504842b1a2486bd09a833ef25f8f6ffb2e6b05',
    'sensitive_data': '96509372de458483cd3d22be5419a110107b197abe640c7563fbe5e54bdd2b2c',
}


class ExplicitFenceError(RuntimeError):
    pass


def _sync(callback, *args):
    value = callback(*args)
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise ExplicitFenceError('synchronous_owner_callback_required')
    return value


def _same_method(left, right):
    return (inspect.ismethod(left) and inspect.ismethod(right)
            and left.__self__ is right.__self__ and left.__func__ is right.__func__)


def _ctx_identity(ctx):
    return tuple(getattr(ctx, name, None) for name in (
        'scope', 'platform', 'bot_id', 'user_id', 'session_id', 'persona_id',
        'message_id', 'message_text'))


class NativeMCExplicitFence:
    """Root-owned closed-by-default capture adapter; no service discovery.

    Callbacks are pure synchronous predicates/readers. native_write_allowed is
    also thread safe: the business module repeats branch_gate inside to_thread
    and the existing native SQLite transaction. No callback may mint a lease.
    """
    def __init__(self, service, native_explicit, *, source_current, owned_selector,
                 scope_for, native_write_allowed, relationship_selected=None,
                 relationship_owned=False, profile_selected=None, profile_owned=False,
                 profile_capture=None, drain_timeout=10.0):
        if (type(native_explicit) is not NativeExplicitMemory
                or not all(callable(item) and not inspect.iscoroutinefunction(item)
                           for item in (source_current, owned_selector, scope_for, native_write_allowed))
                or relationship_selected is not None and (not callable(relationship_selected)
                    or inspect.iscoroutinefunction(relationship_selected))
                or type(relationship_owned) is not bool
                or profile_selected is not None and (not callable(profile_selected)
                    or inspect.iscoroutinefunction(profile_selected))
                or type(profile_owned) is not bool
                or profile_capture is not None and (type(profile_capture) is not NativeProfileCapture
                    or profile_capture.adapter is not native_explicit.adapter)
                or profile_owned and profile_capture is None
                or type(drain_timeout) not in (int, float) or not 0 < drain_timeout <= 30):
            raise ExplicitFenceError('actual_native_business_and_sync_callbacks_required')
        self.service, self.native = service, native_explicit
        self.source_current, self.owned_selector = source_current, owned_selector
        self.scope_for, self.native_write_allowed = scope_for, native_write_allowed
        self.relationship_selected = (relationship_selected if relationship_selected is not None
                                      else lambda ctx, event, req: False)
        self._relationship_owned = relationship_owned
        self.profile_selected = (profile_selected if profile_selected is not None
                                 else lambda ctx, event, req: False)
        self._profile_owned, self.profile_capture = profile_owned, profile_capture
        self.drain_timeout = float(drain_timeout)
        self.classifier = vars(service).get('classifier')
        self._current = ContextVar('tls_mc_explicit_capture', default=None)
        self._closed = threading.Event(); self._closed.set()
        self._barrier = asyncio.Event(); self._barrier.set()
        self._installed = self._restoring = self._retired = False
        self._redirect = None
        self._running, self._native_tasks = set(), set()
        self._original, self._own, self._wrappers = {}, {}, {}
        self._files, self._functions = {}, []
        self._snapshot = self._record_type = self._capture_code = None
        self._parent_runtime = self._parent_fence = None
        self._generation = 0
        self._phase, self._last = 'new_closed', 'none'
        self._counts = dict(captures=0, selected=0, native_written=0, closed=0,
                            denied=0, unknown=0, cancelled=0, other_records=0,
                            relationship_selected=0, relationship_written=0,
                            profile_selected=0, profile_observed=0)
        self.native.branch_gate = self.branch_gate
        if self.profile_capture is not None:
            self.profile_capture.branch_gate = self.profile_branch_gate

    def _prepare_sources(self, predecessor=None):
        """Use the existing actual-service audit, then pin the new two slots.

        Nothing here imports or initializes an old business module. The
        already-loaded classifier and its dependencies must be the reviewed
        modules/classes and code, with no instance method overrides except an
        exact known closed predecessor's own derived wrapper.
        """
        parent_fence = vars(self.service).get('_tls_native_companion_context_fence')
        parent_runtime = vars(parent_fence).get('_tls_mc_runtime_owner') if parent_fence is not None else None
        snapshot = vars(parent_runtime).get('snapshot') if parent_runtime is not None else None
        if (type(snapshot) is not audit._Snapshot or snapshot.service is not self.service
                or vars(parent_runtime).get('service') is not self.service
                or vars(parent_runtime).get('fence') is not parent_fence):
            raise ExplicitFenceError('existing_reviewed_parent_snapshot_required')
        self._parent_runtime, self._parent_fence = parent_runtime, parent_fence
        core = snapshot.service_module.__name__.rsplit('.', 1)[0]
        modules, codes = {}, {}
        files = []
        for name, module in (('main', snapshot.module), ('service', snapshot.service_module),
                             ('config', snapshot.config_module), ('store', snapshot.store_module)):
            path = Path(vars(module)['__file__'])
            if hashlib.sha256(audit._regular_file(path)).hexdigest() != audit._SOURCE_HASHES[name]:
                raise ExplicitFenceError('reviewed_parent_source_changed')
            files.append(path)
        for name, digest in EXTRA_SOURCES.items():
            module = sys.modules.get(core + '.' + name)
            if not isinstance(module, ModuleType):
                raise ExplicitFenceError('loaded_classifier_dependency_missing')
            path = Path(vars(snapshot.service_module)['__file__']).with_name(name + '.py')
            if vars(module).get('__file__') != str(path):
                raise ExplicitFenceError('classifier_dependency_path_changed')
            raw = audit._regular_file(path)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ExplicitFenceError('classifier_dependency_source_changed')
            modules[name] = module; codes[name] = audit._compiled(raw, str(path)); files.append(path)
        classifier_cls = vars(modules['classifier']).get('MemoryClassifier')
        record_type = vars(modules['models']).get('MemoryRecord')
        if (type(self.classifier) is not classifier_cls
                or vars(snapshot.service_module).get('MemoryClassifier') is not classifier_cls
                or vars(modules['classifier']).get('MemoryRecord') is not record_type
                or vars(snapshot.service_module).get('MemoryRecord') is not record_type
                or vars(snapshot.store_module).get('MemoryRecord') is not record_type):
            raise ExplicitFenceError('actual_classifier_and_record_class_required')
        cls_code = audit._child(codes['classifier'], 'MemoryClassifier')
        functions = []
        for name, descriptor in vars(classifier_cls).items():
            function = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor
            if not inspect.isfunction(function):
                continue
            if (function.__code__ != audit._child(cls_code, name)
                    or function.__globals__ is not vars(modules['classifier'])):
                raise ExplicitFenceError('loaded_classifier_code_changed')
            override = vars(self.classifier).get(name)
            if override is not None and not (name == 'derived_user_memories' and predecessor is not None
                    and override is predecessor._wrappers.get('derived')):
                raise ExplicitFenceError('classifier_instance_override')
            functions.append((classifier_cls, name, descriptor))
        # Pin actual imported helpers used by the classifier's profile-first
        # extraction. The old extraction itself is never run twice here.
        for name, module_name in (('clean_text', 'models'), ('entity_for_user', 'identity'),
                                  ('entity_for_current_target', 'identity'), ('looks_like_command', 'identity'),
                                  ('extract_profile_candidates', 'profile_quality'),
                                  ('profile_candidate_metadata', 'profile_quality'),
                                  ('profile_rejection_reason', 'profile_quality')):
            function = vars(modules[module_name]).get(name)
            if (not inspect.isfunction(function)
                    or function.__code__ != audit._child(codes[module_name], name)
                    or function.__globals__ is not vars(modules[module_name])
                    or vars(modules['classifier']).get(name) is not function):
                raise ExplicitFenceError('classifier_helper_binding_changed')
            functions.append((modules['classifier'], name, function))
        service_cls = audit._child(audit._compiled(audit._regular_file(
            Path(vars(snapshot.service_module)['__file__'])), vars(snapshot.service_module)['__file__']),
            'MemoryCompanionService')
        capture = vars(type(self.service)).get('_capture_async')
        if (not inspect.iscoroutinefunction(capture)
                or capture.__code__ != audit._child(service_cls, '_capture_async')
                or capture.__globals__ is not vars(snapshot.service_module)):
            raise ExplicitFenceError('actual_capture_code_required')
        if '_capture_async' in vars(self.service) and not (predecessor is not None
                and vars(self.service)['_capture_async'] is predecessor._wrappers.get('capture')):
            raise ExplicitFenceError('capture_instance_override')
        functions.append((type(self.service), '_capture_async', capture))
        self._snapshot, self._record_type, self._capture_code = snapshot, record_type, capture.__code__
        self._functions = functions
        self._files = {path: (path.stat().st_dev, path.stat().st_ino,
                             path.stat().st_size, path.stat().st_mtime_ns) for path in files}

    def _sources_current(self):
        try:
            snapshot = self._snapshot
            if (snapshot is None or vars(snapshot.owner).get('service') is not self.service
                    or self._parent_fence is not None and (
                        vars(self.service).get('_tls_native_companion_context_fence') is not self._parent_fence
                        or vars(self._parent_fence).get('_tls_mc_runtime_owner') is not self._parent_runtime
                        or vars(self._parent_runtime).get('snapshot') is not snapshot)
                    or vars(self.service).get('classifier') is not self.classifier
                    or vars(self.service).get('store') is not snapshot.store
                    or vars(snapshot.store).get('_conn') is not snapshot.connection
                    or vars(snapshot.store).get('_closed') is not False
                    or vars(snapshot.store).get('_closing') is not False
                    or vars(self.service).get('config') is not snapshot.config
                    or audit._config_digest(vars(snapshot.config).get('raw')) != snapshot.config_hash
                    or _sync(self.source_current, self.service) is not True):
                return False
            for owner, name, expected in self._functions:
                if vars(owner).get(name) is not expected:
                    return False
            for path, expected in self._files.items():
                stat = path.stat()
                if path.is_symlink() or (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != expected:
                    return False
            if self._installed and (vars(self.service).get(SLOT) is not self
                    or vars(self.service).get('_capture_async') is not self._wrappers.get('capture')
                    or vars(self.classifier).get('derived_user_memories') is not self._wrappers.get('derived')):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _known_predecessor(value, service):
        return (value is not None and type(value).__name__ == 'NativeMCExplicitFence'
                and type(value).__module__ == NativeMCExplicitFence.__module__
                and type(value).install.__code__ == NativeMCExplicitFence.install.__code__
                and type(value)._make_capture.__code__ == NativeMCExplicitFence._make_capture.__code__
                and type(value)._make_derived.__code__ == NativeMCExplicitFence._make_derived.__code__
                and vars(value).get('service') is service and value._closed.is_set()
                and value._installed and not value._retired
                and type(vars(value).get('_relationship_owned')) is bool
                and type(vars(value).get('_profile_owned')) is bool
                and set(value._wrappers) == {'capture', 'derived'}
                and vars(service).get('_capture_async') is value._wrappers['capture']
                and vars(value.classifier).get('derived_user_memories') is value._wrappers['derived'])

    async def _wait(self, tasks):
        tasks = {task for task in tasks if not task.done() and task is not asyncio.current_task()}
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.drain_timeout)
            if pending:
                raise ExplicitFenceError('capture_drain_not_proven')

    async def _drain_original(self):
        loop = asyncio.get_running_loop(); tasks = asyncio.all_tasks(loop)
        if len(tasks) > audit.MAX_TASKS:
            raise ExplicitFenceError('capture_task_scan_capacity')
        future_iter = type(loop.create_future().__await__()); active = []
        for task in tasks:
            found, unknown = audit._task_chain(task, (self._capture_code,), future_iter)
            if unknown:
                raise ExplicitFenceError('capture_task_chain_unknown')
            if found:
                active.append(task)
        await self._wait(active)
        # A cancelled original capture can leave an old Store executor job.
        threaded, unknown, queued = audit._threads(replace(self._snapshot,
            codes=(*self._snapshot.codes, self._capture_code)))
        if threaded or unknown or queued:
            raise ExplicitFenceError('old_capture_worker_drain_not_proven')

    async def install(self):
        if self._installed or self._retired:
            raise ExplicitFenceError('capture_fence_already_used')
        previous = vars(self.service).get(SLOT)
        if previous is not None and not self._known_predecessor(previous, self.service):
            raise ExplicitFenceError('exact_closed_predecessor_required')
        self._prepare_sources(previous)
        if not self._sources_current():
            raise ExplicitFenceError('current_reviewed_sources_required')
        if previous is not None:
            previous._barrier.clear()
            try:
                await previous._wait(previous._running | previous._native_tasks)
                if not self._known_predecessor(previous, self.service) or not self._sources_current():
                    raise ExplicitFenceError('predecessor_changed_during_drain')
                self._original, self._own = dict(previous._original), dict(previous._own)
                self._relationship_owned = self._relationship_owned or previous._relationship_owned
                self._profile_owned = self._profile_owned or previous._profile_owned
                if self._profile_owned and self.profile_capture is None:
                    raise ExplicitFenceError('owned_profile_capture_required_for_adoption')
                self._attach()
                previous._redirect = self._wrappers['capture']
                previous._retired = True; previous._installed = False
                previous._relationship_owned = False
                previous._profile_owned = False
                previous._phase = 'closed_adopted'; previous._barrier.set()
                return self
            except BaseException:
                previous._barrier.set()
                raise
        for key, owner, name in (('capture', self.service, '_capture_async'),
                                 ('derived', self.classifier, 'derived_user_memories')):
            method = getattr(owner, name, None)
            if not inspect.ismethod(method) or method.__self__ is not owner:
                raise ExplicitFenceError('actual_instance_method_required')
            self._original[key], self._own[key] = method, name in vars(owner)
        self._barrier.clear()
        self._wrappers['capture'] = MethodType(self._make_capture(), self.service)
        setattr(self.service, '_capture_async', self._wrappers['capture'])
        try:
            await self._drain_original()
            if not self._sources_current():
                raise ExplicitFenceError('sources_changed_during_capture_drain')
            self._attach()
            self._barrier.set()
            return self
        except BaseException:
            self._restore_slots()
            self._phase = 'install_failed_no_owner'; self._barrier.set()
            raise

    def _attach(self):
        if 'capture' not in self._wrappers:
            self._wrappers['capture'] = MethodType(self._make_capture(), self.service)
        self._wrappers['derived'] = MethodType(self._make_derived(), self.classifier)
        setattr(self.service, '_capture_async', self._wrappers['capture'])
        setattr(self.classifier, 'derived_user_memories', self._wrappers['derived'])
        setattr(self.service, SLOT, self)
        self._installed = True; self._phase = 'installed_closed'

    def open(self):
        if (not self._installed or self._retired or self._restoring
                or not self._sources_current() or self.native.active is not True
                or not _same_method(self.native.branch_gate, self.branch_gate)):
            raise ExplicitFenceError('installed_current_capture_fence_required')
        if not self._closed.is_set():
            return self.status()
        if any(not task.done() for task in self._native_tasks):
            raise ExplicitFenceError('native_operations_must_drain_before_reopen')
        self._generation += 1
        self._closed.clear(); self._phase = 'native_explicit'
        return self.status()

    def enable_relationship_selection(self):
        """Latch this responsibility before opening its separate write flag.

        Closing the write flag never reopens the old relationship branch.
        Root's selector is a scope predicate, not that write flag.
        """
        if (not self._installed or self._retired or not self._closed.is_set()
                or self._restoring or any(not task.done() for task in self._running | self._native_tasks)
                or not self._sources_current()):
            raise ExplicitFenceError('closed_drained_relationship_selection_required')
        self._relationship_owned = True
        self._generation += 1
        return self.status()

    def close(self):
        self._closed.set()
        # Existing capture states and inherited to_thread contexts never regain
        # admission when a later operator opens this same fence again.
        self._generation += 1
        self._phase = 'closed_fenced' if self._installed else self._phase

    stop = close

    def enable_profile_selection(self):
        if (not self._installed or self._retired or not self._closed.is_set()
                or self._restoring or self.profile_capture is None
                or any(not task.done() for task in self._running | self._native_tasks)
                or not self._sources_current()):
            raise ExplicitFenceError('closed_drained_profile_selection_required')
        self._profile_owned = True
        self._generation += 1
        return self.status()

    def _make_capture(self):
        async def capture(_service, ctx, event, req, reply_chain):
            await self._barrier.wait()
            if self._retired:
                if self._redirect is None:
                    raise ExplicitFenceError('retired_capture_fence')
                return await self._redirect(ctx, event, req, reply_chain)
            if not self._installed:
                return await self._original['capture'](ctx, event, req, reply_chain)
            task = asyncio.current_task()
            state = dict(task=task, ctx=ctx, event=event, req=req, active=True,
                         generation=self._generation,
                         record=None, record_digest=None, ctx_identity=None,
                         scope=None, native_task=None, kind=None, relationship_admitted=False)
            state.update(records=None, records_digest=None, profile_snapshots=None,
                         profile_snapshot_digest=None, profile_admitted=False)
            token = self._current.set(state); self._running.add(task)
            self._counts['captures'] += 1
            try:
                result = await self._original['capture'](ctx, event, req, reply_chain)
                if state['record'] is not None:
                    if self._closed.is_set() or not self.branch_gate(event, state['scope']):
                        self._counts['closed' if self._closed.is_set() else 'denied'] += 1
                        self._last = 'closed' if self._closed.is_set() else 'branch_denied'
                    else:
                        # Shield the actual already-requested native operation,
                        # so parent cancellation cannot hide its to_thread work
                        # from restore/adoption drain. This is not a scheduler.
                        if state['kind'] == 'profile':
                            operation = asyncio.create_task(self.profile_capture.capture_event(
                                event, state['scope'], state['profile_snapshots']))
                        else:
                            capture_method = (self.native.capture_relationship_event
                                if state['kind'] == 'relationship_claim' else self.native.capture_event)
                            operation = asyncio.create_task(capture_method(event, state['scope']))
                        state['native_task'] = operation; self._native_tasks.add(operation)
                        operation.add_done_callback(self._native_done)
                        try:
                            saved = await asyncio.shield(operation)
                        except asyncio.CancelledError:
                            state['active'] = False
                            self._counts['cancelled'] += 1; self._last = 'cancelled_unknown'
                            raise
                        except Exception:
                            self._counts['unknown'] += 1; self._last = 'native_unknown'
                        else:
                            if type(saved) is dict and saved.get('ok') is True:
                                self._counts['native_written'] += 1; self._last = 'stored_or_replayed'
                                if state['kind'] == 'relationship_claim':
                                    self._counts['relationship_written'] += 1
                                if state['kind'] == 'profile':
                                    self._counts['profile_observed'] += len(state['records'])
                            else:
                                self._counts['denied'] += 1; self._last = 'native_rejected'
                return result
            finally:
                state['active'] = False
                self._current.reset(token); self._running.discard(task)

        return capture

    def _native_done(self, task):
        self._native_tasks.discard(task)
        if not task.cancelled():
            # Retrieve only to prevent an unobserved exception warning after
            # parent cancellation; no exception text/content is retained.
            task.exception()

    def _make_derived(self):
        def derived(_classifier, ctx, source_memory_id=''):
            state = self._current.get()
            frame = inspect.currentframe()
            try:
                caller = frame.f_back
                genuine = (state is not None and state['active']
                    and state['ctx'] is ctx and state['task'] is asyncio.current_task()
                    and caller.f_code is self._capture_code
                    and caller.f_globals is self._original['capture'].__func__.__globals__
                    and caller.f_locals.get('self') is self.service
                    and caller.f_locals.get('ctx') is ctx
                    and caller.f_locals.get('event') is state['event']
                    and caller.f_locals.get('req') is state['req'])
            finally:
                del frame
                try: del caller
                except UnboundLocalError: pass
            if not genuine:
                return self._original['derived'](ctx, source_memory_id=source_memory_id)
            owner = _sync(self.owned_selector, ctx, state['event'], state['req'])
            if owner is False:
                return self._original['derived'](ctx, source_memory_id=source_memory_id)
            if owner is not True:
                raise ExplicitFenceError('explicit_owner_or_source_unknown')
            # Closing/replacing TLS is not a reason to truncate the original
            # profile/relationship/tail path. Native write admission still
            # repeats the complete source/owner check in branch_gate below.
            selected = self._original['derived'](ctx, source_memory_id=source_memory_id)
            if type(selected) is not list or any(type(row) is not self._record_type for row in selected):
                raise ExplicitFenceError('actual_derived_record_list_required')
            profiles = [row for row in selected if row.memory_type in
                ('user_profile', 'user_preference', 'user_habit') and row.metadata.get('profile_dimension')]
            if profiles and self._profile_owned:
                choice = _sync(self.profile_selected, ctx, state['event'], state['req'])
                if choice is False:
                    return selected
                if len(profiles) > 16:
                    self._counts['denied'] += 1
                    self._last = 'profile_batch_rejected'
                    raise ExplicitFenceError('actual_profile_batch_required')
                if (state['record'] is not None
                        or any(row.metadata.get('extractor') != 'rule_v2' or row.scope != 'private'
                            or row.session_id != ctx.session_id or row.platform != ctx.platform
                            or row.message_id != ctx.message_id for row in profiles)):
                    raise ExplicitFenceError('actual_profile_batch_required')
                state['record'], state['kind'] = profiles[0], 'profile'
                state['records'] = profiles
                state['records_digest'] = audit._json_digest(profiles, dataclasses=True)
                state['profile_snapshots'] = [asdict(row) for row in profiles]
                state['profile_snapshot_digest'] = audit._json_digest(state['profile_snapshots'])
                state['profile_admitted'] = choice is True
                self._remember_selection(state, ctx)
                self._counts['selected'] += len(profiles)
                self._counts['profile_selected'] += len(profiles)
                self._counts['other_records'] += len(selected) - len(profiles)
                filtered = {id(row) for row in profiles}
                return [row for row in selected if id(row) not in filtered]
            candidates = [row for row in selected if row.memory_type in ('explicit_memory', 'relationship_claim')]
            if not candidates:
                return selected
            if len(candidates) != 1 or state['record'] is not None:
                raise ExplicitFenceError('single_actual_explicit_selection_required')
            row = candidates[0]
            if row.memory_type == 'relationship_claim':
                if not self._relationship_owned:
                    return selected
                choice = _sync(self.relationship_selected, ctx, state['event'], state['req'])
                if choice is False:
                    return selected
                # Unknown selection keeps this owned branch closed; it never
                # becomes permission to fall back to the old relationship write.
                state['relationship_admitted'] = choice is True
            if (row.metadata.get('extractor') != 'rule_v2' or row.metadata.get('profile_dimension')
                    or row.scope != 'private' or row.session_id != ctx.session_id
                    or row.platform != ctx.platform or row.message_id != ctx.message_id):
                raise ExplicitFenceError('non_profile_explicit_record_required')
            state['record'] = row
            state['kind'] = row.memory_type
            self._remember_selection(state, ctx)
            self._counts['selected'] += 1
            if state['kind'] == 'relationship_claim':
                self._counts['relationship_selected'] += 1
            self._counts['other_records'] += len(selected) - 1
            # No legacy insert or vector scheduling sees this object/ID. Every
            # other original record keeps its original identity and ordering.
            return [item for item in selected if item is not row]

        return derived

    def _remember_selection(self, state, ctx):
        state['record_digest'] = audit._json_digest(state['record'], dataclasses=True)
        state['ctx_identity'] = _ctx_identity(ctx)
        try:
            state['scope'] = private_scope(_sync(self.scope_for, ctx, state['event'], state['req']))
        except Exception:
            state['scope'] = None

    def _profile_current(self, state):
        return (self._profile_owned and self.profile_capture is not None
            and state['profile_admitted'] is True and type(state['records']) is list
            and 1 <= len(state['records']) <= 16
            and state['record'] is state['records'][0]
            and all(type(row) is self._record_type and row.memory_type in
                ('user_profile', 'user_preference', 'user_habit')
                and row.metadata.get('profile_dimension') for row in state['records'])
            and audit._json_digest(state['records'], dataclasses=True) == state['records_digest']
            and _sync(self.profile_selected, state['ctx'], state['event'], state['req']) is True
            and _same_method(self.profile_capture.branch_gate, self.profile_branch_gate))

    def profile_branch_gate(self, event, scope, records):
        try:
            state = self._current.get()
            return (state is not None and state['kind'] == 'profile'
                and audit._json_digest(records) == state['profile_snapshot_digest']
                and self.branch_gate(event, scope))
        except Exception:
            return False

    def branch_gate(self, event, scope):
        """Pure repeated admission; ContextVar also crosses native to_thread."""
        try:
            state = self._current.get()
            return bool(not self._closed.is_set() and self._installed and not self._retired
                and not self._restoring and state is not None and state['active']
                and state['generation'] == self._generation
                and state['event'] is event and state['record'] is not None
                and (state['kind'] == 'profile' and self._profile_current(state)
                    or state['kind'] == state['record'].memory_type
                    and state['kind'] in ('explicit_memory', 'relationship_claim'))
                and (state['kind'] != 'relationship_claim' or self._relationship_owned
                    and state['relationship_admitted'] is True
                    and _sync(self.relationship_selected, state['ctx'], event, state['req']) is True)
                and type(state['record']) is self._record_type and state['scope'] == private_scope(scope)
                and _ctx_identity(state['ctx']) == state['ctx_identity']
                and not state['task'].done() and not state['task'].cancelling()
                and audit._json_digest(state['record'], dataclasses=True) == state['record_digest']
                and self._sources_current()
                and _same_method(self.native.branch_gate, self.branch_gate)
                and _sync(self.native_write_allowed, state['ctx'], event, state['req'],
                          dict(scope), state['record']) is True
                and not self._closed.is_set() and state['active'])
        except Exception:
            return False

    def _restore_slots(self):
        for key, owner, name in (('capture', self.service, '_capture_async'),
                                 ('derived', self.classifier, 'derived_user_memories')):
            if key not in self._wrappers:
                continue
            if vars(owner).get(name) is self._wrappers.get(key):
                if self._own[key]:
                    setattr(owner, name, self._original[key])
                else:
                    delattr(owner, name)
        if vars(self.service).get(SLOT) is self:
            delattr(self.service, SLOT)
        self._installed = False
        self._relationship_owned = False
        self._profile_owned = False

    async def wait_drained(self):
        """After close, wait actual native operations before Host store close.

        Closed new captures may still run their legacy non-explicit tail. They
        cannot admit another native operation. This method does not claim that
        all unrelated MC data-adapter tasks are stopped.
        """
        if not self._closed.is_set():
            raise ExplicitFenceError('close_before_native_drain')
        await self._wait(self._running | self._native_tasks)
        store = self.native.store
        def barrier():
            with store._lock:
                if store._closed:
                    raise ExplicitFenceError('native_store_closed_before_drain')
        await asyncio.to_thread(barrier)
        if self._native_tasks:
            raise ExplicitFenceError('native_capture_drain_not_proven')
        return dict(native_drained=True, pending_native_operations=0,
                    legacy_data_adapter_tasks_stopped=False)

    async def restore(self, *, legacy_restored=False):
        if legacy_restored is not True or not self._installed or self._retired:
            raise ExplicitFenceError('explicit_legacy_owner_required')
        self.close(); self._restoring = True; self._barrier.clear()
        try:
            await self.wait_drained()
            if self._running or self._native_tasks or not self._sources_current():
                raise ExplicitFenceError('exact_drained_restore_required')
            self._restore_slots(); self._phase = 'legacy_restored'
            return self.status()
        except BaseException:
            self._phase = 'restore_failed_closed'
            raise
        finally:
            self._restoring = False
            # A successful exact restore releases queued captures into their
            # original method. Failure releases them through the still-closed
            # selective fence, preserving the non-explicit data-adapter tail.
            self._barrier.set()

    def status(self):
        return dict(installed=self._installed, active=self._installed and not self._closed.is_set()
                    and not self._retired and self._sources_current(), phase=self._phase,
                    pending_captures=len(self._running), pending_native_operations=len(self._native_tasks),
                    generation=self._generation,
                    relationship_owned=self._relationship_owned,
                    profile_owned=self._profile_owned,
                    counts=dict(self._counts), last_state=self._last, original_slots=2,
                    classifier_recomputed=False, legacy_insert_or_embedding_wrapped=False,
                    model_calls=0, sends=0, ownership_permission_created=False)
