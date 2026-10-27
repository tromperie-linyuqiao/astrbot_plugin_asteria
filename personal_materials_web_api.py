"""Authenticated current-scope CRUD for TLS-owned explicit long-term agreements."""
from __future__ import annotations
import asyncio
import sqlite3
from astrbot.api.web import error_response,json_response,request
from .core.living.native_memory import MemoryConflict
from .core.living.native_memory_adapter import NativeMemoryAdapter
from .core.living.native_personal_materials import NativePersonalMaterials,EDIT_FIELDS,PersonalImportOutcomeUnknown
from .memory_web_api import SCOPE_FIELDS,_InvalidRequest,_integer,_scope

PREFIX='/astrbot_plugin_virtual_body/page/personal-materials'
class _Unavailable(RuntimeError):pass


class NativePersonalMaterialsWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for name in ('list','export','create','update','archive','restore','preview_import','confirm_import','export_batch'):
            path={'preview_import':'import/preview','confirm_import':'import/confirm','export_batch':'export-batch'}.get(name,name)
            self.plugin.context.register_web_api(PREFIX+'/'+path,getattr(self,name),
                ['GET' if name in {'list','export','export_batch'} else 'POST'],'TLS authenticated personal materials '+name)

    def _components(self,scope):
        if getattr(self.plugin,'_stopping',False):raise _Unavailable('plugin stopping')
        presence=getattr(self.plugin,'_presence',None)
        host=getattr(presence,'living_host',None);runtime=getattr(host,'runtime',None)
        adapter=getattr(runtime,'memory',None)
        if (host is None or getattr(runtime,'active',False) is not True
                or not isinstance(adapter,NativeMemoryAdapter) or adapter.active is not True):
            raise _Unavailable('native personal materials unavailable')
        if (not callable(getattr(host,'authorized_scope',None)) or host.authorized_scope(scope) is not True
                or adapter.allowed(scope) is not True):raise PermissionError('genuine scope unavailable')
        return presence,host,runtime,adapter,adapter.store

    @staticmethod
    def _operation(name,data):
        if not isinstance(data,dict):raise _InvalidRequest('请求必须为JSON对象或合法查询')
        if name in {'list','export','export_batch'}:
            allowed=set(SCOPE_FIELDS)|({'include_archived','limit','offset'} if name in {'list','export_batch'} else {'id'})
            if name=='export_batch':allowed.add('expected_generation')
            if set(data)-allowed:raise _InvalidRequest('查询包含未知字段')
            scope=_scope({key:data.get(key) for key in SCOPE_FIELDS})
            if name=='export':
                if set(data)!=set(SCOPE_FIELDS)|{'id'}:raise _InvalidRequest('导出需要完整范围和id')
                return scope,(data['id'],),{}
            archived=data.get('include_archived',False)
            if isinstance(archived,str) and archived in {'true','false'}:archived=archived=='true'
            if type(archived) is not bool:raise _InvalidRequest('include_archived必须为布尔值')
            options=dict(include_archived=archived,
                limit=_integer(data.get('limit',100 if name=='export_batch' else 20),'limit',1,100),offset=_integer(data.get('offset',0),'offset',0,1000000))
            if name=='export_batch' and 'expected_generation' in data:
                options['expected_generation']=_integer(data['expected_generation'],'expected_generation',0,2147483647)
            return scope,(),options
        scope=_scope(data.get('scope'))
        if name=='preview_import':
            if set(data)!={'scope','payload'}:raise _InvalidRequest('预览仅接受范围和payload')
            return scope,(data['payload'],),{}
        if name=='confirm_import':
            if set(data)!={'scope','payload','preview_sha','request_id','owner_confirmed'}:
                raise _InvalidRequest('确认导入仅接受范围、payload、预览校验、请求id和本人确认')
            return scope,(data['payload'],),{key:data[key] for key in ('preview_sha','request_id','owner_confirmed')}
        if name=='create':
            if set(data)!={'scope','request_id'}|EDIT_FIELDS:raise _InvalidRequest('新建仅接受范围、请求id及约定字段')
            return scope,(),{key:data[key] for key in data if key!='scope'}
        if name=='update':
            if set(data)!={'scope','id','expected_revision'}|EDIT_FIELDS:raise _InvalidRequest('编辑仅接受范围、id、修订和约定字段')
            return scope,(data['id'],),{key:data[key] for key in data if key not in {'scope','id'}}
        if set(data)!={'scope','id','expected_revision'}:raise _InvalidRequest('归档/恢复仅接受范围、id及修订')
        return scope,(data['id'],),{'expected_revision':data['expected_revision']}

    async def _respond(self,name):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过AstrBot管理后台认证',status_code=401)
        try:
            data=dict(getattr(request,'query',None) or {}) if name in {'list','export','export_batch'} else await request.json(default=None)
            scope,args,kwargs=self._operation(name,data);bound=self._components(scope)
            def authorized(current):
                try:return current==scope and all(before is after for before,after in zip(bound,self._components(current)))
                except (PermissionError,RuntimeError):return False
            service=NativePersonalMaterials(bound[-1],authorize=authorized,clock=bound[-2].clock)
            result=await asyncio.to_thread(getattr(service,name),scope,*args,**kwargs)
            service.check(scope)
            body=dict(ok=True,scope=scope,access='authenticated_administrator_and_current_scope')
            if name=='list':body.update(result)
            else:body[{'export':'export','export_batch':'export','preview_import':'preview','confirm_import':'import'}.get(name,'record')]=result
            return json_response(body,headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except PermissionError:return error_response('当前真实会话授权已失效，请先在目标私聊发消息后重试',status_code=403)
        # The page bridge exposes HTTP status only. Preserve the original request
        # on an uncertain outcome; 409 is reserved for a definite stale preview.
        except PersonalImportOutcomeUnknown:return error_response('无法完整确认该批导入结果，请回读记录并重新预览；不要自动更换请求id重发',status_code=503)
        except MemoryConflict:return error_response('约定已被修改、归档或来源发生变化，请刷新后重试',status_code=409)
        except KeyError:return error_response('当前范围中找不到该TLS长期约定',status_code=404)
        except (ValueError,TypeError):return error_response('约定字段无效，请检查标题、正文、标签、开关和修订',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):return error_response('原生资料暂不可用，请稍后重试',status_code=503)
        except Exception:return error_response('长期约定操作失败，请稍后重试',status_code=500)

    async def list(self):return await self._respond('list')
    async def export(self):return await self._respond('export')
    async def create(self):return await self._respond('create')
    async def update(self):return await self._respond('update')
    async def archive(self):return await self._respond('archive')
    async def restore(self):return await self._respond('restore')

    async def preview_import(self):return await self._respond('preview_import')
    async def confirm_import(self):return await self._respond('confirm_import')
    async def export_batch(self):return await self._respond('export_batch')
