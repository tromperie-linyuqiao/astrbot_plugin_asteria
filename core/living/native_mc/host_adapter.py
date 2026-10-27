"""TLS lifecycle host for the migrated Companion business and original data.

Preparation does not register a second Star or start a worker. Root first
quiesces the former owner, prepares this service, installs the existing TLS
context owner and typed capture router, then opens the one native lifecycle.
"""
from __future__ import annotations

import asyncio
from functools import wraps
import inspect
from pathlib import Path
from types import AsyncGeneratorType, CoroutineType, GeneratorType

from astrbot.api.web import error_response

from .bridge import MemoryCompanionBridge
from .capture_router import NativeMCCaptureRouter
from .commands import MemoryCompanionCommandHandler
from .hook_methods import COMMAND_METHODS, NativeMemoryCompanionHooks
from .page_api import PAGE_API_PREFIXES, PluginPageApi
from .service import MemoryCompanionService
from .task_drain import task_codes


def _strict_true(callback):
    value = callback()
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        return False
    return value is True


class NativeMemoryCompanion(NativeMemoryCompanionHooks):
    def __init__(self, context, config, *, data_dir, plugin_root,
                 legacy_quiesced, companion_api=None, drain_timeout=30.0):
        if (not callable(legacy_quiesced) or inspect.iscoroutinefunction(legacy_quiesced)
                or type(drain_timeout) not in (int, float) or not 0 < drain_timeout <= 120):
            raise ValueError('explicit original data and synchronous former-owner gate required')
        self.context, self.config = context, config
        self.data_dir, self.plugin_root = Path(data_dir).resolve(), Path(plugin_root).resolve()
        self.legacy_quiesced, self.companion_api = legacy_quiesced, companion_api
        self.drain_timeout = float(drain_timeout)
        self.service = self.memory_companion = self.commands = self.page_api = None
        self.capture_router = None
        self.bot_personal_capabilities = {'available': False, 'state': 'not_prepared'}
        self.phase, self.active, self.closed = 'new', False, False
        self._calls, self._routes_registered = set(), False
        self._lifecycle_lock = asyncio.Lock()
        self._context_ready = None

    @property
    def companion_api(self):
        getter = getattr(self, 'companion_api_getter', None)
        if callable(getter):
            return getter()
        return self._companion_api

    @companion_api.setter
    def companion_api(self, value):
        self._companion_api = value

    async def prepare(self):
        async with self._lifecycle_lock:
            if self.closed:
                raise RuntimeError('native memory owner already closed')
            if self.service is not None:
                return self.status()
            if not _strict_true(self.legacy_quiesced):
                raise RuntimeError('former memory owner is not proven stopped and drained')
            if not self.data_dir.is_dir() or not (self.data_dir / 'memory_companion.db').is_file():
                raise RuntimeError('explicit existing Companion primary database required')
            self.phase = 'preparing'
            try:
                service = MemoryCompanionService(context=self.context, config=self.config,
                    plugin_root=self.plugin_root, data_dir=self.data_dir)
            except BaseException:
                self.phase = 'prepare_failed'
                raise
            self.service = service
            service.native_companion_api = self.companion_api
            service.native_companion_api_getter = lambda: self.companion_api
            self.memory_companion = MemoryCompanionBridge(service)
            self.bot_personal_capabilities = self.memory_companion.probe_capability_snapshot()
            self.commands = MemoryCompanionCommandHandler(service, 'TLS native / source 1.10.6')
            self.page_api = PluginPageApi(self)
            self.phase = 'prepared_context_closed'
            return self.status()

    def bind_capture_router(self, router):
        if (self.closed or self.active or self.service is None
                or type(router) is not NativeMCCaptureRouter or not router.closed
                or self.capture_router is not None and self.capture_router is not router):
            raise RuntimeError('one closed capture router required before native start')
        self.capture_router = router
        self.service._tls_capture_router = router

    async def start_workers(self, *, context_ready):
        async with self._lifecycle_lock:
            if self.active:
                if self._context_ready is not context_ready and not _strict_true(context_ready):
                    raise RuntimeError('current native context owner required')
                return self.status()
            if (self.closed or self.service is None or self.capture_router is None
                    or not callable(context_ready) or inspect.iscoroutinefunction(context_ready)
                    or not _strict_true(self.legacy_quiesced) or not _strict_true(context_ready)
                    or self.service._tls_capture_router is not self.capture_router
                    or self.service._tls_native_final_context_owned is not True
                    or self.service._closing or self.service._closed):
                raise RuntimeError('prepared service, current context and single capture owner required')
            self._context_ready = context_ready
            self.capture_router.open()
            self.active, self.phase = True, 'native_active'
            try:
                self.service._ensure_lifecycle_maintenance_dispatcher()
                self.service._ensure_portrait_daily_dispatcher()
                self.service._ensure_wal_checkpoint_loop()
            except BaseException:
                self.active, self.phase = False, 'start_failed'
                self.capture_router.close()
                raise
            return self.status()

    def register_routes(self):
        if self.page_api is None:
            raise RuntimeError('prepare native memory before registering management routes')
        if self._routes_registered:
            return
        for prefix in PAGE_API_PREFIXES:
            for route, handler, methods, description in self.page_api._route_specs():
                @wraps(handler)
                async def guarded(*args, _handler=handler, **kwargs):
                    if not self.active or self.closed:
                        return error_response('原生记忆服务尚未接管或正在关闭', status_code=503)
                    task = asyncio.current_task()
                    self._calls.add(task)
                    try:
                        return await _handler(*args, **kwargs)
                    finally:
                        self._calls.discard(task)
                self.context.register_web_api(prefix + route, guarded, methods, description)
        self._routes_registered = True

    async def _hook(self, name, *args):
        if not self.active or self.closed:
            return
        task = asyncio.current_task()
        self._calls.add(task)
        try:
            return await getattr(NativeMemoryCompanionHooks, name)(self, *args)
        finally:
            self._calls.discard(task)

    async def on_llm_request(self, event, req):
        return await self._hook('on_llm_request', event, req)

    async def on_group_message(self, event):
        return await self._hook('on_group_message', event)

    async def on_llm_response(self, event, response):
        return await self._hook('on_llm_response', event, response)

    async def dispatch_tool(self, name, event, **kwargs):
        if name not in TOOL_METHODS or not self.active or self.closed:
            return '{"ok":false,"error":"native memory tool unavailable"}'
        task = asyncio.current_task()
        self._calls.add(task)
        try:
            return await getattr(NativeMemoryCompanionHooks, TOOL_METHODS[name])(self, event, **kwargs)
        finally:
            self._calls.discard(task)

    def command_methods(self):
        """Root retains administrator permission on its single mcomp entry."""
        return {name: getattr(self, method) for name, method in COMMAND_METHODS.items()}

    def tool_definitions(self):
        return {name: dict(name=name,
            description=inspect.getdoc(getattr(NativeMemoryCompanionHooks, method)) or name,
            parameters=TOOL_PARAMETERS[name]) for name, method in TOOL_METHODS.items()}

    async def dispatch_command(self, name, event, **kwargs):
        if name not in COMMAND_METHODS or not self.active or self.closed:
            yield event.plain_result('原生记忆命令不可用。')
            return
        task = asyncio.current_task()
        self._calls.add(task)
        try:
            async for result in getattr(self, COMMAND_METHODS[name])(event, **kwargs):
                yield result
        finally:
            self._calls.discard(task)

    def get_bridge(self):
        if not self.active or self.closed:
            return None
        return self.memory_companion

    def begin_stop(self):
        self.active = False
        if not self.closed:
            self.phase = 'closing'
        if self.capture_router is not None:
            self.capture_router.close()
        if self.service is not None:
            self.service._closing = True
        if self.memory_companion is not None:
            self.memory_companion.deactivate()

    @staticmethod
    def _chain(task):
        codes, unknown = task_codes(task)
        if unknown:
            raise RuntimeError('native memory coroutine await chain unknown')
        yield from codes

    def _foreign_instance_task(self, task, package_codes):
        """Exclude only fully visible frames of one proven other MC instance.

        A package path alone is not object ownership. Untracked helpers, opaque
        frames or a current-instance frame retain the original drain barrier.
        """
        frames, seen, current = [], set(), asyncio.Task.get_coro(task)
        for _ in range(128):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            kind = type(current)
            if kind is CoroutineType:
                frame, current = current.cr_frame, current.cr_await
            elif kind is GeneratorType:
                frame, current = current.gi_frame, current.gi_yieldfrom
            elif kind is AsyncGeneratorType:
                frame, current = current.ag_frame, current.ag_await
            else:
                break
            if frame is not None and frame.f_code in package_codes:
                frames.append(frame)
        if not frames or set(package_codes) - {frame.f_code for frame in frames}:
            return False
        foreign = None
        for frame in frames:
            instance = frame.f_locals.get('self')
            if instance is self or instance is self.service:
                return False
            kind = type(instance)
            expected = next((known for known in (NativeMemoryCompanion, MemoryCompanionService)
                if kind.__module__ == known.__module__ and kind.__name__ == known.__name__), None)
            if expected is None:
                return False
            # Hot reload may leave an older class generation. Its actual
            # method must own this frame and equal the currently loaded,
            # unchanged method code; a matching name alone proves nothing.
            actual = vars(kind).get(frame.f_code.co_name)
            current_method = vars(expected).get(frame.f_code.co_name)
            if (getattr(actual, '__code__', None) is not frame.f_code
                    or getattr(current_method, '__code__', None) != frame.f_code):
                return False
            service = instance.service if expected is NativeMemoryCompanion else instance
            service_kind = type(service)
            if (service is self.service or service_kind.__module__ != MemoryCompanionService.__module__
                    or service_kind.__name__ != MemoryCompanionService.__name__):
                return False
            if foreign is not None and foreign is not service:
                return False
            foreign = service
        return foreign is not None

    def _work(self):
        current = asyncio.current_task()
        tasks = {task for task in self._calls if task is not current and not task.done()}
        if self.service is not None:
            tasks.update(task for task in self.service._background_tasks
                         if task is not current and not task.done())
        # Include current direct tool/bridge/service calls not started through
        # this adapter. This is bounded to this package, never global cleanup.
        all_tasks = asyncio.all_tasks()
        if len(all_tasks) > 4096:
            raise RuntimeError('native memory task inventory exceeded bound')
        package_path = Path(__file__).resolve().parent
        for task in all_tasks:
            if task is current or task.done():
                continue
            package_codes = tuple(code for code in self._chain(task)
                if Path(code.co_filename).resolve().is_relative_to(package_path))
            if package_codes and not self._foreign_instance_task(task, package_codes):
                tasks.add(task)
        return tasks

    def _stop_idle_dispatchers(self):
        if self.service is None:
            return
        for name in ('_maintenance_dispatch_task', '_portrait_dispatch_task', '_wal_checkpoint_task'):
            task = getattr(self.service, name, None)
            if task is not None and not task.done() and asyncio.sleep.__code__ in set(self._chain(task)):
                task.cancel()

    async def wait_drained(self, timeout=None):
        deadline = asyncio.get_running_loop().time() + (self.drain_timeout if timeout is None else timeout)
        while True:
            self._stop_idle_dispatchers()
            tasks = self._work()
            if not tasks:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.phase = 'drain_pending'
                raise RuntimeError('native memory work remains; service and original stores retained')
            await asyncio.wait(tasks, timeout=min(0.1, remaining))
        if self.capture_router is not None:
            await self.capture_router.wait_drained(timeout=max(0, deadline - asyncio.get_running_loop().time()))
        return self.status()

    async def close(self):
        self.begin_stop()
        async with self._lifecycle_lock:
            if self.closed:
                return self.status()
            await self.wait_drained()
            if self.service is not None:
                await self.service.aclose()
            self.closed, self.phase = True, 'closed'
            return self.status()

    aclose = close

    def status(self):
        service = self.service
        return dict(backend='tls_native_memory_companion', phase=self.phase,
            active=self.active and not self.closed, closed=self.closed,
            prepared=service is not None, management_registered=self._routes_registered,
            original_data_directory_required=True, new_database_requested=False,
            final_context='TLS Unified owner', source_legacy_version='1.10.6',
            service_closed=getattr(service, '_closed', None),
            service_closing=getattr(service, '_closing', None),
            hook_calls=sum(task is not None and not task.done() for task in self._calls),
            background_tasks=(sum(not task.done() for task in service._background_tasks)
                              if service is not None else 0),
            capture=self.capture_router.status() if self.capture_router is not None else None,
            former_owner_gate_supplied=True, page_prefix=PAGE_API_PREFIXES[0])


TOOL_METHODS = {
    'memory_companion_recall': 'memory_companion_recall_tool',
    'memory_companion_navigate': 'memory_companion_navigate_tool',
    'memory_companion_remember': 'memory_companion_remember_tool',
    'memory_companion_core_memory': 'memory_companion_core_memory_tool',
    'memory_companion_note_create': 'memory_companion_note_create_tool',
    'memory_companion_note_read': 'memory_companion_note_read_tool',
    'memory_companion_note_delete': 'memory_companion_note_delete_tool',
}

TOOL_PARAMETERS = {
    'memory_companion_recall': {'type': 'object', 'properties': {
        'query': {'type': 'string'}, 'top_k': {'type': 'integer'}}, 'required': ['query']},
    'memory_companion_navigate': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['search', 'tag_events', 'event_time',
            'event_context', 'person_aspect', 'topic_events', 'reverse_cues']},
        'query': {'type': 'string'}, 'cue': {'type': 'string'}, 'tag': {'type': 'string'},
        'memory_ids': {'type': 'array', 'items': {'type': 'string'}},
        'node_type': {'type': 'string'}, 'limit': {'type': 'integer'}}, 'required': ['action']},
    'memory_companion_remember': {'type': 'object', 'properties': {
        'content': {'type': 'string'}, 'note_type': {'type': 'string'}}, 'required': ['content']},
    'memory_companion_core_memory': {'type': 'object', 'properties': {
        'action': {'type': 'string'}, 'label': {'type': 'string'}, 'content': {'type': 'string'},
        'kind': {'type': 'string'}, 'priority': {'type': 'integer'},
        'enabled': {'type': 'boolean'}}, 'required': ['action']},
    'memory_companion_note_create': {'type': 'object', 'properties': {
        'title': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['content']},
    'memory_companion_note_read': {'type': 'object', 'properties': {
        'query': {'type': 'string'}, 'limit': {'type': 'integer'}}, 'required': []},
    'memory_companion_note_delete': {'type': 'object', 'properties': {
        'memory_id': {'type': 'string'}, 'title': {'type': 'string'}}, 'required': []},
}
