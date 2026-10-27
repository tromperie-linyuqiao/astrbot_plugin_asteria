"""TLS-native selection of already collected Presence records at read time.

Sources, records, availability and the query clock are snapshots supplied by
the existing scoped reader. This module never collects, authorizes, stores,
refreshes or renders observations. Receiving updates and publishing observer
events remain separate responsibilities.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

__all__ = ["SourcePolicy", "project_record", "select_domain"]


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    name: str
    domains: frozenset[str]
    priority: int
    generation: int
    available: bool


@dataclass(frozen=True, slots=True)
class _Candidate:
    public: dict[str, Any]
    priority: int
    observed: float

    @property
    def rank(self) -> tuple[bool, int, float]:
        return self.public["status"] == "fresh", self.priority, self.observed


def _timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def project_record(record: Mapping[str, Any], *, now: float) -> dict[str, Any]:
    """Return a detached view without changing any source clock or expiry.

    Inputs have already passed the cache's ingress validation. In particular,
    a fresh record has an expiry; the policy does not repair malformed cache
    data or replace missing source clocks with a query timestamp.
    """
    state = record["status"]
    if state == "fresh" and now >= record["expires"]:
        state = "stale"
    metadata = {
        "observed_at": _timestamp(record["observed"]),
        "received_at": _timestamp(record["received"]),
        "expires_at": _timestamp(record["expires"]),
        "source_revision": record["source_revision"],
        "evidence_kind": record["evidence_kind"],
        "device_id": record["device_id"],
        "importance": record["importance"],
        "change_key": copy.deepcopy(record["semantic_value"]),
    }
    return {"value": copy.deepcopy(record["value"]), "source": record["source"],
            "status": state, "meta": metadata}


def _unobserved(domain: str, sources: Mapping[str, SourcePolicy]) -> dict[str, Any]:
    providers = tuple(source for source in sources.values() if domain in source.domains)
    disabled = bool(providers) and not any(source.available for source in providers)
    return {"value": None, "source": None,
            "status": "disabled" if disabled else "unknown", "meta": {}}


def select_domain(domain: str, records: Sequence[Mapping[str, Any]],
                  sources: Mapping[str, SourcePolicy], *, now: float) -> dict[str, Any]:
    """Select one domain from records already isolated to its complete scope.

    Source availability is a captured boolean, never a callback. A fresh
    record outranks every nonfresh record, followed by source priority and
    original observation time. Exact ties preserve record input order.
    """
    candidates: list[_Candidate] = []
    for record in records:
        source = sources.get(record["source"])
        if source is None or not source.available or record["generation"] != source.generation:
            continue
        candidates.append(_Candidate(project_record(record, now=now), source.priority,
                                     record["observed"] or 0))
    if not candidates:
        return _unobserved(domain, sources)

    # max retains the first exact tie, matching the existing stable ordering.
    winner = max(candidates, key=lambda candidate: candidate.rank)
    selected = winner.public
    if selected["status"] == "fresh":
        peers = tuple(candidate.public for candidate in candidates
                      if candidate.priority == winner.priority and candidate.public["status"] == "fresh")
        if any(peer["value"] != selected["value"] for peer in peers):
            selected["status"] = "conflict"
            selected["value"] = None
            selected["meta"]["conflicting_sources"] = sorted({peer["source"] for peer in peers})
    return selected
