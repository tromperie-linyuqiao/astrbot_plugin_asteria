"""Authenticated operator view/CAS for the existing native core-tool owner.

Never changes MC configuration, seeds Presence or constructs a memory store.
The ordinary conversational tool cannot access owner transitions.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope
from .core.living.native_core_tools import NativeCoreTools
from .core.living.native_core_handoff import capture_core_handoff, capture_core_inventory
from .core.living.native_core_task_diagnostics import observe_task_diagnostics
from .core.living.native_memory import MemoryConflict

PREFIX='/astrbot_plugin_virtual_body/page/core-tools'
SHA=re.compile(r'[a-f0-9]{64}\Z')


class NativeCoreToolsWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        self.plugin.context.register_web_api(PREFIX+'/status',self.status,['GET'],'TLS authenticated core-tool handoff status')
        self.plugin.context.register_web_api(PREFIX+'/transition',self.transition,['POST'],'TLS authenticated core-tool owner CAS')
        self.plugin.context.register_web_api(PREFIX+'/task-diagnostics',self.task_diagnostics,['GET'],'TLS authenticated read-only task shapes')

    def _resources(self):
        service=getattr(self.plugin,'_native_core_tools',None)
        if not isinstance(service,NativeCoreTools) or service.active is not True:
            raise RuntimeError('native core tools unavailable')
        resources=self.plugin._core_tool_resources()
        if service.store is not resources[-1]:raise RuntimeError('native core store changed')
        return (*resources,service)

    def _same(self,bound):
        try:return all(a is b for a,b in zip(bound,self._resources()))
        except Exception:return False

    async def _respond(self,transition=False):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过AstrBot管理后台认证',status_code=401)
        try:
            if transition:
                data=await request.json(default=None)
                if not isinstance(data,dict):raise _InvalidRequest('需要JSON对象')
                mode=data.get('mode')
                fields={'scope','mode','expected_generation'}
                if mode=='native':fields|={'expected_mc_config_sha256','expected_legacy_inventory_sha256'}
                if set(data)!=fields or mode not in {'closed','native'}:raise _InvalidRequest('请提交指定的归属变更字段')
                scope=_scope(data['scope']);generation=data['expected_generation']
                if type(generation) is not int or not 0<=generation<=2147483647:raise _InvalidRequest('需要准确归属修订')
                if mode=='native' and any(not isinstance(data[key],str) or not SHA.fullmatch(data[key])
                        for key in ('expected_mc_config_sha256','expected_legacy_inventory_sha256')):
                    raise _InvalidRequest('需要准确配置和来源清单校验值')
            else:
                data=dict(getattr(request,'query',None) or {})
                if set(data)!=set(SCOPE_FIELDS):raise _InvalidRequest('需要明确五项完整私聊范围')
                scope=_scope(data)
            bound=self._resources();service=bound[-1]
            if (transition and mode=='native' and (bound[1].authorized_scope(scope) is not True
                    or bound[3].allowed(scope) is not True)):
                raise PermissionError('genuine activation scope required')
            observed,gate=capture_core_handoff(self.plugin.context)
            inventory_status=None;inventory=None
            if gate is not None and (not transition or mode=='native'):
                inventory_status,inventory=await asyncio.wait_for(capture_core_inventory(gate),timeout=3.)
            if not self._same(bound):raise RuntimeError('native core resources changed')
            if transition:
                if mode=='native':
                    if gate is None or inventory is None:raise PermissionError('legacy handoff not ready')
                    if (data['expected_mc_config_sha256']!=gate.proof['config_sha256']
                            or data['expected_legacy_inventory_sha256']!=inventory.proof['inventory_sha256']):
                        raise MemoryConflict('reviewed core handoff proof changed')
                result=await asyncio.to_thread(service.transition,scope,mode=mode,expected_generation=generation,
                    gate=gate,inventory=inventory,administrator_authorized=lambda candidate:candidate==scope and self._same(bound))
            else:
                result=await asyncio.to_thread(service.owner,scope)
            if not self._same(bound):raise RuntimeError('native core resources changed')
            return json_response(dict(ok=True,owner=result,handoff=observed,legacy_inventory=inventory_status,
                scope_allowed=(service.status(scope)['scope_allowed'] and bound[1].authorized_scope(scope) is True
                    and bound[3].allowed(scope) is True),
                access='authenticated_administrator',scope=scope,configuration_written=False,
                presence_seeded=False,models=0,sends=0),headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except PermissionError:return error_response('旧核心工具闸门、来源清单或归属条件尚未满足；未改变MC配置',status_code=403)
        except MemoryConflict:return error_response('核心工具归属或校验已改变，请刷新后重新审阅',status_code=409)
        except asyncio.TimeoutError:return error_response('来源读取结果未知，保持原配置与归属，不自动重试',status_code=503)
        except (RuntimeError,sqlite3.Error,OSError,ValueError,KeyError,TypeError):
            return error_response('原生核心工具暂不可用或正在重载',status_code=503)

    async def status(self):return await self._respond()
    async def transition(self):return await self._respond(transition=True)

    async def task_diagnostics(self):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过AstrBot管理后台认证',status_code=401)
        try:
            if dict(getattr(request,'query',None) or {}):
                return error_response('任务形状诊断不接受范围、正文或控制参数',status_code=400)
            bound=self._resources()
            observed=observe_task_diagnostics()
            if not self._same(bound):raise RuntimeError('diagnostic resources replaced')
            return json_response(dict(ok=True,diagnostics=observed,read_only=True,
                access='authenticated_administrator',configuration_written=False,
                owner_transitioned=False,presence_seeded=False,models=0,sends=0),headers={'Cache-Control':'no-store'})
        except Exception:return error_response('任务形状诊断暂不可用或正在重载',status_code=503)
