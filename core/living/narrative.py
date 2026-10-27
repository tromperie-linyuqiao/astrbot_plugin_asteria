"""Scoped fictional continuity and explicit preferences inside the TLS runtime.

Uses existing checkpoint CAS and retention bounds. It creates no timer, sender,
LLM client, observation, or real-world memory. Call disk APIs off the event loop.
"""
from __future__ import annotations

import json
import math
import re
import time

from .journal import JournalConflict
from .models import plain, private_scope, scope_key
from .rolecard_adapter import import_card, select_worldbook


_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,95}$")
_NS = {"scene": "tls.narrative.scene", "preference": "tls.narrative.preference",
       "inference": "tls.narrative.inference", "persona": "tls.narrative.persona"}
_KINDS = {"scene": "roleplay_event", "persona": "roleplay_event",
          "preference": "user_reported", "inference": "model_inference"}


def _id(value, field):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid narrative " + field)
    return value


def _text(value, field, limit=1200):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("invalid narrative " + field)
    return value


def _participant_id(value):
    # AstrBot persona identifiers are allowed to contain Unicode and spaces.
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError("invalid narrative participant_id")
    return value


def _time(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid narrative " + field)
    return float(value)


def _strings(value, field, *, maximum=16, limit=240):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("invalid narrative " + field)
    return [_text(item, field, limit) for item in value]


def choose_strategy(requested="normal", *, scene_active=False, explicit_preference=None):
    """Pure explicit selection. Silence is not evidence of mood or permission."""
    modes = {"normal", "deep", "rp", "continue_plot", "share", "playful", "quiet"}
    if requested not in modes or not isinstance(scene_active, bool):
        raise ValueError("invalid interaction strategy")
    if explicit_preference is not None and explicit_preference not in modes:
        raise ValueError("invalid explicit interaction preference")
    mode = explicit_preference if explicit_preference is not None else requested
    reason = "explicit_preference" if explicit_preference is not None else "requested"
    if mode in {"rp", "continue_plot"} and not scene_active:
        mode, reason = "normal", "no_active_fictional_scene"
    return {"mode": mode, "reason": reason, "schedules_message": False,
            "changes_core_persona": False, "infers_emotion": False}


class NarrativeStore:
    """Private-scope checkpoints, separated by evidence namespace.

    authorize(operation, normalized_scope) must explicitly return True. Supported
    operations are read, write and preferences.write. Journal authorization is
    repeated inside the transaction, preventing late permission revocation.
    """
    def __init__(self, journal, *, authorize, clock=time.time):
        if not callable(authorize) or not callable(clock):
            raise TypeError("narrative authorization and clock must be callable")
        self.journal, self.authorize, self.clock = journal, authorize, clock

    def _allowed(self, operation, scope):
        if self.authorize(operation, dict(scope)) is not True:
            raise PermissionError("narrative authority denied")

    def _now(self, now=None):
        return _time(self.clock() if now is None else now, "clock")

    def _write(self, kind, key, scope, payload, source_id, *, expires_at=None, expected_revision=None):
        scope = private_scope(scope)
        operation = "preferences.write" if kind == "preference" else "write"
        self._allowed(operation, scope)
        now = self._now()
        if expected_revision is not None and (isinstance(expected_revision, bool) or
                not isinstance(expected_revision, int) or expected_revision < 0):
            raise ValueError("invalid narrative expected revision")
        data = {"schema_version": 1, "kind": kind, "evidence_kind": _KINDS[kind],
            "scope": scope, "scope_hash": scope_key(scope), "source_id": _id(source_id, "source_id"),
            "updated_at": now, "expires_at": expires_at, "payload": payload}
        return self.journal.put(_NS[kind], key, scope, data, expected_revision=expected_revision,
            authorize=lambda: self.authorize(operation, dict(scope)) is True)

    def _checked(self, record, kind, scope):
        if not isinstance(record, dict) or isinstance(record.get("revision"), bool) or not isinstance(record.get("revision"), int) or record["revision"] < 1:
            raise ValueError("corrupt narrative checkpoint")
        data = record.get("data")
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("unsupported narrative checkpoint")
        if data.get("kind") != kind or data.get("evidence_kind") != _KINDS[kind] or data.get("scope") != scope or data.get("scope_hash") != scope_key(scope):
            raise ValueError("narrative checkpoint binding mismatch")
        updated_at = _time(data.get("updated_at"), "updated_at")
        if updated_at > self._now() + 30:
            raise ValueError("narrative checkpoint is in the future")
        _id(data.get("source_id"), "source_id")
        expiry = data.get("expires_at")
        if expiry is not None:
            _time(expiry, "expires_at")
            if expiry <= updated_at:
                raise ValueError("invalid narrative checkpoint expiry")
        if kind in {"preference", "persona"} and expiry is not None:
            raise ValueError("unexpected narrative checkpoint expiry")
        payload = data.get("payload")
        if kind == "scene":
            if self._scene(payload, scope, validating=True) != payload:
                raise ValueError("noncanonical fictional scene")
            if payload["expires_at"] != expiry or payload["source_id"] != data["source_id"]:
                raise ValueError("narrative scene expiry/source mismatch")
        elif kind == "persona":
            if not isinstance(payload, dict) or import_card(payload.get("original")) != payload:
                raise ValueError("corrupt normalized rolecard")
        elif kind == "preference":
            if not isinstance(payload, dict) or set(payload) != {"key", "value"}:
                raise ValueError("corrupt narrative preference")
            _id(payload["key"], "preference key")
            _text(payload["value"], "preference", 320)
        elif kind == "inference":
            if not isinstance(payload, dict) or set(payload) != {"key", "text", "confidence"}:
                raise ValueError("corrupt narrative inference")
            _id(payload["key"], "inference key")
            _text(payload["text"], "inference", 320)
            self._confidence(payload["confidence"])
            if expiry is None:
                raise ValueError("inference expiry required")
        record_key = record.get("key")
        payload_key = payload.get("scene_id") if kind == "scene" else payload.get("key")
        if record_key is not None and kind != "persona" and record_key != payload_key:
            raise ValueError("narrative checkpoint key mismatch")
        return record

    @staticmethod
    def _confidence(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid narrative inference confidence")
        return float(value)

    def _read(self, kind, key, scope, *, now=None, include_expired=False):
        scope = private_scope(scope)
        self._allowed("read", scope)
        record = self.journal.fetch(_NS[kind], key, scope)
        if record is None:
            return None
        self._checked(record, kind, scope)
        payload = record["data"]["payload"]
        if kind == "scene" and payload["scene_id"] != key or kind in {"preference", "inference"} and payload["key"] != key:
            raise ValueError("narrative checkpoint key mismatch")
        self._allowed("read", scope)
        expiry = record["data"]["expires_at"]
        if not include_expired and expiry is not None and self._now(now) >= expiry:
            return None
        return record

    @staticmethod
    def _known_to(value, participant_ids):
        if not isinstance(value, list) or not value or len(value) > 12 or any(not isinstance(item, str) for item in value) or len(set(value)) != len(value):
            raise ValueError("invalid narrative known_to")
        if any(not isinstance(item, str) or item not in participant_ids for item in value):
            raise ValueError("narrative event references unknown participant")
        return list(value)

    def _event(self, event, participant_ids):
        if not isinstance(event, dict) or set(event) - {"event_id", "source_id", "text", "known_to", "occurred_at"}:
            raise ValueError("invalid narrative event")
        occurred = _time(event.get("occurred_at"), "occurred_at")
        if occurred > self._now() + 30:
            raise ValueError("narrative event is in the future")
        return {"event_id": _id(event.get("event_id"), "event_id"),
            "source_id": _id(event.get("source_id"), "event source_id"),
            "text": _text(event.get("text"), "event text", 600),
            "known_to": self._known_to(event.get("known_to"), participant_ids), "occurred_at": occurred}

    def _scene(self, scene, scope, *, validating=False):
        if not isinstance(scene, dict) or set(scene) - {"scene_id", "source_id", "title", "participants", "summary", "timeline", "unfinished_arcs", "expires_at", "status"}:
            raise ValueError("invalid fictional scene fields")
        expires = _time(scene.get("expires_at"), "expires_at")
        if not validating and not self._now() < expires <= self._now() + 31 * 86400:
            raise ValueError("scene requires a future expiry within 31 days")
        participants = scene.get("participants")
        if not isinstance(participants, list) or not 1 <= len(participants) <= 12:
            raise ValueError("invalid fictional scene participants")
        cleaned = []
        ids = set()
        for participant in participants:
            if not isinstance(participant, dict) or set(participant) != {"participant_id", "display_name", "known_facts"}:
                raise ValueError("invalid fictional participant")
            identity = _participant_id(participant["participant_id"])
            if identity in ids:
                raise ValueError("duplicate fictional participant")
            ids.add(identity)
            cleaned.append({"participant_id": identity,
                "display_name": _text(participant["display_name"], "display_name", 80),
                "known_facts": _strings(participant["known_facts"], "known_facts", maximum=16, limit=240)})
        if scope["character_id"] not in ids:
            raise ValueError("scope character must be a scene participant")
        timeline = scene.get("timeline", [])
        if not isinstance(timeline, list) or len(timeline) > 64:
            raise ValueError("fictional timeline capacity reached")
        events = [self._event(event, ids) for event in timeline]
        if len({event["event_id"] for event in events}) != len(events):
            raise ValueError("duplicate fictional event identity")
        arcs = scene.get("unfinished_arcs", [])
        if not isinstance(arcs, list) or len(arcs) > 16:
            raise ValueError("invalid unfinished arcs")
        clean_arcs = []
        for arc in arcs:
            if not isinstance(arc, dict) or set(arc) != {"arc_id", "text", "known_to"}:
                raise ValueError("invalid unfinished arc")
            clean_arcs.append({"arc_id": _id(arc["arc_id"], "arc_id"),
                "text": _text(arc["text"], "arc text", 400), "known_to": self._known_to(arc["known_to"], ids)})
        if len({arc["arc_id"] for arc in clean_arcs}) != len(clean_arcs):
            raise ValueError("duplicate unfinished arc identity")
        status = scene.get("status", "active")
        if status not in {"active", "paused", "closed"}:
            raise ValueError("invalid fictional scene status")
        return plain({"scene_id": _id(scene.get("scene_id"), "scene_id"),
            "source_id": _id(scene.get("source_id"), "source_id"),
            "title": _text(scene.get("title"), "title", 120), "participants": cleaned,
            "summary": _text(scene.get("summary", ""), "shared summary", 1600),
            "timeline": events, "unfinished_arcs": clean_arcs,
            "expires_at": expires, "status": status}, 49152)

    def put_scene(self, scope, scene, *, expected_revision=0):
        """Explicit create/replace. Summary is shared fiction, not private knowledge."""
        scope = private_scope(scope)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("scene writes require an explicit expected revision")
        scene = self._scene(scene, scope)
        return self._write("scene", scene["scene_id"], scope, scene, scene["source_id"],
            expires_at=scene["expires_at"], expected_revision=expected_revision)

    def read_scene(self, scope, scene_id=None, *, now=None, include_expired=False):
        scope = private_scope(scope)
        if scene_id is not None:
            return self._read("scene", _id(scene_id, "scene_id"), scope, now=now, include_expired=include_expired)
        self._allowed("read", scope)
        # Bounded scan of this private scope; never select a scene from another.
        for record in self.journal.list(_NS["scene"], scope, limit=1000):
            self._checked(record, "scene", scope)
            self._allowed("read", scope)
            if record["data"]["payload"]["status"] == "active" and (include_expired or self._now(now) < record["data"]["expires_at"]):
                return record
        return None

    def append_event(self, scope, scene_id, event, *, expected_revision=None):
        """CAS append; duplicate IDs are idempotent only for identical payloads."""
        scope = private_scope(scope)
        self._allowed("write", scope)
        _id(scene_id, "scene_id")
        if expected_revision is not None and (isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0):
            raise ValueError("invalid narrative expected revision")
        for _ in range(32):
            record = self._read("scene", scene_id, scope)
            if record is None or record["data"]["payload"]["status"] != "active":
                raise ValueError("active fictional scene not found")
            if expected_revision is not None and record["revision"] != expected_revision:
                raise JournalConflict("narrative revision conflict")
            scene = record["data"]["payload"]
            normalized = self._event(event, {item["participant_id"] for item in scene["participants"]})
            for previous in scene["timeline"]:
                if previous["event_id"] == normalized["event_id"]:
                    if previous != normalized:
                        raise JournalConflict("narrative event identity collision")
                    return record
            if len(scene["timeline"]) >= 64:
                raise ValueError("fictional timeline capacity reached; explicitly summarize before replacing")
            scene["timeline"].append(normalized)
            scene["timeline"].sort(key=lambda item: (item["occurred_at"], item["event_id"]))
            try:
                return self.put_scene(scope, scene, expected_revision=record["revision"])
            except JournalConflict:
                if expected_revision is not None:
                    raise
        raise JournalConflict("narrative append contention limit reached")

    def set_preference(self, scope, key, value, *, source_id, expected_revision=None):
        """Caller must possess explicit user input; no inferred preferences."""
        key = _id(key, "preference key")
        return self._write("preference", key, scope, {"key": key, "value": _text(value, "preference", 320)},
            source_id, expected_revision=expected_revision)

    def get_preference(self, scope, key):
        return self._read("preference", _id(key, "preference key"), scope)

    def generation(self, scope):
        """Scope-local data revisions fence already-rendered context fragments.

        Capability configuration does not change when an administrator edits a
        scene or preference. Read their persisted revisions under the same
        journal lock, including optional lore/inferences, without retaining or
        returning narrative content. Closing/editing during another provider's
        await therefore invalidates both old fiction and interaction strategy.
        """
        scope = private_scope(scope)
        self._allowed("read", scope)
        namespaces = tuple(sorted(_NS.values()))
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self.journal._db.execute(
                "SELECT namespace,key,revision FROM checkpoints WHERE scope=? "
                "AND namespace IN (?,?,?,?) ORDER BY namespace,key",
                (scope_key(scope), *namespaces)).fetchall()
            result = tuple((row[0], row[1], row[2]) for row in rows)
        self._allowed("read", scope)
        return result

    def set_inference(self, scope, key, text, *, source_id, expires_at, confidence, expected_revision=None):
        key = _id(key, "inference key")
        expires_at = _time(expires_at, "expires_at")
        if not self._now() < expires_at <= self._now() + 86400:
            raise ValueError("inference requires expiry within one day")
        return self._write("inference", key, scope, {"key": key, "text": _text(text, "inference", 320),
            "confidence": self._confidence(confidence)}, source_id, expires_at=expires_at, expected_revision=expected_revision)

    def get_inference(self, scope, key, *, now=None):
        return self._read("inference", _id(key, "inference key"), scope, now=now)

    def import_rolecard(self, scope, payload, *, source_id, expected_revision=None):
        return self._write("persona", "supplement", scope, import_card(payload), source_id,
            expected_revision=expected_revision)

    def get_rolecard(self, scope):
        return self._read("persona", "supplement", scope)

    def render_context(self, scope, query="", max_chars=1600, now=None):
        """Bounded evidence-labelled fragments, never a system prompt replacement."""
        scope = private_scope(scope)
        self._allowed("read", scope)
        if not isinstance(query, str) or len(query) > 16000 or isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 0 <= max_chars <= 8000:
            raise ValueError("invalid narrative context request")
        now = self._now(now)
        sections = []
        used = 0
        def add(identity, label, value, record):
            nonlocal used
            text = label + ": " + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            cost = len(text) + (1 if sections else 0)
            if cost > max_chars - used:
                return
            sections.append({"id": identity, "text": text,
                "evidence_kind": record["data"]["evidence_kind"], "revision": record["revision"],
                "expires_at": record["data"]["expires_at"]})
            used += cost
        scene_record = self.read_scene(scope, now=now)
        if scene_record:
            scene = scene_record["data"]["payload"]
            viewer = scope["character_id"]
            add("narrative.scene", "Fictional scene; not real-world facts", {
                "scene": scene["title"], "shared_summary": scene["summary"][:480]}, scene_record)
            participant = next(item for item in scene["participants"] if item["participant_id"] == viewer)
            if participant["known_facts"]:
                add("narrative.knowledge", "Fiction known to current character only", participant["known_facts"][:4], scene_record)
            visible = [item["text"] for item in scene["timeline"] if viewer in item["known_to"]]
            if visible:
                add("narrative.timeline", "Recent fictional events known to current character", visible[-3:], scene_record)
            arcs = [item["text"] for item in scene["unfinished_arcs"] if viewer in item["known_to"]]
            if arcs:
                add("narrative.arcs", "Unfinished fictional arcs", arcs[:3], scene_record)
        for record in self.journal.list(_NS["preference"], scope, limit=8):
            self._checked(record, "preference", scope)
            add("narrative.preference." + record["data"]["payload"]["key"], "Explicit user preference", record["data"]["payload"], record)
        card_record = self.get_rolecard(scope)
        if card_record:
            card = card_record["data"]["payload"]
            add("narrative.persona", "Optional fictional supplement; core persona unchanged", card["supplemental"], card_record)
            lore = select_worldbook(card, query, max_chars=min(max_chars, 1200))
            if lore:
                add("narrative.worldbook", "Matched fictional worldbook data", [item["content"] for item in lore], card_record)
        # Inferences require a relevant explicit query; they are never facts.
        if query.strip():
            for record in self.journal.list(_NS["inference"], scope, limit=8):
                self._checked(record, "inference", scope)
                payload = record["data"]["payload"]
                if now < record["data"]["expires_at"] and payload["key"].casefold() in query.casefold():
                    add("narrative.inference." + payload["key"], "Unconfirmed model inference, not a user fact", payload, record)
        self._allowed("read", scope)
        return {"text": "\n".join(item["text"] for item in sections), "sections": sections,
            "evidence_kind": "mixed" if len({item["evidence_kind"] for item in sections}) > 1 else (sections[0]["evidence_kind"] if sections else None),
            "revision": scene_record["revision"] if scene_record else None,
            "expires_at": scene_record["data"]["expires_at"] if scene_record else None}
