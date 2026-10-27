"""Bounded Character Card JSON import for supplemental fictional context.

This is deliberately a safe subset adapter, not a conforming V2 frontend:
system_prompt/post_history_instructions never override the existing persona.
Unknown input fields survive export; nothing is executed or fetched.
"""
from __future__ import annotations

import json

from .models import plain


MAX_CARD_BYTES = 49152
_BASE_FIELDS = ("name", "description", "personality", "scenario", "first_mes", "mes_example")


def _string(value, name, limit=6000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("invalid rolecard " + name)
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate rolecard JSON key")
        result[key] = value
    return result


def _integer(value, name, low=0, high=1000000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("invalid rolecard " + name)
    return value


def _keys(value, name):
    if not isinstance(value, list) or len(value) > 24:
        raise ValueError("invalid rolecard " + name)
    return [_string(item, name, 120) for item in value]


def import_card(payload):
    """Parse V1/V2 JSON without persona replacement or extension execution."""
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_CARD_BYTES:
            raise ValueError("rolecard exceeds byte limit")
        try:
            payload = json.loads(payload, object_pairs_hook=_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite rolecard JSON")))
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid rolecard JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("rolecard must be a JSON object")
    original = plain(payload, MAX_CARD_BYTES)
    if "spec" in original:
        if original.get("spec") != "chara_card_v2" or original.get("spec_version") != "2.0":
            raise ValueError("unsupported rolecard specification")
        data = original.get("data")
        if not isinstance(data, dict):
            raise ValueError("rolecard data must be an object")
        format_name = "character_card_v2_json_subset"
        for field in ("creator_notes", "system_prompt", "post_history_instructions", "creator", "character_version"):
            _string(data.get(field, ""), field)
        _keys(data.get("tags", []), "tags")
        greetings = data.get("alternate_greetings", [])
        if not isinstance(greetings, list) or len(greetings) > 24:
            raise ValueError("invalid rolecard alternate_greetings")
        for greeting in greetings:
            _string(greeting, "alternate_greetings", 6000)
        if not isinstance(data.get("extensions", {}), dict):
            raise ValueError("rolecard extensions must be an object")
    else:
        data = original
        format_name = "character_card_v1_json_subset"
    base = {field: _string(data.get(field), field, 120 if field == "name" else 6000)
            for field in _BASE_FIELDS}
    if not base["name"].strip():
        raise ValueError("rolecard needs a name")
    book = data.get("character_book")
    entries = []
    if book is not None:
        if not isinstance(book, dict) or not isinstance(book.get("entries"), list) or len(book["entries"]) > 48:
            raise ValueError("invalid rolecard character_book")
        if not isinstance(book.get("extensions", {}), dict):
            raise ValueError("invalid character_book extensions")
        for index, entry in enumerate(book["entries"]):
            if not isinstance(entry, dict):
                raise ValueError("invalid worldbook entry")
            enabled = entry.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("worldbook enabled must be boolean")
            for field in ("case_sensitive", "selective", "constant"):
                if field in entry and not isinstance(entry[field], bool):
                    raise ValueError("invalid worldbook " + field)
            if not isinstance(entry.get("extensions", {}), dict):
                raise ValueError("invalid worldbook extensions")
            entries.append({"entry_id": index, "keys": _keys(entry.get("keys"), "keys"),
                "content": _string(entry.get("content"), "content", 3000), "enabled": enabled,
                "insertion_order": _integer(entry.get("insertion_order"), "insertion_order"),
                "priority": _integer(entry.get("priority", 0), "priority"),
                "case_sensitive": entry.get("case_sensitive", False),
                "selective": entry.get("selective", False),
                "secondary_keys": _keys(entry.get("secondary_keys", []), "secondary_keys"),
                "constant": entry.get("constant", False)})
    return plain({"adapter_version": 1, "format": format_name, "name": base["name"],
        "supplemental": {key: base[key] for key in ("description", "personality", "scenario")},
        "worldbook": entries, "original": original,
        "ignored_prompt_fields": [name for name in ("system_prompt", "post_history_instructions") if data.get(name)]}, 65536)


def export_card(card):
    """Return detached original JSON, preserving unknown extensions/metadata."""
    if not isinstance(card, dict) or card.get("adapter_version") != 1:
        raise ValueError("invalid normalized rolecard")
    # Revalidate the source, so corrupted normalized data cannot evade bounds.
    return import_card(card.get("original"))["original"]


def select_worldbook(card, query, *, max_chars=1200):
    """Select literal keys only; no recursive triggers, regex, code or URLs."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 0 <= max_chars <= 8000:
        raise ValueError("invalid worldbook context budget")
    if not isinstance(query, str) or len(query) > 16000:
        raise ValueError("invalid worldbook query")
    normalized = import_card(export_card(card))
    selected = []
    for entry in normalized["worldbook"]:
        if not entry["enabled"]:
            continue
        haystack = query if entry["case_sensitive"] else query.casefold()
        def match(keys):
            return any(key and (key if entry["case_sensitive"] else key.casefold()) in haystack for key in keys)
        if not entry["constant"] and not (match(entry["keys"]) and
                (not entry["selective"] or match(entry["secondary_keys"]))):
            continue
        selected.append(entry)
    # Priority decides admission; insertion_order decides final presentation.
    kept = []
    remaining = max_chars
    seen = set()
    for entry in sorted(selected, key=lambda item: (-item["priority"], item["insertion_order"], item["entry_id"])):
        content = entry["content"]
        cost = len(content) + (1 if kept else 0)
        if content and content not in seen and cost <= remaining:
            kept.append(entry)
            remaining -= cost
            seen.add(content)
    return [dict(item) for item in sorted(kept, key=lambda item: (item["insertion_order"], item["entry_id"]))]
