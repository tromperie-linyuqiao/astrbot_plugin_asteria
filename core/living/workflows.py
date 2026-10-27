"""Explicit local workflow steps and evidence-backed preference history.

There is no scheduler here. An owner-controlled caller registers local handlers
and explicitly calls run_one/recover. Journal checkpoints are workflow records,
not a replacement Presence cache or a replacement long-term memory database.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import re
import time
import uuid

from .journal import JournalConflict
from .models import EvidenceKind, Observation, canonical, plain, private_scope

_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$")


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class BoundedNamespace:
    """CAS-reserved identities bound a namespace across concurrent instances."""
    def __init__(self, journal, namespace, maximum, clock):
        self.journal, self.namespace, self.clock = journal, namespace, clock
        self.maximum = min(max(int(maximum), 1), 100)

    def reserve(self, key, scope):
        for _ in range(16):
            row = self.journal.fetch(self.namespace + ".index", "index", scope)
            items = dict(row["data"]["items"]) if row else {}
            if key in items:
                return True
            if len(items) >= self.maximum:
                return False
            items[key] = self.clock()
            try:
                self.journal.put(self.namespace + ".index", "index", scope, {"items": items},
                                 expected_revision=row["revision"] if row else 0)
                return True
            except JournalConflict:
                continue
        raise JournalConflict("namespace reservation conflict")

    def rows(self, scope):
        return self.journal.list(self.namespace, scope, limit=self.maximum)

    def release_orphans(self, scope, *, before):
        for _ in range(16):
            row = self.journal.fetch(self.namespace + ".index", "index", scope)
            if not row:
                return 0
            items = row["data"]["items"]
            keep = {key: at for key, at in items.items()
                    if at >= before or self.journal.fetch(self.namespace, key, scope) is not None}
            removed = len(items) - len(keep)
            if not removed:
                return 0
            try:
                self.journal.put(self.namespace + ".index", "index", scope, {"items": keep},
                                 expected_revision=row["revision"])
                return removed
            except JournalConflict:
                continue
        raise JournalConflict("namespace recovery conflict")


class PermissionBound:
    def __init__(self, journal, governance, *, clock=time.time, scope_validator=None):
        self.journal, self.governance, self.clock = journal, governance, clock
        self.scope_validator = scope_validator
        self.active = True

    def authorized_sync(self, capability, scope, source):
        """Journal transaction guard; asynchronous validators fail closed."""
        if not self.active: return False
        if self.scope_validator is not None:
            valid = self.scope_validator(scope)
            if inspect.isawaitable(valid):
                if inspect.iscoroutine(valid): valid.close()
                return False
            if not valid: return False
        return bool(self.governance.allows(capability, scope, source))

    async def allowed(self, capability, scope, source):
        if not self.active:
            return False
        if self.scope_validator is not None:
            valid = self.scope_validator(scope)
            valid = await valid if inspect.isawaitable(valid) else valid
            if not valid:
                return False
        permit = await asyncio.to_thread(self.governance.allows, capability, scope, source)
        if not self.active:
            return False
        if self.scope_validator is not None:
            valid = self.scope_validator(scope)
            valid = await valid if inspect.isawaitable(valid) else valid
            if not valid:
                return False
        return bool(permit)


class ExecutionStopped(Exception):
    pass


async def invoke_local(handler, payload, context, *, timeout, operations, running, job_id):
    """Bound even a handler that ignores cancellation; no automatic retry."""
    if len(operations) >= 8:
        raise RuntimeError("local operation capacity reached")
    async def call():
        result = (await handler(copy.deepcopy(payload), context) if inspect.iscoroutinefunction(handler)
                  else await asyncio.to_thread(handler, copy.deepcopy(payload), context))
        if inspect.isawaitable(result):
            result = await result
        return plain(result, 8192)
    task = asyncio.create_task(call())
    operations.add(task)
    running[job_id] = task
    def finished(done):
        operations.discard(done)
        if running.get(job_id) is done:
            running.pop(job_id, None)
        if not done.cancelled():
            done.exception()
    task.add_done_callback(finished)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            task.cancel()
            raise TimeoutError("local handler outcome is unknown")
        if task.cancelled():
            raise ExecutionStopped()
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        raise


class WorkflowManager(PermissionBound):
    namespace = "living.workflows"

    def __init__(self, journal, governance, *, clock=time.time, scope_validator=None,
                 max_tasks=100, max_runtime=2.0, max_retries=2):
        super().__init__(journal, governance, clock=clock, scope_validator=scope_validator)
        self.max_runtime = min(max(float(max_runtime), .01), 5.0)
        self.max_retries = min(max(int(max_retries), 0), 3)
        self.index = BoundedNamespace(journal, self.namespace, max_tasks, clock)
        self.handlers = {}
        self._operations, self._running = set(), {}

    def register(self, kind, handler):
        """Owner-side setup only; this method is never exposed as a model tool."""
        identifier(kind)
        if not callable(handler) or len(self.handlers) >= 32 and kind not in self.handlers:
            raise ValueError("invalid local handler")
        self.handlers[kind] = handler

    async def create(self, scope, *, source_id, kind, payload, idempotency_key,
                     priority=0, max_runtime=None, retries=0):
        scope = private_scope(scope)
        identifier(source_id); identifier(kind); identifier(idempotency_key)
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 9:
            raise ValueError("invalid priority")
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= self.max_retries:
            raise ValueError("invalid retry limit")
        runtime = self.max_runtime if max_runtime is None else float(max_runtime)
        if isinstance(max_runtime, bool) or not .01 <= runtime <= self.max_runtime:
            raise ValueError("invalid runtime limit")
        payload = plain(payload, 8192)
        if not await self.allowed("explore.local", scope, source_id):
            return {"ok": False, "state": "denied"}
        task_id = digest([source_id, kind, idempotency_key])
        signature = digest([kind, payload, priority, runtime, retries])
        def store():
            if not self.governance.allows("explore.local", scope, source_id):
                return {"ok": False, "state": "denied"}
            old = self.journal.fetch(self.namespace, task_id, scope)
            if old:
                return {"ok": old["data"]["signature"] == signature,
                        "state": "duplicate" if old["data"]["signature"] == signature else "idempotency_conflict",
                        "task_id": task_id, "task": old["data"]}
            if not self.index.reserve(task_id, scope):
                return {"ok": False, "state": "capacity"}
            data = {"task_id": task_id, "source_id": source_id, "kind": kind, "payload": payload,
                    "signature": signature, "priority": priority, "max_runtime": runtime,
                    "max_retries": retries, "attempts": 0, "failures": 0, "state": "pending", "created_at": self.clock(),
                    "updated_at": self.clock(), "next_run_at": self.clock(), "history": []}
            try:
                self.journal.put(self.namespace, task_id, scope, data, expected_revision=0,
                                 authorize=lambda: self.authorized_sync("explore.local", scope, source_id))
            except PermissionError:
                return {"ok": False, "state": "denied"}
            except JournalConflict:
                old = self.journal.fetch(self.namespace, task_id, scope)
                return {"ok": old["data"]["signature"] == signature, "state": "duplicate",
                        "task_id": task_id, "task": old["data"]}
            return {"ok": True, "state": "pending", "task_id": task_id, "task": data}
        return await asyncio.to_thread(store)

    def _transition(self, task_id, scope, state, *, claim=None, reason=None, result=None, next_run_at=None, from_states=None, failures=None):
        for _ in range(12):
            row = self.journal.fetch(self.namespace, task_id, scope)
            if not row:
                return {"ok": False, "state": "missing"}
            old = row["data"]
            if from_states is not None and old["state"] not in from_states:
                return {"ok": False, "state": old["state"], "task_id": task_id}
            if claim is not None and (old.get("claim_id") != claim or old["state"] != "running"):
                return {"ok": False, "state": old["state"], "task_id": task_id}
            data = dict(old, state=state, updated_at=self.clock())
            data["history"] = (old.get("history", []) + [{"state": state, "at": self.clock(), "reason": reason}])[-20:]
            if reason is not None: data["reason"] = reason
            if result is not None: data["result"] = result
            if next_run_at is not None: data["next_run_at"] = next_run_at
            if failures is not None: data["failures"] = failures
            if state != "running": data.pop("lease_until", None)
            try:
                self.journal.put(self.namespace, task_id, scope, data, expected_revision=row["revision"],
                    authorize=(lambda: self.authorized_sync("explore.local", scope, old["source_id"]))
                              if state in {"succeeded", "pending"} else None)
                return {"ok": state not in {"failed", "uncertain"}, "changed": True,
                        "state": state, "task_id": task_id, "task": data}
            except JournalConflict:
                continue
            except PermissionError:
                if claim is not None:
                    return self._transition(task_id, scope, "paused", claim=claim, reason="permission_revoked")
                return {"ok": False, "state": "denied", "task_id": task_id}
        raise JournalConflict("workflow transition conflict")

    async def run_one(self, scope, *, task_id=None):
        scope = private_scope(scope)
        if len(self._operations) >= 8:
            return {"ok": False, "state": "busy"}
        rows = await asyncio.to_thread(self.index.rows, scope)
        eligible = [row for row in rows if row["data"]["state"] == "pending"
                    and row["data"].get("next_run_at", 0) <= self.clock()
                    and (task_id is None or row["key"] == task_id)]
        eligible.sort(key=lambda row: (-row["data"]["priority"], row["data"]["created_at"], row["key"]))
        for row in eligible:
            data = row["data"]; task_id = data["task_id"]
            if not await self.allowed("explore.local", scope, data["source_id"]):
                continue
            handler = self.handlers.get(data["kind"])
            if handler is None:
                return {"ok": False, "state": "handler_unavailable", "task_id": task_id}
            budget = await asyncio.to_thread(self.governance.reserve, "explorations", 1, scope,
                reservation_id=task_id + ":" + str(data["attempts"] + 1))
            if not budget["ok"]:
                return {"ok": False, "state": "budget_exhausted", "task_id": task_id}
            claim = uuid.uuid4().hex
            claimed = dict(data, state="running", claim_id=claim, attempts=data["attempts"] + 1,
                           updated_at=self.clock(), lease_until=self.clock() + data["max_runtime"] + 1)
            try:
                await asyncio.to_thread(self.journal.put, self.namespace, task_id, scope, claimed,
                    expected_revision=row["revision"], authorize=lambda: self.authorized_sync("explore.local", scope, data["source_id"]))
            except JournalConflict:
                continue
            except PermissionError:
                return {"ok": False, "state": "denied", "task_id": task_id}
            try:
                if not await self.allowed("explore.local", scope, data["source_id"]):
                    return await asyncio.to_thread(self._transition, task_id, scope, "paused", claim=claim, reason="permission_revoked")
                current = await asyncio.to_thread(self.journal.fetch, self.namespace, task_id, scope)
                if not current or current["data"]["state"] != "running" or current["data"].get("claim_id") != claim:
                    return {"ok": False, "state": current["data"]["state"] if current else "missing", "task_id": task_id}
                result = await invoke_local(handler, data["payload"],
                    {"task_id": task_id, "source_id": data["source_id"], "scope": copy.deepcopy(scope)},
                    timeout=data["max_runtime"], operations=self._operations, running=self._running, job_id=task_id)
                if not await self.allowed("explore.local", scope, data["source_id"]):
                    return await asyncio.to_thread(self._transition, task_id, scope, "paused", claim=claim, reason="permission_revoked")
                return await asyncio.to_thread(self._transition, task_id, scope, "succeeded", claim=claim, result=result)
            except ExecutionStopped:
                return await asyncio.to_thread(self._transition, task_id, scope, "uncertain", claim=claim, reason="execution_stopped")
            except TimeoutError:
                return await asyncio.to_thread(self._transition, task_id, scope, "uncertain", claim=claim, reason="timeout_no_retry")
            except asyncio.CancelledError:
                await asyncio.shield(asyncio.to_thread(self._transition, task_id, scope, "uncertain", claim=claim, reason="caller_cancelled"))
                raise
            except Exception as exc:
                failures = claimed.get("failures", 0) + 1
                retry = failures <= data["max_retries"]
                return await asyncio.to_thread(self._transition, task_id, scope, "pending" if retry else "failed",
                    claim=claim, reason=type(exc).__name__, failures=failures,
                    next_run_at=self.clock() + min(30, 2 ** min(failures, 5)))
        return {"ok": True, "state": "no_action"}

    async def pause(self, task_id, scope):
        row = await asyncio.to_thread(self.journal.fetch, self.namespace, task_id, private_scope(scope))
        if not row or row["data"]["state"] not in {"pending", "running"}:
            return {"ok": False, "state": row["data"]["state"] if row else "missing"}
        result = await asyncio.to_thread(self._transition, task_id, scope, "paused", reason="owner_paused", from_states={"pending", "running"})
        if task_id in self._running: self._running[task_id].cancel()
        return result

    async def resume(self, task_id, scope):
        scope = private_scope(scope)
        row = await asyncio.to_thread(self.journal.fetch, self.namespace, task_id, scope)
        if not row or row["data"]["state"] != "paused":
            return {"ok": False, "state": row["data"]["state"] if row else "missing"}
        data = row["data"]
        if not await self.allowed("explore.local", scope, data["source_id"]):
            return {"ok": False, "state": "denied"}
        return await asyncio.to_thread(self._transition, task_id, scope, "pending", reason="owner_resumed", next_run_at=self.clock(), from_states={"paused"})

    async def cancel(self, task_id, scope):
        scope = private_scope(scope)
        row = await asyncio.to_thread(self.journal.fetch, self.namespace, task_id, scope)
        if not row or row["data"]["state"] in {"succeeded", "failed", "cancelled"}:
            return {"ok": bool(row and row["data"]["state"] == "cancelled"),
                    "state": row["data"]["state"] if row else "missing"}
        result = await asyncio.to_thread(self._transition, task_id, scope, "cancelled", reason="owner_cancelled",
                                         from_states={"pending", "running", "paused", "uncertain"})
        if task_id in self._running: self._running[task_id].cancel()
        return result

    async def recover(self, scope):
        scope = private_scope(scope)
        rows = await asyncio.to_thread(self.index.rows, scope)
        count = 0
        for row in rows:
            data = row["data"]
            if data["state"] == "running" and data.get("lease_until", 0) <= self.clock():
                result = await asyncio.to_thread(self._transition, row["key"], scope, "uncertain",
                    claim=data["claim_id"], reason="interrupted_no_automatic_replay")
                count += result.get("changed", False)
        orphans = await asyncio.to_thread(self.index.release_orphans, scope, before=self.clock() - 10)
        return {"ok": True, "recovered": count, "orphan_reservations": orphans}

    async def forget(self, task_id, scope):
        """Explicitly retire a terminal task; callers retain visited-item history.

        The journal atomically removes both the terminal checkpoint and its
        index reservation. Failure or interruption cannot strand either half.
        """
        scope = private_scope(scope); identifier(task_id)
        def retire():
            row = self.journal.fetch(self.namespace, task_id, scope)
            if not row: return {"ok": True, "state": "missing", "task_id": task_id}
            if row["data"]["state"] not in {"succeeded", "failed", "cancelled"}:
                return {"ok": False, "state": row["data"]["state"], "task_id": task_id}
            try:
                removed = self.journal.remove_indexed_checkpoint(self.namespace, task_id, scope,
                    index_namespace=self.namespace + ".index", expected_revision=row["revision"])
            except JournalConflict:
                current = self.journal.fetch(self.namespace, task_id, scope)
                return {"ok": current is None, "state": current["data"]["state"] if current else "missing", "task_id": task_id}
            return {"ok": True, "state": "forgotten" if removed else "missing", "task_id": task_id}
        return await asyncio.to_thread(retire)

    async def close(self):
        self.active = False
        for task in tuple(self._operations): task.cancel()
        if self._operations: await asyncio.wait(self._operations, timeout=.1)


class PreferenceLedger(PermissionBound):
    """Evidence review records; promotion never writes native long-term memory."""
    namespace = "living.preferences"

    def __init__(self, journal, governance, *, clock=time.time, scope_validator=None, max_keys=100):
        super().__init__(journal, governance, clock=clock, scope_validator=scope_validator)
        self.index = BoundedNamespace(journal, self.namespace, max_keys, clock)

    @staticmethod
    def _classify(events, stable_allowed):
        latest = events[-1]
        eligible = [event for event in events if event["value"] == latest["value"] and event["stance"] == "supports"
                    and event.get("status") == "fresh" and event["observed_at"] is not None
                    and event["evidence_kind"] in {EvidenceKind.REAL_OBSERVATION.value, EvidenceKind.USER_REPORTED.value}
                    and (event["confidence"] is None or event["confidence"] >= .7)]
        days = {int(event["observed_at"] // 86400) for event in eligible if event["observed_at"] is not None}
        contradicted = any(event["stance"] != "supports" or event["value"] != latest["value"] for event in events[-3:])
        stable = stable_allowed and len(eligible) >= 3 and len(days) >= 2 and not contradicted
        if stable: classification = "stable_supported"
        elif latest["stance"] != "supports": classification = "uncertain_or_negative"
        else: classification = {"real_observation": "observed_pattern", "user_reported": "user_reported",
            "model_inference": "inferred", "roleplay_event": "roleplay", "action_result": "action_result"}[latest["evidence_kind"]]
        return {"classification": classification, "stable": bool(stable), "value": latest["value"],
                "stance": latest["stance"], "supporting_observations": [event["observation_id"] for event in eligible]}

    async def record(self, scope, key, value, *, observation_id, stance="supports", confidence=None):
        scope = private_scope(scope); identifier(key)
        value = plain(value, 512)
        if stance not in {"supports", "opposes", "uncertain"}: raise ValueError("invalid preference stance")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            raise ValueError("invalid preference confidence")
        row = await asyncio.to_thread(self.journal.get, observation_id, scope)
        if row is None: return {"ok": False, "state": "missing_evidence"}
        obs = Observation.from_dict(row)
        if obs.confidence is not None:
            confidence = obs.confidence if confidence is None else min(confidence, obs.confidence)
        if not await self.allowed("observe.persist", scope, obs.source_id): return {"ok": False, "state": "denied"}
        stable_allowed = await self.allowed("memory.write", scope, obs.source_id)
        def store():
            if not self.governance.allows("observe.persist", scope, obs.source_id): return {"ok": False, "state": "denied"}
            if not self.index.reserve(key, scope): return {"ok": False, "state": "capacity"}
            for _ in range(12):
                previous = self.journal.fetch(self.namespace, key, scope)
                data = previous["data"] if previous else {"key": key, "events": []}
                old = next((event for event in data["events"] if event["observation_id"] == observation_id), None)
                if old:
                    same = old["value"] == value and old["stance"] == stance and old["confidence"] == confidence
                    return {"ok": same, "state": "duplicate" if same else "evidence_conflict", "preference": data}
                event = {"observation_id": observation_id, "source_id": obs.source_id,
                    "evidence_kind": obs.evidence_kind.value, "observed_at": obs.observed_at,
                    "status": obs.status,
                    "recorded_at": self.clock(), "old_value": data.get("current", {}).get("value"),
                    "value": value, "stance": stance, "confidence": confidence}
                events = (data["events"] + [event])[-32:]
                promote = stable_allowed and all(self.governance.allows("memory.write", scope, source)
                    for source in {event["source_id"] for event in events})
                current = self._classify(events, promote)
                next_data = {"key": key, "events": events, "current": current,
                             "buckets": {kind.value: [e["observation_id"] for e in events if e["evidence_kind"] == kind.value]
                                         for kind in EvidenceKind}, "updated_at": self.clock()}
                try:
                    self.journal.put(self.namespace, key, scope, next_data,
                        expected_revision=previous["revision"] if previous else 0,
                        authorize=lambda: self.authorized_sync("observe.persist", scope, obs.source_id)
                            and self.journal.get(observation_id, scope) is not None
                            and (not current["stable"] or all(self.authorized_sync("memory.write", scope, source)
                                 for source in {event["source_id"] for event in events})))
                    return {"ok": True, "state": "recorded", "preference": next_data}
                except JournalConflict: continue
                except PermissionError: return {"ok": False, "state": "denied"}
            raise JournalConflict("preference update conflict")
        return await asyncio.to_thread(store)

    async def read(self, scope, key):
        row = await asyncio.to_thread(self.journal.fetch, self.namespace, identifier(key), private_scope(scope))
        if row is None: return {"ok": False, "state": "missing"}
        sources = {event["source_id"] for event in row["data"]["events"]}
        if not all([await self.allowed("memory.read", scope, source) for source in sources]):
            return {"ok": False, "state": "denied"}
        return {"ok": True, "preference": row["data"]}


def discover_catalog_candidates(catalog, preferences=None, *, known_ids=(), limit=5):
    """Deterministic metadata selection; no listening or external discovery claim."""
    if not isinstance(catalog, (list, tuple)) or len(catalog) > 1000: raise ValueError("bounded local catalog required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10: raise ValueError("invalid discovery limit")
    preferences = preferences or {}
    if not isinstance(preferences, dict): raise ValueError("invalid local preferences")
    for values in (preferences.get("positive_tags", []), preferences.get("negative_tags", [])):
        if not isinstance(values, list) or len(values) > 32 or any(not isinstance(v, str) or len(v) > 128 for v in values):
            raise ValueError("bounded preference tags required")
    if not isinstance(known_ids, (list, tuple, set)) or len(known_ids) > 1000:
        raise ValueError("bounded known identifiers required")
    positive = {v.casefold() for v in preferences.get("positive_tags", [])}
    negative = {v.casefold() for v in preferences.get("negative_tags", [])}
    known = set(str(value) for value in known_ids)
    results, seen = [], set()
    for entry in catalog:
        if not isinstance(entry, dict): continue
        sid = str(entry.get("song_id") or "")[:128]
        title = entry.get("title")
        if not sid or sid in known or sid in seen or not isinstance(title, str) or not title.strip(): continue
        source_tags = entry.get("tags") or []
        if not isinstance(source_tags, list) or any(not isinstance(tag, str) for tag in source_tags[:32]): continue
        tags = {tag.casefold() for tag in source_tags[:32]}
        if tags & negative: continue
        seen.add(sid)
        clean = lambda value: ' '.join(re.sub(r'[\x00-\x1f\x7f<>]', ' ', str(value)).split())[:160]
        results.append({"song_id": sid, "title": clean(title), "artist": clean(entry.get("artist") or ""),
            "matched_preferences": sorted(tags & positive), "score": len(tags & positive),
            "evidence": "local_catalog_metadata", "playback_claim": False,
            "source_observation_id": entry.get("source_observation_id")})
    return sorted(results, key=lambda item: (-item["score"], item["song_id"]))[:limit]


class CatalogDiscovery:
    def __init__(self, catalog): self.catalog = plain(list(catalog), 131072)
    def __call__(self, payload, context):
        return {"candidates": discover_catalog_candidates(self.catalog, payload.get("preferences"),
                    known_ids=payload.get("known_ids", ()), limit=payload.get("limit", 5)),
                "execution": "local_metadata_only", "new_network_calls": 0}
