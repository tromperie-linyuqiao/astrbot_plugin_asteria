"""Chat calendar/read permissions over the existing scoped TLS services."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .chat_expressions import ChatExpressions, ChatExpressionError

NAMESPACE = 'tls.chat.workspace'
DEFAULTS = dict(shared_memory=True, linked_calendar=False, linked_activity=True, linked_perception=False, proactive_destination='qq')


class ChatWorkspace:
    def __init__(self, links):
        self.links = links

    def settings(self, username, session_id):
        self.links._check()
        row = self.links.journal.fetch(NAMESPACE, 'settings', ChatExpressions.message_scope(username, session_id))
        data = row['data'] if row else {}
        values = dict(DEFAULTS, **{key:data[key] for key in DEFAULTS if key in data})
        link = self.links.get(username, session_id)
        if not link or data.get('link_id') != link['link_id']:
            values.update(linked_calendar=False, linked_perception=False, proactive_destination='qq')
        return dict(values=values, revision=row['revision'] if row else 0)

    def save(self, username, session_id, changes, revision):
        if type(changes) is not dict or not changes or set(changes) - set(DEFAULTS):
            raise ChatExpressionError('请选择明确的查阅权限或发送位置')
        for key, value in changes.items():
            if key != 'proactive_destination' and type(value) is not bool:
                raise ChatExpressionError('查阅权限须为开关')
        if changes.get('proactive_destination', 'qq') not in {'qq', 'chat_text', 'chat_all'}:
            raise ChatExpressionError('发送位置无效')
        if (changes.get('linked_calendar') or changes.get('linked_activity') or changes.get('linked_perception') or changes.get('proactive_destination') in {'chat_text','chat_all'}) and not self.links.get(username, session_id):
            raise ChatExpressionError('请先在真实QQ私聊确认绑定')
        if type(revision) is not int or revision < 0: raise ChatExpressionError('请先读取当前配置')
        with self.links.journal._lock:
            current = self.settings(username, session_id)
            values = dict(current['values'], **changes)
            link = self.links.get(username, session_id)
            self.links.journal.put(NAMESPACE, 'settings', ChatExpressions.message_scope(username, session_id),
                dict(values, link_id=link['link_id'] if link else None), expected_revision=revision, authorize=lambda: self.links.current() and (
                    not values['linked_calendar'] and not values['linked_perception'] and values['proactive_destination'] == 'qq'
                    or (self.links.get(username, session_id) or {}).get('link_id') == (link or {}).get('link_id')))
        return self.settings(username, session_id)


def linked_source_scope(plugin, scope, *, permission='delivery'):
    """Resolve an explicit pair's source without remembering/granting a QQ lease.

    Delivery follows the user's selected Chat destination. Phone data additionally
    requires its separate revocable read permission; original phone ACLs still run.
    """
    from .models import private_scope
    from .chat_identity import identity_service
    try:
        scope=private_scope(scope)
        if permission not in {'delivery','perception'} or scope['platform']!=scope['bot_id'] or scope['platform']!='webchat':return None
        host=plugin._presence.living_host
        if host.authorized_scope(scope) is not True:return None
        origin=scope['session_id'].split(':',2)[-1];prefix='webchat!'+scope['user_id']+'!'
        if not origin.startswith(prefix):return None
        session=origin[len(prefix):];links=identity_service(plugin);row=links.get(scope['user_id'],session)
        if (not row or row.get('app_scope')!=scope or not row.get('app_persona')
                or row['qq_scope'].get('character_id')!=scope['character_id']):return None
        settings=ChatWorkspace(links).settings(scope['user_id'],session)['values']
        if permission=='delivery' and settings['proactive_destination'] not in {'chat_text','chat_all'}:return None
        if permission=='perception' and settings['linked_perception'] is not True:return None
        source=private_scope(row['qq_scope'])
        if links.get(scope['user_id'],session)!=row or not links.current() or host.authorized_scope(scope) is not True:return None
        return source
    except (AttributeError,KeyError,TypeError,ValueError,RuntimeError):
        return None


def actual_app_scope(plugin, username, session):
    from astrbot.dashboard.services.chat_service import build_webchat_unified_msg_origin
    presence = plugin._presence
    umo = build_webchat_unified_msg_origin(session)
    scope = presence.api.peek_scope_for_session(umo)
    if (isinstance(scope, dict) and scope.get('platform') == scope.get('bot_id') == 'webchat'
            and scope.get('user_id') == username and scope.get('session_id') == umo
            and scope.get('private') is True and presence.living_host.authorized_scope(scope)):
        return scope
    return None


async def calendar_view(plugin, links, username, session_id, scope):
    runtime = plugin._presence.living_host.runtime
    settings = ChatWorkspace(links).settings(username, session_id)
    link = links.get(username, session_id)
    rows, notes, sources = [], [], []
    scopes = [('chat', scope)] if scope else []
    if link and settings['values']['linked_calendar']:
        scopes.append(('qq', link['qq_scope']))
    for label, selected in scopes:
        try:
            # Reuse each original service's ACL as well as the explicit read grant.
            values = await asyncio.to_thread(runtime.agenda.list, selected, limit=100)
            rows.extend(dict(item, source=label, editable=label == 'chat') for item in values)
            memo = getattr(runtime, 'memo_notes', None)
            if memo is not None:
                result = await asyncio.to_thread(memo.search, selected, limit=100)
                values = result.get('records', []) if isinstance(result, dict) else result
                notes.extend(dict(item, source=label) for item in values)
            sources.append(dict(source=label, state='available'))
        except (PermissionError, RuntimeError, ValueError):
            sources.append(dict(source=label, state='scope_unavailable'))
        if label == 'qq':
            try:
                owner = getattr(plugin, '_native_pc_full', None)
                service = getattr(owner, 'service', None)
                if owner is not None and owner.active and service is not None and service.active:
                    def authorized():
                        fresh = links.get(username, session_id)
                        return bool(fresh and fresh['link_id'] == link['link_id']
                                    and fresh['qq_scope'] == selected
                                    and ChatWorkspace(links).settings(username, session_id)['values']['linked_calendar']
                                    and plugin._native_pc_full is owner and owner.service is service and owner.active)
                    special = await service.get_special_settings(selected['user_id'], authorize=authorized)
                    timetable = special['calendar']
                    provisional = '（教学周暂定，待核对）' if not timetable['anchor_confirmed'] else ''
                    for item in timetable['items']:
                        start = datetime.fromtimestamp(item['start_at'], timezone.utc).isoformat()
                        rows.append(dict(id='course:' + item['id'], source='qq', editable=False,
                            due_at=start, content='【课程】' + item['name'] + ' · ' + item['location']
                            + ' · 第' + str(item['week']) + '周' + provisional,
                            status='课表', task_state='课前提醒受主动消息权限与节奏限制',
                            end_at=datetime.fromtimestamp(item['end_at'], timezone.utc).isoformat()))
                    sources.append(dict(source='course_timetable', state='available',
                                        anchor_confirmed=timetable['anchor_confirmed']))
            except (PermissionError, RuntimeError, ValueError):
                sources.append(dict(source='course_timetable', state='scope_unavailable'))
    if link:
        fresh = links.get(username, session_id)
        if not fresh or fresh['link_id'] != link['link_id'] or not ChatWorkspace(links).settings(username, session_id)['values']['linked_calendar']:
            rows = [row for row in rows if row['source'] != 'qq']
            notes = [row for row in notes if row['source'] != 'qq']
    return dict(items=sorted(rows, key=lambda row:row['due_at']), notes=notes, sources=sources,
        writable=scope is not None, state='available' if scope else 'waiting_for_real_app_message',
        settings=settings, linked=bool(link), limit_per_source=100,
        capabilities=dict(periodic=True,restore=True,recurrence_choices=['none','daily','weekly','monthly','yearly']),
        note='日程沿用TLS原生提醒；QQ事项仅查阅。新APP提醒保存到当前长期会话。')
