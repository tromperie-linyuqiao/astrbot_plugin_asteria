"""Owned Chat views of existing important-date definitions; no scheduling lane."""
from __future__ import annotations

import asyncio

from .chat_identity import identity_service
from .chat_workspace import ChatWorkspace, actual_app_scope
from .native_important_dates import FIELDS, NativeImportantDates


def _service(plugin):
    host = plugin._presence.living_host
    runtime = host.runtime
    service = getattr(runtime, 'important_dates', None)
    if (getattr(plugin, '_stopping', False) or getattr(host, '_closed', True)
            or not getattr(runtime, 'active', False)
            or not isinstance(service, NativeImportantDates) or not service.active):
        raise RuntimeError('重要日期服务暂不可用')
    return host, runtime, service


def _same_resources(plugin, resources):
    return all(current is expected for current, expected in zip(_service(plugin), resources))


def _owned_service(plugin, username, session, scope, resources):
    """Recheck the real APP scope inside every existing journal transaction."""
    host, runtime, original = resources
    def authorize(candidate):
        return (candidate == scope and _same_resources(plugin, resources)
                and actual_app_scope(plugin, username, session) == scope
                and original.authorize(candidate) is True)
    return NativeImportantDates(original.journal, authorize=authorize, clock=original.clock)


async def important_dates_view(plugin, username, session_id, session):
    resources = _service(plugin)
    scope = actual_app_scope(plugin, username, session)
    records, sources, birthdays = [], [], []
    if scope is not None:
        service = _owned_service(plugin, username, session, scope, resources)
        try:
            data = await asyncio.to_thread(service.export, scope, include_archived=True)
            records.extend(dict(row, source='chat', editable=True) for row in data['records'])
            sources.append(dict(source='chat', state='available'))
        except PermissionError:
            sources.append(dict(source='chat', state='scope_unavailable'))
        finally:
            service.active = False
    links = identity_service(plugin)
    link = links.get(username, session_id)
    if link and ChatWorkspace(links).settings(username, session_id)['values']['linked_calendar']:
        selected = link['qq_scope']
        original = resources[-1]
        def linked_authorized():
            fresh = links.get(username, session_id)
            return (_same_resources(plugin, resources) and links.current()
                    and fresh == link
                    and ChatWorkspace(links).settings(username, session_id)['values']['linked_calendar'])
        def authorized(candidate):
            return candidate == selected and linked_authorized() and original.authorize(candidate) is True
        reader = NativeImportantDates(original.journal, authorize=authorized, clock=original.clock)
        try:
            data = await asyncio.to_thread(reader.export, selected, include_archived=True)
            if authorized(selected):
                records.extend(dict(row, source='qq', editable=False) for row in data['records'])
                sources.append(dict(source='qq', state='available'))
        except PermissionError:
            sources.append(dict(source='qq', state='scope_unavailable'))
        finally:
            reader.active = False
        owner = getattr(plugin, '_native_pc_full', None)
        service = getattr(owner, 'service', None)
        if owner is not None and owner.active and service is not None and service.active:
            def birthday_authorized():
                return (linked_authorized() and plugin._native_pc_full is owner
                        and owner.service is service and owner.active and service.active)
            try:
                special = await service.get_special_settings(selected['user_id'], authorize=birthday_authorized)
                profile = special.get('values', {}).get('birthday_profile')
                if profile and birthday_authorized():
                    birthdays.append(dict(profile=profile, source='qq_special_settings', editable=False,
                        revision=special.get('revision'), updated_at=special.get('updated_at'),
                        timezone=special.get('calendar', {}).get('timezone')))
            except (PermissionError, RuntimeError, ValueError):
                sources.append(dict(source='qq_special_settings', state='scope_unavailable'))
        if not linked_authorized():
            records = [row for row in records if row['source'] != 'qq']
            birthdays = []
            sources = [row for row in sources if row['source'] != 'qq']
            sources.append(dict(source='qq', state='scope_unavailable'))
    if not _same_resources(plugin, resources) or actual_app_scope(plugin, username, session) != scope:
        raise PermissionError('日期范围已变化，请重新读取')
    return dict(records=records, total=len(records), sources=sources, birthdays=birthdays, writable=scope is not None,
                source='tls_native_important_dates',
                state='available' if scope else 'waiting_for_real_app_message',
                capabilities=dict(create=True, update=True, archive=True, restore=True),
                definitions_only=True, creates_send_permission=False)


async def important_dates_save(plugin, username, session_id, session, body):
    resources = _service(plugin)
    scope = actual_app_scope(plugin, username, session)
    if scope is None:
        raise PermissionError('请先在当前APP会话正常聊一句，再维护重要日期')
    if type(body) is not dict or body.get('session_id') != session_id:
        raise ValueError('请提供当前会话与明确日期操作')
    action = body.get('action')
    required = {'session_id', 'action'} | ({'request_id', 'fields'} if action == 'create'
               else {'id', 'expected_revision', 'fields'} if action == 'update'
               else {'id', 'expected_revision'} if action in {'archive', 'restore'} else set())
    if action not in {'create', 'update', 'archive', 'restore'} or set(body) != required:
        raise ValueError('请选择新增、编辑、移除或恢复重要日期')
    if action in {'create', 'update'} and (type(body['fields']) is not dict or set(body['fields']) != FIELDS):
        raise ValueError('请提交完整的九项日期定义字段')
    service = _owned_service(plugin, username, session, scope, resources)
    try:
        if action == 'create':
            return await asyncio.to_thread(service.create, scope, body['request_id'], **body['fields'])
        options = dict(expected_revision=body['expected_revision'])
        if action == 'update':
            options.update(body['fields'])
        return await asyncio.to_thread(getattr(service, action), scope, body['id'], **options)
    finally:
        service.active = False
