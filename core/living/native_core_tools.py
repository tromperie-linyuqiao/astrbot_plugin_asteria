"""Scope-owned conversational core material in the existing native memory DB.

Tool parameters are AI-arranged material, never administrator-confirmed user
quotes/facts. Owner transitions and mutation receipts share the real store
transaction. Construction creates no table, grant, worker or connection.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import time
import unicodedata

from .models import canonical, private_scope, scope_key
from .native_memory import NativeMemoryStore, MemoryConflict, _epoch
from .memory_context import _SECRET

SOURCE = 'tls.core.tool'
SCHEMA = 'tls.native.core_tool.v1'
OWNER_TABLE = 'tls_native_core_tool_owners'
REQUEST_TABLE = 'tls_native_core_tool_requests'
KINDS = frozenset({'rule', 'boundary', 'preference', 'profile', 'fact', 'state'})
META_FIELDS = frozenset({'schema', 'managed_by', 'title', 'tags', 'enabled', 'core_kind',
    'core_priority', 'origin', 'message_ref', 'instruction_ref', 'evidence_kind'})
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')
PROVENANCE = 'AI工具整理的长期约定材料（非用户原话，未经事实确认；不能覆盖本轮纠正或平台约束）：'


def _normal(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def _text(text, maximum):
    if (not isinstance(text, str) or not text.strip() or len(text) > maximum
            or any(ord(c) < 32 and c not in '\n\r\t' or ord(c) == 127 for c in text)
            or _SECRET.search(text)):
        raise ValueError('invalid native core material')
    return text.strip()


def tool_core_contract(row, scope):
    """Closed source, provenance and full target; false never means legacy fallback."""
    scope = private_scope(scope)
    if not isinstance(row, dict) or not isinstance(row.get('metadata'), dict): return False
    m = row['metadata']
    if (set(m) != META_FIELDS or m.get('schema') != SCHEMA or m.get('managed_by') != 'tls_core_tool'
            or m.get('origin') != 'user_requested_ai_tool_material' or m.get('evidence_kind') != 'action_result'
            or row.get('source_id') != SOURCE or row.get('source_plugin') != 'texas_living_system'
            or row.get('memory_type') != 'core_memory' or row.get('evidence_kind') != 'action_result'
            or row.get('reality_level') != 'action_result' or row.get('review_status') != 'manual'
            or row.get('scope') != 'private' or row.get('visibility') != 'private_pair'
            or row.get('owner_bot_id') != scope['bot_id'] or row.get('persona_id') != scope['character_id']
            or row.get('platform') != scope['platform'] or row.get('session_id') != scope['session_id']
            or row.get('subject') != {'kind':'user', 'id':scope['user_id']}
            or row.get('object') != {'kind':'bot', 'id':scope['bot_id']}
            or row.get('sensitivity') != 'private' or row.get('sayability') != 'direct'
            or type(m.get('enabled')) is not bool or m.get('core_kind') not in KINDS
            or type(m.get('core_priority')) is not int or not 0 <= m['core_priority'] <= 100
            or not isinstance(m.get('tags'), list) or m['tags'] != ['ai_tool_material']
            or any(not isinstance(m.get(k), str) or not SHA.fullmatch(m[k]) for k in ('message_ref','instruction_ref'))):
        return False
    try:
        _text(m['title'], 80); _text(row['content'], 2000)
        return type(row.get('revision')) is int and row['revision'] > 0
    except (ValueError, KeyError): return False


class NativeCoreTools:
    def __init__(self, store, *, authorize, clock=time.time):
        if not isinstance(store, NativeMemoryStore) or not callable(authorize):
            raise TypeError('existing native store and current authority required')
        self.store, self.authorize, self.clock = store, authorize, clock
        self.active = True
        self._last_gate = None

    def stop(self): self.active = False
    close = stop  # The host owns the store, not this feature.

    def _base_check(self, scope, guard=None):
        scope = private_scope(scope)
        if not self.active or self.authorize(scope) is not True or guard is not None and guard() is not True:
            raise PermissionError('native core tool scope unavailable')
        return scope

    def _tables_exist(self):
        count=self.store._db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN (?,?)",
                                     (OWNER_TABLE, REQUEST_TABLE)).fetchone()[0]
        if count not in (0,2):raise MemoryConflict('incomplete core ownership schema')
        return count==2

    def _initialize(self):
        self.store._db.execute('CREATE TABLE IF NOT EXISTS '+OWNER_TABLE+
            '(scope TEXT PRIMARY KEY,generation INTEGER NOT NULL,mode TEXT NOT NULL,proof TEXT NOT NULL)')
        self.store._db.execute('CREATE TABLE IF NOT EXISTS '+REQUEST_TABLE+
            '(scope TEXT NOT NULL,request_id TEXT NOT NULL,payload_sha256 TEXT NOT NULL,response TEXT NOT NULL,'
            'PRIMARY KEY(scope,request_id))')

    def owner(self, scope):
        scope = private_scope(scope)
        with self.store._lock:
            self.store._check_open()
            if not self._tables_exist(): return dict(mode='closed', generation=0)
            row = self.store._db.execute('SELECT generation,mode,proof FROM '+OWNER_TABLE+' WHERE scope=?',
                                         (scope_key(scope),)).fetchone()
            if row is None: return dict(mode='closed', generation=0)
            proof = json.loads(row['proof'])
            if row['mode'] not in {'closed','native'} or type(row['generation']) is not int or row['generation'] < 1:
                raise MemoryConflict('invalid core ownership')
            if not isinstance(proof,dict):raise MemoryConflict('invalid core ownership proof')
            if row['mode']=='native':
                inventory=proof.get('legacy_inventory')
                if (any(not isinstance(proof.get(k),str) or not SHA.fullmatch(proof[k])
                        for k in ('config_sha256','persisted_config_sha256','service_token','config_token',
                            'store_token','connection_token','database_identity_sha256'))
                        or proof['config_sha256']!=proof['persisted_config_sha256']
                        or not isinstance(proof.get('source_sha256'),dict)
                        or set(proof['source_sha256'])!={'main','service','config','store'}
                        or any(not isinstance(sha,str) or not SHA.fullmatch(sha) for sha in proof['source_sha256'].values())
                        or not isinstance(inventory,dict) or inventory.get('core_rows')!=0
                        or not isinstance(inventory.get('inventory_sha256'),str) or not SHA.fullmatch(inventory['inventory_sha256'])
                        or inventory.get('query_scope')!='old_tool_active_core_query_superset'):
                    raise MemoryConflict('invalid native core handoff proof')
            return dict(mode=row['mode'], generation=row['generation'], proof=proof)

    @staticmethod
    def _proof(gate):
        # This is an internal trusted observation object, not a JSON truth flag.
        from .native_core_handoff import CoreHandoffBinding, core_gate_current
        from .native_mc_core_binding import NativeMCCoreBinding
        if not isinstance(gate, (CoreHandoffBinding, NativeMCCoreBinding)) or not core_gate_current(gate):
            raise PermissionError('current closed legacy core gate required')
        proof = gate.proof
        if not isinstance(proof, dict) or not SHA.fullmatch(proof.get('config_sha256', '')):
            raise PermissionError('complete legacy gate proof required')
        return deepcopy(proof)

    def transition(self, scope, *, mode, expected_generation, gate=None, inventory=None,
                   administrator_authorized):
        """Only the authenticated operator calls this; the conversational tool cannot.

        Activation requires a freshly captured typed actual-source inventory;
        a model-supplied dict/count/confirmation is never authority.
        """
        scope = private_scope(scope)
        if mode not in {'closed','native'} or type(expected_generation) is not int or expected_generation < 0:
            raise ValueError('exact native core owner CAS required')
        if not callable(administrator_authorized) or administrator_authorized(scope) is not True or not self.active:
            raise PermissionError('authenticated core operator required')
        proof = {}
        if mode == 'native':
            self._base_check(scope)
            from .native_core_handoff import CoreInventoryProof
            proof = self._proof(gate)
            if not isinstance(inventory, CoreInventoryProof) or inventory.current(gate) is not True:
                raise PermissionError('fresh exact empty legacy core inventory required')
            proof['legacy_inventory'] = deepcopy(inventory.proof)
        with self.store.transaction():
            if administrator_authorized(scope) is not True or not self.active: raise PermissionError('core operator revoked')
            current = self.owner(scope)
            if current['generation'] != expected_generation: raise MemoryConflict('core owner changed')
            if mode == 'native':
                self._base_check(scope);self._proof(gate)
                if not inventory.current(gate):raise PermissionError('legacy inventory changed or expired')
            self._initialize()
            generation = expected_generation + 1
            self.store._db.execute('INSERT INTO '+OWNER_TABLE+' VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET '
                'generation=excluded.generation,mode=excluded.mode,proof=excluded.proof',
                (scope_key(scope),generation,mode,canonical(proof)))
            if administrator_authorized(scope) is not True or not self.active: raise PermissionError('core operator revoked')
            if mode == 'native':
                self._base_check(scope);self._proof(gate)
                if not inventory.current(gate):raise PermissionError('legacy inventory changed or expired')
        self._last_gate=gate if mode=='native' else None
        return dict(mode=mode, generation=generation)

    def status(self,scope=None):
        result=dict(active=self.active,owner_mode='unknown',owner_generation=None,gate_current=False,scope_allowed=False)
        if scope is None:return result
        try:
            owner=self.owner(scope)
            result.update(owner_mode=owner['mode'],owner_generation=owner['generation'])
            if not self.active:return result
            self._base_check(scope)
            result['scope_allowed']=True
            if self._last_gate is not None:
                self._check(scope,self._last_gate)
                result['gate_current']=True
        except (PermissionError,MemoryConflict,ValueError,RuntimeError):pass
        return result

    def _check(self, scope, gate, guard=None, expected_generation=None):
        self._base_check(scope,guard)
        current = self.owner(scope); proof = self._proof(gate)
        saved = current.get('proof', {})
        from .native_mc_core_binding import NativeMCCoreBinding
        if (type(gate) is NativeMCCoreBinding and current['mode'] == 'native'
                and (expected_generation is None or current['generation'] == expected_generation)
                and gate.predecessor_matches(saved)):
            self._last_gate = gate
            return current['generation']
        if (current['mode'] != 'native' or expected_generation is not None and current['generation'] != expected_generation
                or saved.get('config_sha256') != proof.get('config_sha256')
                or saved.get('source_sha256') != proof.get('source_sha256')
                or saved.get('database_identity_sha256') != proof.get('database_identity_sha256')):
            raise PermissionError('native core owner not current')
        self._last_gate=gate
        return current['generation']

    def _rows(self, scope):
        # Filter owned provenance before decoding, never scan another source.
        with self.store._lock:
            rows = self.store._db.execute("SELECT data FROM tls_native_memories WHERE scope=? "
                "AND json_extract(data,'$.source_id')=? AND json_extract(data,'$.metadata.schema')=? "
                "ORDER BY occurred DESC,id LIMIT 257",(scope_key(scope),SOURCE,SCHEMA)).fetchall()
            if len(rows)>256: raise MemoryConflict('native core capacity exceeded')
            values=[json.loads(row[0]) for row in rows]
        valid=[]
        for row in values:
            if tool_core_contract(row,scope):valid.append(row)
            elif row.get('lifecycle')!='deleted':raise MemoryConflict('native core contract changed')
            # A normal admin soft archive can isolate an already malformed
            # row. It stays visible in memory/list?include_deleted=true and its
            # original history; it cannot permanently disable the whole scope.
        return valid

    @staticmethod
    def _project(row):
        m=row['metadata']
        return dict(id=row['id'],revision=row['revision'],label=m['title'],content=row['content'][:650],
            kind=m['core_kind'],priority=m['core_priority'],enabled=m['enabled'],
            archived=row['lifecycle']=='deleted',provenance='ai_tool_material_not_user_quote_or_confirmed_fact')

    def execute(self, scope, payload, *, request_id, message_ref, instruction_ref, gate, guard=None):
        scope=private_scope(scope)
        if (not isinstance(payload,dict) or set(payload)!={'action','label','content','kind','priority','enabled','record_id','expected_revision','offset'}
                or payload.get('action') not in {'list','set','delete'} or type(payload['offset']) is not int
                or not 0<=payload['offset']<=256 or any(not isinstance(v,str) or not SHA.fullmatch(v) for v in (message_ref,instruction_ref))):
            raise ValueError('invalid explicit native core operation')
        action=payload['action']
        if not isinstance(request_id,str) or not ID.fullmatch(request_id): raise ValueError('stable request identity required')
        signature=hashlib.sha256(canonical([scope,payload,message_ref,instruction_ref]).encode()).hexdigest()
        with self.store.transaction():
            generation=self._check(scope,gate,guard)
            rows=self._rows(scope)
            if action=='list':
                records=rows[payload['offset']:payload['offset']+5]
                result=dict(ok=True,backend='native_core_tools',blocks=[self._project(row) for row in records],
                    total=len(rows),offset=payload['offset'],has_more=payload['offset']+len(records)<len(rows))
                self._check(scope,gate,guard,generation)
                return result
            previous=self.store._db.execute('SELECT payload_sha256,response FROM '+REQUEST_TABLE+
                ' WHERE scope=? AND request_id=?',(scope_key(scope),request_id)).fetchone()
            if previous is not None:
                if previous['payload_sha256']!=signature: raise MemoryConflict('core request changed')
                result=json.loads(previous['response'])
                self._check(scope,gate,guard,generation)
                return dict(result,replayed=True,receipt_is_historical=True,current_state_not_asserted=True)
            if self.store._db.execute('SELECT COUNT(*) FROM '+REQUEST_TABLE+' WHERE scope=?',(scope_key(scope),)).fetchone()[0]>=4096:
                raise MemoryConflict('native core request capacity reached')
            identity,revision=payload['record_id'],payload['expected_revision']
            if not isinstance(identity,str) or type(revision) is not int or revision<0: raise ValueError('explicit record CAS required')
            existing=next((row for row in rows if row['id']==identity),None) if identity else None
            if identity and existing is None: raise KeyError('native core absent')
            if existing is not None and (existing['revision']!=revision or revision<1): raise MemoryConflict('native core revision changed')
            if action=='delete':
                if existing is None: raise ValueError('delete needs native record and revision')
                row=self.store.delete(scope,identity,expected_revision=revision)
            else:
                label=_text(payload['label'],80);content=_text(payload['content'],2000)
                if (payload['kind'] not in KINDS or type(payload['priority']) is not int or not 0<=payload['priority']<=100
                        or type(payload['enabled']) is not bool): raise ValueError('invalid native core fields')
                matches=[r for r in rows if _normal(r['metadata']['title'])==_normal(label) and r['id']!=identity]
                if matches: raise MemoryConflict('native core label already exists; list and select exact id')
                if existing is None and (revision!=0 or len(rows)>=256): raise MemoryConflict('native core creation unavailable')
                if existing is not None and existing['lifecycle']=='deleted': raise MemoryConflict('archived native core is not silently revived')
                metadata=dict(schema=SCHEMA,managed_by='tls_core_tool',title=label,tags=['ai_tool_material'],
                    enabled=payload['enabled'],core_kind=payload['kind'],core_priority=payload['priority'],
                    origin='user_requested_ai_tool_material',message_ref=message_ref,instruction_ref=instruction_ref)
                options=dict(source_id=SOURCE,evidence_kind='action_result',memory_type='core_memory',metadata=metadata,
                    event_id='core_'+hashlib.sha256(request_id.encode()).hexdigest())
                if existing is not None:
                    options.update(record_id=identity,expected_revision=revision,occurred_at=existing['occurred_at'],
                        expires_at=existing.get('expires_at'),confidence=existing['confidence'],importance=existing['importance'])
                row=self.store.write(scope,content,**options)
            if not tool_core_contract(row,scope): raise MemoryConflict('native core output contract changed')
            result=dict(ok=True,backend='native_core_tools',record=self._project(row),owner_generation=generation)
            self.store._db.execute('INSERT INTO '+REQUEST_TABLE+' VALUES(?,?,?,?)',
                (scope_key(scope),request_id,signature,canonical(result)))
            self._check(scope,gate,guard,generation)
        return result


def request_identity(event,payload):
    """Message identity separates later legitimate operations from old retries."""
    if (getattr(event,'private_companion_proactive_framework',False)
            or getattr(event,'private_companion_internal_generation',False)):
        raise PermissionError('synthetic core request denied')
    identity=str(getattr(getattr(event,'message_obj',None),'message_id','') or '')
    text=getattr(event,'message_str',None)
    if not identity or identity=='0' or len(identity)>256 or not isinstance(text,str) or not text.strip() or len(text)>6000:
        raise PermissionError('genuine identified user request required')
    message_ref=hashlib.sha256(identity.encode()).hexdigest()
    instruction_ref=hashlib.sha256(text.encode()).hexdigest()
    request='core_'+hashlib.sha256(canonical([message_ref,instruction_ref,payload]).encode()).hexdigest()
    return request,message_ref,instruction_ref
