"""Native priority projection for explicit companion candidates.

This is the retained PC priority contract, not its persona scoring, random
planning, fuzzy topic merging or future-window arbitration. The scheduler owns
due times and stable queue ordering after this projection.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

__all__ = ["delivery_priority", "candidate_priority"]

_SOURCES = dict(timer=100, pending_followup=92, followup=88,
                birthday_celebration=86, daily_greeting=72, meal_care=78,
                balance=82, birthday_curiosity=68, habit=64, state=60,
                story=58, event=56, creative=54, random=20)
_BIRTHDAYS = frozenset(("birthday_celebration", "birthday_eve_hint",
                        "birthday_makeup", "important_date_share"))
_GREETINGS = frozenset(("morning_greeting", "noon_greeting", "evening_greeting"))
_LEGACY_GREETING = dict(morning="morning_greeting", noon="noon_greeting",
                        evening="evening_greeting")
_TAG = re.compile(r"&&([A-Za-z_][A-Za-z0-9_]*)&&")


def _line(value: Any) -> str:
    return " ".join(str(value or "").split())[:40]


def delivery_priority(source: Any = "", reason: Any = "") -> int:
    """Map a source/reason to the established 20..100 queue priority.

    Wrapped legacy greeting tokens remain readable; source tokens are treated
    exactly as the retained PC source field (whitespace collapsed, lowercase).
    Unknown sources deliberately retain priority 48.
    """
    def canonical(match: re.Match[str]) -> str:
        token = match.group(1).lower()
        return _LEGACY_GREETING.get(token, token)

    normalized_reason = _line(_TAG.sub(canonical, str(reason or "")).strip())
    priority = _SOURCES.get(_line(source).lower(), 48)
    if normalized_reason in _BIRTHDAYS:
        return max(priority, 86)
    if normalized_reason in _GREETINGS:
        return max(priority, 72)
    if normalized_reason == "quiet_care":
        return max(priority, 74)
    return priority


def candidate_priority(candidate: Mapping[str, Any]) -> int:
    """Project an explicit candidate without reading or modifying host state."""
    if not isinstance(candidate, Mapping):
        raise TypeError("candidate must be a mapping")
    return delivery_priority(candidate.get("source"), candidate.get("reason"))
