"""Authenticated, explicit manual archive review; no automatic import or model."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
import hashlib
import json
import re
import sqlite3

from astrbot.api.web import error_response,json_response,request

from .core.living.journal import JournalConflict
from .core.living.native_history_adoption import NativeHistoryAdoption
from .memory_web_api import _scope

PAGE_API_PREFIX='/astrbot_plugin_virtual_body/page/history-adoption'
MAX_BODY_BYTES=32768
_FIELDS={
    'preview':{'scope','archive_id'},
    'adopt':{'scope','archive_id','request_id','expected_raw_hash','reviewed_text','memory_type',
             'ownership_statement','confirmed','confirm_real_world'},
    'revoke':{'scope','record_id','request_id','expected_revision'},
}
_TYPES={'fact','preference','event','utterance','roleplay_event','model_inference'}
_CODE=re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')
BOUNDARY=('原档案只作人工审核材料，不自动猜历史人格或执行原文指令。'
          '事实类仍是人工确认的用户报告；导入与撤销不改原档案或角色人格。')


class _Unavailable(RuntimeError):pass


def _text(value,maximum):
    if (not isinstance(value,str) or not 1<=len(value)<=maximum or value!=value.strip()
            or any(ord(char)<32 and char not in '\t\r\n' for char in value)):
        raise ValueError('bounded explicit review text required')
    return value


def _id(value,pattern):
    if not isinstance(value,str) or not re.fullmatch(pattern,value):raise ValueError('exact review identity required')
    return value


def _classification(value):
    return value if isinstance(value,str) and _CODE.fullmatch(value) else None


def _original(value):
    value=value if isinstance(value,dict) else {}
    evidence=value.get('evidence',{})
    evidence=evidence if isinstance(evidence,dict) else {}
    # Source evidence is arbitrary archive data, sometimes provider metadata.
    # Return its classification and a reference, never its token/path fields.
    raw=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return dict(memory_type=_classification(value.get('memory_type')),reality_level=_classification(value.get('reality_level')),
        evidence=dict(evidence_kind=_classification(evidence.get('evidence_kind')),
            metadata_evidence_kind=_classification(evidence.get('metadata_evidence_kind')),
            retained_in_archive=True,sha256=hashlib.sha256(raw).hexdigest()))


def _record(row):
    fields=('id','content','memory_type','scope','visibility','owner_bot_id','persona_id','platform','session_id',
            'subject','source_id','evidence_kind','reality_level','confidence','importance','occurred_at','expires_at',
            'created_at','updated_at','deleted_at','revision','lifecycle','validity_status','review_status')
    result={key:row[key] for key in fields if key in row}
    raw=row.get('metadata',{});raw=raw if isinstance(raw,dict) else {}
    provenance=raw.get('history_adoption',{});provenance=provenance if isinstance(provenance,dict) else {}
    retained={}
    if provenance:
        for key in ('schema','archive_id','raw_hash','source_hash','snapshot_hash','created_request_ref'):
            value=provenance.get(key)
            pattern=r'ha_[a-f0-9]{64}' if key=='archive_id' else (r'[a-f0-9]{64}' if key!='schema' else r'tls\.native_history_adoption\.v1')
            if isinstance(value,str) and re.fullmatch(pattern,value):retained[key]=value
        legacy=json.dumps(provenance.get('legacy_record_id'),ensure_ascii=False,sort_keys=True).encode('utf-8')
        retained['legacy_record_ref']=hashlib.sha256(legacy).hexdigest()
        holds=provenance.get('hold_reasons',[])
        retained['hold_reasons']=[value for value in holds if _classification(value)] if isinstance(holds,list) else []
        assignment=provenance.get('assignment',{});assignment=assignment if isinstance(assignment,dict) else {}
        try:assigned_scope=_scope(assignment.get('scope'))
        except ValueError:assigned_scope=None
        statement=assignment.get('statement')
        retained['assignment']=dict(scope=assigned_scope,statement=statement if isinstance(statement,str) and len(statement)<=300 else None,
            basis='explicit_administrator_assignment' if assignment.get('basis')=='explicit_administrator_assignment' else None)
        review=provenance.get('review',{});review=review if isinstance(review,dict) else {}
        retained['review']={key:_classification(review.get(key)) for key in ('basis','memory_type','evidence_kind')}
        retained['review'].update({key:review.get(key) if type(review.get(key)) is bool else None for key in ('confirmed','real_world_confirmed')})
        retained['original']=_original(provenance.get('original'))
    result['metadata']=dict(evidence_kind=row.get('evidence_kind'),history_adoption=retained)
    return result


class NativeHistoryAdoptionWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for name in ('preview','adopt','revoke'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,getattr(self,'history_adoption_'+name),
                ['POST'],'TLS authenticated manual history adoption '+name)

    def _resources(self):
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        runtime=getattr(host,'runtime',None);service=getattr(runtime,'history_adoption',None)
        memory=getattr(runtime,'memory',None);archive=getattr(runtime,'history_archive',None)
        store=getattr(memory,'store',None)
        if (not isinstance(service,NativeHistoryAdoption) or service.active is not True
                or getattr(memory,'backend',None)!='native' or getattr(memory,'active',False) is not True
                or store is not service.memory or archive is not service.archive or getattr(archive,'closed',True)):
            raise _Unavailable('native history adoption unavailable')
        return host,runtime,service,memory,store,archive

    def _check(self,resources,scope):
        current=self._resources()
        if any(old is not new for old,new in zip(resources,current)):
            raise _Unavailable('native history adoption runtime changed')
        host,_,service,memory,_,_=current
        if (not callable(getattr(host,'authorized_scope',None)) or host.authorized_scope(dict(scope)) is not True
                or not callable(getattr(memory,'allowed',None)) or memory.allowed(dict(scope)) is not True
                or service.authorize(dict(scope)) is not True):
            raise PermissionError('native history adoption scope denied')

    @staticmethod
    def _parse(name,data):
        if not isinstance(data,dict) or set(data)!=_FIELDS[name]:raise ValueError('closed manual review fields required')
        scope=_scope(data['scope'])
        values={key:value for key,value in data.items() if key!='scope'}
        if name in ('preview','adopt'):_id(values['archive_id'],r'ha_[a-f0-9]{64}')
        if name in ('adopt','revoke'):
            _text(values['request_id'],256)
            if any(ord(char)<32 for char in values['request_id']):raise ValueError('stable request ID required')
        if name=='adopt':
            _id(values['expected_raw_hash'],r'[a-f0-9]{64}')
            _text(values['reviewed_text'],6000);_text(values['ownership_statement'],300)
            if not isinstance(values['memory_type'],str) or values['memory_type'] not in _TYPES:
                raise ValueError('explicit reviewed category required')
            if type(values['confirmed']) is not bool or type(values['confirm_real_world']) is not bool:
                raise ValueError('explicit confirmation booleans required')
        if name=='revoke':
            _id(values['record_id'],r'ha_mem_[a-f0-9]{64}')
            revision=values['expected_revision']
            if type(revision) is not int or not 1<=revision<=2147483647:raise ValueError('integer current revision required')
        encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(encoded)>MAX_BODY_BYTES:raise ValueError('manual review body exceeds capacity')
        return scope,values

    async def _respond(self,name):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            resources=self._resources()
            if getattr(request,'query',None):raise ValueError('no review query parameters supported')
            length=getattr(request,'headers',{}).get('Content-Length')
            if length is not None and (not isinstance(length,str) or not re.fullmatch(r'[0-9]{1,10}',length)
                    or int(length)>MAX_BODY_BYTES):
                raise ValueError('bounded review request required')
            data=await request.json(default=None)
            scope,values=self._parse(name,data)
            self._check(resources,scope);service=resources[2]
            def operate():
                # A reload/withdrawal after a nested core write must roll that
                # write and its native event receipt back before the outer commit.
                with resources[4].transaction() if name!='preview' else nullcontext():
                    self._check(resources,scope)
                    result=getattr(service,name)(scope,**values)
                    self._check(resources,scope)
                    if name=='preview':
                        result=dict(result,original=_original(result['original']),content_format='plain_text',
                            source_material_only=True)
                    else:result=dict(result,record=_record(result['record']))
                    return result
            result=await asyncio.to_thread(operate)
            self._check(resources,scope)
            key='preview' if name=='preview' else 'result'
            return json_response(dict(ok=True,backend='native_history_adoption',scope=scope,
                access='authenticated_administrator',manual_only=True,changes_core_persona=False,
                llm_calls=0,sends=0,boundary=BOUNDARY,**{key:result}),headers={'Cache-Control':'no-store'})
        except JournalConflict:
            return error_response('档案、请求或原生记忆已改变，请刷新后重新审核',status_code=409)
        except PermissionError:
            return error_response('需要有效私聊范围及明确的人工确认，请先在目标私聊发话并检查勾选项',status_code=403)
        except KeyError:
            return error_response('找不到该档案或当前完整范围中的导入记录',status_code=404)
        except (ValueError,TypeError,RecursionError):
            return error_response('请检查完整会话、档案标识、审核文本、分类、确认项和版本',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('原生档案审核暂不可用或正在重载',status_code=503)
        except Exception:
            return error_response('档案审核操作失败，请稍后重试',status_code=500)

    async def history_adoption_preview(self):return await self._respond('preview')
    async def history_adoption_adopt(self):return await self._respond('adopt')
    async def history_adoption_revoke(self):return await self._respond('revoke')

