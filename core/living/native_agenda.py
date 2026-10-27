"""Scoped single and recurring agenda on the existing ReminderService authority.

No database, worker, cron, model or legacy note/PC port is created here. Stable
front-end request IDs bind absolute instants and content; retrying after the due
time cannot produce a new delay or reactivate cancelled/finished occurrences.
Provenance lives in the same reminder journal, separate from old task data.
"""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json
import re

from .delivery_store import DeliveryConflict,TERMINAL
from .models import canonical,plain,private_scope,scope_key
from .reminders import ReminderService
from .native_important_dates import date_zone
from .native_pc_integration.recurrence import REPEATS,advance_due

NAMESPACE='tls.native.agenda.v1'
_SOURCE=re.compile(r'tls\.agenda\.[a-f0-9]{64}\Z')
_ISO=re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})\Z')


class AgendaConflict(DeliveryConflict):
    pass


def _utc(value):return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')


def _due(value):
    if not isinstance(value,str) or not _ISO.fullmatch(value):raise ValueError('explicit timezone-aware ISO8601 due time required')
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        timestamp=parsed.timestamp()
        if parsed.tzinfo is None or not 0<timestamp<=253402300799:raise ValueError
        return timestamp
    except (ValueError,OverflowError,OSError):raise ValueError('invalid timezone-aware agenda due time') from None


def _request(value):
    if (not isinstance(value,str) or not 1<=len(value)<=256 or value!=value.strip()
            or any(ord(char)<32 for char in value)):raise ValueError('stable frontend request ID required')
    return value


def _content(value):
    if (not isinstance(value,str) or not 1<=len(value.strip())<=3000
            or any(ord(char)<32 and char not in '\n\r\t' for char in value)):
        raise ValueError('bounded explicit agenda content required')
    value=value.strip()
    return value if value.startswith('【日程】') else '【日程】'+value


def _recurrence(repeat,zone,due):
    """Small calendar rule using the same PC calendar arithmetic and zones."""
    if repeat in (None,'','none','once'):
        if zone not in (None,''):
            date_zone(zone)  # Invalid zone input is never silently discarded.
        return None
    if not isinstance(repeat,str) or repeat not in REPEATS:raise ValueError('daily/weekly/monthly/yearly recurrence required')
    if not isinstance(zone,str) or not zone.strip():raise ValueError('explicit recurrence timezone required')
    local=datetime.fromtimestamp(due,date_zone(zone))
    if not 0<due<=4102444800:raise ValueError('calendar recurrence supports dates through 2100')
    return dict(repeat=repeat,timezone=zone,anchor_day=local.day,anchor_month=local.month)


class NativeAgenda:
    backend='native_agenda'

    def __init__(self,reminders,*,authorize,clock=None):
        if not isinstance(reminders,ReminderService) or not callable(authorize):raise ValueError('existing native reminder authority required')
        self.reminders,self.authorize=reminders,authorize
        self.clock=reminders.clock if clock is None else clock
        if not callable(self.clock):raise ValueError('agenda clock required')
        self.active=True
        # Reuse the original reminder driver's reconcile cycle. No second
        # worker, polling loop or scheduler is introduced.
        previous=getattr(reminders,'_agenda_reconciler',None)
        if previous is not None:raise RuntimeError('agenda reconciler already attached')
        reminders._agenda_reconciler=self._reconcile_recurring
        try:self._reconcile_recurring()
        except BaseException:
            reminders._agenda_reconciler=None;self.active=False
            raise

    def _scope(self,scope):
        scope=private_scope(scope)
        if not self.active or not self.reminders.active:raise RuntimeError('native agenda unavailable')
        if self.authorize(scope) is not True or not self.reminders._authorized(scope):
            raise PermissionError('genuine private agenda scope required')
        return scope

    @staticmethod
    def _source(scope,request_id):
        return 'tls.agenda.'+hashlib.sha256(canonical(['tls.agenda.request.v1',scope,_request(request_id)]).encode()).hexdigest()

    def _metadata(self,db,scope,source):
        if not isinstance(source,str) or not _SOURCE.fullmatch(source):return None
        row=db.execute('SELECT data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                       (NAMESPACE,source,scope_key(scope))).fetchone()
        value=json.loads(row[0]) if row else None
        if value is not None and (not isinstance(value,dict) or value.get('schema')!=1 or value.get('source_id')!=source
                      or value.get('occurrence_id')!=self.reminders._key(scope,source)):
            raise RuntimeError('invalid native agenda provenance')
        return value

    def _owned(self,db,scope,source):
        metadata=self._metadata(db,scope,source)
        if metadata is None:return None,None
        row=db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=? AND scope=?',
                       (metadata['occurrence_id'],scope_key(scope))).fetchone()
        occurrence=json.loads(row[0]) if row else None
        if occurrence and (occurrence['scope']!=scope or occurrence['source_id']!=source or occurrence.get('linked_note_id')):
            raise RuntimeError('agenda occurrence provenance differs')
        return metadata,occurrence

    def _public(self,db,scope,metadata,occurrence):
        task=db.execute('SELECT state FROM tls_delivery_tasks WHERE id=?',(occurrence['task_id'],)).fetchone() if occurrence['task_id'] else None
        recurrence=metadata.get('recurrence')
        return plain(dict(id=occurrence['source_id'],source_id=occurrence['source_id'],occurrence_id=occurrence['id'],
            scope=scope,revision=occurrence['revision'],status=occurrence['status'],
            due_at=_utc(occurrence['due_at']),expires_at=_utc(occurrence['expires_at']),created_at=_utc(occurrence['created_at']),
            closed_at=_utc(occurrence['closed_at']) if occurrence.get('closed_at') is not None else None,
            content=occurrence['text'],task_id=occurrence['task_id'],task_state=task[0] if task else None,
            execution_owner=self.reminders.store._owner(db,scope_key(scope))['mode'],
            metadata=dict(origin='tls_native_agenda',single_occurrence=not bool(recurrence),periodic=bool(recurrence),
                recurrence=recurrence,recurrence_state=metadata.get('recurrence_state','single'),
                sequence=metadata.get('sequence',0),last_occurrence=metadata.get('last_occurrence'),
                recurrence_error=metadata.get('recurrence_error'),
                legacy_migrated=False,linked_note_completion=False,signature=metadata['signature'])))

    def get(self,scope,identity):
        scope=self._scope(scope)
        with self.reminders.journal._lock:
            self.reminders.journal._ensure_open()
            metadata,occurrence=self._owned(self.reminders.journal._db,scope,identity)
            result=self._public(self.reminders.journal._db,scope,metadata,occurrence) if occurrence else None
        self._scope(scope)
        return result

    def list(self,scope,*,limit=50,offset=0):
        scope=self._scope(scope)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:
            raise ValueError('bounded agenda pagination required')
        with self.reminders.journal._lock:
            self.reminders.journal._ensure_open();db=self.reminders.journal._db
            rows=db.execute('SELECT data FROM tls_reminder_occurrences WHERE scope=?',(scope_key(scope),)).fetchall()
            result=[]
            for row in rows:
                occurrence=json.loads(row[0]);source=occurrence['source_id']
                metadata=self._metadata(db,scope,source)
                if metadata is not None:
                    if occurrence.get('linked_note_id') or occurrence['scope']!=scope:raise RuntimeError('agenda occurrence provenance differs')
                    result.append((occurrence['due_at'],self._public(db,scope,metadata,occurrence)))
        self._scope(scope)
        result.sort(key=lambda item:(item[0],item[1]['id']))
        return [item[1] for item in result[offset:offset+limit]]

    def _prepare(self,scope,source,due,text,signature,recurrence=None):
        scope=self._scope(scope);journal=self.reminders.journal
        with journal._lock:
            metadata,occurrence=self._owned(journal._db,scope,source)
            if metadata is not None:
                if metadata['signature']!=signature:raise AgendaConflict('request ID reused with different absolute agenda content')
                return occurrence
            now=self.clock()
            if not now<due<=now+366*86400:raise ValueError('new agenda must have a future due time within 366 days')
            # Match the existing host's consent ID. A new agenda must not rotate
            # the shared consent and invalidate already-authorized TLS reminders.
            consent_id='tls-explicit-'+hashlib.sha256(canonical(scope).encode()).hexdigest()[:24]
            existing=journal._db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?',(scope_key(scope),)).fetchone()
            if existing is not None and (not existing['enabled'] or existing['id']!=consent_id or existing['evidence']!='user_explicit'):
                raise AgendaConflict('existing reminder consent requires explicit owner review')
            owner=self.reminders.store.owner(scope)
            if owner['mode']!='tls':self.reminders.set_mode(scope,'tls',owner['generation'])
            self.reminders.grant(scope,consent_id,evidence='user_explicit')
            metadata=dict(schema=1,source_id=source,occurrence_id=self.reminders._key(scope,source),signature=signature,
                          origin='tls_native_agenda',created_at=now)
            if recurrence:metadata.update(recurrence=recurrence,recurrence_state='active',sequence=0)
            journal.put(NAMESPACE,source,scope,metadata,expected_revision=0,authorize=lambda:self._scope(scope)==scope)
            return None

    async def create(self,scope,request_id,*,due_at,text,repeat=None,timezone=None):
        scope=self._scope(scope);source=self._source(scope,request_id);due=_due(due_at);text=_content(text)
        recurrence=_recurrence(repeat,timezone,due)
        signature=hashlib.sha256(canonical([due,text,recurrence] if recurrence else [due,text]).encode()).hexdigest()
        occurrence=await self.reminders._run(self._prepare,scope,source,due,text,signature,recurrence)
        if occurrence is None:
            consent_id='tls-explicit-'+hashlib.sha256(canonical(scope).encode()).hexdigest()[:24]
            await self.reminders.create_once(scope,source,due_at=due,text=text,consent_id=consent_id,linked_note_id='')
        elif occurrence['status']=='active':
            await self.reminders._run(self.reminders._materialize,occurrence)
        result=await self.reminders._run(self.get,scope,source)
        if result is None:raise RuntimeError('native agenda not materialized')
        return result

    def _cancel(self,scope,identity,expected_revision):
        scope=self._scope(scope)
        if type(expected_revision) is not int or expected_revision<1:raise ValueError('positive agenda revision required')
        # Atomic scope/CAS/lifecycle check in the actual reminder authority.
        # Unlike generic reminder rescheduling, agenda cancellation refuses even
        # CLAIMED work, before touching either occurrence or its queue row.
        with self.reminders.journal._transaction() as db:
            metadata,occurrence=self._owned(db,scope,identity)
            if occurrence is None:raise KeyError('native agenda absent')
            if occurrence['revision']!=expected_revision:raise AgendaConflict('stale native agenda revision')
            if occurrence['status']=='cancelled':return
            if occurrence['status']!='active':raise AgendaConflict('terminal native agenda cannot be cancelled')
            task=self.reminders.store._task(db,occurrence['task_id']) if occurrence['task_id'] else None
            if task and task['state'] in {'claimed','sending','unknown','confirmed'}:raise AgendaConflict('inflight or uncertain reminder cannot be cancelled')
            if task and task['state'] not in TERMINAL:
                task['state']='cancelled';self.reminders.store._save(db,task)
                self.reminders.store._audit(db,task,'native_agenda_cancelled',self.clock())
            occurrence['status']='cancelled';self.reminders._save_occurrence(db,occurrence)
            if metadata.get('recurrence'):
                metadata['recurrence_state']='cancelled';self._save_metadata(db,scope,metadata)
            self._scope(scope)

    async def cancel(self,scope,identity,*,expected_revision):
        scope=self._scope(scope)
        await self.reminders._run(self._cancel,scope,identity,expected_revision)
        return await self.reminders._run(self.get,scope,identity)

    def _update(self,scope,identity,expected_revision,due,text,repeat=None,timezone=None):
        scope=self._scope(scope)
        # The callback runs INSIDE the existing authority's transaction, both
        # before mutation and before commit. It cannot race a different DB
        # connection claiming the old task between a precheck and reschedule.
        def guard(db,current,task):
            self._scope(scope)
            metadata,owned=self._owned(db,scope,identity)
            if metadata is None or owned is None or owned['id']!=current['id']:
                raise KeyError('native agenda absent')
            if task and task['state'] in {'claimed','sending','unknown','confirmed'}:
                raise AgendaConflict('inflight or uncertain reminder cannot be edited')
            old=metadata.get('recurrence') or {}
            desired=_recurrence(old.get('repeat') if repeat is None else repeat,
                old.get('timezone') if timezone is None else timezone,due)
            if current['revision']!=expected_revision:
                metadata.update(recurrence=desired,recurrence_state='active' if desired else 'single')
                metadata.pop('recurrence_error',None)
                self._save_metadata(db,scope,metadata)
                self._scope(scope)
        return self.reminders._change(scope,identity,expected_revision=expected_revision,
            changes={'due_at':due,'text':text},guard=guard)

    async def update(self,scope,identity,*,expected_revision,due_at,text,repeat=None,timezone=None):
        scope=self._scope(scope);due=_due(due_at);text=_content(text)
        occurrence=await self.reminders._run(self._update,scope,identity,expected_revision,due,text,repeat,timezone)
        # Reuse the original generation-bound queue materializer. An interrupted
        # materialization is recovered by ReminderService._reconcile on reopen.
        await self.reminders._run(self.reminders._materialize,occurrence)
        return await self.reminders._run(self.get,scope,identity)

    def _save_metadata(self,db,scope,metadata):
        changed=db.execute('UPDATE checkpoints SET data=?,revision=revision+1,updated=? '
            'WHERE namespace=? AND key=? AND scope=?',
            (canonical(metadata),self.clock(),NAMESPACE,metadata['source_id'],scope_key(scope))).rowcount
        if changed!=1:raise AgendaConflict('agenda provenance disappeared')

    @staticmethod
    def _last_occurrence(occurrence):
        return {key:occurrence.get(key) for key in ('revision','due_at','status','closed_at','task_id')}

    def _fresh_generation(self,db,scope,current,due,text,*,automatic=False):
        consent=db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?',(scope_key(scope),)).fetchone()
        owner=self.reminders.store._owner(db,scope_key(scope))
        if (not consent or not consent['enabled'] or consent['id']!=current['consent_id']
                or consent['generation']!=current['consent_generation'] or owner['mode']!='tls'):
            raise PermissionError('recurring agenda consent/owner requires review')
        previous=self.reminders.store._task(db,current['task_id']) if current['task_id'] else None
        if automatic and previous and previous['owner_generation']!=owner['generation']:
            raise PermissionError('recurring agenda owner generation changed')
        if not self.clock()<due<=self.clock()+366*86400:raise ValueError('next agenda must be future bounded')
        current.update(revision=current['revision']+1,status='active',due_at=due,
            expires_at=due+self.reminders.policy.catchup_seconds,text=text,created_at=self.clock(),task_id=None)
        current.pop('closed_at',None)
        self.reminders._save_occurrence(db,current)
        self._scope(scope)
        return current

    def _restore(self,scope,identity,expected_revision,due,text,repeat,timezone):
        scope=self._scope(scope)
        if type(expected_revision)is not int or expected_revision<1:raise ValueError('positive agenda revision required')
        with self.reminders.journal._transaction() as db:
            metadata,current=self._owned(db,scope,identity)
            if current is None:raise KeyError('native agenda absent')
            if current['revision']!=expected_revision:raise AgendaConflict('stale agenda revision')
            needs_review=current['status']=='done' and metadata.get('recurrence_state')=='needs_review'
            if current['status'] not in {'cancelled','expired','failed'} and not needs_review:
                raise AgendaConflict('only definitively stopped agenda may be restored')
            task=self.reminders.store._task(db,current['task_id']) if current['task_id'] else None
            if task and task['state'] not in ({'cancelled','expired','failed','confirmed'} if needs_review else {'cancelled','expired','failed'}):
                raise AgendaConflict('uncertain or delivered task cannot be restored')
            old=metadata.get('recurrence') or {}
            recurrence=_recurrence(old.get('repeat') if repeat is None else repeat,
                old.get('timezone') if timezone is None else timezone,due)
            metadata.update(last_occurrence=self._last_occurrence(current),recurrence=recurrence,
                recurrence_state='active' if recurrence else 'single',sequence=metadata.get('sequence',0)+1)
            metadata.pop('recurrence_error',None)
            result=self._fresh_generation(db,scope,current,due,text)
            self._save_metadata(db,scope,metadata)
            self._scope(scope)
            return result

    async def restore(self,scope,identity,*,expected_revision,due_at,text,repeat=None,timezone=None):
        """Explicit new generation; never revives a previous immutable queue task."""
        scope=self._scope(scope);due=_due(due_at);text=_content(text)
        occurrence=await self.reminders._run(self._restore,scope,identity,expected_revision,due,text,repeat,timezone)
        await self.reminders._run(self.reminders._materialize,occurrence)
        return await self.reminders._run(self.get,scope,identity)

    def _reconcile_recurring(self):
        """Advance confirmed/expired occurrences on the original reminder tick.

        UNKNOWN, failure and cancellation stay stopped for explicit review.
        New revisions, rule progress and occurrence state share one transaction;
        the existing materializer recovers a crash after that commit.
        """
        if not self.active or not self.reminders.active:return
        journal=self.reminders.journal
        with journal._lock:
            rows=journal._db.execute('SELECT o.data FROM tls_reminder_occurrences o JOIN checkpoints c '
                "ON json_extract(c.data,'$.occurrence_id')=o.id AND c.scope=o.scope "
                "WHERE c.namespace=? AND o.status IN ('done','expired') "
                "AND json_extract(c.data,'$.recurrence_state')='active' ORDER BY o.id LIMIT 1000",(NAMESPACE,)).fetchall()
        for row in rows:
            observed=json.loads(row[0]);scope=observed['scope']
            try:
                self._scope(scope)
                with journal._transaction() as db:
                    metadata,current=self._owned(db,scope,observed['source_id'])
                    if (current is None or current['revision']!=observed['revision']
                            or current['status'] not in {'done','expired'}
                            or metadata.get('recurrence_state')!='active'):continue
                    rule=metadata.get('recurrence')
                    if not rule:continue
                    task=self.reminders.store._task(db,current['task_id']) if current['task_id'] else None
                    if task and task['state'] not in {'confirmed','expired'}:continue
                    try:
                        due=advance_due(current['due_at'],rule['repeat'],now=max(self.clock(),current['due_at']),
                            timezone=rule['timezone'],anchor_day=rule['anchor_day'],anchor_month=rule['anchor_month'])
                    except ValueError:
                        metadata.update(recurrence_state='needs_review',recurrence_error='calendar_range_or_catchup_limit')
                        self._save_metadata(db,scope,metadata);self._scope(scope)
                        continue
                    metadata.update(last_occurrence=self._last_occurrence(current),sequence=metadata.get('sequence',0)+1)
                    ready=self._fresh_generation(db,scope,current,due,current['text'],automatic=True)
                    self._save_metadata(db,scope,metadata);self._scope(scope)
            except PermissionError:
                # A changed permission rolls the entire occurrence/rule write
                # back; the original consent and due record remain untouched.
                continue
            self.reminders._materialize(ready)

    def context_generation(self,scope):
        """Read-only token for legitimate monotonic edits/terminal changes.

        An agenda ID cannot be reassigned or revived; revisions only increase.
        Grouped status/revision counters therefore fence changes without reading
        every reminder body on the event loop. Ownership and consent are included.
        """
        try:
            scope=self._scope(scope);key=scope_key(scope)
            with self.reminders.journal._lock:
                self.reminders.journal._ensure_open();db=self.reminders.journal._db
                rows=db.execute("SELECT o.status,COUNT(*),SUM(o.revision) FROM tls_reminder_occurrences o "
                    "JOIN checkpoints c ON json_extract(c.data,'$.occurrence_id')=o.id AND c.scope=o.scope "
                    "WHERE c.namespace=? AND o.scope=? GROUP BY o.status ORDER BY o.status",(NAMESPACE,key)).fetchall()
                owner=db.execute('SELECT mode,generation FROM tls_delivery_owners WHERE scope=?',(key,)).fetchone()
                consent=db.execute('SELECT id,generation,enabled FROM tls_reminder_consent WHERE scope=?',(key,)).fetchone()
            self._scope(scope)
            return ('native_agenda',id(self),tuple(tuple(x) for x in rows),tuple(owner) if owner else None,
                tuple(consent) if consent else None)
        except Exception:return None

    def context_material(self,scope,*,limit=32):
        """Only this scoped native agenda, future plans, never delivery claims."""
        scope=self._scope(scope)
        if type(limit) is not int or not 1<=limit<=64:raise ValueError('bounded material limit required')
        generation=self.context_generation(scope)
        if generation is None:raise PermissionError('agenda context authority unavailable')
        now=self.clock();items=[]
        with self.reminders.journal._lock:
            db=self.reminders.journal._db
            rows=db.execute("SELECT o.data FROM tls_reminder_occurrences o JOIN checkpoints c "
                "ON json_extract(c.data,'$.occurrence_id')=o.id AND c.scope=o.scope "
                "WHERE c.namespace=? AND o.scope=? AND o.status='active' "
                "AND CAST(json_extract(o.data,'$.due_at') AS REAL)>? "
                "ORDER BY CAST(json_extract(o.data,'$.due_at') AS REAL),o.id LIMIT ?",
                (NAMESPACE,scope_key(scope),now,limit)).fetchall()
            for row in rows:
                occurrence=json.loads(row[0]);metadata,current=self._owned(db,scope,occurrence['source_id'])
                if metadata is None or current!=occurrence:raise AgendaConflict('agenda changed during material read')
                items.append(dict(id=occurrence['source_id'],canonical_key=occurrence['source_id'],
                    content=('管理页登记的周期提醒下一次' if metadata.get('recurrence') else '管理页登记的一次性提醒')+
                        '（只是计划，未确认发生或送达）：'+_utc(occurrence['due_at'])+' '+occurrence['text'],
                    owner_bot_id=scope['bot_id'],persona_id=scope['character_id'],platform=scope['platform'],
                    scope='private',session_id=scope['session_id'],visibility='bot_self',
                    subject=dict(kind='bot',id=scope['bot_id']),object=dict(kind='user',id=scope['user_id']),
                    memory_type='companion_note',source_plugin='tls_native_agenda',reality_level='bot_action',
                    lifecycle='active',validity_status='active',review_status='manual',sensitivity='private',
                    sayability='direct',mention_policy='when_relevant',confidence=1.0,
                    created_at=occurrence['created_at'],occurred_at=occurrence['created_at'],updated_at=occurrence['created_at'],
                    valid_to=occurrence['due_at'],context_metadata=dict(status='active',timezone='UTC',
                        start_at=_utc(occurrence['due_at']),end_at=_utc(occurrence['due_at']+1),
                        native_plan=dict(schema=1,source_id=occurrence['source_id'],occurrence_id=occurrence['id'],
                            revision=occurrence['revision'],due_at=occurrence['due_at']))))
        if generation!=self.context_generation(scope):raise AgendaConflict('agenda generation changed')
        return items

    def stop(self):
        self.active=False
        if getattr(self.reminders,'_agenda_reconciler',None)==self._reconcile_recurring:
            self.reminders._agenda_reconciler=None

    async def close(self):self.stop()  # The host retains the shared service.
