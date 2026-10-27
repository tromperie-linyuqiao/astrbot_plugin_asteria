"""Authenticated native note maintenance; no old PC writes or extra scheduler."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_memo_notes import FIELDS, MAX_NOTES, NativeMemoNotes
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/memo-notes'
MAX_BODY_BYTES = 80 * 1024
READS = frozenset(('list', 'detail', 'export', 'request'))


class _Unavailable(RuntimeError):
    pass


class NativeMemoNotesWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'export', 'request', 'create', 'update', 'complete', 'reopen', 'archive', 'restore', 'preview_import', 'confirm_import'):
            path = {'preview_import': 'import/preview', 'confirm_import': 'import/confirm'}.get(name, name)
            self.plugin.context.register_web_api(PREFIX + '/' + path, getattr(self, name),
                ['GET' if name in READS else 'POST'], 'TLS authenticated native memo notes ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'memo_notes', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativeMemoNotes) or service.active is not True
                or not isinstance(journal, LivingJournal) or service.journal is not journal
                or getattr(runtime, 'journal', None) is not journal or getattr(journal, '_closed', True)):
            raise _Unavailable('native memo notes unavailable')
        return presence, host, runtime, service, journal

    def _same_resources(self, resources):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise _Unavailable('native memo notes runtime changed')

    def _admin_service(self, resources, scope):
        expected = dict(scope)
        def authorize(candidate):
            self._same_resources(resources)
            return candidate == expected
        return NativeMemoNotes(resources[-1], authorize=authorize, clock=resources[-2].clock)

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('请提交大小适当的便签对象或合法查询')
        if name in READS:
            extra = {'q', 'status', 'include_archived', 'limit', 'offset'} if name == 'list' else {'id'} if name == 'detail' else {'request_id'} if name == 'request' else set()
            if set(data) - set(SCOPE_FIELDS) - extra:
                raise _InvalidRequest('便签查询包含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name == 'detail': return scope, (_text(data.get('id'), '便签 ID', 100),), {}
            if name == 'request': return scope, (_text(data.get('request_id'), 'request_id', 128),), {}
            if name == 'export': return scope, (), {}
            archived = data.get('include_archived', False)
            if type(archived) is str and archived in {'true', 'false'}: archived = archived == 'true'
            if type(archived) is not bool: raise _InvalidRequest('include_archived 必须为布尔值')
            selected = data.get('status', 'active')
            if selected not in {'active', 'completed', 'all'}: raise _InvalidRequest('请选择进行中、已完成或全部便签')
            return scope, (), dict(query=_text(data.get('q', ''), '关键词', 100, blank=True), status=selected,
                include_archived=archived, limit=_integer(data.get('limit', 20), 'limit', 1, 100),
                offset=_integer(data.get('offset', 0), 'offset', 0, MAX_NOTES))
        scope = _scope(data.get('scope'))
        if name in {'preview_import', 'confirm_import'}:
            allowed = {'scope', 'payload'} if name == 'preview_import' else {'scope', 'payload', 'preview_sha256', 'request_id', 'owner_confirmed'}
            if set(data) != allowed: raise _InvalidRequest('迁移需要来源制品和本次明确归属确认')
            return scope, (data['payload'],), {key: data[key] for key in data if key not in {'scope', 'payload'}}
        allowed = ({'scope', 'request_id', 'fields'} if name == 'create' else {'scope', 'id', 'expected_revision'}
            | ({'fields'} if name == 'update' else {'request_id'} if name in {'complete', 'reopen'} else set()))
        if set(data) != allowed: raise _InvalidRequest('便签操作需要完整参数，不接受发送或旧系统权限')
        if name in {'create', 'update'} and (type(data['fields']) is not dict or set(data['fields']) != FIELDS):
            raise _InvalidRequest('请提交标题、内容、颜色、置顶、到期、重复和提醒偏好七项字段')
        if name == 'create': return scope, (_text(data['request_id'], 'request_id', 128),), dict(data['fields'])
        revision = data['expected_revision']
        if type(revision) is not int or not 1 <= revision <= 2**53 - 1: raise _InvalidRequest('请先读取当前便签版本')
        options = dict(expected_revision=revision)
        if name == 'update': options.update(data['fields'])
        if name in {'complete', 'reopen'}: options['request_id'] = _text(data['request_id'], 'request_id', 128)
        return scope, (_text(data['id'], '便签 ID', 100),), options

    async def _respond(self, name):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        service = None
        try:
            resources = self._resources()
            if name in READS: data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None): raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii() or not length.isdigit()
                        or len(length) > 10 or int(length) > MAX_BODY_BYTES): raise _InvalidRequest('便签请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            self._same_resources(resources); service = self._admin_service(resources, scope)
            def operate():
                self._same_resources(resources)
                result = getattr(service, 'search' if name == 'list' else 'get' if name == 'detail' else 'get_request' if name == 'request' else name)(scope, *args, **kwargs)
                if name in {'detail', 'request'} and result is None: raise KeyError('memo note absent')
                if name in {'create', 'update', 'complete', 'reopen', 'archive', 'restore'}:
                    saved = service.get(scope, result['id'])
                    if saved != result: raise RuntimeError('memo write readback changed')
                    result = saved
                if name == 'confirm_import':
                    records = [service.get(scope, value) for value in result['created_ids'] + result['existing_ids']]
                    if any(value is None for value in records): raise RuntimeError('memo import readback absent')
                    result = dict(result, records=records)
                self._same_resources(resources); service._scope(scope)
                return result
            result = await asyncio.to_thread(operate)
            self._same_resources(resources); service._scope(scope)
            body = dict(ok=True, backend='tls_native_memo_notes', scope=scope, access='authenticated_administrator',
                authority='historical_administrator_materials', metadata_only=True, schedules_reminder=False,
                external_completion_confirmed=False, legacy_consumer_retained=True, creates_send_permission=False)
            if name == 'list': body.update(result)
            elif name == 'confirm_import':
                body['import'] = {key: value for key, value in result.items() if key != 'records'}; body['records'] = result['records']
            else: body[{'export': 'export', 'preview_import': 'preview'}.get(name, 'record')] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc: return error_response(str(exc), status_code=400)
        except JournalConflict: return error_response('便签版本或预览已变化，保留草稿并读取当前版本', status_code=409)
        except PermissionError: return error_response('当前便签范围或归属未获准', status_code=403)
        except KeyError: return error_response('当前完整范围找不到这张便签', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('便签字段或迁移制品无效；循环推进与真实提醒尚未接管', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('便签服务重载或写入结果未知，请保留原请求并回读核查', status_code=503)
        except Exception: return error_response('便签操作暂未确认，请保留草稿后核查', status_code=500)
        finally:
            if service is not None: service.stop()

    async def list(self): return await self._respond('list')
    async def detail(self): return await self._respond('detail')
    async def export(self): return await self._respond('export')
    async def request(self): return await self._respond('request')
    async def create(self): return await self._respond('create')
    async def update(self): return await self._respond('update')
    async def complete(self): return await self._respond('complete')
    async def reopen(self): return await self._respond('reopen')
    async def archive(self): return await self._respond('archive')
    async def restore(self): return await self._respond('restore')
    async def preview_import(self): return await self._respond('preview_import')
    async def confirm_import(self): return await self._respond('confirm_import')
