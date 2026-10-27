"""TLS-owned role personal goals and daily progression on the existing journal.

These goals are the character's own non-creative aims (life, study, habits).
They are not user sticky notes and not creative projects. Records live in the
existing LivingJournal under the complete private scope with revision CAS; this
module adds no second memory store, scheduler, sender or permission system.

Automatic progression only consumes sourced activity events. Every advance
carries the evidence kind of that event, so a simulated role experience, an
explicitly maintained owner record and a real external observation stay
distinguishable; model inference is refused outright. Proactive output is a
bounded list of candidate reasons for the one existing queue. Nothing here
sends, schedules delivery, claims quiet hours or grants send permission, and
reading candidates never writes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta
import hashlib
import json
import math
import re

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key
from .native_important_dates import date_zone

NAMESPACE = 'tls.native.personal_goals.v1'
BATCH_NAMESPACE = 'tls.native.personal_goals.batch.v1'
MAX_GOALS = 200
MAX_LOGS = 24
MAX_APPLIED = 64
STATUSES = ('active', 'paused', 'completed', 'abandoned')
STATUS_RANK = {'active': 0, 'paused': 1, 'completed': 2, 'abandoned': 3}
# Category is display metadata, never evidence: keeping it out of the match
# terms stops one activity from advancing every goal in that category.
EDIT_FIELDS = frozenset(('title', 'category', 'next_step', 'note', 'keywords',
                         'auto_step', 'stall_days', 'share_cooldown_hours'))
RECORD_FIELDS = frozenset(('schema', 'id', 'scope', 'origin', 'fields', 'status',
                           'progress', 'logs', 'applied', 'pending_share', 'created_at',
                           'last_progress_at', 'last_activity_at', 'completed_at',
                           'stall_notified_at', 'share_notified_at', 'share_count',
                           'archived', 'creation_signature', 'provenance', 'import_batch_id'))
EVIDENCE_KINDS = ('real_observation', 'user_reported', 'roleplay_event',
                  'action_result', 'model_inference')
# Only a sourced event may move progress. model_inference is deliberately absent.
PROGRESS_EVIDENCE = frozenset(('real_observation', 'user_reported',
                               'roleplay_event', 'action_result'))
EVIDENCE_LABEL = {'real_observation': '真实外部观测', 'user_reported': '用户明确维护',
                  'roleplay_event': '虚构角色经历', 'action_result': '行动结果',
                  'model_inference': '模型推断'}
LOG_KINDS = frozenset(('imported', 'manual_progress', 'activity_progress',
                       'manual_adjust', 'completed', 'reopened', 'paused', 'resumed',
                       'abandoned', 'archived', 'restored'))
SHARE_KINDS = ('progress', 'milestone', 'completed', 'stalled')
CREATIVE_MARKERS = ('创作', '写作', '绘画创作', '作品')
ACTIVITY_FIELDS = frozenset(('id', 'text', 'occurred_at', 'evidence_kind', 'source'))
MIGRATION_FIELDS = frozenset(('schema', 'source_plugin', 'source_ref', 'source_sha256',
                              'source_default_stall_days',
                              'source_default_share_cooldown_hours', 'records'))
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_GOAL = re.compile(r'goal\.[a-f0-9]{64}\Z')
_EVENT = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:|-]{0,95}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')
_MAX_CLOCK = 253402214400


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _epoch(value, label='timestamp'):
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value) \
            or not 0 < value <= _MAX_CLOCK:
        raise ValueError('bounded exact %s required' % label)
    return float(value)


def _optional_epoch(value, label='timestamp'):
    """Zero means "never happened yet"; anything else must be a real instant."""
    if type(value) in (int, float) and not isinstance(value, bool) and value == 0:
        return 0.0
    return _epoch(value, label)


def _text(value, maximum, *, empty=False):
    if type(value) is not str or any(ord(c) < 32 and c not in '\r\n\t' for c in value):
        raise ValueError('plain bounded goal text required')
    value = ' '.join(value.split())
    if len(value) > maximum or (not empty and not value):
        raise ValueError('plain bounded goal text required')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded exact integer required')
    return value


def _number(value, low, high):
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value) \
            or not low <= value <= high:
        raise ValueError('bounded exact number required')
    return float(value)


def _request_id(value):
    if type(value) is not str or not _REQUEST.fullmatch(value):
        raise ValueError('explicit request identifier required')
    return value


def edit_fields(values):
    """Closed editable definition; idempotent so stored fields can be rechecked."""
    if type(values) is not dict or set(values) != EDIT_FIELDS:
        raise ValueError('explicit goal fields required')
    title = _text(values['title'], 60)
    category = _text(values['category'], 24)
    if any(marker in category for marker in CREATIVE_MARKERS):
        raise ValueError('creative goals stay in the creative-project business')
    keywords = values['keywords']
    if (type(keywords) is not list or len(keywords) > 16
            or any(type(item) is not str or not item or len(item) > 32
                   or any(ord(char) < 32 for char in item) for item in keywords)
            or len(set(keywords)) != len(keywords)):
        raise ValueError('bounded unique goal keywords required')
    return dict(title=title, category=category,
                next_step=_text(values['next_step'], 100, empty=True),
                note=_text(values['note'], 160, empty=True), keywords=list(keywords),
                auto_step=_integer(values['auto_step'], 1, 50),
                stall_days=_integer(values['stall_days'], 1, 30),
                share_cooldown_hours=_number(values['share_cooldown_hours'], 1, 168))


def goal_terms(fields):
    """The old bounded match terms, without category or any hidden expansion."""
    terms = []
    for raw in [fields.get('title'), fields.get('next_step'), *(fields.get('keywords') or [])]:
        term = raw if isinstance(raw, str) else ''
        if term and term not in terms:
            terms.append(term)
    return terms[:16]


def matches_activity(fields, text):
    if not isinstance(text, str):
        return False
    text = ' '.join(text.split())
    if not text:
        return False
    # Single-character terms would match almost any schedule text.
    return any(len(term) >= 2 and term in text for term in goal_terms(fields))


def activity_event(activity):
    """Detached, attributed activity; never a prompt, plan dump or inference."""
    if (type(activity) is not dict or set(activity) - ACTIVITY_FIELDS
            or not {'id', 'text', 'occurred_at', 'evidence_kind'} <= set(activity)):
        raise ValueError('explicit sourced activity event required')
    event_id = activity['id']
    if type(event_id) is not str or not _EVENT.fullmatch(event_id):
        raise ValueError('invalid activity event identity')
    evidence_kind = activity['evidence_kind']
    if evidence_kind not in EVIDENCE_KINDS:
        raise ValueError('unknown activity evidence kind')
    if evidence_kind not in PROGRESS_EVIDENCE:
        # The decisive boundary: imagined progress must never become a record.
        raise ValueError('only a sourced activity may advance a goal; model inference never does')
    return dict(id=event_id, text=_text(activity['text'], 500),
                occurred_at=_epoch(activity['occurred_at'], 'activity time'),
                evidence_kind=evidence_kind,
                source=_text(activity.get('source', 'tls.host.activity'), 64))


def _mapped_text(value, maximum):
    """Legacy text mapping that reports loss instead of guessing a truncation."""
    if value is None:
        return '', None
    if type(value) is not str:
        return None, '类型无效'
    text = ' '.join(value.split())
    if len(text) > maximum:
        return None, '超过 %d 字符上限' % maximum
    return text, None


def _valid_log(entry):
    required = {'ts', 'kind', 'progress', 'evidence', 'evidence_kind'}
    if type(entry) is not dict or set(entry) - {'event_id', 'source'} != required:
        return False
    try:
        _epoch(entry['ts'], 'log time')
        _integer(entry['progress'], 0, 100)
        if entry['kind'] not in LOG_KINDS or entry['evidence_kind'] not in EVIDENCE_KINDS:
            return False
        if type(entry['evidence']) is not str or len(entry['evidence']) > 160:
            return False
        if 'event_id' in entry and (type(entry['event_id']) is not str
                                    or not _EVENT.fullmatch(entry['event_id'])):
            return False
        if 'source' in entry and (type(entry['source']) is not str or not entry['source']
                                 or len(entry['source']) > 64
                                 or any(ord(char) < 32 for char in entry['source'])):
            return False
    except (ValueError, TypeError):
        return False
    return True


def _valid_pending(value):
    if value is None:
        return True
    if type(value) is not dict or set(value) != {'kind', 'milestone', 'evidence',
                                                 'evidence_kind', 'at'}:
        return False
    try:
        return (value['kind'] in SHARE_KINDS
                and _integer(value['milestone'], 0, 100) == value['milestone']
                and type(value['evidence']) is str and 0 < len(value['evidence']) <= 160
                and value['evidence_kind'] in PROGRESS_EVIDENCE
                and _epoch(value['at'], 'share time') == value['at'])
    except (ValueError, TypeError):
        return False


class NativePersonalGoals:
    """Role self-directed goals; the caller owns the shared journal."""

    backend = 'native_personal_goals'

    def __init__(self, journal, *, authorize, clock=None, timezone='UTC', max_goals=MAX_GOALS):
        if not isinstance(journal, LivingJournal) or not callable(authorize):
            raise ValueError('existing journal and scope authorization required')
        self.journal, self.authorize = journal, authorize
        self.clock = journal.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('goal clock required')
        self.timezone = date_zone(timezone)
        self.timezone_name = timezone
        self.max_goals = _integer(max_goals, 1, MAX_GOALS)
        self.active = True

    # -- scope and transaction fences -------------------------------------

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize(dict(scope)) is not True:
            raise PermissionError('personal-goal scope unavailable')
        return scope

    @contextmanager
    def _transaction(self, scope):
        with self.journal._transaction() as db:
            self._scope(scope)
            yield db
            # The operation-local fence stays after the last nested write and
            # before COMMIT, including idempotent returns.
            self._scope(scope)

    def _now(self):
        return _epoch(self.clock(), 'personal-goal clock')

    def _count(self, db, scope):
        return db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',
                          (NAMESPACE, scope_key(scope))).fetchone()[0]

    # -- record codec ------------------------------------------------------

    def _decode(self, row, scope):
        value = json.loads(row['data'])
        if (type(value) is not dict or set(value) != RECORD_FIELDS
                or type(value.get('schema')) is not int or value.get('schema') != 1
                or value.get('id') != row['key'] or type(value.get('id')) is not str
                or not _GOAL.fullmatch(value['id'])
                or value.get('scope') != scope or value.get('origin') != 'tls_native_personal_goals'
                or type(value.get('archived')) is not bool or value.get('status') not in STATUSES
                or type(value.get('progress')) is not int or not 0 <= value['progress'] <= 100
                or edit_fields(value['fields']) != value['fields']
                or type(value.get('logs')) is not list or len(value['logs']) > MAX_LOGS
                or any(not _valid_log(entry) for entry in value['logs'])
                or type(value.get('applied')) is not dict or len(value['applied']) > MAX_APPLIED
                or any(type(key) is not str or not _EVENT.fullmatch(key) for key in value['applied'])
                or not _valid_pending(value.get('pending_share'))
                or type(value.get('share_count')) is not int
                or not 0 <= value['share_count'] < 2 ** 31
                or type(value.get('provenance')) is not dict
                or value['provenance'].get('kind') not in {'user_explicit', 'legacy_import'}
                or (value.get('import_batch_id') is not None
                    and (type(value['import_batch_id']) is not str
                         or not _HASH.fullmatch(value['import_batch_id'])))):
            raise RuntimeError('invalid personal-goal record')
        for key in ('created_at', 'last_progress_at', 'last_activity_at'):
            _epoch(value[key], 'goal ' + key)
        for key in ('completed_at', 'stall_notified_at', 'share_notified_at'):
            _optional_epoch(value[key], 'goal ' + key)
        for value_at in value['applied'].values():
            _epoch(value_at, 'applied event time')
        return dict(value, revision=row['revision'], updated_at=row['updated'])

    def _rows(self, db, scope):
        rows = db.execute('SELECT key,revision,updated,data FROM checkpoints '
                          'WHERE namespace=? AND scope=? ORDER BY key LIMIT ?',
                          (NAMESPACE, scope_key(scope), self.max_goals + 1)).fetchall()
        if len(rows) > self.max_goals:
            raise RuntimeError('personal-goal scope capacity exceeded')
        return [self._decode(row, scope) for row in rows]

    def _get(self, db, scope, identity):
        if type(identity) is not str or not _GOAL.fullmatch(identity):
            raise ValueError('invalid personal-goal identity')
        row = db.execute('SELECT key,revision,updated,data FROM checkpoints '
                         'WHERE namespace=? AND key=? AND scope=?',
                         (NAMESPACE, identity, scope_key(scope))).fetchone()
        return self._decode(row, scope) if row else None

    def _read_rows(self, scope):
        with self.journal._lock:
            self.journal._ensure_open()
            return self._rows(self.journal._db, scope)

    def _write(self, db, scope, value, revision):
        _integer(revision, 0, 2 ** 53 - 1)
        self._scope(scope)
        if revision == 0:
            if self._count(db, scope) >= self.max_goals:
                raise RuntimeError('personal-goal scope capacity reached')
            if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
                raise RuntimeError('checkpoint capacity reached')
        updated = self._now()
        clean = {key: item for key, item in value.items() if key not in {'revision', 'updated_at'}}
        encoded = canonical(plain(clean, 32768))
        if revision == 0:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (NAMESPACE, value['id'], scope_key(scope), 1, updated, encoded))
        else:
            changed = db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? '
                                 'WHERE namespace=? AND key=? AND scope=? AND revision=?',
                                 (revision + 1, updated, encoded, NAMESPACE, value['id'],
                                  scope_key(scope), revision)).rowcount
            if changed != 1:
                raise JournalConflict('personal-goal revision conflict')
        expected = dict(clean, revision=revision + 1, updated_at=updated)
        saved = self._get(db, scope, value['id'])
        if saved != expected:
            raise RuntimeError('personal-goal write readback mismatch')
        self._scope(scope)
        return saved

    # -- progress helpers --------------------------------------------------

    @staticmethod
    def _log(record, *, kind, progress, evidence, evidence_kind, now, event_id=None,
             source=None):
        entry = dict(ts=now, kind=kind, progress=progress, evidence=evidence[:160],
                     evidence_kind=evidence_kind)
        if event_id is not None:
            entry['event_id'] = event_id
        if source is not None:
            entry['source'] = source
        record['logs'] = (record['logs'] + [entry])[-MAX_LOGS:]

    def _advance(self, record, value, *, kind, evidence, evidence_kind, now, event_id=None,
                 source=None):
        old = record['progress']
        if value <= old:
            return False
        record['progress'] = value
        record['last_progress_at'] = now
        record['last_activity_at'] = now
        record['stall_notified_at'] = 0.0
        bucket = value // 25
        if value >= 100:
            record['status'] = 'completed'
            if not record['completed_at']:
                record['completed_at'] = now
            record['pending_share'] = dict(kind='completed', milestone=100,
                                           evidence=evidence[:160],
                                           evidence_kind=evidence_kind, at=now)
            kind = 'completed'
        elif bucket > old // 25:
            record['pending_share'] = dict(kind='milestone', milestone=bucket * 25,
                                           evidence=evidence[:160],
                                           evidence_kind=evidence_kind, at=now)
        self._log(record, kind=kind, progress=value, evidence=evidence,
                  evidence_kind=evidence_kind, now=now, event_id=event_id, source=source)
        return True

    @staticmethod
    def _remember(record, event_id, occurred_at):
        """Bounded ledger: the newest occurrences win, older replays are refused."""
        applied = dict(record['applied'])
        applied[event_id] = occurred_at
        while len(applied) > MAX_APPLIED:
            applied.pop(min(applied, key=lambda key: (applied[key], key)))
        record['applied'] = applied

    def _touch(self, record, now):
        if now > record['last_activity_at']:
            record['last_activity_at'] = now

    # -- definition CRUD ---------------------------------------------------

    def create(self, scope, request_id, fields, *, progress=0):
        scope = self._scope(scope)
        request_id = _request_id(request_id)
        if type(fields) is not dict:
            raise ValueError('explicit goal fields required')
        values = dict(fields)
        if not values.get('category'):
            values['category'] = '生活'
        if not values.get('keywords'):
            values['keywords'] = [values['title']] if values.get('title') else []
        values = edit_fields(values)
        progress = _integer(progress, 0, 100)
        identity = 'goal.' + _digest(['new', scope, request_id])
        signature = _digest([values, progress])
        now = self._now()
        with self._transaction(scope) as db:
            existing = self._get(db, scope, identity)
            if existing:
                if existing['creation_signature'] != signature:
                    raise JournalConflict('goal request ID reused with different content')
                return existing
            status = 'completed' if progress >= 100 else 'active'
            record = dict(schema=1, id=identity, scope=scope, origin='tls_native_personal_goals',
                          fields=values, status=status, progress=progress, logs=[], applied={},
                          pending_share=None, created_at=now, last_progress_at=now,
                          last_activity_at=now,
                          completed_at=now if status == 'completed' else 0.0,
                          stall_notified_at=0.0, share_notified_at=0.0, share_count=0,
                          archived=False, creation_signature=signature,
                          provenance=dict(kind='user_explicit', source_ref=request_id),
                          import_batch_id=None)
            if progress:
                self._log(record, kind='manual_progress', progress=progress,
                          evidence='新建目标时登记的初始进度',
                          evidence_kind='user_reported', now=now)
            return self._write(db, scope, record, 0)

    def get(self, scope, identity):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            value = self._get(self.journal._db, scope, identity)
        self._scope(scope)
        return value

    def list(self, scope, *, include_archived=False, status=None, limit=50, offset=0):
        scope = self._scope(scope)
        if type(include_archived) is not bool:
            raise ValueError('exact archive option required')
        if status is not None and status not in STATUSES:
            raise ValueError('unknown goal status filter')
        _integer(limit, 1, 100)
        _integer(offset, 0, MAX_GOALS)
        rows = self._read_rows(scope)
        self._scope(scope)
        rows = [row for row in rows if include_archived or not row['archived']]
        if status is not None:
            rows = [row for row in rows if row['status'] == status]
        rows.sort(key=lambda row: (row['archived'], STATUS_RANK[row['status']],
                                   -row['last_activity_at'], row['fields']['title'], row['id']))
        return rows[offset:offset + limit]

    def search(self, scope, query, *, include_archived=False, limit=20):
        scope = self._scope(scope)
        query = _text(query, 80).casefold()
        if type(include_archived) is not bool:
            raise ValueError('exact archive option required')
        _integer(limit, 1, 50)
        rows = self._read_rows(scope)
        self._scope(scope)
        found = []
        for row in rows:
            if row['archived'] and not include_archived:
                continue
            fields = row['fields']
            haystack = ' '.join([fields['title'], fields['category'], fields['next_step'],
                                 fields['note'], ' '.join(fields['keywords'])]).casefold()
            if query in haystack:
                found.append(row)
        found.sort(key=lambda row: (row['archived'], STATUS_RANK[row['status']],
                                    -row['last_activity_at'], row['fields']['title'], row['id']))
        return found[:limit]

    def update(self, scope, identity, *, expected_revision, fields=None, progress=None):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2 ** 53 - 1)
        if fields is None and progress is None:
            raise ValueError('explicit editable goal fields or progress required')
        values = edit_fields(fields) if fields is not None else None
        target = None if progress is None else _integer(progress, 0, 100)
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('personal goal absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('personal-goal revision conflict')
            now = self._now()
            if values is not None:
                row['fields'] = values
            if target is not None and target != row['progress']:
                if target > row['progress']:
                    if row['archived']:
                        raise JournalConflict('restore the goal before recording progress')
                    self._advance(row, target, kind='manual_progress',
                                  evidence='在管理面板中手动更新进度',
                                  evidence_kind='user_reported', now=now)
                else:
                    # A lower value withdraws any unreleased milestone claim: the
                    # recorded progress no longer supports it.
                    row['progress'] = target
                    row['pending_share'] = None
                    self._log(row, kind='manual_adjust', progress=target,
                              evidence='在管理面板中下调进度',
                              evidence_kind='user_reported', now=now)
                    if row['status'] == 'completed' and target < 100:
                        row['status'] = 'active'
                        row['completed_at'] = 0.0
                        self._log(row, kind='reopened', progress=target,
                                  evidence='进度下调后重新打开目标',
                                  evidence_kind='user_reported', now=now)
            self._touch(row, now)
            return self._write(db, scope, row, expected_revision)

    def _transition(self, scope, identity, expected_revision, target, *, evidence):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2 ** 53 - 1)
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('personal goal absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('personal-goal revision conflict')
            if row['status'] == target:
                return row
            if row['archived']:
                raise JournalConflict('restore the archived goal before changing its status')
            now = self._now()
            advanced = False
            if target == 'completed':
                if row['progress'] < 100:
                    advanced = self._advance(row, 100, kind='manual_progress', evidence=evidence,
                                             evidence_kind='user_reported', now=now)
                row['status'] = 'completed'
                if not row['completed_at']:
                    row['completed_at'] = now
                row['pending_share'] = dict(kind='completed', milestone=100,
                                            evidence=evidence[:160],
                                            evidence_kind='user_reported', at=now)
                if not advanced:
                    self._log(row, kind='completed', progress=row['progress'],
                              evidence=evidence, evidence_kind='user_reported', now=now)
            else:
                row['status'] = target
                row['completed_at'] = 0.0
                # Pausing, abandoning or reopening withdraws an unreleased claim;
                # the queue never receives a stale reason.
                row['pending_share'] = None
                if target == 'active':
                    row['stall_notified_at'] = 0.0
                self._log(row, kind={'active': 'resumed', 'paused': 'paused',
                                     'abandoned': 'abandoned'}[target],
                          progress=row['progress'], evidence=evidence,
                          evidence_kind='user_reported', now=now)
            self._touch(row, now)
            saved = self._write(db, scope, row, expected_revision)
            if saved['status'] != target:
                raise RuntimeError('personal-goal status write mismatch')
            return saved

    def pause(self, scope, identity, *, expected_revision):
        return self._transition(scope, identity, expected_revision, 'paused',
                                evidence='在管理面板中暂停目标')

    def resume(self, scope, identity, *, expected_revision):
        return self._transition(scope, identity, expected_revision, 'active',
                                evidence='在管理面板中恢复目标')

    def complete(self, scope, identity, *, expected_revision):
        return self._transition(scope, identity, expected_revision, 'completed',
                                evidence='在管理面板中确认目标完成')

    def abandon(self, scope, identity, *, expected_revision):
        return self._transition(scope, identity, expected_revision, 'abandoned',
                                evidence='在管理面板中放弃目标')

    def _archive(self, scope, identity, expected_revision, archived):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2 ** 53 - 1)
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('personal goal absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('personal-goal revision conflict')
            if row['archived'] == archived:
                return row
            now = self._now()
            row['archived'] = archived
            if archived:
                row['pending_share'] = None
            else:
                row['stall_notified_at'] = 0.0
            self._touch(row, now)
            self._log(row, kind='archived' if archived else 'restored',
                      progress=row['progress'],
                      evidence='在管理面板中归档目标' if archived else '从归档恢复目标',
                      evidence_kind='user_reported', now=now)
            return self._write(db, scope, row, expected_revision)

    def archive(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, True)

    def restore(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, False)

    def export(self, scope, *, include_archived=True):
        """One bounded definition snapshot; not an import and not a send plan."""
        scope = self._scope(scope)
        if type(include_archived) is not bool:
            raise ValueError('exact archive option required')
        rows = self._read_rows(scope)
        self._scope(scope)
        rows = [row for row in rows if include_archived or not row['archived']]
        rows.sort(key=lambda row: (row['fields']['title'], row['id']))
        return dict(schema='tls.native.personal_goals.export.v1', scope=scope, records=rows,
                    total=len(rows), exported_at=self._now(), definitions_only=True,
                    creates_send_permission=False, creative_projects_excluded=True)

    # -- sourced progression ----------------------------------------------

    def apply_activity(self, scope, activity, *, now=None):
        """Advance each matching active goal once for one sourced activity."""
        scope = self._scope(scope)
        event = activity_event(activity)
        current = self._now() if now is None else _epoch(now, 'activity receipt')
        if event['occurred_at'] > current + 30:
            raise ValueError('activity occurs after receipt')
        rows = self._read_rows(scope)
        report = dict(event_id=event['id'], evidence_kind=event['evidence_kind'],
                      matched=[], advanced=[], duplicate=[], skipped=[],
                      progressed=False, creates_send_permission=False,
                      delivery='none')
        for row in rows:
            if not matches_activity(row['fields'], event['text']):
                continue
            report['matched'].append(row['id'])
            if row['archived'] or row['status'] != 'active':
                report['skipped'].append(dict(goal_id=row['id'], reason='goal_not_active'))
                continue
            try:
                with self._transaction(scope) as db:
                    fresh = self._get(db, scope, row['id'])
                    if fresh is None:
                        raise KeyError('personal goal absent')
                    outcome = self._apply_one(db, scope, fresh, event, current)
            except JournalConflict:
                report['skipped'].append(dict(goal_id=row['id'], reason='concurrent_revision'))
                continue
            if outcome['state'] == 'advanced':
                report['advanced'].append(outcome)
                report['progressed'] = True
            elif outcome['state'] == 'duplicate':
                report['duplicate'].append(outcome)
            else:
                report['skipped'].append(dict(goal_id=outcome['goal_id'],
                                              reason=outcome['reason']))
        self._scope(scope)
        return report

    def _apply_one(self, db, scope, record, event, now):
        goal_id = record['id']
        occurred = event['occurred_at']
        # The outer read only discovers candidates. An administrator may pause,
        # archive or edit matching terms before this transaction starts; the
        # fresh row, not that earlier discovery snapshot, decides progression.
        if record['archived'] or record['status'] != 'active':
            return dict(goal_id=goal_id, state='skipped', reason='goal_not_active')
        if not matches_activity(record['fields'], event['text']):
            return dict(goal_id=goal_id, state='skipped',
                        reason='activity_no_longer_matches')
        if event['id'] in record['applied']:
            return dict(goal_id=goal_id, state='duplicate', revision=record['revision'])
        applied = record['applied']
        if applied and (occurred < min(applied.values())
                        or len(applied) >= MAX_APPLIED and occurred == min(applied.values())):
            # Beyond the bounded ledger we can no longer prove this event is new,
            # including an evicted ID tied with the oldest retained timestamp.
            # Unknown equal-time events at a full boundary are explicitly
            # refused; existing IDs were already classified as duplicates above.
            return dict(goal_id=goal_id, state='skipped',
                        reason='outside_deduplication_window')
        target = min(100, record['progress'] + record['fields']['auto_step'])
        if target <= record['progress']:
            return dict(goal_id=goal_id, state='skipped', reason='progress_already_complete')
        evidence = '%s：%s' % (EVIDENCE_LABEL[event['evidence_kind']], event['text'])
        self._advance(record, target, kind='activity_progress', evidence=evidence,
                      evidence_kind=event['evidence_kind'], now=now, event_id=event['id'],
                      source=event['source'])
        self._remember(record, event['id'], occurred)
        saved = self._write(db, scope, record, record['revision'])
        if saved['applied'].get(event['id']) != occurred:
            raise RuntimeError('activity ledger readback mismatch')
        if saved['logs'][-1].get('event_id') != event['id']:
            raise RuntimeError('activity log binding missing')
        return dict(goal_id=goal_id, state='advanced', revision=saved['revision'],
                    progress=saved['progress'], status=saved['status'],
                    pending_share=saved['pending_share'])

    # -- proactive candidate reasons (read-only) ---------------------------

    @staticmethod
    def _stalled_rows(rows, now):
        found = []
        for row in rows:
            if row['archived'] or row['status'] != 'active':
                continue
            idle = now - row['last_activity_at']
            if idle < row['fields']['stall_days'] * 86400:
                continue
            if row['stall_notified_at'] > 0 and row['stall_notified_at'] >= row['last_activity_at']:
                continue
            found.append(dict(goal_id=row['id'], revision=row['revision'],
                              title=row['fields']['title'],
                              stalled_days=int(idle // 86400),
                              stall_days=row['fields']['stall_days'],
                              last_activity_at=row['last_activity_at']))
        return found

    def stalled(self, scope, *, now=None):
        scope = self._scope(scope)
        current = self._now() if now is None else _epoch(now, 'stall clock')
        rows = self._read_rows(scope)
        self._scope(scope)
        return self._stalled_rows(rows, current)

    def proactive_candidates(self, scope, *, now=None, limit=3, include_ineligible=False):
        """Bounded reasons for the existing queue. Pure read: never writes.

        Cooldown is a property of the goal's own last release. Quiet hours,
        rates and single-executor admission stay with the existing queue, which
        owns the reason name 'personal_goal_progress'.
        """
        scope = self._scope(scope)
        current = self._now() if now is None else _epoch(now, 'candidate clock')
        _integer(limit, 1, 8)
        if type(include_ineligible) is not bool:
            raise ValueError('exact candidate eligibility option required')
        rows = self._read_rows(scope)
        stalled = {item['goal_id']: item for item in self._stalled_rows(rows, current)}
        found = []
        for row in rows:
            if row['archived'] or row['status'] not in ('active', 'completed'):
                continue
            pending = row['pending_share']
            if row['status'] == 'completed':
                if not pending or pending['kind'] != 'completed':
                    continue
                found.append(self._candidate(row, 'completed', current, pending,
                                             cooldown_exempt=True))
                continue
            if pending and pending['kind'] in ('progress', 'milestone'):
                found.append(self._candidate(row, pending['kind'], current, pending))
                continue
            stall = stalled.get(row['id'])
            if stall is not None:
                found.append(self._candidate(row, 'stalled', current, dict(
                    kind='stalled', milestone=row['progress'],
                    evidence='已连续 %d 天没有匹配到有来源的推进' % stall['stalled_days'],
                    evidence_kind='user_reported', at=current)))
        found.sort(key=lambda item: (-item['score'], item['goal_id']))
        if not include_ineligible:
            found = [item for item in found if item['eligible']]
        self._scope(scope)
        return found[:limit]

    def _candidate(self, row, kind, now, pending, *, cooldown_exempt=False):
        fields = row['fields']
        fictional = pending['evidence_kind'] == 'roleplay_event'
        if kind == 'completed':
            topic = '%s终于完成了' % fields['title']
            motive = '自己持续推进的目标已有完成记录，想自然分享这条进度记录，不据此声称现实活动已经发生'
            score = 90
        elif kind == 'stalled':
            topic = '%s最近一直没顾上' % fields['title']
            motive = '意识到自己的长期目标停了一阵，想低压力提一句，不把责任推给用户'
            score = 70
        else:
            topic = '%s推进到 %d%%' % (fields['title'], row['progress'])
            motive = '自己持续推进的目标跨过了一个明确里程碑，想简短分享进展'
            score = 85 if kind == 'milestone' else 80
        if fictional:
            topic = '虚构角色进展：' + topic
            motive = '本条是虚构角色经历，不是现实完成。' + motive
        cooldown_until = row['share_notified_at'] + fields['share_cooldown_hours'] * 3600
        eligible = cooldown_exempt or now >= cooldown_until
        evidence = pending['evidence'][:160]
        evidence_kind = pending['evidence_kind']
        context = dict(goal_id=row['id'], title=fields['title'], category=fields['category'],
                       status=row['status'], progress=row['progress'],
                       next_step=fields['next_step'], note=fields['note'],
                       milestone=pending['milestone'], event_kind=kind,
                       evidence=evidence, evidence_kind=evidence_kind,
                       evidence_label=EVIDENCE_LABEL[evidence_kind],
                       revision=row['revision'])
        return dict(source='personal_goal', reason='personal_goal_progress', kind=kind,
                    goal_id=row['id'], revision=row['revision'], title=fields['title'],
                    topic=topic, motive=motive, score=score, occurred_at=now,
                    progress=row['progress'], milestone=pending['milestone'],
                    evidence=evidence, evidence_kind=evidence_kind,
                    evidence_label=EVIDENCE_LABEL[evidence_kind], topic_is_data=True,
                    eligible=eligible,
                    cooldown_until=0.0 if cooldown_exempt else cooldown_until,
                    blocked_reason=None if eligible else 'share_cooldown',
                    context_key='planned_personal_goal_context', context=context,
                    dedupe_key=_digest(['personal_goal_share', row['id'], kind,
                                        pending['milestone'], evidence]),
                    candidate_id=_digest(['personal_goal_candidate', row['id'], kind,
                                          row['revision'], pending['milestone']]),
                    creates_send_permission=False,
                    delivery='existing_proactive_queue_only',
                    single_executor_required=True)

    def claim_share(self, scope, identity, *, expected_revision, kind, candidate_id=None,
                    now=None):
        """Record that the existing queue accepted this reason; never sends.

        The caller only calls this after its own admission (quiet hours, rates,
        single executor) accepted the candidate, so one released reason is not
        offered twice inside the cooldown.
        """
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2 ** 53 - 1)
        if kind not in SHARE_KINDS:
            raise ValueError('unknown share reason')
        if candidate_id is not None and (type(candidate_id) is not str
                                         or not _HASH.fullmatch(candidate_id)):
            raise ValueError('invalid candidate identity')
        current = self._now() if now is None else _epoch(now, 'share clock')
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('personal goal absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('personal-goal revision conflict')
            if candidate_id is not None:
                pending = row['pending_share']
                milestone = pending['milestone'] if pending else row['progress']
                expected = _digest(['personal_goal_candidate', row['id'], kind,
                                    row['revision'], milestone])
                if candidate_id != expected:
                    raise JournalConflict('candidate no longer current')
            row['share_notified_at'] = current
            row['share_count'] = row['share_count'] + 1
            if kind == 'stalled':
                row['stall_notified_at'] = current
            if row['pending_share'] is not None and row['pending_share']['kind'] == kind:
                row['pending_share'] = None
            return self._write(db, scope, row, expected_revision)

    # -- unified context ---------------------------------------------------

    def context_generation(self, scope):
        try:
            scope = self._scope(scope)
            rows = self._read_rows(scope)
            now = self._now()
            day = datetime.fromtimestamp(now, self.timezone).date().isoformat()
            self._scope(scope)
            return ('native_personal_goals', id(self),
                    tuple((row['id'], row['revision']) for row in rows), day)
        except Exception:
            return None

    def context_material(self, scope, *, limit=6):
        scope = self._scope(scope)
        _integer(limit, 1, 16)
        generation = self.context_generation(scope)
        if generation is None:
            raise PermissionError('personal-goal material unavailable')
        now = self._now()
        rows = self._read_rows(scope)
        local_today = datetime.fromtimestamp(now, self.timezone).date()
        # Expiry fences the daily projection of an existing definition, not the
        # durable goal itself; created_at keeps the real registration time.
        valid_to = datetime.combine(local_today + timedelta(days=1), time.min,
                                   self.timezone).timestamp()
        result = []
        for row in rows:
            if row['archived'] or row['status'] != 'active':
                continue
            fields = row['fields']
            idle = int((now - row['last_activity_at']) // 86400)
            last = row['logs'][-1] if row['logs'] else None
            fictional = any(entry['evidence_kind'] == 'roleplay_event' for entry in row['logs'])
            content = ('已登记的角色非创作型个人目标：%s｜类别：%s｜进度：%d%%｜下一步：%s'
                       '｜匹配词：%s。这是角色自己的长期目标定义与既有进度记录；不代表今天已经'
                       '安排或已经完成，不虚构做过的步骤，也不把目标变成向用户索取监督的任务。'
                       % (fields['title'], fields['category'], row['progress'],
                          fields['next_step'] or '尚未指定',
                          '、'.join(goal_terms(fields)[:6])))
            if fictional:
                content = '虚构角色进度，非现实经历。' + content
            if last is not None:
                content += '最近一次推进（%s）：%s。' % (
                    EVIDENCE_LABEL.get(last['evidence_kind'], '来源不明'), last['evidence'][:80])
            if idle >= fields['stall_days']:
                content += '已连续 %d 天没有匹配到有来源的推进。' % idle
            result.append(dict(
                id=row['id'], canonical_key=row['id'], content=content,
                owner_bot_id=scope['bot_id'], persona_id=scope['character_id'],
                platform=scope['platform'], scope='private', session_id=scope['session_id'],
                visibility='bot_self', subject=dict(kind='bot', id=scope['bot_id']),
                object=dict(kind='user', id=scope['user_id']),
                memory_type='companion_note', source_plugin='tls_native_personal_goals',
                # Same bot-self material class as the sibling date definitions.
                reality_level='persona_life' if fictional else 'bot_action',
                lifecycle='active', validity_status='active',
                review_status='manual', sensitivity='private', sayability='direct',
                mention_policy='when_relevant', confidence=1.0, created_at=row['created_at'],
                occurred_at=now, updated_at=row['updated_at'], valid_to=valid_to,
                context_metadata=dict(
                    status='active', expires_at=valid_to,
                    projection_kind='personal_goal_definition',
                    definition_only=True, projection_computed_at=now,
                    source_created_at=row['created_at'], goal_status=row['status'],
                    progress=row['progress'], auto_step=fields['auto_step'],
                    stall_days=fields['stall_days'], idle_days=idle,
                    definition_revision=row['revision'],
                    last_activity_at=row['last_activity_at'],
                    last_evidence_kind=last['evidence_kind'] if last else None,
                    creative_project=False)))
            if len(result) >= limit:
                break
        if generation != self.context_generation(scope):
            raise JournalConflict('personal-goal generation changed during read')
        return result

    # -- read-only legacy migration preview --------------------------------

    @staticmethod
    def _migration_values(raw, options, now):
        """Map one detached old goal; every guess is reported, never applied."""
        if type(raw) is not dict:
            raise ValueError('old goal record must be an object')
        title = raw.get('title')
        if type(title) is not str or not title.strip():
            raise ValueError('old goal has no title')
        title = _text(title, 60)
        category = raw.get('category')
        category = _text(category, 24) if type(category) is str and category.strip() else '生活'
        if any(marker in category for marker in CREATIVE_MARKERS):
            return None, 'unsafe_domain', ['类别属于创作型目标，应继续留在创作项目，不迁入个人目标']
        status = raw.get('status', 'active')
        if status not in STATUSES:
            return None, 'ambiguous', ['旧状态无法识别为进行中/暂停/完成/放弃，本次不推断']
        progress = raw.get('progress', 0)
        if type(progress) is not int or isinstance(progress, bool) or not 0 <= progress <= 100:
            return None, 'ambiguous', ['旧进度不是 0–100 的整数，本次不推断']
        if progress >= 100 and status != 'completed':
            return None, 'ambiguous', ['旧记录进度已满但状态不是已完成；旧实现会自动完成，本次不猜']
        if raw.get('pending_share_event') is not None:
            return None, 'ambiguous', ['旧记录带着未释放的分享事件；不接管旧待发任务，需人工决定']
        issues = []
        keywords = raw.get('keywords')
        if type(keywords) is list:
            kept = [item for item in keywords if type(item) is str and item.strip()]
        else:
            kept = []
        if not kept:
            keywords = [title]
            issues.append('旧记录没有关键词，按旧实现以标题作为匹配词')
        else:
            keywords = kept[:16]
            if len(kept) > 16:
                issues.append('旧关键词超过 16 个，已保留前 16 个')
            if any(len(item) > 32 for item in keywords):
                return None, 'ambiguous', ['旧关键词超过 32 字符上限，需人工确认']
        next_step, problem = _mapped_text(raw.get('next_step'), 100)
        if problem:
            return None, 'ambiguous', ['旧下一步' + problem + '，需人工确认']
        note, problem = _mapped_text(raw.get('note'), 160)
        if problem:
            return None, 'ambiguous', ['旧备注' + problem + '，需人工确认']
        step = raw.get('auto_step', 10)
        if type(step) is not int or isinstance(step, bool) or not 1 <= step <= 50:
            step = 10
            issues.append('旧自动步长无效，使用默认 10')
        values = dict(title=title, category=category, next_step=next_step, note=note,
                      keywords=keywords, auto_step=step,
                      stall_days=options['source_default_stall_days'],
                      share_cooldown_hours=options['source_default_share_cooldown_hours'])
        created = raw.get('created_at')
        try:
            created = _epoch(created, 'old creation time')
        except (ValueError, TypeError):
            created = now
            issues.append('旧创建时间无效，使用迁移时间')
        if created > now + 30:
            return None, 'ambiguous', ['旧创建时间在未来，本次不推断']
        last = raw.get('last_progress_at')
        try:
            last = _epoch(last, 'old progress time')
        except (ValueError, TypeError):
            last = created
            issues.append('旧最近推进时间无效，使用创建时间')
        if last > now + 30:
            return None, 'ambiguous', ['旧最近推进时间在未来，本次不推断']
        if last < created:
            last = created
            issues.append('旧最近推进时间早于创建时间，已按创建时间修正')
        issues.append('旧推进日志与分享/停滞时间戳不迁移；新记录从迁移时刻重新记录')
        return dict(fields=edit_fields(values), status=status, progress=progress,
                    created_at=created, last_progress_at=last), 'ready', issues

    def preview_import(self, scope, payload):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            result = self._preview(self.journal._db, scope, payload)
        self._scope(scope)
        return result

    def _preview(self, db, scope, payload):
        payload = plain(payload, 262144)
        if (type(payload) is not dict or set(payload) != MIGRATION_FIELDS
                or type(payload['schema']) is not int or payload['schema'] != 1
                or payload['source_plugin'] != 'private_companion'
                or type(payload['source_sha256']) is not str
                or not _HASH.fullmatch(payload['source_sha256'])
                or type(payload['records']) is not list
                or not 1 <= len(payload['records']) <= 100):
            raise ValueError('bounded explicit PC goal source artifact required')
        source_ref = _text(payload['source_ref'], 128)
        options = dict(source_default_stall_days=
                       _integer(payload['source_default_stall_days'], 1, 30),
                       source_default_share_cooldown_hours=
                       _number(payload['source_default_share_cooldown_hours'], 1, 168))
        now = self._now()
        results, seen = [], set()
        for item in payload['records']:
            result = dict(status='invalid', source_id='',
                          source_record_sha256=_digest(item), issues=[])
            try:
                if type(item) is not dict or set(item) != {'source_id', 'record', 'target_scope'}:
                    raise ValueError
                source_id = _text(item['source_id'], 128)
                raw = item['record']
                if type(raw) is not dict or raw.get('id') != source_id:
                    raise ValueError
                result['source_id'] = source_id
                result['source_record_sha256'] = _digest(raw)
                if source_id in seen:
                    result.update(status='duplicate_source_id',
                                  issues=['旧来源记录 ID 重复'])
                    results.append(result)
                    continue
                seen.add(source_id)
                if item['target_scope'] is None:
                    # No identity is guessed from a user or character name.
                    result.update(status='unassigned',
                                  issues=['旧记录没有明确归属，未按用户名或角色名猜测'])
                    results.append(result)
                    continue
                if private_scope(item['target_scope']) != scope:
                    result.update(status='foreign_scope',
                                  issues=['旧记录归属另一完整私聊范围'])
                    results.append(result)
                    continue
                mapped, status, issues = self._migration_values(raw, options, now)
                result['issues'] = list(issues)
                if mapped is None:
                    result['status'] = status
                    results.append(result)
                    continue
                provenance = dict(kind='legacy_import', source_plugin='private_companion',
                                  source_ref=source_ref,
                                  source_sha256=payload['source_sha256'], source_id=source_id,
                                  source_record_sha256=_digest(raw),
                                  attribution='operator_explicit')
                identity = 'goal.' + _digest(['import', scope, source_ref, source_id])
                signature = _digest([mapped, {key: value for key, value in provenance.items()
                                              if key != 'source_sha256'}])
                old = self._get(db, scope, identity)
                state = 'ready' if old is None else 'existing' if \
                    old['creation_signature'] == signature else 'conflict'
                result.update(status=state, id=identity, fields=mapped['fields'],
                              goal_status=mapped['status'], progress=mapped['progress'],
                              created_at=mapped['created_at'],
                              last_progress_at=mapped['last_progress_at'],
                              provenance=provenance, creation_signature=signature,
                              revision=old['revision'] if old else 0,
                              archived=old['archived'] if old else False)
            except (ValueError, TypeError, KeyError, OverflowError):
                result['status'] = 'invalid'
                if not result['issues']:
                    result['issues'] = ['记录字段缺失、多余或类型无效']
            results.append(result)
        summary = {status: sum(row['status'] == status for row in results)
                   for status in ('ready', 'existing', 'unassigned', 'foreign_scope',
                                  'unsafe_domain', 'ambiguous', 'invalid', 'conflict',
                                  'duplicate_source_id')}
        value = dict(schema=1, source_ref=source_ref, source_sha256=payload['source_sha256'],
                     scope=scope, records=results, counts=summary, writes=0,
                     requires_explicit_attribution=True, creates_send_permission=False,
                     inherited_defaults=dict(stall_days=options['source_default_stall_days'],
                                             share_cooldown_hours=
                                             options['source_default_share_cooldown_hours']),
                     preview_sha256=None)
        value['preview_sha256'] = _digest(value)
        return value

    def confirm_import(self, scope, payload, *, preview_sha256, request_id, owner_confirmed):
        scope = self._scope(scope)
        if owner_confirmed is not True or type(preview_sha256) is not str \
                or not _HASH.fullmatch(preview_sha256):
            raise PermissionError('explicit source attribution confirmation required')
        request_id = _request_id(request_id)
        identity = _digest(['goal_import', scope, request_id])
        signature = _digest([plain(payload, 262144), preview_sha256])
        now = self._now()
        with self._transaction(scope) as db:
            receipt = db.execute('SELECT data FROM checkpoints '
                                 'WHERE namespace=? AND key=? AND scope=?',
                                 (BATCH_NAMESPACE, identity, scope_key(scope))).fetchone()
            if receipt:
                receipt = json.loads(receipt[0])
                if receipt['signature'] != signature:
                    raise JournalConflict('import request ID reused with a different preview')
                return receipt
            preview = self._preview(db, scope, payload)
            if preview['preview_sha256'] != preview_sha256:
                raise JournalConflict('goal import preview changed')
            if any(row['status'] not in {'ready', 'existing'} for row in preview['records']):
                raise JournalConflict('goal import needs every record mapped and attributed')
            ready = [row for row in preview['records'] if row['status'] == 'ready']
            total = db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
            if total + len(ready) + 1 > self.journal.max_records \
                    or self._count(db, scope) + len(ready) > self.max_goals:
                raise RuntimeError('personal-goal import capacity reached')
            created = []
            for row in ready:
                record = dict(schema=1, id=row['id'], scope=scope,
                              origin='tls_native_personal_goals', fields=row['fields'],
                              status=row['goal_status'], progress=row['progress'], logs=[],
                              applied={}, pending_share=None, created_at=row['created_at'],
                              last_progress_at=row['last_progress_at'],
                              last_activity_at=row['last_progress_at'],
                              completed_at=now if row['goal_status'] == 'completed' else 0.0,
                              stall_notified_at=0.0, share_notified_at=0.0, share_count=0,
                              archived=False, creation_signature=row['creation_signature'],
                              provenance=row['provenance'], import_batch_id=identity)
                self._log(record, kind='imported', progress=row['progress'],
                          evidence='从旧 PC 来源人工确认迁移（来源记录 %s）'
                                   % row['source_id'][:64],
                          evidence_kind='user_reported', now=now)
                created.append(self._write(db, scope, record, 0)['id'])
            receipt = dict(schema=1, id=identity, signature=signature, created_ids=created,
                           existing_ids=[row['id'] for row in preview['records']
                                         if row['status'] == 'existing'],
                           source_ref=preview['source_ref'],
                           source_sha256=preview['source_sha256'])
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (BATCH_NAMESPACE, identity, scope_key(scope), 1, now,
                        canonical(receipt)))
            saved = db.execute('SELECT data FROM checkpoints '
                               'WHERE namespace=? AND key=? AND scope=?',
                               (BATCH_NAMESPACE, identity, scope_key(scope))).fetchone()
            if saved is None or json.loads(saved[0]) != receipt:
                raise RuntimeError('personal-goal import receipt readback mismatch')
            self._scope(scope)
            return receipt

    # -- lifecycle ---------------------------------------------------------

    def stop(self):
        self.active = False

    def close(self):
        self.stop()  # The caller owns the shared journal.
