"""Optional, read-only Host seam for real SDK selected-Persona observation.

This controller registers no hook, creates no scope/lease, and performs no
memory operation. Its accessor returns observation evidence, never an MC or
write/send grant. The capture owns the only bounded, weak request state.
"""
from __future__ import annotations

import inspect
import time

from .models import private_scope
from .native_memory import NativeMemoryStore
from .native_memory_adapter import NativeMemoryAdapter
from .native_selected_persona_capture import NativeSelectedPersonaCapture


def _method(value):
    if not callable(value):
        raise ValueError('existing synchronous Host method required')
    return (getattr(value, '__self__', None), getattr(value, '__func__', value))


def _same_method(value, binding):
    current = _method(value)
    return all(left is right for left, right in zip(current, binding))


def _true(value):
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        return False
    return value is True


class NativeSelectedPersonaHost:
    """Synchronous Waiting/Request boundaries over an already-running Host."""

    def __init__(self, host, *, clock=time.monotonic, max_entries=64, ttl_seconds=120.):
        from .host import LivingHost
        if type(host) is not LivingHost:
            raise ValueError('existing exact LivingHost required')
        self.host, self.context = host, host.context
        self._host = host
        self._plugin, self._presence, self._runtime = host.plugin, host.presence, host.runtime
        self._integration = self._plugin._presence
        self._memory = getattr(self._runtime, 'memory', None)
        self._store = getattr(self._memory, 'store', None)
        if type(self._memory) is not NativeMemoryAdapter or type(self._store) is not NativeMemoryStore:
            raise ValueError('existing native memory backend required')
        self._memory_generation = self._memory.generation
        self._database = self._store._db
        self._methods = tuple((owner, name, _method(getattr(owner, name))) for owner, name in (
            (host, '_native_memory_allowed'), (host, 'authorized_scope'),
            (self._presence, 'scope_for_event'), (self._presence, 'peek_scope_for_session'),
            (self._presence, 'authorization_active'), (self._plugin, '_cfg'),
            (self._plugin, '_cfg_bool'), (self._plugin, '_resolve_session'),
            (self._memory, 'allowed')))
        self._memory_authorizer = _method(self._memory._authorize)
        self._runtime_authorizer = _method(self._runtime.scope_validator)
        if (not _same_method(self._memory._authorize, _method(host._native_memory_allowed))
                or not _same_method(self._runtime.scope_validator, _method(host.authorized_scope))):
            raise ValueError('native memory must retain existing Host authorizers')
        self._config = self._configuration()
        self.active = True
        self._counts = dict(begun=0, captured=0, denied=0, errors=0, invalidations=0)
        self.capture = NativeSelectedPersonaCapture(self.context, authorize=self._authorize,
            clock=clock, max_entries=max_entries, ttl_seconds=ttl_seconds)
        self._capture = self.capture
        # PresenceIntegration publishes living_host only after await
        # host.start() returns. Construct now, but no boundary is usable until
        # that genuine owner backlink has actually been published.
        if not self._stable(require_published_owner=False):
            self.capture.stop()
            self.active = False
            raise ValueError('Host native memory lifecycle unavailable')

    def _count(self, name):
        self._counts[name] = min(1000000, self._counts[name] + 1)

    def _configuration(self):
        backend = self._plugin._cfg('living_memory_backend', 'legacy')
        sessions = self._plugin._cfg('living_memory_sessions', [])
        catalog = self._plugin._cfg('living_catalog_path', '')
        enabled = self._plugin._cfg_bool('living_system_enabled', False)
        if (type(backend) is not str or backend != 'native' or type(sessions) is not list or len(sessions) > 512
                or any(type(value) is not str or len(value) > 4096 for value in sessions)
                or type(catalog) is not str or len(catalog) > 4096 or enabled is not True):
            raise ValueError('bounded existing native memory configuration required')
        return backend, tuple(sessions), catalog, enabled

    def _stable(self, *, require_published_owner=True):
        try:
            published = self._integration.living_host
            return (self.active and self.capture is self._capture and self._capture.active is True
                and self.host is self._host and self.context is self._capture.context
                and self.host.context is self.context and self.host.plugin is self._plugin
                and self._plugin.context is self.context and self._plugin._presence is self._integration
                and self._integration.api is self._presence and self._integration.context is self.context
                and self._integration.plugin is self._plugin
                and (published is self.host or not require_published_owner and published is None)
                and self.context.living_system is self._runtime
                and self.host.presence is self._presence and self.host.runtime is self._runtime
                and self.host._closed is False and not getattr(self._plugin, '_stopping', False)
                and self._runtime.active is True and self._runtime.presence is self._presence
                and self._runtime.memory is self._memory and self._memory.active is True
                and type(self._memory.backend) is str and self._memory.backend == 'native'
                and self._memory.store is self._store
                and type(self._memory.generation) is type(self._memory_generation)
                and self._memory.generation == self._memory_generation
                and self._store._closed is False and self._store._db is self._database
                and all(_same_method(getattr(owner, name), binding) for owner, name, binding in self._methods)
                and _same_method(self._memory._authorize, self._memory_authorizer)
                and _same_method(self._runtime.scope_validator, self._runtime_authorizer)
                and self._configuration() == self._config)
        except Exception:
            return False

    def _scope(self, event):
        if not self._stable():
            return None
        # This method only derives identity. Existing Host authorization below
        # must independently prove the already-remembered genuine inbound lease.
        value = self._presence.scope_for_event(event)
        scope = private_scope(value)
        if (type(value) is not dict or value != scope
                or not _true(self.host._native_memory_allowed(dict(scope)))
                or not _true(self.host.authorized_scope(dict(scope)))
                or not _true(self._memory.allowed(dict(scope))) or not self._stable()):
            return None
        return scope

    def _authorize(self, event, scope):
        return self._scope(event) == scope

    def invalidate(self, event):
        """Revoke this event only; this never remembers or grants a scope."""
        self._count('invalidations')
        self._capture.invalidate(event)

    def _failed(self, event, *, error=False):
        self.invalidate(event)
        self._count('errors' if error else 'denied')

    def begin(self, event):
        self.invalidate(event)
        try:
            scope = self._scope(event)
            if scope is None or self._capture.begin_event(event, scope) is None:
                self._failed(event)
                return False
            self._count('begun')
            return True
        except Exception:
            self._failed(event, error=True)
            return False
        except BaseException:
            self.invalidate(event)
            raise

    def finish(self, req, event):
        try:
            scope = self._scope(event)
            if scope is None or not self._capture.finish_event(req, event, scope):
                self._failed(event)
                return False
            proof = self._capture.take(req, event, scope)
            if proof is None or not self._capture.current(proof, req, event, scope):
                self._failed(event)
                return False
            # Proof stays in the capture's existing weak request/event epoch.
            # No second cache, timeout, selected ID inventory or history is made.
            self._count('captured')
            return True
        except Exception:
            self._failed(event, error=True)
            return False
        except BaseException:
            self.invalidate(event)
            raise

    def current(self, req, event):
        """Return current observation evidence, not a consumer permission."""
        try:
            scope = self._scope(event)
            state = self._capture._states.get(self._capture._requests.get(id(req)))
            proof = state.get('proof') if state is not None else None
            if (scope is None or proof is None or state.get('mode') != 'event_epoch'
                    or proof.capture_mode != 'event_epoch'
                    or not self._capture.current(proof, req, event, scope)):
                self._failed(event)
                return None
            return proof
        except Exception:
            self._failed(event, error=True)
            return None
        except BaseException:
            self.invalidate(event)
            raise

    def stop(self):
        self.active = False
        self._capture.stop()

    def diagnostics(self):
        raw = self._capture.diagnostics()
        return dict(active=self._stable(), counts=dict(self._counts),
            event_attachments=raw['event_attachments'], request_epochs=raw['request_epochs'],
            pending_event_epochs=raw['pending_event_epochs'], max_entries=raw['max_entries'],
            alias_restore_failures=raw['alias_restore_failures'],
            original_alias_restoration_complete=raw['original_alias_restoration_complete'],
            grants_mc_authority=False, grants_write_or_send=False, creates_scopes=False,
            reads_memory=False, model_calls=0, sends=0)
