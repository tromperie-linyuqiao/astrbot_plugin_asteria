"""Native sender: durable fence -> existing AstrBot adapter -> durable outcome.

Platform exceptions/timeouts after invocation are UNKNOWN, never safe retries.
No PrivateCompanion imports, planning, image generation, or platform SDK copy.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from pathlib import Path


class BeforeDispatchError(Exception):
    """An adapter can prove that no platform call has begun."""


class _ReceiptCommittedCancellation(asyncio.CancelledError):
    """Cancellation arrived during a commit that has now completed."""


@dataclass(frozen=True)
class SendResult:
    outcome: str
    code: str


class AstrBotDeliveryAdapter:
    supports_audio = True
    def __init__(self, context, *, media_root):
        self.context=context
        self.media_root=Path(media_root).resolve()

    async def healthy(self, session):
        # Presence of the exact SDK dispatcher, not a remote delivery promise.
        return callable(getattr(self.context,'send_message',None)) and isinstance(session,str) and bool(session)

    def prepare(self, task):
        from astrbot.api.message_components import Image, Plain
        from astrbot.core.message.message_event_result import MessageChain
        components=[]
        if 'audio' in task:
            from astrbot.api.message_components import Record
            source=Path(task['audio'])
            path=source.resolve()
            if (source.is_symlink() or not path.is_relative_to(self.media_root) or not path.is_file()
                    or path.suffix.lower() not in {'.wav','.mp3','.ogg','.flac','.m4a','.aac','.amr','.silk','.pcm'}
                    or not 0 < path.stat().st_size <= 20*1024*1024
                    or type(task.get('audio_text')) is not bool):
                raise BeforeDispatchError('owned_audio_unavailable')
            components.append(Record(file=str(path)))
        for image in task['images']:
            path=Path(image).resolve()
            if not path.is_relative_to(self.media_root) or not path.is_file():
                raise BeforeDispatchError('media_unavailable')
            if path.stat().st_size > 20*1024*1024: raise BeforeDispatchError('media_too_large')
            components.append(Image.fromFileSystem(str(path)))
        if 'audio' not in task or task['audio_text']:
            components.append(Plain(task['text']))
        return MessageChain(components)

    async def send(self, task, prepared):
        return await self.context.send_message(task['session'],prepared)


class NativeSender:
    def __init__(self, store, adapter, *, authorize, policy, task_authorize=None):
        self.store,self.adapter,self.authorize,self.policy=store,adapter,authorize,policy
        if task_authorize is not None and not callable(task_authorize):
            raise ValueError('task authorizer must be callable')
        self.task_authorize=task_authorize
        self.confirmed_observer = None
        self.confirmed_observer_errors = 0
        self.active=True
        self.metrics={'confirmed':0,'failed':0,'unknown':0,'retryable':0,'denied':0}
        self._pending=set()

    async def _authorized(self, scope, task=None):
        if not self.active: return False
        value=self.authorize(scope)
        if inspect.isawaitable(value): value=await value
        if not bool(value) or not self.active:return False
        if self.task_authorize is not None:
            if task is None:return False
            allowed=self.task_authorize(scope,task)
            if inspect.isawaitable(allowed):allowed=await allowed
            return allowed is True and self.active
        return True

    async def healthy(self,session):
        if not self.active: return False
        return bool(await self.adapter.healthy(session))

    async def deliver(self, claimed, node, *, policy=None):
        task_id,token=claimed['id'],claimed['token']
        if len(self._pending)>=8:
            # An uncooperative platform coroutine may ignore cancellation.
            # Bound orphaned transports rather than accumulating one per tick.
            await asyncio.to_thread(self.store.defer,task_id,node,token,
                claimed['lease_until']+1,code='adapter_capacity')
            return SendResult('blocked','adapter_capacity')
        if not await self._authorized(claimed['scope'],claimed):
            self.metrics['denied']+=1
            # No dispatch started: finish accepts a claimed safe failure.
            return await self._finish(claimed,node,'failed','authorization_denied')
        try:
            if not await self.healthy(claimed['session']):
                return await self._finish(claimed,node,'retryable','adapter_unavailable')
            prepared=self.adapter.prepare(claimed)
        except (BeforeDispatchError,ValueError,OSError):
            return await self._finish(claimed,node,'retryable','prepare_unavailable')
        if not await self._authorized(claimed['scope'],claimed):
            return await self._finish(claimed,node,'failed','authorization_revoked')
        parameters=dict(policy or self.policy.as_dict())
        parameters.setdefault('last_activity_at',0)
        begun=await asyncio.to_thread(self.store.begin,task_id,node,token,parameters)
        if not begun: return SendResult('blocked','final_gate')
        # Cancel/revoke after this durable fence is conservative UNKNOWN. It is
        # unsafe to release a reservation based on absence of a local receipt.
        dispatched=None
        try:
            if not await self._authorized(claimed['scope'],begun):
                return await self._finish(claimed,node,'failed','revoked_before_dispatch')
            dispatched=asyncio.create_task(self.adapter.send(begun,prepared))
            self._pending.add(dispatched)
            dispatched.add_done_callback(self._settled)
            done,_=await asyncio.wait({dispatched},timeout=self.policy.timeout_seconds)
            if not done:
                dispatched.cancel()
                return await self._finish(claimed,node,'unknown','platform_timeout')
            answer=dispatched.result()
            # SDK False is a definite local route absence; True is SDK receipt,
            # not proof that a human read the message.
            if answer is False: return await self._finish(claimed,node,'failed','route_unavailable')
            if answer is not True: return await self._finish(claimed,node,'unknown','ambiguous_receipt')
            return await self._finish(claimed,node,'confirmed','sdk_confirmed')
        except _ReceiptCommittedCancellation:
            raise
        except asyncio.CancelledError:
            if dispatched is not None: dispatched.cancel()
            # A cancellation cannot interrupt the persistence worker safely.
            await self._finish(claimed,node,'unknown','dispatch_cancelled')
            raise
        except Exception:
            return await self._finish(claimed,node,'unknown','platform_exception')

    async def _finish(self, task,node,outcome,code):
        # If this commit fails, durable SENDING survives and recovery quarantines
        # UNKNOWN. Do not retry the SDK call or fall back to the legacy sender.
        commit=asyncio.create_task(asyncio.to_thread(self.store.finish,task['id'],node,task['token'],outcome,code=code))
        cancelled=False
        while not commit.done():
            try: await asyncio.shield(commit)
            except asyncio.CancelledError: cancelled=True
        commit.result()
        self.metrics[outcome]+=1
        if outcome == 'confirmed' and self.confirmed_observer is not None:
            try: self.confirmed_observer(task)
            except Exception: self.confirmed_observer_errors += 1
        if cancelled: raise _ReceiptCommittedCancellation()
        return SendResult(outcome,code)

    def _settled(self, task):
        self._pending.discard(task)
        if not task.cancelled(): task.exception()

    async def close(self):
        self.active=False
        tasks=tuple(self._pending)
        for task in tasks: task.cancel()
        if tasks: await asyncio.wait(tasks,timeout=min(self.policy.timeout_seconds,1))

