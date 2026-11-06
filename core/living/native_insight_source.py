"""Read-only projections of AstrBot's conversation and dashboard interfaces."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math


class InsightSourceUnavailable(RuntimeError):
    pass


_ITEM_BYTES = 256 * 1024
_SAMPLE_BYTES = 2 * 1024 * 1024


def _stamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if isinstance(value, datetime):
            return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
        if type(value) in (int, float) and math.isfinite(value):
            return float(value)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _history(row):
    raw = getattr(row, 'history', None)
    if not isinstance(raw, str):
        raise InsightSourceUnavailable('conversation_shape_unavailable')
    if len(raw) > _ITEM_BYTES:
        raise InsightSourceUnavailable('conversation_sample_budget_exceeded')
    return raw


def _decode(raw):
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InsightSourceUnavailable('conversation_json_unavailable') from exc
    if not isinstance(rows, list):
        raise InsightSourceUnavailable('conversation_shape_unavailable')
    return rows


class AstrBotConversationReader:
    """Use exact UMO APIs. Never open the database or ask AstrBot to create history."""

    def __init__(self, context):
        self.manager = getattr(context, 'conversation_manager', None)

    async def _call(self, name, *args, **kwargs):
        method = getattr(self.manager, name, None)
        if not callable(method):
            raise InsightSourceUnavailable('conversation_api_unavailable')
        try:
            return await method(*args, **kwargs)
        except InsightSourceUnavailable:
            raise
        except Exception as exc:
            raise InsightSourceUnavailable('conversation_api_read_failed') from exc

    @staticmethod
    def _session(value):
        if (not isinstance(value, str) or not 0 < len(value) <= 1024
                or len(value.split(':', 2)) != 3 or any(ord(ch) < 32 for ch in value)):
            raise ValueError('exact conversation identity required')
        return value

    async def _get(self, session_id, cid):
        if not isinstance(cid, str) or not cid:
            return None
        row = await self._call('get_conversation', session_id, cid, create_if_not_exists=False)
        # Some AstrBot versions look up the CID before checking the UMO.
        if row is not None and (getattr(row, 'user_id', None) != session_id or getattr(row, 'cid', None) != cid):
            raise InsightSourceUnavailable('conversation_identity_mismatch')
        return row

    async def current_history(self, session_id):
        session_id = self._session(session_id)
        row = await self._get(session_id, await self._call('get_curr_conversation_id', session_id))
        if row is None:
            return []
        return await asyncio.to_thread(self._bounded_decode, _history(row))

    @staticmethod
    def _bounded_decode(raw):
        if len(raw.encode('utf-8')) > _ITEM_BYTES:
            raise InsightSourceUnavailable('conversation_sample_budget_exceeded')
        return _decode(raw)

    async def conversations(self, *, since, session_id, limit=60):
        if type(limit) is not int or not 1 <= limit <= 60 or (minimum := _stamp(since)) is None:
            raise ValueError('bounded conversation sample required')
        session_id = self._session(session_id)
        rows = await self._call('get_conversations', session_id)
        if not isinstance(rows, (tuple, list)):
            raise InsightSourceUnavailable('conversation_shape_unavailable')
        if any(getattr(row, 'user_id', None) != session_id for row in rows):
            raise InsightSourceUnavailable('conversation_identity_mismatch')
        return await asyncio.to_thread(self._project, rows, minimum, limit)

    async def calibration_sample(self, *, since, limit, authorized):
        """Page metadata first; fetch the content only for current allowed private scopes."""
        if type(limit) is not int or not 1 <= limit <= 30 or (minimum := _stamp(since)) is None:
            raise ValueError('bounded conversation sample required')
        rows, _ = await self._call('get_filtered_conversations', page=1, page_size=limit,
                                   message_types=['FriendMessage'], include_history=False)
        chosen = []
        for row in rows[:limit]:
            umo = getattr(row, 'user_id', None)
            stamp = _stamp(getattr(row, 'updated_at', None))
            if (stamp is None or stamp < minimum or not isinstance(umo, str)
                    or ':FriendMessage:' not in umo or authorized(umo) is not True):
                continue
            self._session(umo)
            result = await self._get(umo, getattr(row, 'cid', None))
            if result is not None and authorized(umo) is True:
                chosen.append(result)
        return await asyncio.to_thread(self._project, chosen, minimum, limit)

    @staticmethod
    def _project(rows, minimum, limit):
        eligible = [(stamp, row) for row in rows
                    if (stamp := _stamp(getattr(row, 'updated_at', None))) is not None and stamp >= minimum]
        eligible.sort(key=lambda item: item[0], reverse=True)
        result, total = [], 0
        for stamp, row in eligible[:limit]:
            raw = _history(row)
            size = len(raw.encode('utf-8'))
            total += size
            if size > _ITEM_BYTES or total > _SAMPLE_BYTES:
                raise InsightSourceUnavailable('conversation_sample_budget_exceeded')
            _decode(raw)
            result.append(dict(content=raw, updated_at=stamp))
        return result


class AstrBotUsageReader:
    """Project the host's statistics API; never infer missing per-session fields."""

    def __init__(self, context):
        self.context = context

    async def _stats(self, days):
        # This is the same supported service the AstrBot dashboard uses. Older
        # AstrBot builds may not expose it; return unavailable rather than SQL.
        try:
            from astrbot.core import db_helper
            from astrbot.dashboard.services.stat_service import StatService
            service = StatService(db_helper, None, self.context.get_config())
            result = await service.get_provider_token_stats(days)
        except Exception as exc:
            raise InsightSourceUnavailable('dashboard_usage_api_unavailable') from exc
        if not isinstance(result, dict) or result.get('days') != days:
            raise InsightSourceUnavailable('dashboard_usage_shape_unavailable')
        return result

    async def usage(self, days, *, session_id=None):
        effective = 7 if days >= 7 else 3 if days >= 3 else 1
        value = await self._stats(effective)
        scoped = session_id is not None
        common = dict(requested_days=days, days=effective, by_model=[], daily=[], hourly=[],
                      coverage='current_private_session' if scoped else 'administrator_server_aggregate',
                      source='astrbot_dashboard_statistics', monetary_cost='not_available_without_pricing')
        if scoped:
            rows = value.get('range_by_umo')
            if not isinstance(rows, list):
                raise InsightSourceUnavailable('scoped_usage_not_supported')
            tokens = sum(int(row.get('tokens') or 0) for row in rows if row.get('umo') == session_id)
            return dict(common, state='available' if tokens else 'empty', totals=dict(tokens=tokens, calls=None))
        if not {'range_total_calls', 'range_total_tokens', 'range_by_provider', 'trend'} <= set(value):
            raise InsightSourceUnavailable('dashboard_usage_shape_unavailable')
        provider = value['range_by_provider']
        common['by_model'] = [dict(model=str(row['provider_id'])[:120], tokens=int(row['tokens']),
                                   calls=None, avg_ttft=None) for row in provider[:30]]
        per_day = Counter()
        zone = timezone(timedelta(hours=8))
        for millis, tokens in value['trend'].get('total_series', ()):
            per_day[datetime.fromtimestamp(millis / 1000, zone).date().isoformat()] += int(tokens)
        common['daily'] = [dict(day=day, tokens=tokens, calls=None) for day, tokens in sorted(per_day.items())]
        calls = int(value['range_total_calls'])
        return dict(common, state='available' if calls else 'empty',
                    totals=dict(tokens=int(value['range_total_tokens']), calls=calls),
                    avg_ttft_ms=value.get('range_avg_ttft_ms'), models_truncated=len(provider) > 30,
                    time_zone='UTC+08:00')
