"""Permission-gated read adapters, without an observation cache or polling loop.

``ConnectorRegistry.read`` is async. Its permission checker may be synchronous
or async and must explicitly return True. Permission is checked before source
access and again after collection. Pause, revoke, re-enable and close advance a
generation, so a pending read cannot publish after its authorization changes.

Presence adapters only read the existing snapshot; they never call refresh.
Catalog observations describe a metadata artifact read, never user playback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import inspect
import math
import re
import time
from typing import Any, Callable

from .models import EvidenceKind, Observation, plain, private_scope
from ..presence import _epoch


_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$")
_EVIDENCE = {"observed": EvidenceKind.REAL_OBSERVATION,
             "reported": EvidenceKind.USER_REPORTED,
             "inferred": EvidenceKind.MODEL_INFERENCE,
             "simulated": EvidenceKind.ROLEPLAY_EVENT,
             "derived": EvidenceKind.MODEL_INFERENCE}
_STATUSES = {"fresh", "unknown", "stale", "unavailable", "disabled", "ambiguous", "conflict"}


def _text(value: Any, limit: int = 160) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())[:limit] if isinstance(value, str) else ""


def _stamp(value: Any) -> float | None:
    try:
        return _epoch(value)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class ConnectorCapability:
    connector_id: str
    observation_types: tuple[str, ...]
    permission_scope: str
    label: str
    source_kind: str
    max_results: int = 16

    def __post_init__(self):
        if not _ID.fullmatch(self.connector_id) or not _ID.fullmatch(self.permission_scope):
            raise ValueError("invalid connector identity")
        if (not self.observation_types or len(self.observation_types) > 32 or
                any(not isinstance(v, str) or not _ID.fullmatch(v) for v in self.observation_types)):
            raise ValueError("invalid connector observation types")
        if type(self.max_results) is not int or not 1 <= self.max_results <= 64:
            raise ValueError("invalid connector result limit")

    def as_dict(self) -> dict:
        return {"connector_id": self.connector_id, "source_id": self.connector_id,
                "observation_types": list(self.observation_types),
                "permission_scope": self.permission_scope, "label": self.label,
                "source_kind": self.source_kind, "max_results": self.max_results,
                "private_scope_required": True, "read_only": True,
                "network_access": False, "background_polling": False}


@dataclass
class _Registration:
    connector: Any
    capability: ConnectorCapability
    enabled: bool = False
    paused: bool = False
    revoked: bool = False
    generation: int = 0
    health: dict = field(default_factory=lambda: {"status": "idle", "reads": 0, "returned": 0})
    pending: set = field(default_factory=set)


class ConnectorRegistry:
    """Bounded capability registry; permission checks are fail-closed.

    ``register(connector, enabled=False)`` keeps new sources opt-in. ``resume``
    only clears pause; ``enable`` explicitly clears pause/revocation. Neither
    replaces the permission checker. No observations are retained here.
    """

    def __init__(self, permission_checker: Callable, *, clock=time.time,
                 timeout_seconds: float = 2, max_connectors: int = 32):
        if not callable(permission_checker):
            raise ValueError("permission checker is required")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or not 0.01 <= timeout <= 10:
            raise ValueError("invalid connector timeout")
        if type(max_connectors) is not int or not 1 <= max_connectors <= 64:
            raise ValueError("invalid registry capacity")
        self.permission_checker, self.clock = permission_checker, clock
        self.timeout_seconds, self.max_connectors = timeout, max_connectors
        self._entries: dict[str, _Registration] = {}
        self._closed = False

    def register(self, connector: Any, *, enabled: bool = False) -> bool:
        capability = getattr(connector, "capability", None)
        if (self._closed or not isinstance(capability, ConnectorCapability) or
                not callable(getattr(connector, "read", None)) or type(enabled) is not bool):
            return False
        key = capability.connector_id
        if key in self._entries or len(self._entries) >= self.max_connectors:
            return False
        self._entries[key] = _Registration(connector, capability, enabled=enabled)
        return True

    def _transition(self, connector_id: str, action: str) -> bool:
        entry = self._entries.get(connector_id)
        if self._closed or entry is None:
            return False
        entry.generation += 1
        for task in tuple(entry.pending):
            task.cancel()
        if action == "pause":
            entry.paused = True
        elif action == "resume":
            if entry.revoked:
                return False
            entry.paused = False
        elif action == "revoke":
            entry.revoked = True
            entry.enabled = False
        elif action == "enable":
            entry.enabled, entry.paused, entry.revoked = True, False, False
        entry.health["status"] = action
        return True

    def pause(self, connector_id: str) -> bool:
        return self._transition(connector_id, "pause")

    def resume(self, connector_id: str) -> bool:
        return self._transition(connector_id, "resume")

    def revoke(self, connector_id: str) -> bool:
        return self._transition(connector_id, "revoke")

    def enable(self, connector_id: str) -> bool:
        return self._transition(connector_id, "enable")

    def close(self) -> None:
        self._closed = True
        for entry in self._entries.values():
            entry.generation += 1
            entry.health["status"] = "closed"
            for task in tuple(entry.pending):
                task.cancel()

    async def aclose(self, *, timeout_seconds: float = 0.1) -> dict:
        """Close and give cancelled readers a bounded opportunity to finish.

        A source that suppresses cancellation stays tracked, occupies its one
        pending slot, and cannot publish. It is never replaced by more tasks.
        """
        self.close()
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or not 0 <= timeout <= 5:
            raise ValueError("invalid close timeout")
        tasks = {task for entry in self._entries.values() for task in entry.pending if not task.done()}
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
        return self.health()

    def capabilities(self) -> list[dict]:
        return [entry.capability.as_dict() for entry in self._entries.values()]

    def health(self, connector_id: str | None = None) -> dict:
        def row(entry):
            return {**entry.health, "enabled": entry.enabled, "paused": entry.paused,
                    "revoked": entry.revoked, "generation": entry.generation,
                    "pending_reads": sum(not task.done() for task in entry.pending)}
        if connector_id is not None:
            entry = self._entries.get(connector_id)
            return row(entry) if entry is not None else {"status": "unknown_connector"}
        return {"closed": self._closed, "connectors": {key: row(value) for key, value in self._entries.items()}}

    def _active(self, entry: _Registration, generation: int) -> bool:
        return (not self._closed and entry.enabled and not entry.paused and
                not entry.revoked and entry.generation == generation)

    async def _permitted(self, entry: _Registration, scope: dict) -> bool:
        result = self.permission_checker(entry.capability.connector_id, dict(scope), entry.capability.permission_scope)
        if inspect.isawaitable(result):
            result = await result
        return result is True

    async def read(self, connector_id: str, scope: dict, **query) -> list[Observation]:
        entry = self._entries.get(connector_id)
        if entry is None or self._closed:
            return []
        generation = entry.generation
        if not self._active(entry, generation):
            return []
        if any(not task.done() for task in entry.pending):
            entry.health.update(status="busy", returned=0)
            return []
        task = None
        try:
            normalized = private_scope(scope)
            if "now" in query:
                raise ValueError("clock is owned by the registry")
            async def collect():
                permitted = await self._permitted(entry, normalized)
                if not self._active(entry, generation):
                    return []
                if not permitted:
                    entry.health.update(status="permission_denied", returned=0)
                    return []
                now = _epoch(self.clock())
                if now is None:
                    raise ValueError("clock is unavailable")
                entry.health["reads"] += 1
                rows = entry.connector.read(dict(normalized), now=now, **query)
                if inspect.isawaitable(rows):
                    rows = await rows
                if not self._active(entry, generation):
                    return []
                permitted = await self._permitted(entry, normalized)
                if not self._active(entry, generation):
                    return []
                if not permitted:
                    entry.health.update(status="permission_denied", returned=0)
                    return []
                if not isinstance(rows, (list, tuple)) or len(rows) > entry.capability.max_results:
                    raise ValueError("connector returned an unbounded batch")
                result = []
                for item in rows:
                    if (not isinstance(item, Observation) or item.source_id != entry.capability.connector_id or
                            item.permission_scope != entry.capability.permission_scope or item.scope != normalized or
                            item.observation_type not in entry.capability.observation_types):
                        raise ValueError("connector exceeded its declared capability")
                    result.append(Observation.from_dict(item.as_dict()))
                entry.health.update(status="ready", returned=len(result))
                entry.health.pop("error_type", None)
                return result
            task = asyncio.create_task(collect())
            entry.pending.add(task)
            def finished(done):
                entry.pending.discard(done)
                if not done.cancelled():
                    done.exception()  # Always retrieve detached failures.
            task.add_done_callback(finished)
            done, _ = await asyncio.wait({task}, timeout=self.timeout_seconds)
            if not done:
                if entry.generation == generation:
                    entry.generation += 1
                    entry.health.update(status="timeout", error_type="TimeoutError", returned=0)
                task.cancel()
                return []
            return [] if task.cancelled() else task.result()
        except asyncio.CancelledError:
            if task is not None and not task.done():
                if entry.generation == generation:
                    entry.generation += 1
                task.cancel()
            raise
        except Exception as exc:
            if entry.generation == generation and not self._closed:
                entry.health.update(status="error", error_type=type(exc).__name__, returned=0)
            return []


class PresenceSnapshotConnector:
    """Read authorized public Presence records without renewing their clocks."""

    def __init__(self, api: Any, *, source_id="presence.snapshot", domains=("time", "weather", "music"),
                 permission_scope="presence.read"):
        domains = tuple(dict.fromkeys(domains))
        self.api, self.domains = api, domains
        self.capability = ConnectorCapability(source_id, domains, permission_scope,
                                              "Existing environment observations", "presence_snapshot")

    @staticmethod
    def _payload(domain: str, value: Any) -> Any:
        if not isinstance(value, dict):
            return None
        if domain == "music":
            info = value.get("song_info") if isinstance(value.get("song_info"), dict) else {}
            state = value.get("user_state") if isinstance(value.get("user_state"), dict) else {}
            return {**{key: plain(value.get(key)) for key in ("event_type", "song_id", "match_status")},
                    "song_info": {key: _text(info.get(key)) for key in
                                  ("title", "artist", "album", "language", "genre", "mood", "source", "metadata_source")},
                    "user_state": {key: plain(state.get(key)) for key in
                                   ("state", "playing", "reliable", "observed_at", "age_seconds", "source",
                                    "device_id", "duration_ms", "progress_ms", "listening_seconds", "reason")}}
        fields = {"time": ("local", "utc_offset_hours"),
                  "weather": ("city", "condition", "is_rain", "location_scope")}.get(domain)
        return {key: plain(value.get(key)) for key in fields} if fields else plain(value)

    async def read(self, scope: dict, *, now: float, **query) -> list[Observation]:
        if query:
            raise ValueError("snapshot connector accepts no query")
        snapshot = self.api.snapshot(scope, now=now)
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        if (not isinstance(snapshot, dict) or private_scope(snapshot.get("scope")) != scope or
                not isinstance(snapshot.get("states"), dict)):
            return []
        result = []
        for domain in self.domains:
            record = snapshot["states"].get(domain, {})
            if not isinstance(record, dict):
                continue
            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
            status = record.get("status", "unknown")
            status = status if status in _STATUSES else "unknown"
            observed, expiry = _stamp(meta.get("observed_at")), _stamp(meta.get("expires_at"))
            if status == "fresh":
                if observed is None or expiry is None or observed > now + 30 or expiry < observed:
                    status, observed, expiry = "unknown", None, None
                elif now >= expiry:
                    status = "stale"
            if observed is not None and observed > now + 30:
                status, observed, expiry = "unknown", None, None
            if expiry is not None and (observed is None or expiry < observed):
                expiry = None
            payload = self._payload(domain, record.get("value")) if status == "fresh" else None
            semantic = meta.get("change_key", payload)
            if domain == "music" and isinstance(payload, dict):
                user = payload["user_state"]
                semantic = {key: payload[key] for key in ("event_type", "song_id", "match_status", "song_info")}
                semantic["user_state"] = {key: user[key] for key in
                                          ("state", "playing", "reliable", "source", "device_id")}
            if status != "fresh":
                semantic = None
            device = meta.get("device_id")
            device = device if isinstance(device, str) and _ID.fullmatch(device) else None
            result.append(Observation(source_id=self.capability.connector_id, observation_type=domain,
                scope=scope, observed_at=observed, received_at=now, expires_at=expiry,
                payload=payload, provenance={"connector": "presence_snapshot", "upstream_source": _text(record.get("source")),
                    "upstream_received_at": meta.get("received_at"), "snapshot_revision": snapshot.get("revision"),
                    "collection": "public_snapshot_without_refresh"},
                permission_scope=self.capability.permission_scope,
                evidence_kind=_EVIDENCE.get(meta.get("evidence_kind"), EvidenceKind.REAL_OBSERVATION),
                status=status, device_id=device,
                change_key={"upstream_source": record.get("source"), "status": status,
                            "value": semantic},
                importance=meta.get("importance") if meta.get("importance") in {"normal", "important", "critical"} else "normal"))
        return result


class ClockConnector:
    """Observe the server clock; never infer the user's activity or location."""

    def __init__(self, *, utc_offset_hours: float | None = None, ttl_seconds=90,
                 source_id="server.clock", permission_scope="clock.read"):
        if utc_offset_hours is not None and (isinstance(utc_offset_hours, bool) or
                not isinstance(utc_offset_hours, (int, float)) or not math.isfinite(utc_offset_hours) or
                not -14 <= utc_offset_hours <= 14):
            raise ValueError("invalid timezone offset")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300:
            raise ValueError("invalid clock TTL")
        self.offset, self.ttl_seconds = utc_offset_hours, ttl_seconds
        self.capability = ConnectorCapability(source_id, ("time",), permission_scope,
                                              "Server clock", "local_clock", max_results=1)

    async def read(self, scope: dict, *, now: float, **query) -> list[Observation]:
        if query:
            raise ValueError("clock connector accepts no query")
        tz = timezone(timedelta(hours=self.offset)) if self.offset is not None else datetime.fromtimestamp(now).astimezone().tzinfo
        local = datetime.fromtimestamp(now, tz)
        offset = local.utcoffset().total_seconds() / 3600
        payload = {"local": local.strftime("%Y-%m-%d %H:%M") + " 星期" + "一二三四五六日"[local.weekday()],
                   "utc_offset_hours": offset, "iso": local.isoformat(), "clock_basis": "server_clock"}
        return [Observation(source_id=self.capability.connector_id, observation_type="time", scope=scope,
            observed_at=now, received_at=now, expires_at=now + self.ttl_seconds, payload=payload,
            provenance={"connector": "server_clock", "clock_basis": "registry_clock",
                        "timezone_basis": "configured_offset" if self.offset is not None else "server_timezone"},
            permission_scope=self.capability.permission_scope,
            change_key={"local_minute": payload["local"], "utc_offset_hours": offset})]


class MusicCatalogConnector:
    """Read the local catalog through the TLS exact matcher and field allowlist.

    Existing get/match readers may still be injected as ``index`` or through
    ``index_factory``. The default is native; source access stays after permission.
    Without a title query, a bounded sample of unique exact matches is returned.
    """

    def __init__(self, index=None, *, path=None, index_factory=None, ttl_seconds=300,
                 source_id="music.catalog", permission_scope="music.catalog.read"):
        if (index is None) == (path is None):
            raise ValueError("provide exactly one index reader or path")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError("invalid catalog TTL")
        self._index, self._path, self._factory = index, path, index_factory
        self.ttl_seconds = ttl_seconds
        self.capability = ConnectorCapability(source_id, ("music.catalog_reference",), permission_scope,
                                              "Local music catalog metadata", "local_metadata_catalog")

    def _reader(self):
        if self._index is None:
            factory = self._factory
            if factory is None:
                from .native_music_catalog import NativeMusicCatalog
                factory = NativeMusicCatalog
            self._index = factory(self._path)
        if not all(callable(getattr(self._index, method, None)) for method in ("get", "match")):
            raise ValueError("existing MusicIndex API required")
        return self._index

    @staticmethod
    def _metadata(row: dict) -> dict:
        result = {key: _text(row.get(key)) for key in
                  ("song_id", "title", "artist", "album", "language", "genre", "mood", "source")}
        result["missing"] = [key for key in ("title", "artist", "album", "language", "genre", "mood")
                             if not result.get(key) or result.get(key) == "unknown"]
        if type(row.get("instrumental")) is bool:
            result["instrumental"] = row["instrumental"]
        return result

    def _read_sync(self, scope, now, title, artist, limit):
        from .native_music_catalog import NativeMusicCatalog, match_music
        reader = self._reader()
        index = reader.get()
        if (not isinstance(index, dict) or type(index.get("schema_version")) is not int or
                index.get("schema_version") != 1 or not isinstance(index.get("songs"), list)):
            return []
        source = _text(index.get("source"))
        built = _text(index.get("built_at"), 80)
        native = isinstance(reader, NativeMusicCatalog)
        # Native get() returned one detached snapshot. Match its metadata and
        # provenance together, even if the source file changes immediately.
        # Explicitly injected readers retain their established match API.
        lookup = (lambda title, artist: match_music(index, title, artist)) if native else reader.match
        provenance = {"connector": "local_music_catalog", "observation_basis": "metadata_artifact_read",
                      "artifact_created_at": built, "catalog_source": source,
                      "catalog_source_sha256": _text(index.get("source_sha256")),
                      "playback_claim": False,
                      "lookup": ("tls_native_catalog_exact_match"
                                 if native
                                 else "injected_index_exact_match")}
        matches = []
        if title:
            matches.append(lookup(title, artist))
        else:
            seen = set()
            for row in index["songs"][:10000]:
                if not isinstance(row, dict):
                    continue
                match = lookup(_text(row.get("title"), 300), _text(row.get("artist"), 300))
                if match.get("status") == "matched" and match.get("song_id") not in seen:
                    matches.append(match)
                    seen.add(match.get("song_id"))
                if len(matches) >= limit:
                    break
        result = []
        for match in matches[:limit]:
            status = match.get("status") if isinstance(match, dict) else "unknown"
            status = status if status in {"matched", "unknown", "ambiguous"} else "unknown"
            row = match.get("song_info") if isinstance(match.get("song_info"), dict) else {}
            count = match.get("candidate_count", 0)
            payload = {"reference_kind": "catalog_metadata", "playback_claim": False,
                       "match_status": status, "candidate_count": count if type(count) is int and 0 <= count <= 10000 else 0,
                       "song_info": self._metadata(row) if status == "matched" else {},
                       "catalog_built_at": built}
            result.append(Observation(source_id=self.capability.connector_id,
                observation_type="music.catalog_reference", scope=scope,
                observed_at=now, received_at=now, expires_at=now + self.ttl_seconds,
                payload=payload, provenance=provenance, permission_scope=self.capability.permission_scope,
                status="fresh" if status == "matched" else status,
                change_key={"catalog_source": source, "catalog_built_at": built,
                            "match_status": status, "song_info": payload["song_info"]}))
        return result

    async def read(self, scope: dict, *, now: float, title="", artist="", limit=1, **query) -> list[Observation]:
        if query or type(limit) is not int or not 1 <= limit <= self.capability.max_results:
            raise ValueError("invalid catalog query")
        if not isinstance(title, str) or not isinstance(artist, str) or len(title) > 300 or len(artist) > 300:
            raise ValueError("invalid exact-match query")
        return await asyncio.to_thread(self._read_sync, scope, now, _text(title, 300), _text(artist, 300), limit)
