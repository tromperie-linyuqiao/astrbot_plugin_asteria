"""Bounded append catch-up from the existing SDK message table.

No event outbox, cursor database, sender or polling loop is created. The API
checks private session ownership before calling, and again before returning.
Normal /history remains authoritative for edits/deletes and the active run.
"""
from __future__ import annotations

from sqlmodel import select
from astrbot.core.db.po import PlatformMessageHistory
from astrbot.dashboard.services.chat_service import serialize_history_entry

LIMIT = 100


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
