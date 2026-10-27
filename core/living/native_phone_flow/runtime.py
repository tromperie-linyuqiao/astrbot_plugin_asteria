"""TLS-owned complete pacing runtime, with explicit host/store ownership.

Reuses the existing preference schema and event/cooldown ledger. It does not
collect PPB, alter ListeningStreams, or create any polling task. Existing SDK
hooks/routes must be transferred once by the host before use.
"""
from __future__ import annotations

import asyncio
import copy
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import StarTools
from astrbot.api.web import error_response, json_response, request
from astrbot.core.agent.message import TextPart

from .config import ConfigSection
from .batching import MessageBatcher
from .policy import DEFAULTS, build_hint, effective_preferences, parse_control, validate_preferences, validate_settings
from .store import PreferenceStore

PLUGIN_NAME = "astrbot_plugin_virtual_body"
HOST_PLUGIN_NAME = PLUGIN_NAME
VERSION = "0.2.0"


class NativePhoneFlow:
    def __init__(self, context, config: ConfigSection, save_lock: asyncio.Lock, *,
                 store_path, authorize_session, register_routes=False,
                 manual_quiet_key="living_phone_respect_manual_quiet"):
        if not callable(authorize_session):
            raise ValueError("explicit existing-session authorization required")
        if type(register_routes) is not bool:
            raise ValueError("explicit route registration flag required")
        if manual_quiet_key not in {"living_phone_respect_manual_quiet", "phone_respect_manual_quiet"}:
            raise ValueError("unsupported manual-quiet configuration key")
        self._manual_quiet_key = manual_quiet_key
        self._authorize_session = authorize_session
        self.context = context
        self.config = config
        self.settings = validate_settings({k: config[k] for k in DEFAULTS if k in config})
        self.config.update(copy.deepcopy(self.settings))
        self.store = PreferenceStore(store_path)
        self.batcher = MessageBatcher()
        self._active = True
        self._save_lock = save_lock
        self._connected_producers: set[str] = set()
        self._notices: dict[int, asyncio.Task] = {}
        self._integrated_sends = 0
        if register_routes:
            self.register_routes()

    def register_routes(self):
        for path, handler, methods in (
            ("settings", self.settings_get, ["GET"]),
            ("settings/save", self.settings_save, ["POST"]),
            ("sessions", self.sessions_get, ["GET"]),
            ("session", self.session_get, ["GET"]),
            ("session/save", self.session_save, ["POST"]),
            ("session/clear", self.session_clear, ["POST"]),
            ("session/quiet", self.session_quiet, ["POST"]),
            ("session/resume", self.session_resume, ["POST"]),
            ("diagnostics", self.diagnostics_get, ["GET"]),
        ):
            self.context.register_web_api(f"/{PLUGIN_NAME}/phone-integration/flow/{path}", handler, methods, "TLS 手机感知与聊天节奏")

    def _runtime(self):
        phone_quiet = bool(self.config.parent.get(self._manual_quiet_key, False))
        return {"version": VERSION, "target_astrbot": "4.26.6", "active": self._active,
                "pending_batches": self.batcher.pending,
                "host_plugin": HOST_PLUGIN_NAME,
                "proactive_integration": "connected" if self._connected_producers else "phone_manual_quiet" if phone_quiet else "internal_api_ready",
                "phone_manual_quiet_enabled": phone_quiet,
                "phone_shared_cooldown_enabled": False,
                "proactive_rule_note": "手机沿用现有提醒与节流规则，仅手动免打扰可选；其他主动插件需显式调用节奏接口。",
                "connected_producers": sorted(self._connected_producers),
                "integrated_send_attempts": self._integrated_sends}

    def _guard(self):
        if not self._active:
            raise RuntimeError("插件已停用，请重载页面")
        if not request.username:
            raise PermissionError("请先登录 AstrBot 管理页面")

    async def _api(self, operation):
        try:
            self._guard()
            return json_response(await operation())
        except PermissionError as exc:
            return error_response(str(exc), status_code=401)
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
        except RuntimeError as exc:
            return error_response(str(exc), status_code=503)
        except Exception:
            logger.exception("聊天节奏助手管理操作失败")
            return error_response("操作失败，请检查插件日志和数据目录权限", status_code=503)

    async def _body(self):
        body = await request.json(default={})
        if not isinstance(body, dict):
            raise ValueError("请求必须是 JSON 对象")
        return body

    async def settings_get(self):
        async def run():
            return {"ok": True, "settings": copy.deepcopy(self.settings), "runtime": self._runtime()}
        return await self._api(run)

    async def diagnostics_get(self):
        async def run():
            return {"ok": True, "runtime": self._runtime()}
        return await self._api(run)

    async def settings_save(self):
        async def run():
            body = await self._body()
            async with self._save_lock:
                updated = validate_settings(body.get("settings"), self.settings)
                old = self.config.snapshot()
                self.config.update(copy.deepcopy(updated))
                try:
                    await asyncio.to_thread(self.config.save_config)
                except Exception as exc:
                    self.config.restore(old)
                    raise RuntimeError("配置保存失败，原配置已保留") from exc
                self.settings = updated
                # A window/range change must not keep applying stale batch rules.
                await self.batcher.release()
            return {"ok": True, "settings": copy.deepcopy(updated), "runtime": self._runtime()}
        return await self._api(run)

    async def _session(self, umo):
        overrides = await asyncio.to_thread(self.store.get, umo)
        return {"umo": umo, "preferences": overrides,
                "effective": effective_preferences(self.settings, overrides, time.time())}

    async def sessions_get(self):
        async def run():
            rows = await asyncio.to_thread(self.store.list_sessions)
            for row in rows:
                row["effective"] = effective_preferences(self.settings, row["preferences"], time.time())
            return {"ok": True, "sessions": rows}
        return await self._api(run)

    async def session_get(self):
        async def run():
            umo = request.query.get("umo")
            return {"ok": True, "session": await self._session(umo)}
        return await self._api(run)

    async def session_save(self):
        async def run():
            body = await self._body()
            patch = validate_preferences(body.get("preferences"))
            await asyncio.to_thread(self.store.put, body.get("umo"), patch)
            return {"ok": True, "session": await self._session(body.get("umo"))}
        return await self._api(run)

    async def session_clear(self):
        async def run():
            body = await self._body()
            await asyncio.to_thread(self.store.clear, body.get("umo"))
            return {"ok": True, "session": await self._session(body.get("umo"))}
        return await self._api(run)

    async def _quiet_api(self, resume=False):
        async def run():
            body = await self._body()
            minutes = body.get("minutes")
            if not resume and (type(minutes) is not int or not 1 <= minutes <= 1440):
                raise ValueError("安静时间需要是 1–1440 分钟的整数")
            await asyncio.to_thread(self.store.put, body.get("umo"), {"quiet_until": 0 if resume else time.time() + minutes * 60})
            return {"ok": True, "session": await self._session(body.get("umo"))}
        return await self._api(run)

    async def session_quiet(self):
        return await self._quiet_api()

    async def session_resume(self):
        return await self._quiet_api(resume=True)

    def _eligible(self, event):
        if not self._active or not self.settings["enabled"] or not event.is_private_chat():
            return False
        return self._scope_reason(event.unified_msg_origin) is None

    async def _preferences(self, umo):
        return effective_preferences(self.settings, await asyncio.to_thread(self.store.get, umo), time.time())

    async def _control(self, event, text):
        if not self._eligible(event):
            return False
        control = parse_control(text, time.time(), self.settings["busy_default_minutes"], self.settings["timezone_offset_minutes"])
        if control is None:
            return False
        self.batcher.flush(event.unified_msg_origin)
        if control.get("clear"):
            await asyncio.to_thread(self.store.clear, event.unified_msg_origin)
        else:
            await asyncio.to_thread(self.store.put, event.unified_msg_origin, control["preferences"])
        if not self._eligible(event):
            return False
        event.stop_event()
        reply = control["reply"]
        if "quiet_until" in control["preferences"]:
            if control["preferences"]["quiet_until"] > time.time():
                if self.config.parent.get(self._manual_quiet_key, False):
                    reply = "已记录本会话手动免打扰，手机提醒也会暂停。你可以照常发消息。"
                else:
                    reply = "已记录本会话手动免打扰。手机提醒仍按原规则执行，你可以照常发消息。"
            else:
                reply = "本会话手动免打扰已结束。"
        await event.send(event.plain_result(reply))
        return True

    async def flow_command(self, event: AstrMessageEvent, action: str = ""):
        if not self._eligible(event):
            yield event.plain_result("聊天节奏设置请在私聊中使用。")
            event.stop_event()
            return
        shortcuts = {"listen": "先听我说", "solve": "帮我想办法", "auto": "恢复自动模式",
                     "resume": "恢复主动聊天", "reset": "清除聊天偏好", "busy": "我现在忙，稍后再聊"}
        if action in shortcuts and await self._control(event, shortcuts[action]):
            return
        prefs = await self._preferences(event.unified_msg_origin)
        if not self._eligible(event):
            return
        yield event.plain_result(f"当前模式：{prefs['mode']}，长度：{prefs['reply_length']}。\n/flow listen 倾听，/flow solve 想办法，/flow auto 自动，/flow busy 安静，/flow resume 恢复，/flow reset 清除。\n自然说‘少用列表’‘回答简短一点’也可以。感知与聊天节奏在此统一设置。")
        event.stop_event()

    async def wait_for_message(self, event: AstrMessageEvent):
        if not self._eligible(event):
            return
        # Structured content and custom provider requests must keep their original
        # attachments, quotes, parameters and plugin-specific handling.
        components = event.get_messages()
        text = event.message_str
        if event.get_extra("provider_request") is not None or not components or any(not isinstance(c, Plain) for c in components):
            self.batcher.flush(event.unified_msg_origin)
            return
        if await self._control(event, text):
            return
        if not self.settings["merge_enabled"] or not text.strip() or text.lstrip().startswith(("/", "!", "！")):
            self.batcher.flush(event.unified_msg_origin)
            return
        merged = await self.batcher.submit(event.unified_msg_origin, text, self.settings)
        if not self._eligible(event):
            return
        if merged is None:
            event.stop_event()
        elif merged != text:
            event.message_str = merged
            event.message_obj.message_str = merged
            event.message_obj.message = [Plain(merged)]
            event.set_extra("dialogue_flow_merged", True)

    async def style_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self._eligible(event):
            return
        if event.get_extra("dialogue_flow_hint_added"):
            return
        try:
            preferences = await self._preferences(event.unified_msg_origin)
        except Exception:
            logger.warning("聊天偏好读取失败，本轮按默认节奏继续；请检查数据目录")
            preferences = effective_preferences(self.settings, {}, time.time())
        if not self._eligible(event):
            return
        hint = build_hint(preferences, event.message_str)
        if hint:
            req.extra_user_content_parts.append(TextPart(text=hint).mark_as_temp())
            event.set_extra("dialogue_flow_hint_added", True)
        if self.settings["notice_enabled"]:
            async def notice():
                await asyncio.sleep(self.settings["notice_delay_seconds"])
                if self._eligible(event):
                    try:
                        await event.send(event.plain_result("这轮还在处理中，稍等我一下。"))
                    except Exception:
                        logger.warning("聊天节奏等待提示发送失败")
            notice_key = id(event)
            previous = self._notices.pop(notice_key, None)
            if previous:
                previous.cancel()
            task = asyncio.create_task(notice())
            self._notices[notice_key] = task
            task.add_done_callback(lambda finished: self._notices.pop(notice_key, None) if self._notices.get(notice_key) is finished else None)

    async def finish_notice(self, event: AstrMessageEvent, response):
        task = self._notices.pop(id(event), None)
        if task:
            task.cancel()

    def mark_producer_connected(self, name: str):
        if name:
            self._connected_producers.add(str(name))

    def _scope_reason(self, umo):
        if not self._active:
            return "unavailable"
        if not self.settings["enabled"]:
            return "disabled"
        if not isinstance(umo, str) or len(umo.split(":", 2)) != 3 or umo.split(":", 2)[1] != "FriendMessage":
            return "private_only"
        try:
            if self._authorize_session(umo) is not True:
                return "unauthorized"
        except Exception:
            return "unauthorized"
        allowed = self.settings["allowed_sessions"]
        if allowed and umo not in allowed:
            return "outside_scope"
        return None

    async def quiet_reason(self, umo):
        """Read explicit quiet without reserving or changing delivery history."""
        if self._scope_reason(umo):
            return None
        preferences = await asyncio.to_thread(self.store.get, umo)
        return "quiet" if preferences.get("quiet_until", 0) > time.time() else None

    async def _reserve_delivery(self, umo, event_key, *, bypass_cooldown=False):
        """Reserve just before submit; bypass does not remove explicit quiet."""
        reason = self._scope_reason(umo)
        if reason:
            return {"allowed": False, "reason": reason, "lease": None}
        self._integrated_sends += 1
        cooldown = 0 if bypass_cooldown else self.settings["proactive_cooldown_minutes"] * 60
        return await asyncio.to_thread(self.store.reserve_proactive, umo, event_key, time.time(), cooldown)

    async def _finish_delivery(self, lease, success):
        return await asyncio.to_thread(self.store.finish_proactive, lease, success, time.time())

    async def send_proactive(self, umo, event_key, chain):
        reservation = await self._reserve_delivery(umo, event_key)
        if not reservation["allowed"]:
            return {"sent": False, "reason": reservation["reason"]}
        if self._scope_reason(umo) is not None:
            await self._finish_delivery(reservation["lease"], False)
            return {"sent": False, "reason": "unauthorized"}
        try:
            delivered = await self.context.send_message(umo, chain)
        except Exception:
            # Keep the short lease: an exception cannot prove non-delivery.
            logger.warning("主动消息提交结果不确定；未自动重试")
            return {"sent": False, "reason": "delivery_uncertain"}
        # AstrBot returns bool; older adapters returned None on successful submit.
        sent = delivered is not False
        await self._finish_delivery(reservation["lease"], sent)
        return {"sent": sent, "reason": "submitted" if sent else "platform_missing"}

    async def terminate(self):
        self._active = False
        await self.batcher.close()
        tasks = list(self._notices.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._notices.clear()
        await asyncio.to_thread(self.store.close)
