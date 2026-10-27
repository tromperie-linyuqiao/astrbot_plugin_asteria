"""Explicit, local migration of MC memory rows into the native memory store.

Snapshots contain private source data. Preview/receipts deliberately omit source
text, paths, actor identifiers and raw exception messages. Nothing opens a legacy
plugin, initializes its schema, calls a model, or activates production runtime.
"""
from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .models import plain, private_scope, scope_key
from .journal import JournalConflict


SNAPSHOT_SCHEMA = "tls.native_memory.legacy_snapshot.v1"
RECEIPT_SCHEMA = "tls.native_memory.migration_receipt.v1"
_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$")
_IDENTITY_KEYS = {"platform", "scope", "session_id", "owner_bot_id", "persona_id"}
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ROWS = 100000
_EVIDENCE = {"real_observation", "user_reported", "model_inference", "roleplay_event", "action_result"}
_REALITY = {
    "observed_utterance": "user_reported", "explicit_user_statement": "user_reported",
    "real_user_fact": "user_reported", "historical_evidence": "user_reported",
    "external_observation": "real_observation", "bot_action": "action_result",
    "llm_summary": "model_inference", "llm_tool_assertion": "model_inference",
    "imported_summary": "model_inference", "model_inference": "model_inference",
    "persona_life": "roleplay_event", "roleplay_event": "roleplay_event",
    "simulated": "roleplay_event", "roleplay": "roleplay_event",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _identifier(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid " + name)
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate migration JSON key")
        result[key] = value
    return result


def _parse(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _: _invalid_json())
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid migration JSON") from exc


def _invalid_json():
    raise ValueError("non-finite migration JSON")


def _time(value, *, optional=False):
    if value in (None, "") and optional:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid migration time")
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("migration time needs timezone")
            value = parsed.timestamp()
    if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise ValueError("invalid migration time")
    return float(value)


def _object(value, *, default=None):
    if value in (None, "") and default is not None:
        return default
    if isinstance(value, str):
        value = _parse(value)
    if not isinstance(value, dict):
        raise ValueError("invalid legacy metadata")
    return value


def _snapshot(source, records, inventory, captured_at):
    value = {"schema": SNAPSHOT_SCHEMA, "source": source, "captured_at": _time(captured_at),
             "records": records, "inventory": inventory}
    value["snapshot_hash"] = _hash(value)
    return _validate_snapshot(value)


def _validate_snapshot(snapshot):
    value = plain(snapshot, _MAX_BYTES)
    if (not isinstance(value, dict) or set(value) != {
            "schema", "source", "captured_at", "records", "inventory", "snapshot_hash"}
            or value["schema"] != SNAPSHOT_SCHEMA):
        raise ValueError("unsupported legacy snapshot")
    if value["snapshot_hash"] != _hash({k: v for k, v in value.items() if k != "snapshot_hash"}):
        raise ValueError("legacy snapshot hash mismatch")
    source = value["source"]
    if not isinstance(source, dict) or source.get("format") not in {"mc.sqlite", "astrbot-memory-jsonl.v1"}:
        raise ValueError("unsupported legacy source")
    _identifier(source.get("source_id"), "legacy source identity")
    _time(value["captured_at"])
    records = value["records"]
    if not isinstance(records, list) or len(records) > _MAX_ROWS:
        raise ValueError("invalid legacy record count")
    seen = set()
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("legacy record requires exact identity")
        if row["id"] in seen:
            raise ValueError("duplicate legacy record identity")
        seen.add(row["id"])
    if not isinstance(value["inventory"], list):
        raise ValueError("invalid legacy inventory")
    for table in value["inventory"]:
        if (not isinstance(table, dict) or not isinstance(table.get("name"), str)
                or type(table.get("count")) is not int or table["count"] < 0
                or table.get("disposition") not in {"memory_rows", "retained_source_only"}):
            raise ValueError("invalid legacy inventory table")
    return value


def read_legacy_sqlite(path, *, source_id, clock=time.time):
    """Read a consistent SQLite backup through a mode=ro source connection.

    Use a closed recovery copy for a file-level guarantee including WAL/SHM.
    SQLite may maintain shared-memory locks when reading a live WAL database.
    The source receives no schema initialization, DDL, DML, or checkpoint.
    """
    _identifier(source_id, "legacy source identity")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("legacy database not found")
    source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    copy = sqlite3.connect(":memory:")
    copy.row_factory = sqlite3.Row
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(copy)
        tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "memories" not in tables:
            raise ValueError("legacy MC memories table is missing")
        # Constant names below; no source-controlled SQL identifier interpolation.
        columns = [row[1] for row in copy.execute("PRAGMA table_info(memories)")]
        if not {"id", "content", "memory_type", "scope", "session_id", "metadata"} <= set(columns):
            raise ValueError("unsupported legacy MC memories schema")
        if copy.execute("SELECT COUNT(*) FROM memories").fetchone()[0] > _MAX_ROWS:
            raise ValueError("legacy record capacity exceeded")
        rows = [dict(row) for row in copy.execute("SELECT * FROM memories ORDER BY id")]
        inventory = []
        for table in sorted(tables):
            quoted = '"' + table.replace('"', '""') + '"'
            count = copy.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
            inventory.append({"name": table, "count": count,
                              "disposition": "memory_rows" if table == "memories" else "retained_source_only"})
        schema = None
        if "schema_metadata" in tables:
            meta_columns = {row[1] for row in copy.execute("PRAGMA table_info(schema_metadata)")}
            if {"key", "value"} <= meta_columns:
                row = copy.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()
                schema = row[0] if row else None
        return _snapshot({"source_id": source_id, "format": "mc.sqlite", "schema_version": schema,
                          "memory_columns": columns}, rows, inventory, clock())
    except sqlite3.DatabaseError as exc:
        raise ValueError("legacy SQLite snapshot read failed") from exc
    finally:
        copy.close()
        source.close()


def read_legacy_json(path, *, source_id=None, clock=time.time):
    """Read our JSON snapshot or the actual MC portable JSONL v1 envelope.

    Portable archives omit newer safety columns; preview reports these missing
    states instead of recreating them with active/approved defaults.
    """
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_BYTES:
        raise ValueError("invalid legacy JSON artifact")
    raw = path.read_text(encoding="utf-8-sig")
    try:
        value = _parse(raw)
    except ValueError:
        value = None
    if isinstance(value, dict) and value.get("schema") == SNAPSHOT_SCHEMA:
        snapshot = _validate_snapshot(value)
        if source_id is not None and snapshot["source"]["source_id"] != source_id:
            raise ValueError("legacy source identity mismatch")
        return snapshot
    _identifier(source_id, "legacy source identity")
    items = [_parse(line) for line in raw.splitlines() if line.strip()]
    if not items or any(not isinstance(item, dict) for item in items):
        raise ValueError("invalid legacy portable archive")
    header = items.pop(0)
    if (header.get("record_type") != "header" or header.get("format") != "astrbot-memory-jsonl"
            or type(header.get("version")) is not int or header["version"] != 1):
        raise ValueError("unsupported legacy portable archive")
    counts = Counter()
    rows = []
    for item in items:
        if set(item) != {"record_type", "data"} or not isinstance(item["data"], dict):
            raise ValueError("invalid legacy portable record")
        kind = item["record_type"]
        if kind not in {"memory", "identity", "relationship", "timeline", "acl_rule", "acl_policy"}:
            raise ValueError("unsupported legacy portable record kind")
        counts[kind] += 1
        if kind == "memory":
            rows.append(item["data"])
    declared = header.get("counts")
    if not isinstance(declared, dict):
        raise ValueError("legacy portable counts missing")
    for kind in set(declared) | set(counts):
        if type(declared.get(kind)) is not int or declared[kind] < 0 or declared[kind] != counts[kind]:
            raise ValueError("legacy portable count mismatch")
    inventory = [{"name": kind, "count": count,
                  "disposition": "memory_rows" if kind == "memory" else "retained_source_only"}
                 for kind, count in sorted(declared.items())]
    return _snapshot({"source_id": source_id, "format": "astrbot-memory-jsonl.v1", "schema_version": 1,
                      "exported_at": header.get("exported_at"), "excluded": header.get("excluded", [])},
                     rows, inventory, clock())


def export_snapshot(snapshot, path):
    """Create a new PRIVATE JSON artifact, never overwrite an existing file."""
    value = _validate_snapshot(snapshot)
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_json(value) + "\n")
    return {"snapshot_hash": value["snapshot_hash"], "record_count": len(value["records"])}


def legacy_identity(row):
    """Exact session selector, without inference from display names/actors."""
    meta = _object(row.get("metadata"), default={})
    return {"platform": row.get("platform", ""), "scope": row.get("scope", ""),
            "session_id": row.get("session_id", ""),
            "owner_bot_id": row.get("owner_bot_id") or meta.get("owner_bot_id", ""),
            "persona_id": row.get("persona_id") or meta.get("persona_id", "")}


def _mappings(mappings):
    if not isinstance(mappings, list):
        raise ValueError("explicit migration mappings must be a list")
    result = []
    for item in mappings:
        if not isinstance(item, dict) or set(item) not in ({"record_id", "scope"}, {"identity", "scope"}):
            raise ValueError("invalid explicit migration mapping")
        scope = private_scope(item["scope"])
        if "record_id" in item:
            if not isinstance(item["record_id"], str) or not item["record_id"]:
                raise ValueError("mapping requires exact legacy record id")
            result.append({"record_id": item["record_id"], "scope": scope})
        else:
            identity = item["identity"]
            if (not isinstance(identity, dict) or set(identity) != _IDENTITY_KEYS
                    or any(not isinstance(value, str) for value in identity.values())
                    or not identity["session_id"]):
                raise ValueError("mapping requires exact complete legacy session identity")
            result.append({"identity": dict(identity), "scope": scope})
    return result


def _actors(row):
    for name in ("subject", "object"):
        actor = row.get(name)
        if isinstance(actor, dict):
            yield actor
        else:
            yield {key: row.get(name + "_" + key, "") for key in ("kind", "id", "role", "name")}


def _ownership(row, meta, scope):
    # A mapping fills missing ownership; it never overwrites explicit ownership.
    constraints = {
        "platform": [row.get("platform"), meta.get("platform")],
        "bot_id": [row.get("owner_bot_id"), meta.get("owner_bot_id"), meta.get("bot_id")],
        "character_id": [row.get("persona_id"), meta.get("persona_id"), meta.get("character_id")],
        "session_id": [row.get("session_id"), meta.get("session_id")],
        "user_id": [meta.get("user_id"), meta.get("sender_id")],
    }
    session = row.get("session_id", "")
    # Match only the exact token formats used by legacy identity.py; no suffix,
    # fuzzy name, or arbitrary session parsing is used to grant ownership.
    if isinstance(session, str):
        tokens = (":friendmessage:", ":privatemessage:", ":friend:", ":private:")
        for token in tokens:
            index = session.lower().rfind(token)
            if index >= 0:
                constraints["user_id"].append(session[index + len(token):])
                break
    for actor in _actors(row):
        if actor.get("kind") == "user" and actor.get("role") in {"current_sender", "current_private_user"}:
            constraints["user_id"].append(actor.get("id"))
        # Importing third-party personal records under the current user's scope
        # would turn an actor identity into ownership. Keep them in the source.
        if actor.get("kind") == "user" and actor.get("id") and actor["id"] != scope["user_id"]:
            return "third_party_actor"
    for key, values in constraints.items():
        if any(value not in (None, "") and (not isinstance(value, str) or value != scope[key]) for value in values):
            return "source_ownership_conflict"
    return None


def _evidence(row, meta):
    derived = _REALITY.get(row.get("reality_level"))
    declarations = [meta[key] for key in ("evidence_kind", "provenance_classification") if meta.get(key) is not None]
    if any(declaration not in _EVIDENCE for declaration in declarations):
        raise ValueError("unrecognized_evidence")
    if derived is None:
        if not declarations:
            raise ValueError("unrecognized_evidence")
        derived = declarations[0]
    # Negative proof always wins; no source inference or fiction is upgraded.
    if (derived == "roleplay_event" or "roleplay_event" in declarations
            or meta.get("claim_domain") in {"roleplay", "persona_life", "simulated"}):
        return "roleplay_event"
    if (derived == "model_inference" or "model_inference" in declarations
            or meta.get("extraction_quality") == "inferred"):
        return "model_inference"
    if any(declaration != derived for declaration in declarations):
        raise ValueError("conflicting_evidence")
    return derived


def _score(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid_score")
    return float(value)


def _record_plan(snapshot, row, mappings, now, batch_id):
    meta = _object(row.get("metadata"), default={})
    identity = legacy_identity(row)
    choices = [mapping["scope"] for mapping in mappings if mapping.get("record_id") == row["id"]
               or ("identity" in mapping and mapping["identity"] == identity)]
    unique = {scope_key(scope): scope for scope in choices}
    if not unique:
        raise ValueError("missing_scope_mapping")
    if len(unique) != 1:
        raise ValueError("ambiguous_scope_mapping")
    scope = next(iter(unique.values()))
    if row.get("scope") != "private" or row.get("group_id") or meta.get("scope") not in (None, "", "private"):
        raise ValueError("non_private_source")
    conflict = _ownership(row, meta, scope)
    if conflict:
        raise ValueError(conflict)
    states = {key: row.get(key) or meta.get(key) for key in
              ("validity_status", "review_status", "lifecycle", "visibility", "sensitivity", "sayability")}
    if any(row.get(key) not in (None, "") and meta.get(key) not in (None, "")
           and row[key] != meta[key] for key in states):
        raise ValueError("conflicting_source_safety_state")
    if any(value is None or value == "" for value in states.values()):
        raise ValueError("missing_source_safety_state")
    if states["validity_status"] != "active":
        raise ValueError("retained_inactive_source")
    if states["review_status"] not in {"auto", "approved", "confirmed", "manual"}:
        raise ValueError("retained_unreviewed_source")
    if states["lifecycle"] not in {"stable_memory", "raw_event", "open_loop"}:
        raise ValueError("retained_source_lifecycle")
    if states["visibility"] != "private_pair" or states["sensitivity"] not in {"public", "private"}:
        raise ValueError("retained_private_visibility_policy")
    if states["sayability"] != "direct":
        raise ValueError("retained_expression_policy")
    if meta.get("mention_policy", "") not in {"", "direct", "soft_echo"}:
        raise ValueError("retained_expression_policy")
    if meta.get("profile_state", "active") != "active" or meta.get("quality_gate_passed") is False:
        raise ValueError("retained_unreviewed_source")
    tags = row.get("tags", [])
    if isinstance(tags, str):
        tags = _parse(tags)
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("invalid_tags")
    if meta.get("claim_domain") == "system_catalog_metadata" or "catalog_metadata_only" in tags:
        raise ValueError("retained_catalog_data")
    if (row.get("memory_type") in {"user_profile", "user_preference", "user_habit"}
            and states["review_status"] not in {"approved", "confirmed", "manual"}):
        raise ValueError("retained_profile_review_proof")
    occurred = _time(row.get("occurred_at") or row.get("created_at"), optional=True)
    if occurred is None:
        raise ValueError("missing_source_time")
    since_values = [_time(value, optional=True) for value in (row.get("valid_from"), meta.get("valid_from"))]
    since = max([value for value in since_values if value is not None], default=None)
    until_values = [_time(value, optional=True) for value in (row.get("valid_to"), meta.get("valid_to"))]
    until = min([value for value in until_values if value is not None], default=None)
    expiry_values = [_time(value, optional=True) for value in (row.get("expires_at"), meta.get("expires_at"))]
    expiry = min([value for value in expiry_values if value is not None], default=None)
    expires = min([v for v in (until, expiry) if v is not None], default=None)
    if (occurred is not None and occurred > now or since is not None and since > now):
        raise ValueError("retained_future_source")
    if expires is not None and (expires <= now or occurred is not None and expires <= occurred):
        raise ValueError("retained_expired_source")
    if since is not None and until is not None and until <= since:
        raise ValueError("invalid_validity_window")
    content = row.get("content")
    if (not isinstance(content, str) or not content.strip() or content != content.strip() or len(content) > 6000
            or any(ord(ch) < 32 and ch not in "\t\r\n" for ch in content)):
        raise ValueError("invalid_content")
    memory_type = _identifier(row.get("memory_type"), "memory type")
    if row.get("reality_level") in {"observed_utterance", "historical_evidence"}:
        # The native API expresses a historical utterance through this type.
        # Retaining the old type at the top level would cause NativeMemoryStore
        # to render it as real_user_fact and lose the original speech boundary.
        # The exact original type/reality remain in metadata.legacy.row below.
        memory_type = "utterance"
    evidence_kind = _evidence(row, meta)
    canonical_key = row.get("canonical_key", "")
    if not isinstance(canonical_key, str) or len(canonical_key) > 240:
        raise ValueError("invalid_canonical_key")
    source_id = snapshot["source"]["source_id"]
    identity_hash = _hash([source_id, row["id"], scope_key(scope)])
    metadata = {"legacy": {"source_ref": _hash(source_id), "record_ref": _hash(row["id"]),
                "row_hash": _hash(row), "snapshot_hash": snapshot["snapshot_hash"],
                "batch_id": batch_id, "row": row}, "sayability": states["sayability"],
                "mention_policy": meta.get("mention_policy", ""), "evidence_kind": evidence_kind}
    plain(metadata, 16384)
    return {"scope": scope, "record_id": "mc_" + identity_hash, "event_id": "mc_event_" + identity_hash,
            "content": content, "source_id": "legacy_mc_migration", "evidence_kind": evidence_kind,
            "memory_type": memory_type, "canonical_key": canonical_key,
            "confidence": _score(row.get("confidence")), "importance": _score(row.get("importance")),
            "occurred_at": occurred, "expires_at": expires, "metadata": metadata}


def _plans(snapshot, mappings, *, now, batch_id):
    value = _validate_snapshot(snapshot)
    mappings = _mappings(mappings)
    plans, reports = [], []
    # Only fixed reason codes reach a preview. A legacy malformed JSON value or
    # database exception can itself contain private text, so never echo it.
    reasons = {"missing_scope_mapping", "ambiguous_scope_mapping", "non_private_source", "third_party_actor",
               "source_ownership_conflict", "missing_source_safety_state", "retained_inactive_source",
               "retained_unreviewed_source", "retained_source_lifecycle", "retained_private_visibility_policy",
               "retained_expression_policy", "retained_future_source", "retained_expired_source",
               "invalid_validity_window", "invalid_content", "unrecognized_evidence", "conflicting_evidence",
               "invalid_score", "invalid_canonical_key", "missing_source_time", "retained_profile_review_proof",
               "conflicting_source_safety_state", "invalid_tags", "retained_catalog_data"}
    for row in value["records"]:
        report = {"record_ref": _hash(row["id"])}
        try:
            plan = _record_plan(value, row, mappings, _time(now), batch_id)
            plans.append(plan)
            report.update(status="ready", evidence_kind=plan["evidence_kind"], scope_ref=scope_key(plan["scope"]))
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            reason = str(exc) if str(exc) in reasons else "invalid_or_oversized_source_record"
            report.update(status="retained", reason=reason)
        reports.append(report)
    counts = Counter(item.get("reason", item["status"]) for item in reports)
    report = {"snapshot_hash": value["snapshot_hash"], "source_ref": _hash(value["source"]["source_id"]),
              "record_count": len(reports), "ready": len(plans), "retained": len(reports) - len(plans),
              "counts": dict(counts), "records": reports,
              "retained_tables": [item for item in value["inventory"] if item["disposition"] == "retained_source_only"],
              "production_activation": False}
    return value, plans, report


def preview(snapshot, mappings, *, clock=time.time):
    """Read-only, private-content-free ownership and eligibility report."""
    return _plans(snapshot, mappings, now=clock(), batch_id="preview")[2]


def _receipt(value):
    value["receipt_hash"] = _hash({k: v for k, v in value.items() if k != "receipt_hash"})
    return value


class MigrationApplyError(RuntimeError):
    """Public message is fixed; .receipt describes safely recoverable writes."""
    def __init__(self, receipt):
        super().__init__("native memory migration failed; inspect private receipt")
        self.receipt = receipt


def _same_import(current, plan):
    legacy = current.get("metadata", {}).get("legacy", {})
    return (legacy.get("source_ref") == plan["metadata"]["legacy"]["source_ref"]
            and legacy.get("record_ref") == plan["metadata"]["legacy"]["record_ref"]
            and legacy.get("row_hash") == plan["metadata"]["legacy"]["row_hash"])


def apply(snapshot, mappings, store, *, batch_id, allow_apply=False, clock=time.time):
    """Explicitly import eligible rows. Never overwrite an existing target row.

    NativeMemoryStore.transaction makes the batch atomic. The fallback supports
    API-compatible stores with per-row transactions, returning an exception's
    receipt for partial writes. Receipts are private because rollback needs scope.
    """
    if allow_apply is not True:
        raise PermissionError("explicit native migration apply required")
    _identifier(batch_id, "migration batch identity")
    value, plans, report = _plans(snapshot, mappings, now=clock(), batch_id=batch_id)
    atomic = callable(getattr(store, "transaction", None))
    receipt = {"schema": RECEIPT_SCHEMA, "batch_id": batch_id, "snapshot_hash": value["snapshot_hash"],
               "source_ref": report["source_ref"], "status": "applying", "atomic": atomic,
               "created": [], "duplicates": [], "retained": report["retained"], "production_activation": False}
    try:
        with store.transaction() if atomic else nullcontext():
            for plan in plans:
                current = store.get(plan["scope"], plan["record_id"], include_deleted=True)
                if current is not None:
                    if not _same_import(current, plan):
                        raise JournalConflict("legacy target identity already exists")
                    # A later correction/deletion remains authoritative; rerun
                    # never restores old content or revives a deleted record.
                    receipt["duplicates"].append({"record_ref": plan["metadata"]["legacy"]["record_ref"],
                                                  "record_id": plan["record_id"]})
                    continue
                written = store.write(plan["scope"], plan["content"], **{
                    key: child for key, child in plan.items() if key not in {"scope", "content"}})
                if not _same_import(written, plan) or written.get("revision") != 1:
                    raise JournalConflict("migration write receipt mismatch")
                receipt["created"].append({"scope": plan["scope"], "record_id": written["id"],
                    "target_revision": written["revision"], "target_hash": _hash(written),
                    "record_ref": plan["metadata"]["legacy"]["record_ref"]})
        receipt["status"] = "applied"
        return _receipt(receipt)
    except Exception:
        receipt["status"] = "failed_atomic" if atomic else "failed_partial"
        if atomic:
            receipt["created"] = []
        # Avoid an unhandled traceback echoing a provider/database exception
        # containing a source value. Recovery information is in the receipt.
        raise MigrationApplyError(_receipt(receipt)) from None


def recover_receipt(store, scopes, *, batch_id, snapshot_hash, source_ref):
    """Recover a lost PRIVATE receipt from native metadata and version history.

    Callers must supply the exact private scopes and source/snapshot hashes.
    There is no global cross-user scan. Later changes are not altered and retain
    their original revision-1 hashes, so rollback still reports those conflicts.
    """
    _identifier(batch_id, "migration batch identity")
    for digest in (snapshot_hash, source_ref):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid migration recovery binding")
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("explicit migration recovery scopes required")
    normalized = {scope_key(private_scope(scope)): private_scope(scope) for scope in scopes}
    result = {"schema": RECEIPT_SCHEMA, "batch_id": batch_id, "snapshot_hash": snapshot_hash,
              "source_ref": source_ref, "status": "applied", "atomic": True,
              "created": [], "duplicates": [], "retained": 0, "production_activation": False}
    scanned = 0
    with store.transaction():
        for scope in normalized.values():
            offset = 0
            while True:
                rows = store.list(scope, limit=500, offset=offset, include_deleted=True)
                scanned += len(rows)
                if scanned > _MAX_ROWS:
                    raise ValueError("migration recovery scan capacity exceeded")
                for row in rows:
                    legacy = row.get("metadata", {}).get("legacy", {})
                    if (legacy.get("batch_id") != batch_id or legacy.get("snapshot_hash") != snapshot_hash
                            or legacy.get("source_ref") != source_ref):
                        continue
                    original = row
                    if row.get("revision") != 1:
                        history = store.history(scope, row["id"])
                        original = next((item.get("record") for item in history if item.get("revision") == 1), None)
                    if not isinstance(original, dict) or original.get("metadata", {}).get("legacy") != legacy:
                        raise ValueError("migration original history binding mismatch")
                    result["created"].append({"scope": scope, "record_id": row["id"], "target_revision": 1,
                        "target_hash": _hash(original), "record_ref": legacy["record_ref"]})
                offset += len(rows)
                if len(rows) < 500:
                    break
    result["created"].sort(key=lambda item: (scope_key(item["scope"]), item["record_id"]))
    return _receipt(result)


def rollback(store, receipt, *, allow_rollback=False):
    """Soft-delete only unchanged rows created by this exact migration batch.

    Conflicts are reported and left untouched. Repeated rollback is idempotent;
    already-deleted unchanged originals are counted without another write.
    """
    if allow_rollback is not True:
        raise PermissionError("explicit native migration rollback required")
    value = plain(receipt, _MAX_BYTES)
    if (not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA
            or value.get("status") not in {"applied", "failed_partial", "failed_atomic"}
            or value.get("receipt_hash") != _hash({k: v for k, v in value.items() if k != "receipt_hash"})):
        raise ValueError("invalid native migration receipt")
    _identifier(value.get("batch_id"), "migration batch identity")
    created = value.get("created")
    if not isinstance(created, list):
        raise ValueError("invalid native migration receipt records")
    checked = []
    seen = set()
    for item in created:
        if (not isinstance(item, dict) or set(item) != {"scope", "record_id", "target_revision", "target_hash", "record_ref"}
                or type(item["target_revision"]) is not int or item["target_revision"] != 1):
            raise ValueError("invalid native migration receipt record")
        scope = private_scope(item["scope"])
        key = (scope_key(scope), _identifier(item["record_id"], "migration target identity"))
        if key in seen:
            raise ValueError("duplicate migration receipt target")
        seen.add(key)
        checked.append((item, scope))
    result = {"batch_id": value["batch_id"], "deleted": 0, "already_deleted": 0, "conflicts": [],
              "production_activation": False}
    with store.transaction() if callable(getattr(store, "transaction", None)) else nullcontext():
        for item, scope in checked:
            current = store.get(scope, item["record_id"], include_deleted=True)
            legacy = (current or {}).get("metadata", {}).get("legacy", {})
            if (current is None or legacy.get("batch_id") != value["batch_id"]
                    or legacy.get("source_ref") != value["source_ref"]
                    or legacy.get("record_ref") != item["record_ref"]
                    or legacy.get("snapshot_hash") != value["snapshot_hash"]):
                result["conflicts"].append(item["record_ref"])
                continue
            if current.get("lifecycle") == "deleted" and current.get("revision") == item["target_revision"] + 1:
                # A deletion is already effective; verify its exact prior row.
                # This does not attribute a deletion to the rollback operation.
                history = store.history(scope, item["record_id"])
                prior = next((row.get("record") for row in history
                              if row.get("revision") == item["target_revision"]), None)
                if prior is not None and _hash(prior) == item["target_hash"]:
                    result["already_deleted"] += 1
                    continue
            if current.get("revision") != item["target_revision"] or _hash(current) != item["target_hash"]:
                result["conflicts"].append(item["record_ref"])
                continue
            try:
                store.delete(scope, item["record_id"], expected_revision=item["target_revision"])
            except JournalConflict:
                result["conflicts"].append(item["record_ref"])
                continue
            result["deleted"] += 1
    return result
