"""Bounded orchestration over Presence and the existing public memory bridge.

The host may attach isolated native policies/delivery and unified composition.
No implicit production takeover, model invocation, or extra polling loop.
"""
from __future__ import annotations
import asyncio
import hashlib
import inspect
import re
import time
import threading
from datetime import datetime, timedelta, timezone

from .models import EvidenceKind, Observation, PRESENCE_EVIDENCE, canonical, private_scope
from .journal import JournalConflict


def _safe_text(value, maximum=160):
    return ' '.join(re.sub(r'[\x00-\x1f\x7f<>]', ' ', str(value or '')).split())[:maximum]


def _catalog_metadata(payload):
    song=payload.get('song_info') if isinstance(payload,dict) else None
    if not isinstance(song,dict):return None
    if any(not isinstance(song.get(key),str) or not song[key].strip() or len(song[key])>maximum
           for key,maximum in (('song_id',128),('title',300))):return None
    if 'artist' in song and not isinstance(song['artist'],str):return None
    return song


class LivingRuntime:
    def __init__(self, presence, journal, governance, memory=None, *, clock=time.time,
                 scope_validator=None, operation_timeout=2.0):
        self.presence, self.journal, self.governance, self.memory = presence,journal,governance,memory
        self.clock, self.scope_validator = clock,scope_validator
        self.active=True
        self._lock=asyncio.Lock()
        self._owned_sources={}
        self._pending=set()
        self.operation_timeout=min(max(float(operation_timeout),0.01),10.0)
        self.metrics={'accepted':0,'duplicates':0,'denied':0,'errors':0,'memory_success':0}

    def memory_context_legacy_allowed(self, context):
        """Compatibility gate; absent policy preserves the legacy composer."""
        from .memory_context_mode import current_memory_policy
        policy = current_memory_policy(self)
        return True if policy is None else policy.legacy_allowed(context)

    async def compose_feature_context(self, session_context, *, query, kind, max_chars=900):
        """Route a legacy caller using its genuine, current inbound binding.

        An unowned scope preserves the existing legacy route. A known Native
        session never falls back on stale identity, missing grants or errors.
        """
        from .memory_context_mode import current_memory_policy
        def field(name, default=None):
            return session_context.get(name, default) if isinstance(session_context, dict) else getattr(session_context, name, default)
        try:
            policy = current_memory_policy(self)
            if policy is None or policy.legacy_allowed(session_context):
                return {'handled': False, 'text': '', 'state': 'legacy_owner'}
        except (TypeError, ValueError, PermissionError, RuntimeError):
            return {'handled': True, 'text': '', 'state': 'ownership_unavailable'}
        denied = {'handled': True, 'text': '', 'state': 'native_denied'}
        session = field('session_id')
        scope = self.presence.scope_for_session(session) if isinstance(session, str) else None
        if not self.active or scope is None:
            return denied
        # The persona may be absent in the old public context; only the
        # genuine Presence binding can supply it, never guessed defaults.
        platform_aliases = {scope['platform'], scope['session_id'].split(':', 1)[0]}
        if (field('scope', 'private' if field('private') is True else '') != 'private'
                or field('platform') not in platform_aliases
                or any(field(key) != scope[key] for key in ('bot_id', 'user_id', 'session_id'))
                or any(field(key) not in (None, '', scope['character_id']) for key in ('persona_id', 'character_id'))):
            return denied
        if kind in {'private_turn_recall', 'current_state_reply'}:
            return {'handled': True, 'text': '', 'state': 'unified_request_outlet'}
        unified = getattr(self, 'unified', None)
        if unified is None:
            return denied
        try:
            text = await unified.compose_feature_context(scope, query=query, kind=kind, max_chars=max_chars)
        except (TypeError, ValueError, RuntimeError, PermissionError):
            return {'handled': True, 'text': '', 'state': 'native_unavailable'}
        return {'handled': True, 'text': text, 'state': 'ready' if text else 'empty_or_denied'}

    async def _allowed(self, capability, scope, source=None):
        if not self.active:return False
        if self.scope_validator is not None:
            result=self.scope_validator(scope)
            if inspect.isawaitable(result):result=await result
            if not result:return False
        permitted=await asyncio.to_thread(self.governance.allows,capability,scope,source)
        if not self.active:return False
        if self.scope_validator is not None:
            result=self.scope_validator(scope)
            if inspect.isawaitable(result):result=await result
            if not result:return False
        return bool(permitted)

    def _authorized_sync(self, scope, source, *capabilities, cancelled=None):
        """Final SQLite authority check, including the current host binding.

        Transaction guards cannot await: hosts must provide a synchronous scope
        validator. An asynchronous/awaitable validator fails closed here even
        when it passed the earlier asynchronous admission checks.
        """
        def current_scope():
            if not self.active or cancelled is not None and cancelled.is_set():
                return False
            if self.scope_validator is None:
                return True
            result = self.scope_validator(scope)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result): result.close()
                return False
            return bool(result)
        try:
            return (current_scope() and
                all(self.governance.allows(capability, scope, source) for capability in capabilities) and
                current_scope())
        except Exception:
            return False

    def bind_projection_source(self, source_id, domains, renderer=None):
        """Explicitly bind a NEW source; never replace another plugin's owner."""
        if not self.active:raise RuntimeError('living runtime is closed')
        if source_id in self._owned_sources:return
        if any(s['source']==source_id for s in self.presence.diagnostics()['registered_sources']):
            raise ValueError('source already belongs to another provider')
        self.presence.register(source_id,owner=self,domains=tuple(domains),renderer=renderer)
        self._owned_sources[source_id]=frozenset(domains)

    async def _bounded(self, awaitable):
        if len(self._pending)>=8:
            if inspect.iscoroutine(awaitable):awaitable.close()
            raise RuntimeError('operation capacity reached')
        task=asyncio.create_task(awaitable)
        self._pending.add(task)
        def completed(t):
            self._pending.discard(t)
            if not t.cancelled():t.exception()
        task.add_done_callback(completed)
        try:
            done,_=await asyncio.wait({task},timeout=self.operation_timeout)
            if not done:
                task.cancel()
                raise TimeoutError('operation timed out; outcome may be unknown')
            return task.result()
        except asyncio.CancelledError:
            task.cancel();raise

    async def ingest(self, observation, *, publish=False):
        obs=Observation.from_dict(observation.as_dict())
        scope=obs.scope;oid=obs.observation_id
        if obs.received_at>self.clock()+30:
            return {'ok':False,'state':'rejected','reason':'future_receipt','observation_id':oid}
        async with self._lock:
            if not await self._allowed(obs.permission_scope,scope,obs.source_id) or not await self._allowed('observe.persist',scope,obs.source_id):
                self.metrics['denied']+=1
                return {'ok':False,'state':'denied','observation_id':oid}
            try:
                budget=await asyncio.to_thread(self.governance.reserve,'observations',1,scope,reservation_id=oid)
                if not budget['ok']:return {'ok':False,'state':'budget_exhausted','observation_id':oid}
                if not await self._allowed(obs.permission_scope,scope,obs.source_id) or not await self._allowed('observe.persist',scope,obs.source_id):
                    return {'ok':False,'state':'denied','observation_id':oid}
                # Cancellation cannot stop a SQLite worker. Check a cancellation
                # token and grants inside the same transaction before commit.
                cancelled=threading.Event()
                def authority():
                    return self._authorized_sync(scope, obs.source_id,
                        obs.permission_scope, 'observe.persist', cancelled=cancelled)
                write_task=asyncio.create_task(asyncio.to_thread(self.journal.record,obs,authorize=authority))
                try:inserted=await asyncio.shield(write_task)
                except asyncio.CancelledError:
                    cancelled.set()
                    write_task.add_done_callback(lambda t:t.exception() if not t.cancelled() else None)
                    raise
                if not await self._allowed(obs.permission_scope,scope,obs.source_id) or not await self._allowed('observe.persist',scope,obs.source_id):
                    if inserted:await asyncio.to_thread(self.journal.remove_observation,oid,scope)
                    return {'ok':False,'state':'revoked','observation_id':oid}
                if publish:
                    if obs.observation_type not in self._owned_sources.get(obs.source_id,()):
                        raise ValueError('explicit projection source binding required')
                    accepted=self.presence.update(obs.source_id,scope,obs.observation_type,obs.payload,
                        observed_at=obs.observed_at,received_at=obs.received_at,
                        ttl_seconds=(obs.expires_at-obs.observed_at) if obs.expires_at is not None else 0,
                        evidence_kind=PRESENCE_EVIDENCE[obs.evidence_kind],status=obs.status,
                        device_id=obs.device_id,change_key=obs.change_key,importance=obs.importance)
                    if not accepted:return {'ok':False,'state':'projection_rejected','observation_id':oid}
                self.metrics['accepted' if inserted else 'duplicates']+=1
                memory_result={'ok':False,'state':'not_important'}
                # Heartbeats, device progress, unknown music and RP body changes are not long-term facts.
                transient=(obs.observation_type in {'time','heartbeat','music','music_unknown','music_stale'} or
                    obs.observation_type.startswith('device.') or obs.observation_type=='user_activity')
                unknown_music=(obs.observation_type=='music' and (not isinstance(obs.payload,dict) or
                    obs.payload.get('state') in {'unknown','unavailable','stale'}))
                important=(not transient and not unknown_music and obs.valid_at(self.clock()) and
                    obs.evidence_kind is EvidenceKind.REAL_OBSERVATION and (
                    obs.importance in {'important','critical'} or
                    obs.observation_type=='music.catalog_reference' and isinstance(obs.payload,dict) and
                    obs.payload.get('match_status')=='matched' and _catalog_metadata(obs.payload) is not None))
                if obs.observation_type=='music.catalog_reference' and _catalog_metadata(obs.payload) is None:
                    important=False
                if inserted and important and self.memory is not None and await self._allowed('memory.write',scope,obs.source_id):
                    try:
                        fact_key=hashlib.sha256(canonical([obs.source_id,obs.observation_type,
                            obs.evidence_kind.value,obs.change_key if obs.change_key is not None else obs.payload]).encode()).hexdigest()
                        fact=await asyncio.to_thread(self.journal.fetch,'fact_memory',fact_key,scope)
                        if fact:
                            memory_result=dict(fact['data'].get('result') or {'ok':False,'state':'pending'},deduplicated=True)
                        else:
                            try:
                                fact=await asyncio.to_thread(self.journal.put,'fact_memory',fact_key,scope,
                                    {'state':'pending','observation_id':oid},expected_revision=0,authorize=authority)
                            except JournalConflict:
                                fact=await asyncio.to_thread(self.journal.fetch,'fact_memory',fact_key,scope)
                                memory_result=dict(fact['data'].get('result') or {'ok':False,'state':'pending'},deduplicated=True)
                            else:fact=None
                        if fact is not None:
                            await asyncio.to_thread(self.journal.audit,'ObservationReceived',scope,oid,'recorded',
                                {'type':obs.observation_type,'memory_state':memory_result.get('state','pending'),'semantic_duplicate':True})
                            return {'ok':True,'state':'recorded','observation_id':oid,'memory':memory_result}
                        memory_obs=obs
                        if obs.observation_type=='music.catalog_reference':
                            info=obs.payload.get('song_info',{})
                            summary='既有曲库资料：曲目《'+_safe_text(info.get('title'),160)+'》'
                            if info.get('artist'):summary+='，艺术家：'+_safe_text(info['artist'],160)
                            summary+='。系统仅读取元数据，未获取或播放音频；不代表用户的收听或偏好。'
                            memory_data=obs.as_dict();memory_data['payload']=dict(obs.payload,summary=summary)
                            memory_data['change_key']=obs.change_key if obs.change_key is not None else obs.payload
                            memory_obs=Observation.from_dict(memory_data)
                        async def authorize_memory():
                            return (await self._allowed(obs.permission_scope,scope,obs.source_id) and
                                await self._allowed('observe.persist',scope,obs.source_id) and
                                await self._allowed('memory.write',scope,obs.source_id))
                        parameters=inspect.signature(self.memory.write).parameters
                        call=self.memory.write(memory_obs,authorize=authorize_memory) if 'authorize' in parameters else self.memory.write(memory_obs)
                        memory_result=await self._bounded(call)
                        if memory_result.get('ok'):self.metrics['memory_success']+=1
                        await asyncio.to_thread(self.journal.put,'fact_memory',fact_key,scope,
                            {'state':memory_result.get('state','unknown'),'observation_id':oid,'result':memory_result})
                    except TimeoutError:
                        memory_result={'ok':False,'state':'unknown'}
                        await asyncio.to_thread(self.journal.put,'fact_memory',fact_key,scope,
                            {'state':'unknown','observation_id':oid,'result':memory_result})
                await asyncio.to_thread(self.journal.audit,'ObservationReceived',scope,oid,'recorded' if inserted else 'duplicate',
                    {'type':obs.observation_type,'evidence_kind':obs.evidence_kind.value,'memory_state':memory_result.get('state','unknown')})
                return {'ok':True,'state':'recorded' if inserted else 'duplicate','observation_id':oid,'memory':memory_result}
            except asyncio.CancelledError:raise
            except Exception as e:
                self.metrics['errors']+=1
                return {'ok':False,'state':'error','error_type':type(e).__name__,'observation_id':oid}

    async def restore(self, scope):
        """Restore valid new projections only, retaining ORIGINAL times/expiry."""
        rows=await asyncio.to_thread(self.journal.recent,scope,limit=1000,now=self.clock())
        count=0
        for row in reversed(rows):
            obs=Observation.from_dict(row)
            if obs.source_id not in self._owned_sources or not obs.valid_at(self.clock()):continue
            if not await self._allowed(obs.permission_scope,scope,obs.source_id):continue
            if not await self._allowed('observe.persist',scope,obs.source_id):continue
            if self.presence.update(obs.source_id,scope,obs.observation_type,obs.payload,
                    observed_at=obs.observed_at,received_at=obs.received_at,
                    ttl_seconds=obs.expires_at-obs.observed_at,evidence_kind=PRESENCE_EVIDENCE[obs.evidence_kind],
                    status=obs.status,device_id=obs.device_id,change_key=obs.change_key,importance=obs.importance):count+=1
        return {'ok':True,'restored':count}

    async def propose(self, observation_id, scope, *, relevance=0.7, reason='new_catalog_reference'):
        scope=private_scope(scope)
        row=await asyncio.to_thread(self.journal.get,observation_id,scope)
        if row is None:return {'ok':False,'state':'missing_observation'}
        obs=Observation.from_dict(row)
        if not await self._allowed('share.propose',scope,obs.source_id):return {'ok':False,'state':'denied'}
        if not obs.valid_at(self.clock()):return {'ok':False,'state':'expired'}
        if obs.evidence_kind is not EvidenceKind.REAL_OBSERVATION:return {'ok':False,'state':'unsupported_evidence'}
        if obs.observation_type!='music.catalog_reference' or not isinstance(obs.payload,dict) or obs.payload.get('match_status')!='matched':
            return {'ok':True,'state':'no_action','reason':'no_valuable_discovery'}
        if isinstance(relevance,bool) or not isinstance(relevance,(int,float)) or not 0<=relevance<=1:
            raise ValueError('invalid relevance')
        song=_catalog_metadata(obs.payload)
        if song is None:return {'ok':False,'state':'invalid_metadata'}
        fingerprint=hashlib.sha256(canonical([obs.source_id,song['song_id'],obs.evidence_kind.value]).encode()).hexdigest()
        existing=await asyncio.to_thread(self.journal.fetch,'candidates',fingerprint,scope)
        if existing:return {'ok':True,'state':'duplicate','candidate_id':fingerprint,'candidate':existing['data']}
        count=await asyncio.to_thread(self.journal.list,'candidates',scope,limit=100)
        if len(count)>=100:return {'ok':False,'state':'candidate_capacity'}
        budget=await asyncio.to_thread(self.governance.reserve,'explorations',1,scope,reservation_id=fingerprint)
        if not budget['ok']:return {'ok':False,'state':'budget_exhausted'}
        if not await self._allowed('share.propose',scope,obs.source_id) or not self.active:
            return {'ok':False,'state':'denied'}
        candidate={'candidate_id':fingerprint,'observation_id':observation_id,'source_id':obs.source_id,
            'content_type':'music_catalog_reference','external_id':song['song_id'],
            'title':_safe_text(song['title']), 'artist':_safe_text(song.get('artist')),
            'relevance':float(relevance),'evaluation_basis':'catalog_metadata_only',
            'playback_claim':False,'state':'discovered','reason':_safe_text(reason),
            'discovered_at':self.clock(),'expires_at':obs.expires_at}
        def authorized():
            return obs.valid_at(self.clock()) and self._authorized_sync(scope, obs.source_id, 'share.propose')
        try:await asyncio.to_thread(self.journal.put,'candidates',fingerprint,scope,candidate,expected_revision=0,authorize=authorized)
        except JournalConflict:return {'ok':True,'state':'duplicate','candidate_id':fingerprint}
        except PermissionError:return {'ok':False,'state':'denied'}
        await asyncio.to_thread(self.journal.audit,'CandidateDiscovered',scope,fingerprint,'metadata_only')
        return {'ok':True,'state':'discovered','candidate_id':fingerprint,'candidate':candidate}

    async def decide(self, candidate_id, scope, *, quiet_hours='02:00-08:00', utc_offset_hours=8,
                     recent_chat_seconds=0, resources_ok=True):
        scope=private_scope(scope)
        row=await asyncio.to_thread(self.journal.fetch,'candidates',candidate_id,scope)
        if not row:return {'ok':False,'state':'missing_candidate'}
        c=row['data'];now=self.clock()
        action='prepare_share';reason='valuable_new_catalog_reference'
        if c.get('state') in {'prepared_only','confirmed','unknown','cancelled'}:action,reason='no_action','already_consumed_or_uncertain'
        elif c.get('expires_at',0)<=now:action,reason='no_action','expired'
        elif not await self._allowed('share.propose',scope,c['source_id']):action,reason='no_action','permission_denied'
        elif c.get('relevance',0)<0.5:action,reason='no_action','low_relevance'
        elif resources_ok is not True:action,reason='no_action','resource_protection'
        elif recent_chat_seconds>0 and recent_chat_seconds<1200:action,reason='no_action','recent_conversation'
        else:
            match=re.fullmatch(r'(\d{2}):(\d{2})-(\d{2}):(\d{2})',quiet_hours)
            if not match:raise ValueError('invalid quiet hours')
            h1,m1,h2,m2=map(int,match.groups())
            if max(h1,h2)>23 or max(m1,m2)>59:raise ValueError('invalid quiet hours')
            local=datetime.fromtimestamp(now,timezone(timedelta(hours=utc_offset_hours)))
            minute=local.hour*60+local.minute;start=h1*60+m1;end=h2*60+m2
            quiet=start<=minute<end if start<end else minute>=start or minute<end if start>end else False
            if quiet:action,reason='no_action','quiet_hours'
        decision_id=hashlib.sha256(canonical([candidate_id,action,reason]).encode()).hexdigest()
        decision={'decision_id':decision_id,'candidate_id':candidate_id,'observation_id':c['observation_id'],
            'action':action,'reason':reason,'evidence':['catalog_metadata_only'],
            'risk':'medium' if action=='prepare_share' else 'low','status':'material_ready' if action=='prepare_share' else 'not_sent',
            'cost':{'new_llm_calls':0,'new_api_calls':0},'decided_at':now,
            'policy':{'quiet_hours':quiet_hours,'utc_offset_hours':utc_offset_hours}}
        await asyncio.to_thread(self.journal.put,'decisions',decision_id,scope,decision)
        await asyncio.to_thread(self.journal.audit,'ShareProposed',scope,decision_id,decision['status'],{'reason':reason})
        return {'ok':True,**decision}

    async def material_for(self, scope, context=None):
        """Native PC executor input; material preparation is NOT a send receipt."""
        scope=private_scope(scope)
        rows=await asyncio.to_thread(self.journal.list,'decisions',scope,limit=100)
        for row in rows:
            decision=row['data']
            if decision.get('status')!='material_ready':continue
            candidate=await asyncio.to_thread(self.journal.fetch,'candidates',decision['candidate_id'],scope)
            if not candidate:continue
            c=candidate['data']
            if not await self._allowed('share.send',scope,c['source_id']):return {'ok':False,'status':'permission_denied'}
            if c.get('expires_at',0)<=self.clock() or c.get('state')!='discovered':continue
            if not await self._allowed('observe.persist',scope,c['source_id']):continue
            # An old prepared decision must not outlive a newly reached quiet window.
            policy=decision.get('policy',{})
            reconsidered=await self.decide(c['candidate_id'],scope,
                quiet_hours=policy.get('quiet_hours','02:00-08:00'),utc_offset_hours=policy.get('utc_offset_hours',8))
            if reconsidered.get('action')!='prepare_share':continue
            budget=await asyncio.to_thread(self.governance.reserve,'shares',1,scope,reservation_id=decision['decision_id'])
            if not budget['ok']:return {'ok':False,'status':'budget_exhausted'}
            if not await self._allowed('share.send',scope,c['source_id']) or not self.active:
                return {'ok':False,'status':'permission_denied'}
            def authority():
                return (c.get('expires_at',0)>self.clock() and self._authorized_sync(scope, c['source_id'],
                    'share.send', 'share.propose', 'observe.persist'))
            try:
                await asyncio.to_thread(self.journal.put,'candidates',c['candidate_id'],scope,
                    dict(c,state='prepared_only',prepared_at=self.clock()),expected_revision=candidate['revision'],authorize=authority)
            except JournalConflict:continue
            except PermissionError:return {'ok':False,'status':'permission_denied'}
            # No claim of listening. Actual native PC generation may phrase this through the original persona.
            text='……资料里看到了《'+_safe_text(c['title'],80)+'》'
            if c.get('artist'):text+='，'+_safe_text(c['artist'],60)
            text+='。先记下了，还没听过。'
            await asyncio.to_thread(self.journal.put,'decisions',decision['decision_id'],scope,
                dict(decision,status='prepared_only'))
            if not await self._allowed('share.send',scope,c['source_id']):
                return {'ok':False,'status':'permission_denied'}
            return {'ok':True,'text':text,'summary':'catalog_metadata_only',
                'status':'prepared_only','decision_id':decision['decision_id'],
                'observation_id':c['observation_id'],'candidate_id':c['candidate_id']}
        return {'ok':False,'status':'no_candidate'}

    async def close(self):
        self.active=False
        reminders=getattr(self,'reminders',None)
        unified=getattr(self,'unified',None)
        delivery=getattr(self,'delivery',None)
        phone=getattr(self,'phone_companion',None)
        images=getattr(self,'image_service',None)
        agenda=getattr(self,'agenda',None)
        important_dates=getattr(self,'important_dates',None)
        music_library=getattr(self,'music_library',None)
        memo_notes=getattr(self,'memo_notes',None)
        personal_goals=getattr(self,'personal_goals',None)
        scoped_daily_plans=getattr(self,'scoped_daily_plans',None)
        pc_daily_lifecycle=getattr(self,'pc_daily_lifecycle',None)
        expression_review=getattr(self,'expression_review',None)
        shared_timeline=getattr(self,'shared_timeline',None)
        expression_reply=getattr(self,'expression_reply',None)
        expression_assets=getattr(self,'expression_assets',None)
        history_adoption=getattr(self,'history_adoption',None)
        memory_transfer=getattr(self,'memory_transfer',None)
        proactive=getattr(self,'proactive_companion',None)
        generator=getattr(self,'proactive_generation',None)
        persona_binding=getattr(self,'proactive_persona_binding',None)
        errors=[]
        # Reject every ingress before the first await, including when close is
        # called directly after a cancelled construction rather than Host.stop.
        for service in (pc_daily_lifecycle, proactive, generator, persona_binding, shared_timeline, expression_review, music_library, memo_notes, scoped_daily_plans, personal_goals, important_dates, memory_transfer, history_adoption, expression_reply, expression_assets, agenda, phone, reminders, unified):
            if service is not None:
                try: service.stop()
                except BaseException as exc: errors.append(exc)
        if delivery is not None:
            delivery.active=False
            delivery.sender.active=False
        for task in tuple(self._pending):task.cancel()
        for service in (proactive, generator, agenda, phone, images, reminders, unified, delivery):
            if service is not None:
                try: await service.close()
                except BaseException as exc: errors.append(exc)
        if expression_reply is not None:
            try: await expression_reply.close()
            except BaseException as exc: errors.append(exc)
        if expression_assets is not None:
            try: await asyncio.to_thread(expression_assets.close)
            except BaseException as exc: errors.append(exc)
        if history_adoption is not None:
            try: await asyncio.to_thread(history_adoption.close)
            except BaseException as exc: errors.append(exc)
        if memory_transfer is not None:
            try: await asyncio.to_thread(memory_transfer.close)
            except BaseException as exc: errors.append(exc)
        if getattr(getattr(self, 'memory', None), 'backend', None) == 'native':
            try: await self.memory.close()
            except BaseException as exc: errors.append(exc)
        history = getattr(self, 'history_archive', None)
        if history is not None:
            try: await asyncio.to_thread(history.close)
            except BaseException as exc: errors.append(exc)
        for source in tuple(self._owned_sources):
            try:
                self.presence.unregister(source,owner=self)
                self._owned_sources.pop(source,None)
            except BaseException as exc: errors.append(exc)
        if self._pending:
            try: await asyncio.wait(self._pending,timeout=1.0)
            except BaseException as exc: errors.append(exc)
        if len(errors)==1: raise errors[0]
        if errors: raise BaseExceptionGroup('TLS runtime cleanup failed', errors)

    def diagnostics(self):
        delivery=getattr(self,'delivery',None)
        reminders=getattr(self,'reminders',None)
        return {'active':self.active,'pending_operations':len(self._pending),'metrics':dict(self.metrics),
                'memory_backend':getattr(self.memory, 'backend', 'legacy_bridge'),
                'host_services':getattr(self, 'native_services', None).diagnostics()
                    if getattr(self, 'native_services', None) is not None else {'active':False},
                'history_archive_active':not getattr(getattr(self, 'history_archive', None), 'closed', True),
                'history_adoption_active':getattr(getattr(self,'history_adoption',None),'active',False),
                'memory_transfer_active':getattr(getattr(self,'memory_transfer',None),'active',False),
                'projection_sources':sorted(self._owned_sources),'sender':'tls_native_isolated' if delivery is not None else 'existing_private_companion',
                'delivery_receipt_support':'host_adapter_required','new_scheduler':delivery is not None,
                'isolated_delivery':delivery.diagnostics() if delivery is not None else None,
                'isolated_reminders':reminders.diagnostics() if reminders is not None else None}
