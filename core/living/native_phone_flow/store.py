"""SQLite preferences and transactional coordination for proactive messages.

Only explicit preferences, session identifiers, event keys, and delivery times
are stored. Message bodies and model inputs never enter this database.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from .policy import validate_preferences, validate_umo


LEASE_SECONDS = 60.0
DEDUPE_SECONDS = 24 * 60 * 60.0


def _timestamp(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name}必须为有限非负数字")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{name}必须为有限非负数字") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name}必须为有限非负数字")
    return result


def _event_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(unicodedata.category(ch) == "Cc" for ch in value)
    ):
        raise ValueError("事件标识必须是最多 256 字符的非空文本，且不能含控制字符")
    return value


class PreferenceStore:
    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            PRAGMA busy_timeout = 15000;
            CREATE TABLE IF NOT EXISTS preferences (
                umo TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proactive_clock (
                umo TEXT PRIMARY KEY,
                last_sent REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proactive_events (
                umo TEXT NOT NULL,
                event_key TEXT NOT NULL,
                sent_at REAL NOT NULL,
                PRIMARY KEY (umo, event_key)
            );
            CREATE INDEX IF NOT EXISTS idx_proactive_events_sent
                ON proactive_events(sent_at);
            CREATE TABLE IF NOT EXISTS proactive_leases (
                umo TEXT PRIMARY KEY,
                lease TEXT NOT NULL UNIQUE,
                event_key TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("聊天偏好存储已关闭")

    def _read(self, umo: str) -> dict:
        row = self._db.execute(
            "SELECT value FROM preferences WHERE umo = ?", (umo,)
        ).fetchone()
        return {} if row is None else validate_preferences(json.loads(row["value"]))

    def get(self, umo: str) -> dict:
        umo = validate_umo(umo)
        with self._lock:
            self._ensure_open()
            return self._read(umo)

    def put(self, umo: str, patch: dict) -> dict:
        umo = validate_umo(umo)
        patch = validate_preferences(patch)
        with self._lock:
            self._ensure_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                merged = self._read(umo)
                merged.update(patch)
                payload = json.dumps(merged, ensure_ascii=False, allow_nan=False)
                self._db.execute(
                    """INSERT INTO preferences (umo, value, updated_at)
                    VALUES (?, ?, ?) ON CONFLICT(umo) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at""",
                    (umo, payload, time.time()),
                )
                self._db.commit()
                return dict(merged)
            except BaseException:
                self._db.rollback()
                raise

    def clear(self, umo: str) -> None:
        umo = validate_umo(umo)
        with self._lock:
            self._ensure_open()
            with self._db:
                self._db.execute("DELETE FROM preferences WHERE umo = ?", (umo,))

    def list_sessions(self, limit: int = 200) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit必须为 1–1000 的整数")
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT umo, value, updated_at FROM preferences ORDER BY updated_at DESC, umo LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "umo": row["umo"],
                    "preferences": validate_preferences(json.loads(row["value"])),
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    def reserve_proactive(
        self,
        umo: str,
        event_key: str,
        now: float,
        cooldown_seconds: float,
    ) -> dict:
        """Atomically reserve delivery, without performing any network send.

        Callers must use a stable event key identifying an occurrence, not the
        message text, and call finish_proactive after delivery completes.
        """
        umo = validate_umo(umo)
        event_key = _event_key(event_key)
        now = _timestamp(now, "now")
        cooldown_seconds = _timestamp(cooldown_seconds, "cooldown_seconds")
        with self._lock:
            self._ensure_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "DELETE FROM proactive_events WHERE sent_at <= ?",
                    (now - DEDUPE_SECONDS,),
                )
                self._db.execute(
                    "DELETE FROM proactive_leases WHERE expires_at <= ?", (now,)
                )
                preferences = self._read(umo)
                reason = None
                if preferences.get("quiet_until", 0) > now:
                    reason = "quiet"
                elif self._db.execute(
                    "SELECT 1 FROM proactive_events WHERE umo = ? AND event_key = ?",
                    (umo, event_key),
                ).fetchone():
                    reason = "duplicate"
                else:
                    clock = self._db.execute(
                        "SELECT last_sent FROM proactive_clock WHERE umo = ?", (umo,)
                    ).fetchone()
                    if (
                        clock is not None
                        and now < clock["last_sent"] + cooldown_seconds
                    ):
                        reason = "cooldown"
                    elif self._db.execute(
                        "SELECT 1 FROM proactive_leases WHERE umo = ?", (umo,)
                    ).fetchone():
                        reason = "in_flight"
                if reason is not None:
                    self._db.commit()
                    return {"allowed": False, "reason": reason, "lease": None}
                lease = uuid.uuid4().hex
                self._db.execute(
                    "INSERT INTO proactive_leases (umo, lease, event_key, expires_at) VALUES (?, ?, ?, ?)",
                    (umo, lease, event_key, now + LEASE_SECONDS),
                )
                self._db.commit()
                return {"allowed": True, "reason": "allowed", "lease": lease}
            except BaseException:
                self._db.rollback()
                raise

    def finish_proactive(self, lease: str, success: bool, now: float) -> bool:
        """Release ownership and record successful sends only.

        A replaced lease cannot finish. An owner that still exists may finish
        after its nominal expiry, provided no newer reservation replaced it.
        This reduces duplicates after a slow but successful delivery.
        """
        if not isinstance(lease, str) or not _valid_lease(lease):
            raise ValueError("无效的主动消息租约")
        if type(success) is not bool:
            raise ValueError("success必须为布尔值")
        now = _timestamp(now, "now")
        with self._lock:
            self._ensure_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute(
                    "SELECT umo, event_key FROM proactive_leases WHERE lease = ?",
                    (lease,),
                ).fetchone()
                if row is None:
                    self._db.commit()
                    return False
                if success:
                    self._db.execute(
                        """INSERT INTO proactive_clock (umo, last_sent) VALUES (?, ?)
                        ON CONFLICT(umo) DO UPDATE SET
                        last_sent = MAX(last_sent, excluded.last_sent)""",
                        (row["umo"], now),
                    )
                    self._db.execute(
                        """INSERT INTO proactive_events (umo, event_key, sent_at) VALUES (?, ?, ?)
                        ON CONFLICT(umo, event_key) DO UPDATE SET
                        sent_at = MAX(sent_at, excluded.sent_at)""",
                        (row["umo"], row["event_key"], now),
                    )
                self._db.execute(
                    "DELETE FROM proactive_leases WHERE lease = ?", (lease,)
                )
                self._db.commit()
                return True
            except BaseException:
                self._db.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True


def _valid_lease(value: str) -> bool:
    return len(value) == 32 and all(ch in "0123456789abcdef" for ch in value)
