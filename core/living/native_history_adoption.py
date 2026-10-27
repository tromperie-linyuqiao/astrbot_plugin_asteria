"""Manual adoption of archive material into the existing native memory store.

The archive remains read-only. A reviewed text and an explicit full private
scope are required; source instructions and missing historical identities are
never executed or inferred. Existing memory transactions/events/history hold
the write, retry and revocation evidence. No schema, worker or model is added.
"""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json
import math
import re
import time

from .journal import JournalConflict
from .models import plain,private_scope,scope_key
from .native_history_archive import NativeHistoryArchive
from .native_memory import NativeMemoryStore

SCHEMA='tls.native_history_adoption.v1'
SOURCE_ID='history.reviewed'
_TYPES={'fact':'user_reported','preference':'user_reported','event':'user_reported',
        'utterance':'user_reported','roleplay_event':'roleplay_event','model_inference':'model_inference'}
_FACT_TYPES={'fact','preference','event'}
_SCOPE_FIELDS={'platform','bot_id','user_id','character_id','session_id','private'}
_SHA=re.compile(r'[a-f0-9]{64}\Z')
_ARCHIVE_ID=re.compile(r'ha_[a-f0-9]{64}\Z')
_RECORD_ID=re.compile(r'ha_mem_[a-f0-9]{64}\Z')


class HistoryAdoptionConflict(JournalConflict):
    """A changed source/request/record, or a request that does not own a row."""


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _hash(value):return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value,label,limit):
    if (not isinstance(value,str) or not 1<=len(value)<=limit or value!=value.strip()
            or any(ord(char)<32 and char not in '\t\r\n' for char in value)):
        raise ValueError('invalid '+label)
    return value


def _scope(value):
    if not isinstance(value,dict) or set(value)!=_SCOPE_FIELDS or value['private'] is not True:
        raise ValueError('complete explicit private scope required')
    scope=private_scope(value)
    if scope!=value or any(not isinstance(value[key],str) or len(value[key])>512 for key in _SCOPE_FIELDS-{'private'}):
        raise ValueError('complete explicit private scope required')
    return scope


def _original(row):
    metadata=row.get('metadata',{})
    if isinstance(metadata,str):
        try:metadata=json.loads(metadata)
        except (ValueError,RecursionError):metadata={}
    metadata=metadata if isinstance(metadata,dict) else {}
    evidence={key:row.get(key) for key in ('evidence_kind','evidence','source_evidence')}
    evidence['metadata_evidence_kind']=metadata.get('evidence_kind')
    evidence['metadata_source_evidence']=metadata.get('source_evidence')
    try:retained=plain(evidence,4096)
    except ValueError:retained=dict(retained_in_archive=True,sha256=_hash(evidence))
    return dict(memory_type=row.get('memory_type'),reality_level=row.get('reality_level'),evidence=retained)


class NativeHistoryAdoption:
    """Synchronous, host-authorized manual operations over two shared stores.

    API callers authenticate the administrator, move I/O to a worker, and supply
    confirmed=True only for the user's explicit import action. authorize is a
    fresh thread-safe full-scope callback, including the native-memory gate.
    """
    backend='native_history_adoption'

    def __init__(self,archive,memory,*,authorize,clock=time.time):
        if not isinstance(archive,NativeHistoryArchive) or not isinstance(memory,NativeMemoryStore) or not callable(authorize):
            raise ValueError('existing native archive, memory and scope authorizer required')
        self.archive,self.memory,self.authorize,self.clock=archive,memory,authorize,clock
        self.active=True

    def _allowed(self,scope):
        scope=_scope(scope)
        if not self.active or self.authorize(scope) is not True:
            raise PermissionError('native history adoption scope unavailable')
        return scope

    def _source(self,archive_id):
        if not isinstance(archive_id,str) or not _ARCHIVE_ID.fullmatch(archive_id):
            raise ValueError('exact native archive ID required')
        source=self.archive.get(archive_id)
        row=source['source_row']
        if (not _SHA.fullmatch(source['raw_hash']) or _hash(row)!=source['raw_hash']
                or row.get('id')!=source['legacy_record_id']
                or archive_id!='ha_'+_hash([source['source_hash'],source['legacy_record_id']])):
            raise HistoryAdoptionConflict('archive source integrity changed')
        return source

    def preview(self,scope,archive_id):
        scope=self._allowed(scope);source=self._source(archive_id)
        now=self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<=253402300799:
            raise ValueError('invalid review clock')
        result=dict(schema=SCHEMA,scope=scope,archive_id=archive_id,raw_hash=source['raw_hash'],
            source_hash=source['source_hash'],snapshot_hash=source['snapshot_hash'],
            content=source['source_row']['content'],original=_original(source['source_row']),
            hold_reasons=list(source['hold_reasons']),
            missing_historical_ownership=[reason for reason in source['hold_reasons'] if reason.startswith('missing_historical_')],
            historical_identity={key:source['source_row'].get(key) for key in
                ('scope','platform','session_id','owner_bot_id','persona_id','user_id')},
            required_fields=['reviewed_text','memory_type','ownership_statement','confirmed'],
            fact_types_require_real_world_confirmation=sorted(_FACT_TYPES),allowed_memory_types=list(_TYPES),
            prepared_fields=dict(scope=scope,source_id=SOURCE_ID,reviewed_text='',memory_type=None,
                evidence_kind=None,ownership_basis='explicit_administrator_assignment'),
            warning='历史归属缺失不会自动补齐；原文只作审核材料。事实类仍是人工确认的用户报告，不是系统观测。',
            previewed_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),writes=0)
        self._allowed(scope)
        return result

    @staticmethod
    def _request(scope,request_id):
        _text(request_id,'stable review request ID',256)
        if any(ord(char)<32 for char in request_id):raise ValueError('invalid stable review request ID')
        return _hash([SCHEMA,scope_key(scope),request_id])

    def _event_record(self,scope,event_id):
        # The concrete store has no public event-reader. Read its existing
        # indexed receipt under transaction(); all writes still use store APIs.
        row=self.memory._db.execute('SELECT record_id FROM tls_native_memory_events WHERE scope=? AND id=?',
            (scope_key(scope),event_id)).fetchone()
        return row['record_id'] if row else None

    @staticmethod
    def _write_fields(original):
        return dict(source_id=SOURCE_ID,evidence_kind=original['evidence_kind'],memory_type=original['memory_type'],
            record_id=original['id'],canonical_key='',confidence=1.,importance=.5,occurred_at=None,expires_at=None,
            metadata=original['metadata'])

    def _original_record(self,scope,current):
        history=self.memory.history(scope,current['id'])
        first=next((item for item in history if item['revision']==1 and item['operation']=='create'),None)
        if not first:raise HistoryAdoptionConflict('native adoption creation evidence missing')
        original=first['record'];meta=original.get('metadata',{}).get('history_adoption',{})
        origin=meta.get('created_request_ref')
        if (original.get('source_id')!=SOURCE_ID or meta.get('schema')!=SCHEMA or meta.get('assignment',{}).get('scope')!=scope
                or not isinstance(origin,str) or not _SHA.fullmatch(origin)
                or self._event_record(scope,'ha_adopt_'+origin)!=original['id']):
            raise HistoryAdoptionConflict('native record is not owned by a history adoption')
        return original,history

    def adopt(self,scope,archive_id,*,request_id,expected_raw_hash,reviewed_text,memory_type,
              ownership_statement,confirmed=False,confirm_real_world=False):
        scope=self._allowed(scope)
        if confirmed is not True:raise PermissionError('explicit manual import confirmation required')
        if type(confirm_real_world) is not bool:raise ValueError('explicit real-world confirmation flag required')
        if not isinstance(memory_type,str) or memory_type not in _TYPES:raise ValueError('explicit reviewed memory classification required')
        if memory_type in _FACT_TYPES and not confirm_real_world:
            raise PermissionError('explicit real-world review confirmation required')
        if memory_type not in _FACT_TYPES and confirm_real_world:
            raise ValueError('real-world confirmation is only for reviewed fact categories')
        _text(reviewed_text,'reviewed memory text',6000);_text(ownership_statement,'manual ownership statement',300)
        if not isinstance(expected_raw_hash,str) or not _SHA.fullmatch(expected_raw_hash):
            raise ValueError('preview archive raw hash required')
        request_ref=self._request(scope,request_id)
        with self.memory.transaction():
            self._allowed(scope);source=self._source(archive_id)
            if source['raw_hash']!=expected_raw_hash:raise HistoryAdoptionConflict('archive changed since preview')
            kind=_TYPES[memory_type]
            provenance=dict(schema=SCHEMA,archive_id=archive_id,raw_hash=source['raw_hash'],
                source_hash=source['source_hash'],snapshot_hash=source['snapshot_hash'],
                legacy_record_id=source['legacy_record_id'],original=_original(source['source_row']),
                hold_reasons=source['hold_reasons'],assignment=dict(scope=scope,statement=ownership_statement,
                    basis='explicit_administrator_assignment'),
                review=dict(basis='explicit_review',memory_type=memory_type,evidence_kind=kind,
                    confirmed=True,real_world_confirmed=confirm_real_world))
            identity=_hash([SCHEMA,scope,reviewed_text,provenance])
            record_id='ha_mem_'+identity
            current=self.memory.get(scope,record_id,include_deleted=True)
            if current is None:
                metadata=dict(evidence_kind=kind,history_adoption=dict(provenance,created_request_ref=request_ref))
                fields=dict(source_id=SOURCE_ID,evidence_kind=kind,memory_type=memory_type,record_id=record_id,metadata=metadata)
                owner_ref=request_ref
            else:
                original,_=self._original_record(scope,current)
                saved=dict(original['metadata']['history_adoption']);saved.pop('created_request_ref',None)
                if saved!=provenance or original['content']!=reviewed_text or original['memory_type']!=memory_type:
                    raise HistoryAdoptionConflict('native adoption identity conflict')
                fields=self._write_fields(original)
                owner_ref=original['metadata']['history_adoption']['created_request_ref']
            written=self.memory.write(scope,reviewed_text,event_id='ha_adopt_'+request_ref,**fields)
            self._allowed(scope)
            state='adopted' if current is None else 'existing'
            if written['lifecycle']=='deleted':
                state='revoked' if written['revision']==2 and self._event_record(scope,'ha_revoke_'+owner_ref)==written['id'] else 'deleted'
            result=dict(schema=SCHEMA,state=state,
                scope=scope,request_ref=request_ref,record_id=written['id'],target_revision=1,
                created=current is None,owned=owner_ref==request_ref,
                record=written,archive_modified=False)
        self._allowed(scope)
        return result

    def revoke(self,scope,record_id,*,request_id,expected_revision):
        scope=self._allowed(scope);request_ref=self._request(scope,request_id)
        if not isinstance(record_id,str) or not _RECORD_ID.fullmatch(record_id):
            raise ValueError('exact adopted native memory ID required')
        if type(expected_revision) is not int or expected_revision<1:raise ValueError('positive current revision required')
        with self.memory.transaction():
            self._allowed(scope);current=self.memory.get(scope,record_id,include_deleted=True)
            if current is None:raise KeyError('adopted native memory not found')
            original,history=self._original_record(scope,current)
            if original['metadata']['history_adoption']['created_request_ref']!=request_ref:
                raise HistoryAdoptionConflict('review request does not own this native record')
            if current['revision']==1:
                if expected_revision!=1 or _hash(current)!=_hash(original):
                    raise HistoryAdoptionConflict('adopted memory changed after import')
                # An indexed native event marks this module's deletion in the
                # same transaction. A later manual delete cannot forge a retry.
                self.memory.write(scope,original['content'],event_id='ha_revoke_'+request_ref,
                    expected_revision=1,**self._write_fields(original))
                written=self.memory.delete(scope,record_id,expected_revision=1)
            else:
                deletion=next((item for item in history if item['revision']==2 and item['operation']=='delete'),None)
                if (current['revision']!=2 or expected_revision not in (1,2) or current['lifecycle']!='deleted'
                        or deletion is None or _hash(current)!=_hash(deletion['record'])
                        or self._event_record(scope,'ha_revoke_'+request_ref)!=record_id):
                    raise HistoryAdoptionConflict('adopted memory changed after import')
                written=current
            self._allowed(scope)
            result=dict(schema=SCHEMA,state='revoked',scope=scope,request_ref=request_ref,record_id=record_id,
                target_revision=1,owned=True,record=written,archive_modified=False,physical_delete=False)
        self._allowed(scope)
        return result

    def stop(self):self.active=False
    def close(self):self.stop()  # Both databases belong to the host.

