"""Isolated, bounded read-only MC private-material adapter.

No host wiring, ownership grant, legacy selector/composer, provider or writer.
The caller supplies an explicit MC persona_id; TLS character IDs are not aliases.
The synchronous authorize callback MUST be pure and thread-safe. A future host
must separately validate its sealed selected-persona proof on its owning loop
before/after to_thread; calling Task-bound capture.current here is not supported.

The exact schema is audited from MC store SHA a28468782823c0b2255ed2491ac14f6f2af44e7b00e6f17f85278d3ddc8327df.
SQL reads never mutate the existing store connection. SQLite may use its normal
WAL read-lock/shared-memory bookkeeping; this is not an immutable-file snapshot.
"""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import threading
import time


class MCContextMaterialError(ValueError):
    """Fixed diagnostic code only; never database contents or transport paths."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_TYPES = ('user_profile', 'user_preference', 'user_habit', 'relationship_claim',
          'manual_memory', 'explicit_memory', 'living_observation', 'tool_memory', 'core_memory')
_METADATA = frozenset(('core_memory', 'core_label', 'core_kind', 'core_scope', 'core_priority',
    'core_enabled', 'target_id', 'core_revision', 'managed_by', 'profile_state',
    'profile_dimension', 'profile_value', 'normalized_value', 'extractor', 'producer_kind',
    'extraction_quality', 'extraction_quality_score', 'evidence_strength', 'quality_gate_passed',
    'mention_policy', 'evidence_kind', 'provenance_classification', 'claim_domain', 'expires_at'))
_TEXT_COLUMNS = ('id memory_type subject_kind subject_id subject_name subject_role '
    'object_kind object_id object_name object_role scope session_id platform message_id group_id '
    'visibility sayability reality_level lifecycle content evidence owner_bot_id validity_status '
    'valid_from valid_to durability sensitivity last_injected_at canonical_key review_status tags '
    'metadata created_at updated_at occurred_at last_accessed_at source_plugin import_batch_id '
    'content_fingerprint supersedes_id').split()
_REAL_COLUMNS = ('confidence importance salience reinforcement_score').split()
_INT_COLUMNS = ('injection_count access_count merged_count').split()
_SCHEMA = {**dict.fromkeys(_TEXT_COLUMNS, 'TEXT'), **dict.fromkeys(_REAL_COLUMNS, 'REAL'),
           **dict.fromkeys(_INT_COLUMNS, 'INTEGER')}
_PUBLIC = ('id', 'memory_type', 'scope', 'session_id', 'platform', 'visibility', 'sayability',
    'reality_level', 'lifecycle', 'owner_bot_id', 'validity_status', 'valid_from', 'valid_to',
    'canonical_key', 'content', 'review_status', 'source_plugin', 'created_at', 'updated_at',
    'occurred_at', 'sensitivity')
_READ = (*_PUBLIC, 'confidence', 'importance', 'tags', 'metadata',
         'subject_kind', 'subject_id', 'subject_name', 'subject_role',
         'object_kind', 'object_id', 'object_name', 'object_role')
_SCOPE = frozenset(('scope', 'platform', 'bot_id', 'user_id', 'session_id', 'persona_id'))
_MAX_CANDIDATES = 64
_MAX_BYTES = 48000
_MAX_VM_STEPS = 200000


def _scope(raw):
    if type(raw) is not dict or set(raw) != _SCOPE or raw.get('scope') != 'private':
        raise MCContextMaterialError('complete_explicit_mc_scope_required')
    if any(type(value) is not str or not value or value != value.strip() or len(value) > 200
           or any(ord(char) < 32 for char in value) for value in raw.values()):
        raise MCContextMaterialError('complete_explicit_mc_scope_required')
    return dict(raw)


def _database(path):
    path = Path(path).absolute()
    if path.name != 'memory_companion.db' or str(path).startswith(('\\\\', '//')):
        raise MCContextMaterialError('existing_local_mc_database_required')
    if any(part.is_symlink() or getattr(part, 'is_junction', lambda: False)()
           for part in (path, *path.parents)) or not path.is_file():
        raise MCContextMaterialError('existing_local_mc_database_required')
    return path


def _json(raw, kind):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise MCContextMaterialError('invalid_json')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(MCContextMaterialError('invalid_json')))
    except (ValueError, TypeError, RecursionError) as exc:
        raise MCContextMaterialError('invalid_json') from exc
    if type(value) is not kind:
        raise MCContextMaterialError('invalid_json_shape')
    return value


def _schema(connection):
    kind = connection.execute("SELECT type FROM sqlite_master WHERE name='memories'").fetchall()
    if len(kind) != 1 or kind[0][0] != 'table':
        raise MCContextMaterialError('unknown_schema')
    rows = connection.execute('PRAGMA table_xinfo(memories)').fetchall()
    if ({row[1]: row[2] for row in rows} != _SCHEMA or len(rows) != len(_SCHEMA)
            or any(len(row) != 7 or row[6] != 0 or row[5] != (1 if row[1] == 'id' else 0)
                or row[3] != (0 if row[1] == 'id' else 1) for row in rows)):
        raise MCContextMaterialError('unknown_schema')


def _query(scope, include_core):
    types = _TYPES if include_core else _TYPES[:-1]
    where = ("memory_type IN (" + ','.join('?' for _ in types) + ") AND owner_bot_id=? "
        "AND lifecycle NOT IN ('archived','deleted','superseded','quarantined') "
        "AND review_status NOT IN ('pending','rejected') AND validity_status='active' AND ("
        "(scope='private' AND visibility='private_pair' AND platform=? "
        "AND ((subject_kind='user' AND subject_id=?) OR (object_kind='user' AND object_id=?)) "
        "AND (session_id=? OR (memory_type='core_memory' AND session_id=''))) "
        "OR (memory_type='core_memory' AND scope='global' AND visibility='bot_self' "
        "AND platform IN ('',?)))")
    return where, (*types, scope['bot_id'], scope['platform'], scope['user_id'], scope['user_id'],
                   scope['session_id'], scope['platform'])


def _preflight(connection, where, parameters):
    # Fetch only scalar size information before any content, actors, tags or
    # metadata. The bounded CTE never materializes an unbounded result in Python.
    lengths = '+'.join('COALESCE(length(CAST(' + name + ' AS BLOB)),0)' for name in _READ)
    value = connection.execute('WITH bounded AS (SELECT ' + lengths + ' AS bytes FROM memories WHERE '
        + where + ' LIMIT ?) SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM bounded',
        (*parameters, _MAX_CANDIDATES + 1)).fetchone()
    if value[0] > _MAX_CANDIDATES or value[1] > _MAX_BYTES:
        raise MCContextMaterialError('candidate_capacity_exceeded')
    return value[0], value[1]


def _material(row, scope):
    if any(type(row[name]) is not str for name in _READ if name not in ('confidence', 'importance')):
        raise MCContextMaterialError('invalid_field_type')
    metadata = _json(row['metadata'], dict)
    tags = _json(row['tags'], list)
    if len(tags) > 64 or any(type(tag) is not str or len(tag) > 80 for tag in tags):
        raise MCContextMaterialError('invalid_tags')
    if not row['id'] or len(row['id']) > 160:
        raise MCContextMaterialError('invalid_record_id')
    if metadata.get('owner_bot_id') != scope['bot_id'] or metadata.get('persona_id') != scope['persona_id']:
        return None
    actors = []
    for name in ('subject', 'object'):
        actor = {key: row[name + '_' + key] for key in ('kind', 'id', 'name', 'role')}
        if ((actor['kind'] == 'user' and actor['id'] != scope['user_id'])
                or (actor['kind'] == 'bot' and actor['id'] != scope['bot_id'])
                or actor['kind'] not in ('user', 'bot')):
            return None
        actors.append(actor)
    if row['scope'] == 'global':
        if (row['memory_type'] != 'core_memory' or metadata.get('core_scope') != 'global'
                or metadata.get('target_id') not in ('', None)
                or any(actor['kind'] != 'bot' for actor in actors)):
            return None
    elif row['session_id'] != scope['session_id']:
        if (row['session_id'] != '' or row['memory_type'] != 'core_memory'
                or metadata.get('core_scope') != 'private' or metadata.get('target_id') != scope['user_id']):
            return None
    elif row['memory_type'] == 'core_memory':
        if metadata.get('core_scope') != 'private' or metadata.get('target_id') != scope['user_id']:
            return None
    safe_metadata = {}
    for name in _METADATA:
        if name not in metadata:
            continue
        value = metadata[name]
        if type(value) not in (str, int, float, bool) or type(value) is float and not math.isfinite(value):
            raise MCContextMaterialError('invalid_metadata_type')
        safe_metadata[name] = value
    result = {name: row[name] for name in _PUBLIC}
    for name in ('confidence', 'importance'):
        value = row[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise MCContextMaterialError('invalid_score')
        result[name] = float(value)
    result.update(persona_id=scope['persona_id'], subject=actors[0], object=actors[1], tags=tags,
        metadata=safe_metadata, private_context_metadata=dict(safe_metadata))
    if 'mention_policy' in safe_metadata:
        result['mention_policy'] = safe_metadata['mention_policy']
    return result


class NativeMCContextMaterialReader:
    """Synchronous private/core/profile/fact storage adapter, isolated only.

    Authorization does not originate here. The supplied pure thread-safe
    callback must bind this exact MC scope and a controller-held generation.
    Selected SDK persona presence alone is never an authorization grant.
    """

    def __init__(self, db_path, *, authorize, deadline_seconds=0.35, monotonic=time.monotonic,
                 environment='isolated'):
        if (environment != 'isolated' or not callable(authorize) or not callable(monotonic)
                or type(deadline_seconds) not in (int, float) or not math.isfinite(deadline_seconds)
                or not 0.01 <= deadline_seconds <= 2):
            raise MCContextMaterialError('isolated_bounded_reader_required')
        self.path = _database(db_path)
        self.authorize, self.deadline, self.monotonic = authorize, float(deadline_seconds), monotonic
        self._closed = threading.Event()

    def close(self):
        self._closed.set()

    def _allowed(self, scope):
        if self._closed.is_set():
            raise MCContextMaterialError('reader_closed')
        try:
            allowed = self.authorize(dict(scope)) is True
        except Exception as exc:
            raise MCContextMaterialError('authorization_unavailable') from exc
        if self._closed.is_set():
            raise MCContextMaterialError('reader_closed')
        if not allowed:
            raise MCContextMaterialError('authorization_denied')

    def read_private(self, scope, *, limit=64, include_core=True):
        scope = _scope(scope)
        if type(limit) is not int or not 1 <= limit <= 64 or type(include_core) is not bool:
            raise MCContextMaterialError('invalid_limit')
        self._allowed(scope)
        path = _database(self.path)
        identity = path.stat()
        started = self.monotonic()
        deadline = started + self.deadline
        steps = 0
        expired = False
        def progress():
            nonlocal steps, expired
            steps += 1000
            expired = self.monotonic() >= deadline or steps > _MAX_VM_STEPS or self._closed.is_set()
            return int(expired)
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                    timeout=min(self.deadline, 0.2), isolation_level=None)) as connection:
                connection.row_factory = sqlite3.Row
                connection.set_progress_handler(progress, 1000)
                connection.execute('PRAGMA query_only=ON')
                connection.execute('BEGIN')
                try:
                    _schema(connection)
                    where, parameters = _query(scope, include_core)
                    candidates, source_bytes = _preflight(connection, where, parameters)
                    self._allowed(scope)
                    if self.monotonic() >= deadline:
                        raise MCContextMaterialError('query_deadline_exceeded')
                    rows = connection.execute('SELECT ' + ','.join(_READ) + ' FROM memories WHERE '
                        + where + ' ORDER BY id ASC LIMIT ?', (*parameters, _MAX_CANDIDATES + 1)).fetchall()
                    if len(rows) != candidates:
                        raise MCContextMaterialError('snapshot_changed')
                    items = []
                    for row in rows:
                        item = _material(row, scope)
                        if item is not None:
                            items.append(item)
                    if len(items) > limit:
                        raise MCContextMaterialError('result_capacity_exceeded')
                    encoded = json.dumps(items, ensure_ascii=False, allow_nan=False).encode('utf8')
                    if len(encoded) > _MAX_BYTES:
                        raise MCContextMaterialError('serialized_capacity_exceeded')
                    after = path.stat()
                    if (identity.st_dev, identity.st_ino) != (after.st_dev, after.st_ino):
                        raise MCContextMaterialError('database_identity_changed')
                    self._allowed(scope)
                    if self.monotonic() >= deadline:
                        raise MCContextMaterialError('query_deadline_exceeded')
                    return dict(ok=True, state='ready', items=items, candidate_count=candidates,
                        source_bytes=source_bytes, serialized_bytes=len(encoded),
                        adapter='tls.mc.private_material.isolated.v1', writes=0)
                finally:
                    connection.rollback()
                    connection.set_progress_handler(None, 0)
        except MCContextMaterialError:
            raise
        except (sqlite3.Error, OSError, OverflowError) as exc:
            code = 'query_deadline_exceeded' if expired else 'database_read_failed'
            raise MCContextMaterialError(code) from exc
