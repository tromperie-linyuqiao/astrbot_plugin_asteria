"""Typed permission for existing Phone music sources, never a private scope.

The only factory observes one actual SDK-registered Phone instance and its
already configured user/device/bridge/catalog sources. It calls no Phone
business method and creates no client, lease, task, memory or send authority.
The returned RAM capability cannot be reconstructed from its public JSON.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import sys
import threading
from types import FunctionType, ModuleType
from urllib.parse import urlsplit
import weakref

from .native_legacy_companion_inspection import _attrs, _registry
from .native_phone_music_binding import (_capture_phone_parts, _code_equal, _codes,
    _CONFIG_KEYS, _json, _regular, _signature, NativePhoneMusicBinding)

ROOT = 'astrbot_plugin_phone_perception'
CLIENT_SHA256 = '2282a9468ab7418e6f536f9f4cf70726c41d69916f6a03f37fab50ddae2e561c'
_DEVICE = re.compile(r'[A-Za-z0-9_.-]{1,64}\Z')
_CLIENT_METHODS = ('configure', 'invalidate', '_fetch_once', 'get_state')
_SEAL = object()


class SourceReadGrantError(ValueError):
    pass


def _config_copy(config):
    if (not isinstance(config, dict)
            or inspect.getattr_static(config, 'get', None) is not inspect.getattr_static(dict, 'get')):
        raise SourceReadGrantError('plain_configuration_required')
    nodes = 0
    def copy(value, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 2048 or depth > 8:
            raise SourceReadGrantError('configuration_capacity')
        kind = type(value)
        if value is None or kind in (bool, int): return value
        if kind is float and math.isfinite(value): return value
        if kind is str and len(value) <= 65536: return value
        if kind is list: return [copy(item, depth + 1) for item in value]
        if kind is dict and all(type(key) is str for key in value):
            return {key: copy(item, depth + 1) for key, item in value.items()}
        raise SourceReadGrantError('plain_configuration_required')
    result = {key: copy(dict.get(config, key), 0) for key in _CONFIG_KEYS}
    _json(result)
    return result


def _strict_mapping(raw):
    if type(raw) is not str: return raw
    if len(raw.encode()) > 8192: raise SourceReadGrantError('device_mapping_capacity')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise SourceReadGrantError('ambiguous_device_mapping')
            out[key] = value
        return out
    def nonfinite(_): raise SourceReadGrantError('invalid_device_mapping')
    try: return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError): raise SourceReadGrantError('invalid_device_mapping') from None


def _selection(config, expected_user):
    """Literal old routing for accepted plain values, with no invented device.

    Falsey mapping is tested before parsing, as in the old collector. Devices
    are length/type/regex checked before ordered de-duplication, also as old.
    Non-string user/device coercions and implicit default 'phone' are denied.
    """
    if (type(expected_user) is not str or not 1 <= len(expected_user) <= 256
            or expected_user != expected_user.strip() or any(ord(c) < 32 for c in expected_user)):
        raise SourceReadGrantError('exact_user_required')
    raw_users = config.get('allowed_user_ids')
    if type(raw_users) is str:
        users = {item.strip() for item in raw_users.replace('，', ',').split(',') if item.strip()}
    elif type(raw_users) is list and all(type(item) is str for item in raw_users):
        users = {item.strip() for item in raw_users if item.strip()}
    else: raise SourceReadGrantError('single_allowed_user_required')
    if users != {expected_user}: raise SourceReadGrantError('single_allowed_user_required')
    if config.get('enable_phone_perception') is not True or config.get('enable_music_context') is not True:
        raise SourceReadGrantError('music_source_disabled')
    raw_mapping = config.get('music_user_devices')
    if raw_mapping:
        mapping = _strict_mapping(raw_mapping)
        if type(mapping) is not dict: raise SourceReadGrantError('invalid_device_mapping')
        devices = mapping.get(expected_user, [])
        mode = 'explicit_user_devices'
    else:
        raw = config.get('device_ids') or []
        if type(raw) is str:
            raw = [item for item in raw.replace('，', ',').split(',') if item.strip()]
        if type(raw) is not list or any(type(item) is not str for item in raw):
            raise SourceReadGrantError('explicit_device_source_required')
        devices = [item.strip() for item in raw if item.strip()]
        if not devices:
            single = config.get('device_id')
            if type(single) is not str or not single.strip():
                raise SourceReadGrantError('explicit_device_source_required')
            devices = [single.strip()]
        mode = 'single_allowed_user_fallback'
    if (type(devices) is not list or not 1 <= len(devices) <= 8
            or any(type(item) is not str or not _DEVICE.fullmatch(item) for item in devices)):
        raise SourceReadGrantError('invalid_device_source')
    return tuple(dict.fromkeys(devices)), mode


def _unique_owner(parts, metadata=None):
    rows = [row for row in _registry(parts.context) if _attrs(row).get('root_dir_name') == ROOT]
    if len(rows) != 1: raise SourceReadGrantError('unique_live_phone_required')
    row = rows[0]; attrs = _attrs(row); main = parts._modules['main.py'][0]
    module = attrs.get('module')
    if module is None: module = sys.modules.get(attrs.get('module_path'))
    if (metadata is not None and row is not metadata or attrs.get('activated') is not True
            or attrs.get('star_cls') is not parts.phone or module is not main):
        raise SourceReadGrantError('unique_live_phone_required')
    return row


def _bridge(config):
    base, token = config.get('bridge_base_url'), config.get('bridge_token')
    if (type(base) is not str or not 1 <= len(base) <= 500 or any(ord(c) <= 32 or ord(c) == 127 for c in base)
            or type(token) is not str or not token.strip() or len(token) > 512
            or any(not 32 <= ord(c) < 127 for c in token)):
        raise SourceReadGrantError('configured_bridge_required')
    try:
        parsed = urlsplit(base)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.port == 0):
            raise ValueError
    except ValueError: raise SourceReadGrantError('configured_bridge_required') from None
    # Exact existing configure() normalization, not a new endpoint or token.
    default_device = str(config.get('device_id') or 'phone')
    return base.rstrip('/'), token.strip(), default_device


def _client_snapshot(parts, config):
    main, root = parts._modules['main.py'][0], parts._modules['main.py'][1].parent
    client = _attrs(parts.phone).get('client')
    cls = type(client); module = sys.modules.get(cls.__module__)
    path = root / 'perception_client.py'
    if (type(module) is not ModuleType or vars(module).get('__file__') != str(path)
            or vars(module).get('PerceptionClient') is not cls or vars(main).get('PerceptionClient') is not cls):
        raise SourceReadGrantError('actual_bridge_client_required')
    raw = _regular(path)
    if hashlib.sha256(raw).hexdigest() != CLIENT_SHA256: raise SourceReadGrantError('bridge_client_source_mismatch')
    codes = _codes(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0))
    bindings = []
    for key in (*_CLIENT_METHODS, 'configured'):
        descriptor = vars(cls).get(key)
        function = descriptor.fget if type(descriptor) is property else descriptor
        if (type(function) is not FunctionType or function.__globals__ is not vars(module)
                or function.__module__ != module.__name__ or function.__code__.co_filename != str(path)
                or not _code_equal(function.__code__, codes.get('PerceptionClient.' + key))
                or key in _attrs(client)):
            raise SourceReadGrantError('bridge_client_loaded_code_mismatch')
        bindings.append((key, descriptor, function.__code__))
    identity = _bridge(config)
    attrs = _attrs(client)
    if tuple(attrs.get(key) for key in ('base_url', 'token', 'device_id')) != identity:
        raise SourceReadGrantError('bridge_client_configuration_mismatch')
    return client, module, path, _signature(path), tuple(bindings), identity


def _original_parts_current(parts):
    phone, main = parts.phone, parts._modules['main.py'][0]
    if (phone._music_provider is not parts.provider or phone._context_aggregator is not parts.aggregator
            or phone.config is not parts.config or phone.context is not parts.context
            or parts.aggregator._providers.get('music') is not parts.provider
            or parts.original_index.path != parts._catalog_path
            or type(phone) is not vars(main).get('PhonePerceptionPlugin')): return False
    if any(path.is_symlink() for path in parts._unlinked_paths): return False
    if any(sys.modules.get(module.__name__) is not module or _signature(path) != parts._source_signatures[name]
           for name, (module, path, _) in parts._modules.items()): return False
    return (all(vars(owner).get(key) is value for owner, key, value in parts._function_bindings)
        and all(function.__code__ is code for function, code in parts._function_codes)
        and all(not any(key in vars(obj) for key in names) for obj, names in parts._instance_methods)
        and all(vars(owner).get(key) is value for owner, key, value in parts._entry_bindings))


@dataclass(frozen=True, repr=False)
class SourceReadGrant:
    _parts: object
    _metadata: object
    _user: str
    _devices: tuple
    _mode: str
    _config: str
    _client: object
    _client_module: ModuleType
    _client_path: Path
    _client_signature: tuple
    _client_bindings: tuple
    _client_identity: tuple
    _loop: object
    _thread: int
    _seal: object = field(repr=False)
    _owner_ref: object = field(default=None, repr=False)
    _revoked: bool = field(default=False, repr=False)

    @property
    def devices(self): return self._devices

    @property
    def proof(self):
        return dict(schema='tls.phone.music.source_read_grant.v1', state='current' if self.current() else 'unavailable',
            mode=self._mode, device_count=len(self._devices), read_only=True, normalization_only=True,
            genuine_private_scope_created=False, memory_permission=False, presence_lease_granted=False,
            inbound_seeded=False, send_permission=False, persistent_owner=False,
            public_json_is_authority=False, client_source_verified=True)

    def current(self): return source_read_grant_current(self, self._parts.phone)

    def revoke(self):
        if self._seal is _SEAL: object.__setattr__(self, '_revoked', True)


def capture_phone_music_source_grant(phone, *, expected_user):
    """Observe existing source permission. No old getter/parser or I/O call."""
    try:
        cls = type(phone)
        if type(cls) is not type: raise SourceReadGrantError('actual_phone_required')
        module = sys.modules.get(cls.__module__)
        if (type(module) is not ModuleType or vars(module).get('PhonePerceptionPlugin') is not cls
                or inspect.getattr_static(phone, '__getattribute__') is not object.__getattribute__
                or inspect.getattr_static(phone, '__getattr__', None) is not None):
            raise SourceReadGrantError('actual_phone_required')
        parts = _capture_phone_parts(phone)
        metadata = _unique_owner(parts)
        config = _config_copy(parts.config)
        devices, mode = _selection(config, expected_user)
        client = _client_snapshot(parts, config)
        if (any(_regular(path) != raw for _, path, raw in parts._modules.values())
                or hashlib.sha256(_regular(client[2])).hexdigest() != CLIENT_SHA256):
            raise SourceReadGrantError('source_changed_during_capture')
        grant = SourceReadGrant(parts, metadata, expected_user, devices, mode, _json(config), *client,
            asyncio.get_running_loop(), threading.get_ident(), _SEAL)
        if not source_read_grant_current(grant, phone): raise SourceReadGrantError('source_changed_during_capture')
        return grant
    except SourceReadGrantError: raise
    except Exception: raise SourceReadGrantError('source_identity_unavailable') from None


def source_read_grant_current(grant, phone):
    if type(grant) is not SourceReadGrant or grant._seal is not _SEAL or grant._revoked: return False
    try:
        if (threading.get_ident() != grant._thread or asyncio.get_running_loop() is not grant._loop
                or phone is not grant._parts.phone): return False
        parts = grant._parts
        _unique_owner(parts, grant._metadata)
        config = _config_copy(parts.config)
        devices, mode = _selection(config, grant._user)
        if (_json(config) != grant._config or devices != grant._devices or mode != grant._mode
                or parts.phone._music_stopping is not False): raise SourceReadGrantError('source_changed')
        owner = grant._owner_ref() if grant._owner_ref is not None else None
        if owner is None:
            if not _original_parts_current(parts): raise SourceReadGrantError('source_changed')
        elif (type(owner) is not NativePhoneMusicBinding or owner._source_grant is not grant
                or owner.phone is not phone or owner.original_index is not parts.original_index
                or not owner._bindings_current(owner._stage == 'native')):
            raise SourceReadGrantError('source_changed')
        client = grant._client; attrs = _attrs(client)
        if (phone.client is not client or sys.modules.get(grant._client_module.__name__) is not grant._client_module
                or vars(grant._client_module).get('PerceptionClient') is not type(client)
                or vars(parts._modules['main.py'][0]).get('PerceptionClient') is not type(client)
                or _signature(grant._client_path) != grant._client_signature
                or any(path.is_symlink() for path in (grant._client_path, *grant._client_path.parents))
                or any(vars(type(client)).get(key) is not value or key in attrs
                       or (value.fget if type(value) is property else value).__code__ is not code
                       for key, value, code in grant._client_bindings)
                or tuple(attrs.get(key) for key in ('base_url', 'token', 'device_id')) != grant._client_identity
                or _bridge(config) != grant._client_identity): raise SourceReadGrantError('source_changed')
        return True
    except Exception:
        # An observed source/config revocation is sticky for this capability.
        object.__setattr__(grant, '_revoked', True)
        return False


def _attach_source_binding(grant, owner):
    if (type(owner) is not NativePhoneMusicBinding or owner._source_grant is not grant
            or not source_read_grant_current(grant, owner.phone)):
        raise SourceReadGrantError('current_source_grant_required')
    existing = grant._owner_ref() if grant._owner_ref is not None else None
    if existing is not None and existing is not owner:
        raise SourceReadGrantError('source_binding_already_owned')
    object.__setattr__(grant, '_owner_ref', weakref.ref(owner))


def _detach_source_binding(grant, owner):
    if type(grant) is SourceReadGrant and grant._seal is _SEAL and grant._owner_ref is not None and grant._owner_ref() is owner:
        object.__setattr__(grant, '_owner_ref', None)
