"""TLS-owned explicit long-term agreements in the existing native memory store.

No legacy source is read or relabelled. Writes use the store's real revisions,
append-only history, event idempotency and soft deletion. The authorization
callback is checked inside the outer write transaction so a late failure rolls
back the operation rather than returning a forbidden response after a commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata

from .models import private_scope, scope_key, canonical
from .native_memory import NativeMemoryStore, MemoryConflict, _epoch
from .memory_context import _SECRET

SOURCE = 'tls.personal.panel'
SCHEMA = 'tls.native.personal.v1'
CORE_KINDS = frozenset({'rule','boundary','preference','profile','fact','state'})
EDIT_FIELDS = frozenset({'title','content','tags','enabled','core_kind','core_priority'})
META_FIELDS = frozenset({'schema','managed_by','personal_kind','title','tags','enabled','core_kind','core_priority','evidence_kind'})
_REQUEST = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,95}')
_ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}')


def _text(value, name, maximum):
    if (not isinstance(value,str) or not value.strip() or len(value)>maximum
            or any(ord(char)<32 and char not in '\n\r\t' for char in value)
            or _SECRET.search(value)):
        raise ValueError('invalid '+name)
    return value


def edit_fields(data):
    if not isinstance(data,dict) or set(data)!=EDIT_FIELDS:
        raise ValueError('exact personal edit fields required')
    title=_text(data['title'],'title',80)
    content=_text(data['content'],'content',2000)
    tags=data['tags']
    if (not isinstance(tags,list) or len(tags)>12
            or any(not isinstance(tag,str) or not tag.strip() or len(tag)>24
                or any(ord(char)<32 for char in tag) or _SECRET.search(tag) for tag in tags)
            or len(set(tags))!=len(tags)):
        raise ValueError('invalid tags')
    if type(data['enabled']) is not bool:raise ValueError('enabled must be boolean')
    if data['core_kind'] not in CORE_KINDS:raise ValueError('invalid core kind')
    if type(data['core_priority']) is not int or not 0<=data['core_priority']<=100:
        raise ValueError('invalid core priority')
    return dict(title=title,content=content,tags=list(tags),enabled=data['enabled'],
        core_kind=data['core_kind'],core_priority=data['core_priority'])


def personal_contract(row,scope):
    """Closed native contract; no normalization into a legacy MC identity."""
    scope=private_scope(scope)
    if not isinstance(row,dict):return False
    meta=row.get('metadata')
    if (not isinstance(meta,dict) or set(meta)!=META_FIELDS
            or meta.get('schema')!=SCHEMA or meta.get('managed_by')!='tls_material_panel'
            or meta.get('personal_kind')!='core' or meta.get('evidence_kind')!='user_reported'
            or row.get('memory_type')!='core_memory' or row.get('source_id')!=SOURCE
            or row.get('source_plugin')!='texas_living_system'
            or row.get('evidence_kind')!='user_reported' or row.get('reality_level')!='real_user_fact'
            or row.get('review_status')!='manual' or row.get('scope')!='private'
            or row.get('visibility')!='private_pair'
            or row.get('platform')!=scope['platform'] or row.get('owner_bot_id')!=scope['bot_id']
            or row.get('persona_id')!=scope['character_id'] or row.get('session_id')!=scope['session_id']
            or row.get('subject')!={'kind':'user','id':scope['user_id']}
            or row.get('object')!={'kind':'bot','id':scope['bot_id']}
            or row.get('lifecycle') not in {'stable_memory','deleted'}
            or row.get('validity_status')!=('deleted' if row.get('lifecycle')=='deleted' else 'active')
            or type(row.get('revision')) is not int or row['revision']<1):return False
    try:edit_fields({key:row.get('content') if key=='content' else meta.get(key) for key in EDIT_FIELDS})
    except (ValueError,TypeError):return False
    return True


class NativePersonalMaterials:
    def __init__(self,store,*,authorize,clock):
        if not isinstance(store,NativeMemoryStore) or not callable(authorize):
            raise TypeError('existing native store and authorization required')
        self.store,self.authorize,self.clock=store,authorize,clock

    def check(self,scope):
        scope=private_scope(scope)
        if self.authorize(scope) is not True:raise PermissionError('personal scope unavailable')
        return scope

    @staticmethod
    def _revision(value):
        if type(value) is not int or not 1<=value<=2147483647:raise ValueError('positive revision required')

    def _record(self,scope,identity):
        if not isinstance(identity,str) or not _ID.fullmatch(identity):raise ValueError('invalid record id')
        row=self.store.get(scope,identity,include_deleted=True)
        if not personal_contract(row,scope):raise KeyError(identity)
        return row

    def project(self,row):
        meta=row['metadata']
        eligible=meta['enabled'] is True and row['lifecycle']=='stable_memory'
        try:
            now=_epoch(self.clock());occurred=_epoch(row['occurred_at'])
            since=_epoch(row['valid_from']) if row.get('valid_from') not in (None,'') else occurred
            endings=[_epoch(row[key]) for key in ('expires_at','valid_to') if row.get(key) not in (None,'')]
            eligible=bool(eligible and occurred<=now and since<=now
                and all(until>now and until>occurred and until>since for until in endings))
        except (ValueError,TypeError,OverflowError):
            eligible=False
        return dict(id=row['id'],revision=row['revision'],title=meta['title'],content=row['content'],
            tags=list(meta['tags']),enabled=meta['enabled'],core_kind=meta['core_kind'],
            core_priority=meta['core_priority'],archived=row['lifecycle']=='deleted',
            created_at=row['created_at'],updated_at=row['updated_at'],source=SOURCE,schema=SCHEMA,
            eligible_for_context=eligible,
            actually_used='unknown')

    @staticmethod
    def _metadata(fields):
        return dict(schema=SCHEMA,managed_by='tls_material_panel',personal_kind='core',
            **{key:fields[key] for key in EDIT_FIELDS if key!='content'})

    def create(self,scope,*,request_id,**fields):
        scope=self.check(scope);fields=edit_fields(fields)
        if not isinstance(request_id,str) or not _REQUEST.fullmatch(request_id):raise ValueError('invalid request id')
        event='personal_'+hashlib.sha256(request_id.encode()).hexdigest()
        with self.store.transaction():
            self.check(scope)
            row=self.store.write(scope,fields['content'],source_id=SOURCE,evidence_kind='user_reported',
                memory_type='core_memory',metadata=self._metadata(fields),event_id=event)
            if not personal_contract(row,scope):raise MemoryConflict('personal identity was changed')
            self.check(scope)
            result=self.project(row)
        return result

    def update(self,scope,identity,*,expected_revision,**fields):
        scope=self.check(scope);self._revision(expected_revision);fields=edit_fields(fields)
        with self.store.transaction():
            self.check(scope);old=self._record(scope,identity)
            if old['lifecycle']=='deleted':raise MemoryConflict('restore archived material before edit')
            row=self.store.write(scope,fields['content'],source_id=SOURCE,evidence_kind='user_reported',
                memory_type='core_memory',metadata=self._metadata(fields),record_id=identity,
                expected_revision=expected_revision,occurred_at=old['occurred_at'],
                expires_at=old.get('expires_at'),
                confidence=old['confidence'],importance=old['importance'])
            if not personal_contract(row,scope):raise MemoryConflict('personal identity was changed')
            self.check(scope);result=self.project(row)
        return result

    def _change(self,scope,identity,expected_revision,operation):
        scope=self.check(scope);self._revision(expected_revision)
        with self.store.transaction():
            self.check(scope);self._record(scope,identity)
            row=getattr(self.store,operation)(scope,identity,expected_revision=expected_revision)
            if not personal_contract(row,scope):raise MemoryConflict('personal identity was changed')
            self.check(scope);result=self.project(row)
        return result

    def archive(self,scope,identity,*,expected_revision):
        return self._change(scope,identity,expected_revision,'delete')

    def restore(self,scope,identity,*,expected_revision):
        return self._change(scope,identity,expected_revision,'restore')

    def export(self,scope,identity):
        scope=self.check(scope)
        row=self._record(scope,identity);self.check(scope)
        return dict(schema='tls.native.personal.export.v1',scope=scope,record=self.project(row),
            generated_at=datetime.fromtimestamp(self.clock(),timezone.utc).isoformat())

    def list(self,scope,*,include_archived=False,limit=20,offset=0):
        scope=self.check(scope)
        if type(include_archived) is not bool:raise ValueError('include_archived must be boolean')
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:
            raise ValueError('invalid pagination')
        # SQL filters server-owned provenance before pagination. No unrelated
        # memory content is scanned or returned. Corrupt contract rows are held.
        where="scope=? AND json_extract(data,'$.source_id')=? AND json_extract(data,'$.metadata.schema')=? AND json_extract(data,'$.memory_type')='core_memory'"
        args=[scope_key(scope),SOURCE,SCHEMA]
        if not include_archived:where+=" AND lifecycle!='deleted'"
        import json
        with self.store._lock:
            self.store._check_open();self.check(scope)
            if self.store._db.in_transaction:raise MemoryConflict('store is in another transaction')
            self.store._db.execute('BEGIN')
            try:
                total=self.store._db.execute('SELECT COUNT(*) FROM tls_native_memories WHERE '+where,args).fetchone()[0]
                raw=self.store._db.execute('SELECT data FROM tls_native_memories WHERE '+where+
                    ' ORDER BY occurred DESC,id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
                records=[];held=0
                for value in raw:
                    row=json.loads(value[0])
                    if personal_contract(row,scope):records.append(self.project(row))
                    else:held+=1
                self.check(scope)
            finally:self.store._db.execute('ROLLBACK')
        return dict(records=records,total=total,limit=limit,offset=offset,has_more=offset+len(raw)<total,
            held_invalid_count=held,total_scope='exact-source-schema candidates; invalid rows held from output')


    def preview_import(self,scope,payload):
        return _preview_import(self,scope,payload)

    def confirm_import(self,scope,payload,*,preview_sha,request_id,owner_confirmed):
        return _confirm_import(self,scope,payload,preview_sha=preview_sha,request_id=request_id,owner_confirmed=owner_confirmed)

    def export_batch(self,scope,*,include_archived=False,limit=100,offset=0,expected_generation=None):
        return _export_batch(self,scope,include_archived=include_archived,limit=limit,offset=offset,expected_generation=expected_generation)


# Batch transfer stays in the same store and event protocol. No receipt record,
# second table or fake memory is used to remember a batch.
PERSONAL_CAPACITY=1000
MAX_IMPORT_ITEMS=20
MAX_IMPORT_BYTES=96*1024
PROJECT_FIELDS=frozenset({'id','revision','title','content','tags','enabled','core_kind','core_priority',
    'archived','created_at','updated_at','source','schema','eligible_for_context','actually_used'})
BATCH_STATUSES=('ready','invalid','payload_duplicate','payload_conflict','existing_duplicate','existing_conflict','archived_conflict')


class PersonalImportOutcomeUnknown(MemoryConflict):
    """Existing request events do not prove one complete, matching transaction."""


def _canonical_payload(payload):
    try:
        value=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
        if len(value.encode('utf-8'))>MAX_IMPORT_BYTES:raise ValueError('payload exceeds 96 KiB')
        return value
    except (TypeError,ValueError,RecursionError) as exc:raise ValueError('invalid or oversized import JSON') from exc


def _export_scope(scope,payload):
    exported_scope=payload.get('scope');required={'platform','bot_id','user_id','character_id','session_id'}
    if (not isinstance(exported_scope,dict) or set(exported_scope)-required-{'private'}
            or not required.issubset(exported_scope) or exported_scope.get('private',True) is not True
            or private_scope(exported_scope)!=scope):raise ValueError('complete matching export scope required')


def _export_record(row):
    if (not isinstance(row,dict) or set(row)!=PROJECT_FIELDS
            or row.get('source')!=SOURCE or row.get('schema')!=SCHEMA
            or type(row.get('archived')) is not bool or type(row.get('eligible_for_context')) is not bool
            or row.get('actually_used')!='unknown'
            or not isinstance(row.get('id'),str) or not _ID.fullmatch(row['id'])
            or type(row.get('revision')) is not int or row['revision']<1):raise ValueError('invalid product export record')
    _epoch(row['created_at']);_epoch(row['updated_at'])
    return edit_fields({key:row.get(key) for key in EDIT_FIELDS})


def _page_integer(value,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:raise ValueError('invalid product page count')
    return value


def _import_entries(scope,payload):
    encoded=_canonical_payload(payload);archived=set();source_page=None
    if isinstance(payload,list):entries=payload
    elif isinstance(payload,dict):
        _export_scope(scope,payload)
        if payload.get('schema')=='tls.native.personal.export.v1':
            if set(payload)!={'schema','scope','record','generated_at'}:raise ValueError('invalid single export fields')
            row=payload.get('record');fields=_export_record(row);_epoch(payload['generated_at'])
            if row['archived']:archived.add(0)
            entries=[fields]
        elif payload.get('schema')=='tls.native.personal.batch-export.v1':
            expected={'schema','scope','items','records','total','limit','offset','truncated','has_more','next_offset',
                'held_invalid_count','total_scope','source_label','actually_used','generated_at','snapshot_generation'}
            if set(payload)!=expected:raise ValueError('invalid batch export fields')
            _epoch(payload['generated_at'])
            total=_page_integer(payload['total'],0,2147483647)
            limit=_page_integer(payload['limit'],1,100);offset=_page_integer(payload['offset'],0,1000000)
            held=_page_integer(payload['held_invalid_count'],0,limit)
            generation=_page_integer(payload['snapshot_generation'],0,2147483647)
            records=payload['records'];entries=payload['items']
            if (not isinstance(records,list) or not isinstance(entries,list) or len(records)!=len(entries)
                    or len(records)+held!=min(limit,max(0,total-offset))
                    or payload['source_label']!='用户管理页确认的约定' or payload['actually_used']!='unknown'
                    or payload['total_scope']!='exact-source-schema candidates; invalid rows held from output'):
                raise ValueError('batch records or source counters mismatch')
            more=offset+len(records)+held<total
            if (type(payload['truncated']) is not bool or type(payload['has_more']) is not bool
                    or payload['truncated'] is not more or payload['has_more'] is not more):
                raise ValueError('batch pagination mismatch')
            if more:
                if type(payload['next_offset']) is not int or payload['next_offset']!=offset+limit:
                    raise ValueError('batch next offset mismatch')
            elif payload['next_offset'] is not None:raise ValueError('unexpected next offset')
            identities=set()
            for index,(entry,row) in enumerate(zip(entries,records)):
                fields=_export_record(row)
                if edit_fields(entry)!=fields or row['id'] in identities:raise ValueError('items and records mismatch')
                identities.add(row['id'])
                if row['archived']:archived.add(index)
            source_page=dict(kind='batch_export',total=total,offset=offset,limit=limit,returned=len(records),
                truncated=more,has_more=more,next_offset=payload['next_offset'],held_invalid_count=held,
                snapshot_generation=generation)
        else:raise ValueError('unsupported product export schema')
    else:raise ValueError('import payload must be a list or a product export')
    if not 1<=len(entries)<=MAX_IMPORT_ITEMS:raise ValueError('import requires 1..20 items')
    return entries,archived,hashlib.sha256(encoded.encode('utf-8')).hexdigest(),source_page


def _normal_label(value):return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())


def _edit_signature(fields):
    # Title is the policy's label; tags remain user labels, not an authority.
    return canonical(dict(fields,title=_normal_label(fields['title']),content=_normal_label(fields['content'])))


def _owned_rows_locked(self,scope):
    where="scope=? AND json_extract(data,'$.source_id')=? AND json_extract(data,'$.metadata.schema')=? AND json_extract(data,'$.memory_type')='core_memory'"
    args=(scope_key(scope),SOURCE,SCHEMA)
    total=self.store._db.execute('SELECT COUNT(*) FROM tls_native_memories WHERE '+where,args).fetchone()[0]
    raw=self.store._db.execute('SELECT data FROM tls_native_memories WHERE '+where+
        ' ORDER BY occurred DESC,id LIMIT ?',(*args,PERSONAL_CAPACITY+1)).fetchall()
    records=[];held=0
    for value in raw:
        row=json.loads(value[0])
        if personal_contract(row,scope):records.append(row)
        else:held+=1
    return total,records,held


def _preview_locked(self,scope,payload):
    entries,archived,payload_sha,source_page=_import_entries(scope,payload)
    generation=self.store.data_generation(scope)
    total,existing,held=_owned_rows_locked(self,scope)
    by_claim={}
    for row in existing:
        fields={key:row['content'] if key=='content' else row['metadata'][key] for key in EDIT_FIELDS}
        claim=(_normal_label(fields['title']),fields['core_kind'])
        by_claim.setdefault(claim,[]).append((fields,row))
    counts={key:0 for key in BATCH_STATUSES};items=[];seen={}
    for index,raw in enumerate(entries):
        status='ready';issues=[];fields=None
        try:fields=edit_fields(raw)
        except (ValueError,TypeError):status='invalid';issues=['字段缺失、多余、类型或长度无效；凭据内容不允许导入']
        if fields is not None:
            claim=(_normal_label(fields['title']),fields['core_kind']);signature=_edit_signature(fields)
            if index in archived:status='archived_conflict';issues=['来源导出已归档；请先人工核对，导入不会自动恢复']
            elif claim in seen:
                status='payload_duplicate' if seen[claim]==signature else 'payload_conflict'
                issues=['本批含相同标题和类别的重复或冲突约定']
            else:
                seen[claim]=signature
                matches=by_claim.get(claim,[])
                if any(row['lifecycle']=='deleted' for _,row in matches):
                    status='archived_conflict';issues=['已有同标题类别的归档记录；请使用原记录恢复/编辑']
                elif any(_edit_signature(value)==signature for value,_ in matches):
                    status='existing_duplicate';issues=['已有相同约定；不会重复创建或覆盖']
                elif matches:status='existing_conflict';issues=['已有同标题类别的不同约定；请使用单项编辑解决']
        counts[status]+=1;items.append(dict(index=index,status=status,issues=issues,fields=fields))
    issues=[]
    if held:issues.append('同源资料存在契约受损记录，请先检查；本次不自动修复')
    if total+len(entries)>PERSONAL_CAPACITY:issues.append('导入后将超出当前范围1000条容量（含归档），本次不写入')
    can_import=counts['ready']==len(items) and not issues and total<=PERSONAL_CAPACITY
    material=dict(schema='tls.native.personal.preview.v1',scope=scope,payload_sha=payload_sha,
        snapshot_generation=generation,source_page=source_page,items=items,counts=counts,
        capacity=dict(limit=PERSONAL_CAPACITY,current=total,remaining=max(0,PERSONAL_CAPACITY-total)),
        can_import=can_import,issues=issues,
        source_label='用户管理页确认的约定',
        confirmation_text='我确认这些内容是本人希望角色遵守的约定；不是未经核实的现实经历或模型推断。')
    material['preview_sha']=hashlib.sha256(canonical(material).encode()).hexdigest()
    return material


def _preview_import(self,scope,payload):
    scope=self.check(scope)
    with self.store._lock:
        self.store._check_open();self.check(scope)
        if self.store._db.in_transaction:raise MemoryConflict('preview requires independent read snapshot')
        self.store._db.execute('BEGIN')
        try:result=_preview_locked(self,scope,payload);self.check(scope)
        finally:self.store._db.execute('ROLLBACK')
    return result


def _batch_events(self,scope,request_id,payload,preview_sha):
    if not isinstance(request_id,str) or not _REQUEST.fullmatch(request_id):raise ValueError('invalid request id')
    if not isinstance(preview_sha,str) or not re.fullmatch('[a-f0-9]{64}',preview_sha):raise ValueError('invalid preview hash')
    entries,_,payload_sha,_=_import_entries(scope,payload)
    fields=[edit_fields(row) for row in entries]
    prefix='pmb_'+hashlib.sha256(request_id.encode()).hexdigest()
    binding=hashlib.sha256(canonical([scope,payload_sha,preview_sha,True]).encode()).hexdigest()[:48]
    events=[prefix+'_'+binding+'_'+str(len(fields)).zfill(2)+'_'+str(index).zfill(2) for index in range(len(fields))]
    return prefix,events,fields


def _completed_batch_locked(self,scope,prefix,events,fields):
    start=prefix+'_'
    saved=self.store._db.execute('SELECT id,fingerprint,record_id FROM tls_native_memory_events WHERE scope=? AND substr(id,1,?)=?',
        (scope_key(scope),len(start),start)).fetchall()
    if not saved:return None
    by_id={row['id']:row for row in saved}
    if set(by_id)!=set(events):raise PersonalImportOutcomeUnknown('batch request has incomplete or different event set')
    records=[]
    for event,value in zip(events,fields):
        payload=self.store._payload(value['content'],SOURCE,'user_reported','core_memory','',1.,.5,None,None,self._metadata(value))
        fingerprint=self.store._fingerprint(payload)
        expected=hashlib.sha256(canonical([fingerprint,None,None]).encode()).hexdigest()
        if by_id[event]['fingerprint']!=expected:raise PersonalImportOutcomeUnknown('batch event fingerprint mismatch')
        try:row=self._record(scope,by_id[event]['record_id'])
        except KeyError as exc:raise PersonalImportOutcomeUnknown('batch record unavailable') from exc
        records.append(self.project(row))
    return records


def _confirm_import(self,scope,payload,*,preview_sha,request_id,owner_confirmed):
    scope=self.check(scope)
    if owner_confirmed is not True:raise ValueError('explicit owner confirmation required')
    prefix,events,fields=_batch_events(self,scope,request_id,payload,preview_sha)
    with self.store.transaction():
        self.check(scope)
        completed=_completed_batch_locked(self,scope,prefix,events,fields)
        if completed is not None:
            self.check(scope)
            return dict(state='already_committed',records=completed,imported_count=len(completed),replayed=True,actually_used='unknown')
        preview=_preview_locked(self,scope,payload)
        if preview['preview_sha']!=preview_sha:raise MemoryConflict('preview snapshot changed; read and preview again')
        if preview['can_import'] is not True:raise MemoryConflict('preview contains unresolved items or capacity limit')
        records=[]
        for event,value in zip(events,fields):
            self.check(scope)
            row=self.store.write(scope,value['content'],source_id=SOURCE,evidence_kind='user_reported',
                memory_type='core_memory',metadata=self._metadata(value),event_id=event)
            if not personal_contract(row,scope):raise MemoryConflict('personal identity changed during import')
            self.check(scope);records.append(self.project(row))
        self.check(scope)
    return dict(state='committed',records=records,imported_count=len(records),replayed=False,actually_used='unknown')


def _export_batch(self,scope,*,include_archived=False,limit=100,offset=0,expected_generation=None):
    scope=self.check(scope)
    if expected_generation is not None:_page_integer(expected_generation,0,2147483647)
    before=self.store.data_generation(scope)
    if expected_generation is not None and before!=expected_generation:raise MemoryConflict('export snapshot changed; restart from first page')
    page=self.list(scope,include_archived=include_archived,limit=limit,offset=offset)
    after=self.store.data_generation(scope)
    if before!=after:raise MemoryConflict('export snapshot changed while reading')
    items=[{key:row[key] for key in EDIT_FIELDS} for row in page['records']]
    self.check(scope)
    return dict(schema='tls.native.personal.batch-export.v1',scope=scope,items=items,records=page['records'],
        total=page['total'],limit=limit,offset=offset,snapshot_generation=after,truncated=page['has_more'],has_more=page['has_more'],
        next_offset=offset+limit if page['has_more'] else None,held_invalid_count=page['held_invalid_count'],
        total_scope=page['total_scope'],source_label='用户管理页确认的约定',actually_used='unknown',
        generated_at=datetime.fromtimestamp(self.clock(),timezone.utc).isoformat())


