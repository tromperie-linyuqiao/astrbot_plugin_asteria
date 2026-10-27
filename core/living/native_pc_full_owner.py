"""One PC business owner, preserving the original files and memo binding.

Construction is inert. Real SDK hooks/tools/write routes are fenced before the
old schedulers drain naturally. Normal plugin disable occurs only after that
barrier. Source/configuration identities and the real old memo binding survive
in the existing TLS configuration; no old task/data/UNKNOWN record is erased.
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
import re
import sys
import threading
from types import MethodType

from .models import canonical, private_scope, scope_key
from .native_legacy_companion_inspection import inspect_legacy_companion
from .native_pc_service import NativePCService


LEGACY = 'astrbot_plugin_private_companion'
FLAG = 'living_pc_full_native_enabled'
CONFIG = 'living_pc'
BINDING = 'living_pc_binding_state'
RETIRED_SLOT = '_tls_native_pc_retired_owner'
_HEX = re.compile(r'[a-f0-9]{64}\Z')
_MANIFEST = Path(__file__).resolve().parent / 'native_pc_business/SOURCE-MANIFEST.json'


class NestedConfig(dict):
    """The mature PC config interface, persisted exclusively inside TLS."""
    def __init__(self, owner, values):
        super().__init__(deepcopy(values))
        self.owner = owner

    def save_config(self):
        return self.owner.persist_config(self)


class NativePCFullOwner:
    def __init__(self, integrations):
        self.integrations = integrations
        self.plugin, self.context = integrations.plugin, integrations.context
        self.service = None
        self.active = False
        self.binding_state = None
        self.send_chain = self.platform_action = None
        self.phase, self.last_error, self.generation = 'inactive', None, 0
        self.last_error_sha256 = None
        self._lock = asyncio.Lock()
        self._legacy = self._legacy_module = self._source_root = None
        self._source_paths, self._source_identities = set(), {}
        self._config_path = self._config_identity = self._config_sha = None
        self._legacy_enabled = self._legacy_relationship_stopping = None
        self._legacy_stop_set = self._bridge_stop_set = None
        self._bridge = self._bridge_stopping = None
        self._hook_slots, self._tool_slots, self._page_slots = [], [], []
        self._method_slots = {}
        self._legacy_flags = {}
        self._last_config = self._retired_config = None
        self._old_off_attempted = self._old_off_confirmed = False
        self._pending = dict(legacy_candidates=0, unknown=0, sending=0, bridge_attempts=0)
        self._drain = dict(tasks=None, threads=None, queued=None, unknown=None)
        self._last_inspection = None
        self._bound_source = None

    def _rows(self):
        return [row for row in self.context.get_all_stars()
            if getattr(row, 'root_dir_name', None) == LEGACY]

    def _row(self):
        rows = self._rows()
        if len(rows) != 1:
            raise RuntimeError('original PC registry is not unique')
        return rows[0]

    @staticmethod
    def _fingerprint(path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('original PC source/configuration missing or linked')
        st = path.stat()
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns

    def _pin(self, root):
        if root.name != LEGACY or root.is_symlink():
            raise RuntimeError('unexpected original PC source directory')
        manifest = json.loads(_MANIFEST.read_bytes())
        if manifest.get('schema') != 'tls.native.pc.business.source.v1':
            raise RuntimeError('native PC source manifest unavailable')
        modules = manifest.get('modules')
        if not isinstance(modules, dict) or not 60 <= len(modules) <= 128:
            raise RuntimeError('native PC fixed source scope changed')
        identities = {}
        for relative, proof in modules.items():
            if (not isinstance(relative, str) or Path(relative).is_absolute()
                    or '..' in Path(relative).parts or not relative.endswith('.py')):
                raise RuntimeError('PC source manifest path invalid')
            expected = proof.get('original_sha256')
            if (relative in {'__init__.py', 'native_runtime_bindings.py'}
                    and proof.get('source_kind') == 'generated_tls'
                    and proof.get('reference') == 'new TLS native adapter' and expected is None):
                # These are real new TLS adapters, not alleged old source.
                # NativePCService.native_source_current owns their live proof.
                continue
            if not isinstance(expected, str) or _HEX.fullmatch(expected) is None:
                raise RuntimeError('original PC source proof missing')
            path = root / relative
            before = self._fingerprint(path)
            raw = path.read_bytes()
            if len(raw) > 3 * 1024**2 or hashlib.sha256(raw).hexdigest() != expected:
                raise RuntimeError('original PC production source differs from migrated source')
            if self._fingerprint(path) != before:
                raise RuntimeError('original PC source changed during pinning')
            identities[str(path.resolve())] = before
        if len(identities) != 76:
            raise RuntimeError('exact original PC production source scope changed')
        self._source_root = root
        self._source_paths, self._source_identities = set(identities), identities
        path = self.integrations.data_dir.parent.parent / 'config' / (LEGACY + '_config.json')
        before = self._fingerprint(path)
        raw = path.read_bytes()
        if len(raw) > 8 * 1024**2 or not isinstance(json.loads(raw), dict) or self._fingerprint(path) != before:
            raise RuntimeError('original PC configuration changed or is invalid')
        self._config_path, self._config_identity = path, before
        self._config_sha = hashlib.sha256(raw).hexdigest()
        return hashlib.sha256((root / 'main.py').read_bytes()).hexdigest(), json.loads(raw)

    def _source_current(self):
        try:
            return (bool(self._source_identities)
                and self._config_path is not None
                and all(self._fingerprint(Path(name)) == proof for name, proof in self._source_identities.items())
                and self._fingerprint(self._config_path) == self._config_identity)
        except (OSError, RuntimeError, TypeError):
            return False

    def _save(self, changes):
        with self.integrations._config_lock:
            before = {name: (name in self.plugin.config, deepcopy(self.plugin.config.get(name)))
                for name in changes}
            try:
                for name, value in changes.items():
                    self.plugin.config[name] = deepcopy(value)
                self.plugin.config.save_config()
            except BaseException:
                for name, (present, value) in before.items():
                    if present:
                        self.plugin.config[name] = value
                    else:
                        self.plugin.config.pop(name, None)
                raise

    def persist_config(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('complete native PC configuration required')
        value = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        self._save({CONFIG: value})
        self._last_config = deepcopy(value)
        return dict(ok=True, configuration=CONFIG, legacy_config_written=False)

    def _capture_old(self):
        row = self._row()
        owner = getattr(row, 'star_cls', None)
        if getattr(row, 'activated', None) is not True or owner is None:
            raise RuntimeError('current active original PC instance required')
        module = getattr(row, 'module', None) or sys.modules.get(type(owner).__module__)
        source = getattr(module, '__file__', None)
        if not isinstance(source, str) or getattr(module, '_private_companion_plugin', None) is not owner:
            raise RuntimeError('original PC module owner backreference changed')
        source_sha, file_config = self._pin(Path(source).resolve().parent)
        raw = getattr(owner, 'config', None)
        if not isinstance(raw, dict):
            raise RuntimeError('complete original PC RAM configuration unavailable')
        # AstrBot may merge schema defaults in RAM. Preserve the actual loaded
        # effective object while retaining a separate exact old file hash.
        runtime_config = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        lock = getattr(owner, '_data_lock', None)
        if not isinstance(lock, asyncio.Lock):
            raise RuntimeError('original PC data-lock barrier unavailable')
        memo = getattr(self.plugin, '_native_memo_tool_router', None)
        if (memo is None or getattr(memo,'context',None) is not self.context
                or memo._ensure_child() is not True):
            raise RuntimeError('current physical memo runtime binding is unavailable')
        bridge = getattr(memo, 'bridge', None)
        binding = getattr(bridge, 'binding_sha256', None)
        if not isinstance(binding, str) or _HEX.fullmatch(binding) is None:
            raise RuntimeError('actual current memo binding must be captured before PC retirement')
        self.binding_state = dict(binding_sha256=binding, source_kind='retired_legacy_pc',
            legacy_source_sha256=source_sha, legacy_config_sha256=self._config_sha)
        self._legacy, self._legacy_module = owner, module
        self._retired_config = deepcopy(runtime_config)
        self._last_inspection = inspect_legacy_companion(self.context, inspect_tasks=True)
        if self._last_inspection.get('state') != 'observed':
            raise RuntimeError('current original PC task/instance inventory unknown')
        self._save({CONFIG: runtime_config, BINDING: self.binding_state})

    @staticmethod
    def _closed_callback(callback, *, tool=False):
        if inspect.isasyncgenfunction(callback):
            async def generator(*args, **kwargs):
                if False:
                    yield None
            return generator
        if inspect.iscoroutinefunction(callback):
            async def coroutine(*args, **kwargs):
                return json.dumps(dict(ok=False, code='pc_owner_transition')) if tool else None
            return coroutine
        def function(*args, **kwargs):
            return json.dumps(dict(ok=False, code='pc_owner_transition')) if tool else None
        return function

    def _freeze_admission(self):
        if self._legacy is None or not self._source_current() or self._hook_slots or self._tool_slots:
            raise RuntimeError('unfenced current original PC required')
        owner = self._legacy
        self._legacy_enabled = getattr(owner, 'enabled', None)
        self._legacy_relationship_stopping = getattr(owner, '_relationship_analysis_stopping', None)
        if type(self._legacy_enabled) is not bool:
            raise RuntimeError('original PC runtime enable state unknown')
        stop = getattr(owner, '_stop_event', None)
        if not isinstance(stop, asyncio.Event):
            raise RuntimeError('original PC scheduler stop event missing')
        self._legacy_stop_set = stop.is_set()
        bridge = getattr(owner, '_proactive_chat_runtime_bridge', None)
        if bridge is not None:
            self._bridge = bridge
            self._bridge_stopping = getattr(bridge, '_stopping', None)
            bridge_stop = getattr(bridge, '_stop_event', None)
            if not isinstance(bridge_stop, asyncio.Event) or type(self._bridge_stopping) is not bool:
                raise RuntimeError('original PC bridge watcher state missing')
            self._bridge_stop_set = bridge_stop.is_set()
        from astrbot.core.star.star_handler import star_handlers_registry
        handlers = getattr(star_handlers_registry, '_handlers', None)
        if not isinstance(handlers, list) or len(handlers) > 4096:
            raise RuntimeError('normal SDK hook registry unavailable')
        module = type(self._legacy).__module__
        for metadata in handlers:
            if getattr(metadata, 'handler_module_path', None) != module:
                continue
            original = metadata.handler
            wrapped = self._closed_callback(original)
            metadata.handler = wrapped
            self._hook_slots.append((metadata, original, wrapped))
        manager = self.context.get_llm_tool_manager()
        tools = getattr(manager, 'func_list', None)
        if not isinstance(tools, list) or len(tools) > 4096:
            raise RuntimeError('normal SDK tool registry unavailable')
        for item in tools:
            if getattr(item, 'handler_module_path', None) != module:
                continue
            original = item.handler
            wrapped = self._closed_callback(original, tool=True)
            item.handler = wrapped
            self._tool_slots.append((item, original, wrapped))
        if not self._hook_slots or not self._tool_slots:
            raise RuntimeError('complete actual original hook/tool entrypoints were not found')
        # The independent proactive plugin has an injected PC preflight. Close
        # just that PC admission, not its timer or already-running send. Its
        # normal refusal branch retains/reschedules its own task.
        name = '_prepare_proactive_chat_bridge'
        original = getattr(self._legacy, name, None)
        if callable(original):
            async def closed_bridge_preflight(_owner, *args, **kwargs):
                return dict(enabled=True, allowed=False, reason='pc_owner_transition')
            replacement = MethodType(closed_bridge_preflight, self._legacy)
            self._method_slots[name] = (name in vars(self._legacy), original, replacement)
            setattr(self._legacy, name, replacement)
        registry = getattr(self.context, 'registered_web_apis', None)
        if type(registry) is not list:
            raise RuntimeError('normal SDK web registry unavailable')
        for index, entry in enumerate(tuple(registry)):
            if (not isinstance(entry, tuple) or len(entry) != 4
                    or not str(entry[0]).startswith('/' + LEGACY + '/page')
                    or not any(str(method).upper() != 'GET' for method in entry[2])):
                continue
            async def closed_post(*args, **kwargs):
                from astrbot.api.web import error_response
                return error_response('旧陪伴业务正在交接，请使用 TLS 原生入口。', status_code=409)
            replacement = (entry[0], closed_post, entry[2], entry[3])
            registry[index] = replacement
            self._page_slots.append((entry, replacement))
        owner.enabled = False
        owner._relationship_analysis_stopping = True
        stop.set()  # wake the idle scheduler; do not cancel a model or send
        if bridge is not None:
            bridge_stop = getattr(bridge, '_stop_event', None)
            bridge._stopping = True
            bridge_stop.set()

    @staticmethod
    def _chain(task):
        value, seen = task.get_coro(), set()
        for _ in range(96):
            if value is None or id(value) in seen:
                return
            seen.add(id(value))
            code = getattr(value, 'cr_code', None) or getattr(value, 'gi_code', None)
            if code is not None:
                yield code
            value = getattr(value, 'cr_await', None) or getattr(value, 'gi_yieldfrom', None)
        if value is not None:
            raise RuntimeError('PC await chain exceeds inspection bound')

    def _scan(self, paths):
        current, owned = asyncio.current_task(), set()
        tasks = asyncio.all_tasks()
        if len(tasks) > 4096:
            raise RuntimeError('PC task inventory exceeds bound')
        for task in tasks:
            if task is not current and not task.done() and any(
                    str(Path(code.co_filename).resolve()) in paths for code in self._chain(task)):
                owned.add(task)
        frames = sys._current_frames()
        if len(frames) > 512:
            raise RuntimeError('PC thread inventory exceeds bound')
        threaded = unknown = 0
        try:
            for ident, frame in frames.items():
                if ident == threading.get_ident():
                    continue
                matched = False
                for _ in range(96):
                    if frame is None:
                        break
                    matched = matched or str(Path(frame.f_code.co_filename).resolve()) in paths
                    frame = frame.f_back
                else:
                    unknown += int(frame is not None)
                threaded += int(matched)
        finally:
            del frames
            try:
                del frame
            except UnboundLocalError:
                pass
        queued = 0
        executor = getattr(asyncio.get_running_loop(), '_default_executor', None)
        if executor is not None:
            if type(executor) is not ThreadPoolExecutor or type(executor._work_queue) is not SimpleQueue:
                raise RuntimeError('PC executor queue cannot be inspected')
            queued = executor._work_queue.qsize()
            if type(queued) is not int or queued < 0:
                raise RuntimeError('PC executor queue inventory invalid')
        self._drain = dict(tasks=len(owned), threads=threaded, queued=queued, unknown=unknown)
        return owned

    def _pending_legacy(self, scope=None):
        owner = self._legacy
        data = getattr(self.service, 'data', None) if self.service is not None else getattr(owner, 'data', None)
        if not isinstance(data, dict):
            raise RuntimeError('original PC durable task inventory unavailable')
        users = data.get('users', {})
        if not isinstance(users, dict) or len(users) > 4096:
            raise RuntimeError('original PC user-task inventory unknown')
        user_id = private_scope(scope)['user_id'] if scope is not None else None
        candidates = unknown = sending = 0
        # Exact original proactive.py contract: the global candidate pool is a
        # list and _pending_candidate_status uses these six values.
        pool = data.get('proactive_candidate_pool', [])
        if not isinstance(pool, list) or len(pool) > 4096:
            raise RuntimeError('original PC candidate inventory unknown')
        for item in pool:
            if not isinstance(item, dict):
                raise RuntimeError('original PC candidate shape unknown')
            target = str(item.get('user_id') or item.get('target_user_id') or '')
            if user_id is not None and target and target != user_id:
                continue
            state = str(item.get('status') or '').strip().lower()
            candidates += state in {'accepted', 'deferred', 'queued', 'pending', 'unknown', ''}
            unknown += (state in {'unknown', 'quarantined', 'delivery_unknown'}
                or item.get('delivery_unknown') is True or item.get('tls_handoff_hold') is True)
        for key, row in users.items():
            if not isinstance(row, dict) or user_id is not None and str(key) != user_id:
                continue
            sending += row.get('proactive_sending') is True
            candidates += bool(row.get('planned_candidate_id'))
            retry = row.get('pending_proactive_send_retry')
            if retry:
                if not isinstance(retry, dict):
                    raise RuntimeError('original PC retry ledger shape unknown')
                candidates += 1
                unknown += retry.get('unknown') is True or retry.get('state') == 'unknown'
        bridge = getattr(owner, '_proactive_chat_runtime_bridge', None) if owner is not None else None
        attempts = getattr(bridge, '_open_attempts', {}) if bridge is not None else {}
        if not isinstance(attempts, dict) or len(attempts) > 256:
            raise RuntimeError('original PC bridge attempt inventory unknown')
        for item in attempts.values():
            if isinstance(item, dict):
                unknown += item.get('delivery_unknown') is True or item.get('phase') == 'delivery_unknown'
        result = dict(legacy_candidates=candidates, unknown=unknown, sending=sending,
            bridge_attempts=len(attempts))
        if scope is None:
            self._pending = result
        return result

    async def _drain_old(self, timeout=30):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if not self._source_current():
                raise RuntimeError('original PC source/configuration changed during handoff')
            self._last_inspection = inspect_legacy_companion(self.context, inspect_tasks=True)
            inspected = self._last_inspection
            counts = inspected.get('counts', {})
            if (inspected.get('state') != 'observed' or any(counts.get(name, 1) for name in
                    ('uninspectable_tasks', 'truncated_await_chains', 'unattributed_sensitive_tasks'))):
                raise RuntimeError('original PC task ownership inspection is incomplete')
            tasks = self._scan(self._source_paths)
            pending = self._pending_legacy()
            if not any(self._drain.values()) and not pending['sending'] and not pending['bridge_attempts']:
                async with self._legacy._data_lock:
                    if not self._source_current():
                        raise RuntimeError('original PC changed at data-lock barrier')
                    self._pending_legacy()
                return
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                raise RuntimeError('original PC model/send/thread work remains; no cancellation or new writer')
            if tasks:
                await asyncio.wait(tasks, timeout=min(.1, left))
            else:
                await asyncio.sleep(min(.05, left))

    def _record_retirement(self):
        row = self._row()
        owner = self._legacy
        if (getattr(row, 'activated', None) is not False
                or getattr(self._legacy_module, '_private_companion_plugin', None) is not None
                or not getattr(owner, '_stop_event', asyncio.Event()).is_set()):
            raise RuntimeError('normal original PC retirement is not confirmed')
        self._scan(self._source_paths)
        pending = self._pending_legacy()
        if any(self._drain.values()) or pending['sending'] or pending['bridge_attempts']:
            raise RuntimeError('original PC operations remain after normal disable')
        record = dict(schema='tls.pc.retired.r60.v1', pid=os.getpid(), context=self.context,
            owner=owner, module=self._legacy_module, source_paths=tuple(self._source_paths),
            source_identities=dict(self._source_identities), config_path=self._config_path,
            config_identity=self._config_identity, binding_state=dict(self.binding_state),
            original_config=deepcopy(self._retired_config))
        setattr(self.context, RETIRED_SLOT, record)
        self._old_off_confirmed = True

    def legacy_closed(self):
        try:
            row = self._row()
            if getattr(row, 'activated', None) is not False or not self._source_current():
                return False
            record = getattr(self.context, RETIRED_SLOT, None)
            if isinstance(record, dict):
                owner = record.get('owner')
                return (record.get('schema') == 'tls.pc.retired.r60.v1'
                    and record.get('context') is self.context and record.get('pid') == os.getpid()
                    and record.get('binding_state') == self.binding_state
                    and getattr(row, 'star_cls', None) in (None, owner)
                    and getattr(record.get('module'), '_private_companion_plugin', None) is None
                    and getattr(owner, '_stop_event', asyncio.Event()).is_set()
                    and (not isinstance(getattr(owner, '_task', None), asyncio.Task) or owner._task.done())
                    and not getattr(getattr(owner, '_proactive_chat_runtime_bridge', None), '_open_attempts', {}))
            # On a fresh SDK boot a disabled plugin must have no live RAM
            # instance/bridge or stale registered old write route.
            if getattr(row, 'star_cls', None) is not None:
                return False
            module = getattr(row, 'module', None)
            if module is not None and getattr(module, '_private_companion_plugin', None) is not None:
                return False
            return not any(str(entry[0]).startswith('/' + LEGACY + '/page')
                for entry in getattr(self.context, 'registered_web_apis', ()))
        except Exception:
            return False

    def _host(self):
        host = self.integrations._host()
        if host is None or host._closed or not getattr(host.runtime, 'active', False):
            raise RuntimeError('current TLS Host required')
        return host

    def _authorize(self, operation, scope):
        try:
            scope = private_scope(scope)
            if (not self.active or self.plugin.config.get(FLAG) is not True or not self.legacy_closed()
                    or self._host().authorized_scope(scope) is not True):
                return False
            if operation in {'model', 'send', 'platform_action'}:
                pending = self._pending_legacy(scope)
                # Old, unsent candidate definitions are retained but never
                # selected by the native future-plan producers. They do not
                # prevent unrelated new sourced work after the old executor
                # is physically retired. In-flight/UNKNOWN effects still hold.
                if any(pending[key] for key in ('unknown','sending','bridge_attempts')):
                    return False
            return True
        except Exception:
            return False

    async def _send(self, scope, umo, chain, metadata):
        if not self._authorize('send', scope) or not callable(self.send_chain):
            return dict(state='blocked', reason='native_pc_send_authority_or_adapter_unavailable')
        value = self.send_chain(scope, umo, chain, metadata)
        return await value if inspect.isawaitable(value) else value

    def _music_library_view(self, event=None):
        """Operation-local native metadata read, never a new QQ identity lease."""
        from .native_music_library import NativeMusicLibrary
        host = self._host(); runtime = host.runtime; service = self.service
        library = getattr(runtime, 'music_library', None)
        if (service is None or not isinstance(library, NativeMusicLibrary) or not library.active
                or library.journal is not host.journal or getattr(runtime, 'journal', None) is not host.journal):
            raise PermissionError('native music metadata source unavailable')
        if event is None:
            scope = private_scope(service._tls_primary_scope)
            source = service._tls_source
            if (not isinstance(source, dict) or source.get('source') != 'genuine_inbound_sdk_selection'
                    or not source.get('event_id') or not source.get('persona_id')):
                raise PermissionError('genuine current music context required')
        else:
            session = str(getattr(event, 'unified_msg_origin', '') or '')
            scope = private_scope(host.presence.peek_scope_for_session(session))
            if (scope['session_id'] != session or not event.is_private_chat() or event.get_group_id()
                    or str(event.get_sender_id() or '') != scope['user_id']
                    or str(event.get_self_id() or '') != scope['bot_id']):
                raise PermissionError('actual music event differs from its scope')

        revision_checks = []
        def generation(target):
            from .native_music_library import NAMESPACE
            row = library.journal._db.execute('SELECT COUNT(*),COALESCE(SUM(revision),0) FROM checkpoints WHERE namespace=? AND scope=?',
                (NAMESPACE, scope_key(target))).fetchone()
            return tuple(row)
        def unchanged():
            with library.journal._lock:
                library.journal._ensure_open()
                return all(generation(target) == expected for target, expected in revision_checks)

        def current():
            try:
                return (self.active and self.service is service and service.active
                    and service._tls_music_library_reader is not None and self._host() is host
                    and host.runtime is runtime and runtime.music_library is library
                    and library.active and library.journal is host.journal and not host.journal._closed
                    and self._authorize('hook', scope)
                    and (event is None or host.presence.peek_scope_for_session(scope['session_id']) == scope)
                    and unchanged())
            except (AttributeError, TypeError, ValueError, RuntimeError):
                return False

        def source_configured(target):
            sessions = self.plugin._cfg('living_memory_sessions', [])
            return (self.plugin._cfg('living_memory_backend', 'legacy') == 'native'
                and type(sessions) is list and all(isinstance(item, str) for item in sessions)
                and (not sessions or target['session_id'] in sessions))

        def read(target, allowed):
            if not source_configured(target) or allowed() is not True:
                raise PermissionError('music source read permission unavailable')
            reader = NativeMusicLibrary(library.journal, authorize=lambda candidate:
                candidate == target and source_configured(target) and allowed() is True, clock=library.clock)
            try:
                with library.journal._lock:
                    rows = reader.export(target)['records']
                    revision_checks.append((dict(target), generation(target)))
                    return rows
            finally:
                reader.stop()

        target, permitted, source_kind = scope, current, 'current_scope'
        records = read(target, permitted)
        if not records and scope['platform'] == scope['bot_id'] == 'webchat':
            from .chat_identity import identity_service
            from .chat_workspace import ChatWorkspace
            origin = scope['session_id'].split(':', 2)[-1]
            prefix = 'webchat!' + scope['user_id'] + '!'
            if not origin.startswith(prefix):
                raise PermissionError('actual APP music session required')
            session_id = origin[len(prefix):]; links = identity_service(self.plugin)
            row = links.get(scope['user_id'], session_id)
            if (not row or row.get('app_scope') != scope or not row.get('app_persona')
                    or row['qq_scope'].get('character_id') != scope['character_id']):
                raise PermissionError('confirmed APP music read binding unavailable')
            target = private_scope(row['qq_scope'])
            def linked_current():
                return (current() and links.current() is True
                    and links.get(scope['user_id'], session_id) == row
                    and ChatWorkspace(links).settings(scope['user_id'], session_id)['values']['shared_memory'] is True)
            permitted, source_kind = linked_current, 'explicit_confirmed_link'
            records = read(target, permitted)
        if permitted() is not True:
            raise PermissionError('music read permission changed')
        if not records:
            # The old public catalog remains visibly unassigned metadata. A
            # native tombstone/disabled row never falls through this branch.
            return dict(allow_legacy=True, current=permitted)
        songs = []
        for record in records:
            fields = record['fields']
            if record['archived'] or fields['enabled'] is not True:
                continue
            song = dict(id=record['id'], name=fields['title'], artists=fields['artist'], album=fields['album'],
                style=fields['genre'], language=fields['language'], mood=fields['mood'], lyric=fields['lyrics'])
            song.update({key: deepcopy(fields[key]) for key in ('tags','meaning','user_preference','user_comment','character_comment') if key in fields})
            songs.append(song)
        result = dict(songs=songs, styles=sorted({song['style'] for song in songs if song['style']}),
            languages=sorted({song['language'] for song in songs if song['language']}),
            playlist=dict(name='TLS原生音乐资料'), _tls_music_source=dict(kind='tls_native_music_library',
                read_source=source_kind, retained_records=len(records), active_records=len(songs),
                metadata_only=True, creates_playback_evidence=False))
        if permitted() is not True:
            raise PermissionError('music read permission changed after projection')
        return dict(db=result, current=permitted, allow_legacy=False)

    async def _platform_action(self, scope, action, payload):
        if not self._authorize('platform_action', scope) or not callable(self.platform_action):
            return dict(state='blocked', reason='native_pc_platform_action_adapter_unavailable')
        value = self.platform_action(scope, action, payload)
        return await value if inspect.isawaitable(value) else value

    async def _start_native(self):
        if not self.legacy_closed():
            raise RuntimeError('original PC executor closure is not proven')
        raw = self.plugin.config.get(CONFIG)
        if not isinstance(raw, dict) or not raw:
            raise RuntimeError('complete persisted native PC configuration required')
        self._host()
        self._save({FLAG: True})
        config = NestedConfig(self, raw)
        self._last_config = deepcopy(dict(config))
        service = NativePCService(self.context, config, legacy_closed=self.legacy_closed,
            authorize=self._authorize, send_chain=self._send, platform_action=self._platform_action,
            register_ui=False, journal=self._host().journal, music_library_reader=self._music_library_view)
        self.service = service  # retain partially initialized resources on failure
        expected = (self.integrations.data_dir.parent / LEGACY).resolve()
        if Path(service.data_dir).resolve() != expected:
            raise RuntimeError('native PC must reuse the exact original state directory')
        self.active = True
        await service.initialize()
        if not service.native_source_current():
            self.active = False
            raise RuntimeError('actual native PC source proof failed')
        service.register_native_routes()
        self.phase, self.last_error = 'native', None
        self.generation += 1

    async def activate(self):
        async with self._lock:
            if self.active and self.service is not None:
                return self.status()
            if self.phase in {'blocked', 'drain_pending', 'turnoff_unknown'}:
                raise RuntimeError('previous PC handoff needs explicit status/restore')
            self.phase, self.last_error = 'preparing', None
            try:
                if getattr(self._row(), 'activated', None) is True:
                    self._capture_old()
                    self._freeze_admission()
                    self.phase = 'draining_original'
                    await self._drain_old()
                    self._old_off_attempted = True
                    self.phase = 'turning_off_original'
                    await self.context._star_manager.turn_off_plugin(LEGACY)
                    self._record_retirement()
                elif not self.legacy_closed():
                    await self._load_retirement()
                await self._start_native()
                return self.status()
            except BaseException as exc:
                self.active = False
                self.last_error = type(exc).__name__
                self.last_error_sha256 = hashlib.sha256(str(exc).encode()).hexdigest()
                self.phase = 'turnoff_unknown' if self._old_off_attempted and not self._old_off_confirmed else 'blocked'
                raise

    async def _load_retirement(self):
        value = self.plugin.config.get(BINDING)
        if (not isinstance(value, dict) or set(value) != {'binding_sha256', 'source_kind',
                'legacy_source_sha256', 'legacy_config_sha256'} or value['source_kind'] != 'retired_legacy_pc'
                or any(not isinstance(value[name], str) or _HEX.fullmatch(value[name]) is None
                    for name in ('binding_sha256', 'legacy_source_sha256', 'legacy_config_sha256'))):
            raise RuntimeError('persisted genuine retired PC memo binding unavailable')
        row = self._row()
        module = getattr(row, 'module', None)
        filename = getattr(module, '__file__', None)
        if filename is None:
            filename = self.integrations.data_dir.parent.parent / 'plugins' / LEGACY / 'main.py'
        source_sha, old_config = self._pin(Path(filename).resolve().parent)
        self.binding_state = dict(value)
        if source_sha != value['legacy_source_sha256'] or self._config_sha != value['legacy_config_sha256']:
            raise RuntimeError('retired PC source/configuration fingerprint changed')
        record = getattr(self.context, RETIRED_SLOT, None)
        if isinstance(record, dict) and record.get('context') is self.context:
            self._legacy, self._legacy_module = record['owner'], record['module']
            self._retired_config = deepcopy(record.get('original_config', old_config))
        else:
            self._retired_config = old_config
        if not self.legacy_closed():
            raise RuntimeError('disabled original PC retains an unretired runtime')

    async def start_if_configured(self):
        if self.plugin.config.get(FLAG) is not True:
            return self.status()
        async with self._lock:
            if self.active:
                return self.status()
            try:
                if getattr(self._row(), 'activated', None) is True:
                    raise RuntimeError('native PC intent conflicts with an active original plugin')
                await self._load_retirement()
                await self._start_native()
            except BaseException as exc:
                self.active, self.phase, self.last_error = False, 'blocked', type(exc).__name__
                self.last_error_sha256 = hashlib.sha256(str(exc).encode()).hexdigest()
            return self.status()

    def _native_paths(self):
        here = Path(__file__).resolve().parent
        return {str(path.resolve()) for path in (here / 'native_pc_business').rglob('*.py')} | {
            str((here / 'native_pc_service.py').resolve())}

    async def _stop_locked(self, persist):
        self.active = False
        if persist:
            self._save({FLAG: False})
        service = self.service
        if service is None:
            self.phase = 'closed'
            return
        service._tls_running = False
        service._tls_music_library_reader = None
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            tasks = self._scan(self._native_paths())
            if not any(self._drain.values()):
                break
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                self.phase = 'drain_pending'
                raise RuntimeError('native PC model/send/thread work remains; retain runtime references')
            if tasks:
                await asyncio.wait(tasks, timeout=min(.1, left))
            else:
                await asyncio.sleep(min(.05, left))
        await service.terminate()
        registry = self.context.registered_web_apis
        owned = getattr(service, '_tls_registered_routes', ())
        registry[:] = [entry for entry in registry if not any(entry is previous for previous in owned)]
        self.service = None
        self.phase = 'closed'

    async def stop(self):
        async with self._lock:
            await self._stop_locked(True)
            return self.status()

    async def close(self):
        async with self._lock:
            # TLS reload closes this runtime only; persisted ownership survives
            # and the old plugin is never enabled as a shutdown side effect.
            await self._stop_locked(False)

    async def _unfreeze_existing(self):
        if self._legacy is None or not self._source_current():
            raise RuntimeError('original PC source/configuration changed before restore')
        for holder, original, replacement in self._hook_slots + self._tool_slots:
            if holder.handler is not replacement:
                raise RuntimeError('original SDK entry fence changed before restore')
        for name, (had_slot, original, replacement) in self._method_slots.items():
            if vars(self._legacy).get(name) is not replacement:
                raise RuntimeError('original PC bridge admission fence changed before restore')
        registry = self.context.registered_web_apis
        for original, replacement in self._page_slots:
            positions = [index for index, entry in enumerate(registry) if entry is replacement]
            if len(positions) != 1:
                raise RuntimeError('original PC write route fence changed before restore')
            registry[positions[0]] = original
        for holder, original, replacement in self._hook_slots + self._tool_slots:
            holder.handler = original
        for name, (had_slot, original, replacement) in self._method_slots.items():
            if had_slot:
                setattr(self._legacy, name, original)
            else:
                delattr(self._legacy, name)
        owner = self._legacy
        owner.enabled = self._legacy_enabled
        owner._relationship_analysis_stopping = self._legacy_relationship_stopping
        if self._legacy_stop_set is False:
            owner._stop_event.clear()
            if not isinstance(getattr(owner, '_task', None), asyncio.Task) or owner._task.done():
                owner._task = asyncio.create_task(owner._scheduler_loop())
        if self._bridge is not None:
            self._bridge._stopping = self._bridge_stopping
            if self._bridge_stop_set is False:
                self._bridge._stop_event.clear()
                task = getattr(self._bridge, '_watch_task', None)
                if not isinstance(task, asyncio.Task) or task.done():
                    await self._bridge.start()
        self._hook_slots.clear(); self._tool_slots.clear(); self._page_slots.clear(); self._method_slots.clear()

    async def restore_legacy(self):
        async with self._lock:
            await self._stop_locked(True)
            if not self._source_current():
                raise RuntimeError('original PC source/configuration changed; explicit reconciliation required')
            row = self._row()
            if getattr(row, 'activated', None) is True:
                if self._hook_slots or self._tool_slots or self._page_slots or self._method_slots:
                    await self._unfreeze_existing()
            elif self.legacy_closed():
                await self.context._star_manager.turn_on_plugin(LEGACY)
                if getattr(self._row(), 'activated', None) is not True:
                    self.phase = 'restore_unknown'
                    raise RuntimeError('normal original PC startup result unknown')
                setattr(self.context, RETIRED_SLOT, None)
            else:
                raise RuntimeError('original PC retirement outcome unknown; do not start a second executor')
            self.phase, self.last_error = 'legacy', None
            return self.status()

    async def tick(self):
        if not self.active or self.service is None or self._host()._closed:
            return dict(state='closed')
        return await self.service.host_tick()

    async def observe_event(self, event):
        if not self.active or self.service is None:
            return False
        if (not event.is_private_chat() or event.get_group_id()
                or getattr(event, 'private_companion_proactive_framework', False)):
            return False
        host = self._host()
        session = str(getattr(event, 'unified_msg_origin', '') or '')
        scope = private_scope(host.presence.peek_scope_for_session(session))
        if (scope['session_id'] != session or str(event.get_sender_id() or '') != scope['user_id']
                or str(event.get_self_id() or '') != scope['bot_id'] or not self._authorize('bind', scope)):
            return False
        event_id = str(getattr(getattr(event, 'message_obj', None), 'message_id', '') or '')
        if not event_id or event_id == '0' or len(event_id) > 256:
            return False
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(session)
        conversation = await manager.get_conversation(session, cid, create_if_not_exists=False) if cid else None
        if cid and (conversation is None or getattr(conversation, 'user_id', None) != session):
            return False
        selected, persona, *_ = await self.context.persona_manager.resolve_selected_persona(
            umo=session, conversation_persona_id=getattr(conversation, 'persona_id', None),
            platform_name=scope['platform'],
            provider_settings=self.context.get_config(umo=session).get('provider_settings', {}))
        if not selected or not isinstance(persona, dict) or not self._authorize('bind', scope):
            return False
        await self.service.bind_scope(scope, event_id, selected)
        self._bound_source = dict(source='genuine_inbound_sdk_selection', scope=dict(scope), persona_id=selected)
        return True

    def get_private_companion_api(self):
        if not self.active or self.service is None:
            return None
        getter = getattr(self.service, 'get_private_companion_api', None)
        return getter() if callable(getter) else getattr(self.service, 'extension_api', None)

    def status(self):
        service = self.service
        return dict(ok=True, active=self.active, phase=self.phase, generation=self.generation,
            configured=self.plugin.config.get(FLAG) is True, last_error=self.last_error,
            last_error_sha256=self.last_error_sha256,
            source_current=self._source_current(), legacy_closed=self.legacy_closed(),
            old_admission_fenced=bool(self._hook_slots or self._tool_slots or self._page_slots),
            legacy_turnoff_attempted=self._old_off_attempted, legacy_turnoff_confirmed=self._old_off_confirmed,
            binding_state=dict(self.binding_state) if isinstance(self.binding_state, dict) else None,
            legacy_pending=dict(self._pending), drain=dict(self._drain),
            legacy_inspection=({key: self._last_inspection.get(key) for key in
                ('state', 'reason', 'scheduler', 'counts', 'handoff')}
                if isinstance(self._last_inspection, dict) else None),
            real_scope_bound=self._bound_source is not None,
            service=service.diagnostics() if service is not None else None,
            legacy_data_copied=False, legacy_configuration_written=False,
            source_scope_guessed=False, native_background_scheduler=False,
            legacy_pending_or_unknown_auto_adopted=False)
