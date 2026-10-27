"""Read existing Presence ownership for a stopped, fail-closed restart guard.

No new journal, grants, coordinator lock, source state, task loop or Native
authority is created. Actual transitions still belong to the live router.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3

from .presence_policy_router import FEATURE, PresencePolicyRouter


class _ExistingOwnership:
    def __init__(self, path, *, feature=FEATURE):
        self.path = Path(path)
        self.feature = feature

    def ownership_records(self):
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("unsupported existing TLS ownership schema")
            rows = connection.execute(
                "SELECT key,scope,revision,data FROM checkpoints "
                "WHERE namespace='tls.ownership' AND key=? ORDER BY scope LIMIT 257", (self.feature,)).fetchall()
            if len(rows) > 256:
                raise ValueError("Presence ownership capacity exceeded")
            result = []
            for key, scope, revision, data in rows:
                if not isinstance(data, str) or len(data.encode("utf8")) > 16384:
                    raise ValueError("invalid bounded Presence ownership row")
                result.append(dict(key=key, scope_hash=scope, revision=revision, data=json.loads(data)))
            return result
        finally:
            connection.close()


async def restore_presence_tombstone(presence, data_dir):
    """Attach before optional runtime construction, including factory failure.

    No file means no database/worker task is created. If a previous in-memory
    tombstone exists, absence never clears it. A wholly deleted/corrupt database
    in a fresh process cannot reveal lost identities; that limit is diagnosed by
    the caller instead of fabricating per-user leases.
    """
    path = Path(data_dir) / "living" / "living.sqlite3"
    if not path.exists():
        return False
    if not path.is_file() or path.is_symlink():
        raise ValueError("existing ownership journal must be a regular file")
    snapshot = await asyncio.to_thread(PresencePolicyRouter.retired_snapshot, _ExistingOwnership(path))
    return presence.restore_read_policy_tombstone(snapshot)


def _operator_router(presence):
    from ..presence import PresenceLayer
    router = getattr(presence, '_read_policy_router', None)
    if (not isinstance(presence, PresenceLayer) or presence._closed
            or not isinstance(router, PresencePolicyRouter) or router.environment != 'isolated'
            or router._closed or router._retired_snapshot):
        raise PermissionError('a live attached isolated Presence coordinator is required')
    return router


def presence_mode_status(presence, scope):
    """Local operator metadata only; no identity, observation or grant output."""
    return _operator_router(presence).snapshot(scope)


async def set_presence_mode(presence, scope, mode, *, expected_generation, validation=None):
    """Use the actual live router's CAS; never grant or manufacture validation.

    Operator/test Python only: no config UI, LLM tool, remote endpoint or offline
    competing writer is registered. Native still requires the trusted factory,
    fresh identity, current clean shadow comparisons and explicit receipt.
    """
    router = _operator_router(presence)
    result = await router.transition(scope, mode, expected_generation=expected_generation, validation=validation)
    if _operator_router(presence) is not router:
        raise RuntimeError('Presence owner changed; inspect durable mode before retrying')
    return result
