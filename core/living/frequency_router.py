"""Compatibility API for the existing three companion frequency call sites.

Ownership mechanics live in policy_router; this wrapper supplies only the pure
operations, original denial shape, full user binding and legacy owner labels.
"""
from __future__ import annotations

from . import native_frequency as native
from .journal import JournalConflict
from .policy_router import (CoordinatorBusy, MODES, NAMESPACE, ScopedPolicyRouter,
                            _ProcessLock, _validation)

FEATURE = 'companion.frequency.v1'
OPERATIONS = {'profile': native.build_frequency_profile,
              'limits': native.hard_limit_reason, 'bucket': native.sampling_bucket}


class FrequencyPolicyRouter(ScopedPolicyRouter):
    def __init__(self, journal, *, resolve_scope, authorized_scope,
                 environment='host', max_scopes=256):
        self.resolve_scope = resolve_scope
        super().__init__(journal, feature=FEATURE, operations=OPERATIONS, denied=self._denied,
            authorized_scope=authorized_scope, legacy_owner='private_companion.frequency',
            native_owner='tls.frequency', lock_suffix='.frequency.lock',
            environment=environment, max_scopes=max_scopes)

    @classmethod
    def retired_snapshot(cls, journal):
        """Restore denial metadata only, using the shared ownership validator.

        The snapshot has no identity resolver, execution authority or OS lock.
        A fresh PC owner can therefore retain durable nonlegacy fences without
        enabling Native or constructing a second live coordinator.
        """
        result = cls.__new__(cls)
        result.resolve_scope = lambda user: None
        ScopedPolicyRouter.__init__(result, journal, feature=FEATURE,
            operations=OPERATIONS, denied=result._denied,
            authorized_scope=lambda scope: False,
            legacy_owner='private_companion.frequency', native_owner='tls.frequency',
            lock_suffix='.frequency.lock', environment='isolated', _retired_snapshot=True)
        return result

    @staticmethod
    def _denied(operation):
        reason = 'TLS 频率归属不可用，暂缓主动陪伴'
        if operation == 'limits':
            return reason
        if operation == 'bucket':
            raise PermissionError(reason)
        return {'allowed': False, 'probability': 0.0, 'delay_hours': (0.5, 1.0),
                'stage': 'blocked', 'block_reason': reason, 'silent_minutes': None,
                'is_night': False, 'sampling_bucket': 0, 'sampling_minutes': 10,
                'retry_at': 0.0}

    def evaluate_user(self, operation, user, values, legacy):
        session = user.get('umo') if isinstance(user, dict) else None
        if self._retired_snapshot:
            if operation not in self.operations or not isinstance(values, dict):
                raise ValueError('unknown pure-policy operation')
            with self._lock:
                return (self.unavailable(operation) if self.has_nonlegacy_session(session)
                        else legacy(**values))
        def identity(scope):
            actual = str(user.get('user_id') or user.get('id') or '').strip() if isinstance(user, dict) else ''
            return actual == scope['user_id']
        return self.evaluate(operation, values, legacy, scope_resolver=lambda: self.resolve_scope(user),
                             session=session, identity_validator=identity)

    def has_native_binding(self, user):
        return self.has_native_session(user.get('umo') if isinstance(user, dict) else None)

    def can_resume_from(self, previous, user):
        return self._can_resume(previous, user.get('umo') if isinstance(user, dict) else None)
