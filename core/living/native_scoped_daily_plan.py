"""Future, explicitly scoped goal plans on the existing LivingJournal.

This is a goal-only virtual plan, not the old global character daily state.
An administrator can maintain a definition without manufacturing a live chat
lease. A completed virtual activity advances goals only through the original
NativePersonalGoals instance and its current authority. No sender, scheduler,
model call, legacy plan generator or claim_share is used here.
"""
from __future__ import annotations

from datetime import date, datetime, time
import hashlib
import math
import re

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope
from .native_important_dates import date_zone
from .native_personal_goals import NativePersonalGoals, activity_event

NAMESPACE = 'tls.native.scoped_daily_plan.v1'
SOURCE = 'tls.scoped_daily_plan'
MAX_PLANS = 64
MAX_ITEMS = 12
_PLAN = re.compile(r'plan\.[a-f0-9]{64}\Z')
_ITEM = re.compile(r'item\.[a-f0-9]{24}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')


def _digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _text(value, maximum, *, empty=False):
    if type(value) is not str or any(ord(char) < 32 and char not in '\r\n\t' for char in value):
        raise ValueError('plain plan text required')
    value = ' '.join(value.split())
    if len(value) > maximum or (not empty and not value):
        raise ValueError('bounded plan text required')
    return value


def _epoch(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 253402214400:
        raise ValueError('bounded exact plan timestamp required')
    return float(value)


def _revision(value):
    if type(value) is not int or not 1 <= value <= 2 ** 53 - 1:
        raise ValueError('explicit positive revision required')
    return value


class NativeScopedDailyPlans:
    backend = 'native_scoped_daily_plan'

    def __init__(self, journal, *, goals, authorize, authorize_activity=None,
                 goal_reader=None, clock=None, automatic_enabled=False,
                 authorize_automatic=None):
        if (not isinstance(journal, LivingJournal) or not isinstance(goals, NativePersonalGoals)
                or goals.journal is not journal or not callable(authorize)):
            raise ValueError('the existing journal, goal instance and scope authority are required')
        if type(automatic_enabled) is not bool:
            raise ValueError('exact automatic progression flag required')
        self.journal, self.goals, self.authorize = journal, goals, authorize
        self.authorize_activity = authorize_activity
        self.goal_reader = goal_reader or goals.export
        self.clock = journal.clock if clock is None else clock
        self.automatic_enabled = automatic_enabled
        self.authorize_automatic = authorize_automatic
        self.timezone, self.timezone_name = goals.timezone, goals.timezone_name
        self.active = True

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize(dict(scope)) is not True:
            raise PermissionError('scoped daily plan authority unavailable')
        return scope

    def _now(self):
        return _epoch(self.clock())

    def _day(self, value):
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError('ISO calendar date required')
        return value

    def _decode(self, row, scope):
        if row is None:
            return None
        data = row['data']
        if (type(data) is not dict or data.get('schema') != 1 or data.get('scope') != scope
                or data.get('id') != row.get('key', data.get('id'))
                or type(data.get('id')) is not str or not _PLAN.fullmatch(data['id'])
                or data.get('status') not in {'active', 'cancelled'}
                or type(data.get('archived')) is not bool or type(data.get('items')) is not list
                or not 1 <= len(data['items']) <= MAX_ITEMS):
            raise RuntimeError('invalid scoped plan record')
        self._day(data['date'])
        date_zone(data['timezone'])
        seen = set()
        for item in data['items']:
            if (type(item) is not dict or not _ITEM.fullmatch(item.get('id', ''))
                    or item['id'] in seen or item.get('status') not in {'pending', 'completed', 'cancelled'}
                    or item.get('progress_state') not in {'not_started', 'pending', 'waiting_for_scope', 'partial', 'applied'}):
                raise RuntimeError('invalid scoped plan item')
            seen.add(item['id'])
            _text(item['title'], 100)
            _text(item['description'], 300, empty=True)
            _epoch(item['scheduled_at'])
            event = item.get('activity')
            if item['status'] == 'completed':
                checked = activity_event(event)
                if (checked['id'] != self._occurrence(data['id'], item['id'])
                        or checked['source'] != SOURCE or checked['evidence_kind'] != 'roleplay_event'):
                    raise RuntimeError('scoped plan occurrence binding mismatch')
            elif event is not None:
                raise RuntimeError('uncompleted plan cannot carry a completed activity')
        return dict(data, revision=row['revision'], updated_at=row['updated_at'])

    def _get(self, scope, identity):
        if type(identity) is not str or not _PLAN.fullmatch(identity):
            raise ValueError('valid scoped plan ID required')
        return self._decode(self.journal.fetch(NAMESPACE, identity, scope), scope)

    def get(self, scope, identity):
        scope = self._scope(scope)
        row = self._get(scope, identity)
        self._scope(scope)
        return row

    def _write(self, scope, record, revision):
        scope = self._scope(scope)
        data = {key: value for key, value in record.items() if key not in {'revision', 'updated_at'}}
        row = self.journal.put(NAMESPACE, data['id'], scope, plain(data, 65536),
                               expected_revision=revision,
                               authorize=lambda: self._scope(scope) == scope)
        return self._decode(dict(row, key=data['id']), scope)

    def list(self, scope, *, day=None, include_archived=False, limit=20, offset=0):
        scope = self._scope(scope)
        if type(include_archived) is not bool or type(limit) is not int or not 1 <= limit <= MAX_PLANS \
                or type(offset) is not int or not 0 <= offset <= MAX_PLANS:
            raise ValueError('bounded plan pagination required')
        if day is not None:
            day = self._day(day)
        rows = self.journal.list(NAMESPACE, scope, limit=MAX_PLANS + 1)
        if len(rows) > MAX_PLANS:
            raise RuntimeError('scoped plan capacity exceeded')
        records = [self._decode(row, scope) for row in rows]
        records = [row for row in records if (include_archived or not row['archived'])
                   and (day is None or row['date'] == day)]
        records.sort(key=lambda row: (row['date'], row['created_at'], row['id']), reverse=True)
        self._scope(scope)
        return dict(records=records[offset:offset + limit], total=len(records), limit=limit, offset=offset)

    def _items(self, values, identity, day, *, previous=None, check_future=True, zone=None):
        if type(values) is not list or not 1 <= len(values) <= MAX_ITEMS:
            raise ValueError('a plan requires 1–12 items')
        prior = {item['id']: item for item in (previous or [])}
        result, seen = [], set()
        now = self._now()
        for index, value in enumerate(values):
            if type(value) is not dict or set(value) - {'id', 'title', 'description', 'scheduled_at'}:
                raise ValueError('unknown plan item field')
            title = _text(value.get('title'), 100)
            description = _text(value.get('description', ''), 300, empty=True)
            scheduled = _epoch(value.get('scheduled_at'))
            if datetime.fromtimestamp(scheduled, self.timezone if zone is None else zone).date().isoformat() != day:
                raise ValueError('item timestamp must belong to the selected role calendar day')
            item_id = value.get('id') or 'item.' + _digest([identity, index, title, scheduled])[:24]
            if type(item_id) is not str or not _ITEM.fullmatch(item_id) or item_id in seen:
                raise ValueError('unique stable item ID required')
            seen.add(item_id)
            old = prior.get(item_id)
            if old is not None and old['status'] != 'pending':
                if (title, description, scheduled) != (old['title'], old['description'], old['scheduled_at']):
                    raise JournalConflict('completed or cancelled item history cannot be rewritten')
                result.append(dict(old))
                continue
            if check_future and scheduled < now:
                raise ValueError('new or edited plan items must be in the future')
            result.append(dict(id=item_id, title=title, description=description, scheduled_at=scheduled,
                               status='pending', activity=None, completed_at=None, cancelled_at=None,
                               progress_state='not_started', progress_report=None, completion_request=None))
        if any(item['status'] != 'pending' and item['id'] not in seen for item in (previous or [])):
            raise JournalConflict('completed or cancelled item history must be retained')
        return result

    def create(self, scope, request_id, *, title, day, items, actor='administrator', origin='manual', generation_limit=None):
        scope = self._scope(scope)
        if type(request_id) is not str or not _REQUEST.fullmatch(request_id):
            raise ValueError('stable creation request ID required')
        title, day, actor = _text(title, 80), self._day(day), _text(actor, 120)
        if origin not in {'manual', 'goal_definition_template'}:
            raise ValueError('explicit plan definition origin required')
        identity = 'plan.' + _digest([scope, request_id])
        with self.journal._lock:
            existing = self._get(scope, identity)
            normalized = self._items(items, identity, day, check_future=existing is None,
                                     zone=date_zone(existing['timezone']) if existing else None)
            signature = _digest([title, day, normalized, actor, origin, generation_limit])
            if existing is not None:
                if existing['creation_signature'] != signature:
                    raise JournalConflict('creation request already names a different plan')
                return existing
            if date.fromisoformat(day) < datetime.fromtimestamp(self._now(), self.timezone).date():
                raise ValueError('only current or future plans can be created')
            if len(self.journal.list(NAMESPACE, scope, limit=MAX_PLANS + 1)) >= MAX_PLANS:
                raise RuntimeError('scoped plan capacity reached')
            record = dict(schema=1, id=identity, scope=scope, title=title, date=day,
                          timezone=self.timezone_name, items=normalized, status='active', archived=False,
                          created_at=self._now(), creation_signature=signature,
                          provenance=dict(kind='administrator_maintained_definition', actor=actor,
                                          origin=origin, request_id=request_id,
                                          generation_limit=generation_limit,
                                          creates_runtime_lease=False, sdk_persona_proof=None))
            return self._write(scope, record, 0)

    def generate(self, scope, request_id, *, day, limit=6, actor='administrator'):
        """Make an editable future draft from real goal definitions, without LLM side effects."""
        scope, day = self._scope(scope), self._day(day)
        if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
            raise ValueError('bounded draft item count required')
        identity = 'plan.' + _digest([scope, request_id])
        existing = self._get(scope, identity)
        if existing is not None:
            if (existing['date'] != day or existing['provenance'].get('origin') != 'goal_definition_template'
                    or existing['provenance'].get('generation_limit') != limit
                    or existing['provenance'].get('actor') != actor):
                raise JournalConflict('generation request already names a different plan')
            return existing
        snapshot = self.goal_reader(scope)
        rows = snapshot['records'] if isinstance(snapshot, dict) else snapshot
        rows = [row for row in rows if row.get('status') == 'active' and not row.get('archived')]
        if not rows:
            raise ValueError('no active scoped goal definition is available for a draft')
        target = date.fromisoformat(day)
        start = datetime.combine(target, time(9, 0), self.timezone).timestamp()
        current = self._now()
        if start <= current:
            start = (math.floor(current / 1800) + 1) * 1800
        items = []
        for index, row in enumerate(rows[:limit]):
            at = start + index * 3600
            if datetime.fromtimestamp(at, self.timezone).date() != target:
                break
            fields = row['fields']
            items.append(dict(title=(fields.get('next_step') or fields['title'])[:100],
                              description=('为角色目标“%s”安排的虚构活动；提出计划不代表已经完成。'
                                           % fields['title'])[:300], scheduled_at=at))
        if not items:
            raise ValueError('no future time remains in that day; select a later date')
        return self.create(scope, request_id, title='目标专用日计划', day=day, items=items,
                           actor=actor, origin='goal_definition_template', generation_limit=limit)

    def update(self, scope, identity, *, expected_revision, title=None, items=None):
        scope = self._scope(scope)
        with self.journal._lock:
            row = self._get(scope, identity)
            if row is None:
                raise KeyError('scoped plan absent')
            if row['revision'] != _revision(expected_revision):
                raise JournalConflict('scoped plan revision changed')
            if row['archived'] or row['status'] != 'active':
                raise ValueError('restore an active plan before editing it')
            if title is not None:
                row['title'] = _text(title, 80)
            if items is not None:
                row['items'] = self._items(items, identity, row['date'], previous=row['items'],
                                           zone=date_zone(row['timezone']))
            return self._write(scope, row, expected_revision)

    @staticmethod
    def _occurrence(plan_id, item_id):
        return 'daily.' + _digest([plan_id, item_id])

    def _progress_allowed(self, scope):
        try:
            return (self.goals.active is True and self.goals.journal is self.journal
                    and (self.authorize_activity is None or self.authorize_activity(dict(scope)) is True)
                    and self.goals._scope(scope) == scope)
        except (PermissionError, RuntimeError):
            return False

    def complete_item(self, scope, identity, item_id, *, expected_revision, request_id,
                      actor='administrator', occurred_at=None):
        scope = self._scope(scope)
        if type(request_id) is not str or not _REQUEST.fullmatch(request_id):
            raise ValueError('stable completion request ID required')
        with self.journal._lock:
            row = self._get(scope, identity)
            if row is None:
                raise KeyError('scoped plan absent')
            item = next((item for item in row['items'] if item['id'] == item_id), None)
            if item is None:
                raise KeyError('scoped plan item absent')
            if item['status'] == 'completed':
                return row
            if row['revision'] != _revision(expected_revision):
                raise JournalConflict('scoped plan revision changed')
            if row['archived'] or row['status'] != 'active' or item['status'] != 'pending':
                raise ValueError('only a pending item in an active plan can be completed')
            current = self._now()
            occurred = current if occurred_at is None else _epoch(occurred_at)
            if occurred > current + 30:
                raise ValueError('completion cannot occur after its receipt')
            event = activity_event(dict(id=self._occurrence(identity, item_id),
                text='虚构角色活动完成：%s。%s' % (item['title'], item['description']),
                occurred_at=occurred, evidence_kind='roleplay_event', source=SOURCE))
            item.update(status='completed', completed_at=occurred, activity=event,
                        progress_state='pending', completion_request=request_id,
                        completed_by=_text(actor, 120))
            self._write(scope, row, expected_revision)
        return self.apply_completed(scope, identity)

    @staticmethod
    def _report(report):
        skipped = report.get('skipped', [])
        return dict(event_id=report['event_id'], matched=len(report.get('matched', [])),
                    advanced=len(report.get('advanced', [])), duplicate=len(report.get('duplicate', [])),
                    skipped=len(skipped), retry_required=any(row.get('reason') == 'concurrent_revision' for row in skipped),
                    progressed=report.get('progressed') is True, delivery='none')

    def apply_completed(self, scope, identity):
        """Resume the stable occurrences; no unconditional repeat and no new permission."""
        scope = self._scope(scope)
        with self.journal._lock:
            row = self._get(scope, identity)
            if row is None:
                raise KeyError('scoped plan absent')
            if row['archived']:
                raise ValueError('restore the plan before applying its completed activities')
            for item_id in [item['id'] for item in row['items']]:
                item = next(item for item in row['items'] if item['id'] == item_id)
                if item['status'] != 'completed' or item['progress_state'] == 'applied':
                    continue
                if not self._progress_allowed(scope):
                    item['progress_state'] = 'waiting_for_scope'
                    row = self._write(scope, row, row['revision'])
                    break
                # The durable item contains the event before the first goal write.
                # A crash between per-goal commits and this receipt can replay only
                # that same ID; the original goal ledger decides duplicate/old events.
                try:
                    report = self.goals.apply_activity(scope, item['activity'])
                except PermissionError:
                    item['progress_state'] = 'waiting_for_scope'
                    row = self._write(scope, row, row['revision'])
                    break
                summary = self._report(report)
                item['progress_report'] = summary
                item['progress_state'] = 'partial' if summary['retry_required'] else 'applied'
                row = self._write(scope, row, row['revision'])
            return row

    def cancel_item(self, scope, identity, item_id, *, expected_revision):
        return self._change(scope, identity, expected_revision, item_id=item_id, action='cancel_item')

    def cancel(self, scope, identity, *, expected_revision):
        return self._change(scope, identity, expected_revision, action='cancel')

    def archive(self, scope, identity, *, expected_revision):
        return self._change(scope, identity, expected_revision, action='archive')

    def restore(self, scope, identity, *, expected_revision):
        return self._change(scope, identity, expected_revision, action='restore')

    def _change(self, scope, identity, revision, *, action, item_id=None):
        scope = self._scope(scope)
        with self.journal._lock:
            row = self._get(scope, identity)
            if row is None:
                raise KeyError('scoped plan absent')
            if row['revision'] != _revision(revision):
                raise JournalConflict('scoped plan revision changed')
            if action in {'archive', 'restore'}:
                row['archived'] = action == 'archive'
            else:
                found = False
                for item in row['items']:
                    if item_id is not None and item['id'] != item_id:
                        continue
                    found = True
                    if item['status'] == 'completed' and item_id is not None:
                        raise ValueError('completed goal progress is history, not a cancellable pending action')
                    if item['status'] == 'pending':
                        item.update(status='cancelled', cancelled_at=self._now())
                if not found:
                    raise KeyError('scoped plan item absent')
                if action == 'cancel':
                    row['status'] = 'cancelled'
            return self._write(scope, row, revision)

    def advance_due(self, scope, source_event):
        """Optional future host hook; off until a real source/old-writer handoff exists."""
        scope = self._scope(scope)
        if (not self.automatic_enabled or not callable(self.authorize_automatic)
                or self.authorize_automatic(dict(scope), source_event) is not True):
            raise PermissionError('automatic scoped plan progression is not enabled or sourced')
        event = activity_event(source_event)
        if event['evidence_kind'] != 'roleplay_event' or event['source'] != SOURCE + '.clock':
            raise ValueError('a sourced virtual clock event is required')
        if event['occurred_at'] > self._now() + 30:
            raise ValueError('virtual clock event is in the future')
        results = []
        for row in self.list(scope, limit=MAX_PLANS)['records']:
            if row['status'] != 'active':
                continue
            for item in list(row['items']):
                if item['status'] == 'pending' and item['scheduled_at'] <= event['occurred_at']:
                    row = self.complete_item(scope, row['id'], item['id'], expected_revision=row['revision'],
                        request_id='clock.' + _digest([event['id'], row['id'], item['id']]),
                        actor='sourced_virtual_clock', occurred_at=event['occurred_at'])
            results.append(row)
        return dict(records=results, delivery='none', claims_share=False)

    def diagnostics(self, scope=None):
        result = dict(active=self.active, automatic_enabled=self.automatic_enabled,
                      timezone_name=self.timezone_name,
                      automatic_source_hook_present=callable(self.authorize_automatic),
                      virtual_evidence='roleplay_event', legacy_global_plan_retained=True,
                      claims_share=False, sends_messages=False, owns_scheduler=False)
        if scope is None:
            return dict(result, progress_authorized=None, complete_scope_required=True)
        scope = self._scope(scope)
        allowed = self._progress_allowed(scope)
        return dict(result, progress_authorized=allowed,
                    material_only_without_live_scope=not allowed, complete_scope_required=False)

    def stop(self):
        self.active = False

    def close(self):
        self.stop()
