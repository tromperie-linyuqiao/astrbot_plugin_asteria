"""Authenticated administration of the role's own scoped personal goals.

AstrBot owns authentication and the plugin-extension permission boundary; these
handlers use only its injected ``request.username``. A complete historical
private scope can be managed, exactly like the sibling date and memory pages.
This never creates a Presence lease, sends a message, schedules delivery or
grants send permission; proactive work stays a candidate for the existing queue.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_personal_goals import (EDIT_FIELDS, MAX_GOALS,
                                                NativePersonalGoals, STATUSES)
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/personal-goals'
MAX_BODY_BYTES = 288 * 1024
READS = frozenset(('list', 'detail', 'export', 'search'))
STATUS_ACTIONS = ('pause', 'resume', 'complete', 'abandon', 'archive', 'restore')
ROUTES = (('list', 'GET'), ('detail', 'GET'), ('export', 'GET'), ('search', 'GET'),
          ('create', 'POST'), ('update', 'POST'), ('pause', 'POST'), ('resume', 'POST'),
          ('complete', 'POST'), ('abandon', 'POST'), ('archive', 'POST'), ('restore', 'POST'),
          ('preview_import', 'POST'), ('confirm_import', 'POST'))
PATHS = {'preview_import': 'import/preview', 'confirm_import': 'import/confirm'}


class _Unavailable(RuntimeError):
    pass


class NativePersonalGoalsWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name, method in ROUTES:
            self.plugin.context.register_web_api(
                PREFIX + '/' + PATHS.get(name, name), getattr(self, name), [method],
                'TLS authenticated administrator personal goals ' + name)

    # -- resource fence ----------------------------------------------------

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'personal_goals', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativePersonalGoals)
                or service.active is not True
                or not isinstance(journal, LivingJournal) or service.journal is not journal
                or getattr(runtime, 'journal', None) is not journal
                or getattr(journal, '_closed', True)):
            raise _Unavailable('native personal goals unavailable')
        return presence, host, runtime, service, journal

    def _same_resources(self, resources):
        current = self._resources()
        if any(before is not after for before, after in zip(resources, current)):
            raise _Unavailable('native personal goals runtime changed')

    def _admin_service(self, resources, scope):
        # Same administrator material boundary as memory/dates. This local
        # callback never edits the runtime reader's authorization, creates a
        # Presence lease, resolves a persona or permits delivery.
        expected = dict(scope)

        def authorize(candidate):
            self._same_resources(resources)
            return candidate == expected

        _, _, _, source, journal = resources
        # The service stores an explicit IANA/fixed-offset name as well as its
        # resolved tzinfo. The constructor accepts the name, never the tzinfo.
        zone_name = getattr(source, 'timezone_name', None)
        if type(zone_name) is not str or not zone_name:
            raise _Unavailable('explicit personal goals timezone unavailable')
        return NativePersonalGoals(journal, authorize=authorize,
                                   clock=source.clock, timezone=zone_name)

    # -- request parsing ---------------------------------------------------

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict:
            raise _InvalidRequest('请求必须为 JSON 对象或合法查询')
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('目标请求过大，迁移预览最多 100 条')
        if name in READS:
            extra = {'include_archived', 'limit', 'offset', 'status', 'private'} if name == 'list' else \
                {'id', 'private'} if name == 'detail' else \
                {'q', 'limit', 'include_archived', 'private'} if name == 'search' else \
                {'include_archived', 'private'}
            if set(data) - set(SCOPE_FIELDS) - extra:
                raise _InvalidRequest('目标查询包含未知字段')
            scope = _scope(_scope_query(data))
            if name == 'detail':
                return scope, (_text(data.get('id'), '目标 ID', 100),), {}
            if name == 'search':
                return scope, (_text(data.get('q'), '检索内容', 80),), dict(
                    include_archived=_flag(data.get('include_archived', False)),
                    limit=_integer(data.get('limit', 20), 'limit', 1, 50))
            if name == 'list':
                status = data.get('status')
                if status is not None and status not in STATUSES:
                    raise _InvalidRequest('status 必须是 active/paused/completed/abandoned')
                return scope, (), dict(
                    include_archived=_flag(data.get('include_archived', False)),
                    status=status,
                    limit=_integer(data.get('limit', 20), 'limit', 1, 100),
                    offset=_integer(data.get('offset', 0), 'offset', 0, MAX_GOALS))
            return scope, (), dict(include_archived=_flag(data.get('include_archived', True)))
        scope = _scope(data.get('scope'))
        if name in {'preview_import', 'confirm_import'}:
            allowed = {'scope', 'payload'} if name == 'preview_import' else \
                {'scope', 'payload', 'preview_sha256', 'request_id', 'owner_confirmed'}
            if set(data) != allowed:
                raise _InvalidRequest('迁移仅接受完整范围、来源 JSON 和本次明确确认字段')
            return scope, (data['payload'],), {key: data[key] for key in data
                                               if key not in {'scope', 'payload'}}
        if name == 'create':
            allowed = {'scope', 'request_id', 'fields', 'progress'}
            if set(data) - allowed or not {'scope', 'request_id', 'fields'} <= set(data):
                raise _InvalidRequest('新建目标需要完整范围、请求 ID 和字段')
            fields = data['fields']
            if type(fields) is not dict or set(fields) != EDIT_FIELDS:
                raise _InvalidRequest('请提交完整的八项目标定义字段')
            progress = _integer(data.get('progress', 0), 'progress', 0, 100)
            return scope, (_text(data['request_id'], 'request_id', 128),), dict(
                fields=dict(fields), progress=progress)
        if name == 'update':
            allowed = {'scope', 'id', 'expected_revision', 'fields', 'progress'}
            if set(data) - allowed or not {'scope', 'id', 'expected_revision'} <= set(data):
                raise _InvalidRequest('编辑目标需要完整范围、ID 和修订号')
            if 'fields' not in data and 'progress' not in data:
                raise _InvalidRequest('编辑需要字段或进度')
            kwargs = {}
            if 'fields' in data:
                fields = data['fields']
                if type(fields) is not dict or set(fields) != EDIT_FIELDS:
                    raise _InvalidRequest('请提交完整的八项目标定义字段')
                kwargs['fields'] = dict(fields)
            if 'progress' in data:
                kwargs['progress'] = _integer(data['progress'], 'progress', 0, 100)
            return scope, (_text(data['id'], '目标 ID', 100),), dict(
                expected_revision=_revision(data['expected_revision']), **kwargs)
        if name in STATUS_ACTIONS:
            if set(data) != {'scope', 'id', 'expected_revision'}:
                raise _InvalidRequest('状态操作只接受完整范围、ID 和预期修订号')
            return scope, (_text(data['id'], '目标 ID', 100),), dict(
                expected_revision=_revision(data['expected_revision']))
        raise _InvalidRequest('未知目标操作')

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
                                           or not length.isdigit() or len(length) > 10
                                           or int(length) > MAX_BODY_BYTES):
                    raise _InvalidRequest('目标请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            self._same_resources(resources)
            service = self._admin_service(resources, scope)

            def operate():
                self._same_resources(resources)
                if name == 'list':
                    snapshot = service.export(scope, include_archived=kwargs['include_archived'])
                    records = snapshot['records']
                    if kwargs['status'] is not None:
                        records = [row for row in records if row['status'] == kwargs['status']]
                    start, maximum = kwargs['offset'], kwargs['limit']
                    result = dict(records=records[start:start + maximum], total=len(records),
                                  limit=maximum, offset=start,
                                  status=kwargs['status'])
                elif name == 'search':
                    found = service.search(scope, args[0], **kwargs)
                    result = dict(records=found, total=len(found), query=args[0])
                else:
                    result = getattr(service, 'get' if name == 'detail' else name)(
                        scope, *args, **kwargs)
                    if name == 'detail' and result is None:
                        raise KeyError('goal absent')
                if name in {'create', 'update'} | set(STATUS_ACTIONS):
                    result = service.get(scope, result['id'])
                    if result is None:
                        raise RuntimeError('goal write readback absent')
                if name == 'confirm_import':
                    records = [service.get(scope, identity)
                               for identity in result['created_ids'] + result['existing_ids']]
                    if any(row is None for row in records):
                        raise RuntimeError('goal import write readback absent')
                    result = dict(result, records=records)
                self._same_resources(resources)
                service._scope(scope)
                return result

            result = await asyncio.to_thread(operate)
            self._same_resources(resources)
            service._scope(scope)
            body = dict(ok=True, backend='native_personal_goals', scope=scope,
                        access='authenticated_administrator',
                        authority='role_self_directed_goals',
                        creative_projects_excluded=True,
                        creates_send_permission=False, delivery='existing_proactive_queue_only',
                        legacy_consumer_retained=True)
            if name in {'list', 'search'}:
                body.update(result)
            elif name == 'confirm_import':
                body['import'] = {key: value for key, value in result.items()
                                  if key != 'records'}
                body['records'] = result['records']
            else:
                body[{'export': 'export', 'preview_import': 'preview'}.get(name, 'record')] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except JournalConflict:
            return error_response('目标版本或迁移预览已变化，请回读后重新决定', status_code=409)
        except PermissionError:
            return error_response('需要当前后台认证及完整的逐条归属确认', status_code=403)
        except KeyError:
            return error_response('当前完整范围中找不到该原生目标', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('目标字段无效，请检查标题、类目、匹配词、进度和修订', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('目标资料暂不可用或正在重载；写操作请保留请求 ID 并回读确认',
                                  status_code=503)
        except Exception:
            return error_response('目标操作失败，请保留草稿并稍后回读确认', status_code=500)
        finally:
            if service is not None:
                service.stop()

    async def list(self):
        return await self._respond('list')

    async def detail(self):
        return await self._respond('detail')

    async def export(self):
        return await self._respond('export')

    async def search(self):
        return await self._respond('search')

    async def create(self):
        return await self._respond('create')

    async def update(self):
        return await self._respond('update')

    async def pause(self):
        return await self._respond('pause')

    async def resume(self):
        return await self._respond('resume')

    async def complete(self):
        return await self._respond('complete')

    async def abandon(self):
        return await self._respond('abandon')

    async def archive(self):
        return await self._respond('archive')

    async def restore(self):
        return await self._respond('restore')

    async def preview_import(self):
        return await self._respond('preview_import')

    async def confirm_import(self):
        return await self._respond('confirm_import')


def _scope_query(data):
    """Query scopes arrive flattened; an explicit ``private`` must say true."""
    value = {key: data.get(key) for key in SCOPE_FIELDS}
    if 'private' in data:
        private = data['private']
        if type(private) is str and private in {'true', 'false'}:
            private = private == 'true'
        value['private'] = private
    return value


def _flag(value):
    if type(value) is str and value in {'true', 'false'}:
        return value == 'true'
    if type(value) is not bool:
        raise _InvalidRequest('include_archived 必须为布尔值')
    return value


def _revision(value):
    if type(value) is not int or not 1 <= value <= 2 ** 53 - 1:
        raise _InvalidRequest('expected_revision 必须是明确的正整数')
    return value
