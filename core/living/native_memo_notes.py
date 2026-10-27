"""Native scoped memo definitions and one-off lifecycle, using the shared journal.

This is not a reminder worker. Legacy PC data, queues and external completion
remain untouched. Recurring completion requires a separately reviewed scheduler.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import re

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key

NAMESPACE = 'tls.native.memo_notes.v1'
RECEIPTS = 'tls.native.memo_notes.requests.v1'
MAX_NOTES = 200
MAX_IMPORT_RECORDS = 50
MAX_IMPORT_BYTES = 65536
FIELDS = frozenset(('title', 'content', 'color', 'pinned', 'due_at', 'repeat', 'remind_enabled'))
COLORS = frozenset(('yellow', 'blue', 'green', 'rose', 'gray'))
REPEATS = frozenset(('none', 'daily', 'weekly', 'monthly', 'yearly'))
_ID = re.compile(r'memo\.[a-f0-9]{64}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')
MAX_TIME = 4102444800.0  # Absolute epoch, not host-local date parsing.
BOUNDARY = dict(metadata_only=True, schedules_reminder=False,
                external_completion_confirmed=False, legacy_consumer_retained=True)


def _digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _text(value, limit, *, empty=False, multiline=False):
    if type(value) is not str or any(ord(c) < 32 and c not in '\r\n\t' for c in value):
        raise ValueError('plain memo text required')
    if multiline:
        value = '\n'.join(line for line in (' '.join(x.split()) for x in value.replace('\r\n', '\n').replace('\r', '\n').strip().split('\n')) if line)
    else:
        value = ' '.join(value.split())
    if len(value) > limit or not empty and not value:
        raise ValueError('bounded memo text required; no silent truncation')
    return value


def _integer(value, low=0, high=2**53 - 1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded exact integer required')
    return value


def _time(value, *, zero=True):
    if type(value) not in (int, float) or not math.isfinite(value) or not (0 if zero else 0.000001) <= value <= MAX_TIME:
        raise ValueError('finite absolute memo epoch required')
    return float(value)


def edit_fields(values):
    if type(values) is not dict or set(values) - FIELDS:
        raise ValueError('explicit editable memo fields required')
    title = _text(values.get('title', ''), 60, empty=True)
    content = _text(values.get('content', ''), 800, empty=True, multiline=True)
    if not title and not content:
        raise ValueError('memo title or content required')
    color, repeat = values.get('color', 'yellow'), values.get('repeat', 'none')
    if type(color) is not str or color not in COLORS or type(repeat) is not str or repeat not in REPEATS:
        raise ValueError('known memo color and repetition required')
    due_at = _time(values.get('due_at', 0))
    if repeat != 'none' and due_at == 0:
        raise ValueError('recurring memo requires an absolute due time')
    pinned, remind = values.get('pinned', False), values.get('remind_enabled', False)
    if type(pinned) is not bool or type(remind) is not bool:
        raise ValueError('exact memo flags required')
    return dict(title=title, content=content, color=color, pinned=pinned, due_at=due_at,
                repeat=repeat, remind_enabled=remind and due_at > 0)


def due_state(record, *, now):
    """Definition display only, no due task is created or claimed."""
    if record['status'] == 'completed':
        return 'completed'
    due = record['fields']['due_at']
    return ('none' if due <= 0 else 'overdue' if due - now < -60 else 'due' if due - now <= 1800
            else 'today' if due - now <= 86400 else 'upcoming')


def _tool_provenance(request_id, message_ref, instruction_ref):
    for ref in (message_ref, instruction_ref):
        if type(ref) is not str or not _HASH.fullmatch(ref):
            raise ValueError('tool memo evidence references must be lowercase 64-hex')
    return dict(kind='user_requested_ai_tool', source_ref=_text(request_id, 128),
                message_ref=message_ref, instruction_ref=instruction_ref, verbatim=False)


def _valid_provenance(value):
    """Validate every accepted source shape; malformed rows are never skipped."""
    if type(value) is not dict or type(value.get('kind')) is not str:
        return False
    shapes = {
        'user_explicit': {'kind', 'source_ref'},
        'user_requested_ai_tool': {'kind', 'source_ref', 'message_ref', 'instruction_ref', 'verbatim'},
        'legacy_import': {'kind', 'source_plugin', 'source_ref', 'source_id', 'source_sha256',
                          'source_record_sha256', 'attribution', 'external_record_unchanged'},
    }
    if value['kind'] not in shapes or set(value) != shapes[value['kind']]:
        return False
    try:
        if _text(value['source_ref'], 128) != value['source_ref']:
            return False
        if value['kind'] == 'user_requested_ai_tool':
            return (value['verbatim'] is False
                    and value == _tool_provenance(value['source_ref'], value['message_ref'], value['instruction_ref']))
        if value['kind'] == 'legacy_import':
            return (value['source_plugin'] == 'private_companion' and value['attribution'] == 'operator_explicit'
                and value['external_record_unchanged'] is True and _text(value['source_id'], 64) == value['source_id']
                and all(type(value[key]) is str and _HASH.fullmatch(value[key]) is not None
                        for key in ('source_sha256', 'source_record_sha256')))
        return True
    except (ValueError, TypeError):
        return False


class NativeMemoNotes:
    backend = 'tls_native_memo_notes'

    def __init__(self, journal, *, authorize, clock=None):
        if not isinstance(journal, LivingJournal) or not callable(authorize):
            raise ValueError('shared journal and exact scope authorization required')
        self.journal, self.authorize = journal, authorize
        self.clock = journal.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('clock required')
        self._bindings = (self.journal, self.authorize, self.clock)
        self.active = True

    def _scope(self, scope):
        scope = private_scope(scope)
        valid = lambda: (self.active and all(a is b for a, b in zip(self._bindings, (self.journal, self.authorize, self.clock))))
        if not valid() or self.authorize(dict(scope)) is not True or not valid():
            raise PermissionError('memo scope unavailable')
        return scope

    def _now(self):
        return _time(self.clock(), zero=False)

    @contextmanager
    def _transaction(self, scope):
        with self.journal._transaction() as db:
            self._scope(scope)
            yield db
            self._scope(scope)

    def _decode(self, row, scope):
        value = json.loads(row['data'])
        if (type(value) is not dict or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('id') != row['key'] or not _ID.fullmatch(value['id'])
                or value.get('scope') != scope or value.get('origin') != self.backend
                or type(value.get('archived')) is not bool or value.get('status') not in {'active', 'completed'}
                or edit_fields(value['fields']) != value['fields'] or not _HASH.fullmatch(value['creation_signature'])
                or not _valid_provenance(value.get('provenance'))
                or type(value.get('legacy_state')) is not dict):
            raise RuntimeError('invalid stored memo definition')
        _integer(row['revision'], 1); _integer(value['completion_count'])
        _time(row['updated'], zero=False); _time(value['created_at'], zero=False)
        _time(value['completed_at']); _time(value['last_completed_at'])
        if value['status'] == 'active' and value['completed_at'] != 0:
            raise RuntimeError('invalid active memo completion')
        return dict(value, revision=row['revision'], updated_at=row['updated'])

    def _rows(self, db, scope):
        rows = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? ORDER BY key LIMIT ?',
                          (NAMESPACE, scope_key(scope), MAX_NOTES + 1)).fetchall()
        if len(rows) > MAX_NOTES:
            raise RuntimeError('memo capacity exceeded')
        return [self._decode(row, scope) for row in rows]

    def _get(self, db, scope, identity):
        if type(identity) is not str or not _ID.fullmatch(identity):
            raise ValueError('native memo ID required')
        row = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                         (NAMESPACE, scope_key(scope), identity)).fetchone()
        return self._decode(row, scope) if row else None

    def _capacity(self, db, *, additional=1):
        if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] + additional > self.journal.max_records:
            raise RuntimeError('journal checkpoint capacity reached')

    def _write(self, db, scope, value, revision, *, updated_at=None):
        self._scope(scope); _integer(revision)
        if revision == 0:
            if len(self._rows(db, scope)) >= MAX_NOTES:
                raise RuntimeError('memo capacity reached; existing notes are never discarded')
            self._capacity(db)
        clean = {k: v for k, v in value.items() if k not in {'revision', 'updated_at'}}
        now = self._now() if updated_at is None else _time(updated_at, zero=False)
        encoded = canonical(plain(clean, 16384))
        if revision == 0:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (NAMESPACE, value['id'], scope_key(scope), 1, now, encoded))
        elif db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND scope=? AND key=? AND revision=?',
                        (revision + 1, now, encoded, NAMESPACE, scope_key(scope), value['id'], revision)).rowcount != 1:
            raise JournalConflict('memo revision conflict')
        saved = self._get(db, scope, value['id'])
        if saved != dict(clean, revision=revision + 1, updated_at=now):
            raise RuntimeError('memo write readback mismatch')
        return saved

    def create(self, scope, request_id, **fields):
        scope = self._scope(scope); request_id = _text(request_id, 128); fields = edit_fields(fields)
        identity, signature = 'memo.' + _digest(['new', scope, request_id]), _digest(fields)
        with self._transaction(scope) as db:
            old = self._get(db, scope, identity)
            if old:
                if old['creation_signature'] != signature:
                    raise JournalConflict('memo request reused with different fields')
                return old
            return self._write(db, scope, dict(schema=1, id=identity, scope=scope, origin=self.backend,
                fields=fields, archived=False, status='active', completed_at=0., last_completed_at=0., completion_count=0,
                created_at=self._now(), creation_signature=signature, legacy_state={},
                provenance=dict(kind='user_explicit', source_ref=request_id)), 0)

    def create_from_tool(self, scope, request_id, *, message_ref, instruction_ref, **fields):
        """Persist user-requested AI organization without asserting verbatim text.

        The same request shares the normal stable note ID, but creation fields
        and both evidence references are bound to a distinct source signature.
        A later edit is returned on replay, never overwritten or relabelled.
        """
        scope = self._scope(scope); request_id = _text(request_id, 128); fields = edit_fields(fields)
        provenance = _tool_provenance(request_id, message_ref, instruction_ref)
        identity = 'memo.' + _digest(['new', scope, request_id])
        signature = _digest(['user_requested_ai_tool', fields, provenance])
        with self._transaction(scope) as db:
            old = self._get(db, scope, identity)
            if old:
                if old['creation_signature'] != signature:
                    raise JournalConflict('memo creation request source or evidence changed')
                return old
            return self._write(db, scope, dict(schema=1, id=identity, scope=scope, origin=self.backend,
                fields=fields, archived=False, status='active', completed_at=0., last_completed_at=0., completion_count=0,
                created_at=self._now(), creation_signature=signature, legacy_state={}, provenance=provenance), 0)

    def get(self, scope, identity):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open(); result = self._get(self.journal._db, scope, identity)
        self._scope(scope)
        return result

    def get_request(self, scope, request_id):
        scope = self._scope(scope)
        return self.get(scope, 'memo.' + _digest(['new', scope, _text(request_id, 128)]))

    def search(self, scope, *, query='', status='active', include_archived=False, limit=20, offset=0):
        scope = self._scope(scope); query = _text(query, 100, empty=True).casefold()
        if status not in {'active', 'completed', 'all'} or type(include_archived) is not bool:
            raise ValueError('explicit memo status and archive filter required')
        _integer(limit, 1, 100); _integer(offset, 0, MAX_NOTES)
        with self.journal._lock:
            self.journal._ensure_open(); rows = self._rows(self.journal._db, scope)
        rows = [r for r in rows if (include_archived or not r['archived']) and (status == 'all' or r['status'] == status)
                and (not query or query in (r['fields']['title'] + '\n' + r['fields']['content']).casefold())]
        now = self._now()
        rows.sort(key=lambda r: (r['status'] == 'completed', not r['fields']['pinned'],
            0 if 0 < r['fields']['due_at'] <= now else 1 if r['fields']['due_at'] > 0 else 2,
            r['fields']['due_at'] if r['fields']['due_at'] > 0 else float('inf'), -r['updated_at'], r['id']))
        self._scope(scope)
        return dict(records=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset, **BOUNDARY)

    def _existing(self, db, scope, identity, expected_revision):
        _integer(expected_revision, 1)
        row = self._get(db, scope, identity)
        if row is None:
            raise KeyError('memo absent')
        if row['revision'] != expected_revision:
            raise JournalConflict('memo revision conflict')
        return row

    def update(self, scope, identity, *, expected_revision, **changes):
        scope = self._scope(scope)
        if not changes or set(changes) - FIELDS:
            raise ValueError('editable memo changes required')
        with self._transaction(scope) as db:
            row = self._existing(db, scope, identity, expected_revision)
            if row['archived']:
                raise JournalConflict('restore memo before editing')
            row['fields'] = edit_fields(dict(row['fields'], **changes))
            return self._write(db, scope, row, expected_revision)

    def update_from_tool(self, scope, identity, *, expected_revision, request_id,
                         message_ref, instruction_ref, **changes):
        """CAS an AI-organized edit and its request receipt in one transaction."""
        scope = self._scope(scope); _integer(expected_revision, 1)
        if not changes or set(changes) - FIELDS:
            raise ValueError('editable memo changes required')
        provenance = _tool_provenance(request_id, message_ref, instruction_ref)
        key = _digest(['action', scope, provenance['source_ref']])
        signature = _digest(['update_from_tool', identity, expected_revision, plain(changes, 16384), provenance])
        with self._transaction(scope) as db:
            prior = self._receipt(db, scope, key, signature)
            if prior is not None:
                return self._get(db, scope, prior['record_id'])
            row = self._existing(db, scope, identity, expected_revision)
            if row['archived']:
                raise JournalConflict('restore memo before editing')
            row['fields'] = edit_fields(dict(row['fields'], **changes))
            row['provenance'] = provenance
            row = self._write(db, scope, row, expected_revision)
            self._save_receipt(db, scope, key, dict(signature=signature, record_id=row['id'],
                action='update_from_tool', expected_revision=expected_revision, revision=row['revision'], **BOUNDARY))
            return row

    def _lifecycle(self, scope, identity, *, expected_revision, request_id, action):
        scope = self._scope(scope); _integer(expected_revision, 1)
        key = _digest(['action', scope, _text(request_id, 128)])
        signature = _digest([action, identity, expected_revision])
        with self._transaction(scope) as db:
            prior = self._receipt(db, scope, key, signature)
            if prior is not None:
                return self._get(db, scope, prior['record_id'])
            row = self._existing(db, scope, identity, expected_revision)
            if row['archived']:
                raise JournalConflict('restore archived memo before changing lifecycle')
            if row['fields']['repeat'] != 'none':
                raise ValueError('recurring completion requires separately reviewed scheduler binding')
            target = 'completed' if action == 'complete' else 'active'
            if row['status'] != target:
                row['status'] = target
                row['completed_at'] = self._now() if action == 'complete' else 0.
                if action == 'complete':
                    row['last_completed_at'] = row['completed_at']; row['completion_count'] += 1
                row = self._write(db, scope, row, expected_revision)
            self._save_receipt(db, scope, key, dict(signature=signature, record_id=row['id'], action=action,
                expected_revision=expected_revision, revision=row['revision'], **BOUNDARY))
            return row

    def complete(self, scope, identity, *, expected_revision, request_id):
        return self._lifecycle(scope, identity, expected_revision=expected_revision, request_id=request_id, action='complete')

    def reopen(self, scope, identity, *, expected_revision, request_id):
        return self._lifecycle(scope, identity, expected_revision=expected_revision, request_id=request_id, action='reopen')

    def _archive(self, scope, identity, expected_revision, archived):
        scope = self._scope(scope)
        with self._transaction(scope) as db:
            row = self._existing(db, scope, identity, expected_revision)
            if row['archived'] == archived:
                return row
            row['archived'] = archived
            return self._write(db, scope, row, expected_revision)

    def archive(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, True)

    def restore(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, False)

    def export(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open(); rows = self._rows(self.journal._db, scope)
        self._scope(scope)
        return dict(schema='tls.native.memo_notes.export.v1', scope=scope, records=rows, exported_at=self._now(), **BOUNDARY)

    def context_generation(self, scope):
        try:
            scope = self._scope(scope)
            with self.journal._lock:
                self.journal._ensure_open(); rows = self._rows(self.journal._db, scope)
            self._scope(scope)
            return ('native_memo_notes', id(self), tuple((row['id'], row['revision']) for row in rows))
        except Exception:
            return None

    def get_action_request(self, scope, request_id):
        """Read the original CAS for a retry; never infer it from current state.

        Pre-R33 receipts have no original expected revision and return None.
        Callers still pass the full original request to its normal mutation
        method, which verifies its immutable signature before returning replay.
        """
        scope = self._scope(scope); key = _digest(['action', scope, _text(request_id, 128)])
        with self.journal._lock:
            self.journal._ensure_open()
            found = self.journal._db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                (RECEIPTS, scope_key(scope), key)).fetchone()
            if found is None:
                result = None
            else:
                value = json.loads(found[0])
                required = {'signature', 'record_id', 'action', 'revision'} | set(BOUNDARY)
                if (type(value) is not dict or not required <= set(value) or set(value) - required - {'expected_revision'}
                        or value['action'] not in {'complete', 'reopen', 'update_from_tool'}
                        or type(value['signature']) is not str or not _HASH.fullmatch(value['signature'])
                        or type(value['record_id']) is not str or not _ID.fullmatch(value['record_id'])
                        or any(value[key] is not flag for key, flag in BOUNDARY.items())):
                    raise RuntimeError('invalid memo action request receipt')
                _integer(value['revision'], 1)
                if 'expected_revision' not in value:
                    result = None
                else:
                    _integer(value['expected_revision'], 1)
                    result = dict(action=value['action'], record_id=value['record_id'], expected_revision=value['expected_revision'])
        self._scope(scope)
        return result

    def context_material(self, scope, *, limit=32):
        scope = self._scope(scope); _integer(limit, 1, 32)
        generation = self.context_generation(scope)
        if generation is None:
            raise PermissionError('memo context unavailable')
        now = self._now()
        with self.journal._lock:
            self.journal._ensure_open(); rows = self._rows(self.journal._db, scope)
        # Imported copies retain their legacy context owner until a separately
        # reviewed handoff; merely importing cannot duplicate PC injection.
        selected = [r for r in rows if not r['archived'] and r['status'] == 'active'
                    and r['provenance']['kind'] in {'user_explicit', 'user_requested_ai_tool'}]
        selected.sort(key=lambda r: (not r['fields']['pinned'], -r['updated_at'], r['id']))
        result = []
        for row in selected[:limit]:
            f = row['fields']
            origin = row['provenance']['kind']
            due = datetime.fromtimestamp(f['due_at'], timezone.utc).isoformat() if f['due_at'] > 0 else '未设置'
            source_notice = ("这是按用户请求由AI整理的待办定义，不是用户逐字原话，也不是已经发生的经历；"
                             "不代表已经完成、已安排提醒或已发送。" if origin == 'user_requested_ai_tool' else
                             "这是人工登记的待办定义，不是已经发生的经历；不代表已经完成、已安排提醒或已发送。")
            content = (f"已登记且尚未完成的便签：{f['title'] or '未填写标题'}｜{f['content']}"
                       f"｜到期定义：{due}｜重复定义：{f['repeat']}。"
                       + source_notice)
            result.append(dict(id=row['id'], canonical_key=row['id'], revision=row['revision'], content=content,
                owner_bot_id=scope['bot_id'], persona_id=scope['character_id'], platform=scope['platform'],
                user_id=scope['user_id'], scope='private', session_id=scope['session_id'], visibility='bot_self',
                subject=dict(kind='bot', id=scope['bot_id']), object=dict(kind='user', id=scope['user_id']),
                memory_type='companion_note', source_plugin='tls_native_memo_notes', reality_level='bot_action',
                lifecycle='active', validity_status='active', review_status='manual', sensitivity='private',
                sayability='direct', mention_policy='when_relevant', confidence=1., created_at=row['created_at'],
                occurred_at=row['created_at'], updated_at=row['updated_at'], valid_to=now + 60,
                context_metadata=dict(status='active', timezone='UTC', expires_at=now + 60,
                    native_memo=dict(schema=1, id=row['id'], revision=row['revision'], status='active',
                                     has_reminder_authority=False, origin=origin))))
        if generation != self.context_generation(scope):
            raise JournalConflict('memo context generation changed during read')
        self._scope(scope)
        return result

    def _receipt(self, db, scope, key, signature):
        found = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                           (RECEIPTS, scope_key(scope), key)).fetchone()
        if found:
            result = json.loads(found[0])
            if result.get('signature') != signature:
                raise JournalConflict('memo request reused with different operation')
            return result
        return None

    def _save_receipt(self, db, scope, key, value):
        self._capacity(db)
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                   (RECEIPTS, key, scope_key(scope), 1, self._now(), canonical(plain(value, 65536))))
        found = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                           (RECEIPTS, scope_key(scope), key)).fetchone()
        if not found or json.loads(found[0]) != value:
            raise RuntimeError('memo receipt readback mismatch')

    @staticmethod
    def _legacy(raw, source_id):
        if type(raw) is not dict or raw.get('id') != source_id:
            raise ValueError('explicit original memo ID required')
        allowed = FIELDS | {'id', 'status', 'created_at', 'updated_at', 'completed_at', 'last_completed_at', 'completion_count',
                            'repeat_anchor_day', 'repeat_anchor_month', 'last_reminder_offer_at', 'last_reminder_attempt_at'}
        if set(raw) - allowed:
            raise ValueError('unknown source memo fields require review')
        fields = edit_fields({k: raw[k] for k in FIELDS if k in raw})
        status = raw.get('status', 'active')
        if status not in {'active', 'completed'}:
            raise ValueError('explicit original memo lifecycle required')
        created, updated = _time(raw.get('created_at'), zero=False), _time(raw.get('updated_at'), zero=False)
        if updated < created:
            raise ValueError('invalid original memo timestamps')
        completed = _time(raw.get('completed_at', 0)); last = _time(raw.get('last_completed_at', 0))
        count = _integer(raw.get('completion_count', 0))
        if status == 'active' and completed != 0:
            raise ValueError('invalid original active memo')
        legacy = {k: raw.get(k, 0) for k in ('repeat_anchor_day', 'repeat_anchor_month', 'last_reminder_offer_at', 'last_reminder_attempt_at')}
        _integer(legacy['repeat_anchor_day'], 0, 31); _integer(legacy['repeat_anchor_month'], 0, 12)
        _time(legacy['last_reminder_offer_at']); _time(legacy['last_reminder_attempt_at'])
        return dict(fields=fields, status=status, created_at=created, source_updated_at=updated,
                    completed_at=completed, last_completed_at=last, completion_count=count, legacy_state=legacy)

    def _preview(self, db, scope, payload):
        payload = plain(payload, MAX_IMPORT_BYTES)
        if (type(payload) is not dict or set(payload) != {'schema', 'source_plugin', 'source_ref', 'source_sha256', 'records'}
                or type(payload['schema']) is not int or payload['schema'] != 1 or payload['source_plugin'] != 'private_companion'
                or type(payload['source_sha256']) is not str or not _HASH.fullmatch(payload['source_sha256'])
                or type(payload['records']) is not list or not 1 <= len(payload['records']) <= MAX_IMPORT_RECORDS):
            raise ValueError('bounded detached legacy memo artifact required')
        source_ref = _text(payload['source_ref'], 128); results, seen = [], set()
        for item in payload['records']:
            row = dict(source_id='', status='invalid')
            try:
                if type(item) is not dict or set(item) != {'source_id', 'record', 'target_scope'}:
                    raise ValueError('explicit source row and attribution required')
                source_id = _text(item['source_id'], 64); row['source_id'] = source_id
                if source_id in seen:
                    row['status'] = 'duplicate_source_id'; results.append(row); continue
                seen.add(source_id)
                if item['target_scope'] is None:
                    row['status'] = 'unassigned'; results.append(row); continue
                if private_scope(item['target_scope']) != scope:
                    row['status'] = 'foreign_scope'; results.append(row); continue
                adapted = self._legacy(item['record'], source_id)
                provenance = dict(kind='legacy_import', source_plugin='private_companion', source_ref=source_ref,
                    source_id=source_id, source_sha256=payload['source_sha256'], source_record_sha256=_digest(item['record']),
                    attribution='operator_explicit', external_record_unchanged=True)
                signature = _digest([adapted, {k: v for k, v in provenance.items() if k != 'source_sha256'}])
                identity = 'memo.' + _digest(['import', scope, source_ref, source_id]); old = self._get(db, scope, identity)
                row.update(status='ready' if old is None else 'existing' if old['creation_signature'] == signature else 'conflict',
                    id=identity, adapted=adapted, provenance=provenance, creation_signature=signature,
                    revision=old['revision'] if old else 0, archived=old['archived'] if old else False)
            except (ValueError, TypeError, KeyError, OverflowError):
                row['status'] = 'invalid'
            results.append(row)
        result = dict(schema=1, scope=scope, source_ref=source_ref, records=results, writes=0,
            counts={x: sum(r['status'] == x for r in results) for x in ('ready', 'existing', 'conflict', 'invalid', 'unassigned', 'foreign_scope', 'duplicate_source_id')}, **BOUNDARY)
        result['preview_sha256'] = _digest(result)
        return result

    def preview_import(self, scope, payload):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open(); result = self._preview(self.journal._db, scope, payload)
        self._scope(scope)
        return result

    def confirm_import(self, scope, payload, *, preview_sha256, request_id, owner_confirmed):
        scope = self._scope(scope)
        if owner_confirmed is not True or type(preview_sha256) is not str or not _HASH.fullmatch(preview_sha256):
            raise PermissionError('explicit memo attribution confirmation required')
        payload = plain(payload, MAX_IMPORT_BYTES); key = _digest(['import', scope, _text(request_id, 128)])
        signature = _digest([payload, preview_sha256])
        with self._transaction(scope) as db:
            prior = self._receipt(db, scope, key, signature)
            if prior is not None:
                return prior
            preview = self._preview(db, scope, payload)
            if preview['preview_sha256'] != preview_sha256 or any(r['status'] not in {'ready', 'existing'} for r in preview['records']):
                raise JournalConflict('memo source changed or attribution incomplete')
            ready = [r for r in preview['records'] if r['status'] == 'ready']
            if len(self._rows(db, scope)) + len(ready) > MAX_NOTES:
                raise RuntimeError('memo scope capacity reached')
            self._capacity(db, additional=len(ready) + 1); created = []
            for row in ready:
                adapted = dict(row['adapted']); updated = adapted.pop('source_updated_at')
                value = dict(schema=1, id=row['id'], scope=scope, origin=self.backend, archived=False,
                    creation_signature=row['creation_signature'], provenance=row['provenance'], **adapted)
                created.append(self._write(db, scope, value, 0, updated_at=updated)['id'])
            receipt = dict(id=key, signature=signature, action='import', created_ids=created,
                existing_ids=[r['id'] for r in preview['records'] if r['status'] == 'existing'], **BOUNDARY)
            self._save_receipt(db, scope, key, receipt)
            return receipt

    def preview_import_rollback(self, scope, import_id):
        scope = self._scope(scope)
        if type(import_id) is not str or not _HASH.fullmatch(import_id):
            raise ValueError('known import receipt ID required')
        with self.journal._lock:
            self.journal._ensure_open(); result = self._rollback_preview(self.journal._db, scope, import_id)
        self._scope(scope)
        return result

    def _rollback_preview(self, db, scope, import_id):
        found = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                           (RECEIPTS, scope_key(scope), import_id)).fetchone()
        if not found or json.loads(found[0]).get('action') != 'import':
            raise KeyError('memo import receipt absent')
        receipt = json.loads(found[0]); rows = []
        for identity in receipt['created_ids']:
            row = self._get(db, scope, identity)
            rows.append(dict(id=identity, status='ready' if row and row['revision'] == 1 and not row['archived'] else 'conflict',
                             revision=row['revision'] if row else None))
        result = dict(import_id=import_id, records=rows, writes=0, rollback_kind='archive_created_unchanged_only', **BOUNDARY)
        result['preview_sha256'] = _digest(result)
        return result

    def rollback_import(self, scope, import_id, *, preview_sha256, request_id, owner_confirmed):
        scope = self._scope(scope)
        if owner_confirmed is not True:
            raise PermissionError('explicit archive rollback confirmation required')
        key = _digest(['rollback', scope, _text(request_id, 128)]); signature = _digest([import_id, preview_sha256])
        with self._transaction(scope) as db:
            prior = self._receipt(db, scope, key, signature)
            if prior is not None:
                return prior
            preview = self._rollback_preview(db, scope, import_id)
            if preview['preview_sha256'] != preview_sha256 or any(r['status'] != 'ready' for r in preview['records']):
                raise JournalConflict('memo import changed; rollback refuses to overwrite edits')
            self._capacity(db); archived = []
            for item in preview['records']:
                row = self._existing(db, scope, item['id'], 1); row['archived'] = True
                archived.append(self._write(db, scope, row, 1)['id'])
            receipt = dict(id=key, signature=signature, action='rollback_import', archived_ids=archived,
                           deleted_ids=[], original_source_unchanged=True, **BOUNDARY)
            self._save_receipt(db, scope, key, receipt)
            return receipt

    def stop(self):
        self.active = False

    def close(self):
        self.stop()
