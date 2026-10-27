"""Administrator-only explicit scoped memory transfer; synchronous IO in workers."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
import json
import re
import sqlite3

from astrbot.api.web import error_response,json_response,request

from .core.living.journal import JournalConflict
from .core.living.native_memory_transfer import NativeMemoryTransfer
from .memory_web_api import _scope

PAGE_API_PREFIX='/astrbot_plugin_virtual_body/page/memory-transfer'
MAX_BODY_BYTES=1024*1024
_FIELDS={
    'preview':{'scope','payload','format','mode','confirm_real_world'},
    'import':{'scope','payload','format','mode','confirm_real_world','request_id','preview_sha','confirmed'},
    'export':{'scope','limit','offset'},
}
BOUNDARY=('仅向当前授权私聊新增人工导入资料或跳过重复，不自动判真、合并更新、迁移旧档案、调用模型或上传外部。'
          '默认按原话资料保存；事实类需要明确确认。撤销使用原生记忆的版本软删除与恢复。')
ADMIN_BOUNDARY=('仅由已登录管理员向明确选定的完整私聊范围新增资料或跳过重复。'
                '历史资料维护不授予聊天、主动消息或任务发送权；默认原话资料不自动判真。'
                '不合并、不覆盖、不调用模型；撤销与恢复仍使用原生记忆的版本校验。')


class _Unavailable(RuntimeError):pass


class NativeMemoryTransferWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for name in ('preview','import','export'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,getattr(self,'memory_transfer_'+name),
                ['POST'],'TLS authenticated native memory transfer '+name)

    def register_admin_routes(self):
        # Keep the original live-lease routes intact. Historical administration
        # uses the same SDK authentication/extension permission as memory CRUD.
        for name in ('preview','import','export'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/admin-'+name,
                getattr(self,'memory_transfer_admin_'+name),['POST'],
                'TLS authenticated administrator historical memory '+name)

    def _resources(self):
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        runtime=getattr(host,'runtime',None);service=getattr(runtime,'memory_transfer',None)
        memory=getattr(runtime,'memory',None);store=getattr(memory,'store',None)
        if (not isinstance(service,NativeMemoryTransfer) or service.active is not True
                or getattr(memory,'backend',None)!='native' or getattr(memory,'active',False) is not True
                or service.store is not store or getattr(store,'_closed',True)):
            raise _Unavailable('native memory transfer unavailable')
        return host,runtime,service,memory,store

    def _same_resources(self,resources):
        current=self._resources()
        if any(old is not new for old,new in zip(resources,current)):
            raise _Unavailable('native memory transfer runtime changed')
        return current

    def _check(self,resources,scope):
        current=self._same_resources(resources)
        host,_,service,memory,_=current
        if (not callable(getattr(host,'authorized_scope',None)) or host.authorized_scope(dict(scope)) is not True
                or not callable(getattr(memory,'allowed',None)) or memory.allowed(dict(scope)) is not True
                or service.authorize(dict(scope)) is not True):
            raise PermissionError('native memory transfer scope denied')

    def _admin_service(self,resources,scope):
        # Operation-local authority is limited to the parsed full private scope
        # and this exact live store. Do not mutate the runtime recall/send ACL,
        # fabricate an inbound identity lease, or open a second SQLite store.
        expected=dict(scope)
        def authorize(candidate):
            self._same_resources(resources)
            return candidate==expected
        return NativeMemoryTransfer(resources[4],authorize=authorize,clock=resources[2].clock)

    @staticmethod
    def _parse(name,data):
        if not isinstance(data,dict) or set(data)!=_FIELDS[name]:
            raise ValueError('closed transfer fields required')
        if len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8'))>MAX_BODY_BYTES:
            raise ValueError('bounded transfer request required')
        scope=_scope(data['scope']);values={key:value for key,value in data.items() if key!='scope'}
        if name=='export':
            if type(values['limit']) is not int or not 1<=values['limit']<=200 or type(values['offset']) is not int or values['offset']<0:
                raise ValueError('bounded export page required')
        else:
            if (not isinstance(values['payload'],str) or not isinstance(values['format'],str)
                    or values['format'] not in {'json','text','csv'} or values['mode']!='append'
                    or type(values['confirm_real_world']) is not bool):
                raise ValueError('append-only explicit material required')
            if name=='import':
                if (type(values['confirmed']) is not bool or not isinstance(values['request_id'],str)
                        or not 1<=len(values['request_id'])<=256 or not isinstance(values['preview_sha'],str)
                        or not re.fullmatch(r'[a-f0-9]{64}',values['preview_sha'])):
                    raise ValueError('stable transfer request and preview required')
        return scope,values

    async def _respond(self,name,*,administrative=False):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        local_service=None
        try:
            resources=self._resources()
            if getattr(request,'query',None):raise ValueError('transfer query unsupported')
            length=getattr(request,'headers',{}).get('Content-Length')
            if length is not None and (not isinstance(length,str) or not re.fullmatch(r'[0-9]{1,10}',length)
                    or int(length)>MAX_BODY_BYTES):
                raise ValueError('bounded transfer request required')
            data=await request.json(default=None)
            scope,values=self._parse(name,data)
            def check():
                if administrative:
                    self._same_resources(resources)
                    if local_service is not None and local_service.active is not True:
                        raise PermissionError('administrator operation ended')
                else:self._check(resources,scope)
            check()
            if administrative:
                local_service=self._admin_service(resources,scope)
            service=local_service if administrative else resources[2]
            def operate():
                # Keep the runtime/authority check inside the same atomic store
                # commit, including replacement after a nested core write.
                with resources[4].transaction() if name=='import' else nullcontext():
                    check()
                    function=service.import_records if name=='import' else getattr(service,name)
                    result=function(scope,**values)
                    check()
                    return result
            result=await asyncio.to_thread(operate)
            check()
            return json_response(dict(ok=True,backend='native_memory_transfer',scope=scope,
                access='authenticated_administrator',manual_only=True,changes_core_persona=False,
                llm_calls=0,sends=0,uploads=0,
                authority='historical_administrator' if administrative else 'live_private_scope',
                boundary=ADMIN_BOUNDARY if administrative else BOUNDARY,
                **{'preview' if name=='preview' else 'result':result}),headers={'Cache-Control':'no-store'})
        except JournalConflict:
            return error_response('预览后的记忆或相同请求内容已改变，请重新预览',status_code=409)
        except PermissionError:
            return error_response('需要明确的管理员导入确认，请核对当前后台登录与选定范围' if administrative
                else '需要有效私聊授权与明确导入确认，请先在目标私聊发话',status_code=403)
        except (ValueError,TypeError,RecursionError,UnicodeError):
            return error_response('请检查 JSON数组、行文本或CSV；最多200条、128KiB；仅支持新增和跳过重复，未知字段需修正',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('原生记忆批量操作暂不可用或正在重载',status_code=503)
        except Exception:
            return error_response('原生记忆批量操作失败，请稍后重试',status_code=500)
        finally:
            if local_service is not None:local_service.close()

    async def memory_transfer_preview(self):return await self._respond('preview')
    async def memory_transfer_import(self):return await self._respond('import')
    async def memory_transfer_export(self):return await self._respond('export')

    async def memory_transfer_admin_preview(self):return await self._respond('preview',administrative=True)
    async def memory_transfer_admin_import(self):return await self._respond('import',administrative=True)
    async def memory_transfer_admin_export(self):return await self._respond('export',administrative=True)

