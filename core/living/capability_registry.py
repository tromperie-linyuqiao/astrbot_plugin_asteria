"""Bounded, owner-registered internal capabilities; no jobs or senders.

Registration/configuration is trusted host setup, never an LLM tool. Handlers
are ordinary functions; async handlers should wrap blocking I/O themselves.
JSON schemas use the documented small subset, not the full JSON Schema spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import math
import re
import threading

from .models import plain, private_scope


_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_KINDS = {"object", "array", "string", "integer", "number", "boolean", "null"}
_COMMON = {"type", "enum", "description"}
_KEYS = {
    "object": {"properties", "required", "additionalProperties", "maxProperties"},
    "array": {"items", "minItems", "maxItems"},
    "string": {"minLength", "maxLength"},
    "integer": {"minimum", "maximum"}, "number": {"minimum", "maximum"},
    "boolean": set(), "null": set(),
}


def _identifier(value):
    if not isinstance(value, str) or len(value) > 128 or not _ID.fullmatch(value):
        raise ValueError("invalid capability identifier")
    return value


def _version(value):
    if not isinstance(value, str) or len(value) > 32 or not _VERSION.fullmatch(value):
        raise ValueError("version must be numeric major.minor.patch")
    return tuple(int(part) for part in value.split("."))


def _integer(value, lower, upper):
    return isinstance(value, int) and not isinstance(value, bool) and lower <= value <= upper


def _schema(schema, depth=0):
    """Reject unsupported keywords at registration, rather than ignore them."""
    if depth > 6 or not isinstance(schema, dict):
        raise ValueError("invalid bounded schema")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _KINDS or set(schema) - _COMMON - _KEYS[kind]:
        raise ValueError("unsupported schema type or keyword")
    if "description" in schema and (not isinstance(schema["description"], str) or len(schema["description"]) > 512):
        raise ValueError("invalid schema description")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not 1 <= len(schema["enum"]) <= 32):
        raise ValueError("invalid schema enum")
    if kind == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        maximum = schema.get("maxProperties", 64)
        if (not isinstance(props, dict) or len(props) > 64 or
                not all(isinstance(key, str) and 0 < len(key) <= 128 for key in props) or
                not isinstance(required, list) or not all(isinstance(key, str) for key in required) or
                len(required) != len(set(required)) or not set(required) <= set(props) or
                not _integer(maximum, 0, 64) or len(required) > maximum or
                not isinstance(schema.get("additionalProperties", False), bool)):
            raise ValueError("invalid bounded object schema")
        for child in props.values():
            _schema(child, depth + 1)
    elif kind == "array":
        lo, hi = schema.get("minItems", 0), schema.get("maxItems", 64)
        if not _integer(lo, 0, 256) or not _integer(hi, lo, 256):
            raise ValueError("invalid bounded array schema")
        _schema(schema.get("items"), depth + 1)
    elif kind == "string":
        lo, hi = schema.get("minLength", 0), schema.get("maxLength", 4096)
        if not _integer(lo, 0, 16384) or not _integer(hi, lo, 16384):
            raise ValueError("invalid bounded string schema")
    elif kind in {"integer", "number"}:
        lo, hi = schema.get("minimum", -1e15), schema.get("maximum", 1e15)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not -1e15 <= v <= 1e15 or not math.isfinite(v) for v in (lo, hi)) or lo > hi:
            raise ValueError("invalid numeric schema bounds")


def validate_value(schema, value):
    """Validate a plain JSON clone with a 64 KiB / 12-level outer bound."""
    value = plain(value, 65536)

    def visit(rule, item):
        kind = rule["type"]
        if "enum" in rule and not any(type(item) is type(v) and item == v for v in rule["enum"]):
            raise ValueError("value outside enum")
        if kind == "object":
            props = rule.get("properties", {})
            if (not isinstance(item, dict) or len(item) > rule.get("maxProperties", 64) or
                    not set(rule.get("required", [])) <= set(item) or
                    (not rule.get("additionalProperties", False) and set(item) - set(props))):
                raise ValueError("invalid object fields")
            for key, child in item.items():
                if key in props:
                    visit(props[key], child)
        elif kind == "array":
            if not isinstance(item, list) or not rule.get("minItems", 0) <= len(item) <= rule.get("maxItems", 64):
                raise ValueError("invalid array")
            for child in item:
                visit(rule["items"], child)
        elif kind == "string":
            if not isinstance(item, str) or not rule.get("minLength", 0) <= len(item) <= rule.get("maxLength", 4096):
                raise ValueError("invalid string")
        elif kind in {"integer", "number"}:
            if (isinstance(item, bool) or not isinstance(item, (int, float)) or
                    (kind == "integer" and not isinstance(item, int)) or
                    not rule.get("minimum", -1e15) <= item <= rule.get("maximum", 1e15)):
                raise ValueError("invalid numeric value")
        elif kind == "boolean" and not isinstance(item, bool):
            raise ValueError("boolean required")
        elif kind == "null" and item is not None:
            raise ValueError("null required")

    visit(schema, value)
    return value


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    description: str
    input_schema: dict
    output_schema: dict
    version: str = "1.0.0"
    dependencies: dict = field(default_factory=dict)
    permissions: tuple = ()
    config_schema: dict | None = None
    test_entry: str | None = None

    def checked(self):
        _identifier(self.capability_id)
        _version(self.version)
        if not isinstance(self.description, str) or not 1 <= len(self.description) <= 512:
            raise ValueError("capability needs a bounded description")
        schemas = [plain(self.input_schema, 16384), plain(self.output_schema, 16384)]
        for schema in schemas:
            _schema(schema)
        if (not isinstance(self.dependencies, dict) or len(self.dependencies) > 16 or
                not isinstance(self.permissions, (list, tuple)) or len(self.permissions) > 16 or
                not all(isinstance(item, str) for item in self.permissions) or
                len(set(self.permissions)) != len(self.permissions)):
            raise ValueError("invalid dependencies or permissions")
        dependencies = {}
        for name, version in self.dependencies.items():
            dependencies[_identifier(name)] = version
            _version(version)
            if name == self.capability_id:
                raise ValueError("self dependency forbidden")
        permissions = tuple(_identifier(item) for item in self.permissions)
        configuration = plain(self.config_schema, 16384) if self.config_schema is not None else {
            "type": "object", "properties": {}, "additionalProperties": False}
        _schema(configuration)
        if self.test_entry is not None:
            _identifier(self.test_entry)
        return CapabilitySpec(self.capability_id, self.description, schemas[0], schemas[1],
                              self.version, dependencies, permissions, configuration, self.test_entry)


@dataclass
class _Entry:
    spec: CapabilitySpec
    handler: object
    fallback: object
    config: dict
    enabled: bool
    generation: int
    inflight: int = 0
    successes: int = 0
    failures: int = 0
    last_error: str | None = None


class RegistryConflict(RuntimeError):
    """Generation changed or a capability/dependent is currently in use."""


class CapabilityRegistry:
    def __init__(self, *, authorize, capacity=64, max_inflight=32):
        if (not callable(authorize) or not _integer(capacity, 1, 128) or
                not _integer(max_inflight, 1, 128)):
            raise ValueError("invalid registry limits or authorization callback")
        self._authorize = authorize
        self._capacity, self._max_inflight = capacity, max_inflight
        self._entries, self._lock = {}, threading.RLock()
        self._closed, self._inflight = False, 0

    def _graph(self, entries, name, stack=(), visited=None):
        visited = set() if visited is None else visited
        if name in stack:
            raise ValueError("cyclic capability dependency")
        if name not in entries or name in visited:
            return
        for dependency in entries[name].spec.dependencies:
            self._graph(entries, dependency, stack + (name,), visited)
        visited.add(name)

    def register(self, spec, handler, *, config=None, enabled=True, fallback=None):
        """Trusted setup only; existing IDs require explicit replace with CAS."""
        return self._install(spec, handler, config, enabled, fallback, None)

    def replace(self, spec, handler, *, expected_generation, config=None, enabled=True, fallback=None):
        return self._install(spec, handler, config, enabled, fallback, expected_generation)

    def _install(self, spec, handler, config, enabled, fallback, expected_generation):
        if not isinstance(spec, CapabilitySpec) or not callable(handler) or (fallback is not None and not callable(fallback)) or not isinstance(enabled, bool):
            raise ValueError("invalid capability registration")
        spec = spec.checked()
        config = validate_value(spec.config_schema, {} if config is None else config)
        with self._lock:
            if self._closed:
                raise RegistryConflict("registry is closed")
            old = self._entries.get(spec.capability_id)
            if expected_generation is None:
                if old is not None:
                    raise RegistryConflict("capability already registered")
                if len(self._entries) >= self._capacity:
                    raise RegistryConflict("registry capacity")
            else:
                self._editable(old, expected_generation)
            generation = old.generation + 1 if old else 1
            entry = _Entry(spec, handler, fallback, config, enabled, generation)
            projected = dict(self._entries, **{spec.capability_id: entry})
            for name in projected:
                self._graph(projected, name)
            self._entries[spec.capability_id] = entry
            return generation

    @staticmethod
    def _editable(entry, expected_generation):
        if (entry is None or not _integer(expected_generation, 1, 2**63 - 1) or
                entry.generation != expected_generation or entry.inflight):
            raise RegistryConflict("stale generation or capability in use")

    def set_enabled(self, capability_id, enabled, *, expected_generation):
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        with self._lock:
            if self._closed:
                raise RegistryConflict("registry is closed")
            entry = self._entries.get(capability_id)
            self._editable(entry, expected_generation)
            entry.enabled = enabled
            entry.generation += 1
            return entry.generation

    def configure(self, capability_id, config, *, expected_generation):
        with self._lock:
            if self._closed:
                raise RegistryConflict("registry is closed")
            entry = self._entries.get(capability_id)
            self._editable(entry, expected_generation)
            entry.config = validate_value(entry.spec.config_schema, config)
            entry.generation += 1
            return entry.generation

    def _dependencies(self, name, result=None):
        result = {} if result is None else result
        entry = self._entries.get(name)
        if entry is None or not entry.enabled:
            return None
        result[name] = entry
        for dependency, minimum in entry.spec.dependencies.items():
            candidate = self._entries.get(dependency)
            if candidate is None:
                return None
            actual, required = _version(candidate.spec.version), _version(minimum)
            if actual[0] != required[0] or actual < required:
                return None
            if dependency not in result and self._dependencies(dependency, result) is None:
                return None
        return result

    @staticmethod
    async def _await(value):
        return await value if inspect.isawaitable(value) else value

    async def _allowed(self, scope, permissions):
        try:
            for permission in sorted(permissions):
                if await self._await(self._authorize(plain(scope), permission)) is not True:
                    return "denied"
        except Exception:
            return "authorization_unavailable"
        return None

    async def call(self, capability_id, payload, *, scope):
        """Return a small typed envelope; exceptions/messages and inputs are not logged."""
        try:
            scope = private_scope(scope)
        except (TypeError, ValueError):
            return {"ok": False, "state": "invalid_scope"}
        with self._lock:
            if self._closed:
                return {"ok": False, "state": "closed"}
            entry = self._entries.get(capability_id)
            if entry is None:
                return {"ok": False, "state": "not_registered"}
            base = {"capability_id": capability_id, "generation": entry.generation}
            if not entry.enabled:
                return dict(base, ok=False, state="disabled")
            pinned = self._dependencies(capability_id)
            if pinned is None:
                return dict(base, ok=False, state="dependency_unavailable")
            if self._inflight >= self._max_inflight:
                return dict(base, ok=False, state="busy")
            try:
                payload = validate_value(entry.spec.input_schema, payload)
            except (TypeError, ValueError, OverflowError):
                return dict(base, ok=False, state="invalid_input")
            permissions = {permission for item in pinned.values() for permission in item.spec.permissions}
            for item in pinned.values():
                item.inflight += 1
            self._inflight += 1
            config = plain(entry.config, 65536)
        try:
            denied = await self._allowed(scope, permissions)
            if denied:
                return dict(base, ok=False, state=denied)
            failure, fallback = None, False
            try:
                output = await self._await(entry.handler(plain(payload, 65536), scope=plain(scope),
                                                       config=plain(config, 65536)))
            except Exception:
                failure = "handler_failed"
            if failure is None:
                try:
                    output = validate_value(entry.spec.output_schema, output)
                except (TypeError, ValueError, OverflowError):
                    failure = "invalid_output"
            if failure is not None and entry.fallback is not None:
                denied = await self._allowed(scope, permissions)
                if denied:
                    return dict(base, ok=False, state=denied)
                try:
                    output = await self._await(entry.fallback(plain(payload, 65536), scope=plain(scope),
                                                              config=plain(config, 65536), cause=failure))
                    output = validate_value(entry.spec.output_schema, output)
                    fallback = True
                except Exception:
                    failure = "fallback_failed"
            denied = await self._allowed(scope, permissions)
            if denied:
                return dict(base, ok=False, state=denied)
            with self._lock:
                if self._closed:
                    return dict(base, ok=False, state="closed")
                if failure:
                    entry.failures += 1
                    entry.last_error = failure
                if failure and not fallback:
                    return dict(base, ok=False, state=failure)
                entry.successes += 1
                if not failure:
                    entry.last_error = None
                return dict(base, ok=True, state="degraded" if fallback else "ok", data=output, fallback=fallback)
        finally:
            with self._lock:
                for item in pinned.values():
                    item.inflight -= 1
                self._inflight -= 1

    def describe(self):
        """Technical metadata only: never expose config values, inputs or scopes."""
        with self._lock:
            result = []
            for name, entry in sorted(self._entries.items()):
                dependency_ok = self._dependencies(name) is not None
                state = ("closed" if self._closed else "disabled" if not entry.enabled else
                         "dependency_unavailable" if not dependency_ok else
                         "degraded" if entry.last_error else "healthy" if entry.successes else "ready")
                result.append({"capability_id": name, "description": entry.spec.description,
                    "version": entry.spec.version, "generation": entry.generation,
                    "enabled": entry.enabled, "health": state, "inflight": entry.inflight,
                    "successes": entry.successes, "failures": entry.failures,
                    "last_error": entry.last_error, "dependencies": dict(entry.spec.dependencies),
                    "permissions": list(entry.spec.permissions), "test_entry": entry.spec.test_entry,
                    "input_schema": plain(entry.spec.input_schema, 16384),
                    "output_schema": plain(entry.spec.output_schema, 16384),
                    "config_schema": plain(entry.spec.config_schema, 16384)})
            return result

    def status_snapshot(self):
        """Read-only bounded status for ownership UI; never handlers or config.

        Registration and successful component calls do not prove platform
        delivery, device visibility, or production execution ownership.
        """
        with self._lock:
            rows = self.describe()
            return {'closed': self._closed, 'entries': [{key: row[key] for key in (
                'capability_id', 'version', 'generation', 'enabled', 'health',
                'inflight', 'successes', 'failures', 'dependencies', 'test_entry')}
                for row in rows]}

    def health(self):
        with self._lock:
            entries = self.describe()
            return {"closed": self._closed, "capabilities": len(entries), "inflight": self._inflight,
                    "unavailable": sum(item["health"] in {"closed", "disabled", "dependency_unavailable"} for item in entries),
                    "degraded": sum(item["health"] == "degraded" for item in entries)}

    def close(self):
        """Block new calls and discard results of in-flight handlers; own no tasks."""
        with self._lock:
            self._closed = True
