"""Optional image follow-ups on the existing Host, image service and sender.

Jobs are checkpoints in the existing LivingJournal. There is no new timer,
provider account, database or sender. Uncertain provider/storage outcomes are
read-only until reconciled; only a definitely rejected generation can retry.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

from .models import canonical, private_scope, scope_key
from .delivery_types import make_task
from .journal import JournalConflict

NAMESPACE = 'tls.chat.image_jobs.v1'
TASKS = 'tls.chat.image_tasks.v1'
REQUESTS = 'tls.chat.image_requests.v1'
UNRESOLVED = {'pending','generating','submitting','dispatching','queued','unknown'}
MAX_UNRESOLVED = 256
_ID = re.compile(r'[A-Za-z0-9_.:-]{8,128}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')
PURPOSES = {'chat', 'life', 'roleplay'}
RETRYABLE = {'definite_failure', 'blocked'}

def _app_session(scope):
    raw=scope['session_id'].split(':',2)[-1];prefix='webchat!'+scope['user_id']+'!'
    if not raw.startswith(prefix)or not raw[len(prefix):]:raise PermissionError('actual APP origin required')
    return raw[len(prefix):]


def explicit_image_request(text):
    """Narrow user command detection, not inference from roleplay actions."""
    if not isinstance(text, str) or len(text)>16000 or re.search(r'不要|别|不用|无需|不想|不需要',text):return None
    command=r'(?:^|[。！？!?\n])\s*(?:(?:请|麻烦|能不能|可以|能否|我想要|我要|帮我|给我|为我|你)\s*){0,3}'
    if not re.search(command+r'(?:(?:生成|画|绘制|制作).{0,48}(?:图|画|角色)|(?:发|给我看).{0,24}(?:一张|张).{0,24}(?:你的|角色).{0,12}(?:图片|照片|自拍))',text):return None
    return dict(prompt=text.strip()[:1200],purpose='chat')


class ChatGeneratedImages:
    def __init__(self, host):
        self.host, self.plugin, self.journal = host, host.plugin, host.journal
        self.runtime = host.runtime
        self.active = True
        self._pending = {}
        self._observers = {}
        self._owned_requests = {}

    def _current(self):
        return bool(self.active and not self.host._closed and not getattr(self.plugin,'_stopping',True)
            and self.host.runtime is self.runtime and getattr(self.runtime,'chat_images',None)is self
            and getattr(self.runtime,'active',False)and not self.journal._closed)

    def _allowed(self, scope):
        service=getattr(self.runtime,'image_service',None)
        return bool(self._current()and self.host.authorized_scope(scope)and service is not None and service._allowed(scope))

    def _request_scope_allowed(self,scope):
        """An owned conversational reply, without proactive sending authority."""
        image=getattr(self.runtime,'image_service',None)
        return bool(self._current()and self.host.authorized_scope(scope)and image is not None
            and not getattr(image,'_closed',True))

    async def _owned_parent(self,scope,parent_id):
        """Read the original SDK owner and saved source; never trust a client ID."""
        if not self._request_scope_allowed(scope):return False
        try:
            delivery=self.runtime.delivery;database=getattr(delivery.sender.adapter,'database',None)
            if database is None:
                from astrbot.core import db_helper
                database=db_helper
            sid=_app_session(scope)
            session=await database.get_platform_session_by_id(sid)
            if (session is None or session.creator!=scope['user_id']or session.session_id!=sid
                    or session.platform_id!='webchat'or session.is_group!=0):return False
            parent=await database.get_platform_message_history_by_id(int(parent_id))
            return bool(parent is not None and str(parent.id)==parent_id and parent.platform_id=='webchat'
                and parent.user_id==sid and isinstance(parent.content,dict)
                and parent.content.get('type')in {'user','bot'}and self._request_scope_allowed(scope))
        except (AttributeError,TypeError,ValueError,RuntimeError,OSError):return False

    def _owned_request_allowed(self,scope,row,image_task_id):
        """A volatile proof bound to one accepted job and its original task."""
        if not self._request_scope_allowed(scope):return False
        d=row['data'];key=(scope_key(scope),d['id'])
        proof=self._owned_requests.get(key)
        if (proof!=(d['request_id'],d['event_id'],d['parent_message_id'],self.runtime.image_service)
                or image_task_id!='chat-image-'+d['delivery_task_id']
                or self._pending.get(key)is not asyncio.current_task()):return False
        current=self.journal.fetch(NAMESPACE,d['id'],scope)
        return bool(current and current['data']['source']=='user_request'
            and all(current['data'].get(name)==d.get(name)for name in
                ('request_id','event_id','parent_message_id','signature','delivery_task_id'))
            and current['data']['state']in {'pending','generating','submitting','dispatching'})

    @staticmethod
    def _scope(scope, username=None):
        scope=private_scope(scope)
        if scope['platform']!='webchat'or scope['bot_id']!='webchat'or username is not None and scope['user_id']!=username:
            raise PermissionError('owned APP image scope required')
        return scope

    def status(self,scope=None):
        image=getattr(self.runtime,'image_service',None);delivery=getattr(self.runtime,'delivery',None)
        return dict(available=self._current()and image is not None and delivery is not None,
            backend='existing_native_image_service'if image is not None else'not_configured',
            size=getattr(getattr(image,'config',None),'size',None),
            reference_configured=bool(getattr(image,'_appearance','')),
            pending=len(self._pending),observed_chat_runs=len(self._observers),background='existing_living_host',
            authorized=self._request_scope_allowed(scope)if scope is not None else None,
            proactive_authorized=self._allowed(scope)if scope is not None else None,
            authorization_basis='owned_reply_request',
            configured_daily_limit=getattr(getattr(delivery,'policy',None),'daily_limit',None),
            retained_history=True,unresolved_limit=MAX_UNRESOLVED,
            unresolved_jobs=self._unresolved(scope)if scope is not None else None,
            global_checkpoint_limit=self.journal.max_records,
            provider_credentials_exposed=False,process_exit_push=False)

    def _view(self,row):
        d=row['data'];result={k:d.get(k)for k in ['id','request_id','state','reason','purpose','source','parent_message_id','created_at','updated_at','attempt','delivery_task_id','message_id']}
        result.update(revision=row['revision'],can_retry=d['source']=='user_request'and d['state']in RETRYABLE,
            can_reconcile=d['state']in {'unknown','dispatching','queued'}or(d['state']=='stored'and not d.get('message_id')),
            authority='server_job_state',client_received=False)
        return result

    def list(self,scope,*,limit=20):
        if not self._current():raise RuntimeError('image follow-up service unavailable')
        scope=self._scope(scope)
        if type(limit)is not int or not 1<=limit<=50:raise ValueError('bounded image list required')
        return [self._view(row)for row in self.journal.list(NAMESPACE,scope,limit=limit)]

    def lookup(self,scope,request_id):
        if not self._current():raise RuntimeError('image follow-up service unavailable')
        scope=self._scope(scope)
        if not isinstance(request_id,str)or not _ID.fullmatch(request_id):raise ValueError('invalid original image request')
        row,matched_attempt=self._request_record(scope,request_id)
        return dict(request_id=request_id,found=row is not None,job=self._view(row)if row else None,
            matched_attempt=matched_attempt)

    @staticmethod
    def _request_key(scope,request_id):
        return hashlib.sha256(canonical([scope_key(scope),request_id]).encode()).hexdigest()

    def _request_record(self,scope,request_id):
        """Point lookup for new nonces; exact original/legacy lookup at any age."""
        key=self._request_key(scope,request_id)
        with self.journal._lock:
            ref=self.journal.fetch(REQUESTS,key,scope)
            if ref:
                row=self.journal.fetch(NAMESPACE,ref['data']['job_id'],scope)
                if not row or row['data']['signature']!=ref['data']['signature']:
                    raise JournalConflict('image request mapping requires review')
                return row,ref['data']['attempt']
            row=self.journal.fetch(NAMESPACE,key,scope)
            if row:return row,1  # The first nonce is the original stable job ID.
            # R103 stored only its latest retry nonce. Search that exact field,
            # without silently losing an old UNKNOWN behind a 256-row window.
            rows=self.journal._db.execute("SELECT revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? AND json_extract(data,'$.request_id')=? LIMIT 2",
                (NAMESPACE,scope_key(scope),request_id)).fetchall()
            if len(rows)>1:raise JournalConflict('legacy image request identity is ambiguous')
            row=self.journal._record(rows[0])if rows else None
            return row,row['data']['attempt']if row else None

    def _unresolved(self,scope):
        with self.journal._lock:
            self.journal._ensure_open()
            marks=','.join('?'for _ in UNRESOLVED)
            return self.journal._db.execute("SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=? AND json_extract(data,'$.state') IN ("+marks+')',
                (NAMESPACE,scope_key(self._scope(scope)),*sorted(UNRESOLVED))).fetchone()[0]

    @staticmethod
    def _paid_days(data):
        total=data.get('paid_attempts',0);days=data.get('paid_days')
        if type(total)is not int or total<0:raise ValueError('已有图片调用记录无法核清，暂不发起新生成；请先核对。')
        if days is None:
            day=data.get('day')
            if total and(not isinstance(day,str)or re.fullmatch(r'\d{4}-\d{2}-\d{2}',day)is None):
                raise ValueError('已有图片调用日期未核清，暂不发起新生成；请先核对。')
            # Old lifetime totals cannot be reconstructed into invented dates.
            # Retain their original conservative last-day accounting once.
            return {day:total}if total else{}
        if (type(days)is not dict or any(type(day)is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}',day)is None
                or type(count)is not int or count<0 for day,count in days.items())or sum(days.values())!=total):
            raise ValueError('已有图片调用记录无法核清，暂不发起新生成；请先核对。')
        return dict(days)

    def _put(self,scope,data,revision):
        return self.journal.put(NAMESPACE,data['id'],scope,data,expected_revision=revision,authorize=self._current)

    def _budget(self,scope,*,inherited=False,at=None):
        delivery=getattr(self.runtime,'delivery',None)
        if delivery is None:return False
        policy=delivery.policy;day=policy.day(self.host.clock()if at is None else at)
        with self.journal._lock:
            self.journal._ensure_open()
            # New records read only today's bucket. Legacy paid records are
            # conservatively checked even when their recorded date is invalid.
            rows=self.journal._db.execute("SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND ((json_type(data,'$.paid_days') IS NULL AND COALESCE(json_extract(data,'$.paid_attempts'),0)!=0) OR (json_type(data,'$.paid_days') IS NOT NULL AND (json_type(data,'$.paid_days')!='object' OR json_extract(data,?) IS NOT NULL)))",
                (NAMESPACE,scope_key(scope),'$.paid_days."'+day+'"')).fetchall()
            used=sum(self._paid_days(json.loads(row[0])).get(day,0)for row in rows)
        counters=delivery.store.counters(scope,day)
        # The same configured image/delivery budget bounds this optional lane.
        return used+(0 if inherited else int(counters.get('sent_today',0)))<policy.daily_limit

    def _start_generation(self,scope,row):
        with self.journal._lock:
            latest=self.journal.fetch(NAMESPACE,row['data']['id'],scope)
            if not latest or latest['revision']!=row['revision']:raise JournalConflict('image job changed before submission')
            data=latest['data'];now=self.host.clock();changes=dict(updated_at=now)
            if not self._budget(scope,inherited=data.get('inheritance')is not None,at=now):
                changes.update(state='blocked',reason='configured_image_budget_exhausted')
            else:
                day=self.runtime.delivery.policy.day(now);days=self._paid_days(data)
                days[day]=days.get(day,0)+1
                changes.update(state='generating',reason='provider_submission',day=day,
                    paid_attempts=data.get('paid_attempts',0)+1,paid_days=days)
            return self._put(scope,dict(data,**changes),latest['revision'])

    def _inheritance_allowed(self,scope,proof):
        """A same-admission media follow-up, never a fresh proactive candidate."""
        if not isinstance(proof,dict)or set(proof)!={'task_id','source_scope','event_id','event_version','target','expires_at'}:return False
        if not self._allowed(scope)or self.host.clock()>=proof['expires_at']:return False
        delivery=self.runtime.delivery;original=delivery.store.get(proof['task_id'])
        if (not original or original.get('scope')!=proof['source_scope']or original.get('state')!='confirmed'
                or original.get('images')or(original.get('decision')or original.get('approval')or{}).get('text_only')is not True):return False
        if delivery.sender.adapter._target(original)!=proof['target']:return False
        if proof['target']['username']!=scope['user_id']or proof['target']['session_id']!=_app_session(scope):return False
        from .delivery_types import delivery_quiet_window
        if delivery_quiet_window(delivery.policy.as_dict(),self.host.clock())['quiet_until']>self.host.clock():return False
        life=getattr(self.runtime,'autonomous_life',None)
        if life is None or not life.active:return False
        policy=life.settings(proof['source_scope'])['settings']
        event=life.get_event(proof['source_scope'],proof['event_id'])
        if (not policy['enabled']or not policy['share_enabled']or not event or not event['valid']
                or event['archived']or event['version']!=proof['event_version']):return False
        text=event['fields']['title']+' '+event['fields']['content']
        if any(topic.casefold()in text.casefold()for topic in policy.get('muted_topics',[])):return False
        shares=life.shares(proof['source_scope'],event_id=proof['event_id'])['records']
        return any(item['task_id']==proof['task_id']and item['state']=='confirmed'and item['event_version']==proof['event_version']for item in shares)

    async def followup_for_share(self,source_scope,task_id,event_id,event_version):
        """The existing life lane calls this only after its real text commit."""
        from .chat_workspace import actual_app_scope
        delivery=self.runtime.delivery;task=await asyncio.to_thread(delivery.store.get,task_id)
        if not task or task.get('scope')!=source_scope or task.get('state')!='confirmed':return None
        adapter=delivery.sender.adapter;target=adapter._target(task)
        if target is None:return None  # This task does not route to Chat.
        database=getattr(adapter,'database',None)
        if database is None:
            from astrbot.core import db_helper
            database=db_helper
        session=await database.get_platform_session_by_id(target['session_id'])
        if (session is None or session.creator!=target['username']or session.session_id!=target['session_id']
                or session.platform_id!='webchat'or session.is_group!=0):return None
        scope=actual_app_scope(self.plugin,target['username'],session)
        if scope is None:return None
        proof=dict(task_id=task_id,source_scope=source_scope,event_id=event_id,event_version=event_version,
            target=target,expires_at=task['expires_at'])
        if not self._inheritance_allowed(scope,proof):return None
        from .chat_delivery import key_for
        history=await database.get_platform_message_history(platform_id='webchat',user_id=target['session_id'],page_size=1000)
        matches=[item for item in history if isinstance(item.content,dict)and item.content.get('type')=='bot'
            and isinstance(item.content.get('refs'),dict)and item.content['refs'].get('tls_delivery_key')==key_for(task)]
        if len(matches)!=1:return None
        event=self.runtime.autonomous_life.get_event(source_scope,event_id)
        prompt=('这是角色的虚构生活画面，不是现实照片。'+event['fields']['title']+'：'+event['fields']['content'])[:1200]
        return await self.request(scope,request_id='chat-life-image-'+task_id,prompt=prompt,purpose='life',
            parent_message_id=str(matches[0].id),source='life_event',inheritance=proof)

    async def request(self,scope,*,request_id,prompt,purpose,parent_message_id,source='user_request',retry_job_id=None,expected_revision=None,inheritance=None):
        scope=self._scope(scope)
        if (not isinstance(request_id,str)or not _ID.fullmatch(request_id)or purpose not in PURPOSES
                or not isinstance(prompt,str)or not 1<=len(prompt.strip())<=1200
                or any(ord(c)<32 and c not in '\n\t'for c in prompt)
                or source not in {'user_request','model_candidate','life_event'}
                or not isinstance(parent_message_id,str)or not parent_message_id.isdigit()):
            raise ValueError('invalid owned image candidate')
        if not self._current():raise RuntimeError('image follow-up service unavailable')
        owned_parent=await self._owned_parent(scope,parent_message_id)if source=='user_request'else False
        prompt=prompt.strip()
        identity=self._request_key(scope,request_id)
        if retry_job_id is not None:
            if not isinstance(retry_job_id,str)or not _HASH.fullmatch(retry_job_id):raise ValueError('invalid original image job')
            identity=retry_job_id
        if inheritance is not None and(source!='life_event'or purpose!='life'):raise ValueError('life source proof required')
        signature=hashlib.sha256(canonical([prompt,purpose,parent_message_id,source,inheritance]).encode()).hexdigest()
        # Acceptance is single-loop, with the journal transaction establishing
        # the durable paid-call fence before the new Host task can execute.
        with self.journal._lock:
            accepted,_=self._request_record(scope,request_id)
            if accepted:
                if accepted['data']['signature']!=signature or retry_job_id is not None and accepted['data']['id']!=retry_job_id:
                    raise JournalConflict('image request identity changed')
                if retry_job_id is not None and accepted['data']['state']=='unknown':
                    raise JournalConflict('image task must be reconciled, not replayed')
                return self._view(accepted)
            previous=self.journal.fetch(NAMESPACE,identity,scope)
            if previous:
                if previous['data']['signature']!=signature:raise JournalConflict('image request identity changed')
                if retry_job_id is None:return self._view(previous)
                if previous['revision']!=expected_revision or previous['data']['source']!='user_request'or previous['data']['state']not in RETRYABLE:
                    raise JournalConflict('image task must be reconciled, not replayed')
            elif retry_job_id is not None:raise KeyError('original image job absent')
            if self._unresolved(scope)>=MAX_UNRESOLVED:
                raise ValueError('已有256项图片任务仍未核清，请先核对；历史不会删除，也不会重新付费。')
            # Keep the original shared Journal bound and room for the existing
            # task/SDK delivery receipts. Nothing is purged to accept a job.
            required=(1 if previous is None else 0)+3
            used=self.journal._db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
            if used+required>self.journal.max_records:
                raise ValueError('服务记录空间不足，暂不生成新图片；已有历史会保留，也不会重新付费。')
            image=getattr(self.runtime,'image_service',None);delivery=getattr(self.runtime,'delivery',None)
            now=self.host.clock();attempt=1 if previous is None else previous['data']['attempt']+1
            event_id='chat.image.'+identity+'.'+str(attempt)
            task_id=make_task(scope,event_id,text='图片',now=now)['id']
            data=dict(schema=1,id=identity,request_id=request_id,signature=signature,prompt=prompt,purpose=purpose,source=source,
                parent_message_id=parent_message_id,created_at=previous['data']['created_at']if previous else now,
                updated_at=now,day=delivery.policy.day(now)if delivery is not None else'',attempt=attempt,
                event_id=event_id,delivery_task_id=task_id,state='pending',reason='accepted',scope=scope,
                paid_attempts=previous['data'].get('paid_attempts',0)if previous else 0,
                paid_days=self._paid_days(previous['data'])if previous else{},inheritance=inheritance)
            if image is None or delivery is None:data.update(state='blocked',reason='image_backend_not_configured')
            elif not (self._request_scope_allowed(scope)if source=='user_request'else self._allowed(scope)):
                data.update(state='blocked',reason='image_scope_not_authorized')
            elif source=='user_request'and not owned_parent:data.update(state='blocked',reason='owned_parent_unavailable')
            elif inheritance is not None and not self._inheritance_allowed(scope,inheritance):data.update(state='blocked',reason='original_share_authority_changed')
            elif not self._budget(scope,inherited=inheritance is not None):data.update(state='blocked',reason='configured_image_budget_exhausted')
            elif len(self.host._tasks)>=self.host.max_pending or any(k[0]==scope_key(scope)for k in self._pending):
                data.update(state='blocked',reason='image_job_busy')
            saved=self._put(scope,data,previous['revision']if previous else 0)
            self.journal.put(REQUESTS,self._request_key(scope,request_id),scope,
                dict(job_id=identity,signature=signature,attempt=attempt),expected_revision=0,authorize=self._current)
            if data['state']=='pending':
                if source=='user_request':
                    self._owned_requests[(scope_key(scope),identity)]=(request_id,event_id,parent_message_id,image)
                task=asyncio.create_task(self._run(scope,saved),name='tls-chat-image-'+identity[:12])
                key=(scope_key(scope),identity);self._pending[key]=task;self.host._tasks.add(task)
                task.add_done_callback(self.host._finished)
                task.add_done_callback(lambda finished:self._pending.pop(key,None))
                task.add_done_callback(lambda finished:self._owned_requests.pop(key,None))
        return self._view(saved)

    async def _change(self,scope,row,**changes):
        data=dict(row['data'],**changes,updated_at=self.host.clock())
        return await asyncio.to_thread(self._put,scope,data,row['revision'])

    def observe_saved_run(self,service,username,session_id,checkpoint_id,accept):
        """Wait on the existing SDK task, so closing the page loses no candidate.

        This is one owned continuation, not a second model run or polling loop.
        The original task and its original history checkpoint stay authoritative.
        """
        if not self._current()or checkpoint_id in self._observers:return
        runs=[run for run in getattr(service,'chat_runs',{}).values()
            if run.username==username and run.session_id==session_id
            and run.platform_history_id=='webchat'and run.llm_checkpoint_id==checkpoint_id]
        if len(runs)!=1 or not isinstance(runs[0].task,asyncio.Task):return
        if len(self.host._tasks)>=self.host.max_pending:return
        async def finish():
            try:
                await asyncio.shield(runs[0].task)
                if not self._current():return
                session=await service.db.get_platform_session_by_id(session_id)
                if (session is None or session.creator!=username or session.platform_id!='webchat'
                        or session.session_id!=session_id or session.is_group!=0):return
                history=await service.db.get_platform_message_history(platform_id='webchat',user_id=session_id,page_size=1000)
                selected=[record for record in history if record.llm_checkpoint_id==checkpoint_id
                    and record.platform_id=='webchat'and record.user_id==session_id and isinstance(record.content,dict)]
                # The explicit request takes precedence over an optional model
                # candidate for the same run; the shared stable key also fences
                # SSE and detached completion observing the same record.
                for record in sorted(selected,key=lambda record:(record.content.get('type')!='user',int(record.id))):
                    kind='user_message_saved'if record.content.get('type')=='user'else'message_saved'if record.content.get('type')=='bot'else None
                    if kind is not None:await accept(service,username,session_id,record,kind)
            except asyncio.CancelledError:raise
            except Exception:pass  # No model/send replay after an optional observer failure.
        task=asyncio.create_task(finish(),name='tls-chat-image-observer-'+checkpoint_id[:12])
        self._observers[checkpoint_id]=task;self.host._tasks.add(task)
        task.add_done_callback(self.host._finished)
        task.add_done_callback(lambda finished:self._observers.pop(checkpoint_id,None))

    async def _run(self,scope,row):
        try:
            image=self.runtime.image_service;delivery=self.runtime.delivery;d=row['data']
            image_task_id='chat-image-'+d['delivery_task_id']
            def allowed():
                return self._owned_request_allowed(scope,row,image_task_id)if d['source']=='user_request'else self._allowed(scope)
            async def parent_current():
                return await self._owned_parent(scope,d['parent_message_id'])if d['source']=='user_request'else True
            if d['source']!='user_request'and d.get('inheritance')is None:
                preview=await delivery.preflight(scope,d['event_id'])
                if preview.get('allowed')is not True:
                    await self._change(scope,row,state='blocked',reason='native_delivery_'+str(preview.get('reason','denied')));return
            if not allowed()or not await parent_current():await self._change(scope,row,state='blocked',reason='image_scope_not_authorized');return
            if d.get('inheritance')is not None and not self._inheritance_allowed(scope,d['inheritance']):
                await self._change(scope,row,state='blocked',reason='original_share_authority_changed');return
            row=await asyncio.to_thread(self._start_generation,scope,row)
            if row['data']['state']!='generating':return
            # A picture is a fictional illustration, never evidence of a real
            # observed photograph. The accepted owner reply uses one RAM proof;
            # model/life candidates retain the original proactive policy.
            kwargs={'request_authorize':lambda selected,task: selected==scope and task==image_task_id and allowed()}if d['source']=='user_request'else{}
            scene='这是用户请求的虚构角色插画，不是现实照片。'+d['prompt']if d['purpose']in {'life','roleplay'}else d['prompt']
            result=await image.generate(scope,image_task_id,'daily',scene_description=scene[:1200],explicit_sexual=False,**kwargs)
            if not isinstance(result,dict)or result.get('state')not in {'ready','denied','definite_failure'}:
                await self._change(scope,row,state='unknown',reason='provider_outcome_unknown');return
            if result['state']!='ready':await self._change(scope,row,state='definite_failure'if result['state']=='definite_failure'else'blocked',reason=result.get('reason','image_not_generated'));return
            path=Path(result['path']).resolve()
            if path.parent!=image.media_root or path.is_symlink()or not path.is_file():raise ValueError('owned image required')
            if not allowed()or not await parent_current()or d.get('inheritance')is not None and not self._inheritance_allowed(scope,d['inheritance']):
                await self._change(scope,row,state='unknown',reason='authorization_changed_after_generation');return
            now=self.host.clock();d=dict(row['data'],image_path=str(path),image_sha256=result['image_sha256'],
                expires_at=d['inheritance']['expires_at']if d.get('inheritance')is not None else now+3600)
            row=await self._change(scope,row,**{k:v for k,v in d.items()if k not in row['data']},state='submitting',reason='image_prepared')
            self.journal.put(TASKS,d['delivery_task_id'],scope,dict(job_id=d['id']),authorize=self._current)
            if d['source']=='user_request'or d.get('inheritance')is not None:
                # Explicit requested media is an ordinary reply follow-up. Reuse
                # the already-owned Chat adapter's exact storage/dedup path,
                # without treating current conversation activity as proactive.
                task=make_task(scope,d['event_id'],text='图片已生成。'if d['source']=='user_request'else'刚才那个生活画面。',
                    images=[str(path)],now=now,max_attempts=1,expires_at=d['inheritance']['expires_at']if d.get('inheritance')is not None else None)
                row=await self._change(scope,row,state='dispatching',reason='sdk_history_write_started')
                adapter=delivery.sender.adapter
                if not allowed()or not await parent_current()or d.get('inheritance')is not None and not self._inheritance_allowed(scope,d['inheritance']):
                    await self._change(scope,row,state='unknown',reason='authorization_changed_before_storage');return
                if getattr(adapter,'_target',lambda _:None)(task)is None:raise RuntimeError('owned Chat destination required')
                outcome=await adapter.send(task,adapter.prepare(task))
                if outcome is True:
                    from .chat_delivery import NAMESPACE as DIRECT,key_for
                    from .chat_expressions import ChatExpressions
                    receipt=self.journal.fetch(DIRECT,key_for(task),ChatExpressions.message_scope(scope['user_id'],_app_session(scope)))
                    row=await self._change(scope,row,state='stored',reason='sdk_history_saved',message_id=receipt['data'].get('message_id')if receipt else None)
                else:row=await self._change(scope,row,state='unknown',reason='sdk_history_outcome_unknown')
            else:
                queued=await delivery.submit(scope,d['event_id'],text='想把这个画面分享给你。',images=[str(path)],max_attempts=1,expires_at=d['expires_at'])
                await self._change(scope,row,state='queued'if queued.get('state')in {'queued','approved','claimed','sending'}else'blocked',reason='native_delivery_'+queued.get('state','unknown'))
        except asyncio.CancelledError:
            try:await self._change(scope,row,state='unknown',reason='job_interrupted')
            except (RuntimeError,JournalConflict,PermissionError):pass
            raise
        except Exception:
            try:await self._change(scope,row,state='unknown',reason='image_followup_unconfirmed')
            except (RuntimeError,JournalConflict,PermissionError):pass

    def delivery_metadata(self,task):
        if not self._current():return None
        scope=self._scope(task['scope']);ref=self.journal.fetch(TASKS,task['id'],scope)
        if not ref:return None
        row=self.journal.fetch(NAMESPACE,ref['data']['job_id'],scope)
        if not row:return None
        d=row['data']
        if d.get('delivery_task_id')!=task['id']or task.get('images')!=[d.get('image_path')]:return None
        return dict(job_id=d['id'],parent_message_id=d['parent_message_id'],purpose=d['purpose'],source=d['source'])

    async def owns_task(self,scope,task):
        if not self._current()or task.get('scope')!=scope:return False
        return await asyncio.to_thread(self.delivery_metadata,task)is not None

    async def delivery_allowed(self,scope,task):
        if not await self.owns_task(scope,task)or not self._allowed(scope):return False
        ref=await asyncio.to_thread(self.journal.fetch,TASKS,task['id'],scope)
        row=await asyncio.to_thread(self.journal.fetch,NAMESPACE,ref['data']['job_id'],scope)
        if row is None:return False
        data=row['data']
        from .delivery_types import task_input_hash
        if (data['source']=='user_request'or data.get('inheritance')is not None
                or data['state']not in {'submitting','queued'}or task.get('max_attempts')!=1
                or task.get('text')!='想把这个画面分享给你。'or task.get('expires_at')!=data['expires_at']
                or self.host.clock()>=data['expires_at']or task.get('input_hash')!=task_input_hash(task)):
            return False
        def exact_media():
            path=Path(data['image_path'])
            return (not path.is_symlink()and path.parent==self.runtime.image_service.media_root
                and path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==data['image_sha256'])
        if not await asyncio.to_thread(exact_media):return False
        latest=await asyncio.to_thread(self.journal.fetch,NAMESPACE,data['id'],scope)
        return bool(latest and latest['revision']==row['revision']and latest['data']==data and self._allowed(scope))

    async def reconcile(self,scope):
        """Read pending originals. No image call or second SDK insert."""
        scope=self._scope(scope)
        def pending_rows():
            with self.journal._lock:
                self.journal._ensure_open()
                rows=self.journal._db.execute("SELECT revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? AND (json_extract(data,'$.state') IN ('unknown','queued','pending','generating','submitting','dispatching') OR (json_extract(data,'$.state')='stored' AND COALESCE(json_extract(data,'$.message_id'),'')='')) ORDER BY updated DESC,key LIMIT 50",
                    (NAMESPACE,scope_key(scope))).fetchall()
                return [self.journal._record(row)for row in rows]
        rows=await asyncio.to_thread(pending_rows)
        delivery=getattr(self.runtime,'delivery',None)
        for row in rows:
            d=row['data'];state=d['state']
            if state=='queued'and delivery is not None:
                task=await asyncio.to_thread(delivery.store.get,d['delivery_task_id'])
                if task and task['state']in {'confirmed','failed','cancelled','expired','unknown','quarantined'}:
                    await self._change(scope,row,state='stored'if task['state']=='confirmed'else'unknown'if task['state']in {'unknown','quarantined'}else'failed',reason='native_delivery_'+task['state'])
            if (state in UNRESOLVED or state=='stored'and not d.get('message_id'))and(scope_key(scope),d['id'])not in self._pending:
                # Recovery keeps the original image and SDK delivery identities.
                from .chat_delivery import NAMESPACE as DIRECT
                from .chat_expressions import ChatExpressions
                message_scope=ChatExpressions.message_scope(scope['user_id'],_app_session(scope))
                direct_key=hashlib.sha256(canonical([scope,d['delivery_task_id']]).encode()).hexdigest()
                receipt=await asyncio.to_thread(self.journal.fetch,DIRECT,direct_key,message_scope)
                message_id=receipt['data'].get('message_id')if receipt else None
                stored=bool(receipt and receipt['data'].get('state')=='stored')
                if receipt and not message_id and delivery is not None:
                    adapter=delivery.sender.adapter
                    database=getattr(adapter,'database',None)
                    if database is None:
                        from astrbot.core import db_helper
                        database=db_helper
                    history=await database.get_platform_message_history(platform_id='webchat',user_id=_app_session(scope),page_size=1000)
                    matches=[item for item in history if isinstance(item.content,dict)
                        and isinstance(item.content.get('refs'),dict)
                        and item.content['refs'].get('tls_delivery_key')==direct_key
                        and item.content['refs'].get('tls_generated_image',{}).get('job_id')==d['id']]
                    if len(matches)==1:stored=True;message_id=str(matches[0].id)
                if stored:
                    latest=await asyncio.to_thread(self.journal.fetch,NAMESPACE,d['id'],scope)
                    if latest['data']['state']!='stored'or message_id and latest['data'].get('message_id')!=message_id:
                        await self._change(scope,latest,state='stored',reason='original_history_reconciled',message_id=message_id)
                elif state not in {'queued','unknown','stored'}:
                    latest=await asyncio.to_thread(self.journal.fetch,NAMESPACE,d['id'],scope)
                    await self._change(scope,latest,state='unknown',reason='interrupted_original_requires_review')
        return await asyncio.to_thread(self.list,scope)

    def stop(self):
        self.active=False
        for task in tuple(self._pending.values())+tuple(self._observers.values()):task.cancel()

    async def close(self):
        tasks=list(self._pending.values())+list(self._observers.values());self.stop()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        self._owned_requests.clear()


def service_for(plugin):
    host=getattr(getattr(plugin,'_presence',None),'living_host',None)
    runtime=getattr(host,'runtime',None)
    if host is None or runtime is None or host._closed or not runtime.active:raise RuntimeError('living Host unavailable')
    service=getattr(runtime,'chat_images',None)
    if service is None:
        service=ChatGeneratedImages(host);runtime.chat_images=service
    return service
