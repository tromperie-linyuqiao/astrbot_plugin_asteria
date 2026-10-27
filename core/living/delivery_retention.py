"""Explicit, reversible local delivery archival; never a background deletion job.

Full terminal records and their *currently retained* audit are compressed in the
same authoritative SQLite transaction.  A small terminal sentinel remains in
the old table as a fail-closed guard for already-open old readers.  Durable
tombstones are never expired: idempotency is not a cache TTL.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

from .models import canonical


class ArchiveIntegrityError(RuntimeError):
    """No execution or reconstruction is permitted from invalid archive bytes."""


_SAFE = frozenset({'confirmed', 'failed', 'cancelled', 'expired'})
_MAX_RECORD = 2 * 1024 * 1024
_MAX_COMPRESSED = _MAX_RECORD + 65536


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_tombstones(task TEXT PRIMARY KEY,input_hash TEXT NOT NULL,state TEXT NOT NULL,scope_hash TEXT NOT NULL,archived REAL NOT NULL,archive_hash TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS tls_delivery_archives(task TEXT PRIMARY KEY,raw_bytes INTEGER NOT NULL,audit_rows INTEGER NOT NULL,body BLOB NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS tls_delivery_audit_task ON tls_delivery_audit(task,occurred)")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _marked(data, prefix):
    if isinstance(prefix, bytes):
        prefix = prefix.decode('utf8', errors='ignore')
    marked = str(prefix or '').startswith('{"archived":true,')
    if data is not None:
        try:
            value = json.loads(data)
            marked = marked or isinstance(value, dict) and value.get('archived') is True
        except (ValueError, TypeError, RecursionError):
            pass
    return marked


def _check_orphan_sentinels(db):
    # A count comparison alone misses loss of *both* archive and tombstone.
    # Stream bounded markers, never full dormant message bodies.
    rows = db.execute("""SELECT CASE WHEN LENGTH(q.data)<=1024 THEN q.data END AS data,
        SUBSTR(q.data,1,128) AS prefix FROM tls_delivery_tasks q
        LEFT JOIN tls_delivery_tombstones t ON t.task=q.id
        LEFT JOIN tls_delivery_archives a ON a.task=q.id
        WHERE t.task IS NULL OR a.task IS NULL""")
    for row in rows:
        if _marked(row['data'], row['prefix']):
            raise ArchiveIntegrityError('orphan delivery archive sentinel')


def _decode(db, task_id):
    # Evaluate envelope/length bounds inside SQLite, *before* copying a BLOB
    # into Python. Anchor on the requested identity so orphan links are not
    # silently mistaken for ordinary, unarchived tasks.
    row = db.execute("""SELECT t.*,a.task AS archive_task,a.raw_bytes,a.audit_rows,
        CASE WHEN TYPEOF(a.body)='blob' THEN LENGTH(a.body) END AS body_bytes,
        CASE WHEN t.task IS NOT NULL AND TYPEOF(a.raw_bytes)='integer'
          AND a.raw_bytes BETWEEN 1 AND ? AND TYPEOF(a.body)='blob'
          AND LENGTH(a.body)<=? THEN a.body END AS body,
        q.id AS sentinel_id,q.scope AS sentinel_scope,q.state AS sentinel_state,
        q.priority AS sentinel_priority,q.due AS sentinel_due,q.expires AS sentinel_expires,
        CASE WHEN LENGTH(q.data)<=1024 THEN q.data END AS sentinel_data,
        SUBSTR(q.data,1,128) AS sentinel_prefix
        FROM (SELECT ? AS identity) k
        LEFT JOIN tls_delivery_tombstones t ON t.task=k.identity
        LEFT JOIN tls_delivery_archives a ON a.task=k.identity
        LEFT JOIN tls_delivery_tasks q ON q.id=k.identity""", (_MAX_RECORD, _MAX_COMPRESSED, task_id)).fetchone()
    try:
        if row['task'] is None:
            if row['archive_task'] is not None or _marked(row['sentinel_data'], row['sentinel_prefix']):
                raise ValueError('orphan delivery archive identity')
            return None
        if row['state'] not in _SAFE or type(row['raw_bytes']) is not int or not 0 < row['raw_bytes'] <= _MAX_RECORD:
            raise ValueError('invalid archive envelope')
        if type(row['body_bytes']) is not int or not 0 < row['body_bytes'] <= _MAX_COMPRESSED or not isinstance(row['body'], bytes):
            raise ValueError('invalid compressed archive envelope')
        decoder = zlib.decompressobj()
        raw = decoder.decompress(row['body'], row['raw_bytes'] + 1)
        if len(raw) != row['raw_bytes'] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or _digest(raw) != row['archive_hash']:
            raise ValueError('invalid archive body')
        payload = json.loads(raw)
        task_row = payload['row']
        task = json.loads(task_row['data'])
        from .delivery_types import task_input_hash
        from .models import private_scope, scope_key
        if (payload['version'] != 1 or task_row['id'] != task_id or task['id'] != task_id
                or task_row['state'] != row['state'] or task['state'] != row['state']
                or task_input_hash(task) != row['input_hash'] or task['input_hash'] != row['input_hash']
                or task_row['scope'] != scope_key(private_scope(task['scope']))
                or task_row['priority'] != task['priority'] or task_row['due'] != task['available_at'] or task_row['expires'] != task['expires_at']
                or _digest(task_row['scope'].encode()) != row['scope_hash']
                or len(payload['audit']) != row['audit_rows']):
            raise ValueError('archive binding mismatch')
        expected = canonical({'id': task_id, 'state': row['state'], 'input_hash': row['input_hash'], 'archived': True})
        if (row['sentinel_data'] != expected
                or any(row['sentinel_' + key] != task_row[key] for key in ('id','scope','state','priority','due','expires'))):
            raise ValueError('archive sentinel binding mismatch')
        return payload
    except (ValueError, TypeError, KeyError, OverflowError, zlib.error, UnicodeError, RecursionError) as error:
        raise ArchiveIntegrityError('delivery archive integrity failed') from error


def archived_task(db, task_id):
    payload = _decode(db, task_id)
    return json.loads(payload['row']['data']) if payload else None


@dataclass(frozen=True)
class RetentionPolicy:
    minimum_age_seconds: float = 7 * 86400
    maximum_batch: int = 100
    maximum_batch_bytes: int = 4 * 1024 * 1024
    maximum_archive_rows: int = 100000
    maximum_archive_bytes: int = 256 * 1024 * 1024

    def __post_init__(self):
        if isinstance(self.minimum_age_seconds, bool) or not isinstance(self.minimum_age_seconds, (int, float)) or not math.isfinite(self.minimum_age_seconds) or not 60 <= self.minimum_age_seconds <= 10 * 365 * 86400:
            raise ValueError('invalid archive age')
        for name, low, high in [('maximum_batch', 1, 500), ('maximum_batch_bytes', 1024, 16 * 1024 * 1024), ('maximum_archive_rows', 1, 1000000), ('maximum_archive_bytes', 1024, 2 * 1024 ** 3)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('invalid ' + name)


class DeliveryRetention:
    """Explicit maintenance API, deliberately absent from worker RPC.

    New readers accept queue v1/v2.  Actual archive commits v2; old constructors
    reject v2.  A legacy process opened before that commit still sees terminal
    sentinels and cannot recreate or dispatch an archived identity.
    """
    def __init__(self, store, *, policy=None):
        self.store = store
        self.journal = store.journal
        with self.journal._lock:
            feature=self.journal._db.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()
            if feature is None or feature[0] not in (1, 2):
                raise ValueError('retention requires companion queue schema 1 or 2')
        self.policy = policy or RetentionPolicy()

    @staticmethod
    def _maintenance(db):
        feature=db.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()
        if feature is None or feature[0] not in (1, 2):
            raise ValueError('retention requires companion queue schema 1 or 2')
        if db.execute("SELECT 1 FROM tls_delivery_owners WHERE mode NOT IN ('legacy','shadow') OR TYPEOF(mode)!='text' OR TYPEOF(generation)!='integer' OR generation<0 LIMIT 1").fetchone() or db.execute("SELECT 1 FROM tls_delivery_tasks WHERE state IN ('claimed','sending') LIMIT 1").fetchone():
            raise PermissionError('archive requires stopped workers and non-TLS execution ownership')

    def _plan(self, db, now):
        policy = self.policy
        _check_orphan_sentinels(db)
        counts = {row[0]: row[1] for row in db.execute('SELECT state,COUNT(*) FROM tls_delivery_tasks GROUP BY state')}
        selected, raw_total, compressed_total = [], 0, 0
        # No audit timestamp means no defensible terminal age: preserve it.
        rows = db.execute("""SELECT t.*,MAX(a.occurred) AS terminal_observed FROM tls_delivery_tasks t
            JOIN tls_delivery_audit a ON a.task=t.id AND a.state=t.state
            LEFT JOIN tls_delivery_tombstones x ON x.task=t.id
            WHERE t.state IN ('confirmed','failed','cancelled','expired') AND x.task IS NULL
            GROUP BY t.id HAVING MAX(a.occurred)<=? ORDER BY MAX(a.occurred),t.id LIMIT ?""",
            (now - policy.minimum_age_seconds, policy.maximum_batch))
        for source in rows:
            row = {key: source[key] for key in ('id', 'scope', 'state', 'priority', 'due', 'expires', 'data')}
            task = json.loads(row['data'])
            from .delivery_types import task_input_hash
            from .models import private_scope, scope_key
            if (task['state'] != row['state'] or task['id'] != row['id'] or task_input_hash(task) != task['input_hash']
                    or scope_key(private_scope(task['scope'])) != row['scope']
                    or task['priority'] != row['priority'] or task['available_at'] != row['due'] or task['expires_at'] != row['expires']):
                raise ArchiveIntegrityError('terminal row cannot be safely archived')
            audit = [dict(item) for item in db.execute('SELECT * FROM tls_delivery_audit WHERE task=? ORDER BY seq', (row['id'],))]
            # Internal SQLite rows are already scalar values; the archive has
            # its own explicit size bound rather than the context JSON budget.
            raw = json.dumps({'version': 1, 'row': row, 'audit': audit}, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) > _MAX_RECORD:
                raise ArchiveIntegrityError('terminal archive record exceeds bounded decoder')
            if raw_total + len(raw) > policy.maximum_batch_bytes:
                break
            compressed = zlib.compress(raw, 6)
            selected.append({'row': row, 'task': task, 'audit': audit, 'body': compressed,
                             'raw_bytes': len(raw), 'archive_hash': _digest(raw)})
            raw_total += len(raw)
            compressed_total += len(compressed)
        existing = db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(body)),0) FROM tls_delivery_archives').fetchone()
        capacity_ok = existing[0] + len(selected) <= policy.maximum_archive_rows and existing[1] + compressed_total <= policy.maximum_archive_bytes
        public = {'version': 'tls.delivery.retention.v1', 'selected': len(selected), 'raw_bytes': raw_total,
                  'compressed_bytes': compressed_total, 'existing_archives': existing[0], 'existing_archive_bytes': existing[1],
                  'capacity_ok': capacity_ok, 'states': counts, 'unknown_preserved': counts.get('unknown', 0),
                  'quarantined_preserved': counts.get('quarantined', 0),
                  'plan_hash': _digest(canonical([[item['row']['id'], item['archive_hash']] for item in selected]).encode())}
        return public, selected

    def dry_run(self):
        with self.journal._transaction() as db:
            public, _ = self._plan(db, self.store._now())
            return dict(public, dry_run=True)

    def archive(self, *, expected_plan_hash):
        # A dry run is a reviewable CAS plan, not a permission to archive newer
        # or changed records under the same invocation.
        from .delivery_store import DeliveryConflict
        with self.journal._transaction() as db:
            self._maintenance(db)
            now = self.store._now()
            public, selected = self._plan(db, now)
            if public['plan_hash'] != expected_plan_hash:
                raise DeliveryConflict('retention plan changed')
            if not public['capacity_ok']:
                raise RuntimeError('delivery archive capacity reached; no identities discarded')
            for item in selected:
                row, task = item['row'], item['task']
                db.execute('INSERT INTO tls_delivery_archives VALUES(?,?,?,?)', (row['id'], item['raw_bytes'], len(item['audit']), item['body']))
                db.execute('INSERT INTO tls_delivery_tombstones VALUES(?,?,?,?,?,?)', (row['id'], task['input_hash'], row['state'], _digest(row['scope'].encode()), now, item['archive_hash']))
                sentinel = canonical({'id': row['id'], 'state': row['state'], 'input_hash': task['input_hash'], 'archived': True})
                db.execute('UPDATE tls_delivery_tasks SET data=? WHERE id=?', (sentinel, row['id']))
                db.execute('DELETE FROM tls_delivery_audit WHERE task=?', (row['id'],))
            if selected:
                db.execute("UPDATE tls_delivery_features SET version=2 WHERE name='queue'")
            return dict(public, dry_run=False, archived=len(selected))

    def stats(self):
        with self.journal._lock:
            self.journal._ensure_open()
            db = self.journal._db
            row = db.execute('SELECT COUNT(*),COALESCE(SUM(raw_bytes),0),COALESCE(SUM(LENGTH(body)),0),COALESCE(SUM(audit_rows),0) FROM tls_delivery_archives').fetchone()
            return {'archives': row[0], 'original_bytes': row[1], 'compressed_bytes': row[2], 'audit_rows': row[3],
                    'tombstones': db.execute('SELECT COUNT(*) FROM tls_delivery_tombstones').fetchone()[0],
                    'hot_tasks': db.execute('SELECT COUNT(*) FROM tls_delivery_tasks t LEFT JOIN tls_delivery_tombstones x ON x.task=t.id WHERE x.task IS NULL').fetchone()[0],
                    'queue_feature_version': db.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()[0]}

    def rehydrate_all(self):
        """Atomic, fail-closed rollback preparation. Never schedules or sends."""
        with self.journal._transaction() as db:
            self._maintenance(db)
            if db.execute('SELECT COUNT(*) FROM tls_delivery_tombstones').fetchone()[0] != db.execute('SELECT COUNT(*) FROM tls_delivery_archives').fetchone()[0]:
                raise ArchiveIntegrityError('archive/tombstone population mismatch')
            _check_orphan_sentinels(db)
            # Bound memory by decoding one row at a time inside the rollback
            # transaction. No deletion/feature downgrade occurs before verify.
            restored = 0
            last = ''
            while True:
                identities = db.execute('SELECT task FROM tls_delivery_tombstones WHERE task>? ORDER BY task LIMIT 100', (last,)).fetchall()
                if not identities:
                    break
                for identity in identities:
                    self._rehydrate_one(db, identity[0])
                    restored += 1
                    last = identity[0]
            db.execute("UPDATE tls_delivery_features SET version=1 WHERE name='queue'")
            return {'restored': restored, 'queue_feature_version': 1}

    @staticmethod
    def _rehydrate_one(db, identity):
        from .delivery_store import DeliveryConflict
        payload = _decode(db, identity)
        row = payload['row']
        current = db.execute('SELECT * FROM tls_delivery_tasks WHERE id=?', (identity,)).fetchone()
        expected = canonical({'id': identity, 'state': row['state'], 'input_hash': json.loads(row['data'])['input_hash'], 'archived': True})
        if current is None or current['data'] != expected or any(current[key] != row[key] for key in ('id','scope','state','priority','due','expires')):
            raise DeliveryConflict('archived sentinel changed; rollback refused')
        for audit in payload['audit']:
            old = db.execute('SELECT * FROM tls_delivery_audit WHERE seq=?', (audit['seq'],)).fetchone()
            if old is not None and dict(old) != audit:
                raise DeliveryConflict('archive audit identity conflict')
            if old is None:
                db.execute('INSERT INTO tls_delivery_audit(seq,task,occurred,event,state,details) VALUES(?,?,?,?,?,?)', tuple(audit[key] for key in ('seq','task','occurred','event','state','details')))
        db.execute('UPDATE tls_delivery_tasks SET data=? WHERE id=?', (row['data'], identity))
        db.execute('DELETE FROM tls_delivery_archives WHERE task=?', (identity,))
        db.execute('DELETE FROM tls_delivery_tombstones WHERE task=?', (identity,))

    def backup(self, destination, *, timeout_seconds=30):
        """SQLite online backup includes committed WAL; destination must be new."""
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int,float)) or not math.isfinite(timeout_seconds) or not 0.01 <= timeout_seconds <= 600:
            raise ValueError('invalid backup deadline')
        destination = Path(destination)
        if destination.exists() or destination.resolve() == self.journal.path.resolve():
            raise ValueError('new backup path required')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.journal._lock:
            self.journal._ensure_open()
            if self.journal._db.in_transaction:
                raise RuntimeError('backup cannot run inside a source write transaction')
            # Exclusive file creation avoids overwriting a race winner.
            with destination.open('xb'):
                pass
            target = sqlite3.connect(destination)
            try:
                deadline = time.monotonic() + timeout_seconds
                def progress(status, remaining, total):
                    if time.monotonic() > deadline:
                        raise TimeoutError('delivery backup deadline exceeded')
                self.journal._db.backup(target, pages=128, progress=progress, sleep=0.05)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ArchiveIntegrityError('backup integrity check failed')
            finally:
                target.close()
        return {'created': True, 'sqlite_integrity': 'ok', 'bytes': destination.stat().st_size}
