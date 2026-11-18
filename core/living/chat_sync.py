"""Bounded append catch-up from the existing SDK message table.

No event outbox, cursor database, sender or polling loop is created. The API
checks private session ownership before calling, and again before returning.
Normal /history remains authoritative for edits/deletes and the active run.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select
from astrbot.core.db.po import PlatformMessageHistory
from astrbot.dashboard.services.chat_service import serialize_history_entry

LIMIT = 100
HISTORY_WINDOW_LIMIT = 80


def capability():
    return dict(schema=1, supported=True, mode='saved_rows_after_id', limit=LIMIT,
        server_push=False, edits_and_deletes='normal_history_refresh')


def cursor(value, *, optional=False):
    if value is None and optional:
        return None
    if (not isinstance(value, str) or not value.isascii() or not value.isdigit()
            or len(value) > 19 or str(int(value)) != value
            or not 0 <= int(value) <= 9223372036854775807):
        raise ValueError('同步游标必须为实际服务器消息编号')
    return int(value)


def _saved_companion_filters(session_id):
    content = PlatformMessageHistory.content
    refs = content['refs']
    notice = refs['tls_notice']
    return (
        PlatformMessageHistory.platform_id == 'webchat',
        PlatformMessageHistory.user_id == session_id,
        content['type'].as_string() == 'bot',
        refs['source'].as_string() == 'tls_chat_direct',
        func.json_type(content, '$.refs.tls_notice.schema') == 'integer',
        notice['schema'].as_integer() == 1,
        notice['kind'].as_string() == 'proactive',
        notice['mode'].as_string() == 'companion',
    )


async def has_saved_companion_delivery(database, session_id, delivery_key):
    """Confirm one exact direct companion delivery in the caller's owned session."""
    stored_key = PlatformMessageHistory.content['refs']['tls_delivery_key'].as_string()
    query = select(PlatformMessageHistory.id).where(
        *_saved_companion_filters(session_id), stored_key == delivery_key,
    ).limit(1)
    async with database.get_db() as db:
        return (await db.execute(query)).scalar_one_or_none() is not None


async def saved_latest_companion(database, session_id):
    """Find the latest saved direct companionship turn in one owned WebChat."""
    query = (select(PlatformMessageHistory).where(*_saved_companion_filters(session_id))
             .order_by(PlatformMessageHistory.id.desc()).limit(1))
    async with database.get_db() as db:
        row = (await db.execute(query)).scalar_one_or_none()
    return [] if row is None else [serialize_history_entry(row)]


async def saved_window(database, session_id, *, limit, before_id=None, message_id=None):
    """Read one bounded page from the same private WebChat history as sync."""
    owned = (PlatformMessageHistory.platform_id == 'webchat',
             PlatformMessageHistory.user_id == session_id)
    query = select(PlatformMessageHistory).where(*owned)
    mode = 'recent'
    if message_id is not None:
        mode = 'message'
        query = query.where(PlatformMessageHistory.id == message_id)
        limit = 1
    elif before_id is not None:
        mode = 'before'
        query = query.where(PlatformMessageHistory.id < before_id)
    async with database.get_db() as db:
        rows = (await db.execute(query.order_by(PlatformMessageHistory.id.desc())
                                 .limit(limit + 1))).scalars().all()
    return ([serialize_history_entry(row) for row in reversed(rows[:limit])],
            dict(schema=1, mode=mode, has_older=len(rows) > limit))


async def saved_after(database, session_id, after_id=None, *, limit=LIMIT):
    if type(limit) is not int or not 1 <= limit <= LIMIT:
        raise ValueError('同步批次为1至100条')
    if after_id is not None and (type(after_id) is not int or after_id < 0):
        raise ValueError('同步游标无效')
    owned = (PlatformMessageHistory.platform_id == 'webchat',
             PlatformMessageHistory.user_id == session_id)
    async with database.get_db() as db:
        latest = (await db.execute(select(PlatformMessageHistory.id).where(*owned)
            .order_by(PlatformMessageHistory.id.desc()).limit(1))).scalar()
        head = int(latest or 0)
        common = dict(message_sync=capability(), latest_id=str(head),
            append_only=True, ordering='server_message_id_ascending')
        if after_id is None:
            return dict(common, bootstrap=True, history=[], next_after_id=str(head),
                anchor_found=True, reset_required=False, has_more=False)
        anchor_found = after_id == 0
        if after_id:
            anchor_found = (await db.execute(select(PlatformMessageHistory.id)
                .where(*owned, PlatformMessageHistory.id == after_id).limit(1))).scalar() is not None
        if not anchor_found or after_id > head:
            return dict(common, bootstrap=False, history=[], next_after_id=str(after_id),
                anchor_found=False, reset_required=True, reason='cursor_unavailable', has_more=False)
        rows = (await db.execute(select(PlatformMessageHistory).where(*owned,
            PlatformMessageHistory.id > after_id, PlatformMessageHistory.id <= head)
            .order_by(PlatformMessageHistory.id.asc()).limit(limit + 1))).scalars().all()
        batch = rows[:limit]
        return dict(common, bootstrap=False, history=[serialize_history_entry(row) for row in batch],
            next_after_id=str(batch[-1].id if batch else after_id), anchor_found=True,
            reset_required=False, has_more=len(rows) > limit)
