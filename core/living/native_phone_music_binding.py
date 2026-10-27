"""Explicit, process-local CAS binding of the retained Phone music collector.

This module is deliberately not wired into Host or plugin startup. A trusted
caller must supply the actual loaded Phone instance and an independently
authorized complete TLS scope. It does not import/reload Phone, register a
Presence source, grant sends, or persist an ownership claim. Restart/reload
requires a fresh binding; stale references fail closed rather than adopting a
new instance. The collector and its listening accumulator remain legacy-owned.
"""
from __future__ import annotations

import asyncio
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import threading
import types

from . import native_music_catalog as catalog_module
from .native_phone_music_projection import build_music_event, unknown_music

SOURCE_SHA256 = {
    'main.py': 'c966b04fd8554dd0d5dbc50a71b77d3dbb73b6461b52095edad57edcb8d07973',
    'music_context.py': '641a1f6b725c790d0d9e186db2299d012728ab021e980dab6c587a9e124495ac',
    'music_index.py': 'c698fa764b895b244e4e20c56fba627b5a5d09f349922b9e8fb4bc05cc44e319',
    'context_aggregator.py': 'e392e5bc728dc329d45631d3a3c71d9498ce6b36080dca1daf2a22a8e8a2a739',
}
_CONFIG_KEYS = ('enable_phone_perception', 'enable_music_context', 'allowed_user_ids',
    'music_user_devices', 'music_preferred_device', 'music_stale_seconds', 'device_ids',
    'device_id', 'bridge_base_url', 'bridge_token', 'stale_minutes', 'timeout_seconds')
_SCOPE_KEYS = frozenset(('platform', 'bot_id', 'user_id', 'character_id', 'session_id', 'private'))


class MusicBindingConflict(RuntimeError):
    """A fixed diagnostic only; never include private bindings in errors."""


def _scope(value):
    if (type(value) is not dict or set(value) != _SCOPE_KEYS or value['private'] is not True
            or any(type(value[key]) is not str or not 1 <= len(value[key]) <= 256
                   or any(ord(c) < 32 for c in value[key]) for key in _SCOPE_KEYS - {'private'})):
        raise MusicBindingConflict('complete_exact_scope_required')
    return dict(value)


def _json(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(raw.encode()) > 65536:
        raise MusicBindingConflict('configuration_bound_exceeded')
    return raw


def _code_equal(actual, expected):
    if not isinstance(actual, types.CodeType) or not isinstance(expected, types.CodeType):
        return False
    fields = ('co_code', 'co_names', 'co_varnames', 'co_argcount', 'co_posonlyargcount',
        'co_kwonlyargcount', 'co_nlocals', 'co_stacksize', 'co_flags', 'co_freevars', 'co_cellvars')
    if any(getattr(actual, key) != getattr(expected, key) for key in fields) or len(actual.co_consts) != len(expected.co_consts):
        return False
    return all(_code_equal(a, b) if isinstance(a, types.CodeType) or isinstance(b, types.CodeType)
               else type(a) is type(b) and a == b for a, b in zip(actual.co_consts, expected.co_consts))


def _codes(code):
    result = {}
    for child in code.co_consts:
        if isinstance(child, types.CodeType):
            result[child.co_qualname] = child
            result.update(_codes(child))
    return result


def _regular(path, maximum=2 * 1024 * 1024):
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise MusicBindingConflict('source_identity_unavailable')
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise MusicBindingConflict('source_identity_unavailable')
    return raw


def _signature(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _capture_phone_parts(phone):
    """Shared source/object validation; no scope, callback or binding mutation."""
    parts = types.SimpleNamespace()
    parts.phone = phone
    parts.provider = phone._music_provider
    parts.aggregator = phone._context_aggregator
    parts.original_index = phone._music_index
    parts.config = phone.config
    parts.context = phone.context
    parts._stage, parts._active, parts.generation = 'prepared', False, 0
    parts._modules = {}
    parts._source_signatures = {}
    for name, obj in (('main.py', type(phone)), ('music_context.py', type(parts.provider)),
                      ('music_index.py', type(parts.original_index)), ('context_aggregator.py', type(parts.aggregator))):
        module = sys.modules.get(obj.__module__)
        if type(module) is not types.ModuleType or not isinstance(getattr(module, '__file__', None), str):
            raise MusicBindingConflict('loaded_module_identity_required')
        path = Path(module.__file__)
        if not path.is_absolute() or path.name != name:
            raise MusicBindingConflict('loaded_module_identity_required')
        raw = _regular(path)
        if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256[name]:
            raise MusicBindingConflict('source_pin_mismatch')
        parts._modules[name] = (module, path, raw)
        parts._source_signatures[name] = _signature(path)
    roots = {path.parent for _, path, _ in parts._modules.values()}
    if len(roots) != 1:
        raise MusicBindingConflict('loaded_module_identity_required')
    main = parts._modules['main.py'][0]
    music = parts._modules['music_context.py'][0]
    index_module = parts._modules['music_index.py'][0]
    aggregator_module = parts._modules['context_aggregator.py'][0]
    if (type(phone) is not main.PhonePerceptionPlugin or type(parts.provider) is not music.MusicContextProvider
            or type(parts.original_index) is not index_module.MusicIndex
            or type(parts.aggregator) is not aggregator_module.ContextAggregator
            or parts.provider.index is not parts.original_index
            or parts.aggregator._providers.get('music') is not parts.provider
            or main.build_music_event is not music.build_music_event):
        raise MusicBindingConflict('object_binding_mismatch')
    parts._function_bindings = []
    for module, path, raw in parts._modules.values():
        expected = _codes(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0))
        # Enumerate pinned definitions, not only currently native-looking
        # functions: a foreign replacement must not disappear from checks.
        for node in ast.parse(raw).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates = [(module, node.name, node.name)]
            elif isinstance(node, ast.ClassDef):
                owner = vars(module).get(node.name)
                if not isinstance(owner, type) or owner.__module__ != module.__name__:
                    raise MusicBindingConflict('loaded_code_mismatch')
                candidates = [(owner, child.name, node.name + '.' + child.name) for child in node.body
                              if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            else:
                continue
            for owner, key, qualname in candidates:
                item = vars(owner).get(key)
                function = item.__func__ if isinstance(item, (staticmethod, classmethod)) else item
                if (not isinstance(function, types.FunctionType) or function.__module__ != module.__name__
                        or function.__qualname__ != qualname or function.__globals__ is not vars(module)
                        or not _code_equal(function.__code__, expected.get(qualname))):
                    raise MusicBindingConflict('loaded_code_mismatch')
                parts._function_bindings.append((owner, key, item))
    parts._function_codes = tuple((item.__func__ if isinstance(item, (staticmethod, classmethod)) else item,
                                  (item.__func__ if isinstance(item, (staticmethod, classmethod)) else item).__code__)
                                 for _, _, item in parts._function_bindings)
    parts._instance_methods = [(obj, tuple(key for owner, key, _ in parts._function_bindings if owner is type(obj)))
                              for obj in (phone, parts.provider, parts.original_index, parts.aggregator)]
    if any(any(key in vars(obj) for key in methods) for obj, methods in parts._instance_methods):
        raise MusicBindingConflict('loaded_code_mismatch')
    path = parts.original_index.path
    if (not isinstance(path, Path) or not path.is_absolute()
            or path.parts[-3:] != ('astrbot_plugin_phone_perception', 'music', 'music_index.json')
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise MusicBindingConflict('catalog_path_identity_required')
    parts._catalog_path = path
    parts._unlinked_paths = frozenset(part for _, source, _ in parts._modules.values()
                                    for part in (source, *source.parents)) | frozenset((path, *path.parents))
    if len(parts._unlinked_paths) > 128:
        raise MusicBindingConflict('source_identity_unavailable')
    parts._entry_bindings = [
        (main, "build_music_event", main.build_music_event),
        (music, "build_music_event", music.build_music_event),
        (music, "display_text", music.display_text),
        (music, "normalize_text", music.normalize_text),
        (music, "match_music", music.match_music),
        (phone, "_music_index", parts.original_index),
        (parts.provider, "index", parts.original_index),
    ]
    return parts


class _CatalogProjection:
    """Only the existing diagnostics get/error_type and parser match surface."""
    def __init__(self, binding):
        self._binding = binding

    @property
    def error_type(self):
        return self._binding.catalog.error_type if self._binding.current() else 'MusicBindingUnavailable'

    def get(self):
        if not self._binding.current():
            return {}
        value = self._binding.catalog.get()
        return value if self._binding.current() else {}

    def match(self, title, artist=''):
        if not self._binding.current():
            return dict(status='unknown', song_id='', song_info={}, candidate_count=0,
                        match_method='', reason='native_binding_unavailable')
        value = self._binding.catalog.match(title, artist)
        return value if self._binding.current() else dict(status='unknown', song_id='', song_info={},
            candidate_count=0, match_method='', reason='native_binding_unavailable')


class NativePhoneMusicBinding:
    """Seven RAM slots, one event-loop callback, and exact identity CAS restore.

    No await occurs while switching slots. Pinned collector code reads these
    globals/attributes after its bridge await; it does not retain a parser or
    index local across that await. Existing synchronous parser frames on any
    thread block a switch. This is a known-call-path contract, not a claim that
    Python cannot retain arbitrary external references to a legacy function.
    """
    def __init__(self, phone, *, scope=None, current_scope=None, authorize=None, source_grant=None):
        self._source_grant = source_grant
        if source_grant is not None:
            from .native_phone_music_source_grant import source_read_grant_current
            if (scope is not None or current_scope is not None or authorize is not None
                    or not source_read_grant_current(source_grant, phone)):
                raise MusicBindingConflict('exclusive_current_source_grant_required')
            self._scope = None  # Source permission never fabricates a private identity.
            self._current_scope = self._authorize = None
        else:
            if not callable(current_scope) or not callable(authorize):
                raise MusicBindingConflict('live_scope_callbacks_required')
            self._scope = _scope(scope)
            self._current_scope, self._authorize = current_scope, authorize
        self._loop = asyncio.get_running_loop()
        self._thread = threading.get_ident()
        vars(self).update(vars(_capture_phone_parts(phone)))
        path = self._catalog_path
        main = self._modules["main.py"][0]
        music = self._modules["music_context.py"][0]
        self.catalog = catalog_module.NativeMusicCatalog(path)
        self._native_functions = {key: vars(catalog_module.NativeMusicCatalog)[key]
                                  for key in ('get', 'match', '_refresh')}
        self._native_function_codes = tuple((value, value.__code__) for value in self._native_functions.values())
        self._native_helpers = tuple((key, vars(catalog_module)[key], vars(catalog_module)[key].__code__)
            for key in ('display_text', 'normalize_text', 'title_artist_key', '_unknown', 'match_music'))
        self.index = _CatalogProjection(self)
        self._config_snapshot = self._configuration()
        self._devices = frozenset(source_grant.devices) if source_grant is not None else self._explicit_devices()
        self._parser = self._project
        self._slots = [
            (main, 'build_music_event', main.build_music_event, self._parser),
            (music, 'build_music_event', music.build_music_event, self._parser),
            (music, 'display_text', music.display_text, catalog_module.display_text),
            (music, 'normalize_text', music.normalize_text, catalog_module.normalize_text),
            (music, 'match_music', music.match_music, catalog_module.match_music),
            (phone, '_music_index', self.original_index, self.index),
            (self.provider, 'index', self.original_index, self.index),
        ]
        self._require_authority()

    @property
    def scope(self):
        return deepcopy(self._scope)

    def _configuration(self):
        return _json({key: self.config.get(key) for key in _CONFIG_KEYS})

    def _explicit_devices(self):
        # No old helper calls, global/default-device fallback or role aliases.
        raw = self.config.get('allowed_user_ids')
        if isinstance(raw, str):
            users = {item.strip() for item in raw.replace('，', ',').split(',') if item.strip()}
        elif type(raw) is list and all(type(item) is str for item in raw):
            users = {item.strip() for item in raw if item.strip()}
        else:
            raise MusicBindingConflict('explicit_single_user_binding_required')
        mapping = self.config.get('music_user_devices')
        if isinstance(mapping, str):
            if len(mapping.encode()) > 8192:
                raise MusicBindingConflict('explicit_device_binding_required')
            try:
                mapping = json.loads(mapping)
            except (ValueError, TypeError):
                raise MusicBindingConflict('explicit_device_binding_required') from None
        devices = mapping.get(self.scope['user_id']) if type(mapping) is dict else None
        if (users != {self.scope['user_id']} or type(mapping) is not dict or set(mapping) != users
                or type(devices) is not list or not 1 <= len(devices) <= 8
                or any(type(device) is not str or not device or len(device) > 64
                       or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in device)
                       for device in devices)):
            raise MusicBindingConflict('explicit_device_binding_required')
        return frozenset(devices)

    def _require_authority(self):
        if self._source_grant is not None:
            from .native_phone_music_source_grant import source_read_grant_current
            if not source_read_grant_current(self._source_grant, self.phone):
                raise MusicBindingConflict('source_read_grant_unavailable')
            return
        try:
            allowed = (_scope(self._current_scope()) == self._scope and self._authorize(dict(self._scope)) is True
                and self.config.get('enable_phone_perception') is True
                and self.config.get('enable_music_context') is True
                and self.phone._music_stopping is False)
        except Exception:
            allowed = False
        if not allowed:
            raise MusicBindingConflict('scope_or_music_authority_unavailable')

    def _same_loop(self):
        return threading.get_ident() == self._thread and asyncio.get_running_loop() is self._loop

    def _objects_current(self):
        return (self.phone._music_provider is self.provider and self.phone._context_aggregator is self.aggregator
            and self.phone.config is self.config and self.phone.context is self.context
            and self.aggregator._providers.get('music') is self.provider
            and self.original_index.path == self._catalog_path
            and type(self.catalog) is catalog_module.NativeMusicCatalog and self.catalog.path == self._catalog_path
            and not any(key in vars(self.catalog) for key in self._native_functions)
            and not any(any(key in vars(obj) for key in methods) for obj, methods in self._instance_methods)
            and all(function.__code__ is code for function, code in self._function_codes)
            and all(function.__code__ is code for function, code in self._native_function_codes)
            and all(vars(catalog_module.NativeMusicCatalog)[key] is value for key, value in self._native_functions.items())
            and not any(path.is_symlink() for path in self._unlinked_paths)
            and all(sys.modules.get(module.__name__) is module and _signature(path) == self._source_signatures[name]
                    for name, (module, path, _) in self._modules.items()))

    def _bindings_current(self, native):
        replacements = {(id(owner), key): new for owner, key, _, new in self._slots} if native else {}
        return (self._objects_current()
            and all(vars(owner).get(key) is replacements.get((id(owner), key), original)
                    for owner, key, original in self._function_bindings)
            and all(vars(owner).get(key) is (new if native else old) for owner, key, old, new in self._slots))

    def _source_current(self):
        return all(sys.modules.get(module.__name__) is module and _regular(path) == raw
                   for module, path, raw in self._modules.values())

    def _no_legacy_frames(self):
        filenames = {str(path) for _, path, _ in self._modules.values()}
        frames = sys._current_frames()
        if len(frames) > 256:
            return False
        for frame in frames.values():
            depth = 0
            while frame is not None:
                if depth >= 256 or frame.f_code.co_filename in filenames:
                    return False
                frame = frame.f_back
                depth += 1
        return True

    def _native_helpers_current(self):
        return all(vars(catalog_module).get(key) is function and function.__code__ is code
                   for key, function, code in self._native_helpers)

    def current(self):
        try:
            if not self._active or not self._same_loop():
                return False
            if not self._bindings_current(True) or not self._native_helpers_current():
                raise MusicBindingConflict('binding_changed')
            self._require_authority()
            if self._configuration() != self._config_snapshot:
                raise MusicBindingConflict('configuration_changed')
            return True
        except Exception:
            # An observed native/source drift cannot silently revive this grant
            # when an object is put back. Explicit restore remains separate.
            if self._stage == 'native' and self._source_grant is not None:
                self._source_grant.revoke()
            return False

    def _project(self, view, index=None, *, now=None, ttl_seconds=180):
        if not self.current():
            return unknown_music(reason='native_binding_unavailable')
        if isinstance(view, dict) and view.get('ok') is True and view.get('device_id') not in self._devices:
            return unknown_music(reason='explicit_device_binding_required')
        if index is not None and index is not self.index:
            return unknown_music(reason='native_index_binding_mismatch')
        value = build_music_event(view, self.catalog if index is self.index else None, now=now, ttl_seconds=ttl_seconds)
        return value if self.current() else unknown_music(reason='native_binding_unavailable')

    def apply(self, *, expected_generation=0):
        if (type(expected_generation) is not int or expected_generation != self.generation
                or self._stage != 'prepared' or not self._same_loop() or not self._bindings_current(False)
                or not self._source_current() or not self._no_legacy_frames() or not self._native_helpers_current()):
            raise MusicBindingConflict('binding_compare_and_swap_failed')
        self._require_authority()
        if self._configuration() != self._config_snapshot:
            raise MusicBindingConflict('configuration_changed')
        if self._source_grant is not None:
            from .native_phone_music_source_grant import _attach_source_binding
            _attach_source_binding(self._source_grant, self)
        # Plain module/object dictionaries only; no await or legacy callback.
        for owner, key, _, new in self._slots:
            vars(owner)[key] = new
        self.generation += 1
        self._stage, self._active = 'native', True
        return self.diagnostics()

    def stop(self):
        """Revoke the projection. Returning to legacy is an explicit restore."""
        self._active = False

    def restore(self, *, expected_generation):
        if (type(expected_generation) is not int or expected_generation != self.generation
                or self._stage != 'native' or not self._same_loop() or not self._bindings_current(True)
                or not self._source_current() or not self._no_legacy_frames()):
            raise MusicBindingConflict('restore_compare_and_swap_failed')
        self._active = False
        for owner, key, old, _ in reversed(self._slots):
            vars(owner)[key] = old
        self.generation += 1
        self._stage = 'restored'
        if self._source_grant is not None:
            from .native_phone_music_source_grant import _detach_source_binding
            _detach_source_binding(self._source_grant, self)
        return self.diagnostics()

    def diagnostics(self):
        return dict(state=self._stage, generation=self.generation, projection_current=self.current(),
            authority_mode='source_read_grant' if self._source_grant is not None else 'private_scope',
            persistent_owner=False, restart_rebind_required=True, phone_reloaded=False,
            phone_provider_replaced=False, source_registration_changed=False, send_permission=False,
            whole_plugin_replaced=False, bound_devices=len(self._devices), binding_slots=len(self._slots))
