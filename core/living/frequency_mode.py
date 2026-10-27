"""Recover non-executing frequency ownership before optional runtime startup."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

from .frequency_router import FEATURE, FrequencyPolicyRouter
from .presence_mode import _ExistingOwnership


def _frequency_router(value):
    """Recognize retained controller objects across a real module reload.

    PluginManager can remove/reimport the package while Context still retains
    its stopped object. Class identity changes, so require the same class
    family/module and feature; durable scope/generation validation stays in the
    shared engine rather than accepting arbitrary duck-typed lease objects.
    """
    return (getattr(value, 'feature', None) == FEATURE
            and any(base.__name__ == FrequencyPolicyRouter.__name__
                    and base.__module__ == FrequencyPolicyRouter.__module__
                    for base in type(value).__mro__))


def _preserves_recovery_high_water(snapshot, previous):
    """Preserve release receipts as well as active ownership during recovery.

    The shared handoff contract intentionally fences nonlegacy ownership only.
    A recovery guard also keeps explicit legacy releases: forgetting one would
    let a late stopped owner reinstate an older fence. Both snapshots have
    already passed the shared record validator; this only compares high water.
    """
    if (not _frequency_router(previous) or previous._closed is not True
            or previous._retired_snapshot is not True or previous._process is not None
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


def retain_frequency_tombstone(context, router):
    """Keep committed in-memory high-water marks during identity-safe stop.

    The normal controller has already validated these rows; the same shared
    constructor validates the detached stopped snapshot again. No disk access
    or second coordinator lock occurs on this synchronous shutdown path.
    """
    if not _frequency_router(router) or not router._closed:
        return False
    current = getattr(getattr(context, 'living_system', None), 'frequency_policy', None)
    if current is not None and current is not router and not getattr(current, '_closed', True):
        return False
    with router._lock:
        rows = [dict(key=FEATURE, scope_hash=key, revision=data['generation'],
                     data=copy.deepcopy(data)) for key, data in router._records.items()]
    snapshot = FrequencyPolicyRouter.retired_snapshot(SimpleNamespace(
        path=router.journal.path, ownership_records=lambda: rows))
    snapshot.journal = _ExistingOwnership(router.journal.path, feature=FEATURE)
    previous = getattr(context, '_tls_frequency_recovery', None)
    if previous is not None and not _preserves_recovery_high_water(snapshot, previous):
        return False
    if previous is None and not snapshot.has_nonlegacy_bindings():
        return False
    context._tls_frequency_recovery = snapshot
    return True


async def restore_frequency_tombstone(context, data_dir):
    """Retain durable TLS/shadow fences for a cold, fresh PC instance.

    This reuses the Presence read-only reader and shared router validator. It
    creates no journal, lock, source lease, task loop or live policy authority.
    Missing files preserve any known guard; a fresh process cannot reconstruct
    identities from a wholly missing/corrupt journal.
    """
    def live_owner():
        runtime = getattr(context, 'living_system', None)
        router = getattr(runtime, 'frequency_policy', None)
        return _frequency_router(router) and not router._closed

    if live_owner():
        return False  # Recovery must not interfere with an existing live owner.
    path = Path(data_dir) / 'living' / 'living.sqlite3'
    if not path.exists():
        return False
    if not path.is_file() or path.is_symlink():
        raise ValueError('existing ownership journal must be a regular file')
    snapshot = await asyncio.to_thread(FrequencyPolicyRouter.retired_snapshot,
                                      _ExistingOwnership(path, feature=FEATURE))
    if live_owner():
        return False
    previous = getattr(context, '_tls_frequency_recovery', None)
    if previous is not None:
        if not _preserves_recovery_high_water(snapshot, previous):
            raise PermissionError('persisted frequency ownership lost its high-water mark')
    elif not snapshot.has_nonlegacy_bindings():
        return False
    # A newer, explicitly committed legacy record may replace a known Native
    # fence. Keep that release proof for any PC instance with older local pins.
    context._tls_frequency_recovery = snapshot
    return True
