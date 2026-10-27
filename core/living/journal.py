"""Bounded SQLite provenance/workflow journal, not a second Presence engine.

Current sensor state remains in PresenceLayer and source-owned stores. This
journal owns only new observation history and the new workflow's checkpoints.
Host integrations must call disk operations off the AstrBot event loop.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import re
import sqlite3
import threading
import time

from .models import Observation, canonical, plain, private_scope, scope_key


class JournalConflict(RuntimeError):
    pass


class LivingJournal:
    def __init__(self, path, *, clock=time.time, max_observations=10000,
                 max_records=4096, max_audit=20000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.max_observations = max(1, min(int(max_observations), 100000))
        self.max_records = max(1, min(int(max_records), 50000))
        self.max_audit = max(1, min(int(max_audit), 100000))
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(self.path, timeout=1, check_same_thread=False, isolation_level=None)
        try:
            self._initialize_schema()
        except BaseException:
            # A constructor failure has no host-owned object to close later.
            self._db.close()
            self._closed = True
            raise

    def _initialize_schema(self):
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("unsupported journal schema")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS observations(
              id TEXT PRIMARY KEY, scope TEXT NOT NULL, source TEXT NOT NULL,
              kind TEXT NOT NULL, observed REAL, received REAL NOT NULL,
              expires REAL, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS observations_scope ON observations(scope,received DESC);
            CREATE TABLE IF NOT EXISTS checkpoints(
              namespace TEXT NOT NULL, key TEXT NOT NULL, scope TEXT NOT NULL,
              revision INTEGER NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(namespace,key,scope));
            CREATE TABLE IF NOT EXISTS audit(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
              occurred REAL NOT NULL, event_type TEXT NOT NULL, entity_id TEXT NOT NULL,
              status TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS resource_usage(
              scope TEXT NOT NULL,day TEXT NOT NULL,resource TEXT NOT NULL,used INTEGER NOT NULL,
              PRIMARY KEY(scope,day,resource));
            CREATE TABLE IF NOT EXISTS resource_reservations(
              scope TEXT NOT NULL,day TEXT NOT NULL,resource TEXT NOT NULL,identity TEXT NOT NULL,units INTEGER NOT NULL,
              PRIMARY KEY(scope,day,resource,identity));
            PRAGMA user_version=1;
        """)

    @contextmanager
    def _transaction(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("journal is closed")
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                # SQLite may already have rolled back (e.g. RAISE(ROLLBACK)
                # in a trigger). Preserve that original error and its cause.
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def record(self, observation: Observation, *, authorize=None) -> bool:
        data = observation.as_dict()
        with self._transaction() as db:
            if authorize is not None and not authorize():
                raise PermissionError('observation authority changed')
            existing = db.execute("SELECT data FROM observations WHERE id=?", (observation.observation_id,)).fetchone()
            if existing:
                # Same source event may arrive again with newer receipt/progress.
                old = Observation.from_dict(json.loads(existing[0]))
                if old.observation_id != observation.observation_id:
                    raise JournalConflict("observation identity mismatch")
                return False
            if db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] >= self.max_observations:
                raise RuntimeError("observation retention capacity reached")
            db.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)", (
                observation.observation_id, scope_key(observation.scope), observation.source_id,
                observation.observation_type, observation.observed_at, observation.received_at,
                observation.expires_at, observation.status, canonical(data)))
            if authorize is not None and not authorize():
                raise PermissionError('observation authority changed')
        return True

    def get(self, observation_id: str, scope: dict | None = None) -> dict | None:
        with self._lock:
            if self._closed:
                raise RuntimeError("journal is closed")
            if scope is None:
                raise ValueError("scope is required")
            row = self._db.execute("SELECT data FROM observations WHERE id=? AND scope=?",
                (observation_id, scope_key(private_scope(scope)))).fetchone()
            return json.loads(row[0]) if row else None

    def remove_observation(self, observation_id: str, scope: dict) -> bool:
        with self._transaction() as db:
            return bool(db.execute('DELETE FROM observations WHERE id=? AND scope=?',
                (observation_id,scope_key(private_scope(scope)))).rowcount)

    def recent(self, scope: dict, *, limit=100, now=None, include_expired=False,
               source_id=None, observation_type=None) -> list[dict]:
        where = ["scope=?"]
        params = [scope_key(private_scope(scope))]
        if not include_expired:
            where.extend(["status='fresh'", "expires>?"])
            params.append(self.clock() if now is None else now)
        if source_id is not None:
            where.append("source=?"); params.append(source_id)
        if observation_type is not None:
            where.append("kind=?"); params.append(observation_type)
        params.append(min(max(int(limit), 1), 1000))
        with self._lock:
            self._ensure_open()
            return [json.loads(r[0]) for r in self._db.execute(
                "SELECT data FROM observations WHERE " + " AND ".join(where) + " ORDER BY received DESC,id LIMIT ?", params)]

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("journal is closed")

    @staticmethod
    def _record(row):
        return {"revision": row["revision"], "updated_at": row["updated"], "data": json.loads(row["data"])} if row else None

    def put(self, namespace: str, key: str, scope: dict, data, *, expected_revision=None, authorize=None) -> dict:
        normalized = scope_key(private_scope(scope))
        if not namespace or not key or len(namespace) > 64 or len(key) > 256:
            raise ValueError("invalid checkpoint identity")
        encoded = canonical(plain(data, 65536))
        with self._transaction() as db:
            if authorize is not None and not authorize():raise PermissionError('checkpoint authority changed')
            previous = db.execute("SELECT revision FROM checkpoints WHERE namespace=? AND key=? AND scope=?",
                                  (namespace, key, normalized)).fetchone()
            rev = previous[0] if previous else 0
            if expected_revision is not None and rev != expected_revision:
                raise JournalConflict("checkpoint revision conflict")
            if previous is None and db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] >= self.max_records:
                raise RuntimeError("checkpoint capacity reached")
            updated = self.clock()
            db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data",
                       (namespace,key,normalized,rev+1,updated,encoded))
            if authorize is not None and not authorize():raise PermissionError('checkpoint authority changed')
        return {"revision": rev+1, "updated_at": updated, "data": json.loads(encoded)}

    def fetch(self, namespace: str, key: str, scope: dict) -> dict | None:
        with self._lock:
            self._ensure_open()
            row = self._db.execute("SELECT revision,updated,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?",
                                  (namespace,key,scope_key(private_scope(scope)))).fetchone()
            return self._record(row)

    def list(self, namespace: str, scope: dict, *, limit=100) -> list[dict]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute("SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? ORDER BY updated DESC,key LIMIT ?",
                (namespace,scope_key(private_scope(scope)),min(max(int(limit),1),1000)))
            return [dict(key=r['key'], **self._record(r)) for r in rows]

    def ownership_records(self) -> list[dict]:
        """Internal coordinator recovery, not a cross-scope plugin read API.

        Ownership data contains its complete private binding; verify that
        binding against scope_hash before restoring any execution authority.
        The journal's existing checkpoint capacity bounds this scan.
        """
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT key,scope,revision,updated,data FROM checkpoints "
                "WHERE namespace='tls.ownership' ORDER BY scope,key").fetchall()
            return [dict(key=row['key'], scope_hash=row['scope'], **self._record(row))
                    for row in rows]

    def remove(self, namespace: str, key: str, scope: dict, *, expected_revision=None) -> bool:
        with self._transaction() as db:
            sk = scope_key(private_scope(scope))
            row = db.execute("SELECT revision FROM checkpoints WHERE namespace=? AND key=? AND scope=?",(namespace,key,sk)).fetchone()
            if not row:return False
            if expected_revision is not None and row[0] != expected_revision:
                raise JournalConflict("checkpoint revision conflict")
            db.execute("DELETE FROM checkpoints WHERE namespace=? AND key=? AND scope=?",(namespace,key,sk))
            return True

    def remove_indexed_checkpoint(self, namespace, key, scope, *, index_namespace=None,
                                  index_key='index', expected_revision=None,
                                  terminal_states=('succeeded','failed','cancelled')):
        """Atomically retire a terminal workflow and its capacity reservation."""
        sk=scope_key(private_scope(scope));index_namespace=index_namespace or namespace+'.index'
        with self._transaction() as db:
            row=db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                (namespace,key,sk)).fetchone()
            if row is None:return False
            if expected_revision is not None and row['revision']!=expected_revision:
                raise JournalConflict('checkpoint revision conflict')
            if json.loads(row['data']).get('state') not in terminal_states:
                raise ValueError('only terminal checkpoints may be retired')
            index=db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                (index_namespace,index_key,sk)).fetchone()
            if index:
                data=json.loads(index['data']);items=dict(data.get('items',{}));items.pop(key,None);data['items']=items
                db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND key=? AND scope=?',
                    (index['revision']+1,self.clock(),canonical(data),index_namespace,index_key,sk))
            db.execute('DELETE FROM checkpoints WHERE namespace=? AND key=? AND scope=?',(namespace,key,sk))
        return True

    def audit(self, event_type: str, scope: dict, entity_id: str, status: str, details=None):
        # Details must be technical identifiers/counts. Never pass raw prompts or credentials.
        data = plain(details or {},4096)
        with self._transaction() as db:
            db.execute("INSERT INTO audit(scope,occurred,event_type,entity_id,status,details) VALUES(?,?,?,?,?,?)",
                (scope_key(private_scope(scope)),self.clock(),str(event_type)[:80],str(entity_id)[:256],str(status)[:64],canonical(data)))
            db.execute("DELETE FROM audit WHERE seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT ?)",(self.max_audit,))

    def events(self, scope: dict, *, limit=100) -> list[dict]:
        with self._lock:
            self._ensure_open()
            return [dict(r,details=json.loads(r['details'])) for r in self._db.execute(
                "SELECT seq,occurred,event_type,entity_id,status,details FROM audit WHERE scope=? ORDER BY seq DESC LIMIT ?",
                (scope_key(private_scope(scope)),min(max(int(limit),1),1000)))]

    def delete_scope(self, scope: dict) -> dict:
        sk = scope_key(private_scope(scope))
        with self._transaction() as db:
            counts={table:db.execute("SELECT COUNT(*) FROM "+table+" WHERE scope=?",(sk,)).fetchone()[0]
                    for table in ('observations','checkpoints','audit','resource_usage','resource_reservations')}
            for table in counts:db.execute("DELETE FROM "+table+" WHERE scope=?",(sk,))
        return counts

    def reserve_resource(self, scope, day, resource, identity, units, limit):
        sk=scope_key(private_scope(scope))
        with self._transaction() as db:
            old=db.execute('SELECT used FROM resource_usage WHERE scope=? AND day=? AND resource=?',
                (sk,day,resource)).fetchone()
            used=old[0] if old else 0
            reservation=db.execute('SELECT units FROM resource_reservations WHERE scope=? AND day=? AND resource=? AND identity=?',
                (sk,day,resource,identity)).fetchone()
            if reservation:return {'ok':reservation[0]==units,'duplicate':True,'used':used,'limit':limit}
            if used+units>limit:return {'ok':False,'reason':'budget_exhausted','used':used,'limit':limit}
            db.execute('INSERT INTO resource_reservations VALUES(?,?,?,?,?)',(sk,day,resource,identity,units))
            db.execute('INSERT INTO resource_usage VALUES(?,?,?,?) ON CONFLICT(scope,day,resource) DO UPDATE SET used=excluded.used',
                (sk,day,resource,used+units))
            return {'ok':True,'duplicate':False,'used':used+units,'limit':limit}

    def resource_usage(self,scope,day,resource):
        with self._lock:
            self._ensure_open()
            row=self._db.execute('SELECT used FROM resource_usage WHERE scope=? AND day=? AND resource=?',
                (scope_key(private_scope(scope)),day,resource)).fetchone()
            return row[0] if row else 0

    def prune(self, *, before: float) -> int:
        # Explicit maintenance only. Keep provenance referenced by memory,
        # decisions, preferences, actions and durable workflows in this scope.
        # Conservative matching also retains unknown future checkpoint formats.
        with self._transaction() as db:
            referenced = set()
            for checkpoint in db.execute('SELECT scope,key,data FROM checkpoints'):
                pending = [checkpoint['key'], json.loads(checkpoint['data'])]
                while pending:
                    value = pending.pop()
                    if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value):
                        referenced.add((checkpoint['scope'], value))
                    elif isinstance(value, dict):
                        pending.extend(value.values())
                    elif isinstance(value, list):
                        pending.extend(value)
            eligible = db.execute("SELECT id,scope FROM observations WHERE received<? AND (expires<? OR status!='fresh')",
                                  (before,self.clock())).fetchall()
            removable = [(row['id'],row['scope']) for row in eligible
                         if (row['scope'],row['id']) not in referenced]
            db.executemany('DELETE FROM observations WHERE id=? AND scope=?', removable)
            return len(removable)

    def stats(self) -> dict:
        with self._lock:
            self._ensure_open()
            return {"schema_version":1,**{t:self._db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                    for t in ('observations','checkpoints','audit')}}

    def close(self):
        with self._lock:
            if not self._closed:
                self._db.close(); self._closed=True

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
