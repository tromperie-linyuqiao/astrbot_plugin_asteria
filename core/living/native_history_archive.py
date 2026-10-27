"""Independent, non-retrievable archive of exact legacy snapshot rows.

Historical ownership gaps and source safety states are preserved. This store has
no memory adapter, LLM hook, legacy connection, model call or automatic import.
Only an explicit operator import can write a validated snapshot to this archive.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time


SNAPSHOT_SCHEMA = 'tls.native_memory.legacy_snapshot.v1'
ARCHIVE_SCHEMA = 'tls.native_history_archive.v1'
_TOKEN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}')
_SHA = re.compile(r'[a-f0-9]{64}')
_CATEGORIES = ('scope', 'source_plugin', 'memory_type', 'reality_level', 'sayability',
               'lifecycle', 'review_status', 'visibility', 'sensitivity', 'validity_status')


class HistoryArchiveConflict(RuntimeError):
    pass


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError('archive requires finite plain JSON') from None


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value, label, limit=512, *, blank=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or (not blank and not value.strip()):
        raise ValueError('invalid archive ' + label)
    return value


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid archive ' + label)
    return value


def _metadata(row):
    value = row.get('metadata')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            value = None
    return value if isinstance(value, dict) else {}


def _state(row, key):
    value = row.get(key)
    return value if isinstance(value, str) else None


def _holds(row):
    metadata = _metadata(row)
    reasons = ['historical_archive_only_no_llm']
    if not (row.get('persona_id') or metadata.get('persona_id') or metadata.get('character_id')):
        reasons.append('missing_historical_persona')
    if not (row.get('owner_bot_id') or metadata.get('owner_bot_id') or metadata.get('bot_id')):
        reasons.append('missing_historical_bot')
    if row.get('scope') != 'private':
        reasons.append('source_scope_not_private')
    if row.get('sayability') != 'direct' or metadata.get('mention_policy') not in (None, '', 'direct', 'soft_echo'):
        reasons.append('source_expression_restricted')
    if row.get('lifecycle') not in ('stable_memory', 'raw_event', 'open_loop'):
        reasons.append('source_lifecycle_retained')
    if row.get('validity_status') != 'active':
        reasons.append('source_inactive_or_unknown_validity')
    if row.get('visibility') != 'private_pair' or row.get('sensitivity') not in ('public', 'private'):
        reasons.append('source_visibility_restricted')
    if row.get('review_status') not in ('approved', 'confirmed', 'manual'):
        reasons.append('source_not_manually_approved')
    if row.get('reality_level') in ('llm_summary', 'model_inference', 'inferred', 'persona_life', 'roleplay_event', 'simulated', 'fictional_content'):
        reasons.append('source_inference_or_roleplay')
    return sorted(reasons)


def _snapshot(snapshot):
    raw = _json(snapshot)
    if len(raw.encode('utf-8')) > 64 * 1024 * 1024:
        raise ValueError('archive snapshot exceeds capacity')
    # Clone to detach caller mutation before any transaction begins.
    snapshot = json.loads(raw)
    if (not isinstance(snapshot, dict) or snapshot.get('schema') != SNAPSHOT_SCHEMA
            or set(snapshot) != {'schema', 'source', 'captured_at', 'records', 'inventory', 'snapshot_hash'}
            or snapshot.get('snapshot_hash') != _hash({k:v for k,v in snapshot.items() if k != 'snapshot_hash'})):
        raise ValueError('invalid archive snapshot hash or schema')
    source = snapshot['source']
    if (not isinstance(source, dict) or source.get('format') not in ('mc.sqlite', 'astrbot-memory-jsonl.v1')
            or not isinstance(source.get('source_id'), str) or not source['source_id']):
        raise ValueError('invalid archive snapshot source')
    records = snapshot['records']
    if not isinstance(records, list) or len(records) > 100000 or not isinstance(snapshot['inventory'], list):
        raise ValueError('invalid archive snapshot records')
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('invalid archive source row')
        identity = _text(row.get('id'), 'legacy record identity', 2048)
        if identity in seen:
            raise ValueError('duplicate archive source identity')
        seen.add(identity)
        if not isinstance(row.get('content'), str) or len(_json(row).encode('utf-8')) > 2 * 1024 * 1024:
            raise ValueError('invalid or oversized archive source row')
    return snapshot


class NativeHistoryArchive:
    """Private SQLite archive. List summaries; get returns the exact source row."""
    backend = 'native_history_archive'
    retrieval_enabled = False

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self.closed = False
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self._db.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables and 'history_archive_meta' not in tables:
                raise ValueError('archive path already contains another database')
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.executescript('''
                CREATE TABLE IF NOT EXISTS history_archive_meta(schema TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history_archive_batches(
                    batch_id TEXT PRIMARY KEY,source_hash TEXT NOT NULL,snapshot_hash TEXT NOT NULL,
                    request_hash TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,
                    imported INTEGER NOT NULL,existing INTEGER NOT NULL,created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS history_archive_records(
                    id TEXT PRIMARY KEY,source_hash TEXT NOT NULL,legacy_record_id TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,source_id TEXT NOT NULL,created_batch TEXT NOT NULL,
                    revision INTEGER NOT NULL,raw_json TEXT NOT NULL,raw_hash TEXT NOT NULL,
                    content TEXT NOT NULL,scope TEXT,source_plugin TEXT,memory_type TEXT,reality_level TEXT,
                    sayability TEXT,lifecycle TEXT,review_status TEXT,visibility TEXT,sensitivity TEXT,validity_status TEXT,
                    hold_json TEXT NOT NULL,imported_at REAL NOT NULL,
                    UNIQUE(source_hash,legacy_record_id));
                CREATE TABLE IF NOT EXISTS history_archive_batch_entries(
                    batch_id TEXT NOT NULL,archive_id TEXT NOT NULL,owned INTEGER NOT NULL,
                    expected_revision INTEGER NOT NULL,expected_hash TEXT NOT NULL,removed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(batch_id,archive_id));
                CREATE INDEX IF NOT EXISTS history_archive_order ON history_archive_records(imported_at,id);
            ''')
            meta = self._db.execute('SELECT schema FROM history_archive_meta').fetchall()
            if not meta:
                self._db.execute('INSERT INTO history_archive_meta VALUES(?)', (ARCHIVE_SCHEMA,))
            elif len(meta) != 1 or meta[0][0] != ARCHIVE_SCHEMA:
                raise ValueError('unsupported history archive schema')
            if os.name != 'nt':
                os.chmod(self.path, 0o600)
        except Exception:
            self._db.close(); self.closed = True
            raise

    def _open(self):
        if self.closed:
            raise RuntimeError('history archive is closed')

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._open()
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise

    def _receipt(self, batch):
        return {'schema': 'tls.native_history_archive.import_receipt.v1',
            **{key:batch[key] for key in ('batch_id','source_hash','snapshot_hash','revision','status','imported','existing')},
            'archive_only': True, 'retrieval_enabled': False}

    def import_batch(self, snapshot, *, batch_id, source_hash, allow_import=False):
        if allow_import is not True:
            raise PermissionError('explicit archive import required')
        if not isinstance(batch_id, str) or not _TOKEN.fullmatch(batch_id):
            raise ValueError('invalid archive batch identity')
        if not isinstance(source_hash, str) or not _SHA.fullmatch(source_hash):
            raise ValueError('invalid archive source hash')
        snapshot = _snapshot(snapshot)
        request_hash = _hash([source_hash, snapshot['snapshot_hash']])
        now = self._clock()
        if type(now) not in (float,int) or not math.isfinite(now):
            raise ValueError('invalid archive clock')
        with self._transaction():
            batch = self._db.execute('SELECT * FROM history_archive_batches WHERE batch_id=?',(batch_id,)).fetchone()
            if batch:
                if batch['request_hash'] != request_hash:
                    raise HistoryArchiveConflict('archive batch identity conflict')
                return self._receipt(batch)
            imported = existing = 0
            for source_row in snapshot['records']:
                archive_id = 'ha_' + _hash([source_hash,source_row['id']])
                raw = _json(source_row); raw_hash = _hash(source_row)
                prior = self._db.execute('SELECT * FROM history_archive_records WHERE id=?',(archive_id,)).fetchone()
                if prior:
                    if prior['raw_hash'] != raw_hash or _hash(json.loads(prior['raw_json'])) != raw_hash:
                        raise HistoryArchiveConflict('archive source record changed')
                    existing += 1; owned = 0
                else:
                    columns = ['id','source_hash','legacy_record_id','snapshot_hash','source_id','created_batch',
                               'revision','raw_json','raw_hash','content',*_CATEGORIES,'hold_json','imported_at']
                    values = [archive_id,source_hash,source_row['id'],snapshot['snapshot_hash'],snapshot['source']['source_id'],
                              batch_id,1,raw,raw_hash,source_row['content'],*[_state(source_row,key) for key in _CATEGORIES],
                              _json(_holds(source_row)),float(now)]
                    self._db.execute('INSERT INTO history_archive_records('+','.join(columns)+') VALUES('+','.join('?' for _ in values)+')',values)
                    imported += 1; owned = 1
                saved = prior or self._db.execute('SELECT * FROM history_archive_records WHERE id=?',(archive_id,)).fetchone()
                self._db.execute('INSERT INTO history_archive_batch_entries VALUES(?,?,?,?,?,0)',
                    (batch_id,archive_id,owned,saved['revision'],_hash(dict(saved))))
            self._db.execute('INSERT INTO history_archive_batches VALUES(?,?,?,?,1,?,?,?,?)',
                (batch_id,source_hash,snapshot['snapshot_hash'],request_hash,'applied',imported,existing,float(now)))
            return self._receipt(self._db.execute('SELECT * FROM history_archive_batches WHERE batch_id=?',(batch_id,)).fetchone())

    def rollback_batch(self, batch_id, *, expected_revision, allow_rollback=False):
        if allow_rollback is not True:
            raise PermissionError('explicit archive rollback required')
        _text(batch_id,'batch identity',128)
        _integer(expected_revision,'batch revision',1,2147483647)
        with self._transaction():
            batch = self._db.execute('SELECT * FROM history_archive_batches WHERE batch_id=?',(batch_id,)).fetchone()
            if not batch:
                raise KeyError('archive batch not found')
            if batch['revision'] != expected_revision:
                raise HistoryArchiveConflict('archive batch revision conflict')
            if batch['status'] == 'rolled_back':
                return {**self._receipt(batch),'removed':0,'conflicts':[]}
            removed = 0; conflicts = []
            entries = self._db.execute('SELECT * FROM history_archive_batch_entries WHERE batch_id=? AND owned=1 AND removed=0',(batch_id,)).fetchall()
            for entry in entries:
                record = self._db.execute('SELECT * FROM history_archive_records WHERE id=?',(entry['archive_id'],)).fetchone()
                unchanged = bool(record and record['created_batch'] == batch_id and record['revision'] == entry['expected_revision']
                    and _hash(dict(record)) == entry['expected_hash'])
                if unchanged:
                    try:
                        unchanged = _hash(json.loads(record['raw_json'])) == record['raw_hash'] and record['content'] == json.loads(record['raw_json']).get('content')
                    except (ValueError,TypeError):
                        unchanged = False
                if record is not None and not unchanged:
                    conflicts.append({'record_ref':hashlib.sha256(entry['archive_id'].encode()).hexdigest(), 'reason':'record_changed_after_import'})
                    continue
                if record is not None:
                    self._db.execute('DELETE FROM history_archive_records WHERE id=? AND created_batch=? AND revision=?',
                        (entry['archive_id'],batch_id,entry['expected_revision']))
                    removed += 1
                self._db.execute('UPDATE history_archive_batch_entries SET removed=1 WHERE batch_id=? AND archive_id=?',(batch_id,entry['archive_id']))
            self._db.execute('UPDATE history_archive_batches SET revision=revision+1,status=? WHERE batch_id=?',
                ('rollback_partial' if conflicts else 'rolled_back',batch_id))
            return {**self._receipt(self._db.execute('SELECT * FROM history_archive_batches WHERE batch_id=?',(batch_id,)).fetchone()),
                    'removed':removed,'conflicts':conflicts}

    @staticmethod
    def _summary(row):
        return {'id':row['id'],'source_hash':row['source_hash'],'source_id':row['source_id'],
            'legacy_record_id':row['legacy_record_id'],'revision':row['revision'],
            'content_preview':row['content'][:400], **{key:row[key] for key in _CATEGORIES},
            'hold_reasons':json.loads(row['hold_json']),'archive_only':True,'retrieval_enabled':False}

    def get(self, archive_id):
        _text(archive_id,'record identity',128)
        with self._lock:
            self._open()
            row = self._db.execute('SELECT * FROM history_archive_records WHERE id=?',(archive_id,)).fetchone()
            if not row:
                raise KeyError('archive record not found')
            return {**self._summary(row),'source_row':json.loads(row['raw_json']),
                    'raw_hash':row['raw_hash'],'snapshot_hash':row['snapshot_hash'],'imported_at':row['imported_at']}

    def _select(self, *, q=None, limit=50, offset=0, source_hash=None, scope=None, source_plugin=None):
        _integer(limit,'limit',1,100); _integer(offset,'offset',0,1000000)
        clauses=[]; parameters=[]
        for key,value in (('source_hash',source_hash),('scope',scope),('source_plugin',source_plugin)):
            if value is not None:
                clauses.append(key+'=?'); parameters.append(_text(value,key,512,blank=True))
        if q is not None:
            _text(q,'query',512)
            clauses.append('instr(lower(content),lower(?))>0'); parameters.append(q)
        sql='SELECT * FROM history_archive_records' + (' WHERE '+' AND '.join(clauses) if clauses else '')
        with self._lock:
            self._open()
            return [self._summary(row) for row in self._db.execute(sql+' ORDER BY imported_at DESC,id LIMIT ? OFFSET ?',(*parameters,limit,offset))]

    def list(self, *, limit=50, offset=0, source_hash=None, scope=None, source_plugin=None):
        return self._select(limit=limit,offset=offset,source_hash=source_hash,scope=scope,source_plugin=source_plugin)

    def query(self, q, *, limit=50, offset=0, source_hash=None, scope=None, source_plugin=None):
        return self._select(q=q,limit=limit,offset=offset,source_hash=source_hash,scope=scope,source_plugin=source_plugin)

    def stats(self):
        with self._lock:
            self._open()
            counts = {key:[{'value':row[0],'count':row[1]} for row in self._db.execute('SELECT '+key+',count(*) FROM history_archive_records GROUP BY '+key+' ORDER BY count(*) DESC,'+key)] for key in _CATEGORIES}
            holds = Counter(code for row in self._db.execute('SELECT hold_json FROM history_archive_records') for code in json.loads(row[0]))
            return {'schema':ARCHIVE_SCHEMA,'records':self._db.execute('SELECT count(*) FROM history_archive_records').fetchone()[0],
                'batches':self._db.execute('SELECT count(*) FROM history_archive_batches').fetchone()[0],
                'classifications':counts,'hold_reasons':dict(holds),'archive_only':True,'retrieval_enabled':False}

    def close(self):
        with self._lock:
            if not self.closed:
                self._db.close(); self.closed=True
