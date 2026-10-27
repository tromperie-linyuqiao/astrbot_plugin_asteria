"""Select one destination inside the original durable sender, never dual-send."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from .chat_expressions import ChatExpressions
from .chat_identity import identity_service
from .chat_workspace import ChatWorkspace
from .delivery_sender import BeforeDispatchError
from .models import canonical

NAMESPACE = 'tls.chat.direct_delivery'


def key_for(task):
    return hashlib.sha256(canonical([task['scope'], task['id']]).encode()).hexdigest()


def notice_for_task(task):
    """Presentation provenance from the existing durable lane, never from text."""
    from .reminders import LANE
    return dict(schema=1, kind='reminder' if task.get('delivery_lane') == LANE else 'proactive')


class ChatDeliveryAdapter:
    supports_audio = True

    def __init__(self, plugin, original, *, database=None):
        self.plugin, self.original, self.database = plugin, original, database
        self.media_root = getattr(original, 'media_root', None)

    async def healthy(self, session):
        # A fully migrated Chat destination is independent of QQ connectivity.
        # Resolve only an already observed identity; this read grants no lease.
        presence = getattr(getattr(self.plugin, '_presence', None), 'api', None)
        scope = presence.peek_scope_for_session(session) if presence is not None else None
        if scope is not None:
            target = self._target(dict(scope=scope, images=[], audio=None))
            direct = scope['platform'] == scope['bot_id'] == 'webchat'
            if target is not None:
                links = identity_service(self.plugin)
                all_media = direct or ChatWorkspace(links).settings(target['username'], target['session_id'])['values']['proactive_destination'] == 'chat_all'
                if all_media:
                    if self.database is None:
                        from astrbot.core import db_helper
                        database = db_helper
                    else: database = self.database
                    selected = await database.get_platform_session_by_id(target['session_id'])
                    return bool(selected is not None and selected.creator == target['username']
                        and selected.is_group == 0 and selected.platform_id == 'webchat'
                        and selected.session_id == target['session_id'])
        return await self.original.healthy(session)

    def _target(self, task):
        links = identity_service(self.plugin)
        scope = task['scope']
        if scope['platform'] == scope['bot_id'] == 'webchat':
            prefix = 'webchat!' + scope['user_id'] + '!'
            session = scope['session_id'].split(':', 2)[-1]
            if not session.startswith(prefix): raise BeforeDispatchError('invalid_app_origin')
            return dict(username=scope['user_id'], session_id=session[len(prefix):], link_id=None)
        link = links.for_qq(scope)
        if not link: return None
        prefs = ChatWorkspace(links).settings(link['username'], link['session_id'])['values']
        mode = prefs['proactive_destination']
        if mode not in {'chat_text', 'chat_all'} or (mode == 'chat_text' and (task.get('images') or task.get('audio'))):
            return None
        return dict(username=link['username'], session_id=link['session_id'], link_id=link['link_id'])

    def prepare(self, task):
        chain = self.original.prepare(task)
        target = self._target(task)
        return dict(chain=chain, target=target)

    async def send(self, task, prepared):
        target = prepared['target']
        if target is None:
            return await self.original.send(task, prepared['chain'])
        # Permission changes after prepare cannot silently select QQ instead.
        if self._target(task) != target: raise BeforeDispatchError('chat_destination_changed')
        if self.database is None:
            from astrbot.core import db_helper
            database = db_helper
        else: database = self.database
        session = await database.get_platform_session_by_id(target['session_id'])
        if (session is None or session.creator != target['username'] or session.is_group != 0
                or session.platform_id != 'webchat' or session.session_id != target['session_id']):
            return False
        links = identity_service(self.plugin)
        scope = ChatExpressions.message_scope(target['username'], target['session_id'])
        key = key_for(task)
        def reserve():
            with links.journal._lock:
                row = links.journal.fetch(NAMESPACE, key, scope)
                if row: return row, False
                if self._target(task) != target: raise BeforeDispatchError('chat_destination_changed')
                return links.journal.put(NAMESPACE, key, scope, dict(state='writing', task_id=task['id'],
                    target=target, source='tls_chat_direct'), expected_revision=0,
                    authorize=lambda: links.current() and self._target(task) == target), True
        receipt, new = await asyncio.to_thread(reserve)
        if not new:
            if receipt['data']['state'] == 'stored': return True
            # A late SDK insert can only be reconciled; never repeat the insert.
            history = await database.get_platform_message_history(platform_id='webchat', user_id=target['session_id'], page_size=1000)
            found = any(isinstance(item.content, dict) and isinstance(item.content.get('refs'), dict)
                and item.content['refs'].get('tls_delivery_key') == key for item in history)
            if not found: return None
        else:
            from astrbot.core.platform.sources.webchat.message_parts_helper import message_chain_to_storage_message_parts
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            parts = await message_chain_to_storage_message_parts(prepared['chain'],
                insert_attachment=database.insert_attachment,
                attachments_dir=Path(get_astrbot_data_path())/'attachments')
            if not parts: return False
            if self._target(task) != target: raise BeforeDispatchError('chat_destination_changed')
            await database.insert_platform_message_history(platform_id='webchat', user_id=target['session_id'],
                content=dict(type='bot', message=parts, refs=dict(tls_delivery_key=key,
                    tls_proactive_task=task['id'], source='tls_chat_direct', tls_notice=notice_for_task(task))),
                sender_id='bot', sender_name='bot')
        await asyncio.to_thread(links.journal.put, NAMESPACE, key, scope,
            dict(receipt['data'], state='stored'), expected_revision=receipt['revision'], authorize=links.current)
        return True  # Durable Chat history, not a phone notification/read ACK.
