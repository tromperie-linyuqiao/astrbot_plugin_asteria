"""Isolated exact-instance transfer of MC's summary algorithm, not its pipeline.

No Host/API/config wiring exists. Root must provide the current reviewed service
predicate; this module does not discover an owner or grant any read/model right.
Only two actual async service entrypoints are temporarily gated while their
existing work drains. Queued calls resume rather than disappearing. The original
timeline/provider/store/worker/failure state and audit.py static calls remain MC.
"""
from __future__ import annotations

import asyncio
import ast
import hashlib
import inspect
import math
from pathlib import Path
import sys
from types import MethodType, ModuleType

from . import native_core_handoff as audit
from .native_memory_summarizer import NativeMemorySummarizer


METHODS = ('maybe_summarize_session', '_summarize_decay_records_with_provider')
PARAMETERS = ('max_input_chars', 'max_summary_chars', 'provider_timeout_seconds')
SERVICE_SHA = '6b1c9b52cc918cde66cfa14635720bfdde80332defff51278829030496d7fad2'
SUMMARY_SHA = 'c0e554613ae9b336a7f7e95bb9c9322268eeef2c81ea5a9f68709131d37aca80'
NATIVE_SHA = '40f59638cf6820af25e009a1e1888a527ef505ba79e3624636c9f98591097911'
NATIVE_HELPER_SHA = 'e57adadd737bd067ca032511c025c381f8254275797ec90ceb81e95849d42cc6'
SLOT = '_tls_native_mc_summary_algorithm'


class SummaryAlgorithmError(RuntimeError):
    pass


class NativeMCSummaryAlgorithm:
    def __init__(self, service, *, source_current, drain_timeout=10.0):
        if (not callable(source_current) or inspect.iscoroutinefunction(source_current)
                or type(drain_timeout) not in (int, float)
                or not math.isfinite(drain_timeout) or not 0 < drain_timeout <= 30):
            raise SummaryAlgorithmError('current_sync_service_predicate_required')
        self.service, self.source_current = service, source_current
        self.timeout = float(drain_timeout)
        self.old = self.native = None
        self._original, self._own, self._wrappers = {}, {}, {}
        self._loop = None; self._lock = asyncio.Lock(); self._gate = asyncio.Event(); self._gate.set()
        self._phase = 'unprepared'; self._codes = (); self._parameters = None
        self._files = {}; self._active = False; self._transition = False
        self._loaded_pins, self._constant_pins, self._alias_pins = [], [], []

    def _current(self):
        value = self.source_current(self.service)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value): value.close()
            return False
        if value is not True: return False
        for path, expected in self._files.items():
            stat = path.stat()
            if path.is_symlink() or (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != expected:
                return False
        return True

    def _bind_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is None: self._loop = loop
        if loop is not self._loop: raise SummaryAlgorithmError('same_event_loop_required')
        return loop

    @staticmethod
    def _file(module, digest):
        if not isinstance(module, ModuleType) or type(vars(module).get('__file__')) is not str:
            raise SummaryAlgorithmError('loaded_source_module_required')
        path = Path(vars(module)['__file__'])
        raw = audit._regular_file(path)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise SummaryAlgorithmError('reviewed_algorithm_source_changed')
        return path, audit._compiled(raw, str(path)), raw

    def _pin_functions(self, owner, code, namespace):
        for name, descriptor in vars(owner).items():
            function = descriptor.__func__ if isinstance(descriptor, (staticmethod, classmethod)) else descriptor
            if not inspect.isfunction(function): continue
            expected = audit._child(code, name)
            if function.__code__ != expected or function.__globals__ is not namespace:
                raise SummaryAlgorithmError('loaded_algorithm_or_helper_changed')
            self._loaded_pins.append((owner, name, descriptor, expected, namespace))

    def _pin_constants(self, owner, nodes):
        for node in nodes:
            if not isinstance(node, ast.Assign): continue
            value = node.value
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == 'frozenset' and len(value.args) == 1 and not value.keywords):
                expected = frozenset(ast.literal_eval(value.args[0]))
            else:
                expected = ast.literal_eval(value)
            for target in node.targets:
                if not isinstance(target, ast.Name): raise SummaryAlgorithmError('algorithm_constant_shape_changed')
                self._constant_pins.append((owner, target.id, expected))

    @staticmethod
    def _plain_equal(actual, expected):
        if type(actual) is not type(expected): return False
        if type(expected) is dict:
            return actual.keys() == expected.keys() and all(
                NativeMCSummaryAlgorithm._plain_equal(actual[key], value) for key, value in expected.items())
        if type(expected) in (tuple, list):
            return len(actual) == len(expected) and all(
                NativeMCSummaryAlgorithm._plain_equal(a, b) for a, b in zip(actual, expected))
        return actual == expected

    def _loaded_current(self):
        for owner, name, descriptor, code, namespace in self._loaded_pins:
            actual = vars(owner).get(name)
            function = actual.__func__ if isinstance(actual, (staticmethod, classmethod)) else actual
            if (actual is not descriptor or not inspect.isfunction(function)
                    or function.__code__ != code or function.__globals__ is not namespace): return False
        return (all(self._plain_equal(vars(owner).get(name), expected)
                    for owner, name, expected in self._constant_pins)
                and all(vars(owner).get(name) is expected for owner, name, expected in self._alias_pins))

    def _prepare(self):
        if not self._current() or vars(self.service).get(SLOT) is not None:
            raise SummaryAlgorithmError('reviewed_service_without_other_algorithm_owner_required')
        module = sys.modules.get(type(self.service).__module__)
        service_path, service_code, _ = self._file(module, SERVICE_SHA)
        if vars(module).get('MemoryCompanionService') is not type(self.service):
            raise SummaryAlgorithmError('exact_service_class_required')
        service_class = audit._child(service_code, 'MemoryCompanionService')
        old = vars(self.service).get('summarizer')
        summary_module = sys.modules.get(type(old).__module__)
        summary_path, summary_code, summary_raw = self._file(summary_module, SUMMARY_SHA)
        if (type(old) is not vars(summary_module).get('MemorySummarizer')
                or vars(module).get('MemorySummarizer') is not type(old)):
            raise SummaryAlgorithmError('exact_old_summary_instance_required')
        old_class = audit._child(summary_code, 'MemorySummarizer')
        self._pin_functions(type(old), old_class, vars(summary_module))
        old_node = next(node for node in ast.parse(summary_raw).body if isinstance(node, ast.ClassDef)
                        and node.name == 'MemorySummarizer')
        self._pin_constants(type(old), old_node.body)
        if set(vars(old)) != set(PARAMETERS):
            raise SummaryAlgorithmError('unknown_old_algorithm_state')
        parameters = {name: vars(old)[name] for name in PARAMETERS}
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in parameters.values()):
            raise SummaryAlgorithmError('actual_algorithm_parameters_required')
        native_module = sys.modules.get(NativeMemorySummarizer.__module__)
        native_path, native_code, native_raw = self._file(native_module, NATIVE_SHA)
        helper = sys.modules.get(native_module.__name__.rsplit('.', 1)[0] + '.native_memory_summary_text')
        helper_path, helper_code, helper_raw = self._file(helper, NATIVE_HELPER_SHA)
        if vars(native_module).get('NativeMemorySummarizer') is not NativeMemorySummarizer:
            raise SummaryAlgorithmError('loaded_native_class_binding_changed')
        self._pin_functions(NativeMemorySummarizer,
            audit._child(native_code, 'NativeMemorySummarizer'), vars(native_module))
        self._pin_functions(helper, helper_code, vars(helper))
        native_node = next(node for node in ast.parse(native_raw).body if isinstance(node, ast.ClassDef)
                           and node.name == 'NativeMemorySummarizer')
        self._pin_constants(NativeMemorySummarizer, native_node.body)
        self._pin_constants(helper, ast.parse(helper_raw).body)
        self._alias_pins.append((native_module, 'NativeMemorySummarizer', NativeMemorySummarizer))
        for name in ('clean_text', 'json_dumps', 'json_loads', 'message_terms'):
            self._alias_pins.append((native_module, name, vars(helper).get(name)))
        if not self._loaded_current():
            raise SummaryAlgorithmError('loaded_algorithm_or_helper_changed')
        native = NativeMemorySummarizer(**parameters)
        if vars(native) != parameters:
            raise SummaryAlgorithmError('algorithm_parameters_changed')
        codes = [type(old).summarize_with_provider.__code__, type(native).summarize_with_provider.__code__]
        for name in METHODS:
            audit._method(self.service, name, audit._child(service_class, name), service_path)
            if name in vars(self.service): raise SummaryAlgorithmError('service_entry_override')
            method = getattr(self.service, name)
            if not inspect.iscoroutinefunction(method): raise SummaryAlgorithmError('async_service_entry_required')
            self._original[name] = method; self._own[name] = False; codes.append(method.__func__.__code__)
        self.old, self.native, self._parameters = old, native, parameters
        self._codes = tuple(codes)
        for path in (service_path, summary_path, native_path, helper_path):
            stat = path.stat(); self._files[path] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        self._phase = 'legacy'

    def _install_gate(self):
        self._gate.clear(); self._transition = True
        for name in METHODS:
            original = self._original[name]
            if not (getattr(self.service, name).__self__ is self.service
                    and getattr(self.service, name).__func__ is original.__func__):
                raise SummaryAlgorithmError('service_entry_drift')
        for name in METHODS:
            original = self._original[name]
            async def gated(_service, *args, __original=original, **kwargs):
                await self._gate.wait()
                return await __original(*args, **kwargs)
            wrapper = MethodType(gated, self.service)
            self._wrappers[name] = wrapper; setattr(self.service, name, wrapper)

    def _release_gate(self):
        for name, wrapper in self._wrappers.items():
            if vars(self.service).get(name) is wrapper:
                if self._own[name]: setattr(self.service, name, self._original[name])
                else: delattr(self.service, name)
        self._wrappers.clear(); self._transition = False
        self._gate.set()

    async def _drain(self):
        loop = self._bind_loop(); tasks = asyncio.all_tasks(loop)
        if len(tasks) > audit.MAX_TASKS: raise SummaryAlgorithmError('task_scan_capacity')
        frame = inspect.currentframe()
        try:
            for _ in range(audit.MAX_DEPTH):
                if frame is None: break
                if frame.f_code in self._codes:
                    raise SummaryAlgorithmError('transition_inside_owned_summary')
                frame = frame.f_back
            else: raise SummaryAlgorithmError('current_stack_unknown')
        finally: del frame
        future_iter = type(loop.create_future().__await__()); active = []
        for task in tasks:
            if task is asyncio.current_task(): continue
            found, unknown = audit._task_chain(task, self._codes, future_iter)
            if unknown: raise SummaryAlgorithmError('summary_await_chain_unknown')
            if found: active.append(task)
        if active:
            _, pending = await asyncio.wait(active, timeout=self.timeout)
            if pending: raise SummaryAlgorithmError('summary_drain_timeout')
        # No await occurs between this final known-code scan and the CAS.
        tasks = asyncio.all_tasks(loop)
        if len(tasks) > audit.MAX_TASKS: raise SummaryAlgorithmError('task_scan_capacity')
        for task in tasks:
            if task is asyncio.current_task() or task.done(): continue
            found, unknown = audit._task_chain(task, self._codes, future_iter)
            if found or unknown: raise SummaryAlgorithmError('late_summary_drain_not_proven')

    def _cas_ready(self, expected, anchor):
        return (self._current() and self._loaded_current()
            and vars(self.service).get(SLOT) is anchor
            and vars(self.service).get('summarizer') is expected
            and vars(expected) == self._parameters
            and all(vars(self.service).get(name) is wrapper for name, wrapper in self._wrappers.items()))

    async def activate(self):
        self._bind_loop()
        async with self._lock:
            if self._active:
                if (vars(self.service).get('summarizer') is not self.native
                        or vars(self.service).get(SLOT) is not self):
                    raise SummaryAlgorithmError('native_algorithm_pointer_drift')
                return self.status()
            if self.old is None: self._prepare()
            if (vars(self.service).get('summarizer') is not self.old
                    or vars(self.service).get(SLOT) is not None or not self._current()):
                raise SummaryAlgorithmError('legacy_algorithm_pointer_or_source_changed')
            try:
                self._install_gate(); await self._drain()
                if not self._cas_ready(self.old, None): raise SummaryAlgorithmError('algorithm_cas_not_proven')
                self.service.summarizer = self.native
                setattr(self.service, SLOT, self)
                self._active = True; self._phase = 'native_algorithm'
            except BaseException:
                self._phase = 'activation_refused'
                raise
            finally:
                self._release_gate()
            return self.status()

    async def restore(self):
        self._bind_loop()
        async with self._lock:
            if not self._active or vars(self.service).get(SLOT) is not self:
                raise SummaryAlgorithmError('owned_native_algorithm_required')
            try:
                self._install_gate(); await self._drain()
                if not self._cas_ready(self.native, self): raise SummaryAlgorithmError('native_algorithm_cas_not_proven')
                self.service.summarizer = self.old
                if vars(self.service).get(SLOT) is self: delattr(self.service, SLOT)
                self._active = False; self._phase = 'legacy_restored'
            except BaseException:
                self._phase = 'restore_refused'
                raise
            finally:
                self._release_gate()
            return self.status()

    def status(self):
        current = vars(self.service).get('summarizer')
        anchor = vars(self.service).get(SLOT)
        return dict(active=self._active and current is self.native and anchor is self,
            phase=self._phase, transition_pending=self._transition,
            owner='native_algorithm' if current is self.native and self.native is not None and anchor is self
                else 'original_algorithm' if current is self.old and self.old is not None and anchor is None else 'unknown',
            parameters_preserved=self._parameters is not None and vars(current) == self._parameters
                if current is not None and (current is self.old or current is self.native) else False,
            temporary_service_gates=len(self._wrappers), model_calls_created=0,
            tasks_created=0, stores_created=0, original_pipeline_changed=False,
            old_audit_static_calls_replaced=False)
