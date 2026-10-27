"""TLS-owned memory operations; no legacy plugin discovery or model calls."""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
import unicodedata

from .memory_context import NativeMemoryContextPolicy, _SECRET
from .models import EvidenceKind, Observation, private_scope


class NativeMemoryAdapter:
    backend = 'native'

    def __init__(self, store, *, authorize=None, clock=time.time):
        self.store, self.clock = store, clock
        self._authorize = authorize or (lambda scope: True)
        self.active = True
        self.generation = 1
        self.metrics = dict(writes=0, recalls=0, captured=0, rejected=0)
        self._selection = NativeMemoryContextPolicy()
        self._material_reader = self._material_generation = None
        self.mc_context_provider = None  # Existing MC data, selected only by TLS.
        self.mc_context_runtime = None  # Same request owner; not a new grant.
        self.profile_candidates = None  # Same SQLite authority, typed review state.

    def bind_context_material(self,reader,generation):
        if not callable(reader) or not callable(generation) or self._material_reader is not None:
            raise ValueError('one owned native material source required')
        self._material_reader,self._material_generation=reader,generation
        self.generation+=1

    def context_material_generation(self,scope):
        memory=self.context_generation(scope)
        if memory is None:return None
        if self._material_generation is None:return memory
        try:
            token=self._material_generation(scope)
            return (memory,token) if token is not None and self.allowed(scope) else None
        except Exception:return None

    def allowed(self, scope):
        return self.active and self._authorize(private_scope(scope)) is True

    def context_generation(self, scope):
        """Opaque current-context token, or None when this source is unavailable.

        Lifecycle epoch alone cannot fence WebUI/direct store changes while a
        request awaits another provider. Include the durable scoped history
        marker and adapter/store instance bindings, and repeat authority after
        reading it. Callers must discard staged fragments when tokens differ;
        None is never permission to reuse an older token or a legacy fallback.
        No scope identifier, path or memory content is included in this token.
        """
        try:
            scope = private_scope(scope)
            store, generation = self.store, self.generation
            if not self.allowed(scope):
                return None
            data = store.data_generation(scope)
            if (self.store is not store or self.generation != generation or not self.allowed(scope)):
                return None
            provider = self.mc_context_provider
            mc_token = provider.current_token(scope) if provider is not None else None
            if self.mc_context_provider is not provider or not self.allowed(scope):
                return None
            base = ('native_memory', id(self), generation, id(store), data)
            profiles=self.profile_candidates
            if profiles is not None:
                token=profiles.data_generation(scope)
                if token is None or self.profile_candidates is not profiles or not self.allowed(scope):return None
                base=(*base,('native_profiles',id(profiles),token))
            return base if provider is None else (*base, mc_token)
        except Exception:
            # A closed/replaced store or late permission failure must fence
            # this source rather than preserve already staged private text.
            return None

    async def _operation(self, scope, method, *args, **kwargs):
        scope = private_scope(scope)
        if not self.allowed(scope):
            raise PermissionError('native memory scope unavailable')
        result = await asyncio.to_thread(method, scope, *args, **kwargs)
        if not self.allowed(scope):
            raise PermissionError('native memory scope changed')
        return result

    async def write(self, observation, *, authorize=None):
        if not isinstance(observation, Observation):
            return {'ok': False, 'state': 'rejected', 'error_code': 'observation_required'}
        scope = private_scope(observation.scope)
        if authorize is not None:
            value = authorize()
            if asyncio.iscoroutine(value):
                value = await value
            if value is not True:
                return {'ok': False, 'state': 'denied'}
        if not observation.valid_at(self.clock()):
            return {'ok': False, 'state': 'rejected', 'error_code': 'observation_not_fresh'}
        payload = observation.payload
        content = next((payload.get(k) for k in ('summary', 'content', 'text')
                        if isinstance(payload.get(k), str) and payload[k].strip()), '') if isinstance(payload, dict) else ''
        if not content or _SECRET.search(content):
            return {'ok': False, 'state': 'rejected', 'error_code': 'invalid_memory_content'}
        row = await self._operation(scope, self.store.write, content,
            source_id=observation.source_id, event_id=observation.observation_id,
            evidence_kind=observation.evidence_kind.value,
            memory_type='catalog_discovery' if observation.observation_type == 'music.catalog_reference' else 'living_observation',
            occurred_at=observation.observed_at, expires_at=observation.expires_at,
            confidence=.8 if observation.confidence is None else observation.confidence,
            importance={'normal': .4, 'important': .7, 'critical': .9}[observation.importance],
            metadata={'observation_type': observation.observation_type,
                      'provenance': observation.provenance,
                      **({'claim_domain': 'system_catalog_metadata'} if observation.observation_type == 'music.catalog_reference' else {})})
        self.metrics['writes'] += 1
        return {'ok': True, 'state': 'stored', 'memory_id': row['id'], 'revision': row['revision']}

    async def recall(self, query, *, scope, event=None, top_k=5):
        limit = min(max(int(top_k), 1), 10)
        rows = await self._operation(scope, self.store.search, query, limit=32,
                                     evidence_kinds=('user_reported', 'real_observation'))
        provider = self.mc_context_provider
        token = provider.current_token(scope) if provider is not None else None
        if token is not None:
            material = await provider.materials(scope, limit=32, query=query)
            if (self.mc_context_provider is provider and provider.current_token(scope) == token
                    and self.allowed(scope) and material.get('ok') is True):
                extra = material.get('memory_items', [])
                if isinstance(extra, list) and extra:
                    rows = rows + extra[:32]
                    def score(row):
                        value = row.get('score', 0)
                        return float(value) if type(value) in (int, float) and math.isfinite(value) else 0.0
                    rows.sort(key=score, reverse=True)
        rows=await self._with_profiles(scope,rows,query=query,limit=32)
        normalize = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
        now = self.clock()
        rows = [row for row in rows if normalize(row['content']) != normalize(query)
                and self._selection._candidate(row, private_scope(scope), now)[0] is not None][:limit]
        self.metrics['recalls'] += 1
        return {'ok': True, 'state': 'ready', 'memories': rows, 'backend': self.backend}

    async def _with_profiles(self,scope,rows,*,query='',limit=64):
        profiles=self.profile_candidates
        if profiles is None:return rows
        if profiles.store is not self.store:raise PermissionError('profile authority differs')
        def read(current_scope):
            with self.store.transaction():
                return (profiles.search(current_scope,query,limit=min(limit,64)),
                    profiles.active_single_dimensions(current_scope))
        extra,dimensions=await self._operation(scope,read)
        if self.profile_candidates is not profiles or not profiles.active:
            raise PermissionError('native profile source changed')
        # Only already-authorized user-profile material in this full scope is
        # shadowed. Old history remains in its original store; pending native
        # candidates never suppress it or become context themselves.
        rows=[row for row in rows if not (row.get('memory_type') in
            {'user_profile','user_preference','user_habit'}
            and row.get('source_id')!='tls.chat.profile_candidates'
            and isinstance(row.get('metadata'),dict)
            and row['metadata'].get('profile_dimension') in dimensions)]
        result=extra+rows
        if query:
            result.sort(key=lambda row:float(row.get('score',0)) if type(row.get('score',0)) in (int,float)
                and math.isfinite(row.get('score',0)) else 0,reverse=True)
        return result[:min(limit,64)]

    async def context_material(self, *, scope, limit=64):
        generation=self.context_material_generation(scope)
        if generation is None:return {'ok':False,'items':[],'state':'native_material_unavailable'}
        material=[]
        if self._material_reader is not None:
            material=await asyncio.to_thread(self._material_reader,scope,limit=min(limit,64))
        rows = await self._operation(scope, self.store.list, limit=min(limit, 64))
        rows=await self._with_profiles(scope,rows,limit=min(limit,64))
        if generation!=self.context_material_generation(scope):
            return {'ok':False,'items':[],'state':'native_material_changed'}
        return {'ok': True, 'items': (material+rows)[:min(limit,64)], 'backend': self.backend}

    async def private_context_material(self, *, scope, limit=64):
        limit = min(limit, 64)
        provider = self.mc_context_provider
        token = provider.current_token(scope) if provider is not None else None
        rows = await self._operation(scope, self.store.read_private_context, limit=limit)
        if token is not None:
            material = await provider.materials(scope, limit=limit)
            if (self.mc_context_provider is provider and provider.current_token(scope) == token
                    and self.allowed(scope) and material.get('ok') is True):
                extra = material.get('private_items', [])
                if isinstance(extra, list) and extra:
                    # Keep both sources represented; the existing private policy
                    # owns final relevance, provenance, dedup and presentation.
                    native_limit = max(1, limit // 2)
                    rows = rows[:native_limit] + extra[:limit-native_limit]
        rows=await self._with_profiles(scope,rows,limit=limit)
        return {'ok': True, 'items': rows, 'backend': self.backend}

    async def correct(self, memory_id, content, *, scope, expected_revision=None):
        if expected_revision is None:
            raise ValueError('expected_revision is required')
        row = await self._operation(scope, self.store.correct, memory_id, content,
                                    expected_revision=expected_revision)
        return {'ok': True, 'state': 'corrected', 'memory': row}

    async def delete(self, memory_id, *, scope, expected_revision=None):
        if expected_revision is None:
            raise ValueError('expected_revision is required')
        row = await self._operation(scope, self.store.delete, memory_id,
                                    expected_revision=expected_revision)
        return {'ok': True, 'state': 'deleted', 'memory': row}

    async def capture_event(self, event, scope):
        """Retain user utterances as utterances, never inferred personal facts."""
        if getattr(event, 'private_companion_proactive_framework', False):
            return {'ok': False, 'state': 'synthetic_event'}
        scope = private_scope(scope)
        if str(event.get_sender_id() or '') != scope['user_id'] or str(event.get_self_id() or '') != scope['bot_id']:
            return {'ok': False, 'state': 'identity_mismatch'}
        if str(getattr(event, 'unified_msg_origin', '')) != scope['session_id']:
            return {'ok': False, 'state': 'identity_mismatch'}
        text = getattr(event, 'message_str', '')
        identity = str(getattr(getattr(event, 'message_obj', None), 'message_id', '') or '')
        if (not isinstance(text, str) or not text.strip() or len(text) > 6000
                or text.lstrip().startswith('/') or not identity or identity == '0' or _SECRET.search(text)):
            self.metrics['rejected'] += 1
            return {'ok': False, 'state': 'not_a_retainable_utterance'}
        row = await self._operation(scope, self.store.write, text.strip(), source_id='tls.chat.user',
            evidence_kind=EvidenceKind.USER_REPORTED.value, memory_type='utterance',
            event_id='chat.' + hashlib.sha256(identity.encode()).hexdigest(),
            confidence=1., importance=.3,
            metadata={'capture': 'user_utterance', 'message_id': identity})
        self.metrics['captured'] += 1
        return {'ok': True, 'state': 'deleted' if row.get('lifecycle') == 'deleted' else 'stored', 'memory_id': row['id']}

    async def fragments(self, scope, query, *, max_chars=900):
        from .context_engine import ContextFragment
        if not query.strip():
            return []
        recalled = await self.recall(query[:2000], scope=scope, top_k=8)
        result = self._selection.select(recalled['memories'], scope=scope, query=query[:2000],
                                        now=self.clock(), max_chars=max_chars)
        return [ContextFragment(item['id'], item['text'], item['evidence_kind'], 'tls.memory',
                                priority=70, expires_at=item.get('expires_at'))
                for item in result['sections']]

    def stop(self):
        self.active = False
        self.generation += 1
        if self.profile_candidates is not None:self.profile_candidates.close()

    async def close(self):
        self.stop()
        await asyncio.to_thread(self.store.close)

