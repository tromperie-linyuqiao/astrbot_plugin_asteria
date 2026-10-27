"""Non-destructive typed narrative snapshots for isolated staging only.

This does not migrate arbitrary legacy databases or activate production. A
fresh destination becomes a ready artifact only after full validation. Source
files and existing destinations are never removed, replaced, or rewritten.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid

from .journal import LivingJournal
from .models import plain, private_scope, scope_key
from .narrative import NarrativeStore


_SCHEMA = "tls.narrative.snapshot.v1"
_NAMESPACES = {"scene": "tls.narrative.scene", "preference": "tls.narrative.preference",
               "inference": "tls.narrative.inference", "persona": "tls.narrative.persona"}
_KINDS = {"scene": "roleplay_event", "preference": "user_reported", "inference": "model_inference", "persona": "roleplay_event"}
_MAX_BYTES = 2 * 1024 * 1024
_MAX_RECORDS = 128
_READY = "READY.json"
_INACTIVE = "ROLLED_BACK.json"
_DB = "narrative.sqlite"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _time(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid migration timestamp")
    return float(value)


def _authority(authorize, scope):
    if not callable(authorize):
        raise TypeError("migration authorization must be callable")
    if authorize("write", dict(scope)) is not True:
        raise PermissionError("narrative migration authority denied")


def _unlinked_directory(path):
    """Reject linked ancestors before resolving a destination or reading it.

    This is a filesystem boundary check, not a claim of protection from an OS
    user racing directory replacements outside the isolated staging contract.
    """
    absolute = Path(path).absolute()
    for item in (absolute, *absolute.parents):
        if item.is_symlink() or (callable(getattr(item, "is_junction", None)) and item.is_junction()):
            raise ValueError("linked staging paths are not allowed")
    return absolute


def _pairs(items):
    value = {}
    for key, child in items:
        if key in value:
            raise ValueError("duplicate migration JSON key")
        value[key] = child
    return value


def _load(path, limit=_MAX_BYTES):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("invalid migration artifact file")
    try:
        return plain(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs), limit)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError("corrupt migration artifact JSON") from exc


def _write_new(path, value):
    # Exclusive creation is intentional: never replace even a partial artifact.
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(_json(value))
        output.write("\n")


def export_snapshot(store, scope):
    """Read one consistent private-scope snapshot without source writes."""
    scope = private_scope(scope)
    store._allowed("read", scope)
    records = []
    # Existing transaction lock also fences other SQLite connections while the
    # four namespaces are read. This transaction contains SELECT statements only.
    with store.journal._transaction():
        for kind, namespace in _NAMESPACES.items():
            rows = store.journal.list(namespace, scope, limit=_MAX_RECORDS + 1)
            if len(rows) + len(records) > _MAX_RECORDS:
                raise ValueError("narrative snapshot record capacity exceeded")
            for record in rows:
                store._checked(record, kind, scope)
                data = record["data"]
                item = {"kind": kind, "key": record["key"], "expected_source_revision": record["revision"],
                    "recorded_at": data["updated_at"], "source_id": data["source_id"],
                    "evidence_kind": data["evidence_kind"], "expires_at": data["expires_at"],
                    "payload": data["payload"]}
                item["content_hash"] = _hash(item)
                records.append(item)
        store._allowed("read", scope)
    body = {"schema": _SCHEMA, "source_schema_version": 1, "scope": scope, "scope_hash": scope_key(scope),
        "captured_at": _time(store.clock()), "records": sorted(records, key=lambda item: (item["kind"], item["key"]))}
    body["snapshot_hash"] = _hash(body)
    return plain(body, _MAX_BYTES)


def _validated_envelope(snapshot, now):
    value = plain(snapshot, _MAX_BYTES)
    expected = {"schema", "source_schema_version", "scope", "scope_hash", "captured_at", "records", "snapshot_hash"}
    if not isinstance(value, dict) or set(value) != expected or value["schema"] != _SCHEMA or type(value["source_schema_version"]) is not int or value["source_schema_version"] != 1:
        raise ValueError("unsupported narrative snapshot")
    scope = private_scope(value["scope"])
    if scope != value["scope"] or value["scope_hash"] != scope_key(scope):
        raise ValueError("snapshot scope binding mismatch")
    captured = _time(value["captured_at"])
    if captured > now + 30:
        raise ValueError("snapshot captured in the future")
    body = {key: child for key, child in value.items() if key != "snapshot_hash"}
    if value["snapshot_hash"] != _hash(body):
        raise ValueError("snapshot content hash mismatch")
    records = value["records"]
    if not isinstance(records, list) or len(records) > _MAX_RECORDS:
        raise ValueError("invalid narrative snapshot record count")
    identities = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"kind", "key", "expected_source_revision", "recorded_at", "source_id", "evidence_kind", "expires_at", "payload", "content_hash"}:
            raise ValueError("invalid narrative snapshot record")
        kind = record["kind"]
        if not isinstance(kind, str) or kind not in _NAMESPACES or record["evidence_kind"] != _KINDS[kind]:
            raise ValueError("snapshot evidence kind mismatch")
        if not isinstance(record["key"], str) or not record["key"] or len(record["key"]) > 256:
            raise ValueError("invalid snapshot record key")
        identity = (kind, record["key"])
        if identity in identities:
            raise ValueError("duplicate snapshot identity")
        identities.add(identity)
        revision = record["expected_source_revision"]
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid snapshot source revision")
        if _time(record["recorded_at"]) > captured + 30:
            raise ValueError("snapshot record follows capture")
        if record["content_hash"] != _hash({key: child for key, child in record.items() if key != "content_hash"}):
            raise ValueError("snapshot record hash mismatch")
    return value


def _apply_record(store, scope, record):
    kind, payload = record["kind"], record["payload"]
    common = {"source_id": record["source_id"], "expected_revision": 0}
    if kind == "scene":
        if not isinstance(payload, dict) or payload.get("scene_id") != record["key"] or payload.get("source_id") != record["source_id"] or payload.get("expires_at") != record["expires_at"]:
            raise ValueError("snapshot scene binding mismatch")
        result = store.put_scene(scope, payload, expected_revision=0)
    elif kind == "persona":
        if record["key"] != "supplement" or record["expires_at"] is not None:
            raise ValueError("snapshot persona binding mismatch")
        result = store.import_rolecard(scope, payload.get("original") if isinstance(payload, dict) else None, **common)
    elif kind == "preference":
        if not isinstance(payload, dict) or payload.get("key") != record["key"] or record["expires_at"] is not None:
            raise ValueError("snapshot preference binding mismatch")
        result = store.set_preference(scope, record["key"], payload.get("value"), **common)
    else:
        if not isinstance(payload, dict) or payload.get("key") != record["key"]:
            raise ValueError("snapshot inference binding mismatch")
        result = store.set_inference(scope, record["key"], payload.get("text"),
            expires_at=record["expires_at"], confidence=payload.get("confidence"), **common)
    if result["data"]["payload"] != payload or result["data"]["expires_at"] != record["expires_at"]:
        raise ValueError("snapshot normalization changed payload")
    return {"namespace": _NAMESPACES[kind], "key": record["key"], "target_revision": result["revision"],
        "source_revision": record["expected_source_revision"], "data_hash": _hash(result["data"])}


def validate_snapshot(snapshot, *, authorize, clock=time.time):
    """Full scratch replay before any destination file/directory is created."""
    value = _validated_envelope(snapshot, _time(clock()))
    _authority(authorize, value["scope"])
    replay_clock = [value["captured_at"]]
    journal = LivingJournal(":memory:", clock=lambda: replay_clock[0])
    store = NarrativeStore(journal, authorize=authorize, clock=lambda: replay_clock[0])
    try:
        fingerprints = []
        for record in value["records"]:
            replay_clock[0] = record["recorded_at"]
            fingerprints.append(_apply_record(store, value["scope"], record))
        _authority(authorize, value["scope"])
        return {"valid": True, "snapshot_hash": value["snapshot_hash"], "scope_hash": value["scope_hash"],
            "record_count": len(value["records"]), "records": fingerprints}
    finally:
        journal.close()


def stage_snapshot(snapshot, *, target_directory, authorize, clock=time.time, environment):
    """Create a new isolated immutable staging artifact; never activate runtime."""
    if environment != "isolated":
        raise PermissionError("narrative staging is restricted to isolated environments")
    value = _validated_envelope(snapshot, _time(clock()))
    _authority(authorize, value["scope"])
    validation = validate_snapshot(value, authorize=authorize, clock=clock)
    target = _unlinked_directory(target_directory)
    if not target.parent.is_dir():
        raise ValueError("invalid staging destination")
    _authority(authorize, value["scope"])
    target.mkdir(exist_ok=False)
    replay_clock = [value["captured_at"]]
    journal = None
    try:
        _write_new(target / "SOURCE_SNAPSHOT.json", value)
        journal = LivingJournal(target / _DB, clock=lambda: replay_clock[0])
        store = NarrativeStore(journal, authorize=authorize, clock=lambda: replay_clock[0])
        fingerprints = []
        for record in value["records"]:
            replay_clock[0] = record["recorded_at"]
            fingerprints.append(_apply_record(store, value["scope"], record))
        if fingerprints != validation["records"]:
            raise ValueError("staging replay differs from validation")
        _authority(authorize, value["scope"])
        journal.close()
        journal = None
        receipt = {"schema": "tls.narrative.stage.v1", "receipt_id": uuid.uuid4().hex,
            "snapshot_hash": value["snapshot_hash"], "scope_hash": value["scope_hash"],
            "record_count": len(fingerprints), "records": fingerprints, "production_activation": False}
        receipt["receipt_hash"] = _hash(receipt)
        _write_new(target / _READY, receipt)
        inspect_stage(target)
        _authority(authorize, value["scope"])
        return receipt
    except BaseException:
        if journal is not None:
            journal.close()
        # Technical marker only, no raw exception strings or source content.
        if not (target / "FAILED.json").exists():
            _write_new(target / "FAILED.json", {"status": "unready", "production_activation": False})
        raise


def inspect_stage(target_directory):
    """Read-only integrity inspection; rejects partial/modified artifacts."""
    target = _unlinked_directory(target_directory)
    if (target / "FAILED.json").exists():
        raise ValueError("staging artifact is unready")
    receipt = _load(target / _READY)
    expected = {"schema", "receipt_id", "snapshot_hash", "scope_hash", "record_count", "records", "production_activation", "receipt_hash"}
    if not isinstance(receipt, dict) or set(receipt) != expected or receipt["schema"] != "tls.narrative.stage.v1" or receipt["production_activation"] is not False:
        raise ValueError("invalid staging receipt")
    if receipt["receipt_hash"] != _hash({key: child for key, child in receipt.items() if key != "receipt_hash"}):
        raise ValueError("staging receipt hash mismatch")
    if (type(receipt["record_count"]) is not int or not 0 <= receipt["record_count"] <= _MAX_RECORDS
            or not isinstance(receipt["records"], list) or not isinstance(receipt["receipt_id"], str)
            or len(receipt["receipt_id"]) != 32 or any(char not in "0123456789abcdef" for char in receipt["receipt_id"])):
        raise ValueError("invalid staging receipt metadata")
    source = _load(target / "SOURCE_SNAPSHOT.json")
    if not isinstance(source, dict) or source.get("snapshot_hash") != receipt["snapshot_hash"] or source.get("scope_hash") != receipt["scope_hash"]:
        raise ValueError("staging source binding mismatch")
    validation = validate_snapshot(source, authorize=lambda *_: True, clock=lambda: _time(source.get("captured_at")))
    if receipt["records"] != validation["records"]:
        raise ValueError("staging receipt differs from source replay")
    if receipt["record_count"] != len(receipt["records"]) or receipt["record_count"] != len(source["records"]):
        raise ValueError("staging record count mismatch")
    path = target / _DB
    if path.is_symlink() or not path.is_file() or any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("invalid staging database")
    # Published staging databases are closed/checkpointed artifacts. Immutable
    # inspection must not create WAL/SHM files or ignore a pending WAL above.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("unsupported staging database version")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected_tables = {"observations", "checkpoints", "audit", "resource_usage", "resource_reservations", "sqlite_sequence"}
        if tables != expected_tables or db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]:
            raise ValueError("unexpected staging database table family")
        for table in ("observations", "audit", "resource_usage", "resource_reservations", "sqlite_sequence"):
            if db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]:
                raise ValueError("unexpected unrelated staging data")
        count = db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        if count != receipt["record_count"]:
            raise ValueError("staging target was modified")
        for row in receipt["records"]:
            actual = db.execute("SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?",
                (row["namespace"], row["key"], receipt["scope_hash"])).fetchone()
            if actual is None or actual[0] != row["target_revision"] or _hash(json.loads(actual[1])) != row["data_hash"]:
                raise ValueError("staging target was modified")
    finally:
        db.close()
    inactive = (target / _INACTIVE).exists()
    if inactive:
        marker = _load(target / _INACTIVE, 4096)
        if marker != {"receipt_id": receipt["receipt_id"], "receipt_hash": receipt["receipt_hash"], "status": "inactive", "data_deleted": False}:
            raise ValueError("invalid staging rollback marker")
    return {"status": "inactive" if inactive else "ready", "receipt_id": receipt["receipt_id"],
        "receipt_hash": receipt["receipt_hash"], "record_count": count,
        "snapshot_hash": receipt["snapshot_hash"], "production_activation": False}


def rollback_stage(target_directory, *, receipt_id):
    """Retire only an unchanged staging artifact. Preserve all imported bytes."""
    target = _unlinked_directory(target_directory)
    state = inspect_stage(target)
    if receipt_id != state["receipt_id"]:
        raise ValueError("rollback receipt does not match staging artifact")
    if state["status"] == "inactive":
        return state
    _write_new(target / _INACTIVE, {"receipt_id": receipt_id, "receipt_hash": state["receipt_hash"],
        "status": "inactive", "data_deleted": False})
    return inspect_stage(target)
