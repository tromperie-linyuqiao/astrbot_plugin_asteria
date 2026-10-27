"""TLS-owned SQLite private memory, with a local lexical index.

Chinese characters and adjacent character pairs are indexed alongside Latin
words. Retrieval is deterministic lexical matching, not embedding/vector or
semantic search. No legacy plugin, model, network or paid service is involved.
All operations are synchronous; async hosts must move them off the event loop.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata
import uuid

from .journal import JournalConflict
from .models import EvidenceKind, canonical, plain, private_scope, scope_key

_ID = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}$')
_WORDS = re.compile(r'[a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0003134f]+')
_REALITY = {'user_reported': 'real_user_fact', 'real_observation': 'external_observation',
            'model_inference': 'model_inference', 'roleplay_event': 'roleplay_event',
            'action_result': 'action_result'}


class NativeMemoryConflict(JournalConflict):
    """A stale revision, reused event, or conflicting record identity."""


MemoryConflict = NativeMemoryConflict


def _identity(value, name):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('invalid ' + name)
    return value


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _tokens(value):
    result = {}
    for word in _WORDS.findall(_normal(value)):
        if word.isascii():
            result['w:' + word] = 3.0
        else:
            for char in word:
                result['c:' + char] = .15
            for index in range(len(word) - 1):
                result['b:' + word[index:index + 2]] = 2.0
    return result


def _epoch(value):
    if type(value) in (int, float):
        result = float(value)
    elif isinstance(value, str) and 0 < len(value) <= 80:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('timestamp needs a timezone')
        result = parsed.timestamp()
    else:
        raise ValueError('invalid timestamp')
    if not math.isfinite(result) or not 0 <= result <= 253402300799:
        raise ValueError('timestamp out of range')
    return result


def _iso(value, *, receipt=False):
    stamp = datetime.fromtimestamp(value, timezone.utc)
    # ISO stores full microseconds, while a wall-clock tick may have finer
    # floating precision. An implicit receipt must not round into the future
    # of that same tick. Explicit occurrence/expiry values keep their existing
    # timestamp conversion and strict visibility semantics.
    if receipt and stamp.timestamp() > value:
        stamp -= timedelta(microseconds=1)
    return stamp.isoformat().replace('+00:00', 'Z')


def _revision(value, optional=False):
    if value is None and optional:
        return
    if type(value) is not int or value < 1:
        raise ValueError('positive expected_revision required')


class NativeMemoryStore:
    """Full-scope records, optimistic revisions and append-only change history.

    ``event_id`` is unique within the complete private scope. An exact retry
    returns the current record (even if subsequently deleted), without writes;
    changed input raises NativeMemoryConflict. Implicit receipt time is excluded
    from that comparison. Explicit timestamps are part of the input.

    Identical normalized payloads deduplicate within scope, including deleted
    records; only restore can reactivate a deleted record. History and event
    identities survive soft deletion. This is retention, not physical erasure.
    ``transaction()`` permits atomic multi-record imports and rollbacks.
    """

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.RLock()
        self._depth = 0
        self._serial = 0
        self._closed = False
        self._db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=FULL')
            with self.transaction():
                self._db.execute('CREATE TABLE IF NOT EXISTS tls_native_memory_schema(version INTEGER NOT NULL)')
                versions = self._db.execute('SELECT version FROM tls_native_memory_schema').fetchall()
                if versions and (len(versions) != 1 or versions[0][0] != 1):
                    raise ValueError('unsupported native memory schema')
                if not versions:
                    self._db.execute('INSERT INTO tls_native_memory_schema VALUES(1)')
                for statement in (
                    '''CREATE TABLE IF NOT EXISTS tls_native_memories(
                       scope TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,
                       lifecycle TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,
                       occurred REAL NOT NULL,expires REAL,updated REAL NOT NULL,data TEXT NOT NULL,
                       PRIMARY KEY(scope,id))''',
                    '''CREATE INDEX IF NOT EXISTS tls_native_memory_scope
                       ON tls_native_memories(scope,lifecycle,occurred DESC,id)''',
                    '''CREATE INDEX IF NOT EXISTS tls_native_memory_duplicate
                       ON tls_native_memories(scope,fingerprint)''',
                    '''CREATE INDEX IF NOT EXISTS tls_native_memory_duplicate_order
                       ON tls_native_memories(scope,fingerprint,id)''',
                    '''CREATE TABLE IF NOT EXISTS tls_native_memory_terms(
                       scope TEXT NOT NULL,token TEXT NOT NULL,record_id TEXT NOT NULL,
                       PRIMARY KEY(scope,token,record_id),
                       FOREIGN KEY(scope,record_id) REFERENCES tls_native_memories(scope,id))''',
                    '''CREATE INDEX IF NOT EXISTS tls_native_memory_terms_record
                       ON tls_native_memory_terms(scope,record_id)''',
                    '''CREATE TABLE IF NOT EXISTS tls_native_memory_events(
                       scope TEXT NOT NULL,id TEXT NOT NULL,fingerprint TEXT NOT NULL,
                       record_id TEXT NOT NULL,PRIMARY KEY(scope,id),
                       FOREIGN KEY(scope,record_id) REFERENCES tls_native_memories(scope,id))''',
                    '''CREATE TABLE IF NOT EXISTS tls_native_memory_history(
                       scope TEXT NOT NULL,record_id TEXT NOT NULL,revision INTEGER NOT NULL,
                       operation TEXT NOT NULL,changed_at TEXT NOT NULL,data TEXT NOT NULL,
                       PRIMARY KEY(scope,record_id,revision),
                       FOREIGN KEY(scope,record_id) REFERENCES tls_native_memories(scope,id))''',
                ):
                    self._db.execute(statement)
        except BaseException:
            self._db.close()
            self._closed = True
            raise

    def _check_open(self):
        if self._closed:
            raise RuntimeError('native memory store is closed')

    @contextmanager
    def transaction(self):
        """Reentrant write transaction; an exception rolls back its entire scope."""
        with self._lock:
            self._check_open()
            self._serial += 1
            savepoint = 'native_memory_' + str(self._serial)
            outer = self._depth == 0
            self._db.execute('BEGIN IMMEDIATE' if outer else 'SAVEPOINT ' + savepoint)
            self._depth += 1
            try:
                yield self
                self._db.execute('COMMIT' if outer else 'RELEASE ' + savepoint)
            except BaseException:
                if outer:
                    if self._db.in_transaction:
                        self._db.execute('ROLLBACK')
                else:
                    self._db.execute('ROLLBACK TO ' + savepoint)
                    self._db.execute('RELEASE ' + savepoint)
                raise
            finally:
                self._depth -= 1

    def _raw(self, key, record_id):
        return self._db.execute('SELECT * FROM tls_native_memories WHERE scope=? AND id=?',
                                (key, record_id)).fetchone()

    def _save(self, key, row, payload, fingerprint, operation, now):
        encoded = canonical(plain(row, 32768))
        self._db.execute('''INSERT INTO tls_native_memories VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scope,id) DO UPDATE SET revision=excluded.revision,
            lifecycle=excluded.lifecycle,fingerprint=excluded.fingerprint,payload=excluded.payload,
            occurred=excluded.occurred,expires=excluded.expires,updated=excluded.updated,data=excluded.data''',
            (key, row['id'], row['revision'], row['lifecycle'], fingerprint, canonical(payload),
             _epoch(row['occurred_at']), _epoch(row['expires_at']) if row['expires_at'] else None,
             now, encoded))
        self._db.execute('DELETE FROM tls_native_memory_terms WHERE scope=? AND record_id=?',
                         (key, row['id']))
        if row['lifecycle'] != 'deleted':
            self._db.executemany('INSERT INTO tls_native_memory_terms VALUES(?,?,?)',
                                 ((key, term, row['id']) for term in _tokens(row['content'])))
        self._db.execute('INSERT INTO tls_native_memory_history VALUES(?,?,?,?,?,?)',
                         (key, row['id'], row['revision'], operation, _iso(now, receipt=True), encoded))

    @staticmethod
    def _payload(content, source_id, evidence_kind, memory_type, canonical_key,
                 confidence, importance, occurred_at, expires_at, metadata):
        _identity(source_id, 'source_id')
        _identity(memory_type, 'memory_type')
        kind = EvidenceKind(evidence_kind).value
        if (not isinstance(content, str) or not content.strip() or len(content) > 6000
                or any(ord(ch) < 32 and ch not in '\t\r\n' for ch in content)):
            raise ValueError('invalid memory content')
        if not isinstance(canonical_key, str) or len(canonical_key) > 240:
            raise ValueError('invalid canonical_key')
        for value in (confidence, importance):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('invalid confidence or importance')
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError('metadata must be a mapping')
        metadata = plain(metadata, 16384)
        if metadata.get('evidence_kind', kind) != kind:
            raise ValueError('conflicting metadata evidence_kind')
        occurred = None if occurred_at is None else _epoch(occurred_at)
        expires = None if expires_at is None else _epoch(expires_at)
        if occurred is not None and expires is not None and expires <= occurred:
            raise ValueError('expiry must follow occurrence')
        return dict(content=content.strip(), source_id=source_id, evidence_kind=kind,
                    memory_type=memory_type, canonical_key=canonical_key,
                    confidence=float(confidence), importance=float(importance),
                    occurred_at=occurred, expires_at=expires, metadata=metadata)

    @staticmethod
    def _fingerprint(payload):
        normalized = dict(payload, content=_normal(payload['content']))
        return hashlib.sha256(canonical(normalized).encode()).hexdigest()

    @staticmethod
    def _row(scope, identity, payload, now, previous=None):
        kind = payload['evidence_kind']
        occurred = payload['occurred_at'] if payload['occurred_at'] is not None else now
        occurred_iso = _iso(occurred, receipt=payload['occurred_at'] is None)
        expires = payload['expires_at']
        if expires is not None and expires <= occurred:
            raise ValueError('expiry must follow occurrence')
        metadata = dict(payload['metadata'], evidence_kind=kind)
        return dict(id=identity, content=payload['content'], memory_type=payload['memory_type'],
            scope='private', visibility='private_pair', owner_bot_id=scope['bot_id'],
            persona_id=scope['character_id'], platform=scope['platform'], session_id=scope['session_id'],
            subject={'kind': 'user', 'id': scope['user_id']},
            object={'kind': 'bot', 'id': scope['bot_id']},
            source_id=payload['source_id'], source_plugin='texas_living_system',
            evidence_kind=kind, evidence=payload['source_id'], metadata=metadata,
            reality_level=('observed_utterance' if kind == 'user_reported' and
                           payload['memory_type'] == 'utterance' else _REALITY[kind]),
            confidence=payload['confidence'], importance=payload['importance'],
            canonical_key=payload['canonical_key'], occurred_at=occurred_iso,
            expires_at=_iso(expires) if expires is not None else None,
            valid_from=occurred_iso, valid_to=_iso(expires) if expires is not None else '',
            created_at=previous['created_at'] if previous else _iso(now, receipt=True), updated_at=_iso(now, receipt=True),
            revision=previous['revision'] + 1 if previous else 1,
            lifecycle='stable_memory', validity_status='active', review_status='manual',
            sensitivity='private', sayability='direct', mention_policy='direct', tags=[])

    def write(self, scope, content, *, source_id, evidence_kind='user_reported',
              memory_type='fact', record_id=None, event_id=None, canonical_key='',
              confidence=1.0, importance=.5, occurred_at=None, expires_at=None,
              metadata=None, expected_revision=None):
        scope = private_scope(scope)
        key = scope_key(scope)
        if record_id is not None:
            _identity(record_id, 'record_id')
        if event_id is not None:
            _identity(event_id, 'event_id')
        _revision(expected_revision, optional=True)
        if expected_revision is not None and record_id is None:
            raise ValueError('expected_revision requires record_id')
        payload = self._payload(content, source_id, evidence_kind, memory_type, canonical_key,
                                confidence, importance, occurred_at, expires_at, metadata)
        fingerprint = self._fingerprint(payload)
        request = hashlib.sha256(canonical([fingerprint, record_id, expected_revision]).encode()).hexdigest()
        with self.transaction():
            if event_id is not None:
                event = self._db.execute('SELECT * FROM tls_native_memory_events WHERE scope=? AND id=?',
                                          (key, event_id)).fetchone()
                if event:
                    if event['fingerprint'] != request:
                        raise NativeMemoryConflict('event_id reused with different input')
                    return json.loads(self._raw(key, event['record_id'])['data'])
            old = self._raw(key, record_id) if record_id is not None else None
            if expected_revision is not None and old is None:
                raise KeyError(record_id)
            if old is not None:
                if expected_revision is not None and old['revision'] != expected_revision:
                    raise NativeMemoryConflict('stale memory revision')
                if old['fingerprint'] == fingerprint:
                    row = json.loads(old['data'])
                else:
                    if expected_revision is None or old['lifecycle'] == 'deleted':
                        raise NativeMemoryConflict('explicit current revision and active record required')
                    now = _epoch(self.clock())
                    row = self._row(scope, record_id, payload, now, json.loads(old['data']))
                    self._save(key, row, payload, fingerprint, 'write', now)
            else:
                duplicate = self._db.execute('SELECT * FROM tls_native_memories WHERE scope=? AND fingerprint=? ORDER BY id LIMIT 1',
                                             (key, fingerprint)).fetchone()
                if duplicate:
                    if record_id is not None and record_id != duplicate['id']:
                        raise NativeMemoryConflict('duplicate payload already has another record_id')
                    row = json.loads(duplicate['data'])
                else:
                    now = _epoch(self.clock())
                    row = self._row(scope, record_id or 'mem_' + uuid.uuid4().hex, payload, now)
                    self._save(key, row, payload, fingerprint, 'create', now)
            if event_id is not None:
                self._db.execute('INSERT INTO tls_native_memory_events VALUES(?,?,?,?)',
                                 (key, event_id, request, row['id']))
            return row

    def get(self, scope, record_id, include_deleted=False):
        key = scope_key(private_scope(scope))
        _identity(record_id, 'record_id')
        if type(include_deleted) is not bool:
            raise ValueError('include_deleted must be boolean')
        with self._lock:
            self._check_open()
            raw = self._raw(key, record_id)
            return (json.loads(raw['data']) if raw is not None and
                    (include_deleted or raw['lifecycle'] != 'deleted') else None)

    @staticmethod
    def _page(limit, offset=0):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('invalid limit')
        if type(offset) is not int or offset < 0:
            raise ValueError('invalid offset')

    def list(self, scope, limit=50, offset=0, include_deleted=False):
        key = scope_key(private_scope(scope))
        self._page(limit, offset)
        if type(include_deleted) is not bool:
            raise ValueError('include_deleted must be boolean')
        now = _epoch(self.clock())
        with self._lock:
            self._check_open()
            return [json.loads(row[0]) for row in self._db.execute('''SELECT data FROM tls_native_memories
                WHERE scope=? AND (? OR (lifecycle!='deleted' AND occurred<=? AND (expires IS NULL OR expires>?)))
                ORDER BY occurred DESC,id LIMIT ? OFFSET ?''',
                (key, include_deleted, now, now, limit, offset))]

    def read_private_context(self, scope, limit=64):
        """Prefer effective owner-managed core over ordinary recent history.

        One bounded snapshot of the same scoped store, never a new cache/index.
        The policy still validates every returned row and its source contract.
        """
        key=scope_key(private_scope(scope))
        if type(limit) is not int or not 1<=limit<=64:
            raise ValueError('private context limit must be 1..64')
        now=_epoch(self.clock())
        panel_owned="(json_extract(data,'$.source_plugin')='texas_living_system' AND " \
              "json_extract(data,'$.source_id')='tls.personal.panel' AND " \
              "json_extract(data,'$.memory_type')='core_memory' AND " \
              "json_type(data,'$.metadata.enabled')='true' AND " \
              "json_type(data,'$.metadata.core_priority')='integer' AND " \
              "json_extract(data,'$.metadata.core_priority') BETWEEN 0 AND 100 AND " \
              "json_extract(data,'$.metadata.schema')='tls.native.personal.v1' AND " \
              "json_extract(data,'$.metadata.managed_by')='tls_material_panel' AND " \
              "json_extract(data,'$.metadata.personal_kind')='core')"
        tool_owned="(json_extract(data,'$.source_id')='tls.core.tool' AND " \
              "json_extract(data,'$.source_plugin')='texas_living_system' AND " \
              "json_extract(data,'$.memory_type')='core_memory' AND " \
              "json_type(data,'$.metadata.enabled')='true' AND " \
              "json_type(data,'$.metadata.core_priority')='integer' AND " \
              "json_extract(data,'$.metadata.core_priority') BETWEEN 0 AND 100 AND " \
              "json_extract(data,'$.metadata.schema')='tls.native.core_tool.v1' AND " \
              "json_extract(data,'$.metadata.managed_by')='tls_core_tool')"
        owned='('+panel_owned+' OR '+tool_owned+')'
        with self._lock:
            self._check_open()
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT data FROM tls_native_memories WHERE scope=? AND lifecycle!='deleted' "
                "AND occurred<=? AND (expires IS NULL OR expires>?) ORDER BY "
                +"CASE WHEN "+panel_owned+" THEN 0 WHEN "+tool_owned+" THEN 1 ELSE 2 END, "
                +"CASE WHEN "+owned+" THEN CAST(json_extract(data,'$.metadata.core_priority') AS INTEGER) ELSE 0 END DESC, "
                +"occurred DESC,id LIMIT ?",(key,now,now,limit))]

    def scopes(self, limit=100):
        """Actual private identities, including scopes with only deleted rows.

        This administrative inventory contains no memory text or provenance.
        No identity is inferred from session-name conventions.
        """
        self._page(limit)
        with self._lock:
            self._check_open()
            rows = self._db.execute('''SELECT scope,data FROM tls_native_memories
                GROUP BY scope ORDER BY scope LIMIT ?''', (limit,)).fetchall()
        result = []
        for raw in rows:
            row = json.loads(raw['data'])
            scope = private_scope(dict(platform=row['platform'], bot_id=row['owner_bot_id'],
                user_id=row['subject']['id'], character_id=row['persona_id'],
                session_id=row['session_id'], private=True))
            if scope_key(scope) != raw['scope']:
                raise ValueError('corrupt native memory scope')
            result.append(scope)
        return result

    def search(self, scope, query, limit=8, *, evidence_kinds=None):
        key = scope_key(private_scope(scope))
        self._page(limit)
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('invalid query')
        # A multi-character query must match a pair/word: an incidental shared
        # character (图书馆 versus 书店) is insufficient. Single-character
        # queries still use the character index. Bound SQLite parameters.
        terms = _tokens(query)
        if any(not term.startswith('c:') for term in terms):
            terms = {term: weight for term, weight in terms.items() if not term.startswith('c:')}
        terms = dict(tuple(terms.items())[:256])
        if not terms:
            return []
        now = _epoch(self.clock())
        marks = ','.join('(?,?)' for _ in terms)
        parameters = tuple(value for item in terms.items() for value in item)
        kind_filter, kind_parameters = '', ()
        if evidence_kinds is not None:
            if (not isinstance(evidence_kinds, (tuple, list)) or not evidence_kinds
                    or any(kind not in _REALITY for kind in evidence_kinds)):
                raise ValueError('invalid evidence filter')
            kind_filter = " AND json_extract(m.data,'$.evidence_kind') IN (" + ','.join('?' for _ in evidence_kinds) + ')'
            kind_parameters = tuple(evidence_kinds)
        with self._lock:
            self._check_open()
            rows = self._db.execute('WITH query_terms(token,weight) AS (VALUES ' + marks +
                ''') SELECT m.data,sum(q.weight) AS score FROM query_terms q
                JOIN tls_native_memory_terms t ON t.token=q.token
                JOIN tls_native_memories m ON m.scope=t.scope AND m.id=t.record_id
                WHERE t.scope=? AND m.lifecycle!='deleted' AND m.occurred<=?
                AND (m.expires IS NULL OR m.expires>?)''' + kind_filter + ' GROUP BY m.scope,m.id',
                (*parameters, key, now, now, *kind_parameters)).fetchall()
        found = []
        for raw in rows:
            row = json.loads(raw['data'])
            found.append(dict(row, score=raw['score']))
        phrase = _normal(query)
        for row in found:
            if phrase in _normal(row['content']):
                row['score'] += 8.0
            row['score'] = round(row['score'], 6)
        ranked = sorted(found, key=lambda row: (-row['score'], -row['importance'],
                      -row['confidence'], -_epoch(row['occurred_at']), row['id']))
        # De-duplicate before truncating, so repeated utterances with distinct
        # platform IDs cannot occupy every candidate slot and hide an agreement.
        seen, result = set(), []
        for row in ranked:
            identity = (row['evidence_kind'], _normal(row['content']))
            if identity not in seen:
                result.append(row)
                seen.add(identity)
                if len(result) == limit:
                    break
        return result

    def _change(self, scope, record_id, expected_revision, operation, content=None):
        scope = private_scope(scope)
        key = scope_key(scope)
        _identity(record_id, 'record_id')
        _revision(expected_revision)
        with self.transaction():
            old = self._raw(key, record_id)
            if old is None:
                raise KeyError(record_id)
            if old['revision'] != expected_revision:
                raise NativeMemoryConflict('stale memory revision')
            row, payload = json.loads(old['data']), json.loads(old['payload'])
            now = _epoch(self.clock())
            if operation == 'correct':
                if row['lifecycle'] == 'deleted':
                    raise NativeMemoryConflict('restore deleted memory before correction')
                payload = self._payload(content, payload['source_id'], payload['evidence_kind'],
                    payload['memory_type'], payload['canonical_key'], payload['confidence'],
                    payload['importance'], _epoch(_iso(now, receipt=True)), payload['expires_at'], payload['metadata'])
                row = self._row(scope, record_id, payload, now, row)
            else:
                target = 'deleted' if operation == 'delete' else 'stable_memory'
                if row['lifecycle'] == target:
                    return row
                row.update(revision=row['revision'] + 1, lifecycle=target,
                           validity_status='deleted' if operation == 'delete' else 'active',
                           updated_at=_iso(now, receipt=True), deleted_at=_iso(now, receipt=True) if operation == 'delete' else None)
            if operation in {'correct','restore'} and row.get('source_id')=='tls.core.tool':
                # Administrator edits preserve this source's AI-material
                # contract; they do not turn model text into confirmed facts.
                from .native_core_tools import tool_core_contract
                if not tool_core_contract(row,scope):
                    raise ValueError('native core material must retain its closed source contract')
            fingerprint = self._fingerprint(payload)
            self._save(key, row, payload, fingerprint, operation, now)
            return row

    def correct(self, scope, record_id, content, expected_revision):
        return self._change(scope, record_id, expected_revision, 'correct', content)

    def delete(self, scope, record_id, expected_revision):
        return self._change(scope, record_id, expected_revision, 'delete')

    def restore(self, scope, record_id, expected_revision):
        return self._change(scope, record_id, expected_revision, 'restore')

    def history(self, scope, record_id):
        key = scope_key(private_scope(scope))
        _identity(record_id, 'record_id')
        with self._lock:
            self._check_open()
            if self._raw(key, record_id) is None:
                raise KeyError(record_id)
            return [dict(revision=row['revision'], operation=row['operation'],
                         changed_at=row['changed_at'], record=json.loads(row['data']))
                    for row in self._db.execute('''SELECT * FROM tls_native_memory_history
                       WHERE scope=? AND record_id=? ORDER BY revision''', (key, record_id))]

    def data_generation(self, scope):
        """Persistent scope-local change marker, containing no record content.

        Every visible create/write/correct/delete/restore appends exactly one
        revision to the existing append-only history in the same transaction.
        Its indexed scope count therefore changes for direct store operations,
        other connections, imports and compensating soft rollbacks. Exact event
        retries, payload deduplication and failed/rolled-back transactions leave
        it unchanged. No new schema, content scan or global connection counter
        is needed; writes in another full private scope do not invalidate this
        one. Physical history erasure is not part of this store's public API.

        Outside transaction(), this reads committed data. Within an explicit
        transaction the caller sees its own provisional revision count, just as
        with get/list; consumers on another connection see it only on commit.
        """
        key = scope_key(private_scope(scope))
        with self._lock:
            self._check_open()
            return self._db.execute('SELECT count(*) FROM tls_native_memory_history WHERE scope=?',
                                    (key,)).fetchone()[0]

    def stats(self, scope):
        key = scope_key(private_scope(scope))
        now = _epoch(self.clock())
        with self._lock:
            self._check_open()
            row = self._db.execute('''SELECT count(*) total,
                coalesce(sum(lifecycle='deleted'),0) deleted,
                coalesce(sum(lifecycle!='deleted' AND occurred<=? AND (expires IS NULL OR expires>?)),0) active,
                coalesce(sum(lifecycle!='deleted' AND expires IS NOT NULL AND expires<=?),0) expired
                FROM tls_native_memories WHERE scope=?''', (now, now, now, key)).fetchone()
            result = dict(row)
            result['history_entries'] = self._db.execute(
                'SELECT count(*) FROM tls_native_memory_history WHERE scope=?', (key,)).fetchone()[0]
            result.update(schema_version=1, retrieval='local_lexical_chinese_bigrams', vector_search=False)
            return result

    def close(self):
        with self._lock:
            if self._depth:
                raise RuntimeError('cannot close during a transaction')
            if not self._closed:
                self._db.close()
                self._closed = True
