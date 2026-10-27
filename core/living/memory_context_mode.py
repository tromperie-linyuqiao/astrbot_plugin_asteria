"""Read-only recovery fences for the isolated memory-context owner.

No controller, lock, task, Native grant or new database is created by recovery.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

from .memory_policy_router import FEATURE, MemoryContextPolicyRouter
from .presence_mode import _ExistingOwnership


def _memory_router(value):
    return (getattr(value, 'feature', None) == FEATURE and any(
        base.__name__ == MemoryContextPolicyRouter.__name__
        and base.__module__ == MemoryContextPolicyRouter.__module__ for base in type(value).__mro__))


def _runtime_policy(context):
    runtime = getattr(context, 'living_system', context)
    router = getattr(runtime, 'memory_policy', None)
    if not _memory_router(router):
        router = getattr(getattr(runtime, 'unified', None), 'memory_policy', None)
    return router if _memory_router(router) else None


def current_memory_policy(context_or_runtime):
    """Choose one validated live owner or the newest stopped recovery fence.

    Both AstrBot Context and LivingRuntime are accepted. Incomparable recovery
    journals/high-water marks fail closed instead of making an arbitrary
    choice which could resurrect a released owner or forget a Native fence.
    """
    router = _runtime_policy(context_or_runtime)
    if router is not None and not router._closed:
        return router
    runtime = getattr(context_or_runtime, 'living_system', context_or_runtime)
    recoveries = (getattr(context_or_runtime, '_tls_memory_context_recovery', None),
                  getattr(runtime, 'memory_context_recovery', None))
    selected = router
    for recovery in recoveries:
        if recovery is selected or not _memory_router(recovery):
            continue
        if not recovery._closed or not recovery._retired_snapshot or recovery._process is not None:
            raise PermissionError('memory recovery must be a non-executing snapshot')
        if selected is None or _covers_high_water(recovery, selected):
            selected = recovery
        elif not _covers_high_water(selected, recovery):
            raise PermissionError('memory ownership recovery is incomparable')
    return selected


def _covers_high_water(snapshot, previous):
    if (not _memory_router(snapshot) or not _memory_router(previous)
            or not snapshot.can_resume_controller(previous)):
        return False
    with previous._lock:
        prior = copy.deepcopy(previous._records)
    with snapshot._lock:
        return all((new := snapshot._records.get(key)) is not None
                   and new['scope'] == old['scope']
                   and new['generation'] >= old['generation']
                   and (new['generation'] != old['generation'] or new['mode'] == old['mode'])
                   for key, old in prior.items())


def _preserves_high_water(snapshot, previous):
    return (_memory_router(previous) and previous._closed is True
        and previous._retired_snapshot is True and previous._process is None
        and _covers_high_water(snapshot, previous))


def retain_memory_context_tombstone(context, router):
    if not _memory_router(router) or not router._closed:
        return False
    current = _runtime_policy(context)
    if current is not None and current is not router and not current._closed:
        return False
    with router._lock:
        rows = [dict(key=FEATURE, scope_hash=key, revision=value['generation'],
                     data=copy.deepcopy(value)) for key, value in router._records.items()]
    snapshot = MemoryContextPolicyRouter.retired_snapshot(SimpleNamespace(
        path=router.journal.path, ownership_records=lambda: rows))
    snapshot.journal = _ExistingOwnership(router.journal.path, feature=FEATURE)
    previous = getattr(context, '_tls_memory_context_recovery', None)
    if previous is not None and not _preserves_high_water(snapshot, previous):
        return False
    if previous is None and not snapshot.has_nonlegacy_bindings():
        return False
    context._tls_memory_context_recovery = snapshot
    return True


async def restore_memory_context_tombstone(context, data_dir):
    def live_owner():
        router = _runtime_policy(context)
        return router is not None and not router._closed
    if live_owner():
        return False
    path = Path(data_dir) / 'living' / 'living.sqlite3'
    if not path.exists():
        return False
    if not path.is_file() or path.is_symlink():
        raise ValueError('existing memory ownership journal must be a regular file')
    snapshot = await asyncio.to_thread(MemoryContextPolicyRouter.retired_snapshot,
                                      _ExistingOwnership(path, feature=FEATURE))
    if live_owner():
        return False
    previous = getattr(context, '_tls_memory_context_recovery', None)
    if previous is not None:
        if not _preserves_high_water(snapshot, previous):
            raise PermissionError('persisted memory ownership lost its high-water mark')
    elif not snapshot.has_nonlegacy_bindings():
        return False
    context._tls_memory_context_recovery = snapshot
    return True


def memory_context_legacy_allowed(context, session_context):
    router = current_memory_policy(context)
    return router.legacy_allowed(session_context) if router is not None else True


async def set_memory_context_mode(context, scope, mode, *, expected_generation, validation=None):
    router = _runtime_policy(context)
    if (router is None or router.environment != 'isolated'
            or router._closed or router._retired_snapshot):
        raise PermissionError('a live attached isolated memory coordinator is required')
    result = await router.transition(scope, mode, expected_generation=expected_generation, validation=validation)
    if _runtime_policy(context) is not router:
        raise RuntimeError('memory owner changed; inspect durable mode before retrying')
    return result
