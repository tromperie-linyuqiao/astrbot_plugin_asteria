"""Copy an explicitly opted-in, confirmed QQ proactive text into owned WebChat.

The original unified sender remains the only platform sender. APP history and
its existing notification watcher consume the copy without another LLM call.
"""
from __future__ import annotations

import asyncio
import hashlib

from .chat_expressions import ChatExpressions
from .chat_identity import identity_service

NAMESPACE = 'tls.chat.notification.inbox'


def enqueue_confirmed(plugin, task):
    links = identity_service(plugin)
    row = links.for_qq(task['scope'])
    if not row or row.get('notifications') is not True: return
    text = task.get('text') or ''
    if not isinstance(text, str) or len(text) > 16000: return
    if task.get('images') or task.get('audio'):
        text += '\n（这条QQ消息含图片或语音，媒体原件可在QQ查看。）'
    if not text.strip(): return
    scope = ChatExpressions.message_scope(row['username'], row['session_id'])
    from .chat_delivery import NAMESPACE as DIRECT_NAMESPACE, key_for, notice_for_task
    # A direct Chat delivery has already persisted its own history, never copy it.
    if links.journal.fetch(DIRECT_NAMESPACE, key_for(task), scope): return
    key = hashlib.sha256(str(task['id']).encode()).hexdigest()
    with links.journal._transaction() as db:
        fresh = links.get(row['username'], row['session_id'])
        if (not links.current() or not fresh or fresh['link_id'] != row['link_id']
                or fresh.get('notifications') is not True): return
        if links.journal.fetch(NAMESPACE, key, scope): return
        # Use the same transaction and capacity contract as the journal.
        from .models import scope_key, canonical
        if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= links.journal.max_records:
            raise RuntimeError('notification inbox capacity reached')
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (NAMESPACE, key, scope_key(scope), 1,
            links.clock(), canonical(dict(state='ready', link_id=row['link_id'],
                text=text, original_task_id=str(task['id']), source='qq_confirmed_proactive',
                notice=notice_for_task(task),
                confirmed_at=links.clock()))))


async def drain_inbox(plugin, service, username, session_id, *, lock):
    links = identity_service(plugin)
    scope = ChatExpressions.message_scope(username, session_id)
    async with lock:
        link = await asyncio.to_thread(links.get, username, session_id)
        if not link or link.get('notifications') is not True: return False
        records = await asyncio.to_thread(links.journal.list, NAMESPACE, scope, limit=32)
        records = [item for item in reversed(records) if item['data'].get('link_id') == link['link_id']
            and item['data'].get('state') in {'ready', 'copying', 'unknown'}][:8]
        changed = False
        for record in records:
            fresh = await asyncio.to_thread(links.get, username, session_id)
            if not fresh or fresh['link_id'] != link['link_id']: break
            snapshot = await service.get_session(username, session_id)
            data = record['data']
            # A previous save may have completed after its HTTP caller was
            # interrupted. First reconcile its stable original task reference.
            found = any(isinstance(item.get('content'), dict)
                and ((item['content'].get('refs') or {}).get('tls_proactive_task') == data['original_task_id'])
                for item in snapshot.get('history', [])
                if isinstance(item, dict) and isinstance(item.get('content'), dict)
                and isinstance(item['content'].get('refs', {}), dict))
            if found:
                await asyncio.to_thread(links.journal.put, NAMESPACE, record['key'], scope,
                    dict(data, state='copied'), expected_revision=record['revision'], authorize=links.current)
                continue
            if data['state'] != 'ready': continue  # Unknown copies are never reissued.
            copying = await asyncio.to_thread(links.journal.put, NAMESPACE, record['key'], scope,
                dict(data, state='copying'), expected_revision=record['revision'], authorize=links.current)
            try:
                refs={'tls_proactive_task':data['original_task_id'], 'source':'qq_confirmed_proactive'}
                notice=data.get('notice')
                if isinstance(notice,dict) and notice.get('schema')==1 and notice.get('kind') in {'reminder','proactive'}:
                    refs['tls_notice']=dict(schema=1,kind=notice['kind'])
                await service.save_bot_message(session_id,
                    [{'type':'plain', 'text':data['text']}], {},
                    refs)
            except BaseException:
                # The persistent copying state is deliberately retained for
                # GET reconciliation; do not turn it into another send retry.
                raise
            await asyncio.to_thread(links.journal.put, NAMESPACE, record['key'], scope,
                dict(data, state='copied'), expected_revision=copying['revision'], authorize=links.current)
            changed = True
        return changed
