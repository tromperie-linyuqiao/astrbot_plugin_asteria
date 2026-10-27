"""Authenticated maintenance of sourced native PC day-to-day execution."""
from __future__ import annotations

import asyncio
import inspect
import json

from astrbot.api.web import request, json_response, error_response
from .core.living.journal import JournalConflict
from .core.living.native_pc_daily_lifecycle import NativePCDailyLifecycle
from .core.living.native_pc_goal_handoff import PCGoalHandoffError
from .memory_web_api import SCOPE_FIELDS, _scope, _InvalidRequest

PREFIX = '/astrbot_plugin_virtual_body/page/pc-daily-native'
ROUTES = (('status', 'GET'), ('settings', 'POST'), ('generate', 'POST'), ('tick', 'POST'),
          ('owner_status', 'GET'), ('owner_activate', 'POST'), ('owner_stop', 'POST'), ('owner_restore', 'POST'))


class NativePCDailyWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name, method in ROUTES:
            self.plugin.context.register_web_api(PREFIX + '/' + name.replace('_', '/'), getattr(self, name), [method],
                'TLS native PC sourced daily lifecycle ' + name)

    def _resources(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'pc_daily_lifecycle', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativePCDailyLifecycle)
                or service.journal is not getattr(runtime, 'journal', None)
                or service.plans is not getattr(runtime, 'scoped_daily_plans', None)
                or service.goals is not getattr(runtime, 'personal_goals', None)):
            raise RuntimeError('native PC daily runtime unavailable')
        return host, runtime, service

    async def _respond(self, operation):
        try:
            username = getattr(request, 'username', None)
            if not isinstance(username, str) or not username.strip():
                return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
            resources = self._resources(); service = resources[-1]
            if operation in {'status', 'owner_status'}:
                data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None): raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (not str(length).isdigit() or int(length) > 16384):
                    raise _InvalidRequest('请求内容过大')
                data = await request.json(default=None)
                if type(data) is not dict or len(json.dumps(data, ensure_ascii=False).encode()) > 16384:
                    raise _InvalidRequest('需要有效的小型 JSON 对象')
            scope = None
            if operation.startswith('owner_'):
                if operation == 'owner_status':
                    if data: raise _InvalidRequest('执行权状态不接受范围或其他字段')
                    result = service.handoff.status()
                else:
                    if set(data) != {'expected_phase', 'confirm'} or data['confirm'] is not True:
                        raise _InvalidRequest('执行权操作需要明确确认与当前阶段')
                    if service.handoff.status()['phase'] != data['expected_phase']:
                        raise JournalConflict('执行权阶段已变化；请先回读，勿重复提交')
                    if operation == 'owner_activate': result = await service.handoff.activate()
                    elif operation == 'owner_restore': result = await service.handoff.restore()
                    else:
                        service.stop()
                        result = service.handoff.status()
            else:
                if operation == 'status':
                    if set(data) != set(SCOPE_FIELDS): raise _InvalidRequest('需要完整用户、角色及会话范围')
                    scope = _scope(data)
                    result = service.diagnostics(scope)
                else:
                    if type(data.get('scope')) is not dict: raise _InvalidRequest('需要完整明确范围')
                    scope = _scope(data['scope'])
                    if operation == 'settings':
                        if set(data) != {'scope', 'expected_revision', 'flags'}: raise _InvalidRequest('设置字段不完整')
                        result = service.configure(scope, expected_revision=data['expected_revision'], flags=data['flags'], actor=username)
                    elif operation == 'generate':
                        if set(data) != {'scope', 'day', 'routines'} or type(data['routines']) is not bool:
                            raise _InvalidRequest('需要日期及明确的计划类型')
                        result = await service.generate(scope, day=data['day'] or None, routines=data['routines'])
                    else:
                        if set(data) != {'scope'}: raise _InvalidRequest('推进操作只接受当前范围')
                        result = await service.tick(scope)
            if any(before is not after for before, after in zip(resources, self._resources())):
                raise RuntimeError('native PC daily runtime changed')
            return json_response({'ok': True, 'backend': 'native_pc_daily', 'scope': scope, 'result': result})
        except (JournalConflict, PCGoalHandoffError) as error:
            return error_response(str(error), status_code=409)
        except PermissionError as error:
            return error_response(str(error), status_code=403)
        except (ValueError, TypeError, KeyError, _InvalidRequest) as error:
            return error_response(str(error), status_code=400)
        except asyncio.CancelledError: raise
        except Exception:
            return error_response('日常执行状态暂不可用，请刷新核对；不要自动重发写操作。', status_code=503)

    async def status(self): return await self._respond('status')
    async def settings(self): return await self._respond('settings')
    async def generate(self): return await self._respond('generate')
    async def tick(self): return await self._respond('tick')
    async def owner_status(self): return await self._respond('owner_status')
    async def owner_activate(self): return await self._respond('owner_activate')
    async def owner_stop(self): return await self._respond('owner_stop')
    async def owner_restore(self): return await self._respond('owner_restore')
