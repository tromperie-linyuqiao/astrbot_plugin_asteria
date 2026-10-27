"""Existing AstrBot administrator boundary for scoped profile-candidate review.

No live identity, observe endpoint, quality-proof input, lease or send authority
is created here. The existing native store owns persistence and review CAS.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import request, json_response, error_response

from .core.living.native_memory import NativeMemoryConflict, NativeMemoryStore
from .core.living.native_profile_candidates import NativeProfileCandidates
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope, _integer, _text

PREFIX = '/astrbot_plugin_virtual_body/page/profile-candidates'
READS = frozenset(('list', 'detail'))
STATUSES = frozenset(('pending', 'active', 'rejected', 'superseded'))
MAX_BODY_BYTES = 16 * 1024


class NativeProfileCandidatesWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'approve', 'reject'):
            self.plugin.context.register_web_api(PREFIX + '/' + name, getattr(self, name),
                ['GET' if name in READS else 'POST'], 'TLS authenticated administrator profile candidates ' + name)

    @staticmethod
    def _username():
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            raise PermissionError('normal AstrBot administrator required')
        return username

    def _resources(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        adapter = getattr(runtime, 'memory', None)
        store = getattr(adapter, 'store', None)
        service = getattr(runtime, 'profile_candidates', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or getattr(adapter, 'backend', None) != 'native' or getattr(adapter, 'active', False) is not True
                or not isinstance(store, NativeMemoryStore) or store._closed
                or not isinstance(service, NativeProfileCandidates) or service.active is not True
                or service.store is not store
                or getattr(self.plugin, '_native_profile_candidates', service) is not service):
            raise RuntimeError('current native profile candidates unavailable')
        return host, runtime, adapter, store, service

    def _same(self, resources, username):
        if self._username() != username or any(a is not b for a, b in zip(resources, self._resources())):
            raise RuntimeError('profile candidate resources changed')

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > MAX_BODY_BYTES:
            raise _InvalidRequest('候选请求必须是有界JSON对象')
        if name in READS:
            allowed = set(SCOPE_FIELDS) | ({'status', 'q', 'limit'} if name == 'list' else {'id'})
            if set(data) - allowed:
                raise _InvalidRequest('候选查询包含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name == 'detail':
                return scope, (_text(data.get('id'), '候选ID', 256),), {}
            status = data.get('status')
            if status is not None and status not in STATUSES:
                raise _InvalidRequest('候选状态必须为pending/active/rejected/superseded')
            return scope, (), dict(status=status, query=_text(data.get('q', ''), '搜索文字', 128, blank=True),
                                  limit=_integer(data.get('limit', 100), 'limit', 1, 100))
        if set(data) != {'scope', 'id', 'expected_revision', 'event_id'}:
            raise _InvalidRequest('审核仅接受完整范围、候选ID、预期修订和本次动作ID')
        revision = data['expected_revision']
        if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
            raise _InvalidRequest('预期修订必须为明确正整数')
        event_id = _text(data['event_id'], '审核动作ID', 128)
        if event_id != event_id.strip() or any(ord(char) < 32 for char in event_id):
            raise _InvalidRequest('审核动作ID不能含首尾空白或控制字符')
        return _scope(data['scope']), (_text(data['id'], '候选ID', 256),), dict(
            action=name, expected_revision=revision, event_id=event_id)

    async def _respond(self, name):
        try:
            username = self._username()
        except PermissionError:
            return error_response('请先登录AstrBot管理后台', status_code=401)
        try:
            resources = self._resources()
            if name in READS:
                data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None):
                    raise _InvalidRequest('审核操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii()
                        or not length.isdigit() or len(length) > 10 or int(length) > MAX_BODY_BYTES):
                    raise _InvalidRequest('审核请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            self._same(resources, username)
            service, store = resources[-1], resources[-2]

            def operate():
                self._same(resources, username)
                if name == 'list':
                    value = service.list(scope, **kwargs)
                elif name == 'detail':
                    value = service.get(scope, *args)
                    if value is None:
                        raise KeyError('candidate absent')
                else:
                    with store.transaction():
                        self._same(resources, username)
                        value = service.review(scope, *args, reviewer=username, **kwargs)
                        value = service.get(scope, value['id'])
                        if value is None:
                            raise RuntimeError('review readback unavailable')
                        self._same(resources, username)
                self._same(resources, username)
                return value

            value = await asyncio.to_thread(operate)
            self._same(resources, username)
            body = dict(ok=True, backend='native_profile_candidates', scope=scope,
                        access='authenticated_administrator', creates_send_permission=False)
            body['records' if name == 'list' else 'record'] = value
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except NativeMemoryConflict:
            return error_response('候选已变化，请回读后重新决定', status_code=409)
        except PermissionError:
            return error_response('当前范围不可审核，请核对后台身份和完整归属', status_code=403)
        except KeyError:
            return error_response('当前完整范围中找不到该候选', status_code=404)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return error_response('候选参数无效，请检查状态、范围和修订', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('候选资料暂不可用；若已提交审核，请只回读核对结果', status_code=503)
        except Exception:
            return error_response('候选审核暂未完成，请保留本次动作ID并回读核对', status_code=500)

    async def list(self):
        return await self._respond('list')

    async def detail(self):
        return await self._respond('detail')

    async def approve(self):
        return await self._respond('approve')

    async def reject(self):
        return await self._respond('reject')
