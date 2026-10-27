"""Administrator API for TLS single/recurring agenda on the existing authority."""
from __future__ import annotations

import asyncio
import sqlite3

from astrbot.api.web import error_response,json_response,request

from .core.living.delivery_store import DeliveryConflict
from .core.living.native_agenda import NativeAgenda
from .memory_web_api import SCOPE_FIELDS,_InvalidRequest,_integer,_scope,_text

PAGE_API_PREFIX='/astrbot_plugin_virtual_body/page/agenda'


class NativeAgendaWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for name in ('list','detail','create','cancel','update','restore'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,getattr(self,'agenda_'+name),
                ['GET' if name in ('list','detail') else 'POST'],'TLS native authenticated agenda '+name)

    def _agenda(self):
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        agenda=getattr(getattr(host,'runtime',None),'agenda',None)
        if not isinstance(agenda,NativeAgenda) or not agenda.active or not agenda.reminders.active:
            raise RuntimeError('native agenda unavailable')
        return agenda

    @staticmethod
    def _operation(name,data):
        if not isinstance(data,dict):raise _InvalidRequest('请求正文必须是 JSON 对象')
        if name in ('list','detail'):
            allowed=set(SCOPE_FIELDS)|({'limit','offset'} if name=='list' else {'id'})
            if set(data)-allowed:raise _InvalidRequest('日程查询含未知字段')
            scope=_scope({key:data.get(key) for key in SCOPE_FIELDS})
            if name=='list':return scope,(),dict(limit=_integer(data.get('limit',50),'limit',1,100),offset=_integer(data.get('offset',0),'offset',0,1000000))
            return scope,(_text(data.get('id'),'日程 ID',128),),{}
        allowed=({'scope','request_id','due_at','content'} if name=='create' else
            {'scope','id','expected_revision','due_at','content'} if name in ('update','restore') else {'scope','id','expected_revision'})
        optional={'repeat','timezone'} if name in ('create','update','restore') else set()
        if not allowed<=set(data) or set(data)-(allowed|optional):raise _InvalidRequest('日程操作需要完整参数，不能提交其他任务或便签字段')
        recurrence={key:data[key] for key in optional if key in data}
        if 'repeat' in recurrence and (not isinstance(recurrence['repeat'],str) or recurrence['repeat'] not in {'none','daily','weekly','monthly','yearly'}):
            raise _InvalidRequest('周期须为单次、每天、每周、每月或每年')
        if 'timezone' in recurrence and (not isinstance(recurrence['timezone'],str) or not 1<=len(recurrence['timezone'])<=80):
            raise _InvalidRequest('周期日程需要明确有效时区')
        scope=_scope(data['scope'])
        if name=='create':return scope,(_text(data['request_id'],'request_id',256),),dict(
            due_at=_text(data['due_at'],'带时区的日程时间',64),text=_text(data['content'],'日程内容',3000),**recurrence)
        if name in ('update','restore'):return scope,(_text(data['id'],'日程 ID',128),),dict(
            expected_revision=_integer(data['expected_revision'],'expected_revision',1,2147483647),
            due_at=_text(data['due_at'],'带时区的日程时间',64),text=_text(data['content'],'日程内容',3000),**recurrence)
        return scope,(_text(data['id'],'日程 ID',128),),dict(expected_revision=_integer(data['expected_revision'],'expected_revision',1,2147483647))

    async def _respond(self,name):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            agenda=self._agenda()
            data=dict(getattr(request,'query',None) or {}) if name in ('list','detail') else await request.json(default=None)
            scope,args,kwargs=self._operation(name,data)
            if self._agenda() is not agenda:raise RuntimeError('native agenda replaced')
            if name in ('list','detail'):
                def read():
                    if self._agenda() is not agenda:raise RuntimeError('native agenda replaced')
                    return getattr(agenda,'get' if name=='detail' else 'list')(scope,*args,**kwargs)
                result=await asyncio.to_thread(read)
                if name=='detail' and result is None:raise KeyError('native agenda absent')
            else:result=await getattr(agenda,name)(scope,*args,**kwargs)
            if self._agenda() is not agenda:raise RuntimeError('native agenda replaced')
            periodic=bool(isinstance(result,dict) and result.get('metadata',{}).get('periodic'))
            return json_response(dict(ok=True,backend='native_agenda',access='authenticated_administrator',scope=scope,
                **{'records' if name=='list' else 'record':result},single_occurrence=not periodic,periodic=periodic,
                recurring_supported=True,recurrence_options=['daily','weekly','monthly','yearly'],
                legacy_migrated=False,linked_note_completion=False,llm_calls=0),headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except DeliveryConflict:return error_response('日程版本、请求 ID 或执行状态已改变，请刷新后重试',status_code=409)
        except PermissionError:return error_response('请先在目标私聊中发一条消息，建立当前完整会话授权后再管理日程',status_code=403)
        except KeyError:return error_response('当前会话中找不到该 TLS 原生日程',status_code=404)
        except ValueError:return error_response('请检查带时区的未来时间、内容、请求 ID 和版本',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):return error_response('请启用 TLS 原生提醒服务；当前日程暂不可用',status_code=503)
        except Exception:return error_response('原生日程操作失败，请稍后重试',status_code=500)

    async def agenda_list(self):return await self._respond('list')
    async def agenda_detail(self):return await self._respond('detail')
    async def agenda_create(self):return await self._respond('create')
    async def agenda_cancel(self):return await self._respond('cancel')
    async def agenda_update(self):return await self._respond('update')
    async def agenda_restore(self):return await self._respond('restore')
