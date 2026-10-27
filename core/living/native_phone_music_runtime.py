"""One Host-owned, source-only Phone parser binding on the existing loop.

There is no collector, private scope, worker or persistent authority here.
Only initial SDK load ordering is retried. Once applied, any loss of authority
permanently fences this controller; a fresh grant cannot hide revocation.
"""
from __future__ import annotations

import asyncio
import threading

from .native_legacy_companion_inspection import _attrs, _registry
from .native_phone_music_binding import NativePhoneMusicBinding
from .native_phone_music_source_grant import (ROOT, _config_copy,
    capture_phone_music_source_grant)


_RECOVERY_KEY = '_tls_phone_music_recovery'


def _retained_controller(value, context):
    # A real TLS reload changes class identity. As with frequency recovery,
    # recognize the retained class family/module and fixed stopped state,
    # never a JSON description or an arbitrary duck-typed restore callback.
    try:
        return (value is not None and any(base.__name__ == NativePhoneMusicRuntime.__name__
                and base.__module__ == NativePhoneMusicRuntime.__module__ for base in type(value).__mro__)
            and value.context is context and value._blocked is True and value._state == 'blocked'
            and value._ever_native is True and value._binding is not None and value._grant is not None
            and value._binding.context is context and value._binding._active is False
            and value._binding._source_grant is value._grant and value._grant._revoked is True
            and ((value._restore_required is True and value._binding._stage == 'native'
                  and value._binding.generation == 1)
                 or (value._restore_required is False and value._restored is True
                     and value._binding._stage == 'restored' and value._binding.generation == 2)))
    except Exception:
        return False


def restore_phone_music_recovery(context):
    """Restore the retained stopped owner before any fresh grant/runtime."""
    owner = getattr(context, _RECOVERY_KEY, None)
    if owner is None:
        return True
    if not _retained_controller(owner, context):
        return False
    owner._restore()
    return getattr(context, _RECOVERY_KEY, None) is None


def phone_music_recovery_diagnostics(context):
    owner = getattr(context, _RECOVERY_KEY, None)
    if owner is None:
        return None
    if _retained_controller(owner, context):
        return owner.diagnostics()
    return dict(state='blocked', reason='unknown_recovery_owner',
                restore_pending=True, projection_current=False)


def _single_user(phone):
    # Read the actual whitelist, then let the exact factory independently
    # validate its literal routing, devices, source code and loaded client.
    raw = _config_copy(_attrs(phone).get('config')).get('allowed_user_ids')
    if type(raw) is str:
        users = {item.strip() for item in raw.replace('，', ',').split(',') if item.strip()}
    elif type(raw) is list and all(type(item) is str for item in raw):
        users = {item.strip() for item in raw if item.strip()}
    else:
        raise ValueError('single_allowed_user_required')
    if len(users) != 1:
        raise ValueError('single_allowed_user_required')
    return next(iter(users))


class NativePhoneMusicRuntime:
    """Synchronous lifecycle around the binding's strict seven-slot CAS."""

    def __init__(self, host):
        self.host = host
        self.plugin, self.context, self.presence = host.plugin, host.context, host.presence
        self.runtime = host.runtime
        self._loop, self._thread = asyncio.get_running_loop(), threading.get_ident()
        self._binding = self._grant = None
        self._closed = self._blocked = self._ever_native = False
        self._restore_required = False
        self._restored = False
        self._state, self._reason = 'disabled', 'default_disabled'

    def _same_loop(self):
        return (threading.get_ident() == self._thread
                and asyncio.get_running_loop() is self._loop)

    def _enabled(self):
        try:
            return (self._same_loop() and not self._closed
                and self.host.plugin is self.plugin and self.host.context is self.context
                and self.host.presence is self.presence and self.host.runtime is self.runtime
                and self.runtime is not None and self.runtime.active is True
                and getattr(self.context, 'living_system', None) is self.runtime
                and self.host._enabled() is True
                and self.plugin._cfg_bool('living_native_phone_music_enabled', False) is True)
        except Exception:
            return False

    def _restore(self):
        if not self._restore_required:
            self._retain_recovery()
            return
        try:
            result = self._binding.restore(expected_generation=1)
            if result.get('state') == 'restored' and result.get('generation') == 2:
                self._restore_required, self._restored = False, True
        except Exception:
            # Keep the owner and all original references. Never overwrite a
            # changed source/object/slot, and never claim shutdown restored it.
            pass
        self._retain_recovery()

    def _retain_recovery(self):
        previous = getattr(self.context, _RECOVERY_KEY, None)
        if self._restore_required and self._blocked:
            if previous is None or previous is self:
                setattr(self.context, _RECOVERY_KEY, self)
        elif previous is self:
            delattr(self.context, _RECOVERY_KEY)

    def _fence(self, reason):
        self._blocked = True
        self._state, self._reason = 'blocked', reason
        if self._binding is not None:
            self._binding.stop()
        if self._grant is not None:
            self._grant.revoke()
        self._restore()

    def tick(self):
        """Run inside Host.start/living_tick; no scheduling or source reads."""
        if self._closed or self._blocked:
            self._restore()
            return self.diagnostics()
        if not restore_phone_music_recovery(self.context):
            self._state, self._reason = 'waiting', 'prior_restore_pending'
            return self.diagnostics()
        if not self._enabled():
            if self._ever_native:
                self._fence('host_or_enablement_revoked')
            else:
                self._state, self._reason = 'disabled', 'host_or_feature_disabled'
            return self.diagnostics()
        if self._ever_native:
            if not self._grant.current() or not self._binding.current():
                self._fence('source_or_binding_changed')
            return self.diagnostics()
        try:
            matches = [row for row in _registry(self.context)
                       if _attrs(row).get('root_dir_name') == ROOT]
            if not matches or (len(matches) == 1 and _attrs(matches[0]).get('activated') is not True):
                self._state, self._reason = 'waiting', 'phone_not_loaded'
                return self.diagnostics()
            if len(matches) != 1:
                raise ValueError('unique_live_phone_required')
            phone = _attrs(matches[0]).get('star_cls')
            if _attrs(phone).get('context') is not self.context:
                raise ValueError('shared_context_required')
            self._grant = capture_phone_music_source_grant(phone, expected_user=_single_user(phone))
            self._binding = NativePhoneMusicBinding(phone, source_grant=self._grant)
            self._binding.apply(expected_generation=0)
            self._ever_native = self._restore_required = True
            if not self._enabled() or not self._grant.current() or not self._binding.current():
                self._fence('source_changed_during_apply')
            else:
                self._state, self._reason = 'native', 'source_parser_current'
        except Exception:
            # apply performs plain dict CAS without await. Still retain an
            # applied owner if a later validation raises unexpectedly.
            if self._binding is not None and self._binding.generation == 1:
                self._ever_native = self._restore_required = True
            self._fence('source_capture_or_apply_failed')
        return self.diagnostics()

    def stop(self):
        """Fence before other Host teardown, then restore on the same loop."""
        self._closed = True
        self._fence('host_stopped')
        return self.diagnostics()

    def diagnostics(self):
        binding_current = (self._binding is not None and self._grant.current()
                           and self._binding.current())
        current = self._state == 'native' and self._enabled() and binding_current
        return dict(schema='tls.phone.music.runtime.v1', state=self._state,
            reason=self._reason, projection_current=current,
            binding_projection_current=binding_current,
            generation=self._binding.generation if self._binding is not None else 0,
            binding_slots=7 if self._ever_native else 0,
            authority_mode='source_read_grant', ever_native=self._ever_native,
            sticky_blocked=self._blocked, restore_required=self._restore_required,
            restore_pending=self._blocked and self._restore_required,
            restored=self._restored, worker_created=False, source_registration_changed=False,
            private_scope_created=False, memory_permission=False, send_permission=False,
            persistent_owner=False, restart_rebind_required=True)
