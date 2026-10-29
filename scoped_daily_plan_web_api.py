"""Normal AstrBot admin routes for scoped virtual goal plans, never live leases."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_personal_goals import NativePersonalGoals
from .core.living.native_scoped_daily_plan import MAX_PLANS, NativeScopedDailyPlans
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/scoped-daily-plan'
MAX_BODY_BYTES = 96 * 1024
ROUTES = (('list', 'GET'), ('detail', 'GET'), ('status', 'GET'),
          ('create', 'POST'), ('generate', 'POST'), ('update', 'POST'),
          ('complete_item', 'POST'), ('cancel_item', 'POST'), ('apply', 'POST'),
          ('cancel', 'POST'), ('archive', 'POST'), ('restore', 'POST'))
PATHS = {'complete_item': 'item/complete', 'cancel_item': 'item/cancel'}


class NativeScopedDailyPlanWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name, method in ROUTES:
            self.plugin.context.register_web_api(PREFIX + '/' + PATHS.get(name, name),
                getattr(self, name), [method], 'TLS authenticated scoped virtual goal plan ' + name)

    def _resources(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'scoped_daily_plans', None)
        goals = getattr(runtime, 'personal_goals', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativeScopedDailyPlans) or service.active is not True
                or not isinstance(goals, NativePersonalGoals) or goals.active is not True
                or not isinstance(journal, LivingJournal) or service.journal is not journal
                or service.goals is not goals or goals.journal is not journal
                or getattr(journal, '_closed', True)):
            raise RuntimeError('scoped daily plans unavailable')
        return host, runtime, service, goals, journal

    def _same(self, resources):
        if any(before is not after for before, after in zip(resources, self._resources())):
            raise RuntimeError('scoped daily plan runtime changed')

    def _admin_service(self, resources, scope):
        _, _, source, goals, journal = resources

        def authorize(candidate):
            self._same(resources)
            return candidate == scope

        def progression(candidate):
            self._same(resources)
            return candidate == scope and source._progress_allowed(candidate)

        # This extra facade reads definitions under existing admin material
        # authority. Only the original live goals instance can apply activities.
        reader = NativePersonalGoals(journal, authorize=authorize, clock=goals.clock,
                                     timezone=goals.timezone_name)
        service = NativeScopedDailyPlans(journal, goals=goals, authorize=authorize,
            authorize_activity=progression, goal_reader=reader.export, clock=source.clock,
            automatic_enabled=source.automatic_enabled)
        return service, reader

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict:
            raise _InvalidRequest('请求必须为 JSON 对象')
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('计划请求过大')
        if name in {'list', 'detail', 'status'}:
            allowed = set(SCOPE_FIELDS) | {'private'} | ({'day', 'include_archived', 'limit', 'offset'} if name == 'list' else {'id'} if name == 'detail' else set())
            if set(data) - allowed:
                raise _InvalidRequest('计划查询含未知字段')
            raw_scope = {key: data.get(key) for key in SCOPE_FIELDS}
            if 'private' in data:
                raw_scope['private'] = data['private'] == 'true' if type(data['private']) is str else data['private']
            scope = _scope(raw_scope)
            if name == 'detail':
                return scope, (_text(data.get('id'), '计划 ID', 100),), {}
            if name == 'status':
                return scope, (), {}
            archive = data.get('include_archived', False)
            if type(archive) is str and archive in {'true', 'false'}:
                archive = archive == 'true'
            if type(archive) is not bool:
                raise _InvalidRequest('include_archived 必须为布尔值')
            return scope, (), dict(day=data.get('day'), include_archived=archive,
                limit=_integer(data.get('limit', 20), 'limit', 1, MAX_PLANS),
                offset=_integer(data.get('offset', 0), 'offset', 0, MAX_PLANS))
        scope = _scope(data.get('scope'))
        if name == 'create':
            if set(data) != {'scope', 'request_id', 'title', 'day', 'items'}:
                raise _InvalidRequest('新建需完整范围、稳定请求 ID、标题、日期和条目')
            return scope, (_text(data['request_id'], 'request_id', 128),), dict(title=data['title'], day=data['day'], items=data['items'])
        if name == 'generate':
            if set(data) - {'scope', 'request_id', 'day', 'limit'} or not {'scope', 'request_id', 'day'} <= set(data):
                raise _InvalidRequest('生成草稿需完整范围、稳定请求 ID 和日期')
            return scope, (_text(data['request_id'], 'request_id', 128),), dict(day=data['day'], limit=_integer(data.get('limit', 6), 'limit', 1, 12))
        identity = _text(data.get('id'), '计划 ID', 100)
        if name == 'apply':
            if set(data) != {'scope', 'id'}:
                raise _InvalidRequest('恢复推进只接受完整范围和计划 ID')
            return scope, (identity,), {}
        revision = data.get('expected_revision')
        if type(revision) is not int or not 1 <= revision <= 2 ** 53 - 1:
            raise _InvalidRequest('请提交明确的当前修订号')
        if name == 'update':
            if set(data) - {'scope', 'id', 'expected_revision', 'title', 'items'} or not {'title', 'items'} & set(data):
                raise _InvalidRequest('编辑需要标题或条目及当前修订号')
            return scope, (identity,), {key: data[key] for key in ('expected_revision', 'title', 'items') if key in data}
        if name in {'complete_item', 'cancel_item'}:
            allowed = {'scope', 'id', 'item_id', 'expected_revision'} | ({'request_id'} if name == 'complete_item' else set())
            if set(data) != allowed:
                raise _InvalidRequest('条目操作需要完整范围、计划/条目 ID 和修订号')
            kwargs = dict(expected_revision=revision)
            if name == 'complete_item':
                kwargs['request_id'] = _text(data['request_id'], 'request_id', 128)
            return scope, (identity, _text(data['item_id'], '条目 ID', 100)), kwargs
        if name in {'cancel', 'archive', 'restore'} and set(data) == {'scope', 'id', 'expected_revision'}:
            return scope, (identity,), dict(expected_revision=revision)
        raise _InvalidRequest('未知计划操作或多余字段')

    async def _respond(self, name):
        service = reader = None
        try:
            username = getattr(request, 'username', None)
            if not isinstance(username, str) or not username.strip():
                return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
            resources = self._resources()
            if name in {'list', 'detail', 'status'}:
                data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None):
                    raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (not str(length).isascii() or not str(length).isdigit() or int(length) > MAX_BODY_BYTES):
                    raise _InvalidRequest('计划请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            service, reader = self._admin_service(resources, scope)
            if name in {'create', 'generate', 'complete_item'}:
                kwargs['actor'] = username

            def operate():
                self._same(resources)
                operation = {'detail': 'get', 'status': 'diagnostics', 'apply': 'apply_completed'}.get(name, name)
                result = getattr(service, operation)(scope, *args, **kwargs)
                if name == 'detail' and result is None:
                    raise KeyError('scoped plan absent')
                self._same(resources)
                return result

            result = await asyncio.to_thread(operate)
            self._same(resources)
            body = dict(ok=True, backend='native_scoped_daily_plan', scope=scope,
                        access='authenticated_administrator', creates_runtime_lease=False,
                        virtual_evidence='roleplay_event', sends_messages=False,
                        legacy_global_plan_retained=True)
            if name == 'list':
                body.update(result)
                body['goal_options'] = await asyncio.to_thread(service.goal_options, scope)
                self._same(resources)
            else:
                body['status' if name == 'status' else 'record'] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except JournalConflict:
            return error_response('计划版本已经变化，请回读后再修改', status_code=409)
        except PermissionError:
            return error_response('缺少当前范围权限；后台维护不能创建实时会话授权', status_code=403)
        except KeyError:
            return error_response('当前范围中没有这个计划或条目', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('计划字段无效，请检查日期、未来时间、条目和修订号', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('计划服务暂不可用；写入结果未知时请按原 ID 回读，不要重复新建', status_code=503)
        finally:
            if service is not None:
                service.stop()
            if reader is not None:
                reader.stop()

    async def list(self): return await self._respond('list')
    async def detail(self): return await self._respond('detail')
    async def status(self): return await self._respond('status')
    async def create(self): return await self._respond('create')
    async def generate(self): return await self._respond('generate')
    async def update(self): return await self._respond('update')
    async def complete_item(self): return await self._respond('complete_item')
    async def cancel_item(self): return await self._respond('cancel_item')
    async def apply(self): return await self._respond('apply')
    async def cancel(self): return await self._respond('cancel')
    async def archive(self): return await self._respond('archive')
    async def restore(self): return await self._respond('restore')
