"""Operation-local administrator access to manual shared-event definitions."""
from __future__ import annotations
import asyncio
import hashlib
import json
import sqlite3
from astrbot.api.web import request, json_response, error_response
from .memory_web_api import SCOPE_FIELDS, _scope, _integer, _InvalidRequest
from .core.living.native_memory import MemoryConflict
from .core.living.native_memory_adapter import NativeMemoryAdapter
from .core.living.native_shared_timeline import NativeSharedTimeline, FIELDS, CATEGORIES
from .core.living.models import scope_key

PREFIX = '/astrbot_plugin_virtual_body/page/shared-timeline'
READS = {'list', 'detail', 'history', 'export'}


class NativeSharedTimelineWebApi:
    def __init__(self, plugin): self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'history', 'export', 'create', 'update', 'archive', 'restore'):
            self.plugin.context.register_web_api(PREFIX + '/' + name, getattr(self, name),
                ['GET' if name in READS else 'POST'], 'TLS authenticated administrator shared timeline ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None); host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None); service = getattr(runtime, 'shared_timeline', None)
        memory = getattr(runtime, 'memory', None); store = getattr(memory, 'store', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True or not isinstance(memory, NativeMemoryAdapter)
                or memory.active is not True or not isinstance(service, NativeSharedTimeline)
                or service.active is not True or service.store is not store or getattr(store, '_closed', True)):
            raise RuntimeError('shared timeline unavailable')
        return presence, host, runtime, service, memory, store

    def _same(self, resources):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise RuntimeError('shared timeline runtime changed')

    def _local(self, resources, scope):
        def authorize(candidate):
            self._same(resources)
            return candidate == scope
        return NativeSharedTimeline(resources[-1], authorize=authorize, clock=resources[3].clock)

    @staticmethod
    def _parse(name, data):
        if type(data) is not dict or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > 24576:
            raise _InvalidRequest('需要有界 JSON 对象')
        if name in READS:
            extra = {'include_archived', 'category', 'q', 'limit', 'offset'} if name == 'list' else ({'id', 'request_id'} if name == 'detail' else {'id'} if name == 'history' else set())
            if set(data) - set(SCOPE_FIELDS) - extra: raise _InvalidRequest('时间线查询含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name in {'detail', 'history'}:
                if name == 'detail' and 'request_id' in data:
                    request_id = data['request_id']
                    if ('id' in data or type(request_id) is not str or not 1 <= len(request_id) <= 128
                            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-' for c in request_id)
                            or request_id[0] not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'):
                        raise _InvalidRequest('需要单一稳定创建请求标识')
                    return scope, (), dict(request_id=request_id)
                if type(data.get('id')) is not str: raise _InvalidRequest('需要明确记录 ID')
                return scope, (data['id'],), {}
            if name == 'export': return scope, (), {}
            archived = data.get('include_archived', False)
            if type(archived) is str and archived in {'true', 'false'}: archived = archived == 'true'
            if type(archived) is not bool: raise _InvalidRequest('include_archived必须为布尔值')
            category = data.get('category', '')
            if category and category not in CATEGORIES: raise _InvalidRequest('来源证据类别无效')
            return scope, (), dict(include_archived=archived, category=category, query=data.get('q', ''),
                limit=_integer(data.get('limit', 50), 'limit', 1, 100), offset=_integer(data.get('offset', 0), 'offset', 0, 1000))
        required = {'scope', 'request_id', 'fields'} if name == 'create' else {'scope', 'id', 'expected_revision'} | ({'fields'} if name == 'update' else set())
        if set(data) != required: raise _InvalidRequest('时间线写操作需要完整参数，不能提供发送或旧库参数')
        scope = _scope(data['scope'])
        if name in {'create', 'update'} and (type(data['fields']) is not dict or set(data['fields']) != FIELDS):
            raise _InvalidRequest('需要完整七项事件字段')
        if name == 'create': return scope, (data['request_id'],), dict(data['fields'])
        if type(data['expected_revision']) is not int: raise _InvalidRequest('修订必须为明确整数')
        return scope, (data['id'],), dict(expected_revision=data['expected_revision'], **(data['fields'] if name == 'update' else {}))

    async def _respond(self, name):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip(): return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        local = None
        try:
            resources = self._resources()
            if name in READS: data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None): raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii() or not length.isdigit() or len(length) > 10 or int(length) > 24576):
                    raise _InvalidRequest('时间线请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._parse(name, data)
            self._same(resources); local = self._local(resources, scope)
            def operate():
                self._same(resources)
                if name == 'detail' and 'request_id' in kwargs:
                    # Read the receipt of the original creation. A check must
                    # never replay POST create, even though creation is idempotent.
                    event = 'shared_timeline_' + hashlib.sha256(kwargs['request_id'].encode()).hexdigest()
                    with local.store._lock:
                        local.check(scope)
                        receipt = local.store._db.execute(
                            'SELECT record_id FROM tls_native_memory_events WHERE scope=? AND id=?',
                            (scope_key(scope), event)).fetchone()
                        if receipt is None: raise KeyError('creation receipt not found')
                        result = local.get(scope, receipt['record_id'])
                        local.check(scope)
                else:
                    result = getattr(local, 'get' if name == 'detail' else name)(scope, *args, **kwargs)
                if name in {'create', 'update', 'archive', 'restore'}:
                    saved = local.get(scope, result['id'])
                    if saved != result: raise RuntimeError('timeline API readback changed')
                    result = saved
                self._same(resources); local.check(scope)
                return result
            result = await asyncio.to_thread(operate)
            self._same(resources); local.check(scope)
            body = dict(ok=True, backend='native_shared_timeline', scope=scope, access='authenticated_administrator',
                automatic_recall=False, context_mode='confirmed_manual_reference',
                requires_runtime_authorization=True, actually_used='unknown',
                sends=0, legacy_migrated=False, evidence_categories=CATEGORIES)
            if name == 'list': body.update(result)
            else: body[{'history': 'history', 'export': 'export'}.get(name, 'record')] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc: return error_response(str(exc), status_code=400)
        except MemoryConflict: return error_response('记录或修订已变化，请回读后核对，草稿不会自动覆盖', status_code=409)
        except PermissionError: return error_response('本次管理员资料授权已结束', status_code=403)
        except KeyError: return error_response('当前范围中找不到该手工经历记录', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError): return error_response('请检查事件时间、来源类别、确认项和字段范围', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError): return error_response('时间线暂不可用；写操作请保留原请求并回读确认', status_code=503)
        except Exception: return error_response('时间线操作未完成，请保留草稿并回读确认', status_code=500)
        finally:
            if local is not None: local.stop()

    async def list(self): return await self._respond('list')
    async def detail(self): return await self._respond('detail')
    async def history(self): return await self._respond('history')
    async def export(self): return await self._respond('export')
    async def create(self): return await self._respond('create')
    async def update(self): return await self._respond('update')
    async def archive(self): return await self._respond('archive')
    async def restore(self): return await self._respond('restore')
