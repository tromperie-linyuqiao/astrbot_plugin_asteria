"""Internal TLS composition root. Existing policies and delivery stay in place.

The first increment is isolated-only. A trusted host factory supplies it; no
configuration or LLM tool can acquire production ownership through this API.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time

from .capability_registry import CapabilityRegistry, CapabilitySpec
from .context_engine import ContextAssembler, ContextFragment, content_fingerprint
from .models import private_scope, scope_key
from .narrative import NarrativeStore, choose_strategy
from .memory_context import NativeMemoryContextPolicy
from .native_shared_timeline import NativeSharedTimeline
from .native_music_library import NativeMusicLibrary
from .native_music_reference import MusicReferenceContribution, NativeMusicReference

_OBJECT = {'type': 'object', 'additionalProperties': True, 'maxProperties': 64}
_QUERY = {'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 2000}},
          'additionalProperties': False}


class UnifiedSystem:
    environment = 'isolated'

    def __init__(self, *, journal, runtime, presence, authorize, governance,
                 clock=time.time, max_chars=2400, environment, memory_policy=None, feature_policy=None,
                 private_memory_policy=None):
        from .native_memory_adapter import NativeMemoryAdapter
        native_memory = isinstance(getattr(runtime, 'memory', None), NativeMemoryAdapter)
        if environment != 'isolated' and not (environment == 'native_memory' and native_memory):
            raise PermissionError('unified composition requires isolated environment')
        self.environment = environment
        self.runtime, self.presence, self.governance = runtime, presence, governance
        self._authorize_scope, self.clock = authorize, clock
        self.memory_policy = memory_policy
        self._memory_selection = NativeMemoryContextPolicy()
        self.feature_policy = feature_policy
        self.private_memory_policy = private_memory_policy
        self.active = True
        self.assembler = ContextAssembler(authorize=lambda scope: self._permission(scope, 'context.read'),
            max_chars=max_chars, clock=clock)
        self.narrative = NarrativeStore(journal, authorize=self._narrative_authorize, clock=clock)
        library = getattr(runtime, 'music_library', None)
        self._music_reference = NativeMusicReference(library, clock=clock) if type(library) is NativeMusicLibrary else None
        self.capabilities = CapabilityRegistry(authorize=self._permission)
        self.metrics = {'provider_errors': 0, 'context_calls': 0}
        self._register()

    def scope_allowed(self, scope):
        try:
            return self.active and self._authorize_scope(private_scope(scope)) is True
        except Exception:
            return False

    def _permission(self, scope, permission):
        memory = getattr(self.runtime, 'memory', None)
        if self.environment == 'native_memory' and permission in {
                'context.read', 'memory.read', 'presence.read',
                'narrative.read', 'narrative.write', 'preferences.write', 'context.feature.read', 'context.private.read'}:
            return self.scope_allowed(scope) and memory.allowed(scope) and self.scope_allowed(scope)
        return (self.scope_allowed(scope) and self.governance.allows(permission, scope)
                and self.scope_allowed(scope))

    def _narrative_authorize(self, operation, scope):
        permission = {'read': 'narrative.read', 'write': 'narrative.write',
                      'preferences.write': 'preferences.write'}.get(operation)
        return bool(permission and self._permission(scope, permission))

    def _register(self):
        self.capabilities.register(CapabilitySpec(
            'tls.presence.read', '读取已有 Presence 的当前有效投影，不创建第二个采集器。',
            {'type': 'object', 'properties': {'aspect': {'type': 'string', 'maxLength': 128}},
             'additionalProperties': False}, _OBJECT, permissions=('presence.read',),
            test_entry='tests.test_living_unified_system.test_actual_registry_handlers_and_unified_context_do_not_replace_persona'), self._read_presence)
        self.capabilities.register(CapabilitySpec(
            'tls.narrative.context', '读取分来源、带知识边界的当前剧情与明确偏好。',
            _QUERY, _OBJECT, permissions=('narrative.read',),
            test_entry='tests.test_living_narrative'), self._read_narrative)
        self.capabilities.register(CapabilitySpec(
            'tls.context.preview', '通过统一装配器预览补充上下文，不调用模型、不发送。',
            _QUERY, _OBJECT,
            permissions=('context.read',), test_entry='tests.test_living_context_engine'), self._preview)
        self.capabilities.register(CapabilitySpec(
            'tls.memory.recall', '使用已有公开记忆桥检索真实记忆，缺失时降级。',
            _QUERY, _OBJECT, permissions=('memory.read',),
            test_entry='tests.test_living_unified_system.test_no_grants_and_foreign_scope_fail_closed'), self._recall)
        self.capabilities.register(CapabilitySpec(
            'tls.interaction.strategy', '显式选择互动方式；不推断沉默情绪、不调度或发送。',
            {'type': 'object', 'properties': {'requested': {'type': 'string', 'maxLength': 64}},
             'additionalProperties': False}, _OBJECT, permissions=('context.read',),
            test_entry='tests.test_living_narrative.test_strategy_is_explicit_pure_and_has_no_emotion_or_delivery_effect'), self._strategy)
        timeline = getattr(self.runtime, 'shared_timeline', None)
        if isinstance(timeline, NativeSharedTimeline) and timeline.store is getattr(getattr(self.runtime, 'memory', None), 'store', None):
            self.capabilities.register(CapabilitySpec(
                'tls.timeline.context', '按相关性读取人工确认的共同经历参考，不变更人格或调用模型。',
                _QUERY, _OBJECT, permissions=('context.read', 'memory.read'),
                test_entry='tests.test_native_shared_timeline_context_r35'), self._read_timeline_context)
        if self.feature_policy is not None:
            self.capabilities.register(CapabilitySpec(
                'tls.feature.context', '原生筛选日程、穿搭、能力与媒体材料，不生成或发送。',
                {'type': 'object', 'properties': {
                    'query': {'type': 'string', 'maxLength': 2000},
                    'kind': {'type': 'string', 'maxLength': 64},
                    'max_chars': {'type': 'integer', 'minimum': 160, 'maximum': 2400}},
                 'required': ['query', 'kind', 'max_chars'], 'additionalProperties': False},
                _OBJECT, permissions=('context.read', 'memory.read', 'context.feature.read'),
                test_entry='tests.test_stage7_feature_integration'), self._read_feature_context)
        if self.private_memory_policy is not None:
            self.capabilities.register(CapabilitySpec(
                'tls.private_memory.context', '原生筛选已授权私人规则、偏好和相关事实，不生成画像或调用模型。',
                {'type':'object','properties':{'query':{'type':'string','maxLength':2000},
                    'kind':{'type':'string','maxLength':64},
                    'mode':{'type':'string','enum':['all','core_only']},
                    'max_chars':{'type':'integer','minimum':160,'maximum':2400}},
                 'required':['query','kind','max_chars'],'additionalProperties':False},
                _OBJECT,permissions=('context.read','memory.read','context.feature.read','context.private.read'),
                test_entry='tests.test_stage8_private_integration'),self._read_private_context)

    async def _read_timeline_context(self, payload, *, scope, config):
        generation = self._timeline_generation(scope)
        if generation is None:
            return {'sections': [], 'selected_ids': [], 'state': 'timeline_unavailable'}
        material = await asyncio.to_thread(self.runtime.shared_timeline.context_material,
            scope, query=payload.get('query', ''), limit=4, max_chars=600)
        if self._timeline_generation(scope) != generation:
            return {'sections': [], 'selected_ids': [], 'state': 'timeline_authority_changed'}
        return material

    async def _read_presence(self, payload, *, scope, config):
        return self.presence.read(scope, payload.get('aspect') or None, now=self.clock())

    async def _read_narrative(self, payload, *, scope, config):
        return await asyncio.to_thread(self.narrative.render_context, scope,
            query=payload.get('query', ''), max_chars=min(1200, self.assembler.max_chars // 2), now=self.clock())

    async def _recall(self, payload, *, scope, config):
        bridge = getattr(self.runtime, 'memory', None)
        if bridge is None:
            return {'ok': False, 'state': 'memory_adapter_missing', 'memories': []}
        return await bridge.recall(payload.get('query', ''), scope=scope, top_k=3)

    async def _read_feature_context(self, payload, *, scope, config):
        bridge = getattr(self.runtime, 'memory', None)
        reader = getattr(bridge, 'context_material', None)
        if not callable(reader):
            return {'sections': [], 'selected_ids': [], 'state': 'material_adapter_missing'}
        raw = await reader(scope=scope, limit=64)
        if not isinstance(raw, dict) or raw.get('ok') is not True:
            return {'sections': [], 'selected_ids': [], 'state': 'material_unavailable'}
        return self.feature_policy.select(raw.get('items', []), scope=scope,
            query=payload['query'], kind=payload['kind'], now=self.clock(), max_chars=payload['max_chars'])

    async def _read_private_context(self,payload,*,scope,config):
        generation=self._private_generation(scope)
        if generation is None:
            return {'sections':[],'selected_ids':[],'state':'private_owner_unavailable'}
        bridge=getattr(self.runtime,'memory',None)
        reader=getattr(bridge,'private_context_material',None)
        if not callable(reader):
            return {'sections':[],'selected_ids':[],'state':'private_adapter_missing'}
        raw=await reader(scope=scope,limit=64)
        if self._private_generation(scope)!=generation:
            return {'sections':[],'selected_ids':[],'state':'private_authority_changed'}
        if not isinstance(raw,dict) or raw.get('ok') is not True:
            return {'sections':[],'selected_ids':[],'state':'private_material_unavailable'}
        rows=raw.get('items',[])
        if not isinstance(rows,list):
            return {'sections':[],'selected_ids':[],'state':'invalid_private_material'}
        # One invocation of the existing public recall supplements older
        # relevant facts. The native policy owns final selection/dedup; there
        # is no second index, composer, memory writer or model request.
        core_only=payload.get('mode')=='core_only'
        if core_only:
            rows=[row for row in rows if isinstance(row,dict) and row.get('memory_type')=='core_memory']
        recall=getattr(bridge,'recall',None)
        if not core_only and callable(recall) and payload['query'].strip():
            recalled=await recall(payload['query'],scope=scope,top_k=3)
            if isinstance(recalled,dict) and recalled.get('ok') is True:
                facts=recalled.get('memories',[])
                if isinstance(facts,list):
                    rows=rows[:61]+facts[:3]
        if self._private_generation(scope)!=generation:
            return {'sections':[],'selected_ids':[],'state':'private_authority_changed'}
        # The native policy binds keys to its authorized selected candidates.
        # Never infer a key from unvalidated raw rows sharing a record ID.
        selected=self.private_memory_policy.select(rows,scope=scope,
            query=payload['query'],kind=payload['kind'],now=self.clock(),max_chars=payload['max_chars'])
        controller=getattr(bridge,'mc_context_runtime',None)
        if controller is not None:controller.record_selection(scope,selected)
        return selected

    async def _strategy(self, payload, *, scope, config):
        scene, preference = None, None
        if self._permission(scope, 'narrative.read'):
            scene = await asyncio.to_thread(self.narrative.read_scene, scope)
            row = await asyncio.to_thread(self.narrative.get_preference, scope, 'interaction_mode')
            if row:
                preference = row['data']['payload']['value']
                if preference not in {'normal', 'deep', 'rp', 'continue_plot', 'share', 'playful', 'quiet'}:
                    preference = None
        return choose_strategy(payload.get('requested', 'normal'), scene_active=scene is not None,
                               explicit_preference=preference)

    async def _preview(self, payload, *, scope, config):
        generations=self._context_generations(scope)
        fragments = await self.contributions(scope, query=payload.get('query', ''))
        fragments=[f for f in fragments if self._fragment_authorized(scope,f,generations)]
        fragments=sorted(fragments,key=lambda f:(-f.priority,f.fragment_id))[:self.assembler.max_fragments]
        material=self.assembler.compose(scope, fragments)
        by_id={f.fragment_id:f for f in fragments}
        if any(not self._fragment_authorized(scope,by_id[identity],generations)
               for identity in material['selected']):
            return {'text':'','selected':[],'chars':0}
        return material

    def _source_generation(self,scope,source):
        if source=='tls.timeline':return self._timeline_generation(scope)
        if source=='tls.expression':return self._expression_generation(scope)
        if source=='tls.memory':return self._memory_generation(scope)
        if source=='tls.feature':return self._feature_generation(scope)
        if source=='tls.private_memory':return self._private_generation(scope)
        name={'tls.narrative':'tls.narrative.context','tls.interaction':'tls.interaction.strategy'}.get(source)
        if name is None or not self._permission(scope,'narrative.read'):
            return None
        for row in self.capabilities.describe():
            if row['capability_id']==name:
                if row['enabled'] and row['health'] not in {'closed','disabled','dependency_unavailable'}:
                    try:
                        return (row['generation'], self.narrative.generation(scope))
                    except (PermissionError, ValueError, RuntimeError, sqlite3.Error):
                        return None
        return None

    def _context_generations(self,scope):
        return {source:self._source_generation(scope,source) for source in
            ('tls.memory','tls.feature','tls.private_memory','tls.narrative','tls.interaction','tls.expression','tls.timeline')}

    def context_generation(self,scope):
        """Opaque native context revision for delayed, host-owned candidates.

        This contains ownership/version markers, never memory text. Presence
        rendering has its own event-loop snapshot because collectors are not
        thread-safe and cannot run in a journal transaction worker.
        """
        try:
            scope=private_scope(scope)
            if not self._permission(scope,'context.read'):return None
            versions=self._context_generations(scope)
            if versions['tls.memory'] is None or not self._permission(scope,'context.read'):
                return None
            return ('tls.unified.context',id(self),versions)
        except (PermissionError,ValueError,RuntimeError,sqlite3.Error):
            return None

    def _fragment_authorized(self,scope,fragment,generations):
        if not self._permission(scope,'context.read'):
            return False
        if fragment.source not in generations:
            return True  # Trusted host-staged material retains its existing gate.
        generation=generations[fragment.source]
        return generation is not None and self._source_generation(scope,fragment.source)==generation

    async def contributions(self, scope, *, query=''):
        if not self._permission(scope, 'context.read'):
            return []
        generations=self._context_generations(scope)
        result = await self.capabilities.call('tls.narrative.context', {'query': query[:2000]}, scope=scope)
        fragments = []
        if result.get('ok') is True:
            value = result.get('data', {})
            for section in value.get('sections', [])[:8]:
                try:
                    fragments.append(ContextFragment(
                        'narrative.' + str(section['id']), section['text'], section['evidence_kind'],
                        'tls.narrative', priority=65, expires_at=section.get('expires_at')))
                except (KeyError, TypeError, ValueError):
                    self.metrics['provider_errors'] += 1
        elif result.get('state') not in {'denied', 'disabled'}:
            self.metrics['provider_errors'] += 1
        strategy = await self.capabilities.call('tls.interaction.strategy', {}, scope=scope)
        if strategy.get('ok'):
            mode = strategy['data']['mode']
            wording = {'deep': '适合深入讨论，维持既有人格与观点。',
                'rp': '延续当前明确的虚构情境，遵守角色知识边界。',
                'continue_plot': '接续已保存的剧情与未完成线索，不虚构现实经历。',
                'share': '可围绕已确认的共同话题简短分享；主动发送仍受统一调度限制。',
                'playful': '可轻松互动，尊重明确偏好与现有人格。',
                'quiet': '允许保持安静，不催促、不用内疚或关系威胁维持交流。'}.get(mode)
            if wording:
                fragments.append(ContextFragment('interaction.strategy', wording,
                    'setting', 'tls.interaction', priority=70))
        mc_provider=getattr(getattr(self.runtime,'memory',None),'mc_context_provider',None)
        fragments.extend(await self._private_contributions(scope,query=query,kind='continuity',max_chars=650,
            mode='all' if mc_provider is not None else 'core_only'))
        fragments.extend(await self._memory_contributions(scope, query=query))
        fragments.extend(await self._feature_contributions(scope, query=query))
        fragments.extend(await self._expression_contributions(scope))
        fragments.extend(await self._timeline_contributions(scope, query=query))
        # An earlier source may have been revoked/disabled while a different
        # optional provider awaited. Do not return those stale private records
        # even to callers which only preview contributions without inject().
        return [f for f in fragments if self._fragment_authorized(scope,f,generations)]

    def _timeline_generation(self, scope):
        service = getattr(self.runtime, 'shared_timeline', None)
        if (not isinstance(service, NativeSharedTimeline)
                or service.store is not getattr(getattr(self.runtime, 'memory', None), 'store', None)
                or not self._permission(scope, 'context.read') or not self._permission(scope, 'memory.read')):
            return None
        for row in self.capabilities.describe():
            if row['capability_id'] == 'tls.timeline.context' and row['enabled'] and row['health'] not in {'closed', 'disabled', 'dependency_unavailable'}:
                try:
                    return (row['generation'], service.context_generation(scope))
                except (PermissionError, ValueError, RuntimeError, sqlite3.Error):
                    return None
        return None

    async def _timeline_contributions(self, scope, *, query):
        generation = self._timeline_generation(scope)
        if generation is None:
            return []
        try:
            result = await self.runtime._bounded(self.capabilities.call('tls.timeline.context',
                {'query': query[:2000]}, scope=scope))
            if self._timeline_generation(scope) != generation or not result.get('ok'):
                return []
            return [ContextFragment(section['id'], section['text'], 'user_reported',
                'tls.timeline', priority=78-index, expires_at=section['expires_at'],
                content_key=section['content_key'])
                for index, section in enumerate(result['data'].get('sections', [])[:4])]
        except (TimeoutError, PermissionError, TypeError, ValueError, RuntimeError, KeyError, sqlite3.Error):
            self.metrics['provider_errors'] += 1
            return []

    def _expression_generation(self,scope):
        learner=getattr(self.runtime,'expression_learning',None)
        if learner is None or not self._permission(scope,'context.read'):
            return None
        try:return learner.generation(scope)
        except (PermissionError,ValueError,RuntimeError):return None

    async def _expression_contributions(self,scope):
        generation=self._expression_generation(scope)
        if generation is None:return []
        try:
            material=await self.runtime._bounded(asyncio.to_thread(
                self.runtime.expression_learning.context,scope,max_chars=300))
            if generation!=self._expression_generation(scope) or not material['text']:
                return []
            return [ContextFragment('expression.preferences',material['text'],
                'user_reported','tls.expression',priority=92)]
        except (TimeoutError,PermissionError,ValueError,RuntimeError,KeyError):
            self.metrics['provider_errors']+=1
            return []

    def _memory_generation(self, scope):
        memory = getattr(self.runtime, 'memory', None)
        if getattr(memory, 'backend', None) == 'native' and self._permission(scope, 'memory.read'):
            return memory.context_generation(scope)
        if self.memory_policy is None or not self._permission(scope, 'memory.read'):
            return None
        try:
            row = self.memory_policy.snapshot(scope)
            if row.get('mode') == 'tls' and not row.get('transitioning') and not self.memory_policy._closed:
                return row['generation']
        except (ValueError, TypeError, RuntimeError):
            pass
        return None

    def _feature_generation(self, scope):
        if (self.feature_policy is None or not self._permission(scope, 'context.read')
                or not self._permission(scope, 'context.feature.read')):
            return None
        memory = self._memory_generation(scope)
        if memory is None:
            return None
        for row in self.capabilities.describe():
            if row['capability_id'] == 'tls.feature.context':
                if row['enabled'] and row['health'] not in {'closed', 'disabled', 'dependency_unavailable'}:
                    reader=getattr(getattr(self.runtime,'memory',None),'context_material_generation',None)
                    material=reader(scope) if callable(reader) else memory
                    return (memory, row['generation'],material) if material is not None else None
        return None

    async def _feature_contributions(self, scope, *, query, kind='continuity', max_chars=700):
        generation = self._feature_generation(scope)
        if generation is None:
            return []
        try:
            result = await self.runtime._bounded(self.capabilities.call('tls.feature.context',
                dict(query=query[:2000], kind=kind, max_chars=max_chars), scope=scope))
            if self._feature_generation(scope) != generation or not result.get('ok'):
                return []
            return [ContextFragment(section['id'], section['text'], section['evidence_kind'],
                    'tls.feature', priority=71, expires_at=section.get('expires_at'))
                for section in result['data'].get('sections', [])[:8]]
        except (TimeoutError, TypeError, ValueError, RuntimeError, KeyError):
            self.metrics['provider_errors'] += 1
            return []

    async def compose_feature_context(self, scope, *, query, kind, max_chars=900):
        """Material for an existing PC generation, never another LLM/send call.

        Uses the same typed assembler and ownership gates as the inbound outlet.
        No rendered cache or alternate memory writer is created.
        """
        if (not isinstance(query, str) or len(query) > 2000 or not isinstance(kind, str)
                or not 0 < len(kind) <= 64 or type(max_chars) is not int or not 160 <= max_chars <= 2400):
            return ''
        generation = self._composition_generation(scope)
        if generation is None:
            return ''
        fragments = await self._feature_contributions(scope, query=query, kind=kind, max_chars=max_chars)
        fragments.extend(await self._private_contributions(scope,query=query,kind=kind,max_chars=min(max_chars,900)))
        fragments.extend(await self._timeline_contributions(scope, query=query))
        if self._composition_generation(scope) != generation:
            return ''
        assembler = ContextAssembler(authorize=lambda s: self._composition_generation(s) == generation,
            max_chars=min(max_chars, self.assembler.max_chars), clock=self.clock)
        try:
            material = assembler.compose(scope, fragments)
            return material['text'] if self._composition_generation(scope) == generation else ''
        finally:
            assembler.close()

    def _private_generation(self,scope):
        if (self.private_memory_policy is None or not self._permission(scope,'context.read')
                or not self._permission(scope,'context.feature.read')
                or not self._permission(scope,'context.private.read')):
            return None
        memory=self._memory_generation(scope)
        if memory is None:
            return None
        for entry in self.capabilities.describe():
            if entry['capability_id']=='tls.private_memory.context':
                if entry['enabled'] and entry['health'] not in {'closed','disabled','dependency_unavailable'}:
                    return (memory,entry['generation'])
        return None

    def _composition_generation(self,scope):
        feature,private,timeline=self._feature_generation(scope),self._private_generation(scope),self._timeline_generation(scope)
        return (feature,private,timeline) if any(value is not None for value in (feature,private,timeline)) else None

    async def _private_contributions(self,scope,*,query,kind,max_chars,mode='all'):
        generation=self._private_generation(scope)
        if generation is None:
            return []
        try:
            call=self.capabilities.call('tls.private_memory.context',
                dict(query=query[:2000],kind=kind,max_chars=max_chars,mode=mode),scope=scope)
            if getattr(getattr(self.runtime,'memory',None),'mc_context_provider',None)is not None:
                # The sealed SDK selected-Persona proof belongs to this Task.
                # timeout bounds the await without minting a child-task grant.
                async with asyncio.timeout(self.runtime.operation_timeout):response=await call
            else:response=await self.runtime._bounded(call)
            if self._private_generation(scope)!=generation or not response.get('ok'):
                return []
            return [ContextFragment(section['id'],section['text'],section['evidence_kind'],
                'tls.private_memory',priority=90-index,expires_at=section.get('expires_at'),
                content_key=section.get('content_key'))
                for index,section in enumerate(response['data'].get('sections',[])[:6])]
        except (TimeoutError,TypeError,ValueError,RuntimeError,KeyError):
            self.metrics['provider_errors']+=1
            return []

    async def _memory_contributions(self, scope, *, query):
        # An explicit durable transfer is required. Legacy/shadow never creates
        # a second context outlet or a second retrieval request here.
        generation = self._memory_generation(scope)
        if generation is None or not query.strip():
            return []
        try:
            # Reuse the runtime's bounded pending set and deadline. wait_for
            # alone can hang while an optional adapter suppresses cancellation.
            # Late results retain a bounded slot and can never emit context.
            call=self.capabilities.call('tls.memory.recall', {'query': query[:2000]}, scope=scope)
            if getattr(getattr(self.runtime,'memory',None),'mc_context_provider',None)is not None:
                async with asyncio.timeout(self.runtime.operation_timeout):response=await call
            else:response = await self.runtime._bounded(call)
            if self._memory_generation(scope) != generation or not response.get('ok'):
                return []
            value = response.get('data', {})
            if value.get('ok') is not True:
                return []  # Missing/failed retrieval never falls back to an old composer.
            rows = value.get('memories', [])
            now = self.clock()
            material = self._memory_selection.select(rows, scope=scope,
                query=query[:2000], now=now, max_chars=900)
            if getattr(getattr(self.runtime, 'memory', None), 'backend', None) == 'native':
                ids = material['selected_ids']
            else:
                ids = self.memory_policy.evaluate_ids(scope, rows, query=query[:2000],
                    now=now, max_chars=900, legacy=lambda **_: [],
                    guard=lambda: self._memory_generation(scope) == generation)
            if self._memory_generation(scope) != generation:
                return []
            # IDs are returned separately from rendered sections. A race that
            # releases ownership yields no material rather than legacy calls.
            if ids != material['selected_ids']:
                return []
            controller=getattr(getattr(self.runtime,'memory',None),'mc_context_runtime',None)
            if controller is not None:controller.record_selection(scope,material)
            keys={}
            for row in rows:
                candidate,_=self._memory_selection._candidate(row,scope,now)
                if candidate is not None:
                    keys.setdefault(candidate.identity,set()).add(content_fingerprint(candidate.content))
            return [ContextFragment(section['id'], section['text'],
                section['evidence_kind'], 'tls.memory', priority=72,
                expires_at=section['expires_at'],content_key=next(iter(keys[identity])))
                for identity,section in zip(material['selected_ids'],material['sections'])
                if len(keys.get(identity,set()))==1]
        except (TimeoutError, TypeError, ValueError, RuntimeError, KeyError):
            self.metrics['provider_errors'] += 1
            return []

    def begin_request(self, req, scope):
        return self.assembler.begin(req, scope)

    def stage(self, req, scope, text, domain):
        if not self._permission(scope, 'context.read'):
            return False
        return self.assembler.stage(req, scope, ContextFragment(domain, text,
            'roleplay_event', 'existing.virtual_engine', priority=80, expires_at=self.clock() + 180))

    def _music_snapshot(self, scope, reference, presence, library):
        """Pure owning-loop proof; it never reads the music database."""
        if (reference is None or self._music_reference is not reference
                or self.presence is not presence or reference.library is not library
                or getattr(self.runtime, 'music_library', None) is not library
                or not self._permission(scope, 'context.read')
                or not self._permission(scope, 'presence.read')):
            return None
        try:
            snapshot = presence.read(scope, 'music', now=self.clock())
            return snapshot if reference.snapshot_token(scope, snapshot) is not None else None
        except Exception:
            return None

    async def inject(self, req, scope, *, query, environment_block, text_part):
        self.metrics['context_calls'] += 1
        generations=self._context_generations(scope)
        state = getattr(req, '_tls_context_state', None)
        if (not isinstance(state, dict) or state.get('owner') is not self.assembler
                or state.get('scope') != scope_key(private_scope(scope))):
            state = self.assembler.begin(req, scope)
        if not self._permission(scope, 'context.read'):
            self.assembler._clear_owned(req, expected_state=state)
            return {'text': '', 'selected': [], 'chars': 0}
        reference, music_presence = self._music_reference, self.presence
        music_library = getattr(self.runtime, 'music_library', None)
        music_snapshot = self._music_snapshot(scope, reference, music_presence, music_library)
        music_token = reference.snapshot_token(scope, music_snapshot) if music_snapshot is not None else None
        fragments = self.assembler.staged(req, scope)
        if environment_block and self._permission(scope, 'presence.read'):
            # Presence wording already distinguishes fresh observations,
            # unknown music, server time and inferred activity explicitly.
            fragments.append(ContextFragment('presence.context', environment_block,
                'setting', 'presence.policy', priority=95, expires_at=self.clock() + 2))
        fragments.extend(await self.contributions(scope, query=query))
        music = None
        if music_token is not None:
            current_snapshot = self._music_snapshot(scope, reference, music_presence, music_library)
            if reference.snapshot_token(scope, current_snapshot) == music_token:
                try:
                    # This is the final await in ordinary injection. All
                    # library generations/matching run on the existing worker,
                    # after other providers could edit through another DB
                    # connection. No music SQL is added to synchronous final
                    # checks. An external write after this worker's last read
                    # remains a validation window, not a cross-store lock.
                    candidate = await self.runtime._bounded(asyncio.to_thread(reference.build,
                        scope, current_snapshot, query=query, max_chars=min(900, self.assembler.max_chars)))
                    if (type(candidate) is MusicReferenceContribution
                            and reference.snapshot_token(scope, self._music_snapshot(
                                scope, reference, music_presence, music_library)) == candidate.music_token):
                        music = candidate
                        fragments.append(music.fragment)
                except (TimeoutError, TypeError, ValueError, RuntimeError, KeyError):
                    self.metrics['provider_errors'] += 1
        if getattr(req, '_tls_context_state', None) is not state:
            return {'text': '', 'selected': [], 'chars': 0}
        if not self._permission(scope, 'context.read'):
            self.assembler._clear_owned(req, expected_state=state)
            return {'text': '', 'selected': [], 'chars': 0}
        if not self._permission(scope, 'presence.read'):
            fragments = [f for f in fragments if f.fragment_id != 'presence.context']
        selected = sorted(fragments, key=lambda f: (-f.priority, f.fragment_id))[:self.assembler.max_fragments]
        def final_check(ids):
            by_id = {f.fragment_id: f for f in selected}
            def allowed(identity):
                fragment = by_id[identity]
                if identity == 'presence.context':
                    return self._permission(scope, 'presence.read')
                if fragment.source == 'tls.music.library.reference':
                    return (music is not None and fragment is music.fragment
                        and reference.snapshot_token(scope, self._music_snapshot(
                            scope, reference, music_presence, music_library)) == music.music_token)
                return self._fragment_authorized(scope, fragment, generations)
            return all(allowed(identity) for identity in ids)
        material = self.assembler.emit(req, scope, selected, text_part,
            expected_state=state, final_check=final_check)
        controller=getattr(getattr(self.runtime,'memory',None),'mc_context_runtime',None)
        if controller is not None:controller.record_emitted(req,scope,material)
        current = getattr(req, '_tls_context_state', None)
        if current is state and state.get('owner') is self.assembler:
            state['environment_projection'] = environment_block if 'presence.context' in material['selected'] else ''
        return material

    def stop(self):
        self.active = False
        if self._music_reference is not None:
            self._music_reference.stop()
        if self.memory_policy is not None:
            self.memory_policy.stop()
        self.assembler.close()
        close = getattr(self.capabilities, 'close', None)
        if callable(close):
            close()

    async def close(self):
        self.stop()
        if self.memory_policy is not None:
            await asyncio.to_thread(self.memory_policy.close)

    def diagnostics(self):
        return {'active': self.active, 'environment': self.environment,
                'production_owner': False, 'context': self.assembler.diagnostics(),
                'capabilities': self.capabilities.describe(), 'metrics': dict(self.metrics),
                'memory_backend': getattr(getattr(self.runtime, 'memory', None), 'backend', 'existing_public_bridge'),
                'scheduler': 'existing_stage4_native',
                'persona': 'existing_system_prompt_unchanged'}
