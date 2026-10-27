"""MC storage adapter and TLS final selection, without a new owner or writer.

The Host supplies its existing selected-persona/read-ACL/context-owner proofs.
Tokens below are labels for those proofs, never grants minted by this module.
``binding_for`` and ``authorize`` run only on the owning event loop;
``authorize_read`` MUST be pure/thread-safe and must not call capture.current.

All original MC types are read from the existing table in one bounded RO
snapshot. R42's audited schema, JSON and byte-budget helpers are reused. No
legacy retriever/composer/model, index, ingestion task or database is created.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from types import MappingProxyType

from . import native_mc_context_material_reader as raw
from .context_engine import ContextFragment, content_fingerprint
from .memory_context import NativeMemoryContextPolicy
from .models import private_scope
from .native_memory import _normal, _tokens
from .private_memory_context import NativePrivateMemoryContextPolicy


PRIVATE_TYPES = frozenset(raw._TYPES)
MAX_ROWS, MAX_BYTES = 64, 48000


class CompanionTakeoverError(ValueError):
    """Fixed error code; no raw database path, identity or content."""


def _failure(state):
    return dict(ok=False,state=state,items=[],private_items=[],memory_items=[],mc_revision=None,writes=0)


def read_mc_private_recall_switch(db_path, mc_scope, *, configured_recall_enabled):
    """Read the original own-window switch, not an ACL sharing grant.

    ``window_id`` is the existing private SessionContext.current_target_id,
    i.e. its exact user_id. No cross-window ACL allow rule is introduced.
    Persona existence/selected proof and Host scope remain separate checks.
    """
    result=dict(known=False,recall_enabled=False,override=None,revision=None,grants_authority=False)
    if type(configured_recall_enabled) is not bool:
        return result
    try:
        scope=raw._scope(dict(mc_scope));path=raw._database(db_path)
        started=time.monotonic();steps=0
        def progress():
            nonlocal steps
            steps+=1000
            return int(steps>100000 or time.monotonic()-started>.25)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,
                     timeout=.2,isolation_level=None)) as conn:
            conn.set_progress_handler(progress,1000)
            conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
            try:
                kind=conn.execute("SELECT type FROM sqlite_master WHERE name='memory_acl_policies'").fetchall()
                if kind != [('table',)]:
                    return result
                revision=_revision(conn)
                rows=conn.execute('SELECT recall_enabled FROM memory_acl_policies '
                    "WHERE window_scope='private' AND window_id=? LIMIT 2",(scope['user_id'],)).fetchall()
                if len(rows)>1 or rows and (rows[0][0] is not None
                        and (type(rows[0][0]) is not int or rows[0][0] not in (0,1))):
                    return result
                override=rows[0][0] if rows else None
                return dict(known=True,recall_enabled=configured_recall_enabled if override is None else override==1,
                            override=override,revision=revision,grants_authority=False)
            finally:
                conn.rollback();conn.set_progress_handler(None,0)
    except (ValueError,TypeError,sqlite3.Error,OSError):
        return result


@dataclass(frozen=True)
class MCContextBinding:
    tls_scope: object
    mc_scope: object
    selected_token: object
    owner_token: object
    read_revision: int | None = None

    def __post_init__(self):
        tls = private_scope(dict(self.tls_scope))
        mc = raw._scope(dict(self.mc_scope))
        if any(tls[name] != mc[name] for name in ('platform', 'bot_id', 'user_id', 'session_id')):
            raise CompanionTakeoverError('mc_identity_binding_mismatch')
        if self.selected_token is None or self.owner_token is None:
            raise CompanionTakeoverError('explicit_selection_and_context_owner_required')
        if self.read_revision is not None and (type(self.read_revision)is not int or self.read_revision<0):
            raise CompanionTakeoverError('invalid_mc_read_revision')
        object.__setattr__(self, 'tls_scope', MappingProxyType(tls))
        object.__setattr__(self, 'mc_scope', MappingProxyType(mc))


@dataclass(frozen=True,eq=False)
class MCContextFeedback:
    """Opaque, request-local candidate; creating one performs no write.

    The Host supplies actual policy ``(selected_id, section_id)`` pairs, then
    confirms only after that request emitted those sections and completed its
    LLM response. This object is not a new permission or a durable receipt.
    """
    _issuer: object
    _state: object
    _pairs: tuple


def _revision(connection):
    rows = connection.execute('SELECT singleton,revision FROM retrieval_revision LIMIT 2').fetchall()
    if (len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] < 0):
        raise CompanionTakeoverError('mc_revision_unavailable')
    return rows[0][1]


def _placeholder(actor):
    # The exact optional EntityRef shape already accepted by TLS's policy.
    return (actor['kind'] == 'user' and actor['id'] == '' and actor['name'] == ''
            and actor['role'] in ('', 'unknown'))


def _material(row, scope):
    if any(type(row[name]) is not str for name in raw._READ if name not in ('confidence', 'importance')):
        raise CompanionTakeoverError('invalid_mc_field')
    metadata, tags = raw._json(row['metadata'], dict), raw._json(row['tags'], list)
    if metadata.get('owner_bot_id') != scope['bot_id'] or metadata.get('persona_id') != scope['persona_id']:
        return None
    if len(tags) > 64 or any(type(tag) is not str or len(tag) > 80 for tag in tags):
        raise CompanionTakeoverError('invalid_mc_tags')
    actors = [{key: row[name+'_'+key] for key in ('kind', 'id', 'name', 'role')}
              for name in ('subject', 'object')]
    for actor in actors:
        if _placeholder(actor):
            continue
        if (actor['kind'] not in ('user', 'bot')
                or actor['id'] != scope['user_id' if actor['kind'] == 'user' else 'bot_id']):
            return None
    if row['scope'] == 'global':
        if (row['memory_type'] != 'core_memory' or metadata.get('core_scope') != 'global'
                or metadata.get('target_id') not in ('', None)
                or any(actor['kind'] != 'bot' for actor in actors)):
            return None
    elif row['session_id'] != scope['session_id']:
        if (row['session_id'] != '' or row['memory_type'] != 'core_memory'
                or metadata.get('core_scope') != 'private' or metadata.get('target_id') != scope['user_id']):
            return None
    safe = {}
    for name in raw._METADATA:
        if name in metadata:
            value = metadata[name]
            if type(value) not in (str, int, float, bool) or type(value) is float and not math.isfinite(value):
                raise CompanionTakeoverError('invalid_mc_metadata')
            safe[name] = value
    item = {name: row[name] for name in raw._PUBLIC}
    for name in ('confidence', 'importance'):
        value = row[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise CompanionTakeoverError('invalid_mc_score')
        item[name] = float(value)
    if not item['id'] or len(item['id']) > 160:
        raise CompanionTakeoverError('invalid_mc_record_id')
    item.update(persona_id=scope['persona_id'], subject=actors[0], object=actors[1],
                tags=tags, metadata=safe, private_context_metadata=dict(safe))
    if 'mention_policy' in safe:
        item['mention_policy'] = safe['mention_policy']
    return item


class NativeCompanionTakeoverProvider:
    """No controller is installed here. Denial never invokes legacy compose."""

    def __init__(self, db_path, *, binding_for, authorize, authorize_read,
                 base_materials=None, base_recall=None, clock=time.time, deadline_seconds=.35):
        if (not all(callable(x) for x in (binding_for, authorize, authorize_read, clock))
                or type(deadline_seconds) not in (int, float) or not .01 <= deadline_seconds <= 2):
            raise CompanionTakeoverError('explicit_read_callbacks_required')
        self.path = raw._database(db_path)
        self.binding_for, self.authorize, self.authorize_read = binding_for, authorize, authorize_read
        self.base_materials, self.base_recall, self.clock = base_materials, base_recall, clock
        self.deadline = float(deadline_seconds)
        self._closed = threading.Event()
        self._epoch = 1
        # Bounded request-local origins/consumption. No new DB or retry queue.
        # A process crash cannot provide durable exactly-once bookkeeping.
        self._feedback = {}
        self.private_policy = NativePrivateMemoryContextPolicy()
        self.memory_policy = NativeMemoryContextPolicy()

    def close(self):
        self._closed.set()
        self._epoch += 1
        self._feedback.clear()

    def current(self, binding):
        try:
            return (not self._closed.is_set() and type(binding) is MCContextBinding
                    and self.authorize(binding) is True and not self._closed.is_set())
        except Exception:
            return False

    def _binding(self, scope):
        scope = private_scope(dict(scope))
        binding = self.binding_for(scope)
        if (type(binding) is not MCContextBinding or dict(binding.tls_scope) != scope
                or not self.current(binding)):
            raise CompanionTakeoverError('mc_context_not_authorized')
        return binding

    def _read_allowed(self, binding):
        if (self._closed.is_set()
                or self.authorize_read(binding, dict(binding.mc_scope)) is not True
                or self._closed.is_set()):
            raise CompanionTakeoverError('mc_read_authority_changed')

    def _revision_now(self, binding):
        self._read_allowed(binding)
        path = raw._database(self.path)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True,
                     timeout=min(self.deadline, .2), isolation_level=None)) as conn:
            conn.execute('PRAGMA query_only=ON')
            result = _revision(conn)
        self._read_allowed(binding)
        return result

    def generation(self, scope, *, binding=None):
        """Host must include this token in final context freshness checks."""
        try:
            binding = self._binding(scope) if binding is None else binding
            if dict(binding.tls_scope) != private_scope(dict(scope)) or not self.current(binding):
                return None
            revision=self._revision_now(binding)
            if binding.read_revision is not None and revision!=binding.read_revision:
                return None
            return (self._epoch, binding.selected_token, binding.owner_token, revision)
        except Exception:
            return None

    def current_token(self, scope):
        return self.generation(scope)

    def revision(self, scope):
        token=self.current_token(scope)
        return token[-1] if token is not None else None

    def _read_snapshot(self, binding, query):
        self._read_allowed(binding)
        path, scope = raw._database(self.path), dict(binding.mc_scope)
        identity = path.stat()
        started, steps = time.monotonic(), 0
        def progress():
            nonlocal steps
            steps += 1000
            try:
                self._read_allowed(binding)
                return int(time.monotonic()-started >= self.deadline or steps > 200000)
            except Exception:
                return 1
        terms=_tokens(query)
        if any(not term.startswith('c:') for term in terms):
            terms={term:weight for term,weight in terms.items() if not term.startswith('c:')}
        terms=set(tuple(terms)[:256])
        def lexical_match(content):
            self._read_allowed(binding)
            if time.monotonic()-started >= self.deadline:
                raise CompanionTakeoverError('mc_query_deadline')
            return int(type(content)is str and bool(terms.intersection(_tokens(content))))
        where = ("owner_bot_id=? AND lifecycle NOT IN ('archived','deleted','superseded','quarantined') "
            "AND review_status NOT IN ('pending','rejected') AND validity_status='active' AND ("
            "(scope='private' AND visibility='private_pair' AND platform=? "
            "AND ((subject_kind='user' AND subject_id=?) OR (object_kind='user' AND object_id=?)) "
            "AND (session_id=? OR (memory_type='core_memory' AND session_id=''))) "
            "OR (memory_type='core_memory' AND scope='global' AND visibility='bot_self' AND platform IN ('',?))) "
            "AND (memory_type IN ("+','.join('?' for _ in raw._TYPES)+") OR (?=1 AND CASE "
            "WHEN typeof(content)!='text' THEN 1 WHEN length(content)<=6000 THEN tls_mc_match(content) ELSE 0 END=1))")
        values = (scope['bot_id'],scope['platform'],scope['user_id'],scope['user_id'],scope['session_id'],scope['platform'],
                  *raw._TYPES,int(bool(terms)))
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True,
                     timeout=min(self.deadline,.2), isolation_level=None)) as conn:
            conn.row_factory = sqlite3.Row
            # A connection-local pure reuse of TLS lexical matching; CASE
            # bounds Python-visible generic text before calling the function.
            # No index or function is persisted in the MC database.
            conn.create_function('tls_mc_match',1,lexical_match,deterministic=True)
            conn.set_progress_handler(progress,1000)
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            try:
                raw._schema(conn)
                revision = _revision(conn)
                if binding.read_revision is not None and revision!=binding.read_revision:
                    raise CompanionTakeoverError('mc_read_revision_changed')
                count, _ = raw._preflight(conn,where,values)
                rows = conn.execute('SELECT '+','.join(raw._READ)+' FROM memories WHERE '+where
                    +' ORDER BY id LIMIT 65',values).fetchall()
                if len(rows) != count:
                    raise CompanionTakeoverError('mc_snapshot_changed')
                result = [item for row in rows if (item := _material(row,scope)) is not None]
                if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf8')) > MAX_BYTES:
                    raise CompanionTakeoverError('mc_material_capacity')
                after = raw._database(path).stat()
                if (identity.st_dev,identity.st_ino) != (after.st_dev,after.st_ino):
                    raise CompanionTakeoverError('mc_database_identity_changed')
                self._read_allowed(binding)
                if time.monotonic()-started >= self.deadline:
                    raise CompanionTakeoverError('mc_query_deadline')
                return revision,result
            finally:
                conn.rollback()
                conn.set_progress_handler(None,0)

    @staticmethod
    def _project(rows,binding):
        # This mapping is explicit, live-authorized and in-memory only. Never
        # infer the MC persona from a TLS character or alter its source row.
        result=[]
        for row in rows:
            row=deepcopy(row)
            origin=json.dumps(dict(binding.mc_scope),sort_keys=True)+'\0'+row['id']
            row['id']='mc_'+hashlib.sha256(origin.encode()).hexdigest()
            row['persona_id']=binding.tls_scope['character_id']
            result.append(row)
        return result

    def _remember_projection(self,binding,source,projected):
        key=id(binding)
        state=self._feedback.get(key)
        if state is None or state['binding'] is not binding:
            if len(self._feedback)>=128:
                self._feedback.pop(next(iter(self._feedback)))
            state=dict(binding=binding,epoch=self._epoch,origins={},consumed=set(),tickets={})
            self._feedback[key]=state
        if state['epoch']!=self._epoch:
            raise CompanionTakeoverError('mc_feedback_owner_changed')
        for old,new in zip(source,projected):
            original=old['id']
            # The original service cleans IDs at 120 characters. Do not let a
            # longer identifier be truncated into a different existing row.
            if (type(original)is not str or not original or len(original)>120
                    or re.sub(r'\s+',' ',original.replace('\u3000',' ')).strip()!=original):
                continue
            previous=state['origins'].get(new['id'])
            if previous is not None and previous!=original:
                raise CompanionTakeoverError('mc_feedback_origin_conflict')
            if len(state['origins'])>=MAX_ROWS and new['id'] not in state['origins']:
                raise CompanionTakeoverError('mc_feedback_capacity')
            state['origins'][new['id']]=original

    def feedback_candidates(self,scope,selections,*,binding=None):
        """Bind policy-selected IDs to section IDs, without recording use.

        Pass only the existing policy's aligned selected_ids/sections after
        final filtering, not all raw rows. The final ContextAssembler may
        still drop sections; confirm_feedback intersects its actual IDs.
        Native-only IDs have no MC origin and are deliberately ignored.
        """
        scope=private_scope(dict(scope))
        binding=self._binding(scope) if binding is None else binding
        if self.generation(scope,binding=binding) is None:
            return None
        state=self._feedback.get(id(binding))
        if state is None or state['binding'] is not binding or state['epoch']!=self._epoch:
            return None
        if type(selections) not in (list,tuple) or len(selections)>MAX_ROWS:
            raise CompanionTakeoverError('invalid_mc_feedback_selection')
        pairs=[]
        for pair in selections:
            if (type(pair) not in (list,tuple) or len(pair)!=2
                    or any(type(x)is not str or not x or len(x)>192 for x in pair)):
                raise CompanionTakeoverError('invalid_mc_feedback_selection')
            identity,section=pair
            if identity in state['origins'] and (identity,section) not in pairs:
                pairs.append((identity,section))
        if not pairs:
            return None
        if len(state['tickets'])>=64:
            raise CompanionTakeoverError('mc_feedback_ticket_capacity')
        ticket=MCContextFeedback(self,state,tuple(pairs))
        state['tickets'][id(ticket)]=dict(ticket=ticket,state='candidate')
        return ticket

    def feedback_status(self,ticket):
        if type(ticket)is not MCContextFeedback or ticket._issuer is not self:
            return 'unknown_ticket'
        entry=ticket._state['tickets'].get(id(ticket))
        return entry['state'] if entry is not None and entry['ticket'] is ticket else 'unknown_ticket'

    async def confirm_feedback(self,ticket,*,emitted_ids,service,configured_recall_enabled,p5_snapshot=None):
        """One attempt for actually emitted MC IDs after an LLM response.

        Uses the original service's mark_injected and P5 data adapters only.
        Callback authorization must still prove the bound owner/read scope;
        one original ACL snapshot is read before writing. Its old data revision
        need not remain unchanged after a legitimate concurrent capture. The
        caller supplies the current original private-recall config bool on the
        owning loop, never a guessed default. A failed/cancelled/unknown attempt is
        consumed and never retried here, since a DB commit may have occurred.
        This is per-binding in-process suppression, not crash-proof exactly
        once. The Host must never call this for previews or bridge compose.
        """
        result=dict(ok=False,state='mc_feedback_unavailable',count=0,mark_invoked=False,
                    provenance_invoked=False,retry_safe=False)
        if type(ticket)is not MCContextFeedback or ticket._issuer is not self:
            return result
        if type(configured_recall_enabled)is not bool:
            raise CompanionTakeoverError('invalid_mc_feedback_recall_configuration')
        state=ticket._state;binding=state['binding']
        entry=state['tickets'].get(id(ticket))
        if (entry is None or entry['ticket'] is not ticket
                or self._feedback.get(id(binding)) is not state
                or state['epoch']!=self._epoch or not self.current(binding)):
            return result
        if entry['state']!='candidate':
            return dict(result,ok=entry['state'] in ('recorded','not_emitted_or_already_recorded'),state=entry['state'])
        if (type(emitted_ids) not in (list,tuple) or len(emitted_ids)>128
                or any(type(x)is not str or not x or len(x)>192 for x in emitted_ids)):
            raise CompanionTakeoverError('invalid_mc_emitted_selection')
        try:
            self._read_allowed(binding)
            store=vars(service).get('store')
            if store is None or raw._database(vars(store).get('db_path'))!=self.path:
                return result
            marker=getattr(service,'_mark_injected_memories',None)
            observer=getattr(service,'_p5_record_observed',None)
            if (not callable(marker) or getattr(marker,'__self__',None)is not service
                    or p5_snapshot is not None and (not callable(observer)
                        or getattr(observer,'__self__',None)is not service)):
                return result
        except (TypeError,ValueError,OSError,CompanionTakeoverError):
            return result
        emitted=set(emitted_ids)
        ids=list(dict.fromkeys(state['origins'][identity] for identity,section in ticket._pairs
            if section in emitted and identity in state['origins']))
        ids=[identity for identity in ids if identity not in state['consumed']]
        if not ids:
            entry['state']='not_emitted_or_already_recorded'
            return dict(result,ok=True,state=entry['state'])
        # This single bounded RO ACL read is separate from pure per-VM
        # authorization callbacks. A normal new memory may change revision
        # during the LLM request; a current explicit recall denial must still
        # stop bookkeeping. Neither this check nor the old Store adapter is
        # a cross-DB/config atomic transaction.
        entry['state']='checking_acl'
        try:
            acl=await asyncio.to_thread(read_mc_private_recall_switch,self.path,dict(binding.mc_scope),
                configured_recall_enabled=configured_recall_enabled)
            if acl.get('known')is not True or acl.get('recall_enabled')is not True:
                entry['state']='mc_feedback_recall_denied'
                return dict(result,state=entry['state'])
            if (self._feedback.get(id(binding)) is not state or state['epoch']!=self._epoch
                    or not self.current(binding)):
                entry['state']='mc_feedback_authority_changed'
                return dict(result,state=entry['state'])
            self._read_allowed(binding)
        except asyncio.CancelledError:
            entry['state']='pending_unknown'
            raise
        except Exception:
            entry['state']='mc_feedback_acl_unavailable'
            return dict(result,state=entry['state'])
        # Sibling candidate checks may have completed while this RO snapshot
        # was pending. Recompute the consumed intersection before reserving.
        ids=[identity for identity in ids if identity not in state['consumed']]
        if not ids:
            entry['state']='not_emitted_or_already_recorded'
            return dict(result,ok=True,state=entry['state'])
        # Reserve synchronously before the first await, including sibling
        # tickets from public/private policies for this exact request binding.
        state['consumed'].update(ids);entry['state']='pending_unknown'
        result.update(count=len(ids),mark_invoked=True)
        try:
            await marker(ids)
            if not self.current(binding):
                entry['state']='mark_recorded_authority_changed'
                return dict(result,state=entry['state'])
            self._read_allowed(binding)
            if p5_snapshot is not None:
                result['provenance_invoked']=True
                observed=await observer(ids,p5_snapshot)
                if not isinstance(observed,dict) or observed.get('ok')is not True:
                    entry['state']='mark_recorded_provenance_unconfirmed'
                    return dict(result,state=entry['state'])
            entry['state']='recorded'
            return dict(result,ok=True,state=entry['state'])
        except asyncio.CancelledError:
            entry['state']='pending_unknown'
            raise
        except Exception:
            entry['state']='pending_unknown'
            return dict(result,state=entry['state'])

    @staticmethod
    def _rank(rows,query):
        terms=_tokens(query)
        if any(not term.startswith('c:') for term in terms):
            terms={term:weight for term,weight in terms.items() if not term.startswith('c:')}
        terms=dict(tuple(terms.items())[:256])
        ranked=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('content'),str):
                continue
            tokens=_tokens(row['content'])
            score=sum(weight for term,weight in terms.items() if term in tokens)
            if score:
                ranked.append(dict(row,score=score+(8. if _normal(query) in _normal(row['content']) else 0.)))
        return ranked

    async def materials(self,scope,*,limit=64,query='',binding=None):
        if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
            raise CompanionTakeoverError('invalid_material_limit')
        if type(query) is not str or len(query)>2000:
            raise CompanionTakeoverError('invalid_material_query')
        scope=private_scope(dict(scope))
        try:
            binding=self._binding(scope) if binding is None else binding
            token=self.generation(scope,binding=binding)
            if token is None:
                return _failure('mc_context_not_authorized')
            revision,rows=await asyncio.to_thread(self._read_snapshot,binding,query)
            if revision != token[-1]:
                return _failure('mc_material_changed')
            source=rows
            rows=self._project(source,binding)
            projected=list(rows)
            if self.base_materials is not None:
                base=await self.base_materials(scope=scope,limit=limit)
                if not isinstance(base,dict) or base.get('ok') is not True or not isinstance(base.get('items'),list):
                    return _failure('native_material_unavailable')
                rows+=base['items']
            if len(rows)>limit or len(json.dumps(rows,ensure_ascii=False,allow_nan=False).encode('utf8'))>MAX_BYTES:
                return _failure('combined_material_capacity')
            if token != self.generation(scope,binding=binding):
                return _failure('mc_material_changed')
            self._remember_projection(binding,source,projected)
            private=[row for row in rows if row.get('memory_type') in PRIVATE_TYPES]
            memories=self._rank([row for row in rows if row.get('memory_type') not in PRIVATE_TYPES],query)
            return dict(ok=True,state='ready',items=rows,private_items=private,memory_items=memories,
                        mc_revision=revision,writes=0)
        except (CompanionTakeoverError,raw.MCContextMaterialError,sqlite3.Error,OSError,ValueError,TypeError):
            return _failure('mc_material_unavailable')

    async def private_context_material(self,*,scope,limit=64):
        return await self.materials(scope,limit=limit)

    async def select(self,scope,*,query='',kind='continuity',max_chars=900,binding=None):
        scope=private_scope(dict(scope))
        binding=self._binding(scope) if binding is None else binding
        token=self.generation(scope,binding=binding)
        material=await self.materials(scope,query=query,binding=binding)
        if token is None or not material.get('ok'):
            return {'ok':False,'state':material.get('state','mc_context_not_authorized'),'sections':[]}
        private=material['private_items']
        generic=material['memory_items']
        if self.base_recall is not None and query.strip():
            base=await self.base_recall(query,scope=scope,top_k=3)
            if not isinstance(base,dict) or base.get('ok') is not True:
                return {'ok':False,'state':'native_recall_unavailable','sections':[]}
            generic+=base.get('memories',[])
        if len(generic)>MAX_ROWS:
            return {'ok':False,'state':'combined_material_capacity','sections':[]}
        ranked=self._rank(generic,query)
        now=self.clock()
        selected=self.private_policy.select(private,scope=scope,query=query,kind=kind,now=now,max_chars=max_chars)
        remaining=max_chars-selected['chars']
        facts=self.memory_policy.select(ranked,scope=scope,query=query,now=now,max_chars=max(120,remaining))
        sections=list(selected['sections'])
        if remaining>=120:
            selected_rows={row['id']:row for row in ranked}
            for identity,section in zip(facts['selected_ids'],facts['sections']):
                section=dict(section,content_key=content_fingerprint(selected_rows[identity]['content']))
                sections.append(section)
        if token != self.generation(scope,binding=binding):
            return {'ok':False,'state':'mc_material_changed','sections':[]}
        return dict(ok=True,state='ready',sections=sections,
                    rejected=selected['rejected']+facts['rejected'],writes=0,old_composer_calls=0)

    async def fragments(self,scope,*,query='',kind='continuity',max_chars=900,binding=None):
        value=await self.select(scope,query=query,kind=kind,max_chars=max_chars,binding=binding)
        return [ContextFragment('mc.'+section['id'],section['text'],section['evidence_kind'],
                    'tls.mc_native',priority=max(50,90-index),expires_at=section.get('expires_at'),
                    content_key=section.get('content_key'))
                for index,section in enumerate(value.get('sections',[]))]

    async def compose(self,scope,*,assembler,query='',kind='continuity',max_chars=900,binding=None):
        binding=self._binding(scope) if binding is None else binding
        token=self.generation(scope,binding=binding)
        fragments=await self.fragments(scope,query=query,kind=kind,max_chars=max_chars,binding=binding)
        if token is None or token != self.generation(scope,binding=binding):
            return ''
        value=assembler.compose(scope,fragments)
        return value['text'] if token==self.generation(scope,binding=binding) else ''
