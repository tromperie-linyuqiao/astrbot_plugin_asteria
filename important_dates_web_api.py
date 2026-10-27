"""Authenticated administration of scoped date definitions, never chat/send authority."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_important_dates import FIELDS, MAX_DATES, NativeImportantDates
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/important-dates'
MAX_BODY_BYTES = 272 * 1024
READS = frozenset(('list', 'detail', 'export'))


class _Unavailable(RuntimeError):
    pass


class NativeImportantDatesWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'export', 'create', 'update', 'archive', 'restore', 'preview_import', 'confirm_import'):
            path = {'preview_import': 'import/preview', 'confirm_import': 'import/confirm'}.get(name, name)
            self.plugin.context.register_web_api(PREFIX + '/' + path, getattr(self, name),
                ['GET' if name in READS else 'POST'], 'TLS authenticated administrator date definitions ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'important_dates', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativeImportantDates) or service.active is not True
                or not isinstance(journal, LivingJournal) or service.journal is not journal
                or getattr(journal, '_closed', True)):
            raise _Unavailable('native date definitions unavailable')
        return presence, host, runtime, service, journal

    def _same_resources(self, resources):
        current = self._resources()
        if any(before is not after for before, after in zip(resources, current)):
            raise _Unavailable('native date definitions runtime changed')

    def _admin_service(self, resources, scope):
        # Same administrator material boundary as assets/memory-transfer. This
        # local callback never edits the runtime source reader's authorization,
        # creates a Presence lease, resolves a persona, or permits delivery.
        expected = dict(scope)
        def authorize(candidate):
            self._same_resources(resources)
            return candidate == expected
        return NativeImportantDates(resources[-1], authorize=authorize, clock=resources[-2].clock)

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict:
            raise _InvalidRequest('请求必须为 JSON 对象或合法查询')
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('日期请求过大，迁移预览最多 200 条')
        if name in READS:
            extra = {'include_archived', 'limit', 'offset'} if name == 'list' else {'id'} if name == 'detail' else {'include_archived'}
            if set(data) - set(SCOPE_FIELDS) - extra:
                raise _InvalidRequest('日期查询包含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name == 'detail':
                return scope, (_text(data.get('id'), '日期 ID', 100),), {}
            archived = data.get('include_archived', name == 'export')
            if type(archived) is str and archived in {'true', 'false'}:
                archived = archived == 'true'
            if type(archived) is not bool:
                raise _InvalidRequest('include_archived 必须为布尔值')
            options = dict(include_archived=archived)
            if name == 'list':
                options.update(limit=_integer(data.get('limit', 20), 'limit', 1, 100),
                               offset=_integer(data.get('offset', 0), 'offset', 0, MAX_DATES))
            return scope, (), options
        scope = _scope(data.get('scope'))
        if name in {'preview_import', 'confirm_import'}:
            allowed = {'scope', 'payload'} if name == 'preview_import' else {'scope', 'payload', 'preview_sha256', 'request_id', 'owner_confirmed'}
            if set(data) != allowed:
                raise _InvalidRequest('导入仅接受完整范围、来源 JSON 和本次明确预览确认字段')
            return scope, (data['payload'],), {key: data[key] for key in data if key not in {'scope', 'payload'}}
        allowed = {'scope', 'request_id', 'fields'} if name == 'create' else {'scope', 'id', 'expected_revision'} | ({'fields'} if name == 'update' else set())
        if set(data) != allowed:
            raise _InvalidRequest('日期操作需要完整参数，不能提交发送、任务或来源权限')
        if name in {'create', 'update'}:
            if type(data['fields']) is not dict or set(data['fields']) != FIELDS:
                raise _InvalidRequest('请提交完整的九项日期定义字段')
        if name == 'create':
            return scope, (_text(data['request_id'], 'request_id', 128),), dict(data['fields'])
        revision = data['expected_revision']
        if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
            raise _InvalidRequest('expected_revision 必须是明确整数')
        return scope, (_text(data['id'], '日期 ID', 100),), dict(
            expected_revision=revision, **(data['fields'] if name == 'update' else {}))

    async def _respond(self, name):
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        service = None
        try:
            resources = self._resources()
            if name in READS:
                data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None):
                    raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii()
                        or not length.isdigit() or len(length) > 10 or int(length) > MAX_BODY_BYTES):
                    raise _InvalidRequest('日期请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            self._same_resources(resources)
            service = self._admin_service(resources, scope)
            def operate():
                self._same_resources(resources)
                if name == 'list':
                    snapshot = service.export(scope, include_archived=kwargs['include_archived'])
                    start, maximum = kwargs['offset'], kwargs['limit']
                    result = dict(records=snapshot['records'][start:start + maximum], total=snapshot['total'],
                                  limit=maximum, offset=start)
                else:
                    result = getattr(service, 'get' if name == 'detail' else name)(scope, *args, **kwargs)
                    if name == 'detail' and result is None:
                        raise KeyError('date definition absent')
                if name in {'create', 'update', 'archive', 'restore'}:
                    result = service.get(scope, result['id'])
                    if result is None:
                        raise RuntimeError('date definition write readback absent')
                if name == 'confirm_import':
                    records = [service.get(scope, identity) for identity in result['created_ids'] + result['existing_ids']]
                    if any(row is None for row in records):
                        raise RuntimeError('date import write readback absent')
                    result = dict(result, records=records)
                self._same_resources(resources)
                service._scope(scope)
                return result
            result = await asyncio.to_thread(operate)
            self._same_resources(resources)
            service._scope(scope)
            body = dict(ok=True, backend='native_important_dates', scope=scope,
                        access='authenticated_administrator', authority='historical_administrator_materials',
                        definitions_only=True, creates_send_permission=False, legacy_consumer_retained=True)
            if name == 'list':
                body.update(result)
            elif name == 'confirm_import':
                body['import'] = {key: value for key, value in result.items() if key != 'records'}
                body['records'] = result['records']
            else:
                body[{'export': 'export', 'preview_import': 'preview', 'confirm_import': 'import'}.get(name, 'record')] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except JournalConflict:
            return error_response('日期版本、来源、请求 ID 或预览已变化，请回读后重新预览', status_code=409)
        except PermissionError:
            return error_response('需要当前后台认证及明确的逐条归属确认', status_code=403)
        except KeyError:
            return error_response('当前完整范围中找不到该原生日期', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('日期字段或迁移材料无效，请检查日期、时区、开关和修订', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('日期资料暂不可用或正在重载；写操作请保留请求 ID 并回读确认', status_code=503)
        except Exception:
            return error_response('日期操作失败，请保留草稿并稍后回读确认', status_code=500)
        finally:
            if service is not None:
                service.stop()

    async def list(self): return await self._respond('list')
    async def detail(self): return await self._respond('detail')
    async def export(self): return await self._respond('export')
    async def create(self): return await self._respond('create')
    async def update(self): return await self._respond('update')
    async def archive(self): return await self._respond('archive')
    async def restore(self): return await self._respond('restore')
    async def preview_import(self): return await self._respond('preview_import')
    async def confirm_import(self): return await self._respond('confirm_import')
