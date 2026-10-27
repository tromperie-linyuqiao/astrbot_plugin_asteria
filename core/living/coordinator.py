"""One opt-in catalog step from the host's existing tick, without a scheduler.

The journal stores only discovery progress/workflow checkpoints. Presence owns
current observations, the original memory bridge owns memory, and Companion
owns delivery. A fresh genuine inbound identity is required after every reload.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
import time

from .connectors import ConnectorRegistry, MusicCatalogConnector
from .journal import JournalConflict
from .models import canonical, private_scope, scope_key
from .workflows import WorkflowManager


def existing_music_index(path):
    """Compatibility factory name; the implementation is owned by TLS."""
    from .native_music_catalog import NativeMusicCatalog
    return NativeMusicCatalog(path)


class CatalogCoordinator:
    source_id = "music.catalog"
    namespace = "living.catalog_progress"
    kind = "catalog.metadata_step"
    capabilities = ("catalog.read", "observe.persist", "explore.local")

    def __init__(self, runtime, *, catalog_path, enabled, share_enabled=lambda: False,
                 scope_validator=None, index_factory=existing_music_index,
                 clock=time.time, workflow_factory=WorkflowManager,
                 cooldown_seconds=6 * 3600, max_per_day=4, source_read_timeout=2.0):
        self.runtime, self.journal, self.governance = runtime, runtime.journal, runtime.governance
        self.catalog_path, self.enabled, self.share_enabled = catalog_path, enabled, share_enabled
        self.configured_path = str(catalog_path()).strip()
        self.scope_validator, self.index_factory, self.clock = scope_validator, index_factory, clock
        self.cooldown_seconds, self.max_per_day = max(21600, int(cooldown_seconds)), min(4, max(1, int(max_per_day)))
        self.active = True
        self._reader = None
        self._path = None
        self._registered_reader = None
        self._bound = False
        self._source_task = None
        self.source_read_timeout = min(3.0, max(.01, float(source_read_timeout)))
        self._running = set()
        self.registry = self._registry()
        self.workflows = workflow_factory(self.journal, self.governance, clock=clock,
            scope_validator=self._live, max_tasks=100, max_runtime=5.0, max_retries=0)
        self.workflows.register(self.kind, self._step)
        self.metrics = {"steps": 0, "denied": 0, "errors": 0}

    def _registry(self):
        return ConnectorRegistry(lambda source, scope, permission: self._permitted(scope), clock=self.clock,
                                 timeout_seconds=3)

    def _live(self, scope):
        if (not self.active or not self.runtime.active or not self.enabled() or
                str(self.catalog_path()).strip() != self.configured_path):
            return False
        return self.scope_validator(scope) is True if self.scope_validator is not None else True

    async def _permitted(self, scope):
        if not self._live(scope):
            return False
        for capability in self.capabilities:
            allowed = await asyncio.to_thread(self.governance.allows, capability, scope, self.source_id)
            if not allowed or not self._live(scope):
                return False
        return True

    def _authority(self, scope):
        return self._live(scope) and all(self.governance.allows(capability, scope, self.source_id)
                                       for capability in self.capabilities)

    async def _catalog(self, scope):
        # Both construction and get() are after the complete source grant gate.
        if not await self._permitted(scope):
            return None
        path = self.catalog_path()
        if not isinstance(path, str) or not path.strip():
            return None
        path = path.strip()
        if path.startswith(("\\\\", "//")) or "://" in path:
            return None  # This connector is for a local artifact, never a network location.
        existing = self._reader if path == self._path else None
        def read():
            if not self._authority(scope):
                return None
            reader = existing if existing is not None else self.index_factory(path)
            return reader, reader.get()
        # Keep the actual worker alive and tracked on timeout: cancelling a
        # to_thread wrapper would hide a still-running filesystem operation.
        task = asyncio.create_task(asyncio.to_thread(read))
        self._source_task = task
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        done, _ = await asyncio.wait({task}, timeout=self.source_read_timeout)
        if not done:
            return None
        result = task.result()
        if result is None or not await self._permitted(scope) or self.catalog_path().strip() != path:
            return None
        reader, value = result
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
            return None
        rows = value.get("songs")
        if not isinstance(rows, list) or len(rows) > 750:
            return None
        self._reader, self._path = reader, path
        return [row for row in rows if isinstance(row, dict) and
                all(isinstance(row.get(key), str) and row[key].strip() and len(row[key]) <= maximum
                    for key, maximum in (("song_id", 128), ("title", 300))) and
                isinstance(row.get("artist", ""), str) and len(row.get("artist", "")) <= 300]

    def _reserve_step(self, scope, song, prior):
        now = self.clock()
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        old = prior["data"] if prior else {}
        visited = list(old.get("visited", []))[:750]
        if song["song_id"] in visited or len(visited) >= 750:
            return None
        count = old.get("day_count", 0) if old.get("day") == day else 0
        if old.get("next_at", 0) > now or count >= self.max_per_day:
            return None
        data = {"visited": visited + [song["song_id"]], "next_at": now + self.cooldown_seconds,
                "day": day, "day_count": count + 1, "last_song_id": song["song_id"],
                "last_state": "reserved", "updated_at": now}
        try:
            return self.journal.put(self.namespace, "progress", scope, data,
                expected_revision=prior["revision"] if prior else 0, authorize=lambda: self._authority(scope))
        except (JournalConflict, PermissionError):
            return None

    async def _step(self, payload, context):
        scope = private_scope(context["scope"])
        if not await self._permitted(scope):
            return {"state": "denied"}
        if payload["path_signature"] != hashlib.sha256(str(self.catalog_path()).strip().encode()).hexdigest():
            return {"state": "source_changed"}
        rows = await self.registry.read(self.source_id, scope, title=payload["title"], artist=payload["artist"])
        if (not rows or not await self._permitted(scope) or
                payload["path_signature"] != hashlib.sha256(str(self.catalog_path()).strip().encode()).hexdigest()):
            return {"state": "source_unavailable"}
        obs = rows[0]
        if obs.status != "fresh" or obs.payload.get("match_status") != "matched":
            return {"state": "no_exact_match"}
        song_info = obs.payload.get("song_info")
        if not isinstance(song_info, dict) or song_info.get("song_id") != payload["song_id"]:
            # The same title/artist may resolve to a different catalog ID after
            # reservation. Never ingest it under the earlier song's workflow.
            return {"state": "source_changed"}
        result = await self.runtime.ingest(obs, publish=True)
        if not result.get("ok") or not await self._permitted(scope):
            return {"state": result.get("state", "denied")}
        output = {"state": "observed", "observation_id": obs.observation_id,
                  "memory_state": result.get("memory", {}).get("state", "not_important"),
                  "playback_claim": False}
        if self.share_enabled():
            proposed = await self.runtime.propose(obs.observation_id, scope)
            if proposed.get("ok") and proposed.get("candidate_id") and await self._permitted(scope):
                if not self.share_enabled():
                    return output
                decision = await self.runtime.decide(proposed["candidate_id"], scope)
                output.update(candidate_id=proposed["candidate_id"],
                              decision=decision.get("action", "no_action"), delivery_state="not_sent")
        return output

    async def tick(self, scope):
        """At most one bounded workflow step; denied/cooldown paths are quiet."""
        try:
            scope = private_scope(scope)
        except (ValueError, TypeError):
            return {"ok": False, "state": "invalid_scope"}
        key = scope_key(scope)
        if key in self._running or len(self._running) >= 8:
            return {"ok": False, "state": "busy"}
        if self._source_task is not None and not self._source_task.done():
            return {"ok": False, "state": "busy"}
        self._running.add(key)
        try:
            if not await self._permitted(scope):
                self.metrics["denied"] += 1
                return {"ok": False, "state": "denied"}
            prior = await asyncio.to_thread(self.journal.fetch, self.namespace, "progress", scope)
            now = self.clock()
            old = prior["data"] if prior else {}
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            if old.get("next_at", 0) > now:
                return {"ok": True, "state": "cooldown"}
            if old.get("day") == day and old.get("day_count", 0) >= self.max_per_day:
                return {"ok": True, "state": "day_limit"}
            catalog = await self._catalog(scope)
            if catalog is None:
                return {"ok": True, "state": "source_unavailable"}
            known = set(old.get("visited", []))
            choices = sorted((row for row in catalog if row["song_id"] not in known), key=lambda row: row["song_id"])
            if not choices:
                return {"ok": True, "state": "catalog_exhausted"}
            song = choices[0]
            lease = await asyncio.to_thread(self._reserve_step, scope, song, prior)
            if lease is None or not await self._permitted(scope):
                return {"ok": False, "state": "denied_or_contended"}
            if not self.registry.capabilities():
                self.registry.register(MusicCatalogConnector(self._reader, source_id=self.source_id,
                    permission_scope="catalog.read"), enabled=True)
                self._registered_reader = self._reader
            elif self._registered_reader is not self._reader:
                self.registry.close()
                self.registry = self._registry()
                self.registry.register(MusicCatalogConnector(self._reader, source_id=self.source_id,
                    permission_scope="catalog.read"), enabled=True)
                self._registered_reader = self._reader
            if not self._bound:
                self.runtime.bind_projection_source(self.source_id, ("music.catalog_reference",))
                self._bound = True
            identity = hashlib.sha256(canonical([song["song_id"], self._path]).encode()).hexdigest()
            created = await self.workflows.create(scope, source_id=self.source_id, kind=self.kind,
                payload={"song_id": song["song_id"], "title": song["title"], "artist": song.get("artist", ""),
                         "path_signature": hashlib.sha256(self._path.encode()).hexdigest()},
                idempotency_key=identity, max_runtime=5.0, retries=0)
            if not created.get("ok"):
                return created
            result = await self.workflows.run_one(scope, task_id=created["task_id"])
            if await self._permitted(scope):
                data = dict(lease["data"], last_state=result.get("state", "unknown"),
                            last_workflow_id=created["task_id"], updated_at=self.clock())
                try:
                    await asyncio.to_thread(self.journal.put, self.namespace, "progress", scope, data,
                        expected_revision=lease["revision"], authorize=lambda: self._authority(scope))
                except (JournalConflict, PermissionError):
                    pass
            if result.get("state") in {"succeeded", "failed", "cancelled"}:
                await self.workflows.forget(created["task_id"], scope)
            self.metrics["steps"] += 1
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.metrics["errors"] += 1
            return {"ok": False, "state": "source_unavailable", "error_type": type(exc).__name__}
        finally:
            self._running.discard(key)

    def stop(self):
        self.active = False
        self.registry.close()
        self.workflows.active = False

    async def close(self):
        self.stop()
        await self.registry.aclose(timeout_seconds=.1)
        await self.workflows.close()
        if self._source_task is not None and not self._source_task.done():
            await asyncio.wait({self._source_task}, timeout=.1)

    def diagnostics(self):
        return {"active": self.active, "inflight_scopes": len(self._running),
                "pending_source_read": bool(self._source_task is not None and not self._source_task.done()),
                "cooldown_seconds": self.cooldown_seconds, "max_per_day": self.max_per_day,
                "metrics": dict(self.metrics), "new_scheduler": False}
