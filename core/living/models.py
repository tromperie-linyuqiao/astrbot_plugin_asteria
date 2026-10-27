"""Versioned observations; external content remains data, never instructions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any

from ..presence import _epoch, _json_value, normalize_scope


class EvidenceKind(str, Enum):
    REAL_OBSERVATION = "real_observation"
    USER_REPORTED = "user_reported"
    MODEL_INFERENCE = "model_inference"
    ROLEPLAY_EVENT = "roleplay_event"
    ACTION_RESULT = "action_result"


PRESENCE_EVIDENCE = {
    EvidenceKind.REAL_OBSERVATION: "observed",
    EvidenceKind.USER_REPORTED: "reported",
    EvidenceKind.MODEL_INFERENCE: "inferred",
    EvidenceKind.ROLEPLAY_EVENT: "simulated",
    EvidenceKind.ACTION_RESULT: "derived",
}
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$")


def plain(value: Any, max_bytes: int = 32768) -> Any:
    return _json_value(value, max_bytes=max_bytes)


def canonical(value: Any) -> str:
    return json.dumps(plain(value, 131072), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def scope_key(scope: dict) -> str:
    return hashlib.sha256(canonical(normalize_scope(scope)).encode()).hexdigest()


def private_scope(scope: dict) -> dict:
    value = normalize_scope(scope)
    if not value["private"] or not all(value[k] for k in
            ("platform", "bot_id", "user_id", "character_id", "session_id")):
        raise ValueError("complete private identity required")
    return value


@dataclass(frozen=True)
class Observation:
    source_id: str
    observation_type: str
    scope: dict
    observed_at: float | None
    received_at: float
    expires_at: float | None
    payload: Any
    provenance: dict
    permission_scope: str
    evidence_kind: EvidenceKind = EvidenceKind.REAL_OBSERVATION
    confidence: float | None = None
    status: str = "fresh"
    device_id: str | None = None
    change_key: Any = None
    importance: str = "normal"
    schema_version: int = 1

    def __post_init__(self):
        for value in (self.source_id, self.observation_type, self.permission_scope):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise ValueError("invalid observation identifier")
        object.__setattr__(self, "scope", private_scope(self.scope))
        object.__setattr__(self, "payload", plain(self.payload))
        if not isinstance(self.provenance, dict) or not self.provenance:
            raise ValueError("provenance is required")
        object.__setattr__(self, "provenance", plain(self.provenance, 4096))
        object.__setattr__(self, "change_key", plain(self.change_key))
        object.__setattr__(self, "evidence_kind", EvidenceKind(self.evidence_kind))
        for name in ("observed_at", "received_at", "expires_at"):
            object.__setattr__(self, name, _epoch(getattr(self, name)))
        if self.received_at is None:
            raise ValueError("received_at is required")
        if self.observed_at is not None and self.observed_at > self.received_at + 30:
            raise ValueError("observation occurs after receipt")
        if self.status == "fresh" and (self.observed_at is None or self.expires_at is None):
            raise ValueError("fresh observation needs source time and expiry")
        if self.expires_at is not None and (self.observed_at is None or self.expires_at < self.observed_at):
            raise ValueError("invalid expiry")
        if self.status not in {"fresh", "unknown", "stale", "unavailable", "disabled", "ambiguous", "conflict"}:
            raise ValueError("invalid observation status")
        if self.importance not in {"normal", "important", "critical"}:
            raise ValueError("invalid importance")
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("unsupported observation version")
        if self.confidence is not None and (isinstance(self.confidence, bool) or
                not isinstance(self.confidence, (float, int)) or not math.isfinite(self.confidence) or
                not 0 <= self.confidence <= 1):
            raise ValueError("invalid confidence")
        if self.device_id is not None and (not isinstance(self.device_id, str) or not _ID.fullmatch(self.device_id)):
            raise ValueError("invalid device identity")

    @property
    def observation_id(self) -> str:
        # Receipt time and progress-only transport values do not identify a new event.
        fact = self.change_key if self.change_key is not None else self.payload
        identity = [self.source_id, scope_key(self.scope), self.observation_type,
                    self.device_id, self.observed_at, self.evidence_kind.value, self.status,
                    self.provenance.get("upstream_id"), fact]
        return hashlib.sha256(canonical(identity).encode()).hexdigest()

    def valid_at(self, now: float) -> bool:
        value = _epoch(now)
        return bool(self.status == "fresh" and self.expires_at is not None and
                    value is not None and self.observed_at <= value + 30 and value < self.expires_at)

    def as_dict(self) -> dict:
        return plain({"schema_version": self.schema_version, "source_id": self.source_id,
            "observation_type": self.observation_type, "scope": self.scope,
            "observed_at": self.observed_at, "received_at": self.received_at,
            "expires_at": self.expires_at, "payload": self.payload,
            "provenance": self.provenance, "permission_scope": self.permission_scope,
            "evidence_kind": self.evidence_kind.value, "confidence": self.confidence,
            "status": self.status, "device_id": self.device_id,
            "change_key": self.change_key, "importance": self.importance}, 131072)

    @classmethod
    def from_dict(cls, value: dict) -> "Observation":
        if not isinstance(value, dict):
            raise ValueError("observation must be a mapping")
        return cls(**value)
