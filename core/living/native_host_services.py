"""Real host wiring for the existing native queues, without legacy business calls.

Only explicit TLS reminder commands enter the reminder lane. Existing PC tasks
are not imported or claimed. Companion delivery is separately opt-in and needs
an exact session allowlist; constructing a console cannot enable a sender.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path

from .delivery_scheduler import NativeScheduler
from .delivery_sender import AstrBotDeliveryAdapter, NativeSender
from .delivery_store import DeliveryStore
from .delivery_store import DeliveryConflict
from .delivery_types import DeliveryPolicy,delivery_quiet_window
from .journal import JournalConflict
from .models import canonical, private_scope
from .reminders import ReminderService


class _PCReminderFinalAdapter:
    """Keep the original reminder fence and add PC source validation at send."""
    def __init__(self, services, adapter): self.services,self.adapter=services,adapter
    async def healthy(self, session): return await self.adapter.healthy(session)
    def prepare(self, task): return self.adapter.prepare(task)
    async def send(self, task, prepared):
        from .delivery_sender import BeforeDispatchError
        if self.services._pc_reminder_task_allowed(task['scope'],task) is not True:
            raise BeforeDispatchError('pc_memo_definition_or_source_revoked')
        return await self.adapter.send(task,prepared)


class NativeHostServices:
    environment = 'native_host'

    def __init__(self, host, runtime, data_dir, *, adapter_factory=AstrBotDeliveryAdapter):
        self.host, self.runtime, self.plugin = host, runtime, host.plugin
        self.path = Path(data_dir)
        self.clock = host.clock
        self.active = True
        self.started = False
        self.reminders = self.delivery = None
        self.phone = self.image_service = self.state_reader = None
        self.proactive = self.generator = self.persona_binding = None
        self.proactive_config_error = None
        self.pc_integration = None
        self.node = 'tls-astrbot-main'
        adapter = adapter_factory(host.context, media_root=self.path/'media')
        from .chat_delivery import ChatDeliveryAdapter
        adapter = ChatDeliveryAdapter(self.plugin, adapter)
        try:
            if self._flag('living_native_reminders_enabled'):
                if getattr(runtime, 'reminders', None) is not None:
                    raise RuntimeError('reminder lane already has an executor')
                self.reminders = ReminderService(self.path/'living'/'native_reminders.sqlite3',
                    node=self.node, authorize=self._reminder_allowed, adapter=_PCReminderFinalAdapter(self,adapter), clock=self.clock)
                self.reminders.environment = self.environment
                self.reminders.driver.environment = self.environment
                self.reminders.sender.task_authorize = self._pc_reminder_task_allowed
                runtime.reminders = self.reminders
            if self._flag('living_native_delivery_enabled'):
                if getattr(runtime, 'delivery', None) is not None:
                    raise RuntimeError('companion lane already has an executor')
                policy = DeliveryPolicy(require_image=self._flag('living_native_delivery_require_image'),
                    quiet_hours=self.plugin._cfg('living_native_delivery_quiet_hours',''))
                store = DeliveryStore(runtime.journal, clock=self.clock)
                from .native_companion_state import NativeCompanionStateReader
                self.state_reader=NativeCompanionStateReader(
                    self.path.parent/'astrbot_plugin_private_companion'/'companions.json',
                    authorize=self._delivery_allowed,clock=self.clock)
                sender = NativeSender(store, adapter, authorize=self._shared_final_delivery_allowed,
                    task_authorize=self._task_delivery_allowed, policy=policy)
                from .chat_notifications import enqueue_confirmed
                sender.confirmed_observer = lambda task: enqueue_confirmed(self.plugin, task)
                self.delivery = NativeScheduler(store, sender, node=self.node,
                    read_state=self._read_delivery_state,
                    authorize=self._delivery_allowed, policy=policy, clock=self.clock)
                self.delivery.environment = self.environment
                runtime.delivery = self.delivery
            if self._flag('living_phone_companion_enabled') or self._flag('living_proactive_companion_enabled'):
                if self.delivery is None:raise ValueError('native phone requires native delivery')
                self._configure_phone()
                self._configure_proactive()
        except BaseException:
            if self.pc_integration is not None:self.pc_integration.stop()
            if self.proactive is not None:self.proactive.stop()
            if self.generator is not None:self.generator.stop()
            if self.persona_binding is not None:self.persona_binding.stop()
            if self.phone is not None:self.phone.stop()
            if self.image_service is not None:
                self.image_service.abort_initialization()
            if self.reminders is not None:
                self.reminders.abort_initialization()
                if getattr(runtime, 'reminders', None) is self.reminders:
                    del runtime.reminders
            if self.delivery is not None:
                self.delivery.active = self.delivery.sender.active = False
                if getattr(runtime, 'delivery', None) is self.delivery:
                    del runtime.delivery
            for name,owned in (('phone_companion',self.phone),('image_service',self.image_service),
                    ('proactive_companion',self.proactive),('proactive_generation',self.generator),
                    ('proactive_persona_binding',self.persona_binding)):
                if owned is not None and getattr(runtime,name,None) is owned:delattr(runtime,name)
            raise

    def _flag(self, key):
        return self.active and self.plugin._cfg_bool(key, False) is True

    def _reminder_allowed(self, scope):
        return self._flag('living_native_reminders_enabled') and self.host.authorized_scope(scope)

    def _delivery_allowed(self, scope):
        try:self._refresh_delivery_policy()
        except (ValueError,TypeError):return False
        sessions = self.plugin._cfg('living_native_delivery_sessions', [])
        scope=private_scope(scope)
        selected=scope['session_id']
        if isinstance(sessions,list) and selected not in sessions:
            from .chat_workspace import linked_source_scope
            source=linked_source_scope(self.plugin,scope,permission='delivery')
            selected=source['session_id'] if source is not None else None
        return (self._flag('living_native_delivery_enabled')
                and (self._flag('living_phone_companion_enabled') or self._flag('living_proactive_companion_enabled'))
                and isinstance(sessions, list)
                and all(isinstance(item, str) for item in sessions)
                and selected in sessions and self.host.authorized_scope(scope))

    def _refresh_delivery_policy(self):
        """Read the existing setting at authorization; never re-sign queued approvals."""
        delivery=getattr(self,'delivery',None)
        policy=getattr(delivery,'policy',None)
        if not isinstance(policy,DeliveryPolicy):return
        updated=replace(policy,quiet_hours=self.plugin._cfg('living_native_delivery_quiet_hours',''))
        if updated!=policy:
            delivery.policy=updated
            delivery.sender.policy=updated

    def _read_shared_state(self,scope):
        if scope.get('platform')!='webchat':return self.state_reader.read(scope)
        from .chat_workspace import linked_source_scope
        source=linked_source_scope(self.plugin,scope,permission='delivery')
        return self.state_reader.read(scope,source_scope=source) if source is not None else self.state_reader.read(scope)

    async def _read_delivery_state(self,scope):
        state=await asyncio.to_thread(self._read_shared_state,scope)
        if state.get('state')!='current':return state
        def local():
            from .linked_chat_activity import linked_activity_at
            return (self.delivery.store.activity(scope),
                self.delivery.store.counters(scope,self.delivery.policy.day(self.clock())),
                linked_activity_at(self.plugin, scope, self.delivery.store, self.clock()))
        activity,counters,paired_activity=await asyncio.to_thread(local)
        return dict(state,last_activity_at=max(state['last_activity_at'],activity,paired_activity),
            shared_last_sent_at=max(state['shared_last_sent_at'],counters['last_sent']),
            shared_sent_today=state['shared_sent_today']+counters['sent_today'])

    async def ensure_phone_scope(self,scope):
        """Bind only a new, explicitly configured and genuinely observed lane.

        Generation zero has never had an executor. A later legacy/shadow
        assignment is an explicit rollback and must never be auto-reclaimed.
        This authority belongs solely to the new TLS queue, not old PC tasks.
        """
        if self.delivery is None or not self._delivery_allowed(scope):return False
        def bind():
            if not self._delivery_allowed(scope):return False
            owner=self.delivery.store.owner(scope)
            if owner['mode']=='legacy' and owner['generation']==0:
                try:self.delivery.store.set_owner(scope,'tls',0)
                except DeliveryConflict:pass
                owner=self.delivery.store.owner(scope)
            return owner['mode']=='tls' and self._delivery_allowed(scope)
        return await asyncio.to_thread(bind)

    async def phone_tick(self,scope):
        if self.phone is None or not await self.ensure_phone_scope(scope):
            return {'state':'disabled','reason':'native_owner_not_granted'}
        return await self.phone.tick(scope)

    async def _shared_final_delivery_allowed(self,scope):
        if not self._delivery_allowed(scope):return False
        # Local reservations include this very task after begin(). Only the
        # other executor's fresh counters belong in this additional guard;
        # the native store separately fences its own reservation and quota.
        state=await asyncio.to_thread(self._read_shared_state,scope)
        if state.get('state')!='current' or not state.get('enabled') or state.get('is_friend'):
            return False
        from .native_frequency import hard_limit_reason
        policy=self.delivery.policy;now=self.clock()
        if policy.quiet_hours and delivery_quiet_window(policy.as_dict(),now)['quiet_until']>now:return False
        activity=await asyncio.to_thread(self.delivery.store.activity,scope)
        from .linked_chat_activity import linked_activity_at
        paired_activity=await asyncio.to_thread(linked_activity_at,self.plugin,scope,self.delivery.store,now)
        blocked=hard_limit_reason(now=now,last_sent=state['shared_last_sent_at'],
            sent_today=state['shared_sent_today'],daily_limit=policy.daily_limit,
            min_interval_minutes=policy.min_interval_seconds/60,
            recent_activity_at=max(activity,state['last_activity_at'],paired_activity),
            recent_chat_minutes=policy.recent_chat_seconds/60)
        if blocked or state['rest_until'] > now or not self._delivery_allowed(scope):
            return False
        return self._delivery_allowed(scope)

    async def _final_delivery_allowed(self,scope):
        """Compatibility reader for the original phone-only final guard."""
        if not await self._shared_final_delivery_allowed(scope):return False
        # The phone owner binds pending work to the current saved App rules.
        # Queueing is not permission to use an obsolete rule after an await.
        phone = getattr(self, 'phone', None)
        guard = getattr(phone, 'delivery_allowed', None)
        if callable(guard) and await guard(scope) is not True:
            return False
        return self._delivery_allowed(scope)

    def _proactive_allowed(self,scope):
        from .native_legacy_companion_inspection import runtime_disabled,runtime_random_disabled
        activated=self.plugin._cfg('living_proactive_activated_at',0)
        if (type(activated) not in (int,float) or not math.isfinite(activated)
                or not 0<activated<=self.clock()-2700):return False
        return (self._flag('living_proactive_companion_enabled') and self._delivery_allowed(scope)
            and self.host._native_memory_allowed(scope)
            and (runtime_disabled(self.host.context) is True
                 or runtime_random_disabled(self.host.context,scope) is True))

    def _legacy_quiescent(self,scope=None):
        from .native_legacy_companion_inspection import inspect_legacy_companion,inspect_random_handoff,runtime_random_disabled
        if scope is not None and runtime_random_disabled(self.host.context,scope) is True:
            return inspect_random_handoff(self.host.context,scope).get('state')=='quiescent_observed'
        result=inspect_legacy_companion(self.host.context)
        return result.get('handoff',{}).get('state')=='quiescent_observed'

    def _pc_source_allowed(self,scope,source):
        if (source not in {'memo_note','timer','important_date','environment_change','special_calendar'}
                or not self._flag('living_pc_integration_enabled')
                or getattr(self.runtime,'active',False) is not True
                or not self.host._native_memory_allowed(scope)):
            return False
        if source in {'memo_note','timer'}: return self._reminder_allowed(scope)
        if source == 'special_calendar':
            return self._proactive_allowed(scope) and self._legacy_quiescent(scope)
        flag='living_pc_important_dates_enabled' if source=='important_date' else 'living_pc_environment_change_enabled'
        return (self._flag(flag) and self._proactive_allowed(scope) and self._legacy_quiescent(scope))

    def configure_pc(self):
        """Called after the existing memo/date services have been constructed."""
        if self.pc_integration is not None:return self.pc_integration
        if self.reminders is None:return None
        notes=getattr(self.runtime,'memo_notes',None);dates=getattr(self.runtime,'important_dates',None)
        if notes is None or dates is None:return None
        from .native_pc_integration import NativePCIntegration
        self.pc_integration=NativePCIntegration(notes,self.reminders,self.proactive,important_dates=dates,
            authorize=self._pc_source_allowed,read_special=self._special_calendar_reason,clock=self.clock)
        self.runtime.pc_integration=self.pc_integration
        return self.pc_integration

    async def _special_calendar_reason(self, scope):
        owner = getattr(getattr(self.plugin, '_native_server_integrations', None), 'pc_full', None)
        service = getattr(owner, 'service', None)
        if (owner is None or not owner.active or service is None
                or service._tls_primary_scope != scope or not service._tls_allowed('tick', scope)):
            return None
        from .native_special_occasions import occasion_reason
        async with service._data_lock:
            user = (service.data.get('users') or {}).get(scope['user_id'])
            if scope['platform'] == scope['bot_id'] == 'webchat':
                # The actual APP identity can consume its explicitly linked
                # calendar without receiving a QQ execution/Presence lease.
                from .chat_identity import identity_service
                from .chat_workspace import ChatWorkspace
                origin = scope['session_id'].split(':', 2)[-1]
                prefix = 'webchat!' + scope['user_id'] + '!'
                if not origin.startswith(prefix): return None
                links = identity_service(self.plugin)
                session_id = origin[len(prefix):]
                link = links.get(scope['user_id'], session_id)
                if (not link or link.get('app_scope') != scope
                        or not ChatWorkspace(links).settings(scope['user_id'],session_id)['values']['linked_calendar']):
                    return None
                user = (service.data.get('users') or {}).get(link['qq_scope']['user_id'])
            return occasion_reason(scope, user, self.clock()) if isinstance(user, dict) else None

    async def pc_tick(self,scope):
        if self.pc_integration is None or not self.active:
            return {'state':'disabled','reason':'pc_integration_unavailable'}
        return await self.pc_integration.tick(scope)

    def _pc_reminder_task_allowed(self,scope,task):
        """Unrelated reminders keep their original permission and task fence."""
        pc=self.pc_integration
        if pc is not None and pc.memos.owns_task(scope,task):
            return pc.memos.delivery_allowed(scope,task)
        # A persisted PC task must remain closed if optional integration was
        # not constructed; absence of an object is never a bypass.
        if self.reminders is not None:
            with self.reminders.journal._lock:
                row=self.reminders.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?',
                    (task.get('reminder_binding',{}).get('occurrence_id'),)).fetchone()
            if row:
                value=json.loads(row[0])
                if value.get('source_id','').startswith(('pc.memo:','pc.timer:')):return False
        return True

    async def _task_delivery_allowed(self,scope,task):
        """Every native task must have one exact, still-current producer."""
        if not self._delivery_allowed(scope):return False
        daily=getattr(self.runtime,'pc_daily_lifecycle',None)
        if daily is not None and daily.owns_task(scope,task):
            return await daily.delivery_allowed(scope,task) is True
        integrations=getattr(self.plugin,'_native_server_integrations',None)
        business=getattr(integrations,'_business_delivery',None)
        if business is not None and await business.owns_task(scope,task):
            return await business.delivery_allowed(scope,task) is True
        independent=getattr(integrations,'proactive_chat',None)
        if independent is not None and await independent.owns_task(scope,task):
            return await independent.delivery_allowed(scope,task) is True
        pc=self.pc_integration
        if pc is not None and pc.nonrandom is not None and pc.nonrandom.owns_task(scope,task):
            if await pc.nonrandom.delivery_allowed(scope,task) is not True:return False
        if self.proactive is not None and await self.proactive.owns_task(scope,task):
            allowed=await self.proactive.delivery_allowed(scope,task)
            return allowed is True and self._proactive_allowed(scope) and self._legacy_quiescent(scope)
        if self.phone is not None and await self.phone.owns_task(scope,task):
            return await self.phone.delivery_allowed(scope,task) is True and self._delivery_allowed(scope)
        return False

    async def _proactive_environment(self,scope,topic):
        if not self._proactive_allowed(scope):return None
        integration=getattr(self.plugin,'_presence',None)
        prepare=getattr(integration,'_prepare_context',None)
        if not callable(prepare):return ''
        # Read the prepared projection, without committing its outlet dedupe.
        block,_selected,_memory_scope=prepare(scope,query=topic,max_chars=420,
            now=self.clock(),channel='tls.native.proactive')
        return block if self._proactive_allowed(scope) else None

    def _configure_proactive(self):
        unified=getattr(self.runtime,'unified',None)
        if unified is None or not callable(getattr(unified,'context_generation',None)):return
        activated=self.plugin._cfg('living_proactive_activated_at',0)
        if (type(activated) not in (int,float) or not math.isfinite(activated)
                or not 0<=activated<=self.clock()+30):
            self.proactive_config_error='invalid_activation_timestamp'
            return
        from .native_proactive_generation import NativeProactiveGeneration
        from .native_proactive_companion import NativeProactiveCompanion
        from .native_proactive_persona_binding import NativeProactivePersonaBinding
        from .native_legacy_companion_inspection import current_legacy_persona
        self.persona_binding=NativeProactivePersonaBinding(self.runtime.journal,
            authorize=self._proactive_allowed,
            expected_legacy_persona=lambda scope:current_legacy_persona(self.host.context),clock=self.clock)
        self.generator=NativeProactiveGeneration(self.host.context,self.runtime.journal,unified,self.delivery,
            authorize=self._proactive_allowed,context_generation=unified.context_generation,
            persona_allowed=self.persona_binding.allow,environment_for=self._proactive_environment,clock=self.clock)
        self.proactive=NativeProactiveCompanion(self.host,self.runtime,self.generator,self.image_service,
            authorize=self._proactive_allowed,clock=self.clock,
            transition_until=float(activated)+2700)
        self.runtime.proactive_companion=self.proactive
        self.runtime.proactive_generation=self.generator
        self.runtime.proactive_persona_binding=self.persona_binding

    async def proactive_tick(self,scope):
        if (self.proactive is None or not self._proactive_allowed(scope)
                or not self._legacy_quiescent(scope) or not await self.ensure_phone_scope(scope)):
            return {'state':'disabled','reason':'native_owner_or_legacy_quiescence_unproven'}
        return await self.proactive.tick(scope)

    def _configure_phone(self):
        from .native_phone_connector import NativePhoneConnector
        from .native_phone_messages import NativePhoneMessages
        from .native_phone_companion import NativePhoneCompanion
        from .native_image_service import NativeImageService
        path=self.path/'living'/'phone_runtime.private.json'
        if path.is_symlink() or path.stat().st_size>128*1024:raise ValueError('bounded private phone configuration required')
        value=json.loads(path.read_text(encoding='utf-8'))
        if (set(value)!={'schema','bridge_url','bridge_token','user_devices','image','appearance','clothing_hint','surprises','activated_at'}
                or value['schema']!='tls.native.phone.runtime.v1'):
            raise ValueError('native phone configuration schema')
        from .delivery_types import number
        activated_at=number(value['activated_at'],'phone activation timestamp',maximum=self.clock()+30)
        if activated_at==0:raise ValueError('phone lane not activated')
        connector=NativePhoneConnector(value['bridge_url'],value['bridge_token'],value['user_devices'],
            authorize=self._delivery_allowed,clock=self.clock)
        messages=NativePhoneMessages(custom_lines=self.plugin._cfg('living_phone_custom_lines',[]),
            surprises=value['surprises'])
        self.image_service=NativeImageService(value['image'],media_root=self.path/'media',
            state_path=self.path/'living'/'native_images.sqlite3',authorize=self._delivery_allowed,
            appearance=value['appearance'],clothing_hint=value['clothing_hint'],clock=self.clock)
        self.phone=NativePhoneCompanion(self.host,self.runtime,connector,messages,self.image_service,
            transition_until=activated_at+2700,warm_start=True)
        self.runtime.phone_companion=self.phone
        self.runtime.image_service=self.image_service

    def abort_initialization(self):
        self.active=False
        if self.pc_integration is not None:self.pc_integration.stop()
        if self.proactive is not None:self.proactive.stop()
        if self.generator is not None:self.generator.stop()
        if self.persona_binding is not None:self.persona_binding.stop()
        if self.phone is not None:self.phone.stop()
        if self.image_service is not None:self.image_service.abort_initialization()

    def start(self):
        if self.started or not self.active:
            return
        if self.reminders is not None:
            self.reminders.start(poll_seconds=1)
        if self.delivery is not None:
            self.delivery.start(poll_seconds=1)
        self.started = True

    async def create_reminder(self, scope, event_id, *, delay_seconds, text):
        """A stable user command maps to one persisted occurrence across retries."""
        scope = private_scope(scope)
        if self.reminders is None or not self._reminder_allowed(scope):
            raise PermissionError('native reminders unavailable for this session')
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 256
                or type(delay_seconds) not in (int, float) or not 1 <= delay_seconds <= 366*86400
                or not isinstance(text, str) or not 1 <= len(text.strip()) <= 3000):
            raise ValueError('bounded explicit reminder command required')
        text = text.strip()
        identity = hashlib.sha256(canonical(['tls.user.reminder', scope, event_id]).encode()).hexdigest()
        signature = hashlib.sha256(canonical([delay_seconds, text]).encode()).hexdigest()
        namespace = 'tls.native.command_reminders'

        def prepare():
            if not self._reminder_allowed(scope):
                raise PermissionError('reminder session revoked')
            prior = self.runtime.journal.fetch(namespace, identity, scope)
            if prior is None:
                record = dict(signature=signature, due_at=self.clock()+delay_seconds, source_id='tls.'+identity)
                try:
                    prior = self.runtime.journal.put(namespace, identity, scope, record,
                        expected_revision=0, authorize=lambda: self._reminder_allowed(scope))
                except JournalConflict:
                    prior = self.runtime.journal.fetch(namespace, identity, scope)
            if prior is None or prior['data']['signature'] != signature:
                raise JournalConflict('reminder command identity content conflict')
            owner = self.reminders.store.owner(scope)
            if owner['mode'] != 'tls':
                try:
                    self.reminders.set_mode(scope, 'tls', owner['generation'])
                except DeliveryConflict:
                    if self.reminders.store.owner(scope)['mode'] != 'tls':
                        raise
            consent_id = 'tls-explicit-' + hashlib.sha256(canonical(scope).encode()).hexdigest()[:24]
            self.reminders.grant(scope, consent_id, evidence='user_explicit')
            return prior['data'], consent_id

        record, consent_id = await asyncio.to_thread(prepare)
        return await self.reminders.create_once(scope, record['source_id'], due_at=record['due_at'],
            text=text, consent_id=consent_id)

    def _queue_workers(self):
        """Only exact-source native queue workers on this event loop."""
        from . import delivery_scheduler
        expected=Path(delivery_scheduler.__file__).resolve()
        tasks=asyncio.all_tasks()
        if len(tasks)>4096:raise RuntimeError('native queue worker scan capacity')
        for task in tasks:
            if task.done() or not task.get_name().startswith('tls-native-delivery-'):continue
            coro=task.get_coro();code=getattr(coro,'cr_code',None);frame=getattr(coro,'cr_frame',None)
            if code is None or frame is None or code.co_name!='run' or Path(code.co_filename).resolve()!=expected:continue
            worker=frame.f_locals.get('self')
            callback=getattr(worker,'authorize',None);owner=getattr(callback,'__self__',None)
            service=getattr(getattr(owner,'authorize',None),'__self__',None) if hasattr(owner,'driver') else owner
            plugin=getattr(service,'plugin',None)
            if plugin is not None:yield worker,service,plugin

    async def retire_stopping_queue_workers(self):
        """Finish only our stopped predecessor's workers after a failed unload.

        Old memory work and its databases stay retained. The existing scheduler
        close path preserves uncertain dispatch rather than replaying it.
        """
        retired=0
        for worker,service,plugin in list(self._queue_workers()):
            if (plugin is self.plugin or getattr(plugin,'context',None) is not self.host.context
                    or getattr(plugin,'_stopping',False) is not True
                    or Path(service.path).resolve()!=self.path.resolve()
                    or worker.node!=self.node):continue
            worker.active=False;worker.sender.active=False
            await worker.close()
            retired+=1
        self._retired_queue_workers=retired

    def queue_authority_status(self, scope):
        """Event-loop-only object/authorization checks, without message data."""
        def quiet_policy():
            policy=getattr(self.delivery,'policy',None)
            return dict(delivery_quiet_hours=getattr(policy,'quiet_hours',''),
                legacyquiet_enabled=getattr(policy,'quiet_enabled',None),
                legacyquiet_start=getattr(policy,'quiet_start',None),legacyquiet_end=getattr(policy,'quiet_end',None))
        reminder=self.reminders
        current_host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        recovery=getattr(self.plugin,'_session_recovery',None)
        recovery=recovery if isinstance(recovery,dict) else {}
        result=dict(current_host=current_host is self.host,
            reminder_same_object=reminder is getattr(self.runtime,'reminders',None)
                and reminder is getattr(getattr(self.runtime,'agenda',None),'reminders',None),
            reminder_authorized=bool(scope and reminder and reminder._authorized(scope)),
            scope_authorized=bool(scope and self.host.authorized_scope(scope)),
            reminder_active=bool(reminder and reminder.active),
            reminder_worker_alive=bool(reminder and reminder.driver._worker and not reminder.driver._worker.done()),
            reminder_claims=reminder.driver.metrics['steps'] if reminder else 0,
            restored_scopes=recovery.get('restored_scopes',0) if type(recovery.get('restored_scopes',0)) is int else 0,
            restored_pc=recovery.get('pc_bound') is True,
            retired_stopping_workers=getattr(self,'_retired_queue_workers',0),
            worker_count=0,current_workers=0,stopping_owner_workers=0,
            foreign_context_workers=0,worker_scope_allowed=0)
        # Only inspect our scheduler's named, exact-source coroutines. No
        # arbitrary locals, task names, object IDs or private scope leave here.
        try:workers=list(self._queue_workers())
        except RuntimeError:return dict(result,**quiet_policy(),worker_scan='capacity_unknown')
        for worker,service,plugin in workers:
            callback=worker.authorize
            result['worker_count']+=1
            if getattr(plugin,'context',None) is not self.host.context:
                result['foreign_context_workers']+=1;continue
            result['current_workers']+=int(plugin is self.plugin)
            result['stopping_owner_workers']+=int(getattr(plugin,'_stopping',False) is True)
            if scope:
                try:result['worker_scope_allowed']+=int(callback(scope) is True)
                except Exception:pass
        return dict(result,**quiet_policy(),worker_scan='current_loop_only')

    def diagnostics(self):
        from .native_legacy_companion_inspection import inspect_legacy_companion
        return dict(environment=self.environment, active=self.active, started=self.started,
            explicit_reminders=self.reminders is not None,
            pc_integration=self.pc_integration.diagnostics() if self.pc_integration is not None else {'active':False},
            companion_delivery=self.delivery is not None,
            phone_companion=self.phone.diagnostics() if self.phone is not None else {'active':False},
            proactive_companion=dict(configured=self._flag('living_proactive_companion_enabled'),
                configuration_error=self.proactive_config_error,
                runtime=self.proactive.diagnostics() if self.proactive is not None else {'active':False}),
            legacy_proactive=inspect_legacy_companion(self.host.context),
            legacy_tasks_imported=False, normal_chat_ownership_changed=False)


def attach_native_services(host, runtime, data_dir):
    if not any(host.plugin._cfg_bool(key, False) for key in
               ('living_native_reminders_enabled', 'living_native_delivery_enabled')):
        return None
    services = NativeHostServices(host, runtime, data_dir)
    runtime.native_services = services
    return services
