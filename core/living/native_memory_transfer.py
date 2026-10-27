"""Explicit scoped bulk material transfer through the existing native store.

No schema, second database, model or background work is added. Existing native
events hold hash-only batch/row receipts atomically with the public store writes;
their mt_* namespace is private to this module, never a memory fact.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
import re
import time
import unicodedata

from .journal import JournalConflict
from .models import private_scope,scope_key
from .native_memory import NativeMemoryStore

SCHEMA='tls.native_memory_transfer.v1'
MAX_BYTES=128*1024
MAX_ROWS=200
_FIELDS={'id','content','memory_type','evidence_kind','tags','source','updated_at'}
_TYPES={'fact':'user_reported','preference':'user_reported','event':'user_reported',
    'utterance':'user_reported','roleplay_event':'roleplay_event','model_inference':'model_inference'}
_FACT={'fact','preference','event'}
_SHA=re.compile(r'[a-f0-9]{64}\Z')
_ID=re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')
_SCOPE={'platform','bot_id','user_id','character_id','session_id','private'}


class MemoryTransferConflict(JournalConflict):pass


def _hash(value):
    # Inputs/rows are closed and bounded before this helper. The document cap
    # applies to user bytes, not JSON quoting or generated preview overhead.
    encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _scope(value):
    if not isinstance(value,dict) or set(value)!=_SCOPE or value.get('private') is not True:
        raise ValueError('complete private transfer scope required')
    result=private_scope(value)
    if result!=value or any(not isinstance(value[key],str) or len(value[key])>512 for key in _SCOPE-{'private'}):
        raise ValueError('complete private transfer scope required')
    return result


def _text(value,maximum,*,empty=False):
    return (isinstance(value,str) and (empty or bool(value)) and len(value)<=maximum and value==value.strip()
        and not any(ord(char)<32 and char not in '\t\r\n' for char in value))


def _normal(value):return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())


def _tags(value):
    if (not isinstance(value,list) or len(value)>16 or any(not _text(item,32) for item in value)
            or len(set(value))!=len(value)):
        raise ValueError('bounded distinct manual tags required')
    return list(value)


class NativeMemoryTransfer:
    backend='native_memory_transfer'

    def __init__(self,store,*,authorize,clock=time.time):
        if not isinstance(store,NativeMemoryStore) or not callable(authorize) or not callable(clock):
            raise ValueError('native memory and dynamic authority required')
        self.store,self.authorize,self.clock=store,authorize,clock
        self.active=True

    def _allowed(self,value):
        scope=_scope(value)
        if not self.active or self.authorize(dict(scope)) is not True:
            raise PermissionError('native transfer scope unavailable')
        return scope

    @staticmethod
    def _parse(payload,format,mode,confirm_real_world):
        if format not in {'json','text','csv'}:raise ValueError('unsupported transfer format')
        if mode!='append':raise ValueError('update and merge are unsupported')
        if type(confirm_real_world) is not bool:raise ValueError('explicit world confirmation required')
        if not isinstance(payload,str) or not 1<=len(payload.encode('utf-8'))<=MAX_BYTES:
            raise ValueError('bounded material text required')
        try:
            if format=='json':
                rows=json.loads(payload)
                if not isinstance(rows,list):raise ValueError('JSON array required')
            elif format=='text':rows=[line for line in payload.splitlines() if line.strip()]
            else:
                reader=csv.DictReader(io.StringIO(payload,newline=''),strict=True)
                names=reader.fieldnames
                if not names or len(set(names))!=len(names) or 'content' not in names:
                    raise ValueError('distinct CSV headers with content required')
                rows=[]
                for source in reader:
                    if None in source:raise ValueError('CSV column count mismatch')
                    row={key:value for key,value in source.items() if value not in ('',None)}
                    if 'tags' in row:
                        try:row['tags']=json.loads(row['tags'])
                        except (ValueError,TypeError):row['tags']=None
                    rows.append(row)
                    if len(rows)>MAX_ROWS:raise ValueError('too many material rows')
        except (csv.Error,UnicodeError,RecursionError):raise ValueError('invalid material document') from None
        if not 1<=len(rows)<=MAX_ROWS:raise ValueError('one to 200 material rows required')
        return rows,_hash([format,mode,confirm_real_world,payload])

    @staticmethod
    def _item(raw,line,confirm_real_world):
        result=dict(line=line,status='failed',errors=[],unknown_fields=[],notes=[])
        if isinstance(raw,str):raw={'content':raw}
        if not isinstance(raw,dict):result['errors']=['record_object_or_text_required'];return result
        unknown=set(raw)-_FIELDS
        if unknown:result['unknown_fields']=sorted(str(key)[:128] for key in unknown);result['errors'].append('unknown_fields')
        content=raw.get('content')
        kind=raw.get('memory_type','utterance')
        evidence=raw.get('evidence_kind',_TYPES.get(kind) if isinstance(kind,str) else None)
        if not _text(content,6000):result['errors'].append('invalid_content')
        if not isinstance(kind,str) or kind not in _TYPES:result['errors'].append('unsupported_memory_type')
        if not isinstance(kind,str) or evidence!=_TYPES.get(kind) or evidence=='real_observation':result['errors'].append('unsupported_evidence')
        if isinstance(kind,str) and kind in _FACT and not confirm_real_world:result['errors'].append('explicit_real_world_confirmation_required')
        identity=raw.get('id')
        if identity is not None and (not isinstance(identity,str) or not _ID.fullmatch(identity)):
            result['errors'].append('invalid_id')
        try:tags=_tags(raw.get('tags',[]))
        except (ValueError,TypeError):tags=[];result['errors'].append('invalid_tags')
        source=raw.get('source','')
        if not _text(source,128,empty=True):result['errors'].append('invalid_source')
        updated=raw.get('updated_at')
        if updated is not None:
            try:
                if not isinstance(updated,str) or not 1<=len(updated)<=80:raise ValueError()
                stamp=datetime.fromisoformat(updated.replace('Z','+00:00'))
                if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError()
            except (ValueError,TypeError,OverflowError):result['errors'].append('invalid_source_updated_at')
        if result['errors']:return result
        result.update(content=content,memory_type=kind,evidence_kind=evidence,tags=tags,source=source,
            source_updated_at=updated,requested_id=identity,status='new',notes=[])
        if updated is not None:result['notes'].append('source_timestamp_retained_as_provenance')
        if kind=='utterance':result['notes'].append('imported_material_not_an_automatic_user_fact')
        return result

    def _all(self,scope):
        offset=0
        while True:
            page=self.store.list(scope,limit=1000,offset=offset,include_deleted=True)
            offset+=len(page)
            if offset>20000:raise ValueError('scope inventory exceeds transfer budget')
            yield from page
            if len(page)<1000:return

    @staticmethod
    def _key(row):
        meta=row.get('metadata',{})
        tags=meta.get('tags',[]) if isinstance(meta,dict) else []
        try:tags=_tags(tags)
        except (ValueError,TypeError):tags=[]
        return (_normal(row['content']),row['memory_type'],row['evidence_kind'],tuple(tags))

    def _preview(self,scope,raw,signature,format,mode,confirm_real_world):
        generation=self.store.data_generation(scope)
        items=[self._item(value,index,confirm_real_world) for index,value in enumerate(raw,1)]
        keys={(_normal(item['content']),item['memory_type'],item['evidence_kind'],tuple(item['tags']))
            for item in items if item['status']!='failed'}
        ids={item['requested_id'] for item in items if item['status']!='failed' and item['requested_id']}
        by_id={};by_key={}
        for row in self._all(scope):
            if row['id'] in ids:by_id[row['id']]=row
            key=self._key(row)
            if key in keys and (key not in by_key or row['id']<by_key[key]['id']):by_key[key]=row
        rows=[]
        for item in items:
            if item['status']=='failed':rows.append(item);continue
            key=(_normal(item['content']),item['memory_type'],item['evidence_kind'],tuple(item['tags']))
            requested=item['requested_id'];current=by_id.get(requested) if requested else None
            if current is not None and self._key(current)!=key:
                item.update(status='failed',errors=['id_content_conflict_update_unsupported']);rows.append(item);continue
            current=current or by_key.get(key)
            if current is not None:
                item.update(status='duplicate',id=current['id'],existing_revision=current['revision'])
                if requested and current['id']!=requested:item['notes'].append('existing_duplicate_id_preserved')
                if current.get('lifecycle')=='deleted':item['notes'].append('deleted_record_not_restored')
            else:
                identity=requested or 'import_'+_hash([scope,[key[0],key[1],key[2],list(key[3])]])
                item.update(id=identity)
                synthetic=dict(id=identity,content=item['content'],memory_type=item['memory_type'],
                    evidence_kind=item['evidence_kind'],metadata={'tags':item['tags']},revision=1,lifecycle='active')
                by_id[identity]=synthetic;by_key[key]=synthetic
            rows.append(item)
        counts={name:sum(row['status']==status for row in rows) for name,status in (
            ('new','new'),('duplicate','duplicate'),('failed','failed'))}
        sha=_hash([SCHEMA,scope,generation,signature,rows])
        return dict(schema=SCHEMA,scope=scope,format=format,mode=mode,preview_sha=sha,generation=generation,
            counts=counts,rows=rows,atomic=True,updates_supported=False,
            confirmation_required=True,real_world_confirmed=confirm_real_world)

    def preview(self,scope,payload,*,format='json',mode='append',confirm_real_world=False):
        scope=self._allowed(scope);raw,signature=self._parse(payload,format,mode,confirm_real_world)
        with self.store.transaction():
            self._allowed(scope);result=self._preview(scope,raw,signature,format,mode,confirm_real_world);self._allowed(scope)
        self._allowed(scope);return result

    def _event(self,scope,identity):
        # Existing event table only: hash receipts share the same atomic commit.
        return self.store._db.execute('SELECT fingerprint,record_id FROM tls_native_memory_events WHERE scope=? AND id=?',
            (scope_key(scope),identity)).fetchone()

    def _mark(self,scope,identity,fingerprint,record_id):
        self.store._db.execute('INSERT INTO tls_native_memory_events VALUES(?,?,?,?)',
            (scope_key(scope),identity,fingerprint,record_id))

    def _receipt(self,scope,request_ref,signature,count):
        event=self._event(scope,'mt_batch_'+request_ref)
        if event is None:return None
        try:proof=json.loads(event['fingerprint'])
        except (ValueError,TypeError):raise MemoryTransferConflict('invalid transfer receipt') from None
        if (not isinstance(proof,dict) or set(proof)!={'signature','preview_sha','count'}
                or proof['signature']!=signature or proof['count']!=count
                or not isinstance(proof['preview_sha'],str) or not _SHA.fullmatch(proof['preview_sha'])):
            raise MemoryTransferConflict('transfer request content changed')
        rows=[]
        for index in range(1,count+1):
            created=self._event(scope,'mt_new_'+request_ref+'_'+str(index))
            reused=self._event(scope,'mt_dup_'+request_ref+'_'+str(index))
            if bool(created)==bool(reused):raise MemoryTransferConflict('incomplete transfer receipt')
            source=created or reused
            if source['fingerprint']!=signature:raise MemoryTransferConflict('transfer row receipt differs')
            current=self.store.get(scope,source['record_id'],include_deleted=True)
            if current is None:raise MemoryTransferConflict('transfer record unavailable')
            rows.append(dict(line=index,id=current['id'],revision=current['revision'],lifecycle=current['lifecycle'],
                status='created' if created else 'duplicate',owned=bool(created),
                can_revoke=bool(created) and current['revision']==1 and current['lifecycle']!='deleted',
                undo_expected_revision=1 if created else None))
        return dict(schema=SCHEMA,scope=scope,request_ref=request_ref,preview_sha=proof['preview_sha'],
            created=sum(row['owned'] for row in rows),duplicates=sum(not row['owned'] for row in rows),
            records=rows,generation=self.store.data_generation(scope),physical_delete=False,
            undo='existing_memory_CAS_soft_delete_and_restore',updates_supported=False)

    def import_records(self,scope,payload,*,request_id,preview_sha,confirmed=False,
                       format='json',mode='append',confirm_real_world=False):
        scope=self._allowed(scope)
        if confirmed is not True:raise PermissionError('explicit import confirmation required')
        if not _text(request_id,256) or not isinstance(preview_sha,str) or not _SHA.fullmatch(preview_sha):
            raise ValueError('stable request and preview hash required')
        raw,signature=self._parse(payload,format,mode,confirm_real_world);request_ref=_hash([SCHEMA,scope,request_id])
        with self.store.transaction():
            self._allowed(scope);previous=self._receipt(scope,request_ref,signature,len(raw))
            if previous is not None:self._allowed(scope);return previous
            preview=self._preview(scope,raw,signature,format,mode,confirm_real_world)
            if preview['preview_sha']!=preview_sha:raise MemoryTransferConflict('memory changed since preview')
            if preview['counts']['failed']:raise ValueError('all failed rows must be corrected before import')
            first=None
            for item in preview['rows']:
                self._allowed(scope)
                if item['status']=='new':
                    metadata=dict(tags=item['tags'],memory_transfer=dict(schema=SCHEMA,basis='user_provided_material',
                        created_request_ref=request_ref,source_label=item['source'],
                        source_updated_at=item['source_updated_at'],explicitly_confirmed=True,
                        real_world_confirmed=confirm_real_world))
                    row=self.store.write(scope,item['content'],source_id='memory.imported',
                        evidence_kind=item['evidence_kind'],memory_type=item['memory_type'],record_id=item['id'],metadata=metadata)
                    event='mt_new_'
                else:
                    row=self.store.get(scope,item['id'],include_deleted=True)
                    if row is None:raise MemoryTransferConflict('duplicate disappeared')
                    event='mt_dup_'
                self._mark(scope,event+request_ref+'_'+str(item['line']),signature,row['id']);first=first or row['id']
            self._mark(scope,'mt_batch_'+request_ref,json.dumps(dict(signature=signature,preview_sha=preview_sha,
                count=len(raw)),sort_keys=True,separators=(',',':')),first)
            self._allowed(scope);result=self._receipt(scope,request_ref,signature,len(raw))
        self._allowed(scope);return result

    def export(self,scope,*,limit=200,offset=0):
        scope=self._allowed(scope)
        if type(limit) is not int or not 1<=limit<=MAX_ROWS or type(offset) is not int or offset<0:
            raise ValueError('bounded export page required')
        with self.store.transaction():
            self._allowed(scope);generation=self.store.data_generation(scope)
            source=self.store.list(scope,limit=limit+1,offset=offset);rows=[]
            for row in source[:limit]:
                metadata=row.get('metadata',{});metadata=metadata if isinstance(metadata,dict) else {}
                try:tags=_tags(metadata.get('tags',[]))
                except (ValueError,TypeError):tags=[]
                provenance=metadata.get('memory_transfer',{});provenance=provenance if isinstance(provenance,dict) else {}
                label=provenance.get('source_label')
                item=dict(id=row['id'],content=row['content'],memory_type=row['memory_type'],
                    evidence_kind=row['evidence_kind'],tags=tags,
                    source=label if _text(label,128) else row['source_id'],updated_at=row['updated_at'])
                if len(json.dumps(rows+[item],ensure_ascii=False,indent=2).encode('utf-8'))>MAX_BYTES:break
                rows.append(item)
            content=json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False)
            self._allowed(scope)
        self._allowed(scope)
        return dict(schema=SCHEMA,scope=scope,format='json',content=content,count=len(rows),generation=generation,
            has_more=len(source)>len(rows),next_offset=offset+len(rows) if len(source)>len(rows) else None,
            includes_internal_metadata=False,uploads=0)

    def stop(self):self.active=False
    def close(self):self.stop()  # The shared native memory store is host-owned.

