"""Host-tick app-entry composition through the existing native delivery owner.

No timers, Presence registration, old phone business calls or direct sends.
The host separately transfers the legacy app-greeting lane. Other phone care,
music and Presence providers retain their current owners. Scheduler preflight
must pass before image generation; the queue still rechecks before dispatch.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import inspect
from pathlib import Path
import re
import stat

from .journal import JournalConflict
from .models import EvidenceKind, Observation, canonical, plain, private_scope, scope_key
from .native_phone_candidates import NativePhoneCandidatePolicy

NAMESPACE='tls.native.phone_companion.v1'
_HASH=re.compile(r'[a-f0-9]{64}\Z')
_PENDING={'approved','queued','claimed','sending','retry_wait','paused'}


class NativePhoneCompanion:
    """One inflight host call and a 15-second poll floor; no worker is started.

    The connector is owned here and closed here. Image service, scheduler and
    journal are shared host resources. Existing journal checkpoints hold only
    this lane's pending task references, allowing receipt reconciliation after
    restart without regenerating or resubmitting uncertain work.
    """
    def __init__(self,host,runtime,connector,messages,image_service,*,transition_until=0,warm_start=False):
        from .delivery_types import number
        self.transition_until=number(transition_until,'phone transition',maximum=253402300799)
        if type(warm_start) is not bool:raise ValueError('explicit phone warm-start flag required')
        self.warm_start=warm_start;self._seen_devices=OrderedDict();self._observations=OrderedDict()
        self.host,self.runtime=host,runtime
        self.connector,self.messages,self.image_service=connector,messages,image_service
        self.clock=host.clock;self.active=True;self._inflight=None;self._last_tick=None
        self._scopes={};self._configuration=None
        self.policy=NativePhoneCandidatePolicy(runtime.journal,{},authorize=self._authorized,
            clock=self.clock,candidate_ttl_seconds=300)
        self._metrics=dict(ticks=0,reads=0,candidates=0,images=0,submitted=0,acked=0,unknown=0,failed=0,errors=0)
        self._last_reason='idle'
        self._last_admission_reason=None
        self._music_last_reason='idle'
        self._music_metrics=dict(music_candidates=0,music_submitted=0,music_acked=0)

    def _cfg(self,key,default):return self.host.plugin._cfg(key,default)

    def _authorized(self,scope):
        try:
            if scope.get('platform')=='webchat':
                from .chat_workspace import linked_source_scope
                if linked_source_scope(self.host.plugin,scope,permission='perception') is None:return False
            scheduler=getattr(self.runtime,'delivery',None)
            return (self.active and self.host.plugin._cfg_bool('living_phone_companion_enabled',False) is True
                    and self.host.authorized_scope(scope) is True and scheduler is not None
                    and getattr(scheduler,'active',False) is True
                    and callable(getattr(scheduler,'preflight',None)))
        except Exception:return False

    def _now(self):
        from .delivery_types import number
        return number(self.clock(),'phone companion clock',maximum=253402300799)

    @staticmethod
    async def _value(callback,*args,**kwargs):
        result=callback(*args,**kwargs)
        return await result if inspect.isawaitable(result) else result

    def _result(self,state,reason,**details):
        self._last_reason=reason
        return dict(state=state,reason=reason,**details)

    def _plan(self,scope,now):
        from .native_app_rules import NativeAppRules
        config=self.messages.export()['config']
        lines=self._cfg('living_phone_custom_lines',[])
        if lines!=config['custom_lines']:
            config['custom_lines']=lines;self.messages.configure(**config)
        scheduler=self.runtime.delivery
        app=self._cfg('living_phone_app_cooldown_minutes',120)
        shared=self._cfg('living_phone_shared_cooldown_minutes',10)
        if type(app) is not int or not 10<=app<=1440 or type(shared) is not int or not 1<=shared<=1440:
            raise ValueError('invalid configured phone cooldown')
        rules=NativeAppRules(self._cfg('living_app_rules','[]'))
        plan=rules.compile(scope,self.messages,hour=scheduler.policy.local_time(now).hour,
            app_cooldown_minutes=app,shared_cooldown_minutes=shared)
        plan.update(app_cooldown_minutes=app,rule_config=rules)
        return plan

    def _new_policy(self,plan):
        scheduler=self.runtime.delivery
        overrides={package:dict(cooldown_seconds=row['effective_cooldown_minutes']*60,
            priority=row['priority'],rule_id=row['rule_id']) for package,row in plan['per_app'].items()
            if row['enabled'] and row['rule_id'] is not None}
        return NativePhoneCandidatePolicy(self.runtime.journal,plan['candidate_rules'],authorize=self._authorized,
            clock=self.clock,app_cooldown_seconds=plan['app_cooldown_minutes']*60,
            shared_cooldown_seconds=plan['shared_cooldown_minutes']*60,per_app_policy=overrides or None,
            candidate_ttl_seconds=300,timezone_offset_minutes=scheduler.policy.tz_offset_minutes)

    def _configure_scope(self,scope,now):
        plan=self._plan(scope,now)
        digest=hashlib.sha256(canonical([plan['rules_digest'],plan['candidate_rules'],
            self.runtime.delivery.policy.tz_offset_minutes]).encode()).hexdigest()
        if digest!=self._configuration:
            policy=self._new_policy(plan)
            self.policy.close();self.policy=policy;self._configuration=digest
        return plan

    def _rules_current(self,scope,digest):
        try:return self._authorized(scope) and self._plan(scope,self._now())['rules_digest']==digest
        except (ValueError,TypeError):return False

    def _music_plan(self,scope,now):
        """Use the current paired APP source and its original quiet policy."""
        if scope['platform']!='webchat' or scope['bot_id']!='webchat':
            raise PermissionError('music_app_only')
        enabled=self._cfg('living_phone_music_notifications_enabled',False)
        minutes=self._cfg('living_phone_music_cooldown_minutes',45)
        if type(enabled) is not bool or type(minutes) is not int or not 10<=minutes<=1440:
            raise ValueError('music_configuration_invalid')
        if not enabled:return dict(enabled=False,cooldown=minutes*60,quiet=False,digest=None)
        proactive=getattr(self.host.plugin,'_native_proactive_chat',None)
        if (proactive is None or getattr(proactive,'host',None) is not self.host
                or getattr(proactive,'active',False) is not True
                or not proactive._allowed(scope)):
            raise PermissionError('music_proactive_source_unavailable')
        config=proactive._get_session_config(scope['session_id'])
        zone=proactive.timezone
        if not isinstance(config,dict) or config.get('enable') is not True or zone is None:
            raise PermissionError('music_proactive_policy_unavailable')
        quiet=config.get('schedule_settings',{}).get('quiet_hours')
        if not isinstance(quiet,str) or not 1<=len(quiet)<=143:raise ValueError('music_quiet_policy_invalid')
        ranges=quiet.split(',')
        if not 1<=len(ranges)<=24:raise ValueError('music_quiet_policy_invalid')
        for window in ranges:
            parts=window.split('-')
            if len(parts)!=2 or any(not part.strip().isdigit() for part in parts):raise ValueError('music_quiet_policy_invalid')
            if any(not 0<=int(part.strip())<=23 for part in parts):raise ValueError('music_quiet_policy_invalid')
        from .native_proactive_chat.utils.time_utils import is_quiet_time
        quiet_now=is_quiet_time(quiet,zone,now=now)
        digest=hashlib.sha256(canonical(['tls.phone.music.settings.v1',enabled,minutes,
            proactive.policy_session(scope['session_id']),quiet,str(zone)]).encode()).hexdigest()
        return dict(enabled=True,cooldown=minutes*60,quiet=quiet_now,digest=digest)

    def _music_result(self,state,reason,**details):
        self._music_last_reason=reason
        return dict(state=state,reason=reason,kind='music',**details)

    def _work_current(self,scope,work):
        if work.get('kind')=='music':
            try:
                plan=self._music_plan(scope,self._now())
                return (self._authorized(scope) and plan['enabled'] and not plan['quiet']
                    and plan['digest']==work.get('settings_digest') and self._now()<work['expires_at'])
            except (AttributeError,ValueError,TypeError,KeyError,PermissionError):return False
        digest=work.get('rules_digest')
        if digest is not None:return self._rules_current(scope,digest)
        # Pre-R7 tasks retain their old behavior until scoped rules are added.
        try:return self._authorized(scope) and not self._plan(scope,self._now())['rule_config'].list(scope)
        except (ValueError,TypeError):return False

    async def owns_task(self,scope,task):
        scope=private_scope(scope)
        if not isinstance(task,dict) or task.get('scope')!=scope:return False
        record=await self._fetch_pending(scope)
        work=record['data'] if record else None
        return isinstance(work,dict) and work.get('task_id')==task.get('id')

    async def delivery_allowed(self,scope,task=None):
        """Final host/SDK guard for this lane, including rule edits after enqueue."""
        scope=private_scope(scope)
        if not self._authorized(scope):return False
        record=await self._fetch_pending(scope)
        if task is not None:
            work=record['data'] if record else None
            if (not isinstance(task,dict) or task.get('scope')!=scope or not isinstance(work,dict)
                    or work.get('task_id')!=task.get('id')):return False
        if not record or record['data'] is None:return self._work_current(scope,{})
        return self._work_current(scope,record['data'])

    def _quiet(self,scope,row,state,now):
        quiet=max(state['rest_until'],state['shared_last_sent_at']+2700 if state['shared_last_sent_at'] else 0)
        seed=(self.warm_start and (scope_key(scope),row.device_id) not in self._seen_devices
              or self.transition_until>0 and row.observed_at is not None and row.observed_at<self.transition_until)
        return max(quiet,self.transition_until,now+1 if seed else 0)

    async def preview(self,scope,package,*,observation=None,rule_id=None):
        """Read-only real eligibility when a trusted observation is available.

        With just an editor's package sample, live checks stay explicitly
        pending. This method never polls PPB, generates an image or reserves.
        """
        scope=private_scope(scope)
        if not self._authorized(scope):raise PermissionError('native phone scope unavailable')
        now=self._now();plan=self._plan(scope,now);check=None;preflight=None
        if observation is not None:
            if (not isinstance(observation,Observation) or observation.scope!=scope
                    or not isinstance(observation.payload,dict) or observation.payload.get('foreground_package')!=package):
                raise ValueError('scope-bound backend App observation required')
            state=await self._state(scope)
            policy=self._new_policy(plan)
            try:check=await asyncio.to_thread(policy.preview,observation,
                quiet_until=self._quiet(scope,observation,state,self._now()),shared_last_sent_at=state['shared_last_sent_at'])
            finally:policy.close()
            if check['allowed']:
                preflight=await self.runtime.delivery.preflight(scope,'tls.phone.app:'+check['candidate']['id'])
        if not self._rules_current(scope,plan['rules_digest']):raise JournalConflict('App rule configuration changed during preview')
        result=plan['rule_config'].preview(scope,dict(trigger='app_enter',package=package),self.messages,
            hour=self.runtime.delivery.policy.local_time(now).hour,rule_id=rule_id,
            app_cooldown_minutes=plan['app_cooldown_minutes'],shared_cooldown_minutes=plan['shared_cooldown_minutes'],
            candidate_check=check,preflight=preflight,delivery_policy=self.runtime.delivery.policy)
        result.update(connection_state='not_observed' if observation is None else
            'observed' if observation.valid_at(self._now()) and observation.observed_at<=self._now() else 'stale',
            observed_at=observation.observed_at if observation else None,expires_at=observation.expires_at if observation else None)
        return result

    async def preview_rules(self,scope,event,*,rule_id=None):
        """Editor sample plus only this host's already observed PPB data."""
        scope=private_scope(scope)
        if not isinstance(event,dict) or set(event)!={'trigger','package'} or event['trigger']!='app_enter':
            raise ValueError('closed App-entry preview event required')
        row=self._observations.get((scope_key(scope),event['package']))
        return await self.preview(scope,event['package'],observation=row,rule_id=rule_id)

    async def _state(self,scope):
        from .delivery_types import number
        state=await self._value(self.runtime.delivery.read_state,scope)
        required=('last_activity_at','rest_until','shared_last_sent_at','shared_sent_today')
        if not isinstance(state,dict) or any(key not in state for key in required):raise ValueError('shared phone state unavailable')
        for key in required:number(state[key],key)
        now=self._now()
        if state['last_activity_at']<=0 or state['last_activity_at']>now+30 or state['shared_last_sent_at']>now+30:
            raise ValueError('shared phone activity clock unavailable')
        if type(state['shared_sent_today']) is not int:raise ValueError('shared phone count unavailable')
        return state

    async def _fetch_pending(self,scope):
        record=await asyncio.to_thread(self.runtime.journal.fetch,NAMESPACE,'pending',scope)
        if record and record['data'] is not None:
            data=record['data']
            if (not isinstance(data,dict) or data.get('schema')!=1 or data.get('scope')!=scope
                    or not isinstance(data.get('candidate_id'),str) or not _HASH.fullmatch(data['candidate_id'])
                    or not isinstance(data.get('task_id'),str) or not _HASH.fullmatch(data['task_id'])):
                raise ValueError('invalid phone workflow checkpoint')
        return record

    async def _save_pending(self,scope,data,revision):
        return await asyncio.to_thread(self.runtime.journal.put,NAMESPACE,'pending',scope,data,
            expected_revision=revision,authorize=lambda:self._authorized(scope))

    async def _settle(self,scope,record,outcome):
        work=record['data']
        await asyncio.to_thread(self.policy.finish,scope,work['candidate_id'],outcome,
                                expected_revision=work['candidate_revision'])
        await self._save_pending(scope,None,record['revision'])
        self._scopes.pop(scope_key(scope),None);self._metrics[outcome if outcome!='acked' else 'acked']+=1
        if work.get('kind')=='music':
            if outcome=='acked':self._music_metrics['music_acked']+=1
            return self._music_result(outcome,'delivery_'+outcome,task_id=work['task_id'])
        return self._result(outcome,'delivery_'+outcome,task_id=work['task_id'])

    async def _reconcile(self,scope,record):
        if not record or record['data'] is None:return None
        work=record['data'];self._scopes[scope_key(scope)]=scope
        task=await asyncio.to_thread(self.runtime.delivery.store.get,work['task_id'])
        if task is None:
            # A crash/exception after starting preparation or submission is not
            # permission to create another image or retry an uncertain task.
            return await self._settle(scope,record,'unknown')
        state=task.get('state')
        if state in ('candidate','approved','queued','retry_wait','paused') and not self._work_current(scope,work):
            await self.runtime.delivery.control(work['task_id'],'cancel')
            return await self._settle(scope,record,'failed')
        if state=='confirmed':return await self._settle(scope,record,'acked')
        if state in ('unknown','quarantined'):return await self._settle(scope,record,'unknown')
        if state in ('failed','cancelled','expired'):return await self._settle(scope,record,'failed')
        if state in ('candidate','approved','queued','retry_wait','paused') and self._now()>=work['expires_at']:
            await self.runtime.delivery.control(work['task_id'],'cancel')
            return await self._settle(scope,record,'failed')
        if state=='candidate':
            await self.runtime.delivery.control(work['task_id'],'cancel')
            return await self._settle(scope,record,'failed')
        if state in _PENDING:
            result=self._music_result if work.get('kind')=='music' else self._result
            return result('pending','awaiting_native_receipt',task_id=work['task_id'])
        return await self._settle(scope,record,'unknown')

    def _image_path(self,result):
        if (not isinstance(result,dict) or result.get('ok') is not True or result.get('state')!='ready'
                or result.get('fresh') is not True or result.get('prepared_replay') is not False
                or not isinstance(result.get('path'),str) or not isinstance(result.get('image_sha256'),str)
                or not _HASH.fullmatch(result['image_sha256'])):raise ValueError('new task image required')
        path=Path(result['path']);root=Path(self.image_service.media_root).resolve()
        if not path.is_absolute() or path.resolve()!=path or not path.is_relative_to(root):raise ValueError('owned local media required')
        if any(part.is_symlink() for part in (path,*path.parents)):raise ValueError('linked media refused')
        before=path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 1<=before.st_size<=20*1024*1024:
            raise ValueError('bounded regular image required')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=result['image_sha256']:raise ValueError('prepared image checksum differs')
        after=path.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('prepared image changed')
        adapter_root=getattr(getattr(self.runtime.delivery.sender,'adapter',None),'media_root',root)
        if not path.is_relative_to(Path(adapter_root).resolve()):raise ValueError('image outside delivery media root')
        return str(path)

    async def _music_tick(self,scope,rows,state,record):
        music=[row for row in rows if isinstance(row,Observation) and row.scope==scope
               and row.source_id=='phone.music' and row.observation_type=='music']
        music.sort(key=lambda row:(row.observed_at or 0,row.device_id or ''),reverse=True)
        if not music:
            self._music_last_reason=('no_fresh_music_track' if
                self._cfg('living_phone_music_notifications_enabled',False) is True else 'music_disabled')
            return None
        try:plan=self._music_plan(scope,self._now())
        except PermissionError as exc:
            self._music_last_reason=str(exc);return None
        except (AttributeError,ValueError,TypeError,KeyError):
            self._music_last_reason='music_configuration_invalid';return None
        for row in music:
            now=self._now()
            quiet=max(state['rest_until'],self.transition_until,now+1 if plan['quiet'] else 0)
            result=await asyncio.to_thread(self.policy.observe_music,row,quiet_until=quiet,
                shared_last_sent_at=state['shared_last_sent_at'],music_cooldown_seconds=plan['cooldown'],
                enabled=plan['enabled'])
            self._music_last_reason=result['reason']
            candidate=result.get('candidate')
            if candidate is None:continue
            self._metrics['candidates']+=1;self._music_metrics['music_candidates']+=1
            work=dict(schema=1,kind='music',scope=scope,candidate_id=candidate['id'],
                candidate_revision=candidate['revision'],event_id='tls.phone.music:'+candidate['id'],
                expires_at=candidate['expires_at'],stage='submitting',settings_digest=plan['digest'])
            if not self._work_current(scope,work):
                await asyncio.to_thread(self.policy.finish,scope,candidate['id'],'failed',expected_revision=candidate['revision'])
                return self._music_result('blocked','music_settings_changed')
            admission=await self.runtime.delivery.preflight(scope,work['event_id'])
            self._last_admission_reason=(admission.get('reason') if isinstance(admission,dict)
                and isinstance(admission.get('reason'),str) else 'admission_result_unavailable')
            if (not isinstance(admission,dict) or admission.get('allowed') is not True
                    or not self._work_current(scope,work)):
                await asyncio.to_thread(self.policy.finish,scope,candidate['id'],'failed',expected_revision=candidate['revision'])
                return self._music_result('blocked','native_admission_denied')
            task_id=admission.get('task_id')
            if not isinstance(task_id,str) or not _HASH.fullmatch(task_id):raise ValueError('native music task binding required')
            work['task_id']=task_id
            record=await self._save_pending(scope,work,record['revision'] if record else 0)
            self._scopes[scope_key(scope)]=scope
            if not self._work_current(scope,work):return await self._settle(scope,record,'failed')
            try:
                task=await self.runtime.delivery.submit(scope,work['event_id'],text=candidate['text'],images=[],
                    expires_at=candidate['expires_at'],priority=50,trigger='event',max_attempts=1,text_only=True)
            except asyncio.CancelledError:raise
            except Exception:return self._music_result('pending','submission_uncertain',task_id=task_id)
            self._metrics['submitted']+=1;self._music_metrics['music_submitted']+=1
            work['stage']='submitted';record=await self._save_pending(scope,work,record['revision'])
            if not isinstance(task,dict) or task.get('id')!=task_id:raise ValueError('native music submission identity differs')
            return await self._reconcile(scope,record)
        return None

    async def tick(self,scope):
        scope=private_scope(scope)
        if not self._authorized(scope):return self._result('disabled','scope_or_lane_unavailable')
        if self._inflight is not None:return self._result('busy','one_phone_tick_inflight')
        if scope_key(scope) not in self._scopes and len(self._scopes)>=32:return self._result('blocked','pending_scope_capacity')
        now=self._now()
        if self._last_tick is not None and now<self._last_tick:return self._result('blocked','clock_moved_backwards')
        if self._last_tick is not None and now-self._last_tick<15:return self._result('throttled','poll_interval')
        self._last_tick=now;self._inflight=asyncio.current_task();self._metrics['ticks']+=1
        try:
            record=await self._fetch_pending(scope)
            reconciled=await self._reconcile(scope,record)
            if reconciled:return reconciled
            try:plan=self._configure_scope(scope,now)
            except (ValueError,TypeError):return self._result('blocked','phone_configuration_invalid')
            try:state=await self._state(scope)
            except (ValueError,TypeError,OSError):return self._result('blocked','shared_state_unavailable')
            if not self._authorized(scope):return self._result('disabled','scope_or_lane_unavailable')
            self._metrics['reads']+=1;rows=await self.connector.read(scope)
            if not self._authorized(scope):return self._result('disabled','scope_or_lane_unavailable')
            if not isinstance(rows,list) or len(rows)>64:raise ValueError('bounded phone observations required')
            apps=[row for row in rows if isinstance(row,Observation) and row.scope==scope
                  and row.source_id=='phone.device' and row.observation_type=='device.app']
            apps.sort(key=lambda row:(row.observed_at or 0,row.device_id or ''),reverse=True)
            # Config may change during the bridge read; compile the current
            # rules before considering any returned event.
            try:plan=self._configure_scope(scope,self._now())
            except (ValueError,TypeError):return self._result('blocked','phone_configuration_invalid')
            music_result=await self._music_tick(scope,rows,state,record)
            if music_result is not None:return music_result
            for row in apps:
                now=self._now();device_key=(scope_key(scope),row.device_id)
                if (row.evidence_kind==EvidenceKind.REAL_OBSERVATION and isinstance(row.payload,dict)
                        and isinstance(row.payload.get('foreground_package'),str)):
                    key=(scope_key(scope),row.payload['foreground_package']);previous=self._observations.get(key)
                    if previous is None or (row.observed_at or 0)>(previous.observed_at or 0):self._observations[key]=row
                    self._observations.move_to_end(key)
                    while len(self._observations)>128:self._observations.popitem(last=False)
                quiet=self._quiet(scope,row,state,now)
                result=await asyncio.to_thread(self.policy.observe,row,quiet_until=quiet,
                                               shared_last_sent_at=state['shared_last_sent_at'])
                if (row.device_id and row.evidence_kind==EvidenceKind.REAL_OBSERVATION and row.valid_at(now)
                        and row.observed_at<=now):
                    self._seen_devices[device_key]=None;self._seen_devices.move_to_end(device_key)
                    while len(self._seen_devices)>1024:self._seen_devices.popitem(last=False)
                candidate=result.get('candidate')
                if candidate is None:continue
                self._metrics['candidates']+=1
                digest=plan['rules_digest']
                if not self._rules_current(scope,digest):
                    await asyncio.to_thread(self.policy.finish,scope,candidate['id'],'failed',expected_revision=candidate['revision'])
                    return self._result('blocked','app_rules_changed')
                event_id='tls.phone.app:'+candidate['id']
                admission=await self.runtime.delivery.preflight(scope,event_id)
                self._last_admission_reason=(admission.get('reason')
                    if isinstance(admission,dict) and isinstance(admission.get('reason'),str) else 'admission_result_unavailable')
                if (not isinstance(admission,dict) or admission.get('allowed') is not True
                        or not self._rules_current(scope,digest)):
                    await asyncio.to_thread(self.policy.finish,scope,candidate['id'],'failed',expected_revision=candidate['revision'])
                    return self._result('blocked','native_admission_denied')
                task_id=admission.get('task_id')
                if not isinstance(task_id,str) or not _HASH.fullmatch(task_id):raise ValueError('native task binding required')
                work=dict(schema=1,scope=scope,candidate_id=candidate['id'],candidate_revision=candidate['revision'],
                          task_id=task_id,event_id=event_id,expires_at=candidate['expires_at'],stage='preparing',rules_digest=digest)
                record=await self._save_pending(scope,work,record['revision'] if record else 0)
                self._scopes[scope_key(scope)]=scope
                if not self._authorized(scope):return self._result('disabled','scope_or_lane_unavailable')
                if not self._rules_current(scope,digest):return await self._settle(scope,record,'failed')
                if not callable(getattr(self.image_service,'generate',None)):
                    return await self._settle(scope,record,'failed')
                budget=min(180.,candidate['expires_at']-self._now())
                if budget<=0:return await self._settle(scope,record,'failed')
                self._metrics['images']+=1
                try:image=await asyncio.wait_for(
                    self.image_service.generate(scope,task_id,'care',explicit_sexual=False),timeout=budget)
                except asyncio.CancelledError:raise
                except Exception:return await self._settle(scope,record,'unknown')
                if not self._authorized(scope):return self._result('disabled','scope_or_lane_unavailable')
                if not isinstance(image,dict) or image.get('state')=='unknown':return await self._settle(scope,record,'unknown')
                if image.get('state') in ('definite_failure','denied'):return await self._settle(scope,record,'failed')
                if not self._rules_current(scope,digest):return await self._settle(scope,record,'failed')
                try:path=await asyncio.to_thread(self._image_path,image)
                except (ValueError,TypeError,OSError):return await self._settle(scope,record,'failed')
                if self._now()>=candidate['expires_at'] or not self._rules_current(scope,digest):return await self._settle(scope,record,'failed')
                # Recheck opportunity after generation. A new user activity or
                # legacy PC send may have arrived while the image was prepared.
                admission=await self.runtime.delivery.preflight(scope,event_id)
                if not self._rules_current(scope,digest) or admission.get('allowed') is not True:
                    return await self._settle(scope,record,'failed')
                try:
                    task=await self.runtime.delivery.submit(scope,event_id,text=candidate['text'],images=[path],
                        expires_at=candidate['expires_at'],priority=candidate.get('priority',50),trigger='event',max_attempts=1)
                except asyncio.CancelledError:raise
                except Exception:return self._result('pending','submission_uncertain',task_id=task_id)
                self._metrics['submitted']+=1
                work['stage']='submitted';record=await self._save_pending(scope,work,record['revision'])
                if not isinstance(task,dict) or task.get('id')!=task_id:raise ValueError('native submission identity differs')
                return await self._reconcile(scope,record)
            return self._result('idle','no_fresh_app_entry')
        except asyncio.CancelledError:
            raise  # Durable pending reference and image owner retain uncertainty.
        except Exception:
            self._metrics['errors']+=1
            return self._result('blocked','phone_tick_failed')
        finally:self._inflight=None

    def stop(self):
        self.active=False
        try:current=asyncio.current_task()
        except RuntimeError:current=None
        if self._inflight is not None and self._inflight is not current:self._inflight.cancel()

    async def close(self):
        running=self._inflight;self.stop()
        if running is not None and running is not asyncio.current_task():await asyncio.wait({running},timeout=1)
        # Cancel only this lane's demonstrably unsent queue rows. Never close the
        # shared scheduler or cancel CLAIMED/SENDING platform work here.
        for scope in tuple(self._scopes.values()):
            try:
                record=await self._fetch_pending(scope)
                if not record or record['data'] is None:continue
                task=await asyncio.to_thread(self.runtime.delivery.store.get,record['data']['task_id'])
                if task and task.get('state') in ('candidate','approved','queued','retry_wait','paused'):
                    await self.runtime.delivery.control(task['id'],'cancel')
            except Exception:pass
        self.policy.close()
        await self._value(self.connector.close)

    def diagnostics(self):
        return dict(active=self.active,inflight=self._inflight is not None,poll_seconds=15,
                    pending_scopes=len(self._scopes),last_reason=self._last_reason,
                    last_admission_reason=self._last_admission_reason,**self._metrics,
                    music_enabled=self._cfg('living_phone_music_notifications_enabled',False) is True,
                    music_last_reason=self._music_last_reason,**self._music_metrics,
                    timers_started=0,presence_sources_registered=0,direct_sends=0,
                    warm_start=self.warm_start,transition_active=self._now()<self.transition_until)
