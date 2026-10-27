"""Exact-source bridge for the existing PC memo implementation slot.

No tool registration, owner grant, scope manufacture, worker or PC disk write.
The compatibility slot remains after TLS stop, so native identifiers cannot
fall back into the original store during a TLS reload.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
import sys
import threading
import types


PC_ROOT = 'astrbot_plugin_private_companion'
TLS_ROOT = 'astrbot_plugin_virtual_body'
PROTOCOL = 'tls.native.memo_tool.pc_router.v1'
SLOT = '_pc_manage_memo_impl'
LEGACY_SLOT = '_tls_legacy_pc_manage_memo_impl'
_BINDING = '_tls_native_memo_runtime_binding'
SOURCE_PINS = {
    'main.py': '43df488644dd4621b3f720d682214cfe48fb43fbc7665f4c93e7acc84c6b0e94',
    'llm_tool_actions.py': 'b4f97f72a729f83a3941b0e93c0937130818af160ac9fbfe291e6c2e87847825',
    'tls_memo_tool_adapter.py': 'ea8a834be8efa7cd01b5cb71ee52da73a7f61823f75b6cf50e8d936477a9a09d',
    'proactive.py': 'b26d068d386b3acb3f5f57bebdd35d3249bc2e978c438c72776ffb9d325f1ac4',
}
_MAX_SOURCE = 4 * 1024**2


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _code_tree(code):
    """Compare executable structure, excluding source positions and renamed IDs."""
    def constant(value):
        if isinstance(value, types.CodeType):
            return {'code': _code_tree(value)}
        if value is None or type(value) in (str, int, bool):
            return [type(value).__name__, value]
        if type(value) is float:
            return ['float', value.hex()]
        if type(value) is complex:
            return ['complex', value.real.hex(), value.imag.hex()]
        if type(value) is bytes:
            return ['bytes', value.hex()]
        if type(value) is tuple:
            return ['tuple', [constant(item) for item in value]]
        if type(value) is frozenset:
            return ['frozenset', sorted((constant(item) for item in value), key=repr)]
        if value is Ellipsis:
            return ['ellipsis']
        raise ValueError('unsupported code constant')
    return dict(argcount=code.co_argcount, posonly=code.co_posonlyargcount,
        kwonly=code.co_kwonlyargcount, nlocals=code.co_nlocals, stack=code.co_stacksize,
        flags=code.co_flags, bytecode=code.co_code.hex(),
        exceptiontable=getattr(code, 'co_exceptiontable', b'').hex(),
        consts=[constant(item) for item in code.co_consts], names=code.co_names,
        varnames=code.co_varnames, freevars=code.co_freevars, cellvars=code.co_cellvars)


def code_fingerprint(code):
    if not isinstance(code, types.CodeType):
        raise ValueError('real loaded code required')
    return hashlib.sha256(_canonical(_code_tree(code))).hexdigest()


def _find_code(code, name):
    found = []
    def visit(current):
        if current.co_name == name:
            found.append(current)
        for item in current.co_consts:
            if isinstance(item, types.CodeType):
                visit(item)
    visit(code)
    if len(found) != 1:
        raise ValueError('exact compiled method required')
    return found[0]


def _read_sources(directory):
    result = {}
    for name, expected in SOURCE_PINS.items():
        path = directory / name
        if path.is_symlink() or path.stat().st_size > _MAX_SOURCE:
            raise ValueError('bounded regular reviewed PC source required')
        with path.open('rb') as stream:
            raw = stream.read(_MAX_SOURCE + 1)
        if len(raw) > _MAX_SOURCE or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('reviewed PC overlay source changed')
        result[name] = raw
    return result


def _registry(context):
    getter = getattr(context, 'get_all_stars', None)
    if not callable(getter):
        raise ValueError('actual SDK registry required')
    rows = getter()
    if type(rows) not in (list, tuple) or len(rows) > 128:
        raise ValueError('bounded actual SDK registry required')
    return rows


def _metadata(context, root, expected=None):
    rows = [row for row in _registry(context) if getattr(row, 'root_dir_name', None) == root]
    if len(rows) != 1:
        raise ValueError('unique current plugin required')
    row = rows[0]
    instance = getattr(row, 'star_cls', None)
    if (getattr(row, 'activated', None) is not True or instance is None
            or getattr(instance, 'context', None) is not context
            or expected is not None and instance is not expected):
        raise ValueError('exact current active plugin instance required')
    return row, instance


def _same_family(value, cls):
    return value is not None and any(base.__module__ == cls.__module__
        and base.__name__ == cls.__name__ for base in type(value).__mro__)


class NativeMemoPCSourceProof:
    """Compile the reviewed renamed helper; never inspect changed disk lines."""
    def __init__(self, pc):
        module = sys.modules.get(type(pc).__module__)
        path = getattr(module, '__file__', None)
        if not isinstance(path, str):
            raise ValueError('real PC main module path required')
        path = Path(path)
        if path.name != 'main.py' or path.parent.name != PC_ROOT or path.is_symlink():
            raise ValueError('exact PC main source location required')
        self.pc, self.module, self.directory = pc, module, path.parent.resolve()
        sources = _read_sources(self.directory)
        code = compile(sources['llm_tool_actions.py'], '<reviewed-PC-overlay>', 'exec', dont_inherit=True)
        self.legacy_code_sha256 = code_fingerprint(_find_code(code, LEGACY_SLOT))
        self.patched_code_sha256 = code_fingerprint(_find_code(code, SLOT))
        self.previous_binding_sha256 = hashlib.sha256(_canonical(dict(schema='tls.memo.single_slot.proof.v1',
            sources={key:value for key,value in SOURCE_PINS.items() if key != 'proactive.py'}, slot=SLOT, legacy_code=self.legacy_code_sha256,
            patched_code=self.patched_code_sha256))).hexdigest()
        namespace = {'__name__': '_tls_reviewed_pc_memo_adapter'}
        exec(compile(sources['tls_memo_tool_adapter.py'], '<reviewed-PC-adapter>', 'exec', dont_inherit=True), namespace)
        self.adapter, self.classify = namespace['dispatch_memo_tool'], namespace['_kind']
        if namespace['PROTOCOL'] != PROTOCOL or not inspect.iscoroutinefunction(self.adapter):
            raise ValueError('reviewed thin adapter required')
        from .native_memo_legacy_origin import NativeMemoLegacyOriginInspector
        self.origin = NativeMemoLegacyOriginInspector(pc,pc.context,source_current=self._base_current)
        self.binding_sha256 = hashlib.sha256(_canonical(dict(schema='tls.memo.single_slot.proof.v2',
            sources=SOURCE_PINS, slot=SLOT, legacy_code=self.legacy_code_sha256,
            patched_code=self.patched_code_sha256,constructor=self.origin.constructor_sha256,
            native_domain='distinct_bot_sender_and_no_synthetic.v1'))).hexdigest()

    def _base_current(self):
        try:
            path = Path(getattr(sys.modules.get(type(self.pc).__module__), '__file__', ''))
            return (sys.modules.get(type(self.pc).__module__) is self.module
                and path.name == 'main.py' and path.parent.resolve() == self.directory
                and bool(_read_sources(self.directory)))
        except Exception:
            return False

    def current(self):
        return self._base_current() and self.origin.current()

    def original(self, method):
        if not inspect.ismethod(method) or method.__self__ is not self.pc:
            raise ValueError('real loaded bound PC implementation required')
        fingerprint = code_fingerprint(method.__func__.__code__)
        if fingerprint == self.legacy_code_sha256:
            return method
        if fingerprint == self.patched_code_sha256:
            original = getattr(self.pc, LEGACY_SLOT, None)
            if (inspect.ismethod(original) and original.__self__ is self.pc
                    and code_fingerprint(original.__func__.__code__) == self.legacy_code_sha256):
                return original
        raise ValueError('loaded original differs from reviewed renamed helper')


def _retained_binding(pc):
    record = vars(pc).get(_BINDING)
    wrapper = vars(pc).get(SLOT)
    if record is None:
        return None
    if (not _same_family(record, NativeMemoPCBinding) or record.pc is not pc
            or record.context is not getattr(pc, 'context', None)
            or record.wrapper is not wrapper or not inspect.ismethod(wrapper)
            or wrapper.__self__ is not pc
            or code_fingerprint(wrapper.__func__.__code__) != code_fingerprint(_memo_compat.__code__)
            or not _same_family(record.proof, NativeMemoPCSourceProof)
            or record.proof.pc is not pc or not inspect.ismethod(record.original)
            or record.original.__self__ is not pc
            or code_fingerprint(record.original.__func__.__code__) != record.proof.legacy_code_sha256):
        raise ValueError('unreviewed retained PC slot owner')
    for name in ('current','legacy','call'):
        method=getattr(record,name,None)
        if (not inspect.ismethod(method) or method.__self__ is not record
                or code_fingerprint(method.__func__.__code__) != code_fingerprint(getattr(NativeMemoPCBinding,name).__code__)):
            raise ValueError('unreviewed retained PC binding method')
    return record


def _originals_drained(loop, legacy_code_sha256):
    try:
        tasks=asyncio.all_tasks(loop)
        if len(tasks)>512:return False
        for task in tasks:
            current,seen=task.get_coro(),set()
            for _ in range(128):
                if current is None:break
                if id(current) in seen:return False
                seen.add(id(current))
                code=getattr(current,'cr_code',getattr(current,'gi_code',getattr(current,'ag_code',None)))
                if (isinstance(code,types.CodeType) and code.co_name in (SLOT,LEGACY_SLOT)
                        and code_fingerprint(code)==legacy_code_sha256):return False
                current=getattr(current,'cr_await',getattr(current,'gi_yieldfrom',getattr(current,'ag_await',None)))
            else:return False
        return True
    except Exception:return False


async def _memo_compat(pc, event, **payload):
    try:
        record = _retained_binding(pc)
        if record is None:
            raise ValueError('binding absent')
        return await record.call(event, payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        return json.dumps(dict(status='unavailable', saved=False,
            code='memo_runtime_binding_unavailable', legacy_fallback_permitted=False,
            native_result_unknown=True, schedules_reminder=False,
            external_completion_confirmed=False), separators=(',', ':'))


class NativeMemoPCBinding:
    def __init__(self, context, pc, proof, original):
        self.context, self.pc, self.proof, self.original = context, pc, proof, original
        self.wrapper = types.MethodType(_memo_compat, pc)
        self.closed, self.legacy_inflight = False, 0
        self.controller = None

    def current(self):
        try:
            return (_metadata(self.context, PC_ROOT, self.pc)[1] is self.pc
                and vars(self.pc).get(SLOT) is self.wrapper
                and vars(self.pc).get(_BINDING) is self and self.proof.current()
                and code_fingerprint(self.original.__func__.__code__) == self.proof.legacy_code_sha256)
        except Exception:
            return False

    async def legacy(self, event, **payload):
        if not self.current():
            raise PermissionError('current PC source and bound slot required')
        self.legacy_inflight += 1
        try:
            return await self.original(event, **payload)
        finally:
            self.legacy_inflight -= 1

    async def call(self, event, payload):
        if not self.current():
            raise PermissionError('current PC source and bound slot required')
        if self.closed:
            if self.proof.classify(payload) == 'legacy':
                return await self.legacy(event, **payload)
            return json.dumps(dict(status='unavailable', saved=False,
                code='memo_runtime_stopped', legacy_fallback_permitted=False,
                native_result_unknown=True, schedules_reminder=False,
                external_completion_confirmed=False), separators=(',', ':'))
        return await self.proof.adapter(self.pc, event, dict(payload), self.legacy)


def _native_pc_successor(context, tls_plugin):
    """A genuine TLS owner after normal old-PC retirement, not a fake Star."""
    _metadata(context, TLS_ROOT, tls_plugin)
    old = [row for row in _registry(context) if getattr(row, 'root_dir_name', None) == PC_ROOT]
    if len(old) != 1 or getattr(old[0], 'activated', None) is not False: return None
    integrations = getattr(tls_plugin, '_native_server_integrations', None)
    owner = getattr(integrations, 'pc_full', None)
    pc = getattr(owner, 'service', None)
    from .native_pc_service import NativePCService
    if (integrations is None or getattr(integrations, 'context', None) is not context
            or getattr(integrations, 'plugin', None) is not tls_plugin or getattr(integrations, '_closed', True)
            or owner is None or getattr(owner, 'context', None) is not context
            or getattr(owner, 'active', False) is not True or not isinstance(pc, NativePCService)
            or getattr(pc, 'context', None) is not context or pc.active is not True
            or not callable(getattr(owner, 'legacy_closed', None)) or owner.legacy_closed() is not True
            or pc.native_source_current() is not True): return None
    return owner, pc


class NativeMemoSuccessorProof:
    """Continue the retired native memo binding hash, never rewrite its ledger."""
    def __init__(self, context, plugin, owner, pc):
        self.context, self.plugin, self.owner, self.pc = context, plugin, owner, pc
        state = getattr(owner, 'binding_state', None)
        if (type(state) is not dict or state.get('source_kind') != 'retired_legacy_pc'
                or any(type(state.get(key)) is not str or len(state[key]) != 64
                       or any(c not in '0123456789abcdef' for c in state[key])
                       for key in ('binding_sha256', 'legacy_source_sha256', 'legacy_config_sha256'))):
            raise ValueError('actual retired PC memo binding state required')
        self._state = _canonical(state); self.binding_sha256 = state['binding_sha256']
        original = getattr(pc, SLOT, None)
        if not inspect.ismethod(original) or original.__self__ is not pc:
            raise ValueError('actual native PC memo implementation required')
        self.legacy_code_sha256 = code_fingerprint(original.__func__.__code__)
        from .native_memo_legacy_origin import NativeMemoSuccessorOriginInspector
        self.origin = NativeMemoSuccessorOriginInspector(pc, context, source_current=self.current)

    def current(self):
        try:
            value = _native_pc_successor(self.context, self.plugin)
            return (value is not None and value[0] is self.owner and value[1] is self.pc
                    and _canonical(self.owner.binding_state) == self._state)
        except Exception: return False


async def _memo_successor_compat(pc, event, **payload):
    record = vars(pc).get(_BINDING)
    if not isinstance(record, NativeMemoSuccessorBinding) or record.pc is not pc or not record.current():
        return json.dumps(dict(status='unavailable', saved=False, code='native_pc_memo_binding_unavailable'))
    return await record.call(event, payload)


class NativeMemoSuccessorBinding:
    def __init__(self, context, pc, proof, original):
        self.context, self.pc, self.proof, self.original = context, pc, proof, original
        self.wrapper = types.MethodType(_memo_successor_compat, pc)
        self.closed, self.legacy_inflight, self.controller = False, 0, None

    def current(self):
        return (self.proof.current() and vars(self.pc).get(_BINDING) is self
                and vars(self.pc).get(SLOT) is self.wrapper
                and code_fingerprint(self.wrapper.__func__.__code__) == code_fingerprint(_memo_successor_compat.__code__))

    async def legacy(self, event, **payload):
        # The prior global legacy store remains preserved. No new full-scope
        # owner is inferred for legacy IDs or SyntheticPrivateWakeEvent calls.
        return json.dumps(dict(status='unavailable', saved=False,
            code='retired_legacy_memo_write_not_reopened', legacy_fallback_permitted=False,
            schedules_reminder=False, external_completion_confirmed=False))

    async def call(self, event, payload):
        if self.closed or not self.current():
            return json.dumps(dict(status='unavailable', saved=False, code='native_pc_memo_runtime_stopped'))
        bridge = self.controller
        controller = getattr(bridge.tls_plugin, '_native_memo_tool_router', None) if bridge else None
        router = getattr(controller, 'router', None)
        if (controller is None or getattr(controller, 'bridge', None) is not bridge
                or router is None or getattr(router, 'active', False) is not True):
            return json.dumps(dict(status='unavailable', saved=False, code='current_native_memo_router_required'))
        return await router.dispatch(self.pc, event, dict(payload), self.legacy)


class NativeMemoRuntimeBridge:
    def __init__(self, context, tls_plugin):
        self.context, self.tls_plugin = context, tls_plugin
        self._loop, self._thread = asyncio.get_running_loop(), threading.get_ident()
        self._binding = self._pc = self._tls_metadata = None
        self._closed = False
        self._successor = False

    @property
    def pc(self):
        return self._pc

    @property
    def binding_sha256(self):
        return self._binding.proof.binding_sha256 if self._binding is not None else None

    def _same_loop(self):
        try:
            return threading.get_ident() == self._thread and asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    def bind(self):
        if self._closed or not self._same_loop():
            raise PermissionError('live same-loop bridge required')
        tls_metadata, _ = _metadata(self.context, TLS_ROOT, self.tls_plugin)
        successor = _native_pc_successor(self.context, self.tls_plugin)
        if successor is not None:
            owner, pc = successor
            if self._binding is not None:
                if self.source_current(): return self.diagnostics()
                raise ValueError('stop the prior memo bridge before binding a new native PC instance')
            record = vars(pc).get(_BINDING)
            if record is not None:
                if (not isinstance(record, NativeMemoSuccessorBinding) or record.closed is not True
                        or not record.current()): raise ValueError('current stopped native successor binding required')
                record.closed = False
            else:
                original = getattr(pc, SLOT, None)
                proof = NativeMemoSuccessorProof(self.context, self.tls_plugin, owner, pc)
                record = NativeMemoSuccessorBinding(self.context, pc, proof, original)
                setattr(pc, _BINDING, record); setattr(pc, SLOT, record.wrapper)
            record.controller = self
            self._successor = True
            self._binding, self._pc, self._tls_metadata = record, pc, tls_metadata
            if not self.source_current():
                record.closed = True
                raise ValueError('native PC source or retired binding changed during attachment')
            return self.diagnostics()
        _, pc = _metadata(self.context, PC_ROOT)
        if self._binding is not None:
            if self.source_current():
                return self.diagnostics()
            raise ValueError('stop old bridge before rebinding replaced PC')
        proof = NativeMemoPCSourceProof(pc)
        record = _retained_binding(pc)
        if record is not None:
            if record.closed is not True:
                raise ValueError('only reviewed stopped binding may be reused')
            if record.proof.binding_sha256 == proof.binding_sha256:
                if not record.current():raise ValueError('reviewed stopped binding changed')
                record.closed = False
            elif (record.proof.binding_sha256 == proof.previous_binding_sha256
                    and type(record.legacy_inflight) is int and record.legacy_inflight==0
                    and proof.current() and _originals_drained(self._loop,proof.legacy_code_sha256)):
                # Replace the stopped record and slot together. Never mutate
                # its old proof or reopen an unwrapped legacy implementation.
                # Captured old _memo_compat references re-read the current PC
                # slot record and therefore cannot revive the old controller.
                record=NativeMemoPCBinding(self.context,pc,proof,proof.original(record.original))
                setattr(pc,_BINDING,record)
                setattr(pc,SLOT,record.wrapper)
            else:raise ValueError('retained binding migration requires exact source and complete old drain')
        else:
            original = proof.original(getattr(pc, SLOT, None))
            record = NativeMemoPCBinding(self.context, pc, proof, original)
            # One SDK implementation slot. No SDK registry/tool mutation.
            setattr(pc, _BINDING, record)
            setattr(pc, SLOT, record.wrapper)
        record.controller = self
        self._binding, self._pc, self._tls_metadata = record, pc, tls_metadata
        if not self.source_current():
            record.closed = True
            raise ValueError('source or registry changed during binding')
        return self.diagnostics()

    def source_current(self):
        try:
            if self._successor:
                return (not self._closed and self._loop.is_running() and not self._loop.is_closed()
                    and isinstance(self._binding, NativeMemoSuccessorBinding) and self._binding.closed is False
                    and self._binding.current() and self._binding.controller is self
                    and _metadata(self.context, TLS_ROOT, self.tls_plugin)[0] is self._tls_metadata)
            # Existing memo mutations execute in asyncio.to_thread. This is a
            # synchronous read proof, also used by their final owner guard.
            # Only bind mutates the slot and remains restricted to its loop.
            return (not self._closed and self._loop.is_running() and not self._loop.is_closed()
                and self._binding is not None
                and self._binding.closed is False and self._binding.current()
                and self._binding.controller is self
                and _metadata(self.context, TLS_ROOT, self.tls_plugin)[0] is self._tls_metadata
                and _metadata(self.context, PC_ROOT, self._pc)[1] is self._pc)
        except Exception:
            return False

    def pc_current(self, pc):
        return pc is self._pc and self.source_current()

    def native_identity_domain(self,event):
        return self.source_current() and self._binding.proof.origin.native_identity_domain(event)

    def legacy_origin(self,event,*,native_history_clear):
        if not self.source_current():return None
        return self._binding.proof.origin.prove(event,native_history_clear=native_history_clear)

    def old_drained(self, scope=None):
        """Observe already-entered originals too, including nested await chains."""
        if not self.source_current() or self._binding.legacy_inflight != 0:
            return False
        if self._successor:
            return self._binding.proof.owner.legacy_closed() is True
        return _originals_drained(self._loop,self._binding.proof.legacy_code_sha256)

    def stop(self):
        self._closed = True
        if self._binding is not None and self._binding.controller is self:
            self._binding.closed = True
        return self.diagnostics()

    def diagnostics(self):
        return dict(schema='tls.memo.runtime_bridge.v1', bound=self._binding is not None,
            active=self.source_current(), stopped=self._closed,
            binding_sha256=self.binding_sha256, implementation_slots=1 if self._binding else 0,
            legacy_inflight=self._binding.legacy_inflight if self._binding else 0,
            registers_tool=False, creates_scope=False, creates_owner=False,
            writes_pc_source=False, restores_unwrapped_legacy_on_stop=False,
            sends=0, models=0, worker_created=False,
            native_pc_successor=self._successor, original_binding_hash_preserved=self._successor)
