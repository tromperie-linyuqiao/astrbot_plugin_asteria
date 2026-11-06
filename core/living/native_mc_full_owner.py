"""One explicit transition from the original MC lifecycle to TLS ownership.

Construction is offline. No database is opened and no former plugin is stopped
until an explicit activation, or a previously persisted native owner resumes.
The source pins below are from the actual R60 fixed-file inventory. This owner
never migrates identities, restores database snapshots or clears task ledgers.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
from queue import SimpleQueue
import sys
import threading
from types import MethodType

from .native_mc.host_adapter import NativeMemoryCompanion
from .native_mc.task_drain import source_codes, task_chain, task_codes
from .native_mc.companion_identity import native_companion
from .native_mc_owned_runtime import NativeOwnedMCContextRuntime
from .native_mc_takeover_runtime import NativeMCTakeoverRuntime
from .native_mc_retirement import NativeMCRetirement, SCHEMA as RETIREMENT_SCHEMA


LEGACY = 'astrbot_plugin_memory_companion'
FLAG = 'living_mc_full_native_enabled'
CONFIG = 'living_mc'
RETIRED_SLOT = '_tls_native_mc_retired_service'
NATIVE_SLOT = '_tls_native_mc_lifecycle'
BRANCH_FLAGS = ('living_mc_context_native_enabled', 'living_mc_explicit_native_enabled',
    'living_mc_relationship_native_enabled', 'living_mc_profile_native_enabled',
    'living_mc_summary_native_enabled')
HOOKS = ('handle_llm_request', 'handle_group_message', 'handle_llm_response')
TOOLS = ('tool_recall', 'tool_navigate', 'tool_remember', 'tool_core_memory',
         'tool_note_create', 'tool_note_read', 'tool_note_delete')
DISPATCHERS = ('_maintenance_dispatch_task', '_portrait_dispatch_task', '_wal_checkpoint_task')


class NativeMCLifecyclePending(RuntimeError):
    """No new native store may open until the retained lifecycle closes."""


class NativeMCFullOwner:
    def __init__(self, integrations):
        self.integrations, self.plugin, self.context = integrations, integrations.plugin, integrations.context
        self.adapter = self.runtime = None
        self.phase, self.generation, self.last_error = 'inactive', 0, None
        self.last_error_sha256 = None
        self._lock = asyncio.Lock()
        self._legacy = self._legacy_service = self._legacy_runtime = None
        self._source_root = None
        self._source_paths, self._source_identities = set(), {}
        self._source_codes = ()
        self._hook_slots, self._page_slots = {}, []
        self._bridge = self._bridge_before = self._bridge_after = None
        self._prior_closing = None
        self._command_slot = None
        self._saved_flags = self._last_enabled_flags = None
        self._last_config = None
        self._old_off_attempted = self._old_off_confirmed = False
        self._drain = dict(tasks=None, threads=None, queued=None, unknown=None)
        self._native_record = None
        self._pre_anchor_report = None

    def inspect_predecessors(self):
        self._pre_anchor_report = NativeMCRetirement(self, self._native_directory()).inspect()
        return dict(self._pre_anchor_report)

    def _native_pending(self, code):
        self.phase, self.last_error = 'waiting_native_predecessor', code
        raise NativeMCLifecyclePending(code)

    def _native_directory(self):
        record = getattr(self.context, RETIRED_SLOT, None)
        if self._legacy_service is not None:
            return Path(self._legacy_service.data_dir).resolve()
        if type(record) is dict and record.get('context') is self.context:
            return Path(record['service'].data_dir).resolve()
        from ...identity import component_data_directory
        return component_data_directory('memory_companion', LEGACY,
            retain_existing=self.plugin.config.get(FLAG) is True,
            markers=('memory_companion.db',))

    def _claim_native(self, directory, adapter):
        if getattr(self.context, NATIVE_SLOT, None) is not None:
            self._native_pending('native_lifecycle_anchor_changed')
        record = dict(schema='tls.mc.native.lifecycle.v1', context=self.context,
            pid=os.getpid(), loop=asyncio.get_running_loop(), directory=directory,
            owner=self, close=self.close, adapter=adapter, service=None,
            work=adapter._work, adapter_close=adapter.close, stopping=False)
        self._native_record = record
        setattr(self.context, NATIVE_SLOT, record)

    def _release_native(self):
        record = self._native_record
        if record is None:
            return
        if getattr(self.context, NATIVE_SLOT, None) is not record:
            self._native_pending('native_lifecycle_anchor_changed')
        delattr(self.context, NATIVE_SLOT)
        self._native_record = None

    async def _settle_native(self, directory):
        record = getattr(self.context, NATIVE_SLOT, None)
        if record is None:
            return
        if (type(record) is not dict or record.get('schema') != 'tls.mc.native.lifecycle.v1'
                or record.get('context') is not self.context or record.get('pid') != os.getpid()
                or record.get('loop') is not asyncio.get_running_loop()
                or record.get('directory') != directory):
            self._native_pending('native_lifecycle_reference_unverified')
        previous, close = record.get('owner'), record.get('close')
        kind = type(previous)
        if (kind.__module__ != __name__ or kind.__name__ != type(self).__name__
                or getattr(previous, 'context', None) is not self.context
                or getattr(previous, '_native_record', None) is not record
                or type(close) is not MethodType or close.__self__ is not previous
                or close.__func__ is not vars(kind).get('close')):
            self._native_pending('native_lifecycle_callback_unverified')
        adapter = previous.adapter
        if (adapter is None or record.get('adapter') is not adapter
                or adapter.context is not self.context or adapter.data_dir != directory
                or adapter.service is not record.get('service')):
            self._native_pending('native_lifecycle_objects_changed')
        for key, name in (('work', '_work'), ('adapter_close', 'close')):
            saved, actual = record.get(key), getattr(adapter, name, None)
            if (type(saved) is not MethodType or type(actual) is not MethodType
                    or saved.__self__ is not adapter or actual.__self__ is not adapter
                    or saved.__func__ is not actual.__func__
                    or saved.__func__ is not vars(type(adapter)).get(name)):
                self._native_pending('native_lifecycle_callback_unverified')
        if record.get('stopping') is not True:
            self._native_pending('previous_native_lifecycle_active')
        if previous is not self and previous._lock.locked():
            self._native_pending('previous_native_close_in_progress')
        service = adapter.service
        if not adapter.closed:
            if adapter.active or service is not None and service._closing is not True:
                self._native_pending('previous_native_lifecycle_not_stopped')
            # This is a read of the original adapter's work, not adoption of
            # its business. A pending unit is neither cancelled nor retried.
            tasks = record['work']()
            current = asyncio.current_task()
            if current in adapter._calls or service is not None and current in service._background_tasks:
                tasks.add(current)
            if tasks:
                self._native_pending('previous_native_memory_work_pending')
        try:
            if previous is self:
                await self._stop_locked(False)
            else:
                await close()
        except RuntimeError:
            self._native_pending('previous_native_close_pending')
        if (previous.adapter is not adapter or adapter.service is not service or not adapter.closed
                or service is not None and (not service._closed or not service.store._closed)
                or getattr(self.context, NATIVE_SLOT, None) is not None):
            self._native_pending('previous_native_close_not_confirmed')

    def _rows(self):
        return [row for row in self.context.get_all_stars()
                if getattr(row, 'root_dir_name', None) == LEGACY]

    def _row(self):
        rows = self._rows()
        if len(rows) > 1:
            raise RuntimeError('conflicting memory registry entries')
        return rows[0] if rows else None

    def _flags(self):
        return {name: self.plugin.config.get(name, False) is True for name in BRANCH_FLAGS}

    def _save(self, values):
        with self.integrations._config_lock:
            previous = {key: (key in self.plugin.config, deepcopy(self.plugin.config.get(key)))
                        for key in values}
            try:
                for key, value in values.items():
                    self.plugin.config[key] = deepcopy(value)
                self.plugin.config.save_config()
            except BaseException:
                for key, (present, value) in previous.items():
                    if present:
                        self.plugin.config[key] = value
                    else:
                        self.plugin.config.pop(key, None)
                raise

    def persist_config(self, raw):
        """Native UI and presets write TLS living_mc, never the old cfg file."""
        if type(raw) is not dict:
            raise ValueError('complete native memory configuration object required')
        value = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        value.setdefault('memory_tools', {})['enable_core_memory_tool'] = False
        value.setdefault('core_memory', {})['llm_management_enabled'] = False
        with self.integrations._config_lock:
            target = self.plugin.config.get(CONFIG)
            if type(target) is not dict:
                raise RuntimeError('native memory configuration was replaced')
            previous = deepcopy(self._last_config if self._last_config is not None else target)
            target.clear(); target.update(value)
            try:
                self.plugin.config.save_config()
            except BaseException:
                target.clear(); target.update(previous)
                raise
            self._last_config = deepcopy(target)
        return dict(ok=True, owner='tls', configuration=CONFIG)

    def _pin_sources(self, owner):
        module = sys.modules.get(type(owner).__module__)
        if module is None or getattr(module, '__file__', None) is None:
            raise RuntimeError('original memory source module unavailable')
        root = Path(module.__file__).resolve().parent
        if root.name != LEGACY:
            raise RuntimeError('unexpected original memory source root')
        identities, paths, codes = {}, set(), []
        for relative, digest in _LEGACY_SOURCE_HASHES.items():
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('original memory source file missing or linked')
            data = path.read_bytes()
            if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('original memory fixed source fingerprint changed')
            st = path.stat()
            identities[str(path)] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            paths.add(str(path))
            codes.extend(source_codes(data, str(path)))
        self._source_root, self._source_paths, self._source_identities = root, paths, identities
        self._source_codes = tuple(codes)

    def _source_current(self):
        try:
            for filename, identity in self._source_identities.items():
                path = Path(filename)
                st = path.stat()
                if path.is_symlink() or (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != identity:
                    return False
            return bool(self._source_identities)
        except (OSError, ValueError):
            return False

    def _guard_legacy(self):
        row = self._row()
        owner = getattr(row, 'star_cls', None)
        runtime = self.integrations.mc
        if (getattr(row, 'activated', False) is not True or owner is None
                or type(runtime) is not NativeMCTakeoverRuntime
                or runtime.service is not getattr(owner, 'service', None)
                or runtime.snapshot is None or runtime.snapshot.owner is not owner
                or runtime._source_current() is not True):
            raise RuntimeError('current reviewed original memory runtime required')
        self._pin_sources(owner)
        self._legacy, self._legacy_service, self._legacy_runtime = owner, owner.service, runtime
        self._saved_flags = self._flags()
        self._last_enabled_flags = dict(self._saved_flags)
        raw = getattr(owner.service.config, 'raw', None)
        if not isinstance(raw,dict):
            raise RuntimeError('complete original memory configuration required')
        config = json.loads(json.dumps(dict(raw),ensure_ascii=False,allow_nan=False))
        config.setdefault('memory_tools', {})['enable_core_memory_tool'] = False
        config.setdefault('core_memory', {})['llm_management_enabled'] = False
        return config

    def _freeze_admission(self):
        service = self._legacy_service
        if service is None or not self._source_current() or self._hook_slots:
            raise RuntimeError('unfenced original service required')
        self._prior_closing = service._closing
        if self._prior_closing or service._closed:
            raise RuntimeError('original service already closing')
        for name in HOOKS + TOOLS:
            original = getattr(service, name)
            if not inspect.ismethod(original) or original.__self__ is not service:
                raise RuntimeError('original memory hook implementation changed')
            had_slot = name in vars(service)
            if name in TOOLS:
                async def closed_hook(_service, *args, **kwargs):
                    return dict(ok=False, error='original memory owner transition in progress')
            else:
                async def closed_hook(_service, *args, **kwargs):
                    return None
            wrapped = MethodType(closed_hook, service)
            self._hook_slots[name] = (had_slot, original, wrapped)
            setattr(service, name, wrapped)
        original_commands = getattr(self._legacy, 'commands', None)
        if original_commands is not None:
            class ClosedCommands:
                def __getattr__(self, name):
                    if name in {'help', 'preset'}:
                        return lambda *args, **kwargs: '旧记忆命令正在交接，请使用TLS原生记忆中心。'
                    async def closed(*args, **kwargs):
                        return '旧记忆命令正在交接，请使用TLS原生记忆中心。'
                    return closed
            closed_commands = ClosedCommands()
            self._command_slot = (original_commands, closed_commands)
            self._legacy.commands = closed_commands
        routes = getattr(self.context, 'registered_web_apis', None)
        if type(routes) is not list:
            raise RuntimeError('normal AstrBot web route registry unavailable')
        for index, entry in enumerate(tuple(routes)):
            if (type(entry) is not tuple or len(entry) != 4
                    or not str(entry[0]).startswith('/' + LEGACY + '/page')):
                continue
            if getattr(entry[1], '__self__', None) is not getattr(self._legacy, 'page_api', None):
                raise RuntimeError('original memory page handler ownership changed')
            async def blocked_post(*args, **kwargs):
                from astrbot.api.web import error_response
                return error_response('旧记忆入口已临时封闭，正在交接TLS原生服务', status_code=409)
            replacement = (entry[0], blocked_post, entry[2], entry[3])
            routes[index] = replacement
            self._page_slots.append((entry, replacement))
        self._bridge = getattr(self._legacy, 'memory_companion', None)
        if self._bridge is None or getattr(self._bridge, '_plugin', None) is not service:
            raise RuntimeError('original memory bridge unavailable')
        self._bridge_before = {key: vars(self._bridge).get(key) for key in
            ('_active', '_emotion_producer_token', '_emotion_page_admin_token')}
        self._bridge.deactivate()
        self._bridge_after = {key: vars(self._bridge).get(key) for key in self._bridge_before}
        service._closing = True

    @staticmethod
    def _chain(task):
        codes, unknown = task_codes(task)
        if unknown:
            raise RuntimeError('memory coroutine await chain unknown')
        yield from codes

    def _scan_legacy(self):
        current, active, unknown = asyncio.current_task(), set(), 0
        tasks = asyncio.all_tasks()
        if len(tasks) > 4096:
            raise RuntimeError('memory task inventory exceeds bound')
        for task in tasks:
            if task is current or task.done():
                continue
            found, opaque = task_chain(task, self._source_codes)
            unknown += int(opaque)
            if found:
                active.add(task)
        frames = sys._current_frames()
        if len(frames) > 512:
            raise RuntimeError('memory thread inventory exceeds bound')
        threaded = 0
        try:
            for thread_id, frame in frames.items():
                if thread_id == threading.get_ident():
                    continue
                matched = False
                for _ in range(96):
                    if frame is None:
                        break
                    matched = matched or str(Path(frame.f_code.co_filename).resolve()) in self._source_paths
                    frame = frame.f_back
                else:
                    unknown += int(frame is not None)
                threaded += int(matched)
        finally:
            del frames
            try: del frame
            except UnboundLocalError: pass
        queued = 0
        executor = getattr(asyncio.get_running_loop(), '_default_executor', None)
        if executor is not None:
            if type(executor) is not ThreadPoolExecutor or type(executor._work_queue) is not SimpleQueue:
                raise RuntimeError('memory executor inventory unknown')
            queued = executor._work_queue.qsize()
            if type(queued) is not int or queued < 0:
                raise RuntimeError('memory executor queue unknown')
        self._drain = dict(tasks=len(active), threads=threaded, queued=queued, unknown=unknown)
        return active

    def _cancel_idle_dispatchers(self):
        service = self._legacy_service
        if service is None:
            return
        for name in DISPATCHERS:
            task = getattr(service, name, None)
            if task is not None and not task.done() and asyncio.sleep.__code__ in set(self._chain(task)):
                task.cancel()

    async def _drain_legacy(self, timeout=30.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if not self._source_current():
                raise RuntimeError('memory source changed during transition')
            self._cancel_idle_dispatchers()
            tasks = self._scan_legacy()
            if not any(self._drain.values()):
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError('original capture model or executor work has not drained')
            if tasks:
                await asyncio.wait(tasks, timeout=min(0.1, remaining))
            else:
                await asyncio.sleep(min(0.05, remaining))

    async def _release_slices(self):
        await self.integrations.restore_mc_summary()
        await self.integrations.stop_mc_profile()
        await self.integrations.stop_mc_relationship()
        await self.integrations.stop_mc_explicit()
        if self._legacy_runtime.explicit is not None:
            await self._legacy_runtime.explicit.wait_drained()
        state = self._legacy_runtime.status()
        for name in ('explicit', 'relationship', 'profile'):
            branch = state.get(name, {})
            if (branch.get('configured') is not False or branch.get('pending_captures') != 0
                    or branch.get('pending_native_operations') != 0):
                raise RuntimeError('original typed capture has not drained')
        await self.integrations.restore_mc_explicit()
        state = self._legacy_runtime.status()
        if any(state.get(name, {}).get('installed') is not False for name in ('explicit', 'relationship', 'profile')):
            raise RuntimeError('original typed capture slots remain installed')
        await self._legacy_runtime.restore_legacy()
        if self._legacy_runtime.status().get('fence_installed') is not False:
            raise RuntimeError('original final context slots remain installed')

    def _record_retirement(self):
        service = self._legacy_service
        if service is None or service._closed is not True or self._row().activated is not False:
            raise RuntimeError('normal original plugin termination is not confirmed')
        self._scan_legacy()
        if any(self._drain.values()):
            raise RuntimeError('original memory work remains after normal termination')
        setattr(self.context, RETIRED_SLOT, dict(schema='tls.mc.retired.r60.v1', pid=os.getpid(),
            context=self.context, owner=self._legacy, service=service,
            source_paths=tuple(self._source_paths), source_identities=dict(self._source_identities),
            source_codes=self._source_codes,
            flags=dict(self._saved_flags or {}), page_slots=list(self._page_slots)))
        self._old_off_confirmed = True

    def legacy_quiesced(self):
        try:
            row = self._row()
            if getattr(row, 'activated', False) is not False:
                return False
            record = getattr(self.context, RETIRED_SLOT, None)
            if type(record) is dict:
                service = record.get('service')
                return (record.get('schema') == 'tls.mc.retired.r60.v1'
                    and record.get('context') is self.context and record.get('pid') == os.getpid()
                    and service is not None and getattr(service, '_closed', None) is True
                    and getattr(getattr(service, 'store', None), '_closed', None) is True
                    and getattr(row, 'star_cls', None) in (None, record.get('owner')))
            # A fresh SDK boot does not instantiate disabled plugins. An
            # inactive row with an actual RAM instance is never treated as a
            # fresh boot or as evidence of completed in-process termination.
            if getattr(row, 'star_cls', None) is not None:
                return False
            module = getattr(row, 'module', None)
            modules = [module, sys.modules.get('data.plugins.' + LEGACY + '.main'), sys.modules.get(LEGACY + '.main')]
            if any(getattr(item, '_ACTIVE_BRIDGE', None) is not None for item in modules):
                return False
            for entry in getattr(self.context, 'registered_web_apis', ()):
                if str(entry[0]).startswith('/' + LEGACY + '/page'):
                    page = getattr(entry[1], '__self__', None)
                    old = getattr(getattr(page, 'plugin', None), 'service', None)
                    if old is not None and getattr(old, '_closed', None) is not True:
                        return False
            return True
        except Exception:
            return False

    def _companion_api(self):
        selected, _, api = native_companion(self.context)
        return api if selected else None

    async def _prepare_native(self, reconcile_previous=False):
        host = self.integrations._host()
        if host is None or host._closed:
            raise RuntimeError('current TLS Host required')
        directory = self._native_directory()
        record = getattr(self.context, NATIVE_SLOT, None)
        if reconcile_previous and (record is None or type(record) is dict and record.get('schema') == RETIREMENT_SCHEMA):
            retirement = NativeMCRetirement(self, directory)
            self._pre_anchor_report = retirement.inspect()
            if self._pre_anchor_report['eligible']:
                try:
                    result = await retirement.retire()
                    self._pre_anchor_report = dict(eligible=False, state='retired', **result)
                except RuntimeError as exc:
                    self._native_pending(str(exc))
            elif self._pre_anchor_report.get('reason') != 'pre_anchor_original_owner_not_found':
                self._native_pending(self._pre_anchor_report['reason'])
        await self._settle_native(directory)
        if self.adapter is not None and not self.adapter.closed:
            self._native_pending('previous_native_reference_unverified')
        config = self.plugin.config.get(CONFIG)
        if type(config) is not dict:
            raise RuntimeError('TLS memory configuration required')
        self._last_config = deepcopy(config)
        companion_api = self._companion_api()
        companion = NativeMemoryCompanion(self.context, config, data_dir=directory,
            plugin_root=Path(inspect.getfile(type(self.plugin))).resolve().parent,
            legacy_quiesced=self.legacy_quiesced, companion_api=companion_api)
        # Older releases have no lifecycle record. Visible same-store work
        # still blocks a bootstrap; never manufacture a recovery reference.
        if companion._work():
            self._native_pending('untracked_native_memory_work_pending')
        self._claim_native(directory, companion)
        companion.persist_config = self.persist_config
        companion.companion_api_getter = self._companion_api
        self.adapter = companion
        self.integrations.mc_full = companion
        record = self._native_record
        try:
            await companion.prepare()
        finally:
            # A partly prepared service must remain reachable if cleanup also
            # cannot finish; it is still the original adapter's responsibility.
            record['service'] = companion.service
        companion.service.persist_native_config = self.persist_config
        runtime = NativeOwnedMCContextRuntime(self.plugin, host, companion)
        self.runtime = runtime
        self.integrations.mc = runtime
        await runtime.activate()
        desired = self._saved_flags or self._flags()
        self._save({**desired, 'living_mc_context_native_enabled': True,
                    'living_mc_summary_native_enabled': True, FLAG: True})
        await companion.start_workers(context_ready=lambda: runtime.status()['active'] is True)
        companion.register_routes()
        self.phase, self.last_error = 'native', None
        self.generation += 1

    async def _undo_before_off(self):
        if self._old_off_attempted or self._legacy_service is None or self._legacy_service._closed:
            raise RuntimeError('original plugin turnoff outcome requires explicit restoration')
        service = self._legacy_service
        service._closing = self._prior_closing
        # The original source proof includes its actual core-tool method.
        # Restore exact tool slots while ordinary hooks/commands remain closed,
        # then re-install the earlier native slices before reopening events.
        for name in TOOLS:
            if name not in self._hook_slots:
                continue
            had_slot, original, wrapper = self._hook_slots[name]
            if vars(service).get(name) is not wrapper:
                raise RuntimeError('original tool changed before recovery')
            if had_slot:
                setattr(service, name, original)
            else:
                delattr(service, name)
        if self._saved_flags is not None:
            self._save(self._saved_flags)
        runtime = self._legacy_runtime
        if runtime is not None:
            self.integrations.mc = runtime
            await runtime.start()
        for name, (had_slot, original, wrapper) in self._hook_slots.items():
            if name in TOOLS:
                continue
            if vars(service).get(name) is not wrapper:
                raise RuntimeError('original hook changed before recovery')
            if had_slot:
                setattr(service, name, original)
            else:
                delattr(service, name)
        if self._command_slot is not None:
            original, replacement = self._command_slot
            if self._legacy.commands is not replacement:
                raise RuntimeError('original command fence changed before recovery')
            self._legacy.commands = original
        routes = self.context.registered_web_apis
        for original, replacement in self._page_slots:
            matches = [index for index, value in enumerate(routes) if value is replacement]
            if len(matches) != 1:
                raise RuntimeError('original page fence changed before recovery')
            routes[matches[0]] = original
        if self._bridge is not None and self._bridge_after is not None:
            if any(vars(self._bridge).get(key) is not value for key, value in self._bridge_after.items()):
                raise RuntimeError('original bridge changed before recovery')
            vars(self._bridge).update(self._bridge_before)
        service._ensure_lifecycle_maintenance_dispatcher()
        service._ensure_portrait_daily_dispatcher()
        service._ensure_wal_checkpoint_loop()
        self._hook_slots.clear(); self._page_slots.clear()
        self.phase = 'legacy_retained'

    async def activate(self, *, reconcile_previous=False):
        async with self._lock:
            if self.adapter is not None and self.adapter.active:
                if self._native_record is None or self._native_record is not getattr(self.context, NATIVE_SLOT, None):
                    self._native_pending('native_lifecycle_anchor_changed')
                return self.status()
            if self.phase in {'blocked', 'turnoff_unknown'}:
                raise RuntimeError('previous transition needs explicit status and restore')
            self._old_off_attempted = self._old_off_confirmed = False
            self._hook_slots.clear(); self._page_slots.clear()
            self._bridge = self._bridge_before = self._bridge_after = None
            self._command_slot = None
            self.phase, self.last_error = 'preparing', None
            try:
                if not self.legacy_quiesced():
                    raise RuntimeError('another memory executor is active or has unretired work')
                await self._prepare_native(reconcile_previous=reconcile_previous)
                return self.status()
            except NativeMCLifecyclePending:
                # Retain configured intent and the exact predecessor. This
                # is a waiting state, not a failed new installation.
                raise
            except BaseException as exc:
                self.last_error = type(exc).__name__
                self.last_error_sha256 = hashlib.sha256(str(exc).encode()).hexdigest()
                retained = getattr(self.context, NATIVE_SLOT, None)
                if (isinstance(exc, asyncio.CancelledError) and type(retained) is dict
                        and retained.get('schema') == RETIREMENT_SCHEMA
                        and retained.get('context') is self.context):
                    self.phase = 'waiting_native_predecessor'
                    raise
                if self.adapter is not None and not self.adapter.closed:
                    try:
                        await self._stop_locked(False)
                    except BaseException as close_error:
                        self.last_error += '/native_close:' + type(close_error).__name__
                    try:
                        self._save({FLAG: False})
                    except BaseException as save_error:
                        self.last_error += '/intent_save:' + type(save_error).__name__
                if not self._old_off_attempted and self._hook_slots:
                    try:
                        await self._undo_before_off()
                    except BaseException as restore_error:
                        self.last_error += '/recovery:' + type(restore_error).__name__
                        self.phase = 'blocked'
                else:
                    self.phase = 'turnoff_unknown' if self._old_off_attempted and not self._old_off_confirmed else 'blocked'
                raise

    async def start_if_configured(self):
        if self.plugin.config.get(FLAG, False) is not True:
            return self.status()
        if getattr(self._row(), 'activated', None) is True:
            self.phase = 'blocked'
            self.last_error = 'both_native_intent_and_original_active'
            return self.status()
        if not self.legacy_quiesced():
            self.phase = 'blocked'
            self.last_error = 'original_ram_not_proven_retired'
            return self.status()
        record = getattr(self.context, RETIRED_SLOT, None)
        if type(record) is dict:
            self._source_paths = set(record.get('source_paths', ()))
            self._source_identities = dict(record.get('source_identities', {}))
            self._source_codes = tuple(record.get('source_codes', ()))
            if not self._source_codes:
                self.phase, self.last_error = 'blocked', 'retired_original_source_code_inventory_missing'
                return self.status()
            self._scan_legacy()
            if any(self._drain.values()):
                self.phase, self.last_error = 'blocked', 'retired_original_has_inflight_work'
                return self.status()
        try:
            return await self.activate()
        except NativeMCLifecyclePending:
            # Other TLS services can initialize. A later explicit activate
            # uses the same original owner to finish closing, then starts fresh.
            return self.status()

    async def _stop_locked(self, persist):
        record = getattr(self.context, NATIVE_SLOT, None)
        if persist and record is not None and record is not self._native_record:
            await self._settle_native(self._native_directory())
        if self.adapter is not None:
            self._last_enabled_flags = self._flags()
            self.adapter.begin_stop()
            if self._native_record is not None:
                self._native_record['stopping'] = True
            self.phase = 'draining_native'
            try:
                if self.runtime is not None:
                    await self.runtime.close()
                await self.adapter.close()
                service = self.adapter.service
                if not self.adapter.closed or service is not None and (
                        not service._closed or not service.store._closed):
                    raise RuntimeError('native memory store close not confirmed')
                self._release_native()
            except BaseException as exc:
                self.phase, self.last_error = 'drain_pending', type(exc).__name__
                raise
        if persist:
            self._save({FLAG: False})
        self.phase = 'native_stopped' if self.adapter is not None else 'inactive'
        return self.status()

    async def stop(self):
        async with self._lock:
            return await self._stop_locked(True)

    async def close(self):
        """TLS reload ends this lifecycle, retaining the persisted native owner."""
        async with self._lock:
            return await self._stop_locked(False)

    async def restore_legacy(self):
        raise RuntimeError('legacy plugin restoration is retired; TLS is a standalone plugin')

    def status(self):
        try:
            original_active = getattr(self._row(), 'activated', False)
        except Exception:
            original_active = None
        adapter = self.adapter.status() if self.adapter is not None else None
        runtime = self.runtime.status() if self.runtime is not None else None
        return dict(backend='tls_native_memory_companion_full', phase=self.phase,
            execution_model='standalone_tls', original_installation_required=False,
            active=bool(adapter and adapter.get('active') is True and runtime and runtime.get('active') is True
                        and original_active is False and self._native_record is not None
                        and getattr(self.context, NATIVE_SLOT, None) is self._native_record),
            configured=self.plugin.config.get(FLAG, False) is True,
            native_lifecycle_retained=getattr(self.context, NATIVE_SLOT, None) is not None,
            pre_anchor_retirement=dict(self._pre_anchor_report) if self._pre_anchor_report else None,
            generation=self.generation, original_plugin_active=original_active,
            old_off_attempted=self._old_off_attempted, old_off_confirmed=self._old_off_confirmed,
            original_source_pinned=bool(self._source_identities), drain=dict(self._drain),
            native=adapter, context=runtime, last_error=self.last_error, last_error_sha256=self.last_error_sha256,
            configuration=CONFIG, original_configuration_preserved=True,
            original_history_path_preserved=True, historical_identity_remap=False,
            database_snapshot_restore=False, automatic_legacy_restart=False)


_LEGACY_SOURCE_HASHES = {
    'core/__init__.py': 'ab54c868879424cef69c75f28bc6f8c4892a60719feb7c5d30d528497f55dae1',
    'core/affect_modulation.py': 'b133ad37e578c1d7bf50419c277bdc3c357dcbb8c66a89779863c2b57335e967',
    'core/astrbot_compat.py': '369f028634d0244b55ffcb5597b3cde97bd5e741e3fe5cefff67ae65e4bb7e77',
    'core/audit.py': '6f21c5cc8f4c29c219edc578f990c2c1bebdd8f7ee113cdfc7dd9df30f276a18',
    'core/bot_personal_consumer.py': 'fe62f1c20c9aa89b117d9481184559bf334d552e16e031c2eed63ca91cfa8853',
    'core/bot_personal_contract.py': 'c6afa7944cbe6cd8308bbf815aefa320f2ab770f9be9f78cc1e536d9d9e18fc4',
    'core/bot_personal_dto.py': '47de1a6451543c9e7d6f1bed03a3069b93ba0b34f4814783782f78b79ac237cf',
    'core/bridge.py': '75224e363ed5179e6dc1852c29ef22dc0d123f829ccb26e4c2378c5c77172b5c',
    'core/capability_probe.py': 'bd6961ba37fa1480bd61bea8f6cf6cbf4e724ddf520b5dea4f73f504233fc8b5',
    'core/chat_import.py': '233056e0f99008fb0bd6a5dce1cafe1ca7bf210067298f13cc77dc258be7c39d',
    'core/classifier.py': 'e0064564ad7d3dba664adc8f1a448dcb70e076ca54f71b531ff5d7402ff815ff',
    'core/commands.py': '74e9449368f46213decb57b00c5f10761ce6f2621559072a5d2a1d5466ed5407',
    'core/config.py': '0f277b5b294b8f9df9430c7db198b3df02ac3e40ac5ac836f23d31ae8a928b89',
    'core/context_consumer.py': '7575c0954fda4519c9d1c1c7083e123f1bb613f246209aed46d413b11fc9da31',
    'core/context_orchestrator.py': 'e806b5efc59dc9940d30180d9113459dd4f41878129893098ae19aa281a9dd51',
    'core/coordination_status.py': 'be4f89e9e5a996dda49e2436c602dcec436681b71500490ee6b60354abdcdc66',
    'core/emotion_event_contract.py': '3a1069af7dc37a0948ff8b00134be590d33bb0b56a8b9c1bc8c95f4cea34b148',
    'core/emotion_targeting.py': '341f3c705a70eb5474c1747558a56aa9babe6255121684df1482fa362e5b818c',
    'core/identity.py': 'bd68f2eaa61d9a75282033271a504842b1a2486bd09a833ef25f8f6ffb2e6b05',
    'core/importance.py': '283f8befb943fb0f9fcfe312319b0329993b05e355e96e9da892d341fb8a9aed',
    'core/injection.py': '960b2b5b32cecfca0013fc7be8474987d55732daec0b5e3ba2d437b5e97aa85c',
    'core/memory_atom.py': 'a3c4b7db9c918c058999e3fa9fbacaed413bcddb27f8981538773e40d3668be3',
    'core/memory_lifecycle.py': '449125c4bad594e0731b54b52f55a5324e2a35e8ac89ca73f6ef09d1abf6e3f6',
    'core/migration_livingmemory.py': 'bb5c0e7c67b1f5f9738051fe13404ba05e552e85045a92b4c6c013f083db602c',
    'core/migration_outbox.py': '6b24dca452667e3b33d8054462299d41ecddabd321b8b7d50f0e08ea03615779',
    'core/models.py': '89f1aaad1cea14e635119642ec6d2eb3690a5ae261dd345ce0e4c2722ec7e7a3',
    'core/namespace.py': '827be342cf9e56595b69301c13d025b64fc4bc104f158b2d7d48b9080095bbd7',
    'core/namespace_capability.py': '710d39746051e002985591fddc343bed47fe37fd55d308cbeab11f4f9aecb4b2',
    'core/operations.py': '1b6e4ecab9a66787e16ed97488c09dddaac508dfd61c2aab425a24ea6483da5a',
    'core/p6_four_package_manifest.py': '770511167ddcc5e246fa3b68cc7bc938d6e954de37916431ffdef059fc6a03fa',
    'core/p6_readonly_projection.py': '7f92e607e7ed01dc0290cc690bdd8265f36ccf5460f22ede297d70d4674fdac3',
    'core/person_context_contract.py': '3ba0eeb7c4cfd0b146db8eabf089eff1102dead2b6dec6ec1d7afa43027f7ba3',
    'core/person_projection.py': '49f2d857d90b0f4db9ddeaa024ca1f50cfea7d53818702f5fc918e7c2ad207b2',
    'core/portrait.py': '67d8dd116024975e48b30c5031339aeab31bc093532e5014c81621030f43d4b4',
    'core/portrait_namespace.py': 'c43c96b2b5178ebdb78d533397bf8097ce5eb88270e1bd6ae2cfce84d0631d07',
    'core/portrait_service.py': '25a03c38a779eb35854f7c5ed41ac67e8447cd9dd192e951a4245a058b29f849',
    'core/profile_api.py': '97727efd15c59c49113825c410913a8b89601f059f4a22c76715fbe65e22106f',
    'core/profile_quality.py': 'd07efef2ceb94a4951c04e5e97ca737b5a3779d068fb793bd6035e1e655583e3',
    'core/provenance.py': '603f963361da35e685c7e65d0aeef22881c2317e95441d4a694c210341bc3bf2',
    'core/provenance_store.py': '65b4c8ab8e3042d4b584e8e7888c6690442958529a59b8352370e0eb34485c59',
    'core/qq_history.py': 'f1ea6a4049121bd99adeb80438dd145c49f0ac2f436464748397f8003bb3f4d2',
    'core/reply_chain.py': '8134a1d7334bc1ce35d1aeab9118ccae182b690c7dc6d54ec4b5d8c3b495d0e0',
    'core/retrieval.py': 'e343a1b65161a01f4ed064bda6da2118004d9dd12bc46a7662668afd7ee7f555',
    'core/scoped_domain_contract.py': 'b200228d67dfc3fc64106fc7bb151c4f9cbb0adb55643cf635d65bdb6d25ce53',
    'core/scoped_store.py': 'ea8df6b06f3763be27caf55c324c0e36a088100b5684c7f7a91a40d9e9c172fc',
    'core/sensitive_data.py': '96509372de458483cd3d22be5419a110107b197abe640c7563fbe5e54bdd2b2c',
    'core/service.py': '6b1c9b52cc918cde66cfa14635720bfdde80332defff51278829030496d7fad2',
    'core/store.py': 'a28468782823c0b2255ed2491ac14f6f2af44e7b00e6f17f85278d3ddc8327df',
    'core/summarizer.py': 'c0e554613ae9b336a7f7e95bb9c9322268eeef2c81ea5a9f68709131d37aca80',
    'core/time_intent.py': 'f60bc109d6276357146e59317feab584cf28f78c017aa0204aed97adb592cc8a',
    'core/turn_signal.py': '983a536e9dd9b20b1e644830d675b35cf2e2830588e4f9435314d8feaaf1f14d',
    'core/visibility.py': 'd75ca089517d327e532745fdbca002b599095f6715d212a88164af8f3f17125b',
    'main.py': '4722e5a4cbe2acc7b9fb9a79b46ea54d7f72300f25af8bf2768091db3b844af7',
    'page_api.py': '54177bb5948ff41506ae8d505d3159f4c2b5753f3a5722d86839564f3190f0da',
    'unified_profile_contract.py': 'aca1475dbe471f3050cd862317a4b461ef61089b78149967987374d453d205e6',
}

