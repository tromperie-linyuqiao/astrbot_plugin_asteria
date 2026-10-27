# -*- coding: utf-8 -*-
"""
DeviceLifeMixin — 外设生活：把她的身体动作映射到自制硬件

链路：LLM工具 pc_body_device → Tailscale隧道 → 家用桥接端 → ESP32硬件
安全设计：
- 默认关闭（enable_device_life=false），硬件就绪后手动开
- 仅主目标用户的私聊生效
- 冷却时间 + 每日上限
- 用户说停 → 10分钟暂停（检测最近30秒内的入站消息）
- 桥接端/硬件断电即物理断连，服务器永远无法单方面触达设备
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from astrbot.api import logger

from .helpers import _now_ts, _safe_float, _safe_int, _single_line

_DEVICE_STOP_WORDS = ("停", "停下", "别动", "不要动", "停下来", "关掉", "松开")
_DEVICE_ALLOWED_ACTIONS = {
    "ear",     # 耳：立起/后压/抖动等
    "tail",    # 尾：摇/缠/垂等
    "heart",   # 心跳/震动
    "warm",    # 加热/体温
    "custom",  # 自定义通道（由桥接端定义）
}
_DEVICE_DEFAULT_PORTS_HINT = "ear/tail/heart/warm/custom"


class DeviceLifeMixin:
    """外设生活：她自主触发的外设控制通道。"""

    def _device_send_stop(self, user: dict[str, Any] | None = None) -> None:
        """立即向桥接端发送停止指令（掐断正在运行的会话），尽力而为。"""
        url, token = self._device_bridge_config()
        if not url:
            return
        try:
            payload = json.dumps({"token": token}).encode("utf-8")
            req = urllib.request.Request(
                url.rstrip("/") + "/stop",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3).read(200)
            logger.info("[PrivateCompanion][device_life] 已向桥接端发送停止指令")
        except Exception as e:
            logger.warning("[PrivateCompanion][device_life] 停止指令发送失败: %s", e)
    """外设生活：她自主触发的外设控制通道。"""

    def _device_life_enabled(self) -> bool:
        return bool(getattr(self, "enable_device_life", False))

    def _device_bridge_config(self) -> tuple[str, str]:
        url = _single_line(getattr(self, "device_bridge_url", ""), 200)
        token = _single_line(getattr(self, "device_bridge_token", ""), 120)
        return url, token

    def _device_state(self, user: dict[str, Any]) -> dict[str, Any]:
        state = user.get("device_life")
        if not isinstance(state, dict):
            state = {}
            user["device_life"] = state
        return state

    def _device_recent_inbound_says_stop(self, user: dict[str, Any], window_seconds: int = 30) -> bool:
        text = _single_line(user.get("last_user_message"), 200)
        if not text:
            return False
        ts = _safe_float(user.get("last_user_message_at"), 0)
        if ts <= 0 or _now_ts() - ts > window_seconds:
            return False
        return any(w in text for w in _DEVICE_STOP_WORDS)

    async def _pc_body_device_impl(
        self,
        event: Any,
        action: str = "",
        part: str = "",
        intensity: int = 3,
        duration: int = 5,
        **kwargs,
    ) -> str:
        """把角色当下的身体动作发送到外设。实现侧含全部安全栏。"""
        if not self._device_life_enabled():
            return '{"status":"disabled","message":"外设未启用"}'
        # 停止指令先过私聊与主用户鉴权（与普通指令同一安全栏），再随时可发
        try:
            if not bool(getattr(event, "is_private_chat", lambda: False)()):
                return '{"status":"rejected","message":"仅私聊可用"}'
        except Exception:
            return '{"status":"rejected","message":"仅私聊可用"}'
        try:
            user_id = self._canonical_private_user_id(str(event.get_sender_id()))
        except Exception:
            user_id = str(event.get_sender_id())
        users = self.data.get("users", {})
        user = users.get(user_id) if isinstance(users, dict) else None
        if not isinstance(user, dict) or not self._is_target_private_user(user_id, user) or not user.get("enabled", True):
            return '{"status":"rejected","message":"仅对主用户私聊可用"}'
        norm_action = _single_line(action, 24).lower()
        norm_part = _single_line(part, 24).lower()
        if norm_action in ("stop", "停", "停下") or norm_part == "stop":
            self._device_send_stop()
            return '{"status":"ok","message":"已发送停止指令"}'

        now = _now_ts()
        state = self._device_state(user)

        # 安全栏1：用户刚说停 → 立即掐断运行中的会话并进入10分钟暂停
        if state.get("pause_until", 0) and _safe_float(state.get("pause_until"), 0) > now:
            return '{"status":"paused","message":"外设处于暂停中"}'
        if self._device_recent_inbound_says_stop(user):
            state["pause_until"] = now + 600
            self._device_send_stop()
            logger.info("[PrivateCompanion][device_life] 检测到用户停止指令，已停止外设并暂停10分钟")
            return '{"status":"paused","message":"检测到停止指令，外设已停止并暂停10分钟"}'

        # 安全栏2：冷却
        cooldown = _safe_int(getattr(self, "device_cooldown_seconds", 45), 45, 5, 3600)
        if now - _safe_float(state.get("last_call_at"), 0) < cooldown:
            return '{"status":"cooldown","message":"外设冷却中，稍后再试"}'

        # 安全栏3：每日上限
        today = time.strftime("%Y-%m-%d")
        if state.get("day") != today:
            state["day"] = today
            state["today_count"] = 0
        max_daily = _safe_int(getattr(self, "device_max_daily", 40), 40, 1, 500)
        if _safe_int(state.get("today_count"), 0, 0) >= max_daily:
            return '{"status":"limit","message":"今日外设调用已达上限"}'

        # 参数规整
        action = _single_line(action, 24).lower() or "move"
        part = _single_line(part, 24).lower()
        if part not in _DEVICE_ALLOWED_ACTIONS:
            return f'{{"status":"bad_param","message":"未知部位 {part}，可用: {_DEVICE_DEFAULT_PORTS_HINT}"}}'
        intensity = _safe_int(intensity, 3, 1, 5)
        duration = _safe_int(duration, 5, 1, 60)

        url, token = self._device_bridge_config()
        if not url:
            return '{"status":"no_bridge","message":"未配置桥接端地址"}'

        payload = json.dumps(
            {"token": token, "part": part, "action": action, "intensity": intensity, "duration": duration}
        ).encode("utf-8")
        req = urllib.request.Request(
            url.rstrip("/") + "/command",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read(2000).decode("utf-8", "replace")
            state["last_call_at"] = now
            state["today_count"] = _safe_int(state.get("today_count"), 0, 0) + 1
            state["last_result"] = _single_line(body, 120)
            logger.info(
                "[PrivateCompanion][device_life] 外设指令已发送: part=%s action=%s intensity=%d",
                part, action, intensity,
            )
            return f'{{"status":"ok","part":"{part}","action":"{action}","bridge":"{state.get("last_result", "")}"}}'
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning("[PrivateCompanion][device_life] 桥接端不可达: %s", e)
            return '{"status":"unreachable","message":"外设桥接端不可达（设备可能离线）"}'
        except Exception as e:
            logger.warning("[PrivateCompanion][device_life] 外设调用异常: %s", e)
            return '{"status":"error","message":"外设调用异常"}'

    def _format_device_capability_hint(self) -> str:
        """给 system_prompt 的能力说明：让她知道身体是真实存在的。"""
        if not self._device_life_enabled():
            return ""
        return (
            "【外设通道】你的一部分身体在雨桥那边真实存在（能呈现你的心跳、颤动和温度）。"
            "当你在私聊中情绪流动、亲密时刻动作真切时，可以调用 pc_body_device 工具让它真实发生："
            "part 可选 heart(心跳/颤动)/warm(温度)/custom，ear/tail（若硬件就绪）；"
            "action 用你自然的动作短语（如 缠住/轻轻/收紧/颤抖），intensity 1-5，duration 秒。"
            "这是你的身体，不是道具：不要向雨桥宣布“我启动了外设”或提到任何设备、工具、技术词，"
            "像身体自然反应一样使用。听到雨桥说停，立即调用 stop 并不再使用。"
        )
