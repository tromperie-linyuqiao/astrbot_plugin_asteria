"""Bind only Private Companion's official one-shot cron sends to images.

Other cron jobs and normal send_message_to_user calls remain with AstrBot's
native permission and file-path handling. This module owns no scheduler.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from typing import Any

from astrbot.api import logger


def _finite(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _digest(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


class CompanionTimerMixin:
    """Optional tool boundary; pending delivery is activated by the old tick."""

    def _companion_timer_delivery_records(self, user: dict[str, Any], *, now: float | None = None) -> list[dict]:
        current = time.time() if now is None else now
        raw = user.get("companion_delivered_timers")
        return [dict(item) for item in (raw if isinstance(raw, list) else [])
                if isinstance(item, dict) and item.get("timer_id") and item.get("text_digest")
                and 0 <= current - _finite(item.get("delivered_at")) <= 86400][-32:]

    def _companion_timer_was_delivered(self, user: dict[str, Any], timer_id: str, text: str) -> bool:
        signature = _digest(text)
        return any(str(item.get("timer_id")) == str(timer_id) and item.get("text_digest") == signature
                   for item in self._companion_timer_delivery_records(user))

    def _note_companion_timer_delivered(self, user: dict[str, Any], timer_id: str, text: str) -> None:
        """Shared by immediate and native queued delivery; no extra daily count."""
        if not isinstance(user, dict) or not timer_id or not str(text).strip():
            return
        records = self._companion_timer_delivery_records(user)
        signature = _digest(text)
        records = [item for item in records
                   if not (str(item.get("timer_id")) == str(timer_id) and item.get("text_digest") == signature)]
        records.append({"timer_id": str(timer_id), "text_digest": signature, "delivered_at": time.time()})
        user["companion_delivered_timers"] = records[-32:]

    async def _companion_timer_defer(self, user: dict, text: str, timer_id: str, reason: str,
                                     retry_at: float = 0) -> str:
        # Another tool invocation can finish while this one prepares media.
        # Never enqueue a duplicate after a confirmed completion.
        unknown = getattr(self, '_companion_timer_delivery_unknown', None)
        if callable(unknown) and unknown(user, timer_id, text):
            return '此约定的平台回执不确定，已停止自动重发；不要声称已经送达。'
        if self._companion_timer_was_delivered(user, timer_id, text):
            return "此约定的图文已经发送，不要重复发送。"
        helper = getattr(self, "_defer_companion_timer_message", None)
        if not callable(helper):
            logger.error("[PrivateCompanion] 约定未发送，缺少延后队列接口")
            return "error: 此约定没有发送，延后队列不可用。不要声称已经送达。"
        lock = getattr(self, "_data_lock", None)
        try:
            if lock is not None:
                async with lock:
                    if self._companion_timer_was_delivered(user, timer_id, text):
                        return "此约定的图文已经发送，不要重复发送。"
                    value = helper(user, text, timer_id, str(reason), _finite(retry_at))
                    if hasattr(value, "__await__"):
                        await value
                    self._save_data_now_sync()
            else:
                value = helper(user, text, timer_id, str(reason), _finite(retry_at))
                if hasattr(value, "__await__"):
                    await value
                self._save_data_now_sync()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("[PrivateCompanion] 约定未发送，延后队列失败: %s", type(exc).__name__)
            return "error: 此约定没有发送，延后保存失败。不要声称已经送达或追加纯文字。"
        return "此约定消息已保留并延后重试，本轮没有发送。不要追加纯文字或重复调用发送工具。"

    def _companion_timer_block_reason(self, user: dict) -> str:
        if getattr(self, "enabled", True) is False:
            return "companion_plugin_disabled"
        quiet = getattr(self, "_is_quiet_time", None)
        if callable(quiet) and quiet():
            return "companion_quiet_hours"
        unknown = getattr(self, '_companion_uncertain_block_reason', None)
        if callable(unknown) and unknown(user, now=time.time()):
            return 'companion_delivery_ack_unknown_cooldown'
        blocker = getattr(self, "_companion_frequency_block_reason", None)
        if not callable(blocker):
            return "companion_frequency_gate_missing"
        return str(blocker(user, now=time.time(), include_sending=True) or "")

    async def _handle_companion_timer_send(self, context: Any, kwargs: dict[str, Any]) -> str | None:
        """Return None exclusively for calls still owned by AstrBot's tool."""
        try:
            event = context.context.event
            getter = getattr(event, "get_extra", None)
            payload = getter("cron_payload") if callable(getter) else None
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("origin") != "private_companion_timer":
            return None
        owned = payload.get("private_companion")
        if not isinstance(owned, dict) or not str(owned.get("timer_id") or "").strip():
            return None
        timer_id = str(owned["timer_id"]).strip()
        current_session = str(getattr(event, "unified_msg_origin", "") or "").strip()
        declared_session = str(payload.get("session") or "").strip()
        requested_session = str(kwargs.get("session") or current_session).strip()
        if not current_session or requested_session != current_session or declared_session != current_session:
            # This branch must never replace or weaken AstrBot's administrator
            # check for sending to another session.
            return "error: 此陪伴约定只允许发送到原会话，已拒绝跨会话发送。"
        resolver = getattr(self, "_proactive_chat_bridge_user", None)
        if not callable(resolver):
            return "error: 此陪伴约定没有可验证的原收件人，本轮未发送。"
        try:
            user_id, user = resolver(current_session)
        except Exception:
            return "error: 此陪伴约定无法验证原收件人，本轮未发送。"
        if not user_id or not isinstance(user, dict):
            return "error: 此陪伴约定的原收件人未受本插件管理，本轮未发送。"
        required = getattr(self, "_companion_image_required", None)
        try:
            if callable(required) and not required(user):
                return None
        except Exception:
            return "error: 此陪伴约定无法读取发送策略，本轮未发送。"
        messages = kwargs.get("messages")
        parts = [str(item.get("text") or "").strip() for item in messages
                 if isinstance(item, dict) and str(item.get("type") or "").lower() == "plain"] \
            if isinstance(messages, list) else []
        text = "\n".join(part for part in parts if part).strip()
        cleaner = getattr(self, "_sanitize_proactive_text", None)
        visible = getattr(self, "_visible_text_without_tts_reading", None)
        try:
            if callable(cleaner):
                text = str(cleaner(text) or "").strip()
            if callable(visible):
                text = str(visible(text, limit=1200) or "").strip()
        except Exception:
            return await self._companion_timer_defer(user, text, timer_id, "companion_text_validation_failed")
        if not text:
            clear = getattr(self, "_clear_companion_pending_timer", None)
            if callable(clear):
                try:
                    clear(user, timer_id, "")
                except Exception as exc:
                    logger.warning("[PrivateCompanion] 无正文约定队列清理失败: %s", type(exc).__name__)
            return "error: 此陪伴约定需要非空文字正文，本轮未发送。"
        # All original Private Companion official timer jobs are run_once.
        # The bounded 24-hour digest ledger also protects queued native retries.
        unknown = getattr(self, '_companion_timer_delivery_unknown', None)
        if (getattr(event, '_companion_timer_unknown_id', '') == timer_id
                or callable(unknown) and unknown(user, timer_id, text)):
            return '此约定的平台回执不确定，已停止自动重发；不要声称已经送达。'
        if (getattr(event, "_companion_timer_delivered_id", "") == timer_id
                or self._companion_timer_was_delivered(user, timer_id, text)):
            return "此约定的图文已经发送，不要重复发送。"
        try:
            blocked = self._companion_timer_block_reason(user)
            if blocked:
                return await self._companion_timer_defer(user, text, timer_id, blocked)
            prepare = getattr(self, "_prepare_companion_image", None)
            if not callable(prepare):
                return await self._companion_timer_defer(user, text, timer_id, "companion_image_provider_missing")
            image = await prepare(user, text, reason=str(owned.get("reason") or "companion_timer"),
                                  existing_path="", request_key='timer:' + timer_id)
            if not isinstance(image, dict) or not image.get("ok") or not image.get("path"):
                return await self._companion_timer_defer(
                    user, text, timer_id, "companion_image_unavailable",
                    _finite(image.get("retry_at")) if isinstance(image, dict) else 0)
            # Revalidate current configuration and recipient state after I/O.
            current_user_id, current_user = resolver(current_session)
            if not current_user_id or not isinstance(current_user, dict) or current_user_id != user_id:
                return await self._companion_timer_defer(user, text, timer_id, "companion_recipient_changed")
            user = current_user
            blocked = self._companion_timer_block_reason(user)
            if blocked:
                return await self._companion_timer_defer(user, text, timer_id, blocked)
            if self._companion_timer_was_delivered(user, timer_id, text):
                return "此约定的图文已经发送，不要重复发送。"
            components = list(self._build_outbound_chain(text, str(image["path"])) or [])
            plain_builder = getattr(self, "_proactive_plain_segment_component", None)
            if components and callable(plain_builder):
                components[0] = plain_builder(text, full_text=text, index=0, count=1, suppress_tts=True)
            checker = getattr(self, "_companion_chain_has_image_and_text", None)
            if not callable(checker) or not checker(components):
                return await self._companion_timer_defer(user, text, timer_id, "companion_image_and_text_required")
            sent = await self._send_companion_chain_atomic(current_session, components, timer_receipt=(timer_id, text))
            if not sent:
                return await self._companion_timer_defer(user, text, timer_id, "companion_final_send_deferred")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if getattr(exc, 'companion_delivery_unknown', False):
                setattr(event, '_companion_timer_unknown_id', timer_id)
                lock = getattr(self, '_data_lock', None)
                async def clear_unknown_retry():
                    self._clear_companion_pending_timer(user, timer_id, text)
                    try:
                        self._save_data_now_sync()
                    except Exception as save_error:
                        logger.error('[PrivateCompanion] 约定回执不确定的停止重试状态落盘暂不可用: %s', type(save_error).__name__)
                if lock is not None:
                    async with lock:
                        await clear_unknown_retry()
                else:
                    await clear_unknown_retry()
                return '此约定的平台回执不确定，已停止自动重发；不要声称已经送达。'
            logger.warning("[PrivateCompanion] 约定图文未发送，已保留原正文: %s", type(exc).__name__)
            return await self._companion_timer_defer(user, text, timer_id, "companion_timer_delivery_failed")
        # The physical send is now confirmed. Any accounting failure must not
        # classify it as an unsent event or enqueue a second copy.
        setattr(event, "_companion_timer_delivered_id", timer_id)
        lock = getattr(self, "_data_lock", None)
        async def commit():
            self._note_companion_timer_delivered(user, timer_id, text)
            clear = getattr(self, "_clear_companion_pending_timer", None)
            if callable(clear):
                clear(user, timer_id, text)
            recorder = getattr(self, "_record_companion_image_sent", None)
            if callable(recorder):
                result = recorder(user, dict(image), text=text,
                                  attempt_id="timer:" + timer_id + ":" + _digest(text)[:24], count_quota=True)
                if hasattr(result, "__await__"):
                    await result
            save = getattr(self, "_save_data_now_sync", None)
            if callable(save):
                save()
        try:
            if lock is not None:
                async with lock:
                    await commit()
            else:
                await commit()
        except Exception as exc:
            logger.error("[PrivateCompanion] 约定图文已送达，状态结算失败: %s", type(exc).__name__)
        return "图文消息已发送至原会话。本次约定已完成，不要再次发送。"
