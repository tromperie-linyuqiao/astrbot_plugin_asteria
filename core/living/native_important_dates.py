"""TLS-owned important-date definitions and future calendar projections.

Uses the existing journal, complete private scope and revision CAS. Nothing
here schedules, sends, imports PC at runtime, writes its data, or proves that
an event happened. Disk methods belong off the Host event loop. Legacy import
accepts detached, explicitly attributed source records; hashes identify the
operator's artifact, not an attestation of production source permission.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key

NAMESPACE = 'tls.native.important_dates.v1'
BATCH_NAMESPACE = 'tls.native.important_dates.batch.v1'
MAX_DATES = 500
FIELDS = frozenset(('title', 'date', 'type', 'note', 'enabled', 'repeat_yearly',
                    'remind_days', 'priority', 'timezone'))
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_DATE = re.compile(r'(?:\d{4}-)?\d{2}-\d{2}\Z')
_OFFSET = re.compile(r'UTC([+-])(\d{2}):(\d{2})\Z')


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _text(value, maximum, *, empty=False):
    if type(value) is not str or any(ord(c) < 32 and c not in '\r\n\t' for c in value):
        raise ValueError('plain bounded date text required')
    value = ' '.join(value.split())
    if len(value) > maximum or (not empty and not value):
        raise ValueError('plain bounded date text required')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded exact integer required')
    return value


def date_zone(name):
    """Explicit IANA zone or fixed UTC offset; never the machine's local zone."""
    name = _text(name, 80)
    if name == 'UTC':
        return timezone.utc
    match = _OFFSET.fullmatch(name)
    if match:
        hours, minutes = int(match[2]), int(match[3])
        if hours > 14 or minutes > 59 or (hours == 14 and minutes):
            raise ValueError('invalid explicit UTC offset')
        delta = timedelta(hours=hours, minutes=minutes)
        return timezone(delta if match[1] == '+' else -delta)
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('installed explicit date timezone required') from None


def next_occurrence(value, repeat_yearly, today):
    """Next real Gregorian day; leap-day anniversaries use the next leap year.

    Unlike old PC's 1900 strptime and current/next-year-only check, 02-29 is
    accepted and never guessed as 02-28 or a lunar date. Ordinary valid dates
    retain the old next-date semantics. Past one-time dates stay past here;
    relevant() excludes them rather than converting them to yearly dates.
    """
    if type(value) is not str or not _DATE.fullmatch(value) or type(repeat_yearly) is not bool or type(today) is not date:
        raise ValueError('exact Gregorian date, repetition and local day required')
    short = len(value) == 5
    try:
        base = date.fromisoformat(('2000-' if short else '') + value)
    except ValueError:
        raise ValueError('invalid Gregorian date') from None
    if not repeat_yearly:
        if short:
            raise ValueError('one-time date requires an explicit year')
        return base
    for year in range(today.year, min(today.year + 9, 10000)):
        try:
            candidate = date(year, base.month, base.day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def edit_fields(values):
    if type(values) is not dict or set(values) - FIELDS or not {'title', 'date', 'timezone'} <= set(values):
        raise ValueError('explicit date fields required')
    value = dict(title=_text(values['title'], 40), date=_text(values['date'], 10),
                 type=_text(values.get('type', '重要日期'), 30), note=_text(values.get('note', ''), 120, empty=True),
                 timezone=_text(values['timezone'], 80), enabled=values.get('enabled', True),
                 repeat_yearly=values.get('repeat_yearly', len(values['date']) == 5),
                 remind_days=values.get('remind_days', 7), priority=values.get('priority', 50))
    if type(value['enabled']) is not bool or type(value['repeat_yearly']) is not bool:
        raise ValueError('exact date flags required')
    _integer(value['remind_days'], 0, 365)
    _integer(value['priority'], 0, 1000)
    date_zone(value['timezone'])
    next_occurrence(value['date'], value['repeat_yearly'], date(2000, 1, 1))
    return value


def relevant_dates(entries, *, now):
    """Detached upcoming definitions, sorted by day then priority; no action."""
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now <= 253402214400:
        raise ValueError('bounded explicit clock required')
    result = []
    for entry in entries:
        if entry.get('archived') or not entry.get('enabled'):
            continue
        today = datetime.fromtimestamp(now, date_zone(entry['timezone'])).date()
        upcoming = next_occurrence(entry['date'], entry['repeat_yearly'], today)
        if upcoming is None:
            continue
        days = (upcoming - today).days
        if 0 <= days <= entry['remind_days']:
            result.append(dict(entry, next_date=upcoming.isoformat(), days_until=days,
                               calendar_policy='next_valid_gregorian_year'))
    return sorted(result, key=lambda row: (row['days_until'], -row['priority']))


class NativeImportantDates:
    backend = 'native_important_dates'

    def __init__(self, journal, *, authorize, clock=None):
        if not isinstance(journal, LivingJournal) or not callable(authorize):
            raise ValueError('existing journal and scope authorization required')
        self.journal, self.authorize = journal, authorize
        self.clock = journal.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('date clock required')
        self.active = True

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize(dict(scope)) is not True:
            raise PermissionError('important-date scope unavailable')
        return scope

    @contextmanager
    def _transaction(self, scope):
        with self.journal._transaction() as db:
            self._scope(scope)
            yield db
            # Keep the operation-local resource check after the last nested
            # write/readback and before COMMIT, including idempotent returns.
            self._scope(scope)

    def _rows(self, db, scope):
        rows = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? ORDER BY key LIMIT ?',
                          (NAMESPACE, scope_key(scope), MAX_DATES + 1)).fetchall()
        if len(rows) > MAX_DATES:
            raise RuntimeError('important-date scope capacity exceeded')
        return [self._decode(row, scope) for row in rows]

    def _decode(self, row, scope):
        value = json.loads(row['data'])
        if (type(value) is not dict or type(value.get('schema')) is not int or value.get('schema') != 1 or value.get('id') != row['key']
                or value.get('scope') != scope or value.get('origin') != 'tls_native_important_dates'
                or type(value.get('archived')) is not bool or edit_fields(value['fields']) != value['fields']
                or type(value.get('creation_signature')) is not str or not _HASH.fullmatch(value['creation_signature'])
                or type(value.get('created_at')) not in (int, float) or not math.isfinite(value['created_at'])
                or not 0 < value['created_at'] <= 253402214400
                or type(value.get('provenance')) is not dict
                or value['provenance'].get('kind') not in {'user_explicit', 'legacy_import'}):
            raise RuntimeError('invalid important-date provenance')
        return dict(value, revision=row['revision'], updated_at=row['updated'])

    def _get(self, db, scope, identity):
        identity = _text(identity, 100)
        row = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                         (NAMESPACE, identity, scope_key(scope))).fetchone()
        return self._decode(row, scope) if row else None

    def _write(self, db, scope, value, revision):
        _integer(revision, 0, 2**53 - 1)
        self._scope(scope)
        if revision == 0:
            if len(self._rows(db, scope)) >= MAX_DATES:
                raise RuntimeError('important-date scope capacity reached')
            if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
                raise RuntimeError('checkpoint capacity reached')
        updated = self.clock()
        clean = {key: item for key, item in value.items() if key not in {'revision', 'updated_at'}}
        encoded = canonical(plain(clean, 16384))
        if revision == 0:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (NAMESPACE, value['id'], scope_key(scope), 1, updated, encoded))
        else:
            changed = db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND key=? AND scope=? AND revision=?',
                                 (revision + 1, updated, encoded, NAMESPACE, value['id'], scope_key(scope), revision)).rowcount
            if changed != 1:
                raise JournalConflict('important-date revision conflict')
        expected = dict(clean, revision=revision + 1, updated_at=updated)
        saved = self._get(db, scope, value['id'])
        if saved != expected:
            raise RuntimeError('important-date write readback mismatch')
        self._scope(scope)
        return saved

    def create(self, scope, request_id, **fields):
        scope = self._scope(scope)
        request_id = _text(request_id, 128)
        fields = edit_fields(fields)
        identity = 'date.' + _digest(['new', scope, request_id])
        signature = _digest(fields)
        with self._transaction(scope) as db:
            existing = self._get(db, scope, identity)
            if existing:
                if existing['creation_signature'] != signature:
                    raise JournalConflict('date request ID reused with different content')
                self._scope(scope)
                return existing
            value = dict(schema=1, id=identity, scope=scope, origin='tls_native_important_dates',
                         fields=fields, archived=False, created_at=self.clock(), creation_signature=signature,
                         provenance=dict(kind='user_explicit', source_ref=request_id))
            return self._write(db, scope, value, 0)

    def get(self, scope, identity):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            value = self._get(self.journal._db, scope, identity)
        self._scope(scope)
        return value

    def list(self, scope, *, include_archived=False, limit=50, offset=0):
        scope = self._scope(scope)
        if type(include_archived) is not bool:
            raise ValueError('exact archive option required')
        _integer(limit, 1, 100); _integer(offset, 0, MAX_DATES)
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self._rows(self.journal._db, scope)
        self._scope(scope)
        return [row for row in rows if include_archived or not row['archived']][offset:offset + limit]

    def export(self, scope, *, include_archived=True):
        """One bounded definition snapshot; not an import or a send plan."""
        scope = self._scope(scope)
        if type(include_archived) is not bool:
            raise ValueError('exact archive option required')
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self._rows(self.journal._db, scope)
        self._scope(scope)
        rows = [row for row in rows if include_archived or not row['archived']]
        return dict(schema='tls.native.important_dates.export.v1', scope=scope,
                    records=rows, total=len(rows), exported_at=self.clock(),
                    definitions_only=True, creates_send_permission=False)

    def update(self, scope, identity, *, expected_revision, **changes):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2**53 - 1)
        if type(changes) is not dict or not changes or set(changes) - FIELDS:
            raise ValueError('explicit editable date fields required')
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('important date absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('important-date revision conflict')
            row['fields'] = edit_fields(dict(row['fields'], **changes))
            return self._write(db, scope, row, expected_revision)

    def _archive(self, scope, identity, expected_revision, archived):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2**53 - 1)
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('important date absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('important-date revision conflict')
            if row['archived'] == archived:
                self._scope(scope)
                return row
            row['archived'] = archived
            return self._write(db, scope, row, expected_revision)

    def archive(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, True)

    def restore(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, False)

    def _preview(self, db, scope, payload):
        payload = plain(payload, 262144)
        keys = {'schema', 'source_plugin', 'source_ref', 'source_sha256', 'source_default_remind_days', 'records'}
        if (type(payload) is not dict or set(payload) != keys or type(payload['schema']) is not int or payload['schema'] != 1
                or payload['source_plugin'] != 'private_companion' or type(payload['source_sha256']) is not str
                or not _HASH.fullmatch(payload['source_sha256']) or type(payload['records']) is not list
                or not 1 <= len(payload['records']) <= 200):
            raise ValueError('bounded explicit PC source artifact required')
        source_ref = _text(payload['source_ref'], 128)
        fallback = _integer(payload['source_default_remind_days'], 0, 365)
        results, seen = [], set()
        for item in payload['records']:
            result = dict(status='invalid', source_id='', source_record_sha256=_digest(item))
            try:
                if type(item) is not dict or set(item) != {'source_id', 'record', 'target_scope', 'timezone'}:
                    raise ValueError
                source_id = _text(item['source_id'], 128)
                raw = item['record']
                if type(raw) is not dict or raw.get('id') != source_id:
                    raise ValueError
                result.update(source_id=source_id, source_record_sha256=_digest(raw))
                if source_id in seen:
                    result['status'] = 'duplicate_source_id'
                    results.append(result); continue
                seen.add(source_id)
                if item['target_scope'] is None:
                    result['status'] = 'unassigned'
                    results.append(result); continue
                if private_scope(item['target_scope']) != scope:
                    result['status'] = 'foreign_scope'
                    results.append(result); continue
                fields = {key: raw[key] for key in FIELDS - {'timezone'} if key in raw}
                fields.setdefault('remind_days', fallback)
                fields.setdefault('repeat_yearly', True)
                fields['timezone'] = item['timezone']
                fields = edit_fields(fields)
                provenance = dict(kind='legacy_import', source_plugin='private_companion', source_ref=source_ref,
                                  source_sha256=payload['source_sha256'], source_id=source_id,
                                  source_record_sha256=_digest(raw), attribution='operator_explicit')
                identity = 'date.' + _digest(['import', scope, source_ref, source_id])
                # A different whole-PC snapshot need not duplicate unchanged
                # source records. Keep the first artifact SHA as provenance;
                # stable source identity + exact raw-record digest own dedup.
                signature = _digest([fields, {key: value for key, value in provenance.items() if key != 'source_sha256'}])
                old = self._get(db, scope, identity)
                status = 'ready' if old is None else 'existing' if old['creation_signature'] == signature else 'conflict'
                result.update(status=status, id=identity, fields=fields, provenance=provenance,
                              creation_signature=signature, revision=old['revision'] if old else 0,
                              archived=old['archived'] if old else False)
            except (ValueError, TypeError, KeyError, OverflowError):
                result['status'] = 'invalid'
            results.append(result)
        summary = {status: sum(row['status'] == status for row in results)
                   for status in ('ready', 'existing', 'unassigned', 'foreign_scope', 'invalid', 'conflict', 'duplicate_source_id')}
        value = dict(schema=1, source_ref=source_ref, source_sha256=payload['source_sha256'],
                     scope=scope, records=results, counts=summary, writes=0,
                     requires_explicit_attribution=True, creates_send_permission=False)
        value['preview_sha256'] = _digest(value)
        return value

    def preview_import(self, scope, payload):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            result = self._preview(self.journal._db, scope, payload)
        self._scope(scope)
        return result

    def confirm_import(self, scope, payload, *, preview_sha256, request_id, owner_confirmed):
        scope = self._scope(scope)
        if owner_confirmed is not True or type(preview_sha256) is not str or not _HASH.fullmatch(preview_sha256):
            raise PermissionError('explicit source attribution confirmation required')
        identity = _digest(['date_import', scope, _text(request_id, 128)])
        signature = _digest([plain(payload, 262144), preview_sha256])
        with self._transaction(scope) as db:
            receipt = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                                 (BATCH_NAMESPACE, identity, scope_key(scope))).fetchone()
            if receipt:
                receipt = json.loads(receipt[0])
                if receipt['signature'] != signature:
                    raise JournalConflict('import request ID reused with a different preview')
                self._scope(scope)
                return receipt
            preview = self._preview(db, scope, payload)
            if preview['preview_sha256'] != preview_sha256 or any(row['status'] not in {'ready', 'existing'} for row in preview['records']):
                raise JournalConflict('date import preview changed or attribution incomplete')
            ready = [row for row in preview['records'] if row['status'] == 'ready']
            total = db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
            if total + len(ready) + 1 > self.journal.max_records or len(self._rows(db, scope)) + len(ready) > MAX_DATES:
                raise RuntimeError('important-date import capacity reached')
            created = []
            for row in ready:
                value = dict(schema=1, id=row['id'], scope=scope, origin='tls_native_important_dates',
                             fields=row['fields'], archived=False, created_at=self.clock(),
                             creation_signature=row['creation_signature'], provenance=row['provenance'], import_batch_id=identity)
                created.append(self._write(db, scope, value, 0)['id'])
            receipt = dict(schema=1, id=identity, signature=signature, created_ids=created,
                           existing_ids=[row['id'] for row in preview['records'] if row['status'] == 'existing'],
                           source_ref=preview['source_ref'], source_sha256=preview['source_sha256'])
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (BATCH_NAMESPACE, identity, scope_key(scope), 1, self.clock(), canonical(receipt)))
            saved = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                               (BATCH_NAMESPACE, identity, scope_key(scope))).fetchone()
            if saved is None or json.loads(saved[0]) != receipt:
                raise RuntimeError('important-date import receipt readback mismatch')
            self._scope(scope)
            return receipt

    def context_generation(self, scope):
        try:
            scope = self._scope(scope)
            with self.journal._lock:
                self.journal._ensure_open()
                rows = self._rows(self.journal._db, scope)
            now = self.clock()
            days = tuple(sorted({(row['fields']['timezone'], datetime.fromtimestamp(now, date_zone(row['fields']['timezone'])).date().isoformat())
                                 for row in rows if not row['archived'] and row['fields']['enabled']}))
            self._scope(scope)
            return ('native_important_dates', id(self), tuple((row['id'], row['revision']) for row in rows), days)
        except Exception:
            return None

    def context_material(self, scope, *, limit=32):
        scope = self._scope(scope)
        _integer(limit, 1, 64)
        generation = self.context_generation(scope)
        if generation is None:
            raise PermissionError('important-date material unavailable')
        now = self.clock()
        with self.journal._lock:
            rows = self._rows(self.journal._db, scope)
        flat = [dict(row['fields'], id=row['id'], archived=row['archived'], record=row) for row in rows]
        result = []
        for value in relevant_dates(flat, now=now)[:limit]:
            row, zone = value['record'], date_zone(value['timezone'])
            local_today = datetime.fromtimestamp(now, zone).date()
            # Expiry fences the derived local-day projection, not the durable
            # definition. occurred_at is this read-only calculation's time;
            # created_at keeps the actual registration time unchanged.
            expires = datetime.combine(local_today + timedelta(days=1), time.min, zone).timestamp()
            when = '今天' if value['days_until'] == 0 else f"{value['days_until']} 天后"
            content = (f"已登记的重要日期定义：{value['title']}｜{value['next_date']}（{when}，{value['timezone']}）"
                       f"｜类型：{value['type']}｜备注：{value['note']}。仅未来日期投影，不证明已发生或送达；不代表已设发送提醒。")
            result.append(dict(id=row['id'], canonical_key=row['id'], content=content,
                owner_bot_id=scope['bot_id'], persona_id=scope['character_id'], platform=scope['platform'],
                scope='private', session_id=scope['session_id'], visibility='bot_self',
                subject=dict(kind='bot', id=scope['bot_id']), object=dict(kind='user', id=scope['user_id']),
                memory_type='companion_note', source_plugin='tls_native_important_dates', reality_level='bot_action',
                lifecycle='active', validity_status='active', review_status='manual', sensitivity='private',
                sayability='direct', mention_policy='when_relevant', confidence=1., created_at=row['created_at'],
                occurred_at=now, updated_at=row['updated_at'], valid_to=expires,
                context_metadata=dict(status='active', timezone='UTC', expires_at=expires,
                    projection_kind='important_date_definition', projection_computed_at=now,
                    source_created_at=row['created_at'], next_date=value['next_date'],
                    date_timezone=value['timezone'], source_record_sha256=row['provenance'].get('source_record_sha256'),
                    definition_revision=row['revision'], calendar_policy=value['calendar_policy'])))
        if generation != self.context_generation(scope):
            raise JournalConflict('important-date generation changed during read')
        return result

    def stop(self):
        self.active = False

    def close(self):
        self.stop()  # The caller owns the shared journal.
