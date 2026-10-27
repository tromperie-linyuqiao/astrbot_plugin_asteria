"""Normal-admin memo-tool intent and close-only management; no lease grants."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict
from .core.living.native_memo_host_controller import NativeMemoHostController
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope

PREFIX = '/astrbot_plugin_virtual_body/page/memo-tools'
MAX_BODY_BYTES = 4096


class NativeMemoToolsWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('status', 'arm', 'close'):
            self.plugin.context.register_web_api(PREFIX + '/' + name, getattr(self, name),
                ['GET' if name == 'status' else 'POST'], 'TLS authenticated memo tool ' + name)

    def _controller(self):
        controller = getattr(self.plugin, '_native_memo_tool_router', None)
        if not isinstance(controller, NativeMemoHostController) or controller.plugin is not self.plugin:
            raise RuntimeError('current memo tool controller unavailable')
        resources = controller._resources()
        return controller, resources

    def _same(self, controller, resources):
        current, latest = self._controller()
        if current is not controller or any(old is not new for old, new in zip(resources, latest)):
            raise RuntimeError('memo tool controller reloaded')

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('便签工具请求需要大小适当的对象')
        if name == 'status':
            if set(data) != set(SCOPE_FIELDS): raise _InvalidRequest('状态查询需要五项完整范围')
            return _scope(data), {}
        expected = {'scope', 'expected_revision', 'request_id'} | ({'binding_sha256'} if name == 'arm' else set())
        if set(data) != expected: raise _InvalidRequest('操作需要完整范围、当前版本和原请求标识')
        if type(data['expected_revision']) is not int or not 0 <= data['expected_revision'] < 2**53:
            raise _InvalidRequest('请读取当前意图版本后再修改')
        return _scope(data['scope']), {key: value for key, value in data.items() if key != 'scope'}

    async def _respond(self, name):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        active = [True]
        try:
            controller, resources = self._controller()
            if name == 'status':
                # Source files may be deployed after TLS. Binding mutates only
                # the reviewed compatibility RAM slot, on its event loop. It
                # neither observes a private scope nor activates an owner.
                controller._ensure_child()
            if name == 'status': data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None): raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii() or not length.isdigit()
                        or len(length) > 10 or int(length) > MAX_BODY_BYTES): raise _InvalidRequest('便签工具请求过大')
                data = await request.json(default=None)
            scope, kwargs = self._operation(name, data)
            def authorize(candidate):
                self._same(controller, resources)
                return active[0] and candidate == scope
            def operate():
                self._same(controller, resources)
                result = getattr(controller, name)(scope, authorize_operation=authorize, **kwargs)
                self._same(controller, resources)
                if not authorize(scope): raise PermissionError('memo operation cancelled')
                return result
            result = await asyncio.to_thread(operate)
            self._same(controller, resources)
            if not authorize(scope): raise PermissionError('memo operation cancelled')
            return json_response(dict(ok=True, scope=scope, result=result,
                access='authenticated_administrator', operation=name, arm_is_intent_only=True,
                creates_private_scope=False, grants_runtime_authority=False,
                changes_old_plugin_config=False, sends=0, models=0), headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc: return error_response(str(exc), status_code=400)
        except JournalConflict: return error_response('便签工具意图版本已变化，请先回读状态，勿盲目重发', status_code=409)
        except PermissionError: return error_response('当前管理操作已撤销或范围未获准', status_code=403)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('便签工具字段无效；不能借此创建私聊或发送权限', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('便签工具服务重载或操作结果未确认，请按原请求回读状态', status_code=503)
        except Exception: return error_response('便签工具操作尚未确认，请保留原请求后核查', status_code=500)
        finally:
            active[0] = False

    async def status(self): return await self._respond('status')
    async def arm(self): return await self._respond('arm')
    async def close(self): return await self._respond('close')
