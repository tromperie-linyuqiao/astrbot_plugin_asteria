"""Recurring memo/one-shot timer orchestration on the existing reminder authority.

No worker, owner grant or database is created. The host must route this object's
final task fence through its existing SDK adapter before enabling the source.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
from datetime import datetime
from ..journal import JournalConflict
from ..models import canonical, private_scope, scope_key
from ..native_memo_notes import NativeMemoNotes, _text, _integer, _time
from ..reminders import ReminderService
from ..delivery_store import DeliveryConflict
from .recurrence import advance_due
from ..native_important_dates import date_zone

NAMESPACE = 'tls.native.pc.memo_execution.v1'
ACTIONS = 'tls.native.pc.memo_actions.v1'
TIMERS = 'tls.native.pc.timers.v1'
_UNKNOWN = {'sending', 'unknown', 'quarantined'}
_TERMINAL = {'confirmed', 'failed', 'cancelled', 'expired'}


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


class NativePCMemoScheduler:
    def __init__(self, notes, reminders, *, authorize, clock=None, timezone='Asia/Shanghai'):
        if not isinstance(notes, NativeMemoNotes) or not isinstance(reminders, ReminderService) or not callable(authorize):
            raise ValueError('existing memo and reminder services required')
        self.notes, self.reminders, self.journal, self.authorize = notes, reminders, notes.journal, authorize
        self.clock = clock or notes.clock
        self.timezone = timezone; date_zone(timezone)
        self._bindings = (notes, reminders, self.journal, authorize, self.clock)
        self._serial = asyncio.Lock(); self.active = True

    def _scope(self, scope, source='memo_note'):
        scope = private_scope(scope)
        if (not self.active or any(a is not b for a, b in zip(self._bindings, (self.notes, self.reminders, self.journal, self.authorize, self.clock)))
                or self.authorize(dict(scope), source) is not True):
            raise PermissionError('native PC source is not the current executor')
        self.notes._scope(scope); self.reminders._scope(scope)
        return scope

    def _read(self, ns, key, scope):
        row = self.journal.fetch(ns, key, scope)
        if row is not None and (type(row['data']) is not dict or row['data'].get('scope') != scope or row['data'].get('schema') != 1):
            raise RuntimeError('invalid PC execution checkpoint')
        if row is not None:
            data = row['data']
            if ns == NAMESPACE:
                required = {'schema','scope','memo_id','consent_id','record_revision','cycle','source_signature','legacy_disposition','legacy_state','occurrence_source','sequence','phase','last_confirmed_at','not_before'}
                if (not required <= set(data) or set(data)-required-{'materialization_due'} or data['memo_id'] != key
                        or data['legacy_disposition'] not in {'not_pending','confirmed','unknown'}
                        or data['phase'] not in {'idle','materializing','confirmed','unknown'}
                        or type(data['legacy_state']) is not dict): raise RuntimeError('invalid memo execution binding')
                _integer(data['record_revision'],1); _integer(data['sequence']); _text(data['consent_id'],128)
                for field in ('cycle','source_signature'):
                    if type(data[field]) is not str or not re.fullmatch('[a-f0-9]{64}',data[field]): raise RuntimeError('invalid memo lineage')
                if data['occurrence_source'] is not None and (type(data['occurrence_source']) is not str or not re.fullmatch('pc\\.memo:[a-f0-9]{64}',data['occurrence_source'])): raise RuntimeError('invalid memo occurrence source')
                for field in ('last_confirmed_at','not_before'): _time(data[field])
                if 'materialization_due' in data: _time(data['materialization_due'],zero=False)
            elif ns == TIMERS:
                if set(data) != {'schema','scope','source_id','original_timer_id','signature','due_at','text','consent_id','phase'} or data['source_id'] != key or data['phase'] not in {'not_pending','confirmed','unknown'}:
                    raise RuntimeError('invalid native timer binding')
                _text(data['original_timer_id'],128); _text(data['text'],3900,multiline=True); _text(data['consent_id'],128); _time(data['due_at'],zero=False)
                if key != 'pc.timer:' + digest([scope,data['original_timer_id']]) or data['signature'] != digest([data['original_timer_id'],data['due_at'],data['text'],data['consent_id'],data['phase']]): raise RuntimeError('invalid native timer lineage')
            elif ns == ACTIONS:
                if set(data) != {'schema','scope','signature','record_id','revision','expected_revision','action','external_record_modified','delivery_confirmed'} or data['action'] != 'complete' or data['external_record_modified'] is not False or data['delivery_confirmed'] is not False:
                    raise RuntimeError('invalid recurring completion receipt')
        return row

    def _put(self, ns, key, scope, data, revision):
        return self.journal.put(ns, key, scope, dict(data, schema=1, scope=scope), expected_revision=revision,
            authorize=lambda: self._scope(scope, 'timer' if ns == TIMERS else 'memo_note') == scope)

    def bind_memo(self, scope, identity, *, expected_revision, consent_id, legacy_disposition='not_pending', operation_guard=None):
        scope = self._scope(scope); consent_id = _text(consent_id, 128)
        if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
        if legacy_disposition not in {'not_pending', 'confirmed', 'unknown'}:
            raise ValueError('explicit detached legacy delivery disposition required')
        with self.journal._transaction() as db:
            if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
            row = self.notes._existing(db, scope, identity, expected_revision)
            prior = self._read(NAMESPACE, identity, scope)
            if prior:
                if prior['data']['consent_id'] != consent_id: raise JournalConflict('memo consent binding changed')
                return prior['data']
            imported = row['provenance']['kind'] == 'legacy_import'
            if not imported and legacy_disposition != 'not_pending': raise ValueError('legacy outcome only applies to imported notes')
            data = dict(schema=1, scope=scope, memo_id=identity, consent_id=consent_id,
                record_revision=row['revision'], cycle=self._cycle(row), source_signature=row['creation_signature'],
                legacy_disposition=legacy_disposition, legacy_state=dict(row['legacy_state']),
                occurrence_source=None, sequence=0, phase='unknown' if legacy_disposition == 'unknown' else 'idle',
                last_confirmed_at=self.clock() if legacy_disposition == 'confirmed' else 0.,
                not_before=max(float(row['legacy_state'].get('last_reminder_offer_at', 0)) + 86400 if imported and row['legacy_state'].get('last_reminder_offer_at') else 0.,
                    float(row['legacy_state'].get('last_reminder_attempt_at', 0)) + 600 if imported and row['legacy_state'].get('last_reminder_attempt_at') else 0.))
            # Nested transactions are deliberately avoided; this insert shares
            # the existing memo read's BEGIN IMMEDIATE and keeps original state.
            self.notes._capacity(db)
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (NAMESPACE, identity, scope_key(scope), 1, self.clock(), canonical(data)))
            self._scope(scope)
            if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
            return data

    @staticmethod
    def _cycle(row): return digest([row['id'], row['fields']['due_at'], row['completion_count']])

    def _occurrence(self, scope, data):
        return self.reminders.get(scope, data['occurrence_source']) if data.get('occurrence_source') else None

    def _task(self, occurrence):
        return self.reminders.store.get(occurrence['task_id']) if occurrence and occurrence.get('task_id') else None

    async def _cancel_current(self, scope, data):
        occurrence = self._occurrence(scope, data); task = self._task(occurrence)
        if data.get('phase') == 'unknown' or task and task['state'] in _UNKNOWN:
            raise JournalConflict('previous delivery requires outcome reconciliation; no automatic resend or advance')
        if occurrence and occurrence['status'] == 'active' and (not task or task['state'] not in _TERMINAL):
            await self.reminders.cancel(scope, occurrence['source_id'], expected_revision=occurrence['revision'])
        return occurrence, task

    async def complete_memo(self, scope, identity, *, expected_revision, request_id):
        scope = self._scope(scope); request_id = _text(request_id, 128); _integer(expected_revision, 1)
        signature = digest([identity, expected_revision, request_id]); key = digest(['complete', scope, request_id])
        async with self._serial:
            previous = self._read(ACTIONS, key, scope)
            if previous:
                if previous['data']['signature'] != signature: raise JournalConflict('completion request reused')
                return self.notes.get(scope, identity)
            binding = self._read(NAMESPACE, identity, scope)
            if binding is None: raise PermissionError('bind existing memo execution before recurring completion')
            await self._cancel_current(scope, binding['data'])
            with self.journal._transaction() as db:
                row = self.notes._existing(db, scope, identity, expected_revision)
                if row['archived']: raise JournalConflict('restore archived memo before completion')
                now = _time(self.clock(), zero=False); fields = row['fields']
                if fields['repeat'] == 'none':
                    if row['status'] != 'completed':
                        row.update(status='completed', completed_at=now, last_completed_at=now, completion_count=row['completion_count'] + 1)
                else:
                    local = datetime.fromtimestamp(fields['due_at'], date_zone(self.timezone))
                    legacy = row['legacy_state']
                    next_due = advance_due(fields['due_at'], fields['repeat'], now=now, timezone=self.timezone,
                        anchor_day=legacy.get('repeat_anchor_day') or local.day,
                        anchor_month=legacy.get('repeat_anchor_month') or local.month)
                    row['fields'] = dict(fields, due_at=next_due)
                    row.update(status='active', completed_at=0., last_completed_at=now, completion_count=row['completion_count'] + 1)
                    row['legacy_state'] = dict(legacy, repeat_anchor_day=legacy.get('repeat_anchor_day') or local.day,
                        repeat_anchor_month=legacy.get('repeat_anchor_month') or local.month,
                        last_reminder_offer_at=0., last_reminder_attempt_at=0.)
                saved = self.notes._write(db, scope, row, expected_revision)
                self.notes._capacity(db)
                data = dict(schema=1, scope=scope, signature=signature, record_id=identity, revision=saved['revision'],expected_revision=expected_revision,
                    action='complete', external_record_modified=False, delivery_confirmed=False)
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (ACTIONS, key, scope_key(scope), 1, now, canonical(data)))
                self._scope(scope)
                return saved

    async def tick_memos(self, scope, *, limit=20):
        scope = self._scope(scope); _integer(limit, 1, 200)
        async with self._serial:
            records = self.notes.export(scope)['records']; output = []
            for note in records:
                binding = self._read(NAMESPACE, note['id'], scope)
                if binding is None: continue  # A definition is not a handoff or a consent.
                if len(output) >= limit: break
                output.append(await self._tick_note(scope, note, binding))
            return dict(records=output, total_bound=len(output), sends_performed_by_this_method=0)

    async def _tick_note(self, scope, note, binding):
        self._scope(scope); data = dict(binding['data']); phase = data['phase']
        if note['creation_signature'] != data['source_signature']:
            raise JournalConflict('memo provenance changed after execution binding')
        occurrence, task = self._occurrence(scope, data), None
        if occurrence: task = self._task(occurrence)
        if phase == 'unknown' or task and task['state'] in {'unknown', 'quarantined'}:
            return dict(memo_id=note['id'], state='unknown', automatic_retry=False)
        if task and task['state'] == 'sending': return dict(memo_id=note['id'], state='sending')
        changed = note['revision'] != data['record_revision']
        if changed:
            await self._cancel_current(scope, data)
            cycle_changed = self._cycle(note) != data['cycle']
            data.update(record_revision=note['revision'], cycle=self._cycle(note), occurrence_source=None,
                sequence=0 if cycle_changed else data['sequence'] + 1, phase='idle',
                last_confirmed_at=0. if cycle_changed else max(data['last_confirmed_at'], self.clock() if task and task['state'] == 'confirmed' else 0.), not_before=0.)
            binding = self._put(NAMESPACE, note['id'], scope, data, binding['revision'])
            data = dict(binding['data']); occurrence = task = None
        fields = note['fields']
        if note['archived'] or note['status'] != 'active' or not fields['remind_enabled'] or fields['due_at'] <= 0:
            await self._cancel_current(scope, data)
            return dict(memo_id=note['id'], state='inactive')
        now = self.clock()
        if task:
            if task['state'] == 'confirmed':
                if data['phase'] != 'confirmed':
                    data.update(phase='confirmed', last_confirmed_at=now)
                    binding = self._put(NAMESPACE, note['id'], scope, data, binding['revision'])
                if now < data['last_confirmed_at'] + 86400: return dict(memo_id=note['id'], state='confirmed')
                data.update(sequence=data['sequence'] + 1, occurrence_source=None, phase='idle')
                binding = self._put(NAMESPACE, note['id'], scope, data, binding['revision'])
            elif task['state'] in {'failed', 'cancelled', 'expired'}:
                return dict(memo_id=note['id'], state=task['state'], automatic_retry=False)
            else: return dict(memo_id=note['id'], state='pending', task_id=task['id'])
        elif data.get('occurrence_source'):
            # Replaying create_once below repairs a crash before or during its
            # own durable materialization with the same immutable identity.
            pass
        if now < max(fields['due_at'], data['not_before'], data['last_confirmed_at'] + 86400 if data['last_confirmed_at'] else 0):
            return dict(memo_id=note['id'], state='waiting')
        source = data.get('occurrence_source') or 'pc.memo:' + digest([scope, note['id'], data['cycle'], data['sequence']])
        due = data.get('materialization_due') if data.get('occurrence_source') else max(now, fields['due_at'], data['not_before'], data['last_confirmed_at'] + 86400 if data['last_confirmed_at'] else 0)
        text = '便签提醒：' + (fields['title'] or fields['content'])
        if fields['content'] and fields['content'] != fields['title']: text += '；' + fields['content']
        if not data.get('occurrence_source'):
            data.update(occurrence_source=source, materialization_due=due, phase='materializing')
            binding = self._put(NAMESPACE, note['id'], scope, data, binding['revision'])
        result = await self.reminders.create_once(scope, source, due_at=due, text=text,
            consent_id=data['consent_id'], linked_note_id='')
        self._scope(scope)
        # The existing ReminderService supplies all retries, leases and ACKs.
        return dict(memo_id=note['id'], state=result['status'], occurrence_id=result['id'], task_id=result.get('task_id'))

    def timer_request(self, scope, timer_id):
        scope=self._scope(scope,'timer'); timer_id=_text(timer_id,128)
        return self._read(TIMERS,'pc.timer:'+digest([scope,timer_id]),scope)

    async def adopt_timer(self, scope, timer_id, *, due_at, text, consent_id, legacy_disposition='not_pending'):
        scope = self._scope(scope, 'timer'); timer_id = _text(timer_id, 128); due_at = _time(due_at, zero=False)
        text, consent_id = _text(text, 3900, multiline=True), _text(consent_id, 128)
        if legacy_disposition not in {'not_pending', 'confirmed', 'unknown'}: raise ValueError('known legacy timer result required')
        source = 'pc.timer:' + digest([scope, timer_id]); signature = digest([timer_id, due_at, text, consent_id, legacy_disposition])
        async with self._serial:
            row = self._read(TIMERS, source, scope)
            if row is None:
                data = dict(schema=1, scope=scope, source_id=source, original_timer_id=timer_id, signature=signature,
                    due_at=due_at, text=text, consent_id=consent_id, phase=legacy_disposition)
                row = self._put(TIMERS, source, scope, data, 0)
            elif row['data']['signature'] != signature: raise JournalConflict('old timer ID reused with different content or outcome')
            if row['data']['phase'] != 'not_pending':
                return dict(source_id=source, state=row['data']['phase'], automatic_retry=False)
            return await self.reminders.create_once(scope, source, due_at=due_at, text=text, consent_id=consent_id)

    def owns_task(self, scope, task):
        try:
            scope=private_scope(scope)
            with self.reminders.journal._lock:
                raw=self.reminders.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (task.get('reminder_binding',{}).get('occurrence_id'),)).fetchone()
            occurrence=json.loads(raw[0]) if raw else None
            return bool(occurrence and occurrence['scope']==scope and task.get('scope')==scope
                and occurrence['source_id'].startswith(('pc.memo:','pc.timer:')))
        except Exception: return False

    def delivery_allowed(self, scope, task):
        """Add to the host's existing task-specific final adapter fence."""
        try:
            scope = private_scope(scope)
            source = task.get('reminder_binding', {}).get('occurrence_id')
            occurrence = self.reminders.get(scope, task.get('pc_source_id', '')) if task.get('pc_source_id') else None
            if occurrence is None:
                with self.reminders.journal._lock:
                    raw = self.reminders.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (source,)).fetchone()
                    occurrence = json.loads(raw[0]) if raw else None
            if not occurrence or occurrence['scope'] != scope or occurrence.get('task_id') != task.get('id'): return False
            source_id = occurrence['source_id']
            if source_id.startswith('pc.timer:'):
                self._scope(scope, 'timer'); row = self._read(TIMERS, source_id, scope)
                return bool(row and row['data']['phase'] == 'not_pending' and row['data']['due_at'] == occurrence['due_at']
                    and occurrence['text'] == ('【日程】' + row['data']['text'] if not row['data']['text'].startswith('【日程】') else row['data']['text'])
                    and occurrence['consent_id'] == row['data']['consent_id'])
            if not source_id.startswith('pc.memo:'): return False
            self._scope(scope)
            # At most 200 existing memo records; no new index or global scan.
            for note in self.notes.export(scope)['records']:
                row = self._read(NAMESPACE, note['id'], scope)
                if not row or row['data']['occurrence_source'] != source_id: continue
                data = row['data']; fields = note['fields']
                return (data['phase'] != 'unknown' and data['record_revision'] == note['revision']
                    and data['cycle'] == self._cycle(note) and not note['archived'] and note['status'] == 'active'
                    and fields['remind_enabled'] and fields['due_at'] > 0)
            return False
        except Exception: return False

    def status(self, scope, *, administrator=False):
        scope=private_scope(scope)
        if type(administrator) is not bool: raise ValueError('typed read mode required')
        if not self.active or self.journal._closed or not self.notes.active or not self.reminders.active:
            raise RuntimeError('PC orchestration stopped')
        if not administrator: self._scope(scope)
        # A scoped administrator view reads existing definitions without
        # turning a historical scope into a live runtime lease or send grant.
        view=NativeMemoNotes(self.journal,authorize=lambda candidate:candidate==scope,clock=self.clock) if administrator else self.notes
        try: definitions=view.export(scope)['records']
        finally:
            if administrator: view.stop()
        output=[]
        for note in definitions:
            binding=self._read(NAMESPACE,note['id'],scope)
            if binding is None: continue
            data=binding['data']; occurrence=None; task=None
            if data.get('occurrence_source'):
                key=self.reminders._key(scope,data['occurrence_source'])
                with self.reminders.journal._lock:
                    raw=self.reminders.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=? AND scope=?',(key,scope_key(scope))).fetchone()
                occurrence=json.loads(raw[0]) if raw else None
                if occurrence and occurrence.get('scope')!=scope: raise RuntimeError('foreign reminder occurrence in scoped status')
                if occurrence and occurrence.get('task_id'): task=self.reminders.store.get(occurrence['task_id'])
                if task and task.get('scope')!=scope: raise RuntimeError('foreign reminder task in scoped status')
            changed=note['revision']!=data['record_revision']; task_state=task['state'] if task else None
            if data['phase']=='unknown' or task_state in {'unknown','quarantined'}: execution='unknown'
            elif note['archived'] or note['status']!='active' or not note['fields']['remind_enabled']: execution='inactive'
            elif changed: execution='definition_changed'
            elif task_state in {'confirmed','failed','cancelled','expired','sending'}: execution=task_state
            elif task_state is not None: execution='pending'
            elif self.clock()<max(note['fields']['due_at'],data['not_before']): execution='waiting'
            else: execution='bound_awaiting_host_tick'
            output.append(dict(memo_id=note['id'],record_revision=note['revision'],bound_revision=data['record_revision'],
                binding_revision=binding['revision'],binding_verified=True,execution_state=execution,
                delivery_confirmed=task_state=='confirmed' and not changed and data['cycle']==self._cycle(note),
                human_visible_confirmed=False,
                definition_changed=note['revision']!=data['record_revision'],status=note['status'],archived=note['archived'],
                remind_enabled=note['fields']['remind_enabled'],repeat=note['fields']['repeat'],due_at=note['fields']['due_at'],
                phase=data['phase'],legacy_disposition=data['legacy_disposition'],
                occurrence_status=occurrence['status'] if occurrence else None,task_state=task['state'] if task else None,
                task_id=task['id'] if task else None))
        timers=[]
        stored=self.journal.list(TIMERS,scope,limit=1000)
        for entry in stored:
            data=self._read(TIMERS,entry['key'],scope)['data']; key=self.reminders._key(scope,data['source_id'])
            with self.reminders.journal._lock:
                raw=self.reminders.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=? AND scope=?',(key,scope_key(scope))).fetchone()
            occurrence=json.loads(raw[0]) if raw else None
            if occurrence and occurrence.get('scope')!=scope: raise RuntimeError('foreign timer occurrence in scoped status')
            task=self.reminders.store.get(occurrence['task_id']) if occurrence and occurrence.get('task_id') else None
            if task and task.get('scope')!=scope: raise RuntimeError('foreign timer task in scoped status')
            timers.append(dict(source_id=data['source_id'],due_at=data['due_at'],legacy_disposition=data['phase'],
                occurrence_status=occurrence['status'] if occurrence else None,task_state=task['state'] if task else None,
                task_id=task['id'] if task else None))
        with self.journal._lock:
            timer_count=self.journal._db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',(TIMERS,scope_key(scope))).fetchone()[0]
        with self.reminders.journal._lock:
            consent=self.reminders.journal._db.execute('SELECT id,generation,enabled,evidence FROM tls_reminder_consent WHERE scope=?',(scope_key(scope),)).fetchone()
        try: live=self._scope(scope)==scope
        except PermissionError: live=False
        return dict(reminder_owner=self.reminders.store.owner(scope),records=output,total=len(output),timers=timers,timer_total=timer_count,timers_truncated=timer_count>len(timers),live_source_allowed=live,consent_present=bool(consent and consent['enabled']==1),
            consent_id=consent['id'] if consent and consent['enabled']==1 else None,
            consent_generation=consent['generation'] if consent else None,administrator_read=administrator,
            creates_private_scope=False,grants_execution=False)

    def _empty_new_reminder_scope(self, db, scope):
        """Only the never-created queue identity can receive a first owner.

        Called inside the reminder authority's BEGIN IMMEDIATE while this
        instance holds the existing LivingJournal lock. The fixed-table check
        is one reminder DB snapshot, not a cross-database atomic snapshot.
        """
        sk=scope_key(scope)
        for table,column,value in (
            ('tls_delivery_tasks','scope',sk),('tls_reminder_occurrences','scope',sk),
            ('tls_delivery_reservations','scope',sk),('checkpoints','scope',sk),
            ('resource_usage','scope',sk),('resource_reservations','scope',sk),
            ('tls_delivery_tombstones','scope_hash',hashlib.sha256(sk.encode()).hexdigest())):
            if db.execute('SELECT 1 FROM '+table+' WHERE '+column+'=? LIMIT 1',(value,)).fetchone():return False
        if db.execute('SELECT 1 FROM tls_delivery_archives a LEFT JOIN tls_delivery_tombstones t ON t.task=a.task WHERE t.task IS NULL LIMIT 1').fetchone():
            return False  # An orphan has no provable scope; never guess it away.
        budget=db.execute('SELECT COUNT(*),COALESCE(SUM(length(CAST(data AS BLOB))),0) FROM tls_reminder_completions').fetchone()
        if budget[0]>1000 or budget[1]>8*1024**2:return False
        for row in db.execute('SELECT data FROM tls_reminder_completions'):
            try:
                value=json.loads(row[0])
                if type(value) is not dict or private_scope(value.get('scope'))==scope:return False
            except (ValueError,TypeError,KeyError,UnicodeError):return False
        self.journal._ensure_open()
        names=(NAMESPACE,ACTIONS,TIMERS,'tls.native.command_reminders','tls.native.agenda.v1')
        if self.journal._db.execute('SELECT 1 FROM checkpoints WHERE scope=? AND namespace IN (?,?,?,?,?) LIMIT 1',(sk,*names)).fetchone():return False
        return True

    def prepare_explicit_new_consent(self, scope, *, source, consent, operation_guard=None):
        if source not in {'memo_note','timer'}: raise ValueError('new explicit task source required')
        scope=self._scope(scope,source)
        if consent is not True: raise JournalConflict('explicit user consent is required')
        if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
        consent_id='tls-explicit-'+digest(scope)[:24];sk=scope_key(scope)
        changed=bootstrapped=False
        # Do not split the fresh-identity inventory check from its first CAS:
        # a second SQLite connection must not insert an older queue between them.
        with self.journal._lock:
            with self.reminders.journal._transaction() as db:
                self._scope(scope,source)
                if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
                prior=db.execute('SELECT id,enabled FROM tls_reminder_consent WHERE scope=?',(sk,)).fetchone()
                if prior and prior['enabled']==1 and prior['id']!=consent_id:
                    raise JournalConflict('existing consent binding differs; preserve its pending tasks')
                owner=self.reminders.store._owner(db,sk)
                stored=db.execute('SELECT mode,generation FROM tls_delivery_owners WHERE scope=?',(sk,)).fetchone()
                if owner['mode']=='legacy':
                    if stored is not None or owner['generation']!=0 or prior is not None or not self._empty_new_reminder_scope(db,scope):
                        raise JournalConflict('existing legacy or nonempty reminder scope must not be taken over')
                    if db.execute('SELECT COUNT(*) FROM tls_delivery_owners').fetchone()[0]>=self.reminders.journal.max_records:
                        raise RuntimeError('delivery ownership capacity reached')
                    # Exact generation-zero initialization on the existing owner
                    # table, with the same generation/audit semantics as set_owner.
                    db.execute("INSERT INTO tls_delivery_owners VALUES(?,'tls',1)",(sk,))
                    self.reminders.store._audit(db,{'id':'owner:'+sk,'state':'tls'},'owner_changed',self.reminders.store._now(),
                        {'generation':1,'previous_mode':'legacy'})
                    changed=bootstrapped=True;owner=dict(mode='tls',generation=1)
                elif owner['mode']=='shadow':
                    pending=db.execute("SELECT 1 FROM tls_delivery_tasks WHERE scope=? AND state NOT IN ('confirmed','failed','cancelled','expired') LIMIT 1",(sk,)).fetchone()
                    if pending or db.execute("SELECT 1 FROM tls_reminder_occurrences WHERE scope=? AND status IN ('active','unknown') LIMIT 1",(sk,)).fetchone():
                        raise JournalConflict('existing pending or unknown work must be reconciled before owner switch')
                elif owner['mode']!='tls':raise JournalConflict('unknown reminder executor')
                self._scope(scope,source)
                if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
        if owner['mode']=='shadow':
            try:self.reminders.set_mode(scope,'tls',owner['generation']);changed=True
            except DeliveryConflict:
                if self.reminders.store.owner(scope)['mode']!='tls':raise
        self._scope(scope,source)
        if operation_guard is not None and operation_guard() is not True: raise PermissionError('memo tool operation revoked')
        recorded=self.reminders.grant(scope,consent_id,evidence='user_explicit')
        self._scope(scope,source)
        return dict(consent_id=consent_id,owner_changed=changed,owner_bootstrapped=bootstrapped,consent_recorded=True,
            consent_generation=recorded['generation'])

    def require_existing_consent(self, scope, consent_id, *, source='memo_note'):
        scope=self._scope(scope,source); consent_id=_text(consent_id,128)
        with self.reminders.journal._lock:
            row=self.reminders.journal._db.execute('SELECT id,enabled FROM tls_reminder_consent WHERE scope=?',(scope_key(scope),)).fetchone()
        if not row or row['enabled']!=1 or row['id']!=consent_id:
            raise JournalConflict('existing explicit reminder consent required')
        owner=self.reminders.store.owner(scope)
        if owner['mode']!='tls': raise JournalConflict('existing TLS reminder executor required')
        self._scope(scope,source)
        return True

    def stop(self): self.active = False
    def diagnostics(self):
        return dict(active=self.active, backend='existing_memo_journal_and_reminder_authority',
            creates_worker=False, grants_authority=False, unknown_automatically_retried=False,
            final_task_fence_required=True)
