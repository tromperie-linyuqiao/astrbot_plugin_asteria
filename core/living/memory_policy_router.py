"""Isolated ownership of final private-memory context selection only."""
from __future__ import annotations

from .memory_context import NativeMemoryContextPolicy
from .models import private_scope, scope_key
from .policy_router import ScopedPolicyRouter
from .memory_routing_strategy import public_contract as memory_strategy_contract

FEATURE = 'memory.context_selection.v1'


def _select_ids(rows, *, scope, query='', now, max_chars=900):
    return NativeMemoryContextPolicy().select(rows, scope=scope, query=query,
        now=now, max_chars=max_chars)['selected_ids']


OPERATIONS = {'select_ids': _select_ids}


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def memory_scope(value):
    """Convert the public legacy SessionContext without importing its plugin."""
    if _field(value, 'private') is True:
        return private_scope(value)
    if _field(value, 'scope') != 'private':
        raise ValueError('private memory context required')
    return private_scope(dict(platform=_field(value, 'platform'), bot_id=_field(value, 'bot_id'),
        user_id=_field(value, 'user_id'), character_id=_field(value, 'persona_id'),
        session_id=_field(value, 'session_id'), private=True))


class MemoryContextPolicyRouter(ScopedPolicyRouter):
    def __init__(self, journal, *, authorized_scope, environment='isolated', max_scopes=256):
        super().__init__(journal, feature=FEATURE, operations=OPERATIONS,
            denied=lambda operation: [], authorized_scope=authorized_scope,
            legacy_owner='memory_companion.context_selection',
            native_owner='tls.memory.context_selection', lock_suffix='.memory-context.lock',
            environment=environment, max_scopes=max_scopes)

    @classmethod
    def retired_snapshot(cls, journal):
        result = cls.__new__(cls)
        ScopedPolicyRouter.__init__(result, journal, feature=FEATURE, operations=OPERATIONS,
            denied=lambda operation: [], authorized_scope=lambda scope: False,
            legacy_owner='memory_companion.context_selection',
            native_owner='tls.memory.context_selection', lock_suffix='.memory-context.lock',
            environment='isolated', _retired_snapshot=True)
        return result

    def evaluate_ids(self, scope, rows, *, query='', now, max_chars=900, legacy, guard=None):
        values = dict(rows=rows, scope=scope, query=query, now=now, max_chars=max_chars)
        session = scope.get('session_id') if isinstance(scope, dict) else None
        with self._lock:
            if self._closed:
                return [] if self.has_nonlegacy_session(session) else legacy(**values)
        return self.evaluate('select_ids', values, legacy, scope=scope, session=session,
                             guard=guard, incomplete_legacy=True)

    def legacy_allowed(self, context):
        """A live legacy/shadow owner may compose; a stopped Native never falls back.

        Incomplete old PC bridge identities cannot evade an existing session
        fence. Explicit newer legacy releases remain valid across restarts.
        """
        session = _field(context, 'session_id')
        try:
            scope = memory_scope(context)
            key = scope_key(scope)
        except (TypeError, ValueError, AttributeError):
            with self._lock:
                return not self.has_nonlegacy_session(session)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return not self.has_nonlegacy_session(session)
            if key in self._changing:
                return False
            if record['mode'] == 'legacy':
                return True
            return record['mode'] == 'shadow' and self._authorized(scope)
