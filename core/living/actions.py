"""Owner-registered, bounded MOCK actions with durable simulated receipts.

No payment, network, shell, filesystem, shopping API or real delivery executor
exists here. Registration is operator-side setup, never a model capability.
"""
from __future__ import annotations

import asyncio
import copy
from decimal import Decimal, InvalidOperation
import re
import time
import uuid

from .journal import JournalConflict
from .models import Observation, plain, private_scope
from .workflows import (BoundedNamespace, ExecutionStopped, PermissionBound,
                        digest, identifier, invoke_local)

_MONEY = re.compile(r"^\d{1,8}(?:\.\d{1,2})?$")
_FORBIDDEN = frozenset({"real", "pay", "payment", "purchase", "network", "http", "shell", "file", "filesystem",
                        "bank", "transfer", "checkout", "charge", "refund", "exec", "python", "script"})


def money(value):
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValueError("money must be a bounded decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("invalid money") from None
    if not number.is_finite() or number < 0:
        raise ValueError("invalid money")
    return number.quantize(Decimal(".01"))


def validate_schema(schema, value, depth=0):
    """Deliberately small bounded JSON-schema subset; reject unknown fields."""
    if depth > 6 or not isinstance(schema, dict): raise ValueError("invalid bounded schema")
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]: raise ValueError("value outside enum")
    if kind == "object":
        if not isinstance(value, dict): raise ValueError("object required")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 32: raise ValueError("invalid properties")
        if schema.get("additionalProperties", False) is not False: raise ValueError("unbounded object forbidden")
        if set(value) - set(properties) or not set(schema.get("required", [])) <= set(value):
            raise ValueError("missing or unknown field")
        for key, item in value.items(): validate_schema(properties[key], item, depth + 1)
    elif kind == "string":
        maximum = schema.get("maxLength")
        if not isinstance(maximum, int) or not 1 <= maximum <= 4096: raise ValueError("bounded string required")
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= maximum: raise ValueError("invalid string")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value): raise ValueError("invalid string pattern")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int): raise ValueError("integer required")
        if not schema.get("minimum", -1000000) <= value <= schema.get("maximum", 1000000): raise ValueError("integer out of range")
    elif kind == "boolean":
        if not isinstance(value, bool): raise ValueError("boolean required")
    elif kind == "array":
        maximum = schema.get("maxItems")
        if not isinstance(maximum, int) or not 1 <= maximum <= 64: raise ValueError("bounded array required")
        if not isinstance(value, list) or not schema.get("minItems", 0) <= len(value) <= maximum: raise ValueError("invalid array")
        for item in value: validate_schema(schema["items"], item, depth + 1)
    else:
        raise ValueError("unsupported schema type")


def _check_schema(schema, depth=0):
    # Registration-time validation does not call any handler or execute schema text.
    if depth > 6 or not isinstance(schema, dict): raise ValueError("invalid schema")
    kind = schema.get("type")
    if kind == "object":
        if schema.get("additionalProperties", False) is not False: raise ValueError("unbounded object forbidden")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 32: raise ValueError("invalid schema properties")
        if not set(schema.get("required", [])) <= set(properties): raise ValueError("invalid required fields")
        for item in properties.values(): _check_schema(item, depth + 1)
    elif kind == "array":
        if not isinstance(schema.get("maxItems"), int) or not 1 <= schema["maxItems"] <= 64: raise ValueError("unbounded array")
        _check_schema(schema.get("items"), depth + 1)
    elif kind == "string":
        if not isinstance(schema.get("maxLength"), int) or not 1 <= schema["maxLength"] <= 4096: raise ValueError("unbounded string")
        if "pattern" in schema:
            # Only the built-in schema uses patterns; operator patterns are capped.
            if not isinstance(schema["pattern"], str) or len(schema["pattern"]) > 128: raise ValueError("invalid pattern")
            re.compile(schema["pattern"])
    elif kind not in {"integer", "boolean"}: raise ValueError("unsupported schema type")


_STRING = {"type": "string", "minLength": 1, "maxLength": 128}
_PRICE = {"type": "string", "minLength": 1, "maxLength": 11, "pattern": r"\d{1,8}(?:\.\d{1,2})?"}
_REFS = {"type": "array", "minItems": 1, "maxItems": 8,
         "items": {"type": "string", "minLength": 64, "maxLength": 64, "pattern": r"[0-9a-f]{64}"}}
ORDER_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["gift_candidate_id", "quantity", "shipping", "budget"],
    "properties": {"gift_candidate_id": _STRING,
        "quantity": {"type": "integer", "minimum": 1, "maximum": 99},
        "shipping": _PRICE, "budget": _PRICE}}


class ActionRegistry(PermissionBound):
    namespace = "living.actions"
    gift_namespace = "living.gifts"

    def __init__(self, journal, governance, *, clock=time.time, scope_validator=None,
                 max_actions=100, max_runtime=2.0, max_risk="medium"):
        super().__init__(journal, governance, clock=clock, scope_validator=scope_validator)
        if max_risk not in {"low", "medium"}: raise ValueError("high risk actions are unavailable")
        self.max_risk = max_risk
        self.max_runtime = min(max(float(max_runtime), .01), 5.0)
        self.index = BoundedNamespace(journal, self.namespace, max_actions, clock)
        self.gift_index = BoundedNamespace(journal, self.gift_namespace, max_actions, clock)
        self.definitions = {}
        self._operations, self._running = set(), {}
        self.register("simulate.gift_order", ORDER_SCHEMA, self._simulate_order, risk="low")

    @staticmethod
    def _name(name):
        identifier(name)
        if not name.startswith("simulate.") or set(re.split(r"[._:-]+", name.casefold())) & _FORBIDDEN:
            raise ValueError("only whitelisted local simulation actions are available")

    def register(self, name, schema, handler, *, risk="low", timeout=None, simulation_only=True):
        """Trusted operator setup only. Arbitrary callers cannot register tools."""
        self._name(name)
        if simulation_only is not True or risk not in {"low", "medium"} or not callable(handler):
            raise ValueError("real or high risk actions are unavailable")
        if len(self.definitions) >= 32 and name not in self.definitions: raise ValueError("registry capacity")
        duration = self.max_runtime if timeout is None else float(timeout)
        if isinstance(timeout, bool) or not .01 <= duration <= self.max_runtime: raise ValueError("invalid action timeout")
        _check_schema(schema)
        self.definitions[name] = {"schema": plain(schema, 8192), "handler": handler, "risk": risk, "timeout": duration}

    async def propose_gift(self, scope, *, source_id, item_id, title, unit_price,
                           source_observation_ids, idempotency_key, currency="CNY"):
        scope = private_scope(scope); identifier(source_id); identifier(item_id); identifier(idempotency_key)
        if not isinstance(title, str) or not 1 <= len(title) <= 160 or currency != "CNY": raise ValueError("invalid mock gift metadata")
        price = str(money(unit_price))
        validate_schema(_REFS, source_observation_ids)
        if not await self.allowed("action.simulate", scope, source_id): return {"ok": False, "state": "denied"}
        source_evidence = []
        for observation_id in source_observation_ids:
            row = await asyncio.to_thread(self.journal.get, observation_id, scope)
            if not row or row["source_id"] != source_id:
                return {"ok": False, "state": "invalid_source_reference"}
            if not await self.allowed("observe.persist", scope, row["source_id"]):
                return {"ok": False, "state": "denied"}
            source_evidence.append({"observation_id": observation_id, "evidence_kind": row["evidence_kind"], "status": row["status"]})
        candidate_id = digest([source_id, idempotency_key])
        signature = digest([item_id, title, price, currency, source_observation_ids])
        def store():
            if not self.governance.allows("action.simulate", scope, source_id): return {"ok": False, "state": "denied"}
            old = self.journal.fetch(self.gift_namespace, candidate_id, scope)
            if old:
                same = old["data"]["signature"] == signature
                return {"ok": same, "state": "duplicate" if same else "idempotency_conflict",
                        "candidate_id": candidate_id, "candidate": old["data"]}
            if not self.gift_index.reserve(candidate_id, scope): return {"ok": False, "state": "capacity"}
            candidate = {"candidate_id": candidate_id, "source_id": source_id, "item_id": item_id,
                "title": title, "unit_price": price, "currency": currency, "signature": signature,
                "source_observation_ids": list(source_observation_ids), "state": "proposed",
                "source_evidence": source_evidence,
                "created_at": self.clock(), "simulated_only": True}
            try:
                self.journal.put(self.gift_namespace, candidate_id, scope, candidate, expected_revision=0,
                    authorize=lambda: self.authorized_sync("action.simulate", scope, source_id)
                        and self.authorized_sync("observe.persist", scope, source_id)
                        and all(self.journal.get(oid, scope) is not None for oid in source_observation_ids))
            except PermissionError: return {"ok": False, "state": "denied"}
            except JournalConflict:
                old = self.journal.fetch(self.gift_namespace, candidate_id, scope)["data"]
                return {"ok": old["signature"] == signature, "state": "duplicate" if old["signature"] == signature else "idempotency_conflict",
                        "candidate_id": candidate_id, "candidate": old}
            return {"ok": True, "state": "proposed", "candidate_id": candidate_id, "candidate": candidate}
        return await asyncio.to_thread(store)

    def _finish(self, action_id, scope, state, *, claim=None, result=None, reason=None):
        for _ in range(12):
            row = self.journal.fetch(self.namespace, action_id, scope)
            if row is None: return {"ok": False, "state": "missing"}
            old = row["data"]
            if claim is not None and (old.get("claim_id") != claim or old["state"] != "running"):
                return {"ok": False, "state": old["state"], "action_id": action_id}
            data = dict(old, state=state, updated_at=self.clock())
            if result is not None: data["receipt"] = result
            if reason is not None: data["reason"] = reason
            try:
                self.journal.put(self.namespace, action_id, scope, data, expected_revision=row["revision"],
                                 authorize=(lambda: self._action_authorized(data, scope)) if state == "simulated" else None)
                self._gift_state(data, scope, state)
                return {"ok": state in {"simulated", "cancelled", "compensated"}, "state": state,
                        "action_id": action_id, "receipt": data.get("receipt"), "action": data}
            except JournalConflict: continue
            except PermissionError:
                return self._finish(action_id, scope, "cancelled", claim=claim, reason="permission_revoked")
        raise JournalConflict("action transition conflict")

    def _action_authorized(self, action, scope):
        source = action["source_id"]
        if not self.authorized_sync("action.simulate", scope, source): return False
        if action["name"] == "simulate.gift_order":
            if not self.authorized_sync("observe.persist", scope, source): return False
            candidate = self.journal.fetch(self.gift_namespace, action["payload"]["gift_candidate_id"], scope)
            if not candidate or candidate["data"]["source_id"] != source: return False
            if any(self.journal.get(oid, scope) is None for oid in candidate["data"]["source_observation_ids"]): return False
        return True

    def _gift_state(self, action, scope, state):
        if action["name"] != "simulate.gift_order": return
        allowed_previous = {"simulated": {"reserved"}, "failed": {"reserved"}, "unknown": {"reserved"},
            "cancelled": {"reserved", "unknown", "failed"}, "compensated": {"reserved", "simulated"}}
        for _ in range(12):
            row = self.journal.fetch(self.gift_namespace, action["payload"]["gift_candidate_id"], scope)
            if (not row or row["data"].get("action_id") != action["action_id"]
                    or row["data"]["state"] not in allowed_previous.get(state, set())): return
            data = dict(row["data"], state=state, receipt_id=(action.get("receipt") or {}).get("receipt_id"))
            try:
                self.journal.put(self.gift_namespace, action["payload"]["gift_candidate_id"], scope, data, expected_revision=row["revision"])
                return
            except JournalConflict: continue
        raise JournalConflict("gift state conflict")

    def _claim(self, action_id, scope, data):
        old = self.journal.fetch(self.namespace, action_id, scope)
        if old:
            same = old["data"]["payload_fingerprint"] == data["payload_fingerprint"]
            return {"ok": same and old["data"]["state"] == "simulated",
                    "state": old["data"]["state"] if same else "idempotency_conflict", "duplicate": True,
                    "action_id": action_id, "receipt": old["data"].get("receipt")}
        if not self.index.reserve(action_id, scope): return {"ok": False, "state": "capacity"}
        try:
            self.journal.put(self.namespace, action_id, scope, data, expected_revision=0,
                             authorize=lambda: self.authorized_sync("action.simulate", scope, data["source_id"]))
        except JournalConflict: return self._claim(action_id, scope, data)
        except PermissionError: return {"ok": False, "state": "denied"}
        return None

    def _claim_gift(self, candidate_id, scope, source_id, action_id):
        row = self.journal.fetch(self.gift_namespace, candidate_id, scope)
        if not row or row["data"]["source_id"] != source_id: raise ValueError("invalid gift candidate")
        if row["data"]["state"] != "proposed": raise ValueError("gift candidate already consumed")
        data = dict(row["data"], state="reserved", action_id=action_id)
        self.journal.put(self.gift_namespace, candidate_id, scope, data, expected_revision=row["revision"],
            authorize=lambda: self.authorized_sync("action.simulate", scope, source_id)
                and self.authorized_sync("observe.persist", scope, source_id))
        return data

    async def execute(self, scope, name, payload, *, source_id, idempotency_key):
        scope = private_scope(scope); self._name(name); identifier(source_id); identifier(idempotency_key)
        definition = self.definitions.get(name)
        if definition is None: return {"ok": False, "state": "not_registered"}
        if self.max_risk == "low" and definition["risk"] != "low": return {"ok": False, "state": "risk_limit"}
        payload = plain(payload, 8192); validate_schema(definition["schema"], payload)
        if len(self._operations) >= 8: return {"ok": False, "state": "busy"}
        if not await self.allowed("action.simulate", scope, source_id): return {"ok": False, "state": "denied"}
        action_id = digest([source_id, name, idempotency_key])
        claim = uuid.uuid4().hex
        data = {"action_id": action_id, "name": name, "source_id": source_id, "payload": payload,
            "payload_fingerprint": digest(payload), "claim_id": claim, "state": "running", "risk": definition["risk"],
            "created_at": self.clock(), "updated_at": self.clock(), "lease_until": self.clock() + definition["timeout"] + 1,
            "simulation_only": True}
        duplicate = await asyncio.to_thread(self._claim, action_id, scope, data)
        if duplicate is not None: return duplicate
        try:
            budget = await asyncio.to_thread(self.governance.reserve, "simulated_actions", 1, scope, reservation_id=action_id)
            if not budget["ok"]:
                return await asyncio.to_thread(self._finish, action_id, scope, "rejected", claim=claim, reason="budget_exhausted")
            if not await self.allowed("action.simulate", scope, source_id):
                return await asyncio.to_thread(self._finish, action_id, scope, "cancelled", claim=claim, reason="permission_revoked")
            context = {"action_id": action_id, "source_id": source_id, "scope": copy.deepcopy(scope), "simulated": True}
            if name == "simulate.gift_order":
                candidate = await asyncio.to_thread(self.journal.fetch, self.gift_namespace, payload["gift_candidate_id"], scope)
                if not candidate or candidate["data"]["source_id"] != source_id:
                    raise ValueError("invalid gift candidate")
                if not await self.allowed("observe.persist", scope, source_id):
                    return await asyncio.to_thread(self._finish, action_id, scope, "cancelled", claim=claim, reason="source_permission_revoked")
                for observation_id in candidate["data"]["source_observation_ids"]:
                    evidence = await asyncio.to_thread(self.journal.get, observation_id, scope)
                    if not evidence or evidence["source_id"] != source_id:
                        raise ValueError("gift source reference missing")
                context["candidate"] = await asyncio.to_thread(self._claim_gift, payload["gift_candidate_id"], scope, source_id, action_id)
            current = await asyncio.to_thread(self.journal.fetch, self.namespace, action_id, scope)
            if not current or current["data"]["state"] != "running" or current["data"].get("claim_id") != claim:
                if current:
                    await asyncio.to_thread(self._gift_state, current["data"], scope, current["data"]["state"])
                return {"ok": False, "state": current["data"]["state"] if current else "missing", "action_id": action_id}
            result = await invoke_local(definition["handler"], payload, context, timeout=definition["timeout"],
                operations=self._operations, running=self._running, job_id=action_id)
            if not await self.allowed("action.simulate", scope, source_id):
                return await asyncio.to_thread(self._finish, action_id, scope, "cancelled", claim=claim, reason="permission_revoked")
            if name == "simulate.gift_order" and not await self.allowed("observe.persist", scope, source_id):
                return await asyncio.to_thread(self._finish, action_id, scope, "cancelled", claim=claim, reason="source_permission_revoked")
            if not isinstance(result, dict) or result.get("simulated") is not True:
                raise ValueError("mock handler must return an explicit simulated receipt")
            result = dict(result, receipt_id=digest([action_id, "simulated_receipt"]), evidence_kind="action_result",
                          action_id=action_id, actual_order_placed=False, payment_charged=False)
            state = "simulated" if result.get("ok") is True else "failed"
            return await asyncio.to_thread(self._finish, action_id, scope, state, claim=claim, result=result)
        except ExecutionStopped:
            return await asyncio.to_thread(self._finish, action_id, scope, "unknown", claim=claim, reason="execution_stopped")
        except TimeoutError:
            return await asyncio.to_thread(self._finish, action_id, scope, "unknown", claim=claim, reason="timeout_no_retry")
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._finish, action_id, scope, "unknown", claim=claim, reason="caller_cancelled"))
            raise
        except PermissionError:
            return await asyncio.to_thread(self._finish, action_id, scope, "cancelled", claim=claim, reason="permission_revoked")
        except Exception as exc:
            return await asyncio.to_thread(self._finish, action_id, scope, "failed", claim=claim, reason=type(exc).__name__)

    @staticmethod
    def _simulate_order(payload, context):
        candidate = context["candidate"]
        unit = money(candidate["unit_price"])
        shipping, budget = money(payload["shipping"]), money(payload["budget"])
        total = unit * payload["quantity"] + shipping
        return {"ok": total <= budget, "simulated": True,
            "status": "simulated_order" if total <= budget else "budget_exceeded",
            "item_id": candidate["item_id"], "gift_candidate_id": candidate["candidate_id"],
            "quantity": payload["quantity"], "unit_price": str(unit), "shipping": str(shipping),
            "total": str(total), "budget": str(budget), "currency": candidate["currency"],
            "source_observation_ids": candidate["source_observation_ids"], "source_evidence": candidate.get("source_evidence", []),
            "real_financial_effect": False}

    async def cancel(self, action_id, scope):
        scope = private_scope(scope)
        for _ in range(12):
            row = await asyncio.to_thread(self.journal.fetch, self.namespace, action_id, scope)
            if row is None: return {"ok": False, "state": "missing"}
            data = row["data"]
            if data["state"] in {"cancelled", "compensated"}:
                return {"ok": True, "state": data["state"], "duplicate": True, "receipt": data.get("receipt")}
            state = "compensated" if data["state"] == "simulated" else "cancelled"
            receipt = {"ok": True, "simulated": True, "status": "simulated_compensation" if state == "compensated" else "cancelled",
                "action_id": action_id, "receipt_id": digest([action_id, "compensation"]),
                "original_receipt_id": (data.get("receipt") or {}).get("receipt_id"),
                "real_financial_effect": False, "refund_issued": False, "actual_order_placed": False}
            replacement = dict(data, state=state, receipt=receipt, original_receipt=data.get("receipt"), updated_at=self.clock())
            try:
                await asyncio.to_thread(self.journal.put, self.namespace, action_id, scope, replacement, expected_revision=row["revision"])
                await asyncio.to_thread(self._gift_state, replacement, scope, state)
                if action_id in self._running: self._running[action_id].cancel()
                return {"ok": True, "state": state, "action_id": action_id, "receipt": receipt}
            except JournalConflict: continue
        raise JournalConflict("action cancellation conflict")

    async def recover(self, scope):
        scope = private_scope(scope)
        rows = await asyncio.to_thread(self.index.rows, scope)
        count = 0
        for row in rows:
            data = row["data"]
            if data["state"] == "running" and data.get("lease_until", 0) <= self.clock():
                result = await asyncio.to_thread(self._finish, row["key"], scope, "unknown", claim=data["claim_id"], reason="restart_no_replay")
                count += result["state"] == "unknown"
        orphans = await asyncio.to_thread(self.index.release_orphans, scope, before=self.clock() - 10)
        return {"ok": True, "recovered": count, "orphan_reservations": orphans}

    async def close(self):
        self.active = False
        for task in tuple(self._operations): task.cancel()
        if self._operations: await asyncio.wait(self._operations, timeout=.1)
