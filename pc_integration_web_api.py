"""AstrBot-authenticated entrypoints for selected native PC responsibilities.

Admin read is historical scoped read only. Writes still need the host's live
source owner; explicit consent uses the existing closed-to-TLS CAS and consent journal.
No public endpoint accepts a claimed legacy pending-task disposition.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import sqlite3
from astrbot.api.web import request, json_response, error_response
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope, _text
from .core.living.journal import JournalConflict
from .core.living.delivery_store import DeliveryConflict
from .core.living.models import canonical
from .core.living.native_memo_notes import _time
from .core.living.native_pc_integration import NativePCIntegration

PREFIX='/astrbot_plugin_virtual_body/page/pc-integration'
MAX_BODY_BYTES=16384


class NativePCIntegrationWebApi:
    def __init__(self,plugin): self.plugin=plugin

    def register_routes(self):
        for name,path,method in [('status','status','GET'),('memo_bind','memo/bind','POST'),
            ('memo_complete','memo/complete','POST'),('timer_adopt','timer/adopt','POST')]:
            self.plugin.context.register_web_api(PREFIX+'/'+path,getattr(self,name),[method],
                'TLS native PC integration '+path)

    def _resources(self):
        service=getattr(self.plugin,'_native_pc_integration',None)
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        runtime=getattr(host,'runtime',None)
        if (getattr(self.plugin,'_stopping',False) or getattr(host,'_closed',True)
                or not isinstance(service,NativePCIntegration) or service.active is not True
                or getattr(runtime,'active',False) is not True
                or service.memos.active is not True
                or service.nonrandom is not None and service.nonrandom.active is not True
                or service.memos.notes is not getattr(runtime,'memo_notes',None)
                or service.memos.reminders is not getattr(runtime,'reminders',None)
                or service.nonrandom is not None and (service.nonrandom.proactive is not getattr(runtime,'proactive_companion',None)
                    or service.nonrandom.dates is not getattr(runtime,'important_dates',None))
                or service.memos.journal is not getattr(runtime,'journal',None)):
            raise RuntimeError('native PC integration unavailable')
        return service,host,runtime

    def _same(self,resources):
        if any(a is not b for a,b in zip(resources,self._resources())): raise RuntimeError('native PC integration changed')

    @staticmethod
    def _revision(value):
        if type(value) is not int or not 1<=value<2**53: raise _InvalidRequest('请先读取当前便签版本')
        return value

    @staticmethod
    def _operation(action,data):
        if type(data) is not dict or len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode())>MAX_BODY_BYTES:
            raise _InvalidRequest('请提交大小适当的合法对象')
        if action=='status':
            if set(data)!=set(SCOPE_FIELDS): raise _InvalidRequest('请选择完整私聊范围')
            return _scope(data),{}
        scope=_scope(data.get('scope'))
        if action in {'memo_bind','timer_adopt'} and data.get('consent') is not True:
            raise JournalConflict('explicit user consent is required')
        fields={
            'memo_bind':{'scope','id','expected_revision','consent'},
            'memo_complete':{'scope','id','expected_revision','request_id'},
            'timer_adopt':{'scope','request_id','due_at','text','consent'},
        }[action]
        if set(data)!=fields: raise _InvalidRequest('操作需要完整参数，不接受旧队列或来源认领字段')
        result={key:data[key] for key in data if key!='scope'}
        if 'consent' in result and result['consent'] is not True:
            raise JournalConflict('explicit user consent is required')
        if 'id' in result: result['id']=_text(result['id'],'便签ID',100)
        if 'expected_revision' in result: result['expected_revision']=NativePCIntegrationWebApi._revision(result['expected_revision'])
        if 'request_id' in result: result['request_id']=_text(result['request_id'],'request_id',128)
        if action=='timer_adopt':
            result['due_at']=_time(result['due_at'],zero=False)
            if type(result['text']) is not str or not 1<=len(result['text'].strip())<=3900:
                raise _InvalidRequest('请填写不超过3900字的事项')
        return scope,result

    async def _respond(self,action):
        try: username=getattr(request,'username',None)
        except RuntimeError: username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过AstrBot管理后台认证',status_code=401)
        try:
            resources=self._resources(); service=resources[0]
            if action=='status': data=dict(getattr(request,'query',None) or {})
            else:
                if getattr(request,'query',None): raise _InvalidRequest('写操作不接受查询参数')
                length=getattr(request,'headers',{}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii() or not length.isdigit() or len(length)>10 or int(length)>MAX_BODY_BYTES):
                    raise _InvalidRequest('请求过大')
                data=await request.json(default=None)
            scope,args=self._operation(action,data); self._same(resources)
            if action=='status':
                result=await asyncio.to_thread(service.memos.status,scope,administrator=True)
                result=dict(result,nonrandom=service.nonrandom.diagnostics() if service.nonrandom is not None else dict(active=False),read_only=True,
                    snapshot_atomic_across_databases=False)
            elif action=='memo_bind':
                def bind():
                    self._same(resources)
                    note=service.memos.notes.get(scope,args['id'])
                    if note is None: raise KeyError('memo absent')
                    if (note['provenance']['kind'] not in {'user_explicit','user_requested_ai_tool'}
                            or note['archived'] or note['status']!='active' or not note['fields']['remind_enabled'] or note['fields']['due_at']<=0):
                        raise PermissionError('public bind requires an explicit native active reminder definition')
                    old=service.memos._read('tls.native.pc.memo_execution.v1',note['id'],scope)
                    if old and old['data']['phase']=='unknown': raise JournalConflict('existing unknown delivery retained')
                    if old:
                        current=service.memos._occurrence(scope,old['data']); task=service.memos._task(current)
                        if task and task['state'] in {'unknown','quarantined','sending'}: raise JournalConflict('existing delivery needs reconciliation')
                    if note['revision']!=args['expected_revision']: raise JournalConflict('memo revision changed')
                    consent=service.memos.prepare_explicit_new_consent(scope,source='memo_note',consent=args['consent'])
                    result=service.memos.bind_memo(scope,note['id'],expected_revision=args['expected_revision'],
                        consent_id=consent['consent_id'],legacy_disposition='not_pending')
                    stored=service.memos._read('tls.native.pc.memo_execution.v1',note['id'],scope)
                    if stored is None or stored['data']!=result: raise RuntimeError('memo execution binding readback mismatch')
                    current=next((row for row in service.memos.status(scope)['records'] if row['memo_id']==note['id']),None)
                    if current is None: raise RuntimeError('memo binding status readback absent')
                    self._same(resources)
                    return dict(binding=result,binding_revision=stored['revision'],binding_verified=True,current=current,
                        state='bound_awaiting_host_tick',**consent)
                result=await asyncio.to_thread(bind)
            elif action=='memo_complete':
                result=dict(record=await service.memos.complete_memo(scope,args['id'],
                    expected_revision=args['expected_revision'],request_id=args['request_id']))
            else:
                # Public creation has a distinct TLS namespace. An old timer ID
                # and not_pending/UNKNOWN assertion cannot be supplied by JS.
                timer_id='tls.web.timer.'+hashlib.sha256(canonical([scope,args['request_id']]).encode()).hexdigest()
                prior=service.memos.timer_request(scope,timer_id); now=service.memos.clock()
                if prior is None and not now<=args['due_at']<=now+366*86400:
                    raise _InvalidRequest('新约定需要未来一年内的明确时间')
                consent=await asyncio.to_thread(service.memos.prepare_explicit_new_consent,scope,source='timer',consent=args['consent'])
                result=dict(record=await service.memos.adopt_timer(scope,timer_id,due_at=args['due_at'],
                    text=args['text'],consent_id=consent['consent_id'],legacy_disposition='not_pending'),**consent)
            self._same(resources)
            body=dict(result)
            body.update(ok=True,backend='tls_native_pc_integration',scope=scope,access='authenticated_administrator',
                delivery_confirmed=False,external_record_modified=False,creates_private_scope=False,
                grants_execution=body.get('owner_changed',False),execution_scope='new_explicit_tls_tasks_only')
            return json_response(body,headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc: return error_response(str(exc),status_code=400)
        except (JournalConflict,DeliveryConflict):
            return error_response('版本、原执行结果或现有提醒授权需要核对；保留原请求后回读，不要重复提交',status_code=409)
        except PermissionError: return error_response('当前事项的原生执行权或真实私聊权限尚不可用',status_code=403)
        except KeyError: return error_response('完整范围内找不到该便签',status_code=404)
        except (ValueError,TypeError,UnicodeError,RecursionError): return error_response('参数无效，未认领任何旧任务',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('服务变化或结果尚未确认；请保留原请求并回读核查',status_code=503)
        except Exception: return error_response('操作尚未确认，请保留原请求后核查',status_code=500)

    async def status(self): return await self._respond('status')
    async def memo_bind(self): return await self._respond('memo_bind')
    async def memo_complete(self): return await self._respond('memo_complete')
    async def timer_adopt(self): return await self._respond('timer_adopt')
