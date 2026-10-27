"""Authenticated scoped diagnostics and explicit logical material maintenance.

No old tool, source path, caller-supplied SQL, LLM or repair action is accepted.
The service is request-local and owns no connections or background lifecycle.
"""
from __future__ import annotations

import asyncio
import sqlite3

from astrbot.api.web import error_response,json_response,request

from .core.living.native_material_diagnostics import NativeMaterialDiagnostics,MaterialDiagnosticsConflict
from .core.living.native_memory_adapter import NativeMemoryAdapter
from .core.living.native_history_archive import NativeHistoryArchive
from .core.living.native_material_maintenance import NativeMaterialMaintenance,MaintenanceOutcomeUnknown,MAX_BYTES
from .core.living.journal import LivingJournal,JournalConflict
from .core.living.native_memory import MemoryConflict,NativeMemoryStore
from .core.living.native_personal_goals import NativePersonalGoals
import json
from .memory_web_api import SCOPE_FIELDS,_InvalidRequest,_integer,_scope

PREFIX='/astrbot_plugin_virtual_body/page/material-maintenance'


class _Unavailable(RuntimeError):pass


class NativeMaterialMaintenanceWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        self.plugin.context.register_web_api(PREFIX+'/preview',self.preview,['GET'],
            'TLS authenticated read-only material diagnostics')
        for path,name,method in [('status','status','GET'),('export','export','POST'),
                ('restore/preview','restore_preview','POST'),('restore/confirm','restore_confirm','POST'),
                ('repair/preview','repair_preview','POST'),('repair/confirm','repair_confirm','POST'),
                ('receipt','receipt','GET'),('records','records','GET'),
                ('bulk/preview','bulk_preview','POST'),('bulk/confirm','bulk_confirm','POST')]:
            self.plugin.context.register_web_api(PREFIX+'/'+path,getattr(self,name),[method],
                'TLS scoped explicit logical material maintenance '+name)

    def _maintenance(self,scope):
        bound=self._admin_components(scope)
        host,runtime,memory,store,_=bound
        journal=getattr(host,'journal',None)
        if not isinstance(journal,LivingJournal) or getattr(journal,'_closed',True):journal=None
        goals=getattr(runtime,'personal_goals',None)
        if not isinstance(goals,NativePersonalGoals) or not goals.active:goals=None
        def authorized(current):
            try:
                now=self._admin_components(current)
                return (current==scope and all(a is b for a,b in zip(bound,now))
                    and (journal is None or getattr(host,'journal',None) is journal and not journal._closed)
                    and (goals is None or getattr(runtime,'personal_goals',None) is goals and goals.active))
            except (PermissionError,RuntimeError):return False
        # Match the existing personal-goals administrator view: this new
        # request-local manager shares the same journal, without replacing the
        # runtime reader's authorize callback or granting a Presence lease.
        admin_goals=(NativePersonalGoals(journal,authorize=authorized,clock=goals.clock,
            timezone=goals.timezone_name,max_goals=goals.max_goals)
            if goals is not None and journal is not None and goals.journal is journal else None)
        return NativeMaterialMaintenance(store,authorize=authorized,journal=journal,goals=admin_goals,
            clock=getattr(host,'clock',store.clock))

    def _admin_components(self,scope):
        """Existing memory-page admin boundary; no runtime chat authority."""
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            raise PermissionError('normal administrator request required')
        if getattr(self.plugin,'_stopping',False):raise _Unavailable('plugin stopping')
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        runtime=getattr(host,'runtime',None);memory=getattr(runtime,'memory',None)
        store=getattr(memory,'store',None)
        if (host is None or getattr(host,'_closed',False) or getattr(runtime,'active',False) is not True
                or not isinstance(memory,NativeMemoryAdapter) or memory.active is not True
                or not isinstance(store,NativeMemoryStore) or getattr(store,'_closed',True)):
            raise _Unavailable('native administrator material resources unavailable')
        archive=getattr(runtime,'history_archive',None)
        if not isinstance(archive,NativeHistoryArchive) or archive.closed or archive.retrieval_enabled is not False:archive=None
        return host,runtime,memory,store,archive

    async def _workflow(self,name):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            if name in {'status','receipt','records'}:
                data=dict(getattr(request,'query',None) or {})
                allowed=set(SCOPE_FIELDS)|({'request_id'} if name=='receipt' else
                    {'include_archived','limit','offset'} if name=='records' else set())
                if set(data)-allowed:raise _InvalidRequest('维护查询含未知字段')
                scope=_scope({key:data.get(key) for key in SCOPE_FIELDS})
                options={'request_id':data.get('request_id')} if name=='receipt' else {}
                if name=='records':
                    archived=data.get('include_archived',False)
                    if isinstance(archived,str) and archived in {'true','false'}:archived=archived=='true'
                    if type(archived) is not bool:raise _InvalidRequest('include_archived 必须为布尔值')
                    options=dict(include_archived=archived,limit=_integer(data.get('limit',20),'limit',1,20),
                        offset=_integer(data.get('offset',0),'offset',0,1000000))
            else:
                data=await request.json(default=None)
                if type(data) is not dict or len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode())>MAX_BYTES+8192:
                    raise _InvalidRequest('维护请求必须为有界 JSON 对象')
                allowed={'scope'}|{
                    'export':{'kinds','limit','offset'},'restore_preview':{'bundle','kind'},
                    'restore_confirm':{'bundle','kind','preview_sha256','request_id','confirmed'},
                    'repair_preview':{'limit'},'repair_confirm':{'limit','preview_sha256','request_id','confirmed'},
                    'bulk_preview':{'operation','items'},
                    'bulk_confirm':{'operation','items','preview_sha256','request_id','confirmed'}}[name]
                if set(data)-allowed:raise _InvalidRequest('维护请求含未知字段')
                scope=_scope(data.get('scope'));options={key:value for key,value in data.items() if key!='scope'}
            service=self._maintenance(scope)
            result=await asyncio.to_thread(getattr(service,name),scope,**options)
            service.check(scope)
            return json_response(dict(ok=True,scope=scope,maintenance=result,
                access='authenticated_administrator',administration_does_not_grant_runtime_scope=True),
                headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except PermissionError:return error_response('管理员请求资源已变化或明确确认缺失，请重新读取并检查确认项',status_code=403)
        except MaintenanceOutcomeUnknown:return error_response('原请求可能已经写入；请保留请求ID并查询回执，不要自动重发',status_code=503)
        except (JournalConflict,MemoryConflict,MaterialDiagnosticsConflict):return error_response('预览或资料已变化、存在冲突；请重新预览，不覆盖原记录',status_code=409)
        except (ValueError,TypeError,KeyError):return error_response('备份校验、范围、资料类型或维护参数无效',status_code=400)
        except (RuntimeError,OSError,sqlite3.Error):return error_response('维护服务暂不可用；若提交过确认请先核对回执',status_code=503)
        except Exception:return error_response('维护操作结果未能完整确认，请保留请求ID核对',status_code=500)

    async def status(self):return await self._workflow('status')
    async def export(self):return await self._workflow('export')
    async def restore_preview(self):return await self._workflow('restore_preview')
    async def restore_confirm(self):return await self._workflow('restore_confirm')
    async def repair_preview(self):return await self._workflow('repair_preview')
    async def repair_confirm(self):return await self._workflow('repair_confirm')
    async def receipt(self):return await self._workflow('receipt')
    async def records(self):return await self._workflow('records')
    async def bulk_preview(self):return await self._workflow('bulk_preview')
    async def bulk_confirm(self):return await self._workflow('bulk_confirm')

    def _components(self,scope):
        if getattr(self.plugin,'_stopping',False):raise _Unavailable('plugin stopping')
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        runtime=getattr(host,'runtime',None);memory=getattr(runtime,'memory',None)
        if (host is None or getattr(runtime,'active',False) is not True
                or not isinstance(memory,NativeMemoryAdapter) or memory.active is not True):
            raise _Unavailable('native memory runtime unavailable')
        if (not callable(getattr(host,'authorized_scope',None)) or host.authorized_scope(scope) is not True
                or memory.allowed(scope) is not True):
            raise PermissionError('genuine scope unavailable')
        archive=getattr(runtime,'history_archive',None)
        if not isinstance(archive,NativeHistoryArchive) or archive.closed or archive.retrieval_enabled is not False:archive=None
        return host,runtime,memory,memory.store,archive

    @staticmethod
    def _options(data):
        if not isinstance(data,dict) or set(data)-set(SCOPE_FIELDS)-{'limit','include_archive'}:
            raise _InvalidRequest('体检仅接受完整会话范围、扫描上限和历史统计开关')
        scope=_scope({key:data.get(key) for key in SCOPE_FIELDS})
        limit=_integer(data.get('limit',200),'limit',1,1000)
        include=data.get('include_archive',True)
        if isinstance(include,str) and include in {'true','false'}:include=include=='true'
        if type(include) is not bool:raise _InvalidRequest('include_archive 必须为布尔值')
        return scope,limit,include

    async def preview(self):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            data=dict(getattr(request,'query',None) or {})
            scope,limit,include=self._options(data)
            bound=self._components(scope)
            def authorized(current_scope):
                try:return current_scope==scope and all(before is after for before,after in zip(bound,self._components(current_scope)))
                except (PermissionError,RuntimeError):return False
            service=NativeMaterialDiagnostics(bound[3],archive=bound[4],authorize=authorized)
            result=await asyncio.to_thread(service.preview,scope,limit=limit,include_archive=include)
            service.check(scope)
            return json_response(dict(ok=True,access='authenticated_administrator_and_current_scope',**result),
                headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except PermissionError:return error_response('请先在目标私聊中发一条消息，建立当前会话授权后查看体检',status_code=403)
        except MaterialDiagnosticsConflict:return error_response('资料库正处于其它事务，请稍后刷新',status_code=409)
        except (ValueError,TypeError):return error_response('资料或体检参数无效，请检查完整范围',status_code=400)
        except (RuntimeError,OSError,sqlite3.Error):return error_response('原生资料服务暂不可用，请稍后刷新',status_code=503)
        except Exception:return error_response('资料体检失败，请稍后重试',status_code=500)
