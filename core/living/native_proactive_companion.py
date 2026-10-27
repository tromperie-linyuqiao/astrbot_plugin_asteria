"""One host-tick ordinary proactive lane; no loop, legacy business or sender.

A durable pending record binds one ten-minute event to its generated text and
fresh owned media. A crash only reconciles that task; it never asks a provider
for the same event again. Shared generator/images/scheduler remain host-owned.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
from pathlib import Path
import re
import stat
import time

from .delivery_types import make_task,number,task_input_hash
from .journal import JournalConflict
from .models import canonical,plain,private_scope,scope_key

NAMESPACE='tls.native.proactive_companion.v1'
SCHEMA=1
TOPIC='一次简短自然的日常陪伴；没有具体理由可以不说，不捏造现实经历。'
_HASH=re.compile(r'[a-f0-9]{64}\Z')
_ACTIVE={'candidate','approved','queued','retry_wait','paused','claimed','sending'}
_UNSENT={'candidate','approved','queued','retry_wait','paused'}
_TERMINAL={'acked','failed','dropped','blocked','duplicate','unknown'}
_CANDIDATE_FIELDS={'scope','event_id','task_id','generation_id','text','source_id','evidence_kind',
    'generated_at','expires_at','context_revision','sdk_revision','topic','environment_revision','fresh','delivery_confirmed'}


def event_id_for(now):
    return 'tls.proactive.native:'+str(int(number(now,'proactive clock',maximum=253402300799)//600))


class NativeProactiveCompanion:
    def __init__(self,host,runtime,generator,image_service,*,authorize,clock=time.time,transition_until=0,
                 image_timeout_seconds=180):
        if not callable(authorize) or not callable(clock):raise ValueError('trusted proactive callbacks required')
        if not all(callable(getattr(generator,name,None)) for name in ('generate','is_current')):
            raise ValueError('native proactive generator required')
        self.transition_until=number(transition_until,'proactive transition',maximum=253402300799)
        self.image_timeout=number(image_timeout_seconds,'image timeout',minimum=.01,maximum=180)
        self.host,self.runtime,self.generator,self.image_service=host,runtime,generator,image_service
        self.authorize,self.clock=authorize,clock
        self.active=True;self._inflight=None;self._scopes={};self._last_clock=None
        self._counts=dict(ticks=0,generation_calls=0,image_calls=0,submitted=0,errors=0)
        self._last_reason='idle'

    @staticmethod
    async def _value(callback,*args,**kwargs):
        value=callback(*args,**kwargs)
        return await value if inspect.isawaitable(value) else value

    def _allowed(self,scope):
        try:
            scheduler=getattr(self.runtime,'delivery',None)
            return (self.active and self.authorize(scope) is True and getattr(scheduler,'active',False) is True
                and callable(getattr(scheduler,'preflight',None)))
        except Exception:return False

    def _now(self):return number(self.clock(),'proactive clock',maximum=253402300799)

    def _out(self,state,reason,**values):
        self._last_reason=reason
        return dict(state=state,reason=reason,**values)

    async def _fetch(self,scope):
        row=await asyncio.to_thread(self.runtime.journal.fetch,NAMESPACE,'pending',scope)
        if row is not None:
            work=row['data']
            if (not isinstance(work,dict) or work.get('schema')!=SCHEMA or work.get('scope')!=scope
                    or not isinstance(work.get('event_id'),str) or not re.fullmatch(r'tls\.proactive\.native:[0-9]+',work['event_id'])
                    or not isinstance(work.get('task_id'),str) or not _HASH.fullmatch(work['task_id'])
                    or work.get('phase') not in _TERMINAL|{'generating','imaging','submitting','queued'}
                    or work['task_id']!=make_task(scope,work['event_id'],text='identity',now=work['created_at'])['id']):
                raise ValueError('invalid native proactive pending record')
        return row

    async def _put(self,scope,work,revision):
        return await asyncio.to_thread(self.runtime.journal.put,NAMESPACE,'pending',scope,work,
            expected_revision=revision,authorize=lambda:self._allowed(scope))

    async def _finish(self,scope,row,phase,reason):
        work=dict(row['data'],phase=phase,finished_at=self._now())
        await self._put(scope,work,row['revision']);self._scopes.pop(scope_key(scope),None)
        return self._out(phase,reason,task_id=work['task_id'])

    async def _state(self,scope):
        value=await self._value(self.runtime.delivery.read_state,scope)
        fields=('last_activity_at','rest_until','shared_last_sent_at','shared_sent_today')
        if not isinstance(value,dict) or any(key not in value for key in fields):
            raise ValueError('shared proactive activity unavailable')
        for key in fields:number(value[key],key)
        now=self._now()
        if (value.get('state','current')!='current' or value['last_activity_at']<=0
                or value['last_activity_at']>now+30 or value['shared_last_sent_at']>now+30
                or type(value['shared_sent_today']) is not int):
            raise ValueError('shared proactive activity unavailable')
        return value

    def _candidate(self,scope,value,work):
        if (not isinstance(value,dict) or set(value)!=_CANDIDATE_FIELDS or value['scope']!=scope
                or value['event_id']!=work['event_id'] or value['task_id']!=work['task_id']
                or value['source_id']!='tls.proactive.native' or value['evidence_kind']!='model_inference'
                or value['fresh'] is not True or value['delivery_confirmed'] is not False
                or not isinstance(value['text'],str) or not 1<=len(value['text'].strip())<=500
                or any(not isinstance(value[key],str) or not _HASH.fullmatch(value[key])
                       for key in ('generation_id','context_revision','sdk_revision','environment_revision'))
                or not isinstance(value['topic'],str) or not 1<=len(value['topic'])<=300
                or value['topic']!=value['topic'].strip() or any(ord(char)<32 for char in value['topic'])
                or hashlib.sha256(canonical([scope,work['event_id'],value['topic']]).encode()).hexdigest()!=work['signature']):
            raise ValueError('bound native proactive candidate required')
        generated=number(value['generated_at'],'candidate generation',maximum=253402300799)
        expires=number(value['expires_at'],'candidate expiry',maximum=253402300799)
        if not generated<=self._now()<expires or expires>generated+900:raise ValueError('current proactive candidate required')
        return plain(value,8192)

    def _media(self,value,*,fresh=False):
        if fresh and (not isinstance(value,dict) or value.get('ok') is not True or value.get('state')!='ready'
                or value.get('fresh') is not True or value.get('prepared_replay') is not False):
            raise ValueError('fresh task image required')
        if (not isinstance(value,dict) or not isinstance(value.get('path'),str)
                or not isinstance(value.get('image_sha256'),str) or not _HASH.fullmatch(value['image_sha256'])):
            raise ValueError('bound task image required')
        path=Path(value['path']);root=Path(self.image_service.media_root).resolve()
        if not path.is_absolute() or path.resolve()!=path or not path.is_relative_to(root):
            raise ValueError('owned task image required')
        if any(part.is_symlink() for part in (path,*path.parents)):raise ValueError('linked task image refused')
        before=path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 1<=before.st_size<=20*1024*1024:
            raise ValueError('bounded task image required')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=value['image_sha256']:raise ValueError('task image differs')
        after=path.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('task image changed')
        adapter_root=getattr(getattr(self.runtime.delivery.sender,'adapter',None),'media_root',root)
        if not path.is_relative_to(Path(adapter_root).resolve()):raise ValueError('task image outside sender root')
        return dict(path=str(path),image_sha256=value['image_sha256'])

    async def owns_task(self,scope,task):
        """Routing identity only, including stopped/expired work; never a permit."""
        try:
            scope=private_scope(scope)
            if not isinstance(task,dict) or task.get('scope')!=scope:return False
            row=await self._fetch(scope)
            return row is not None and row['data']['task_id']==task.get('id')
        except Exception:return False

    async def delivery_allowed(self,scope,task):
        """Task-aware final SDK gate; do not run fresh preflight after begin()."""
        try:
            scope=private_scope(scope)
            if not self._allowed(scope) or not isinstance(task,dict) or task.get('scope')!=scope:return False
            row=await self._fetch(scope)
            if row is None:return False
            work=row['data']
            if work['phase'] not in {'submitting','queued'}:return False
            candidate=self._candidate(scope,work.get('candidate'),work)
            image = None if work.get('text_only') is True else await asyncio.to_thread(self._media,work.get('image'))
            if (task.get('id')!=work['task_id'] or task.get('session')!=scope['session_id']
                    or task.get('text')!=candidate['text'] or task.get('images')!=([] if image is None else [image['path']])
                    or task.get('expires_at')!=work['expires_at'] or self._now()>=work['expires_at']
                    or task.get('priority')!=50 or task.get('trigger')!='event' or task.get('max_attempts')!=1
                    or task.get('input_hash')!=task_input_hash(task)):
                return False
            current=await self._fetch(scope)
            if current is None or current['revision']!=row['revision'] or current['data']!=work:return False
            if not await self.generator.is_current(scope,candidate,check_preflight=False):return False
            # This bounded local checkpoint read deliberately has no await:
            # neither source changes during the prior read nor pending edits
            # during the SDK/source check may escape the last sender fence.
            final=self.runtime.journal.fetch(NAMESPACE,'pending',scope)
            return (self._allowed(scope) and final is not None and final['revision']==row['revision']
                    and final['data']==work)
        except Exception:return False

    async def _reconcile(self,scope,row):
        work=row['data'];phase=work['phase']
        if phase in _TERMINAL-{'unknown'}:return self._out(phase,'event_already_settled',task_id=work['task_id'])
        self._scopes[scope_key(scope)]=scope
        task=await asyncio.to_thread(self.runtime.delivery.store.get,work['task_id'])
        if task is None:
            if phase=='unknown':return self._out('unknown','event_outcome_unknown',task_id=work['task_id'])
            return await self._finish(scope,row,'unknown','preparation_or_submission_interrupted')
        state=task['state']
        if state=='confirmed':return await self._finish(scope,row,'acked','native_delivery_confirmed')
        if state in ('unknown','quarantined'):return await self._finish(scope,row,'unknown','native_delivery_unknown')
        if state in ('failed','cancelled','expired'):return await self._finish(scope,row,'failed','native_delivery_not_dispatched')
        if state in _ACTIVE:
            if state in _UNSENT and (self._now()>=work['expires_at']
                    or not await self.generator.is_current(scope,work.get('candidate'),check_preflight=False)):
                await self.runtime.delivery.control(work['task_id'],'cancel')
                return await self._finish(scope,row,'failed','candidate_no_longer_current')
            return self._out('pending','awaiting_native_receipt',task_id=work['task_id'])
        return await self._finish(scope,row,'unknown','native_task_state_unrecognized')

    async def tick(self,scope,topic=TOPIC,*,text_only=False,expires_at=None):
        scope=private_scope(scope)
        if not self._allowed(scope):return self._out('disabled','scope_or_lane_unavailable')
        if self._inflight is not None:return self._out('busy','one_proactive_tick_inflight')
        now=self._now()
        if self._last_clock is not None and now<self._last_clock:return self._out('blocked','clock_moved_backwards')
        self._last_clock=now;self._inflight=asyncio.current_task();self._counts['ticks']+=1
        row=None
        try:
            if type(text_only) is not bool: raise ValueError('media policy must be a boolean')
            expiry = now + 300 if expires_at is None else min(now + 300, number(expires_at, 'reason expiry', maximum=253402300799))
            if expiry <= now: return self._out('dropped', 'reason_expired')
            event_id=event_id_for(now)
            if not isinstance(topic,str) or not 1<=len(topic)<=300 or topic!=topic.strip() or any(ord(char)<32 for char in topic):
                raise ValueError('plain bounded proactive topic required')
            signature=hashlib.sha256(canonical([scope,event_id,topic]).encode()).hexdigest()
            row=await self._fetch(scope)
            if row is not None:
                result=await self._reconcile(scope,row)
                if result['state']=='pending':return result
                if row['data']['event_id']==event_id:
                    if row['data']['signature']!=signature:raise JournalConflict('proactive event topic changed')
                    return result
                row=await self._fetch(scope)  # Reconciliation may have advanced its CAS revision.
            if now<self.transition_until:return self._out('blocked','handoff_transition')
            if scope_key(scope) not in self._scopes and len(self._scopes)>=32:return self._out('blocked','pending_scope_capacity')
            await self._state(scope)
            admission=await self.runtime.delivery.preflight(scope,event_id)
            if not self._allowed(scope) or not isinstance(admission,dict) or admission.get('allowed') is not True:
                return self._out('blocked','native_admission_denied')
            task_id=admission.get('task_id')
            if not isinstance(task_id,str) or not _HASH.fullmatch(task_id):raise ValueError('native task binding required')
            work=dict(schema=SCHEMA,scope=scope,event_id=event_id,signature=signature,task_id=task_id,phase='generating',
                created_at=now,expires_at=expiry,candidate=None,image=None,text_only=text_only)
            row=await self._put(scope,work,row['revision'] if row else 0);self._scopes[scope_key(scope)]=scope
            self._counts['generation_calls']+=1
            generated=await self.generator.generate(scope,event_id,topic)
            if not self._allowed(scope):return self._out('disabled','scope_or_lane_unavailable')
            if not isinstance(generated,dict):return await self._finish(scope,row,'unknown','generation_result_unknown')
            if generated.get('state')!='ready':
                phase=generated.get('state');phase=phase if phase in {'blocked','dropped','duplicate','unknown'} else 'unknown'
                return await self._finish(scope,row,phase,'native_generation_'+phase)
            candidate=self._candidate(scope,generated.get('candidate'),work)
            if not await self.generator.is_current(scope,candidate,check_preflight=False):
                return await self._finish(scope,row,'dropped','candidate_no_longer_current')
            work=dict(work,candidate=candidate,expires_at=min(work['expires_at'],candidate['expires_at']),phase='submitting' if text_only else 'imaging')
            row=await self._put(scope,work,row['revision'])
            budget=min(self.image_timeout,work['expires_at']-self._now())
            if budget<=0:return await self._finish(scope,row,'failed','candidate_expired')
            media = None
            if not text_only:
                self._counts['image_calls']+=1
                try:image=await asyncio.wait_for(self.image_service.generate(scope,task_id,'care',explicit_sexual=False),timeout=budget)
                except asyncio.CancelledError:raise
                except Exception:return await self._finish(scope,row,'unknown','image_outcome_unknown')
                if not self._allowed(scope):return self._out('disabled','scope_or_lane_unavailable')
                if not isinstance(image,dict) or image.get('state')=='unknown':
                    return await self._finish(scope,row,'unknown','image_outcome_unknown')
                if image.get('state') in ('definite_failure','denied'):
                    return await self._finish(scope,row,'failed','image_not_prepared')
                try:media=await asyncio.to_thread(self._media,image,fresh=True)
                except (ValueError,TypeError,OSError):return await self._finish(scope,row,'failed','fresh_owned_image_required')
            if not await self.generator.is_current(scope,candidate,check_preflight=False):
                return await self._finish(scope,row,'dropped','candidate_no_longer_current')
            admission=await self.runtime.delivery.preflight(scope,event_id)
            if (not self._allowed(scope) or admission.get('allowed') is not True
                    or not await self.generator.is_current(scope,candidate,check_preflight=False)
                    or self._now()>=work['expires_at']):
                return await self._finish(scope,row,'dropped','final_native_admission_denied')
            work=dict(work,image=media,phase='submitting');row=await self._put(scope,work,row['revision'])
            try:
                task=await self.runtime.delivery.submit(scope,event_id,text=candidate['text'],images=[] if media is None else [media['path']],
                    expires_at=work['expires_at'],priority=50,trigger='event',max_attempts=1,text_only=text_only)
            except asyncio.CancelledError:raise
            except Exception:return self._out('pending','submission_uncertain',task_id=task_id)
            if not isinstance(task,dict) or task.get('id')!=task_id:raise ValueError('native submission binding differs')
            self._counts['submitted']+=1
            row=await self._put(scope,dict(work,phase='queued'),row['revision'])
            return await self._reconcile(scope,row)
        except asyncio.CancelledError:raise  # Durable phase and provider/image receipts fence paid replay.
        except JournalConflict:return self._out('blocked','proactive_pending_conflict')
        except (ValueError,TypeError,OSError):
            self._counts['errors']+=1;return self._out('blocked','proactive_input_or_state_unavailable')
        except Exception:
            self._counts['errors']+=1;return self._out('blocked','proactive_tick_failed')
        finally:self._inflight=None

    def stop(self):
        self.active=False
        try:current=asyncio.current_task()
        except RuntimeError:current=None
        if self._inflight is not None and self._inflight is not current:self._inflight.cancel()

    async def close(self):
        running=self._inflight;self.stop()
        if running is not None and running is not asyncio.current_task():await asyncio.wait({running},timeout=1)
        for scope in tuple(self._scopes.values()):
            try:
                row=await self._fetch(scope)
                if row is None:continue
                task=await asyncio.to_thread(self.runtime.delivery.store.get,row['data']['task_id'])
                if task and task['state'] in _UNSENT:await self.runtime.delivery.control(task['id'],'cancel')
            except Exception:pass

    def diagnostics(self):
        return dict(active=self.active,inflight=self._inflight is not None,pending_scopes=len(self._scopes),
            last_reason=self._last_reason,event_bucket_seconds=600,transition_active=self._now()<self.transition_until,
            timers_started=0,direct_sends=0,**self._counts)

