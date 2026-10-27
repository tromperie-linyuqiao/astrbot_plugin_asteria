"""Opt-in isolated ownership of Presence read TTL/source selection only.

The caller owns scope/cache, evaluates source availability once, and supplies
detached records/immutable source metadata. This router never refreshes a source
or owns ingestion, projection, context rendering, timers or delivery.
"""
from __future__ import annotations

from . import native_presence_policy as native
from .policy_router import ScopedPolicyRouter

FEATURE = "presence.read_selection.v1"
OPERATIONS = {"select": native.select_domain}


class PresencePolicyRouter(ScopedPolicyRouter):
    def __init__(self, journal, *, authorized_scope, environment="isolated", max_scopes=256):
        super().__init__(journal, feature=FEATURE, operations=OPERATIONS, denied=self._denied,
            authorized_scope=authorized_scope, legacy_owner="presence.read_selection",
            native_owner="tls.presence.read_selection", lock_suffix=".presence-selection.lock",
            environment=environment, max_scopes=max_scopes)

    @classmethod
    def retired_snapshot(cls, journal):
        """Restore validated non-executing ownership, without taking an OS lock.

        This is a fail-closed tombstone, never a way to activate Native without
        the trusted factory. The shared engine validates the exact same rows.
        """
        result = cls.__new__(cls)
        ScopedPolicyRouter.__init__(result, journal, feature=FEATURE, operations=OPERATIONS,
            denied=result._denied, authorized_scope=lambda scope: False,
            legacy_owner="presence.read_selection", native_owner="tls.presence.read_selection",
            lock_suffix=".presence-selection.lock", environment="isolated", _retired_snapshot=True)
        return result

    @staticmethod
    def _denied(operation):
        return {"value": None, "source": None, "status": "unavailable", "meta": {}}

    def evaluate_selection(self, scope, domain, records, sources, *, now, legacy, guard=None):
        values = dict(domain=domain, records=records, sources=sources, now=now)
        session = scope.get("session_id") if isinstance(scope, dict) else None
        with self._lock:
            # A retired nonlegacy owner remains a scoped tombstone. Unrelated
            # legacy scopes keep their original owner and ordinary behavior.
            if self._closed:
                return self._denied("select") if self.has_nonlegacy_session(session) else legacy(**values)
        return self.evaluate("select", values, legacy, scope=scope, session=session,
                             guard=guard, incomplete_legacy=True)
