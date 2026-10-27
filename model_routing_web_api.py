"""Normal AstrBot administration for task model IDs, never provider credentials."""
from __future__ import annotations

import asyncio
import json

from astrbot.api.web import request, json_response, error_response

from .core.living.journal import JournalConflict
from .core.living.task_model_router import TaskModelRouter

PREFIX = '/astrbot_plugin_virtual_body/page/model-routing'


class TaskModelRoutingWebApi:
    def __init__(self, plugin): self.plugin = plugin

    def register_routes(self):
        for name, method in [('state', 'GET'), ('settings', 'POST')]:
            self.plugin.context.register_web_api(PREFIX+'/'+name, getattr(self, name), [method],
                                                'TLS authenticated task model routing '+name)

    def _resources(self):
        username = getattr(request, 'username', None)
        if not isinstance(username, str) or not username.strip(): raise PermissionError('administrator required')
        router = getattr(self.plugin, '_task_model_router', None)
        if (getattr(self.plugin, '_stopping', False) or not isinstance(router, TaskModelRouter)
                or router.context is not self.plugin.context
                or getattr(self.plugin.context, '_tls_task_model_router', None) is not router
                or router.current() is not True):
            raise RuntimeError('current model router unavailable')
        return username, router

    async def _respond(self, write=False):
        try:
            username, router = self._resources()
            if getattr(request, 'query', None): raise ValueError('此入口不接受查询参数')
            body = None
            if write:
                body = await request.json(default=None)
                if (type(body) is not dict or set(body) != {'expected_revision', 'changes'}
                        or len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode()) > 16384):
                    raise ValueError('模型路由设置字段或大小无效')
            def operate():
                if self._resources() != (username, router): raise RuntimeError('router changed')
                if write: router.save(body['changes'], body['expected_revision'])
                result = router.snapshot()
                if self._resources() != (username, router): raise RuntimeError('router changed')
                return result
            value = await asyncio.to_thread(operate)
            return json_response(dict(ok=True, backend='task_model_router', routing=value),
                                 headers={'Cache-Control': 'no-store'})
        except PermissionError:
            return error_response('请先登录AstrBot管理后台', status_code=401)
        except JournalConflict:
            return error_response('模型路由已有变化，请读取当前版本后保存', status_code=409)
        except (ValueError, TypeError) as exc:
            return error_response(str(exc) if isinstance(exc, ValueError) else '模型路由字段无效', status_code=400)
        except (RuntimeError, OSError, AttributeError):
            return error_response('任务模型服务正在更新，操作结果请回读核对', status_code=503)

    async def state(self): return await self._respond()
    async def settings(self): return await self._respond(True)
