"""Read-only proof for handing the audited MC core tool to the native owner.

Only the SDK registry, loaded Python objects, fixed source files and current
event-loop await chains are inspected. No legacy getter or business method is
called. A binding is RAM-only; its public proof contains hashes, never IDs,
paths, configuration values or task locals.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from functools import lru_cache
import gc
import hashlib
import inspect
import json
import math
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import SimpleQueue
from types import AsyncGeneratorType, BuiltinFunctionType, CodeType, CoroutineType, GeneratorType, ModuleType

from .native_legacy_companion_inspection import _attrs, _registry

ROOT = 'astrbot_plugin_memory_companion'
MAX_TASKS = 512
MAX_DEPTH = 64
MAX_THREADS = 512
MAX_SOURCE_BYTES = 2_000_000
_SOURCE_HASHES = {
    'main': '4722e5a4cbe2acc7b9fb9a79b46ea54d7f72300f25af8bf2768091db3b844af7',
    'service': '6b1c9b52cc918cde66cfa14635720bfdde80332defff51278829030496d7fad2',
    'config': '0f277b5b294b8f9df9430c7db198b3df02ac3e40ac5ac836f23d31ae8a928b89',
    'store': 'a28468782823c0b2255ed2491ac14f6f2af44e7b00e6f17f85278d3ddc8327df',
}
_SERVICE_METHODS = ('tool_core_memory', 'core_memories_for_context',
    'list_core_memory_blocks', 'save_core_memory_block', 'delete_core_memory_block')
_CONFIG_METHODS = ('get', '_get_exact', 'bool')
_STORE_METHODS = ('list_core_memories', '_list_core_memories_sync',
    '_run_recoverable_database_operation', '_run_with_database_recovery_sync',
    'save_core_memory', '_save_core_memory_sync', 'delete_memory', '_delete_memory_sync')
_RLOCK_TYPE = type(threading.RLock())
_SALT = secrets.token_bytes(32)
_MISSING = object()
_CORE_STORE_NAMES = frozenset({'_save_core_memory_sync', '_delete_memory_sync', '_list_core_memories_sync'})


def _token(value):
    return hashlib.sha256(_SALT + str(id(value)).encode('ascii')).hexdigest()


def _json_digest(raw, *, dataclasses=False):
    """Bounded plain JSON snapshot, bypassing user-defined dict accessors."""
    seen = set(); nodes = 0
    def copy(value, depth):
        nonlocal nodes
        nodes += 1
        if depth > 16 or nodes > 16384: raise ValueError('configuration capacity')
        if value is None or type(value) in (bool, int, str):
            if type(value) is str and len(value) > 100000: raise ValueError('configuration capacity')
            return value
        if type(value) is float and math.isfinite(value): return value
        if dataclasses and is_dataclass(value) and not isinstance(value, type):
            if id(value) in seen: raise ValueError('configuration cycle')
            seen.add(id(value))
            try:
                # Bound and validate before asdict can recurse/deepcopy. The
                # complete asdict value is then hashed; no record is filtered.
                for item in fields(value): copy(object.__getattribute__(value, item.name), depth + 1)
                return copy(asdict(value), depth + 1)
            finally: seen.remove(id(value))
        if isinstance(value, dict) or type(value) in (list, tuple):
            if id(value) in seen: raise ValueError('configuration cycle')
            seen.add(id(value))
            try:
                if isinstance(value, dict):
                    if any(type(key) is not str for key in dict.keys(value)): raise ValueError('configuration key')
                    return {key: copy(item, depth + 1) for key, item in dict.items(value)}
                return [copy(item, depth + 1) for item in value]
            finally: seen.remove(id(value))
        raise ValueError('configuration object')
    encoded = json.dumps(copy(raw, 0), sort_keys=True, ensure_ascii=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_SOURCE_BYTES: raise ValueError('configuration capacity')
    return hashlib.sha256(encoded).hexdigest()


def _config_digest(raw):
    if not isinstance(raw, dict): raise ValueError('configuration root')
    return _json_digest(raw)


def _regular_file(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('source link')
    if not path.is_file(): raise ValueError('source file')
    with path.open('rb') as handle: value = handle.read(MAX_SOURCE_BYTES + 1)
    if len(value) > MAX_SOURCE_BYTES: raise ValueError('source capacity')
    return value


def _persisted_config(path):
    if (path.parent.parent.name != 'plugins' or path.parent.parent.parent.name != 'data'
            or '..' in path.parts): raise ValueError('fixed config layout unknown')
    config_path = path.parent.parent.parent / 'config' / (ROOT + '_config.json')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('duplicate configuration key')
            result[key] = value
        return result
    def constant(_): raise ValueError('nonfinite configuration value')
    persisted = json.loads(_regular_file(config_path).decode('utf-8-sig'),
        object_pairs_hook=pairs, parse_constant=constant)
    return _config_digest(persisted)


def _flag(raw, name):
    # Exact ConfigView._get_exact algorithm for these two non-aliased keys.
    # Missing/None values default True. The authority gate separately requires
    # the raw management flag to be the boolean False, not a false-like string.
    for method in ('get', '__contains__'):
        if inspect.getattr_static(raw, method, None) is not inspect.getattr_static(dict, method):
            raise ValueError('configuration dictionary accessor')
    group = dict.get(raw, 'core_memory', _MISSING)
    if group is _MISSING or group is None: value = _MISSING
    elif not isinstance(group, dict): raise ValueError('core configuration object')
    else:
        for method in ('get', '__contains__'):
            if inspect.getattr_static(group, method, None) is not inspect.getattr_static(dict, method):
                raise ValueError('configuration dictionary accessor')
        value = dict.get(group, name, _MISSING)
    def truth(value):
        if isinstance(value, dict): return dict.__len__(value) != 0
        if type(value) in (list, tuple): return len(value) != 0
        if type(value) in (bool, int, float): return bool(value)
        raise ValueError('configuration flag object')
    parsed = True if value is _MISSING or value is None else (
        value.strip().lower() in {'1', 'true', 'yes', 'on', '开', '开启'}
        if type(value) is str else truth(value))
    return parsed, value


@lru_cache(maxsize=8)
def _compiled(source, filename):
    # Compilation does not execute a module or import legacy business code.
    return compile(source, filename, 'exec', dont_inherit=True, optimize=sys.flags.optimize)


def _child(code, name):
    matches = [item for item in code.co_consts if isinstance(item, CodeType) and item.co_name == name]
    if len(matches) != 1: raise ValueError('source code shape')
    return matches[0]


def _method(owner, name, code, path):
    method = inspect.getattr_static(owner, name, None)
    if (not inspect.isfunction(method) or method.__code__ != code
            or Path(method.__code__.co_filename) != path
            or not isinstance(sys.modules.get(type(owner).__module__),ModuleType)
            or method.__globals__ is not vars(sys.modules[type(owner).__module__])):
        raise ValueError('loaded implementation mismatch: ' + name)
    return method.__code__


@dataclass(frozen=True, repr=False)
class _Snapshot:
    context: object
    metadata: object
    owner: object
    service: object
    config: object
    raw: dict
    module: ModuleType
    service_module: ModuleType
    config_module: ModuleType
    store_module: ModuleType
    store: object
    connection: sqlite3.Connection
    store_lock: object
    database_identity: str
    codes: tuple
    config_hash: str
    persisted_config_hash: str
    source_hashes: tuple
    tool_enabled: bool
    context_enabled: bool
    explicit_disabled: bool

    def proof(self):
        return dict(service_token=_token(self.service), config_token=_token(self.config),
            store_token=_token(self.store), connection_token=_token(self.connection),
            database_identity_sha256=self.database_identity,
            config_sha256=self.config_hash, persisted_config_sha256=self.persisted_config_hash,
            source_sha256=dict(self.source_hashes))


def _snapshot(context):
    rows = [row for row in _registry(context) if _attrs(row).get('root_dir_name') == ROOT]
    if len(rows) != 1: raise ValueError('registry_not_unique')
    metadata = rows[0]; meta = _attrs(metadata)
    if meta.get('activated') is not True: raise ValueError('owner_not_active')
    owner = meta.get('star_cls'); module = meta.get('module')
    if not isinstance(module, ModuleType): module = sys.modules.get(meta.get('module_path'))
    if not isinstance(module, ModuleType) or sys.modules.get(module.__name__) is not module:
        raise ValueError('loaded_module_unknown')
    main_file = _attrs(module).get('__file__')
    if type(main_file) is not str: raise ValueError('loaded_module_unknown')
    path = Path(main_file)
    if path.name != 'main.py' or path.parent.name != ROOT or not path.is_absolute():
        raise ValueError('exact_module_path_unknown')
    service = _attrs(owner).get('service'); config = _attrs(service).get('config')
    raw = _attrs(config).get('raw')
    if _attrs(owner).get('context') is not context or _attrs(service).get('context') is not context:
        raise ValueError('context_owner_mismatch')
    package = module.__name__.rsplit('.', 1)[0]
    service_module = sys.modules.get(package + '.core.service')
    config_module = sys.modules.get(package + '.core.config')
    store_module = sys.modules.get(package + '.core.store')
    if any(not isinstance(item, ModuleType) for item in (service_module,config_module,store_module)):
        raise ValueError('loaded_service_module_unknown')
    if (type(owner) is not _attrs(module).get('MemoryCompanionPlugin')
            or type(service) is not _attrs(service_module).get('MemoryCompanionService')
            or type(config) is not _attrs(config_module).get('ConfigView')
            or _attrs(module).get('MemoryCompanionService') is not type(service)
            or _attrs(service_module).get('ConfigView') is not type(config)):
        raise ValueError('loaded_class_mismatch')
    store = _attrs(service).get('store')
    if (type(store) is not _attrs(store_module).get('MemoryStore')
            or _attrs(service_module).get('MemoryStore') is not type(store)):
        raise ValueError('loaded_store_mismatch')
    sources = {}; classes = {}; files = {'main': path, 'service': path.parent / 'core' / 'service.py',
        'config': path.parent / 'core' / 'config.py', 'store': path.parent / 'core' / 'store.py'}
    modules = {'main': module, 'service': service_module, 'config': config_module, 'store': store_module}
    names = {'main': 'MemoryCompanionPlugin', 'service': 'MemoryCompanionService', 'config': 'ConfigView',
        'store': 'MemoryStore'}
    for key, filename in files.items():
        if _attrs(modules[key]).get('__file__') != str(filename) or filename.is_symlink():
            raise ValueError('source_path_mismatch')
        source = _regular_file(filename)
        digest = hashlib.sha256(source).hexdigest()
        if digest != _SOURCE_HASHES[key]: raise ValueError('source_hash_mismatch')
        sources[key] = digest
        classes[key] = _child(_compiled(source, str(filename)), names[key])
    codes = [_method(owner, 'memory_companion_core_memory_tool',
        _child(classes['main'], 'memory_companion_core_memory_tool'), path)]
    for name in _SERVICE_METHODS:
        codes.append(_method(service, name, _child(classes['service'], name), files['service']))
    for name in _CONFIG_METHODS:
        _method(config, name, _child(classes['config'], name), files['config'])
    for name in _STORE_METHODS:
        codes.append(_method(store,name,_child(classes['store'],name),files['store']))
    # Bind the exact existing connection and fixed SDK data directory. This
    # reads only the connection's database list; it never opens/initializes a DB.
    data_dir = path.parent.parent.parent / 'plugin_data' / ROOT
    db_path = data_dir / 'memory_companion.db'
    attrs = _attrs(store)
    if (_attrs(service).get('data_dir') != data_dir or attrs.get('db_path') != db_path
            or attrs.get('_closing') is not False or attrs.get('_closed') is not False
            or type(attrs.get('_conn')) is not sqlite3.Connection
            or type(attrs.get('_lock')) is not _RLOCK_TYPE):
        raise ValueError('actual_store_binding_unknown')
    for part in (db_path,*db_path.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('database link')
    if not db_path.is_file():raise ValueError('actual database absent')
    connection,store_lock=attrs['_conn'],attrs['_lock']
    if not store_lock.acquire(blocking=False):raise ValueError('actual store busy')
    try:
        cursor=connection.execute('PRAGMA database_list');cursor.row_factory=None
        try:databases=cursor.fetchall()
        finally:cursor.close()
    finally:store_lock.release()
    if (len(databases)!=1 or databases[0][1]!='main'
            or Path(databases[0][2]).resolve()!=db_path.resolve()):
        raise ValueError('actual connection database mismatch')
    stat=db_path.stat()
    database_identity=_json_digest(dict(path=str(db_path.resolve()),device=stat.st_dev,inode=stat.st_ino))
    # Neither of these keys has an alias in the audited ConfigView. A runtime
    # alias injection must not alter defaults behind our plain read.
    aliases = inspect.getattr_static(config, 'ALIASES', None)
    if (type(aliases) is not dict
            or any(dict.__contains__(aliases, 'core_memory.' + name)
                   for name in ('enabled', 'llm_management_enabled'))):
        raise ValueError('configuration_alias_mismatch')
    config_hash = _config_digest(raw)
    persisted_config_hash = _persisted_config(path)
    enabled, value = _flag(raw, 'llm_management_enabled')
    context_enabled, _ = _flag(raw, 'enabled')
    return _Snapshot(context, metadata, owner, service, config, raw, module,
        service_module, config_module, store_module,store,connection,store_lock,database_identity,
        tuple(codes), config_hash, persisted_config_hash,
        tuple(sorted(sources.items())), enabled, context_enabled, value is False)


def _same(before, after):
    return (all(getattr(before, key) is getattr(after, key) for key in (
        'context', 'metadata', 'owner', 'service', 'config', 'raw', 'module', 'service_module', 'config_module',
        'store_module','store','connection','store_lock'))
        and all(left is right for left, right in zip(before.codes, after.codes))
        and before.config_hash == after.config_hash and before.source_hashes == after.source_hashes
        and before.persisted_config_hash == after.persisted_config_hash
        and before.database_identity == after.database_identity
        and before.tool_enabled == after.tool_enabled and before.context_enabled == after.context_enabled
        and before.explicit_disabled == after.explicit_disabled)


def _core_code(code, codes):
    # A reference captured before an SDK reload can retain an older code object
    # while the current owner has a new equal implementation. Count the exact
    # known source/method pair conservatively, rather than requiring identity.
    return any((code is item or (code.co_name == item.co_name
        and code.co_filename == item.co_filename))
        and item.co_name not in {'_run_recoverable_database_operation','_run_with_database_recovery_sync'}
        for item in codes)


def _coroutine_wrapper_type():
    """Derive the exact CPython iterator type without running a coroutine."""
    if sys.implementation.name != 'cpython': return None
    async def sample(): return None
    coro = sample()
    try:
        wrapper = coro.__await__()
        try: return type(wrapper)
        finally: wrapper.close()
    finally: coro.close()


_COROUTINE_WRAPPER_TYPE = _coroutine_wrapper_type()


def _gc_referents_primitive():
    """Reject a Python replacement even if present before this module loads."""
    if type(gc) is not ModuleType: return None
    primitive = vars(gc).get('get_referents')
    if (type(primitive) is not BuiltinFunctionType or primitive.__name__ != 'get_referents'
            or primitive.__module__ != 'gc' or primitive.__self__ is not gc): return None
    return primitive


_GC_MODULE = gc
_GC_GET_REFERENTS = _gc_referents_primitive()


def _task_chain(task, codes, future_iter_type):
    current = task.get_coro(); seen = set(); found = False
    for _ in range(MAX_DEPTH):
        if current is None: return found, False
        if id(current) in seen: return found, True
        seen.add(id(current))
        # Exact built-in types avoid isinstance's possible __class__ lookup
        # on an unknown object. These CPython types cannot be subclassed.
        kind = type(current)
        if kind is CoroutineType: code, following = current.cr_code, current.cr_await
        elif kind is GeneratorType: code, following = current.gi_code, current.gi_yieldfrom
        elif kind is AsyncGeneratorType: code, following = current.ag_code, current.ag_await
        elif type(current) is _COROUTINE_WRAPPER_TYPE:
            # CPython coroutine.__await__ exposes no cr_await attribute. Its
            # exact built-in wrapper owns one native coroutine GC referent.
            # Follow only that closed shape, without invoking __await__/next,
            # reading unknown attributes or treating an opaque terminal safe.
            if (_GC_GET_REFERENTS is None or gc is not _GC_MODULE or type(gc) is not ModuleType
                    or vars(gc).get('get_referents') is not _GC_GET_REFERENTS): return found, True
            # Call the validated captured C function, not a mutable module
            # attribute read again after the identity check.
            referents = _GC_GET_REFERENTS(current)
            if (type(referents) is not list or len(referents) != 1
                    or type(referents[0]) is not CoroutineType): return found, True
            current = referents[0]
            continue  # Wrapper consumes the same depth/cycle budget as a node.
        elif type(current) is future_iter_type:
            return found, False  # A closed, ordinary terminal Future wait.
        else: return found, True
        found = found or _core_code(code, codes)
        current = following
    return found, current is not None


def _tasks(codes):
    loop = asyncio.get_running_loop(); tasks = asyncio.all_tasks(loop)
    if len(tasks) > MAX_TASKS: raise ValueError('task_scan_capacity')
    future_iter_type = type(loop.create_future().__await__())
    active = 0; uninspectable = 0
    for task in tasks:
        try:
            found, truncated = _task_chain(task, codes, future_iter_type)
            active += int(found); uninspectable += int(truncated)
        except Exception: uninspectable += 1
    # A currently running task exposes only its root coroutine through cr_await.
    # Walk code pointers in the current stack too, without accessing f_locals.
    frame = inspect.currentframe(); current_found = False
    try:
        for _ in range(MAX_DEPTH):
            if frame is None: break
            current_found = current_found or _core_code(frame.f_code, codes)
            frame = frame.f_back
        else: uninspectable += int(frame is not None)
    finally: del frame
    current = asyncio.current_task(loop)
    if current_found and current is not None:
        found, _ = _task_chain(current, codes, future_iter_type)
        active += int(not found)
    return len(tasks), active, uninspectable


def _threads(snapshot):
    """Code pointers only, including cancelled-parent to_thread operations."""
    getter = getattr(sys, '_current_frames', None)
    if not callable(getter): raise ValueError('thread inspection unsupported')
    frames = getter()
    if not isinstance(frames, dict) or len(frames) > MAX_THREADS: raise ValueError('thread capacity')
    main_file = Path(_attrs(snapshot.module)['__file__'])
    store_file = str(main_file.parent / 'core' / 'store.py')
    active = 0; unknown = 0
    try:
        for thread_id, frame in frames.items():
            if thread_id == threading.get_ident(): continue  # Counted in the event-loop task scan.
            core = False; recovery = False
            for _ in range(MAX_DEPTH):
                if frame is None: break
                code = frame.f_code
                core = core or _core_code(code, snapshot.codes)
                if code.co_filename == store_file:
                    core = core or code.co_name in _CORE_STORE_NAMES
                    recovery = recovery or code.co_name == '_run_with_database_recovery_sync'
                frame = frame.f_back
            else: unknown += int(frame is not None)
            active += int(core); unknown += int(recovery and not core)
    finally:
        del frames
        try: del frame
        except UnboundLocalError: pass
    # A cancelled parent can leave a queued executor operation with no frame.
    # Never inspect work-item arguments/locals: any queued work denies capture.
    loop = asyncio.get_running_loop(); executor = _attrs(loop).get('_default_executor')
    queued = 0
    if executor is not None:
        if type(executor) is not ThreadPoolExecutor: raise ValueError('executor unknown')
        queue = _attrs(executor).get('_work_queue')
        if type(queue) is not SimpleQueue: raise ValueError('executor queue unknown')
        queued = queue.qsize()
        if type(queued) is not int or queued < 0: raise ValueError('executor queue unknown')
    return active, unknown, queued


@dataclass(frozen=True, repr=False)
class CoreHandoffBinding:
    """Opaque internal binding; obtain only from a successful capture."""
    _snapshot: _Snapshot = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def proof(self):
        return self._snapshot.proof()

    def current(self):
        return core_gate_current(self)


_BINDING_SEAL = object()
_INVENTORY_SEAL = object()


@dataclass(frozen=True, repr=False)
class CoreInventoryProof:
    """Short-lived actual empty legacy inventory, never caller JSON authority."""
    _binding: CoreHandoffBinding = field(repr=False)
    _rows_sha256: str = field(repr=False)
    _observed_at: float = field(repr=False)
    _database_generation: tuple = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def proof(self):
        return dict(core_rows=0, inventory_sha256=self._rows_sha256,
            business_reads=1, gate_proof=self._binding.proof,
            query_scope='old_tool_active_core_query_superset',
            excluded_archived_pending_expired_unknown_preserved=True)

    def current(self, gate):
        age = time.monotonic() - self._observed_at
        try:
            return (self._seal is _INVENTORY_SEAL and gate is self._binding
                and 0 <= age <= 5.0 and core_gate_current(gate)
                and self._database_generation == _database_generation(gate._snapshot))
        except Exception:return False


def _database_generation(snapshot):
    if not snapshot.store_lock.acquire(blocking=False):raise ValueError('actual store busy')
    try:
        cursor=snapshot.connection.execute('PRAGMA data_version');cursor.row_factory=None
        try:return (snapshot.connection.total_changes,cursor.fetchone()[0])
        finally:cursor.close()
    finally:snapshot.store_lock.release()


async def capture_core_inventory(binding):
    """Handoff-only supported legacy read; never called by runtime core CRUD.

    Outer admin authentication must precede this helper. The exact pinned
    list_core_memory_blocks reads the active-query superset used by the old
    tool, including disabled/global/other-persona rows. Archived, pending,
    expired and not-yet-valid rows are excluded by that query and preserved in
    the old admin path. Any returned row requires a migration decision.
    """
    result = dict(schema='tls.native.core.inventory.v1', state='unknown', reason='gate_not_current',
        read_only=True, business_reads=0, business_writes=0, model_calls=0, sends=0,
        core_rows=None, inventory_sha256=None)
    result.update(query_scope='old_tool_active_core_query_superset',
        excluded_archived_pending_expired_unknown_preserved=True)
    if not core_gate_current(binding): return result, None
    try:
        service = binding._snapshot.service
        method = inspect.getattr_static(service, 'list_core_memory_blocks', None)
        index = 1 + _SERVICE_METHODS.index('list_core_memory_blocks')
        if not inspect.isfunction(method) or method.__code__ is not binding._snapshot.codes[index]:
            return result, None
        result['business_reads'] = 1
        generation=_database_generation(binding._snapshot)
        rows = await method(service)
        if not core_gate_current(binding):
            result['reason'] = 'gate_changed_during_read'; return result, None
        if generation != _database_generation(binding._snapshot):
            result['reason']='legacy_database_changed_during_read';return result,None
        if type(rows) is not list or len(rows) > 1000:
            result['reason'] = 'legacy_inventory_unbounded'; return result, None
        digest = _json_digest(rows, dataclasses=True)
        result.update(core_rows=len(rows), inventory_sha256=digest)
        if rows:
            result.update(state='blocked', reason='legacy_core_rows_require_migration'); return result, None
        proof = CoreInventoryProof(binding, digest, time.monotonic(), generation,_INVENTORY_SEAL)
        result.update(state='ready', reason='actual_old_tool_active_core_superset_empty')
        return result, proof
    except Exception:
        result['reason'] = 'legacy_inventory_read_failed'; return result, None


def core_gate_current(binding):
    """Worker-safe recheck of the same loaded closed gate; no task scanning."""
    from .native_mc_core_binding import NativeMCCoreBinding
    if type(binding) is NativeMCCoreBinding:
        return binding.current()
    if type(binding) is not CoreHandoffBinding or binding._seal is not _BINDING_SEAL: return False
    try:
        current = _snapshot(binding._snapshot.context)
        return (current.explicit_disabled and not current.tool_enabled and current.context_enabled
            and current.config_hash == current.persisted_config_hash
            and _same(binding._snapshot, current))
    except Exception: return False


def capture_core_handoff(context, *, inspect_tasks=True):
    """Return a content-free receipt and an optional RAM-only current binding.

    Ready means no old core call was visible in this event loop after the exact
    audited pre-await gate closed. It makes no global thread/other-loop claim.
    """
    from .native_mc_core_binding import capture_owned_core
    owned = capture_owned_core(context)
    if owned is not None:
        return dict(schema='tls.native.core.handoff.v1',state='ready',reason='tls_full_memory_successor',
            read_only=True,business_calls=0,model_calls=0,sends=0,owner_kind='tls_full_memory_companion'), owned
    result = dict(schema='tls.native.core.handoff.v1', state='unknown', reason='loaded_owner_unknown',
        read_only=True, business_calls=0, imports=0, model_calls=0, sends=0,
        old_tool_enabled=None, old_context_enabled=None, active_old_core_calls=None,
        task_inspection_available=False, observed_tasks=None, uninspectable_tasks=None,
        thread_inspection_available=False, active_old_core_threads=None,
        uninspectable_threads=None, queued_executor_work=None,
        observation_scope='current_python_event_loop_only', absolute_no_inflight_guarantee=False,
        threadpool_and_other_event_loops_observed=False)
    try: before = _snapshot(context)
    except Exception: return result, None
    result.update(old_tool_enabled=before.tool_enabled, old_context_enabled=before.context_enabled,
        proof=before.proof(), persisted_config_matches_live=before.config_hash == before.persisted_config_hash)
    if before.config_hash != before.persisted_config_hash:
        result.update(state='blocked', reason='persisted_config_differs_from_live'); return result, None
    if before.tool_enabled or not before.explicit_disabled:
        result.update(state='blocked', reason='old_tool_not_explicitly_disabled'); return result, None
    if not before.context_enabled:
        result.update(state='blocked', reason='old_context_not_preserved'); return result, None
    if inspect_tasks is not True:
        result['reason'] = 'task_inspection_not_requested'; return result, None
    try:
        total, active, unknown = _tasks(before.codes)
        thread_active, thread_unknown, queued = _threads(before)
        result.update(thread_inspection_available=True, active_old_core_threads=thread_active,
            uninspectable_threads=thread_unknown, queued_executor_work=queued)
        result.update(task_inspection_available=True, observed_tasks=total,
            active_old_core_calls=None if unknown else active, uninspectable_tasks=unknown)
        after = _snapshot(context)
        if not _same(before, after):
            result['reason'] = 'loaded_owner_changed'; return result, None
    except RuntimeError:
        result['reason'] = 'event_loop_not_observable'; return result, None
    except Exception:
        result['reason'] = 'task_observation_unknown'; return result, None
    if active or thread_active:
        result.update(state='blocked', reason='old_core_call_in_flight'); return result, None
    if unknown or thread_unknown or queued:
        result['reason'] = 'task_observation_incomplete'; return result, None
    result.update(state='ready', reason='closed_gate_and_no_visible_old_core_calls')
    return result, CoreHandoffBinding(after, _BINDING_SEAL)


def observe_core_handoff(context, *, inspect_tasks=True):
    """Public serializable observation. The internal binding is not exposed."""
    return capture_core_handoff(context, inspect_tasks=inspect_tasks)[0]
