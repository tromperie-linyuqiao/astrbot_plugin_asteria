"""Validated settings and explicit conversational preference commands.

This module has no framework or model dependencies. It never infers a person's
feelings from device telemetry or persists the supplied message text.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULTS = {
    "enabled": True,
    "allowed_sessions": [],
    "merge_enabled": True,
    "merge_window_seconds": 1.2,
    "merge_max_wait_seconds": 4.0,
    "merge_max_messages": 8,
    "merge_max_chars": 4000,
    "default_mode": "auto",
    "default_reply_length": "auto",
    "default_less_lists": True,
    "default_less_questions": True,
    "busy_default_minutes": 60,
    "notice_enabled": False,
    "notice_delay_seconds": 6,
    "proactive_cooldown_minutes": 20,
    "timezone_offset_minutes": 480,
}

MODES = frozenset({"auto", "listen", "solve"})
REPLY_LENGTHS = frozenset({"auto", "short", "normal", "detailed"})
PREFERENCE_KEYS = frozenset(
    {"mode", "reply_length", "less_lists", "less_questions", "quiet_until"}
)


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}必须是对象")
    return dict(value)


def validate_umo(value: Any) -> str:
    """A stable AstrBot session identifier, not a user-supplied alias."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 512
        or any(unicodedata.category(ch) == "Cc" for ch in value)
    ):
        raise ValueError("会话标识必须是 1–512 字符的非空文本，且不能含控制字符")
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name}必须为布尔值")
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name}必须为数字")
    try:
        numeric = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{name}必须为有限数字") from None
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        raise ValueError(f"{name}必须在 {minimum:g}–{maximum:g} 之间")
    return numeric


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name}必须为 {minimum}–{maximum} 之间的整数")
    return value


def _choice(value: Any, name: str, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{name}的值不受支持")
    return value


def validate_settings(patch: Any, current: Any = None) -> dict:
    """Merge settings atomically; reject unknown fields and invalid full state."""
    result = deepcopy(DEFAULTS)
    candidates = [patch] if current is None else [current, patch]
    for candidate in candidates:
        updates = _mapping(candidate, "设置")
        unknown = set(updates) - set(DEFAULTS)
        if unknown:
            raise ValueError("存在未知设置字段")
        result.update(updates)
    for name in (
        "enabled",
        "merge_enabled",
        "default_less_lists",
        "default_less_questions",
        "notice_enabled",
    ):
        result[name] = _boolean(result[name], name)
    result["default_mode"] = _choice(result["default_mode"], "default_mode", MODES)
    result["default_reply_length"] = _choice(
        result["default_reply_length"], "default_reply_length", REPLY_LENGTHS
    )
    for name, minimum, maximum in (
        ("merge_window_seconds", 0.2, 10.0),
        ("merge_max_wait_seconds", 0.2, 30.0),
        ("notice_delay_seconds", 0.5, 120.0),
    ):
        result[name] = _number(result[name], name, minimum, maximum)
    if result["merge_max_wait_seconds"] < result["merge_window_seconds"]:
        raise ValueError("最长等待时间不能小于连续消息等待窗口")
    for name, minimum, maximum in (
        ("merge_max_messages", 1, 50),
        ("merge_max_chars", 100, 20000),
        ("busy_default_minutes", 1, 1440),
        ("proactive_cooldown_minutes", 0, 1440),
        ("timezone_offset_minutes", -720, 840),
    ):
        result[name] = _integer(result[name], name, minimum, maximum)
    sessions = result["allowed_sessions"]
    if not isinstance(sessions, list) or len(sessions) > 200:
        raise ValueError("允许的会话必须是最多 200 项的列表")
    result["allowed_sessions"] = list(dict.fromkeys(validate_umo(s) for s in sessions))
    return result


def validate_preferences(patch: Any) -> dict:
    """Validate only supplied preference fields; no implicit defaults are saved."""
    result = _mapping(patch, "聊天偏好")
    if set(result) - PREFERENCE_KEYS:
        raise ValueError("存在未知聊天偏好字段")
    for name, choices in (("mode", MODES), ("reply_length", REPLY_LENGTHS)):
        if name in result:
            result[name] = _choice(result[name], name, choices)
    for name in ("less_lists", "less_questions"):
        if name in result:
            result[name] = _boolean(result[name], name)
    if "quiet_until" in result:
        result["quiet_until"] = _number(
            result["quiet_until"], "quiet_until", 0, float("inf")
        )
    return result


def effective_preferences(settings: Any, overrides: Any, now: float) -> dict:
    validated = validate_settings({}, settings)
    result = {
        "mode": validated["default_mode"],
        "reply_length": validated["default_reply_length"],
        "less_lists": validated["default_less_lists"],
        "less_questions": validated["default_less_questions"],
        "quiet_until": 0.0,
    }
    result.update(validate_preferences(overrides))
    current_time = _number(now, "now", 0, float("inf"))
    if result["quiet_until"] <= current_time:
        result["quiet_until"] = 0.0
    return result


def parse_control(
    text: Any,
    now: float,
    default_busy_minutes: int = 60,
    timezone_offset_minutes: int = 480,
) -> dict | None:
    """Only consume a complete, explicit preference command.

    In particular, ``帮我想办法，我今天遇到……`` is normal message content.
    """
    if not isinstance(text, str) or len(text) > 160:
        return None
    command = text.strip().rstrip("。.!！～~").strip()
    fixed = {
        "先听我说": ({"mode": "listen"}, "好的，我先听你说，暂时少给建议。"),
        "我只是想吐槽": ({"mode": "listen"}, "好的，我先听你说，暂时少给建议。"),
        "帮我想办法": ({"mode": "solve"}, "好的，我会帮你分析问题和可行的办法。"),
        "切回自动": ({"mode": "auto"}, "已恢复自动选择回复方式。"),
        "恢复自动模式": ({"mode": "auto"}, "已恢复自动选择回复方式。"),
        "以后少用长列表": ({"less_lists": True}, "好的，以后会少用长列表。"),
        "少用长列表": ({"less_lists": True}, "好的，以后会少用长列表。"),
        "取消少用长列表": ({"less_lists": False}, "已取消少用长列表的偏好。"),
        "恢复使用列表": ({"less_lists": False}, "已取消少用长列表的偏好。"),
        "以后少追问": ({"less_questions": True}, "好的，以后会减少不必要的追问。"),
        "少追问": ({"less_questions": True}, "好的，以后会减少不必要的追问。"),
        "取消少追问": ({"less_questions": False}, "已取消少追问的偏好。"),
        "恢复追问": ({"less_questions": False}, "已取消少追问的偏好。"),
        "以后简短回复": ({"reply_length": "short"}, "好的，以后会优先简短回复。"),
        "以后正常回复": ({"reply_length": "normal"}, "已恢复正常回复长度。"),
        "以后详细回复": (
            {"reply_length": "detailed"},
            "好的，需要时会给出更详细的说明。",
        ),
        "恢复主动消息": (
            {"quiet_until": 0.0},
            "已恢复主动消息；其他插件需接入节奏规则才会生效。",
        ),
        "恢复主动聊天": (
            {"quiet_until": 0.0},
            "已恢复主动消息；其他插件需接入节奏规则才会生效。",
        ),
    }
    if command in fixed:
        patch, reply = fixed[command]
        return {"preferences": dict(patch), "clear": False, "reply": reply}
    if command in {"清除聊天偏好", "重置聊天偏好"}:
        return {
            "preferences": {},
            "clear": True,
            "reply": "已清除聊天偏好，恢复默认设置。",
        }
    if command in {"我先忙了", "我现在忙，稍后再聊"}:
        current_time = _number(now, "now", 0, float("inf"))
        minutes = _integer(default_busy_minutes, "default_busy_minutes", 1, 1440)
        until = current_time + minutes * 60
    elif command == "今天先别主动找我":
        current_time = _number(now, "now", 0, 253402214399)
        offset = _integer(timezone_offset_minutes, "timezone_offset_minutes", -720, 840)
        zone = timezone(timedelta(minutes=offset))
        local_time = datetime.fromtimestamp(current_time, zone)
        midnight = (local_time + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        until = midnight.timestamp()
    else:
        match = re.fullmatch(r"接下来([0-9]{1,4})分钟别主动找我", command)
        if match is None:
            return None
        minutes = int(match.group(1))
        if not 1 <= minutes <= 1440:
            return None
        current_time = _number(now, "now", 0, float("inf"))
        until = current_time + minutes * 60
    return {
        "preferences": validate_preferences({"quiet_until": until}),
        "clear": False,
        "reply": "好的，已暂停非必要的主动消息；其他插件需接入节奏规则才会生效。",
    }


def build_hint(preferences: Any, text: str = "") -> str:
    """A short temporary model hint; it intentionally does not echo user text."""
    supplied = validate_preferences(preferences)
    current = {
        "mode": "auto",
        "reply_length": "auto",
        "less_lists": True,
        "less_questions": True,
        "quiet_until": 0.0,
    }
    current.update(supplied)
    parts = ["本轮聊天偏好：优先遵循用户当前明确需求。"]
    parts.append(
        {
            "auto": "根据用户的文字和上下文选择倾听或分析，不凭手机传感器推断情绪。",
            "listen": "先倾听并回应用户表达，减少未经请求的建议；用户明确要解决办法时仍提供帮助。",
            "solve": "帮助梳理问题，给出具体可行的办法；必要时只问关键问题。",
        }[current["mode"]]
    )
    length = current["reply_length"]
    if length == "short":
        parts.append("优先简短回复；复杂问题、步骤或用户要求详细时可以完整回答。")
    elif length == "normal":
        parts.append("回复长度适中，完整说明必要信息。")
    elif length == "detailed":
        parts.append("需要时解释理由和步骤，避免重复和无关扩展。")
    else:
        parts.append("回复长度按问题需要决定，明确复杂问题应完整回答。")
    if current["less_lists"]:
        parts.append("优先自然段落，只在步骤或比较确有帮助时使用列表。")
    if current["less_questions"]:
        parts.append("减少结尾套话和不必要的追问，不强行延长对话。")
    if current["quiet_until"] > 0:
        parts.append("用户暂时暂停非必要的主动消息；正常回应当前消息。")
    return "".join(parts)
