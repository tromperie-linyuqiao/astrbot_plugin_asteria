"""One confirmed image/text delivery with a shared frequency ledger."""
from __future__ import annotations
import asyncio
import hashlib
import time
from typing import Any
from .helpers import _today_key
from astrbot.api import logger


class CompanionDeliveryUncertainError(RuntimeError):
    """Dispatch began but no reliable acknowledgement was obtained."""
    companion_delivery_unknown = True

    def __init__(self, transport: str, failure: Exception):
        super().__init__('平台发送回执不确定，已停止本条消息的自动重发')
        self.transport = str(transport)
        self.failure_type = type(failure).__name__


class CompanionDeliveryMixin:
    @staticmethod
    def _companion_timer_delivery_unknown(user: dict, timer_id: str, text: str) -> bool:
        raw = user.get('companion_uncertain_deliveries')
        digest = hashlib.sha256(str(text).encode()).hexdigest()
        return any(isinstance(item, dict) and item.get('timer_id') == str(timer_id)
                   and item.get('text_digest') == digest and 0 <= time.time() - float(item.get('at') or 0) <= 86400
                   for item in (raw if isinstance(raw, list) else []))

    @staticmethod
    def _companion_delivery_uncertain_exception(transport: str, failure: Exception) -> CompanionDeliveryUncertainError:
        return CompanionDeliveryUncertainError(transport, failure)

    @staticmethod
    def _companion_mark_uncertain_cancellation(transport: str, failure: BaseException) -> None:
        failure.companion_delivery_unknown = True
        failure.transport = str(transport)
        failure.failure_type = type(failure).__name__

    def _companion_uncertain_block_reason(self, user: dict, *, now: float | None = None) -> str:
        now = time.time() if now is None else now
        raw = user.get('companion_uncertain_deliveries')
        records = [item for item in (raw if isinstance(raw, list) else [])
                   if isinstance(item, dict) and 0 <= now - float(item.get('at') or 0) <= 86400]
        if not records:
            return ''
        interval = getattr(self, '_companion_min_interval_minutes', lambda: 45)() * 60
        if now - max(float(item['at']) for item in records) < interval:
            return '上次平台回执不确定，保留主动消息冷却'
        today = _today_key()
        reserved = sum(item.get('day') == today for item in records)
        confirmed = max(int(user.get('companion_sent_today') or 0) if user.get('companion_sent_day') == today else 0,
                        int(user.get('sent_today') or 0) if str(user.get('sent_day') or today) == today else 0)
        limit = getattr(self, '_companion_max_daily_messages', lambda: 8)()
        if confirmed + reserved >= limit:
            return '今日主动消息次数已含不确定送达预留'
        return ''

    def _companion_delivery_user(self, umo: str) -> dict | None:
        _user_id, user = self._proactive_chat_bridge_user(str(umo or ''))
        return user if isinstance(user, dict) and str(user.get('umo') or '') == str(umo) else None

    def _companion_final_send_block_reason(self, umo: str) -> str:
        user = self._companion_delivery_user(umo)
        if user is None or not getattr(self, 'enabled', False):
            return '陪伴插件或私聊目标不可用'
        if not self._user_enabled_for_proactive(str(user.get('user_id') or user.get('id') or ''), user):
            return '私聊目标已停用'
        uncertain = self._companion_uncertain_block_reason(user)
        if uncertain:
            return uncertain
        reason = self._companion_frequency_block_reason(user, now=time.time())
        if reason:
            return reason
        # Explicit availability never overrides the user's sleep/quiet window.
        if self._is_quiet_time():
            return '免打扰时段'
        rest = getattr(self, '_proactive_rest_block_until', None)
        if callable(rest) and rest(user, now=time.time()) > time.time():
            return '用户明确休息中'
        quota = getattr(self, '_companion_image_quota_ok', None)
        if callable(quota) and not quota(user):
            return '今日主动图片额度已满'
        return ''

    async def _companion_finish_dispatch_commit(self, commit: Any, *, transport: str) -> None:
        """Finish the small local ledger commit even if the caller is cancelled.

        Cancellation is re-raised after persistence, including repeated cancellation
        while waiting for the data lock. The dispatch must not become retryable.
        """
        task = asyncio.create_task(commit)
        cancellation = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                if task.cancelled():
                    raise
                self._companion_mark_uncertain_cancellation(transport, exc)
                cancellation = cancellation or exc
        task.result()
        if cancellation is not None:
            raise cancellation

    async def _send_companion_chain_atomic(self, umo: str, components: list[Any], *,
                                         timer_receipt: tuple[str, str] | None = None) -> bool:
        if not self._companion_chain_has_image_and_text(components):
            return False
        locks = getattr(self, '_companion_delivery_locks', None)
        if not isinstance(locks, dict):
            locks = self._companion_delivery_locks = {}
        if umo not in locks and len(locks) >= 256:
            unlocked = next((key for key, lock in locks.items() if not lock.locked()), None)
            if unlocked is None:
                return False
            locks.pop(unlocked)
        lock = locks.setdefault(umo, asyncio.Lock())
        async with lock:
            if self._companion_final_send_block_reason(umo):
                return False
            delivery_user = self._companion_delivery_user(umo)
            fingerprint = self._companion_delivery_fingerprint(components)
            if (delivery_user is None or not all(fingerprint)
                    or self._companion_image_was_used(delivery_user, fingerprint[0], digest=fingerprint[1])):
                return False
            try:
                sent = await self._send_chain_components(umo, components, require_companion_image=True)
            except (Exception, asyncio.CancelledError) as exc:
                if not getattr(exc, 'companion_delivery_unknown', False):
                    raise
                # A reservation is deliberately separate from confirmed-sent
                # counters/history. It protects the same cooldown and daily cap.
                async def commit_unknown():
                    async with self._data_lock:
                        user = self._companion_delivery_user(umo) or delivery_user
                        if user is not None:
                            now = time.time()
                            self._companion_consume_image(user, fingerprint[0], digest=fingerprint[1], status='unknown', now=now)
                            raw = user.get('companion_uncertain_deliveries')
                            records = [item for item in (raw if isinstance(raw, list) else [])
                                       if isinstance(item, dict) and 0 <= now - float(item.get('at') or 0) <= 86400]
                            timer_id, timer_text = timer_receipt or ('', '')
                            records.append({'at': now, 'day': _today_key(), 'transport': getattr(exc, 'transport', ''),
                                            'failure_type': getattr(exc, 'failure_type', ''),
                                            'image_digest': fingerprint[1],
                                            'timer_id': str(timer_id), 'text_digest': hashlib.sha256(str(timer_text).encode()).hexdigest() if timer_id else '',
                                            'receipt': hashlib.sha256(f'{umo}|{now}'.encode()).hexdigest()})
                            user['companion_uncertain_deliveries'] = records[-64:]
                            try:
                                self._save_data_now_sync()
                            except Exception as save_error:
                                logger.error('[PrivateCompanion] 回执不确定的冷却预留落盘暂不可用: %s', type(save_error).__name__)
                await self._companion_finish_dispatch_commit(commit_unknown(), transport='companion_unknown_commit')
                raise
            if not sent:
                return False
            # Commit before releasing the common per-session send lock. The
            # legacy counters settle separately after history/accounting.
            async def commit_confirmed():
                async with self._data_lock:
                    user = self._companion_delivery_user(umo) or delivery_user
                    if user is not None:
                        self._companion_consume_image(user, fingerprint[0], digest=fingerprint[1], status='sent')
                        today = _today_key()
                        count = int(user.get('companion_sent_today') or 0) if user.get('companion_sent_day') == today else 0
                        legacy = int(user.get('sent_today') or 0) if str(user.get('sent_day') or today) == today else 0
                        used = max(count, legacy)
                        photo_count = int(user.get('companion_photo_sent_today') or 0) if user.get('companion_photo_sent_day') == today else 0
                        legacy_photo = int(user.get('photo_sent_today') or 0) if user.get('photo_sent_day') == today else 0
                        user.update(companion_sent_day=today, companion_sent_today=used + 1,
                                    companion_last_sent_at=time.time(), companion_photo_sent_day=today,
                                    companion_photo_sent_today=max(photo_count, legacy_photo) + 1)
                        timer_id, timer_text = timer_receipt or ('', '')
                        if timer_id and timer_text and user.get('companion_timer_retry_id') == timer_id and user.get('companion_timer_retry_text') == timer_text:
                            self._note_companion_timer_delivered(user, timer_id, timer_text)
                            self._clear_companion_pending_timer(user, timer_id, timer_text)
                        try:
                            self._save_data_now_sync()
                        except Exception as exc:
                            logger.error('[PrivateCompanion] 图文已送达，计数落盘暂不可用: %s', type(exc).__name__)
            await self._companion_finish_dispatch_commit(commit_confirmed(), transport='companion_confirmed_commit')
            return True

    def _record_companion_image_sent(self, user: dict, payload: dict, *, text: str = '',
                                     attempt_id: str = '', count_quota: bool = True) -> None:
        if not payload.get('ok') or not payload.get('path'):
            return
        seen = user.setdefault('companion_image_receipts', [])
        if not isinstance(seen, list):
            seen = user['companion_image_receipts'] = []
        if attempt_id and attempt_id in seen:
            return
        if attempt_id:
            seen.append(str(attempt_id)[:160]);del seen[:-32]
        if count_quota:
            today = _today_key()
            count = int(user.get('photo_sent_today') or 0) if user.get('photo_sent_day') == today else 0
            user.update(photo_sent_day=today, photo_sent_today=count + 1)
        self._companion_record_image_sent(user, str(payload['path']), theme=str(payload.get('theme') or ''))

    def _defer_companion_timer_message(self, user: dict, text: str, timer_id: str,
                                      reason: str = '', retry_at: float = 0) -> None:
        now = time.time()
        raw = user.get('companion_pending_timers')
        raw = raw if isinstance(raw, list) else []
        queue = [x for x in raw if isinstance(x, dict) and float(x.get('expires_at') or 0) > now]
        matching = next((x for x in queue if x.get('timer_id') == timer_id and x.get('text') == text), None)
        if matching is None:
            matching = {'timer_id':str(timer_id)[:128], 'text':str(text)[:4000],
                        'reason':str(reason)[:180], 'created_at':now, 'expires_at':now + 86400}
            queue.append(matching)
        matching['retry_at'] = max(now + 60, float(retry_at or now + 900))
        user['companion_pending_timers'] = queue[-8:]

    def _clear_companion_pending_timer(self, user: dict, timer_id: str, text: str) -> None:
        raw = user.get('companion_pending_timers')
        if isinstance(raw, list):
            user['companion_pending_timers'] = [x for x in raw if not (
                isinstance(x, dict) and x.get('timer_id') == timer_id and x.get('text') == text)]
        if user.get('companion_timer_retry_id') == timer_id and user.get('companion_timer_retry_text') == text:
            user.pop('companion_timer_retry_id', None);user.pop('companion_timer_retry_text', None)

    def _activate_companion_pending_timer(self, user: dict, *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        raw = user.get('companion_pending_timers')
        if not isinstance(raw, list) or user.get('proactive_sending'):
            return False
        user['companion_pending_timers'] = [x for x in raw if isinstance(x, dict) and float(x.get('expires_at') or 0) > now]
        if user.get('pending_proactive_send_retry') or user.get('planned_proactive_reason'):
            return False
        already = getattr(self, '_companion_timer_was_delivered', None)
        item = next((x for x in user['companion_pending_timers'] if float(x.get('retry_at') or 0) <= now
                     and not (callable(already) and already(user, x['timer_id'], x['text']))
                     and not self._companion_timer_delivery_unknown(user, x['timer_id'], x['text'])), None)
        if item is None:
            return False
        user.update(companion_timer_retry_id=item['timer_id'], companion_timer_retry_text=item['text'],
                    planned_proactive_reason='check_in', planned_proactive_action='message',
                    planned_proactive_source='companion_timer_retry', next_proactive_at=now,
                    planned_proactive_window_start_at=now, planned_proactive_best_until_at=item['expires_at'],
                    planned_proactive_expire_at=item['expires_at'])
        key = self._planned_proactive_delivery_key(user)
        user.update(planned_proactive_origin_key=key, planned_proactive_origin_at=now,
                    planned_proactive_freshness='durable', planned_proactive_delivery_state='fresh')
        user['pending_proactive_send_retry'] = {
            'text':item['text'], 'image_path':'', 'extra_components':[], 'reason':'check_in',
            'action':'message', 'action_summary':'延后执行已授权的预约', 'created_at':now, 'active':True,
            'updated_at':now, 'expires_at':item['expires_at'], 'fresh_until_at':item['expires_at'],
            'delivery_key':key, 'freshness':'durable',
            'private_activity_at':self._latest_private_user_activity_ts(user),
            'private_inbound_count':int(user.get('private_inbound_count') or 0), 'retry_count':0,
        }
        return True
