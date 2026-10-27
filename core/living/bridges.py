"""Optional memory and material-only Companion adapters.

These adapters have no timer, sender, provider fallback, or private-store access.
The host authorizes sources before calling them. In-flight external writes are
durable reservations: an ambiguous acknowledgement is never silently retried.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import inspect
import re
import sys
import time
from typing import Any

from ..presence import scope_for_event
from .journal import JournalConflict
from .models import EvidenceKind, Observation, canonical, plain, private_scope, scope_key


def _loaded_api(packages, getter):
    # Do not import a plugin entrypoint or initialize another plugin ourselves.
    for package in packages:
        module = sys.modules.get(package + ".main")
        function = vars(module).get(getter) if module is not None else None
        if callable(function):
            return function()
    return None


def active_memory_bridge():
    return _loaded_api(("data.plugins.astrbot_plugin_memory_companion",
        "astrbot_plugin_memory_companion", "data.plugins.astrbot_plugin_remember_you",
        "astrbot_plugin_remember_you"), "get_active_bridge")


def private_companion_api():
    return _loaded_api(("data.plugins.astrbot_plugin_private_companion",
        "astrbot_plugin_private_companion"), "get_private_companion_api")


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


def _text(value, maximum=2000):
    return str(value).strip()[:maximum] if isinstance(value, str) else ""


def _failure(state, error, **extra):
    return {"ok": False, "state": state, "error_code": error, **extra}


class MemoryBridgeAdapter:
    """Export verified observations through the existing public memory bridge."""
    def __init__(self, journal, bridge_provider=None, *, clock=time.time):
        self.journal = journal
        self.bridge_provider = bridge_provider or active_memory_bridge
        self.clock = clock

    async def _checkpoint(self, observation_id, scope, data, revision):
        return await asyncio.to_thread(self.journal.put, "memory_links", observation_id,
            scope, data, expected_revision=revision)

    async def write(self, observation: Observation, *, authorize=None) -> dict:
        if not isinstance(observation, Observation):
            return _failure("rejected", "observation_required")
        scope = private_scope(observation.scope)
        oid = observation.observation_id
        previous = await asyncio.to_thread(self.journal.fetch, "memory_links", oid, scope)
        if not await self._authorized(authorize):
            return _failure("denied", "memory_write_authorization_revoked")
        if previous:
            data = previous["data"]
            if data.get("state") == "stored" and _text(data.get("memory_id"), 120):
                return {"ok": True, "state": "stored", "memory_id": data["memory_id"], "deduplicated": True}
            # This includes a process death after dispatch and before commit.
            return _failure(data.get("state", "unknown"), "write_requires_reconciliation")
        if not observation.valid_at(self.clock()):
            return _failure("rejected", "observation_not_fresh")
        if observation.evidence_kind not in {EvidenceKind.REAL_OBSERVATION, EvidenceKind.USER_REPORTED}:
            # Fiction/inference remains in the typed local journal. It must not
            # enter record_external_memory's external_observation fact domain.
            return _failure("unsupported", "non_real_memory_export_unsupported")
        payload = observation.payload
        content = next((_text(payload.get(k)) for k in ("summary", "content", "text")
            if _text(payload.get(k))), "") if isinstance(payload, dict) else _text(payload)
        if not content:
            return _failure("rejected", "memory_summary_required")
        try:
            bridge = await _resolve(self.bridge_provider())
        except Exception:
            return _failure("unavailable", "memory_bridge_unavailable")
        if not await self._authorized(authorize):
            return _failure("denied", "memory_write_authorization_revoked")
        writer = getattr(bridge, "record_external_memory", None)
        if not callable(writer):
            return _failure("unsupported", "memory_bridge_unavailable")
        try:
            claim = await self._checkpoint(oid, scope, {"state": "pending", "observation_id": oid}, 0)
        except JournalConflict:
            return _failure("pending", "write_already_reserved")
        if not await self._authorized(authorize):
            await self._checkpoint(oid, scope,
                {"state": "cancelled", "observation_id": oid, "reason": "authorization_revoked_before_dispatch"}, claim["revision"])
            return _failure("denied", "memory_write_authorization_revoked")
        catalog_reference = observation.observation_type == "music.catalog_reference"
        try:
            result = await writer(user_id=scope["user_id"], content=content,
                memory_type="catalog_discovery" if catalog_reference else "living_observation", source_plugin="texas_living_system",
                occurred_at=datetime.fromtimestamp(observation.observed_at, timezone.utc).isoformat(),
                idempotency_key="tls:" + scope_key(scope) + ":" + oid,
                importance={"normal": .5, "important": .7, "critical": .9}[observation.importance],
                confidence=observation.confidence if observation.confidence is not None else .8,
                tags=["living_observation", observation.observation_type, observation.evidence_kind.value]
                    + (["catalog_metadata_only", "system_catalog_read", "not_user_listening", "not_user_preference"] if catalog_reference else []),
                metadata={"observation_id": oid, "owner_bot_id": scope["bot_id"],
                    "persona_id": scope["character_id"], "living_scope_key": scope_key(scope),
                    "source_id": observation.source_id, "evidence_kind": observation.evidence_kind.value,
                    "observation_type": observation.observation_type,
                    "provenance": plain(observation.provenance, 4096),
                    "provenance_classification": observation.evidence_kind.value,
                    **({"claim_domain": "system_catalog_metadata", "user_listening_claim": False,
                        "user_preference_claim": False, "user_commitment_claim": False} if catalog_reference else {}),
                    "permission_scope": observation.permission_scope, "expires_at": observation.expires_at},
                long_term=True)
        except BaseException as exc:
            if not isinstance(exc, (Exception, asyncio.CancelledError)):
                raise
            await asyncio.shield(self._checkpoint(oid, scope,
                {"state": "unknown", "observation_id": oid, "error_type": type(exc).__name__}, claim["revision"]))
            if isinstance(exc, asyncio.CancelledError):
                raise
            return _failure("unknown", "memory_write_ack_unknown")
        memory_id = _text(result.get("memory_id"), 120) if isinstance(result, dict) else ""
        if isinstance(result, dict) and result.get("ok") is True and memory_id:
            await self._checkpoint(oid, scope,
                {"state": "stored", "observation_id": oid, "memory_id": memory_id}, claim["revision"])
            await asyncio.to_thread(self.journal.audit, "memory_export", scope, oid, "stored")
            return {"ok": True, "state": "stored", "memory_id": memory_id,
                "deduplicated": result.get("deduplicated") is True}
        # Only explicit rejection is a known failure. An invalid or success-like
        # response lacking the real record id is still an unknown outcome.
        rejected = isinstance(result, dict) and result.get("ok") is False and result.get("state") in {"rejected", "unsupported"}
        state = "rejected" if rejected else "unknown"
        await self._checkpoint(oid, scope, {"state": state, "observation_id": oid}, claim["revision"])
        return _failure(state, "memory_write_rejected" if rejected else "memory_write_ack_unknown")

    @staticmethod
    async def _authorized(authorize):
        if authorize is None:
            return True
        try:
            return await _resolve(authorize()) is True
        except Exception:
            return False

    async def context_material(self, *, scope, limit=64) -> dict:
        """Use the explicit public raw reader, never old compose or private DB."""
        try:
            scope = private_scope(scope)
            if type(limit) is not int or not 1 <= limit <= 64:
                return _failure("rejected", "invalid_material_limit", items=[])
            bridge = await _resolve(self.bridge_provider())
            reader = getattr(bridge, "read_context_material", None)
            if not callable(reader):
                return _failure("unsupported", "context_material_unavailable", items=[])
            result = await reader(session_context={
                "scope": "private", "platform": scope["platform"], "bot_id": scope["bot_id"],
                "user_id": scope["user_id"], "persona_id": scope["character_id"],
                "session_id": scope["session_id"]}, limit=limit)
            result = plain(result, 60000)
            if (not isinstance(result, dict) or result.get("ok") is not True
                    or not isinstance(result.get("items"), list) or len(result["items"]) > limit):
                return _failure("unavailable", "invalid_context_material", items=[])
            return result
        except Exception:
            # Only this optional provider boundary is contained; native policy
            # and lifecycle exceptions remain visible to their own callers.
            return _failure("unavailable", "context_material_unavailable", items=[])

    async def private_context_material(self, *, scope, limit=64) -> dict:
        """Optional public raw reader; native policy owns all final selection."""
        try:
            scope = private_scope(scope)
            if type(limit) is not int or not 1 <= limit <= 64:
                return _failure("rejected", "invalid_material_limit", items=[])
            bridge = await _resolve(self.bridge_provider())
            reader = getattr(bridge, "read_private_context_material", None)
            if not callable(reader):
                return _failure("unsupported", "private_context_material_unavailable", items=[])
            result = plain(await reader(session_context={
                "scope": "private", "platform": scope["platform"], "bot_id": scope["bot_id"],
                "user_id": scope["user_id"], "persona_id": scope["character_id"],
                "session_id": scope["session_id"]}, limit=limit), 60000)
            if (not isinstance(result, dict) or result.get("ok") is not True
                    or not isinstance(result.get("items"), list) or len(result["items"]) > limit):
                return _failure("unavailable", "invalid_private_context_material", items=[])
            return result
        except Exception:
            return _failure("unavailable", "private_context_material_unavailable", items=[])

    async def recall(self, query, *, scope, event=None, top_k=5) -> dict:
        try:
            scope = private_scope(scope)
        except (TypeError, ValueError):
            return _failure("rejected", "complete_private_scope_required", memories=[])
        if not _text(query):
            return _failure("rejected", "query_required", memories=[])
        if event is not None:
            try:
                if scope_for_event(event, scope["character_id"]) != scope:
                    return _failure("rejected", "event_scope_mismatch", memories=[])
            except Exception:
                return _failure("rejected", "event_scope_invalid", memories=[])
        try:
            bridge = await _resolve(self.bridge_provider())
            limit = min(max(int(top_k), 1), 10)
            if event is not None and callable(getattr(bridge, "recall", None)):
                raw = await bridge.recall(event=event, query=_text(query), top_k=limit)
                if not isinstance(raw, dict) or raw.get("ok") is not True:
                    return _failure("unavailable", "memory_recall_unavailable", memories=[])
                rows = raw.get("memories")
            elif callable(getattr(bridge, "search", None)):
                rows = await bridge.search(_text(query), session_context={
                    "scope": "private", "platform": scope["platform"], "bot_id": scope["bot_id"],
                    "user_id": scope["user_id"], "persona_id": scope["character_id"],
                    "session_id": scope["session_id"], "message_text": _text(query)}, top_k=limit)
            else:
                return _failure("unsupported", "memory_recall_unavailable", memories=[])
        except Exception:
            return _failure("unavailable", "memory_recall_unavailable", memories=[])
        if not isinstance(rows, list):
            return _failure("unavailable", "invalid_memory_recall_result", memories=[])
        links = await asyncio.to_thread(self.journal.list, "memory_links", scope, limit=1000)
        owned_ids = {r["data"].get("memory_id") for r in links if r["data"].get("state") == "stored"}
        safe = []
        for row in rows:
            if not isinstance(row, dict) or row.get("scope") != "private" or row.get("visibility") != "private_pair":
                continue
            if row.get("owner_bot_id") != scope["bot_id"] or row.get("persona_id") != scope["character_id"]:
                continue
            actors = [row.get("subject"), row.get("object")]
            if not any(isinstance(a, dict) and a.get("kind") == "user" and a.get("id") == scope["user_id"] for a in actors):
                continue
            if row.get("session_id") != scope["session_id"] and row.get("id") not in owned_ids:
                continue
            if row.get("reality_level") not in {"real_user_fact", "external_observation", "observed_utterance"}:
                continue
            safe.append(plain(row, 32768))
        return {"ok": True, "state": "ready", "memories": safe[:limit], "filtered_count": len(rows) - len(safe)}

    async def _unsupported_change(self, observation_id, scope, operation):
        try:
            scope = private_scope(scope)
        except (TypeError, ValueError):
            return _failure("rejected", "complete_private_scope_required")
        link = await asyncio.to_thread(self.journal.fetch, "memory_links", str(observation_id), scope)
        if not link or link["data"].get("state") != "stored":
            return _failure("rejected", "owned_memory_link_required")
        # delete_note is not a general delete API. Never unwrap bridge._plugin,
        # open the memory DB, or borrow Companion's protected capabilities.
        return _failure("unsupported", "memory_" + operation + "_api_unavailable")

    async def correct(self, observation_id, content, *, scope):
        return await self._unsupported_change(observation_id, scope, "correction")

    async def delete(self, observation_id, *, scope):
        return await self._unsupported_change(observation_id, scope, "deletion")


class CompanionAbilityAdapter:
    """Return material to Companion's current loop; never send or schedule."""
    def __init__(self, journal, scope_resolver, material_provider, api_provider=None,
            *, name="tls_living_material", clock=time.time, authorize_delivery=None):
        self.journal = journal
        self.scope_resolver = scope_resolver
        self.material_provider = material_provider
        self.api_provider = api_provider or private_companion_api
        self.name = name
        self.clock = clock
        self._api = None
        self._executor = self.executor
        self._listener = self._on_delivery_receipt
        self._receipt_owner = None
        self._authorize_delivery_callback = authorize_delivery

    def register(self):
        try:
            api = self.api_provider()
            register = getattr(api, "register_proactive_ability", None)
            if not callable(register):
                return _failure("unsupported", "companion_extension_unavailable")
            accepted = register({"name": self.name, "module": "Texas Living System",
                "label": "生活观察素材", "description": "有来源及完整私聊归属的生活观察素材",
                "default_enabled": False, "min_interval_hours": 12, "share_probability": .12,
                "executor": self._executor})
            if accepted is not True:
                return _failure("rejected", "companion_registration_rejected")
            self._api = api
            receipt_register = getattr(api, "register_proactive_delivery_listener", None)
            if callable(receipt_register):
                try:
                    self._receipt_owner = receipt_register(self.name, executor=self._executor,
                        listener=self._listener, authorize=self._authorize_delivery)
                except Exception:
                    self._receipt_owner = None
            return {"ok": True, "state": "registered", "delivery_receipts":
                "atomic_image_text" if self._receipt_owner is not None else "unsupported"}
        except Exception:
            return _failure("unavailable", "companion_registration_unavailable")

    def close(self):
        api, self._api = self._api, None
        owner, self._receipt_owner = self._receipt_owner, None
        remove_listener = getattr(api, "unregister_proactive_delivery_listener", None)
        if owner is not None and callable(remove_listener):
            try:
                remove_listener(self.name, owner=owner)
            except Exception:
                pass
        unregister = getattr(api, "unregister_proactive_ability", None)
        if not callable(unregister):
            return False
        try:
            return unregister(self.name) is True
        except Exception:
            return False

    async def executor(self, context):
        if self._api is None:
            return {"ok": False, "status": "companion_not_registered", "context": "", "summary": ""}
        if not isinstance(context, dict):
            return {"ok": False, "status": "context_invalid", "context": "", "summary": ""}
        try:
            scope = private_scope(await _resolve(self.scope_resolver(context)))
            user = context.get("user")
            if not isinstance(user, dict) or str(user.get("user_id") or user.get("id") or "") != scope["user_id"] or user.get("umo") != scope["session_id"]:
                raise ValueError("scope mismatch")
        except Exception:
            return {"ok": False, "status": "private_scope_mismatch", "context": "", "summary": ""}
        try:
            material = await _resolve(self.material_provider(scope, context))
        except Exception:
            return {"ok": False, "status": "material_unavailable", "context": "", "summary": ""}
        if not isinstance(material, dict) or material.get("ok") is False:
            return {"ok": False, "status": "material_unavailable", "context": "", "summary": ""}
        text = _text(material.get("text"), 500)
        summary = _text(material.get("summary"), 500) or text
        content = _text(material.get("context"), 2000) or text or summary
        if not content:
            return {"ok": False, "status": "material_empty", "context": "", "summary": ""}
        identity = _text(material.get("decision_id") or material.get("material_id") or material.get("observation_id"), 128)
        key = hashlib.sha256(canonical([self.name, identity or [text, summary, content]]).encode()).hexdigest()
        reference = {name: _text(material.get(name), 64) for name in ("decision_id", "candidate_id", "observation_id")}
        correlated = self._receipt_owner is not None and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in reference.values())
        previous = await asyncio.to_thread(self.journal.fetch, "share_material", key, scope)
        if previous:
            return {"ok": False, "status": "prepared_only_duplicate", "context": "", "summary": ""}
        try:
            await asyncio.to_thread(self.journal.put, "share_material", key, scope,
                {"state": "prepared_only", "material_id": identity,
                    "delivery_receipts": "atomic_image_text" if correlated else "unsupported",
                    **(reference if correlated else {}),
                    "content_digest": hashlib.sha256(content.encode()).hexdigest()}, expected_revision=0)
        except JournalConflict:
            return {"ok": False, "status": "prepared_only_duplicate", "context": "", "summary": ""}
        await asyncio.to_thread(self.journal.audit, "share_material", scope, key, "prepared_only")
        # The optional opaque envelope is consumed by the selected native
        # external action only. It never enters generated text or user storage.
        result = {"ok": True, "text": text, "summary": summary, "context": content,
            "status": "prepared_only", "delivery_state": "awaiting_receipt" if correlated else "unsupported"}
        if correlated:
            result.update(_delivery_owner=self._receipt_owner,
                _delivery_reference={**reference, "scope": scope, "scope_key": scope_key(scope)})
        return result

    async def _on_delivery_receipt(self, receipt):
        if not isinstance(receipt, dict) or self._receipt_owner is None or receipt.get("owner") is not self._receipt_owner:
            return False
        status = receipt.get("status")
        reference = receipt.get("reference")
        if status not in {"confirmed", "failed", "unknown"} or not isinstance(reference, dict):
            return False
        try:
            scope = private_scope(reference.get("scope"))
        except (TypeError, ValueError):
            return False
        if reference.get("scope_key") != scope_key(scope):
            return False
        ids = {key: reference.get(key) for key in ("decision_id", "candidate_id", "observation_id")}
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in ids.values()):
            return False
        rows = await asyncio.to_thread(self.journal.list, "share_material", scope, limit=1000)
        links = [row for row in rows if all(row["data"].get(key) == value for key, value in ids.items())]
        if len(links) != 1:
            return False
        link = links[0]
        if link["data"].get("state") != "prepared_only":
            return link["data"].get("receipt_id") == receipt.get("receipt_id")
        decision = await asyncio.to_thread(self.journal.fetch, "decisions", ids["decision_id"], scope)
        candidate = await asyncio.to_thread(self.journal.fetch, "candidates", ids["candidate_id"], scope)
        receipt_id = _text(receipt.get("receipt_id"), 64)
        if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
            return False
        # The receipt link is authoritative; candidate/decision are derived views
        # carrying the same receipt id for explicit reconciliation after IO errors.
        settled = {"receipt_id": receipt_id, "receipt_at": self.clock()}
        await asyncio.to_thread(self.journal.put, "share_material", link["key"], scope,
            {**link["data"], **settled, "state": status}, expected_revision=link["revision"])
        if decision and decision["data"].get("status") == "prepared_only" and all(decision["data"].get(key) == value for key, value in ids.items()):
            await asyncio.to_thread(self.journal.put, "decisions", ids["decision_id"], scope,
                {**decision["data"], **settled, "status": status}, expected_revision=decision["revision"])
        if candidate and candidate["data"].get("state") == "prepared_only" and all(candidate["data"].get(key) == ids[key] for key in ("candidate_id", "observation_id")):
            await asyncio.to_thread(self.journal.put, "candidates", ids["candidate_id"], scope,
                {**candidate["data"], **settled, "state": status}, expected_revision=candidate["revision"])
        event = {"confirmed": "ShareSent", "failed": "ShareNotSent", "unknown": "ShareDeliveryUnknown"}[status]
        await asyncio.to_thread(self.journal.audit, event, scope, ids["decision_id"], status,
            {"receipt_id": receipt_id})
        return True

    async def _authorize_delivery(self, request):
        if not isinstance(request, dict) or self._receipt_owner is None or request.get("owner") is not self._receipt_owner:
            return False
        reference = request.get("reference")
        if not isinstance(reference, dict):
            return False
        try:
            scope = private_scope(reference.get("scope"))
        except (TypeError, ValueError):
            return False
        if reference.get("scope_key") != scope_key(scope):
            return False
        ids = {key: reference.get(key) for key in ("decision_id", "candidate_id", "observation_id")}
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in ids.values()):
            return False

        def current_source():
            decision = self.journal.fetch("decisions", ids["decision_id"], scope)
            candidate = self.journal.fetch("candidates", ids["candidate_id"], scope)
            raw = self.journal.get(ids["observation_id"], scope)
            if not decision or not candidate or not raw:
                return None
            if any(decision["data"].get(key) != value for key, value in ids.items()):
                return None
            if decision["data"].get("status") != "prepared_only" or candidate["data"].get("state") != "prepared_only":
                return None
            if any(candidate["data"].get(key) != ids[key] for key in ("candidate_id", "observation_id")):
                return None
            obs = Observation.from_dict(raw)
            if obs.scope != scope or obs.observation_id != ids["observation_id"] or not obs.valid_at(self.clock()):
                return None
            if candidate["data"].get("source_id") != obs.source_id:
                return None
            links = self.journal.list("share_material", scope, limit=1000)
            if sum(row["data"].get("state") == "prepared_only" and all(row["data"].get(key) == value for key, value in ids.items()) for row in links) != 1:
                return None
            return obs.source_id

        async def policy(source_id):
            callback = self._authorize_delivery_callback
            return True if callback is None else await _resolve(callback(scope, source_id)) is True

        try:
            source_id = await asyncio.to_thread(current_source)
            if not source_id or not await policy(source_id):
                return False
            # Re-read after the policy await, then check live policy again at the
            # dispatch boundary. No external work happens between this and send.
            if await asyncio.to_thread(current_source) != source_id:
                return False
            return await policy(source_id)
        except Exception:
            return False

    def record_delivery_receipt(self, *args, **kwargs):
        return _failure("unsupported", "trusted_external_delivery_receipt_hook_unavailable")
