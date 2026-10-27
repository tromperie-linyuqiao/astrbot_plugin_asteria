"""TLS native decision admission and durable queue driver.

Only an explicitly constructed isolated service can execute in this stage.
Production PC is neither invoked nor modified. The authoritative store fences
claims, owners, quotas, expiry and dispatch before the platform boundary.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time

from . import native_frequency
from .delivery_types import DeliveryPolicy, make_task, task_input_hash,delivery_policy_hash,delivery_quiet_window
from .models import canonical, private_scope
from .delivery_store import DeliveryConflict
from .delivery_types import number

_LOGGER = logging.getLogger(__name__)


class NativeScheduler:
    environment='isolated'

    def __init__(self,store,sender,*,node,read_state,authorize,policy=None,clock=time.time,candidate_for_event=None):
        if not isinstance(node,str) or not 1 <= len(node) <= 64: raise ValueError('node identity required')
        self.store,self.sender,self.node=store,sender,node
        self.read_state,self.authorize=read_state,authorize
        self.policy=policy or DeliveryPolicy()
        self.clock=clock
        self.candidate_for_event=candidate_for_event
        self.active=True
        self._worker=None
        self._steps=set()
        self._executing_step=None
        self._step_lock=asyncio.Lock()
        self.metrics={'decisions':0,'denied':0,'queued':0,'steps':0,'errors':0,'shadow':0,
                      'step_attempts':0,'cancelled':0}

    async def _value(self,callback,*args):
        value=callback(*args)
        return await value if inspect.isawaitable(value) else value

    async def _decision(self,scope,now):
        state=await self._value(self.read_state,scope)
        if not isinstance(state,dict): raise ValueError('state reader must return a mapping')
        counters=await asyncio.to_thread(self.store.counters,scope,self.policy.day(now))
        profile=native_frequency.build_frequency_profile(now=now,
            last_activity_at=state.get('last_activity_at',0),
            last_sent=max(counters.get('last_sent',0),number(state.get('shared_last_sent_at',0),'shared_last_sent_at')),
            sent_today=max(counters.get('sent_today',0),number(state.get('shared_sent_today',0),'shared_sent_today')),
            daily_limit=self.policy.daily_limit,min_interval_minutes=self.policy.min_interval_seconds/60,
            recent_chat_minutes=self.policy.recent_chat_seconds/60,sampling_minutes=self.policy.sampling_minutes,
            ignored_streak=state.get('ignored_streak',0),is_friend=state.get('is_friend',False),
            night_mode=self.policy.night_mode,local_hour=self.policy.local_time(now).hour)
        self.metrics['decisions']+=1
        # Preserve the established pure-function tuple API while serializing
        # the durable decision as plain JSON.
        profile=dict(profile,delay_hours=list(profile['delay_hours']))
        rest_until=number(state.get('rest_until',0),'rest_until')
        if state.get('enabled',True) is not True:
            profile.update(allowed=False,block_reason='user_disabled')
        elif rest_until>now:
            profile.update(allowed=False,block_reason='user_resting',retry_at=max(profile['retry_at'],rest_until))
        if getattr(self.policy,'quiet_hours',''):
            parameters=self.policy.as_dict();quiet=delivery_quiet_window(parameters,now)
            retry=max(profile['retry_at'],quiet['quiet_until'])
            retry=max(retry,delivery_quiet_window(parameters,retry)['quiet_until'])
            if quiet['quiet_until']>now and profile['allowed']:
                profile.update(allowed=False,block_reason='quiet_hours')
            profile['retry_at']=retry
        return state,profile

    async def preflight(self,scope,event_id):
        """Read-only admission preview before generating an expensive image.

        This is not a reservation or send permit. submit/begin still check the
        actual immutable content, current ownership, counters and final lease.
        The stable event draw is exactly the one used by submit.
        """
        scope=private_scope(scope)
        identity=make_task(scope,event_id,text='preflight',now=self.clock())['id']
        denied=lambda reason:dict(allowed=False,reason=reason,task_id=identity)
        if not self.active or not await self._value(self.authorize,scope):return denied('scope_unavailable')
        if not callable(getattr(self.store,'owner',None)):return denied('admission_owner_unavailable')
        owner=await asyncio.to_thread(self.store.owner,scope)
        if owner['mode']!='tls':return denied('not_native_owner')
        existing=await asyncio.to_thread(self.store.get,identity)
        if existing is not None:return dict(denied('task_already_exists'),state=existing['state'])
        if callable(getattr(self.store,'task_counts',None)):
            from .delivery_store import ACTIVE
            counts=await asyncio.to_thread(self.store.task_counts)
            if (sum(counts.values())>=getattr(self.store,'max_tasks',20000)
                    or sum(counts.get(state,0) for state in ACTIVE)>=getattr(self.store,'max_active',4096)):
                return denied('queue_capacity')
        now=self.clock();_,profile=await self._decision(scope,now)
        quiet=delivery_quiet_window(self.policy.as_dict(),now)
        if quiet['quiet_until']>now:
            result=denied('quiet_hours')
            if self.policy.quiet_hours:result.update(retry_at=None if quiet['quiet_all_day'] else profile['retry_at'],quiet_all_day=quiet['quiet_all_day'])
            return result
        digest=hashlib.sha256(canonical([identity,profile['sampling_bucket']]).encode()).hexdigest()
        draw=int(digest[:13],16)/16**13
        if (not self.active or not await self._value(self.authorize,scope)
                or await asyncio.to_thread(self.store.owner,scope)!=owner):return denied('authority_changed')
        allowed=bool(profile['allowed'] and draw<profile['probability'])
        return dict(allowed=allowed,reason='ready' if allowed else profile.get('block_reason') or 'sample_not_selected',
            task_id=identity,profile=profile,draw=draw,owner_generation=owner['generation'])

    async def submit(self,scope,event_id,*,text,images=(),due_at=None,expires_at=None,priority=50,trigger='event',max_attempts=3,
                     audio=None,audio_text=True,text_only=False):
        if not self.active: raise RuntimeError('scheduler closed')
        if type(text_only) is not bool or text_only and (images or audio is not None):
            raise ValueError('explicit text-only policy cannot contain media')
        if not await self._value(self.authorize,scope):
            self.metrics['denied']+=1
            raise PermissionError('scope not authorized')
        # Retry with the same event identity must return the original immutable
        # task, not regenerate creation time or sample a new random draw.
        now=self.clock()
        candidate=make_task(scope,event_id,text=text,images=images,now=now,due_at=due_at,
            expires_at=expires_at,priority=priority,trigger=trigger,max_attempts=max_attempts,
            audio=audio,audio_text=audio_text)
        existing=await asyncio.to_thread(self.store.get,candidate['id'])
        if existing is not None:
            if existing['state']=='quarantined':
                return existing  # Preserve the diagnostic; never re-admit corrupt work.
            prior_decision=existing.get('decision') or existing.get('approval') or {}
            if (prior_decision.get('text_only') is True) != text_only:
                raise ValueError('event identity media policy conflict')
            for key in ('scope','session','text','images','priority','trigger','max_attempts'):
                if existing[key]!=candidate[key]: raise ValueError('event identity content conflict')
            if ('audio' in existing) != ('audio' in candidate) or any(existing.get(key)!=candidate.get(key)
                    for key in ('audio','audio_text')):
                raise ValueError('event identity speech content conflict')
            if due_at is not None and existing['due_at']!=due_at or expires_at is not None and existing['expires_at']!=expires_at:
                raise ValueError('event identity timing conflict')
            if existing['state']=='approved':
                return await asyncio.to_thread(self.store.enqueue,existing['id'])
            return existing
        try:
            task=await asyncio.to_thread(self.store.create,candidate)
        except DeliveryConflict:
            # A concurrent admission can commit between get and create. Retry
            # the idempotent read, preserving its original clocks and decision.
            return await self.submit(scope,event_id,text=text,images=images,due_at=due_at,
                expires_at=expires_at,priority=priority,trigger=trigger,max_attempts=max_attempts,
                audio=audio,audio_text=audio_text,text_only=text_only)
        state,profile=await self._decision(scope,now)
        # Stable sampling by source event + policy bucket: restart/repeated
        # admission cannot keep drawing until it wins.
        digest=hashlib.sha256(canonical([task['id'],profile['sampling_bucket']]).encode()).hexdigest()
        draw=int(digest[:13],16)/16**13
        allowed=bool(profile['allowed'] and draw < profile['probability'])
        approval=dict(native=True,allowed=allowed,input_hash=task_input_hash(task),
            policy_hash=delivery_policy_hash(self.policy.as_dict()),
            decision_id=hashlib.sha256(canonical([task['id'],profile,draw]).encode()).hexdigest(),
            checked_at=now,profile=profile,draw=draw)
        if text_only:
            # A trusted producer makes this explicit before the immutable
            # decision is recorded. Ordinary approvals keep their v1 bytes.
            approval['text_only']=True
        await asyncio.to_thread(self.store.record_decision,task['id'],approval)
        if not allowed:
            self.metrics['denied']+=1
            # A rejected candidate remains an auditable non-executable object;
            # a fresh opportunity needs a new source event, not a blind retry.
            return task
        if self.policy.require_image and not task['images'] and not text_only:
            self.metrics['denied']+=1
            return task
        await asyncio.to_thread(self.store.approve,task['id'],approval)
        task=await asyncio.to_thread(self.store.enqueue,task['id'])
        self.metrics['queued']+=1
        return task

    async def receive_event(self,event,scope):
        """Thin SDK ingress; trusted candidate provider owns message content.

        No raw user text is persisted by this adapter. With no provider this is
        an inactive ingress, preserving ordinary chat and production behavior.
        """
        if not self.active: return None
        if not await self._value(self.authorize,scope): return None
        await asyncio.to_thread(self.store.note_activity,scope,self.clock())
        if self.candidate_for_event is None: return None
        spec=await self._value(self.candidate_for_event,event,scope)
        if spec is None: return None
        if not isinstance(spec,dict): raise ValueError('candidate provider returned invalid metadata')
        event_id=str(getattr(getattr(event,'message_obj',None),'message_id','') or '')
        if not event_id or event_id=='0': raise ValueError('stable platform event ID required')
        return await self.submit(scope,event_id,**spec)

    async def step(self):
        if not self.active: return None
        current=asyncio.current_task()
        self._steps.add(current)
        self.metrics['step_attempts']+=1
        try: return await self._step()
        except asyncio.CancelledError:
            # Cancelling an await of to_thread cannot cancel its RPC thread.
            # The client's eventual RPC outcome is a separate measurement.
            self.metrics['cancelled']+=1
            raise
        except Exception:
            self.metrics['errors']+=1
            errors=self.metrics['errors']
            if errors & (errors-1)==0:
                _LOGGER.warning('TLS delivery step failed: failures=%d',errors)
            # Claim/counters/begin/finish failures all propagate once. Never
            # retry here: durable recovery must resolve uncertain dispatch.
            raise
        finally:
            self._steps.discard(current)
            if self._executing_step is current: self._executing_step=None

    async def _step(self):
        if not self.active: return None
        async with self._step_lock:
            if not self.active: return None
            self._executing_step=asyncio.current_task()
            task=await asyncio.to_thread(self.store.claim,self.node,lease_seconds=self.policy.lease_seconds)
            if task is None: return None
            if not self.active:
                # A close concurrent with the transactional claim must not
                # turn unexecuted valid work into a permanent failed message.
                await asyncio.to_thread(self.store.defer,task['id'],self.node,task['token'],self.clock()+1,code='service_stopping')
                return None
            self.metrics['steps']+=1
            if not await self._value(self.authorize,task['scope']):
                return await self._scope_unavailable_after_claim(task)
            state,profile=await self._decision(task['scope'],self.clock())
            if not profile['allowed']:
                now=self.clock()
                available=max(now+self.policy.sampling_minutes*60,profile['retry_at'])
                if getattr(self.policy,'quiet_hours',''):
                    available=max(available,delivery_quiet_window(self.policy.as_dict(),available)['quiet_until'])
                await asyncio.to_thread(self.store.defer,task['id'],self.node,task['token'],available,code='frequency_gate')
                from .delivery_sender import SendResult
                return SendResult('blocked','frequency_gate')
            parameters=self.policy.as_dict()
            parameters['last_activity_at']=state.get('last_activity_at',0)
            return await self.sender.deliver(task,self.node,policy=parameters)

    async def _scope_unavailable_after_claim(self,task):
        """Default lanes retain their established terminal authorization refusal."""
        return await self.sender._finish(task,self.node,'failed','scope_unavailable')

    async def control(self,task_id,action):
        return await asyncio.to_thread(self.store.control,task_id,action)

    def start(self,*,poll_seconds=1):
        if not 0.01 <= poll_seconds <= 60: raise ValueError('invalid poll interval')
        if not self.active: raise RuntimeError('scheduler closed')
        if self._worker is not None and not self._worker.done(): return self._worker
        async def run():
            while self.active:
                try: await self.step()
                except asyncio.CancelledError: raise
                except Exception: pass  # counted in step; durable leases retain outcome
                await asyncio.sleep(poll_seconds)
        self._worker=asyncio.create_task(run(),name='tls-native-delivery-'+self.node)
        return self._worker

    async def close(self):
        self.active=False
        current=asyncio.current_task()
        running=set()
        if self._executing_step is not None and self._executing_step is not current and not self._executing_step.done():
            running.add(self._executing_step)
        if self._worker is not None and self._worker is not current and not self._worker.done(): running.add(self._worker)
        for task in running: task.cancel()
        if running: await asyncio.gather(*running,return_exceptions=True)
        await self.sender.close()

    def diagnostics(self):
        result=dict(active=self.active,worker_alive=self._worker is not None and not self._worker.done(),
                    environment=self.environment,metrics=dict(self.metrics),sender=dict(self.sender.metrics),
                    pending_platform_tasks=len(self.sender._pending),active_steps=len(self._steps))
        from .delivery_authority import AuthorityClient
        if isinstance(self.store,AuthorityClient):
            result['authority_rpc']=self.store.diagnostics()
        return result
