"""Transactional delivery authority on a *single* authoritative LivingJournal.

The journal's public schema version remains 1. This additive feature has its own
version row. SQLite is local to the authority; never put a SQLite file on a
network share and never give two network-partitioned nodes independent copies.
All worker decisions use the authority clock. Unknown dispatch outcomes are
terminal and keep their frequency reservation: retrying them is unsafe without
a platform-provided idempotency key.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import re
import secrets
import time

from .models import canonical, plain, private_scope, scope_key
from .delivery_types import audio_extension, delivery_policy_hash, delivery_quiet_window, task_input_hash
from .delivery_retention import ArchiveIntegrityError, archived_task, initialize as initialize_retention


class DeliveryConflict(RuntimeError):
    """A stale owner, lease or lifecycle transition was rejected."""


TERMINAL = frozenset({"confirmed", "failed", "unknown", "cancelled", "expired", "quarantined"})
ACTIVE = frozenset({"candidate", "approved", "queued", "claimed", "sending", "retry_wait", "paused"})
_IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _number(value, name, minimum=0, maximum=1e13):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("invalid " + name)
    return float(value)


def _identity(value, name):
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise ValueError("invalid " + name)
    return value


class DeliveryStore:
    """Durable bounded queue with fenced leases and transactional reservations.

    ``claim`` and ``begin`` return ``None`` when there is no eligible work.
    Stale mutation attempts raise DeliveryConflict. Local administrative APIs
    (create/approve/enqueue/control/set_owner) are intentionally separate from
    the restricted worker RPC exposed by delivery_authority.
    """
    supported_queue_versions = (1, 2)

    def _immutable_extension(self, value):
        if 'delivery_lane' in value or 'reminder_binding' in value:
            raise ValueError('dedicated delivery authority required')
        return {}

    def __init__(self, journal, *, clock=time.time, max_tasks=20000, max_active=4096, max_audit=20000):
        self.journal = journal
        self.clock = clock
        self.max_tasks = max(1, min(int(max_tasks), 100000))
        self.max_active = max(1, min(int(max_active), self.max_tasks))
        self.max_audit = max(1, min(int(max_audit), 100000))
        with journal._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_features(name TEXT PRIMARY KEY,version INTEGER NOT NULL)")
            old = db.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()
            if old and old[0] not in self.supported_queue_versions:
                raise ValueError("unsupported delivery schema")
            db.execute("INSERT OR IGNORE INTO tls_delivery_features VALUES('queue',1)")
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_tasks(id TEXT PRIMARY KEY,scope TEXT NOT NULL,state TEXT NOT NULL,priority INTEGER NOT NULL,due REAL NOT NULL,expires REAL NOT NULL,data TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS tls_delivery_ready ON tls_delivery_tasks(state,due,priority DESC)")
            # Additive and readable by the previous implementation: no queue
            # schema bump, row rewrite, retention change or lease shortening.
            db.execute("CREATE INDEX IF NOT EXISTS tls_delivery_expiry ON tls_delivery_tasks(state,expires)")
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_owners(scope TEXT PRIMARY KEY,mode TEXT NOT NULL,generation INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_reservations(task TEXT PRIMARY KEY,scope TEXT NOT NULL,day TEXT NOT NULL,reserved REAL NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS tls_delivery_reservation_scope ON tls_delivery_reservations(scope,day)")
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_activity(scope TEXT PRIMARY KEY,observed REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,task TEXT NOT NULL,occurred REAL NOT NULL,event TEXT NOT NULL,state TEXT NOT NULL,details TEXT NOT NULL)")
            initialize_retention(db)

    def _now(self):
        return _number(self.clock(), "authority clock")

    @contextmanager
    def _read_snapshot(self):
        """One WAL snapshot across archive lookup and ordinary-row fallback.

        Another authority connection may archive/rehydrate between SELECTs.
        A deferred read transaction prevents mistaking that valid transition
        for an orphan, without taking the writer lock on every get().
        """
        with self.journal._lock:
            self.journal._ensure_open()
            db = self.journal._db
            nested = db.in_transaction
            if not nested:
                db.execute('BEGIN')
            try:
                yield db
            except BaseException:
                if not nested and db.in_transaction:
                    db.execute('ROLLBACK')
                raise
            else:
                if not nested:
                    db.execute('COMMIT')

    @staticmethod
    def _task(db, task_id):
        # Administrative/worker mutation must never revive an archived ID.
        # Reading archival history is deliberately separate from execution.
        if db.execute("SELECT 1 FROM tls_delivery_tombstones WHERE task=?", (task_id,)).fetchone():
            raise DeliveryConflict("archived delivery cannot execute")
        row = db.execute("SELECT data,state FROM tls_delivery_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError("delivery task not found")
        if row["state"] == "quarantined":
            raise DeliveryConflict("quarantined delivery cannot execute")
        return json.loads(row[0])

    @staticmethod
    def _owner(db, sk):
        row = db.execute("SELECT mode,generation FROM tls_delivery_owners WHERE scope=?", (sk,)).fetchone()
        if row and (row["mode"] not in {"legacy", "shadow", "tls"} or type(row["generation"]) is not int or row["generation"] < 0):
            raise PermissionError("invalid persisted delivery authority")
        return dict(row) if row else {"mode": "legacy", "generation": 0}

    @staticmethod
    def _save(db, task):
        db.execute("UPDATE tls_delivery_tasks SET state=?,priority=?,due=?,expires=?,data=? WHERE id=?", (task["state"], task["priority"], task["available_at"], task["expires_at"], canonical(task), task["id"]))

    def _audit(self, db, task, event, now, details=None):
        # No message text, media path, scope identity or exception strings.
        db.execute("INSERT INTO tls_delivery_audit(task,occurred,event,state,details) VALUES(?,?,?,?,?)", (task["id"], now, event, task["state"], canonical(details or {})))
        db.execute("DELETE FROM tls_delivery_audit WHERE seq <= (SELECT COALESCE(MAX(seq),0)-? FROM tls_delivery_audit)", (self.max_audit,))

    def create(self, value):
        if not isinstance(value, dict):
            raise ValueError("task must be a mapping")
        task_id = _identity(value.get("id"), "task identity")
        scope = private_scope(value.get("scope"))
        session = value.get("session", scope["session_id"])
        if session != scope["session_id"]:
            raise ValueError("session must match complete scope")
        text = value.get("text", "")
        images = value.get("images", [])
        if not isinstance(text, str) or len(text.encode()) > 16000 or not isinstance(images, list) or len(images) > 1 or any(not isinstance(p, str) or not p or len(p) > 4096 for p in images) or not (text.strip() or images):
            raise ValueError("invalid delivery content")
        created = _number(value.get("created_at"), "creation time")
        due = _number(value.get("due_at", created), "due time")
        expires = _number(value.get("expires_at"), "expiry")
        priority, attempts = value.get("priority", 50), value.get("max_attempts", 3)
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100 or isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
            raise ValueError("invalid delivery limits")
        if value.get("trigger", "event") not in {"event", "timer"} or expires <= created or due < created or due >= expires:
            raise ValueError("invalid delivery timing")
        task = {"id": task_id, "scope": scope, "session": session, "text": text, "images": list(images), "created_at": created, "due_at": due, "expires_at": expires, "priority": priority, "trigger": value.get("trigger", "event"), "max_attempts": attempts}
        task.update(self._immutable_extension(value))
        task.update(audio_extension(value))
        digest = task_input_hash(task)
        task.update(state="candidate", input_hash=digest, available_at=due, attempts=0, epoch=0, approval=None, owner_node=None, token=None, lease_until=None, owner_generation=None)
        now = self._now()
        with self.journal._transaction() as db:
            try:
                archived = archived_task(db, task_id)
            except ArchiveIntegrityError as error:
                raise DeliveryConflict("archived delivery is unavailable") from error
            if archived is not None:
                if archived['input_hash'] != digest:
                    raise DeliveryConflict("task identity content conflict")
                return archived
            old = db.execute("SELECT data FROM tls_delivery_tasks WHERE id=?", (task_id,)).fetchone()
            if old:
                previous = json.loads(old[0])
                if previous["input_hash"] != digest:
                    raise DeliveryConflict("task identity content conflict")
                return previous
            # Tombstone sentinels have their own explicit archive capacity.
            # Their durable IDs remain in the old table to fence old readers.
            total = db.execute("SELECT COUNT(*) FROM tls_delivery_tasks t LEFT JOIN tls_delivery_tombstones x ON x.task=t.id WHERE x.task IS NULL").fetchone()[0]
            active = db.execute("SELECT COUNT(*) FROM tls_delivery_tasks WHERE state NOT IN ('confirmed','failed','unknown','cancelled','expired','quarantined')").fetchone()[0]
            if total >= self.max_tasks or active >= self.max_active:
                raise RuntimeError("delivery retention capacity reached")
            db.execute("INSERT INTO tls_delivery_tasks VALUES(?,?,?,?,?,?,?)", (task_id, scope_key(scope), "candidate", priority, due, expires, canonical(task)))
            self._audit(db, task, "created", now)
        return task

    def get(self, task_id):
        _identity(task_id, "task identity")
        with self._read_snapshot():
            try:
                archived = archived_task(self.journal._db, task_id)
            except ArchiveIntegrityError as error:
                raise DeliveryConflict("archived delivery is unavailable") from error
            if archived is not None:
                return archived
            row = self.journal._db.execute("SELECT id,state,data FROM tls_delivery_tasks WHERE id=?", (task_id,)).fetchone()
            return self._read(row) if row else None

    @staticmethod
    def _read(row):
        if row["state"] == "quarantined":
            return {"id": row["id"], "state": "quarantined", "raw_data_preserved": True}
        return json.loads(row["data"])

    def list_tasks(self, scope=None):
        with self._read_snapshot():
            if scope is None:
                rows = self.journal._db.execute("SELECT id,state,data FROM tls_delivery_tasks ORDER BY id")
            else:
                rows = self.journal._db.execute("SELECT id,state,data FROM tls_delivery_tasks WHERE scope=? ORDER BY id", (scope_key(private_scope(scope)),))
            result = []
            for row in rows:
                try:
                    archived = archived_task(self.journal._db, row['id'])
                except ArchiveIntegrityError as error:
                    raise DeliveryConflict("archived delivery is unavailable") from error
                result.append(archived if archived is not None else self._read(row))
            return result

    def task_counts(self, scope=None):
        """Small diagnostic snapshot without decoding retained message bodies.

        Counts describe durable lifecycle rows, including candidates and
        terminal history; they are not a platform delivery health guarantee.
        No cache or pruning is performed, preserving replay/idempotency data.
        """
        with self.journal._lock:
            self.journal._ensure_open()
            if scope is None:
                rows = self.journal._db.execute("SELECT state,COUNT(*) FROM tls_delivery_tasks GROUP BY state")
            else:
                rows = self.journal._db.execute("SELECT state,COUNT(*) FROM tls_delivery_tasks WHERE scope=? GROUP BY state", (scope_key(private_scope(scope)),))
            return {row[0]: row[1] for row in rows}

    def approve(self, task_id, approval):
        if not isinstance(approval, dict) or approval.get("allowed") is not True or approval.get("native") is not True:
            raise PermissionError("native decision approval required")
        _identity(approval.get("decision_id"), "decision identity")
        if not isinstance(approval.get("policy_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", approval["policy_hash"]):
            raise ValueError("decision policy binding required")
        if 'text_only' in approval and type(approval['text_only']) is not bool:
            raise ValueError('explicit text policy must be boolean')
        approval = plain(approval, 4096)
        now = self._now()
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            if approval.get("input_hash") != task["input_hash"]:
                raise PermissionError("decision input binding mismatch")
            if "scope" in approval and private_scope(approval["scope"]) != task["scope"]:
                raise PermissionError("decision scope mismatch")
            if task.get("decision") is not None and task["decision"] != approval:
                raise DeliveryConflict("recorded candidate decision is immutable")
            if task["state"] in {"approved", "queued"} and task["approval"] == approval:
                return task
            if task["state"] != "candidate":
                raise DeliveryConflict("only candidates may be approved")
            if task["expires_at"] <= now:
                raise DeliveryConflict("candidate expired")
            owner = self._owner(db, scope_key(task["scope"]))
            task.update(state="approved", approval=approval, owner_generation=owner["generation"])
            self._save(db, task)
            self._audit(db, task, "approved", now)
        return task

    def record_decision(self, task_id, decision):
        """Persist a native deny/allow decision without granting execution."""
        if not isinstance(decision, dict) or type(decision.get("allowed")) is not bool or decision.get("native") is not True:
            raise ValueError("native decision record required")
        _identity(decision.get("decision_id"), "decision identity")
        if not isinstance(decision.get("policy_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", decision["policy_hash"]):
            raise ValueError("decision policy binding required")
        if 'text_only' in decision and type(decision['text_only']) is not bool:
            raise ValueError('explicit text policy must be boolean')
        decision = plain(decision, 4096)
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            if task["state"] != "candidate":
                raise DeliveryConflict("only candidates may record a new decision")
            if decision.get("input_hash") != task["input_hash"] or ("scope" in decision and private_scope(decision["scope"]) != task["scope"]):
                raise PermissionError("decision input binding mismatch")
            if task.get("decision") is not None and task["decision"] != decision:
                raise DeliveryConflict("candidate decision is immutable")
            if task.get("decision") == decision:
                return task
            task["decision"] = decision
            self._save(db, task)
            self._audit(db, task, "candidate_decision", self._now(), {"allowed": decision["allowed"]})
        return task

    def enqueue(self, task_id):
        now = self._now()
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            if task["state"] != "approved":
                # Recovery or another worker can advance this already-approved
                # task between approve() and enqueue(). Idempotent admission
                # must preserve that newer state, never lower it to queued or
                # fail a successfully completed submission. A candidate or a
                # paused unapproved candidate is still not an execution grant.
                approval = task.get("approval")
                if (task["state"] in (ACTIVE | TERMINAL) - {"candidate"}
                        and isinstance(approval, dict) and approval.get("allowed") is True
                        and approval.get("native") is True
                        and approval.get("input_hash") == task["input_hash"]
                        and task_input_hash(task) == task["input_hash"]):
                    return task
                raise DeliveryConflict("only approved tasks may be enqueued")
            task["state"] = "expired" if task["expires_at"] <= now else "queued"
            self._save(db, task)
            self._audit(db, task, "enqueued", now)
        return task

    def control(self, task_id, action):
        if action not in {"pause", "resume", "cancel"}:
            raise ValueError("invalid task control")
        now = self._now()
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            if task["state"] in {"sending", "claimed"}:
                raise DeliveryConflict("inflight tasks cannot be paused or cancelled")
            if task["state"] in TERMINAL:
                return task
            if action == "cancel":
                task["state"] = "cancelled"
            elif action == "pause" and task["state"] != "paused":
                task["resume_state"], task["state"] = task["state"], "paused"
            elif action == "resume" and task["state"] == "paused":
                task["state"] = "expired" if task["expires_at"] <= now else task.pop("resume_state", "queued")
            self._save(db, task)
            self._audit(db, task, action, now)
        return task

    def owner(self, scope):
        with self.journal._lock:
            self.journal._ensure_open()
            return self._owner(self.journal._db, scope_key(private_scope(scope)))

    def note_activity(self, scope, observed_at):
        """Trusted inbound adapter records one central, durable high-water mark.

        Not exposed through the worker RPC. A stale node cannot lower this
        timestamp, and a future timestamp is rejected rather than silencing
        accompaniment indefinitely.
        """
        observed_at = _number(observed_at, "activity timestamp")
        now = self._now()
        if observed_at > now + 30:
            raise ValueError("future activity timestamp")
        sk = scope_key(private_scope(scope))
        with self.journal._transaction() as db:
            previous = db.execute("SELECT observed FROM tls_delivery_activity WHERE scope=?", (sk,)).fetchone()
            if previous:
                if previous[0] >= observed_at:
                    return previous[0]
            elif db.execute("SELECT COUNT(*) FROM tls_delivery_activity").fetchone()[0] >= self.journal.max_records:
                raise RuntimeError("delivery activity capacity reached")
            db.execute("INSERT INTO tls_delivery_activity VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET observed=MAX(observed,excluded.observed)", (sk, observed_at))
            self._audit(db, {"id": "activity:" + sk, "state": "updated"}, "activity_high_water", now)
        return observed_at

    def activity(self,scope):
        """Read the genuine inbound high-water mark; does not renew it."""
        with self.journal._lock:
            self.journal._ensure_open()
            row=self.journal._db.execute('SELECT observed FROM tls_delivery_activity WHERE scope=?',
                (scope_key(private_scope(scope)),)).fetchone()
            return row[0] if row else 0

    def set_owner(self, scope, mode, expected_generation):
        if mode not in {"legacy", "shadow", "tls"} or isinstance(expected_generation, bool) or not isinstance(expected_generation, int):
            raise ValueError("invalid delivery ownership")
        sk = scope_key(private_scope(scope))
        with self.journal._transaction() as db:
            previous = self._owner(db, sk)
            if previous["generation"] != expected_generation:
                raise DeliveryConflict("delivery ownership generation conflict")
            if previous["mode"] == mode:
                return previous
            if db.execute("SELECT 1 FROM tls_delivery_tasks WHERE scope=? AND state IN ('claimed','sending') LIMIT 1", (sk,)).fetchone():
                raise DeliveryConflict("inflight task blocks ownership switch")
            generation = expected_generation + 1
            if previous["generation"] == 0 and db.execute("SELECT COUNT(*) FROM tls_delivery_owners").fetchone()[0] >= self.journal.max_records:
                raise RuntimeError("delivery ownership capacity reached")
            db.execute("INSERT INTO tls_delivery_owners VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET mode=excluded.mode,generation=excluded.generation", (sk, mode, generation))
            self._audit(db, {"id": "owner:" + sk, "state": mode}, "owner_changed", self._now(), {"generation": generation, "previous_mode": previous["mode"]})
            # Queued work is generation bound and must not silently acquire a new
            # execution owner. Administrators cancel and re-propose if needed.
            return {"mode": mode, "generation": generation}

    def _recover(self, db, now, *, claim_only=False):
        changed = {"requeued": 0, "enqueued": 0, "unknown": 0, "expired": 0, "quarantined": 0}
        if claim_only:
            # Frequent idle polls must not JSON-decode and hash every rejected
            # candidate or future/paused task. Such rows cannot execute. Keep
            # a full integrity sweep in public recover(); here validate every
            # row that can transition or become executable in this transaction.
            # The UNION arms are disjoint and use state/due/expiry indexes.
            rows = db.execute("""SELECT * FROM tls_delivery_tasks
                WHERE state IN ('approved','claimed','sending')
                UNION ALL SELECT * FROM tls_delivery_tasks
                WHERE state IN ('candidate','queued','retry_wait','paused') AND expires<=?
                UNION ALL SELECT * FROM tls_delivery_tasks
                WHERE state IN ('queued','retry_wait') AND due<=? AND expires>?""", (now, now, now)).fetchall()
        else:
            rows = db.execute("SELECT * FROM tls_delivery_tasks WHERE state NOT IN ('confirmed','failed','unknown','cancelled','expired','quarantined')").fetchall()
        for row in rows:
            try:
                task = json.loads(row["data"])
                self._immutable_extension(task)
                if not isinstance(task, dict) or not ACTIVE.issuperset({task["state"]}) or task["state"] != row["state"] or task["id"] != row["id"] or scope_key(private_scope(task["scope"])) != row["scope"] or task_input_hash(task) != task["input_hash"] or task["priority"] != row["priority"] or task["available_at"] != row["due"] or task["expires_at"] != row["expires"]:
                    raise ValueError("invalid persisted binding")
                for key in ("expires_at", "available_at", "created_at"):
                    _number(task[key], key)
                # These mutable fields are deliberately outside input_hash.
                # Validate them before claim can increment or compare them: a
                # malformed high-priority row must not roll back every claim.
                if (type(task["epoch"]) is not int or task["epoch"] < 0
                        or type(task["max_attempts"]) is not int or not 1 <= task["max_attempts"] <= 5
                        or type(task["attempts"]) is not int or not 0 <= task["attempts"] <= task["max_attempts"]):
                    raise ValueError("invalid persisted delivery counters")
                effective_state = task["state"]
                if effective_state == "paused":
                    effective_state = task["resume_state"]
                    if effective_state not in {"candidate", "approved", "queued", "retry_wait"}:
                        raise ValueError("invalid paused resume state")
                if task["state"] in {"claimed", "sending"}:
                    _number(task["lease_until"], "lease expiry")
                    _identity(task["owner_node"], "worker identity")
                    if not isinstance(task["token"], str) or not re.fullmatch(r"[0-9a-f]{48}", task["token"]) or task["epoch"] < 1:
                        raise ValueError("missing lease token")
                if effective_state != "candidate":
                    if type(task["owner_generation"]) is not int or task["owner_generation"] < 0:
                        raise ValueError("invalid persisted owner generation")
                    approval = task["approval"]
                    if not isinstance(approval, dict) or approval.get("allowed") is not True or approval.get("native") is not True or approval.get("input_hash") != task["input_hash"]:
                        raise ValueError("invalid persisted approval")
                    _identity(approval.get("decision_id"), "decision identity")
                    if not isinstance(approval.get("policy_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", approval["policy_hash"]):
                        raise ValueError("invalid persisted approval policy binding")
                    if 'text_only' in approval and type(approval['text_only']) is not bool:
                        raise ValueError('invalid persisted text policy')
                    if "scope" in approval and private_scope(approval["scope"]) != task["scope"]:
                        raise ValueError("invalid persisted approval scope binding")
                    if task.get("decision") is not None and task["decision"] != approval:
                        raise ValueError("persisted decision and approval disagree")
                elif task["approval"] is not None or task["owner_generation"] is not None:
                    raise ValueError("unapproved candidate contains execution authority")
            except (ValueError, TypeError, KeyError, OverflowError):
                # Preserve exact raw bytes and any existing reservation. A bad
                # task must not poison recovery of unrelated valid tasks.
                db.execute("UPDATE tls_delivery_tasks SET state='quarantined' WHERE id=?", (row["id"],))
                self._audit(db, {"id": row["id"], "state": "quarantined"}, "corrupt_task_quarantined", now, {"code": "invalid_persisted_task"})
                changed["quarantined"] += 1
                continue
            if task["state"] == "sending" and task["lease_until"] <= now:
                task["state"] = "unknown"
                changed["unknown"] += 1
            elif task["state"] == "claimed" and task["lease_until"] <= now:
                task["state"] = "expired" if task["expires_at"] <= now else "queued"
                task.update(owner_node=None, token=None, lease_until=None)
                changed["expired" if task["state"] == "expired" else "requeued"] += 1
            elif task["state"] not in {"claimed", "sending"} and task["expires_at"] <= now:
                task["state"] = "expired"
                changed["expired"] += 1
            elif task["state"] == "approved":
                # A crash between durable approval and enqueue must not strand
                # valid work forever. Candidate decisions alone are not grants.
                task["state"] = "queued"
                changed["enqueued"] += 1
            else:
                continue
            self._save(db, task)
            self._audit(db, task, "recovered", now)
        return changed

    def recover(self):
        with self.journal._transaction() as db:
            return self._recover(db, self._now())

    def claim(self, node, lease_seconds=30):
        _identity(node, "worker identity")
        lease_seconds = _number(lease_seconds, "lease duration", 1, 300)
        now = self._now()
        with self.journal._transaction() as db:
            self._recover(db, now, claim_only=True)
            # Stream in priority order; an eligible first task should not
            # allocate decoded copies of the entire ready queue on each poll.
            rows = db.execute("SELECT data FROM tls_delivery_tasks WHERE state IN ('queued','retry_wait') AND due<=? AND expires>? ORDER BY priority DESC,due,id", (now, now))
            for row in rows:
                task = json.loads(row[0])
                owner = self._owner(db, scope_key(task["scope"]))
                if owner["mode"] != "tls" or owner["generation"] != task["owner_generation"]:
                    continue
                task.update(state="claimed", owner_node=node, token=secrets.token_hex(24), lease_until=now + lease_seconds, epoch=task["epoch"] + 1)
                self._save(db, task)
                self._audit(db, task, "claimed", now, {"epoch": task["epoch"]})
                return task
        return None

    @staticmethod
    def _fence(task, node, token, now):
        if task["owner_node"] != node or not isinstance(token, str) or not isinstance(task.get("token"), str) or not secrets.compare_digest(task["token"], token) or task["lease_until"] <= now:
            raise DeliveryConflict("delivery lease is stale")

    @staticmethod
    def _minutes(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("invalid quiet time")
        h, m = map(int, value.split(":"))
        return h * 60 + m

    @classmethod
    def _policy(cls, value, now):
        if not isinstance(value, dict):
            raise ValueError("delivery policy is required")
        limit = value.get("daily_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 100:
            raise ValueError("invalid daily limit")
        interval = _number(value.get("min_interval_seconds"), "minimum interval", 0, 604800)
        recent = _number(value.get("recent_chat_seconds", 0), "recent chat interval", 0, 86400)
        last_activity = _number(value.get("last_activity_at", 0), "last activity")
        if last_activity > now + 30:
            raise ValueError("future activity timestamp")
        offset = value.get("tz_offset_minutes", 480)
        if isinstance(offset, bool) or not isinstance(offset, int) or not -840 <= offset <= 840:
            raise ValueError("invalid timezone offset")
        require_image = value.get("require_image", True)
        if type(require_image) is not bool:
            raise ValueError("invalid media requirement")
        local = datetime.fromtimestamp(now, timezone(timedelta(minutes=offset)))
        quiet = delivery_quiet_window(value,now)
        return {"day": local.date().isoformat(), "limit": limit, "interval": interval, "activity_until": last_activity + recent, "recent_chat_seconds": recent, **quiet, "require_image": require_image, "next_day": (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()}

    @staticmethod
    def _counters(db, sk, day):
        row = db.execute("SELECT COUNT(*),MAX(reserved) FROM tls_delivery_reservations WHERE scope=? AND day=?", (sk, day)).fetchone()
        last = db.execute("SELECT MAX(reserved) FROM tls_delivery_reservations WHERE scope=?", (sk,)).fetchone()[0]
        return {"sent_today": row[0], "last_sent": last or 0}

    def counters(self, scope, day):
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("invalid counter day")
        with self.journal._lock:
            self.journal._ensure_open()
            return self._counters(self.journal._db, scope_key(private_scope(scope)), day)

    def begin(self, task_id, node, token, policy):
        now = self._now()
        policy_hash = delivery_policy_hash(policy)
        input_policy = policy
        policy = self._policy(policy, now)
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            self._fence(task, node, token, now)
            if task["state"] != "claimed":
                raise DeliveryConflict("only claimed tasks may begin")
            sk = scope_key(task["scope"])
            owner = self._owner(db, sk)
            if owner["mode"] != "tls" or owner["generation"] != task["owner_generation"]:
                raise DeliveryConflict("execution authority changed")
            approval = task["approval"]
            if not approval or approval.get("allowed") is not True or approval.get("native") is not True or approval.get("input_hash") != task["input_hash"] or task_input_hash(task) != task["input_hash"]:
                raise PermissionError("native approval binding is invalid")
            if approval.get("policy_hash") != policy_hash:
                raise PermissionError("approved delivery policy changed")
            activity = db.execute("SELECT observed FROM tls_delivery_activity WHERE scope=?", (sk,)).fetchone()
            if activity:
                policy["activity_until"] = max(policy["activity_until"], activity[0] + policy["recent_chat_seconds"])
            if task["expires_at"] <= now:
                task["state"] = "expired"
                self._save(db, task)
                self._audit(db, task, "expired_before_dispatch", now)
                return None
            # Exact native approval/input/policy bindings above remain
            # mandatory. A scope or an empty image list alone grants nothing.
            if policy["require_image"] and not task["images"] and approval.get('text_only') is not True:
                task["state"] = "failed"
                self._save(db, task)
                self._audit(db, task, "image_required", now)
                return None
            usage = self._counters(db, sk, policy["day"])
            defer = max(now, policy["quiet_until"], policy["activity_until"], usage["last_sent"] + policy["interval"] if usage["last_sent"] else now)
            if usage["sent_today"] >= policy["limit"]:
                defer = max(defer, policy["next_day"])
            if input_policy.get('quiet_hours'):
                defer = max(defer,delivery_quiet_window(input_policy,defer)['quiet_until'])
            if policy["quiet_all_day"]:
                defer = task["expires_at"]
            if defer > now:
                task.update(state="queued" if defer < task["expires_at"] else "expired", available_at=defer, owner_node=None, token=None, lease_until=None)
                self._save(db, task)
                self._audit(db, task, "policy_deferred", now)
                return None
            if task["attempts"] >= task["max_attempts"]:
                task["state"] = "failed"
                self._save(db, task)
                self._audit(db, task, "attempts_exhausted", now)
                return None
            db.execute("INSERT INTO tls_delivery_reservations(task,scope,day,reserved) VALUES(?,?,?,?)", (task_id, sk, policy["day"], now))
            task.update(state="sending", attempts=task["attempts"] + 1, reserved_day=policy["day"], dispatch_started_at=now)
            self._save(db, task)
            self._audit(db, task, "dispatch_reserved", now, {"attempt": task["attempts"], "epoch": task["epoch"]})
        return task

    def defer(self, task_id, node, token, available_at, code="frequency_gate"):
        """Recheck a temporary decision later without consuming send attempts."""
        now = self._now()
        available_at = _number(available_at, "deferred availability")
        if available_at <= now or not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", code):
            raise ValueError("invalid delivery deferral")
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            self._fence(task, node, token, now)
            if task["state"] != "claimed":
                raise DeliveryConflict("only unstarted claims may defer")
            task.update(state="queued" if available_at < task["expires_at"] else "expired", available_at=available_at, owner_node=None, token=None, lease_until=None)
            self._save(db, task)
            self._audit(db, task, "decision_deferred", now, {"code": code})
        return task

    def finish(self, task_id, node, token, outcome, code=""):
        if outcome not in {"confirmed", "retryable", "failed", "unknown"}:
            raise ValueError("invalid delivery outcome")
        if not isinstance(code, str) or len(code) > 80 or (code and not re.fullmatch(r"[A-Za-z0-9_.:-]+", code)):
            raise ValueError("outcome code must be a technical identifier")
        now = self._now()
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            self._fence(task, node, token, now)
            if task["state"] not in {"claimed", "sending"}:
                raise DeliveryConflict("only inflight tasks may finish")
            if task["state"] == "claimed":
                if outcome not in {"retryable", "failed"}:
                    raise DeliveryConflict("unstarted tasks cannot be confirmed or unknown")
                task["attempts"] += 1
            if outcome == "confirmed":
                db.execute("UPDATE tls_delivery_reservations SET confirmed=1 WHERE task=?", (task_id,))
                task["state"] = "confirmed"
            elif outcome == "unknown":
                task["state"] = "unknown"
            else:
                # These outcomes mean the platform was definitely not invoked /
                # did not accept a message. Callers must never classify a generic
                # timeout or connection drop after dispatch as retryable.
                db.execute("DELETE FROM tls_delivery_reservations WHERE task=?", (task_id,))
                retry_at = now + min(300, 2 ** min(task["attempts"], 8))
                if outcome == "retryable" and task["attempts"] < task["max_attempts"] and retry_at < task["expires_at"]:
                    task.update(state="retry_wait", available_at=retry_at)
                else:
                    task["state"] = "failed"
            task["result_code"] = code
            self._save(db, task)
            self._audit(db, task, "dispatch_result", now, {"outcome": outcome, "code": code})
        return task

    def audit(self, task_id):
        with self._read_snapshot():
            from .delivery_retention import _decode
            try:
                archived = _decode(self.journal._db, task_id)
            except ArchiveIntegrityError as error:
                raise DeliveryConflict("archived delivery is unavailable") from error
            if archived is not None:
                rows = {row['seq']: dict(seq=row['seq'], occurred=row['occurred'], event=row['event'], state=row['state'], details=json.loads(row['details'])) for row in archived['audit']}
                for row in self.journal._db.execute("SELECT seq,occurred,event,state,details FROM tls_delivery_audit WHERE task=? ORDER BY seq", (task_id,)):
                    current = dict(row, details=json.loads(row['details']))
                    if row['seq'] in rows and rows[row['seq']] != current:
                        raise DeliveryConflict("archived audit identity conflict")
                    rows[row['seq']] = current
                return [rows[key] for key in sorted(rows)]
            return [dict(row, details=json.loads(row["details"])) for row in self.journal._db.execute("SELECT seq,occurred,event,state,details FROM tls_delivery_audit WHERE task=? ORDER BY seq", (task_id,))]

    def health(self):
        with self.journal._lock:
            self.journal._ensure_open()
            self.journal._db.execute("SELECT 1").fetchone()
        return {"ok": True, "feature": "tls.delivery.v1", "schema_version": 1}
