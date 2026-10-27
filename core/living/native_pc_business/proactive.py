# -*- coding: utf-8 -*-
"""
ProactiveMixin — 主动消息调度 + 决策 + 生成发送（三文件合并层）

由 proactive.py（调度）、proactive_engine.py（决策）、proactive_message.py（生成发送）
合并而成；照片子域拆至 proactive_photo.py。方法名与方法体逐字保持不变，
另删除 7 个被 UserRestGateMixin 按 MRO 遮蔽的 _user_rest_* 过期副本。
"""
from __future__ import annotations

import asyncio
import base64
import gc
import hashlib
import html
import importlib
import json
import math
import os
import random
import re
import shutil
import sys
import time
import unicodedata
import uuid
import zoneinfo
from copy import deepcopy
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from xml.etree import ElementTree as ET

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
try:
    from astrbot.api.message_components import At, Image, Plain, Record, Reply
except ImportError:
    from astrbot.api.message_components import At, Image, Plain
    from astrbot.core.message.components import Record
    try:
        from astrbot.api.message_components import Reply
    except ImportError:
        try:
            from astrbot.core.message.components import Reply
        except ImportError:
            Reply = None
try:
    from astrbot.core.message import components as CoreMessageComponents
except ImportError:
    CoreMessageComponents = None
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core import file_token_service
from astrbot.core.astr_main_agent import MainAgentBuildConfig, build_main_agent
from astrbot.core.agent.message import AssistantMessageSegment, TextPart, UserMessageSegment
from astrbot.core.db.po import Conversation
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform import PlatformStatus
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.star.star_handler import EventType, star_handlers_registry
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

try:
    import chinese_calendar as calendar_cn
except Exception:
    calendar_cn = None

try:
    from lunarcalendar import Converter, Solar
except Exception:
    Converter = None
    Solar = None

from .constants import (
    DEFAULT_DAILY_PLAN_ITEMS,
    DEFAULT_HUMANIZED_STATE,
    PLUGIN_NAME,
    DATA_VERSION,
    PROACTIVE_ABILITY_REGISTRY,
    VOICE_FALLBACK_TEMPLATES,
    TIMER_TAG_PATTERN,
    SUPPORTED_TIMER_FORMATS,
    _ACTION_TEXT,
    _DATA_STORE_KEYS,
    _DEFAULT_GROUP_TEMPLATE,
    _DEFAULT_USER_TEMPLATE,
    _REASON_TEXT,
    _SIMULATION_FALLBACK_EVENTS,
)
from .dreaming import (
    build_dream_memory_fragments,
    dream_fragment_effective_weight,
    dream_theme_specs,
    extract_weighted_dream_fragments,
    fallback_diary_payload,
    fallback_dream_fragments_for_diary,
    generate_daily_diary,
    generate_enhanced_dream_pick,
    merge_dream_fragment_pool,
    normalize_dream_fragment_item,
    normalize_dream_fragment_pool,
    recent_diary_context,
    recent_diary_tags,
    weighted_unique_fragment_sample,
)
from .helpers import _date_key, _normalize_outbound_punctuation_flow, _normalize_photo_subject_owner, _now_ts, _photo_subject_owner_prompt_label, _redact_outbound_secrets, _safe_float, _safe_int, _single_line, _strip_internal_message_blocks, _today_key, normalize_legacy_tag_text
from .helpers import special_calendar, special_day_events
from .companion_frequency import build_frequency_profile, hard_limit_reason, sampling_bucket
from .planning import (
    build_daily_plan_prompt,
    build_detail_enhancement_prompt,
    format_plan_for_diary,
    generate_daily_plan,
    generate_detail_enhancement,
    get_schedule_planning_prompt,
    normalize_long_term_events,
    normalize_story_items,
    normalize_story_plan,
    pick_detail_segment,
)

# ===== 区块0 模块级常量（三文件重复字面量去重为一份；DEFAULT_AI_DAILY_NEWS_SOURCE 保留B站UID 285286947 版）=====
DEFAULT_AI_DAILY_NEWS_SOURCE = "B站 AI早报|bilibili:285286947"

DEFAULT_NEWS_SOURCES = "\n".join(
    [
        "BBC中文|https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        "Google新闻中文|https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "Solidot|https://www.solidot.org/index.rss",
        "Hacker News|https://hnrss.org/frontpage",
        "MIT Technology Review|https://www.technologyreview.com/feed/",
        "Ars Technica|https://feeds.arstechnica.com/arstechnica/index",
        DEFAULT_AI_DAILY_NEWS_SOURCE,
    ]
)

LEGACY_DEFAULT_NEWS_SOURCES = "\n".join(
    [
        "BBC中文|https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        "Google新闻中文|https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "Solidot|https://www.solidot.org/index.rss",
    ]
)

PREVIOUS_TECH_DEFAULT_NEWS_SOURCES = "\n".join(
    [
        "BBC中文|https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        "Google新闻中文|https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "Solidot|https://www.solidot.org/index.rss",
        "Hacker News|https://hnrss.org/frontpage",
        "MIT Technology Review|https://www.technologyreview.com/feed/",
        "Ars Technica|https://feeds.arstechnica.com/arstechnica/index",
    ]
)



_LUNAR_MONTH_NAMES = [
    "正月",
    "二月",
    "三月",
    "四月",
    "五月",
    "六月",
    "七月",
    "八月",
    "九月",
    "十月",
    "冬月",
    "腊月",
]
_LUNAR_DAY_NAMES = [
    "初一",
    "初二",
    "初三",
    "初四",
    "初五",
    "初六",
    "初七",
    "初八",
    "初九",
    "初十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
    "十六",
    "十七",
    "十八",
    "十九",
    "二十",
    "廿一",
    "廿二",
    "廿三",
    "廿四",
    "廿五",
    "廿六",
    "廿七",
    "廿八",
    "廿九",
    "三十",
]
_SOLAR_TERM_DATES = {
    (1, 5): "小寒",
    (1, 20): "大寒",
    (2, 4): "立春",
    (2, 19): "雨水",
    (3, 5): "惊蛰",
    (3, 20): "春分",
    (4, 4): "清明",
    (4, 20): "谷雨",
    (5, 5): "立夏",
    (5, 21): "小满",
    (6, 5): "芒种",
    (6, 21): "夏至",
    (7, 7): "小暑",
    (7, 22): "大暑",
    (8, 7): "立秋",
    (8, 23): "处暑",
    (9, 7): "白露",
    (9, 23): "秋分",
    (10, 8): "寒露",
    (10, 23): "霜降",
    (11, 7): "立冬",
    (11, 22): "小雪",
    (12, 7): "大雪",
    (12, 22): "冬至",
}
_ALMANAC_YI = ["整理房间", "写字", "散步", "读书", "听歌", "轻度创作", "复盘", "安静休息"]
_ALMANAC_JI = ["熬夜", "冲动发言", "硬撑", "反复纠结", "过度解释", "临时加压", "情绪化决定"]
_PLATFORM_DISPLAY_NAMES = {
    "aiocqhttp": "QQ",
    "qq": "QQ",
    "onebot": "QQ",
    "telegram": "Telegram",
    "wechat": "微信",
    "discord": "Discord",
}


# ===== 区块1 模块级辅助类（原 proactive_message.py）=====
class SyntheticPrivateWakeEvent(AstrMessageEvent):
    def __init__(
        self,
        *,
        context: Context,
        session: MessageSession,
        message: str,
        sender_name: str = "PrivateCompanion",
    ) -> None:
        platform_meta = PlatformMetadata(
            name=session.platform_id,
            description="SyntheticPrivateWake",
            id=session.platform_id,
        )

        msg_obj = AstrBotMessage()
        msg_obj.type = session.message_type
        msg_obj.self_id = session.session_id
        msg_obj.session_id = session.session_id
        msg_obj.message_id = f"private_companion_{uuid.uuid4().hex}"
        msg_obj.sender = MessageMember(user_id=session.session_id, nickname=sender_name)
        msg_obj.message = [Plain(message)]
        msg_obj.message_str = message
        msg_obj.raw_message = message
        msg_obj.timestamp = int(time.time())

        super().__init__(message, msg_obj, platform_meta, session.session_id)
        self.session = session
        self.context_obj = context
        self.is_at_or_wake_command = True
        self.is_wake = True

    async def send(self, message: MessageChain) -> None:
        if message is None:
            return
        if getattr(self, 'private_companion_require_image', False):
            # A global tool may use event.send instead of AstrBot's sending
            # tool. Capture its text at the same generation boundary so it
            # cannot bypass final review, image binding or the common quota.
            rows = []
            for component in list(getattr(message, 'chain', []) or []):
                if isinstance(component, Plain) and str(component.text or '').strip():
                    rows.append({'type':'plain', 'text':str(component.text)})
            captured = getattr(self, '_private_companion_captured_event_sends', None)
            if not isinstance(captured, list):
                captured = self._private_companion_captured_event_sends = []
            if rows:
                captured.append(_CapturedSendMessageCall(str(self.unified_msg_origin), rows))
                del captured[:-16]
            raise _CapturedFrameworkSendMessage('PrivateCompanion captured event.send payload.')
        await self.context_obj.send_message(self.session, message)
        await super().send(message)


class _CapturedSendMessageCall:
    def __init__(self, session: str, messages: list[dict[str, Any]]) -> None:
        self.session = str(session or "")
        self.messages = [dict(item) for item in messages if isinstance(item, dict)]


class _CapturedFrameworkSendMessage(Exception):
    """Stop the framework agent once its send_message_to_user payload is captured."""


class ProactiveMixin:
    """主动消息调度"""

    _PROACTIVE_DAILY_LIMIT_UNLIMITED = 999_999

    _PROACTIVE_INTENSITY_PRESETS: dict[str, dict[str, Any]] = {
        "off": {
            "label": "关闭预设",
            "description": "沿用手动配置，不覆盖任何主动频率参数。",
            "effects": {},
        },
        "balanced": {
            "label": "标准偏主动",
            "description": "轻度提高主动触达，适合想比手动默认更有存在感但仍保持低打扰的场景。",
            "effects": {
                "max_daily_messages": 9,
                "idle_minutes": 40,
                "min_interval_minutes": 75,
                "unanswered_slowdown_start": 2,
                "unanswered_max_interval_multiplier": 1.65,
                "friend_unanswered_max_cooldown_hours": 30,
                "delay_factor": 0.72,
                "proactive_persona_judge_send_threshold": 54,
                "proactive_review_strength": "lenient",
                "group_wakeup_cooldown_seconds": 50,
                "group_high_intensity_cooldown_seconds": 105,
                "group_wakeup_interest_probability": 0.24,
                "group_wakeup_question_threshold": 60,
                "group_wakeup_cold_group_threshold": 62,
                "group_wakeup_topic_interest_max_boost": 0.55,
                "group_interject_min_interval_minutes": 90,
                "group_interject_max_daily": 4,
            },
        },
        "high_private": {
            "label": "私聊高频",
            "description": "显著提高主要用户私聊主动频率，适合希望 Bot 更常来找的用户。",
            "effects": {
                "max_daily_messages": 15,
                "idle_minutes": 14,
                "min_interval_minutes": 24,
                "unanswered_slowdown_start": 4,
                "unanswered_max_interval_multiplier": 1.25,
                "friend_unanswered_max_cooldown_hours": 14,
                "delay_factor": 0.42,
                "proactive_persona_judge_send_threshold": 45,
                "proactive_review_strength": "lenient",
                "group_wakeup_cooldown_seconds": 45,
                "group_high_intensity_cooldown_seconds": 90,
                "group_wakeup_interest_probability": 0.22,
                "group_wakeup_question_threshold": 60,
                "group_wakeup_cold_group_threshold": 62,
                "group_wakeup_topic_interest_max_boost": 0.5,
                "group_interject_min_interval_minutes": 90,
                "group_interject_max_daily": 4,
            },
        },
        "high_group": {
            "label": "群聊活跃",
            "description": "明显提高群聊唤醒、兴趣词接话和群主动插话，私聊只轻度增强。",
            "effects": {
                "max_daily_messages": 8,
                "idle_minutes": 50,
                "min_interval_minutes": 95,
                "unanswered_slowdown_start": 2,
                "unanswered_max_interval_multiplier": 1.8,
                "friend_unanswered_max_cooldown_hours": 36,
                "delay_factor": 0.75,
                "proactive_persona_judge_send_threshold": 56,
                "proactive_review_strength": "lenient",
                "group_wakeup_cooldown_seconds": 20,
                "group_high_intensity_cooldown_seconds": 45,
                "group_wakeup_interest_probability": 0.45,
                "group_wakeup_question_threshold": 52,
                "group_wakeup_cold_group_threshold": 54,
                "group_wakeup_topic_interest_max_boost": 0.95,
                "group_interject_min_interval_minutes": 24,
                "group_interject_max_daily": 12,
            },
        },
        "live": {
            "label": "在线陪伴",
            "description": "最高在线陪伴档，不限制每日主动次数，也不再替用户节省主动成本；仍会尊重免打扰、休息、拒绝、隐私和硬限额。",
            "effects": {
                "max_daily_messages": _PROACTIVE_DAILY_LIMIT_UNLIMITED,
                "ignore_daily_limit": True,
                "idle_minutes": 0,
                "min_interval_minutes": 5,
                "unanswered_slowdown_start": 8,
                "unanswered_max_interval_multiplier": 1.0,
                "friend_unanswered_max_cooldown_hours": 8,
                "delay_factor": 0.08,
                "ignore_token_soft_limit": True,
                "ignore_soft_daily_target": True,
                "proactive_persona_judge_send_threshold": 32,
                "proactive_review_strength": "lenient",
                "group_wakeup_cooldown_seconds": 3,
                "group_high_intensity_cooldown_seconds": 30,
                "group_wakeup_interest_probability": 0.78,
                "group_wakeup_question_threshold": 40,
                "group_wakeup_cold_group_threshold": 42,
                "group_wakeup_topic_interest_max_boost": 1.5,
                "group_interject_min_interval_minutes": 6,
                "group_interject_max_daily": _PROACTIVE_DAILY_LIMIT_UNLIMITED,
                "ignore_group_interject_daily_limit": True,
            },
        },
    }

    # ===== 区块2 调度层（原 proactive.py 347-2282）=====
    def _normalize_proactive_intensity_preset(self, value: Any) -> str:
        preset = str(value or "off").strip().lower()
        aliases = {
            "": "off",
            "manual": "off",
            "none": "off",
            "default": "off",
            "standard": "balanced",
            "active": "high_private",
            "private": "high_private",
            "group": "high_group",
            "online": "live",
            "直播": "live",
            "高频": "live",
        }
        preset = aliases.get(preset, preset)
        return preset if preset in self._PROACTIVE_INTENSITY_PRESETS else "off"

    def _proactive_intensity_runtime(self) -> dict[str, Any]:
        preset = self._normalize_proactive_intensity_preset(
            getattr(self, "proactive_intensity_preset", "off")
        )
        spec = self._PROACTIVE_INTENSITY_PRESETS.get(preset) or self._PROACTIVE_INTENSITY_PRESETS["off"]
        effects = dict(spec.get("effects") or {})
        return {
            "preset": preset,
            "enabled": preset != "off",
            "label": str(spec.get("label") or preset),
            "description": str(spec.get("description") or ""),
            "effects": effects,
        }

    def _proactive_intensity_effect(self, key: str, default: Any = None) -> Any:
        runtime = self._proactive_intensity_runtime()
        if not runtime.get("enabled"):
            return default
        return runtime.get("effects", {}).get(key, default)

    @classmethod
    def _proactive_daily_limit_is_unlimited(cls, value: Any) -> bool:
        return _safe_int(value, 0, 0) >= cls._PROACTIVE_DAILY_LIMIT_UNLIMITED

    @classmethod
    def _format_proactive_daily_limit(cls, value: Any) -> str:
        return "不限" if cls._proactive_daily_limit_is_unlimited(value) else str(_safe_int(value, 0, 0))

    def _proactive_intensity_ignores_daily_limit(self) -> bool:
        if self._companion_frequency_enabled():
            return False
        return bool(self._proactive_intensity_effect("ignore_daily_limit", False))

    def _effective_proactive_int(self, key: str, configured: int, *, minimum: int = 0, maximum: int | None = None) -> int:
        value = configured
        effect = self._proactive_intensity_effect(key, None)
        if effect is not None:
            value = _safe_int(effect, configured, minimum, maximum if maximum is not None else 10**9)
        value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def _effective_proactive_float(self, key: str, configured: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
        value = configured
        effect = self._proactive_intensity_effect(key, None)
        if effect is not None:
            value = _safe_float(effect, configured, minimum)
        value = max(minimum, float(value))
        if maximum is not None:
            value = min(maximum, value)
        return value

    def _effective_group_wakeup_cooldown_seconds(self) -> int:
        return self._effective_proactive_int(
            "group_wakeup_cooldown_seconds",
            _safe_int(getattr(self, "group_wakeup_cooldown_seconds", 90), 90, 0, 3600),
            minimum=0,
            maximum=3600,
        )

    def _effective_group_high_intensity_cooldown_seconds(self) -> int:
        return self._effective_proactive_int(
            "group_high_intensity_cooldown_seconds",
            _safe_int(getattr(self, "group_high_intensity_cooldown_seconds", 150), 150, 30, 1800),
            minimum=30,
            maximum=1800,
        )

    def _effective_group_interject_min_interval_minutes(self) -> int:
        base_interval = self._effective_proactive_int(
            "group_interject_min_interval_minutes",
            _safe_int(getattr(self, "group_interject_min_interval_minutes", 180), 180, 10, 1440),
            minimum=1,
            maximum=1440,
        )
        profile = self._cycle_proactive_frequency_profile()
        return max(1, min(1440, int(round(base_interval * profile["group_interval_multiplier"]))))

    def _cycle_proactive_frequency_profile(self) -> dict[str, Any]:
        neutral = {
            "phase": "neutral",
            "private_interval_multiplier": 1.0,
            "group_interval_multiplier": 1.0,
            "group_probability_multiplier": 1.0,
        }
        if not bool(getattr(self, "enable_cycle_state", True)):
            return neutral
        data = getattr(self, "data", {})
        state = data.get("daily_state") if isinstance(data, dict) else {}
        if not isinstance(state, dict) or str(state.get("date") or "") not in {"", _today_key()}:
            return neutral
        cycle_text = _single_line(state.get("body_cycle"), 100)
        if not cycle_text or cycle_text in {"无明显周期影响", "不处于生理期", "生理期模拟未开启"}:
            return neutral
        if "后" in cycle_text or "恢复" in cycle_text:
            return {
                "phase": "recovery",
                "private_interval_multiplier": 1.05,
                "group_interval_multiplier": 1.08,
                "group_probability_multiplier": 0.92,
            }
        if "前" in cycle_text:
            return {
                "phase": "pre",
                "private_interval_multiplier": 1.08,
                "group_interval_multiplier": 1.12,
                "group_probability_multiplier": 0.88,
            }
        if "生理期" in cycle_text:
            return {
                "phase": "period",
                "private_interval_multiplier": 1.18,
                "group_interval_multiplier": 1.25,
                "group_probability_multiplier": 0.76,
            }
        return neutral

    def _cycle_group_interject_probability(self, probability: float) -> float:
        profile = self._cycle_proactive_frequency_profile()
        return max(0.0, min(1.0, float(probability) * profile["group_probability_multiplier"]))

    def _effective_group_interject_max_daily(self) -> int:
        if bool(self._proactive_intensity_effect("ignore_group_interject_daily_limit", False)):
            return self._PROACTIVE_DAILY_LIMIT_UNLIMITED
        return self._effective_proactive_int(
            "group_interject_max_daily",
            _safe_int(getattr(self, "group_interject_max_daily", 2), 2, 0, 12),
            minimum=0,
            maximum=48,
        )

    def _effective_group_wakeup_interest_probability(self) -> float:
        return self._effective_proactive_float(
            "group_wakeup_interest_probability",
            max(0.0, min(1.0, _safe_float(getattr(self, "group_wakeup_interest_probability", 0.18), 0.18, 0.0))),
            minimum=0.0,
            maximum=1.0,
        )

    def _effective_group_wakeup_question_threshold(self) -> int:
        return self._effective_proactive_int(
            "group_wakeup_question_threshold",
            _safe_int(getattr(self, "group_wakeup_question_threshold", 65), 65, 0, 100),
            minimum=0,
            maximum=100,
        )

    def _effective_group_wakeup_cold_group_threshold(self) -> int:
        return self._effective_proactive_int(
            "group_wakeup_cold_group_threshold",
            _safe_int(getattr(self, "group_wakeup_cold_group_threshold", 65), 65, 0, 100),
            minimum=0,
            maximum=100,
        )

    def _effective_group_wakeup_topic_interest_max_boost(self) -> float:
        return self._effective_proactive_float(
            "group_wakeup_topic_interest_max_boost",
            max(0.0, min(1.5, _safe_float(getattr(self, "group_wakeup_topic_interest_max_boost", 0.45), 0.45, 0.0))),
            minimum=0.0,
            maximum=1.5,
        )

    def _effective_proactive_persona_judge_send_threshold(self) -> int:
        return self._effective_proactive_int(
            "proactive_persona_judge_send_threshold",
            _safe_int(getattr(self, "proactive_persona_judge_send_threshold", 62), 62, 0, 100),
            minimum=0,
            maximum=100,
        )

    def _effective_proactive_review_strength(self) -> str:
        value = str(self._proactive_intensity_effect("proactive_review_strength", "") or "").strip().lower()
        if value in {"lenient", "balanced", "strict"}:
            return value
        configured = str(getattr(self, "proactive_review_strength", "lenient") or "lenient").strip().lower()
        return configured if configured in {"lenient", "balanced", "strict"} else "lenient"

    def _proactive_intensity_ignores_token_soft_limit(self, task: str | None = None) -> bool:
        return bool(self._proactive_intensity_effect("ignore_token_soft_limit", False))

    def _configured_target_ids(self) -> list[str]:
        raw = self.target_user_ids
        if isinstance(raw, str):
            parts = re.split(r"[,\s,、;；]+", raw)
        elif isinstance(raw, list):
            parts = raw
        else:
            parts = []
        ids = []
        normalizer = getattr(self, "_normalize_private_identity_id", None)
        for part in parts:
            user_id = normalizer(part) if callable(normalizer) else _single_line(part, 128)
            if user_id and not self._is_bot_self_user_id(user_id) and user_id not in ids:
                ids.append(user_id)
        return ids

    def _user_enabled_for_proactive(self, user_id: str, user: dict[str, Any] | None = None) -> bool:
        if not isinstance(user, dict):
            return False
        if user.get("enabled") is False or user.get("manual_disabled"):
            return False
        return self._is_target_private_user(user_id, user)

    def _default_private_umo_for_user_id(self, user_id: str) -> str:
        normalizer = getattr(self, "_normalize_private_identity_id", None)
        user_id = normalizer(user_id) if callable(normalizer) else _single_line(user_id, 128)
        if not user_id or self._is_bot_self_user_id(user_id):
            return ""
        platform = _single_line(getattr(self, "target_platform", ""), 40) or "aiocqhttp"
        return f"{platform}:FriendMessage:{user_id}"

    def _private_delivery_user_id_for(self, user_id: str) -> str:
        canonical = self._canonical_private_user_id(str(user_id or "").strip())
        aliases = getattr(self, "private_user_delivery_aliases", {}) or {}
        normalizer = getattr(self, "_normalize_private_identity_id", None)
        target = normalizer(aliases.get(canonical)) if callable(normalizer) else _single_line(aliases.get(canonical), 128)
        if target and not self._is_bot_self_user_id(target):
            return target
        return canonical

    def _private_delivery_umo_for_user_id(self, user_id: str) -> str:
        return self._default_private_umo_for_user_id(self._private_delivery_user_id_for(user_id))

    def _private_umo_matches_user_id(self, umo: str, user_id: str) -> bool:
        clean_umo = _single_line(umo, 180)
        clean_user_id = str(user_id or "").strip()
        if not clean_umo or not clean_user_id:
            return False
        if f":FriendMessage:{clean_user_id}" not in clean_umo:
            return False
        parser = getattr(self, "_parse_message_session", None)
        if callable(parser):
            try:
                return parser(clean_umo) is not None
            except Exception:
                return False
        return True

    def _note_private_user_umo(self, user_id: str, user: dict[str, Any] | None, umo: str) -> None:
        if not isinstance(user, dict):
            return
        clean_umo = _single_line(umo, 180)
        if not clean_umo:
            return
        user_id = self._canonical_private_user_id(str(user_id or user.get("user_id") or "").strip())
        user["last_inbound_umo"] = clean_umo
        delivery_id = self._private_delivery_user_id_for(user_id)
        if delivery_id and delivery_id != user_id:
            delivery_umo = self._private_delivery_umo_for_user_id(user_id)
            user["umo"] = delivery_umo
            return
        if self._private_umo_matches_user_id(clean_umo, user_id):
            user["umo"] = clean_umo

    def _ensure_private_user_umo(self, user_id: str, user: dict[str, Any] | None) -> bool:
        if not isinstance(user, dict):
            return False
        user_id = str(user_id or user.get("user_id") or "").strip()
        fallback = self._private_delivery_umo_for_user_id(user_id)
        if not fallback:
            return False
        current = _single_line(user.get("umo"), 180)
        delivery_id = self._private_delivery_user_id_for(user_id)
        canonical_id = self._canonical_private_user_id(user_id)
        if delivery_id and delivery_id != canonical_id:
            expected_suffix = f":FriendMessage:{delivery_id}"
            if not current.endswith(expected_suffix):
                user["umo"] = fallback
                return True
        else:
            last_inbound_umo = _single_line(user.get("last_inbound_umo"), 180)
            if (
                last_inbound_umo
                and last_inbound_umo != current
                and self._private_umo_matches_user_id(last_inbound_umo, canonical_id)
            ):
                user["umo"] = last_inbound_umo
                return True
        if not current:
            user["umo"] = fallback
            return True
        parser = getattr(self, "_parse_message_session", None)
        if callable(parser):
            try:
                if parser(current) is None:
                    user["umo"] = fallback
                    return True
            except Exception:
                user["umo"] = fallback
                return True
        return False

    def _private_user_role(self, user: dict[str, Any] | None, user_id: str = "") -> str:
        if not isinstance(user, dict):
            return "friend"
        role_getter = getattr(self, "_ensure_private_user_role", None)
        if callable(role_getter):
            try:
                return role_getter(str(user_id or user.get("user_id") or ""), user)
            except Exception:
                pass
        normalizer = getattr(self, "_normalize_private_user_role", None)
        role = normalizer(user.get("relationship_role")) if callable(normalizer) else str(user.get("relationship_role") or "")
        return role if role in {"owner", "friend"} else "friend"

    def _user_profile_override_int(self, user: dict[str, Any], key: str) -> int | None:
        if not isinstance(user, dict):
            return None
        raw = user.get(key)
        if raw in (None, ""):
            return None
        value = _safe_int(raw, -1, -1)
        return value if value >= 0 else None

    def _effective_user_daily_limit(self, user: dict[str, Any]) -> int:
        override = self._user_profile_override_int(user, "proactive_daily_limit")
        max_daily_messages = self._runtime_max_daily_messages()
        if max_daily_messages <= 0 or override == 0:
            return 0
        if self._companion_frequency_enabled():
            limit = min(max_daily_messages, self._companion_max_daily_messages())
            if override is not None:
                limit = min(limit, override)
            elif self._private_user_role(user) == "friend":
                limit = min(limit, 2)
            return max(0, limit)
        if self._proactive_intensity_ignores_daily_limit():
            return self._PROACTIVE_DAILY_LIMIT_UNLIMITED
        if override is not None:
            return override
        if self._private_user_role(user) == "friend":
            return min(max_daily_messages, 2) if max_daily_messages > 0 else 0
        return max(0, max_daily_messages)

    def _runtime_max_daily_messages(self) -> int:
        runtime_value = _safe_int(getattr(self, "max_daily_messages", 8), 8, 0, 12)
        config = getattr(self, "config", None)
        getter = getattr(config, "get", None)
        if callable(getter):
            try:
                configured_value = _safe_int(getter("max_daily_messages", runtime_value), runtime_value, 0, 12)
                if configured_value != runtime_value:
                    self.max_daily_messages = configured_value
                    runtime_value = configured_value
            except Exception:
                pass
        if runtime_value <= 0:
            return 0
        if self._companion_frequency_enabled():
            return min(runtime_value, self._companion_max_daily_messages())
        effective_value = self._effective_proactive_int("max_daily_messages", runtime_value, minimum=0, maximum=60)
        if effective_value <= 0:
            return 0
        if self._proactive_intensity_ignores_daily_limit():
            return self._PROACTIVE_DAILY_LIMIT_UNLIMITED
        return effective_value

    def _proactive_generation_disabled(self, user: dict[str, Any] | None = None) -> bool:
        if self._runtime_max_daily_messages() <= 0:
            return True
        if isinstance(user, dict) and self._user_profile_override_int(user, "proactive_daily_limit") == 0:
            return True
        return False

    def _suspend_user_proactive_generation(self, user: dict[str, Any]) -> bool:
        if not isinstance(user, dict):
            return False
        tracked = (
            "next_proactive_at",
            "planned_proactive_reason",
            "planned_proactive_action",
            "planned_proactive_source",
            "planned_proactive_motive",
            "planned_proactive_topic",
            "planned_candidate_id",
            "proactive_impulses",
            "pending_followup_event",
            "suspended_proactive",
            "pending_proactive_send_retry",
            "proactive_sending",
        )
        before = {key: deepcopy(user.get(key)) for key in tracked}
        self._clear_pending_proactive_plan(user)
        user["proactive_impulses"] = []
        user["pending_followup_event"] = {}
        user["suspended_proactive"] = {}
        user["pending_proactive_send_retry"] = {}
        user["proactive_sending"] = False
        user["proactive_sending_started_at"] = 0
        return any(before.get(key) != user.get(key) for key in tracked)

    def _format_daily_limit_disabled_reason(self, user: dict[str, Any]) -> str:
        override = user.get("proactive_daily_limit", -1) if isinstance(user, dict) else -1
        runtime_value = _safe_int(getattr(self, "max_daily_messages", 0), 0, 0, 12)
        config_value = runtime_value
        config = getattr(self, "config", None)
        getter = getattr(config, "get", None)
        if callable(getter):
            try:
                config_value = _safe_int(getter("max_daily_messages", runtime_value), runtime_value, 0, 12)
            except Exception:
                config_value = runtime_value
        return f"每日上限为 0（用户覆盖={override}，运行中全局={runtime_value}，配置全局={config_value}）"

    def _effective_user_idle_minutes(self, user: dict[str, Any]) -> int:
        override = self._user_profile_override_int(user, "proactive_idle_minutes")
        if self._companion_frequency_enabled():
            configured = _safe_int(getattr(self, "idle_minutes", 20), 20, 0, 1440)
            idle = max(self._companion_recent_chat_minutes(), override if override is not None else configured)
            return max(idle, 180) if self._private_user_role(user) == "friend" else idle
        if override is not None:
            return override
        base_idle = self._effective_proactive_int(
            "idle_minutes",
            _safe_int(getattr(self, "idle_minutes", 60), 60, 0, 1440),
            minimum=0,
            maximum=1440,
        )
        if self._private_user_role(user) == "friend":
            return max(base_idle, 180)
        return max(0, base_idle)

    def _effective_user_greeting_idle_minutes(self, user: dict[str, Any]) -> int:
        if self._private_user_role(user) == "friend":
            return max(self.greeting_idle_minutes, 120)
        return max(0, self.greeting_idle_minutes)

    def _effective_user_min_interval_minutes(self, user: dict[str, Any]) -> int:
        override = self._user_profile_override_int(user, "proactive_min_interval_minutes")
        if self._companion_frequency_enabled():
            configured = _safe_int(getattr(self, "min_interval_minutes", 45), 45, 0, 2880)
            interval = max(self._companion_min_interval_minutes(), override if override is not None else configured)
            return max(interval, 360) if self._private_user_role(user) == "friend" else interval
        if override is not None:
            return override
        base_interval = self._effective_proactive_int(
            "min_interval_minutes",
            _safe_int(getattr(self, "min_interval_minutes", 120), 120, 0, 2880),
            minimum=0,
            maximum=2880,
        )
        if self._private_user_role(user) == "friend":
            return max(base_interval, 360)
        return max(0, base_interval)

    def _companion_frequency_enabled(self) -> bool:
        value = getattr(self, "companion_frequency_enabled", True)
        return str(value).strip().lower() not in {"false", "0", "off", "no", "none"}

    def _companion_min_interval_minutes(self) -> int:
        return _safe_int(getattr(self, "companion_min_interval_minutes", 45), 45, 10, 2880)

    def _companion_max_daily_messages(self) -> int:
        return _safe_int(getattr(self, "companion_max_daily_messages", 8), 8, 0, 60)

    def _companion_recent_chat_minutes(self) -> int:
        return _safe_int(getattr(self, "companion_recent_chat_minutes", 20), 20, 5, 1440)

    def _companion_frequency_profile(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        check_now = _now_ts() if now is None else now
        current = self._environment_fromtimestamp(check_now)
        today = current.strftime("%Y-%m-%d")
        legacy_count = _safe_int(user.get("sent_today"), 0, 0) if str(user.get("sent_day") or today) == today else 0
        delivery_count = _safe_int(user.get("companion_sent_today"), 0, 0) if str(user.get("companion_sent_day") or today) == today else 0
        sent_today = max(legacy_count, delivery_count)
        last_activity = max(self._latest_private_user_activity_ts(user), _safe_float(user.get("last_user_message_at"), 0))
        return build_frequency_profile(
            now=check_now, last_activity_at=last_activity,
            last_sent=max(_safe_float(user.get("last_sent"), 0),
                          _safe_float(user.get("last_proactive_sent_at"), 0),
                          _safe_float(user.get("companion_last_sent_at"), 0),
                          _safe_float(user.get("proactive_chat_bridge_last_sent_at"), 0)),
            sent_today=sent_today, daily_limit=self._effective_user_daily_limit(user),
            min_interval_minutes=self._effective_min_interval_seconds(user) / 60,
            recent_chat_minutes=self._effective_user_idle_minutes(user),
            sampling_minutes=_safe_int(getattr(self, "companion_sampling_minutes", 10), 10, 1, 60),
            ignored_streak=_safe_int(user.get("ignored_streak"), 0, 0),
            is_friend=self._private_user_role(user) == "friend",
            night_mode=str(getattr(self, "companion_night_mode", "quiet_companion") or "quiet_companion"),
            local_hour=current.hour,
        )

    def _companion_frequency_block_reason(
        self, user: dict[str, Any], *, now: float | None = None, include_sending: bool = False,
    ) -> str:
        if not self._companion_frequency_enabled():
            return ""
        if not isinstance(user, dict):
            return "缺少陪伴用户状态"
        user_id = str(user.get("user_id") or user.get("id") or "")
        if not self._user_enabled_for_proactive(user_id, user):
            return "私聊对象未启用"
        if include_sending and user.get("proactive_sending"):
            return "上一条主动消息仍在发送中"
        check_now = _now_ts() if now is None else now
        current = self._environment_fromtimestamp(check_now)
        today = current.strftime("%Y-%m-%d")
        legacy_count = _safe_int(user.get("sent_today"), 0, 0) if str(user.get("sent_day") or today) == today else 0
        delivery_count = _safe_int(user.get("companion_sent_today"), 0, 0) if str(user.get("companion_sent_day") or today) == today else 0
        count = max(legacy_count, delivery_count)
        last_sent = max(_safe_float(user.get("last_sent"), 0),
                        _safe_float(user.get("last_proactive_sent_at"), 0),
                        _safe_float(user.get("companion_last_sent_at"), 0),
                        _safe_float(user.get("proactive_chat_bridge_last_sent_at"), 0))
        return hard_limit_reason(
            now=check_now, last_sent=last_sent, sent_today=count,
            daily_limit=self._effective_user_daily_limit(user),
            min_interval_minutes=self._effective_min_interval_seconds(user) / 60,
            recent_activity_at=max(self._latest_private_user_activity_ts(user), _safe_float(user.get("last_user_message_at"), 0)),
            recent_chat_minutes=self._effective_user_idle_minutes(user),
        )

    def _effective_user_photo_daily_limit(self, user: dict[str, Any] | None = None) -> int:
        if isinstance(user, dict):
            if self._private_user_role(user) == "friend":
                return 0
            override = self._user_profile_override_int(user, "photo_daily_limit")
            if override is not None:
                return override
        return max(0, self.photo_action_max_daily)

    def _effective_user_screen_peek_daily_limit(self, user: dict[str, Any] | None = None) -> int:
        if isinstance(user, dict):
            if self._private_user_role(user) == "friend":
                return 0
            override = self._user_profile_override_int(user, "screen_peek_daily_limit")
            if override is not None:
                return override
        return max(0, self.screen_peek_max_daily)

    def _effective_user_poke_daily_limit(self, user: dict[str, Any] | None = None) -> int:
        if isinstance(user, dict):
            override = self._user_profile_override_int(user, "poke_daily_limit")
            if override is not None:
                return override
            if self._private_user_role(user) == "friend":
                return 0
        return max(0, self.poke_action_max_times)

    def _format_private_user_boundary_hint(self, user: dict[str, Any]) -> str:
        role = self._private_user_role(user)
        labeler = getattr(self, "_private_user_role_label", None)
        label = labeler(role) if callable(labeler) else ("主要用户" if role == "owner" else "次要用户")
        note = _single_line(user.get("proactive_boundary_note"), 180)
        if role == "owner":
            text = (
                "【当前私聊关系角色】\n"
                f"- 当前用户角色：{label}。\n"
                "- 可以延续人格中对主要用户的亲近、依赖和日常陪伴动机，但仍要尊重用户休息、忙碌和拒绝信号。"
            )
        else:
            text = (
                "【当前私聊关系角色】\n"
                f"- 当前用户角色：{label}。\n"
                "- 对方不是主要用户/恋人/专属陪伴目标。主动联系应像普通朋友：少量、具体、不过度亲密，不使用主要用户专属称呼、占有欲、撒娇索取或暧昧承诺。\n"
                "- 动机应以礼貌关心、共同话题、必要转告、轻分享为主；不要因为想贴近、想被哄、想确认对方在不在而频繁打扰。\n"
                "- 不给次要用户使用窥屏或主动生图能力；不要把主要用户或其他私聊对象的图片、生活碎片复用给次要用户。"
                "- 不对次要用户发起本子/夹层阅读推荐、私密阅读分享、屏幕观察、群聊私下转述、私下创作分享或其他涉及隐私来源的主动。"
            )
        if note:
            text += f"\n- 用户级边界备注：{note}"
        return text

    def _friend_sensitive_proactive_reason(self, reason: Any) -> bool:
        normalized = str(reason or "").strip()
        return normalized in {
            "group_share",
            "jm_cosmos_share",
            "jm_cosmos_recommendation_request",
            "creative_share",
        }

    def _friend_sensitive_proactive_action(self, action: Any) -> bool:
        parts = {part.strip() for part in str(action or "").split("+") if part.strip()}
        return bool(parts & {"screen_peek", "photo_text", "jm_cosmos_read"})

    def _friend_can_receive_proactive_reason(self, user: dict[str, Any] | None, reason: Any, action: Any = "") -> bool:
        if not isinstance(user, dict) or self._private_user_role(user) != "friend":
            return True
        return not (self._friend_sensitive_proactive_reason(reason) or self._friend_sensitive_proactive_action(action))

    def _sanitize_friend_proactive_plan_fields(
        self,
        user: dict[str, Any] | None,
        *,
        reason: str = "",
        action: str = "message",
        topic: str = "",
        motive: str = "",
    ) -> dict[str, str]:
        normalized_action = str(action or "message").strip() or "message"
        normalized_topic = _single_line(topic, 80)
        normalized_motive = self._normalize_internal_motive_text(_single_line(motive, 180))
        if not isinstance(user, dict) or self._private_user_role(user) != "friend":
            return {
                "reason": str(reason or "check_in"),
                "action": normalized_action,
                "topic": normalized_topic,
                "motive": normalized_motive,
            }
        normalized_reason = str(reason or "check_in")
        unanswered_level = self._friend_unanswered_downgrade_level(user)
        if unanswered_level >= 1 and self._friend_unanswered_should_remove_action(normalized_action):
            normalized_action = "message"
        if self._friend_sensitive_proactive_action(normalized_action):
            normalized_action = "message"
        sensitive_markers = (
            "screen_peek", "窥屏", "屏幕", "识屏", "偷看", "偷偷看", "瞄一眼", "看一眼",
            "观察你", "看你在忙", "看看你在干嘛", "看你在干嘛",
        )
        combined = f"{normalized_topic} {normalized_motive}"
        has_sensitive_action_text = any(token in combined for token in sensitive_markers)
        has_friend_interaction_text = self._friend_plan_has_private_interaction_text(combined)
        unanswered_patch = self._friend_unanswered_plan_patch(
            user,
            level=unanswered_level,
            reason=normalized_reason,
            action=normalized_action,
            topic=normalized_topic,
            motive=normalized_motive,
        )
        if unanswered_patch:
            normalized_reason = unanswered_patch["reason"]
            normalized_action = unanswered_patch["action"]
            normalized_topic = unanswered_patch["topic"]
            normalized_motive = unanswered_patch["motive"]
            combined = f"{normalized_topic} {normalized_motive}"
            has_sensitive_action_text = any(token in combined for token in sensitive_markers)
            has_friend_interaction_text = self._friend_plan_has_private_interaction_text(combined)
        if not has_sensitive_action_text and not has_friend_interaction_text:
            return {
                "reason": normalized_reason,
                "action": normalized_action,
                "topic": normalized_topic,
                "motive": normalized_motive,
            }
        if has_friend_interaction_text:
            if not normalized_topic or self._friend_plan_has_private_interaction_text(normalized_topic):
                normalized_topic = "顺手分享一点日常近况"
            normalized_motive = (
                "作为普通朋友轻轻分享一个不指向第三方私聊互动的小片段,不要求立刻回复"
                if str(reason or "") in {"", "check_in", "quiet_care", "state_share", "activity_share"}
                else "按次要用户关系做一次克制的普通文字分享,不写成和次要用户聊天或约见"
            )
            return {
                "reason": normalized_reason,
                "action": normalized_action,
                "topic": normalized_topic,
                "motive": normalized_motive,
            }
        topic_replacements = {
            "空档偷看一眼": "空档问一句",
            "偷看一眼": "问一句近况",
            "你这会儿在干嘛": "问一句近况",
        }
        for old, new in topic_replacements.items():
            normalized_topic = normalized_topic.replace(old, new)
        if not normalized_topic or any(token in normalized_topic for token in sensitive_markers):
            normalized_topic = "问一句近况"
        normalized_motive = (
            "作为次要用户关系想起对方可能正忙,只轻轻问一句,不要求立刻回复"
            if normalized_reason in {"", "check_in", "quiet_care", "state_share"}
            else "按次要用户关系顺手补一句,只做普通文字关心,不涉及屏幕观察"
        )
        return {
            "reason": normalized_reason,
            "action": normalized_action,
            "topic": normalized_topic,
            "motive": normalized_motive,
        }

    def _friend_unanswered_downgrade_level(self, user: dict[str, Any] | None, *, now: float | None = None) -> int:
        if not isinstance(user, dict) or self._private_user_role(user) != "friend":
            return 0
        level = 0
        ignored = _safe_int(user.get("ignored_streak"), 0, 0, 20)
        if ignored >= 3:
            level = 3
        elif ignored >= 2:
            level = 2
        elif ignored >= 1:
            level = 1
        check_now = _now_ts() if now is None else now
        awaiting_since = _safe_float(user.get("awaiting_reply_since"), 0)
        if awaiting_since > 0:
            hours = max(0.0, (check_now - awaiting_since) / 3600.0)
            if hours >= 24:
                level = max(level, 3)
            elif hours >= 10:
                level = max(level, 2)
            elif hours >= 4:
                level = max(level, 1)
        return level

    def _friend_unanswered_silence_reason(self, user: dict[str, Any] | None, *, now: float | None = None) -> str:
        if not isinstance(user, dict) or self._private_user_role(user) != "friend":
            return ""
        ignored = _safe_int(user.get("ignored_streak"), 0, 0, 50)
        if ignored <= 0:
            user["friend_unanswered_silenced_since"] = 0
            user["friend_unanswered_silence_note"] = ""
            return ""
        check_now = _now_ts() if now is None else now
        awaiting_since = _safe_float(user.get("awaiting_reply_since"), 0)
        unanswered_hours = (check_now - awaiting_since) / 3600.0 if awaiting_since > 0 else 0.0
        if ignored >= 4:
            reason = f"次要用户连续 {ignored} 次未回应，普通主动已暂停，等待用户先恢复对话"
        elif ignored >= 3 and unanswered_hours >= 24:
            reason = f"次要用户连续 {ignored} 次未回应且已超过 24 小时，普通主动已暂停"
        elif ignored >= 2 and unanswered_hours >= 48:
            reason = f"次要用户连续未回应已超过 48 小时，普通主动已暂停"
        else:
            reason = ""
        if reason:
            if _safe_float(user.get("friend_unanswered_silenced_since"), 0) <= 0:
                user["friend_unanswered_silenced_since"] = check_now
            user["friend_unanswered_silence_note"] = reason
        else:
            user["friend_unanswered_silenced_since"] = 0
            user["friend_unanswered_silence_note"] = ""
        return reason

    def _block_friend_unanswered_pending_proactive(
        self,
        user: dict[str, Any],
        *,
        note: str,
        now: float | None = None,
    ) -> None:
        if not isinstance(user, dict) or not note:
            return
        check_now = _now_ts() if now is None else now
        safe_note = _single_line(note, 160)
        impulse_cleaner = getattr(self, "_cleanup_proactive_impulses", None)
        if callable(impulse_cleaner):
            try:
                for impulse in impulse_cleaner(user, now=check_now):
                    if not isinstance(impulse, dict):
                        continue
                    state = _single_line(impulse.get("state") or "queued", 24).lower()
                    source = _single_line(impulse.get("source"), 40)
                    if state not in {"queued", "deferred", "pending", ""} or source in {"timer", "troubleshooting", "simulation"}:
                        continue
                    impulse["state"] = "blocked"
                    impulse["last_status"] = "blocked"
                    impulse["last_note"] = safe_note
                    impulse["updated_ts"] = check_now
            except Exception as exc:
                logger.debug("[PrivateCompanion] 清理次要用户未回应主动念头失败: %s", _single_line(exc, 120))
        pool_cleaner = getattr(self, "_cleanup_proactive_candidate_pool", None)
        pending_checker = getattr(self, "_pending_candidate_status", None)
        candidate_user_getter = getattr(self, "_candidate_user_id", None)
        user_id = _single_line(user.get("user_id") or user.get("id"), 40)
        if callable(pool_cleaner) and callable(pending_checker) and callable(candidate_user_getter) and user_id:
            try:
                for candidate in pool_cleaner(now=check_now):
                    if not isinstance(candidate, dict):
                        continue
                    if candidate_user_getter(candidate) != user_id:
                        continue
                    source = _single_line(candidate.get("source"), 40)
                    if source in {"timer", "troubleshooting", "simulation"}:
                        continue
                    if not pending_checker(_single_line(candidate.get("status"), 24).lower()):
                        continue
                    candidate["status"] = "blocked"
                    candidate["note"] = safe_note
                    candidate["updated_ts"] = check_now
            except Exception as exc:
                logger.debug("[PrivateCompanion] 清理次要用户未回应主动候选失败: %s", _single_line(exc, 120))

    @staticmethod
    def _friend_unanswered_should_remove_action(action: str) -> bool:
        parts = {part.strip() for part in str(action or "").split("+") if part.strip()}
        return bool(parts & {"poke", "voice", "photo_text", "screen_peek", "jm_cosmos_read"})

    def _friend_unanswered_plan_patch(
        self,
        user: dict[str, Any],
        *,
        level: int,
        reason: str,
        action: str,
        topic: str,
        motive: str,
    ) -> dict[str, str]:
        if level <= 0:
            return {}
        high_pressure_reasons = {
            "check_in",
            "quiet_care",
            "state_share",
            "activity_share",
            "background_schedule",
            "diary_share",
            "morning_greeting",
            "noon_greeting",
            "evening_greeting",
            "habit_awareness",
        }
        normalized_reason = str(reason or "check_in")
        normalized_action = "message" if self._friend_unanswered_should_remove_action(action) else (str(action or "message") or "message")
        if level == 1:
            if normalized_reason in high_pressure_reasons:
                normalized_reason = "quiet_care" if normalized_reason in {"check_in", "state_share", "habit_awareness"} else normalized_reason
            return {
                "reason": normalized_reason,
                "action": normalized_action,
                "topic": _single_line(topic, 80) or "轻一点的近况",
                "motive": "对方还没接话，放轻；不催不追问",
            }
        if level == 2:
            return {
                "reason": "quiet_care",
                "action": "message",
                "topic": "低压近况",
                "motive": "对方有一阵没回应了，低压；不连问",
            }
        return {
            "reason": "quiet_care",
            "action": "message",
            "topic": "留出空间",
            "motive": "连续没回应，退一步；留空间",
        }

    @staticmethod
    def _friend_plan_has_private_interaction_text(text: Any) -> bool:
        cleaned = str(text or "").strip()
        if not cleaned:
            return False
        patterns = (
            r"给.{0,16}(?:回了?消息|发了?消息|回信|回复了?|发私聊)",
            r"(?:回了?消息|发了?消息|回信|发私聊|私聊|聊天|互相吐槽|互相安慰)",
            r"(?:约饭|夜宵|见面|出门|一起(?:做|看|聊|吃|去|玩|散步|上课|写|打))",
            r"(?:朋友用户|朋友边界|朋友那边|朋友私聊|次要用户|次要用户边界|次要用户那边|次要用户私聊)",
        )
        return any(re.search(pattern, cleaned) for pattern in patterns)

    def _sync_configured_targets(self):
        for user_id in self._configured_target_ids():
            user = self._get_user(user_id)
            if user.get("manual_disabled"):
                self._clear_pending_proactive_plan(user)
                continue
            user["enabled"] = True
            user["target_user"] = True
            user.setdefault("nickname", self.default_nickname)
            self._ensure_private_user_umo(user_id, user)
            if self._user_enabled_for_proactive(user_id, user) and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=_now_ts())

    def _prime_enabled_user_schedules(self) -> bool:
        users = self.data.get("users", {})
        if not isinstance(users, dict):
            return False
        changed = False
        now = _now_ts()
        for raw_user in users.values():
            if not isinstance(raw_user, dict):
                continue
            raw_user_id = str(raw_user.get("user_id") or "")
            if not self._user_enabled_for_proactive(raw_user_id, raw_user):
                raw_user["enabled"] = False
                self._clear_pending_proactive_plan(raw_user)
                changed = True
                continue
            if self._ensure_private_user_umo(raw_user_id, raw_user):
                changed = True
            if not raw_user.get("umo"):
                continue
            if _safe_float(raw_user.get("next_proactive_at"), 0) > 0:
                if self._promote_earlier_daily_greeting_event(raw_user, now=now):
                    changed = True
                continue
            self._schedule_next_proactive(raw_user, now=now)
            changed = True
        return changed

    def _is_quiet_time(self) -> bool:
        match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", self.quiet_hours)
        if not match:
            return False
        sh, sm, eh, em = [int(part) for part in match.groups()]
        start = sh * 60 + sm
        end = eh * 60 + em
        now = datetime.now()
        current = now.hour * 60 + now.minute
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _reset_daily_counter_if_needed(self, user: dict[str, Any]):
        today = _today_key()
        if user.get("sent_day") != today:
            user["sent_day"] = today
            user["sent_today"] = 0
            user["proactive_daypart_day"] = today
            user["proactive_daypart_counts"] = {}
        if user.get("photo_generated_day") != today:
            user["photo_generated_day"] = today
            user["photo_generated_today"] = 0
        if user.get("screen_peek_day") != today:
            user["screen_peek_day"] = today
            user["screen_peek_today"] = 0
            user["screen_peek_last_at"] = 0
        if user.get("greeting_sent_day") != today:
            user["greeting_sent_day"] = today
            user["greetings_sent"] = []
            user["greetings_suppressed_by_inbound"] = []
            user["morning_greeting_sent_at"] = 0
            user["morning_greeting_reply_at"] = 0
        if user.get("proactive_daypart_day") != today:
            user["proactive_daypart_day"] = today
            user["proactive_daypart_counts"] = {}

    def _note_morning_greeting_reply(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        """Record the first inbound message after today's morning greeting."""
        self._reset_daily_counter_if_needed(user)
        reply_at = _now_ts() if now is None else now
        sent_at = _safe_float(user.get("morning_greeting_sent_at"), 0)
        previous_reply_at = _safe_float(user.get("morning_greeting_reply_at"), 0)
        if sent_at <= 0 or reply_at < sent_at or previous_reply_at >= sent_at:
            return False
        user["morning_greeting_reply_at"] = reply_at
        return True

    def _unanswered_slowdown_count(self, user: dict[str, Any]) -> int:
        ignored_streak = _safe_int(user.get("ignored_streak"), 0)
        start = self._effective_proactive_int(
            "unanswered_slowdown_start",
            _safe_int(getattr(self, "proactive_unanswered_slowdown_start", 1), 1, 1, 10),
            minimum=1,
            maximum=10,
        )
        return max(0, ignored_streak - start + 1)

    def _unanswered_interval_multiplier(self, user: dict[str, Any]) -> float:
        active_count = self._unanswered_slowdown_count(user)
        max_multiplier = self._effective_proactive_float(
            "unanswered_max_interval_multiplier",
            max(1.0, _safe_float(getattr(self, "proactive_unanswered_max_interval_multiplier", 2.2), 2.2, 1.0)),
            minimum=1.0,
            maximum=8.0,
        )
        return min(max_multiplier, 1.0 + active_count * 0.35)

    def _effective_min_interval_seconds(self, user: dict[str, Any]) -> int:
        multiplier = (
            self._unanswered_interval_multiplier(user)
            * self._cycle_proactive_frequency_profile()["private_interval_multiplier"]
        )
        return int(self._effective_user_min_interval_minutes(user) * 60 * multiplier)

    def _bot_proactive_drive(self, user: dict[str, Any] | None = None, *, now: float | None = None) -> dict[str, Any]:
        state = self.data.get("daily_state", {})
        if not isinstance(state, dict):
            state = {}
        energy = _safe_int(state.get("energy"), 70, 0, 100)
        mood = _single_line(state.get("mood_bias") or state.get("mood"), 24)
        note = _single_line(state.get("note"), 120)
        conditions = state.get("conditions")
        score = 0.55 + (energy - 55) / 220.0
        reasons: list[str] = [f"energy={energy}"]
        if mood in {"轻快", "兴奋", "松弛", "明亮", "活跃"}:
            score += 0.08
            reasons.append(f"心情{mood}")
        elif mood in {"安静", "疲惫", "低落", "收声", "困倦"}:
            score -= 0.09
            reasons.append(f"心情{mood}")
        if any(token in note for token in ("疲惫", "困", "低电量", "收声", "慢一点")):
            score -= 0.08
            reasons.append("状态偏收")
        if any(token in note for token in ("轻快", "有精神", "想说话", "灵感", "开心")):
            score += 0.07
            reasons.append("状态偏开")
        if isinstance(conditions, list):
            for cond in conditions[:4]:
                text = _single_line(cond.get("label") or cond.get("text") or cond.get("kind"), 40) if isinstance(cond, dict) else _single_line(cond, 40)
                if any(token in text for token in ("疲惫", "困", "安静", "低落", "身体不舒服")):
                    score -= 0.04
                elif any(token in text for token in ("兴奋", "开心", "灵感", "想分享")):
                    score += 0.04
        score = max(0.12, min(1.0, score))
        if score >= 0.72:
            label = "想开口"
        elif score <= 0.42:
            label = "想收着"
        else:
            label = "平稳"
        return {
            "score": score,
            "label": label,
            "detail": "；".join(reasons[:4]),
        }

    def _relationship_proactive_temperature(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        check_now = _now_ts() if now is None else now
        score = 0.54
        reasons: list[str] = []
        relationship_score = _safe_int(user.get("relationship_score"), 0, -100, 300)
        if relationship_score:
            score += max(-0.08, min(0.14, relationship_score / 500.0))
            reasons.append(f"关系分{relationship_score}")
        ignored_streak = _safe_int(user.get("ignored_streak"), 0, 0, 20)
        if ignored_streak:
            score -= min(0.32, ignored_streak * 0.08)
            reasons.append(f"未回应{ignored_streak}")
        last_reply_at = _safe_float(user.get("last_reply_at"), 0)
        if last_reply_at > 0:
            hours = (check_now - last_reply_at) / 3600.0
            if hours <= 6:
                score += 0.12
                reasons.append("刚有回应")
            elif hours <= 24:
                score += 0.06
                reasons.append("近一天回应过")
        awaiting_since = _safe_float(user.get("awaiting_reply_since"), 0)
        if awaiting_since > 0 and check_now - awaiting_since > 4 * 3600:
            score -= 0.08
            reasons.append("上一轮还悬着")
        rel_state = user.get("relationship_state")
        mode = str(rel_state.get("mode") or "") if isinstance(rel_state, dict) else ""
        if mode == "attached":
            score += 0.08
            reasons.append("关系贴近")
        elif mode == "careful":
            score -= 0.08
            reasons.append("关系谨慎")
        elif mode in {"hurt", "refusing", "backoff"}:
            score -= 0.22
            reasons.append(f"关系{mode}")
        if self._private_user_role(user) == "friend":
            score -= 0.04
            reasons.append("朋友边界")
        score = max(0.05, min(1.0, score))
        if score >= 0.7:
            label = "温热"
        elif score <= 0.38:
            label = "偏冷"
        else:
            label = "普通"
        return {
            "score": score,
            "label": label,
            "detail": "；".join(reasons[:5]) or "互动平稳",
        }

    def _proactive_inner_readiness(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        drive = self._bot_proactive_drive(user, now=now)
        temperature = self._relationship_proactive_temperature(user, now=now)
        score = _safe_float(drive.get("score"), 0.55) * 0.48 + _safe_float(temperature.get("score"), 0.55) * 0.52
        motivation: dict[str, Any] = {}
        if bool(getattr(self, "enable_experimental_motivation_model", False)):
            motivation = self._experimental_proactive_motivation(user, now=now, drive=drive, temperature=temperature)
            modifier = (_safe_float(motivation.get("score"), 0.5) - 0.5) * 0.16
            score += modifier
        score = max(0.05, min(1.0, score))
        result = {
            "score": score,
            "label": f"{drive.get('label')}/{temperature.get('label')}",
            "detail": f"状态:{drive.get('detail')}; 关系:{temperature.get('detail')}",
            "drive": drive,
            "temperature": temperature,
        }
        if motivation:
            result["motivation"] = motivation
            result["detail"] = f"{result['detail']}; 动机:{motivation.get('label')} {motivation.get('detail')}"
        return result

    def _experimental_proactive_incentive(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        action = self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40)
        source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        topic = _single_line(user.get("planned_proactive_topic"), 100)
        motive = _single_line(user.get("planned_proactive_motive"), 160)
        semantics: dict[str, Any] = {}
        semantic_getter = getattr(self, "_planned_proactive_semantics", None)
        if callable(semantic_getter):
            try:
                semantics = semantic_getter(user)
            except Exception:
                semantics = {}
        score = 0.5
        reasons: list[str] = []
        if reason in {"timer", "reminder", "pending_followup", "followup"} or source == "timer":
            score += 0.18
            reasons.append("任务/约定诱因")
        if reason in {"creative_share", "diary_share", "dream_share", "activity_share", "news_share", "web_exploration_share", "qzone_life_publish"}:
            score += 0.10
            reasons.append("有内容可分享")
        if reason in {"group_share", "atrelay_followup"}:
            score += 0.12
            reasons.append("外部互动线索")
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            sent_today = _safe_int(user.get("sent_today"), 0, 0, 100)
            last_reply_at = _safe_float(user.get("last_reply_at"), 0)
            check_now = _now_ts() if now is None else now
            if sent_today > 0 or (last_reply_at > 0 and check_now - last_reply_at <= 3 * 3600):
                score -= 0.16
                reasons.append("问候诱因已释放")
            else:
                score += 0.04
                reasons.append("时段问候")
        if reason in {"check_in", "quiet_care", ""}:
            score -= 0.03
            reasons.append("泛关心诱因较弱")
        if action in {"photo_text", "voice", "poke"}:
            score += 0.04
            reasons.append(f"{action}动作诱因")
        if self._private_user_role(user) == "friend" and action in {"photo_text", "screen_peek"}:
            score -= 0.18
            reasons.append("次要用户能力边界")
        concrete_text = f"{topic} {motive}"
        if len(re.sub(r"\s+", "", concrete_text)) >= 18 and not any(token in concrete_text for token in ("问一句近况", "打个招呼", "在不在", "忙不忙")):
            score += 0.07
            reasons.append("切口具体")
        semantic_score = _safe_float(semantics.get("score"), 0.5)
        semantic_pressure = _safe_float(semantics.get("pressure"), 0.4)
        score += (semantic_score - 0.5) * 0.10
        score -= max(0.0, semantic_pressure - 0.55) * 0.16
        ignored = _safe_int(user.get("ignored_streak"), 0, 0, 20)
        if ignored:
            score -= min(0.22, ignored * 0.055)
            reasons.append(f"未回应{ignored}")
        score = max(0.05, min(1.0, score))
        label = "诱因强" if score >= 0.68 else "诱因弱" if score <= 0.38 else "诱因普通"
        return {"score": score, "label": label, "detail": "；".join(reasons[:5]) or "无明显外部诱因"}

    def _experimental_proactive_arousal(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        state = self.data.get("daily_state", {})
        if not isinstance(state, dict):
            state = {}
        energy = _safe_int(state.get("energy"), 70, 0, 100)
        mood = _single_line(state.get("mood_bias") or state.get("mood"), 24)
        note = _single_line(state.get("note"), 160)
        arousal = 0.38 + energy / 180.0
        reasons = [f"energy={energy}"]
        if mood in {"兴奋", "轻快", "活跃", "明亮"}:
            arousal += 0.12
            reasons.append(f"心情{mood}")
        elif mood in {"疲惫", "困倦", "低落", "收声", "安静"}:
            arousal -= 0.12
            reasons.append(f"心情{mood}")
        if any(token in note for token in ("高压", "赶", "急", "兴奋", "停不下来")):
            arousal += 0.08
            reasons.append("状态偏高")
        if any(token in note for token in ("困", "疲惫", "低电量", "慢一点", "收声")):
            arousal -= 0.08
            reasons.append("状态偏低")
        ignored = _safe_int(user.get("ignored_streak"), 0, 0, 20)
        if ignored >= 2:
            arousal -= 0.06
            reasons.append("未回应降唤醒")
        arousal = max(0.0, min(1.0, arousal))
        fit = max(0.0, 1.0 - abs(arousal - 0.55) * 1.45)
        if arousal >= 0.78:
            label = "唤醒偏高"
        elif arousal <= 0.30:
            label = "唤醒偏低"
        else:
            label = "唤醒适中"
        return {"score": fit, "level": arousal, "label": label, "detail": "；".join(reasons[:4])}

    def _experimental_proactive_motivation(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
        drive: dict[str, Any] | None = None,
        temperature: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        drive = drive if isinstance(drive, dict) else self._bot_proactive_drive(user, now=now)
        temperature = temperature if isinstance(temperature, dict) else self._relationship_proactive_temperature(user, now=now)
        incentive = self._experimental_proactive_incentive(user, now=now)
        arousal = self._experimental_proactive_arousal(user, now=now)
        drive_score = _safe_float(drive.get("score"), 0.55)
        temp_score = _safe_float(temperature.get("score"), 0.55)
        incentive_score = _safe_float(incentive.get("score"), 0.5)
        arousal_fit = _safe_float(arousal.get("score"), 0.5)
        score = drive_score * 0.25 + temp_score * 0.18 + incentive_score * 0.37 + arousal_fit * 0.20
        score = max(0.05, min(1.0, score))
        label = "适合行动" if score >= 0.66 else "先收住" if score <= 0.40 else "观望"
        detail = (
            f"驱力{drive_score:.2f} 诱因{incentive_score:.2f} "
            f"唤醒{_safe_float(arousal.get('level'), 0.55):.2f}/适配{arousal_fit:.2f}"
        )
        return {
            "score": score,
            "label": label,
            "detail": detail,
            "drive": drive,
            "temperature": temperature,
            "incentive": incentive,
            "arousal": arousal,
        }

    def _soft_daily_target(self, user: dict[str, Any]) -> float:
        daily_limit = self._effective_user_daily_limit(user)
        if daily_limit <= 0:
            return 0.0
        if bool(self._proactive_intensity_effect("ignore_soft_daily_target", False)):
            return float(daily_limit)
        state = self.data.get("daily_state", {})
        important_dates = self._get_relevant_important_dates()
        energy = _safe_int(state.get("energy") if isinstance(state, dict) else 70, 70, 0, 100)
        active_conditions = state.get("conditions", []) if isinstance(state, dict) else []
        ratio = 0.68
        if energy > 80:
            ratio += 0.06
        elif energy < 40:
            ratio -= 0.02
        if isinstance(active_conditions, list) and active_conditions:
            ratio += min(0.1, len(active_conditions) * 0.03)
        if important_dates:
            ratio += 0.1 if _safe_int(important_dates[0].get("_days_until"), 0) == 0 else 0.05
        ratio = max(0.45, min(0.95, ratio))
        if daily_limit == 1:
            ratio = max(ratio, 0.75)
        return max(0.6, daily_limit * ratio)

    def _daily_intensity_factor(self, user: dict[str, Any]) -> float:
        daily_limit = self._effective_user_daily_limit(user)
        if daily_limit <= 0:
            return 0.0
        sent_today = _safe_int(user.get("sent_today"), 0)
        soft_target = self._soft_daily_target(user)
        no_cost_mode = bool(self._proactive_intensity_effect("ignore_soft_daily_target", False))
        capacity_factor = min(2.6 if no_cost_mode else 1.35, 0.9 + daily_limit * (0.055 if no_cost_mode else 0.08))
        if soft_target <= 0:
            return max(0.35, capacity_factor)
        usage = sent_today / soft_target
        if usage < 0.2:
            pressure = 1.18
        elif usage < 0.5:
            pressure = 1.03
        elif usage < 0.85:
            pressure = 0.88
        elif usage < 1.0:
            pressure = 0.72
        else:
            pressure = 0.9 if no_cost_mode else 0.5
        readiness = self._proactive_inner_readiness(user)
        inner_factor = 0.74 + _safe_float(readiness.get("score"), 0.55) * 0.55
        return max(0.25, min(2.4 if no_cost_mode else 1.5, capacity_factor * pressure * inner_factor))

    def _fallback_proactive_delay_hours(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> tuple[float, float]:
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        if self._private_user_role(user) == "friend":
            spread_delay = self._friend_proactive_spread_delay_hours(user, now=now_dt.timestamp())
            if spread_delay is not None:
                return spread_delay
        sent_today = _safe_int(user.get("sent_today"), 0)
        remaining_target = max(1, math.ceil(max(0.0, self._soft_daily_target(user) - sent_today)))
        readiness_score = _safe_float(self._proactive_inner_readiness(user, now=now_dt.timestamp()).get("score"), 0.55)
        if readiness_score < 0.38:
            return (2.5, 6.0) if self._private_user_role(user) != "friend" else (8.0, 16.0)
        counts = self._today_proactive_daypart_counts(user)
        current_bucket = self._proactive_daypart_bucket_for_minute(now_dt.hour * 60 + now_dt.minute)
        if current_bucket == "late_night" and _safe_int(counts.get("late_night"), 0, 0) >= 1:
            return (7.5, 10.5)
        if current_bucket == "evening" and _safe_int(counts.get("evening"), 0, 0) >= 1 and remaining_target <= 2:
            return (3.0, 5.0)

        if now_dt.hour < 12:
            if remaining_target >= 4:
                return (0.45, 1.4)
            if remaining_target >= 3:
                return (0.75, 2.0)
            if remaining_target >= 2:
                return (1.0, 2.8)
            return (1.6, 4.2)
        if now_dt.hour < 18:
            if remaining_target >= 3:
                return (0.55, 1.8)
            if remaining_target >= 2:
                return (0.9, 2.6)
            return (1.8, 4.5)
        if remaining_target >= 2:
            return (0.5, 1.6)
        return (0.9, 2.4)

    def _friend_proactive_spread_delay_hours(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> tuple[float, float] | None:
        if self._private_user_role(user) != "friend":
            return None
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        sent_today = _safe_int(user.get("sent_today"), 0)
        daily_limit = self._effective_user_daily_limit(user)
        if daily_limit <= 1 or sent_today <= 0:
            return None
        ignored_slowdown = self._unanswered_slowdown_count(user)
        max_cooldown = self._effective_proactive_float(
            "friend_unanswered_max_cooldown_hours",
            max(1.0, _safe_float(getattr(self, "friend_unanswered_max_cooldown_hours", 60.0), 60.0, 1.0)),
            minimum=1.0,
            maximum=168.0,
        )

        def cap_delay(delay: tuple[float, float]) -> tuple[float, float]:
            low, high = delay
            high = min(max_cooldown, high)
            low = min(low, max(1.0, high))
            return (low, high)

        if ignored_slowdown >= 4:
            return cap_delay((36.0, 60.0))
        if ignored_slowdown >= 3:
            return cap_delay((20.0, 36.0))
        if ignored_slowdown >= 2:
            return cap_delay((12.0, 24.0))
        minute = now_dt.hour * 60 + now_dt.minute
        if sent_today <= 1:
            if ignored_slowdown >= 1:
                return cap_delay((8.0, 14.0))
            if minute < 14 * 60:
                return self._delay_hours_until_local_window(now_dt, 14 * 60, 17 * 60)
            if minute < 18 * 60:
                return self._delay_hours_until_local_window(now_dt, 19 * 60, 21 * 60 + 20)
            return (6.0, 11.0)
        if sent_today <= 2 and daily_limit >= 3:
            if ignored_slowdown >= 1:
                return cap_delay((10.0, 18.0))
            if minute < 18 * 60 + 30:
                return self._delay_hours_until_local_window(now_dt, 18 * 60 + 40, 21 * 60 + 20)
            return (8.0, 14.0)
        return (10.0, 18.0)

    def _delay_hours_until_local_window(
        self,
        now_dt: datetime,
        start_minute: int,
        end_minute: int,
    ) -> tuple[float, float]:
        base = datetime.combine(now_dt.date(), datetime.min.time(), tzinfo=now_dt.tzinfo)
        start_dt = base + timedelta(minutes=start_minute)
        end_dt = base + timedelta(minutes=end_minute)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        if end_dt <= now_dt + timedelta(minutes=20):
            start_dt += timedelta(days=1)
            end_dt += timedelta(days=1)
        start_dt = max(start_dt, now_dt + timedelta(hours=3))
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=90)
        min_hours = max(0.25, (start_dt - now_dt).total_seconds() / 3600)
        max_hours = max(min_hours + 0.5, (end_dt - now_dt).total_seconds() / 3600)
        return (min_hours, max_hours)

    def _current_emotion_gate_mode(self, user: dict[str, Any], *, now: float | None = None) -> str:
        if not bool(getattr(self, "enable_emotion_simulation", True)):
            return ""
        rel_state = user.get("relationship_state")
        if not isinstance(rel_state, dict):
            return ""
        check_now = _now_ts() if now is None else now
        mode = str(rel_state.get("mode") or "")
        if mode in {"hurt", "refusing"} and _safe_float(rel_state.get("hurt_until"), 0) <= check_now:
            return ""
        if mode in {"hurt", "refusing", "attached"}:
            return mode
        return ""

    def _current_relationship_gate_mode(self, user: dict[str, Any], *, now: float | None = None) -> str:
        rel_state = user.get("relationship_state")
        if not isinstance(rel_state, dict):
            return ""
        check_now = _now_ts() if now is None else now
        mode = str(rel_state.get("mode") or "")
        if mode == "backoff" and bool(getattr(self, "enable_relationship_state_machine", True)):
            return "backoff" if _safe_float(rel_state.get("backoff_until"), 0) > check_now else ""
        if mode == "careful" and bool(getattr(self, "enable_relationship_state_machine", True)):
            return "careful"
        return ""

    @staticmethod
    def _proactive_reason_is_intimate(reason: str) -> bool:
        return str(reason or "") in {
            "insomnia_night",
            "state_share",
            "diary_share",
            "evening_greeting",
        }

    @staticmethod
    def _proactive_action_is_intimate(action: str) -> bool:
        parts = {part.strip() for part in str(action or "").split("+") if part.strip()}
        return bool(parts & {"poke", "voice", "photo_text", "screen_peek", "jm_cosmos_read"})

    @staticmethod
    def _proactive_text_is_intimate(*parts: Any) -> bool:
        text = " ".join(_single_line(part, 120) for part in parts if _single_line(part, 120))
        return bool(re.search(r"贴贴|抱抱|亲亲|摸摸|揉揉|蹭蹭|逗你|撒娇|想你|黏|贴近|靠近|坏心思|亲密|睡前|床|小屁股", text, re.I))

    def _low_pressure_proactive_replacement(
        self,
        *,
        mode: str,
        reason: str,
        action: str,
        motive: str,
        topic: str = "",
    ) -> tuple[str, str, str, str]:
        if mode == "careful":
            return (
                "quiet_care",
                "message",
                "感觉用户这会儿可能有点累或压力,只低压地问一句,不追问、不要求回复",
                topic or "低压关心",
            )
        if mode in {"hurt", "refusing"}:
            return (
                "quiet_care",
                "message",
                "Bot 还在收敛情绪,只保留一条很短的低压关心；不贴近、不撒娇、不追问",
                topic or "收敛后的低压关心",
            )
        return reason, action, motive, topic

    def _apply_emotion_to_planned_proactive(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
        topic: str = "",
        scheduled: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        check_now = _now_ts() if now is None else now
        mode = self._current_emotion_gate_mode(user, now=check_now) or self._current_relationship_gate_mode(user, now=check_now)
        result = {
            "reason": reason,
            "action": action,
            "motive": motive,
            "topic": topic,
            "scheduled": scheduled,
            "mode": mode,
            "note": "",
            "blocked": False,
        }
        intimate = (
            self._proactive_reason_is_intimate(reason)
            or self._proactive_action_is_intimate(action)
            or self._proactive_text_is_intimate(reason, action, motive, topic)
        )
        if mode == "attached":
            if reason in {"check_in", "quiet_care"} and random.random() < 0.28:
                result["reason"] = "activity_share"
                result["motive"] = motive or "刚刚有个轻轻的小想法,想自然分享一下"
                result["topic"] = topic or "轻分享"
                result["note"] = "情绪 attached: 提高轻分享倾向"
            photo_probability = max(0.0, min(1.0, float(getattr(self, "proactive_photo_text_probability", 0.18))))
            if action == "message" and reason in {"activity_share", "diary_share", "background_schedule"} and self._photo_text_available(user) and random.random() < photo_probability:
                result["action"] = self._fallback_action_for_unavailable("photo_text", user)
                result["note"] = (result["note"] + "；" if result["note"] else "") + "情绪 attached: 轻分享可带图"
            return result
        if mode == "careful":
            if action != "message" or reason not in {"quiet_care", "check_in"} or intimate:
                new_reason, new_action, new_motive, new_topic = self._low_pressure_proactive_replacement(
                    mode=mode,
                    reason=reason,
                    action=action,
                    motive=motive,
                    topic=topic,
                )
                result.update(reason=new_reason, action=new_action, motive=new_motive, topic=new_topic)
                result["note"] = "关系 careful: 只保留低压关心"
            return result
        if mode in {"hurt", "refusing", "backoff"}:
            if str(user.get("planned_proactive_source") or "") == "timer":
                return result
            delay = 2.5 * 3600 if mode == "hurt" else 5.5 * 3600
            if scheduled and scheduled > 0:
                result["scheduled"] = max(scheduled, check_now + random.uniform(delay, delay + 2.5 * 3600))
            if intimate or action != "message" or mode in {"refusing", "backoff"}:
                new_reason, new_action, new_motive, new_topic = self._low_pressure_proactive_replacement(
                    mode="hurt" if mode == "hurt" else "refusing",
                    reason=reason,
                    action=action,
                    motive=motive,
                    topic=topic,
                )
                result.update(reason=new_reason, action=new_action, motive=new_motive, topic=new_topic)
                result["note"] = f"情绪 {mode}: 延后并清理亲密主动候选"
            elif mode == "hurt":
                result["note"] = "情绪 hurt: 候选延后"
            return result
        return result

    def _defer_or_clean_emotion_blocked_plan(self, user: dict[str, Any], *, now: float | None = None) -> str:
        check_now = _now_ts() if now is None else now
        mode = self._current_emotion_gate_mode(user, now=check_now) or self._current_relationship_gate_mode(user, now=check_now)
        if mode not in {"hurt", "refusing", "backoff"}:
            return "情绪/关系状态处于收敛期"
        if str(user.get("planned_proactive_source") or "") == "timer":
            return "情绪/关系状态处于收敛期,预约主动保留"
        reason = str(user.get("planned_proactive_reason") or "")
        action = str(user.get("planned_proactive_action") or "message")
        motive = _single_line(user.get("planned_proactive_motive"), 140)
        topic = _single_line(user.get("planned_proactive_topic"), 60)
        intimate = (
            self._proactive_reason_is_intimate(reason)
            or self._proactive_action_is_intimate(action)
            or self._proactive_text_is_intimate(reason, action, motive, topic)
        )
        rel_state = user.get("relationship_state") if isinstance(user.get("relationship_state"), dict) else {}
        hurt_until = _safe_float(rel_state.get("hurt_until"), 0)
        backoff_until = _safe_float(rel_state.get("backoff_until"), 0)
        gate_until = max(hurt_until, backoff_until)
        base_after = max(check_now + 90 * 60, gate_until + random.uniform(15 * 60, 75 * 60))
        if intimate or mode in {"refusing", "backoff"}:
            self._mark_planned_candidate_status(user, "deferred", f"情绪 {mode}: 亲密主动候选已清理/延后")
            self._clear_pending_proactive_plan(user)
            if mode == "hurt":
                user["next_proactive_at"] = base_after + random.uniform(20 * 60, 90 * 60)
                user["planned_proactive_reason"] = "quiet_care"
                user["planned_proactive_action"] = "message"
                user["planned_proactive_source"] = "emotion_gate"
                user["planned_proactive_motive"] = "Bot 还在收敛情绪,只留一条很短的低压关心,不贴近也不追问"
                user["planned_proactive_topic"] = "情绪收敛后的低压关心"
                user["planned_proactive_impulse_id"] = ""
                user["planned_proactive_window_start_at"] = user["next_proactive_at"]
                active_span, grace_span = self._proactive_impulse_default_window_seconds(user["planned_proactive_reason"])
                user["planned_proactive_best_until_at"] = user["next_proactive_at"] + active_span
                user["planned_proactive_expire_at"] = user["next_proactive_at"] + active_span + grace_span
                semantics = self._planned_proactive_semantics(user)
                user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
                user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
                user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
                user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
                item = self._record_proactive_candidate(
                    str(user.get("user_id") or user.get("id") or ""),
                    {
                        "source": "emotion_gate",
                        "reason": user["planned_proactive_reason"],
                        "action": user["planned_proactive_action"],
                        "scheduled_ts": user["next_proactive_at"],
                        "topic": user["planned_proactive_topic"],
                        "motive": user["planned_proactive_motive"],
                        "score": 32,
                    },
                    status="accepted",
                    note="情绪 hurt: 恢复后低压关心候选",
                    user=user,
                )
                user["planned_candidate_id"] = item.get("id", "")
                saver = getattr(self, "_schedule_data_save", None)
                if callable(saver):
                    saver()
                return "情绪 hurt 收敛中,亲密主动候选已延后"
            scheduler = getattr(self, "_schedule_next_proactive", None)
            if callable(scheduler):
                scheduler(user, now=base_after, delay_hours=(0.5, 2.0))
            if _safe_float(user.get("next_proactive_at"), 0) <= check_now:
                user["next_proactive_at"] = base_after
                user["planned_proactive_window_start_at"] = base_after
                user["planned_proactive_best_until_at"] = base_after + 45 * 60
                user["planned_proactive_expire_at"] = base_after + 90 * 60
            saver = getattr(self, "_schedule_data_save", None)
            if callable(saver):
                saver()
            return f"情绪/关系 {mode} 收敛中,亲密主动候选已清理"
        defer = getattr(self, "_defer_or_replace_planned_impulse", None)
        if callable(defer):
            delay_minutes = max(1.0, (base_after - check_now) / 60)
            defer(
                user,
                now=check_now,
                note=f"情绪 {mode}: 主动候选延后",
                delay_minutes=(delay_minutes, delay_minutes + 30.0),
                block_current=False,
            )
        else:
            self._mark_planned_candidate_status(user, "deferred", f"情绪 {mode}: 主动候选延后")
            user["next_proactive_at"] = max(_safe_float(user.get("next_proactive_at"), 0), base_after)
        saver = getattr(self, "_schedule_data_save", None)
        if callable(saver):
            saver()
        return f"情绪 {mode} 收敛中,主动候选已延后"

    def _normalize_existing_plan_for_emotion(self, user: dict[str, Any], *, now: float | None = None) -> str:
        check_now = _now_ts() if now is None else now
        if str(user.get("planned_proactive_source") or "") == "timer":
            return ""
        reason = str(user.get("planned_proactive_reason") or "")
        action = str(user.get("planned_proactive_action") or "message")
        motive = _single_line(user.get("planned_proactive_motive"), 140)
        topic = _single_line(user.get("planned_proactive_topic"), 60)
        scheduled = _safe_float(user.get("next_proactive_at"), 0)
        adjusted = self._apply_emotion_to_planned_proactive(
            user,
            reason=reason,
            action=action,
            motive=motive,
            topic=topic,
            scheduled=scheduled,
            now=check_now,
        )
        note = _single_line(adjusted.get("note"), 160)
        if not note:
            return ""
        user["planned_proactive_reason"] = str(adjusted.get("reason") or reason)
        user["planned_proactive_action"] = str(adjusted.get("action") or action)
        user["planned_proactive_motive"] = _single_line(adjusted.get("motive"), 140) or motive
        user["planned_proactive_topic"] = _single_line(adjusted.get("topic"), 60) or topic
        user["next_proactive_at"] = _safe_float(adjusted.get("scheduled"), scheduled)
        self._mark_planned_candidate_status(user, "accepted", note)
        saver = getattr(self, "_schedule_data_save", None)
        if callable(saver):
            saver()
        return note

    def _friend_proactive_scheduled_too_early(
        self,
        user: dict[str, Any],
        scheduled_at: float,
    ) -> bool:
        if self._private_user_role(user) != "friend" or scheduled_at <= 0:
            return False
        daily_limit = self._effective_user_daily_limit(user)
        sent_today = _safe_int(user.get("sent_today"), 0)
        if daily_limit <= 1 or sent_today <= 0:
            return False
        ignored_streak = _safe_int(user.get("ignored_streak"), 0)
        if ignored_streak >= 2:
            last_sent = _safe_float(user.get("last_sent"), 0)
            if last_sent > 0 and scheduled_at - last_sent < 12 * 3600:
                return True
        if ignored_streak >= 3:
            last_sent = _safe_float(user.get("last_sent"), 0)
            if last_sent > 0 and scheduled_at - last_sent < 20 * 3600:
                return True
        now_dt = self._environment_now()
        scheduled_dt = self._environment_fromtimestamp(scheduled_at)
        if scheduled_dt.date() != now_dt.date():
            return False
        minute = scheduled_dt.hour * 60 + scheduled_dt.minute
        if sent_today >= 2 and daily_limit >= 3:
            return minute < 18 * 60 + 30
        if sent_today >= 1:
            return minute < 14 * 60
        return False

    def _random_proactive_impulse_context(
        self,
        user: dict[str, Any],
        *,
        now: float,
    ) -> dict[str, Any]:
        if self._companion_frequency_enabled() and self._private_user_role(user) != "friend":
            profile = self._companion_frequency_profile(user, now=now)
            return {
                "allowed": bool(profile.get("allowed")),
                "reasons": ["正常私聊留白中的安静陪伴"],
                "suggest_soft_reason": True,
                "companion_profile": profile,
            }
        state = self.data.get("daily_state", {})
        if not isinstance(state, dict):
            state = {}
        energy = _safe_int(state.get("energy"), 70, 0, 100)
        mood = _single_line(state.get("mood_bias") or state.get("mood"), 24)
        note = _single_line(state.get("note"), 120)
        ignored_streak = _safe_int(user.get("ignored_streak"), 0, 0, 20)
        awaiting_since = _safe_float(user.get("awaiting_reply_since"), 0)
        last_sent = _safe_float(user.get("last_sent"), 0)
        reasons: list[str] = []
        suggest_soft_reason = False
        if awaiting_since > 0:
            silent_hours = (now - awaiting_since) / 3600.0
            if silent_hours >= 3.0:
                reasons.append(f"已等待回复 {silent_hours:.1f}h")
                suggest_soft_reason = True
        elif ignored_streak >= 1 and last_sent > 0 and now - last_sent >= 3 * 3600:
            reasons.append(f"未回应 {ignored_streak} 次")
            suggest_soft_reason = True
        low_energy = energy <= 45
        quiet_mood = mood in {"安静", "疲惫", "低落", "收声", "困倦"}
        if low_energy or quiet_mood or any(token in note for token in ("疲惫", "困", "低电量", "收声", "慢一点", "安静")):
            reasons.append(f"状态偏低({energy}/{mood or '平稳'})")
            suggest_soft_reason = True
        return {
            "allowed": bool(reasons),
            "reasons": reasons,
            "suggest_soft_reason": suggest_soft_reason,
        }

    def _queue_event_driven_proactive_impulses(
        self,
        user: dict[str, Any],
        *,
        now: float,
    ) -> int:
        queued = 0
        event_sources = (
            ("pending_followup", self._pick_pending_followup_event(user, now)),
            ("birthday_celebration", self._pick_birthday_celebration_event(user, now)),
            ("holiday_celebration", self._pick_holiday_celebration_event(user, now)),
            ("course_reminder", self._pick_course_reminder_event(user, now)),
            ("meal_care", self._pick_meal_care_event(user, now=now)),
            ("daily_greeting", self._pick_daily_greeting_event(user, now)),
            ("birthday_curiosity", self._pick_birthday_curiosity_event(user, now)),
            ("habit", self._habit_proactive_event_for_user(user, now=now)),
            ("state", self._pick_state_need_event(user, now=now)),
            ("story", self._pick_story_plan_event(now, user=user)),
        )
        for source, event in event_sources:
            if not isinstance(event, dict):
                continue
            social_relay_note = self._unverified_social_relay_plan_reason(
                event,
                source=source,
                has_trigger=bool(_single_line(event.get("trigger_message_id"), 120)),
            )
            if social_relay_note:
                self._record_proactive_candidate(
                    str(user.get("user_id") or user.get("id") or ""),
                    {
                        "source": source,
                        "reason": _single_line(event.get("reason"), 40) or "check_in",
                        "action": _single_line(event.get("action"), 40) or "message",
                        "scheduled_ts": _safe_float(event.get("_scheduled_ts"), now),
                        "topic": _single_line(event.get("topic"), 80),
                        "motive": _single_line(event.get("motive"), 180),
                        "score": 0,
                    },
                    status="blocked",
                    note=social_relay_note,
                    user=user,
                )
                continue
            reason = _single_line(event.get("reason"), 40) or "check_in"
            motive = _single_line(event.get("motive"), 140)
            action = _single_line(event.get("action"), 40)
            if not action:
                if not motive:
                    motive = self._choose_proactive_motive(reason, user, planned_event=event)
                action = self._choose_action_for_reason(reason, user, motive=motive)
            elif not motive:
                motive = self._choose_proactive_motive(reason, user, action=action, planned_event=event)
            action = self._maybe_upgrade_planned_message_action(
                action,
                reason=reason,
                user=user,
                motive=motive,
                planned_event=event,
            )
            topic = _single_line(event.get("topic"), 60) or self._choose_proactive_topic(reason, user)
            if self._action_has_photo_text(action) and self._private_user_role(user) != "friend":
                photo_patch = self._photo_text_plan_field_patch(
                    reason=reason,
                    topic=topic,
                    motive=motive,
                    planned_event=event,
                )
                topic = _single_line(photo_patch.get("topic"), 60) or topic
                motive = _single_line(photo_patch.get("motive"), 140) or motive
            if self._private_user_role(user) == "friend":
                friend_safe = self._sanitize_friend_proactive_plan_fields(
                    user,
                    reason=reason,
                    action=action,
                    topic=topic,
                    motive=motive,
                )
                reason = friend_safe["reason"]
                action = friend_safe["action"]
                topic = friend_safe["topic"]
                motive = friend_safe["motive"]
            candidate = dict(event)
            candidate["reason"] = reason
            candidate["action"] = action
            candidate["topic"] = topic
            candidate["motive"] = motive
            impulse = self._candidate_to_impulse(user, candidate, source=source, now=now)
            if not isinstance(impulse, dict):
                continue
            rest_until = self._proactive_rest_block_until(
                user,
                now=now,
                reason=reason,
                source=source,
            )
            if rest_until > now and _safe_float(impulse.get("window_start_at"), 0) < rest_until:
                shift = rest_until - _safe_float(impulse.get("window_start_at"), 0) + random.uniform(20 * 60, 90 * 60)
                if reason in {"holiday_celebration", "course_reminder"}:
                    # These are real calendar windows, not windows that may be
                    # extended into the next day or beyond the start of class.
                    shifted = _safe_float(impulse.get("window_start_at"), 0) + shift
                    if shifted >= _safe_float(impulse.get("expire_at"), 0):
                        continue
                    impulse["window_start_at"] = shifted
                    impulse["preferred_ts"] = max(shifted, _safe_float(impulse.get("preferred_ts"), 0))
                    self._queue_proactive_impulse(user, impulse)
                    queued += 1
                    continue
                impulse["window_start_at"] = _safe_float(impulse.get("window_start_at"), 0) + shift
                impulse["preferred_ts"] = _safe_float(impulse.get("preferred_ts"), 0) + shift
                impulse["best_until_at"] = _safe_float(impulse.get("best_until_at"), 0) + shift
                impulse["expire_at"] = _safe_float(impulse.get("expire_at"), 0) + shift
            self._queue_proactive_impulse(user, impulse)
            queued += 1
        return queued

    _TLS_NATIVE_RANDOM_MARKER = 'tls.native.random.owner.v1'

    def _tls_native_random_owned(self, session):
        """RAM-only exact configured session; no identity or persona guessing."""
        marker = 'tls.native.random.owner.v1'
        config = getattr(self, 'config', None)
        sessions = dict.get(config, 'tls_native_random_sessions', []) if isinstance(config, dict) else None
        return (marker == self._TLS_NATIVE_RANDOM_MARKER and isinstance(session, str) and bool(session)
                and isinstance(sessions, list) and len(sessions) <= 64
                and all(isinstance(item, str) and item and len(item) <= 512 and item == item.strip()
                        and not any(ord(char) < 32 for char in item) for item in sessions)
                and len(set(sessions)) == len(sessions) and session in sessions)

    def _tls_native_random_attempt_blocked(self, session, source, user=None):
        if source == 'random' and self._tls_native_random_owned(session):
            return True
        return (isinstance(user, dict) and user.get('planned_proactive_source') == 'random'
                and self._tls_native_random_owned(user.get('umo')))

    def _tls_native_random_quarantine(self, user):
        """Inert audit copies preserve original states; never claim SDK drain."""
        from copy import deepcopy
        if not isinstance(user, dict) or not self._tls_native_random_owned(user.get('umo')):
            return False
        changed = False
        impulses = user.get('proactive_impulses')
        if isinstance(impulses, list):
            retained = []
            quarantined = user.get('_tls_native_random_quarantine')
            if quarantined is not None and not isinstance(quarantined, list):
                return False
            quarantined = list(quarantined or [])
            for row in impulses:
                state = str(row.get('state') or 'queued').lower() if isinstance(row, dict) else ''
                hold = (isinstance(row, dict) and (state == 'unknown'
                    or str(row.get('last_status') or '').lower() in ('unknown', 'delivery_unknown')
                    or row.get('delivery_unknown') is True))
                if (isinstance(row, dict) and row.get('source') == 'random'
                        and row.get('trigger_umo') in (None, '', user.get('umo'))
                        and (state in ('queued', 'deferred', 'unknown') or hold)):
                    copy = deepcopy(row)
                    copy['tls_owner_marker'] = self._TLS_NATIVE_RANDOM_MARKER
                    copy['tls_quarantine_reason'] = 'random_owner_handoff_no_replay'
                    copy['tls_handoff_hold'] = hold
                    if copy not in quarantined:
                        quarantined.append(copy)
                        changed = True
                    if state in ('queued', 'deferred', 'unknown'):
                        changed = True
                        continue
                retained.append(row)
            if changed:
                user['proactive_impulses'] = retained
                user['_tls_native_random_quarantine'] = quarantined
        if user.get('planned_proactive_source') == 'random':
            snapshot = {key: deepcopy(value) for key, value in user.items()
                        if key.startswith('planned_') or key in ('next_proactive_at',
                            'pending_proactive_send_retry', 'proactive_sending', 'proactive_sending_started_at')}
            archive = user.get('_tls_native_random_plan_quarantine')
            if archive is not None and not isinstance(archive, list):
                return changed
            archive = list(archive or [])
            if snapshot not in archive:
                archive.append(snapshot)
                user['_tls_native_random_plan_quarantine'] = archive
                changed = True
            retry = user.get('pending_proactive_send_retry')
            retry_state = retry.get('delivery_state', retry.get('last_status', retry.get('state', ''))) if isinstance(retry, dict) else ''
            uncertain = (user.get('proactive_sending') is True
                         or bool(user.get('proactive_sending_started_at'))
                         or str(user.get('planned_proactive_delivery_state') or '').lower() not in ('', 'fresh', 'deferred')
                         or str(retry_state or '').lower() not in ('', 'fresh', 'deferred', 'queued'))
            if not uncertain:
                self._clear_pending_proactive_plan(user)
                user['pending_proactive_send_retry'] = {}
                changed = True
        return changed
    def _queue_random_proactive_impulse(
        self,
        user: dict[str, Any],
        *,
        now: float,
        delay_hours: tuple[float, float],
    ) -> dict[str, Any] | None:
        if self._tls_native_random_owned(user.get('umo')):
            self._tls_native_random_quarantine(user)
            return None
        context = self._random_proactive_impulse_context(user, now=now)
        if not bool(context.get("allowed")):
            return None
        companion_profile = context.get("companion_profile")
        if isinstance(companion_profile, dict):
            minutes = _safe_int(companion_profile.get("sampling_minutes"), 10, 1, 60)
            bucket = sampling_bucket(now, minutes)
            last_sample = _safe_float(user.get("companion_last_sample_at"), 0)
            if user.get("companion_last_sample_bucket") == bucket or (last_sample > 0 and now - last_sample < minutes * 60):
                return None
            # Persist both misses and hits: the scheduler may check every minute.
            user["companion_last_sample_at"] = now
            user["companion_last_sample_bucket"] = bucket
            user["companion_last_sample_probability"] = companion_profile.get("probability", 0.0)
            user["companion_last_sample_stage"] = companion_profile.get("stage", "")
            if random.random() >= _safe_float(companion_profile.get("probability"), 0, 0, 1):
                return None
            raw_delay = companion_profile.get("delay_hours")
            if isinstance(raw_delay, (tuple, list)) and len(raw_delay) == 2:
                delay_hours = (max(0.05, float(raw_delay[0])), max(0.08, float(raw_delay[1])))
        reason = self._choose_planned_reason()
        if isinstance(companion_profile, dict) and companion_profile.get("is_night"):
            reason = "quiet_care"
        if bool(context.get("suggest_soft_reason")) and reason in {"check_in", "state_share"}:
            reason = "quiet_care"
        motive = self._choose_proactive_motive(reason, user)
        action = self._choose_action_for_reason(reason, user, motive=motive)
        action = self._maybe_upgrade_planned_message_action(
            action,
            reason=reason,
            user=user,
            motive=motive,
            planned_event=None,
        )
        scheduled = now + random.uniform(delay_hours[0] * 3600, delay_hours[1] * 3600)
        scheduled = self._move_timestamp_into_reason_window(scheduled, reason)
        topic = self._choose_proactive_topic(reason, user)
        emotion_adjustment = self._apply_emotion_to_planned_proactive(
            user,
            reason=reason,
            action=action,
            motive=motive,
            topic=topic,
            scheduled=scheduled,
            now=now,
        )
        reason = str(emotion_adjustment.get("reason") or reason)
        action = str(emotion_adjustment.get("action") or action)
        motive = _single_line(emotion_adjustment.get("motive"), 140) or motive
        topic = _single_line(emotion_adjustment.get("topic"), 60) or topic
        scheduled = _safe_float(emotion_adjustment.get("scheduled"), scheduled)
        if self._action_has_photo_text(action) and self._private_user_role(user) != "friend":
            photo_patch = self._photo_text_plan_field_patch(
                reason=reason,
                topic=topic,
                motive=motive,
            )
            topic = _single_line(photo_patch.get("topic"), 60) or topic
            motive = _single_line(photo_patch.get("motive"), 140) or motive
        if self._private_user_role(user) == "friend":
            friend_safe = self._sanitize_friend_proactive_plan_fields(
                user,
                reason=reason,
                action=action,
                topic=topic,
                motive=motive,
            )
            reason = friend_safe["reason"]
            action = friend_safe["action"]
            topic = friend_safe["topic"]
            motive = friend_safe["motive"]
        vague_seek_user = (
            str(action or "message") == "message"
            and self._is_vague_seek_user_motive(reason, action, motive, topic)
        )
        if vague_seek_user:
            scheduled = max(scheduled, now + random.uniform(1.5 * 3600, 3.5 * 3600))
            scheduled = self._move_timestamp_into_reason_window(scheduled, reason)
        active_span, grace_span = self._proactive_impulse_default_window_seconds(reason)
        impulse = self._build_proactive_impulse(
            user,
            reason=reason,
            action=action,
            motive=motive,
            topic=topic,
            source="random",
            window_start_at=scheduled,
            preferred_ts=scheduled,
            best_until_at=scheduled + active_span,
            expire_at=scheduled + active_span + grace_span,
        )
        if vague_seek_user:
            impulse["salience"] = min(_safe_float(impulse.get("salience"), 0.4), 0.34)
            impulse["urgency"] = min(_safe_float(impulse.get("urgency"), 0.3), 0.22)
        return self._queue_proactive_impulse(user, impulse)

    def _schedule_next_proactive(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
        delay_hours: tuple[float, float] | None = None,
    ):
        self._tls_native_random_quarantine(user)
        user_id = str(user.get("user_id") or user.get("id") or "")
        if not self._user_enabled_for_proactive(user_id, user):
            self._clear_pending_proactive_plan(user)
            return
        if self._proactive_generation_disabled(user):
            self._suspend_user_proactive_generation(user)
            return
        now = now or _now_ts()
        timer_event = self._get_active_llm_timer(user)
        if not (isinstance(timer_event, dict) and self._llm_timer_can_use_internal_scheduler(timer_event)):
            silence_reason_getter = getattr(self, "_friend_unanswered_silence_reason", None)
            silence_reason = silence_reason_getter(user, now=now) if callable(silence_reason_getter) else ""
            if silence_reason:
                self._block_friend_unanswered_pending_proactive(user, note=silence_reason, now=now)
                self._clear_pending_proactive_plan(user)
                logger.info(
                    "[PrivateCompanion] 次要用户连续未回应,停止安排普通主动: user=%s ignored=%s reason=%s",
                    _single_line(user_id, 40) or "unknown",
                    _safe_int(user.get("ignored_streak"), 0, 0),
                    _single_line(silence_reason, 120),
                )
                return
        if delay_hours is None:
            delay_hours = self._fallback_proactive_delay_hours(user, now=now)
        delay_factor = self._effective_proactive_float("delay_factor", 1.0, minimum=0.2, maximum=1.0)
        if delay_hours is not None and delay_factor < 1.0:
            delay_hours = (
                max(0.05, delay_hours[0] * delay_factor),
                max(0.08, delay_hours[1] * delay_factor),
            )
        intensity_factor = self._daily_intensity_factor(user)
        if delay_hours is not None and intensity_factor > 0:
            widen = max(0.85, min(1.8, 1.25 - intensity_factor * 0.45))
            delay_hours = (delay_hours[0] * widen, delay_hours[1] * widen)
        if delay_hours is not None:
            cycle_multiplier = self._cycle_proactive_frequency_profile()["private_interval_multiplier"]
            if cycle_multiplier > 1.0:
                delay_hours = (
                    delay_hours[0] * cycle_multiplier,
                    delay_hours[1] * cycle_multiplier,
                )
        planned_event = self._pick_best_planned_event(user, now)
        default_reason = (
            str(planned_event.get("reason") or "")
            if isinstance(planned_event, dict)
            else self._choose_planned_reason()
        ) or "check_in"
        if isinstance(timer_event, dict) and self._llm_timer_can_use_internal_scheduler(timer_event):
            timer_scheduled = _safe_float(timer_event.get("scheduled_ts"), 0)
            if timer_scheduled > now:
                user["next_proactive_at"] = timer_scheduled
                user["planned_proactive_reason"] = _single_line(timer_event.get("reason"), 40) or default_reason
                user["planned_proactive_action"] = _single_line(timer_event.get("action"), 24) or "message"
                user["planned_proactive_source"] = "timer"
                user["planned_proactive_motive"] = self._normalize_internal_motive_text(
                    _single_line(timer_event.get("motive"), 140)
                )
                user["planned_proactive_topic"] = _single_line(timer_event.get("topic"), 60) or (
                    _single_line(planned_event.get("topic"), 60)
                    if isinstance(planned_event, dict)
                    else self._choose_proactive_topic(default_reason, user)
                )
                user["planned_proactive_impulse_id"] = ""
                user["planned_proactive_window_start_at"] = timer_scheduled
                active_span, grace_span = self._proactive_impulse_default_window_seconds(user["planned_proactive_reason"])
                user["planned_proactive_best_until_at"] = timer_scheduled + active_span
                user["planned_proactive_expire_at"] = timer_scheduled + active_span + grace_span
                semantics = self._planned_proactive_semantics(user)
                user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
                user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
                user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
                user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
                self._set_planned_proactive_trigger(
                    user,
                    message_id=_single_line(timer_event.get("trigger_message_id"), 120),
                    umo=_single_line(timer_event.get("trigger_umo"), 160),
                    created_at=_safe_float(timer_event.get("trigger_ts"), 0),
                )
                user["planned_event_chain"] = (
                    []
                    if self._private_user_role(user) == "friend"
                    else list(timer_event.get("chain") or [])
                    if isinstance(timer_event.get("chain"), list)
                    else []
                )
                user["planned_opener_mode"] = ""
                user["planned_followup_kind"] = ""
                user["planned_proactive_quota_exempt"] = False
                item = self._record_proactive_candidate(
                    str(user.get("user_id") or user.get("id") or ""),
                    {
                        "source": "timer",
                        "reason": user["planned_proactive_reason"],
                        "action": user["planned_proactive_action"],
                        "scheduled_ts": timer_scheduled,
                        "topic": user["planned_proactive_topic"],
                        "motive": user["planned_proactive_motive"],
                        "score": 100,
                    },
                    status="accepted",
                    note="用户预约/定时主动",
                    user=user,
                )
                user["planned_candidate_id"] = item.get("id", "")
                return
        self._cleanup_proactive_impulses(user, now=now)
        self._queue_event_driven_proactive_impulses(user, now=now)
        active_impulses = [
            item
            for item in self._cleanup_proactive_impulses(user, now=now)
            if isinstance(item, dict) and str(item.get("state") or "queued") in {"queued", "deferred"}
        ]
        if not active_impulses:
            self._queue_random_proactive_impulse(user, now=now, delay_hours=delay_hours)
        if not self._materialize_best_proactive_impulse(user, now=now):
            self._clear_pending_proactive_plan(user)

    # ===== 区块2 调度层·续（原 proactive.py 2434-2694；已删除被 UserRestGateMixin MRO 遮蔽的 7 个 _user_rest_* 死方法，原 2284-2432）=====
    def _promote_earlier_daily_greeting_event(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> bool:
        if str(user.get("planned_proactive_source") or "") == "timer":
            return False
        current_next = _safe_float(user.get("next_proactive_at"), 0)
        if current_next <= 0:
            return False
        now = now or _now_ts()
        events = []
        events.append(self._pick_holiday_celebration_event(user, now))
        events.append(self._pick_course_reminder_event(user, now))
        if self.enable_daily_greetings:
            events.append(self._pick_daily_greeting_event(user, now))
        if bool(getattr(self, "enable_meal_care_proactive", True)):
            events.append(self._pick_meal_care_event(user, now=now))
        valid_events = [item for item in events if isinstance(item, dict)]
        if not valid_events:
            return False
        event = min(valid_events, key=lambda item: self._timestamp_from_story_event(item, str(item.get("reason") or "check_in")))
        reason = str(event.get("reason") or "")
        special_calendar_event = reason in {"holiday_celebration", "course_reminder"}
        if not (special_calendar_event or self._is_sticky_greeting_reason(reason) or bool(event.get("_daily_meal_care"))):
            return False
        scheduled = self._timestamp_from_story_event(event, reason)
        if special_calendar_event:
            rest_until = self._proactive_rest_block_until(user, now=now, reason=reason, source=reason)
            scheduled = max(scheduled, rest_until)
            if scheduled >= _safe_float(event.get("expire_at"), 0):
                return False
        if scheduled <= 0 or scheduled >= current_next - 60:
            return False
        action = str(event.get("action") or "message")
        motive = _single_line(event.get("motive"), 120) or self._choose_proactive_motive(
            reason,
            user,
            action=action,
            planned_event=event,
        )
        self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = scheduled
        user["planned_proactive_reason"] = reason
        user["planned_proactive_action"] = action
        user["planned_proactive_source"] = (
            reason
            if special_calendar_event
            else "daily_greeting"
            if event.get("_daily_greeting")
            else "meal_care"
            if event.get("_daily_meal_care")
            else "event"
        )
        user["planned_proactive_motive"] = motive
        user["planned_proactive_topic"] = _single_line(event.get("topic"), 60)
        user["planned_proactive_impulse_id"] = ""
        active_span, grace_span = self._proactive_impulse_default_window_seconds(reason)
        if special_calendar_event:
            user["planned_proactive_window_start_at"] = _safe_float(event.get("window_start_at"), scheduled)
            user["planned_proactive_best_until_at"] = max(scheduled, _safe_float(event.get("best_until_at"), scheduled))
            user["planned_proactive_expire_at"] = _safe_float(event.get("expire_at"), scheduled)
        else:
            user["planned_proactive_window_start_at"] = scheduled
            user["planned_proactive_best_until_at"] = scheduled + active_span
            user["planned_proactive_expire_at"] = scheduled + active_span + grace_span
        semantics = self._planned_proactive_semantics(user)
        user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
        user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
        user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
        user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
        self._clear_planned_proactive_trigger(user)
        user["planned_event_chain"] = [] if self._private_user_role(user) == "friend" else (
            list(event.get("chain") or []) if isinstance(event.get("chain"), list) else []
        )
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = False if special_calendar_event else bool(event.get("_free_screen_peek"))
        context_key = _single_line(event.get("context_key"), 60)
        context = event.get("context")
        if context_key and isinstance(context, dict):
            user[context_key] = dict(context)
        return True

    def _is_proactive_plan_stale(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        next_at = _safe_float(user.get("next_proactive_at"), 0)
        if next_at <= 0:
            return False
        check_now = _now_ts() if now is None else now
        return check_now - next_at > self.max_proactive_plan_lag_minutes * 60

    def _reset_planned_proactive_delivery_state(self, user: dict[str, Any]) -> None:
        user["planned_proactive_origin_at"] = 0
        user["planned_proactive_origin_key"] = ""
        user["planned_proactive_freshness"] = ""
        user["planned_proactive_delivery_state"] = ""

    def _clear_pending_proactive_plan(self, user: dict[str, Any]) -> None:
        user["next_proactive_at"] = 0
        user["planned_proactive_reason"] = ""
        user["planned_proactive_action"] = ""
        user["planned_proactive_source"] = ""
        user["planned_proactive_motive"] = ""
        user["planned_proactive_topic"] = ""
        user["planned_proactive_impulse_id"] = ""
        user["planned_proactive_window_start_at"] = 0
        user["planned_proactive_best_until_at"] = 0
        user["planned_proactive_expire_at"] = 0
        self._reset_planned_proactive_delivery_state(user)
        user["planned_proactive_semantic_kind"] = ""
        user["planned_proactive_anchor_type"] = ""
        user["planned_proactive_semantic_score"] = 0
        user["planned_proactive_semantic_note"] = ""
        user["planned_proactive_model_judge_signature"] = ""
        user["planned_proactive_model_judge_result"] = {}
        user["planned_proactive_model_judge_at"] = 0
        user["planned_event_chain"] = []
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = False
        user["planned_candidate_id"] = ""
        self._clear_planned_proactive_trigger(user)

    def _maintenance_failure_cooldown_seconds(self, label: str) -> float:
        if label in {"日常状态", "今日日程", "当前细化", "日记", "创作推进"}:
            return 30 * 60
        return 5 * 60

    def _maintenance_task_blocked_by_failure(self, label: str, *, now: float | None = None) -> str:
        state = getattr(self, "_maintenance_failure_cooldowns", None)
        if not isinstance(state, dict):
            return ""
        item = state.get(label)
        if not isinstance(item, dict):
            return ""
        check_now = _now_ts() if now is None else now
        until = _safe_float(item.get("until"), 0, 0)
        if until <= check_now:
            state.pop(label, None)
            return ""
        error = _single_line(item.get("error"), 120)
        return f"{label} 失败冷却中（{self._format_elapsed(until - check_now)}后重试" + (f"，上次错误：{error}" if error else "") + "）"

    def _record_maintenance_task_failure(self, label: str, exc: Exception) -> None:
        state = getattr(self, "_maintenance_failure_cooldowns", None)
        if not isinstance(state, dict):
            state = {}
            self._maintenance_failure_cooldowns = state
        now = _now_ts()
        state[label] = {
            "until": now + self._maintenance_failure_cooldown_seconds(label),
            "error": _single_line(exc, 180),
            "failed_at": now,
        }

    def _clear_maintenance_task_failure(self, label: str) -> None:
        state = getattr(self, "_maintenance_failure_cooldowns", None)
        if isinstance(state, dict):
            state.pop(label, None)

    async def _scheduler_loop(self):
        while not self._stop_event.is_set():
            try:
                timeout = self._next_scheduler_timeout()
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                await self._tick()
                maintenance_tasks = (
                    ("日常状态", self._ensure_daily_state),
                    ("今日日程", self._ensure_daily_plan),
                    ("当前细化", self._ensure_detail_enhancement),
                    ("当前在线感", self._ensure_current_detail_presence_status),
                    ("日记", self._ensure_daily_diary),
                    ("每日穿搭", self._ensure_daily_outfit_photo),
                    ("创作推进", self._maybe_advance_creative_projects),
                    ("个人目标", self._maybe_settle_personal_goals),
                    ("备忘便签", self._maybe_process_memo_notes),
                    ("环境突变", self._maybe_refresh_environment_change),
                    ("余额感知", self._maybe_refresh_balance_awareness),
                    ("被动注入缓存", self._refresh_passive_injection_cache),
                )
                if self._proactive_generation_disabled():
                    passive_labels = {"日常状态", "今日日程", "当前细化", "当前在线感", "日记", "被动注入缓存"}
                    maintenance_tasks = tuple(item for item in maintenance_tasks if item[0] in passive_labels)
                for label, task_factory in maintenance_tasks:
                    try:
                        if self._maintenance_task_blocked_by_failure(label):
                            continue
                        await task_factory()
                        self._clear_maintenance_task_failure(label)
                    except Exception as exc:
                        self._record_maintenance_task_failure(label, exc)
                        logger.warning("[PrivateCompanion] 主动循环维护步骤失败,已跳过: %s error=%s", label, _single_line(exc, 160))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[PrivateCompanion] 主动消息循环异常: {e}", exc_info=True)

    async def _kick_proactive_loop_once(self) -> None:
        try:
            await self._tick()
            maintenance_tasks = (
                ("日常状态", self._ensure_daily_state),
                ("今日日程", self._ensure_daily_plan),
                ("当前细化", self._ensure_detail_enhancement),
                ("当前在线感", self._ensure_current_detail_presence_status),
                ("日记", self._ensure_daily_diary),
                ("每日穿搭", self._ensure_daily_outfit_photo),
                ("创作推进", self._maybe_advance_creative_projects),
                ("个人目标", self._maybe_settle_personal_goals),
                ("备忘便签", self._maybe_process_memo_notes),
                ("环境突变", self._maybe_refresh_environment_change),
                ("余额感知", self._maybe_refresh_balance_awareness),
                ("被动注入缓存", self._refresh_passive_injection_cache),
            )
            if self._proactive_generation_disabled():
                passive_labels = {"日常状态", "今日日程", "当前细化", "当前在线感", "日记", "被动注入缓存"}
                maintenance_tasks = tuple(item for item in maintenance_tasks if item[0] in passive_labels)
            for label, task_factory in maintenance_tasks:
                try:
                    if self._maintenance_task_blocked_by_failure(label):
                        continue
                    await task_factory()
                    self._clear_maintenance_task_failure(label)
                except Exception as exc:
                    self._record_maintenance_task_failure(label, exc)
                    logger.warning("[PrivateCompanion] 主动链即时维护步骤失败,已跳过: %s error=%s", label, _single_line(exc, 160))
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 主动链即时唤醒失败: {e}", exc_info=True)

    def _next_scheduler_timeout(self) -> float:
        base = max(30.0, float(self.check_interval_seconds))
        now = _now_ts()
        nearest_due_in: float | None = None
        users = self.data.get("users", {})
        if isinstance(users, dict):
            for raw_user in users.values():
                if not isinstance(raw_user, dict):
                    continue
                if not raw_user.get("umo"):
                    continue
                next_at = _safe_float(raw_user.get("next_proactive_at"), 0)
                if next_at <= 0:
                    continue
                due_in = max(0.0, next_at - now)
                if nearest_due_in is None or due_in < nearest_due_in:
                    nearest_due_in = due_in

        if nearest_due_in is None:
            detail_due_in = self._next_detail_due_in_seconds(now)
            if detail_due_in is not None:
                nearest_due_in = detail_due_in

        memo_due_getter = getattr(self, "_next_memo_due_in_seconds", None)
        memo_due_in = memo_due_getter(now) if callable(memo_due_getter) else None
        if memo_due_in is not None and (nearest_due_in is None or memo_due_in < nearest_due_in):
            nearest_due_in = memo_due_in
        elif self.enable_detail_enhancement:
            detail_due_in = self._next_detail_due_in_seconds(now)
            if detail_due_in is not None and detail_due_in < nearest_due_in:
                nearest_due_in = detail_due_in

        if nearest_due_in is None:
            return max(35.0, min(base, random.uniform(base * 0.55, base * 0.95)))
        if nearest_due_in <= 20:
            return max(3.0, nearest_due_in + random.uniform(0.8, 3.2))
        if nearest_due_in <= 90:
            return max(8.0, nearest_due_in * random.uniform(0.35, 0.7))
        if nearest_due_in <= 6 * 60:
            return max(20.0, min(base * 0.5, nearest_due_in * random.uniform(0.18, 0.42)))
        return max(35.0, min(base, random.uniform(base * 0.55, base * 0.95)))

    # ===== 区块3-6 决策层（原 proactive_engine.py 245-7893 全部方法，原决策 Mixin 已并入本类）=====
    def _proactive_candidate_pool(self) -> list[dict[str, Any]]:
        raw = self.data.setdefault("proactive_candidate_pool", [])
        if not isinstance(raw, list):
            raw = []
            self.data["proactive_candidate_pool"] = raw
        return raw

    def _pending_proactive_candidate_limit(self, user: dict[str, Any] | None = None) -> int:
        if not isinstance(user, dict):
            return 200
        override = _safe_int(user.get("pending_proactive_candidate_limit"), -1, -1)
        return override if override > 0 else 200

    def _candidate_user_id(self, item: dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""
        return _single_line(item.get("user_id") or item.get("target_user_id") or item.get("id"), 40)

    @staticmethod
    def _pending_candidate_status(status: str) -> bool:
        normalized = _single_line(status, 24).lower()
        return normalized in {"accepted", "deferred", "queued", "pending", "unknown", ""}

    @staticmethod
    def _candidate_repeat_count_limit(status: str = "") -> int:
        normalized = _single_line(status, 24).lower()
        if normalized in {"accepted", "deferred", "queued", "pending", "unknown", ""}:
            return 12
        if normalized == "sent":
            return 8
        return 6

    def _normalize_candidate_repeat_count(self, item: dict[str, Any]) -> int:
        if not isinstance(item, dict):
            return 1
        limit = self._candidate_repeat_count_limit(str(item.get("status") or ""))
        count = _safe_int(item.get("repeat_count"), 1, 1)
        normalized = max(1, min(limit, count))
        if count != normalized:
            item["repeat_count"] = normalized
            item["repeat_count_capped"] = True
        return normalized

    def _planned_candidate_ids_by_user(self) -> dict[str, str]:
        users = self.data.get("users") if isinstance(self.data.get("users"), dict) else {}
        planned: dict[str, str] = {}
        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            candidate_id = _single_line(user.get("planned_candidate_id"), 40)
            if candidate_id:
                planned[str(user_id)] = candidate_id
        return planned

    def _trim_proactive_candidate_total(self, items: list[dict[str, Any]], *, limit: int = 600) -> list[dict[str, Any]]:
        if len(items) <= limit:
            return items
        planned_ids = set(self._planned_candidate_ids_by_user().values())
        protected = [
            item for item in items
            if _single_line(item.get("id"), 40) in planned_ids
        ]
        protected_ids = {_single_line(item.get("id"), 40) for item in protected}
        remaining = [
            item for item in items
            if _single_line(item.get("id"), 40) not in protected_ids
        ]
        keep_count = max(0, limit - len(protected))
        trimmed = remaining[-keep_count:] if keep_count else []
        result = protected + trimmed
        result.sort(
            key=lambda item: max(
                _safe_float(item.get("updated_ts"), 0),
                _safe_float(item.get("created_ts"), 0),
                _safe_float(item.get("scheduled_ts"), 0),
                _safe_float(item.get("last_seen_ts"), 0),
            )
        )
        return result[-limit:]

    def _candidate_trim_priority(self, item: dict[str, Any], *, planned_candidate_id: str = "") -> tuple[int, int, int, float]:
        status = _single_line(item.get("status"), 24).lower()
        note = _single_line(item.get("note"), 160)
        item_id = _single_line(item.get("id"), 40)
        updated = _safe_float(item.get("updated_ts"), 0)
        created = _safe_float(item.get("created_ts"), 0)
        scheduled = _safe_float(item.get("scheduled_ts"), 0)
        last_seen = _safe_float(item.get("last_seen_ts"), 0)
        repeat_count = _safe_int(item.get("repeat_count"), 1, 1)
        protected = item_id and planned_candidate_id and item_id == planned_candidate_id
        status_rank = {
            "failed": 0,
            "cancelled": 1,
            "dropped": 2,
            "blocked": 3,
            "deferred": 4,
            "accepted": 6,
        }.get(status, 5)
        note_penalty = 0 if note else 1
        freshness = max(updated, scheduled, last_seen, created)
        return (1 if protected else 0, status_rank, repeat_count + note_penalty, freshness)

    def _apply_per_user_pending_candidate_cap(
        self,
        items: list[dict[str, Any]],
        *,
        pending_cap: int | None = None,
        target_user_id: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        users = self.data.get("users") if isinstance(self.data.get("users"), dict) else {}
        planned_ids = self._planned_candidate_ids_by_user()
        grouped: dict[str, list[dict[str, Any]]] = {}
        passthrough: list[dict[str, Any]] = []
        removed = 0
        target = str(target_user_id or "").strip()
        for item in items:
            if not isinstance(item, dict):
                continue
            user_id = self._candidate_user_id(item)
            if not user_id:
                passthrough.append(item)
                continue
            if target and user_id != target:
                passthrough.append(item)
                continue
            grouped.setdefault(user_id, []).append(item)
        kept: list[dict[str, Any]] = list(passthrough)
        for user_id, user_items in grouped.items():
            user = users.get(user_id) if isinstance(users, dict) else None
            limit = pending_cap if pending_cap is not None else self._pending_proactive_candidate_limit(user if isinstance(user, dict) else None)
            if limit <= 0:
                kept.extend(user_items)
                continue
            pending_items = [item for item in user_items if self._pending_candidate_status(str(item.get("status") or ""))]
            sent_items = [item for item in user_items if not self._pending_candidate_status(str(item.get("status") or ""))]
            if len(pending_items) > limit:
                planned_candidate_id = planned_ids.get(user_id, "")
                pending_items.sort(
                    key=lambda item: self._candidate_trim_priority(item, planned_candidate_id=planned_candidate_id),
                    reverse=True,
                )
                trimmed_pending = pending_items[:limit]
                removed += max(0, len(pending_items) - len(trimmed_pending))
                pending_items = sorted(
                    trimmed_pending,
                    key=lambda item: max(
                        _safe_float(item.get("updated_ts"), 0),
                        _safe_float(item.get("created_ts"), 0),
                        _safe_float(item.get("scheduled_ts"), 0),
                    ),
                )
            kept.extend(sent_items)
            kept.extend(pending_items)
        kept.sort(
            key=lambda item: max(
                _safe_float(item.get("updated_ts"), 0),
                _safe_float(item.get("created_ts"), 0),
                _safe_float(item.get("scheduled_ts"), 0),
                _safe_float(item.get("last_seen_ts"), 0),
            )
        )
        return kept, removed

    def _shrink_user_proactive_candidates(
        self,
        user_id: str,
        *,
        pending_cap: int | None = None,
        note: str = "",
    ) -> int:
        target_user_id = str(user_id or "").strip()
        if not target_user_id:
            return 0
        current = [item for item in self._proactive_candidate_pool() if isinstance(item, dict)]
        kept, removed = self._apply_per_user_pending_candidate_cap(
            current,
            pending_cap=pending_cap,
            target_user_id=target_user_id,
        )
        if removed > 0:
            self.data["proactive_candidate_pool"] = kept
            logger.info(
                "[PrivateCompanion] 主动候选自动收缩: user=%s removed=%s cap=%s note=%s",
                target_user_id,
                removed,
                pending_cap or "default",
                _single_line(note, 120),
            )
        return removed

    def _cleanup_proactive_candidate_pool(self, *, now: float | None = None) -> list[dict[str, Any]]:
        now = now or _now_ts()
        kept: list[dict[str, Any]] = []
        for item in self._proactive_candidate_pool():
            if not isinstance(item, dict):
                continue
            self._normalize_candidate_repeat_count(item)
            created = _safe_float(item.get("created_ts"), 0)
            scheduled = _safe_float(item.get("scheduled_ts"), 0)
            status = str(item.get("status") or "")
            ttl = 36 * 3600 if status in {"accepted", "sent"} else 18 * 3600
            anchor = max(created, scheduled)
            if anchor > 0 and now - anchor <= ttl:
                kept.append(item)
        kept, _ = self._apply_per_user_pending_candidate_cap(kept)
        self.data["proactive_candidate_pool"] = self._trim_proactive_candidate_total(kept, limit=600)
        return self.data["proactive_candidate_pool"]

    def _proactive_impulse_pool(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        raw = user.get("proactive_impulses")
        if not isinstance(raw, list):
            raw = []
            user["proactive_impulses"] = raw
        return raw

    def _cleanup_proactive_impulses(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        check_now = _now_ts() if now is None else now
        kept: list[dict[str, Any]] = []
        for item in self._proactive_impulse_pool(user):
            if not isinstance(item, dict):
                continue
            created = _safe_float(item.get("created_ts"), 0)
            updated = _safe_float(item.get("updated_ts"), created)
            state = str(item.get("state") or "queued").strip().lower()
            expire_at = _safe_float(item.get("expire_at"), 0)
            if state in {"sent", "blocked", "cancelled", "dropped"}:
                if max(created, updated, expire_at) > 0 and check_now - max(created, updated, expire_at) <= 12 * 3600:
                    kept.append(item)
                continue
            if expire_at > 0 and check_now - expire_at > 2 * 3600:
                continue
            if created > 0 and check_now - created > 48 * 3600:
                continue
            kept.append(item)
        user["proactive_impulses"] = kept[-16:]
        return user["proactive_impulses"]

    def _user_asks_bot_current_state_or_activity(self, text: str) -> bool:
        raw = _single_line(text, 120)
        if not raw:
            return False
        if raw.lstrip().startswith(("/", "／", "!", "！", "#", "＃")):
            return False
        compact = re.sub(r"[\s,，。.!！?？~～…·、；;：:（）()【】\[\]\"'“”‘’]+", "", raw)
        if not compact or len(compact) > 80:
            return False
        if re.search(r"(?:我|俺|咱|我们)(?:现在|这会儿|刚刚|刚才)?在?(?:干嘛|干啥|做什么|做啥|忙什么|忙啥)", compact):
            return False
        tech_status_words = ("插件", "系统", "接口", "API", "api", "配置", "页面", "排障", "日志", "服务", "连接", "模型", "任务", "进程")
        if "状态" in compact and any(word in raw for word in tech_status_words):
            return False
        direct_patterns = (
            r"(?:你|bot|机器人)?(?:现在|这会儿|这时候|刚才|今天)?在?(?:干嘛|干啥|做什么|做啥|忙什么|忙啥)(?:呢|呀|啊|吗|嘛|没)?$",
            r"(?:你|bot|机器人)?(?:现在|这会儿|今天)?在(?:上课|上班|睡觉|休息|吃饭|忙|摸鱼|干活|写作业|看书)(?:吗|嘛|没|呢)?$",
            r"(?:你|bot|机器人)(?:现在|这会儿|今天)?(?:状态|情况)?(?:怎么样|咋样|如何|还好吗|还好不|累不累|困不困|忙不忙|饿不饿)$",
            r"(?:你|bot|机器人)(?:现在|这会儿)?(?:什么状态|啥状态)$",
        )
        return any(re.fullmatch(pattern, compact, flags=re.I) for pattern in direct_patterns)

    def _proactive_item_is_state_share_for_current_status_question(self, item: dict[str, Any] | None) -> bool:
        if not isinstance(item, dict):
            return False
        reason = self._normalize_legacy_proactive_text(item.get("reason") or item.get("planned_proactive_reason"), limit=40)
        source = self._normalize_legacy_proactive_text(item.get("source") or item.get("planned_proactive_source"), limit=40)
        if source in {"timer", "troubleshooting", "simulation"}:
            return False
        if reason in {"group_share", "news_share", "bili_video_share", "web_exploration_share", "creative_share", "important_date_share"}:
            return False
        if reason in {"state_share", "activity_share", "background_schedule", "diary_share"}:
            return True
        text = " ".join(
            _single_line(item.get(key), 120)
            for key in (
                "topic",
                "planned_proactive_topic",
                "motive",
                "planned_proactive_motive",
                "why",
                "scene",
                "impulse",
            )
            if _single_line(item.get(key), 120)
        )
        if not text:
            return False
        state_tokens = (
            "当前日程", "现在日程", "当前细化", "正在", "刚好在",
            "上课", "上班", "摸鱼", "休息", "吃饭", "路上", "通勤", "回家", "小日常",
            "今天的小事", "刚看到", "刚听到", "刚经历",
        )
        return reason in {"check_in", "quiet_care"} and any(token in text for token in state_tokens)

    def _clear_state_share_proactive_after_user_status_question(
        self,
        user: dict[str, Any],
        *,
        user_id: str = "",
        text: str = "",
        now: float | None = None,
    ) -> bool:
        if not isinstance(user, dict) or not self._user_asks_bot_current_state_or_activity(text):
            return False
        check_now = _now_ts() if now is None else now
        note = "用户已询问当前状态，状态分享念头已由被动回复承接"
        changed = False
        planned_item = {
            "reason": user.get("planned_proactive_reason"),
            "action": user.get("planned_proactive_action"),
            "source": user.get("planned_proactive_source"),
            "topic": user.get("planned_proactive_topic"),
            "motive": user.get("planned_proactive_motive"),
        }
        if _safe_float(user.get("next_proactive_at"), 0) > 0 and self._proactive_item_is_state_share_for_current_status_question(planned_item):
            self._mark_planned_candidate_status(user, "blocked", note)
            self._clear_pending_proactive_plan(user)
            changed = True
        for impulse in self._cleanup_proactive_impulses(user, now=check_now):
            if not isinstance(impulse, dict):
                continue
            state = _single_line(impulse.get("state") or "queued", 24).lower()
            if state not in {"queued", "deferred", "pending", ""}:
                continue
            if not self._proactive_item_is_state_share_for_current_status_question(impulse):
                continue
            impulse["state"] = "blocked"
            impulse["last_status"] = "blocked"
            impulse["last_note"] = note
            impulse["updated_ts"] = check_now
            changed = True
        target_user_id = _single_line(user_id or user.get("user_id") or user.get("id"), 40)
        if target_user_id:
            for candidate in self._cleanup_proactive_candidate_pool(now=check_now):
                if not isinstance(candidate, dict):
                    continue
                if self._candidate_user_id(candidate) != target_user_id:
                    continue
                status = _single_line(candidate.get("status"), 24).lower()
                if not self._pending_candidate_status(status):
                    continue
                if not self._proactive_item_is_state_share_for_current_status_question(candidate):
                    continue
                candidate["status"] = "blocked"
                candidate["note"] = note
                candidate["updated_ts"] = check_now
                changed = True
        if changed:
            logger.info(
                "[PrivateCompanion] 用户已询问当前状态,已清理状态分享主动念头: user=%s text=%s",
                target_user_id or "unknown",
                _single_line(text, 80),
            )
        return changed

    def _friend_proactive_candidate_leaks_owner_environment(self, user: dict[str, Any], candidate: dict[str, Any]) -> bool:
        if not isinstance(user, dict) or self._private_user_role(user) != "friend" or not isinstance(candidate, dict):
            return False
        reason = self._normalize_legacy_proactive_text(candidate.get("reason"), limit=40)
        if reason not in {"activity_share", "diary_share", "background_schedule", "state_share", "check_in", "quiet_care"}:
            return False
        text = " ".join(
            _single_line(candidate.get(key), 180)
            for key in ("topic", "motive", "why", "scene", "impulse", "status")
            if _single_line(candidate.get(key), 180)
        )
        if not text:
            return False
        weather_tokens = (
            "天气", "气温", "温度", "降雨", "下雨", "阵雨", "小雨", "中雨", "大雨",
            "暴雨", "雷雨", "雷暴", "晴", "阳光", "多云", "阴天", "晚霞", "风",
            "外面在下雨", "天色",
        )
        location_tokens = (
            "当前位置", "当前地点", "所在城市", "住处", "住址", "地址", "小区", "街道",
            "校区", "宿舍", "家里", "学校", "工作地点", "路上", "通勤",
        )
        return any(token in text for token in weather_tokens) or any(token in text for token in location_tokens)

    def _proactive_impulse_signature(self, item: dict[str, Any]) -> str:
        if str(item.get("reason") or "") in {"holiday_celebration", "course_reminder"}:
            context = item.get("context") if isinstance(item.get("context"), dict) else {}
            event_key = str(context.get("event_key") or "")
            if event_key:
                return "special:" + hashlib.sha256(event_key.encode()).hexdigest()
        return self._proactive_topic_signature(
            item.get("reason"),
            item.get("source"),
            item.get("topic"),
            item.get("motive"),
        )

    def _proactive_impulse_default_window_seconds(self, reason: str) -> tuple[float, float]:
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            return 70 * 60.0, 35 * 60.0
        if reason in {"group_share", "news_share", "bili_video_share", "web_exploration_share", "environment_change"}:
            return 45 * 60.0, 60 * 60.0
        if reason in {"quiet_care", "check_in", "state_share"}:
            return 55 * 60.0, 80 * 60.0
        return 50 * 60.0, 70 * 60.0

    def _event_time_window_bounds(
        self,
        event: dict[str, Any],
        *,
        reason: str,
        now: float | None = None,
    ) -> tuple[float, float, float, float]:
        check_now = _now_ts() if now is None else now
        preferred_ts = _safe_float(event.get("_scheduled_ts"), 0)
        start_ts = preferred_ts
        end_ts = 0.0
        window = str(event.get("window") or "").strip()
        if window:
            start_minute, end_minute = self._parse_window_minutes(window)
            if start_minute is not None and end_minute is not None:
                when = self._environment_fromtimestamp(check_now)
                date_text = str(event.get("date") or "").strip()
                try:
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
                        base_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                    else:
                        base_date = when.date()
                except Exception:
                    base_date = when.date()
                tzinfo = when.tzinfo
                start_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=tzinfo) + timedelta(minutes=start_minute)
                end_dt = datetime.combine(base_date, datetime.min.time(), tzinfo=tzinfo) + timedelta(minutes=end_minute)
                start_ts = start_dt.timestamp()
                end_ts = end_dt.timestamp()
        if preferred_ts <= 0:
            preferred_ts = start_ts if start_ts > 0 else check_now + 60
        if start_ts <= 0:
            start_ts = preferred_ts
        active_span, grace_span = self._proactive_impulse_default_window_seconds(reason)
        if end_ts <= 0:
            end_ts = max(start_ts + 60.0, preferred_ts + active_span)
        expire_at = max(end_ts + grace_span, preferred_ts + 5 * 60.0)
        return start_ts, preferred_ts, end_ts, expire_at

    def _build_proactive_impulse(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
        topic: str,
        source: str,
        window_start_at: float,
        preferred_ts: float,
        best_until_at: float,
        expire_at: float,
        chain: list[dict[str, Any]] | None = None,
        trigger_message_id: str = "",
        trigger_umo: str = "",
        trigger_ts: float = 0,
        quota_exempt: bool = False,
        context_key: str = "",
        context: Any = None,
        opener_mode: str = "",
        followup_kind: str = "",
    ) -> dict[str, Any]:
        role = self._private_user_role(user)
        impulse_reason = _single_line(reason, 40) or "check_in"
        impulse_action = _single_line(action, 40) or "message"
        impulse_topic = _single_line(topic, 80)
        impulse_motive = self._normalize_internal_motive_text(_single_line(motive, 180))
        salience = 0.54
        warmth = 0.46
        urgency = 0.38
        if source in {"followup", "timer", "pending_followup"}:
            salience += 0.2
            urgency += 0.12
        elif source in {"story", "event"}:
            salience += 0.12
        elif source == "random":
            warmth += 0.06
        if impulse_reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            warmth += 0.1
            urgency += 0.08
        if impulse_reason in {"quiet_care", "important_date_share"}:
            warmth += 0.16
        if role == "friend":
            warmth = max(0.18, warmth - 0.08)
            urgency = max(0.16, urgency - 0.04)
        decay_per_hour = 0.06 if source in {"followup", "timer"} else 0.1
        persona_alignment = self._proactive_persona_alignment(
            user,
            reason=impulse_reason,
            action=impulse_action,
            motive=impulse_motive,
            topic=impulse_topic,
            source=source,
        )
        semantics = self._proactive_candidate_semantics(
            user,
            reason=impulse_reason,
            action=impulse_action,
            motive=impulse_motive,
            topic=impulse_topic,
            source=source,
            context=context,
            chain=chain,
            trigger_message_id=trigger_message_id,
            trigger_ts=trigger_ts,
        )
        return {
            "id": uuid.uuid4().hex[:12],
            "created_ts": _now_ts(),
            "updated_ts": _now_ts(),
            "state": "queued",
            "source": _single_line(source, 40) or "random",
            "reason": impulse_reason,
            "action": impulse_action,
            "topic": impulse_topic,
            "motive": impulse_motive,
            "window_start_at": max(0.0, float(window_start_at or preferred_ts or _now_ts())),
            "preferred_ts": max(0.0, float(preferred_ts or window_start_at or _now_ts())),
            "best_until_at": max(float(best_until_at or preferred_ts or _now_ts()), float(window_start_at or 0.0)),
            "expire_at": max(float(expire_at or best_until_at or preferred_ts or _now_ts()), float(best_until_at or 0.0)),
            "salience": max(0.0, min(1.0, salience)),
            "warmth": max(0.0, min(1.0, warmth)),
            "urgency": max(0.0, min(1.0, urgency)),
            "decay_per_hour": max(0.01, min(0.5, decay_per_hour)),
            "persona_fit": max(0.0, min(1.0, _safe_float(persona_alignment.get("score"), 0.5))),
            "persona_fit_note": _single_line(persona_alignment.get("note"), 160),
            "persona_fit_blocker": bool(persona_alignment.get("blocker")),
            "semantic_kind": _single_line(semantics.get("kind"), 40),
            "semantic_anchor_type": _single_line(semantics.get("anchor_type"), 40),
            "semantic_score": max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))),
            "semantic_anchor_score": max(0.0, min(1.0, _safe_float(semantics.get("anchor_score"), 0.5))),
            "semantic_pressure": max(0.0, min(1.0, _safe_float(semantics.get("pressure"), 0.4))),
            "semantic_risk": max(0.0, min(1.0, _safe_float(semantics.get("risk"), 0.0))),
            "semantic_note": _single_line(semantics.get("note"), 180),
            "semantic_need_layer": _single_line(semantics.get("need_layer"), 40),
            "semantic_need_drive": _single_line(semantics.get("need_drive"), 80),
            "semantic_need_note": _single_line(semantics.get("need_note"), 120),
            "semantic_need_score_bias": _safe_float(semantics.get("need_score_bias"), 0.0),
            "semantic_need_pressure_bias": _safe_float(semantics.get("need_pressure_bias"), 0.0),
            "semantic_blocker": bool(semantics.get("blocker")),
            "signature": self._proactive_topic_signature(impulse_reason, source, impulse_topic, impulse_motive),
            "chain": [] if role == "friend" else [dict(item) for item in (chain or []) if isinstance(item, dict)],
            "trigger_message_id": _single_line(trigger_message_id, 120),
            "trigger_umo": _single_line(trigger_umo, 160),
            "trigger_ts": _safe_float(trigger_ts, 0),
            "quota_exempt": bool(quota_exempt),
            "context_key": _single_line(context_key, 60),
            "context": dict(context) if isinstance(context, dict) else context,
            "opener_mode": _single_line(opener_mode, 24),
            "followup_kind": _single_line(followup_kind, 32),
        }

    def _proactive_impulse_orchestration_priority(self, impulse: dict[str, Any]) -> int:
        source = _single_line(impulse.get("source"), 40).lower()
        reason = self._normalize_legacy_proactive_text(impulse.get("reason"), limit=40)
        priorities = {
            "timer": 100,
            "pending_followup": 92,
            "followup": 88,
            "birthday_celebration": 86,
            "daily_greeting": 72,
            "meal_care": 78,
            "balance": 82,
            "birthday_curiosity": 68,
            "habit": 64,
            "state": 60,
            "story": 58,
            "event": 56,
            "creative": 54,
            "random": 20,
        }
        priority = priorities.get(source, 48)
        if reason in {"birthday_celebration", "birthday_eve_hint", "birthday_makeup", "important_date_share"}:
            priority = max(priority, 86)
        elif reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            priority = max(priority, 72)
        elif reason == "quiet_care":
            priority = max(priority, 74)
        return priority

    def _proactive_impulse_content_signature(self, impulse: dict[str, Any]) -> str:
        return self._proactive_topic_signature(
            impulse.get("topic"),
            impulse.get("motive"),
        )

    def _merge_proactive_impulse_timing(self, target: dict[str, Any], incoming: dict[str, Any]) -> None:
        target_start = _safe_float(target.get("window_start_at"), 0)
        incoming_start = _safe_float(incoming.get("window_start_at"), 0)
        target_preferred = _safe_float(target.get("preferred_ts"), 0)
        incoming_preferred = _safe_float(incoming.get("preferred_ts"), 0)
        if target_start <= 0 or (incoming_start > 0 and incoming_start < target_start):
            target["window_start_at"] = incoming_start
        if target_preferred <= 0 or (incoming_preferred > 0 and incoming_preferred < target_preferred):
            target["preferred_ts"] = incoming_preferred
        target["best_until_at"] = max(
            _safe_float(target.get("best_until_at"), 0),
            _safe_float(incoming.get("best_until_at"), 0),
        )
        target["expire_at"] = max(
            _safe_float(target.get("expire_at"), 0),
            _safe_float(incoming.get("expire_at"), 0),
        )

    def _replace_proactive_impulse_with_higher_priority(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        existing_id = _single_line(existing.get("id"), 20) or uuid.uuid4().hex[:12]
        existing_created = _safe_float(existing.get("created_ts"), _now_ts())
        existing_state = _single_line(existing.get("state"), 24) or "queued"
        replacement = dict(incoming)
        replacement["id"] = existing_id
        replacement["created_ts"] = existing_created
        replacement["updated_ts"] = _now_ts()
        replacement["state"] = existing_state
        self._merge_proactive_impulse_timing(replacement, existing)
        replacement["signature"] = self._proactive_impulse_signature(replacement)
        replacement["salience"] = max(
            _safe_float(existing.get("salience"), 0.0),
            _safe_float(incoming.get("salience"), 0.0),
        )
        replacement["urgency"] = max(
            _safe_float(existing.get("urgency"), 0.0),
            _safe_float(incoming.get("urgency"), 0.0),
        )
        existing.clear()
        existing.update(replacement)
        return existing

    def _queue_proactive_impulse(
        self,
        user: dict[str, Any],
        impulse: dict[str, Any],
    ) -> dict[str, Any]:
        disabled = getattr(self, "_proactive_generation_disabled", None)
        if callable(disabled) and disabled(user):
            return {}
        pool = self._cleanup_proactive_impulses(user)
        signature = self._proactive_impulse_signature(impulse)
        reason = _single_line(impulse.get("reason"), 40)
        source = _single_line(impulse.get("source"), 40)
        for existing in reversed(pool):
            if not isinstance(existing, dict):
                continue
            if str(existing.get("state") or "queued") not in {"queued", "deferred"}:
                continue
            if str(existing.get("reason") or "") != reason:
                continue
            if str(existing.get("source") or "") != source:
                continue
            if reason in {"holiday_celebration", "course_reminder"}:
                context = impulse.get("context") if isinstance(impulse.get("context"), dict) else {}
                old_context = existing.get("context") if isinstance(existing.get("context"), dict) else {}
                if not context.get("event_key") or context.get("event_key") != old_context.get("event_key"):
                    continue
            if not self._topic_signature_similar(signature, str(existing.get("signature") or "")):
                continue
            existing_start = _safe_float(existing.get("window_start_at"), 0)
            incoming_start = _safe_float(impulse.get("window_start_at"), 0)
            existing_preferred = _safe_float(existing.get("preferred_ts"), 0)
            incoming_preferred = _safe_float(impulse.get("preferred_ts"), 0)
            existing["updated_ts"] = _now_ts()
            if existing_start <= 0:
                existing["window_start_at"] = incoming_start
            elif incoming_start > 0:
                existing["window_start_at"] = min(existing_start, incoming_start)
            if existing_preferred <= 0:
                existing["preferred_ts"] = incoming_preferred
            elif incoming_preferred > 0:
                existing["preferred_ts"] = min(existing_preferred, incoming_preferred)
            existing["best_until_at"] = max(
                _safe_float(existing.get("best_until_at"), 0),
                _safe_float(impulse.get("best_until_at"), 0),
            )
            existing["expire_at"] = max(
                _safe_float(existing.get("expire_at"), 0),
                _safe_float(impulse.get("expire_at"), 0),
            )
            existing["salience"] = max(_safe_float(existing.get("salience"), 0.0), _safe_float(impulse.get("salience"), 0.0))
            existing["warmth"] = max(_safe_float(existing.get("warmth"), 0.0), _safe_float(impulse.get("warmth"), 0.0))
            existing["urgency"] = max(_safe_float(existing.get("urgency"), 0.0), _safe_float(impulse.get("urgency"), 0.0))
            existing_fit = _safe_float(existing.get("persona_fit"), 0.0)
            incoming_fit = _safe_float(impulse.get("persona_fit"), 0.0)
            if incoming_fit > 0:
                existing["persona_fit"] = max(existing_fit, incoming_fit)
            if incoming_fit >= existing_fit:
                existing["persona_fit_blocker"] = bool(impulse.get("persona_fit_blocker"))
            elif impulse.get("persona_fit_blocker"):
                existing["persona_fit_blocker"] = True
            if _single_line(impulse.get("persona_fit_note"), 160):
                existing["persona_fit_note"] = _single_line(impulse.get("persona_fit_note"), 160)
            existing_semantic = _safe_float(existing.get("semantic_score"), 0.0)
            incoming_semantic = _safe_float(impulse.get("semantic_score"), 0.0)
            if incoming_semantic >= existing_semantic:
                for key in (
                    "semantic_kind",
                    "semantic_anchor_type",
                    "semantic_score",
                    "semantic_anchor_score",
                    "semantic_pressure",
                    "semantic_risk",
                    "semantic_note",
                    "semantic_need_layer",
                    "semantic_need_drive",
                    "semantic_need_note",
                    "semantic_need_score_bias",
                    "semantic_need_pressure_bias",
                    "semantic_blocker",
                ):
                    if key in impulse:
                        existing[key] = impulse.get(key)
            elif impulse.get("semantic_blocker"):
                existing["semantic_blocker"] = True
                existing["semantic_risk"] = max(_safe_float(existing.get("semantic_risk"), 0.0), _safe_float(impulse.get("semantic_risk"), 0.0))
            if _single_line(impulse.get("topic"), 80):
                existing["topic"] = _single_line(impulse.get("topic"), 80)
            if _single_line(impulse.get("motive"), 180):
                existing["motive"] = self._normalize_internal_motive_text(_single_line(impulse.get("motive"), 180))
            if impulse.get("chain"):
                existing["chain"] = [dict(item) for item in impulse.get("chain", []) if isinstance(item, dict)]
            if _single_line(impulse.get("trigger_message_id"), 120):
                existing["trigger_message_id"] = _single_line(impulse.get("trigger_message_id"), 120)
            if _single_line(impulse.get("trigger_umo"), 160):
                existing["trigger_umo"] = _single_line(impulse.get("trigger_umo"), 160)
            if _safe_float(impulse.get("trigger_ts"), 0) > 0:
                existing["trigger_ts"] = _safe_float(impulse.get("trigger_ts"), 0)
            if impulse.get("quota_exempt"):
                existing["quota_exempt"] = True
            if _single_line(impulse.get("context_key"), 60) and isinstance(impulse.get("context"), dict):
                existing["context_key"] = _single_line(impulse.get("context_key"), 60)
                existing["context"] = dict(impulse.get("context"))
            return existing
        content_signature = self._proactive_impulse_content_signature(impulse)
        if content_signature:
            incoming_priority = self._proactive_impulse_orchestration_priority(impulse)
            for existing in reversed(pool):
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("state") or "queued") not in {"queued", "deferred"}:
                    continue
                if reason in {"holiday_celebration", "course_reminder"} or str(existing.get("reason") or "") in {"holiday_celebration", "course_reminder"}:
                    context = impulse.get("context") if isinstance(impulse.get("context"), dict) else {}
                    old_context = existing.get("context") if isinstance(existing.get("context"), dict) else {}
                    if reason != str(existing.get("reason") or "") or not context.get("event_key") or context.get("event_key") != old_context.get("event_key"):
                        continue
                existing_signature = self._proactive_impulse_content_signature(existing)
                if not self._topic_signature_similar(content_signature, existing_signature):
                    continue
                existing_priority = self._proactive_impulse_orchestration_priority(existing)
                if incoming_priority > existing_priority:
                    return self._replace_proactive_impulse_with_higher_priority(existing, impulse)
                if incoming_priority == existing_priority:
                    self._merge_proactive_impulse_timing(existing, impulse)
                existing["updated_ts"] = _now_ts()
                existing["salience"] = max(
                    _safe_float(existing.get("salience"), 0.0),
                    _safe_float(impulse.get("salience"), 0.0),
                )
                existing["urgency"] = max(
                    _safe_float(existing.get("urgency"), 0.0),
                    _safe_float(impulse.get("urgency"), 0.0),
                )
                return existing
        item = dict(impulse)
        item["id"] = _single_line(item.get("id"), 20) or uuid.uuid4().hex[:12]
        item["signature"] = signature
        item["state"] = str(item.get("state") or "queued")
        pool.append(item)
        del pool[:-16]
        return item

    def _candidate_to_impulse(
        self,
        user: dict[str, Any],
        candidate: dict[str, Any],
        *,
        source: str,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(candidate, dict):
            return None
        disabled = getattr(self, "_proactive_generation_disabled", None)
        if callable(disabled) and disabled(user):
            return None
        check_now = _now_ts() if now is None else now
        reason = _single_line(candidate.get("reason"), 40) or "check_in"
        action = _single_line(candidate.get("action"), 40) or "message"
        motive = _single_line(candidate.get("motive"), 180)
        topic = _single_line(candidate.get("topic"), 80)
        window_start_at = _safe_float(candidate.get("window_start_at"), 0)
        preferred_ts = _safe_float(candidate.get("preferred_ts"), 0)
        best_until_at = _safe_float(candidate.get("best_until_at"), 0)
        expire_at = _safe_float(candidate.get("expire_at"), 0)
        if any(value <= 0 for value in (window_start_at, preferred_ts, best_until_at, expire_at)):
            window_start_at, preferred_ts, best_until_at, expire_at = self._event_time_window_bounds(
                candidate,
                reason=reason,
                now=check_now,
            )
        return self._build_proactive_impulse(
            user,
            reason=reason,
            action=action,
            motive=motive,
            topic=topic,
            source=source,
            window_start_at=window_start_at,
            preferred_ts=preferred_ts,
            best_until_at=best_until_at,
            expire_at=expire_at,
            chain=candidate.get("chain") if isinstance(candidate.get("chain"), list) else [],
            trigger_message_id=self._candidate_trigger_message_id(candidate),
            trigger_umo=_single_line(candidate.get("trigger_umo") or candidate.get("umo"), 160),
            trigger_ts=_safe_float(candidate.get("trigger_ts") or candidate.get("created_ts"), 0),
            quota_exempt=bool(candidate.get("_free_screen_peek")),
            context_key=_single_line(candidate.get("context_key"), 60),
            context=candidate.get("context"),
            opener_mode="name_only" if candidate.get("_name_only_opener") else "",
            followup_kind=(
                "suspended_opener"
                if candidate.get("_opener_followup")
                else "chain_followup"
                if candidate.get("_chain_followup")
                else ""
            ),
        )

    def _impulse_ready_now(self, impulse: dict[str, Any], *, now: float | None = None) -> bool:
        check_now = _now_ts() if now is None else now
        return (
            str(impulse.get("state") or "queued") in {"queued", "deferred"}
            and check_now >= _safe_float(impulse.get("window_start_at"), 0)
            and check_now <= _safe_float(impulse.get("expire_at"), 0)
        )

    def _score_proactive_impulse(
        self,
        user: dict[str, Any],
        impulse: dict[str, Any],
        *,
        now: float | None = None,
    ) -> float:
        check_now = _now_ts() if now is None else now
        created = _safe_float(impulse.get("created_ts"), check_now)
        preferred_ts = _safe_float(impulse.get("preferred_ts"), _safe_float(impulse.get("window_start_at"), check_now))
        best_until_at = _safe_float(impulse.get("best_until_at"), preferred_ts)
        age_hours = max(0.0, check_now - created) / 3600.0
        score = (
            _safe_float(impulse.get("salience"), 0.5)
            + _safe_float(impulse.get("urgency"), 0.3) * 0.9
            + _safe_float(impulse.get("warmth"), 0.3) * 0.7
        )
        score -= age_hours * _safe_float(impulse.get("decay_per_hour"), 0.08)
        if preferred_ts > 0:
            score -= min(0.55, abs(check_now - preferred_ts) / 3600.0 * 0.14)
        if best_until_at > 0 and check_now > best_until_at:
            score -= min(0.7, (check_now - best_until_at) / 3600.0 * 0.25)
        if str(impulse.get("source") or "") in {"pending_followup", "followup"} or str(impulse.get("reason") or "") == "quiet_care":
            score += 0.05
        persona_fit = _safe_float(impulse.get("persona_fit"), -1.0)
        if persona_fit < 0:
            persona_alignment = self._proactive_persona_alignment(
                user,
                reason=_single_line(impulse.get("reason"), 40),
                action=_single_line(impulse.get("action"), 40) or "message",
                motive=_single_line(impulse.get("motive"), 180),
                topic=_single_line(impulse.get("topic"), 80),
                source=_single_line(impulse.get("source"), 40),
                now=check_now,
            )
            persona_fit = _safe_float(persona_alignment.get("score"), 0.55)
            impulse["persona_fit"] = persona_fit
            impulse["persona_fit_note"] = _single_line(persona_alignment.get("note"), 160)
            impulse["persona_fit_blocker"] = bool(persona_alignment.get("blocker"))
        score += (persona_fit - 0.6) * 0.36
        if impulse.get("persona_fit_blocker"):
            score -= 0.45
        semantic_score = _safe_float(impulse.get("semantic_score"), -1.0)
        if semantic_score < 0:
            semantics = self._proactive_candidate_semantics(
                user,
                reason=_single_line(impulse.get("reason"), 40),
                action=_single_line(impulse.get("action"), 60) or "message",
                motive=_single_line(impulse.get("motive"), 180),
                topic=_single_line(impulse.get("topic"), 100),
                source=_single_line(impulse.get("source"), 40),
                context=impulse.get("context"),
                chain=impulse.get("chain") if isinstance(impulse.get("chain"), list) else [],
                trigger_message_id=_single_line(impulse.get("trigger_message_id"), 120),
                trigger_ts=_safe_float(impulse.get("trigger_ts"), 0),
            )
            semantic_score = _safe_float(semantics.get("score"), 0.5)
            impulse["semantic_kind"] = _single_line(semantics.get("kind"), 40)
            impulse["semantic_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
            impulse["semantic_score"] = semantic_score
            impulse["semantic_anchor_score"] = _safe_float(semantics.get("anchor_score"), 0.5)
            impulse["semantic_pressure"] = _safe_float(semantics.get("pressure"), 0.4)
            impulse["semantic_risk"] = _safe_float(semantics.get("risk"), 0.0)
            impulse["semantic_note"] = _single_line(semantics.get("note"), 180)
            impulse["semantic_need_layer"] = _single_line(semantics.get("need_layer"), 40)
            impulse["semantic_need_drive"] = _single_line(semantics.get("need_drive"), 80)
            impulse["semantic_need_note"] = _single_line(semantics.get("need_note"), 120)
            impulse["semantic_need_score_bias"] = _safe_float(semantics.get("need_score_bias"), 0.0)
            impulse["semantic_need_pressure_bias"] = _safe_float(semantics.get("need_pressure_bias"), 0.0)
            impulse["semantic_blocker"] = bool(semantics.get("blocker"))
        score += (semantic_score - 0.5) * 0.42
        score -= max(0.0, _safe_float(impulse.get("semantic_pressure"), 0.4) - 0.55) * 0.22
        score -= _safe_float(impulse.get("semantic_risk"), 0.0) * 0.42
        if impulse.get("semantic_blocker"):
            score -= 0.5
        readiness = self._proactive_inner_readiness(user, now=check_now)
        temperature = readiness.get("temperature") if isinstance(readiness.get("temperature"), dict) else {}
        score += (_safe_float(readiness.get("score"), 0.55) - 0.55) * 0.38
        score += (_safe_float(temperature.get("score"), 0.55) - 0.55) * 0.22
        hesitation_count = _safe_int(impulse.get("hesitation_count"), 0, 0, 8)
        if hesitation_count > 0:
            score += min(0.12, hesitation_count * 0.035)
        if _safe_int(user.get("ignored_streak"), 0, 0) >= 2:
            score -= 0.08
        return score

    def _proactive_persona_alignment(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
        topic: str = "",
        source: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        role = self._private_user_role(user)
        normalized_reason = str(reason or "check_in")
        normalized_action = str(action or "message").strip() or "message"
        normalized_motive = self._normalize_internal_motive_text(_single_line(motive, 180))
        normalized_topic = _single_line(topic, 80)
        normalized_source = _single_line(source, 40)
        text = f"{normalized_reason} {normalized_action} {normalized_topic} {normalized_motive}"
        profile = self._persona_action_profile()
        score = 0.66
        notes: list[str] = []
        blocker = False

        def note(text_value: str) -> None:
            clean = _single_line(text_value, 60)
            if clean and clean not in notes:
                notes.append(clean)

        intimate = (
            self._proactive_reason_is_intimate(normalized_reason)
            or self._proactive_action_is_intimate(normalized_action)
            or self._proactive_text_is_intimate(normalized_reason, normalized_action, normalized_motive, normalized_topic)
        )
        if role == "friend":
            score += 0.02
            if self._friend_sensitive_proactive_reason(normalized_reason) or self._friend_sensitive_proactive_action(normalized_action):
                blocker = True
                score -= 0.45
                note("次要用户关系不适合这个主动来源/能力")
            if intimate:
                score -= 0.22
                note("次要用户关系下亲密度偏高")
            if self._is_vague_seek_user_motive(normalized_reason, normalized_action, normalized_motive, normalized_topic):
                score -= 0.12
                note("次要用户关系下动机太像索取回应")
        else:
            if intimate and (profile.get("clingy") or profile.get("voicey")):
                score += 0.07
                note("亲近型人格可承载这个主动")
            if self._is_vague_seek_user_motive(normalized_reason, normalized_action, normalized_motive, normalized_topic):
                score -= 0.07
                note("动机略空,需要更具体的生活钩子")

        action_parts = {part.strip() for part in normalized_action.split("+") if part.strip()}
        if "screen_peek" in action_parts:
            if profile.get("observant"):
                score += 0.07
                note("观察型人格适合轻观察")
            else:
                score -= 0.05
                note("观察能力和人格标记不强")
        if "photo_text" in action_parts:
            if profile.get("visual"):
                score += 0.08
                note("视觉表达贴合人格")
            else:
                score -= 0.04
                note("图片表达缺少人格支撑")
        if "voice" in action_parts:
            if profile.get("voicey"):
                score += 0.08
                note("语音表达贴合人格")
            else:
                score -= 0.04
                note("语音表达缺少人格支撑")
        if "poke" in action_parts:
            if profile.get("playful") or profile.get("clingy"):
                score += 0.06
                note("轻互动贴合俏皮/依恋人格")
            else:
                score -= 0.06
                note("戳一戳不像当前人格的自然动作")
        if "jm_cosmos_read" in action_parts and not any(token in str(self._get_default_persona_prompt() or "") for token in ("阅读", "书", "小说", "本子", "夹层")):
            score -= 0.08
            note("私下阅读缺少人格兴趣支撑")

        if normalized_reason in {"activity_share", "diary_share", "background_schedule"}:
            if profile.get("playful") or profile.get("visual") or profile.get("observant"):
                score += 0.04
                note("轻分享和人格气质相容")
        if not normalized_topic and not normalized_motive and normalized_reason in {"check_in", "quiet_care", "state_share"}:
            score -= 0.08
            note("念头缺少具体来源")

        leak_tokens = ("模型", "插件", "action", "模块", "接口", "提示词", "LLM", "prompt", "后台任务", "系统调度")
        if any(token in text for token in leak_tokens):
            score -= 0.28
            blocker = True
            note("内部机制泄露风险")
        worldview_mode = str(getattr(self, "worldview_adaptation_mode", "auto") or "auto")
        if worldview_mode in {"fantasy", "sci_fi", "custom"} and any(token in text for token in ("现实网络", "现实设备", "影响现实", "控制设备")):
            score -= 0.25
            blocker = True
            note("世界观边界风险")

        mode = self._current_emotion_gate_mode(user, now=now) or self._current_relationship_gate_mode(user, now=now)
        if mode in {"careful", "hurt", "refusing", "backoff"} and intimate and normalized_source != "timer":
            score -= 0.22
            if mode in {"refusing", "backoff"}:
                blocker = True
            note(f"关系状态 {mode} 不适合亲密主动")

        score = max(0.0, min(1.0, score))
        if not notes:
            note("动机、动作和当前关系基本贴合")
        return {
            "score": score,
            "note": "；".join(notes[:3]),
            "blocker": blocker,
        }

    def _proactive_candidate_semantics(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
        topic: str = "",
        source: str = "",
        context: Any = None,
        chain: list[dict[str, Any]] | None = None,
        trigger_message_id: str = "",
        trigger_ts: float = 0,
    ) -> dict[str, Any]:
        normalized_reason = _single_line(reason, 40) or "check_in"
        normalized_action = _single_line(action, 60) or "message"
        normalized_motive = self._normalize_internal_motive_text(_single_line(motive, 180))
        normalized_topic = _single_line(topic, 100)
        normalized_source = _single_line(source, 40)
        context_text = self._proactive_semantic_evidence_text(context)
        chain_text = self._proactive_semantic_chain_text(chain)
        has_context = bool(context_text)
        has_chain = bool(chain_text)
        has_trigger = bool(_single_line(trigger_message_id, 120))
        text = f"{normalized_reason} {normalized_action} {normalized_topic} {normalized_motive}"
        evidence_text = f"{text} {context_text} {chain_text}"
        action_parts = {part.strip() for part in normalized_action.split("+") if part.strip()}
        kind = "check_in"
        if normalized_reason in {"morning_greeting", "noon_greeting", "evening_greeting", "insomnia_night"}:
            kind = "greeting"
        elif normalized_reason in {"meal_care", "meal_care_followup"}:
            kind = "care"
        elif normalized_reason in {"quiet_care", "state_share"}:
            kind = "care"
        elif normalized_reason in {"activity_share", "diary_share", "background_schedule", "creative_share", "personal_goal_progress"}:
            kind = "self_share"
        elif normalized_reason in {"important_date_share", "memo_note_reminder", "birthday_eve_hint", "birthday_celebration", "birthday_makeup", "birthday_afterglow", "holiday_celebration", "course_reminder"}:
            kind = "reminder"
        elif normalized_reason == "environment_change":
            kind = "observation"
        elif normalized_reason in {"group_share", "bili_video_share", "news_share", "web_exploration_share"}:
            kind = "external_share"
        elif normalized_source in {"pending_followup", "followup"}:
            kind = "continuation"
        elif action_parts & {"screen_peek"}:
            kind = "observation"
        elif action_parts & {"poke"}:
            kind = "light_touch"

        anchor_type = "vague"
        anchor_score = 0.28
        if normalized_source in {"pending_followup", "followup"} or has_trigger or has_chain or "前面提过" in evidence_text:
            anchor_type, anchor_score = "recent_context", 0.78
        elif normalized_reason in {"group_share"} or "群" in evidence_text:
            anchor_type, anchor_score = "group_context", 0.72
        elif normalized_reason in {"diary_share", "creative_share"} or any(token in evidence_text for token in ("日记", "写到", "作品", "片段")):
            anchor_type, anchor_score = "inner_life", 0.68
        elif normalized_reason in {"meal_care", "meal_care_followup"} or any(token in evidence_text for token in ("早餐", "早饭", "午饭", "午餐", "晚饭", "晚餐", "吃了吗", "吃了没")):
            anchor_type, anchor_score = "meal_time", 0.74
        elif normalized_reason in {"background_schedule"} or any(token in evidence_text for token in ("手上", "忙到", "日程", "计划", "刚好停")):
            anchor_type, anchor_score = "current_activity", 0.62
        elif normalized_reason in {"important_date_share", "birthday_eve_hint", "birthday_celebration", "birthday_makeup", "birthday_afterglow"} or any(token in evidence_text for token in ("生日", "纪念", "日期", "考试", "提醒")):
            anchor_type, anchor_score = "important_date", 0.78
        elif normalized_reason == "environment_change":
            anchor_type, anchor_score = "environment", 0.82
        elif normalized_reason in {"news_share", "web_exploration_share", "bili_video_share"}:
            anchor_type, anchor_score = "external_info", 0.66
        elif normalized_reason in {"morning_greeting", "noon_greeting", "evening_greeting", "insomnia_night"}:
            anchor_type, anchor_score = "time_ritual", 0.55
        elif any(token in evidence_text for token in ("天气", "雨", "阳光", "晚霞", "天色", "风", "窗")):
            anchor_type, anchor_score = "environment", 0.58
        elif has_context:
            anchor_type, anchor_score = "topic_hint", 0.56
        elif normalized_topic:
            anchor_type, anchor_score = "topic_hint", 0.48

        if normalized_reason in {"holiday_celebration", "course_reminder"} and has_context:
            anchor_type, anchor_score = "important_date", 0.78

        pressure = 0.34
        if kind in {"greeting", "self_share", "reminder"}:
            pressure -= 0.04
        if kind in {"check_in", "care", "observation", "light_touch"}:
            pressure += 0.08
        if action_parts & {"screen_peek", "poke", "voice"}:
            pressure += 0.16
        if has_context or has_trigger:
            pressure -= 0.05
        if has_chain and normalized_source in {"pending_followup", "followup", "daily_greeting"}:
            pressure -= 0.03
        if self._is_vague_seek_user_motive(normalized_reason, normalized_action, normalized_motive, normalized_topic):
            pressure += 0.18
        if self._private_user_role(user) == "friend":
            pressure += 0.08
        if _safe_int(user.get("ignored_streak"), 0, 0) > 0:
            pressure += min(0.22, _safe_int(user.get("ignored_streak"), 0, 0) * 0.06)

        risk = 0.0
        blocker = False
        notes: list[str] = []

        def note(value: str) -> None:
            clean = _single_line(value, 60)
            if clean and clean not in notes:
                notes.append(clean)

        if anchor_score >= 0.65:
            note(f"由头明确:{anchor_type}")
        elif anchor_score <= 0.35:
            note("由头偏虚")
        if pressure >= 0.62:
            note("打扰压力偏高")
        if self._unverified_social_relay_plan_reason(
            {
                "reason": normalized_reason,
                "action": normalized_action,
                "topic": normalized_topic,
                "motive": normalized_motive,
                "scene": context_text,
            },
            source=normalized_source,
            has_trigger=has_trigger,
        ):
            risk += 0.35
            blocker = True
            note("疑似无来源转述")
        if any(token in evidence_text for token in ("模型", "插件", "接口", "后台", "提示词", "系统调度", "action")):
            risk += 0.42
            blocker = True
            note("内部机制泄露")
        if self._friend_can_receive_proactive_reason(user, normalized_reason, normalized_action) is False:
            risk += 0.35
            blocker = True
            note("次要用户关系语义越界")
        if self._proactive_text_is_intimate(normalized_reason, normalized_action, normalized_motive, normalized_topic):
            risk += 0.18
            if self._private_user_role(user) == "friend":
                risk += 0.18
                note("次要用户关系亲密过量")
        score = 0.52 + (anchor_score - 0.5) * 0.42 - max(0.0, pressure - 0.45) * 0.36 - risk * 0.5
        if kind in {"continuation", "reminder"}:
            score += 0.08
        if kind == "self_share" and anchor_score >= 0.48:
            score += 0.05
        if has_context and anchor_score >= 0.5:
            score += 0.04
        if kind == "check_in" and anchor_score < 0.45:
            score -= 0.08
        need_profile: dict[str, Any] = {}
        if bool(getattr(self, "enable_maslow_motivation_experiment", False)):
            need_profile = self._maslow_motivation_profile(
                user,
                reason=normalized_reason,
                action=normalized_action,
                motive=normalized_motive,
                topic=normalized_topic,
                source=normalized_source,
                semantic_kind=kind,
                anchor_type=anchor_type,
                anchor_score=anchor_score,
                evidence_text=evidence_text,
            )
            strength = max(0.0, min(1.0, _safe_float(getattr(self, "maslow_motivation_strength", 35), 35, 0.0) / 100.0))
            score += _safe_float(need_profile.get("score_bias"), 0.0) * strength
            pressure += _safe_float(need_profile.get("pressure_bias"), 0.0) * strength
            need_note = _single_line(need_profile.get("note"), 60)
            if need_note:
                note(f"实验动机:{need_note}")
        score = max(0.0, min(1.0, score))
        if not notes:
            note(f"{kind}/{anchor_type}")
        result = {
            "kind": kind,
            "anchor_type": anchor_type,
            "anchor_score": anchor_score,
            "pressure": max(0.0, min(1.0, pressure)),
            "risk": max(0.0, min(1.0, risk)),
            "score": score,
            "note": "；".join(notes[:4]),
            "blocker": blocker,
        }
        if need_profile:
            result.update(
                {
                    "need_layer": _single_line(need_profile.get("layer"), 40),
                    "need_drive": _single_line(need_profile.get("drive"), 80),
                    "need_note": _single_line(need_profile.get("note"), 120),
                    "need_score_bias": _safe_float(need_profile.get("score_bias"), 0.0),
                    "need_pressure_bias": _safe_float(need_profile.get("pressure_bias"), 0.0),
                }
            )
        return result

    def _maslow_motivation_profile(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
        topic: str = "",
        source: str = "",
        semantic_kind: str = "",
        anchor_type: str = "",
        anchor_score: float = 0.5,
        evidence_text: str = "",
    ) -> dict[str, Any]:
        text = f"{reason} {action} {topic} {motive} {source} {semantic_kind} {anchor_type} {evidence_text}"
        action_parts = {part.strip() for part in str(action or "").split("+") if part.strip()}
        ignored_streak = _safe_int(user.get("ignored_streak"), 0, 0)

        def has_any(tokens: tuple[str, ...]) -> bool:
            return any(token in text for token in tokens)

        layer = "belonging"
        drive = "维持连接"
        score_bias = 0.02
        pressure_bias = 0.0

        if reason == "insomnia_night" or has_any(("困", "睡", "熬夜", "失眠", "休息", "生病", "头疼", "不舒服", "饿", "胃口", "吃点")):
            layer = "physiological"
            drive = "状态照料"
            score_bias = 0.04
            pressure_bias = -0.02
        elif action_parts & {"screen_peek"} or ignored_streak > 0 or has_any(("边界", "别回", "不用回", "忙", "别打扰", "沉默", "未回复")):
            layer = "safety"
            drive = "确认边界"
            score_bias = -0.02 if ignored_streak >= 2 else 0.01
            pressure_bias = 0.04 + min(0.04, ignored_streak * 0.015)
        elif reason == "important_date_share" or has_any(("生日", "纪念", "考试", "面试", "项目", "成绩", "努力", "鼓励", "夸", "辛苦")):
            layer = "esteem"
            drive = "认可支持"
            score_bias = 0.06
            pressure_bias = -0.03
        elif has_any(("意义", "存在", "世界观", "宇宙", "星空", "命运", "现实边界", "精神", "信念")):
            layer = "meaning"
            drive = "意义连接"
            score_bias = 0.03
            pressure_bias = -0.01
        elif reason in {"creative_share", "diary_share", "news_share", "web_exploration_share", "bili_video_share", "activity_share"} or has_any(
            ("学习", "创作", "灵感", "作品", "研究", "新闻", "搜索", "阅读", "视频", "日记", "见闻")
        ):
            layer = "growth"
            drive = "探索成长"
            score_bias = 0.03
            pressure_bias = -0.02 if anchor_score >= 0.5 else 0.02
        elif source in {"pending_followup", "followup"} or semantic_kind == "continuation" or anchor_type == "recent_context":
            layer = "belonging"
            drive = "续接共同话题"
            score_bias = 0.07
            pressure_bias = -0.06
        elif semantic_kind in {"greeting", "light_touch"} or reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            layer = "belonging"
            drive = "轻量陪伴仪式"
            score_bias = 0.03
            pressure_bias = -0.02
        elif reason in {"quiet_care", "check_in"} and anchor_score < 0.45:
            layer = "belonging"
            drive = "无明确由头的关心"
            score_bias = -0.03
            pressure_bias = 0.03

        if action_parts & {"poke", "voice"}:
            pressure_bias += 0.02
        if self._private_user_role(user) == "friend" and layer in {"belonging", "esteem"}:
            score_bias -= 0.02
            pressure_bias += 0.02

        labels = {
            "physiological": "状态",
            "safety": "安全",
            "belonging": "归属",
            "esteem": "尊重",
            "growth": "成长",
            "meaning": "意义",
        }
        return {
            "layer": layer,
            "drive": drive,
            "score_bias": max(-0.12, min(0.12, score_bias)),
            "pressure_bias": max(-0.12, min(0.12, pressure_bias)),
            "note": f"{labels.get(layer, layer)}/{drive}",
        }

    def _proactive_semantic_evidence_text(self, value: Any, *, limit: int = 260) -> str:
        parts: list[str] = []

        def collect(item: Any, depth: int = 0) -> None:
            if len(parts) >= 8 or depth > 2:
                return
            if isinstance(item, dict):
                priority = (
                    "title",
                    "topic",
                    "summary",
                    "text",
                    "content",
                    "reason",
                    "why",
                    "scene",
                    "impulse",
                    "tone",
                    "group_name",
                    "sender_name",
                    "share_decision",
                    "share_tone",
                    "share_boundary",
                )
                for key in priority:
                    if key in item:
                        collect(item.get(key), depth + 1)
                if len(parts) < 4:
                    for key, nested in list(item.items())[:8]:
                        if key not in priority:
                            collect(nested, depth + 1)
            elif isinstance(item, list):
                for nested in item[:5]:
                    collect(nested, depth + 1)
            else:
                text = _single_line(item, 80)
                if text and text not in parts:
                    parts.append(text)

        collect(value)
        return _single_line(" ".join(parts), limit)

    def _proactive_semantic_chain_text(self, chain: list[dict[str, Any]] | None) -> str:
        if not isinstance(chain, list):
            return ""
        parts: list[str] = []
        for step in chain[:4]:
            if not isinstance(step, dict):
                continue
            bits = [
                _single_line(step.get("kind"), 30),
                _single_line(step.get("reason"), 40),
                _single_line(step.get("topic"), 60),
                _single_line(step.get("motive"), 80),
                _single_line(step.get("tone"), 40),
            ]
            line = _single_line(" ".join(bit for bit in bits if bit), 120)
            if line:
                parts.append(line)
        return _single_line(" ".join(parts), 240)

    def _planned_proactive_semantics(self, user: dict[str, Any]) -> dict[str, Any]:
        impulse = self._planned_proactive_impulse(user)
        if isinstance(impulse, dict):
            return {
                "kind": _single_line(impulse.get("semantic_kind"), 40),
                "anchor_type": _single_line(impulse.get("semantic_anchor_type"), 40),
                "score": _safe_float(impulse.get("semantic_score"), 0.5),
                "anchor_score": _safe_float(impulse.get("semantic_anchor_score"), 0.5),
                "pressure": _safe_float(impulse.get("semantic_pressure"), 0.4),
                "risk": _safe_float(impulse.get("semantic_risk"), 0.0),
                "note": _single_line(impulse.get("semantic_note"), 180),
                "need_layer": _single_line(impulse.get("semantic_need_layer"), 40),
                "need_drive": _single_line(impulse.get("semantic_need_drive"), 80),
                "need_note": _single_line(impulse.get("semantic_need_note"), 120),
                "need_score_bias": _safe_float(impulse.get("semantic_need_score_bias"), 0.0),
                "need_pressure_bias": _safe_float(impulse.get("semantic_need_pressure_bias"), 0.0),
                "blocker": bool(impulse.get("semantic_blocker")),
            }
        return self._proactive_candidate_semantics(
            user,
            reason=self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40) or "check_in",
            action=self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=60) or "message",
            motive=_single_line(user.get("planned_proactive_motive"), 180),
            topic=_single_line(user.get("planned_proactive_topic"), 100),
            source=self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40),
            chain=user.get("planned_event_chain") if isinstance(user.get("planned_event_chain"), list) else [],
            trigger_message_id=_single_line(user.get("planned_proactive_trigger_message_id"), 120),
            trigger_ts=_safe_float(user.get("planned_proactive_trigger_ts"), 0),
        )

    def _planned_proactive_persona_alignment(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        return self._proactive_persona_alignment(
            user,
            reason=self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40) or "check_in",
            action=self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40) or "message",
            motive=_single_line(user.get("planned_proactive_motive"), 180),
            topic=_single_line(user.get("planned_proactive_topic"), 80),
            source=self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40),
            now=now,
        )

    def _planned_proactive_model_judge_signature(self, user: dict[str, Any]) -> str:
        persona = _single_line(str(self._get_default_persona_prompt() or ""), 800)
        worldview = _single_line(str(self._format_worldview_adaptation_prompt() or ""), 400)
        rel_state = user.get("relationship_state") if isinstance(user.get("relationship_state"), dict) else {}
        semantics = self._planned_proactive_semantics(user)
        ignored = _safe_int(user.get("ignored_streak"), 0, 0)
        parts = [
            self._private_user_role(user),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40),
            _single_line(user.get("planned_proactive_topic"), 80).casefold(),
            _single_line(user.get("planned_proactive_motive"), 180).casefold(),
            _single_line(semantics.get("kind"), 40),
            _single_line(semantics.get("anchor_type"), 40),
            _single_line(semantics.get("need_layer"), 40),
            _single_line(semantics.get("need_drive"), 80),
            f"semantic={int(_safe_float(semantics.get('score'), 0.5) * 5)}",
            f"pressure={int(_safe_float(semantics.get('pressure'), 0.4) * 5)}",
            f"risk={int(_safe_float(semantics.get('risk'), 0.0) * 5)}",
            rel_state.get("mode") if isinstance(rel_state, dict) else "",
            "ignored=0" if ignored <= 0 else "ignored=1" if ignored == 1 else "ignored=2+",
            persona,
            worldview,
        ]
        raw = "\n".join(_single_line(part, 1000) for part in parts)
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _cached_proactive_model_judgement(
        self,
        user: dict[str, Any],
        *,
        signature: str,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        if not signature:
            return None
        check_now = _now_ts() if now is None else now
        ttl = max(5, _safe_int(getattr(self, "proactive_persona_judge_cache_minutes", 180), 180, 5, 720)) * 60
        cache = user.get("proactive_persona_judge_cache")
        if isinstance(cache, dict):
            entry = cache.get(signature)
            if isinstance(entry, dict):
                judged_at = _safe_float(entry.get("judged_at"), 0)
                cached = entry.get("result")
                if judged_at > 0 and check_now - judged_at <= ttl and isinstance(cached, dict):
                    return dict(cached)
        if _single_line(user.get("planned_proactive_model_judge_signature"), 80) == signature:
            judged_at = _safe_float(user.get("planned_proactive_model_judge_at"), 0)
            cached = user.get("planned_proactive_model_judge_result")
            if judged_at > 0 and check_now - judged_at <= ttl and isinstance(cached, dict):
                return dict(cached)
        return None

    def _proactive_persona_judge_calls_today(self) -> int:
        usage = self.data.get("token_usage") if isinstance(getattr(self, "data", None), dict) else {}
        by_day_task = usage.get("by_day_task") if isinstance(usage, dict) else {}
        today_tasks = by_day_task.get(_today_key()) if isinstance(by_day_task, dict) else {}
        task = today_tasks.get("proactive_persona_judge") if isinstance(today_tasks, dict) else {}
        return _safe_int(task.get("calls"), 0, 0) if isinstance(task, dict) else 0

    def _local_proactive_persona_judgement(self, user: dict[str, Any]) -> dict[str, Any] | None:
        if self._private_user_role(user) == "friend" or _safe_int(user.get("ignored_streak"), 0, 0) > 0:
            return None
        semantics = self._planned_proactive_semantics(user)
        alignment = self._planned_proactive_persona_alignment(user)
        if (
            not semantics.get("blocker")
            and not alignment.get("blocker")
            and _safe_float(semantics.get("score"), 0.5) >= 0.78
            and _safe_float(semantics.get("pressure"), 0.4) <= 0.30
            and _safe_float(semantics.get("risk"), 0.0) <= 0.10
            and _safe_float(alignment.get("score"), 0.55) >= 0.78
        ):
            return {"decision": "send", "score": 90, "reason": "本地高置信人格判定", "local": True}
        return None

    def _normalize_proactive_model_judgement(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"send", "rewrite", "defer", "drop"}:
            return None
        score = _safe_int(payload.get("score"), 0, 0, 100)
        threshold_getter = getattr(self, "_effective_proactive_persona_judge_send_threshold", None)
        threshold = (
            threshold_getter()
            if callable(threshold_getter)
            else _safe_int(getattr(self, "proactive_persona_judge_send_threshold", 62), 62, 0, 100)
        )
        if decision == "send" and score > 0 and score < threshold:
            decision = "defer"
        reason = self._normalize_legacy_proactive_text(payload.get("reason"), limit=140) or "模型人格判定"
        result = {
            "decision": decision,
            "score": score,
            "reason": reason,
            "delay_minutes": _safe_int(payload.get("delay_minutes"), 90, 20, 360),
            "reason_field": self._normalize_legacy_proactive_text(payload.get("planned_reason") or payload.get("reason_field"), limit=40),
            "action": self._normalize_legacy_proactive_text(payload.get("action"), limit=40),
            "topic": _single_line(payload.get("topic"), 80),
            "motive": self._normalize_internal_motive_text(_single_line(payload.get("motive"), 180)),
        }
        return result

    def _format_proactive_source_model_hint(self, user: dict[str, Any]) -> str:
        source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        if source in {"pending_followup", "followup"}:
            return "\n".join(
                [
                    "【来源专项改写：补一句】",
                    "这类来源不是重新开话题，而是前一句还有一个具体点没落地。",
                    "如果现在的 topic/motive 只是“再说一句/补一句/轻轻放一句/顺着那股劲”，优先 rewrite，不要直接 send。",
                    "rewrite 后必须补出一个实质点：提醒、遗漏信息、没说完的小重点，或前一句里还挂着的小事。",
                    "情绪可以很轻，但只允许当底色：一点点不甘心、惦记，或认真；不要把情绪本身写成内容。",
                ]
            )
        if source == "daily_greeting" or reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            return "\n".join(
                [
                    "【来源专项改写：日常招呼】",
                    "这类来源的价值在“当天这个时段的第一句主动开口”，不是在任何空档里补一声问候。",
                    "如果今天已经发过别的主动，就别再硬写 morning_greeting；用户先自然来聊不等于 Bot 已经醒来，不能因此取消首次起床问候。",
                    "noon_greeting/evening_greeting 仍要避开刚刚发生的来回互动。",
                    "rewrite 后必须落在当前时段的一个小片段上：早晨刚醒/洗漱/出门前，中午刚吃完/发懒/准备午休，晚上收尾/回家/窝下来。",
                    "最终效果要像这个时段第一次顺手冒头，不像模板化签到，也不像聊到一半又补来的礼貌问候。",
                ]
            )
        if source == "random":
            return "\n".join(
                [
                    "【来源专项改写：轻微想念】",
                    "规则层已经判断这次“想来找一下”成立，但正文不能只剩关系姿态。",
                    "如果现在的 topic/motive 只有“想你了/来看看你/在不在/忙不忙”，优先 rewrite。",
                    "rewrite 后要补出一个很小的具体钩子：当前时段的小片段、刚冒出来的小想法，或一句能自然开口的话。",
                    "这类来源只能轻，不要写成索取回应，也不要写成无缘由的空泛表白。",
                ]
            )
        if source == "state" or reason == "state_share":
            return "\n".join(
                [
                    "【来源专项改写：身体小需求】",
                    "这类来源不是汇报状态，而是身体上的那点小事带出来的话头。",
                    "如果现在的 topic/motive 像“我饿了/我累了/状态不好”，优先 rewrite。",
                    "rewrite 后要把它改成一个具体可聊的小需求，比如吃什么、要不要垫一口、想不想来点甜的；不要写成状态播报。",
                    "语气要自然，不要像健康汇报、撒娇表演或硬找人陪。",
                ]
            )
        return ""

    def _format_proactive_model_judge_prompt(self, user: dict[str, Any]) -> str:
        persona = str(self._get_default_persona_prompt() or "").strip()
        worldview = str(self._format_worldview_adaptation_prompt() or "").strip()
        boundary = self._format_private_user_boundary_hint(user) if isinstance(user, dict) else ""
        rel_summary = ""
        formatter = getattr(self, "_format_relationship_summary", None)
        if callable(formatter):
            try:
                rel_summary = _single_line(formatter(user), 220)
            except Exception:
                rel_summary = ""
        local_alignment = self._planned_proactive_persona_alignment(user)
        semantics = self._planned_proactive_semantics(user)
        window_phase, window_detail = self._planned_impulse_window_phase(user)
        inner_readiness = self._proactive_inner_readiness(user)
        source_hint = self._format_proactive_source_model_hint(user)
        planning_voice = self._format_persona_voice_channel_prompt("planning") if callable(getattr(self, "_format_persona_voice_channel_prompt", None)) else ""
        inner_voice = self._format_persona_voice_channel_prompt("inner") if callable(getattr(self, "_format_persona_voice_channel_prompt", None)) else ""
        role = self._private_user_role(user)
        nickname = _single_line(user.get("nickname"), 40) or self.default_nickname
        return f"""
你是“主动消息人格/世界观判定器”。只判断这个主动计划是否像当前角色会自然产生的念头,不要写最终聊天正文。

输出必须是 JSON 对象,不要 Markdown,不要解释：
{{"decision":"send|rewrite|defer|drop","score":0,"reason":"20字以内原因","delay_minutes":90,"planned_reason":"","action":"","topic":"","motive":""}}

判定含义：
- send：计划自然,可以进入生成。
- rewrite：方向有价值,但动机/话题/动作需要更贴合角色；只改 planned_reason/action/topic/motive,不要写最终聊天正文。
- defer：现在不适合或动机不够自然,稍后再看。
- drop：明显不符合角色/世界观/关系边界,或像系统任务、索取回应、无由头打扰。

硬要求：
- 不得放行内部机制泄露、工具名、模型、插件、提示词、后台任务。
- 不得新增事实、现实能力或用户没给过的关系信息。
- 次要用户关系必须普通、低频、不过度亲密；主要用户/亲近关系也要尊重休息和拒绝。
- 世界观表达必须贴合设定；能力只能作为角色内自然动机,不能露出调用过程。
- 如果只是“想你了/来看看/在不在/忙不忙”且没有具体由头,通常 defer 或 rewrite。

【角色设定】
{_single_line(persona, 1800) or "（未读取到显式人格,按自然私聊陪伴角色处理）"}

【世界观/适配】
{_single_line(worldview, 1000) or "（无额外世界观适配）"}

【人格标准化：计划/内心通道】
{planning_voice or "（无单独计划风格）"}
{inner_voice or "（无单独内心活动风格）"}
使用方式：这里只判断“这个念头/安排是否像角色自然产生”,不要把内心活动当成最终聊天正文,也不要因为风格规则而新增事实。

【关系边界】
{boundary}

【当前对象】
- 昵称：{nickname}
- 关系角色：{role}
- 关系摘要：{rel_summary or "暂无"}
- 连续未回应：{_safe_int(user.get("ignored_streak"), 0, 0)}
- 最近用户消息：{_single_line(user.get("last_user_message"), 160) or "（无）"}
- 最近 Bot 消息：{_single_line(user.get("last_companion_message"), 160) or "（无）"}
- Bot 当前开口欲/关系温度：{_safe_float(inner_readiness.get("score"), 0.55):.2f}｜{_single_line(inner_readiness.get("label"), 60)}｜{_single_line(inner_readiness.get("detail"), 180)}

【当前主动计划】
- source：{self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) or "unknown"}
- reason：{self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40) or "check_in"}
- action：{_single_line(user.get("planned_proactive_action"), 40) or "message"}
- topic：{_single_line(user.get("planned_proactive_topic"), 100) or "无"}
- motive：{_single_line(user.get("planned_proactive_motive"), 220) or "无"}
- 候选语义：{_single_line(semantics.get("kind"), 40)}/{_single_line(semantics.get("anchor_type"), 40)}｜score={_safe_float(semantics.get("score"), 0.5):.2f}｜pressure={_safe_float(semantics.get("pressure"), 0.4):.2f}｜risk={_safe_float(semantics.get("risk"), 0.0):.2f}｜{_single_line(semantics.get("note"), 140)}
- 念头窗口：{window_phase}｜{window_detail}
- 本地粗判：{_safe_float(local_alignment.get("score"), 0.0):.2f}｜{_single_line(local_alignment.get("note"), 140)}

{source_hint}
""".strip()

    async def _review_planned_proactive_with_model(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        check_now = _now_ts() if now is None else now
        if not bool(getattr(self, "enable_llm_proactive_persona_judge", True)):
            return {"decision": "send", "score": 100, "reason": "模型人格判定关闭"}
        if self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) in {"timer", "troubleshooting", "simulation", "reading_life", "life_enhancer"}:
            return {"decision": "send", "score": 100, "reason": "特权计划跳过模型人格判定（reading_life/life_enhancer已有独立时间窗与内容控制）"}
        signature = self._planned_proactive_model_judge_signature(user)
        cached = self._cached_proactive_model_judgement(user, signature=signature, now=check_now)
        if isinstance(cached, dict):
            cached["cached"] = True
            return cached
        local_result = self._local_proactive_persona_judgement(user)
        if isinstance(local_result, dict):
            return local_result
        daily_limit = _safe_int(getattr(self, "proactive_persona_judge_max_daily", 12), 12, 0, 100)
        if daily_limit <= 0 or self._proactive_persona_judge_calls_today() >= daily_limit:
            return {"decision": "send", "score": 0, "reason": "模型日预算已满，使用本地规则", "local": True}
        prompt = self._format_proactive_model_judge_prompt(user)
        memory_getter = getattr(self, "_memory_companion_compose_feature_context", None)
        if callable(memory_getter):
            user_id = _single_line(user.get("user_id") or user.get("id"), 80)
            query = " ".join(
                part
                for part in (
                    "主动消息适合性",
                    _single_line(user.get("planned_proactive_reason"), 80),
                    _single_line(user.get("planned_proactive_topic"), 120),
                    _single_line(user.get("planned_proactive_motive"), 180),
                    "用户习惯 上次主动回应 边界 当前穿搭 当前日程 最近状态",
                )
                if part
            )
            memory_context = await memory_getter(
                kind="proactive_review",
                query=query,
                user=user,
                user_id=user_id,
                top_k=5,
                max_chars=800,
            )
            if memory_context:
                prompt = (
                    f"{prompt.rstrip()}\n\n"
                    "<!-- private_companion_memory_review_context_v1 -->\n"
                    "【我会牢牢记住你 相关记忆】\n"
                    f"{memory_context}\n"
                    "使用方式：只辅助判断是否适合主动、是否需要改写或延后；不要在理由里暴露检索过程。"
                )
        started = time.perf_counter()
        raw = await self._llm_call(
            prompt,
            max_tokens=260,
            provider_id=self._task_provider(
                getattr(self, "proactive_persona_judge_provider_id", ""),
                self.response_review_provider_id,
                self.mai_style_provider_id,
            ),
            task="proactive_persona_judge",
        )
        parsed = self._parse_json_object(raw)
        result = self._normalize_proactive_model_judgement(parsed)
        if not isinstance(result, dict):
            logger.info("[PrivateCompanion] 模型人格判定无有效 JSON,降级本地判定")
            return {"decision": "send", "score": 0, "reason": "模型判定失败,降级本地"}
        result["signature"] = signature
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "[PrivateCompanion] 主动模型人格判定: decision=%s score=%s reason=%s elapsed=%sms",
            result.get("decision"),
            result.get("score"),
            _single_line(result.get("reason"), 100),
            result.get("elapsed_ms"),
        )
        return result

    def _cache_proactive_model_judgement(
        self,
        user: dict[str, Any],
        judgement: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        signature = _single_line(judgement.get("signature"), 80) or self._planned_proactive_model_judge_signature(user)
        user["planned_proactive_model_judge_signature"] = signature
        user["planned_proactive_model_judge_result"] = {
            key: value
            for key, value in judgement.items()
            if key in {"decision", "score", "reason", "delay_minutes", "reason_field", "action", "topic", "motive"}
        }
        judged_at = _now_ts() if now is None else now
        user["planned_proactive_model_judge_at"] = judged_at
        cache = user.get("proactive_persona_judge_cache")
        cache = dict(cache) if isinstance(cache, dict) else {}
        ttl = max(5, _safe_int(getattr(self, "proactive_persona_judge_cache_minutes", 180), 180, 5, 720)) * 60
        cache = {
            key: value for key, value in cache.items()
            if isinstance(value, dict) and judged_at - _safe_float(value.get("judged_at"), 0) <= ttl
        }
        cache[signature] = {"judged_at": judged_at, "result": dict(user["planned_proactive_model_judge_result"])}
        if len(cache) > 16:
            newest = sorted(cache.items(), key=lambda item: _safe_float(item[1].get("judged_at"), 0), reverse=True)[:16]
            cache = dict(newest)
        user["proactive_persona_judge_cache"] = cache

    def _apply_proactive_model_rewrite(self, user: dict[str, Any], judgement: dict[str, Any]) -> bool:
        changed = False
        new_reason = self._normalize_legacy_proactive_text(judgement.get("reason_field"), limit=40)
        new_action = self._normalize_legacy_proactive_text(judgement.get("action"), limit=40)
        new_topic = _single_line(judgement.get("topic"), 80)
        new_motive = self._normalize_internal_motive_text(_single_line(judgement.get("motive"), 180))
        current_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        current_action = self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40)
        if new_reason and new_reason != current_reason:
            user["planned_proactive_reason"] = new_reason
            changed = True
        if new_action and self._action_is_available(new_action, user) and new_action != current_action:
            user["planned_proactive_action"] = new_action
            changed = True
        if new_topic and new_topic != _single_line(user.get("planned_proactive_topic"), 80):
            user["planned_proactive_topic"] = new_topic
            changed = True
        if new_motive and new_motive != _single_line(user.get("planned_proactive_motive"), 180):
            user["planned_proactive_motive"] = new_motive
            changed = True
        if changed and self._private_user_role(user) == "friend":
            sanitized = self._sanitize_friend_proactive_plan_fields(
                user,
                reason=self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40) or "check_in",
                action=self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40) or "message",
                topic=_single_line(user.get("planned_proactive_topic"), 80),
                motive=_single_line(user.get("planned_proactive_motive"), 180),
            )
            user["planned_proactive_reason"] = sanitized["reason"]
            user["planned_proactive_action"] = sanitized["action"]
            user["planned_proactive_topic"] = sanitized["topic"]
            user["planned_proactive_motive"] = sanitized["motive"]
        return changed

    def _planned_proactive_impulse(self, user: dict[str, Any]) -> dict[str, Any] | None:
        impulse_id = _single_line(user.get("planned_proactive_impulse_id"), 20)
        if not impulse_id:
            return None
        for item in self._cleanup_proactive_impulses(user):
            if isinstance(item, dict) and _single_line(item.get("id"), 20) == impulse_id:
                return item
        return None

    def _planned_impulse_value(self, user: dict[str, Any], *, now: float | None = None) -> float:
        impulse = self._planned_proactive_impulse(user)
        if isinstance(impulse, dict):
            return self._score_proactive_impulse(user, impulse, now=now)
        reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        value = 0.62
        if source in {"timer", "troubleshooting", "simulation"}:
            value += 0.35
        if source in {"pending_followup", "daily_greeting", "story", "state"}:
            value += 0.08
        if reason in {"important_date_share", "birthday_eve_hint", "birthday_celebration", "birthday_makeup", "birthday_afterglow", "quiet_care", "group_share", "news_share", "creative_share"}:
            value += 0.08
        if self._private_user_role(user) == "friend":
            value -= 0.06
        return value

    def _planned_impulse_window_phase(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> tuple[str, str]:
        check_now = _now_ts() if now is None else now
        start_at = _safe_float(user.get("planned_proactive_window_start_at"), 0)
        best_until = _safe_float(user.get("planned_proactive_best_until_at"), 0)
        expire_at = _safe_float(user.get("planned_proactive_expire_at"), 0)
        if expire_at > 0 and check_now > expire_at:
            return "expired", "念头窗口已过期"
        if start_at > 0 and check_now < start_at:
            return "before", f"距窗口开始还有 {self._format_elapsed(start_at - check_now)}"
        if best_until > 0 and check_now <= best_until:
            return "best", f"正处于最佳表达窗口,剩余 {self._format_elapsed(best_until - check_now)}"
        if expire_at > 0:
            return "tail", f"已过最佳窗口,距过期 {self._format_elapsed(max(0, expire_at - check_now))}"
        return "unknown", "未记录念头窗口"

    def _proactive_item_freshness_class(
        self,
        *,
        action: str,
        reason: str,
        source: str,
        semantic_kind: str = "",
    ) -> str:
        normalized_reason = self._normalize_legacy_proactive_text(reason, limit=40)
        normalized_source = self._normalize_legacy_proactive_text(source, limit=40)
        normalized_kind = self._normalize_legacy_proactive_text(semantic_kind, limit=40)
        if normalized_reason == "environment_change" or normalized_source == "environment_change":
            return "immediate"
        if normalized_source == "timer" or normalized_reason in {
            "birthday_eve_hint",
            "birthday_celebration",
            "birthday_makeup",
            "birthday_afterglow",
            "important_date_share",
            "bili_video_share",
            "news_share",
            "web_exploration_share",
            "creative_share",
        }:
            return "durable"
        action_parts = {part.strip() for part in str(action or "").split("+") if part.strip()}
        if {"photo_text", "screen_peek"} & action_parts:
            return "immediate"
        if normalized_kind in {"self_share", "observation"} and normalized_source in {
            "story",
            "daily_story",
            "state",
            "event",
            "simulation",
        }:
            return "immediate"
        return "contextual"

    def _planned_proactive_delivery_key(self, user: dict[str, Any]) -> str:
        if not isinstance(user, dict):
            return ""
        parts = (
            _single_line(user.get("planned_candidate_id"), 40),
            _single_line(user.get("planned_proactive_impulse_id"), 40),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40),
            _single_line(user.get("planned_proactive_topic"), 120),
            _single_line(user.get("planned_proactive_motive"), 220),
        )
        if not any(parts):
            return ""
        return hashlib.sha1("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()

    def _planned_proactive_freshness_class(self, user: dict[str, Any]) -> str:
        if not isinstance(user, dict):
            return "contextual"
        delivery_key = self._planned_proactive_delivery_key(user)
        if delivery_key and _single_line(user.get("planned_proactive_origin_key"), 80) == delivery_key:
            stored = _single_line(user.get("planned_proactive_freshness"), 24)
            if stored in {"immediate", "contextual", "durable"}:
                return stored
        return self._proactive_item_freshness_class(
            action=str(user.get("planned_proactive_action") or "message"),
            reason=str(user.get("planned_proactive_reason") or ""),
            source=str(user.get("planned_proactive_source") or ""),
            semantic_kind=str(user.get("planned_proactive_semantic_kind") or ""),
        )

    def _ensure_planned_proactive_delivery_state(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        if not isinstance(user, dict):
            return {}
        check_now = _now_ts() if now is None else now
        delivery_key = self._planned_proactive_delivery_key(user)
        if not delivery_key:
            return {}
        origin_key = _single_line(user.get("planned_proactive_origin_key"), 80)
        origin_at = _safe_float(user.get("planned_proactive_origin_at"), 0)
        freshness = self._planned_proactive_freshness_class(user)
        if origin_key != delivery_key or origin_at <= 0:
            origin_at = _safe_float(user.get("planned_proactive_window_start_at"), 0) or _safe_float(user.get("next_proactive_at"), 0) or check_now
            user["planned_proactive_origin_at"] = origin_at
            user["planned_proactive_origin_key"] = delivery_key
            user["planned_proactive_freshness"] = freshness
            user["planned_proactive_delivery_state"] = "fresh"
        elif _single_line(user.get("planned_proactive_freshness"), 24) not in {"immediate", "contextual", "durable"}:
            user["planned_proactive_freshness"] = freshness
        return {
            "key": delivery_key,
            "origin_at": origin_at,
            "best_until_at": _safe_float(user.get("planned_proactive_best_until_at"), 0),
            "expire_at": _safe_float(user.get("planned_proactive_expire_at"), 0),
            "freshness": _single_line(user.get("planned_proactive_freshness"), 24) or freshness,
            "delivery_state": _single_line(user.get("planned_proactive_delivery_state"), 24) or "fresh",
        }

    def _planned_proactive_send_freshness_reason(
        self,
        user: dict[str, Any],
        snapshot: dict[str, Any] | None,
        *,
        now: float | None = None,
    ) -> str:
        if not isinstance(snapshot, dict) or not snapshot:
            return ""
        current = self._ensure_planned_proactive_delivery_state(user, now=now)
        if not current:
            return "主动候选已被清理或替换"
        if _single_line(current.get("key"), 80) != _single_line(snapshot.get("key"), 80):
            return "主动候选在生成期间已变化"
        check_now = _now_ts() if now is None else now
        special_reason = self._special_calendar_send_freshness_reason(user, now=check_now)
        if special_reason:
            return special_reason
        expire_at = _safe_float(current.get("expire_at"), 0)
        if expire_at > 0 and check_now > expire_at and self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) != "timer":
            return "主动候选在生成期间已过期"
        if _single_line(current.get("freshness"), 24) == "immediate":
            best_until = _safe_float(current.get("best_until_at"), 0)
            if best_until > 0 and check_now > best_until:
                return "即时主动已越过自然表达窗口"
        return ""

    def _is_immediate_life_share_impulse(self, impulse: dict[str, Any]) -> bool:
        if not isinstance(impulse, dict) or not self._action_has_photo_text(str(impulse.get("action") or "")):
            return False
        return self._proactive_item_freshness_class(
            action=str(impulse.get("action") or ""),
            reason=str(impulse.get("reason") or ""),
            source=str(impulse.get("source") or ""),
            semantic_kind=str(impulse.get("semantic_kind") or ""),
        ) == "immediate"

    def _defer_or_replace_planned_impulse(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
        note: str = "",
        delay_minutes: tuple[float, float] = (30.0, 90.0),
        block_current: bool = False,
    ) -> bool:
        check_now = _now_ts() if now is None else now
        impulse = self._planned_proactive_impulse(user)
        current_id = _single_line(user.get("planned_proactive_impulse_id"), 20)
        delivery = self._ensure_planned_proactive_delivery_state(user, now=check_now)
        freshness = _single_line(delivery.get("freshness"), 24) or "contextual"
        best_until = _safe_float(delivery.get("best_until_at"), 0)
        is_immediate = freshness == "immediate"
        if is_immediate and not block_current and best_until > 0 and check_now >= best_until:
            expired_note = _single_line(note, 120) or "即时主动已过自然窗口"
            expired_note = f"{expired_note}；原候选已作废并重新安排"
            self._mark_planned_candidate_status(user, "blocked", expired_note)
            if isinstance(impulse, dict):
                impulse["updated_ts"] = check_now
                impulse["last_note"] = expired_note
                impulse["state"] = "blocked"
            self._clear_pending_proactive_plan(user)
            if not self._materialize_best_proactive_impulse(user, now=check_now):
                return False
            return bool(_single_line(user.get("planned_proactive_impulse_id"), 20) != current_id)
        if is_immediate and not block_current:
            self._mark_planned_candidate_status(user, "deferred", note)
            delay = random.uniform(max(1.0, delay_minutes[0]), max(delay_minutes[0] + 1.0, delay_minutes[1])) * 60
            next_window = min(check_now + delay, best_until) if best_until > 0 else check_now + delay
            capped_expire_at = best_until + 8 * 60 if best_until > 0 else 0
            if isinstance(impulse, dict):
                impulse["updated_ts"] = check_now
                impulse["last_note"] = _single_line(note, 160)
                impulse["state"] = "deferred"
                impulse["hesitation_count"] = _safe_int(impulse.get("hesitation_count"), 0, 0, 8) + 1
                impulse["hesitation_at"] = check_now
                impulse["hesitation_note"] = _single_line(note, 160)
                impulse["window_start_at"] = next_window
                impulse["preferred_ts"] = max(_safe_float(impulse.get("preferred_ts"), 0), next_window)
                if capped_expire_at > 0:
                    old_expire_at = _safe_float(impulse.get("expire_at"), 0)
                    impulse["expire_at"] = min(old_expire_at if old_expire_at > 0 else capped_expire_at, capped_expire_at)
                self._remember_proactive_hesitation(user, impulse, note=note, now=check_now)
            user["next_proactive_at"] = next_window
            user["planned_proactive_window_start_at"] = next_window
            if capped_expire_at > 0:
                old_expire_at = _safe_float(user.get("planned_proactive_expire_at"), 0)
                user["planned_proactive_expire_at"] = min(old_expire_at if old_expire_at > 0 else capped_expire_at, capped_expire_at)
            user["planned_proactive_delivery_state"] = "deferred"
            return False
        self._mark_planned_candidate_status(user, "blocked" if block_current else "deferred", note)
        if isinstance(impulse, dict):
            impulse["updated_ts"] = check_now
            impulse["last_note"] = _single_line(note, 160)
            if block_current:
                impulse["state"] = "blocked"
            else:
                hesitation_count = _safe_int(impulse.get("hesitation_count"), 0, 0, 8) + 1
                impulse["hesitation_count"] = hesitation_count
                impulse["hesitation_at"] = check_now
                impulse["hesitation_note"] = _single_line(note, 160)
                self._remember_proactive_hesitation(user, impulse, note=note, now=check_now)
                delay = random.uniform(max(1.0, delay_minutes[0]), max(delay_minutes[0] + 1.0, delay_minutes[1])) * 60
                next_window = check_now + delay
                impulse["state"] = "deferred"
                impulse["window_start_at"] = next_window
                impulse["preferred_ts"] = max(_safe_float(impulse.get("preferred_ts"), 0), next_window)
                impulse["best_until_at"] = max(_safe_float(impulse.get("best_until_at"), 0), next_window + 25 * 60)
                impulse["expire_at"] = max(_safe_float(impulse.get("expire_at"), 0), next_window + 90 * 60)
        elif not block_current:
            delay = random.uniform(max(1.0, delay_minutes[0]), max(delay_minutes[0] + 1.0, delay_minutes[1])) * 60
            next_window = check_now + delay
            user["next_proactive_at"] = next_window
            user["planned_proactive_window_start_at"] = next_window
            user["planned_proactive_best_until_at"] = next_window + 25 * 60
            user["planned_proactive_expire_at"] = next_window + 90 * 60
            user["planned_proactive_delivery_state"] = "deferred"
            return False
        self._clear_pending_proactive_plan(user)
        if not self._materialize_best_proactive_impulse(user, now=check_now):
            return False
        return bool(_single_line(user.get("planned_proactive_impulse_id"), 20) != current_id)

    def _remember_proactive_hesitation(
        self,
        user: dict[str, Any],
        impulse: dict[str, Any],
        *,
        note: str = "",
        now: float | None = None,
    ) -> None:
        check_now = _now_ts() if now is None else now
        raw = user.setdefault("recent_proactive_hesitations", [])
        if not isinstance(raw, list):
            raw = []
            user["recent_proactive_hesitations"] = raw
        item = {
            "ts": check_now,
            "reason": _single_line(impulse.get("reason"), 40),
            "source": _single_line(impulse.get("source"), 40),
            "topic": _single_line(impulse.get("topic"), 80),
            "motive": _single_line(impulse.get("motive"), 140),
            "note": _single_line(note, 140),
            "count": _safe_int(impulse.get("hesitation_count"), 1, 1, 20),
        }
        raw.append(item)
        del raw[:-8]
        user["last_proactive_hesitation_at"] = check_now
        user["last_proactive_hesitation_note"] = item["note"]

    def _motive_with_hesitation_memory(self, impulse: dict[str, Any], motive: str) -> str:
        count = _safe_int(impulse.get("hesitation_count"), 0, 0, 8)
        cleaned = self._normalize_internal_motive_text(motive)
        if count <= 0:
            return cleaned
        source = str(impulse.get("source") or "")
        if source in {"timer", "troubleshooting", "simulation"}:
            return cleaned
        topic = _single_line(impulse.get("topic"), 40)
        if cleaned:
            return cleaned
        if topic:
            return self._normalize_internal_motive_text(f"想到“{topic}”，想短短提一句")
        return ""

    def _materialize_best_proactive_impulse(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> bool:
        check_now = _now_ts() if now is None else now
        user_id = str(user.get("user_id") or user.get("id") or "")
        active = [
            item
            for item in self._cleanup_proactive_impulses(user, now=check_now)
            if isinstance(item, dict) and str(item.get("state") or "queued") in {"queued", "deferred"}
        ]
        if not active:
            return False
        ready = [item for item in active if self._impulse_ready_now(item, now=check_now)]
        selected: dict[str, Any] | None = None
        review_at = 0.0
        if ready:
            ready.sort(
                key=lambda item: (
                    self._score_proactive_impulse(user, item, now=check_now)
                    + self._proactive_impulse_orchestration_priority(item) / 300.0,
                    self._proactive_impulse_orchestration_priority(item),
                ),
                reverse=True,
            )
            selected = ready[0]
            review_at = check_now
        else:
            future = sorted(
                active,
                key=lambda item: (
                    _safe_float(item.get("window_start_at"), check_now + 365 * 24 * 3600),
                    -self._score_proactive_impulse(user, item, now=check_now),
                ),
            )
            if not future:
                return False
            earliest_start = _safe_float(future[0].get("window_start_at"), check_now)
            near_term = [
                item
                for item in future
                if _safe_float(item.get("window_start_at"), earliest_start) <= earliest_start + 90 * 60
            ]
            selected = max(
                near_term,
                key=lambda item: (
                    self._proactive_impulse_orchestration_priority(item),
                    self._score_proactive_impulse(user, item, now=check_now),
                    -_safe_float(item.get("window_start_at"), earliest_start),
                ),
            )
            review_at = _safe_float(selected.get("window_start_at"), check_now)
        candidate = {
            "source": self._normalize_legacy_proactive_text(selected.get("source"), limit=40) or "impulse",
            "reason": self._normalize_legacy_proactive_text(selected.get("reason"), limit=40) or "check_in",
            "action": self._normalize_legacy_proactive_text(selected.get("action"), limit=40) or "message",
            "scheduled_ts": max(review_at, _safe_float(selected.get("window_start_at"), review_at)),
            "topic": _single_line(selected.get("topic"), 80),
            "motive": self._motive_with_hesitation_memory(selected, _single_line(selected.get("motive"), 180)),
            "score": int(max(0.0, min(1.0, self._score_proactive_impulse(user, selected, now=check_now))) * 100),
            "context_key": _single_line(selected.get("context_key"), 60),
            "context": selected.get("context"),
            "chain": selected.get("chain") if isinstance(selected.get("chain"), list) else [],
        }
        item = self._record_proactive_candidate(
            user_id,
            candidate,
            status="accepted",
            note="由潜在念头池物化为当前主动计划",
            user=user,
        )
        self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = candidate["scheduled_ts"]
        user["planned_proactive_reason"] = self._normalize_legacy_proactive_text(candidate["reason"], limit=40) or "check_in"
        user["planned_proactive_action"] = self._normalize_legacy_proactive_text(candidate["action"], limit=40) or "message"
        user["planned_proactive_source"] = self._normalize_legacy_proactive_text(candidate["source"], limit=40) or "impulse"
        user["planned_proactive_motive"] = self._normalize_internal_motive_text(candidate["motive"])
        user["planned_proactive_topic"] = candidate["topic"]
        if user["planned_proactive_reason"] == "birthday_curiosity":
            user["birthday_curiosity_asked_at"] = check_now
        user["planned_proactive_impulse_id"] = _single_line(selected.get("id"), 20)
        user["planned_proactive_window_start_at"] = _safe_float(selected.get("window_start_at"), 0)
        user["planned_proactive_best_until_at"] = _safe_float(selected.get("best_until_at"), 0)
        user["planned_proactive_expire_at"] = _safe_float(selected.get("expire_at"), 0)
        user["planned_proactive_semantic_kind"] = _single_line(selected.get("semantic_kind"), 40)
        user["planned_proactive_anchor_type"] = _single_line(selected.get("semantic_anchor_type"), 40)
        user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(selected.get("semantic_score"), 0.5))) * 100)
        user["planned_proactive_semantic_note"] = _single_line(selected.get("semantic_note"), 180)
        user["planned_proactive_need_layer"] = _single_line(selected.get("semantic_need_layer"), 40)
        user["planned_proactive_need_drive"] = _single_line(selected.get("semantic_need_drive"), 80)
        user["planned_proactive_need_note"] = _single_line(selected.get("semantic_need_note"), 120)
        user["planned_candidate_id"] = item.get("id", "")
        user["planned_event_chain"] = (
            []
            if self._private_user_role(user) == "friend"
            else [dict(step) for step in selected.get("chain", []) if isinstance(step, dict)]
        )
        user["planned_opener_mode"] = _single_line(selected.get("opener_mode"), 24)
        user["planned_followup_kind"] = _single_line(selected.get("followup_kind"), 32)
        user["planned_proactive_quota_exempt"] = bool(selected.get("quota_exempt"))
        self._set_planned_proactive_trigger(
            user,
            message_id=_single_line(selected.get("trigger_message_id"), 120),
            umo=_single_line(selected.get("trigger_umo"), 160),
            created_at=_safe_float(selected.get("trigger_ts"), 0),
        )
        context_key = _single_line(selected.get("context_key"), 60)
        context = selected.get("context")
        if context_key and isinstance(context, dict):
            user[context_key] = dict(context)
        selected["updated_ts"] = check_now
        selected["state"] = "queued"
        return True

    def _record_proactive_candidate(
        self,
        user_id: str,
        candidate: dict[str, Any],
        *,
        status: str,
        note: str = "",
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        disabled = getattr(self, "_proactive_generation_disabled", None)
        target_user = user
        if not isinstance(target_user, dict):
            users = self.data.get("users") if isinstance(self.data.get("users"), dict) else {}
            target_user = users.get(str(user_id)) if isinstance(users.get(str(user_id)), dict) else None
        if callable(disabled) and disabled(target_user):
            return {}
        now = _now_ts()
        topic = _single_line(candidate.get("topic"), 80)
        motive = _single_line(candidate.get("motive"), 160)
        action = _single_line(candidate.get("action"), 40) or "message"
        source = _single_line(candidate.get("source"), 40) or "unknown"
        reason = _single_line(candidate.get("reason"), 40) or "check_in"
        scheduled = _safe_float(candidate.get("scheduled_ts"), now)
        signature = self._proactive_topic_signature(topic, motive)
        semantics: dict[str, Any] = {}
        if isinstance(user, dict):
            semantics = self._proactive_candidate_semantics(
                user,
                reason=reason,
                action=action,
                motive=motive,
                topic=topic,
                source=source,
                context=candidate.get("context"),
                chain=candidate.get("chain") if isinstance(candidate.get("chain"), list) else [],
                trigger_message_id=self._candidate_trigger_message_id(candidate),
                trigger_ts=_safe_float(candidate.get("trigger_ts") or candidate.get("created_ts"), 0),
            )
        semantic_fields = {
            "semantic_kind": _single_line(semantics.get("kind"), 40),
            "semantic_anchor_type": _single_line(semantics.get("anchor_type"), 40),
            "semantic_score": int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.0))) * 100) if semantics else 0,
            "semantic_pressure": int(max(0.0, min(1.0, _safe_float(semantics.get("pressure"), 0.0))) * 100) if semantics else 0,
            "semantic_risk": int(max(0.0, min(1.0, _safe_float(semantics.get("risk"), 0.0))) * 100) if semantics else 0,
            "semantic_note": _single_line(semantics.get("note"), 180),
            "semantic_need_layer": _single_line(semantics.get("need_layer"), 40),
            "semantic_need_drive": _single_line(semantics.get("need_drive"), 80),
            "semantic_need_note": _single_line(semantics.get("need_note"), 120),
            "semantic_need_score_bias": _safe_float(semantics.get("need_score_bias"), 0.0),
            "semantic_need_pressure_bias": _safe_float(semantics.get("need_pressure_bias"), 0.0),
        }
        pool = self._cleanup_proactive_candidate_pool(now=now)
        if status in {"blocked", "accepted"}:
            for existing in reversed(pool):
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("status") or "") != status:
                    continue
                if str(existing.get("user_id") or "") != str(user_id):
                    continue
                if status == "accepted" and str(existing.get("id") or "") == str(candidate.get("id") or ""):
                    continue
                if not self._topic_signature_similar(signature, str(existing.get("signature") or "")):
                    continue
                if now - _safe_float(existing.get("last_seen_ts") or existing.get("created_ts"), 0) > 18 * 3600:
                    continue
                repeat_limit = self._candidate_repeat_count_limit(status)
                previous_repeat = _safe_int(existing.get("repeat_count"), 1, 1)
                existing["repeat_count"] = min(repeat_limit, previous_repeat + 1)
                if previous_repeat + 1 > repeat_limit:
                    existing["repeat_count_capped"] = True
                existing["last_seen_ts"] = now
                existing["scheduled_ts"] = max(_safe_float(existing.get("scheduled_ts"), scheduled), scheduled)
                existing["source"] = source or _single_line(existing.get("source"), 40)
                existing["reason"] = reason or _single_line(existing.get("reason"), 40)
                existing["action"] = action or _single_line(existing.get("action"), 40)
                existing["topic"] = topic or _single_line(existing.get("topic"), 80)
                existing["motive"] = motive or _single_line(existing.get("motive"), 160)
                if note:
                    existing["note"] = _single_line(note, 160)
                existing["score"] = max(_safe_int(existing.get("score"), 0, 0, 100), _safe_int(candidate.get("score"), 0, 0, 100))
                if semantics:
                    existing.update(semantic_fields)
                return existing
        item = {
            "id": uuid.uuid4().hex[:12],
            "created_ts": now,
            "last_seen_ts": now,
            "scheduled_ts": scheduled,
            "user_id": str(user_id),
            "source": source,
            "reason": reason,
            "action": action,
            "topic": topic,
            "motive": motive,
            "score": _safe_int(candidate.get("score"), 0, 0, 100),
            "signature": signature,
            "status": status,
            "note": _single_line(note, 160),
            "repeat_count": 1,
            **(semantic_fields if semantics else {}),
        }
        pool.append(item)
        self._cleanup_proactive_candidate_pool(now=now)
        return item

    def _proactive_candidate_repeated(self, user: dict[str, Any], candidate: dict[str, Any]) -> bool:
        signature = self._proactive_topic_signature(
            candidate.get("topic"),
            candidate.get("motive"),
        )
        if not signature:
            return False
        if self._recent_proactive_topic_repeated(user, signature):
            return True
        now = _now_ts()
        user_id = str(user.get("user_id") or user.get("id") or "")
        for item in self._cleanup_proactive_candidate_pool(now=now):
            if str(item.get("user_id") or "") != user_id:
                continue
            if str(item.get("status") or "") not in {"accepted", "sent"}:
                continue
            if now - _safe_float(item.get("created_ts"), 0) > 8 * 3600:
                continue
            if self._topic_signature_similar(signature, str(item.get("signature") or "")):
                return True
        return False

    def _offer_proactive_candidate(self, user_id: str, user: dict[str, Any], candidate: dict[str, Any]) -> bool:
        user["user_id"] = str(user.get("user_id") or user_id)
        now = _now_ts()
        source = _single_line(candidate.get("source"), 40) or "unknown"
        scheduled = _safe_float(candidate.get("scheduled_ts"), now)
        social_relay_note = self._unverified_social_relay_plan_reason(
            candidate,
            source=source,
            has_trigger=bool(self._candidate_trigger_message_id(candidate)),
        )
        if social_relay_note:
            self._record_proactive_candidate(user_id, candidate, status="blocked", note=social_relay_note, user=user)
            return False
        rest_until = self._proactive_rest_block_until(
            user,
            now=now,
            reason=candidate.get("reason"),
            source=source,
        )
        if rest_until > now and scheduled < rest_until:
            self._record_proactive_candidate(user_id, candidate, status="blocked", note="用户明确休息中", user=user)
            return False
        if not self._user_enabled_for_proactive(str(user_id), user):
            self._clear_pending_proactive_plan(user)
            return False
        silence_reason_getter = getattr(self, "_friend_unanswered_silence_reason", None)
        silence_reason = silence_reason_getter(user, now=now) if callable(silence_reason_getter) else ""
        if silence_reason and source not in {"timer", "troubleshooting", "simulation"}:
            self._record_proactive_candidate(user_id, candidate, status="blocked", note=silence_reason, user=user)
            return False
        if not self._friend_can_receive_proactive_reason(user, candidate.get("reason"), candidate.get("action")):
            return False
        timer_event = self._get_active_llm_timer(user)
        timer_scheduled = _safe_float(timer_event.get("scheduled_ts"), 0) if isinstance(timer_event, dict) else 0.0
        if timer_scheduled > now and scheduled < timer_scheduled and self._in_llm_timer_silence_window(user, now=now):
            self._remember_silenced_candidate_for_timer(user, candidate, now=now)
            self._record_proactive_candidate(user_id, candidate, status="blocked", note="已有聊天临时预约临近", user=user)
            return False
        if _safe_float(user.get("next_proactive_at"), 0) > 0 and self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) == "timer":
            current_timer = self._get_active_llm_timer(user)
            if self._llm_timer_can_use_internal_scheduler(current_timer if isinstance(current_timer, dict) else None):
                self._record_proactive_candidate(user_id, candidate, status="blocked", note="已有用户预约/定时主动", user=user)
                return False
            self._clear_llm_timer_internal_plan_fields(user)
        current_next = _safe_float(user.get("next_proactive_at"), 0)
        if current_next > 0 and current_next <= scheduled:
            self._record_proactive_candidate(user_id, candidate, status="blocked", note="已有更早主动候选", user=user)
            return False
        action = _single_line(candidate.get("action"), 40) or "message"
        if self._private_user_role(user, str(user_id)) == "friend" and self._action_has_photo_text(action):
            action = self._fallback_action_for_unavailable(action, user)
        if self._private_user_role(user, str(user_id)) == "friend":
            sanitized = self._sanitize_friend_proactive_plan_fields(
                user,
                reason=_single_line(candidate.get("reason"), 40) or "check_in",
                action=action,
                topic=_single_line(candidate.get("topic"), 80),
                motive=_single_line(candidate.get("motive"), 180),
            )
            action = sanitized["action"]
            candidate = dict(candidate)
            candidate["reason"] = sanitized["reason"]
            candidate["topic"] = sanitized["topic"]
            candidate["motive"] = sanitized["motive"]
            if self._friend_proactive_candidate_leaks_owner_environment(user, candidate):
                self._record_proactive_candidate(user_id, candidate, status="blocked", note="次要用户不接收主要用户环境/天气分享", user=user)
                return False
        if not self._action_is_available(action, user):
            self._record_proactive_candidate(user_id, candidate, status="blocked", note="动作不可用或媒体额度不足", user=user)
            return False
        if source != "environment_change" and self._proactive_candidate_repeated(user, candidate):
            self._record_proactive_candidate(user_id, candidate, status="blocked", note="近期主题过于相似", user=user)
            return False
        item = self._record_proactive_candidate(user_id, candidate, status="accepted", note="进入主动计划", user=user)
        impulse = self._candidate_to_impulse(user, candidate, source=source, now=now)
        if isinstance(impulse, dict):
            self._queue_proactive_impulse(user, impulse)
        self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = scheduled
        user["planned_proactive_reason"] = self._normalize_legacy_proactive_text(candidate.get("reason"), limit=40) or "check_in"
        user["planned_proactive_action"] = self._normalize_legacy_proactive_text(action, limit=40) or "message"
        user["planned_proactive_source"] = self._normalize_legacy_proactive_text(source, limit=40) or "proactive"
        user["planned_proactive_motive"] = self._normalize_internal_motive_text(
            _single_line(candidate.get("motive"), 180)
        )
        user["planned_proactive_topic"] = _single_line(candidate.get("topic"), 80)
        user["planned_proactive_impulse_id"] = _single_line(impulse.get("id"), 20) if isinstance(impulse, dict) else ""
        user["planned_proactive_window_start_at"] = _safe_float(
            impulse.get("window_start_at"),
            scheduled,
        ) if isinstance(impulse, dict) else scheduled
        user["planned_proactive_best_until_at"] = _safe_float(
            impulse.get("best_until_at"),
            scheduled,
        ) if isinstance(impulse, dict) else scheduled
        user["planned_proactive_expire_at"] = _safe_float(
            impulse.get("expire_at"),
            scheduled,
        ) if isinstance(impulse, dict) else scheduled
        if isinstance(impulse, dict):
            user["planned_proactive_semantic_kind"] = _single_line(impulse.get("semantic_kind"), 40)
            user["planned_proactive_anchor_type"] = _single_line(impulse.get("semantic_anchor_type"), 40)
            user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(impulse.get("semantic_score"), 0.5))) * 100)
            user["planned_proactive_semantic_note"] = _single_line(impulse.get("semantic_note"), 180)
            user["planned_proactive_need_layer"] = _single_line(impulse.get("semantic_need_layer"), 40)
            user["planned_proactive_need_drive"] = _single_line(impulse.get("semantic_need_drive"), 80)
            user["planned_proactive_need_note"] = _single_line(impulse.get("semantic_need_note"), 120)
        else:
            semantics = self._planned_proactive_semantics(user)
            user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
            user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
            user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
            user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
            user["planned_proactive_need_layer"] = _single_line(semantics.get("need_layer"), 40)
            user["planned_proactive_need_drive"] = _single_line(semantics.get("need_drive"), 80)
            user["planned_proactive_need_note"] = _single_line(semantics.get("need_note"), 120)
        user["planned_event_chain"] = [] if self._private_user_role(user) == "friend" else (
            [dict(step) for step in impulse.get("chain", []) if isinstance(step, dict)]
            if isinstance(impulse, dict)
            else []
        )
        user["planned_opener_mode"] = _single_line(impulse.get("opener_mode"), 24) if isinstance(impulse, dict) else ""
        user["planned_followup_kind"] = _single_line(impulse.get("followup_kind"), 32) if isinstance(impulse, dict) else ""
        self._clear_planned_proactive_trigger(user)
        user["planned_proactive_quota_exempt"] = False
        user["planned_candidate_id"] = item.get("id", "")
        self._set_planned_proactive_trigger(
            user,
            message_id=self._candidate_trigger_message_id(candidate),
            umo=_single_line(candidate.get("trigger_umo") or candidate.get("umo"), 160),
            created_at=_safe_float(candidate.get("trigger_ts") or candidate.get("created_ts"), 0),
        )
        context_key = _single_line(candidate.get("context_key"), 60)
        context = candidate.get("context")
        if context_key and isinstance(context, dict):
            user[context_key] = context
        return True

    def _llm_timer_pre_silence_seconds(self) -> float:
        return max(0.0, float(getattr(self, "timer_pre_silence_minutes", 20) or 0) * 60.0)

    def _upcoming_llm_timer_ts(self, user: dict[str, Any], *, now: float | None = None) -> float:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return 0.0
        scheduled_ts = _safe_float(event.get("scheduled_ts"), 0)
        check_now = _now_ts() if now is None else now
        return scheduled_ts if scheduled_ts > check_now else 0.0

    def _in_llm_timer_pre_silence_window(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        lead = self._llm_timer_pre_silence_seconds()
        if lead <= 0:
            return False
        check_now = _now_ts() if now is None else now
        timer_ts = self._upcoming_llm_timer_ts(user, now=check_now)
        return timer_ts > 0 and 0 < timer_ts - check_now <= lead

    def _in_llm_timer_silence_window(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return False
        check_now = _now_ts() if now is None else now
        scheduled_ts = _safe_float(event.get("scheduled_ts"), 0)
        if scheduled_ts <= check_now:
            return False
        if bool(event.get("silence_until_due")):
            return True
        return self._in_llm_timer_pre_silence_window(user, now=check_now)

    def _remember_silenced_plan_for_timer(self, user: dict[str, Any], *, now: float | None = None) -> None:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return
        planned_source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        if planned_source == "timer":
            return
        topic = _single_line(user.get("planned_proactive_topic"), 80)
        motive = _single_line(user.get("planned_proactive_motive"), 160)
        reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        action = self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=32)
        if not any((topic, motive, reason)):
            return
        existing = event.get("deferred_context")
        if isinstance(existing, dict) and existing:
            return
        event["deferred_context"] = {
            "created_at": now or _now_ts(),
            "reason": reason,
            "action": action,
            "topic": topic,
            "motive": self._normalize_internal_motive_text(motive),
            "source": planned_source,
        }

    def _remember_silenced_candidate_for_timer(
        self,
        user: dict[str, Any],
        candidate: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return
        existing = event.get("deferred_context")
        if isinstance(existing, dict) and existing:
            return
        topic = _single_line(candidate.get("topic"), 80)
        motive = _single_line(candidate.get("motive"), 160)
        reason = _single_line(candidate.get("reason"), 40)
        action = _single_line(candidate.get("action"), 32)
        if not any((topic, motive, reason)):
            return
        event["deferred_context"] = {
            "created_at": now or _now_ts(),
            "reason": reason,
            "action": action,
            "topic": topic,
            "motive": self._normalize_internal_motive_text(motive),
            "source": _single_line(candidate.get("source"), 40),
        }

    def _promote_due_llm_timer_plan(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return False
        if not self._llm_timer_can_use_internal_scheduler(event):
            return False
        check_now = _now_ts() if now is None else now
        scheduled_ts = _safe_float(event.get("scheduled_ts"), 0)
        if scheduled_ts <= 0 or scheduled_ts > check_now:
            return False
        if self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) != "timer":
            self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = scheduled_ts
        user["planned_proactive_reason"] = self._normalize_legacy_proactive_text(event.get("reason"), limit=40) or "check_in"
        user["planned_proactive_action"] = self._normalize_legacy_proactive_text(event.get("action"), limit=24) or "message"
        user["planned_proactive_source"] = "timer"
        user["planned_proactive_motive"] = self._normalize_internal_motive_text(_single_line(event.get("motive"), 140))
        user["planned_proactive_topic"] = _single_line(event.get("topic"), 60)
        user["planned_proactive_impulse_id"] = ""
        user["planned_proactive_window_start_at"] = scheduled_ts
        active_span, grace_span = self._proactive_impulse_default_window_seconds(user["planned_proactive_reason"])
        user["planned_proactive_best_until_at"] = scheduled_ts + active_span
        user["planned_proactive_expire_at"] = scheduled_ts + active_span + grace_span
        semantics = self._planned_proactive_semantics(user)
        user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
        user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
        user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
        user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
        user["planned_proactive_need_layer"] = _single_line(semantics.get("need_layer"), 40)
        user["planned_proactive_need_drive"] = _single_line(semantics.get("need_drive"), 80)
        user["planned_proactive_need_note"] = _single_line(semantics.get("need_note"), 120)
        user["planned_event_chain"] = [] if self._private_user_role(user) == "friend" else (
            list(event.get("chain") or []) if isinstance(event.get("chain"), list) else []
        )
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = False
        self._set_planned_proactive_trigger(
            user,
            message_id=_single_line(event.get("trigger_message_id"), 120),
            umo=_single_line(event.get("trigger_umo"), 160),
            created_at=_safe_float(event.get("trigger_ts"), 0),
        )
        return True

    def _promote_upcoming_llm_timer_plan(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        event = self._get_active_llm_timer(user)
        if not isinstance(event, dict):
            return False
        if not self._llm_timer_can_use_internal_scheduler(event):
            return False
        check_now = _now_ts() if now is None else now
        scheduled_ts = _safe_float(event.get("scheduled_ts"), 0)
        if scheduled_ts <= check_now:
            return False
        if self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) != "timer":
            self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = scheduled_ts
        user["planned_proactive_reason"] = self._normalize_legacy_proactive_text(event.get("reason"), limit=40) or "check_in"
        user["planned_proactive_action"] = self._normalize_legacy_proactive_text(event.get("action"), limit=24) or "message"
        user["planned_proactive_source"] = "timer"
        user["planned_proactive_motive"] = self._normalize_internal_motive_text(_single_line(event.get("motive"), 140))
        user["planned_proactive_topic"] = _single_line(event.get("topic"), 60)
        user["planned_proactive_impulse_id"] = ""
        user["planned_proactive_window_start_at"] = scheduled_ts
        active_span, grace_span = self._proactive_impulse_default_window_seconds(user["planned_proactive_reason"])
        user["planned_proactive_best_until_at"] = scheduled_ts + active_span
        user["planned_proactive_expire_at"] = scheduled_ts + active_span + grace_span
        semantics = self._planned_proactive_semantics(user)
        user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
        user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
        user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
        user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
        user["planned_proactive_need_layer"] = _single_line(semantics.get("need_layer"), 40)
        user["planned_proactive_need_drive"] = _single_line(semantics.get("need_drive"), 80)
        user["planned_proactive_need_note"] = _single_line(semantics.get("need_note"), 120)
        user["planned_event_chain"] = [] if self._private_user_role(user) == "friend" else (
            list(event.get("chain") or []) if isinstance(event.get("chain"), list) else []
        )
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = False
        self._set_planned_proactive_trigger(
            user,
            message_id=_single_line(event.get("trigger_message_id"), 120),
            umo=_single_line(event.get("trigger_umo"), 160),
            created_at=_safe_float(event.get("trigger_ts"), 0),
        )
        return True

    def _should_send(self, user: dict[str, Any]) -> tuple[bool, str]:
        if self._tls_native_random_attempt_blocked(user.get('umo'), user.get('planned_proactive_source'), user):
            self._tls_native_random_quarantine(user)
            return False, 'tls_native_random_owner'
        self._recover_stale_proactive_sending(user)
        user_id = str(user.get("user_id") or user.get("id") or "")
        planned_source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        is_troubleshooting = planned_source == "troubleshooting"
        if not self._user_enabled_for_proactive(user_id, user):
            self._clear_pending_proactive_plan(user)
            return False, "私聊对象未启用"
        if self._proactive_generation_disabled(user):
            self._suspend_user_proactive_generation(user)
            reason_formatter = getattr(self, "_format_daily_limit_disabled_reason", None)
            if callable(reason_formatter):
                return False, reason_formatter(user)
            return False, "每日上限为 0，主动生成已停止"
        if user.get("proactive_sending"):
            return False, "上一条主动消息仍在发送中"
        umo_filled = False
        filler = getattr(self, "_ensure_private_user_umo", None)
        if callable(filler):
            try:
                umo_filled = bool(filler(user_id, user))
            except Exception:
                umo_filled = False
        if not user.get("umo"):
            return False, "缺少私聊会话"
        if umo_filled:
            logger.info(
                "[PrivateCompanion] 已为主动私聊对象补全 UMO: user=%s umo=%s",
                _single_line(user_id, 40),
                _single_line(user.get("umo"), 120),
            )
        daily_limit = self._effective_user_daily_limit(user)
        if daily_limit <= 0:
            reason_formatter = getattr(self, "_format_daily_limit_disabled_reason", None)
            if callable(reason_formatter):
                return False, reason_formatter(user)
            return False, "每日上限为 0"
        now = _now_ts()
        companion_block = self._companion_frequency_block_reason(user, now=now)
        if companion_block:
            return False, companion_block
        if self._simulation_active(user):
            return self._should_send_simulation(user)
        due_timer_active = self._has_due_llm_timer(user, now=now)
        if not is_troubleshooting and planned_source == "timer" and not due_timer_active:
            self._clear_llm_timer_internal_plan_fields(user)
            if _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now)
            return False, "对话临时预约已交给官方定时计划"
        silence_reason_getter = getattr(self, "_friend_unanswered_silence_reason", None)
        silence_reason = silence_reason_getter(user, now=now) if callable(silence_reason_getter) else ""
        if (
            silence_reason
            and not is_troubleshooting
            and not due_timer_active
            and planned_source not in {"timer", "simulation"}
        ):
            blocker = getattr(self, "_block_friend_unanswered_pending_proactive", None)
            if callable(blocker):
                blocker(user, note=silence_reason, now=now)
            self._mark_planned_candidate_status(user, "blocked", silence_reason)
            self._clear_pending_proactive_plan(user)
            return False, silence_reason
        if (
            not is_troubleshooting
            and
            self._proactive_rest_block_until(
                user,
                now=now,
                reason=user.get("planned_proactive_reason"),
                source=planned_source,
            ) > now
            and not due_timer_active
        ):
            return False, "用户明确休息中"
        planned_reason = _single_line(user.get("planned_proactive_reason"), 40)
        if (
            not is_troubleshooting
            and planned_reason != "sleep_murmur"  # 梦话本来就发生在静默时段（凌晨3-4点）
            and self._is_quiet_time()
            and not self._can_send_insomnia_night_message(user)
        ):
            return False, "免打扰时段"
        pre_gate_next_at = _safe_float(user.get("next_proactive_at"), 0)
        if not is_troubleshooting and not due_timer_active:
            if pre_gate_next_at <= 0:
                self._schedule_next_proactive(user, now=now)
                return False, "已安排下一次候选主动时间"
            if now < pre_gate_next_at:
                return False, "未到候选主动时间"
        rel_state = user.get("relationship_state")
        relationship_blocked = (
            not is_troubleshooting
            and
            self.enable_relationship_state_machine
            and isinstance(rel_state, dict)
            and rel_state.get("mode") == "backoff"
            and _safe_float(rel_state.get("backoff_until"), 0) > _now_ts()
        )
        emotion_blocked = (
            not is_troubleshooting
            and
            bool(getattr(self, "enable_emotion_simulation", True))
            and isinstance(rel_state, dict)
            and rel_state.get("mode") in {"hurt", "refusing"}
            and _safe_float(rel_state.get("hurt_until"), 0) > _now_ts()
        )
        if relationship_blocked or emotion_blocked:
            gate_until = max(
                _safe_float(rel_state.get("hurt_until"), 0),
                _safe_float(rel_state.get("backoff_until"), 0),
            )
            before_next_at = _safe_float(user.get("next_proactive_at"), 0)
            adjuster = getattr(self, "_defer_or_clean_emotion_blocked_plan", None)
            if callable(adjuster):
                adjusted_reason = adjuster(user, now=now)
            else:
                adjusted_reason = "情绪/关系状态处于收敛期"
            after_next_at = _safe_float(user.get("next_proactive_at"), 0)
            if after_next_at <= now and gate_until > now:
                after_next_at = gate_until + random.uniform(15 * 60, 75 * 60)
                user["next_proactive_at"] = after_next_at
                user["planned_proactive_window_start_at"] = after_next_at
                user["planned_proactive_best_until_at"] = after_next_at + 45 * 60
                user["planned_proactive_expire_at"] = after_next_at + 90 * 60
            logger.info(
                "[PrivateCompanion] 情绪/关系闸门拦截主动: user=%s mode=%s score=%s gate_until=%s reason=%s",
                _single_line(user.get("user_id") or user.get("umo") or user.get("nickname"), 80),
                _single_line(rel_state.get("mode"), 24),
                _safe_int(rel_state.get("mood_score"), 0, -100, 100),
                int(gate_until),
                _single_line(
                    rel_state.get("last_hurt_reason")
                    or rel_state.get("last_backoff_reason")
                    or rel_state.get("last_emotion_reason"),
                    80,
                ),
            )
            return False, adjusted_reason

        planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        if due_timer_active and planned_source != "timer":
            self._promote_due_llm_timer_plan(user, now=now)
            planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
            planned_source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) or planned_source
        next_at = _safe_float(user.get("next_proactive_at"), 0)
        planned_impulse_id = _single_line(user.get("planned_proactive_impulse_id"), 20)
        planned_expire_at = _safe_float(user.get("planned_proactive_expire_at"), 0)
        if (
            not is_troubleshooting
            and planned_impulse_id
            and planned_expire_at > 0
            and now > planned_expire_at
            and not due_timer_active
        ):
            self._mark_planned_candidate_status(user, "blocked", "潜在念头窗口已过期")
            self._clear_pending_proactive_plan(user)
            if not self._materialize_best_proactive_impulse(user, now=now):
                self._schedule_next_proactive(user, now=now, delay_hours=(1.0, 3.0))
            return False, "原主动念头已过期,已重新挑选"
        if next_at <= 0:
            self._schedule_next_proactive(user, now=now)
            return False, "已安排下一次候选主动时间"
        impulse_value = self._planned_impulse_value(user, now=now)
        window_phase, window_detail = self._planned_impulse_window_phase(user, now=now)
        if (
            not is_troubleshooting
            and planned_impulse_id
            and window_phase == "tail"
            and impulse_value < 0.58
            and not due_timer_active
        ):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="低价值念头已过最佳表达窗口",
                delay_minutes=(45, 120),
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(1.0, 3.0))
            return False, "低价值念头已过最佳窗口,已重新挑选"
        if not is_troubleshooting and self._promote_earlier_daily_greeting_event(user, now=now):
            planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
            next_at = _safe_float(user.get("next_proactive_at"), 0)
            impulse_value = self._planned_impulse_value(user, now=now)
            window_phase, window_detail = self._planned_impulse_window_phase(user, now=now)
        if (
            not is_troubleshooting
            and
            not due_timer_active
            and planned_source != "timer"
            and self._in_llm_timer_silence_window(user, now=now)
        ):
            self._remember_silenced_plan_for_timer(user, now=now)
            self._promote_upcoming_llm_timer_plan(user, now=now)
            return False, "用户预约静默窗口"
        if now < next_at:
            return False, "未到候选主动时间"
        delivery = self._ensure_planned_proactive_delivery_state(user, now=now)
        if (
            not is_troubleshooting
            and not due_timer_active
            and _single_line(delivery.get("freshness"), 24) == "immediate"
            and _safe_float(delivery.get("best_until_at"), 0) > 0
            and now > _safe_float(delivery.get("best_until_at"), 0)
        ):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="即时主动已越过自然表达窗口",
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(1.0, 3.0))
            return False, "即时主动已越过自然表达窗口,已重新挑选"
        if not is_troubleshooting and self._is_proactive_plan_stale(user, now=now) and not due_timer_active:
            self._clear_pending_proactive_plan(user)
            self._schedule_next_proactive(user, now=now, delay_hours=(1, 4))
            return False, "候选主动计划已过期,已重新安排"
        inner_readiness = self._proactive_inner_readiness(user, now=now)
        inner_score = _safe_float(inner_readiness.get("score"), 0.55)
        if (
            not is_troubleshooting
            and not due_timer_active
            and planned_source != "timer"
            and inner_score < 0.36
            and impulse_value < 0.72
        ):
            delay_low = 90 if self._private_user_role(user) != "friend" else 240
            self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="Bot 状态/关系温度偏低,这个念头先忍住: " + _single_line(inner_readiness.get("detail"), 120),
                delay_minutes=(delay_low, delay_low + 150),
                block_current=False,
            )
            if _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2.0, 6.0))
            return False, "Bot 状态/关系温度偏低,主动念头先收住"
        social_relay_note = self._unverified_social_relay_plan_reason(
            user,
            source=planned_source,
            has_trigger=bool(_single_line(user.get("planned_proactive_trigger_message_id"), 120)),
        )
        if not is_troubleshooting and social_relay_note:
            self._mark_planned_candidate_status(user, "blocked", social_relay_note)
            self._clear_pending_proactive_plan(user)
            self._schedule_next_proactive(user, now=now, delay_hours=(1.5, 4.5))
            return False, social_relay_note
        suppressed_raw = user.get("greetings_suppressed_by_inbound", [])
        suppressed_greetings: set[str] = set()
        if isinstance(suppressed_raw, list):
            suppressed_greetings = {str(item).strip() for item in suppressed_raw if str(item).strip()}
        if (
            not is_troubleshooting
            and planned_reason in suppressed_greetings
            and self._is_greeting_reason(planned_reason)
            and not self._is_initial_wakeup_greeting(user)
            and planned_source != "timer"
            and not due_timer_active
        ):
            self._mark_planned_candidate_status(user, "blocked", "用户在该问候窗口内已经活跃过")
            self._clear_pending_proactive_plan(user)
            self._schedule_next_proactive(user, now=now, delay_hours=(2, 5))
            return False, "用户在该问候窗口内已经活跃过"
        self._reset_daily_counter_if_needed(user)
        sent_today = _safe_int(user.get("sent_today"), 0)
        if (
            not is_troubleshooting
            and planned_reason == "morning_greeting"
            and planned_source != "timer"
            and not due_timer_active
            and sent_today > 0
        ):
            self._mark_planned_candidate_status(user, "blocked", "早安只适合作为当天第一句主动消息")
            self._clear_pending_proactive_plan(user)
            self._schedule_next_proactive(user, now=now, delay_hours=(2, 5))
            return False, "早安只适合作为当天第一句主动消息"
        if (
            not is_troubleshooting
            and not self._proactive_daily_limit_is_unlimited(daily_limit)
            and _safe_int(user.get("sent_today"), 0) >= daily_limit
        ):
            if not due_timer_active:
                self._schedule_next_proactive(user, now=now, delay_hours=(8, 16))
            return False, "已达每日上限"
        idle_minutes = self._effective_user_idle_minutes(user)
        recent_activity_at = self._latest_private_user_activity_ts(user)
        if (
            not is_troubleshooting
            and not due_timer_active
            and not self._is_initial_wakeup_greeting(user)
            and now - recent_activity_at < idle_minutes * 60
        ):
            idle_limit = (
                self._effective_user_greeting_idle_minutes(user) * 60
                if self._is_greeting_reason(planned_reason)
                else idle_minutes * 60
            )
            if now - recent_activity_at < idle_limit:
                if self._is_sticky_greeting_reason(planned_reason):
                    self._reschedule_greeting_within_window(user, planned_reason, now=now)
                else:
                    replaced = self._defer_or_replace_planned_impulse(
                        user,
                        now=now,
                        note="用户刚活跃过,当前念头先收住",
                        delay_minutes=(max(8.0, idle_limit / 60 * 0.5), max(15.0, idle_limit / 60 + 8.0)),
                        block_current=impulse_value < 0.52,
                    )
                    if replaced:
                        return False, "用户刚活跃过,已换用更贴近当前节奏的念头"
                return False, "用户刚活跃过"
        min_interval = self._effective_min_interval_seconds(user)
        if self._is_greeting_reason(planned_reason) and self._private_user_role(user) != "friend":
            min_interval = min(min_interval, self._greeting_min_interval_seconds(planned_reason))
        if not is_troubleshooting and not due_timer_active and now - _safe_float(user.get("last_sent"), 0) < min_interval:
            if self._is_sticky_greeting_reason(planned_reason):
                self._reschedule_greeting_within_window(user, planned_reason, now=now)
            else:
                remaining_minutes = max(5.0, (min_interval - (now - _safe_float(user.get("last_sent"), 0))) / 60)
                self._defer_or_replace_planned_impulse(
                    user,
                    now=now,
                    note="距离上次主动太近,当前念头先压低",
                    delay_minutes=(remaining_minutes, remaining_minutes + 30.0),
                    block_current=False,
                )
            return False, "发送间隔不足"
        planned_action = str(user.get("planned_proactive_action") or "message")
        normalizer = getattr(self, "_normalize_existing_plan_for_emotion", None)
        if not is_troubleshooting and callable(normalizer):
            emotion_note = normalizer(user, now=now)
            if emotion_note:
                planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40) or planned_reason
                planned_action = self._normalize_legacy_proactive_text(user.get("planned_proactive_action"), limit=40) or planned_action or "message"
                if _safe_float(user.get("next_proactive_at"), 0) > now + 1:
                    return False, emotion_note
        if not is_troubleshooting and self._private_user_role(user) == "friend":
            before_friend_sanitize = (
                planned_reason,
                planned_action,
                _single_line(user.get("planned_proactive_topic"), 80),
                _single_line(user.get("planned_proactive_motive"), 180),
            )
            sanitized = self._sanitize_friend_proactive_plan_fields(
                user,
                reason=planned_reason,
                action=planned_action,
                topic=_single_line(user.get("planned_proactive_topic"), 80),
                motive=_single_line(user.get("planned_proactive_motive"), 180),
            )
            user["planned_proactive_reason"] = sanitized["reason"]
            user["planned_proactive_action"] = sanitized["action"]
            user["planned_proactive_topic"] = sanitized["topic"]
            user["planned_proactive_motive"] = sanitized["motive"]
            planned_reason = sanitized["reason"]
            planned_action = sanitized["action"]
            after_friend_sanitize = (
                planned_reason,
                planned_action,
                sanitized["topic"],
                sanitized["motive"],
            )
            if after_friend_sanitize != before_friend_sanitize:
                user["planned_proactive_impulse_id"] = ""
                user["planned_proactive_semantic_kind"] = ""
                user["planned_proactive_anchor_type"] = ""
                user["planned_proactive_semantic_score"] = 0
                user["planned_proactive_semantic_note"] = ""
                user["planned_proactive_need_layer"] = ""
                user["planned_proactive_need_drive"] = ""
                user["planned_proactive_need_note"] = ""
                user["planned_proactive_model_judge_signature"] = ""
                user["planned_proactive_model_judge_result"] = {}
                user["planned_proactive_model_judge_at"] = 0
                self._mark_planned_candidate_status(user, "accepted", "次要用户未回应状态下已降级为低压主动")
        if not is_troubleshooting and not self._friend_can_receive_proactive_reason(user, planned_reason, planned_action):
            self._clear_pending_proactive_plan(user)
            self._schedule_next_proactive(user, now=now, delay_hours=(2, 6))
            return False, "次要用户关系不接收敏感主动"
        planned_semantics = self._planned_proactive_semantics(user)
        semantic_score = _safe_float(planned_semantics.get("score"), 0.5)
        semantic_pressure = _safe_float(planned_semantics.get("pressure"), 0.4)
        semantic_risk = _safe_float(planned_semantics.get("risk"), 0.0)
        semantic_blocked = bool(planned_semantics.get("blocker"))
        if (
            not is_troubleshooting
            and not due_timer_active
            and planned_source != "timer"
            and (semantic_blocked or semantic_risk >= 0.45 or (semantic_score < 0.32 and semantic_pressure >= 0.58))
        ):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="候选语义不够自然: " + _single_line(planned_semantics.get("note"), 120),
                delay_minutes=(90, 240),
                block_current=semantic_blocked or semantic_risk >= 0.45,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2, 6))
            return False, "候选语义不够自然,已重新挑选"
        persona_alignment = self._planned_proactive_persona_alignment(user, now=now)
        persona_fit = _safe_float(persona_alignment.get("score"), 0.55)
        persona_blocked = bool(persona_alignment.get("blocker"))
        persona_threshold = 0.48 if self._private_user_role(user) == "friend" else 0.42
        if (
            not is_troubleshooting
            and not due_timer_active
            and planned_source != "timer"
            and (persona_blocked or persona_fit < persona_threshold)
        ):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="人格/世界观贴合度不足: " + _single_line(persona_alignment.get("note"), 120),
                delay_minutes=(90, 240),
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2, 6))
            return False, "人格/世界观贴合度不足,已重新挑选"
        if due_timer_active:
            return True, "ok(timer)"
        ignored_streak = _safe_int(user.get("ignored_streak"), 0, 0)
        if (
            not is_troubleshooting
            and ignored_streak >= 2
            and impulse_value < (0.72 if self._private_user_role(user) == "friend" else 0.66)
        ):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note=f"连续 {ignored_streak} 次未回应,低压念头先不打扰",
                delay_minutes=(90, 240),
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2.5, 6.0))
            return False, "连续未回应,低价值主动已收住"
        if not is_troubleshooting and not self._is_reason_allowed_now(planned_reason):
            if self._is_sticky_greeting_reason(planned_reason):
                self._reschedule_greeting_within_window(user, planned_reason, now=now)
                return False, "问候仍在窗口内,稍后再试"
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="计划动机不适合当前时间",
                delay_minutes=(45, 150),
                block_current=window_phase == "tail" or impulse_value < 0.6,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now)
            return False, "计划动机不适合当前时间"
        if self._private_user_role(user) == "friend" and self._action_has_photo_text(planned_action):
            fallback_action = self._fallback_action_for_unavailable(planned_action, user)
            if fallback_action != planned_action:
                planned_action = fallback_action
                user["planned_proactive_action"] = planned_action
        if not self._action_is_available(planned_action, user):
            load_defer_note = self._photo_text_load_defer_note(planned_action)
            if load_defer_note:
                self._defer_planned_photo_text_for_load(user, now=now, note=load_defer_note)
                return False, load_defer_note
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="动作不可用或媒体额度不足",
                delay_minutes=(90, 240),
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2, 6))
            return False, "动作不可用或媒体额度不足"
        if not is_troubleshooting and self._planned_proactive_recently_repeated(user):
            replaced = self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="近期主题过于相似",
                delay_minutes=(120, 360),
                block_current=True,
            )
            if not replaced and _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=(2, 6))
            return False, "近期主动主题过于相似"
        if not is_troubleshooting and self._planned_event_exceeds_daypart_cap(user, planned_reason, next_at):
            delay = self._friend_proactive_spread_delay_hours(user, now=now)
            if delay is None:
                delay = (7.5, 10.5) if self._proactive_daypart_bucket_for_timestamp(next_at) == "late_night" else (2.5, 5.0)
            self._defer_or_replace_planned_impulse(
                user,
                now=now,
                note="当前时段主动已足够",
                delay_minutes=(delay[0] * 60, delay[1] * 60),
                block_current=False,
            )
            if _safe_float(user.get("next_proactive_at"), 0) <= 0:
                self._schedule_next_proactive(user, now=now, delay_hours=delay)
            if self._private_user_role(user) == "friend":
                return False, "朋友主动已按日内节奏延后"
            return False, "当前时段主动已足够,已避开扎堆"
        return True, "ok"

    def _planned_proactive_signature(self, user: dict[str, Any]) -> str:
        return self._proactive_topic_signature(
            user.get("planned_proactive_topic"),
            user.get("planned_proactive_motive"),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40),
            self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40),
        )

    def _planned_proactive_recently_repeated(self, user: dict[str, Any]) -> bool:
        signature = self._planned_proactive_signature(user)
        if not signature:
            return False
        return self._recent_proactive_topic_repeated(user, signature)

    def _unverified_social_relay_plan_reason(
        self,
        item: dict[str, Any],
        *,
        source: str = "",
        has_trigger: bool = False,
    ) -> str:
        if not isinstance(item, dict):
            return ""
        normalized_source = self._normalize_legacy_proactive_text(source or item.get("source") or item.get("planned_proactive_source"), limit=40)
        if normalized_source in {"timer", "troubleshooting", "simulation", "group_share"}:
            return ""
        if has_trigger:
            return ""
        reason = self._normalize_legacy_proactive_text(item.get("reason") or item.get("planned_proactive_reason"), limit=40)
        if reason in {"group_share", "news_share", "bili_video_share", "web_exploration_share"}:
            return ""
        if normalized_source not in {"event", "random", "unknown", ""}:
            return ""
        text = " ".join(
            _single_line(item.get(key), 180)
            for key in (
                "topic",
                "planned_proactive_topic",
                "motive",
                "planned_proactive_motive",
                "why",
                "scene",
                "impulse",
            )
            if _single_line(item.get(key), 180)
        )
        if not text:
            return ""
        relay_markers = ("转达", "转述", "转告", "带话", "捎话")
        if any(token in text for token in relay_markers):
            return "疑似第三方转述/带话内容,缺少真实触发来源"
        invite_markers = ("约", "邀请", "要不要去", "去不去", "一起", "夜宵", "吃饭", "见面", "碰头")
        soft_message_markers = ("留言", "说一声", "说一下", "告诉你一声", "通知你一声")
        third_party_patterns = (
            r"[\u4e00-\u9fffA-Za-z0-9_]{1,12}(?:说|问|发(?:来|了|的)?(?:消息)?|留言|约|邀请)",
            r"(?:他|她|TA|ta)(?:说|问|发(?:来|了|的)?|留言|约|邀请)",
            r"(?:他的|她的|TA的|ta的).{0,8}(?:消息|留言|邀约|邀请)",
        )
        has_third_party_signal = any(re.search(pattern, text) for pattern in third_party_patterns)
        if has_third_party_signal and any(token in text for token in soft_message_markers):
            return "疑似第三方留言/带话内容,缺少真实触发来源"
        if any(token in text for token in invite_markers) and has_third_party_signal:
            return "疑似第三方邀约内容,缺少真实触发来源"
        return ""

    def _planned_proactive_status_snapshot(self, user: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(user, dict):
            return {}
        keys = (
            "planned_candidate_id",
            "planned_proactive_impulse_id",
            "planned_proactive_reason",
            "planned_proactive_action",
            "planned_proactive_source",
            "planned_proactive_motive",
            "planned_proactive_topic",
            "planned_proactive_semantic_kind",
            "planned_proactive_anchor_type",
            "planned_proactive_semantic_score",
            "planned_proactive_semantic_note",
            "planned_proactive_need_layer",
            "planned_proactive_need_drive",
            "planned_proactive_need_note",
        )
        return {key: user.get(key) for key in keys}

    def _mark_planned_candidate_status(
        self,
        user: dict[str, Any],
        status: str,
        note: str = "",
        *,
        planned_snapshot: dict[str, Any] | None = None,
    ) -> None:
        restored_values: dict[str, Any] = {}
        if isinstance(planned_snapshot, dict) and planned_snapshot:
            for key, value in planned_snapshot.items():
                if value in (None, "", {}, []):
                    continue
                restored_values[key] = user.get(key)
                user[key] = value
        try:
            outcome_recorder = getattr(self, "_note_proactive_afterglow_outcome", None)
            if callable(outcome_recorder):
                try:
                    outcome_recorder(user, status=status, note=note)
                except Exception as exc:
                    logger.debug("[PrivateCompanion] 主动结果余韵记录失败: %s", _single_line(exc, 120))
            candidate_id = str(user.get("planned_candidate_id") or "")
            user_id = str(user.get("user_id") or user.get("id") or "")
            if candidate_id:
                for item in self._cleanup_proactive_candidate_pool():
                    if str(item.get("id") or "") == candidate_id:
                        item["status"] = status
                        item["note"] = _single_line(note, 160)
                        item["updated_ts"] = _now_ts()
                        break
            impulse_id = _single_line(user.get("planned_proactive_impulse_id"), 20)
            if not impulse_id:
                return
            for impulse in self._cleanup_proactive_impulses(user):
                if _single_line(impulse.get("id"), 20) != impulse_id:
                    continue
                impulse["updated_ts"] = _now_ts()
                impulse["last_status"] = _single_line(status, 24)
                impulse["last_note"] = _single_line(note, 160)
                if status in {"sent"}:
                    impulse["state"] = "sent"
                elif status in {"blocked", "cancelled", "dropped"}:
                    impulse["state"] = "blocked"
                elif status == "deferred":
                    impulse["state"] = "deferred"
                    next_at = _safe_float(user.get("next_proactive_at"), 0)
                    if next_at > 0:
                        impulse["window_start_at"] = next_at
                        impulse["preferred_ts"] = max(_safe_float(impulse.get("preferred_ts"), 0), next_at)
                        impulse["best_until_at"] = max(_safe_float(impulse.get("best_until_at"), 0), next_at + 20 * 60)
                        impulse["expire_at"] = max(_safe_float(impulse.get("expire_at"), 0), impulse["best_until_at"] + 40 * 60)
                else:
                    impulse["state"] = "queued"
                break
            is_send_retry_deferred = status == "deferred" and (
                "已保留待重发内容" in str(note or "") or "平台发送" in str(note or "")
            )
            if user_id and status in {"blocked", "cancelled", "dropped", "failed", "deferred"} and not is_send_retry_deferred:
                self._shrink_user_proactive_candidates(user_id, note=note)
        finally:
            for key, value in restored_values.items():
                user[key] = value

    def _proactive_decision_factors(self, user: dict[str, Any], *, now: float | None = None) -> list[dict[str, Any]]:
        now = _now_ts() if now is None else now
        factors: list[dict[str, Any]] = []

        def add(
            key: str,
            label: str,
            passed: bool,
            score: int,
            detail: str = "",
            *,
            blocker: bool = False,
        ) -> None:
            factors.append(
                {
                    "key": key,
                    "label": label,
                    "passed": bool(passed),
                    "score": int(score),
                    "detail": _single_line(detail, 160),
                    "blocker": bool(blocker),
                }
            )

        user_id = str(user.get("user_id") or user.get("id") or "")
        enabled = self._user_enabled_for_proactive(user_id, user)
        add("enabled", "用户启用", enabled, 18 if enabled else -80, "已启用" if enabled else "私聊对象未启用", blocker=not enabled)

        has_session = bool(user.get("umo"))
        add("session", "私聊会话", has_session, 12 if has_session else -70, "会话可用" if has_session else "缺少私聊会话", blocker=not has_session)

        if user.get("proactive_sending"):
            add("sending", "发送占用", False, -60, "上一条主动消息仍在发送中", blocker=True)
        else:
            add("sending", "发送占用", True, 6, "当前没有发送占用")

        daily_limit = self._effective_user_daily_limit(user)
        sent_today = _safe_int(user.get("sent_today"), 0)
        unlimited_daily_limit = self._proactive_daily_limit_is_unlimited(daily_limit)
        under_limit = daily_limit > 0 and (unlimited_daily_limit or sent_today < daily_limit)
        daily_limit_text = self._format_proactive_daily_limit(daily_limit)
        if daily_limit <= 0:
            add("daily_limit", "每日上限", False, -55, "每日上限为 0", blocker=True)
        else:
            add(
                "daily_limit",
                "每日上限",
                under_limit,
                8 if under_limit else -40,
                f"{sent_today}/{daily_limit_text}",
                blocker=not under_limit,
            )

        due_timer_active = self._has_due_llm_timer(user, now=now)
        source = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40)
        rest_until = self._proactive_rest_block_until(
            user,
            now=now,
            reason=user.get("planned_proactive_reason"),
            source=source,
        )
        rest_blocked = rest_until > now and not due_timer_active
        add(
            "rest",
            "休息静默",
            not rest_blocked,
            5 if not rest_blocked else -45,
            "未命中静默" if not rest_blocked else "用户明确休息中",
            blocker=rest_blocked,
        )

        quiet_blocked = self._is_quiet_time() and not self._can_send_insomnia_night_message(user)
        add(
            "quiet_hours",
            "免打扰",
            not quiet_blocked,
            4 if not quiet_blocked else -42,
            "当前可发" if not quiet_blocked else "处于免打扰时段",
            blocker=quiet_blocked,
        )

        rel_state = user.get("relationship_state")
        relationship_blocked = (
            self.enable_relationship_state_machine
            and isinstance(rel_state, dict)
            and rel_state.get("mode") == "backoff"
            and _safe_float(rel_state.get("backoff_until"), 0) > now
        )
        emotion_blocked = (
            bool(getattr(self, "enable_emotion_simulation", True))
            and isinstance(rel_state, dict)
            and rel_state.get("mode") in {"hurt", "refusing"}
            and _safe_float(rel_state.get("hurt_until"), 0) > now
        )
        relation_ok = not (relationship_blocked or emotion_blocked)
        relation_detail = "状态平稳"
        if isinstance(rel_state, dict) and rel_state.get("mode"):
            relation_detail = f"mode={_single_line(rel_state.get('mode'), 24)}"
        add(
            "relationship_gate",
            "关系/情绪闸门",
            relation_ok,
            7 if relation_ok else -48,
            relation_detail,
            blocker=not relation_ok,
        )

        next_at = _safe_float(user.get("next_proactive_at"), 0)
        planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        if next_at <= 0:
            add("planned", "候选计划", False, -12, "尚未安排下一次候选")
        else:
            due = now >= next_at
            add(
                "planned",
                "候选计划",
                due,
                10 if due else -10,
                (
                    self._environment_fromtimestamp(next_at).strftime("%m-%d %H:%M:%S")
                    if next_at > 0
                    else "未安排"
                ),
                blocker=False,
            )
        impulse_value = self._planned_impulse_value(user, now=now)
        window_phase, window_detail = self._planned_impulse_window_phase(user, now=now)
        phase_labels = {
            "before": "窗口未开始",
            "best": "最佳窗口",
            "tail": "窗口尾段",
            "expired": "已经过期",
            "unknown": "未记录",
        }
        window_ok = window_phase not in {"expired"}
        add(
            "impulse_window",
            "念头窗口",
            window_ok,
            7 if window_phase == "best" else 2 if window_phase == "tail" else -6 if window_phase == "before" else -35 if window_phase == "expired" else 0,
            f"{phase_labels.get(window_phase, window_phase)}｜{window_detail}",
            blocker=window_phase == "expired",
        )
        add(
            "impulse_value",
            "念头价值",
            impulse_value >= 0.55,
            8 if impulse_value >= 0.85 else 4 if impulse_value >= 0.65 else -8,
            f"{impulse_value:.2f}｜越高越像当前角色真的想说",
            blocker=False,
        )
        inner_readiness = self._proactive_inner_readiness(user, now=now)
        drive = inner_readiness.get("drive") if isinstance(inner_readiness.get("drive"), dict) else {}
        temperature = inner_readiness.get("temperature") if isinstance(inner_readiness.get("temperature"), dict) else {}
        inner_score = _safe_float(inner_readiness.get("score"), 0.55)
        add(
            "bot_drive",
            "Bot 开口欲",
            inner_score >= 0.36,
            7 if inner_score >= 0.72 else 3 if inner_score >= 0.5 else -14,
            f"{inner_score:.2f}｜{_single_line(inner_readiness.get('label'), 40)}｜{_single_line(drive.get('detail'), 70)}",
            blocker=inner_score < 0.28,
        )
        motivation = inner_readiness.get("motivation") if isinstance(inner_readiness.get("motivation"), dict) else {}
        if motivation:
            motivation_score = _safe_float(motivation.get("score"), 0.5)
            add(
                "experimental_motivation",
                "实验动机调度",
                motivation_score >= 0.40,
                6 if motivation_score >= 0.66 else 2 if motivation_score >= 0.50 else -10,
                f"{motivation_score:.2f}｜{_single_line(motivation.get('label'), 24)}｜{_single_line(motivation.get('detail'), 100)}",
                blocker=motivation_score < 0.28,
            )
        temp_score = _safe_float(temperature.get("score"), 0.55)
        add(
            "relationship_temperature",
            "关系温度",
            temp_score >= 0.34,
            7 if temp_score >= 0.7 else 3 if temp_score >= 0.48 else -16,
            f"{temp_score:.2f}｜{_single_line(temperature.get('label'), 24)}｜{_single_line(temperature.get('detail'), 80)}",
            blocker=temp_score < 0.24,
        )
        planned_impulse = self._planned_proactive_impulse(user)
        hesitation_count = _safe_int(planned_impulse.get("hesitation_count"), 0, 0, 20) if isinstance(planned_impulse, dict) else 0
        if hesitation_count > 0:
            add(
                "hesitation_memory",
                "犹豫记忆",
                True,
                min(6, 2 + hesitation_count),
                f"同一候选曾延后 {hesitation_count} 次｜{_single_line(planned_impulse.get('hesitation_note'), 80)}",
                blocker=False,
            )
        semantics = self._planned_proactive_semantics(user)
        semantic_score = _safe_float(semantics.get("score"), 0.5)
        semantic_pressure = _safe_float(semantics.get("pressure"), 0.4)
        semantic_risk = _safe_float(semantics.get("risk"), 0.0)
        semantic_ok = not bool(semantics.get("blocker")) and semantic_risk < 0.45 and not (semantic_score < 0.32 and semantic_pressure >= 0.58)
        add(
            "candidate_semantics",
            "候选语义",
            semantic_ok,
            8 if semantic_score >= 0.68 else 4 if semantic_score >= 0.48 else -18,
            (
                f"{_single_line(semantics.get('kind'), 30)}/{_single_line(semantics.get('anchor_type'), 30)}"
                f"｜语义{semantic_score:.2f} 压力{semantic_pressure:.2f} 风险{semantic_risk:.2f}"
                f"｜{_single_line(semantics.get('note'), 70)}"
            ),
            blocker=not semantic_ok,
        )
        persona_alignment = self._planned_proactive_persona_alignment(user, now=now)
        persona_fit = _safe_float(persona_alignment.get("score"), 0.55)
        persona_threshold = 0.48 if self._private_user_role(user) == "friend" else 0.42
        persona_blocked = bool(persona_alignment.get("blocker")) and source != "timer"
        persona_ok = due_timer_active or source == "timer" or (not persona_blocked and persona_fit >= persona_threshold)
        add(
            "persona_fit",
            "人格/世界观贴合",
            persona_ok,
            8 if persona_fit >= 0.78 else 4 if persona_fit >= 0.58 else -18,
            f"{persona_fit:.2f}｜{_single_line(persona_alignment.get('note'), 110)}",
            blocker=not persona_ok,
        )
        model_signature = self._planned_proactive_model_judge_signature(user)
        model_judgement = self._cached_proactive_model_judgement(user, signature=model_signature, now=now)
        if isinstance(model_judgement, dict):
            model_decision = str(model_judgement.get("decision") or "")
            model_score = _safe_int(model_judgement.get("score"), 0, 0, 100)
            model_ok = model_decision in {"send", "rewrite"}
            add(
                "model_persona_judge",
                "模型人格判定",
                model_ok,
                8 if model_decision == "send" else 4 if model_decision == "rewrite" else -30,
                f"{model_decision or 'unknown'}｜{model_score}/100｜{_single_line(model_judgement.get('reason'), 90)}",
                blocker=not model_ok,
            )
        else:
            add(
                "model_persona_judge",
                "模型人格判定",
                True,
                0,
                "未执行；硬规则通过且到点发送前执行",
                blocker=False,
            )

        last_seen = self._latest_private_user_activity_ts(user)
        idle_minutes = self._effective_user_idle_minutes(user)
        if self._is_greeting_reason(planned_reason):
            idle_minutes = self._effective_user_greeting_idle_minutes(user)
        idle_seconds = max(0, idle_minutes) * 60
        idle_elapsed = now - last_seen if last_seen > 0 else 999999999.0
        idle_passed = due_timer_active or idle_elapsed >= idle_seconds
        add(
            "idle",
            "用户空闲",
            idle_passed,
            9 if idle_passed else -28,
            (
                f"已空闲 {self._format_elapsed(max(0, idle_elapsed))} / 至少 {self._format_elapsed(idle_seconds)}"
                if last_seen > 0
                else "暂无活跃记录"
            ),
            blocker=not idle_passed and not due_timer_active,
        )

        last_sent = _safe_float(user.get("last_sent"), 0)
        min_interval = self._effective_min_interval_seconds(user)
        if self._is_greeting_reason(planned_reason) and self._private_user_role(user) != "friend":
            min_interval = min(min_interval, self._greeting_min_interval_seconds(planned_reason))
        send_elapsed = now - last_sent if last_sent > 0 else 999999999.0
        interval_passed = due_timer_active or send_elapsed >= min_interval
        add(
            "interval",
            "发送间隔",
            interval_passed,
            8 if interval_passed else -25,
            (
                f"已过 {self._format_elapsed(max(0, send_elapsed))} / 至少 {self._format_elapsed(min_interval)}"
                if last_sent > 0
                else "还没有主动发送记录"
            ),
            blocker=not interval_passed and not due_timer_active,
        )

        if planned_reason:
            reason_allowed = due_timer_active or self._is_reason_allowed_now(planned_reason)
            add(
                "reason_window",
                "时段适配",
                reason_allowed,
                6 if reason_allowed else -18,
                planned_reason,
                blocker=not reason_allowed and not due_timer_active,
            )

        planned_action = str(user.get("planned_proactive_action") or "message")
        action_ok = self._action_is_available(planned_action, user)
        add(
            "action",
            "动作可用",
            action_ok,
            6 if action_ok else -24,
            planned_action or "message",
            blocker=not action_ok,
        )

        repeated = self._planned_proactive_recently_repeated(user)
        add(
            "dedupe",
            "主题去重",
            not repeated,
            6 if not repeated else -20,
            "近期无重复" if not repeated else "近期主动主题过于相似",
            blocker=repeated,
        )

        total_score = 50 + sum(int(item.get("score") or 0) for item in factors)
        factors.append(
            {
                "key": "total",
                "label": "综合评分",
                "passed": total_score >= 50,
                "score": max(0, min(100, total_score)),
                "detail": "分数越高越适合现在发",
                "blocker": False,
            }
        )
        return factors

    def _proactive_decision_snapshot(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        now = _now_ts() if now is None else now
        factors = self._proactive_decision_factors(user, now=now)
        blocker_labels = [item.get("label") for item in factors if item.get("blocker")]
        total_score = 0
        for item in factors:
            if item.get("key") == "total":
                total_score = _safe_int(item.get("score"), 0, 0, 100)
                break
        return {
            "score": total_score,
            "blockers": [str(item) for item in blocker_labels if str(item or "").strip()],
            "factors": factors,
            "generated_ts": now,
        }

    def _proactive_audit_log(self) -> list[dict[str, Any]]:
        raw = self.data.setdefault("proactive_audit_log", [])
        if not isinstance(raw, list):
            raw = []
            self.data["proactive_audit_log"] = raw
        return raw

    def _proactive_visible_text_preview(self, text: str, *, limit: int = 180) -> str:
        meta_checker = getattr(self, "_framework_agent_meta_summary_leak", None)
        if callable(meta_checker):
            try:
                if meta_checker(str(text or "")):
                    return ""
            except Exception:
                pass
        cleaner = getattr(self, "_visible_text_without_tts_reading", None)
        if callable(cleaner):
            try:
                return _single_line(cleaner(text, limit=limit), limit)
            except Exception:
                pass
        return _single_line(_strip_internal_message_blocks(text), limit)

    def _proactive_audit_safe_note(self, note: Any, *, limit: int = 180) -> str:
        text = _single_line(note, limit)
        if not text:
            return ""
        meta_checker = getattr(self, "_framework_agent_meta_summary_leak", None)
        if callable(meta_checker):
            try:
                if meta_checker(text):
                    return "模型/供应商返回内部错误，原文已隐藏"
            except Exception:
                pass
        return text

    def _proactive_audit_signature(self, item: dict[str, Any], *, bucket_seconds: int = 300) -> str:
        updated = _safe_float(item.get("updated_ts") or item.get("created_ts"), 0)
        bucket = int(updated // max(1, bucket_seconds)) if updated > 0 else 0
        parts = [
            item.get("user_id"),
            item.get("status"),
            item.get("source"),
            item.get("reason"),
            item.get("action"),
            item.get("topic"),
            item.get("motive"),
            item.get("note"),
            bucket,
        ]
        return "|".join(_single_line(part, 120) for part in parts)

    @staticmethod
    def _proactive_audit_note_is_obsolete_fixed_error(note: Any) -> bool:
        text = str(note or "")
        if "NameError" not in text:
            return False
        return any(
            token in text
            for token in (
                "name 'topic' is not defined",
                "name 'name' is not defined",
            )
        )

    def _compact_proactive_audit_log(self) -> None:
        log = self._proactive_audit_log()
        compacted: list[dict[str, Any]] = []
        seen: dict[str, dict[str, Any]] = {}
        for item in log:
            if not isinstance(item, dict):
                continue
            if self._proactive_audit_note_is_obsolete_fixed_error(item.get("note")):
                item["status"] = "obsolete"
                item["note"] = "旧版本主动发送变量错误，当前版本已修复"
            signature = self._proactive_audit_signature(item)
            previous = seen.get(signature)
            if previous is None:
                seen[signature] = item
                compacted.append(item)
                continue
            previous["updated_ts"] = max(
                _safe_float(previous.get("updated_ts"), 0),
                _safe_float(item.get("updated_ts"), 0),
            )
            previous["duplicate_count"] = _safe_int(previous.get("duplicate_count"), 1, 1) + 1
            for key in ("text_preview", "original_text_preview", "final_text_preview", "image_path"):
                if item.get(key):
                    previous[key] = item.get(key)
            if item.get("extra_count") is not None:
                previous["extra_count"] = max(
                    _safe_int(previous.get("extra_count"), 0, 0),
                    _safe_int(item.get("extra_count"), 0, 0),
                )
        if len(compacted) != len(log):
            log[:] = compacted[-160:]

    def _append_proactive_audit(
        self,
        user_id: str,
        user: dict[str, Any],
        *,
        status: str,
        note: str = "",
        reason: str = "",
        action: str = "",
        text: str = "",
        original_text: str = "",
        final_text: str = "",
    ) -> str:
        now = _now_ts()
        audit_id = uuid.uuid4().hex[:12]
        semantics = self._planned_proactive_semantics(user)
        item = {
            "id": audit_id,
            "created_ts": now,
            "updated_ts": now,
            "user_id": str(user_id or user.get("user_id") or user.get("id") or ""),
            "status": _single_line(status, 32) or "unknown",
            "note": self._proactive_audit_safe_note(note, limit=180),
            "source": self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) or "proactive",
            "reason": self._normalize_legacy_proactive_text(reason or user.get("planned_proactive_reason"), limit=40),
            "action": _single_line(action or user.get("planned_proactive_action"), 60) or "message",
            "topic": _single_line(user.get("planned_proactive_topic"), 100),
            "motive": _single_line(user.get("planned_proactive_motive"), 180),
            "semantic_kind": _single_line(user.get("planned_proactive_semantic_kind"), 40) or _single_line(semantics.get("kind"), 40),
            "semantic_anchor_type": _single_line(user.get("planned_proactive_anchor_type"), 40) or _single_line(semantics.get("anchor_type"), 40),
            "semantic_score": _safe_int(user.get("planned_proactive_semantic_score"), 0, 0, 100) or int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.0))) * 100),
            "semantic_pressure": int(max(0.0, min(1.0, _safe_float(semantics.get("pressure"), 0.0))) * 100),
            "semantic_risk": int(max(0.0, min(1.0, _safe_float(semantics.get("risk"), 0.0))) * 100),
            "semantic_note": _single_line(user.get("planned_proactive_semantic_note"), 180) or _single_line(semantics.get("note"), 180),
            "need_layer": _single_line(user.get("planned_proactive_need_layer"), 40) or _single_line(semantics.get("need_layer"), 40),
            "need_drive": _single_line(user.get("planned_proactive_need_drive"), 80) or _single_line(semantics.get("need_drive"), 80),
            "need_note": _single_line(user.get("planned_proactive_need_note"), 120) or _single_line(semantics.get("need_note"), 120),
            "scheduled_ts": _safe_float(user.get("next_proactive_at"), 0),
            "candidate_id": _single_line(user.get("planned_candidate_id"), 40),
            "umo": _single_line(user.get("umo"), 180),
            "text_preview": self._proactive_visible_text_preview(text) if text else "",
            "original_text_preview": self._proactive_visible_text_preview(original_text) if original_text else "",
            "final_text_preview": self._proactive_visible_text_preview(final_text) if final_text else "",
        }
        log = self._proactive_audit_log()
        signature = self._proactive_audit_signature(item)
        for existing in reversed(log[-30:]):
            if not isinstance(existing, dict):
                continue
            if self._proactive_audit_signature(existing) != signature:
                continue
            existing["updated_ts"] = now
            existing["duplicate_count"] = _safe_int(existing.get("duplicate_count"), 1, 1) + 1
            for key in ("text_preview", "original_text_preview", "final_text_preview"):
                if item.get(key):
                    existing[key] = item.get(key)
            return _single_line(existing.get("id"), 40) or audit_id
        log.append(item)
        self._compact_proactive_audit_log()
        del log[:-160]
        return audit_id

    def _update_proactive_audit(
        self,
        audit_id: str,
        *,
        status: str,
        note: str = "",
        text: str = "",
        image_path: str = "",
        extra_count: int | None = None,
        action: str = "",
        reason: str = "",
        original_text: str = "",
        final_text: str = "",
    ) -> None:
        if not audit_id:
            return
        for item in reversed(self._proactive_audit_log()):
            if str(item.get("id") or "") != str(audit_id):
                continue
            previous_status = _single_line(item.get("status"), 32)
            item["status"] = _single_line(status, 32) or item.get("status") or "unknown"
            item["updated_ts"] = _now_ts()
            if note:
                item["note"] = self._proactive_audit_safe_note(note, limit=180)
            if text:
                item["text_preview"] = self._proactive_visible_text_preview(text)
            if original_text:
                item["original_text_preview"] = self._proactive_visible_text_preview(original_text)
            if final_text:
                item["final_text_preview"] = self._proactive_visible_text_preview(final_text)
            if image_path:
                item["image_path"] = _single_line(image_path, 260)
            if extra_count is not None:
                item["extra_count"] = max(0, int(extra_count))
            if action:
                item["action"] = _single_line(action, 60)
            if reason:
                item["reason"] = _single_line(reason, 40)
            if item.get("status") in {"cancelled", "dropped"} and item.get("status") != previous_status:
                notifier = getattr(self, "_schedule_reply_interception_forward", None)
                if callable(notifier):
                    notifier(
                        "proactive_block",
                        source=_single_line(item.get("source"), 60) or "主动消息",
                        reason=_single_line(item.get("note"), 300) or "主动候选被拦截",
                        source_session=_single_line(item.get("umo"), 180),
                        before=_single_line(
                            item.get("final_text_preview") or item.get("text_preview") or item.get("original_text_preview"),
                            500,
                        ),
                        detail="；".join(
                            part for part in (
                                f"状态={item.get('status')}",
                                f"动作={_single_line(item.get('action'), 60)}" if item.get("action") else "",
                                f"话题={_single_line(item.get('topic'), 120)}" if item.get("topic") else "",
                            ) if part
                        ),
                    )
            self._compact_proactive_audit_log()
            break

    def _recover_stale_proactive_sending(self, user: dict[str, Any], *, now: float | None = None) -> bool:
        if not user.get("proactive_sending"):
            return False
        now = now or _now_ts()
        started_at = _safe_float(user.get("proactive_sending_started_at"), 0)
        if started_at > 0 and now - started_at < 8 * 60:
            return False
        user["proactive_sending"] = False
        user["proactive_sending_started_at"] = 0
        logger.warning(
            "[PrivateCompanion] 检测到残留的主动发送标记,已自动清理: user=%s started_at=%s",
            user.get("user_id") or user.get("id") or "unknown",
            self._environment_fromtimestamp(started_at).strftime("%m-%d %H:%M:%S") if started_at > 0 else "unknown",
        )
        return True

    def _is_recent_poke_echo(self, user: dict[str, Any], text: str, *, now: float | None = None) -> bool:
        now = now or _now_ts()
        suppress_until = _safe_float(user.get("poke_echo_suppress_until"), 0)
        if suppress_until <= 0 or now > suppress_until:
            return False
        return not bool(_single_line(text, 120))

    def _explain_proactive_decision(self, user: dict[str, Any]) -> str:
        probe = dict(user)
        decision, reason = self._should_send(probe)
        now = _now_ts()
        snapshot = self._proactive_decision_snapshot(probe, now=now)
        planned_reason = self._normalize_legacy_proactive_text(probe.get("planned_proactive_reason"), limit=40)
        planned_action = str(probe.get("planned_proactive_action") or "message")
        planned_source = self._normalize_legacy_proactive_text(probe.get("planned_proactive_source"), limit=40)
        planned_motive = _single_line(probe.get("planned_proactive_motive"), 48)
        next_at = _safe_float(probe.get("next_proactive_at"), 0)
        planned_impulse_id = _single_line(probe.get("planned_proactive_impulse_id"), 20)
        planned_best_until = _safe_float(probe.get("planned_proactive_best_until_at"), 0)
        timer_event = self._get_active_llm_timer(probe)
        active_impulses = [
            item for item in self._cleanup_proactive_impulses(probe, now=now)
            if isinstance(item, dict) and str(item.get("state") or "queued") in {"queued", "deferred"}
        ]
        next_at_text = (
            self._environment_fromtimestamp(next_at).strftime("%m-%d %H:%M:%S")
            if next_at > 0
            else "未安排"
        )
        sent_today = _safe_int(probe.get("sent_today"), 0)
        sent_greetings = probe.get("greetings_sent")
        if not isinstance(sent_greetings, list):
            sent_greetings = []
        suppressed_greetings = probe.get("greetings_suppressed_by_inbound")
        if not isinstance(suppressed_greetings, list):
            suppressed_greetings = []
        last_activity_at = self._latest_private_user_activity_ts(probe)
        last_sent_at = _safe_float(probe.get("last_sent"), 0)
        last_seen_gap = now - last_activity_at if last_activity_at > 0 else -1
        last_sent_gap = now - last_sent_at if last_sent_at > 0 else -1
        idle_limit = (
            self._effective_user_greeting_idle_minutes(probe) * 60
            if self._is_greeting_reason(planned_reason)
            else self._effective_user_idle_minutes(probe) * 60
        )
        min_interval = self._effective_min_interval_seconds(probe)
        if self._is_greeting_reason(planned_reason) and self._private_user_role(probe) != "friend":
            min_interval = min(min_interval, self._greeting_min_interval_seconds(planned_reason))
        effective_daily_limit = self._effective_user_daily_limit(probe)
        daily_limit_text = self._format_proactive_daily_limit(effective_daily_limit)
        soft_target_text = "不限" if self._proactive_daily_limit_is_unlimited(effective_daily_limit) else f"{self._soft_daily_target(probe):.1f}"
        reason_allowed = self._is_reason_allowed_now(planned_reason)
        moment_ok = True
        if reason == "未到候选主动时间":
            reason_allowed_text = "到点后再检查"
            moment_ok_text = "到点后再检查"
        else:
            reason_allowed_text = "通过" if reason_allowed else "不适合"
            moment_ok_text = "候选到点即发送"
        lines = [
            f"主动判定：{'会发送' if decision else '这次不发'}",
            f"原因：{reason}",
            f"综合评分：{_safe_int(snapshot.get('score'), 0, 0, 100)}/100",
            f"下次候选：{next_at_text}",
            f"计划：{planned_reason or '未记录'}｜{planned_action}"
            + (f"｜计划源：{planned_source}" if planned_source else "")
            + (f"｜念头ID：{planned_impulse_id}" if planned_impulse_id else "")
            + (f"｜话题：{_single_line(probe.get('planned_proactive_topic'), 24)}" if _single_line(probe.get("planned_proactive_topic"), 24) else "")
            + (f"｜动机：{planned_motive}" if planned_motive else "")
            + (f"｜最佳窗口到 {self._environment_fromtimestamp(planned_best_until).strftime('%H:%M:%S')}" if planned_best_until > 0 else "")
            + (f"｜来源：模型预约" if isinstance(timer_event, dict) and _safe_float(timer_event.get("scheduled_ts"), 0) == next_at else ""),
            f"潜在念头：{len(active_impulses)} 个待选",
            f"今日已发：{sent_today}/{daily_limit_text}｜软目标约 {soft_target_text}",
            f"今日问候：已发 {', '.join(str(item) for item in sent_greetings) or '无'}｜被用户消息跳过 {', '.join(str(item) for item in suppressed_greetings) or '无'}",
            f"免打扰：{'是' if self._is_quiet_time() else '否'}｜失眠特例：{'可用' if self._can_send_insomnia_night_message(probe) else '不可用'}",
            f"距用户上次活跃：{self._format_elapsed(max(0, last_seen_gap)) if last_seen_gap >= 0 else '从未'}｜要求至少 {self._format_elapsed(idle_limit)}",
            f"距上次主动：{self._format_elapsed(max(0, last_sent_gap)) if last_sent_gap >= 0 else '从未'}｜要求至少 {self._format_elapsed(min_interval)}",
            f"时间窗适配：{reason_allowed_text}｜自然动机：{moment_ok_text}",
        ]
        blockers = snapshot.get("blockers") if isinstance(snapshot.get("blockers"), list) else []
        if blockers:
            lines.append("阻塞项：" + " / ".join(_single_line(item, 32) for item in blockers[:6] if _single_line(item, 32)))
        factor_lines = []
        factors = snapshot.get("factors") if isinstance(snapshot.get("factors"), list) else []
        for item in factors:
            if not isinstance(item, dict) or item.get("key") in {"total"}:
                continue
            label = _single_line(item.get("label"), 24)
            detail = _single_line(item.get("detail"), 90)
            state_text = "通过" if item.get("passed") else "未通过"
            score_text = f"{_safe_int(item.get('score'), 0, -100, 100):+d}"
            if label:
                factor_lines.append(f"- {label}：{state_text}（{score_text}）" + (f"｜{detail}" if detail else ""))
        if factor_lines:
            lines.append("判定分解：")
            lines.extend(factor_lines[:12])
        return "\n".join(lines)

    def _simulation_label(self, user: dict[str, Any]) -> str:
        raw = user.get("simulation_mode")
        if isinstance(raw, dict):
            label = _single_line(raw.get("label"), 24)
            if label:
                return label
        return "压缩测试"

    def _should_send_simulation(self, user: dict[str, Any]) -> tuple[bool, str]:
        sim = user.get("simulation_mode")
        if not isinstance(sim, dict) or not sim.get("active"):
            return False, "未处于模拟模式"
        now = _now_ts()
        self._sync_simulation_next_event(user, now=now)
        next_at = _safe_float(user.get("next_proactive_at"), 0)
        label = self._simulation_label(user)
        if next_at <= 0:
            self._finish_simulation_mode(user)
            return False, f"{label}已结束"
        if now < next_at:
            return False, f"{label}等待下一条主动消息"
        return True, "simulation"

    def _sync_simulation_next_event(self, user: dict[str, Any], *, now: float | None = None) -> None:
        sim = user.get("simulation_mode")
        if not isinstance(sim, dict):
            return
        events = sim.get("events")
        if not isinstance(events, list) or not events:
            self._finish_simulation_mode(user)
            return
        now = now or _now_ts()
        remaining = [event for event in events if isinstance(event, dict)]
        if not remaining:
            self._finish_simulation_mode(user)
            return
        remaining.sort(key=lambda item: _safe_float(item.get("_scheduled_ts"), now))
        sim["events"] = remaining
        current = remaining[0]
        user["next_proactive_at"] = _safe_float(current.get("_scheduled_ts"), now)
        user["planned_proactive_reason"] = self._normalize_legacy_proactive_text(current.get("reason"), limit=40) or "check_in"
        user["planned_proactive_action"] = self._normalize_legacy_proactive_text(current.get("action"), limit=40) or "message"
        user["planned_proactive_source"] = "simulation"
        user["planned_proactive_motive"] = _single_line(current.get("motive"), 140)
        user["planned_proactive_topic"] = _single_line(current.get("topic"), 60)
        scheduled_ts = _safe_float(user.get("next_proactive_at"), now)
        user["planned_proactive_impulse_id"] = ""
        user["planned_proactive_window_start_at"] = scheduled_ts
        active_span, grace_span = self._proactive_impulse_default_window_seconds(user["planned_proactive_reason"])
        user["planned_proactive_best_until_at"] = scheduled_ts + active_span
        user["planned_proactive_expire_at"] = scheduled_ts + active_span + grace_span
        semantics = self._planned_proactive_semantics(user)
        user["planned_proactive_semantic_kind"] = _single_line(semantics.get("kind"), 40)
        user["planned_proactive_anchor_type"] = _single_line(semantics.get("anchor_type"), 40)
        user["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, _safe_float(semantics.get("score"), 0.5))) * 100)
        user["planned_proactive_semantic_note"] = _single_line(semantics.get("note"), 180)
        user["planned_event_chain"] = [] if self._private_user_role(user) == "friend" else (
            list(current.get("chain") or []) if isinstance(current.get("chain"), list) else []
        )
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = bool(current.get("_free_screen_peek"))

    def _consume_simulation_event(self, user: dict[str, Any]) -> None:
        sim = user.get("simulation_mode")
        if not isinstance(sim, dict):
            return
        events = sim.get("events")
        if not isinstance(events, list) or not events:
            self._finish_simulation_mode(user)
            return
        sim["events"] = [event for event in events[1:] if isinstance(event, dict)]
        sim["sent_count"] = _safe_int(sim.get("sent_count"), 0, 0) + 1
        self._reset_planned_proactive_delivery_state(user)
        self._sync_simulation_next_event(user)

    def _finish_simulation_mode(self, user: dict[str, Any]) -> None:
        user["simulation_mode"] = {}
        self._reset_planned_proactive_delivery_state(user)
        user["next_proactive_at"] = 0
        user["planned_proactive_reason"] = ""
        user["planned_proactive_action"] = ""
        user["planned_proactive_source"] = ""
        user["planned_proactive_motive"] = ""
        user["planned_proactive_topic"] = ""
        user["planned_proactive_impulse_id"] = ""
        user["planned_proactive_window_start_at"] = 0
        user["planned_proactive_best_until_at"] = 0
        user["planned_proactive_expire_at"] = 0
        user["planned_proactive_semantic_kind"] = ""
        user["planned_proactive_anchor_type"] = ""
        user["planned_proactive_semantic_score"] = 0
        user["planned_proactive_semantic_note"] = ""
        user["planned_proactive_need_layer"] = ""
        user["planned_proactive_need_drive"] = ""
        user["planned_proactive_need_note"] = ""
        user["planned_event_chain"] = []
        user["planned_opener_mode"] = ""
        user["planned_followup_kind"] = ""
        user["planned_proactive_quota_exempt"] = False

    def _available_test_actions(self, user: dict[str, Any]) -> list[str]:
        actions = ["message"]
        if self._screen_glance_available(user):
            actions.append("screen_peek")
        if self._photo_text_available(user):
            actions.append("photo_text")
        if self._voice_available(user):
            actions.append("voice")
        if self._jm_cosmos_read_available(user):
            actions.append("jm_cosmos_read")
        actions.extend(f"external:{item['name']}" for item in self._available_external_proactive_abilities(user) if item.get("name"))
        return actions

    @staticmethod
    def _normalize_external_ability_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9_.:-]+", "_", text)
        return text[:64].strip("_")

    def _external_ability_store(self) -> dict[str, Any]:
        if not isinstance(getattr(self, "data", None), dict):
            self.data = {}
        store = self.data.setdefault("external_proactive_abilities", {})
        if not isinstance(store, dict):
            store = {}
            self.data["external_proactive_abilities"] = store
        return store

    def register_external_proactive_ability(self, spec: dict[str, Any]) -> bool:
        if not isinstance(spec, dict):
            return False
        name = self._normalize_external_ability_name(spec.get("name"))
        executor = spec.get("executor")
        if not name or not callable(executor):
            logger.warning("[PrivateCompanion] 外部主动能力注册失败: name/executor 无效")
            return False
        default_config = spec.get("default_config") if isinstance(spec.get("default_config"), dict) else {}
        config_schema = spec.get("config_schema") if isinstance(spec.get("config_schema"), dict) else {}
        meta = {
            "name": name,
            "module": _single_line(spec.get("module"), 24) or "外部主动能力",
            "label": _single_line(spec.get("label"), 32) or name,
            "description": _single_line(spec.get("description"), 160),
            "when": _single_line(spec.get("when"), 120) or "外部插件认为合适的场景",
            "use_for": _single_line(spec.get("use_for"), 120) or _single_line(spec.get("description"), 120),
            "avoid": _single_line(spec.get("avoid"), 120) or "不要暴露插件调用过程,不要硬触发",
            "default_enabled": bool(spec.get("default_enabled", False)),
            "share_probability": max(0.0, min(1.0, _safe_float(spec.get("share_probability"), _safe_float(default_config.get("share_probability"), 0.12)))),
            "min_interval_hours": max(0.0, _safe_float(spec.get("min_interval_hours"), _safe_float(default_config.get("min_interval_hours"), 12))),
            "config_schema": deepcopy(config_schema),
            "default_config": deepcopy(default_config),
        }
        self._external_proactive_abilities[name] = {**meta, "executor": executor}
        try:
            store = self._external_ability_store()
            item = store.get(name) if isinstance(store.get(name), dict) else {}
            config = item.get("config") if isinstance(item.get("config"), dict) else {}
            merged_config = {**default_config, **config}
            item.update({
                "name": name,
                "module": meta["module"],
                "label": meta["label"],
                "description": meta["description"],
                "when": meta["when"],
                "use_for": meta["use_for"],
                "avoid": meta["avoid"],
                "enabled": bool(item.get("enabled", meta["default_enabled"])),
                "share_probability": _safe_float(item.get("share_probability"), meta["share_probability"], 0.0),
                "min_interval_hours": _safe_float(item.get("min_interval_hours"), meta["min_interval_hours"], 0.0),
                "config": merged_config,
                "config_schema": deepcopy(config_schema),
                "registered": True,
                "updated_ts": _now_ts(),
            })
            store[name] = item
            self._save_data_sync()
        except Exception as exc:
            logger.debug("[PrivateCompanion] 外部主动能力状态保存失败: %s", exc)
        logger.info("[PrivateCompanion] 已注册外部主动能力: %s", name)
        return True

    def unregister_external_proactive_ability(self, name: str) -> bool:
        normalized = self._normalize_external_ability_name(name)
        removed = self._external_proactive_abilities.pop(normalized, None) is not None
        try:
            store = self._external_ability_store()
            item = store.get(normalized)
            if isinstance(item, dict):
                item["registered"] = False
                item["updated_ts"] = _now_ts()
                self._save_data_sync()
        except Exception:
            pass
        return removed

    def external_proactive_abilities(self) -> list[dict[str, Any]]:
        store = self.data.get("external_proactive_abilities") if isinstance(getattr(self, "data", None), dict) else {}
        if not isinstance(store, dict):
            store = {}
        names = sorted(set(store.keys()) | set(self._external_proactive_abilities.keys()))
        items: list[dict[str, Any]] = []
        for name in names:
            runtime = self._external_proactive_abilities.get(name, {})
            stored = store.get(name) if isinstance(store.get(name), dict) else {}
            merged = {**{k: v for k, v in runtime.items() if k != "executor"}, **stored}
            merged["name"] = name
            merged["available"] = callable(runtime.get("executor"))
            merged["registered"] = bool(runtime)
            merged["enabled"] = bool(merged.get("enabled", merged.get("default_enabled", False)))
            merged["share_probability"] = max(0.0, min(1.0, _safe_float(merged.get("share_probability"), 0.0)))
            merged["min_interval_hours"] = max(0.0, _safe_float(merged.get("min_interval_hours"), 0.0))
            items.append(merged)
        return items

    def _external_ability_config(self, name: str) -> dict[str, Any]:
        store = self.data.get("external_proactive_abilities") if isinstance(self.data.get("external_proactive_abilities"), dict) else {}
        item = store.get(name) if isinstance(store.get(name), dict) else {}
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        return dict(config)

    def _external_ability_enabled(self, name: str) -> bool:
        item = next((entry for entry in self.external_proactive_abilities() if entry.get("name") == name), None)
        if not isinstance(item, dict):
            return False
        return bool(item.get("enabled") and item.get("available"))

    def _available_external_proactive_abilities(self, user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        now = _now_ts()
        items: list[dict[str, Any]] = []
        for item in self.external_proactive_abilities():
            name = str(item.get("name") or "")
            if not name or not item.get("enabled") or not item.get("available"):
                continue
            last = _safe_float(item.get("last_executed_ts"), 0)
            cooldown = _safe_float(item.get("min_interval_hours"), 0) * 3600
            if cooldown > 0 and last > 0 and now - last < cooldown:
                continue
            items.append(item)
        return items

    def _available_proactive_abilities(self, user: dict[str, Any] | None = None) -> list[dict[str, str]]:
        user = user if isinstance(user, dict) else {}
        available = {"message"}
        if self._screen_glance_available(user):
            available.add("screen_peek")
        if self._photo_text_available(user):
            available.add("photo_text")
        if self._poke_available() and self._effective_user_poke_daily_limit(user) > 0 and self._poke_action_cooldown_remaining(user) <= 0:
            available.add("poke")
        if self._voice_available(user):
            available.add("voice")
        if self._jm_cosmos_read_available(user):
            available.add("jm_cosmos_read")
        items: list[dict[str, str]] = []
        for raw in PROACTIVE_ABILITY_REGISTRY:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name or name not in available:
                continue
            items.append({str(key): str(value) for key, value in raw.items()})
        for raw in self._available_external_proactive_abilities(user):
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "module": _single_line(raw.get("module"), 24) or "外部主动能力",
                    "name": f"external:{name}",
                    "label": _single_line(raw.get("label"), 32) or name,
                    "when": _single_line(raw.get("when"), 120) or "外部插件认为合适时",
                    "use_for": _single_line(raw.get("use_for"), 120) or _single_line(raw.get("description"), 120),
                    "avoid": _single_line(raw.get("avoid"), 120) or "不要暴露插件调用过程",
                }
            )
        return items

    def _format_proactive_ability_search_hint(self, user: dict[str, Any] | None = None) -> str:
        abilities = self._available_proactive_abilities(user)
        if not abilities:
            return "可用动作：message=普通文字。"
        terms = self._worldview_terms()
        lines = ["可用动作："]
        for item in abilities:
            name = _single_line(item.get("name"), 24)
            label = _single_line(item.get("label"), 16)
            when = _single_line(item.get("when"), 80)
            use_for = _single_line(item.get("use_for"), 80)
            if name == "screen_peek":
                label = f"观察{terms['screen']}"
                when = when.replace("轻窥屏", f"看一眼{terms['screen']}").replace("探头一下", "轻轻确认一下")
            elif name == "jm_cosmos_read":
                label = terms["private_reading"]
                when = f"有空、无聊或夜里自己想给{terms['bookshelf']}{terms['secret_drawer']}添一点阅读内容"
                use_for = "内部阅读、低频形成读后印象,是否提起交给人格"
            elif name == "photo_text" and terms.get("mode") in {"fantasy", "sci_fi"}:
                label = "画面加一句话"
            lines.append(
                "- {name}（{label}）：{when}；{use_for}".format(
                    name=name,
                    label=label,
                    when=when,
                    use_for=use_for,
                )
            )
        preference_hint = self._action_preference_hint(user)
        if preference_hint:
            lines.append("用户媒介偏好：\n" + preference_hint)
        return "\n".join(lines)

    def _format_proactive_ability_list_for_user(self, user: dict[str, Any] | None = None) -> str:
        abilities = self._available_proactive_abilities(user)
        if not abilities:
            return "当前主动能力：文字私聊。"
        terms = self._worldview_terms()
        lines = ["当前主动能力："]
        for item in abilities:
            name = str(item.get("name") or "")
            label = item.get("label")
            when = item.get("when")
            if name == "screen_peek":
                label = f"观察{terms['screen']}"
            elif name == "jm_cosmos_read":
                label = terms["private_reading"]
            lines.append(
                f"- {item.get('module')}/{name}：{label}｜{when}"
            )
        return "\n".join(lines)

    def _summarize_test_action_labels(self, actions: list[str]) -> str:
        labels = {
            "message": "文字",
            "screen_peek": "窥屏",
            "photo_text": "发图",
            "poke": "戳一戳",
            "voice": "语音",
            "jm_cosmos_read": "私下阅读",
        }
        return "、".join(labels.get(action, action) for action in actions)

    def _build_full_test_detail_prompt(
        self,
        segment: dict[str, Any],
        plan: dict[str, Any],
        state: dict[str, Any],
        actions: list[str],
        *,
        missing_actions: list[str] | None = None,
    ) -> str:
        base_prompt = self._build_detail_enhancement_prompt(segment, plan, state)
        action_text = "、".join(actions) if actions else "message"
        extra = [
            "",
            "【这次是临时完整主动链测试】",
            "请只围绕这一段日程生成一串用于真实测试的 proactive_events。",
            "要求它们仍然像正常生活里会长出来的主动消息，不要写成“这是测试”或功能演示。",
            f"这轮测试可用的主动行为有：{action_text}。",
            "请尽量让 proactive_events 覆盖每一种可用行为至少一次；如果某种行为实在不合时宜，也要优先找一个勉强自然的切入点，而不是完全放弃。",
            "这些 proactive_events 之后会被压缩成每两分钟一条真实发送，所以你只需要负责把这一整段里的多个主动契机安排出来。",
            "today_events 仍然保持正常生活感，proactive_events 要像从这段生活里自己长出来。",
            "不要把‘测试’、‘跑满能力’、‘验证功能’写进输出里。",
        ]
        if missing_actions:
            extra.extend(
                [
                    "",
                    "【补正要求】",
                    f"上一轮结果还缺少这些主动行为：{'、'.join(missing_actions)}。",
                    "这一轮请重点补齐缺失行为，同时保持整段仍然像同一个人的连续生活。",
                ]
            )
        return base_prompt + "\n" + "\n".join(extra)

    async def _generate_full_test_detail_enhancement(
        self,
        segment: dict[str, Any],
        plan: dict[str, Any],
        state: dict[str, Any],
        actions: list[str],
    ) -> tuple[dict[str, Any], list[str]]:
        required_actions = [action for action in actions if action in {"message", "screen_peek", "photo_text", "voice", "jm_cosmos_read"}]
        last_normalized = {
            "summary": "这一段按原日程慢慢推进。",
            "today_events": [],
            "proactive_events": [],
            "long_term_events": [],
        }
        missing_actions = list(required_actions)
        for _ in range(3):
            prompt = self._build_full_test_detail_prompt(
                segment,
                plan,
                state,
                required_actions,
                missing_actions=missing_actions if missing_actions and missing_actions != required_actions else None,
            )
            raw_text = await self._llm_call(
                prompt,
                max_tokens=1000,
                provider_id=self._task_provider(
                    self.detail_enhancement_provider_id,
                    self.daily_plan_provider_id,
                    self.mai_style_provider_id,
                ),
                task="full_test_detail",
            )
            payload = self._extract_json_payload(raw_text or "")
            if not isinstance(payload, dict):
                continue
            normalized = self._normalize_story_plan(
                {
                    "today_events": payload.get("today_events", []),
                    "proactive_events": payload.get("proactive_events", []),
                    "long_term_events": [],
                }
            )
            normalized["summary"] = _single_line(payload.get("summary"), 160)
            last_normalized = normalized
            present = {
                str(item.get("action") or "message")
                for item in normalized.get("proactive_events", [])
                if isinstance(item, dict)
            }
            missing_actions = [action for action in required_actions if action not in present]
            if not missing_actions:
                break
        return last_normalized, missing_actions

    def _build_full_test_events(
        self,
        detail: dict[str, Any],
        *,
        actions: list[str],
        segment: dict[str, Any] | None = None,
        spacing_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        proactive_events = detail.get("proactive_events", []) if isinstance(detail, dict) else []
        if not isinstance(proactive_events, list):
            proactive_events = []
        usable = [dict(item) for item in proactive_events if isinstance(item, dict)]
        segment_start = _safe_int((segment or {}).get("start"), -1, -1)
        segment_end = _safe_int((segment or {}).get("end"), -1, -1)
        if segment_start >= 0 and segment_end > segment_start:
            scoped: list[dict[str, Any]] = []
            for item in usable:
                start, end = self._parse_window_minutes(str(item.get("window") or ""))
                if start is None or end is None:
                    continue
                if start < segment_start or end > segment_end:
                    continue
                scoped.append(item)
            usable = scoped
        required_actions = [action for action in actions if action in {"message", "screen_peek", "photo_text", "voice", "jm_cosmos_read"}]
        filtered: list[dict[str, Any]] = []
        for action in required_actions:
            matched = next((item for item in usable if str(item.get("action") or "message") == action and item not in filtered), None)
            if matched:
                filtered.append(matched)
        for item in usable:
            action = str(item.get("action") or "message")
            if action in required_actions and item not in filtered:
                filtered.append(item)
        if not filtered:
            filtered = [dict(item) for item in _SIMULATION_FALLBACK_EVENTS]
            for item in filtered:
                item["motive"] = self._normalize_event_motive(item)
        filtered.sort(
            key=lambda item: (
                (self._parse_window_minutes(str(item.get("window") or ""))[0])
                if self._parse_window_minutes(str(item.get("window") or ""))[0] is not None
                else 24 * 60
            )
        )
        start_ts = _now_ts() + 20
        events: list[dict[str, Any]] = []
        for index, item in enumerate(filtered):
            cloned = dict(item)
            cloned["_scheduled_ts"] = start_ts + index * spacing_seconds
            cloned["_simulated_window"] = str(item.get("window") or "")
            events.append(cloned)
        return events

    def _build_single_poke_test_event(
        self,
        *,
        user: dict[str, Any],
        segment: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = (segment or {}).get("item") if isinstance(segment, dict) else {}
        item = item if isinstance(item, dict) else {}
        topic = (
            _single_line(((detail or {}).get("proactive_events") or [{}])[0].get("topic"), 60)
            if isinstance((detail or {}).get("proactive_events"), list) and (detail or {}).get("proactive_events")
            else ""
        )
        if not topic:
            topic = _single_line(item.get("activity"), 60) or "刚才那条内容"
        motive = self._normalize_internal_motive_text(
            f"关于“{topic}”，想用戳一戳提醒一下用户"
        )
        window = ""
        if isinstance(segment, dict):
            start = _safe_int(segment.get("start"), -1, -1)
            end = _safe_int(segment.get("end"), -1, -1)
            if start >= 0 and end > start:
                window = f"{self._minutes_to_hhmm(start)}-{self._minutes_to_hhmm(end)}"
        return {
            "window": window,
            "reason": "diary_share",
            "action": "poke",
            "why": _single_line(item.get("activity"), 80) or "突然很想戳你一下",
            "topic": topic,
            "motive": motive,
            "scene": _single_line(((detail or {}).get("summary")), 80) or "眼前这一小段",
            "tone": "轻轻使坏",
            "impulse": "先戳一下，再看看你会不会回头",
            "chain": [],
            "_scheduled_ts": _now_ts() + 3,
            "_simulated_window": window or "立即触发",
        }

    def _maybe_upgrade_planned_message_action(
        self,
        action: str,
        *,
        reason: str,
        user: dict[str, Any],
        motive: str = "",
        planned_event: dict[str, Any] | None = None,
    ) -> str:
        if reason in {"holiday_celebration", "course_reminder"}:
            return "message"
        normalized = str(action or "message").strip() or "message"
        if normalized != "message":
            return self._fallback_action_for_unavailable(normalized, user)
        if isinstance(planned_event, dict) and (planned_event.get("_daily_greeting") or planned_event.get("_daily_meal_care")):
            return "message"
        candidates: list[tuple[str, float]] = []
        event_text = ""
        if isinstance(planned_event, dict):
            event_text = " ".join(
                _single_line(planned_event.get(key), 80)
                for key in ("topic", "why", "scene", "motive", "impulse")
            )
        combined_hint = f"{event_text} {motive}"
        if self._screen_glance_available(user) and reason in {"check_in", "quiet_care", "background_schedule"}:
            candidates.append(("screen_peek", 1.15))
        if (
            self._photo_text_available(user)
            and reason in {"activity_share", "diary_share", "background_schedule", "noon_greeting", "evening_greeting"}
            and self._strong_photo_share_intent(event_text, motive, user.get("planned_proactive_topic"))
        ):
            return "photo_text"
        photo_probability = self._proactive_photo_text_trigger_probability(
            reason,
            event_text,
            motive,
            user.get("planned_proactive_topic"),
            user=user,
        )
        if self._photo_text_available(user) and photo_probability > 0 and random.random() < photo_probability:
            return "photo_text"
        if self._photo_text_available(user) and (
            reason in {"activity_share", "diary_share", "background_schedule", "noon_greeting", "evening_greeting"}
            or any(token in combined_hint for token in self._visual_share_tokens())
        ):
            candidates.append(("photo_text", 1.05))
        if self._voice_available(user) and reason in {"quiet_care", "diary_share", "insomnia_night", "evening_greeting"}:
            candidates.append(("voice", 0.82))
        if self._poke_available() and self._effective_user_poke_daily_limit(user) > 0 and self._poke_action_cooldown_remaining(user) <= 0 and reason in {"check_in", "quiet_care", "morning_greeting", "evening_greeting"}:
            candidates.append(("poke", 0.62))
        if not candidates:
            return "message"
        candidates.append(("message", 0.38))
        return self._fallback_action_for_unavailable(self._weighted_choice(candidates), user)

    def _pick_best_planned_event(
        self, user: dict[str, Any], now: float | None = None
    ) -> dict[str, Any] | None:
        now = now or _now_ts()
        candidates = []
        for event in (
            self._pick_pending_followup_event(user, now),
            self._pick_holiday_celebration_event(user, now),
            self._pick_course_reminder_event(user, now),
            self._pick_meal_care_event(user, now=now),
            self._pick_daily_greeting_event(user, now),
            self._habit_proactive_event_for_user(user, now=now),
            self._pick_state_need_event(user, now=now),
            self._pick_story_plan_event(now, user=user),
        ):
            if not isinstance(event, dict):
                continue
            if self._unverified_social_relay_plan_reason(
                event,
                source="event",
                has_trigger=bool(_single_line(event.get("trigger_message_id"), 120)),
            ):
                continue
            reason = str(event.get("reason") or "check_in")
            event_ts = self._timestamp_from_story_event(event, reason)
            if self._friend_proactive_scheduled_too_early(user, event_ts):
                continue
            if event_ts > now or (event_ts > 0 and now - event_ts <= self.max_proactive_plan_lag_minutes * 60):
                candidates.append((event_ts, event))
        if not candidates:
            return None
        near_sticky = [
            (event_ts, event)
            for event_ts, event in candidates
            if self._is_sticky_greeting_event(event) and 0 < event_ts - now <= 90 * 60
        ]
        if near_sticky:
            near_sticky.sort(key=lambda item: (self._event_priority(item[1]), item[0]))
            return near_sticky[0][1]
        non_sticky = [
            (event_ts, event)
            for event_ts, event in candidates
            if not self._is_sticky_greeting_event(event)
        ]
        if non_sticky:
            non_sticky.sort(key=lambda item: item[0])
            weighted = []
            for index, (_, event) in enumerate(non_sticky[:3]):
                priority_tuple = self._event_priority(event)
                priority_score = float(-priority_tuple[0])
                weighted.append((event, 1.0 + priority_score * 0.05 + max(0.0, 0.35 - index * 0.1)))
            return self._weighted_choice(weighted)
        ranked = sorted(
            candidates,
            key=lambda item: (self._event_priority(item[1]), item[0]),
        )
        top = ranked[:3]
        return random.choice(top)[1]

    @staticmethod
    def _food_prompt_cooldown_remaining(user: dict[str, Any], *, now: float) -> float:
        return max(0.0, _safe_float(user.get("last_food_prompt_at"), 0) + 7 * 3600 - now)

    def _meal_care_interval_remaining(self, user: dict[str, Any], *, now: float) -> float:
        interval_hours = _safe_int(
            getattr(self, "meal_care_min_interval_hours", 48),
            48,
            0,
            168,
        )
        if interval_hours <= 0:
            return 0.0
        return max(
            0.0,
            _safe_float(user.get("last_food_prompt_at"), 0) + interval_hours * 3600 - now,
        )

    def _pick_state_need_event(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now = now or _now_ts()
        state = self.data.get("daily_state", {})
        if not isinstance(state, dict) or state.get("date") != _today_key():
            return None
        hunger_text = _single_line(state.get("hunger"), 80)
        if hunger_text in {"", "饥饿感平稳", "该人格不适用饥饿状态"}:
            return None
        if self._food_prompt_cooldown_remaining(user, now=now) > 0:
            return None
        if _safe_float(user.get("last_food_feedback_at"), 0) + 2 * 3600 > now:
            return None
        active_hunger = None
        for cond in self._get_active_conditions():
            if isinstance(cond, dict) and str(cond.get("kind") or "") == "hunger":
                active_hunger = cond
                break
        if not isinstance(active_hunger, dict):
            return None
        started = _safe_float(active_hunger.get("start_ts"), now)
        if now - started < 25 * 60:
            return None
        when = self._environment_fromtimestamp(now)
        minute = when.hour * 60 + when.minute
        if not (10 * 60 + 30 <= minute <= 21 * 60 + 40):
            return None
        intensity = max(0.0, min(1.0, self.humanized_state_intensity / 100))
        chance = 0.18 + 0.32 * intensity
        if random.random() > chance:
            return None
        delay_minutes = random.randint(4, 12) if now - started >= 55 * 60 else random.randint(12, 32)
        scheduled = now + delay_minutes * 60
        phase = _single_line(active_hunger.get("phase"), 24)
        topic = "吃点什么"
        if phase == "afternoon":
            topic = random.choice(["下午想吃点甜的", "下午想吃点咸的", "下午想吃点热的", "下午想吃点凉的"])
        elif phase == "late_snack":
            topic = "夜里要不要吃点东西"
        elif phase in {"lunch", "dinner"}:
            topic = "这一顿吃什么"
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(delay_minutes, width_minutes=18),
            "reason": "state_share",
            "action": "message",
            "why": "有些饿了",
            "topic": topic,
            "motive": self._normalize_internal_motive_text(
                "有些饿了，想问问用户吃什么"
            ),
            "scene": "饭点或嘴馋的小空档",
            "tone": "自然",
            "impulse": "想问问用户吃什么比较好",
            "_scheduled_ts": scheduled,
            "_state_need": "hunger",
        }

    @staticmethod
    def _is_sticky_greeting_event(event: dict[str, Any]) -> bool:
        reason = str(event.get("reason") or "")
        return (
            bool(event.get("_daily_greeting"))
            and reason in {"morning_greeting", "noon_greeting", "evening_greeting"}
        ) or bool(event.get("_daily_meal_care"))

    def _reset_meal_care_day(self, user: dict[str, Any]) -> None:
        today = _today_key()
        if str(user.get("meal_care_day") or "") == today:
            return
        user["meal_care_day"] = today
        user["meal_care_asked"] = []
        user["meal_care_satisfied"] = []
        context = user.get("meal_check_context")
        if not isinstance(context, dict) or str(context.get("date") or "") != today:
            user["meal_check_context"] = {}

    def _meal_care_slots(self) -> tuple[tuple[str, str, str], ...]:
        return (
            ("breakfast", "07:50-10:05", "早餐"),
            ("lunch", "11:40-14:05", "午饭"),
            ("dinner", "17:40-20:35", "晚饭"),
        )

    def _breakfast_waiting_for_morning_reply(self, user: dict[str, Any]) -> bool:
        if not bool(getattr(self, "enable_daily_greetings", True)):
            return False
        self._reset_daily_counter_if_needed(user)
        morning_sent_at = _safe_float(user.get("morning_greeting_sent_at"), 0)
        morning_reply_at = _safe_float(user.get("morning_greeting_reply_at"), 0)
        return morning_sent_at <= 0 or morning_reply_at < morning_sent_at

    def _meal_care_followup_blocked_by_newer_food_prompt(
        self,
        user: dict[str, Any],
        context: dict[str, Any],
        *,
        now: float,
    ) -> bool:
        """Keep a meal follow-up from bypassing a newer food-topic cooldown.

        The initial meal-care message itself sets ``last_food_prompt_at`` to
        the same timestamp as ``asked_at`` and must not cancel its own optional
        follow-up. Any later food prompt, however, supersedes the old question.
        """
        asked_at = _safe_float(context.get("asked_at"), 0)
        last_food_prompt_at = _safe_float(user.get("last_food_prompt_at"), 0)
        return bool(
            asked_at > 0
            and last_food_prompt_at > asked_at + 1
            and self._food_prompt_cooldown_remaining(user, now=now) > 0
        )

    def _meal_care_followup_event(self, user: dict[str, Any], *, now: float) -> dict[str, Any] | None:
        context = user.get("meal_check_context")
        if not isinstance(context, dict) or not context.get("active"):
            return None
        if str(context.get("date") or "") != _today_key():
            user["meal_check_context"] = {}
            return None
        if _safe_int(context.get("followup_count"), 0, 0, 1) >= 1:
            return None
        if self._meal_care_followup_blocked_by_newer_food_prompt(user, context, now=now):
            context.update(
                {
                    "active": False,
                    "stage": "closed_newer_food_prompt",
                    "closed_at": now,
                    "followup_due_at": 0,
                }
            )
            user["meal_check_context"] = context
            return None
        due_at = _safe_float(context.get("followup_due_at"), 0)
        expires_at = _safe_float(context.get("expires_at"), 0)
        if due_at <= 0 or (expires_at > 0 and now > expires_at):
            return None
        stage = _single_line(context.get("stage"), 24) or "awaiting_status"
        meal_label = _single_line(context.get("meal_label"), 12) or "这顿饭"
        if stage == "awaiting_detail":
            topic = f"{meal_label}具体吃了什么"
            motive = f"用户只说已经吃过{meal_label}，还想自然问清具体吃了什么并记住"
        elif stage == "not_eaten":
            topic = f"{meal_label}后来有没有吃上"
            motive = f"用户刚才还没吃{meal_label}，隔一会儿想低压确认有没有垫上"
        else:
            topic = f"{meal_label}吃了吗"
            motive = f"刚才问过用户{meal_label}，还没得到具体饮食信息，想只补问一次"
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(max(1, int((due_at - now) / 60)), width_minutes=20),
            "reason": "meal_care_followup",
            "action": "message",
            "why": "一顿饭的关心还没有落到具体信息，只允许低压补问一次",
            "topic": topic,
            "motive": self._normalize_internal_motive_text(motive),
            "scene": "前一次吃饭关心之后",
            "tone": "自然、简短，不催促",
            "impulse": "想确认用户有没有好好吃东西",
            "_scheduled_ts": due_at,
            "_daily_meal_care": True,
            "_meal_care_followup": True,
            "context_key": "planned_meal_care_context",
            "context": dict(context),
        }

    def _pick_meal_care_event(self, user: dict[str, Any], *, now: float | None = None) -> dict[str, Any] | None:
        if not bool(getattr(self, "enable_meal_care_proactive", True)):
            return None
        if self._private_user_role(user) != "owner":
            return None
        self._reset_meal_care_day(user)
        check_now = _now_ts() if now is None else now
        followup = self._meal_care_followup_event(user, now=check_now)
        if isinstance(followup, dict):
            return followup
        if self._meal_care_interval_remaining(user, now=check_now) > 0:
            return None
        if self._food_prompt_cooldown_remaining(user, now=check_now) > 0:
            return None
        asked = user.get("meal_care_asked") if isinstance(user.get("meal_care_asked"), list) else []
        satisfied = user.get("meal_care_satisfied") if isinstance(user.get("meal_care_satisfied"), list) else []
        max_daily = _safe_int(getattr(self, "meal_care_max_daily", 1), 1, 0, 3)
        if max_daily <= 0 or len(asked) >= max_daily:
            return None
        now_dt = self._environment_fromtimestamp(check_now)
        minute = now_dt.hour * 60 + now_dt.minute
        today = now_dt.date()
        candidates: list[tuple[float, dict[str, Any]]] = []
        for meal_key, window, meal_label in self._meal_care_slots():
            if meal_key in asked or meal_key in satisfied:
                continue
            if meal_key == "breakfast" and self._breakfast_waiting_for_morning_reply(user):
                continue
            start, end = self._parse_window_minutes(window)
            if start is None or end is None or minute >= end:
                continue
            start_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=start)
            end_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=end)
            earliest = max(now_dt + timedelta(minutes=1), start_dt)
            if earliest >= end_dt:
                continue
            latest = min(end_dt, earliest + timedelta(minutes=42))
            scheduled = random.uniform(earliest.timestamp(), max(earliest.timestamp() + 60, latest.timestamp()))
            context = {
                "active": False,
                "date": _today_key(),
                "meal_key": meal_key,
                "meal_label": meal_label,
                "stage": "planned",
                "followup_count": 0,
            }
            candidates.append(
                (
                    scheduled,
                    {
                        "date": _today_key(),
                        "window": window,
                        "reason": "meal_care",
                        "action": "message",
                        "why": f"到了{meal_label}时段，惦记用户有没有按时吃东西",
                        "topic": f"{meal_label}吃了吗",
                        "motive": self._normalize_internal_motive_text(f"想问对方{meal_label}吃了没有"),
                        "scene": f"{meal_label}时段",
                        "tone": "关心但不管教",
                        "impulse": "想确认用户有没有好好吃东西",
                        "_scheduled_ts": scheduled,
                        "_daily_meal_care": True,
                        "context_key": "planned_meal_care_context",
                        "context": context,
                    },
                )
            )
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _pick_pending_followup_event(
        self, user: dict[str, Any], now: float | None = None
    ) -> dict[str, Any] | None:
        now = now or _now_ts()
        if self._private_user_role(user) == "friend":
            return None
        if self._in_llm_timer_silence_window(user, now=now):
            return None
        opener_event = self._build_suspended_opener_followup_event(user, now=now)
        if isinstance(opener_event, dict):
            return opener_event
        raw = user.get("pending_followup_event")
        if not isinstance(raw, dict):
            return None
        if raw.get("_meal_care_followup"):
            context = self._meal_care_active_context(user, now=now)
            blocked_by_newer_food_prompt = bool(
                context
                and self._meal_care_followup_blocked_by_newer_food_prompt(user, context, now=now)
            )
            if (
                not context
                or _safe_int(context.get("followup_count"), 0, 0, 1) >= 1
                or blocked_by_newer_food_prompt
            ):
                if blocked_by_newer_food_prompt:
                    context.update(
                        {
                            "active": False,
                            "stage": "closed_newer_food_prompt",
                            "closed_at": now,
                            "followup_due_at": 0,
                        }
                    )
                    user["meal_check_context"] = context
                user["pending_followup_event"] = {}
                return None
        raw = dict(raw)
        raw["reason"] = self._normalize_legacy_proactive_text(raw.get("reason"), limit=40) or _single_line(raw.get("reason"), 40) or "check_in"
        followup_date = str(raw.get("date") or "")
        if followup_date and followup_date != _today_key():
            return None
        scheduled = _safe_float(raw.get("_scheduled_ts"), 0)
        if scheduled <= 0:
            return None
        if scheduled <= now:
            return raw
        return raw

    def _build_suspended_opener_followup_event(
        self,
        user: dict[str, Any],
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        raw = user.get("suspended_proactive")
        if not isinstance(raw, dict) or not raw.get("active"):
            return None
        if not raw.get("complaint_enabled") or raw.get("complaint_sent"):
            return None
        if max(_safe_float(user.get("awaiting_reply_since"), 0), _safe_float(user.get("last_sent"), 0)) <= 0:
            return None
        due_at = _safe_float(raw.get("complaint_after_ts"), 0)
        if due_at <= 0:
            return None
        now = now or _now_ts()
        if now < due_at:
            return None
        name = _single_line(user.get("nickname") or self.default_nickname, 24)
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(4, width_minutes=18),
            "reason": self._normalize_legacy_proactive_text(raw.get("complaint_reason"), limit=40) or "check_in",
            "action": "message",
            "why": "之前只叫了用户一声，因此把话说完",
            "topic": _single_line(raw.get("complaint_topic"), 80) or "刚才那句后面",
            "motive": _single_line(raw.get("complaint_motive"), 100) or f"刚才只喊了{name}一声，想补完话",
            "scene": "先前那句之后又过了一阵",
            "tone": _single_line(raw.get("complaint_tone"), 30) or "耐心等待",
            "impulse": "想把刚才没说完的话补上",
            "_scheduled_ts": due_at,
            "_opener_followup": True,
            "_cancel_on_inbound": True,
        }

    def _build_followup_event_from_chain(
        self,
        chain: list[dict[str, Any]] | None,
        *,
        origin_reason: str,
        origin_action: str,
        now_ts: float | None = None,
    ) -> dict[str, Any] | None:
        steps = [dict(step) for step in (chain or []) if isinstance(step, dict)]
        if not steps:
            return None
        current = None
        remaining: list[dict[str, Any]] = []
        consumed_name_only = False
        for step in steps:
            kind = str(step.get("kind") or "")
            if kind == "name_only_opener" and not consumed_name_only:
                consumed_name_only = True
                continue
            if current is None and kind in {"if_no_reply", "if_still_no_reply"}:
                current = step
                continue
            remaining.append(step)
        if not isinstance(current, dict):
            return None
        now_ts = now_ts or _now_ts()
        after_minutes = _safe_int(current.get("after_minutes"), 18, 0, 240)
        origin_reason = self._normalize_legacy_proactive_text(origin_reason, limit=40)
        follow_reason = self._normalize_legacy_proactive_text(current.get("reason"), limit=40) or origin_reason or "check_in"
        if origin_reason == "morning_greeting" or follow_reason == "morning_greeting":
            after_minutes = max(after_minutes, 75)
        topic = _single_line(current.get("topic"), 80) or "刚才那条主动后面"
        motive = self._normalize_internal_motive_text(
            _single_line(current.get("motive"), 100) or "刚才那句话信息不够完整,所以想补充一句"
        )
        tone = _single_line(current.get("tone"), 30)
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(after_minutes, width_minutes=18),
            "reason": follow_reason,
            "action": "message",
            "why": "刚才那句话还有个具体点没说完,如果用户还没接住,就把那一点补上。",
            "topic": topic,
            "motive": motive,
            "scene": "前一条主动消息发出去后又过了一阵",
            "tone": "克制一点,把重点补上" if (origin_reason == "morning_greeting" or follow_reason == "morning_greeting") else (tone or "有点认真,顺手补上"),
            "impulse": "早上那句还差个重点,想补完整" if (origin_reason == "morning_greeting" or follow_reason == "morning_greeting") else "刚才那句话还有个点没落到实处,想补完整",
            "_scheduled_ts": now_ts + after_minutes * 60,
            "_origin_action": origin_action,
            "_origin_reason": origin_reason,
            "_cancel_on_inbound": True,
            "_chain_followup": True,
            "chain": remaining,
        }

    def _build_simulation_greeting_events(self) -> list[dict[str, Any]]:
        return [
            {
                "window": "08:15-10:10",
                "reason": "morning_greeting",
                "action": "message",
                "why": "早上醒来后想打个招呼",
                "topic": "刚醒",
                "scene": "一天刚醒来的时候",
                "tone": "还没完全醒",
                "impulse": "想第一时间说声早",
            },
            {
                "window": "12:05-13:35",
                "reason": "noon_greeting",
                "action": "message",
                "why": "午休或午饭时想起这边",
                "topic": "午饭后那会儿",
                "scene": "午后犯困的时候",
                "tone": "懒洋洋",
                "impulse": "想趁午后休息时打个招呼",
            },
            {
                "window": "20:10-21:20",
                "reason": "evening_greeting",
                "action": "message",
                "why": "晚上节奏慢下来时",
                "topic": "天暗下来那会儿",
                "scene": "晚上安静下来时",
                "tone": "安静",
                "impulse": "想趁还没太晚打个招呼",
            },
        ]

    def _build_simulation_events(self, user: dict[str, Any], *, duration_minutes: int = 60) -> list[dict[str, Any]]:
        plan = self.data.get("daily_story_plan", {})
        story_events = plan.get("proactive_events", []) if isinstance(plan, dict) else []
        candidates: list[dict[str, Any]] = []
        if isinstance(story_events, list):
            candidates.extend(event for event in story_events if isinstance(event, dict))
        candidates.extend(self._build_simulation_greeting_events())
        deduped = self._dedupe_proactive_events(candidates)
        ranked = sorted(
            deduped,
            key=lambda item: self._event_priority(item),
        )
        base_target = max(3, min(8, int(round(max(2.0, self._soft_daily_target(user) + 1.2)))))
        selected: list[dict[str, Any]] = []
        used_buckets: set[str] = set()
        for item in ranked:
            bucket = self._simulation_event_bucket(item)
            if bucket in used_buckets:
                continue
            selected.append(item)
            used_buckets.add(bucket)
            if len(selected) >= base_target:
                break
        if not selected:
            selected = [dict(item) for item in _SIMULATION_FALLBACK_EVENTS]
        selected = [dict(item) for item in selected]
        for item in selected:
            item["motive"] = self._normalize_event_motive(item)
        start_ts = _now_ts() + 30
        total = len(selected)
        if total == 1:
            schedule_points = [start_ts + 120]
        else:
            last_ts = start_ts + max(18 * 60, duration_minutes * 60 - 120)
            schedule_points = []
            for index in range(total):
                ratio = index / max(1, total - 1)
                base = start_ts + (last_ts - start_ts) * ratio
                jitter = random.uniform(-70, 95)
                schedule_points.append(max(start_ts + index * 70, base + jitter))
            schedule_points.sort()
        events: list[dict[str, Any]] = []
        for item, scheduled in zip(selected, schedule_points):
            cloned = dict(item)
            cloned["_scheduled_ts"] = scheduled
            cloned["_simulated_window"] = str(item.get("window") or "")
            events.append(cloned)
        return events

    def _simulation_event_bucket(self, item: dict[str, Any]) -> str:
        reason = str(item.get("reason") or "")
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            return reason
        window = str(item.get("window") or "")
        start, _ = self._parse_window_minutes(window)
        if start is None:
            return f"{reason}|misc"
        if start < 11 * 60:
            daypart = "morning"
        elif start < 15 * 60:
            daypart = "noon"
        elif start < 19 * 60:
            daypart = "evening"
        else:
            daypart = "night"
        topic = _single_line(item.get("topic"), 30)
        return f"{reason}|{daypart}|{topic}"

    def _daily_plan_morning_wake_minutes(self) -> int | None:
        """Return the Bot wake point represented by the active daily plan."""
        plan_getter = getattr(self, "_get_active_plan", None)
        plan = plan_getter() if callable(plan_getter) else self._native_daily_plan_view({})
        if not isinstance(plan, dict):
            return None
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            return None

        starts_getter = getattr(self, "_normalized_plan_item_starts", None)
        starts = starts_getter(items) if callable(starts_getter) else []
        if not isinstance(starts, list) or len(starts) != len(items):
            return None

        sleeping_ends: list[tuple[int, int]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or starts[index] is None or not self._is_sleepy_plan_item(item):
                continue
            start = int(starts[index])
            next_start = next((value for value in starts[index + 1 :] if value is not None), None)
            end = self._plan_item_end_minutes(start, item, next_start=next_start)
            wake_minute = end % (24 * 60)
            if 4 * 60 <= wake_minute <= 11 * 60 + 30:
                sleeping_ends.append((end, wake_minute))
        if sleeping_ends:
            return max(sleeping_ends, key=lambda value: value[0])[1]

        # Some plans begin at waking and omit the preceding overnight sleep segment.
        waking_items: list[tuple[int, int]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or starts[index] is None:
                continue
            text = " ".join(
                _single_line(item.get(key), 100)
                for key in ("activity", "mood", "message_seed")
                if _single_line(item.get(key), 100)
            )
            wake_minute = int(starts[index]) % (24 * 60)
            if 4 * 60 <= wake_minute <= 11 * 60 + 30 and re.search(r"睡醒|醒来|醒后|刚醒|起床|洗漱", text):
                waking_items.append((int(starts[index]), wake_minute))
        return min(waking_items, key=lambda value: value[0])[1] if waking_items else None

    def _morning_greeting_window(self) -> tuple[int, int]:
        wake_minute = self._daily_plan_morning_wake_minutes()
        if wake_minute is None:
            return 7 * 60 + 45, 10 * 60 + 20
        start = wake_minute + 3
        end = min(12 * 60, wake_minute + 50)
        if end - start < 15:
            return 7 * 60 + 45, 10 * 60 + 20
        return start, end

    def _is_initial_wakeup_greeting(
        self,
        user: dict[str, Any] | None,
        *,
        reason: str = "",
        source: str = "",
    ) -> bool:
        if not isinstance(user, dict):
            return False
        normalized_reason = self._normalize_legacy_proactive_text(
            reason or user.get("planned_proactive_reason"), limit=40
        )
        normalized_source = self._normalize_legacy_proactive_text(
            source or user.get("planned_proactive_source"), limit=40
        )
        return normalized_reason == "morning_greeting" and normalized_source == "daily_greeting"

    def _pick_daily_greeting_event(
        self, user: dict[str, Any], now: float | None = None
    ) -> dict[str, Any] | None:
        if not self.enable_daily_greetings:
            return None
        self._reset_daily_counter_if_needed(user)
        sent = user.get("greetings_sent", [])
        if not isinstance(sent, list):
            sent = []
            user["greetings_sent"] = sent
        suppressed = user.get("greetings_suppressed_by_inbound", [])
        if not isinstance(suppressed, list):
            suppressed = []
            user["greetings_suppressed_by_inbound"] = suppressed
        elif "morning_greeting" in suppressed:
            suppressed[:] = [reason for reason in suppressed if reason != "morning_greeting"]
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        minute = now_dt.hour * 60 + now_dt.minute
        recent_activity_at = self._latest_private_user_activity_ts(user)
        morning_start, morning_end = self._morning_greeting_window()
        anchors = [
            (
                "morning_greeting",
                f"{self._minutes_to_hhmm(morning_start)}-{self._minutes_to_hhmm(morning_end)}",
                "刚睡醒，想打个招呼",
                "刚醒",
            ),
            ("noon_greeting", "12:05-13:35", "中午有些犯困，想打个招呼", "午饭后那会儿"),
            ("evening_greeting", "20:10-21:20", "晚上闲下来时，想打个招呼", "天暗下来那会儿"),
        ]
        today = now_dt.date()
        candidates = []
        for reason, window, why, topic in anchors:
            if reason in sent or (reason != "morning_greeting" and reason in suppressed):
                continue
            start, end = self._parse_window_minutes(window)
            if start is None or end is None:
                continue
            if reason == "morning_greeting" and _safe_int(user.get("sent_today"), 0) > 0:
                continue
            if self._private_user_role(user) == "friend":
                bucket = self._proactive_daypart_bucket_for_minute(start)
                if _safe_int(self._today_proactive_daypart_counts(user).get(bucket), 0, 0) >= 1:
                    continue
            if (
                reason != "morning_greeting"
                and recent_activity_at > 0
                and self._inbound_satisfies_greeting(reason, now=recent_activity_at)
            ):
                if reason not in suppressed:
                    suppressed.append(reason)
                continue
            if minute >= end:
                continue
            start_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=start)
            end_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=end)
            earliest = max(now_dt + timedelta(minutes=1), start_dt)
            if earliest >= end_dt:
                continue
            if reason == "morning_greeting":
                scheduled = random.uniform(earliest.timestamp(), end_dt.timestamp())
            elif reason == "evening_greeting":
                tighten_end = min(end_dt.timestamp(), (earliest + timedelta(minutes=48)).timestamp())
                scheduled = random.uniform(earliest.timestamp(), max(earliest.timestamp() + 60, tighten_end))
            else:
                scheduled = random.uniform(earliest.timestamp(), end_dt.timestamp())
            if self._friend_proactive_scheduled_too_early(user, scheduled):
                continue
            candidates.append(
                (
                    scheduled,
                    {
                        "window": window,
                        "reason": reason,
                        "action": "message",
                        "_daily_greeting": True,
                        "why": why,
                        "topic": topic,
                        "_scheduled_ts": scheduled,
                    },
                )
            )
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _birthday_profile_matches_on_date(self, user: dict[str, Any], current: datetime) -> bool:
        profile = user.get("birthday_profile")
        if not isinstance(profile, dict):
            return False
        month = _safe_int(profile.get("month"), 0)
        day = _safe_int(profile.get("day"), 0)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return False
        if _single_line(profile.get("calendar"), 12).lower() != "lunar":
            return current.month == month and current.day == day
        if not (Converter and Solar):
            return False
        try:
            lunar = Converter.Solar2Lunar(Solar(current.year, current.month, current.day))
            return int(lunar.month) == month and int(lunar.day) == day and not bool(getattr(lunar, "isleap", False))
        except Exception as exc:
            logger.debug("[PrivateCompanion] 农历生日匹配失败: %s", _single_line(exc, 120))
            return False

    def _birthday_stage_for_date(self, user: dict[str, Any], current: datetime) -> str:
        if self._birthday_profile_matches_on_date(user, current):
            return "birthday"
        if self._birthday_profile_matches_on_date(user, current + timedelta(days=1)):
            return "eve"
        if self._birthday_profile_matches_on_date(user, current - timedelta(days=1)):
            return "after"
        return ""

    @staticmethod
    def _special_calendar_event_delivered(user: dict[str, Any], event_key: str) -> bool:
        ledger = user.get("special_event_ledger")
        if not event_key or not isinstance(ledger, dict):
            return False
        if event_key.startswith("holiday:"):
            # One merged greeting per actual day, including when the user
            # edits the selected holiday combination after an acknowledged send.
            prefix = ":".join(event_key.split(":", 2)[:2]) + ":"
            return any(str(key).startswith(prefix) and _safe_float(value, 0) > 0 for key, value in ledger.items())
        return _safe_float(ledger.get(event_key), 0) > 0

    def _pick_holiday_celebration_event(
        self, user: dict[str, Any], now: float | None = None,
    ) -> dict[str, Any] | None:
        now = _now_ts() if now is None else now
        events = [event for event in special_day_events(user, now) if event.get("kind") == "holiday"]
        if not events:
            return None
        current = datetime.fromtimestamp(now, zoneinfo.ZoneInfo("Asia/Shanghai"))
        date_text = current.date().isoformat()
        events = sorted((event for event in events if event.get("date") == date_text), key=lambda event: str(event["id"]))
        if not events:
            return None
        settings = events[0].get("context") or {}
        start_time, end_time = settings.get("start_time", "10:00"), settings.get("end_time", "20:30")
        start_h, start_m = (int(value) for value in start_time.split(":"))
        end_h, end_m = (int(value) for value in end_time.split(":"))
        start = current.replace(hour=start_h, minute=start_m, second=0, microsecond=0).timestamp()
        end = current.replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp()
        if end <= start or now >= end:
            return None
        ids = [str(event["id"]) for event in events]
        event_key = "holiday:" + date_text + ":" + ",".join(ids)
        if self._special_calendar_event_delivered(user, event_key):
            return None
        names = "、".join(str(event["name"]) for event in events)
        scheduled = max(start, now)
        return {
            "date": date_text, "window": f"{start_time}-{end_time}",
            "reason": "holiday_celebration", "action": "message",
            "topic": _single_line(f"节日 {date_text} {','.join(ids)} {names}", 60),
            "why": f"用户启用的今日节日：{names}，在指定时段合并送一次自然祝福",
            "motive": f"今天是{names}，想按节日原本的含义递一句合适的话；节日本身不证明用户放假",
            "_scheduled_ts": scheduled, "window_start_at": start,
            "preferred_ts": scheduled, "best_until_at": end - 1, "expire_at": end,
            "context_key": "planned_special_event_context",
            "context": {"event_key": event_key, "kind": "holiday", "observance_date": date_text,
                "observance_year": current.year, "holiday_ids": ids,
                "holidays": [{"id": event["id"], "name": event["name"]} for event in events],
                "timezone": "Asia/Shanghai", "start_time": start_time, "end_time": end_time,
                "window_start_at": start, "expire_at": end},
        }

    def _pick_course_reminder_event(
        self, user: dict[str, Any], now: float | None = None,
    ) -> dict[str, Any] | None:
        now = _now_ts() if now is None else now
        settings = user.get("course_timetable") if isinstance(user.get("course_timetable"), dict) else {}
        minutes = _safe_int(settings.get("remind_minutes"), 10, 0, 120)
        if minutes <= 0:
            return None
        calendar = special_calendar(user, now)
        upcoming = [item for item in calendar.get("items", [])
                    if item.get("source") == "course_timetable" and _safe_float(item.get("start_at"), 0) > now]
        if not upcoming:
            return None
        # A future course becomes a candidate only within its real pre-class
        # interval. A late tick never sends a reminder after class has started.
        course = min(upcoming, key=lambda item: (_safe_float(item.get("start_at"), 0), str(item.get("id"))))
        start = _safe_float(course.get("start_at"), 0)
        window_start = start - minutes * 60
        if now < window_start:
            return None
        identity = str(course["id"])
        event_key = "course:" + identity
        if self._special_calendar_event_delivered(user, event_key):
            return None
        local_start = datetime.fromtimestamp(start, zoneinfo.ZoneInfo("Asia/Shanghai"))
        reminder_time = datetime.fromtimestamp(window_start, local_start.tzinfo).strftime("%H:%M")
        name, location = str(course.get("name") or "课程"), str(course.get("location") or "")
        return {
            "date": str(course["date"]), "window": f"{reminder_time}-{local_start:%H:%M}",
            "reason": "course_reminder", "action": "message",
            "topic": _single_line(f"课前 {course['date']} {identity} {name}", 60),
            "why": f"用户课表中的{name}将在{local_start:%H:%M}开始" + (f"，地点{location}" if location else ""),
            "motive": "按用户自己提供的课表，课前轻轻提醒一次课程名称、开始时间与已填写的地点，不追问或催促",
            "_scheduled_ts": now, "window_start_at": window_start,
            "preferred_ts": now, "best_until_at": start - 1, "expire_at": start,
            "context_key": "planned_special_event_context",
            "context": {"event_key": event_key, "kind": "course", "course_id": identity,
                "name": name, "location": location, "date": str(course["date"]),
                "start_at": start, "end_at": _safe_float(course.get("end_at"), 0),
                "week": course.get("week"), "weekday": course.get("weekday"),
                "source": "course_timetable", "timezone": "Asia/Shanghai", "remind_minutes": minutes},
        }

    def _special_calendar_send_freshness_reason(self, user: dict[str, Any], *, now: float) -> str:
        reason = str(user.get("planned_proactive_reason") or "")
        if reason not in {"holiday_celebration", "course_reminder"}:
            return ""
        context = user.get("planned_special_event_context")
        if not isinstance(context, dict) or not context.get("event_key"):
            return "节日或课程候选缺少原始日历来源"
        if self._special_calendar_event_delivered(user, str(context["event_key"])):
            return "这次节日祝福或课前提醒已有确认送达记录"
        current = datetime.fromtimestamp(now, zoneinfo.ZoneInfo("Asia/Shanghai"))
        if reason == "holiday_celebration":
            ids = context.get("holiday_ids")
            if not isinstance(ids, list) or not ids or context.get("observance_date") != current.date().isoformat():
                return "节日祝福已不在原定日期"
            today = {str(event["id"]): event for event in special_day_events(user, now) if event.get("kind") == "holiday"}
            if any(identity not in today for identity in ids):
                return "节日祝福已停用或当天节日设置已变化"
            selected = today[ids[0]].get("context") or {}
            start_h, start_m = (int(value) for value in selected.get("start_time", "10:00").split(":"))
            end_h, end_m = (int(value) for value in selected.get("end_time", "20:30").split(":"))
            start = current.replace(hour=start_h, minute=start_m, second=0, microsecond=0).timestamp()
            end = current.replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp()
            if now >= end or end <= start:
                return "节日祝福已越过用户允许的发送窗口"
            if now < start:
                return "节日祝福的允许时段已调整，等待新窗口"
            expected = "holiday:" + current.date().isoformat() + ":" + ",".join(sorted(ids))
            return "节日候选来源已变化" if context["event_key"] != expected else ""
        calendar = special_calendar(user, now)
        course = next((item for item in calendar.get("items", [])
                       if item.get("id") == context.get("course_id") and item.get("source") == "course_timetable"), None)
        if course is None:
            return "课程提醒已停用或这节课已不在当前课表中"
        start = _safe_float(course.get("start_at"), 0)
        if start <= now:
            return "课程已经开始，不补发课前提醒"
        if abs(start - _safe_float(context.get("start_at"), 0)) > 0.5:
            return "课程开始时间已调整，原课前候选失效"
        if (str(course.get("name") or "课程") != str(context.get("name") or "")
                or str(course.get("location") or "") != str(context.get("location") or "")
                or abs(_safe_float(course.get("end_at"), 0) - _safe_float(context.get("end_at"), 0)) > 0.5):
            return "课程名称、地点或结束时间已调整，原课前文案失效"
        settings = user.get("course_timetable") if isinstance(user.get("course_timetable"), dict) else {}
        minutes = _safe_int(settings.get("remind_minutes"), 10, 0, 120)
        if minutes <= 0 or now < start - minutes * 60:
            return "课前提醒设置已调整，等待实际提醒窗口"
        if context["event_key"] != "course:" + str(course["id"]):
            return "课前提醒候选来源已变化"
        return ""

    def _pick_birthday_celebration_event(
        self,
        user: dict[str, Any],
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now = now or _now_ts()
        if self._private_user_role(user) != "owner" or bool(user.get("birthday_celebration_opt_out")):
            return None
        current = self._environment_fromtimestamp(now)
        stage = self._birthday_stage_for_date(user, current)
        if not stage:
            return None
        event = user.get("birthday_event") if isinstance(user.get("birthday_event"), dict) else {}
        minute = current.hour * 60 + current.minute
        year = current.year if stage == "birthday" else ((current + timedelta(days=1)).year if stage == "eve" else (current - timedelta(days=1)).year)

        if stage == "eve":
            recent_activity = self._latest_private_user_activity_ts(user)
            if _safe_int(event.get("eve_year"), 0) == year or _safe_int(user.get("ignored_streak"), 0) > 0:
                return None
            if recent_activity <= 0 or now - recent_activity > 7 * 24 * 3600 or not (17 * 60 + 30 <= minute < 21 * 60 + 30):
                return None
            scheduled = now + random.randint(8, 38) * 60
            return {
                "window": self._window_from_delay_minutes(max(5, int((scheduled - now) / 60)), width_minutes=48),
                "reason": "birthday_eve_hint",
                "action": "message",
                "why": "明天是一个值得为自己留一点空白的日子，先轻轻递一句，不提前揭开仪式",
                "topic": "明天给自己留一点空白",
                "motive": "明天想让对方放松一点",
                "_scheduled_ts": scheduled,
                "_birthday_stage": "eve",
                "context_key": "planned_birthday_event_context",
                "context": {"observance_year": year},
            }

        if stage == "birthday":
            if _safe_int(event.get("celebrated_year"), 0) == year or minute >= 22 * 60:
                return None
            if _safe_int(user.get("ignored_streak"), 0, 0) > 0 and minute < 18 * 60:
                return None
            if minute < 9 * 60 + 30:
                scheduled = current.replace(hour=10, minute=random.randint(5, 45), second=0, microsecond=0).timestamp()
            elif minute < 18 * 60 + 30:
                scheduled = now + random.randint(12, 75) * 60
            else:
                scheduled = now + random.randint(8, 35) * 60
            action = "photo_text" if self._photo_text_available(user) and random.random() < 0.58 else "message"
            return {
                "window": self._window_from_delay_minutes(max(5, int((scheduled - now) / 60)), width_minutes=75),
                "reason": "birthday_celebration",
                "action": action,
                "why": "今天是用户明确允许记住的生日，想认真递上一份不造成压力的小惊喜",
                "topic": "今天只属于你的生日小惊喜",
                "motive": "今天是对方生日，想留一份小惊喜",
                "_scheduled_ts": scheduled,
                "_birthday_stage": "birthday",
                "context_key": "planned_birthday_event_context",
                "context": {"observance_year": year},
            }

        celebrated_at = _safe_float(event.get("celebrated_at"), 0)
        if _safe_int(event.get("celebrated_year"), 0) != year:
            if minute >= 14 * 60:
                return None
            scheduled = now + random.randint(8, 35) * 60
            return {
                "window": self._window_from_delay_minutes(max(5, int((scheduled - now) / 60)), width_minutes=58),
                "reason": "birthday_makeup",
                "action": "message",
                "why": "昨天的生日仪式因时机错过，只在第二天午前低调补上一句",
                "topic": "迟到一点的生日祝福",
                "motive": "昨天错过了祝福，今天补上",
                "_scheduled_ts": scheduled,
                "_birthday_stage": "makeup",
                "context_key": "planned_birthday_event_context",
                "context": {"observance_year": year},
            }
        if _safe_int(event.get("afterglow_year"), 0) == year or celebrated_at <= 0:
            return None
        last_user_at = _safe_float(user.get("last_user_message_at"), 0)
        if last_user_at <= celebrated_at or minute >= 21 * 60 + 30:
            return None
        scheduled = now + random.randint(18, 70) * 60
        return {
            "window": self._window_from_delay_minutes(max(5, int((scheduled - now) / 60)), width_minutes=55),
            "reason": "birthday_afterglow",
            "action": "message",
            "why": "用户已经在生日祝福后有过回应，轻轻接住那点余温，不再重复庆祝",
            "topic": "昨天留下的一点开心",
            "motive": "昨天的开心还没散",
            "_scheduled_ts": scheduled,
            "_birthday_stage": "afterglow",
            "context_key": "planned_birthday_event_context",
            "context": {"observance_year": year},
        }

    def _birthday_curiosity_has_known_birthday(self, user: dict[str, Any]) -> bool:
        profile = user.get("birthday_profile")
        if isinstance(profile, dict) and (_safe_int(profile.get("month"), 0) or _single_line(profile.get("raw"), 80)):
            return True
        memory = user.get("companion_memory")
        items = memory.get("items") if isinstance(memory, dict) else []
        if not isinstance(items, list):
            return False
        for item in items:
            text = _single_line(item.get("text"), 260) if isinstance(item, dict) else _single_line(item, 260)
            if not text or "生日" not in text:
                continue
            if re.search(r"(?:不想|不愿|不方便|别|不要|不告诉).{0,8}生日", text):
                continue
            if re.search(r"(?:生日.{0,12}(?:是|在|：|:)|(?:农历|公历).{0,8}生日|我.{0,4}生日).{0,30}", text):
                return True
        return False

    def _pick_birthday_curiosity_event(
        self,
        user: dict[str, Any],
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now = now or _now_ts()
        if self._private_user_role(user) != "owner":
            return None
        if bool(user.get("birthday_curiosity_opt_out")) or self._birthday_curiosity_has_known_birthday(user):
            return None
        if _safe_float(user.get("birthday_curiosity_asked_at"), 0) > 0:
            return None
        if _safe_int(user.get("ignored_streak"), 0, 0) > 0:
            return None
        last_message_at = _safe_float(user.get("last_user_message_at"), 0)
        if last_message_at <= 0 or now - last_message_at > 14 * 24 * 3600:
            return None
        memory = user.get("companion_memory")
        memory_items = memory.get("items") if isinstance(memory, dict) else []
        if not isinstance(memory_items, list) or len(memory_items) < 3:
            return None
        if _safe_float(user.get("last_sent"), 0) > 0 and now - _safe_float(user.get("last_sent"), 0) < 18 * 3600:
            return None
        next_check_at = _safe_float(user.get("birthday_curiosity_next_check_at"), 0)
        if next_check_at > now:
            return None
        user["birthday_curiosity_next_check_at"] = now + random.randint(21, 45) * 24 * 3600
        if random.random() > 0.16:
            return None
        scheduled = now + random.randint(35, 130) * 60
        scheduled = self._move_timestamp_into_reason_window(scheduled, "birthday_curiosity")
        return {
            "window": self._window_from_delay_minutes(max(5, int((scheduled - now) / 60)), width_minutes=42),
            "reason": "birthday_curiosity",
            "action": "message",
            "why": "相处了一阵后，想低调地知道一个将来可以认真记住的小日子",
            "topic": "你的生日是哪一天",
            "motive": "好奇对方的生日",
            "_scheduled_ts": scheduled,
            "_birthday_curiosity": True,
        }

    def _pick_story_plan_event(
        self,
        now: float | None = None,
        *,
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        plan = self.data.get("daily_story_plan", {})
        if not isinstance(plan, dict) or not self._is_plan_date_active(plan.get("date")):
            return None
        events = plan.get("proactive_events", [])
        if not isinstance(events, list):
            return None
        now = now or _now_ts()
        future_events = []
        for event in events:
            if not isinstance(event, dict):
                continue
            if _single_line(event.get("lifecycle_status"), 20).lower() in {"cancelled", "canceled", "取消", "已取消"}:
                continue
            if self._unverified_social_relay_plan_reason(
                event,
                source="event",
                has_trigger=bool(_single_line(event.get("trigger_message_id"), 120)),
            ):
                continue
            event_ts = self._timestamp_from_story_event(event, str(event.get("reason") or "check_in"))
            if event_ts > now or (event_ts > 0 and now - event_ts <= self.max_proactive_plan_lag_minutes * 60):
                future_events.append((event_ts, event))
        if not future_events:
            return None
        future_events.sort(key=lambda item: item[0])
        shortlist = future_events[:6]
        weighted: list[tuple[dict[str, Any], float]] = []
        daypart_counts = self._today_proactive_daypart_counts(user or {})
        friend_user = isinstance(user, dict) and self._private_user_role(user) == "friend"
        for index, (_, event) in enumerate(shortlist):
            event_ts = self._timestamp_from_story_event(event, str(event.get("reason") or "check_in"))
            if friend_user and user is not None and self._friend_proactive_scheduled_too_early(user, event_ts):
                continue
            priority_tuple = self._event_priority(event)
            priority_score = float(-priority_tuple[0])
            weight = 1.0 + priority_score * 0.08 + max(0.0, 0.45 - index * 0.06)
            bucket = self._proactive_daypart_bucket_for_event(event)
            sent_in_bucket = _safe_int(daypart_counts.get(bucket), 0, 0) if bucket else 0
            if friend_user and bucket and sent_in_bucket >= 1:
                continue
            if bucket == "late_night" and sent_in_bucket >= 1 and not self._is_sticky_greeting_event(event):
                continue
            if bucket and sent_in_bucket >= 2 and not self._is_sticky_greeting_event(event):
                continue
            if sent_in_bucket > 0:
                weight *= max(0.22, 0.56 ** sent_in_bucket)
            if bucket == "late_night":
                weight *= 0.72
            weighted.append((event, weight))
        if not weighted and shortlist:
            for _, event in shortlist:
                if self._is_sticky_greeting_event(event):
                    weighted.append((event, 1.0))
                    break
        if not weighted:
            return None
        return self._weighted_choice(weighted)

    def _today_proactive_daypart_counts(self, user: dict[str, Any]) -> dict[str, int]:
        if not isinstance(user, dict):
            return {}
        self._reset_daily_counter_if_needed(user)
        raw = user.get("proactive_daypart_counts")
        if not isinstance(raw, dict):
            raw = {}
            user["proactive_daypart_counts"] = raw
        counts: dict[str, int] = {}
        for key, value in raw.items():
            text_key = str(key or "")
            if text_key:
                counts[text_key] = _safe_int(value, 0, 0)
        return counts

    def _proactive_daypart_bucket_for_event(self, event: dict[str, Any]) -> str:
        reason = str(event.get("reason") or "check_in")
        event_ts = self._timestamp_from_story_event(event, reason)
        if event_ts <= 0:
            start, _ = self._parse_window_minutes(str(event.get("window") or ""))
            if start is None:
                return ""
            minute = start
        else:
            when = self._environment_fromtimestamp(event_ts)
            minute = when.hour * 60 + when.minute
        return self._proactive_daypart_bucket_for_minute(minute)

    def _proactive_daypart_bucket_for_timestamp(self, timestamp: float) -> str:
        if timestamp <= 0:
            return ""
        when = self._environment_fromtimestamp(timestamp)
        return self._proactive_daypart_bucket_for_minute(when.hour * 60 + when.minute)

    def _planned_event_exceeds_daypart_cap(self, user: dict[str, Any], reason: str, scheduled_at: float) -> bool:
        if reason in {"insomnia_night", "important_date_share"}:
            return False
        if self._friend_proactive_scheduled_too_early(user, scheduled_at):
            return True
        bucket = self._proactive_daypart_bucket_for_timestamp(scheduled_at)
        if not bucket:
            return False
        counts = self._today_proactive_daypart_counts(user)
        sent_in_bucket = _safe_int(counts.get(bucket), 0, 0)
        if self._private_user_role(user) == "friend":
            return sent_in_bucket >= 1
        if bucket == "late_night":
            return sent_in_bucket >= 1
        return sent_in_bucket >= 2

    @staticmethod
    def _proactive_daypart_bucket_for_minute(minute: int) -> str:
        if minute < 11 * 60:
            return "morning"
        if minute < 14 * 60 + 30:
            return "noon"
        if minute < 18 * 60:
            return "afternoon"
        if minute < 21 * 60:
            return "evening"
        return "late_night"

    def _note_proactive_daypart_sent(self, user: dict[str, Any], sent_at: float | None = None) -> None:
        self._reset_daily_counter_if_needed(user)
        when = self._environment_fromtimestamp(sent_at or _now_ts())
        bucket = self._proactive_daypart_bucket_for_minute(when.hour * 60 + when.minute)
        raw = user.setdefault("proactive_daypart_counts", {})
        if not isinstance(raw, dict):
            raw = {}
            user["proactive_daypart_counts"] = raw
        raw[bucket] = _safe_int(raw.get(bucket), 0, 0) + 1

    # _note_action_sent / _note_action_reply_feedback 的亲和与照片计数逻辑
    # 已合并进 UserMemoryMixin 同名方法（MRO在前的赢家）；此处副本曾是永不可达的死代码
    def _note_photo_generation_attempt(self, user_id: str, image_path: str = "") -> None:
        if not str(user_id or "").strip():
            return
        today = _today_key()
        user = self._get_user(str(user_id or ""))
        if user.get("photo_generated_day") != today:
            user["photo_generated_day"] = today
            user["photo_generated_today"] = 0
        user["photo_generated_today"] = _safe_int(user.get("photo_generated_today"), 0) + 1
        user["last_generated_photo_path"] = _single_line(image_path, 260)
        user["last_generated_photo_at"] = _now_ts()

    def _note_screen_peek_attempt(self, user_id: str, reason: str = "", *, count_daily: bool = True) -> None:
        if not str(user_id or "").strip():
            return
        today = _today_key()
        user = self._get_user(str(user_id or ""))
        if user.get("screen_peek_day") != today:
            user["screen_peek_day"] = today
            user["screen_peek_today"] = 0
        if count_daily:
            user["screen_peek_today"] = _safe_int(user.get("screen_peek_today"), 0) + 1
        user["screen_peek_last_at"] = _now_ts()
        user["last_screen_peek_reason"] = _single_line(reason, 120)
        if not count_daily:
            user["last_unanswered_screen_peek_at"] = _now_ts()

    def _screen_peek_failure_cooldown_active(self, user: dict[str, Any] | None = None, *, now: float | None = None) -> bool:
        if not isinstance(user, dict):
            return False
        check_now = _now_ts() if now is None else now
        return _safe_float(user.get("screen_peek_failure_until"), 0.0) > check_now

    def _note_screen_peek_failure(self, user: dict[str, Any] | None, reason: str = "", *, cooldown_minutes: int = 60) -> None:
        if not isinstance(user, dict):
            return
        now = _now_ts()
        user["screen_peek_failure_until"] = now + max(5, _safe_int(cooldown_minutes, 60, 5)) * 60
        user["screen_peek_failure_reason"] = _single_line(reason, 180)
        user["screen_peek_failure_count"] = _safe_int(user.get("screen_peek_failure_count"), 0, 0) + 1
        try:
            self._save_data_sync()
        except Exception:
            pass

    def _maybe_make_followup_event(self, user: dict[str, Any], reason: str, action: str) -> dict[str, Any] | None:
        daily_limit = self._effective_user_daily_limit(user)
        if (
            not self._proactive_daily_limit_is_unlimited(daily_limit)
            and _safe_int(user.get("sent_today"), 0) >= max(0, daily_limit - 1)
        ):
            return None
        if action not in {"photo_text", "poke", "voice", "screen_peek"} and "+" not in action:
            return None
        chance = 0.12
        if "voice" in action:
            chance += 0.06
        if "photo_text" in action:
            chance += 0.05
        if "poke" in action:
            chance += 0.03
        if random.random() > chance:
            return None
        delay_minutes = random.randint(22, 95)
        follow_reason = "check_in" if action in {"poke", "screen_peek"} else "diary_share"
        topic = {
            "photo_text": "对发送的图片进行补充说明",
            "poke": "刚才戳完之后进行补充说明",
            "voice": "发完语音后的互动",
            "screen_peek": "偷看用户屏幕后的互动",
        }.get(action.split("+")[0], "刚刚那条主动后面")
        motive = {
            "photo_text": "刚才发完图以后，想和{name}聊聊",
            "poke": "刚才戳完以后，想和{name}聊聊",
            "voice": "刚才发完语音消息以后，想和{name}聊聊",
            "screen_peek": "刚才看过屏幕后，想问问{name}现在还忙不忙",
        }.get(action.split("+")[0], "刚才那条主动后面，还有一句话想补上")
        display_name = _single_line(user.get("nickname") or self.default_nickname, 24)
        if display_name:
            motive = motive.replace("{name}", display_name)
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(delay_minutes, width_minutes=26),
            "reason": follow_reason,
            "action": "message",
            "why": "上一条主动消息之后进行自然的接话",
            "topic": topic,
            "motive": motive,
            "scene": "上一条主动消息发出去之后的互动",
            "tone": "自然",
            "impulse": "想接着刚才的话继续聊聊",
            "_scheduled_ts": _now_ts() + delay_minutes * 60,
            "_origin_action": action,
            "_origin_reason": reason,
            "_cancel_on_inbound": True,
        }

    def _bot_currently_bored_for_unanswered_peek(self, user: dict[str, Any]) -> bool:
        text_parts = [
            user.get("last_proactive_reason"),
            user.get("last_proactive_action"),
            user.get("last_proactive_motive"),
            user.get("planned_proactive_reason"),
            user.get("planned_proactive_motive"),
        ]
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        if isinstance(current_item, dict):
            text_parts.extend(
                [
                    current_item.get("activity"),
                    current_item.get("mood"),
                    current_item.get("message_seed"),
                ]
            )
        snapshot = self._current_story_plan_snapshot()
        if isinstance(snapshot, dict):
            text_parts.extend(snapshot.values())
        text = " ".join(_single_line(part, 80) for part in text_parts if part)
        bored_tokens = (
            "无聊", "发呆", "摸鱼", "闲", "空", "没事", "百无聊赖", "松下来",
            "喘口气", "空档", "空隙", "刷视频", "短视频", "休息",
        )
        if any(token in text for token in bored_tokens):
            return True
        reason = self._normalize_legacy_proactive_text(user.get("last_proactive_reason") or user.get("planned_proactive_reason"), limit=40)
        return reason in {"check_in", "quiet_care", "background_schedule"} and _safe_int(user.get("ignored_streak"), 0) >= 1

    def _maybe_make_unanswered_screen_peek_event(
        self,
        user: dict[str, Any],
        reason: str,
        action: str,
    ) -> dict[str, Any] | None:
        if not self.enable_unanswered_screen_peek_followup:
            return None
        if "screen_peek" in str(action or ""):
            return None
        if not self._screen_glance_available(user, ignore_daily_limit=True):
            return None
        now = _now_ts()
        cooldown = max(30, self.unanswered_screen_peek_cooldown_minutes) * 60
        last_at = _safe_float(user.get("last_unanswered_screen_peek_at"), 0)
        if last_at > 0 and now - last_at < cooldown:
            return None
        if not self._bot_currently_bored_for_unanswered_peek(user):
            return None
        delay_minutes = max(10, self.unanswered_screen_peek_after_minutes)
        return {
            "date": _today_key(),
            "window": self._window_from_delay_minutes(delay_minutes, width_minutes=18),
            "reason": "check_in",
            "action": "screen_peek",
            "why": "上一条之后那边一直安静，想看一眼是不是还在忙。",
            "topic": "看看那边是不是还在忙",
            "motive": "那边一直安静着",
            "scene": "上一条主动消息之后的安静空档",
            "tone": "好奇",
            "impulse": "想看一眼那边是不是还在忙",
            "_scheduled_ts": now + delay_minutes * 60,
            "_cancel_on_inbound": True,
            "_unanswered_screen_peek": True,
            "_free_screen_peek": True,
            "_origin_action": action,
            "_origin_reason": reason,
        }

    def _window_from_delay_minutes(self, delay_minutes: int, width_minutes: int = 24) -> str:
        start_dt = self._environment_fromtimestamp(_now_ts() + max(5, delay_minutes) * 60)
        end_dt = start_dt + timedelta(minutes=max(12, width_minutes))
        return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"

    def _timestamp_from_story_event(self, event: dict[str, Any], reason: str) -> float:
        scheduled_ts = _safe_float(event.get("_scheduled_ts"), 0)
        if scheduled_ts > 0:
            return scheduled_ts
        window = str(event.get("window") or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", window)
        now_dt = self._environment_now()
        today = now_dt.date()
        if match:
            sh, sm, eh, em = [int(part) for part in match.groups()]
            start = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo).replace(hour=sh % 24, minute=sm)
            end = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo).replace(hour=eh % 24, minute=em)
            if end <= start:
                end = end + timedelta(days=1)
            if now_dt >= end:
                return 0
            earliest = max(start.timestamp(), (now_dt + timedelta(seconds=45)).timestamp())
            latest = end.timestamp()
            if earliest >= latest:
                return 0
            scheduled = random.uniform(earliest, latest)
            event["_scheduled_ts"] = scheduled
            return scheduled
        scheduled = self._move_timestamp_into_reason_window(_now_ts() + random.uniform(2 * 3600, 10 * 3600), reason)
        event["_scheduled_ts"] = scheduled
        return scheduled

    def _parse_window_minutes(self, window: str) -> tuple[int | None, int | None]:
        normalized = (
            str(window or "")
            .replace("：", ":")
            .replace("—", "-")
            .replace("–", "-")
            .replace("－", "-")
            .replace("~", "-")
            .replace("～", "-")
            .replace("至", "-")
            .replace("到", "-")
        )
        match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", normalized)
        if not match:
            return None, None
        sh, sm, eh, em = [int(part) for part in match.groups()]
        start = (sh % 24) * 60 + sm
        end = (eh % 24) * 60 + em
        if end <= start:
            end += 24 * 60
        return start, end

    def _choose_planned_reason(self) -> str:
        state = self.data.get("daily_state", {})
        can_do = self.data.get("can_do", [])
        diaries = self.data.get("bot_diaries", [])
        important_dates = self._get_relevant_important_dates()
        users = self.data.get("users", {})
        has_recent_user_message = False
        if isinstance(users, dict):
            for raw_user in users.values():
                if not isinstance(raw_user, dict):
                    continue
                if _single_line(raw_user.get("last_user_message"), 24):
                    has_recent_user_message = True
                    break
        has_contextual_source = bool(
            (isinstance(can_do, list) and can_do)
            or (isinstance(diaries, list) and diaries)
            or important_dates
            or self.include_schedule_in_messages
        )
        reasons = ["activity_share", "activity_share", "diary_share"]
        if not has_contextual_source:
            reasons.append("check_in")
        if self._has_active_insomnia_state():
            reasons.extend(["insomnia_night"] * 2)
        if isinstance(state, dict) and state.get("conditions"):
            reasons.extend(["quiet_care"])
        if isinstance(can_do, list) and can_do:
            reasons.extend(["activity_share"] * 3)
        if isinstance(diaries, list) and diaries:
            reasons.extend(["diary_share"] * 2)
        if important_dates:
            reasons.extend(["important_date_share"] * 2)
        if self.include_schedule_in_messages:
            reasons.extend(["background_schedule"] * 2)
        state_note = _single_line(state.get("note"), 80) if isinstance(state, dict) else ""
        state_mood = _single_line(state.get("mood_bias"), 20) if isinstance(state, dict) else ""
        if any(token in state_note for token in ("疲惫", "收声", "安静", "慢一点")) or state_mood in {"安静", "疲惫"}:
            reasons.extend(["quiet_care"])
        if has_recent_user_message:
            reasons.extend(["quiet_care"])
        return random.choice(reasons)

    def _is_greeting_reason(self, reason: str) -> bool:
        return self._normalize_legacy_proactive_text(reason, limit=40) in {"morning_greeting", "noon_greeting", "evening_greeting"}

    def _is_sticky_greeting_reason(self, reason: str) -> bool:
        return self._normalize_legacy_proactive_text(reason, limit=40) in {"morning_greeting", "noon_greeting", "evening_greeting"}

    def _greeting_min_interval_seconds(self, reason: str) -> int:
        if reason == "morning_greeting":
            return 45 * 60
        if reason == "evening_greeting":
            return 60 * 60
        if reason == "noon_greeting":
            return 60 * 60
        return 120 * 60

    def _reschedule_greeting_within_window(
        self,
        user: dict[str, Any],
        reason: str,
        *,
        now: float | None = None,
    ) -> bool:
        if not self._is_sticky_greeting_reason(reason):
            return False
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        windows = self._reason_windows(reason)
        if not windows:
            return False
        today = now_dt.date()
        for start, end in windows:
            start_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=start)
            end_dt = datetime.combine(today, datetime.min.time(), tzinfo=now_dt.tzinfo) + timedelta(minutes=end)
            if now_dt >= end_dt:
                continue
            earliest = max(now_dt + timedelta(minutes=random.randint(6, 14)), start_dt)
            latest = end_dt - timedelta(minutes=3)
            if earliest >= latest:
                continue
            user["next_proactive_at"] = random.uniform(earliest.timestamp(), latest.timestamp())
            return True
        return False

    def _is_now_in_reason_window(self, reason: str, now: float | None = None) -> bool:
        if not reason:
            return False
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        minute_of_day = now_dt.hour * 60 + now_dt.minute
        for start, end in self._reason_windows(reason):
            if start <= minute_of_day <= end:
                return True
        return False

    def _inbound_satisfies_greeting(self, reason: str, *, now: float | None = None) -> bool:
        if not self._is_greeting_reason(reason):
            return False
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        minute_of_day = now_dt.hour * 60 + now_dt.minute
        lead_minutes = {
            "morning_greeting": 10,
            "noon_greeting": 10,
            "evening_greeting": 10,
        }.get(reason, 10)
        for start, end in self._reason_windows(reason):
            if start - lead_minutes <= minute_of_day < end:
                return True
        return False

    def _proactive_text_greeting_reason(self, text: str, *, now: float | None = None) -> str:
        cleaned = _single_line(text, 260)
        if not cleaned:
            return ""
        compact = re.sub(r"\s+", "", cleaned)
        # Allow a short address before the greeting, e.g. "比折，早……" or "主人早".
        compact = re.sub(r"^[\u4e00-\u9fffA-Za-z0-9_\-]{1,12}[,，、:：]+", "", compact, count=1)
        for marker in ("早", "午安", "中午", "晚上", "晚好"):
            index = compact.find(marker)
            if 0 < index <= 6:
                compact = compact[index:]
                break
        now_dt = self._environment_fromtimestamp(now or _now_ts())
        minute = now_dt.hour * 60 + now_dt.minute
        if compact == "早" or (
            compact.startswith("早")
            and (
                compact[1:2] in {"", ".", "。", "…", "·", "~", "～", "!", "！", ",", "，", "、", "呀", "啊", "安", "上", "哇", "哦", "欸", "诶"}
            )
        ):
            return "morning_greeting"
        if compact.startswith(("午安", "中午好", "午好")) or (compact.startswith("中午") and compact[2:3] in {"，", ",", "。", ".", "!", "！", "~", "～"}):
            return "noon_greeting"
        if compact.startswith(("晚上好", "晚好")) or (compact.startswith("晚上") and compact[2:3] in {"，", ",", "。", ".", "!", "！", "~", "～"}):
            return "evening_greeting"
        if re.search(r"(?:早晨|早上).{0,12}(?:安静|洗漱|刚醒|醒来|开机|早安|问候)", compact) and minute < 11 * 60:
            return "morning_greeting"
        return ""

    def _textual_greeting_duplicate_reason(
        self,
        user: dict[str, Any],
        text: str,
        *,
        now: float | None = None,
    ) -> str:
        reason = self._proactive_text_greeting_reason(text, now=now)
        if not reason:
            return ""
        self._reset_daily_counter_if_needed(user)
        sent = user.get("greetings_sent", [])
        if not isinstance(sent, list):
            sent = []
            user["greetings_sent"] = sent
        suppressed = user.get("greetings_suppressed_by_inbound", [])
        if not isinstance(suppressed, list):
            suppressed = []
            user["greetings_suppressed_by_inbound"] = suppressed
        if reason in sent:
            return "该问候时段今天已经主动问候过"
        if reason in suppressed:
            return "该问候时段已被用户自然互动占掉"
        if reason == "morning_greeting" and _safe_int(user.get("sent_today"), 0, 0) > 0:
            return "早安只适合作为当天第一句主动消息"
        return ""

    def _mark_textual_greeting_sent(
        self,
        user: dict[str, Any],
        text: str,
        *,
        sent_at: float | None = None,
    ) -> bool:
        reason = self._proactive_text_greeting_reason(text, now=sent_at)
        if not reason:
            return False
        self._reset_daily_counter_if_needed(user)
        sent = user.setdefault("greetings_sent", [])
        if not isinstance(sent, list):
            sent = []
            user["greetings_sent"] = sent
        if reason in sent:
            return False
        sent.append(reason)
        return True

    def _mark_greeting_satisfied_by_inbound(self, user: dict[str, Any], reason: str) -> bool:
        if not self._is_greeting_reason(reason):
            return False
        self._reset_daily_counter_if_needed(user)
        suppressed = user.setdefault("greetings_suppressed_by_inbound", [])
        if not isinstance(suppressed, list):
            suppressed = []
            user["greetings_suppressed_by_inbound"] = suppressed
        if reason in suppressed:
            return False
        suppressed.append(reason)
        return True

    def _mark_greetings_satisfied_by_recent_activity(
        self,
        user: dict[str, Any],
        *,
        activity_ts: float,
    ) -> bool:
        if not isinstance(user, dict) or activity_ts <= 0:
            return False
        changed = False
        for reason in ("noon_greeting", "evening_greeting"):
            if self._inbound_satisfies_greeting(reason, now=activity_ts):
                changed = self._mark_greeting_satisfied_by_inbound(user, reason) or changed
        return changed

    def _parse_action_list(self, raw: Any) -> set[str]:
        if raw is None:
            return set()
        if isinstance(raw, str):
            parts = re.split(r"[,\s,、;；]+", raw)
        elif isinstance(raw, list):
            parts = raw
        else:
            parts = []
        return {str(part).strip() for part in parts if str(part).strip()}

    @staticmethod
    def _parse_json_object(raw: Any) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
        candidates = [text]
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _visual_share_tokens(self) -> tuple[str, ...]:
        # Broad visual anchors only. Specific subjects should be chosen by the model from context.
        return (
            "看", "拍", "图", "照片", "画面", "颜色", "形状", "光", "影", "反光",
            "桌", "纸", "书", "本", "笔", "杯", "饭", "饮", "路", "窗", "镜",
            "小物", "随手", "涂", "画", "包装", "屏幕", "边角",
        )

    def _strong_photo_share_intent(self, *parts: Any) -> bool:
        text = " ".join(_single_line(part, 160) for part in parts if _single_line(part, 160))
        if not text:
            return False
        strong_tokens = ("拍了张照", "拍了照", "拍照", "照片", "图片", "发你看", "给你看", "你看看")
        if any(token in text for token in strong_tokens):
            return True
        visual_tokens = (
            "花", "颜色", "蓝紫", "矮牵牛", "雨", "小雨", "毛毛雨", "路边", "校门",
            "晚霞", "阳光", "云", "窗边", "倒影", "影子", "小猫", "桌面", "杯", "包装",
        )
        return sum(1 for token in visual_tokens if token in text) >= 2

    def _days_since_last_photo_sent(self, user: dict[str, Any] | None = None) -> int | None:
        if not isinstance(user, dict):
            return None
        day_text = str(user.get("photo_sent_day") or "").strip()
        if not day_text:
            return None
        try:
            last_day = datetime.strptime(day_text[:10], "%Y-%m-%d").date()
            today = datetime.strptime(_today_key(), "%Y-%m-%d").date()
            return max(0, (today - last_day).days)
        except Exception:
            return None

    def _photo_text_overdue_boost(self, user: dict[str, Any] | None = None) -> float:
        days = self._days_since_last_photo_sent(user)
        if days is None:
            return 0.18
        if days >= 10:
            return 0.22
        if days >= 5:
            return 0.12
        if days >= 2:
            return 0.05
        return 0.0

    def _photo_text_plan_field_patch(
        self,
        *,
        reason: str,
        topic: str = "",
        motive: str = "",
        planned_event: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        current_text = self._format_plan_item_for_prompt(current_item)
        event_text = ""
        if isinstance(planned_event, dict):
            event_text = " ".join(
                _single_line(planned_event.get(key), 80)
                for key in ("topic", "scene", "why", "motive", "impulse")
            )
        seed = _single_line(topic, 60) or _single_line(event_text, 60) or _single_line(current_text, 60)
        if not seed:
            seed = {
                "morning_greeting": "早上眼前那点小画面",
                "noon_greeting": "中午手边的小东西",
                "evening_greeting": "晚一点的光线",
                "diary_share": "今天记下来的画面",
                "background_schedule": "手边这一小段",
            }.get(reason, "眼前这个小画面")
        cleaned_seed = re.sub(r"^(?:刚刚|刚才|现在|这会儿)\s*", "", seed).strip(" ，,。")
        patched_topic = _single_line(cleaned_seed, 60) or "眼前这个小画面"
        text = " ".join([motive, topic, event_text, current_text])
        selfie_tokens = ("自拍", "穿搭", "衣服", "校服", "镜子", "发型", "脸", "表情")
        if any(token in text for token in selfie_tokens):
            patched_motive = f"看到“{patched_topic}”那一下,第一反应是想自拍一张给你看"
        else:
            patched_motive = f"看到“{patched_topic}”那一下,第一反应是想拍下来发给你"
        return {
            "topic": self._soften_topic_hook(patched_topic),
            "motive": self._normalize_internal_motive_text(patched_motive),
        }

    def _pick_life_thought_topic(self, reason: str = "") -> str:
        terms = self._worldview_terms()
        if reason == "group_share":
            return f"{terms['group_chat']}里那段片段"
        if reason == "bili_video_share":
            return f"刚看到的{terms['video']}"
        if reason == "news_share":
            return "刚看到的一条新闻"
        if reason == "creative_share":
            return "刚写到的小说片段"
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        activity = _single_line((current_item or {}).get("activity"), 36)
        if activity:
            return f"{activity}里自然冒出来的小内容"
        if reason == "diary_share":
            return "今天记录里想给你看看的一小段"
        return "当前时段里自然冒出来的小内容"

    def _format_content_choice_options_for_prompt(self, action: Any = None) -> str:
        terms = self._worldview_terms()
        if terms.get("mode") == "fantasy":
            object_examples = "营火边、行囊、靴扣、地图角、药草包、酒馆杯沿、委托纸、斗篷边、旅店窗、书页边缘"
            record_examples = "旅记、委托备忘、魔法笔记、读到的藏书里的一小句,或某个没写完的标题"
            photo_examples = "适合用水晶映像或随手画面递给熟人的具体场景"
        elif terms.get("mode") == "sci_fi":
            object_examples = "终端边、舱窗、随身包、杯沿、数据板、照明条、维修工具、航行日志、制服边角、资料页边缘"
            record_examples = "航行日志、终端备忘、读到的资料/影像流里的一小句,或某个没写完的标题"
            photo_examples = "适合用终端快照递给熟人的具体画面"
        else:
            object_examples = "桌边、手边、路上、食物、衣物、门口、杯沿、包装、车窗、书页边缘"
            record_examples = "日记、备忘录、作业、阅读/刷到内容里的一小句,或某个没写完的标题"
            photo_examples = "任何当前场景里适合顺手拍给熟人的具体画面"
        has_action_limit = action is not None and bool(str(action).strip())
        normalized_action = str(action or "").strip().lower()
        is_photo_action = "photo" in normalized_action or "image" in normalized_action or normalized_action in {"selfie", "text2img"}
        is_touch_action = "poke" in normalized_action
        is_voice_action = "voice" in normalized_action or "tts" in normalized_action
        options: list[str] = []
        if not has_action_limit:
            options.extend(
                [
                    f"- 眼前物：从当前{terms['schedule']}里的{object_examples}等具体物件里自选一个。",
                    "- 脑内念头：一句突然冒出来的短想法、吐槽、联想或没头没尾的小结论。",
                    "- 输入残留：上一轮聊天留下的余味、没接完的话、想补但没正式补的一点。",
                    f"- 记录碎片：{record_examples}。",
                    f"- 可拍画面：{photo_examples},不限定天气。",
                    "- 关系试探：想靠近但不直说的半句、说完就停，不追问。",
                ]
            )
        elif is_photo_action:
            options.extend(
                [
                    f"- 眼前物：从当前{terms['schedule']}里的{object_examples}等具体物件里自选一个。",
                    f"- 可拍画面：{photo_examples},不限定天气。",
                ]
            )
        elif is_touch_action:
            options.extend(
                [
                    "- 脑内念头：一句突然冒出来的短想法、吐槽、联想或没头没尾的小结论。",
                    "- 输入残留：上一轮聊天留下的余味、没接完的话、想补但没正式补的一点。",
                    "- 关系试探：想靠近但不直说的半句、说完就停，不追问。",
                ]
            )
        elif is_voice_action:
            options.extend(
                [
                    "- 脑内念头：一句突然冒出来的短想法、吐槽、联想或没头没尾的小结论。",
                    "- 输入残留：上一轮聊天留下的余味、没接完的话、想补但没正式补的一点。",
                    f"- 记录碎片：{record_examples}。",
                    "- 关系试探：想靠近但不直说的半句、说完就停，不追问。",
                ]
            )
        else:
            options.extend(
                [
                    f"- 眼前物：从当前{terms['schedule']}里的{object_examples}等具体物件里自选一个。",
                    "- 脑内念头：一句突然冒出来的短想法、吐槽、联想或没头没尾的小结论。",
                    "- 输入残留：上一轮聊天留下的余味、没接完的话、想补但没正式补的一点。",
                    f"- 记录碎片：{record_examples}。",
                    "- 关系试探：想靠近但不直说的半句、说完就停，不追问。",
                ]
            )
        if has_action_limit and not is_photo_action:
            options.append("- 可拍画面：本轮不是发图动作时不能选；不要在正文里声称拍照、发图或递照片。")
        return (
            "给模型的内容选择菜单,只供内部单选,不要把类别名写进正文：\n"
            + "\n".join(options)
            + "\n单选规则：先选且只选一个正文锚点；正文只围绕这个锚点展开,不要把两个以上动机、画面、旧话题或关系试探并列拼接。"
            "人格、当前时间段、日程和聊天历史只能用于筛选锚点和调整语气,不能各自贡献一段内容。"
            "如果动机、话题、日程、聊天历史指向不同内容,优先保留最贴近本次动作和当前日程的一项,其余全部舍弃。"
            "避免复用示例词。不要反复使用草稿纸、小画、画圆圈、笔尖划来划去这类廉价重复桥段。"
        )

    def _motive_action_bias(self, motive: str) -> dict[str, float]:
        text = str(motive or "")
        return {
            "screen_peek": 0.32 if any(token in text for token in ("还在忙", "埋进去", "看你", "确认", "忙太久", "偷看一眼")) else 0.0,
            "photo_text": 0.34 if any(token in text for token in ("顺手拍", "拍给你", "发你看", "光", "雨", "窗边", "晚霞", "小猫", "桌上", "一幕", "书页", "食堂", "饮料", "便利店", "影子", "倒影", "杯", "包装", "车窗", "门口")) else 0.0,
            "poke": 0.24 if any(token in text for token in ("戳", "碰你一下", "冒头", "轻轻叫你一下", "刷存在感")) else 0.0,
            "voice": 0.3 if any(token in text for token in ("懒得打字", "留句语音", "小声说", "睡不着", "不想敲字")) else 0.0,
        }

    def _soften_topic_hook(self, text: str) -> str:
        cleaned = _single_line(text, 60)
        if not cleaned:
            return ""
        cleaned = re.sub(r"[""\"'《》<>]", "", cleaned).strip("，,。！？；： ")
        cleaned = re.sub(r"^(?:关于|有关|一种|一些|那个|这段|这一段)", "", cleaned).strip()
        return cleaned

    def _choose_proactive_topic(self, reason: str, user: dict[str, Any]) -> str:
        if reason == "birthday_eve_hint":
            return "明天给自己留一点空白"
        if reason == "birthday_celebration":
            return "今天只属于你的生日小惊喜"
        if reason == "birthday_makeup":
            return "迟到一点的生日祝福"
        if reason == "birthday_afterglow":
            return "昨天留下的一点开心"
        if reason == "birthday_curiosity":
            return "你的生日是哪一天"
        if reason == "group_share":
            share = user.get("group_share_context") if isinstance(user.get("group_share_context"), dict) else {}
            return _single_line(share.get("topic"), 48) or _single_line(share.get("text"), 48) or "群里那段片段"
        if reason == "bili_video_share":
            video = user.get("bilibili_video_context") if isinstance(user.get("bilibili_video_context"), dict) else {}
            return _single_line(video.get("title"), 48) or "B站视频"
        if reason == "news_share":
            news = user.get("news_context") if isinstance(user.get("news_context"), dict) else {}
            return _single_line(news.get("topic") or news.get("headline"), 48) or "一条新闻"
        if reason == "web_exploration_share":
            exploration = user.get("web_exploration_context") if isinstance(user.get("web_exploration_context"), dict) else {}
            return _single_line(exploration.get("topic") or exploration.get("query"), 48) or "新发现"
        if reason == "creative_share":
            creative = user.get("creative_share_context") if isinstance(user.get("creative_share_context"), dict) else {}
            return _single_line(creative.get("title"), 48) or "刚写到的小说片段"
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        snapshot = self._current_story_plan_snapshot()
        weather = self._weather_summary_text(self.data.get("daily_weather", {}))
        last_user_message = _single_line(user.get("last_user_message"), 24)
        snapshot_topic = self._soften_topic_hook(snapshot.get("topic")) if isinstance(snapshot, dict) else ""
        if snapshot_topic:
            return snapshot_topic
        snapshot_event = self._soften_topic_hook(snapshot.get("event")) if isinstance(snapshot, dict) else ""
        if snapshot_event:
            return snapshot_event
        if isinstance(current_item, dict):
            activity = _single_line(current_item.get("activity"), 30)
            if activity:
                activity = re.sub(r"[,、]?\s*想起了[^,。]+", "", activity).strip(",。 ")
                activity = re.sub(r"[,、]?\s*突然想到[^,。]+", "", activity).strip(",。 ")
                if activity:
                    return self._soften_topic_hook(activity)
        if reason in {"activity_share", "diary_share"}:
            if random.random() < 0.72:
                return self._pick_life_thought_topic(reason)
            if any(token in weather for token in ("雨", "小雨", "阵雨")):
                return "外面那阵雨声"
            if any(token in weather for token in ("晴", "阳光", "晚霞", "多云")):
                return "刚刚那点天色"
        if reason == "morning_greeting":
            return "刚醒那会儿"
        if reason == "noon_greeting":
            return "中午这会儿有点懒"
        if reason == "evening_greeting":
            return "晚一点的这会儿"
        if reason == "quiet_care" and last_user_message:
            return last_user_message
        return ""

    def _action_affinity_bias(self, user: dict[str, Any] | None = None) -> dict[str, float]:
        base = {"screen_peek": 0.0, "photo_text": 0.0, "poke": 0.0, "voice": 0.0}
        if not isinstance(user, dict):
            return base
        raw = user.get("action_reply_affinity")
        if not isinstance(raw, dict):
            return base
        for action in base:
            stats = raw.get(action)
            if not isinstance(stats, dict):
                continue
            sent = _safe_int(stats.get("sent"), 0, 0)
            replied = _safe_int(stats.get("replied"), 0, 0)
            if sent <= 0:
                continue
            rate = replied / max(1, sent)
            base[action] = max(-0.08, min(0.28, (rate - 0.35) * 0.55))
        return base

    def _screen_glance_available(
        self,
        user: dict[str, Any] | None = None,
        *,
        ignore_daily_limit: bool = False,
    ) -> bool:
        if not self.enable_screen_glance_action:
            return False
        if isinstance(user, dict) and self._private_user_role(user) == "friend":
            return False
        daily_limit = self._effective_user_screen_peek_daily_limit(user)
        if daily_limit <= 0 and not ignore_daily_limit:
            return False
        if isinstance(user, dict):
            if self._screen_peek_failure_cooldown_active(user):
                return False
            today = _today_key()
            used_today = (
                _safe_int(user.get("screen_peek_today"), 0)
                if str(user.get("screen_peek_day") or "") == today
                else 0
            )
            if not ignore_daily_limit and used_today >= daily_limit:
                return False
            cooldown_seconds = max(0, self.screen_peek_cooldown_minutes) * 60
            last_at = _safe_float(user.get("screen_peek_last_at"), 0.0)
            if cooldown_seconds > 0 and last_at > 0 and _now_ts() - last_at < cooldown_seconds:
                return False
        try:
            plugin = self._get_screen_companion_plugin()
            return plugin is not None and callable(getattr(plugin, "_invoke_screen_skill", None))
        except Exception:
            return False

    def _comfyui_photo_available(self) -> bool:
        if not self.enable_photo_text_action:
            return False
        if not self.comfyui_text2img_workflow_name and not self.comfyui_selfie_workflow_name:
            return False
        try:
            module = self._get_comfyui_module()
            return module is not None
        except Exception:
            return False

    def _external_photo_available(self) -> bool:
        if not self.enable_photo_text_action:
            return False
        configured = getattr(self, "external_image_api_endpoints", [])
        has_configured_queue = isinstance(configured, list) and bool(configured)
        queue_getter = getattr(self, "_external_image_api_endpoint_queue", None)
        if callable(queue_getter):
            try:
                queue_available = bool(queue_getter())
                if has_configured_queue:
                    return queue_available
                if queue_available:
                    return True
            except Exception:
                if has_configured_queue:
                    return False
        configured = bool(
            self.external_image_api_base_url
            and self.external_image_api_key
            and self.external_image_api_model
        )
        if configured:
            checker = getattr(self, "_external_image_model_misconfiguration_note", None)
            if callable(checker):
                try:
                    if not checker():
                        return True
                except Exception:
                    return True
            else:
                return True
        return self._backup_external_photo_available()

    def _backup_external_photo_unavailable_note(self) -> str:
        if not self.enable_photo_text_action:
            return "photo_action_disabled"
        configured = getattr(self, "external_image_api_endpoints", [])
        has_configured_queue = isinstance(configured, list) and bool(configured)
        queue_getter = getattr(self, "_external_image_api_endpoint_queue", None)
        endpoint_note = getattr(self, "_external_image_api_endpoint_unavailable_note", None)
        if callable(queue_getter) and callable(endpoint_note):
            try:
                endpoints = queue_getter(include_incomplete=True)
                if has_configured_queue:
                    if len(endpoints) <= 1:
                        return "missing_backup_endpoints"
                    backup_endpoints = endpoints[1:]
                    notes = [
                        _single_line(endpoint_note(endpoint), 80)
                        for endpoint in backup_endpoints
                        if isinstance(endpoint, dict)
                    ]
                    if any(not note for note in notes):
                        return ""
                    return "all_backup_endpoints_unavailable" if notes else "missing_backup_endpoints"
            except Exception:
                if has_configured_queue:
                    return "queue_error"
        if not bool(getattr(self, "enable_backup_external_image_api", False)):
            return "disabled"
        missing = []
        if not getattr(self, "backup_external_image_api_base_url", ""):
            missing.append("base_url")
        if not getattr(self, "backup_external_image_api_key", ""):
            missing.append("api_key")
        if not getattr(self, "backup_external_image_api_model", ""):
            missing.append("model")
        if missing:
            return "missing_" + ",".join(missing)
        checker = getattr(self, "_external_image_model_misconfiguration_note", None)
        if not callable(checker):
            return ""
        keys = (
            "external_image_api_platform",
            "external_image_api_base_url",
            "external_image_api_key",
            "external_image_api_model",
            "external_image_api_size",
            "external_image_api_timeout_seconds",
        )
        backup_values = {
            "external_image_api_platform": getattr(self, "backup_external_image_api_platform", "auto"),
            "external_image_api_base_url": getattr(self, "backup_external_image_api_base_url", ""),
            "external_image_api_key": getattr(self, "backup_external_image_api_key", ""),
            "external_image_api_model": getattr(self, "backup_external_image_api_model", ""),
            "external_image_api_size": getattr(self, "backup_external_image_api_size", "1024x1024"),
            "external_image_api_timeout_seconds": getattr(self, "backup_external_image_api_timeout_seconds", 180),
        }
        old_values = {key: getattr(self, key, None) for key in keys}
        try:
            for key, value in backup_values.items():
                setattr(self, key, value)
            note = checker()
            return _single_line(note, 120) if note else ""
        except Exception:
            return ""
        finally:
            for key, value in old_values.items():
                setattr(self, key, value)

    def _backup_external_photo_available(self) -> bool:
        return not bool(self._backup_external_photo_unavailable_note())

    def _sdgen_photo_available(self) -> bool:
        if not self.enable_photo_text_action:
            return False
        try:
            getter = getattr(getattr(self, "context", None), "get_registered_star", None)
            if callable(getter):
                for name in ("SDGen", "astrbot_plugin_sdgen"):
                    plugin = getter(name)
                    if plugin is not None and callable(getattr(plugin, "_call_t2i_api", None)):
                        return True
        except Exception:
            pass
        for obj in gc.get_objects():
            try:
                cls = obj.__class__
                module = str(getattr(cls, "__module__", ""))
                if "astrbot_plugin_sdgen" not in module:
                    continue
                if callable(getattr(obj, "_call_t2i_api", None)):
                    return True
            except Exception:
                continue
        return False

    def _find_custom_photo_tool_handler(self) -> Any | None:
        tool_name = _single_line(getattr(self, "custom_photo_tool_name", ""), 120)
        if not tool_name:
            return None

        context = getattr(self, "context", None)
        manager_getter = getattr(context, "get_llm_tool_manager", None)
        if callable(manager_getter):
            try:
                manager = manager_getter()
            except Exception as exc:
                logger.warning(
                    "[PrivateCompanion] 获取 LLM Tool Manager 失败: tool=%s error=%s",
                    tool_name,
                    _single_line(exc, 160),
                )
                manager = None
            getter = getattr(manager, "get_func", None)
            if callable(getter):
                try:
                    tool = getter(tool_name)
                except Exception as exc:
                    logger.warning(
                        "[PrivateCompanion] 获取自定义生图函数工具失败: tool=%s error=%s",
                        tool_name,
                        _single_line(exc, 160),
                    )
                    tool = None
                if tool is not None:
                    handler = getattr(tool, "handler", None)
                    if callable(handler):
                        logger.info("[PrivateCompanion] 从 LLM 工具对象获取生图 handler: %s", tool_name)
                        return handler
                    if callable(tool):
                        logger.info("[PrivateCompanion] 自定义生图工具对象本身可调用: %s", tool_name)
                        return tool
                    call = getattr(tool, "call", None)
                    if callable(call):
                        logger.warning(
                            "[PrivateCompanion] 自定义生图工具未暴露 handler，回退 tool.call: %s",
                            tool_name,
                        )
                        return call
                    logger.warning(
                        "[PrivateCompanion] 自定义生图工具不可调用: tool=%s type=%s",
                        tool_name,
                        type(tool).__name__,
                    )
                else:
                    logger.warning("[PrivateCompanion] 自定义生图工具未注册: %s", tool_name)
            elif manager is not None:
                logger.warning("[PrivateCompanion] LLM Tool Manager 不支持 get_func: %s", tool_name)
        else:
            logger.warning("[PrivateCompanion] LLM Tool Manager 未初始化: %s", tool_name)

        # 兼容旧版 AstrBot 或非 @llm_tool 的注册方式。
        try:
            for handler in star_handlers_registry:
                handler_name = str(getattr(handler, "handler_name", "") or "")
                if handler_name == tool_name:
                    callback = getattr(handler, "handler", None) or getattr(handler, "func", None)
                    if callable(callback):
                        logger.info("[PrivateCompanion] 从旧注册表获取自定义生图 handler: %s", tool_name)
                        return callback
        except Exception as exc:
            logger.debug("[PrivateCompanion] 查询旧工具注册表失败: tool=%s error=%s", tool_name, _single_line(exc, 120))
        return None

    def _custom_tool_photo_available(self) -> bool:
        if not self.enable_photo_text_action:
            return False
        if not getattr(self, "custom_photo_tool_name", "").strip():
            return False
        return self._find_custom_photo_tool_handler() is not None

    def _local_photo_generation_load_state(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = _now_ts()
        if not self.enable_local_photo_load_guard:
            return {"enabled": False, "busy": False, "reason": "负载保护未启用", "sampled_at": now}
        cached = getattr(self, "_local_photo_load_cache", {}) if isinstance(getattr(self, "_local_photo_load_cache", {}), dict) else {}
        if cached and not force_refresh and now - _safe_float(cached.get("sampled_at"), 0) < 20:
            return dict(cached)
        state: dict[str, Any] = {
            "enabled": True,
            "available": False,
            "busy": False,
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "reason": "",
            "sampled_at": now,
        }
        try:
            psutil = importlib.import_module("psutil")
            cpu_percent = float(psutil.cpu_percent(interval=0.05))
            memory_percent = float(getattr(psutil.virtual_memory(), "percent", 0.0) or 0.0)
            state.update(
                {
                    "available": True,
                    "cpu_percent": round(cpu_percent, 1),
                    "memory_percent": round(memory_percent, 1),
                }
            )
            reasons = []
            if cpu_percent >= self.local_photo_cpu_busy_percent:
                reasons.append(f"CPU {cpu_percent:.0f}%")
            if memory_percent >= self.local_photo_memory_busy_percent:
                reasons.append(f"内存 {memory_percent:.0f}%")
            state["busy"] = bool(reasons)
            state["reason"] = "、".join(reasons) if reasons else "负载正常"
        except Exception as exc:
            state["reason"] = f"无法读取系统负载:{exc.__class__.__name__}"
        self._local_photo_load_cache = dict(state)
        return state

    def _local_photo_generation_busy_state(self, *, force_refresh: bool = False) -> dict[str, Any] | None:
        state = self._local_photo_generation_load_state(force_refresh=force_refresh)
        if bool(state.get("enabled")) and bool(state.get("available")) and bool(state.get("busy")):
            return state
        return None

    def _action_has_photo_text(self, action: str) -> bool:
        return "photo_text" in {part.strip() for part in str(action or "").split("+") if part.strip()}

    def _proactive_photo_text_trigger_probability(
        self,
        reason: str,
        *parts: Any,
        user: dict[str, Any] | None = None,
    ) -> float:
        base = max(0.0, min(1.0, float(getattr(self, "proactive_photo_text_probability", 0.18))))
        if base <= 0:
            return 0.0
        base = max(base, min(0.45, base + self._photo_text_overdue_boost(user)))
        hard_reasons = {"activity_share", "diary_share", "background_schedule", "noon_greeting", "evening_greeting"}
        soft_reasons = {"check_in", "quiet_care", "state_share"}
        text = " ".join(_single_line(part, 180) for part in parts if _single_line(part, 180))
        has_visual_cut = any(token in text for token in self._visual_share_tokens())
        if reason in hard_reasons:
            return base if has_visual_cut else base * 0.45
        if reason in soft_reasons and has_visual_cut:
            return base * 0.55
        return 0.0

    def _photo_text_load_defer_note(self, action: str = "photo_text", *, force_refresh: bool = False) -> str:
        if not self._action_has_photo_text(action):
            return ""
        if self._daily_token_soft_limit_should_defer("photo_prompt"):
            return (
                "每日 Token 软限额已暂缓主动生图"
                f"（今日已用约 {self._today_llm_token_total()} Token；软限额 {self.daily_token_soft_limit}）"
            )
        if self.photo_generation_backend in {"external", "tool_call"}:
            return ""
        if self.photo_generation_backend == "sdgen":
            local_available = self._sdgen_photo_available()
        else:
            local_available = self._comfyui_photo_available() or (
                self.photo_generation_backend == "auto" and self._sdgen_photo_available()
            )
        if not local_available:
            return ""
        state = self._local_photo_generation_busy_state(force_refresh=force_refresh)
        if not state:
            return ""
        if self.photo_generation_backend == "auto" and self._external_photo_available():
            return ""
        return (
            "电脑高负荷,已延后本地生图"
            f"（{state.get('reason') or '负载偏高'}；{self.local_photo_defer_minutes} 分钟后重试）"
        )

    def _defer_planned_photo_text_for_load(self, user: dict[str, Any], *, now: float, note: str) -> None:
        delay_seconds = max(60, int(self.local_photo_defer_minutes) * 60)
        self._defer_or_replace_planned_impulse(
            user,
            now=now,
            note=note,
            delay_minutes=(delay_seconds / 60, delay_seconds / 60 + min(5.0, delay_seconds / 300)),
            block_current=False,
        )
        user["proactive_sending"] = False
        user["proactive_sending_started_at"] = 0

    def _photo_text_available(self, user: dict[str, Any] | None = None) -> bool:
        if not self.enable_photo_text_action:
            return False
        if isinstance(user, dict) and self._private_user_role(user) == "friend":
            return False
        if self._daily_token_soft_limit_should_defer("photo_prompt"):
            return False
        if self.photo_generation_backend == "comfyui":
            if not self._comfyui_photo_available():
                return False
            if self._local_photo_generation_busy_state():
                return False
        elif self.photo_generation_backend == "sdgen":
            if not self._sdgen_photo_available():
                return False
            if self._local_photo_generation_busy_state():
                return False
        elif self.photo_generation_backend == "external":
            if not self._external_photo_available():
                return False
        elif self.photo_generation_backend == "tool_call":
            if not self._custom_tool_photo_available():
                return False
        else:
            comfyui_available = self._comfyui_photo_available() and not self._local_photo_generation_busy_state()
            sdgen_available = self._sdgen_photo_available() and not self._local_photo_generation_busy_state()
            if not (comfyui_available or sdgen_available or self._external_photo_available()):
                return False
        photo_limit = self._effective_user_photo_daily_limit(user)
        if user and photo_limit <= 0:
            return False
        if user and photo_limit > 0:
            today = _today_key()
            photo_sent_day = str(user.get("photo_sent_day") or "")
            photo_sent_today = _safe_int(user.get("photo_sent_today"), 0)
            photo_generated_day = str(user.get("photo_generated_day") or "")
            photo_generated_today = _safe_int(user.get("photo_generated_today"), 0)
            used_today = max(
                photo_sent_today if photo_sent_day == today else 0,
                photo_generated_today if photo_generated_day == today else 0,
            )
            if used_today >= photo_limit:
                return False
        return True

    def _photo_text_planning_available(self, user: dict[str, Any] | None = None) -> bool:
        try:
            return bool(self._photo_text_available(user))
        except Exception as exc:
            logger.debug("[PrivateCompanion] 主动生图规划可用性检查失败: %s", _single_line(exc, 120))
            return False

    def _poke_available(self) -> bool:
        if not self.enable_poke_action:
            return False
        if self._resolve_aiocqhttp_client() is None:
            return False
        try:
            from data.plugins.astrbot_plugin_pokepro.core.send_poke import PokeSender  # noqa: F401
            return True
        except Exception:
            try:
                from astrbot_plugin_pokepro.core.send_poke import PokeSender  # noqa: F401
                return True
            except Exception:
                return False

    def _voice_available(self, user: dict[str, Any] | None = None) -> bool:
        if not self.enable_voice_action:
            return False
        target = ""
        if isinstance(user, dict):
            target = str(user.get("umo") or "").strip()
        if not target:
            return False
        try:
            config = self.context.get_config(target)
        except Exception:
            try:
                config = self.context.get_config()
            except Exception:
                return False
        provider_settings = dict(config.get("provider_tts_settings", {}) or {})
        if not provider_settings.get("enable", False):
            return False
        try:
            return bool(self.context.get_using_tts_provider(target))
        except Exception:
            return False

    def _action_is_available(self, action: str, user: dict[str, Any] | None = None) -> bool:
        normalized = str(action or "message").strip()
        if not normalized or normalized == "message":
            return True
        if self._friend_sensitive_proactive_action(normalized) and isinstance(user, dict) and self._private_user_role(user) == "friend":
            return False
        parts = [part.strip() for part in normalized.split("+") if part.strip()]
        if not parts:
            return True
        screen_quota_exempt = bool(isinstance(user, dict) and user.get("planned_proactive_quota_exempt"))
        for part in parts:
            if part == "screen_peek" and not self._screen_glance_available(user, ignore_daily_limit=screen_quota_exempt):
                return False
            if part == "photo_text" and not self._photo_text_available(user):
                return False
            if part == "poke" and (
                not self._poke_available()
                or self._effective_user_poke_daily_limit(user) <= 0
                or self._poke_action_cooldown_remaining(user) > 0
            ):
                return False
            if part == "voice" and not self._voice_available(user):
                return False
            if part == "jm_cosmos_read" and not self._jm_cosmos_read_available(user):
                return False
            if part.startswith("external:") and not self._external_ability_enabled(part.split(":", 1)[1]):
                return False
        return True

    def _fallback_action_for_unavailable(self, action: str, user: dict[str, Any] | None = None) -> str:
        normalized = str(action or "message").strip() or "message"
        if self._action_is_available(normalized, user):
            return normalized
        parts = [part.strip() for part in normalized.split("+") if part.strip()]
        available_parts = [part for part in parts if self._action_is_available(part, user)]
        if not available_parts:
            return "message"
        return "+".join(available_parts)

    def _choose_action_for_reason(
        self,
        reason: str,
        user: dict[str, Any] | None = None,
        motive: str = "",
    ) -> str:
        if reason in {"holiday_celebration", "course_reminder"}:
            return "message"
        weather = self._weather_summary_text(self.data.get("daily_weather", {}))
        state = self.data.get("daily_state", {})
        energy = _safe_int(state.get("energy") if isinstance(state, dict) else 70, 70, 0, 100)
        action_profile = self._persona_action_profile()
        motive_bias = self._motive_action_bias(motive)
        affinity_bias = self._action_affinity_bias(user)
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        current_item_text = self._format_plan_item_for_prompt(current_item)

        weighted: list[tuple[str, float]] = [("message", 0.82)]
        if self._screen_glance_available(user) and reason in {"check_in", "quiet_care", "state_share", "background_schedule"}:
            weight = 0.9 + (0.45 if action_profile["observant"] else 0.0) + motive_bias["screen_peek"] + affinity_bias["screen_peek"]
            if energy < 50:
                weight += 0.12
            weighted.append(("screen_peek", weight))
        if (
            self._photo_text_available(user)
            and reason in {"activity_share", "diary_share", "background_schedule", "noon_greeting", "evening_greeting"}
            and self._strong_photo_share_intent(motive, user.get("planned_proactive_topic") if isinstance(user, dict) else "")
        ):
            return "photo_text"
        photo_probability = self._proactive_photo_text_trigger_probability(
            reason,
            motive,
            user.get("planned_proactive_topic") if isinstance(user, dict) else "",
            weather,
            current_item_text,
            user=user,
        )
        if self._photo_text_available(user) and photo_probability > 0 and random.random() < photo_probability:
            return "photo_text"
        visual_hint = any(token in motive for token in self._visual_share_tokens())
        if self._photo_text_available(user) and (
            reason in {"activity_share", "diary_share", "background_schedule", "noon_greeting", "evening_greeting"}
            or photo_probability > 0
        ):
            weight = 0.38 + (0.18 if action_profile["visual"] else 0.0) + motive_bias["photo_text"] * 0.65 + affinity_bias["photo_text"]
            if any(token in weather for token in ("晴", "阳光", "多云", "晚霞", "雨", "阵雨", "小雨")):
                weight += 0.04
            if visual_hint:
                weight += 0.14
            if reason in {"activity_share", "diary_share"}:
                weight += 0.05
            if reason in {"check_in", "quiet_care", "state_share"}:
                weight *= 0.45
            weighted.append(("photo_text", weight))
        if self._poke_available() and self._effective_user_poke_daily_limit(user) > 0 and self._poke_action_cooldown_remaining(user) <= 0 and reason in {"check_in", "quiet_care", "state_share", "important_date_share", "morning_greeting", "evening_greeting"}:
            weight = 0.38 + motive_bias["poke"] + affinity_bias["poke"]
            if action_profile["playful"]:
                weight += 0.22
            if action_profile["clingy"]:
                weight += 0.12
            weighted.append(("poke", weight))
        if self._voice_available(user) and reason in {"state_share", "diary_share", "insomnia_night", "evening_greeting", "quiet_care"}:
            weight = 0.5 + (0.55 if action_profile["voicey"] else 0.0) + motive_bias["voice"] + affinity_bias["voice"]
            if action_profile["clingy"]:
                weight += 0.2
            if reason == "insomnia_night":
                weight += 0.28
            weighted.append(("voice", weight))
        for ability in self._available_external_proactive_abilities(user):
            ability_name = str(ability.get("name") or "")
            if not ability_name:
                continue
            probability = max(0.0, min(1.0, _safe_float(ability.get("share_probability"), 0.0)))
            if probability <= 0:
                continue
            when_text = " ".join(str(ability.get(key) or "") for key in ("when", "use_for", "description"))
            weight = max(0.02, probability) * 0.9
            if reason in {"activity_share", "diary_share", "background_schedule", "state_share", "quiet_care"}:
                weight += probability * 0.35
            if motive and any(token and token in motive for token in re.split(r"[\s,，、/]+", when_text)[:16]):
                weight += probability * 0.25
            weighted.append((f"external:{ability_name}", weight))

        primary = self._weighted_choice(weighted)
        if primary != "message":
            combined = self._maybe_combine_actions(primary, reason, weather=weather, action_profile=action_profile, user=user)
            if combined:
                return self._fallback_action_for_unavailable(combined, user)
        return self._fallback_action_for_unavailable(primary, user)

    def _choose_proactive_motive(
        self,
        reason: str,
        user: dict[str, Any],
        *,
        action: str = "message",
        planned_event: dict[str, Any] | None = None,
    ) -> str:
        state = self.data.get("daily_state", {})
        weather = self._weather_summary_text(self.data.get("daily_weather", {}))
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        snapshot = self._current_story_plan_snapshot()
        last_user_message = _single_line(user.get("last_user_message"), 48)
        can_do = self.data.get("can_do", [])
        energy = _safe_int(state.get("energy") if isinstance(state, dict) else 70, 70, 0, 100)

        topic = ""
        scene = ""
        tone = ""
        impulse = ""
        event_hint = _single_line(snapshot.get("event"), 60) if isinstance(snapshot, dict) else ""
        summary_hint = _single_line(snapshot.get("summary"), 60) if isinstance(snapshot, dict) else ""
        if isinstance(planned_event, dict):
            topic = self._soften_topic_hook(planned_event.get("topic"))
            scene = _single_line(planned_event.get("scene"), 60)
            tone = _single_line(planned_event.get("tone"), 24)
            impulse = _single_line(planned_event.get("impulse"), 60)
        if not topic and isinstance(snapshot, dict):
            topic = self._soften_topic_hook(snapshot.get("topic") or snapshot.get("event"))
        if not scene and isinstance(snapshot, dict):
            scene = _single_line(snapshot.get("scene"), 60)
        if not tone and isinstance(snapshot, dict):
            tone = _single_line(snapshot.get("tone"), 24)
        if not impulse and isinstance(snapshot, dict):
            impulse = _single_line(snapshot.get("impulse"), 60)
        if not topic and current_item:
            topic = _single_line(current_item.get("title"), 36)
        if not topic and isinstance(can_do, list) and can_do and reason == "activity_share":
            topic = _single_line(random.choice(can_do), 28)
        if not topic:
            topic = self._choose_proactive_topic(reason, user)
        if self._private_user_role(user) == "friend":
            if reason in {"quiet_care", "check_in", "state_share"}:
                return random.choice([
                    "作为朋友想到对方可能正忙，只问一句，不要求立刻回复",
                    "朋友之间顺手关心一下近况,说完就把空间留给对方",
                    "看到前面的话题还有一点余味,礼貌地补一句就停",
                ])
            if reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
                return random.choice([
                    "按次要用户关系顺手打个招呼,语气轻一点,不显得黏人",
                    "这个时间点刚好想起对方",
                ])
            if reason in {"activity_share", "diary_share", "background_schedule"}:
                if topic:
                    return self._normalize_internal_motive_text(f"有个和“{topic}”有关的小片段")
                return "有个小片段想分享"
            if reason == "group_share":
                return "共同群里有个和对方可能有关的小片段"
        if impulse:
            return self._normalize_internal_motive_text(impulse)
        if scene or tone or event_hint or summary_hint:
            mood_fragment = ""
            if tone in {"安静", "柔和", "松弛", "轻快", "迷糊", "慵懒"}:
                mood_fragment = f",整个人有点{tone}"
            lived_line = ""
            if topic and event_hint:
                lived_line = f"刚刚{event_hint}之后，还想着“{topic}”{mood_fragment}"
            elif scene and topic:
                lived_line = f"在{scene}的时候，想到“{topic}”{mood_fragment}"
            elif event_hint:
                lived_line = f"刚刚{event_hint}的时候{mood_fragment}"
            elif scene:
                lived_line = f"刚刚在{scene}的时候{mood_fragment}"
            elif summary_hint:
                lived_line = f"这一小段安静下来时{mood_fragment}"
            if lived_line:
                return self._normalize_internal_motive_text(lived_line)

        if reason == "birthday_eve_hint":
            return "明天想让对方放松一点"
        if reason == "birthday_celebration":
            return "今天是对方生日，想留一份小惊喜"
        if reason == "birthday_makeup":
            return "昨天错过了祝福，今天补上"
        if reason == "birthday_afterglow":
            return "昨天的开心还没散"
        if reason == "birthday_curiosity":
            return "好奇对方的生日"

        if reason == "insomnia_night":
            motives = [
                "夜里一直没睡着",
                "睡不着，想看看对方是不是也还醒着",
                "已经很晚了，但还是想说一句",
            ]
            if action == "voice":
                motives.append("夜里不想打太多字，想发语音")
            return random.choice(motives)
        if reason == "state_share":
            motives = [
                "这会儿说话可能慢一点",
                "这会儿不太想说太多",
                "这一会儿比较安静，想慢慢说一句",
            ]
            if energy < 45:
                motives.append("不太想说长句，但想看看那边还在不在")
            return random.choice(motives)
        if reason == "quiet_care":
            motives = [
                "刚刚有点在意用户是不是又忙太久了",
                "想起用户最近的状态，想问一句现在怎么样",
                "本来不想打扰，但还是想看看那边还好不好",
            ]
            if last_user_message:
                motives.append(f"想起用户前面提过“{last_user_message}”，有点放心不下")
            elif topic:
                motives.append(f"刚刚想到“{topic}”的时候，也想起用户那边")
            return random.choice(motives)
        if reason == "group_share":
            share = user.get("group_share_context") if isinstance(user.get("group_share_context"), dict) else {}
            group_id = _single_line(share.get("group_id"), 24)
            speaker = _single_line(share.get("speaker"), 24) or "群友"
            text = _single_line(share.get("text"), 70)
            if _single_line(share.get("kind"), 32) == "bot_harassment":
                if text:
                    return self._normalize_internal_motive_text(
                        f"共同群 {group_id} 里有人持续提到 Bot,{speaker} 那句“{text}”还挺扎眼,但只想很轻地跟你提一下"
                    )
                return self._normalize_internal_motive_text(f"共同群 {group_id} 里有人持续提到 Bot,只想很轻地跟你提一下")
            if text:
                return self._normalize_internal_motive_text(
                    f"共同群 {group_id} 里有个小转折,{speaker} 那句“{text}”还留着点余味,想顺手给你递一下"
                )
            return self._normalize_internal_motive_text("共同群里有个小片段还有点余味,想顺手给你递一下")
        if reason == "activity_share":
            motives = [
                "刚刚碰到一个小片段",
                "看到一个小东西",
                "有个小想法",
                "脑子里冒出一句没头没尾的话",
                "一个小想法放着没用",
                "手边的小东西有点好笑，想给你看",
            ]
            if topic:
                motives.append(f"刚碰到“{topic}”时")
            if any(token in weather for token in ("雨", "小雨", "阵雨")):
                motives.append("外面在下雨")
            if any(token in weather for token in ("晴", "阳光", "晚霞")):
                motives.append("外面光线不错")
            return random.choice(motives)
        if reason == "diary_share":
            return random.choice([
                "翻到今天记下来的小片段",
                "看到今天写下来的那句话，觉得可以给你看看",
                "今天有个小片段还记着",
                "有句话不算重要，但一直记着，想给你看看",
                "今天有个小片段还记着",
            ])
        if reason == "important_date_share":
            return random.choice([
                "怕用户转头又忘，就先提醒一句",
                "今天这个时间点该提醒一下用户",
                "还记着这件事，所以想提醒用户一句",
            ])
        if reason == "background_schedule":
            motives = [
                "手上的事告一段落了",
                "忙到能休息一小会儿了",
                "眼前这一小段缓下来了",
            ]
            if topic:
                motives.append(f"手上这点“{topic}”还没结束")
            return random.choice(motives)
        if reason == "morning_greeting":
            return random.choice([
                "还没太清醒，先打个招呼",
                "刚醒，先打个招呼",
            ])
        if reason == "noon_greeting":
            return random.choice([
                "中午有点懒",
                "午间松下来了",
            ])
        if reason == "evening_greeting":
            return random.choice([
                "晚上安静下来了",
                "白天快结束了",
            ])
        motives = [
            "刚好休息一下",
            "还记着眼前这点小事",
            "刚松一口气",
        ]
        return self._normalize_internal_motive_text(random.choice(motives))

    def _normalize_internal_motive_text(self, text: str) -> str:
        cleaned = _single_line(text, 80)
        if not cleaned:
            return ""
        replacements = {
            "顺手冒了个头": "",
            "冒个头": "",
            "冒个泡": "",
            "刷一下存在感": "",
            "没什么大道理,就是": "",
            "没什么大不了的,就是": "",
            "顺手晃到你这边了": "",
            "顺手晃到你这边": "",
            "一直不理我": "那边还安静着",
            "不理我": "那边还安静着",
            "怎么一点动静都没有": "那边还没什么动静",
            "怎么还没动静": "那边还没什么动静",
            "一点动静都没有": "那边还没什么动静",
            "主要用户": "这边",
            "次要用户": "对方",
            "用户": "你",
        }
        for src, dst in replacements.items():
            cleaned = cleaned.replace(src, dst)
        cleaned = re.sub(r"(?:主动)?(?:小)?念头", "小想法", cleaned)
        cleaned = re.sub(r"这个念头前面忍过一次[,，]?但它还没散[,，]?", "", cleaned)
        cleaned = re.sub(r"刚才差点想说[,，]?后来又先收住了[,，]?", "", cleaned)
        cleaned = re.sub(r"这会儿又绕回[“\"]([^”\"]{1,40})[”\"]", r"想到“\1”", cleaned)
        cleaned = cleaned.replace("忍过一次", "先放了放")
        cleaned = cleaned.replace("还没散", "还记着")
        cleaned = re.sub(r"(?:来找你一下){2,}", "来找你一下", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(",。 ")
        return cleaned

    def _normalize_legacy_proactive_text(self, value: Any, *, limit: int = 40) -> str:
        return _single_line(normalize_legacy_tag_text(value), limit)

    def _is_vague_seek_user_motive(self, reason: str, action: str, motive: str, topic: str = "") -> bool:
        if str(action or "message") != "message":
            return False
        if str(reason or "") not in {
            "check_in",
            "quiet_care",
            "state_share",
            "morning_greeting",
            "noon_greeting",
            "evening_greeting",
        }:
            return False
        text = f"{_single_line(motive, 140)} {_single_line(topic, 80)}"
        if not text.strip():
            return True
        concrete_tokens = (
            "前面提过", "刚刚想到“", "天气", "雨", "阳光", "晚霞", "日记", "群", "照片",
            "新闻", "日期", "生日", "纪念", "考试", "作业", "吃饭", "睡", "生病", "压力",
            "低压关心", "收敛情绪",
        )
        if any(token in text for token in concrete_tokens):
            return False
        vague_tokens = (
            "想跟你说一句", "想确认你还在", "确认用户在不在", "确认一下用户状态",
            "想看你在不在", "来看看你", "想来看看你", "来找你", "想找你",
            "只是想", "就是想", "没什么事", "没什么动机", "普通问候",
            "想到你了", "先想到你", "晃到了你", "拐到了你", "碰一下你",
            "轻轻问你一句", "先冒出来的是你", "就想顺手跟你说句话",
        )
        return any(token in text for token in vague_tokens)

    def _should_use_name_only_opener(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str,
    ) -> bool:
        if self._private_user_role(user) == "friend":
            return False
        if action != "message":
            return False
        if str(user.get("planned_followup_kind") or "") == "suspended_opener":
            return False
        chain = user.get("planned_event_chain")
        if isinstance(chain, list) and chain:
            first = chain[0] if isinstance(chain[0], dict) else {}
            if str(first.get("kind") or "") == "name_only_opener":
                return True
        if reason not in {"check_in", "quiet_care", "state_share", "evening_greeting", "insomnia_night"}:
            return False
        if _safe_float(user.get("awaiting_reply_since"), 0) > 0:
            return False
        profile = self._persona_action_profile()
        chance = 0.09
        if reason in {"quiet_care", "evening_greeting", "insomnia_night"}:
            chance += 0.05
        if profile.get("clingy"):
            chance += 0.06
        if profile.get("observant"):
            chance += 0.03
        if profile.get("playful"):
            chance += 0.02
        if any(token in motive for token in ("来找你", "确认一下用户状态", "想和用户说一句", "放心不下", "想看你在不在")):
            chance += 0.05
        if self._is_vague_seek_user_motive(reason, action, motive):
            chance *= 0.45
        return random.random() < min(0.32, chance)

    def _build_name_only_opener(self, name: str) -> str:
        clean_name = _single_line(name, 24) or self.default_nickname
        return f"{clean_name}……"

    def _build_suspended_proactive_payload(
        self,
        *,
        opener_text: str,
        reason: str,
        action: str,
        motive: str,
        action_summary: str,
        chain: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profile = self._persona_action_profile()
        delay_minutes = random.randint(26, 95)
        complaint_chance = 0.18
        if profile.get("clingy"):
            complaint_chance += 0.16
        if profile.get("playful"):
            complaint_chance += 0.08
        if reason in {"quiet_care", "insomnia_night", "evening_greeting"}:
            complaint_chance += 0.08
        if reason == "morning_greeting":
            delay_minutes = random.randint(80, 150)
            complaint_chance = min(complaint_chance, 0.08)
        chain = list(chain or [])
        no_reply_step = None
        still_no_reply_step = None
        for step in chain:
            if not isinstance(step, dict):
                continue
            kind = str(step.get("kind") or "")
            if kind == "if_no_reply" and no_reply_step is None:
                no_reply_step = step
            elif kind == "if_still_no_reply" and still_no_reply_step is None:
                still_no_reply_step = step
        complaint_after_minutes = _safe_int((no_reply_step or {}).get("after_minutes"), delay_minutes, 0, 240)
        if reason == "morning_greeting":
            complaint_after_minutes = max(complaint_after_minutes, 75)
        return {
            "active": True,
            "resume_ready": False,
            "created_at": _now_ts(),
            "opener_text": _single_line(opener_text, 60),
            "reason": reason,
            "action": action,
            "motive": self._normalize_internal_motive_text(motive),
            "summary": _single_line(action_summary, 60),
            "complaint_enabled": bool(no_reply_step) or random.random() < min(0.55, complaint_chance),
            "complaint_sent": False,
            "complaint_after_ts": _now_ts() + complaint_after_minutes * 60,
            "complaint_reason": _single_line((no_reply_step or {}).get("reason"), 40),
            "complaint_topic": _single_line((no_reply_step or {}).get("topic"), 80),
            "complaint_motive": self._normalize_internal_motive_text(_single_line((no_reply_step or {}).get("motive"), 100)),
            "complaint_tone": "克制一点,把重点补上" if reason == "morning_greeting" else _single_line((no_reply_step or {}).get("tone"), 30),
            "second_followup": still_no_reply_step if isinstance(still_no_reply_step, dict) else {},
        }

    def _weighted_choice(self, items: list[tuple[str, float]]) -> str:
        filtered = [(name, max(0.0, float(weight))) for name, weight in items if name]
        if not filtered:
            return "message"
        total = sum(weight for _, weight in filtered)
        if total <= 0:
            return filtered[0][0]
        point = random.random() * total
        upto = 0.0
        for name, weight in filtered:
            upto += weight
            if point <= upto:
                return name
        return filtered[-1][0]

    def _maybe_combine_actions(
        self,
        primary: str,
        reason: str,
        *,
        weather: str = "",
        action_profile: dict[str, bool] | None = None,
        user: dict[str, Any] | None = None,
    ) -> str:
        profile = action_profile or self._persona_action_profile()
        candidates: list[tuple[str, float]] = []
        if primary == "photo_text" and self._voice_available(user) and reason in {"activity_share", "diary_share", "background_schedule"}:
            weight = 0.06
            if profile["clingy"] or profile["voicey"]:
                weight += 0.06
            if any(token in weather for token in ("晚霞", "雨", "晴", "阳光")):
                weight += 0.04
            candidates.append(("photo_text+voice", weight))
        if not candidates:
            return primary
        candidates.append((primary, 1.0))
        return self._weighted_choice(candidates)

    def _persona_action_profile(self) -> dict[str, bool]:
        text = str(self._get_default_persona_prompt() or "")
        playful_markers = ("恶作剧", "小恶魔", "腹黑", "俏皮", "捉弄", "欺负", "调皮")
        clingy_markers = ("依赖", "依恋", "特殊的情感", "知心朋友", "关心", "体贴", "想念", "共犯")
        observant_markers = ("看透", "观察", "温柔", "安静", "留意", "敏锐")
        visual_markers = ("自拍", "照片", "景色", "表情包", "外观", "外形", "穿搭", "发型", "发饰")
        voice_markers = ("悄悄说", "口语化", "抽空回复", "亲切感", "温柔", "顺从")
        return {
            "playful": any(marker in text for marker in playful_markers),
            "clingy": any(marker in text for marker in clingy_markers),
            "observant": any(marker in text for marker in observant_markers),
            "visual": any(marker in text for marker in visual_markers),
            "voicey": any(marker in text for marker in voice_markers),
        }

    def _reason_windows(self, reason: str) -> list[tuple[int, int]]:
        reason = self._normalize_legacy_proactive_text(reason, limit=40)
        if reason in {"holiday_celebration", "course_reminder"}:
            # Real per-user windows and class start are checked again directly
            # before send; the generic 09:00 floor must not suppress 07:50.
            return [(0, 24 * 60)]
        if reason == "morning_greeting":
            return [self._morning_greeting_window()]
        if (self._companion_frequency_enabled()
                and str(getattr(self, "companion_night_mode", "quiet_companion")) == "quiet_companion"
                and reason in {"check_in", "quiet_care"}):
            return [(9 * 60, 24 * 60), (0, 2 * 60)]
        return {
            "insomnia_night": [(23 * 60, 24 * 60), (0, 6 * 60)],
            "group_share": [(9 * 60, 23 * 60)],
            "bili_video_share": [(10 * 60, 23 * 60)],
            "news_share": [(8 * 60, 23 * 60)],
            "web_exploration_share": [(9 * 60, 23 * 60)],
            "environment_change": [(6 * 60, 23 * 60 + 30)],
            "jm_cosmos_recommendation_request": [(10 * 60, 23 * 60)],
            "creative_share": [(10 * 60, 23 * 60)],
            "personal_goal_progress": [(8 * 60, 22 * 60)],
            "memo_note_reminder": [(7 * 60, 23 * 60)],
            "state_share": [(8 * 60, 22 * 60 + 30)],
            "quiet_care": [(9 * 60, 22 * 60 + 30)],
            "activity_share": [(10 * 60, 18 * 60 + 30)],
            "diary_share": [(19 * 60, 23 * 60)],
            "important_date_share": [(8 * 60 + 30, 22 * 60)],
            "birthday_curiosity": [(10 * 60, 12 * 60), (15 * 60, 20 * 60 + 30)],
            "birthday_eve_hint": [(17 * 60 + 30, 21 * 60 + 30)],
            "birthday_celebration": [(9 * 60 + 30, 21 * 60 + 55)],
            "birthday_makeup": [(9 * 60 + 30, 13 * 60 + 55)],
            "birthday_afterglow": [(10 * 60, 21 * 60 + 25)],
            "background_schedule": [(9 * 60, 22 * 60)],
            "check_in": [(9 * 60, 22 * 60 + 30)],
            "noon_greeting": [(12 * 60 + 5, 13 * 60 + 35)],
            "evening_greeting": [(20 * 60 + 10, 21 * 60 + 20)],
            "meal_care": [(7 * 60 + 50, 20 * 60 + 35)],
            "meal_care_followup": [(8 * 60 + 5, 22 * 60)],
            "reading_share": [(18 * 60, 23 * 60 + 30)],
            "sleep_murmur": [(3 * 60, 4 * 60)],
            "social_visit": [(10 * 60, 22 * 60)],
        }.get(reason, [(9 * 60, 22 * 60)])

    def _is_reason_allowed_now(self, reason: str) -> bool:
        reason = self._normalize_legacy_proactive_text(reason, limit=40)
        now = self._environment_now()
        minute = now.hour * 60 + now.minute
        for start, end in self._reason_windows(reason):
            if start <= minute < end:
                if reason == "insomnia_night":
                    return self._has_active_insomnia_state()
                if reason == "diary_share":
                    return bool(self.data.get("bot_diaries"))
                if reason == "important_date_share":
                    return bool(self._get_relevant_important_dates())
                return True
        return False

    def _move_timestamp_into_reason_window(self, timestamp: float, reason: str) -> float:
        dt = self._environment_fromtimestamp(timestamp)
        minute = dt.hour * 60 + dt.minute
        windows = self._reason_windows(reason)
        for start, end in windows:
            if start <= minute < end:
                return timestamp + random.randint(0, 17 * 60)
        first_start = windows[0][0]
        target_date = dt.date()
        if all(minute >= end for _, end in windows):
            target_date = target_date + timedelta(days=1)
        hour, minute_part = divmod(first_start, 60)
        target = datetime.combine(target_date, datetime.min.time(), tzinfo=dt.tzinfo).replace(
            hour=hour % 24,
            minute=minute_part,
        )
        return target.timestamp() + random.randint(0, 59 * 60)

    def _can_send_insomnia_night_message(self, user: dict[str, Any]) -> bool:
        if not self.allow_insomnia_night_message:
            return False
        if not self._has_active_insomnia_state():
            return False
        hour = self._environment_now().hour
        if not (0 <= hour <= 5 or hour >= 23):
            return False
        daily_limit = self._effective_user_daily_limit(user)
        if (
            not self._proactive_daily_limit_is_unlimited(daily_limit)
            and _safe_int(user.get("sent_today"), 0) >= max(1, daily_limit)
        ):
            return False
        if _safe_float(user.get("last_sent"), 0) > 0:
            elapsed = _now_ts() - _safe_float(user.get("last_sent"), 0)
            if elapsed < max(6 * 3600, self._effective_user_min_interval_minutes(user) * 60):
                return False
        return random.random() < 0.35

    def _has_active_insomnia_state(self) -> bool:
        state = self.data.get("daily_state", {})
        conditions = state.get("conditions", []) if isinstance(state, dict) else []
        if not isinstance(conditions, list):
            return False
        keywords = ("失眠", "睡得很浅", "睡得断断续续", "睡眠延续")
        for cond in conditions:
            if not isinstance(cond, dict):
                continue
            text = f"{cond.get('title', '')} {cond.get('label', '')}"
            if any(keyword in text for keyword in keywords):
                return True
        return False

    def _passes_proactive_moment(self, user: dict[str, Any]) -> bool:
        hour = self._environment_now().hour
        state = self.data.get("daily_state", {})
        energy = _safe_int(state.get("energy") if isinstance(state, dict) else 70, 70, 0, 100)
        active_conditions = state.get("conditions", []) if isinstance(state, dict) else []
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        can_do = self.data.get("can_do", [])
        important_dates = self._get_relevant_important_dates()
        ignored_streak = _safe_int(user.get("ignored_streak"), 0)

        probability = 0.32
        if 8 <= hour <= 11:
            probability += 0.16
        elif 14 <= hour <= 17:
            probability += 0.16
        elif 19 <= hour <= 22:
            probability += 0.18
        else:
            probability -= 0.05

        if energy < 40:
            probability += 0.12
        elif energy > 80:
            probability += 0.06
        if active_conditions:
            probability += min(0.18, len(active_conditions) * 0.06)
        if current_item:
            probability += 0.08
        if isinstance(can_do, list) and can_do:
            probability += 0.12
        if current_item and _single_line(current_item.get("message_seed"), 80):
            probability += 0.12
        if important_dates:
            probability += 0.1 if _safe_int(important_dates[0].get("_days_until"), 0) == 0 else 0.05
        probability -= min(0.18, ignored_streak * 0.07)
        probability *= self._daily_intensity_factor(user)
        probability = max(0.12, min(0.9, probability))
        return random.random() < probability

    async def _render_message(self, user: dict[str, Any]) -> tuple[str, str, str, list[Any], str, str]:
        name = str(user.get("nickname") or self.default_nickname)
        user["planned_opener_mode"] = ""
        user.pop("_proactive_photo_subject_owner", None)
        planned_reason = self._normalize_legacy_proactive_text(user.get("planned_proactive_reason"), limit=40)
        planned_action = str(user.get("planned_proactive_action") or "message")
        planned_motive = _single_line(user.get("planned_proactive_motive"), 140)
        due_timer_active = self._has_due_llm_timer(user)
        troubleshooting_active = self._normalize_legacy_proactive_text(user.get("planned_proactive_source"), limit=40) == "troubleshooting"
        reason = planned_reason if planned_reason and (troubleshooting_active or due_timer_active or self._is_reason_allowed_now(planned_reason)) else ""
        if not reason:
            reason, _ = self._choose_proactive_message(user, name, planned_reason)
            planned_motive = self._choose_proactive_motive(reason, user, action=planned_action)
            planned_action = self._choose_action_for_reason(reason, user, motive=planned_motive)
        # Match one picture after the final approved text. Keep other actions.
        if callable(getattr(self, '_companion_image_required', None)) and self._companion_image_required(user):
            planned_action = '+'.join(p for p in planned_action.split('+') if p and p != 'photo_text') or 'message'
        if self._should_use_name_only_opener(
            user,
            reason=reason,
            action=planned_action,
            motive=planned_motive,
        ):
            user["planned_opener_mode"] = "name_only"
            return reason, self._build_name_only_opener(name), "", [], "先轻轻叫了你一声", "message"
        budget_remaining = getattr(self, "_llm_daily_budget_remaining", None)
        if callable(budget_remaining) and budget_remaining() == 0:
            user["_proactive_render_failure_stage"] = "今日 Token 硬限额已耗尽，未执行主动动作"
            return reason, "", "", [], "Token 硬限额已耗尽", planned_action
        deferred_poke = planned_action == "poke"
        action_payload = (
            {
                "success": True,
                "context": "poke：待主动正文确认可发送后再执行；本阶段尚未产生实际戳一戳",
                "extra_components": [],
                "summary": "准备戳一下",
                "effective_action": "poke",
            }
            if deferred_poke
            else await self._execute_proactive_action(planned_action, user, name, reason)
        )
        effective_action = _single_line(action_payload.get("effective_action") or planned_action, 60) or "message"
        raw_action_context = str(action_payload.get("context") or "")
        if reason == "group_share":
            share_context = self._format_group_share_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, share_context) if part).strip()
        if reason == "bili_video_share":
            video_context = self._format_bilibili_video_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, video_context) if part).strip()
        if reason == "news_share":
            news_context = self._format_news_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, news_context) if part).strip()
        if reason == "web_exploration_share":
            exploration_context = self._format_web_exploration_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, exploration_context) if part).strip()
        if reason == "jm_cosmos_share":
            jm_context = self._format_jm_cosmos_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, jm_context) if part).strip()
        if reason == "jm_cosmos_recommendation_request":
            ask_context = user.get("jm_cosmos_recommendation_context") if isinstance(user.get("jm_cosmos_recommendation_context"), dict) else {}
            ask_text = _single_line(ask_context.get("hint"), 160) or "想向用户问有没有适合私下看的阅读素材推荐。"
            raw_action_context = "\n".join(part for part in (raw_action_context, f"夹层阅读推荐征求：{ask_text}") if part).strip()
        if reason == "creative_share":
            creative_context = self._format_creative_share_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, creative_context) if part).strip()
        if reason == "reading_share":
            reading_context = self._format_reading_share_action_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, reading_context) if part).strip()
        if reason == "sleep_murmur":
            murmur_ctx = self._format_sleep_murmur_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, murmur_ctx) if part).strip()
        if reason == "social_visit":
            visit_ctx = self._format_social_visit_context(user)
            raw_action_context = "\n".join(part for part in (raw_action_context, visit_ctx) if part).strip()
        extra_components = list(action_payload.get("extra_components") or [])
        action_summary = _single_line(action_payload.get("summary") or planned_action, 80)
        if not bool(action_payload.get("success", True)):
            if "photo_text" in {planned_action, effective_action}:
                logger.info(
                    "[PrivateCompanion] 主动图片动作未产出,降级为纯文字分享: user=%s reason=%s topic=%s",
                    _single_line(user.get("user_id"), 40),
                    reason,
                    _single_line(user.get("planned_proactive_topic"), 80),
                )
                planned_action = "message"
                effective_action = "message"
                extra_components = []
                raw_action_context = "message：图片动作本轮未产出；只按原话题自然分享，不得声称已拍照、已生成或已发送图片"
                action_summary = "图片未产出，已降级为文字"
            else:
                user["_proactive_render_failure_stage"] = f"主动动作执行失败：{effective_action or planned_action or 'unknown'}"
                return reason, "", "", [], action_summary, effective_action
        image_path = self._extract_action_image_path(raw_action_context)
        photo_caption = self._extract_action_photo_caption(raw_action_context)
        photo_subject_owner = self._extract_action_photo_subject_owner(raw_action_context)
        if image_path:
            user["_proactive_photo_subject_owner"] = photo_subject_owner or "unknown"
        if image_path and photo_caption:
            action_summary = f"发图：{photo_caption}"
        action_context = await self._narrate_action_context(effective_action, raw_action_context)
        if image_path:
            action_context = f"{action_context}\n真实图片文件：{image_path}".strip()
        text = await self._generate_proactive_message_with_llm(
            user, name, reason, action_context, action=effective_action, motive=planned_motive
        )
        captured_text, captured_image_path, captured_extra_components = self._pop_framework_captured_send_payload(
            str(user.get("umo") or "")
        )
        if "photo_text" in effective_action or planned_action == "photo_text":
            if captured_text:
                text = captured_text
            if captured_image_path:
                image_path = captured_image_path
            if self._contains_inline_image_tag(text):
                image_path = ""
                extra_components = []
        if captured_extra_components:
            extra_components = list(captured_extra_components)
        if "photo_text" in planned_action and self._contains_inline_image_tag(text):
            image_path = ""
            extra_components = []
        if not image_path and not extra_components:
            text = self._remove_unbacked_media_claims(text)
        text = self._visible_text_without_tts_reading(text, limit=1000)
        text = self._normalize_proactive_sentence_flow(text)
        if reason == "group_share":
            recency_repair = getattr(self, "_repair_group_share_recency_text", None)
            if callable(recency_repair):
                text = recency_repair(user, text)
        if not text and not image_path and not extra_components:
            return reason, "", "", [], action_summary, effective_action
        if deferred_poke:
            poke_payload = await self._execute_proactive_action("poke", user, name, reason)
            if not bool(poke_payload.get("success", False)):
                user["_proactive_render_failure_stage"] = _single_line(
                    poke_payload.get("context"), 160
                ) or "主动戳一戳执行失败"
                return reason, "", "", [], "戳一戳未执行", "poke"
            action_summary = _single_line(poke_payload.get("summary"), 80) or "戳了你一下"
        pre_poke_count, pre_poke_context = await self._maybe_run_pre_message_poke(
            user,
            name,
            reason,
            action=effective_action,
            motive=planned_motive,
        )
        if pre_poke_context and not pre_poke_context.startswith("poke：已"):
            logger.info("[PrivateCompanion] 消息前置戳一戳失败,跳过本次前置戳: %s", _single_line(pre_poke_context, 120))
        if pre_poke_count > 0:
            action_summary = f"先戳了 {pre_poke_count} 下 + {action_summary}"
            effective_action = f"poke+{effective_action}" if effective_action != "poke" else "poke"
        return reason, text, image_path, extra_components, action_summary, effective_action

    async def _test_proactive_action(
        self,
        user: dict[str, Any],
        *,
        action_name: str,
        reason: str,
    ) -> tuple[str, str, list[Any]]:
        name = str(user.get("nickname") or self.default_nickname)
        motive = self._choose_proactive_motive(reason, user, action=action_name)
        action_payload = await self._execute_proactive_action(action_name, user, name, reason)
        action_context = str(action_payload.get("context") or "")
        extra_components = list(action_payload.get("extra_components") or [])
        image_path = self._extract_action_image_path(action_context)
        narrated = await self._narrate_action_context(action_name, action_context)
        if image_path:
            narrated = f"{narrated}\n真实图片文件：{image_path}".strip()
        text = await self._generate_proactive_message_with_llm(
            user, name, reason, narrated, action=action_name, motive=motive
        )
        if not text:
            text = ""
        failure_note = ""
        if not bool(action_payload.get("success", True)):
            failure_note = "\n结果：本次真实主动行为失败；后台正常触发时会直接放弃,不会硬发。"
        return (
            "测试完成：\n"
            f"行为：{action_name}\n"
            f"动机：{motive}\n"
            f"转述：{_single_line(narrated, 180)}\n"
            f"最终消息：\n{text}{failure_note}"
        ), image_path, extra_components

    # ===== 区块7-10、12、13 生成发送层（原 proactive_message.py；照片区块拆至 proactive_photo.py；总入口 _choose_proactive_message 位于文件末尾）=====
    def _proactive_chat_bridge_user(self, session_id: str) -> tuple[str, dict[str, Any] | None]:
        session = _single_line(session_id, 180)
        if ":FriendMessage:" not in session:
            return "", None
        resolver = getattr(self, "_input_status_user_id_from_umo", None)
        user_id = resolver(session) if callable(resolver) else ""
        if not user_id:
            user_id = _single_line(session.split(":FriendMessage:", 1)[-1], 100)
        canonicalizer = getattr(self, "_canonical_private_user_id", None)
        if callable(canonicalizer):
            user_id = str(canonicalizer(user_id) or "").strip()
        users = self.data.get("users") if isinstance(getattr(self, "data", None), dict) else None
        user = users.get(user_id) if isinstance(users, dict) else None
        return user_id, user if isinstance(user, dict) else None

    def _proactive_chat_decorating_context(self) -> dict[str, Any]:
        """Read Proactive Chat's send context, preferring the deep runtime attempt."""
        context: dict[str, Any] = {
            "detected": False,
            "deep_bridge": False,
            "attempt_id": "",
            "token": "",
            "full_text": "",
            "tts_sent": False,
            "segment_index": 0,
            "segment_count": 1,
        }
        runtime_context: dict[str, Any] = {}
        runtime_bridge = getattr(self, "_proactive_chat_runtime_bridge", None)
        if runtime_bridge is not None:
            try:
                runtime_context = runtime_bridge.outbound_context()
            except Exception:
                runtime_context = {}
        frame = sys._getframe()
        try:
            for _ in range(48):
                frame = frame.f_back
                if frame is None:
                    break
                module_name = str(frame.f_globals.get("__name__", "") or "")
                if "astrbot_plugin_proactive_chat" not in module_name:
                    continue
                context["detected"] = True
                if frame.f_code.co_name != "_send_proactive_message":
                    continue
                local_values = frame.f_locals
                context["attempt_id"] = f"proactive-chat-{id(frame):x}"
                context["full_text"] = str(local_values.get("text") or "").strip()
                context["tts_sent"] = bool(local_values.get("is_tts_sent", False))
                segments = local_values.get("segments")
                if isinstance(segments, list) and segments:
                    context["segment_count"] = max(1, len(segments))
                    try:
                        context["segment_index"] = max(
                            0,
                            min(
                                int(local_values.get("idx", 0) or 0),
                                context["segment_count"] - 1,
                            ),
                        )
                    except Exception:
                        context["segment_index"] = 0
        finally:
            del frame
        if runtime_context:
            context.update(
                {
                    "detected": True,
                    "deep_bridge": True,
                    "attempt_id": _single_line(runtime_context.get("attempt_id"), 100),
                    "token": _single_line(runtime_context.get("token"), 80),
                    "full_text": str(runtime_context.get("full_text") or context.get("full_text") or "").strip(),
                }
            )
        return context

    def _proactive_chat_bridge_review_cache(self) -> dict[str, dict[str, Any]]:
        cache = getattr(self, "_proactive_chat_bridge_reviews", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_proactive_chat_bridge_reviews", cache)
        now = _now_ts()
        stale = [
            key
            for key, item in cache.items()
            if not isinstance(item, dict) or now - _safe_float(item.get("created_at"), 0) > 10 * 60
        ]
        for key in stale:
            cache.pop(key, None)
        if len(cache) > 80:
            ordered = sorted(
                cache,
                key=lambda key: _safe_float(cache.get(key, {}).get("created_at"), 0),
            )
            for key in ordered[: len(cache) - 80]:
                cache.pop(key, None)
        return cache

    def _proactive_chat_bridge_preflight_block_reason(
        self,
        user: dict[str, Any],
        *,
        now: float,
    ) -> str:
        companion_block = self._companion_frequency_block_reason(user, now=now)
        if companion_block:
            return companion_block
        rest_gate = getattr(self, "_proactive_rest_block_until", None)
        if callable(rest_gate):
            try:
                if _safe_float(
                    rest_gate(
                        user,
                        now=now,
                        reason="check_in",
                        source="proactive_chat",
                    ),
                    0,
                ) > now:
                    return "user_explicit_rest"
            except Exception:
                pass
        quiet_checker = getattr(self, "_is_quiet_time", None)
        insomnia_checker = getattr(self, "_can_send_insomnia_night_message", None)
        try:
            quiet = bool(quiet_checker()) if callable(quiet_checker) else False
            insomnia_allowed = bool(insomnia_checker(user)) if callable(insomnia_checker) else False
            if quiet and not insomnia_allowed:
                return "private_companion_quiet_hours"
        except Exception:
            pass
        relation = user.get("relationship_state")
        if isinstance(relation, dict):
            mode = _single_line(relation.get("mode"), 24)
            blocked_until = max(
                _safe_float(relation.get("backoff_until"), 0),
                _safe_float(relation.get("hurt_until"), 0),
            )
            if mode in {"backoff", "hurt", "refusing"} and blocked_until > now:
                return "relationship_backoff"
        collision_window = max(
            10,
            min(
                600,
                _safe_int(
                    getattr(self, "proactive_chat_bridge_collision_window_seconds", 90),
                    90,
                    10,
                    600,
                ),
            ),
        )
        last_sent = max(
            _safe_float(user.get("last_sent"), 0),
            _safe_float(user.get("last_proactive_sent_at"), 0),
            _safe_float(user.get("proactive_chat_bridge_last_sent_at"), 0),
        )
        if last_sent > 0 and now - last_sent < collision_window:
            return "recent_proactive_collision_window"
        return ""

    async def _prepare_proactive_chat_bridge(
        self,
        session_id: str,
        *,
        unanswered_count: int = 0,
    ) -> dict[str, Any]:
        if not bool(getattr(self, "enable_proactive_chat_integration", True)):
            return {"enabled": False, "allowed": True, "reason": "integration_disabled"}
        user_id, user = self._proactive_chat_bridge_user(session_id)
        if not user_id or not isinstance(user, dict):
            return {"enabled": False, "allowed": True, "reason": "private_user_not_managed"}
        enabled_checker = getattr(self, "_user_enabled_for_proactive", None)
        if callable(enabled_checker) and not enabled_checker(user_id, user):
            return {"enabled": True, "allowed": False, "reason": "private_user_disabled"}
        now = _now_ts()
        if bool(user.get("proactive_sending")):
            recover = getattr(self, "_recover_stale_proactive_sending", None)
            if callable(recover):
                recover(user, now=now)
        if bool(user.get("proactive_sending")):
            return {"enabled": True, "allowed": False, "reason": "another_proactive_message_is_sending"}
        preflight_block = self._proactive_chat_bridge_preflight_block_reason(user, now=now)
        if preflight_block:
            return {"enabled": True, "allowed": False, "reason": preflight_block}
        runtime_formatter = getattr(self, "_format_proactive_review_runtime_context", None)
        runtime_context = runtime_formatter(user, now=now) if callable(runtime_formatter) else ""
        identity_formatter = getattr(self, "_format_proactive_recipient_identity_guard", None)
        recipient_identity = (
            identity_formatter(user, _single_line(user.get("nickname"), 40))
            if callable(identity_formatter)
            else ""
        )
        voice_formatter = getattr(self, "_format_proactive_voice_prompt", None)
        proactive_voice = voice_formatter() if callable(voice_formatter) else ""
        expression_formatter = getattr(self, "_format_expression_voice_for_prompt", None)
        expression_voice = (
            expression_formatter(
                scope="proactive",
                target_id=user_id,
                context_owner=user,
                stage_owner=user,
            )
            if callable(expression_formatter)
            else ""
        )
        relationship_formatter = getattr(self, "_format_proactive_relationship_fact", None)
        try:
            relationship_context = relationship_formatter(user) if callable(relationship_formatter) else ""
        except Exception:
            relationship_context = ""
        intent_formatter = getattr(self, "_format_intent_relationship_injection", None)
        try:
            intent_context = intent_formatter(user) if callable(intent_formatter) else ""
        except Exception:
            intent_context = ""
        time_formatter = getattr(self, "_format_time_period_injection", None)
        try:
            time_context = time_formatter() if callable(time_formatter) else ""
        except Exception:
            time_context = ""
        state_context = ""
        state_formatter = getattr(self, "_format_state_for_framework_prompt", None)
        daily_state = self.data.get("daily_state") if isinstance(getattr(self, "data", None), dict) else None
        if callable(state_formatter):
            try:
                state_context = state_formatter(
                    daily_state if isinstance(daily_state, dict) else {},
                    reason="check_in",
                    action="message",
                )
            except Exception:
                state_context = ""
        schedule_context = ""
        schedule_formatter = getattr(self, "_format_schedule_context_for_prompt", None)
        if callable(schedule_formatter):
            try:
                schedule_context = str(schedule_formatter() or "").strip()
            except Exception:
                schedule_context = ""
        schedule_sanitizer = getattr(self, "_sanitize_schedule_context_for_private_user", None)
        if schedule_context and callable(schedule_sanitizer):
            try:
                schedule_context = str(schedule_sanitizer(schedule_context, user) or "").strip()
            except Exception:
                schedule_context = ""
        fragment = "\n".join(
            part
            for part in (
                "【Private Companion × Proactive Chat 联动】",
                "这是一条由 Proactive Chat 定时触发的主动消息，不是在回复用户刚发来的话。",
                f"当前连续未回应次数：{max(0, int(unanswered_count or 0))}。不要因此质问、催促或制造负担。",
                recipient_identity,
                f"【当前关系】\n{relationship_context}" if relationship_context else "",
                f"【当前互动气氛】\n{_single_line(intent_context, 360)}" if intent_context else "",
                f"【当前时机】\n{time_context}" if time_context else "",
                f"【当前运行态】\n{runtime_context}" if runtime_context else "",
                f"【Bot 当前状态底色】\n{state_context}" if state_context else "",
                f"【当前生活片段候选】\n{schedule_context[:700]}" if schedule_context and schedule_context != "（暂无）" else "",
                proactive_voice,
                expression_voice,
                "先沿用 Proactive Chat 本轮自己的主动动机，再从以上信息中只取与当前收件人和此刻真正相关的少量线索；不要拼成状态播报。",
                "只吸收与当前收件人、关系和时机有关的内容；不要提到插件、调度器、状态字段或联动过程。",
            )
            if str(part or "").strip()
        )
        token = uuid.uuid4().hex
        lock = getattr(self, "_data_lock", None)
        if lock is not None:
            async with lock:
                current = self._get_user(user_id)
                if current.get("proactive_sending"):
                    return {"enabled": True, "allowed": False, "reason": "another_proactive_message_is_sending"}
                preflight_block = self._proactive_chat_bridge_preflight_block_reason(current, now=now)
                if preflight_block:
                    return {"enabled": True, "allowed": False, "reason": preflight_block}
                current["proactive_sending"] = True
                current["proactive_sending_started_at"] = now
                current["proactive_chat_bridge_token"] = token
                current["proactive_chat_bridge_session"] = _single_line(session_id, 180)
                self._save_data_sync()
        return {
            "enabled": True,
            "allowed": True,
            "token": token,
            "prompt_fragment": fragment[:5200].strip(),
            "user_id": user_id,
        }

    async def _review_proactive_chat_bridge_message(
        self,
        session_id: str,
        text: str,
        *,
        token: str = "",
        attempt_id: str = "",
    ) -> dict[str, Any]:
        if not bool(getattr(self, "enable_proactive_chat_integration", True)):
            return {"ok": True, "text": str(text or "").strip(), "reason": "integration_disabled"}
        user_id, user = self._proactive_chat_bridge_user(session_id)
        if not user_id or not isinstance(user, dict):
            return {"ok": True, "text": str(text or "").strip(), "reason": "bridge_not_managed"}
        enabled_checker = getattr(self, "_user_enabled_for_proactive", None)
        if callable(enabled_checker) and not enabled_checker(user_id, user):
            return {"ok": True, "text": str(text or "").strip(), "reason": "bridge_not_managed"}
        expected = _single_line(user.get("proactive_chat_bridge_token"), 80)
        if expected and token != expected:
            return {"ok": False, "text": "", "reason": "bridge_token_mismatch"}
        cache_key = _single_line(attempt_id, 100)
        if cache_key:
            cached = self._proactive_chat_bridge_review_cache().get(cache_key)
            if isinstance(cached, dict) and cached.get("session_id") == _single_line(session_id, 180):
                result = cached.get("result")
                if isinstance(result, dict):
                    return dict(result)
        cleaned = self._sanitize_proactive_text(str(text or "").strip())
        if not cleaned:
            return {"ok": False, "text": "", "reason": "empty_after_sanitize"}
        local_checker = getattr(self, "_local_proactive_send_decision", None)
        decision: dict[str, Any] = {"decision": "send", "reason": "local_checker_unavailable"}
        if callable(local_checker):
            decision = local_checker(
                user,
                cleaned,
                reason="proactive_chat_bridge",
                action="message",
                motive="由 Proactive Chat 提供更即时的主动触发",
                topic="",
                action_context="没有外部图片或工具结果",
            )
        review_mode = str(getattr(self, "proactive_chat_bridge_review_mode", "local") or "local").strip().lower()
        full_reviewer = getattr(self, "_review_proactive_message_send_decision", None)
        if (
            review_mode == "follow_proactive_review"
            and bool(getattr(self, "enable_proactive_message_review", True))
            and callable(full_reviewer)
            and str(getattr(self, "proactive_review_mode", "full") or "full").strip().lower() != "local_only"
        ):
            try:
                decision = await full_reviewer(
                    user,
                    cleaned,
                    reason="proactive_chat_bridge",
                    action="message",
                    motive="由 Proactive Chat 提供更即时的主动触发",
                    topic="",
                    action_summary="Proactive Chat 已生成纯文本主动候选；没有外部图片或工具结果",
                )
            except Exception as exc:
                logger.warning(
                    "[PrivateCompanion] Proactive Chat 联动终审失败，已回退本地检查: %s",
                    _single_line(exc, 160),
                )

        action = str(decision.get("decision") or "send").strip().lower()
        if action in {"drop", "defer"}:
            result = {
                "ok": False,
                "text": "",
                "reason": _single_line(decision.get("reason"), 160) or action,
                "decision": action,
            }
        else:
            if action == "rewrite" and _single_line(decision.get("text"), 500):
                cleaned = self._sanitize_proactive_text(_single_line(decision.get("text"), 500))
            result = {
                "ok": bool(cleaned),
                "text": cleaned,
                "reason": _single_line(decision.get("reason"), 160)
                or ("private_companion_model_review" if review_mode == "follow_proactive_review" else "private_companion_local_review"),
                "decision": action if action in {"send", "rewrite"} else "send",
            }
        if cache_key:
            self._proactive_chat_bridge_review_cache()[cache_key] = {
                "created_at": _now_ts(),
                "session_id": _single_line(session_id, 180),
                "result": dict(result),
            }
        return result

    async def _record_proactive_chat_bridge_sent(
        self,
        session_id: str,
        text: str,
        *,
        token: str = "",
        attempt_id: str = "",
    ) -> dict[str, Any]:
        if not bool(getattr(self, "enable_proactive_chat_integration", True)):
            return {"recorded": False, "reason": "integration_disabled"}
        user_id, user = self._proactive_chat_bridge_user(session_id)
        if not user_id or not isinstance(user, dict):
            return {"recorded": False, "reason": "private_user_not_managed"}
        enabled_checker = getattr(self, "_user_enabled_for_proactive", None)
        if callable(enabled_checker) and not enabled_checker(user_id, user):
            return {"recorded": False, "reason": "private_user_not_managed"}
        now = _now_ts()
        visible_formatter = getattr(self, "_visible_text_without_tts_reading", None)
        visible = (
            visible_formatter(text, limit=500)
            if callable(visible_formatter)
            else _single_line(text, 500)
        )
        lock = getattr(self, "_data_lock", None)
        if lock is not None:
            async with lock:
                current = self._get_user(user_id)
                expected = _single_line(current.get("proactive_chat_bridge_token"), 80)
                if expected and token != expected:
                    return {"recorded": False, "reason": "bridge_token_mismatch"}
                normalized_attempt = _single_line(attempt_id, 100)
                if normalized_attempt and _single_line(current.get("proactive_chat_bridge_last_attempt_id"), 100) == normalized_attempt:
                    return {"recorded": False, "reason": "duplicate_attempt", "user_id": user_id}
                if expected:
                    current["proactive_sending"] = False
                    current["proactive_sending_started_at"] = 0
                current["proactive_chat_bridge_token"] = ""
                current["proactive_chat_bridge_session"] = ""
                current["last_sent"] = now
                current["last_proactive_sent_at"] = now
                current["last_proactive_message"] = visible
                current["last_companion_message"] = visible
                current["last_companion_message_at"] = now
                current["last_proactive_delivery_umo"] = _single_line(session_id, 180)
                current["last_proactive_delivery_inbound_count"] = _safe_int(current.get("inbound_count"), 0)
                current["last_proactive_reply_context_consumed_for"] = 0
                current["last_proactive_reason"] = "proactive_chat_bridge"
                current["last_proactive_action"] = "message"
                current["last_proactive_motive"] = "Proactive Chat 即时触发"
                current["proactive_chat_bridge_last_sent_at"] = now
                current["proactive_chat_bridge_last_attempt_id"] = normalized_attempt
                reset_daily = getattr(self, "_reset_daily_counter_if_needed", None)
                if callable(reset_daily):
                    reset_daily(current)
                elif str(current.get("sent_day") or "") != _today_key():
                    current["sent_day"] = _today_key()
                    current["sent_today"] = 0
                current["sent_today"] = _safe_int(current.get("sent_today"), 0) + 1
                current["proactive_sent_count"] = _safe_int(current.get("proactive_sent_count"), 0) + 1
                current["ignored_streak"] = _safe_int(current.get("ignored_streak"), 0) + 1
                current["awaiting_reply_since"] = now
                current["pending_followup_event"] = {}
                current["planned_proactive_quota_exempt"] = False
                action_recorder = getattr(self, "_note_action_sent", None)
                if callable(action_recorder):
                    action_recorder(
                        current,
                        "message",
                        reason="proactive_chat_bridge",
                        text=visible or text,
                        motive="Proactive Chat 即时触发",
                        action_summary="外部主动插件已完成发送",
                    )
                topic_recorder = getattr(self, "_remember_proactive_topic", None)
                if callable(topic_recorder):
                    topic_recorder(current, text=visible or text, topic="Proactive Chat", motive="即时主动触发")
                self._save_data_sync()
        logger.info(
            "[PrivateCompanion] 已同步 Proactive Chat 主动发送: user=%s session=%s text=%s",
            user_id,
            _single_line(session_id, 120),
            _single_line(visible, 120),
        )
        return {"recorded": True, "user_id": user_id, "sent_at": now}

    async def _cancel_proactive_chat_bridge(self, session_id: str, *, token: str = "") -> bool:
        user_id, user = self._proactive_chat_bridge_user(session_id)
        if not user_id or not isinstance(user, dict):
            return False
        lock = getattr(self, "_data_lock", None)
        if lock is None:
            return False
        async with lock:
            current = self._get_user(user_id)
            expected = _single_line(current.get("proactive_chat_bridge_token"), 80)
            if not expected or token != expected:
                return False
            current["proactive_sending"] = False
            current["proactive_sending_started_at"] = 0
            current["proactive_chat_bridge_token"] = ""
            current["proactive_chat_bridge_session"] = ""
            self._save_data_sync()
        return True

    @staticmethod
    def _looks_like_internal_provider_error_text(text: Any) -> bool:
        cleaned = _single_line(text, 1000).lower()
        if not cleaned:
            return False
        normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff_]+", " ", cleaned).strip()
        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff_]+", "", cleaned)
        direct_markers = (
            "all chat models failed",
            "all llm providers failed",
            "badrequesterror",
            "api connection error",
            "apiconnectionerror",
            "api status error",
            "apistatuserror",
            "authenticationerror",
            "permissiondeniederror",
            "ratelimiterror",
            "notfounderror",
            "internalservererror",
            "provider api error",
            "unable to submit request",
            "invalid_request",
            "invalid request error",
            "functiondeclaration",
            "function declaration",
            "schema didn't specify",
            "tool schema",
            "tool has no return value",
            "status disabled",
            "主动消息专用模式下",
            "普通被动回复不可使用 private companion 工具",
            "主动渲染阶段不可使用 private companion 工具",
            "has sent the result directly to the user",
            "traceback",
            "error code: 400",
            "error code 400",
            "400 bad request",
            "模型调用失败",
            "工具调用失败",
            "函数工具调用失败",
            "api 调用失败",
            "api调用失败",
            "provider 调用失败",
            "provider调用失败",
            "没有返回值，或者已将结果直接发送给用户",
            "没有返回值,或者已将结果直接发送给用户",
        )
        compact_markers = (
            "allchatmodelsfailed",
            "allllmprovidersfailed",
            "badrequesterror",
            "apiconnectionerror",
            "apistatuserror",
            "authenticationerror",
            "permissiondeniederror",
            "ratelimiterror",
            "notfounderror",
            "internalservererror",
            "providerapierror",
            "unabletosubmitrequest",
            "invalid_request",
            "invalidrequest",
            "invalidrequesterror",
            "functiondeclaration",
            "schemadidntspecify",
            "toolschema",
            "toolhasnoreturnvalue",
            "statusdisabled",
            "主动消息专用模式下",
            "普通被动回复不可使用privatecompanion工具",
            "主动渲染阶段不可使用privatecompanion工具",
            "hassenttheresultdirectlytotheuser",
            "errorcode400",
            "400badrequest",
            "模型调用失败",
            "工具调用失败",
            "函数工具调用失败",
            "api调用失败",
            "provider调用失败",
            "没有返回值或者已将结果直接发送给用户",
        )
        if any(marker in cleaned or marker in normalized for marker in direct_markers):
            return True
        if any(marker in compact for marker in compact_markers):
            return True
        if "errorcode" in compact and any(
            token in compact
            for token in (
                "badrequest",
                "invalidrequest",
                "provider",
                "apierror",
                "functiondeclaration",
            )
        ):
            return True
        if "functiondeclaration" in compact and any(
            token in compact for token in ("schema", "properties", "parameters", "tool", "tools", "badrequest", "invalidrequest")
        ):
            return True
        if "aisearch" in cleaned and any(
            marker in cleaned
            for marker in (
                "failed",
                "badrequest",
                "invalid_request",
                "unable to submit",
                "provider api",
            )
        ):
            return True
        return False

    def _clean_external_share_source_field(self, value: Any, limit: int = 160) -> str:
        text = _single_line(value, limit)
        if not text:
            return ""
        if self._looks_like_internal_provider_error_text(text):
            return ""
        if self._framework_agent_meta_summary_leak(text):
            return ""
        return text

    def _format_bilibili_video_action_context(self, user: dict[str, Any]) -> str:
        video = user.get("bilibili_video_context")
        if not isinstance(video, dict):
            return ""
        if _now_ts() - _safe_float(video.get("created_ts"), 0) > 6 * 3600:
            return ""
        title = self._clean_external_share_source_field(video.get("title"), 80)
        bvid = self._clean_external_share_source_field(video.get("bvid"), 32)
        up_name = self._clean_external_share_source_field(video.get("up_name"), 40)
        score = _safe_int(video.get("score"), 0, 0, 10)
        mood = self._clean_external_share_source_field(video.get("mood"), 24)
        comment = self._clean_external_share_source_field(video.get("comment"), 120)
        review = self._clean_external_share_source_field(video.get("review"), 180)
        source = self._clean_external_share_source_field(video.get("source"), 40)
        memory_context = video.get("memory_context") if isinstance(video.get("memory_context"), list) else []
        memory_lines = [
            text
            for item in memory_context
            for text in [self._clean_external_share_source_field(item, 160)]
            if text
        ][:3]
        if not title and not bvid and not comment and not review:
            return ""
        parts = [
            "B站视频分享线索",
            f"标题：{title}" if title else "",
            f"链接：https://www.bilibili.com/video/{bvid}" if bvid else "",
            f"UP：{up_name}" if up_name else "",
            f"评分：{score}/10" if score else "",
            f"心情：{mood}" if mood else "",
            f"短评：{comment}" if comment else "",
            f"回味：{review}" if review else "",
            f"来源：{source}" if source else "",
            "BiliBot记忆：" + " / ".join(memory_lines) if memory_lines else "",
        ]
        return "\n".join(part for part in parts if part)

    def _format_news_action_context(self, user: dict[str, Any]) -> str:
        news = user.get("news_context")
        if not isinstance(news, dict):
            return ""
        if _now_ts() - _safe_float(news.get("created_ts"), 0) > 8 * 3600:
            return ""
        topic = self._clean_external_share_source_field(news.get("topic"), 60)
        headline = self._clean_external_share_source_field(news.get("headline"), 100)
        source = self._clean_external_share_source_field(news.get("selected_source"), 40)
        impression = self._clean_external_share_source_field(news.get("impression"), 240)
        link = self._clean_external_share_source_field(news.get("selected_link"), 400)
        self_link = news.get("self_link") if isinstance(news.get("self_link"), dict) else {}
        self_link_text = self._clean_external_share_source_field(self_link.get("self_link") if isinstance(self_link, dict) else "", 180)
        self_link_tone = self._clean_external_share_source_field(news.get("share_tone") or (self_link.get("tone") if isinstance(self_link, dict) else ""), 80)
        self_link_boundary = self._clean_external_share_source_field(news.get("share_boundary") or (self_link.get("boundary") if isinstance(self_link, dict) else ""), 160)
        if not topic and not headline and not link and not impression:
            return ""
        parts = [
            "新闻阅读线索",
            f"话题：{topic}" if topic else "",
            f"标题：{headline}" if headline else "",
            f"来源：{source}" if source else "",
            f"内部印象：{impression}" if impression else "",
            f"和自己有关的地方：{self_link_text}" if self_link_text else "",
            f"表达气质：{self_link_tone}" if self_link_tone else "",
            f"额外边界：{self_link_boundary}" if self_link_boundary else "",
            f"链接：{link}" if link else "",
            "表达要求：不要像播报新闻,不要夸大或补充未知事实；按人格正常说话即可。",
        ]
        return "\n".join(part for part in parts if part)

    def _format_web_exploration_action_context(self, user: dict[str, Any]) -> str:
        exploration = user.get("web_exploration_context")
        if not isinstance(exploration, dict):
            return ""
        if _now_ts() - _safe_float(exploration.get("created_ts"), 0) > 10 * 3600:
            return ""
        query = self._clean_external_share_source_field(exploration.get("query"), 80)
        topic = self._clean_external_share_source_field(exploration.get("topic"), 80)
        note = self._clean_external_share_source_field(exploration.get("note"), 260)
        source_title = self._clean_external_share_source_field(exploration.get("source_title"), 120)
        source_url = self._clean_external_share_source_field(exploration.get("source_url"), 420)
        source_platform = self._external_share_platform_from_url(source_url)
        reason = self._clean_external_share_source_field(exploration.get("reason"), 140)
        self_link = exploration.get("self_link") if isinstance(exploration.get("self_link"), dict) else {}
        self_link_text = self._clean_external_share_source_field(self_link.get("self_link") if isinstance(self_link, dict) else "", 180)
        self_link_tone = self._clean_external_share_source_field(exploration.get("share_tone") or (self_link.get("tone") if isinstance(self_link, dict) else ""), 80)
        self_link_boundary = self._clean_external_share_source_field(exploration.get("share_boundary") or (self_link.get("boundary") if isinstance(self_link, dict) else ""), 160)
        if not query and not topic and not note and not source_title and not source_url:
            return ""
        parts = [
            "网页探索线索",
            f"搜索词：{query}" if query else "",
            f"为什么想查：{reason}" if reason else "",
            f"探索主题：{topic}" if topic else "",
            f"留下的印象：{note}" if note else "",
            f"和自己有关的地方：{self_link_text}" if self_link_text else "",
            f"表达气质：{self_link_tone}" if self_link_tone else "",
            f"额外边界：{self_link_boundary}" if self_link_boundary else "",
            f"参考来源：{source_title}" if source_title else "",
            f"来源平台（以链接域名为准）：{source_platform}" if source_platform else "",
            f"链接：{source_url}" if source_url else "",
            "表达要求：自然地向用户分享自己刚看的这条内容。标题、印象和链接只是事实参考，按当前人格正常说话，不要照抄字段。",
        ]
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _external_share_platform_from_url(url: Any) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        try:
            parsed = urlparse(value if "://" in value else f"//{value}")
            hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
        except Exception:
            hostname = ""
        if not hostname:
            return ""
        platform_domains = (
            (("bilibili.com", "b23.tv"), "B站"),
            (("douyin.com", "iesdouyin.com"), "抖音"),
            (("xiaohongshu.com", "xhslink.com"), "小红书"),
            (("weibo.com", "weibo.cn"), "微博"),
            (("zhihu.com",), "知乎"),
            (("youtube.com", "youtu.be"), "YouTube"),
            (("reddit.com", "redd.it"), "Reddit"),
            (("github.com",), "GitHub"),
            (("toutiao.com",), "今日头条"),
        )
        for domains, label in platform_domains:
            if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
                return label
        return ""

    @staticmethod
    def _external_share_claimed_platform(text: Any) -> str:
        value = _single_line(text, 320)
        patterns = (
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}(?:B站|哔哩哔哩)|(?:B站|哔哩哔哩)(?:视频|上|里|《)", "B站"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}抖音|抖音(?:视频|上|里|《)", "抖音"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}小红书|小红书(?:笔记|上|里|《)", "小红书"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}微博|微博(?:上|里|《)", "微博"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}知乎|知乎(?:上|里|《)", "知乎"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}YouTube|YouTube(?:上|里)", "YouTube"),
            (r"(?:刚|在|从|刷到|看到|翻到).{0,8}Reddit|Reddit(?:上|里|《)", "Reddit"),
        )
        for pattern, label in patterns:
            if re.search(pattern, value, flags=re.I):
                return label
        return ""

    def _proactive_link_platform_mismatch_reason(self, text: Any) -> str:
        cleaned = _single_line(text, 600)
        claimed_platform = self._external_share_claimed_platform(cleaned)
        if not cleaned or not claimed_platform:
            return ""
        links = re.findall(r"https?://[^\s，。！？!?；;）)】\]》>]+", cleaned, flags=re.I)
        for link in links:
            actual_platform = self._external_share_platform_from_url(link)
            if actual_platform == claimed_platform:
                continue
            try:
                hostname = str(urlparse(link).hostname or "").strip().lower()
            except Exception:
                hostname = ""
            actual_label = actual_platform or hostname or "未知域名"
            return f"正文声称来源为{claimed_platform}，但链接实际属于{actual_label}"
        return ""

    def _user_asks_ai_daily_context(self, inbound_text: str) -> bool:
        text = str(inbound_text or "").strip()
        if not text:
            return False
        if any(
            token in text
            for token in (
                "AI日报", "ai日报", "AI 日报", "ai 日报",
                "AI早报", "ai早报", "AI 早报", "ai 早报",
                "大模型日报", "大模型早报", "人工智能日报", "人工智能早报",
            )
        ):
            return True
        lowered = text.lower()
        if any(token in lowered for token in ("ai daily", "daily ai", "llm daily", "ai digest")):
            return True
        return bool(("日报" in text or "早报" in text) and re.search(r"(ai|llm|大模型|人工智能|模型)", text, flags=re.IGNORECASE))

    def _ai_daily_query_requires_freshness(self, inbound_text: str) -> bool:
        text = str(inbound_text or "").strip()
        if not text:
            return False
        return bool(re.search(r"(今天|今日|今早|刚刚|刚才|最新|现在)", text, flags=re.IGNORECASE))

    def _select_ai_daily_digest_item(self, ai_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        digest = ai_state.get("last_digest") if isinstance(ai_state.get("last_digest"), dict) else {}
        selected_item: dict[str, Any] = {}
        digest_items = digest.get("items") if isinstance(digest.get("items"), list) else []
        selected_key = _single_line(digest.get("selected_key"), 80)
        for candidate in digest_items:
            if not isinstance(candidate, dict):
                continue
            if selected_key and _single_line(candidate.get("key"), 80) == selected_key:
                selected_item = candidate
                break
        if not selected_item and digest_items and isinstance(digest_items[0], dict):
            selected_item = digest_items[0]
        return digest, selected_item

    def _user_asks_news_context(self, inbound_text: str) -> bool:
        text = str(inbound_text or "").strip()
        if not text:
            return False
        if any(token in text for token in ("新闻", "早报", "热点", "时讯", "资讯", "新消息")):
            return True
        lowered = text.lower()
        return any(token in lowered for token in ("ai news", "llm news", "daily ai", "tech news"))

    def _user_asks_web_exploration_context(self, inbound_text: str) -> bool:
        text = str(inbound_text or "").strip()
        if not text:
            return False
        if re.search(r"(主动搜索|网页探索|搜索记录|浏览记录|上网).{0,16}(什么|啥|哪|记录|看|查|搜|了解|发现)|((最近|刚才|今天|这两天|这会儿).{0,16}(搜|查|上网|浏览|了解|看了啥|看了什么|发现了什么))|你.{0,12}(搜了什么|查了什么|上网看了什么|上网看了啥|发现了什么新东西)", text):
            return True
        lowered = text.lower()
        return any(token in lowered for token in ("web exploration", "recent search", "search history", "browsing history"))

    def _format_recent_web_exploration_context_for_reply(self, inbound_text: str = "") -> str:
        if not getattr(self, "enable_web_exploration", False):
            return ""
        if not self._user_asks_web_exploration_context(inbound_text):
            return ""
        state = self.data.get("web_exploration") if isinstance(self.data.get("web_exploration"), dict) else {}
        digest = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
        notes = state.get("notes") if isinstance(state.get("notes"), list) else []
        latest_results = state.get("latest_results") if isinstance(state.get("latest_results"), list) else []
        if not digest and not notes and not latest_results:
            return (
                "【主动搜索上下文】\n"
                "用户正在询问你最近主动搜索/上网探索过什么,但当前没有可用的主动搜索记录。请自然说明自己最近还没搜到能说的东西,不要编造搜索内容。"
            )
        rows: list[str] = []
        if digest:
            rows.append(
                "最近一次搜索："
                + "｜".join(
                    part
                    for part in (
                        f"搜索词：{_single_line(digest.get('query'), 90)}" if _single_line(digest.get("query"), 90) else "",
                        f"主题：{_single_line(digest.get('topic'), 90)}" if _single_line(digest.get("topic"), 90) else "",
                        f"动机：{_single_line(digest.get('reason'), 140)}" if _single_line(digest.get("reason"), 140) else "",
                        f"笔记：{_single_line(digest.get('note'), 240)}" if _single_line(digest.get("note"), 240) else "",
                        f"来源：{_single_line(digest.get('source_title'), 120)}" if _single_line(digest.get("source_title"), 120) else "",
                    )
                    if part
                )
            )
        for item in reversed([item for item in notes if isinstance(item, dict)][-4:]):
            query = _single_line(item.get("query"), 90)
            topic = _single_line(item.get("topic"), 90)
            note = _single_line(item.get("note") or item.get("summary") or item.get("impression"), 180)
            reason = _single_line(item.get("reason"), 100)
            if query or topic or note:
                rows.append("- " + "｜".join(part for part in (f"搜索词：{query}" if query else "", topic, reason, note) if part))
        if latest_results:
            result_rows = []
            for item in latest_results[:4]:
                if not isinstance(item, dict):
                    continue
                title = _single_line(item.get("title"), 120)
                snippet = _single_line(item.get("snippet"), 160)
                if title:
                    result_rows.append("- " + "｜".join(part for part in (title, snippet) if part))
            if result_rows:
                rows.append("最近一次结果摘录：")
                rows.extend(result_rows)
        return (
            "【主动搜索上下文】\n"
            "用户正在询问你最近主动搜索/网页探索过什么。下面是真实搜索记录；回答只能基于这些内容,不要编造额外搜索、来源或结论。"
            "可以用第一人称自然概括“我刚查了/我之前搜到”,但不要说成后台系统日志。\n"
            + "\n".join(rows[:12])
        )

    def _format_recent_ai_daily_context_for_reply(self, inbound_text: str = "") -> str:
        if not self.enable_news_integration:
            return ""
        if not self._user_asks_ai_daily_context(inbound_text):
            return ""
        state = self.data.get("news_integration") if isinstance(self.data.get("news_integration"), dict) else {}
        ai_state = state.get("ai_daily") if isinstance(state.get("ai_daily"), dict) else {}
        digest, selected_item = self._select_ai_daily_digest_item(ai_state)
        record_date = _single_line(ai_state.get("last_success_date"), 20) or _single_line(ai_state.get("date"), 20)
        source_name = _single_line(ai_state.get("last_source_name"), 40)
        source_author = _single_line(ai_state.get("last_source_author"), 60)
        source_schedule = _single_line(ai_state.get("last_source_schedule"), 10)
        video_title = _single_line(ai_state.get("last_video_title"), 120)
        video_link = _single_line(ai_state.get("last_video_link"), 360)
        text_link = _single_line(ai_state.get("last_text_link"), 360)
        headline = _single_line(digest.get("headline") or digest.get("topic"), 120)
        impression = _single_line(digest.get("impression"), 220)
        read_basis = _single_line(ai_state.get("last_read_basis"), 40)
        text_readable_raw = ai_state.get("last_text_readable")
        text_readable = bool(text_readable_raw) if isinstance(text_readable_raw, bool) else bool(selected_item.get("article_readable") and selected_item.get("article_text"))
        subtitle_status = _single_line(ai_state.get("last_video_subtitle_status") or selected_item.get("video_subtitle_status"), 40)
        if not any((record_date, source_name, video_title, headline, impression, video_link, text_link)):
            return (
                "【新闻阅读上下文】\n"
                "用户正在询问 AI 日报/早报,但当前没有可用的 AI 日报记录。请直接说明最近还没读到可确认的 AI 日报,不要编造。"
            )
        today = _today_key()
        rows: list[str] = []
        if record_date:
            if record_date != today and self._ai_daily_query_requires_freshness(inbound_text):
                rows.append(f"时间说明：今天是 {today}；最近一次可用 AI 日报记录日期是 {record_date}，不是今天。")
            else:
                rows.append(f"记录日期：{record_date}")
        if source_name or source_author or source_schedule:
            rows.append("来源：" + "｜".join(part for part in (source_name, source_author, source_schedule) if part))
        if video_title:
            rows.append(f"视频标题：{video_title}")
        if headline:
            rows.append(f"摘要重点：{headline}")
        if impression:
            rows.append(f"阅读印象：{impression}")
        if read_basis:
            rows.append(f"整理依据：{read_basis}")
        if text_link:
            rows.append(f"文字版链接：{text_link}")
        elif video_link:
            rows.append(f"视频链接：{video_link}")
        rows.append(f"正文可读：{'是' if text_readable else '否'}")
        if subtitle_status:
            rows.append(f"字幕状态：{subtitle_status}")
        return (
            "【新闻阅读上下文】\n"
            "用户正在询问 AI 日报/早报。下面是最近一次真实读到的 AI 日报记录；如果日期不是今天，请明确说出具体日期，不要说成今天刚读到。"
            "回答只能基于这些内容，不要编造额外新闻。\n"
            + "\n".join(rows[:10])
        )

    def _format_recent_news_context_for_reply(self, inbound_text: str = "") -> str:
        if not self.enable_news_integration:
            return ""
        ai_daily_context = self._format_recent_ai_daily_context_for_reply(inbound_text)
        if ai_daily_context:
            return ai_daily_context
        if not self._user_asks_news_context(inbound_text):
            return ""
        state = self.data.get("news_integration") if isinstance(self.data.get("news_integration"), dict) else {}
        digest = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
        digests = state.get("digests") if isinstance(state.get("digests"), list) else []
        latest_items = state.get("latest_items") if isinstance(state.get("latest_items"), list) else []
        if not digest and not digests and not latest_items:
            return (
                "【新闻阅读上下文】\n"
                "用户正在询问今天的新闻/AI 新闻,但当前还没有可用的新闻阅读记录。请自然说明自己还没读到今天的新闻,不要编造新闻。"
            )
        rows: list[str] = []
        if digest:
            rows.append(
                "最近一次整理："
                + "｜".join(
                    part
                    for part in (
                        _single_line(digest.get("headline") or digest.get("topic"), 120),
                        _single_line(digest.get("selected_source"), 40),
                        _single_line(digest.get("impression"), 220),
                        _single_line(digest.get("selected_link"), 360),
                    )
                    if part
                )
            )
        for item in reversed([item for item in digests if isinstance(item, dict)][-4:]):
            headline = _single_line(item.get("headline") or item.get("topic"), 120)
            impression = _single_line(item.get("impression"), 180)
            source = _single_line(item.get("selected_source"), 40)
            if headline or impression:
                rows.append("- " + "｜".join(part for part in (headline, source, impression) if part))
        if latest_items:
            rows.append("候选标题：")
            for item in latest_items[:6]:
                if not isinstance(item, dict):
                    continue
                title = _single_line(item.get("title"), 120)
                source = _single_line(item.get("source"), 40)
                summary = _single_line(item.get("summary"), 160)
                if title:
                    rows.append("- " + "｜".join(part for part in (title, source, summary) if part))
        return (
            "【新闻阅读上下文】\n"
            "用户正在询问今天的新闻/AI 新闻。下面是 Bot 近期真实读过或抓到的新闻记录；回答时只能基于这些内容,不要编造额外新闻。"
            "可以按人格自然概括,如果记录不够新或不完整,要直接说明。\n"
            + "\n".join(rows[:12])
        )

    def _format_news_digest_for_command(self) -> str:
        state = self.data.get("news_integration") if isinstance(self.data.get("news_integration"), dict) else {}
        if not self.enable_news_integration:
            return "新闻阅读功能没有开启。"
        status = _single_line(state.get("last_status"), 60) or "未知"
        digest = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
        latest_items = state.get("latest_items") if isinstance(state.get("latest_items"), list) else []
        if not digest and not latest_items:
            return f"这次没有读到可用新闻。\n状态：{status}"
        lines = ["今日新闻见闻："]
        if digest:
            headline = _single_line(digest.get("headline") or digest.get("topic"), 120)
            source = _single_line(digest.get("selected_source"), 40)
            impression = _single_line(digest.get("impression"), 260)
            link = _single_line(digest.get("selected_link"), 420)
            if headline:
                lines.append(f"- 重点：{headline}")
            if source:
                lines.append(f"- 来源：{source}")
            if impression:
                lines.append(f"- 印象：{impression}")
            if link:
                lines.append(f"- 链接：{link}")
        if latest_items:
            lines.append("候选标题：")
            for item in latest_items[:6]:
                if not isinstance(item, dict):
                    continue
                title = _single_line(item.get("title"), 100)
                source = _single_line(item.get("source"), 30)
                if title:
                    lines.append(f"- {title}" + (f"（{source}）" if source else ""))
        return "\n".join(lines)

    def _format_ai_daily_digest_for_command(self) -> str:
        state = self.data.get("news_integration") if isinstance(self.data.get("news_integration"), dict) else {}
        if not self.enable_news_integration:
            return "新闻阅读功能没有开启。"
        if not self.enable_ai_daily_watch:
            return "AI 日报/早报追踪没有开启。"
        ai_state = state.get("ai_daily") if isinstance(state.get("ai_daily"), dict) else {}
        digest, selected_item = self._select_ai_daily_digest_item(ai_state)
        record_date = _single_line(ai_state.get("last_success_date"), 20) or _single_line(ai_state.get("date"), 20)
        source_name = _single_line(ai_state.get("last_source_name"), 40)
        source_author = _single_line(ai_state.get("last_source_author"), 60)
        source_schedule = _single_line(ai_state.get("last_source_schedule"), 10)
        video_title = _single_line(ai_state.get("last_video_title"), 120)
        video_link = _single_line(ai_state.get("last_video_link"), 420)
        text_link = _single_line(ai_state.get("last_text_link"), 420)
        headline = _single_line(digest.get("headline") or digest.get("topic"), 120)
        impression = _single_line(digest.get("impression"), 260)
        read_basis = _single_line(ai_state.get("last_read_basis"), 40) or ("完整文字版正文" if bool(selected_item.get("article_readable") and selected_item.get("article_text")) else "视频标题/简介")
        if not any((record_date, source_name, video_title, headline, impression, video_link, text_link)):
            status = _single_line(ai_state.get("status"), 60) or "未知"
            return f"最近还没有可用的 AI 日报记录。\n状态：{status}"
        today = _today_key()
        lines = ["最近的 AI 日报/早报："]
        if record_date:
            lines.append(f"- 日期：{record_date}")
            if record_date != today:
                lines.append(f"- 说明：今天是 {today}，最近一次成功记录不是今天。")
        if source_name or source_author or source_schedule:
            lines.append("- 来源：" + "｜".join(part for part in (source_name, source_author, source_schedule) if part))
        if video_title:
            lines.append(f"- 视频：{video_title}")
        if headline:
            lines.append(f"- 重点：{headline}")
        if impression:
            lines.append(f"- 印象：{impression}")
        if read_basis:
            lines.append(f"- 整理依据：{read_basis}")
        if text_link:
            lines.append(f"- 文字版：{text_link}")
        elif video_link:
            lines.append(f"- 视频链接：{video_link}")
        return "\n".join(lines)

    def _format_ai_daily_status_for_command(self) -> str:
        state = self.data.get("news_integration") if isinstance(self.data.get("news_integration"), dict) else {}
        ai_state = state.get("ai_daily") if isinstance(state.get("ai_daily"), dict) else {}
        status_labels = {
            "read": "已阅读",
            "waiting_schedule": "等待定时",
            "all_sources_done": "今日来源已处理",
            "waiting_window": "等待窗口",
            "checking": "正在检查",
            "waiting_today_video": "等待今日视频",
            "today_video_without_text": "今日视频暂无文字版",
            "already_read_today_video": "今日已读",
            "missed_today_ai_daily": "今日窗口已过",
            "digest_failed": "整理失败",
        }
        status = _single_line(ai_state.get("status"), 60) or "未知"
        lines = [
            "AI 日报/早报测试结果：",
            f"- 新闻集成：{'开启' if self.enable_news_integration else '关闭'}",
            f"- AI日报/早报追踪：{'开启' if self.enable_ai_daily_watch else '关闭'}",
            f"- 状态：{status_labels.get(status, status)}",
        ]
        sources = ai_state.get("sources") if isinstance(ai_state.get("sources"), list) else []
        configured_sources = str(getattr(self, "ai_daily_sources", "") or "").strip()
        if configured_sources:
            lines.append("- 来源计划：")
            for raw_line in configured_sources.splitlines()[:8]:
                parts = [part.strip() for part in raw_line.split("|")]
                if len(parts) >= 5:
                    lines.append(f"  - {parts[0]}｜{parts[1]}｜{parts[4]}｜UID {parts[2]}")
        elif sources:
            lines.append("- 来源计划：")
            for item in sources[:8]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"  - {_single_line(item.get('name'), 30)}｜{_single_line(item.get('author_name'), 40)}"
                    f"｜{_single_line(item.get('schedule'), 10)}｜UID {_single_line(item.get('mid'), 32)}"
                )
        date = _single_line(ai_state.get("date"), 20)
        checked = self._format_timestamp_elapsed(ai_state.get("last_checked_at", 0))
        success_date = _single_line(ai_state.get("last_success_date"), 20)
        title = _single_line(ai_state.get("last_video_title"), 120)
        video_link = _single_line(ai_state.get("last_video_link"), 420)
        text_link = _single_line(ai_state.get("last_text_link"), 420)
        candidate_count = _safe_int(ai_state.get("last_candidate_count"), 0, 0)
        digest, selected_item = self._select_ai_daily_digest_item(ai_state)
        if date:
            lines.append(f"- 状态日期：{date}")
        if checked:
            lines.append(f"- 最近检查：{checked}")
        if success_date:
            lines.append(f"- 最近成功日期：{success_date}")
        last_source = _single_line(ai_state.get("last_source_name"), 40)
        last_author = _single_line(ai_state.get("last_source_author"), 60)
        last_schedule = _single_line(ai_state.get("last_source_schedule"), 10)
        if last_source or last_author:
            lines.append(
                "- 最近来源："
                + "｜".join(part for part in (last_source, last_author, last_schedule) if part)
            )
        if title:
            lines.append(f"- 视频：{title}")
        if video_link:
            lines.append(f"- 视频链接：{video_link}")
        owner_name = _single_line(ai_state.get("last_video_owner_name") or selected_item.get("video_owner_name"), 80)
        tname = _single_line(ai_state.get("last_video_tname") or selected_item.get("video_tname"), 60)
        duration = _safe_int(ai_state.get("last_video_duration") or selected_item.get("video_duration"), 0, 0)
        video_context_chars = _safe_int(ai_state.get("last_video_context_chars"), 0, 0)
        if not video_context_chars and selected_item:
            video_context_chars = len(str(selected_item.get("video_context_text") or ""))
        video_tags = ai_state.get("last_video_tags") if isinstance(ai_state.get("last_video_tags"), list) else selected_item.get("video_tags")
        video_tags = [_single_line(tag, 30) for tag in video_tags if _single_line(tag, 30)] if isinstance(video_tags, list) else []
        video_comments = ai_state.get("last_video_hot_comments") if isinstance(ai_state.get("last_video_hot_comments"), list) else selected_item.get("video_hot_comments")
        video_comments = [_single_line(comment, 60) for comment in video_comments if _single_line(comment, 60)] if isinstance(video_comments, list) else []
        meta_parts = []
        if owner_name:
            meta_parts.append(f"UP主 {owner_name}")
        if tname:
            meta_parts.append(f"分区 {tname}")
        if duration:
            meta_parts.append(f"时长 {duration // 60}分{duration % 60}秒")
        if meta_parts:
            lines.append("- 视频信息：" + "｜".join(meta_parts))
        if video_context_chars:
            lines.append(f"- 视频公开信息：已读取 {video_context_chars} 字")
        if video_tags:
            lines.append(f"- 视频标签：{'、'.join(video_tags[:8])}")
        if video_comments:
            lines.append(f"- 热门评论：已读取 {len(video_comments)} 条")
        if text_link:
            lines.append(f"- 文字版链接：{text_link}")
        text_readable_raw = ai_state.get("last_text_readable")
        text_readable = bool(text_readable_raw) if isinstance(text_readable_raw, bool) else bool(selected_item.get("article_readable") and selected_item.get("article_text"))
        text_chars = _safe_int(ai_state.get("last_text_chars"), 0, 0)
        if not text_chars and selected_item:
            text_chars = len(str(selected_item.get("article_text") or ""))
        subtitle_readable_raw = ai_state.get("last_video_subtitle_readable")
        subtitle_readable = bool(subtitle_readable_raw) if isinstance(subtitle_readable_raw, bool) else bool(selected_item.get("video_subtitle_readable") and selected_item.get("video_subtitle_text"))
        subtitle_chars = _safe_int(ai_state.get("last_video_subtitle_chars"), 0, 0)
        if not subtitle_chars and selected_item:
            subtitle_chars = len(str(selected_item.get("video_subtitle_text") or ""))
        subtitle_status = _single_line(ai_state.get("last_video_subtitle_status") or selected_item.get("video_subtitle_status"), 40)
        subtitle_status_labels = {
            "read": "已读取字幕",
            "missing": "公开视频暂无字幕",
            "unavailable": "字幕不可用",
        }
        read_basis = _single_line(ai_state.get("last_read_basis"), 40) or ("完整文字版正文" if text_readable else "视频标题/简介")
        if text_link or selected_item or video_link:
            lines.append(f"- 文字版读取：{'已读取完整正文' if text_readable else '未读取到正文'}")
        if text_chars:
            lines.append(f"- 文字版正文字数：{text_chars}")
        if video_link or selected_item:
            lines.append(f"- 字幕读取：{subtitle_status_labels.get(subtitle_status, '已读取字幕' if subtitle_readable else '未读取到字幕')}")
        if subtitle_chars:
            lines.append(f"- 字幕字数：{subtitle_chars}")
        if read_basis:
            lines.append(f"- 整理依据：{read_basis}")
        if candidate_count:
            lines.append(f"- 候选数量：{candidate_count}")
        source_states = ai_state.get("source_states") if isinstance(ai_state.get("source_states"), dict) else {}
        if source_states:
            lines.append("来源状态：")
            for item in source_states.values():
                if not isinstance(item, dict):
                    continue
                source_title = _single_line(item.get("last_video_title"), 80)
                lines.append(
                    f"- {_single_line(item.get('name'), 30) or '来源'}｜{_single_line(item.get('schedule'), 10) or '未定时'}"
                    f"｜{status_labels.get(_single_line(item.get('status'), 60), _single_line(item.get('status'), 60) or '未知')}"
                    + (f"｜{source_title}" if source_title else "")
                )
        if digest:
            headline = _single_line(digest.get("headline") or digest.get("topic"), 120)
            impression = _single_line(digest.get("impression"), 220)
            if headline:
                lines.append(f"- 摘要重点：{headline}")
            if impression:
                lines.append(f"- 阅读印象：{impression}")
        candidates = ai_state.get("last_candidates") if isinstance(ai_state.get("last_candidates"), list) else []
        if candidates:
            lines.append("最近候选：")
            for item in candidates[:5]:
                if not isinstance(item, dict):
                    continue
                title_line = _single_line(item.get("title"), 90) or "未命名"
                published = _single_line(item.get("published"), 24) or "无发布时间"
                today_mark = "今天" if item.get("is_today") else "非今天"
                lines.append(f"- [{today_mark}] {published}｜{title_line}")
        if not self.enable_news_integration:
            lines.append("提示：新闻集成关闭时不会执行抓取。")
        elif not self.enable_ai_daily_watch:
            lines.append("提示：AI 日报/早报追踪关闭时不会执行抓取。")
        return "\n".join(lines)

    def _format_creative_share_action_context(self, user: dict[str, Any]) -> str:
        creative = user.get("creative_share_context")
        if not isinstance(creative, dict):
            return ""
        if _now_ts() - _safe_float(creative.get("created_ts"), 0) > 8 * 3600:
            return ""
        title = _single_line(creative.get("title"), 50)
        work_type = _single_line(creative.get("work_type"), 30) or "作品"
        premise = _single_line(creative.get("premise"), 140)
        tone = _single_line(creative.get("tone"), 40)
        source = _single_line(creative.get("source"), 120)
        snippet = _single_line(creative.get("snippet"), 260)
        current_chars = _safe_int(creative.get("current_chars"), 0, 0)
        target_chars = _safe_int(creative.get("target_chars"), 0, 0)
        parts = [
            "创作分享线索",
            f"作品类型：{work_type}" if work_type else "",
            f"标题：{title}" if title else "",
            f"设定：{premise}" if premise else "",
            f"灵感来源：{source}" if source else "",
            f"行文气质：{tone}" if tone else "",
            f"披露类型：{_single_line(creative.get('disclosure_kind'), 30) or 'milestone'}",
            f"节点：{_single_line(creative.get('milestone'), 30)}" if creative.get("milestone") else "",
            f"当前进度：约 {current_chars}/{target_chars} 字" if current_chars and target_chars else "",
            f"刚写到的片段：{snippet}" if snippet else "",
        ]
        return "\n".join(part for part in parts if part)

    async def _narrate_action_context(self, action: str, action_context: str) -> str:
        if not self.narration_provider_id:
            return self._sanitize_action_context_text(action, action_context)
        if action in {"message", "photo_text", "poke", "voice"} or "photo_text" in action or "voice" in action or "poke" in action or not action_context:
            return self._sanitize_action_context_text(action, action_context)
        cleaned_context = self._sanitize_action_context_text(action, action_context)
        terms = self._worldview_terms()
        worldview_adaptation = self._format_worldview_adaptation_prompt()
        prompt = f"""
请把下面的{terms['screen']}观察结果转成“视觉识别后的内部摘要”,供角色继续私聊使用。
要求：
1. 只描述视觉上看出来的内容,不要猜测工具调用过程,不要输出工具名、action 名、报错栈。
2. 只概括用户大概正在看什么、做什么、情绪上是否像在忙,不要复述完整文字、账号、聊天原文、隐私细节。
3. 绝对不要直接对用户说话,不要安慰、提醒、陪伴、劝休息,不要写成一条完整回复。
4. 要像看了一眼{terms['screen']}后留在脑子里的印象,不要写成建议列表。
5. 50 字以内,只输出摘要本身。

{worldview_adaptation}

原始结果：
{cleaned_context}
""".strip()
        text = await self._llm_call(
            prompt,
            max_tokens=80,
            provider_id=self.narration_provider_id,
            task="screen_narration",
        )
        return _single_line(text, 120) if text else cleaned_context

    def _sanitize_action_context_text(self, action: str, action_context: str) -> str:
        text = str(action_context or "").strip()
        if "screen_peek" not in action:
            return text
        text = re.sub(r"^screen_peek[:：]\s*", "", text).strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        cleaned_lines = []
        for line in lines:
            if re.search(r"(我会一直在这里陪着你|要注意休息|记得休息|辛苦|别太累|我会陪着你)", line):
                continue
            line = re.sub(r"^(?:还在|你还在|感觉|看起来)", "", line).strip(",。！？ ")
            cleaned_lines.append(line)
        collapsed = ",".join(line for line in cleaned_lines if line)
        collapsed = collapsed.replace("用户", "")
        collapsed = re.sub(r"\s+", " ", collapsed).strip(",。！？ ")
        if not collapsed:
            collapsed = lines[0]
        return _single_line(collapsed, 140)

    def _format_state_for_framework_prompt(self, state: dict[str, Any], *, reason: str, action: str) -> str:
        if not isinstance(state, dict):
            return "只作为语气底色：整体平稳,不要在正文里汇报状态。"
        parts: list[str] = []
        energy = _safe_int(state.get("energy"), 70, 0, 100)
        mood = _single_line(state.get("mood_bias"), 20)
        weather = _single_line(state.get("weather"), 40)
        conditions = state.get("conditions")
        meaningful_conditions: list[str] = []
        if isinstance(conditions, list):
            for cond in conditions:
                if not isinstance(cond, dict):
                    continue
                if not self._should_show_condition(cond):
                    continue
                label = _single_line(cond.get("label") or cond.get("kind"), 16)
                text = _single_line(cond.get("text"), 28)
                if label and text:
                    meaningful_conditions.append(f"{label}/{text}")
        if meaningful_conditions:
            parts.append(
                "语气里带一点"
                + "、".join(meaningful_conditions[:2])
                + "的影响,但不要主动解释这些状态。"
            )
        elif energy <= 42:
            parts.append("语气短一点、慢一点；不要直接说状态标签、数值或内部原因。")
        elif energy >= 85:
            parts.append("语气可以轻快一点,但不要直接说自己精神很好。")
        elif mood and mood not in {"平稳", "中性"}:
            parts.append(f"语气底色偏{mood},让它自然露出来,不要直接汇报情绪。")
        if "photo_text" in action or reason in {"activity_share", "diary_share", "evening_greeting", "morning_greeting"}:
            if weather and weather not in {"暂无天气信息"}:
                parts.append(f"天气只作为画面感参考：{weather}。不要像播报天气一样说出来。")
        parts.append(
            "状态只影响语气、用词、句子长短、是否开口和话题选择；不要为了表现状态而写动作小剧场。"
        )
        parts.append(
            "如果一句话已经问候、关心或递出了具体片段,可以直接停住；不用为了显得日常,在后半句补“我刚才在发呆/躺着/盯天花板”这类状态汇报。"
        )
        parts.append(
            "即使状态是困倦、迷糊、半梦半醒或低能量,也只能让语气更轻更慢；不能降低理解质量、事实判断或正常承接能力。"
        )
        parts.append(
            "不要直接宣告“我累了/我吓到了/我在写作业”,也不要用“茶差点打翻/笔帽掉了/喝水呛到”这类动作表演状态。确实要表达时只用最短口语,如“困了”“别说了”。"
        )
        return "；".join(parts) if parts else "只作为语气底色：整体平稳,不要在正文里汇报状态。"

    def _format_plan_item_for_framework_prompt(self, item: dict[str, Any] | None) -> str:
        if not isinstance(item, dict):
            return ""
        activity = _single_line(item.get("activity"), 60)
        mood = _single_line(item.get("mood"), 12)
        time_text = _single_line(item.get("time"), 12)
        if activity:
            activity = re.sub(r"[,、]?\s*想起了[^,。]+", "", activity).strip(",。 ")
            activity = re.sub(r"[,、]?\s*突然想到[^,。]+", "", activity).strip(",。 ")
        parts = []
        if time_text:
            parts.append(time_text)
        if activity:
            parts.append(activity)
        if mood and mood not in {"平稳", "中性"}:
            parts.append(f"情绪偏{mood}")
        return "｜".join(parts)

    def _nearby_plan_items(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = plan if isinstance(plan, dict) else self._native_daily_plan_view({})
        if not isinstance(plan, dict) or not self._is_plan_date_active(plan.get("date")):
            return {}
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            return {}
        now_minutes = self._effective_plan_now_minutes(str(plan.get("date") or ""))
        if now_minutes is None:
            return {}
        parsed: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            minute = self._parse_hhmm_to_minutes(item.get("time"))
            if minute is None:
                continue
            parsed.append((minute, item))
        if not parsed:
            return {}
        parsed.sort(key=lambda pair: pair[0])
        previous: tuple[int, dict[str, Any]] | None = None
        upcoming: tuple[int, dict[str, Any]] | None = None
        for minute, item in parsed:
            if minute <= now_minutes:
                previous = (minute, item)
                continue
            upcoming = (minute, item)
            break
        return {
            "now_minutes": now_minutes,
            "previous": previous[1] if previous else None,
            "previous_age": now_minutes - previous[0] if previous else None,
            "upcoming": upcoming[1] if upcoming else None,
            "upcoming_in": upcoming[0] - now_minutes if upcoming else None,
        }

    def _format_schedule_context_for_prompt(self, plan: dict[str, Any] | None = None) -> str:
        nearby = self._nearby_plan_items(plan)
        if not nearby:
            return ""
        previous = nearby.get("previous")
        upcoming = nearby.get("upcoming")
        previous_age = nearby.get("previous_age")
        upcoming_in = nearby.get("upcoming_in")
        lines: list[str] = []
        if isinstance(upcoming, dict) and isinstance(upcoming_in, int) and 0 <= upcoming_in <= 45:
            lines.append(
                "即将进入："
                + self._format_plan_item_for_prompt(upcoming)
                + f"（约 {upcoming_in} 分钟后）"
            )
            if isinstance(previous, dict) and isinstance(previous_age, int) and previous_age <= 90:
                prev_mood = _single_line(previous.get("mood"), 24)
                prev_time = _single_line(previous.get("time"), 12)
                lines.append(
                    f"上一段只作余味：{prev_time}"
                    + (f"｜情绪：{prev_mood}" if prev_mood else "")
                    + "。不要把上一段当成正在发生。"
                )
        elif isinstance(previous, dict) and isinstance(previous_age, int) and previous_age <= 75:
            lines.append(
                "当前/最近："
                + self._format_plan_item_for_prompt(previous)
                + f"（约 {previous_age} 分钟前开始）"
            )
            if isinstance(upcoming, dict) and isinstance(upcoming_in, int):
                lines.append(
                    "下一段参考："
                    + self._format_plan_item_for_prompt(upcoming)
                    + f"（约 {upcoming_in} 分钟后）"
                )
        elif isinstance(upcoming, dict) and isinstance(upcoming_in, int):
            lines.append(
                "附近更应参考下一段："
                + self._format_plan_item_for_prompt(upcoming)
                + f"（约 {upcoming_in} 分钟后）"
            )
            if isinstance(previous, dict):
                lines.append("上一段已经过去较久,只保留很淡的情绪余味,不要复述场景。")
        elif isinstance(previous, dict):
            lines.append(
                "最近一段："
                + self._format_plan_item_for_prompt(previous)
                + "。如果离当前时间较久,只当作余味。"
            )
        return "\n".join(line for line in lines if line)

    def _sanitize_schedule_context_for_private_user(self, text: str, user: dict[str, Any] | None = None) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if self._private_user_role(user) != "friend":
            return cleaned
        cleaned = self._sanitize_owner_environment_context_for_private_user(cleaned, user)
        sensitive_names = [
            _single_line(item, 24)
            for item in (
                getattr(self, "default_nickname", ""),
                *(getattr(self, "target_user_ids", []) or []),
            )
            if _single_line(item, 24)
        ]
        for name in sensitive_names:
            cleaned = cleaned.replace(name, "某个熟人")
        cleaned = re.sub(r"看见[^，。,；;。！？]{1,24}坐在[^，。,；;。！？]{0,24}", "看见有人在忙", cleaned)
        cleaned = re.sub(r"(?:放在|放到|搁在|塞到)[^，。,；;。！？]{0,12}(?:桌边|桌上|手边|旁边)", "放到一边", cleaned)
        cleaned = re.sub(r"给你[^，。,；;。！？]{0,24}", "给熟人留了一点小东西", cleaned)
        cleaned = re.sub(r"你(?:的|那边|桌边|桌上|手边)", "对方那边", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _sanitize_owner_environment_context_for_private_user(self, text: str, user: dict[str, Any] | None = None) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if self._private_user_role(user) != "friend":
            return cleaned
        weather_tokens = (
            "天气", "气温", "温度", "湿度", "降雨", "下雨", "阵雨", "小雨", "中雨", "大雨",
            "暴雨", "雷雨", "雷暴", "晴", "多云", "阴天", "风速", "风力", "空气质量", "OpenWeather",
        )
        location_tokens = (
            "当前位置", "当前地点", "所在地", "所在城市", "住处", "住址", "地址", "城市", "小区",
            "街道", "门牌", "宿舍", "校区", "位置：", "地点：", "外面在",
        )
        kept: list[str] = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if any(token in line for token in weather_tokens) or any(token in line for token in location_tokens):
                continue
            line = re.sub(r"身处(?:家里|学校|工作地点|外面|路上)[，,；;、]?", "", line)
            line = re.sub(r"(?:家里|学校|工作地点|外面|路上)[（(][^）)]{1,40}[）)]", r"", line)
            if line.strip():
                kept.append(line.strip())
        cleaned = "\n".join(kept).strip()
        cleaned = re.sub(r"天气[^。！？\n]{0,80}[。！？]?", "", cleaned)
        cleaned = re.sub(r"(?:当前位置|当前地点|所在地|所在城市|住处|住址|地址)[^。！？\n]{0,80}[。！？]?", "", cleaned)
        cleaned = re.sub(r"身处(?:家里|学校|工作地点|外面|路上)[，,；;、]?", "", cleaned)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _current_time_period_label(self, now: datetime | None = None) -> tuple[str, str]:
        current = now or self._environment_now()
        minute = current.hour * 60 + current.minute
        periods = [
            (0, 5 * 60, "深夜", "除非已有失眠或夜聊上下文,不要显得精神过满。"),
            (5 * 60, 7 * 60 + 30, "清晨", "适合很轻的醒来感,不要写成已经忙完一上午。"),
            (7 * 60 + 30, 10 * 60 + 30, "早晨", "可以有起床、出门、刚开始一天的余味。"),
            (10 * 60 + 30, 11 * 60 + 45, "上午后段", "还不是午休,不要提前写成吃午饭或午睡。"),
            (11 * 60 + 45, 13 * 60 + 30, "中午", "可以有吃东西、犯困、午间松下来,不要写成刚起床。"),
            (13 * 60 + 30, 17 * 60 + 30, "下午", "适合课间、工作间隙、犯困或缓慢推进。"),
            (17 * 60 + 30, 19 * 60 + 30, "傍晚", "适合收尾、路上、回家、天色变暗的生活感。"),
            (19 * 60 + 30, 22 * 60 + 30, "晚上", "适合放慢、写作业、休息或一点点夜里的黏人感。"),
            (22 * 60 + 30, 24 * 60, "深夜前段", "适合安静收声,不要写成白天刚开始。"),
        ]
        for start, end, label, guard in periods:
            if start <= minute < end:
                return label, guard
        return "当前时段", "贴着当前时间开口,不要跳到明显不属于此刻的生活场景。"

    def _format_time_period_injection(self) -> str:
        current = self._environment_now()
        label, guard = self._current_time_period_label(current)
        weekday = "一二三四五六日"[current.weekday()]
        return (
            f"当前时间：{current.strftime('%Y-%m-%d %H:%M')}（周{weekday}，{label}）。\n"
            f"使用方式：这只用于判断生活节奏和措辞,不要主动报时、报日期或解释时段。\n"
            f"时段边界：{guard}"
        )

    def _format_proactive_relationship_fact(self, user: dict[str, Any]) -> str:
        role = self._private_user_role(user) if isinstance(user, dict) else "owner"
        labeler = getattr(self, "_private_user_role_label", None)
        label = labeler(role) if callable(labeler) else ("主要用户" if role == "owner" else "次要用户")
        profile = self._relationship_profile(user if isinstance(user, dict) else {})
        level = _single_line(profile.get("level"), 20) or "熟悉"
        preference = _single_line(profile.get("preference"), 20) or "普通"
        note = _single_line(user.get("proactive_boundary_note"), 80) if isinstance(user, dict) else ""
        parts = [f"当前用户角色：{label}", f"关系熟悉度：{level}", f"互动偏好：{preference}"]
        if note:
            parts.append(f"用户级备注：{note}")
        return "；".join(parts)

    @staticmethod
    def _normalize_proactive_address_token(value: Any) -> str:
        token = _single_line(value, 24).strip(" -*`_【】[]（）()<>《》\"'“”‘’")
        token = re.sub(r"^[：:]+|[：:，,。.!！?？~～…]+$", "", token).strip()
        return token

    def _proactive_recipient_allowed_names(self, user: dict[str, Any] | None, name: str = "") -> list[str]:
        if not isinstance(user, dict):
            user = {}
        raw_names: list[Any] = [
            name,
            user.get("nickname"),
            user.get("last_display_name"),
            user.get("display_name"),
        ]
        for key in ("observed_display_names", "aliases"):
            values = user.get(key)
            if isinstance(values, list):
                raw_names.extend(values[:12])
        names: list[str] = []
        for value in raw_names:
            token = self._normalize_proactive_address_token(value)
            if token and not token.isdigit() and token not in names:
                names.append(token)
        return names[:16]

    def _proactive_persona_address_candidates(self) -> list[str]:
        sources = [
            str(getattr(self, "persona_proactive_voice_prompt", "") or ""),
            str(getattr(self, "persona_conversation_voice_prompt", "") or ""),
        ]
        try:
            sources.append(str(self._get_default_persona_prompt() or ""))
        except Exception:
            pass
        patterns = (
            r"(?:开头常用|常用开头|常用称呼|专属称呼|称呼偏好)\s*[:：]\s*([^\n]{1,100})",
            r"(?:特定用户|主要用户|专属用户)\s*[（(]\s*([^）)\n]{1,100})[）)]",
        )
        fillers = {
            "哦", "嗯", "唔", "诶", "欸", "啊", "嗨", "嘿", "喂", "哈哈", "早安", "晚安",
            "你", "您", "对方", "用户", "昵称", "名字", "无", "暂无", "无固定称呼",
        }
        candidates: list[str] = []
        for source in sources:
            for pattern in patterns:
                for match in re.finditer(pattern, source, flags=re.IGNORECASE):
                    for part in re.split(r"[/／、,，;；|]", match.group(1)):
                        token = self._normalize_proactive_address_token(part)
                        if (
                            2 <= len(token) <= 16
                            and token not in fillers
                            and not any(word in token for word in ("开头", "称呼", "用户", "例如", "比如", "可用"))
                            and token not in candidates
                        ):
                            candidates.append(token)
        return candidates[:24]

    def _proactive_forbidden_recipient_addresses(self, user: dict[str, Any] | None, name: str = "") -> list[str]:
        if not isinstance(user, dict) or self._private_user_role(user) != "friend":
            return []
        allowed = self._proactive_recipient_allowed_names(user, name)
        forbidden: list[str] = []
        for candidate in self._proactive_persona_address_candidates():
            if any(candidate == item or candidate in item or item in candidate for item in allowed):
                continue
            forbidden.append(candidate)
        return forbidden

    def _format_proactive_recipient_identity_guard(self, user: dict[str, Any] | None, name: str = "") -> str:
        if not isinstance(user, dict):
            return ""
        role = self._private_user_role(user)
        labeler = getattr(self, "_private_user_role_label", None)
        role_label = labeler(role) if callable(labeler) else ("主要用户" if role == "owner" else "次要用户")
        user_id = _single_line(user.get("user_id") or user.get("id"), 48)
        allowed = self._proactive_recipient_allowed_names(user, name)
        forbidden = self._proactive_forbidden_recipient_addresses(user, name)
        lines = [
            "【当前主动消息收件人身份锚点】",
            f"- 稳定 ID：{user_id or '未知'}；关系角色：{role_label}。",
            f"- 当前对象可用称呼：{'、'.join(allowed) if allowed else '优先直接用“你”，不要猜名字'}。",
            "- 显示名只能作为当前稳定 ID 的别名，不能把其他私聊对象的关系、称呼或记忆套进来。",
        ]
        if role == "friend":
            lines.append("- 当前对象不是主要用户/恋人/专属陪伴目标；全局人格与主动风格里的固定人名只作语气示例，不要直接拿来称呼当前对象。")
            if forbidden:
                lines.append(f"- 这些固定称呼不属于当前对象：{'、'.join(forbidden)}。需要称呼时使用上面的当前昵称，也可以自然省略称呼。")
        else:
            lines.append("- 如果人格明确规定了对主要用户的专属称呼，优先遵循该称呼；不要把当前显示名自行拼接后缀来发明新称呼。")
        boundary_getter = getattr(self, "_format_private_user_boundary_hint", None)
        if callable(boundary_getter):
            try:
                boundary = str(boundary_getter(user) or "").strip()
            except Exception:
                boundary = ""
            if boundary:
                lines.append(boundary)
        return "\n".join(lines)

    async def _resolve_proactive_persona_prompt(self, user: dict[str, Any] | None = None, *, umo: str = "") -> str:
        session = str(umo or (user.get("umo") if isinstance(user, dict) else "") or "").strip()
        refresher = getattr(self, "_refresh_default_persona_prompt", None)
        if callable(refresher):
            try:
                resolved = await refresher(session)
                text = str(resolved or "").strip()
                if text:
                    return text
            except Exception as exc:
                logger.debug("[PrivateCompanion] 主动链解析会话人格失败: session=%s error=%s", _single_line(session, 100), _single_line(exc, 120))
        getter = getattr(self, "_get_default_persona_prompt", None)
        if callable(getter):
            try:
                return str(getter(session) or "").strip()
            except TypeError:
                return str(getter() or "").strip()
            except Exception:
                pass
        return ""

    def _wrong_proactive_recipient_address(self, text: Any, user: dict[str, Any] | None, name: str = "") -> str:
        cleaned = _single_line(text, 600)
        if not cleaned:
            return ""
        for address in self._proactive_forbidden_recipient_addresses(user, name):
            if not address:
                continue
            direct_address_pattern = (
                rf"(?:^|[\n，,。.!！?？~～]\s*)"
                rf"{re.escape(address)}"
                rf"(?=$|[\s，,、：:。.!！?？~～])"
            )
            if re.search(direct_address_pattern, cleaned):
                return address
        return ""

    def _repair_proactive_recipient_address(
        self,
        text: str,
        user: dict[str, Any] | None,
        name: str = "",
    ) -> tuple[str, str]:
        cleaned = str(text or "").strip()
        wrong = self._wrong_proactive_recipient_address(cleaned, user, name)
        if not wrong:
            return cleaned, ""
        allowed = self._proactive_recipient_allowed_names(user, name)
        replacement = allowed[0] if allowed else "你"
        pattern = (
            rf"(^|[\n，,。.!！?？~～]\s*)"
            rf"{re.escape(wrong)}"
            rf"(?=$|[\s，,、：:。.!！?？~～])"
        )
        repaired, count = re.subn(pattern, lambda match: f"{match.group(1)}{replacement}", cleaned, count=1)
        return (repaired, wrong) if count else (cleaned, "")

    def _default_proactive_prompt_template(self) -> str:
        return """
你正在给 {{name}} 发一条主动私聊。这不是回复刚收到的新消息，也不是任务说明、状态汇报或例行打卡。

【这次可以使用的线索】
当前时间：{{current_time}}。{{unanswered_hint}}
开口动机：{{motive}}。话题方向：{{topic}}。刚发生或看到的事：{{action_context}}。
此刻状态：{{state_hint}}。生活片段（只作叙事背景，不等同于已执行事实）：{{current_schedule}}。时段边界：{{time_guard}}。
最近已经主动聊过：{{recent_topics}}。关系事实：{{relationship_fact}}。
{{timer_hint}}

【先判断，再开口】
- 从线索中只选一个此刻最真实、最具体、最值得说的切口；无关线索直接忽略。
- 开口动机是内部决策依据，不是你要说出口的话；不要照抄动机里的措辞，用你自己的方式开口。
- 有明确的人、事、画面或感受时，就贴着它说；不要把多个来源拼成一段“近况播报”。
- 日程、状态和记忆只能帮助确定语气与话题，不可单独证明某个动作已经完成；只有本轮真实动作结果可以支撑具体的已发生陈述。
- 线索偏弱、对方尚未回复或时段不适合展开时，把话说得更轻：可以分享、留白或自然收住，但不追问、不催回应、不索取陪伴。
- 不要凭空补事实，不要把旧事写成刚刚发生；不要为了主动而主动。

【成文方式】
- 像角色在聊天窗口里自然想到后说出的一小句，而不是客服关怀、情绪鸡汤、日记、总结、推荐文或任务汇报。
- 口语、具体、有一点个人温度；少解释，不复述上下文，不列清单，不使用“检测到/根据/安排/提醒你”等系统或管理口吻。
- 如果想关心对方，用能自然接住的话表达，不把“在吗”“忙不忙”“怎么不回”“记得回复”当作开场。
- 一两句即可；一个画面、一点感受或一个轻问题已经足够。说完就停，不追加自我解释或结尾客套。

最终文本会直接成为聊天窗口里的下一句话。只输出要发出的正文，不要标题、引号、前缀、分析或说明。不写动作描写、旁白、括号舞台动作；不使用（）括号包裹动作或场景描写；只输出角色真正说出口的话。。
""".strip()

    def _proactive_natural_delivery_hint(self) -> str:
        return (
            "【自然交付提醒】\n"
            "这一轮的最终文本会成为对话里的下一句。"
            "请把注意力放在这句聊天内容本身，像平时主动开口那样自然收住；"
            "过程中的执行状态只供系统判断，不需要写进正文。"
        )

    def _deferred_immediate_share_tense_hint(self, user: dict[str, Any], action: str) -> str:
        freshness_getter = getattr(self, "_planned_proactive_freshness_class", None)
        if not callable(freshness_getter):
            return ""
        try:
            if freshness_getter(user) != "immediate":
                return ""
        except Exception:
            return ""
        if _single_line(user.get("planned_proactive_delivery_state"), 24) != "deferred":
            return ""
        return (
            "【延后分享的时态】\n"
            "这段生活分享发生在稍早一些的时候，但仍在自然分享窗口内。正文要用已经发生的说法，"
            "不要暗示拍摄或事件与发送处于同一时刻，也不要提延后、等待、系统或调度。"
        )

    async def _build_framework_proactive_prompt(
        self,
        *,
        user: dict[str, Any],
        name: str,
        reason: str,
        action: str,
        action_context: str,
        motive: str,
    ) -> str:
        relationship_sanitizer = getattr(self, "_sanitize_generation_relationship_context", None)

        def sanitize_relationship_source(value: Any, source: str) -> str:
            if callable(relationship_sanitizer):
                try:
                    return relationship_sanitizer(value, source=source)
                except Exception:
                    pass
            return str(value or "").strip()

        state = self.data.get("daily_state", {})
        action_prompt_context = sanitize_relationship_source(
            self._format_action_prompt_context(action, action_context),
            "proactive.action_context",
        )
        relationship_fact = self._format_proactive_relationship_fact(user)
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        current_schedule = self._format_schedule_context_for_prompt() or self._format_plan_item_for_prompt(current_item)
        source_focused_reasons = {
            "bili_video_share",
            "news_share",
            "web_exploration_share",
            "creative_share",
            "jm_cosmos_share",
            "jm_cosmos_recommendation_request",
        }
        if reason in source_focused_reasons:
            current_schedule = "（本轮不取生活片段，只围绕主动来源本身）"
        elif reason in {"meal_care", "meal_care_followup"}:
            current_schedule = (
                "（饭点关心只使用当前时间、饭点和本轮动机；"
                "不引用模拟日程中的具体动作、见闻、message_seed 或旧饮食记录）"
            )
        elif reason == "group_share":
            last_sidecar_at = _safe_float(user.get("last_group_share_life_sidecar_at"), 0)
            if last_sidecar_at > 0 and _now_ts() - last_sidecar_at < 6 * 3600:
                current_schedule = "（最近群分享已经顺手带过生活片段，本轮只围绕群里那件事）"
        state_hint = self._format_state_for_framework_prompt(
            state if isinstance(state, dict) else {},
            reason=reason,
            action=action,
        )
        state_hint = self._sanitize_owner_environment_context_for_private_user(state_hint, user)
        state_hint = sanitize_relationship_source(state_hint, "proactive.current_state")
        timer_hint = self._format_llm_timer_context(user)
        time_guard = self._proactive_time_guard_hint(reason, current_item)
        deferred_share_tense_hint = self._deferred_immediate_share_tense_hint(user, action)
        recent_topics_hint = self._format_recent_proactive_topics_hint(user)
        # Search for unresolved open-loop / promise memories from the memory plugin
        open_loops_hint = ""
        try:
            umo = str(user.get("umo") or "").strip()
            if umo:
                open_loops = await self._memory_companion_search_open_loops(session_id=umo, limit=2)
                if open_loops:
                    loop_texts = []
                    for loop in open_loops[:2]:
                        content_preview = _single_line(
                            sanitize_relationship_source(
                                loop.get("content"),
                                "proactive.open_loop",
                            ),
                            80,
                        )
                        if not content_preview:
                            continue
                        age = loop.get("age_days")
                        age_str = f"（{age:.0f}天前）" if age is not None else ""
                        loop_texts.append(f"- {content_preview}{age_str}")
                    open_loops_hint = (
                        "【未完成话题候选】\n"
                        "这些只是可选候选，不是必须提起的任务。只有当本轮主动动机、当前话题或最近私聊比较贴合，"
                        "或者你本来就是想兑现这件事时，才轻轻带一句；如果不贴，就先放着，不必为了它改变本轮话题。\n"
                        + "\n".join(loop_texts)
                    )
        except Exception:
            pass
        current_schedule = self._sanitize_schedule_context_for_private_user(current_schedule, user)
        current_schedule = sanitize_relationship_source(current_schedule, "proactive.current_schedule")
        compact_motive = _single_line(
            sanitize_relationship_source(motive, "proactive.planned_motive"),
            36,
        ) or "有一点想靠近对方"
        topic_hint = _single_line(
            sanitize_relationship_source(
                user.get("planned_proactive_topic"),
                "proactive.planned_topic",
            ),
            40,
        )
        unanswered_count = _safe_int(user.get("ignored_streak"), 0)
        unanswered_hint = f"这是第 {unanswered_count} 次主动后还没等到回复。" if unanswered_count > 0 else ""
        current_time = self._environment_now().strftime("%Y-%m-%d %H:%M")
        persona = await self._resolve_proactive_persona_prompt(user)
        recent_history_hint = ""
        try:
            recent_history_hint = await self._recent_private_conversation_for_proactive_review(user, limit=5)
        except Exception:
            recent_history_hint = ""
        recent_history_hint = sanitize_relationship_source(
            recent_history_hint,
            "proactive.recent_private_history",
        )
        recent_topics_hint = sanitize_relationship_source(
            recent_topics_hint,
            "proactive.recent_topics",
        )
        temporal_grounding_hint = (
            "【时间锚定】\n"
            f"- 当前真实时间：{current_time}。\n"
            "- 优先贴今天最新私聊、当前日程和当前时段；旧记忆只能作背景，不要改写成今天/现在正在发生。\n"
            "- 如果记忆或历史里是昨天、昨晚、之前的天气/通勤/身体状态，除非当前日程或最新私聊明确延续，否则不要拿来当本轮主动切口。\n"
            "- 如果必须提旧事，要明确说“昨晚/昨天/那次”，不要写成“今天刚遇到/现在还在/刚才发生”。"
        )
        prompt = self.proactive_prompt_template or self._default_proactive_prompt_template()
        worldview_adaptation = ""
        reason_text = _REASON_TEXT.get(reason, reason).replace("{name}", name)
        action_text = _ACTION_TEXT.get(action.split("+")[0], action).replace("{name}", name)
        replacements = {
            "{{name}}": name,
            "{{reason}}": reason_text,
            "{{action}}": action_text,
            "{{topic}}": topic_hint or "顺手递过来的一点东西",
            "{{motive}}": compact_motive,
            "{{style_hint}}": relationship_fact,
            "{{relationship_fact}}": relationship_fact,
            "{{state_hint}}": state_hint or "今天整体比较平稳。",
            "{{current_schedule}}": current_schedule if current_schedule and current_schedule != "（暂无）" else "（当前没有明确日程片段）",
            "{{time_guard}}": time_guard,
            "{{recent_topics}}": recent_topics_hint or "（无）",
            "{{content_options}}": "",
            "{{content_anchor}}": "",
            "{{ability_search}}": "",
            "{{action_boundary}}": "",
            "{{worldview_adaptation}}": worldview_adaptation,
            "{{timer_hint}}": timer_hint or "",
            "{{action_context}}": action_prompt_context if action_prompt_context and action_prompt_context != "（无额外上下文）" else "什么都没做,就是忽然想来找你",
            "{{unanswered_count}}": str(unanswered_count) if unanswered_count > 0 else "",
            "{{unanswered_hint}}": unanswered_hint,
            "{{open_loops_hint}}": open_loops_hint,
            "{{current_time}}": current_time,
        }
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)
        persona_marker = "<!-- private_companion_proactive_persona_v1 -->"
        if persona and persona_marker not in prompt:
            prompt = (
                f"{prompt.rstrip()}\n\n{persona_marker}\n"
                "【当前主动消息必须遵循的人格】\n"
                f"{persona[:2600]}\n"
                "这份人格约束最终说话者的身份、性格、关系站位、称呼和措辞。"
                "日程、记忆、主动动机及工具结果只能提供本轮内容，不能覆盖或改写人格。"
            )
        proactive_voice = self._format_proactive_voice_prompt() if callable(getattr(self, "_format_proactive_voice_prompt", None)) else ""
        proactive_voice_marker = "<!-- private_companion_proactive_voice_v1 -->"
        if proactive_voice and proactive_voice_marker not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{proactive_voice_marker}\n{proactive_voice}"
        expression_formatter = getattr(self, "_format_expression_voice_for_prompt", None)
        expression_voice = (
            expression_formatter(
                scope="proactive",
                target_id=_single_line(user.get("user_id") or user.get("id"), 80),
                context_owner=user,
                stage_owner=user,
            )
            if callable(expression_formatter)
            else ""
        )
        expression_voice_marker = "<!-- private_companion_expression_voice_v1 -->"
        if expression_voice and expression_voice_marker not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{expression_voice_marker}\n{expression_voice}"
        delivery_hint = self._proactive_natural_delivery_hint()
        if delivery_hint and "自然交付提醒" not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{delivery_hint}"
        if deferred_share_tense_hint and "延后分享的时态" not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{deferred_share_tense_hint}"
        tool_boundary_hint = (
            "【主动生成工具边界】\n"
            "- 这一轮只生成要发给当前私聊对象的一句正文，不调用任何转述、私聊发送、群发、QQ空间或生图发送工具。\n"
            "- 不要写“已发送/已转述/消息已发给某人/工具执行完成”等状态回执。\n"
            "- 如果想分享一件事，就直接把那句自然聊天内容写出来。"
        )
        if "主动生成工具边界" not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{tool_boundary_hint}"
        if "时间锚定" not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{temporal_grounding_hint}"
        if recent_history_hint and "最近私聊实况" not in prompt:
            prompt = (
                f"{prompt.rstrip()}\n\n"
                "【最近私聊实况】\n"
                f"{recent_history_hint}\n"
                "使用方式：这是当前会话最近真实发生的内容。它优先级高于旧记忆；不要把更早的记录写成今天刚发生。"
            )
        balance_hint_getter = getattr(self, "_format_balance_awareness_prompt", None)
        if callable(balance_hint_getter):
            balance_hint = balance_hint_getter(user, reason=reason)
            if balance_hint:
                balance_hint = sanitize_relationship_source(balance_hint, "proactive.balance_hint")
                if balance_hint:
                    prompt = f"{prompt.rstrip()}\n\n{balance_hint}"
        environment_hint_getter = getattr(self, "_format_environment_change_prompt", None)
        if callable(environment_hint_getter):
            environment_hint = environment_hint_getter(user, reason=reason)
            if environment_hint:
                environment_hint = sanitize_relationship_source(environment_hint, "proactive.environment_hint")
                if environment_hint:
                    prompt = f"{prompt.rstrip()}\n\n{environment_hint}"
        personal_goal_hint_getter = getattr(self, "_format_personal_goal_prompt", None)
        if callable(personal_goal_hint_getter):
            personal_goal_hint = personal_goal_hint_getter(user, reason=reason)
            if personal_goal_hint:
                personal_goal_hint = sanitize_relationship_source(personal_goal_hint, "proactive.personal_goal_hint")
                if personal_goal_hint:
                    prompt = f"{prompt.rstrip()}\n\n{personal_goal_hint}"
        memo_hint_getter = getattr(self, "_format_memo_note_prompt", None)
        if callable(memo_hint_getter):
            memo_hint = memo_hint_getter(user, reason=reason)
            if memo_hint:
                memo_hint = sanitize_relationship_source(memo_hint, "proactive.memo_hint")
                if memo_hint:
                    prompt = f"{prompt.rstrip()}\n\n{memo_hint}"
        if open_loops_hint and "未完成话题候选" not in prompt:
            prompt = f"{prompt.rstrip()}\n\n{open_loops_hint}"
        memory_context = ""
        memory_getter = getattr(self, "_memory_companion_compose_feature_context", None)
        if callable(memory_getter):
            user_id = _single_line(user.get("user_id") or user.get("id"), 80)
            query = " ".join(
                part
                for part in (
                    "主动消息正文生成",
                    f"当前真实时间 {current_time}",
                    "当前日期 最新私聊 当前日程 当前时段 旧日材料不能改写成当前事实",
                    reason,
                    action,
                    topic_hint,
                    compact_motive,
                    "用户习惯 最近互动 当前穿搭 当前日程 自我时间线 避雷",
                )
                if _single_line(part, 180)
            )
            memory_context = await memory_getter(
                kind="proactive_generation",
                query=query,
                user=user,
                user_id=user_id,
                top_k=5,
                max_chars=760,
            )
        if memory_context:
                prompt = (
                    f"{prompt.rstrip()}\n\n"
                    "<!-- private_companion_memory_generation_context_v1 -->\n"
                    "【我会牢牢记住你 可用记忆】\n"
                    f"{memory_context}\n"
                    "使用方式：只作为自然连续性和边界参考；能贴住当前切口就轻轻用,不相关就忽略。不要说“我查到/我记忆里”。"
                )
        relationship_guard_getter = getattr(self, "_format_generation_relationship_authority_guard", None)
        if callable(relationship_guard_getter) and "关系事实权限" not in prompt:
            try:
                relationship_guard = str(relationship_guard_getter() or "").strip()
            except Exception:
                relationship_guard = ""
            if relationship_guard:
                prompt = f"{prompt.rstrip()}\n\n{relationship_guard}"
        from .presence_adapter import shared_presence_available
        if not shared_presence_available(self, str(user.get("umo") or "")):
            from .presence_snapshot import append_to_prompt
            prompt = append_to_prompt(prompt, self, user)
        identity_guard = self._format_proactive_recipient_identity_guard(user, name)
        if identity_guard:
            prompt = f"{prompt.rstrip()}\n\n{identity_guard}"
        if callable(getattr(self, '_companion_image_required', None)) and self._companion_image_required(user):
            prompt += ('\n本轮是安静的主动陪伴：通常一两句，简短、克制、像自然想起对方。'
                       '不要催回复、索要关注、客服式通知或高频撒娇。配图由发送层处理，'
                       '不要调用生图/发送工具，也不要声称刚拍照或编造用户当前状态；夜间不催睡。')
        return prompt.strip()

    def _format_proactive_generation_intent_hint(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        motive: str = "",
        action_context: str = "",
    ) -> str:
        semantics: dict[str, Any] = {}
        semantic_getter = getattr(self, "_planned_proactive_semantics", None)
        if callable(semantic_getter):
            try:
                semantics = semantic_getter(user)
            except Exception as exc:
                logger.debug("[PrivateCompanion] 主动生成语义提示读取失败: %s", _single_line(exc, 120))
                semantics = {}
        readiness: dict[str, Any] = {}
        readiness_getter = getattr(self, "_proactive_inner_readiness", None)
        if callable(readiness_getter):
            try:
                readiness = readiness_getter(user)
            except Exception as exc:
                logger.debug("[PrivateCompanion] 主动生成内在状态提示读取失败: %s", _single_line(exc, 120))
                readiness = {}

        kind = _single_line(semantics.get("kind"), 40)
        anchor_type = _single_line(semantics.get("anchor_type"), 40)
        semantic_score = _safe_float(semantics.get("score"), 0.5)
        semantic_pressure = _safe_float(semantics.get("pressure"), 0.4)
        semantic_risk = _safe_float(semantics.get("risk"), 0.0)
        semantic_note = _single_line(semantics.get("note"), 140)
        readiness_label = _single_line(readiness.get("label"), 60)
        readiness_score = _safe_float(readiness.get("score"), 0.55)
        temperature = readiness.get("temperature") if isinstance(readiness.get("temperature"), dict) else {}
        temperature_label = _single_line(temperature.get("label"), 60)
        temperature_score = _safe_float(temperature.get("score"), 0.55)
        motivation = readiness.get("motivation") if isinstance(readiness.get("motivation"), dict) else {}

        lines = ["【这次主动的内在约束】"]
        if kind or anchor_type:
            lines.append(
                f"候选语义：{kind or 'check_in'}/{anchor_type or 'vague'}；"
                f"自然度 {semantic_score:.2f}，打扰压力 {semantic_pressure:.2f}，风险 {semantic_risk:.2f}。"
                + (f" 备注：{semantic_note}。" if semantic_note else "")
            )
        if readiness_label or temperature_label:
            lines.append(
                f"开口欲：{readiness_label or '平稳'} {readiness_score:.2f}；"
                f"关系温度：{temperature_label or '平稳'} {temperature_score:.2f}。"
            )
        if motivation:
            lines.append(
                f"实验动机调度：{_single_line(motivation.get('label'), 24)} "
                f"{_safe_float(motivation.get('score'), 0.5):.2f}；"
                f"{_single_line(motivation.get('detail'), 120)}。"
            )
        afterglow = user.get("proactive_afterglow") if isinstance(user.get("proactive_afterglow"), dict) else {}
        if afterglow:
            afterglow_age = _now_ts() - _safe_float(afterglow.get("ts"), 0)
            if 0 <= afterglow_age <= 48 * 3600:
                afterglow_label = _single_line(afterglow.get("label"), 120)
                afterglow_tendency = _single_line(afterglow.get("next_tendency"), 140)
                afterglow_status = _single_line(afterglow.get("status"), 40)
                if afterglow_label or afterglow_tendency:
                    lines.append(
                        f"上一条主动回声：{afterglow_status or 'unknown'}｜"
                        f"{afterglow_label or '仍在等待自然落地'}；{afterglow_tendency or '下一次按关系反馈调整'}。"
                    )

        if semantic_score < 0.48 or semantic_pressure >= 0.58:
            lines.append("这次由头不算很硬或打扰压力偏高：正文要更短、更轻，最好像把一句话放下，不追问、不求回应。")
        elif semantic_score >= 0.68:
            lines.append("这次有明确由头：正文可以贴着那个由头说一个具体点，但仍然不要解释调度原因。")
        if reason == "low_balance":
            balance_hint_getter = getattr(self, "_format_balance_awareness_prompt", None)
            balance_hint = balance_hint_getter(user, reason=reason) if callable(balance_hint_getter) else ""
            if balance_hint:
                lines.append(balance_hint)
            lines.append("这是用户明确开启的余额感知事件：允许按人格轻轻要零花钱或补给，但只提一次，不催促、不索要回复，也不把服务余额写成用户欠款。")
        elif reason == "environment_change":
            environment_hint_getter = getattr(self, "_format_environment_change_prompt", None)
            environment_hint = environment_hint_getter(user, reason=reason) if callable(environment_hint_getter) else ""
            if environment_hint:
                lines.append(environment_hint)
            lines.append("这是有短时效的环境变化：只贴着刚发生的变化说一个具体点，不扩写预报，不假设用户正在室外，也不解释信息来源。")
        elif reason == "personal_goal_progress":
            personal_goal_hint_getter = getattr(self, "_format_personal_goal_prompt", None)
            personal_goal_hint = personal_goal_hint_getter(user, reason=reason) if callable(personal_goal_hint_getter) else ""
            if personal_goal_hint:
                lines.append(personal_goal_hint)
            lines.append("这是 Bot 自己的非创作型长期目标变化：只说一个真实进展、停滞或完成结果，不向用户索取监督，不把百分比写成系统汇报。")
        elif reason == "memo_note_reminder":
            memo_hint_getter = getattr(self, "_format_memo_note_prompt", None)
            memo_hint = memo_hint_getter(user, reason=reason) if callable(memo_hint_getter) else ""
            if memo_hint:
                lines.append(memo_hint)
            lines.append("这是用户自己设置的到期便签：直接提醒便签里的事项，一次说清，不解释为什么现在发送，也不要追问用户是否完成。")
        elif reason == "morning_greeting":
            lines.append("这是当天第一次普通早安：只自然打招呼或递出一个很轻的早晨片段，说完就停。用户还没有回应，禁止问早餐/早饭、吃了吗、吃什么，也不要追加起床查岗、健康确认或其他需要回答的问题；饮食关心会在用户回应后的独立时机处理。")
        elif reason == "meal_care":
            lines.append("这是饭点关心：自然问用户这一顿吃了没有。问题主体必须是用户，不要回答成自己吃了什么；像熟悉的人顺口惦记一句，不说教、不盘问，也不要同一条里连续列很多问题。")
        elif reason == "meal_care_followup":
            lines.append("这是一次且仅一次的吃饭补问：根据话题判断是确认后来有没有吃上，还是问已经吃过的具体内容。保持很短、低压力，不责怪用户没回，也不要重复上一句原话。")
        elif reason == "birthday_eve_hint":
            lines.append("这是生日前夜的一点留白：可以温柔地提醒对方明天多偏爱自己一点，但不要说出生日、准备、惊喜或任何剧透；一小句就停，不制造期待压力。")
        elif reason == "birthday_makeup":
            lines.append("这是次日午前的低调补送：真诚祝福即可，不要反复道歉、不解释系统或错过原因，也不要把昨天的生日写成今天。")
        elif reason == "birthday_afterglow":
            lines.append("这是用户在生日祝福后已经回应过才会出现的余温收尾：只轻轻接住一个开心瞬间，不重复说生日快乐、不追问安排，也不延长成连续庆祝。")
        elif reason == "birthday_celebration":
            lines.append("今天是用户明确允许记住的生日，是一年一次的轻量仪式。先送出真诚、具体、低压力的祝福；不要提系统、记录、年龄、出生年份或精确日期，不承诺永远陪伴，也不要求回复或追问庆祝安排。若带图，正文只自然递出，不描述制作过程。")
        elif reason == "holiday_celebration":
            context = user.get("planned_special_event_context") if isinstance(user.get("planned_special_event_context"), dict) else {}
            holidays = context.get("holidays") if isinstance(context.get("holidays"), list) else []
            names = "、".join(_single_line(item.get("name"), 40) for item in holidays if isinstance(item, dict))
            lines.append(f"这是用户启用的今日节日：{names}。多个节日只合并成一条简短、自然、低压力的问候，不逐个连发。节日不是放假或用户空闲的证据，不猜用户安排。")
            lines.append("尊重节日本身的语境：清明保持庄重克制，不机械祝快乐，不假设用户有逝去的家人、正在扫墓或需要被安慰。其他节日同样不猜家人、宗教、身份或庆祝活动；不用追问来索取回应。")
        elif reason == "course_reminder":
            context = user.get("planned_special_event_context") if isinstance(user.get("planned_special_event_context"), dict) else {}
            course_name = _single_line(context.get("name"), 80)
            location = _single_line(context.get("location"), 100)
            start_at = _safe_float(context.get("start_at"), 0)
            start_text = datetime.fromtimestamp(start_at, zoneinfo.ZoneInfo("Asia/Shanghai")).strftime("%H:%M") if start_at > 0 else ""
            lines.append(f"这是用户自己填写的真实课表提醒：课程{course_name}，开始时间{start_text}（北京时间）" + (f"，地点{location}" if location else "，未提供地点，不编造教室") + "。")
            lines.append("只在课前自然提醒一次，可以简短提及课程、时间与已填写地点；不把提醒写成用户刚发的新消息，不要求回复、不催促，不编造用户已到课堂或正在做什么。")
        elif reason == "birthday_curiosity":
            lines.append("这是一次低频的资料好奇：只自然地问生日的月日，可顺带问公历还是农历；明确说不想回答也完全没关系。不要索要出生年份、年龄、证件信息，也不要假装已经准备了生日惊喜。")
        elif reason == "web_exploration_share":
            lines.append("自然地向用户分享自己刚看的这条内容。只把标题、探索印象和链接当作事实依据，像当前人格平时聊天一样表达。")
        elif kind in {"continuation", "reminder"}:
            lines.append("这是有来源的续接/提醒：可以顺着来源，但不要写成用户刚刚又发了新消息。")
        elif kind in {"self_share", "external_share", "observation"}:
            lines.append("这是分享/观察型主动：只取一个最小切口，不写成报告、推荐文或观察总结。")
            true_external_info = reason in {"bili_video_share", "news_share", "web_exploration_share"}
            if true_external_info:
                lines.append("外界分享必须贴住这次看到的标题、视频、新闻或资料本身；如果只是低压地放一句，也要围绕来源表达感受，不要改成无关的个人状态或泛泛压力询问。")
                lines.append("最终正文必须让用户一眼知道你在分享什么：至少带标题、BV/链接、来源名或具体内容锚点之一；不要只写“看这个/这条好离谱/给你看个东西”。")
            elif anchor_type == "group_context":
                lines.append("群聊见闻只是一段共同群里的小片段：可以轻轻转述一个具体笑点或画面，不要把内部话题名写成“标题/新闻/资料”。")
        elif kind in {"care", "check_in", "light_touch"}:
            lines.append("这是靠近型主动：不要直接说想念、关心或刷存在感，要侧着落到一个小动作或小片段。")

        hesitation_note = _single_line(user.get("last_proactive_hesitation_note"), 100)
        hesitation_at = _safe_float(user.get("last_proactive_hesitation_at"), 0)
        if hesitation_note and hesitation_at > 0 and _now_ts() - hesitation_at <= 12 * 3600:
            lines.append(f"前面有过一次犹豫：{hesitation_note}。如果要用，只能变成很淡的语气底色，不要明说系统延后。")
        deferred_share_tense_hint = self._deferred_immediate_share_tense_hint(user, action)
        if deferred_share_tense_hint:
            lines.append("这段生活分享已不是当下现场：必须使用已发生时态，不要暗示事件与发送同一时刻，也不要解释延后。")

        if _safe_int(user.get("ignored_streak"), 0, 0) > 0:
            lines.append("对方最近还没回应：不要连续提问，不要控诉，也不要把沉默写成对方故意不理。")
        if "message" == str(action or "message") and not _single_line(action_context, 120):
            lines.append("本轮没有真实媒体或工具结果：正文只围绕聊天内容本身，不描述动作结果。")
        lines.append("以上只用于决定怎么写，最终正文里不要出现“语义/自然度/压力/风险/开口欲/关系温度/犹豫”等分析词。")
        return "\n".join(lines) if len(lines) > 2 else ""

    def _unexecuted_relay_claim_reason(self, text: str, *, action_context: str = "") -> str:
        cleaned = _single_line(text, 260)
        if not cleaned:
            return ""
        context = str(action_context or "")
        if any(token in context for token in ("pc_relay_message", "转述工具", "消息已发送", "已挂起", "atrelay")):
            return ""
        target_patterns = (
            r"我(?:这就|现在|等下|一会儿|待会儿)?(?:去|会|来|可以)?(?:帮你|替你)?(?:跟|和|给)([^，。！？!?、\s]{1,12})(?:说一声|说一下|转告|转达|带话|留言)",
            r"我(?:这就|现在|等下|一会儿|待会儿)?(?:帮你|替你)([^，。！？!?、\s]{0,12})(?:转告|转达|带话|留言)",
            r"(?:已经|已)(?:帮你|替你)?(?:转告|转达|带话|留言|说过)",
        )
        for pattern in target_patterns:
            match = re.search(pattern, cleaned)
            if not match:
                continue
            target = _single_line(match.group(1) if match.lastindex else "", 20)
            if target and target.startswith(("你", "妳")):
                continue
            return "没有真实转述工具执行结果"
        return ""

    def _fallback_unexecuted_relay_reply(self, inbound_text: str) -> str:
        inbound = _single_line(inbound_text, 160)
        if any(token in inbound for token in ("替我", "帮我", "你去", "跟他", "和他", "跟她", "和她", "说一声", "转告", "转达")):
            return "我不能假装已经说过。你把对象和要带的话再说清楚一点。"
        return "我不能假装已经替你说过。要我带话的话，你把对象和内容说清楚。"

    def _proactive_time_guard_hint(self, reason: str, current_item: dict[str, Any] | None) -> str:
        activity = _single_line((current_item or {}).get("activity"), 80)
        _, period_guard = self._current_time_period_label()
        prefix = f"先遵守当前真实时段：{period_guard}"
        if reason == "morning_greeting":
            return f"{prefix} 这次只能像早晨刚醒、赖床、洗漱或刚开始一天时那样开口；只做自然问候，不问早餐、吃了吗或吃什么，也不要附带健康和查岗问题。"
        if reason == "noon_greeting":
            return f"{prefix} 这次只能像中午、吃东西、发懒、午间发呆或午休前后那样开口；不要写成刚醒起床或准备睡觉。"
        if reason == "evening_greeting":
            return f"{prefix} 这次只能像傍晚收尾、天色往下落、回到家或一天快慢下来时那样开口；不要写成刚醒起床。"
        if activity and any(token in activity for token in ("便利店", "出门", "吹风", "路上", "窗边", "收拾", "吃", "洗漱", "洗澡", "刷视频", "书桌")):
            return f"{prefix} 优先贴着这一小段生活片段来开口：{activity}。不要忽然跳成不在这个时段里的“刚醒”“赖床”或“要睡了”。"
        return f"{prefix} 贴着当前这小段生活片段开口，不要忽然跳成不在这个时段里的“刚醒”“赖床”或“要睡了”。"

    def _build_framework_voice_prompt(
        self,
        *,
        user: dict[str, Any],
        name: str,
        reason: str,
        target: str,
        strict_tts: bool = False,
    ) -> str:
        state = self.data.get("daily_state", {})
        last_user_message = _single_line(user.get("last_user_message"), 80)
        profile = self._relationship_profile(user)
        tts_prompt = self._get_tts_prompt_text(target)
        req = self._voice_requirement_profile(target)
        state_hint = self._format_state_for_framework_prompt(
            state if isinstance(state, dict) else {},
            reason=reason,
            action="voice",
        )
        state_hint = self._sanitize_owner_environment_context_for_private_user(state_hint, user)
        return f"""
你现在要在同一段私聊会话里，准备一小句真正会被念出来的主动语音内容。
当前会话里已有的人格、关系、上下文会继续生效，这里不要再重复铺陈。
站位必须清楚：这是你主动发语音,不是对方刚刚来找你、叫醒你或问候你。聊天历史只作背景,不要把最后一句历史当成当前新消息。

补充信息：
- 对方称呼：{name}
- 主动原因：{reason}
- 最近一句用户消息：{last_user_message or "（暂无）"}
- 关系画像：{profile['level']}｜偏好：{profile['preference']}
- 当前状态底色：{state_hint or "今天整体比较平稳。"}
- 当前会话 TTS 规则：{tts_prompt or "（当前没有额外 TTS 提示词,就按人格自己的语音习惯来）"}
- 当前语音格式重点：{req['summary']}

要求：
1. 只输出这句真正要被念出来的语音内容，不要解释。
2. 如果当前人格或 TTS 规则要求使用 <tts>...</tts>、日语、情绪标签、双语格式，就严格遵守。
3. 如果没有明确格式要求，就写成适合私聊语音的一小句，不像朗读稿。
4. 可以有一点嘴硬、黏人、藏着的想念，但不要把喜欢说满。
5. 不要提 AI、模型、插件、TTS、语音合成这些词。
{"6. 这次必须优先满足语音格式要求；如果有日语或 <tts> 规则，不要退回普通中文句子。" if strict_tts else ""}
""".strip()

    async def _capture_framework_send_message_calls(
        self,
        *,
        target_session: str,
        runner_factory: Any,
        max_steps: int = 20,
    ) -> tuple[Any, list[_CapturedSendMessageCall]]:
        captured: list[_CapturedSendMessageCall] = []
        try:
            from astrbot.core.tools.message_tools import SendMessageToUserTool
            from astrbot.core.agent.runners.tool_loop_agent_runner import _ToolExecutionInterrupted
        except Exception:
            result = await runner_factory()
            return result, captured

        original_call = SendMessageToUserTool.call

        async def _intercept_call(tool_self, context, **kwargs):
            session_value = kwargs.get("session") or getattr(
                getattr(getattr(context, "context", None), "event", None),
                "unified_msg_origin",
                "",
            )
            messages = kwargs.get("messages")
            session_text = str(session_value or "")
            source_event = getattr(getattr(context, 'context', None), 'event', None)
            owned_event = bool(getattr(source_event, 'private_companion_proactive_framework', False))
            if owned_event and session_text == target_session and isinstance(messages, list):
                captured.append(_CapturedSendMessageCall(session_text, messages))
                logger.info(
                    "[PrivateCompanion] 已拦截框架内 send_message_to_user 工具调用: session=%s components=%s",
                    session_text,
                    len(messages),
                )
                raise _ToolExecutionInterrupted("PrivateCompanion captured send_message_to_user payload.")
            return await original_call(tool_self, context, **kwargs)

        SendMessageToUserTool.call = _intercept_call
        try:
            result = await runner_factory()
            runner = getattr(result, "agent_runner", None) if result is not None else None
            if runner is not None and hasattr(runner, "step_until_done"):
                try:
                    async for _ in runner.step_until_done(max_steps):
                        pass
                except (_CapturedFrameworkSendMessage, _ToolExecutionInterrupted):
                    logger.info(
                        "[PrivateCompanion] 主动主链工具发送已捕获,提前结束工具循环: session=%s captured=%s",
                        target_session,
                        len(captured),
                    )
        finally:
            SendMessageToUserTool.call = original_call
        return result, captured

    def _captured_send_plain_text(self, captured_tool_sends: list[Any]) -> str:
        if not captured_tool_sends:
            return ""
        captured_text_parts: list[str] = []
        for call in captured_tool_sends:
            messages = getattr(call, "messages", [])
            if not isinstance(messages, list):
                continue
            for item in messages:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").strip().lower() != "plain":
                    continue
                text_value = self._sanitize_captured_plain_text(item.get("text"))
                if text_value:
                    captured_text_parts.append(text_value)
        return "\n".join(captured_text_parts).strip()

    def _filter_incompatible_proactive_framework_tools(
        self,
        req: ProviderRequest,
        names: set[str] | None = None,
    ) -> list[str]:
        tool_set = getattr(req, "func_tool", None)
        remove_tool = getattr(tool_set, "remove_tool", None)
        if not callable(remove_tool):
            return []
        excluded = {str(name).strip() for name in (names or {"AIsearch"}) if str(name).strip()}
        existing = {
            str(getattr(tool, "name", "") or "").strip()
            for tool in list(getattr(tool_set, "tools", []) or [])
        }
        removed = sorted(name for name in excluded if name in existing)
        for name in removed:
            remove_tool(name)
        if removed:
            logger.info(
                "[PrivateCompanion] 主动主链已隔离不兼容全局工具: %s",
                ",".join(removed),
            )
        return removed

    def _framework_agent_meta_summary_leak(self, text: str) -> bool:
        cleaned = _single_line(text, 500).lower()
        if not cleaned:
            return False
        if self._looks_like_internal_provider_error_text(text):
            return True
        normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff_]+", " ", cleaned).strip()
        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff_]+", "", cleaned)
        if self._is_proactive_delivery_receipt_text(text):
            return True
        if self._is_proactive_instruction_leak_text(text):
            return True
        if (
            ("差不多20条" in cleaned or "差不多 20 条" in cleaned or "20条不同" in cleaned)
            and any(token in cleaned for token in ("没收到回复", "发消息", "消息主要是", "工具调用"))
        ):
            return True
        if (
            ("二十次" in cleaned or "20次" in cleaned or "多次" in cleaned)
            and any(token in cleaned for token in ("试着给", "发私信", "发消息"))
            and any(token in cleaned for token in ("有没有成功", "成功发出去", "没收到回复", "不确定这些消息"))
        ):
            return True
        if (
            ("读取图片文件" in cleaned or "图片文件有问题" in cleaned)
            and any(token in cleaned for token in ("占位", "工具调用", "没法继续", "多次发消息"))
        ):
            return True
        if "工具调用限制" in cleaned and any(token in cleaned for token in ("没法继续", "多次发消息", "发消息")):
            return True
        markers = (
            "trying to send messages",
            "trying to send various messages",
            "sent 20",
            "no response yet",
            "shared parts",
            "asked for her thoughts",
            "message captured",
            "executed the same tool",
            "repetition is now very high",
            "agent reached max steps",
            "forcing a final response",
            "tool `send_message_to_user`",
            "send_message_to_user",
            "一直试着给",
            "发了差不多20条",
            "还没收到回复",
            "读取图片文件有问题",
            "工具调用限制",
        )
        compact_markers = (
            "tryingtosendmessages",
            "tryingtosendvariousmessages",
            "sent20",
            "noresponseyet",
            "sharedparts",
            "askedforherthoughts",
            "messagecaptured",
            "executedthesametool",
            "repetitionisnowveryhigh",
            "agentreachedmaxsteps",
            "forcingafinalresponse",
            "sendmessagetouser",
            "一直试着给",
            "发了差不多20条",
            "还没收到回复",
            "读取图片文件有问题",
            "工具调用限制",
        )
        return any(marker in cleaned or marker in normalized for marker in markers) or any(
            marker in compact for marker in compact_markers
        )

    async def _conversation_db_operation(self, label: str, operation: Any) -> Any:
        lock = getattr(self, "_conversation_db_lock", None)
        if not isinstance(lock, asyncio.Lock):
            lock = asyncio.Lock()
            self._conversation_db_lock = lock
        for attempt in range(5):
            try:
                async with lock:
                    return await operation()
            except Exception as exc:
                text = str(exc or "").lower()
                locked = "database is locked" in text or "sqlite3.operationalerror" in text
                if locked and attempt < 4:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                logger.debug("[PrivateCompanion] 会话数据库操作失败: %s error=%s", label, exc)
                raise

    def _is_sqlite_locked_error(self, exc: Exception) -> bool:
        text = str(exc or "").lower()
        return "database is locked" in text or "sqlite3.operationalerror" in text or "sqlalche.me/e/20/e3q8" in text

    async def _get_current_conversation_safely(self, umo: str, *, label: str = "conversation") -> Any:
        async def _read():
            conv_id = await self.context.conversation_manager.get_curr_conversation_id(umo)
            if not conv_id:
                return None
            return await self.context.conversation_manager.get_conversation(umo, conv_id)

        return await self._conversation_db_operation(label, _read)

    async def _ensure_conversation_id_for_umo(self, umo: str, *, title: str = "Private Companion 主动消息") -> str:
        conv_mgr = getattr(getattr(self, "context", None), "conversation_manager", None)
        if conv_mgr is None:
            return ""
        conv_id = await conv_mgr.get_curr_conversation_id(umo)
        if conv_id:
            return str(conv_id)
        session = self._parse_message_session(umo)
        platform_id = _single_line(getattr(session, "platform_id", ""), 80) if session is not None else ""
        try:
            if platform_id:
                conv_id = await conv_mgr.new_conversation(umo, platform_id)
            else:
                conv_id = await conv_mgr.new_conversation(umo, title=title)
        except TypeError:
            try:
                conv_id = await conv_mgr.new_conversation(umo, title=title)
            except TypeError:
                conv_id = await conv_mgr.new_conversation(umo)
        if conv_id:
            logger.info(
                "[PrivateCompanion] 已为主动消息存档创建 AstrBot 会话: umo=%s cid=%s",
                _single_line(umo, 140),
                _single_line(conv_id, 80),
            )
        return str(conv_id or "")

    def _proactive_synthetic_event(self, umo: str, *, prompt: str, name: str) -> AstrMessageEvent | None:
        framework_context = self._proactive_framework_context()
        if framework_context is None:
            return None
        session = self._parse_message_session(umo)
        if not session:
            return None
        return SyntheticPrivateWakeEvent(
            context=framework_context,
            session=session,
            message=prompt,
            sender_name=name or "PrivateCompanion",
        )

    def _proactive_framework_context(self) -> Context | None:
        """Resolve only a native AstrBot Context from current or legacy wrappers."""
        candidate = getattr(self, "context", None)
        pending = [candidate]
        visited: set[int] = set()
        wrapper_attrs = (
            "context_obj",
            "plugin_context",
            "wrapped_context",
            "raw_context",
            "_context",
            "_context_obj",
            "_plugin_context",
            "_wrapped_context",
            "_raw_context",
            "__wrapped__",
        )
        while pending:
            current = pending.pop(0)
            if isinstance(current, Context):
                return current
            if current is None or id(current) in visited:
                continue
            visited.add(id(current))
            for attr in wrapper_attrs:
                try:
                    nested = getattr(current, attr, None)
                except Exception:
                    continue
                if nested is not None and id(nested) not in visited:
                    pending.append(nested)
        return None

    def _proactive_conversation_with_configured_persona(self, conversation: Any) -> Any:
        specific_id = str(getattr(self, "plugin_specific_persona_id", "") or "").strip()
        if conversation is None or not specific_id:
            return conversation
        if str(getattr(conversation, "persona_id", "") or "").strip() == specific_id:
            return conversation
        try:
            scoped = deepcopy(conversation)
            scoped.persona_id = specific_id
            return scoped
        except Exception as exc:
            logger.warning(
                "[PrivateCompanion] 无法为主动主链应用插件指定人格,继续使用会话人格: persona=%s error=%s",
                _single_line(specific_id, 80),
                _single_line(exc, 120),
            )
            return conversation

    async def _run_framework_agent_text(
        self,
        *,
        umo: str,
        prompt: str,
        name: str,
        label: str,
        max_steps: int = 20,
    ) -> str:
        cache_key = str(umo or "")
        self._framework_captured_send_cache.pop(cache_key, None)
        framework_context = self._proactive_framework_context()
        if framework_context is None:
            context_value = getattr(self, "context", None)
            context_type = type(context_value).__name__ if context_value is not None else "None"
            warning_key = f"{type(context_value).__module__}.{context_type}" if context_value is not None else context_type
            if getattr(self, "_proactive_framework_context_warning_key", "") != warning_key:
                self._proactive_framework_context_warning_key = warning_key
                logger.warning(
                    "[PrivateCompanion] 主动主链未取得 AstrBot 原生 Context,已直接转入人格化兜底: input_type=%s；请重载插件或重启 AstrBot",
                    context_type,
                )
            return ""
        event = self._proactive_synthetic_event(umo, prompt=prompt, name=name)
        if event is None:
            return ""
        try:
            setattr(event, "private_companion_skip_external_token_stats", True)
            setattr(event, "private_companion_proactive_framework", True)
            setattr(event, "private_companion_skip_passive_input_status", True)
            setattr(event, "private_companion_require_image", bool(
                callable(getattr(self, '_companion_image_required', None)) and self._companion_image_required()))
        except Exception:
            pass
        cfg = framework_context.get_config(umo=umo) if umo else framework_context.get_config()
        provider_settings = cfg.get("provider_settings", {}) if isinstance(cfg, dict) else {}
        build_cfg = MainAgentBuildConfig(
            tool_call_timeout=int(provider_settings.get("tool_call_timeout", 120) or 120),
            llm_safety_mode=False,
            streaming_response=False,
        )
        req = ProviderRequest(
            prompt=prompt,
            conversation=None,
            session_id=getattr(event, "session_id", None) or umo,
        )

        captured_tool_sends: list[Any] = []
        result = None
        async def _run_with_retries() -> None:
            nonlocal result, captured_tool_sends
            for attempt in range(3):
                try:
                    conv = await self._get_current_conversation_safely(umo, label=f"{label}_framework_read")
                    req.conversation = self._proactive_conversation_with_configured_persona(conv)

                    async def _runner_factory():
                        runner = await build_main_agent(
                            event=event,
                            # AstrBot 4.26.2+ validates this as the concrete Context type.
                            plugin_context=framework_context,
                            config=build_cfg,
                            req=req,
                        )
                        self._filter_incompatible_proactive_framework_tools(req)
                        return runner

                    result, captured_tool_sends = await self._capture_framework_send_message_calls(
                        target_session=umo,
                        runner_factory=_runner_factory,
                        max_steps=max_steps,
                    )
                    break
                except Exception as exc:
                    if self._is_sqlite_locked_error(exc) and attempt < 2:
                        wait_seconds = 0.35 * (attempt + 1)
                        logger.info(
                            "[PrivateCompanion] 主动主链遇到会话库锁,稍后重试: label=%s session=%s retry=%s",
                            label,
                            _single_line(umo, 120),
                            attempt + 1,
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                    raise
        await _run_with_retries()
        captured_tool_sends.extend(list(getattr(event, '_private_companion_captured_event_sends', []) or []))
        if captured_tool_sends:
            self._framework_captured_send_cache[cache_key] = list(captured_tool_sends)
        runner = getattr(result, "agent_runner", None) if result else None
        llm_resp = runner.get_final_llm_resp() if runner else None
        text = str(getattr(llm_resp, "completion_text", "") or "").strip()
        captured_text = self._captured_send_plain_text(captured_tool_sends)
        if captured_text:
            if text and self._framework_agent_meta_summary_leak(text):
                logger.warning(
                    "[PrivateCompanion] 主动主链 final 疑似工具循环摘要或 Provider 失败,改用已捕获发送文本: label=%s final=%s captured=%s",
                    label,
                    _single_line(text, 160),
                    _single_line(captured_text, 160),
                )
            text = captured_text
        elif text and self._framework_agent_meta_summary_leak(text):
            logger.warning(
                "[PrivateCompanion] 主动主链 final 疑似工具循环摘要或 Provider 失败且无可用捕获文本,已丢弃: label=%s text=%s",
                label,
                _single_line(text, 180),
            )
            return ""
        return text

    async def _generate_proactive_message_via_framework(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        action_context: str = "",
        action: str = "message",
        motive: str = "",
    ) -> str:
        umo = str(user.get("umo") or "").strip()
        if not umo:
            return ""
        # Pull cross-session emotional drift before generating proactive message
        try:
            self._memory_companion_apply_emotional_drift(session_id="")
        except Exception:
            pass
        prompt = await self._build_framework_proactive_prompt(
            user=user,
            name=name,
            reason=reason,
            action=action,
            action_context=action_context,
            motive=motive,
        )
        recorder = getattr(self, "_record_prompt_injection_snapshot", None)
        if callable(recorder):
            trace_id = f"pro-{uuid.uuid4().hex[:16]}"
            message_preview = _single_line(
                " / ".join(
                    part
                    for part in (
                        name,
                        _single_line(user.get("planned_proactive_topic"), 60),
                        motive,
                        reason,
                        action,
                    )
                    if _single_line(part, 60)
                ),
                220,
            )
            await recorder(
                kind="proactive",
                session=umo,
                title="主动消息提示词",
                text=prompt,
                mode=reason,
                trace_id=trace_id,
                message_preview=message_preview,
                sender_label=_single_line(f"{name}/{user.get('user_id')}", 80),
                metadata={
                    "用户": _single_line(user.get("user_id"), 80),
                    "称呼": name,
                    "原因": reason,
                    "动作": action,
                    "动机": motive,
                    "话题": _single_line(user.get("planned_proactive_topic"), 80),
                },
            )
        try:
            raw_text = await self._run_framework_agent_text(
                umo=umo,
                prompt=prompt,
                name=name,
                label="proactive_message",
                max_steps=20,
            )
            raw_text = str(raw_text or "")
            if not raw_text:
                return ""
            cleaned_text, payloads = self._extract_timer_directives(raw_text)
            if payloads:
                logger.info(
                    "[PrivateCompanion] 主动消息中清理到对话临时预约标签,不再由主动链路登记: user=%s",
                    _single_line(user.get("user_id"), 40),
                )
            return cleaned_text
        except Exception as exc:
            if self._is_sqlite_locked_error(exc):
                logger.warning("[PrivateCompanion] 主动消息主链被会话数据库锁住,本轮跳过并等待下次调度: %s", _single_line(umo, 120))
            else:
                logger.warning("[PrivateCompanion] 主动消息主链生成失败: %s", exc)
            return ""

    async def _recent_private_conversation_for_proactive_review(
        self,
        user: dict[str, Any],
        *,
        limit: int = 10,
    ) -> str:
        umo = str(user.get("umo") or "").strip()
        lines: list[str] = []
        if umo:
            try:
                conv = await self._get_current_conversation_safely(umo, label="proactive_review_history_read")
                history = self._load_conversation_history_items(conv)
                for item in history[-max(1, limit):]:
                    line = self._format_history_item_for_summary(item)
                    if line:
                        lines.append(line)
            except Exception as exc:
                logger.debug("[PrivateCompanion] 主动润色读取私聊历史失败: %s", _single_line(exc, 120))
        if not lines:
            last_user = _single_line(user.get("last_user_message"), 180)
            last_bot = _single_line(user.get("last_companion_message"), 180)
            if last_bot:
                lines.append(f"{self.bot_name}: {last_bot}")
            if last_user:
                lines.append(f"用户: {last_user}")
        return "\n".join(lines[-max(1, limit):])

    def _clean_persona_reference_rewrite_text(self, text: Any, *, limit: int = 160) -> str:
        cleaned = self._sanitize_proactive_text(str(text or ""))
        if not cleaned:
            return ""
        cleaned = _strip_internal_message_blocks(cleaned)
        cleaned = self._strip_parenthetical_stage_directions(cleaned)
        cleaned = re.sub(r"^(?:最终(?:聊天)?正文|正文|输出|回复)[:：]\s*", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip('"').strip("'")
        if not cleaned:
            return ""
        forbidden = (
            "参考意图", "参考文案", "兜底", "模板", "系统", "提示词", "工具调用",
            "执行状态", "已发送给用户", "消息已发送", "发送成功", "无文字",
        )
        if any(token in cleaned for token in forbidden):
            return ""
        if self._framework_agent_meta_summary_leak(cleaned):
            return ""
        return _single_line(cleaned, limit)

    async def _rewrite_reference_reply_with_persona(
        self,
        reference_text: str,
        *,
        scene: str = "",
        user: dict[str, Any] | None = None,
        event: AstrMessageEvent | None = None,
        history: str = "",
        fallback_text: str = "",
        task: str = "persona_reference_rewrite",
        max_chars: int = 120,
        allow_fallback: bool = False,
        preserve_status: bool = False,
    ) -> str:
        reference = _single_line(reference_text, 420)
        if not reference:
            return _single_line(fallback_text, max_chars) if allow_fallback else ""
        umo = ""
        if event is not None:
            umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo and isinstance(user, dict):
            umo = str(user.get("umo") or "").strip()
        persona = await self._resolve_proactive_persona_prompt(user, umo=umo)
        proactive_rewrite = str(task or "").startswith("proactive")
        if proactive_rewrite:
            reply_style = self._format_proactive_voice_prompt() if callable(getattr(self, "_format_proactive_voice_prompt", None)) else ""
            expression_voice = self._format_expression_voice_for_prompt(
                scope="proactive",
                target_id=_single_line(user.get("user_id") or user.get("id"), 80) if isinstance(user, dict) else "",
                context_owner=user if isinstance(user, dict) else None,
                stage_owner=user if isinstance(user, dict) else None,
            )
            if expression_voice:
                reply_style = f"{reply_style}\n\n{expression_voice}".strip()
        else:
            reply_style = self._format_reply_style_prompt()
        if not history and isinstance(user, dict):
            try:
                history = await self._recent_private_conversation_for_proactive_review(user, limit=6)
            except Exception:
                history = ""
        recipient_identity = self._format_proactive_recipient_identity_guard(
            user,
            _single_line(user.get("nickname"), 40) if isinstance(user, dict) else "",
        )
        prompt = f"""
你要把一条“参考意图”改写成当前人格会自然说出的聊天正文。参考意图只说明要表达什么，不是要照抄的句子。

【当前人格】
{persona or "保持自然、简洁、有边界。"}

【{"主动开口风格" if proactive_rewrite else "回复风格"}】
{reply_style or "像日常聊天一样短一点，不要报告式。"}

【最近对话】
{history or "（无可用历史）"}

【当前收件人】
{recipient_identity or "当前收件人身份未知；不要猜测名字或套用人格中的专属称呼。"}

【场景】
{_single_line(scene, 180) or "普通聊天回执"}

【参考意图】
{reference}

要求：
- 只输出最终聊天正文，不要解释。
- 1 句，最多 2 句；尽量像这个人格平时聊天，不要像客服、公告或模板。
- 不要照抄参考意图里的固定说法；只保留事实和语义。
- 不要出现“参考/兜底/模板/系统/工具/执行/已发送给用户/消息已发送”等字样。
- 不要新增事实、承诺、动作小剧场或没有发生的状态。
{"- 必须保留成功/失败/等待/完成/稍后再说等状态语义，不要把失败说成成功。" if preserve_status else "- 如果只是轻轻递一句，不要补多余解释。"}
""".strip()
        try:
            from .presence_adapter import temporary_context_parts
            presence_parts = await temporary_context_parts(
                self,
                session_id=umo,
                query="",
                channel="pc_proactive_fallback" if proactive_rewrite else "pc_reference_rewrite",
            )
            presence_kwargs = {"extra_user_content_parts": presence_parts} if presence_parts else {}
            raw = await self._llm_call(
                prompt,
                max_tokens=140,
                provider_id=self._task_provider(
                    getattr(self, "response_review_provider_id", ""),
                    getattr(self, "mai_style_provider_id", ""),
                    getattr(self, "llm_provider_id", ""),
                ),
                task=task,
                **presence_kwargs,
            )
        except Exception as exc:
            logger.debug("[PrivateCompanion] 人格参考意图改写失败: %s", _single_line(exc, 120))
            raw = ""
        cleaned = self._clean_persona_reference_rewrite_text(raw, limit=max_chars)
        if cleaned:
            return cleaned
        return _single_line(fallback_text, max_chars) if allow_fallback else ""

    def _local_proactive_send_decision(
        self,
        user: dict[str, Any],
        text: str,
        *,
        reason: str,
        action: str,
        motive: str = "",
        topic: str = "",
        action_context: str = "",
    ) -> dict[str, Any]:
        strength = self._proactive_review_strength()
        cleaned = _single_line(text, 500)
        if not cleaned:
            return {"decision": "drop", "reason": "主动消息为空", "hard": True}
        link_platform_mismatch = self._proactive_link_platform_mismatch_reason(cleaned)
        if link_platform_mismatch:
            return {
                "decision": "drop",
                "reason": link_platform_mismatch,
                "hard": True,
            }
        if reason == "environment_change" and re.search(
            r"https?://|(?:^|[^A-Za-z0-9])BV[0-9A-Za-z]{8,16}(?:$|[^A-Za-z0-9])|《[^》\n]{1,120}》",
            cleaned,
            flags=re.I,
        ):
            return {
                "decision": "drop",
                "reason": "环境变化主动消息混入了文章、视频或旧链接来源",
                "hard": True,
            }
        wrong_address = self._wrong_proactive_recipient_address(
            cleaned,
            user,
            _single_line(user.get("nickname"), 40),
        )
        if wrong_address:
            repaired_text, repaired_address = self._repair_proactive_recipient_address(
                cleaned,
                user,
                _single_line(user.get("nickname"), 40),
            )
            if repaired_address:
                return {
                    "decision": "rewrite",
                    "reason": f"已把收件人称呼纠正为当前昵称：{repaired_address}",
                    "text": repaired_text,
                    "hard": True,
                }
            return {
                "decision": "drop",
                "reason": f"主动正文无法确认收件人称呼：{wrong_address}",
                "hard": True,
            }
        outbound_guard = self._validate_proactive_outbound_candidate(
            cleaned,
            reason=reason,
            action=action,
            source="review",
        )
        guard_decision = str(outbound_guard.get("decision") or "send")
        if guard_decision == "drop":
            return {
                "decision": "drop",
                "reason": _single_line(outbound_guard.get("reason"), 120) or "主动候选疑似内部泄漏",
                "hard": bool(outbound_guard.get("hard", True)),
            }
        if guard_decision == "rewrite":
            rewritten_guard_text = _single_line(outbound_guard.get("text"), 500)
            if rewritten_guard_text:
                return {
                    "decision": "rewrite",
                    "reason": _single_line(outbound_guard.get("reason"), 120) or "清理主动候选内部残留",
                    "text": rewritten_guard_text,
                }
            return {"decision": "drop", "reason": _single_line(outbound_guard.get("reason"), 120) or "主动候选只剩内部残留", "hard": True}
        fact_decision = self._unverified_proactive_fact_decision(
            cleaned,
            reason=reason,
            action=action,
            action_context=action_context,
        )
        if fact_decision:
            return fact_decision
        semantics: dict[str, Any] = {}
        semantic_getter = getattr(self, "_planned_proactive_semantics", None)
        if callable(semantic_getter):
            try:
                semantics = semantic_getter(user)
            except Exception:
                semantics = {}
        semantic_kind = _single_line(semantics.get("kind"), 40)
        semantic_anchor_type = _single_line(semantics.get("anchor_type"), 40)
        semantic_score = _safe_float(semantics.get("score"), 0.5)
        semantic_pressure = _safe_float(semantics.get("pressure"), 0.4)
        semantic_risk = _safe_float(semantics.get("risk"), 0.0)
        external_info_reasons = {"bili_video_share", "news_share", "web_exploration_share"}
        external_share_active = reason in external_info_reasons
        default_hard_risk = 0.70 if strength == "lenient" else 0.45
        hard_risk_threshold = max(
            0.0,
            min(1.0, _safe_float(getattr(self, "proactive_review_hard_risk_threshold", default_hard_risk), default_hard_risk)),
        )
        low_score_threshold = max(
            0.0,
            min(1.0, _safe_float(getattr(self, "proactive_review_low_score_threshold", 0.34), 0.34)),
        )
        pressure_threshold = max(
            0.0,
            min(1.0, _safe_float(getattr(self, "proactive_review_pressure_threshold", 0.55), 0.55)),
        )
        if semantic_risk >= hard_risk_threshold:
            return {
                "decision": "drop",
                "reason": f"候选语义风险偏高 risk={semantic_risk:.2f}/{hard_risk_threshold:.2f}",
                "hard": True,
            }
        if strength != "lenient" and semantic_score < low_score_threshold and semantic_pressure >= pressure_threshold:
            return {"decision": "defer", "reason": "候选由头偏虚且打扰压力高", "delay_minutes": 75}
        reply_like_openers = (
            "好呀", "好啊", "可以呀", "行啊", "那就", "你说呢", "要不", "刚看到", "才看到",
            "你来了", "你叫我", "你问", "我帮你查", "我去问", "我去说",
        )
        matched_reply_opener = next((token for token in reply_like_openers if cleaned.startswith(token)), "")
        if matched_reply_opener and not (external_share_active and matched_reply_opener in {"刚看到", "才看到"}):
            if strength != "strict":
                rewritten = re.sub(
                    r"^(?:好呀|好啊|可以呀|行啊|那就|你说呢|要不|刚看到|才看到|你来了|你叫我|你问|我帮你查|我去问|我去说)[，,。！!？?\s]*",
                    "",
                    cleaned,
                    count=1,
                ).strip()
                if rewritten and len(rewritten) >= 4:
                    return {"decision": "rewrite", "reason": "去掉回复式开头", "text": rewritten}
            return {"decision": "drop", "reason": "像是在回复刚发来的消息"}
        motive_leak_repaired = self._strip_proactive_motive_leak_text(cleaned)
        if motive_leak_repaired != cleaned:
            if motive_leak_repaired and len(motive_leak_repaired) >= 2:
                return {"decision": "rewrite", "reason": "去掉主动动机自述", "text": motive_leak_repaired}
            return {"decision": "defer", "reason": "主动消息只剩动机自述", "delay_minutes": 75}
        vague = ("想你了", "来看看你", "你在忙什么", "最近怎么样", "吃了吗", "辛苦了", "在吗", "忙不忙")
        if strength != "lenient" and reason in {"check_in", "quiet_care", "state_share"} and any(token in cleaned for token in vague):
            return {"decision": "defer", "reason": "普通主动过于泛泛", "delay_minutes": 60}
        if strength != "lenient" and semantic_kind in {"self_share", "external_share", "observation"} and any(token in cleaned for token in vague):
            return {"decision": "defer", "reason": "生成结果偏离分享型由头", "delay_minutes": 60}
        if external_share_active:
            external_fix = self._external_share_source_consistency_decision(
                user,
                cleaned,
                reason=reason,
                topic=topic,
                motive=motive,
                action_context=action_context,
            )
            if external_fix:
                return external_fix
        role = self._private_user_role(user) if isinstance(user, dict) else "friend"
        if role == "owner":
            social_checker = getattr(self, "_daily_plan_clause_has_named_message_interaction", None)
            has_cross_private_interaction = False
            if callable(social_checker):
                try:
                    has_cross_private_interaction = bool(social_checker(cleaned))
                except Exception:
                    has_cross_private_interaction = False
            if has_cross_private_interaction or any(token in cleaned for token in ("朋友那边", "朋友用户", "朋友私聊", "次要用户那边", "次要用户私聊")):
                return {"decision": "drop", "reason": "疑似混入其他私聊互动", "hard": True}
        if _safe_int(user.get("ignored_streak"), 0, 0) >= 1 and cleaned.count("？") + cleaned.count("?") >= 2:
            return {"decision": "rewrite", "reason": "未回应状态下问题太多", "text": re.split(r"[？?]", cleaned, maxsplit=1)[0].rstrip("，,。") + "。"}
        if _safe_int(user.get("ignored_streak"), 0, 0) >= 2 and len(cleaned) > 36:
            return {"decision": "rewrite", "reason": "连续未回应时主动偏长", "text": cleaned[:36].rstrip("，,。") + "。"}
        return {"decision": "send", "reason": "本地检查通过"}

    def _external_share_source_consistency_decision(
        self,
        user: dict[str, Any],
        text: str,
        *,
        reason: str = "",
        topic: str = "",
        motive: str = "",
        action_context: str = "",
    ) -> dict[str, Any] | None:
        cleaned = _single_line(text, 240)
        if not cleaned:
            return None
        source_text = self._external_share_anchor_text(
            user,
            reason=reason,
            topic=topic,
            motive=motive,
            action_context=action_context,
        )
        if not source_text:
            return {
                "decision": "drop",
                "reason": "外界分享缺少可见来源",
                "hard": True,
            }
        source_link_match = re.search(r"https?://[^\s；，。！？!?]+", source_text, flags=re.I)
        source_link = source_link_match.group(0).rstrip("）)】]》>。.") if source_link_match else ""
        expected_platform = self._external_share_platform_from_url(source_link)
        claimed_platform = self._external_share_claimed_platform(cleaned)
        platform_mismatch = bool(
            source_link
            and claimed_platform
            and (not expected_platform or claimed_platform != expected_platform)
        )
        if platform_mismatch:
            expected_label = expected_platform or "该网页来源"
            reference = self._external_share_fallback_reference(source_text)
            if reference:
                return {
                    "decision": "rewrite",
                    "reason": f"来源平台错配：链接属于{expected_label}，正文却写成{claimed_platform}",
                    "reference_text": reference,
                    "source_text": source_text,
                    "hard": True,
                }
            return {
                "decision": "drop",
                "reason": f"来源平台错配：应为{expected_label}而不是{claimed_platform}",
                "hard": True,
            }
        if source_link and source_link not in cleaned:
            reference = self._external_share_fallback_reference(source_text)
            if reference:
                return {
                    "decision": "rewrite",
                    "reason": "外界分享正文遗漏真实来源链接",
                    "reference_text": reference,
                    "source_text": source_text,
                    "hard": True,
                }
        if self._external_share_text_mentions_source(cleaned, source_text):
            return None
        reference = self._external_share_fallback_reference(source_text)
        if reference:
            return {
                "decision": "rewrite",
                "reason": "外界分享正文偏离来源",
                "reference_text": reference,
                "source_text": source_text,
                "hard": True,
            }
        return {
            "decision": "defer",
            "reason": "外界分享缺少可承接来源",
            "delay_minutes": 75,
            "hard": True,
        }

    def _external_share_anchor_text(
        self,
        user: dict[str, Any],
        *,
        reason: str = "",
        topic: str = "",
        motive: str = "",
        action_context: str = "",
    ) -> str:
        parts: list[str] = []

        def add(value: Any, limit: int = 160) -> None:
            text = self._clean_external_share_source_field(value, limit)
            if text and text not in parts:
                parts.append(text)

        add(topic, 180)
        if action_context:
            for raw_line in str(action_context or "").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if self._looks_like_internal_provider_error_text(line):
                    continue
                if re.match(
                    r"^(?:标题|话题|摘要重点|搜索词|参考来源|来源|链接|UP|短评|回味|内部印象|留下的印象)[:：]",
                    line,
                    flags=re.I,
                ):
                    add(line, 220)
        if isinstance(user, dict):
            context_keys = {
                "bili_video_share": ("bilibili_video_context",),
                "news_share": ("news_context",),
                "web_exploration_share": ("web_exploration_context",),
            }.get(str(reason or "").strip(), ())
            for key in context_keys:
                payload = user.get(key)
                if not isinstance(payload, dict):
                    continue
                for field in (
                    "title",
                    "headline",
                    "topic",
                    "summary",
                    "impression",
                    "comment",
                    "review",
                    "source",
                    "selected_source",
                    "source_title",
                    "selected_link",
                    "source_url",
                    "link",
                    "url",
                    "bvid",
                ):
                    add(payload.get(field), 180)
        if not parts:
            add(motive, 140)
        return _single_line("；".join(parts), 760)

    def _external_share_is_vague_pointer(self, text: str) -> bool:
        message = _single_line(text, 260)
        if not message:
            return False
        if re.search(r"https?://|(?:^|[^A-Za-z0-9])BV[0-9A-Za-z]{8,16}(?:$|[^A-Za-z0-9])", message):
            return False
        if re.search(r"[《“\"『「][^》”\"』」]{2,80}[》”\"』」]", message):
            return False
        compact = re.sub(r"[\s，,。！？!?、~～…]+", "", message)
        vague_patterns = (
            "你快看这个",
            "快看这个",
            "看这个",
            "你看看这个",
            "看看这个",
            "给你看个东西",
            "刷到个东西",
            "这个也太",
            "这个太",
            "这个好",
            "这条也太",
            "这条太",
            "这也太",
            "居然这么",
        )
        if any(pattern in compact for pattern in vague_patterns):
            return True
        if len(compact) <= 26 and any(token in compact for token in ("这个", "这条", "那条", "东西")) and any(
            token in compact for token in ("离谱", "逆天", "好笑", "绷不住", "惊了", "怪")
        ):
            return True
        return False

    def _external_share_text_mentions_source(self, text: str, source_text: str) -> bool:
        message = _single_line(text, 260).lower()
        source = _single_line(source_text, 760).lower()
        if not message or not source:
            return False
        if self._looks_like_internal_provider_error_text(message):
            return False
        if self._external_share_is_vague_pointer(message):
            return False
        anchor_tokens = self._external_share_anchor_tokens(source)
        for token in anchor_tokens:
            if token and token in message:
                return True
        return False

    def _external_share_anchor_tokens(self, source_text: str) -> list[str]:
        text = _single_line(source_text, 760)
        if not text:
            return []
        tokens: list[str] = []

        def add(value: str) -> None:
            clean = value.strip(" \t\r\n，。！？；：、,.!?;:()（）[]【】《》“”\"'")
            if len(clean) >= 2 and clean not in tokens:
                tokens.append(clean)

        for item in re.findall(r"[A-Za-z]+[-_A-Za-z0-9]*|[0-9]+(?:多年|年|月|日|次|个|%)?", text):
            add(item.lower())
        for chunk in re.split(r"[\s，。！？；：、,.!?;:|｜/\\\\()（）\\[\\]【】《》“”\"']+", text):
            chunk = chunk.strip()
            if not chunk:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]{2,12}", chunk):
                add(chunk)
                if len(chunk) > 4:
                    for size in (4, 3, 2):
                        for index in range(0, max(0, len(chunk) - size + 1)):
                            add(chunk[index:index + size])
            elif re.search(r"[\u4e00-\u9fff]", chunk):
                for item in re.findall(r"[\u4e00-\u9fff]{2,8}", chunk):
                    add(item)
        generic = {
            "标题", "视频", "新闻", "文章", "资料", "来源", "分享", "短评", "回味", "评分", "链接",
            "这个", "这条", "那条", "那个", "东西", "内容", "感觉", "有点", "刚刚", "刚才",
            "离谱", "逆天", "好笑", "有趣", "震惊", "惊了", "神奇", "奇怪", "贴", "轻轻",
            "刚刷到一个视频", "刚刷到", "刷到一", "到一个", "一个视", "个视频", "一个视频",
            "b站视频分享线索", "站视频分享线索", "视频分享线索", "分享线索",
            "新闻阅读线索", "阅读线索", "刚扫过", "扫过几", "几条新", "条新闻",
            "网页探索线索", "探索线索", "内部探索笔记", "探索笔记",
            "http", "https", "www", "com", "cn", "bilibili", "video",
        }
        generic_phrases = (
            "b站视频分享线索刚刷到一个视频",
            "新闻阅读线索刚扫过几条新闻其中一条让自己有点想私下提一句",
            "网页探索线索bot刚刚按自己的兴趣主动搜索并了解了一点新东西这是一条内部探索笔记",
            "表达要求不要像播报新闻不要夸大或补充未知事实",
        )
        return [
            token
            for token in tokens
            if token not in generic and not any(token in phrase for phrase in generic_phrases)
        ][:24]

    def _external_share_fallback_reference(self, source_text: str) -> str:
        source = _single_line(source_text, 760)
        if not source:
            return ""
        title = ""
        link = ""
        link_match = re.search(r"https?://[^\s；，。！？!?]+", source, flags=re.I)
        if link_match:
            link = _single_line(link_match.group(0).rstrip("）)】]》>。."), 220)
        source_platform = self._external_share_platform_from_url(link)
        bvid_match = re.search(r"\bBV[0-9A-Za-z]{8,16}\b", source)
        if not link and bvid_match:
            link = f"https://www.bilibili.com/video/{bvid_match.group(0)}"
        reference_match = re.search(r"(?:参考来源|source_title)[:：]\s*([^；。\n\r|｜]{2,90})", source, flags=re.I)
        if reference_match:
            title = _single_line(reference_match.group(1), 64)
        book_match = re.search(r"[《“\"『「]([^》”\"』」]{2,90})[》”\"』」]", source)
        if not title and book_match:
            title = _single_line(book_match.group(1), 64)
        for pattern in (
            r"(?:标题|摘要重点|话题|参考来源|source_title|headline|topic)[:：]\s*([^；。\n\r|｜]{2,90})",
            r"^([^；。\n\r]{4,90})",
        ):
            if title:
                break
            match = re.search(pattern, source, flags=re.I)
            if match:
                title = _single_line(match.group(1), 64)
                title = re.split(
                    r"\s+(?:链接|UP|评分|心情|短评|回味|来源|内部印象|表达气质|额外边界|参考来源|搜索词)[:：]",
                    title,
                    maxsplit=1,
                    flags=re.I,
                )[0]
                break
        if not title:
            if link:
                return _single_line(link, 260)
            return ""
        title = title.strip(" ，。！？；：、,.!?;:|｜")
        if not title:
            if link:
                return _single_line(link, 260)
            return ""
        if self._looks_like_internal_provider_error_text(title):
            return ""
        impression_match = re.search(
            r"(?:留下的印象|内部印象|短评|回味)[:：]\s*([^；\n\r]{4,70})",
            source,
            flags=re.I,
        )
        impression = _single_line(impression_match.group(1), 42).rstrip("。！？!?；;，,") if impression_match else ""
        impression = re.sub(r"让人", "让我", impression)
        if source_platform:
            base = f"刚在{source_platform}刷到“{title}”"
        else:
            base = f"刚看到“{title}”这条内容"
        if impression and impression != title and len(base) + len(impression) <= 96:
            base = f"{base}，{impression}"
        else:
            base = f"{base}，有点想给你看看"
        if link:
            base = f"{base}。{link}"
        else:
            base = f"{base}。"
        return _single_line(base, 300)

    def _strip_proactive_motive_leak_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        units: list[str] = []
        for line in cleaned.splitlines() or [cleaned]:
            units.extend(self._split_proactive_sentence_units(line))
        if not units:
            units = [cleaned]

        leak_unit_patterns = (
            r"(?:怕|担心)[^。！？\n]{0,16}(?:太早|太晚|打扰|吵到|烦到)",
            r"(?:先|又|就)?(?:收住|忍住|憋住|忍了一下|放了一会)[^。！？\n]{0,20}",
            r"(?:结果|后来)?[^。！？\n]{0,12}(?:绕了一圈|转了一圈|想了半天)[^。！？\n]{0,24}(?:来找你|找你|说出口)",
            r"(?:还是|又|最后|结果)[^。！？\n]{0,12}(?:来找你|找你|跑来找你|过来找你)[啦了啊呀]*",
            r"(?:没什么事|没有别的事|也没什么)[^。！？\n]{0,18}(?:就是|只是)?想(?:来)?(?:找你|跟你说话|和你说话|说一句)",
        )
        leak_clause_patterns = (
            r"[，,、\s]*(?:刚[^，。！？\n]{0,24})?(?:就|还是)?想(?:先)?(?:跟|和)?你(?:说早安|说早|说一句|说点什么|打个招呼|聊两句|说话)[^，。！？\n]*",
            r"[，,、\s]*(?:中午|晚上|早上|这会儿|刚才|刚刚)?[^，。！？\n]{0,18}(?:就|又|还是)?想(?:顺手)?(?:来)?(?:找你|跟你打个照面|和你打个照面|往你这边冒个头)[^，。！？\n]*",
            r"[，,、\s]*(?:刚刚|刚才|这会儿|今天|明明|还是)?[^，。！？\n]{0,24}想(?:和|给|问|提醒|确认|看看)?用户[^，。！？\n]*",
            r"[，,、\s]*(?:怕|担心)[^，。！？\n]{0,16}(?:太早|太晚|打扰|吵到|烦到)[^，。！？\n]*",
            r"[，,、\s]*(?:就)?先(?:收住|忍住|憋住)[^，。！？\n]*",
            r"[，,、\s]*(?:结果|后来)?[^，。！？\n]{0,12}(?:绕了一圈|转了一圈|想了半天)[^，。！？\n]*",
            r"[，,、\s]*莫名觉得[^，。！？\n]*",
            r"[，,、\s]*(?:顺手)(?:丢给你|放这儿|递给你|想起|分享一下|分享一下)[^，。！？\n]*",
            r"[，,、\s]*(?:多看一眼|也会留意这个|也会看一眼)[^，。！？\n]*",
            r"[，,、\s]*(?:只)?轻轻(?:提一句|提醒[^，。！？\n]*|说声|补上一句)[^，。！？\n]*",
            r"[，,、\s]*想(?:短短|轻轻)(?:说一句|提一句|说句话|提一声|说一下|打声招呼)[^，。！？\n]*",
            r"[，,、\s]*感觉和[^，。！？\n]{0,20}有点贴[^，。！？\n]*",
            r"[，,、\s]*想跟你说一句[^，。！？\n]*",
        )
        kept: list[str] = []
        changed = False
        for raw_unit in units:
            unit = str(raw_unit or "").strip()
            if not unit:
                continue
            if any(re.search(pattern, unit) for pattern in leak_unit_patterns):
                changed = True
                continue
            repaired = unit
            for pattern in leak_clause_patterns:
                repaired, count = re.subn(pattern, "", repaired)
                changed = changed or count > 0
            repaired = repaired.strip(" ，,、。！？!?；;")
            if repaired:
                kept.append(self._ensure_chat_sentence_punctuation(repaired))
            elif repaired != unit:
                changed = True
        if not changed:
            return cleaned
        return "\n".join(kept)[:260].strip()

    def _proactive_review_strength(self) -> str:
        strength = str(getattr(self, "proactive_review_strength", "lenient") or "lenient").strip().lower()
        return strength if strength in {"lenient", "balanced", "strict"} else "lenient"

    def _effective_proactive_review_mode(self) -> str:
        mode = str(getattr(self, "proactive_review_mode", "full") or "full").strip().lower()
        return mode if mode in {"local_only", "severe_only", "full"} else "full"

    @staticmethod
    def _proactive_review_hard_block_reason(reason: str) -> bool:
        text = str(reason or "")
        if not text:
            return False
        markers = (
            "隐私", "泄露", "越界", "风险", "危险", "敏感", "违规", "骚扰", "威胁",
            "其他私聊", "朋友私聊", "混入", "承诺工具", "承诺发图", "承诺语音", "承诺查询",
            "系统动作", "发送状态", "状态汇报", "工具执行", "工具结果", "工具回执",
            "执行回执", "发送回执", "系统回执", "不是角色真正",
        )
        return any(marker in text for marker in markers)

    def _balanced_proactive_defer_release_reason(
        self,
        user: dict[str, Any],
        *,
        note: str = "",
        now: float | None = None,
    ) -> str:
        if not isinstance(user, dict):
            return ""
        note_text = _single_line(note, 120)
        generic_defer = any(
            token in note_text
            for token in ("刚结束", "稍后", "稍候", "时机", "自然", "突兀", "间隔", "不合适")
        )
        if not generic_defer:
            return ""
        today = _today_key()
        sent_today = _safe_int(user.get("sent_today"), 0) if str(user.get("sent_day") or "") == today else 0
        if sent_today > 0:
            return ""
        last_sent_at = max(
            _safe_float(user.get("last_proactive_sent_at"), 0),
            _safe_float(user.get("last_sent"), 0),
        )
        if last_sent_at > 0 and datetime.fromtimestamp(last_sent_at).strftime("%Y-%m-%d") == today:
            return ""
        check_now = _now_ts() if now is None else now
        now_dt = datetime.fromtimestamp(check_now)
        if now_dt.hour * 60 + now_dt.minute < 10 * 60 + 30:
            return ""
        idle_getter = getattr(self, "_effective_user_idle_minutes", None)
        try:
            idle_minutes = idle_getter(user) if callable(idle_getter) else _safe_int(getattr(self, "idle_minutes", 20), 20)
        except Exception:
            idle_minutes = _safe_int(getattr(self, "idle_minutes", 20), 20)
        recent_private_at = max(
            _safe_float(user.get("last_user_message_at"), 0),
            _safe_float(user.get("last_private_seen"), 0),
        )
        if recent_private_at > 0 and check_now - recent_private_at < max(10, min(60, idle_minutes)) * 60:
            return ""
        return "今日尚无主动且候选非硬风险，标准强度低频放行"

    @staticmethod
    def _proactive_review_elapsed_text(seconds: float) -> str:
        if seconds < 0:
            return "未知"
        if seconds < 90:
            return "刚刚"
        if seconds < 3600:
            return f"约{max(1, int(seconds // 60))}分钟"
        if seconds < 86400:
            return f"约{max(1, int(seconds // 3600))}小时"
        return f"约{max(1, int(seconds // 86400))}天"

    @staticmethod
    def _proactive_has_verified_recent_fact_source(
        *,
        reason: str,
        action: str,
        action_context: str = "",
    ) -> bool:
        source_reasons = {
            "bili_video_share",
            "news_share",
            "web_exploration_share",
            "creative_share",
            "jm_cosmos_share",
            "jm_cosmos_recommendation_request",
        }
        if str(reason or "").strip() in source_reasons:
            return True
        context = str(action_context or "")
        if re.search(r"(?:真实图片文件|图片路径|真实动作结果|工具结果|来源链接|https?://)", context, re.I):
            return True
        return str(action or "message").strip() not in {"", "message", "photo_text"} and bool(_single_line(context, 240))

    def _unverified_proactive_fact_decision(
        self,
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str = "",
    ) -> dict[str, Any] | None:
        if self._proactive_has_verified_recent_fact_source(
            reason=reason,
            action=action,
            action_context=action_context,
        ):
            return None
        recent_self_action = re.compile(
            r"(?:我\s*)?(?:刚刚|刚才|方才|刚|才)\s*"
            r"(?:刷到|刷了|看到|看见|听到|听见|读到|发现|碰到|遇到|收到|"
            r"买了|拍了|做了|画了|写了|吃了|喝了|回到|到家|出门|回来)"
        )
        stale_meal_attribution = re.compile(
            r"你[^。！？!?；;…~～]{0,12}(?:昨天|昨晚)[^。！？!?；;…~～]{0,16}"
            r"(?:吃的|点的|喝的|吃了|点了|喝了)"
        )
        unsafe_units: list[str] = []
        safe_units: list[str] = []
        for unit in self._split_proactive_sentence_units(text):
            recent_claim = bool(recent_self_action.search(unit))
            stale_claim = reason in {"meal_care", "meal_care_followup"} and bool(stale_meal_attribution.search(unit))
            if recent_claim or stale_claim:
                unsafe_units.append(unit)
            else:
                safe_units.append(unit)
        if not unsafe_units:
            return None
        repaired = " ".join(safe_units).strip()
        if repaired and len(re.sub(r"\s+", "", repaired)) >= 4:
            return {
                "decision": "rewrite",
                "reason": "已移除无真实来源的近期动作或旧饮食归因",
                "text": repaired,
                "hard": True,
            }
        return {
            "decision": "drop",
            "reason": "主动正文依赖无真实来源的近期动作或旧饮食归因",
            "hard": True,
        }

    def _format_proactive_review_runtime_context(self, user: dict[str, Any], *, now: float | None = None) -> str:
        check_now = _now_ts() if now is None else now
        now_dt = datetime.fromtimestamp(check_now)
        today = _today_key()
        sent_today = _safe_int(user.get("sent_today"), 0) if str(user.get("sent_day") or "") == today else 0
        last_sent_at = max(
            _safe_float(user.get("last_proactive_sent_at"), 0),
            _safe_float(user.get("last_sent"), 0),
        )
        activity_getter = getattr(self, "_latest_private_user_activity_ts", None)
        try:
            last_private_at = activity_getter(user) if callable(activity_getter) else 0
        except Exception:
            last_private_at = 0
        if last_private_at <= 0:
            last_private_at = max(
                _safe_float(user.get("last_user_message_at"), 0),
                _safe_float(user.get("last_private_seen"), 0),
            )
        idle_getter = getattr(self, "_effective_user_idle_minutes", None)
        interval_getter = getattr(self, "_effective_user_min_interval_minutes", None)
        try:
            idle_minutes = idle_getter(user) if callable(idle_getter) else _safe_int(getattr(self, "idle_minutes", 20), 20)
        except Exception:
            idle_minutes = _safe_int(getattr(self, "idle_minutes", 20), 20)
        try:
            min_interval = interval_getter(user) if callable(interval_getter) else _safe_int(getattr(self, "min_interval_minutes", 80), 80)
        except Exception:
            min_interval = _safe_int(getattr(self, "min_interval_minutes", 80), 80)
        private_elapsed = check_now - last_private_at if last_private_at > 0 else -1
        sent_elapsed = check_now - last_sent_at if last_sent_at > 0 else -1
        return "\n".join(
            part
            for part in (
                f"当前判定时间：{now_dt.strftime('%Y-%m-%d %H:%M')}",
                f"今天已成功主动：{sent_today} 条",
                f"距用户上次私聊活动：{self._proactive_review_elapsed_text(private_elapsed)}；普通主动要求空闲约 {max(0, int(idle_minutes))} 分钟",
                f"距上次主动发送：{self._proactive_review_elapsed_text(sent_elapsed)}；普通主动最小间隔约 {max(0, int(min_interval))} 分钟",
                f"上次主动内容：{_single_line(user.get('last_proactive_message'), 120)}" if user.get("last_proactive_message") else "",
            )
            if part
        )

    def _stale_proactive_review_defer_release_reason(
        self,
        user: dict[str, Any],
        *,
        note: str = "",
        now: float | None = None,
    ) -> str:
        note_text = _single_line(note, 120)
        if not note_text or not re.search(r"(早安|今早|早上|睡前|晚安)", note_text):
            return ""
        check_now = _now_ts() if now is None else now
        now_minutes = datetime.fromtimestamp(check_now).hour * 60 + datetime.fromtimestamp(check_now).minute
        if "睡前" in note_text or "晚安" in note_text:
            stale_after = 9 * 60
        else:
            stale_after = 12 * 60
        if now_minutes < stale_after:
            return ""
        recent_private_at = max(
            _safe_float(user.get("last_user_message_at"), 0),
            _safe_float(user.get("last_private_seen"), 0),
        )
        if recent_private_at > 0 and check_now - recent_private_at < 45 * 60:
            return ""
        return "复核理由沿用了过期早间/睡前语境，已改按当前运行态放行"

    def _normalize_proactive_review_decision_policy(
        self,
        user: dict[str, Any],
        payload: dict[str, Any],
        *,
        strength: str,
        source: str = "model",
    ) -> dict[str, Any]:
        """Normalize the final proactive content gate to send, rewrite, or drop."""
        if not isinstance(payload, dict):
            return {"decision": "send", "reason": "empty review result; local safety gate allowed the message"}
        decision = str(payload.get("decision") or "send").strip().lower()
        note = _single_line(payload.get("reason"), 120)
        reviewed_text = str(payload.get("text") or "").strip()
        if decision == "defer":
            decision = "drop"
            note = _single_line(f"{note or 'candidate is not suitable now'}; final content gate drops instead of deferring", 120)
        if decision not in {"send", "rewrite", "drop"}:
            decision = "send"
        if decision == "rewrite" and not reviewed_text:
            decision = "drop"
            note = _single_line(f"{note or 'rewrite result is empty'}; candidate dropped", 120)
        if decision == "rewrite" and reviewed_text:
            recipient_name = _single_line(user.get("nickname"), 40) if isinstance(user, dict) else ""
            reviewed_text, repaired_address = self._repair_proactive_recipient_address(
                reviewed_text,
                user,
                recipient_name,
            )
            remaining_wrong_address = self._wrong_proactive_recipient_address(
                reviewed_text,
                user,
                recipient_name,
            )
            if remaining_wrong_address:
                decision = "drop"
                reviewed_text = ""
                note = f"最终改写含其他用户专属称呼：{remaining_wrong_address}"
            elif repaired_address:
                note = _single_line(f"{note or 'final rewrite'}; corrected recipient address {repaired_address}", 120)
        return {
            "decision": decision,
            "text": reviewed_text if decision == "rewrite" else "",
            "reason": note or "proactive final content gate",
            "hard": bool(payload.get("hard")),
        }

    async def _review_proactive_message_send_decision(
        self,
        user: dict[str, Any],
        text: str,
        *,
        reason: str,
        action: str,
        motive: str = "",
        topic: str = "",
        action_summary: str = "",
        image_path: str = "",
    ) -> dict[str, Any]:
        strength = self._proactive_review_strength()
        review_context = _single_line(action_summary, 240)
        if image_path:
            review_context = _single_line(f"{review_context}\n真实图片文件：{image_path}", 360)
        local = self._local_proactive_send_decision(
            user,
            text,
            reason=reason,
            action=action,
            motive=motive,
            topic=topic,
            action_context=review_context,
        )
        local_decision = str(local.get("decision") or "send").strip().lower()
        local_hard_block = bool(local.get("hard")) or self._proactive_review_hard_block_reason(_single_line(local.get("reason"), 120))
        review_enabled = bool(getattr(self, "enable_proactive_message_review", True))
        review_mode = self._effective_proactive_review_mode()
        if not review_enabled or review_mode == "local_only":
            if local_decision in {"drop", "defer"}:
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            if local_decision == "rewrite":
                return {
                    "decision": "drop",
                    "text": "",
                    "reason": "主动模型终审未启用，候选需要改写才能安全发送，已取消本轮发送",
                    "hard": True,
                }
            return {
                "decision": "send",
                "text": "",
                "reason": "主动模型终审未启用，本地检查允许原文发送",
            }
        if local_decision in {"drop", "defer"} and local_hard_block:
            return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
        if local.get("decision") == "rewrite" and str(local.get("reference_text") or "").strip():
            rewrite_scene = _single_line(
                "自然地向用户分享自己刚看的这条内容；保留真实标题、来源和链接"
                if reason in {"bili_video_share", "news_share", "web_exploration_share"}
                else f"主动消息改写；reason={reason or 'check_in'}；action={action or 'message'}",
                180,
            )
            rewritten_reference = await self._rewrite_reference_reply_with_persona(
                str(local.get("reference_text") or ""),
                scene=rewrite_scene,
                user=user,
                fallback_text="",
                task="proactive_reference_rewrite",
                max_chars=140,
                allow_fallback=False,
            )
            if rewritten_reference:
                rewritten_reference = self._sanitize_action_boundaries(
                    self._sanitize_proactive_text(rewritten_reference),
                    reason=reason,
                    action=action,
                    action_context=review_context,
                    has_real_image=bool(image_path) or "真实图片文件：" in review_context or "图片路径：" in review_context,
                )
                rewritten_reference = self._normalize_proactive_sentence_flow(rewritten_reference)
                post_rewrite_check = self._external_share_source_consistency_decision(
                    user,
                    rewritten_reference,
                    reason=reason,
                    topic=topic,
                    motive=motive,
                    action_context=review_context,
                )
                if post_rewrite_check:
                    safe_reference = _single_line(local.get("reference_text"), 300)
                    logger.info(
                        "[PrivateCompanion] 主动外界分享人格润色后仍与来源不一致，已使用确定性来源文本: reason=%s before=%s after=%s",
                        _single_line(post_rewrite_check.get("reason"), 120),
                        _single_line(rewritten_reference, 140),
                        _single_line(safe_reference, 140),
                    )
                    rewritten_reference = safe_reference
            if rewritten_reference:
                local = dict(local)
                local["text"] = rewritten_reference
                local.pop("reference_text", None)
            else:
                return {
                    "decision": "drop",
                    "reason": _single_line(local.get("reason"), 80) or "兜底参考意图未能按人格改写",
                    "hard": True,
                }
        if local.get("decision") == "rewrite" and bool(local.get("hard")):
            return local
        if local_decision == "drop":
            return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
        if review_mode == "severe_only" and local_decision == "send" and not local_hard_block:
            return {
                "decision": "send",
                "text": "",
                "reason": "主动终审严重问题模式：本地检查通过",
            }
        persona = await self._resolve_proactive_persona_prompt(user)
        history = await self._recent_private_conversation_for_proactive_review(user, limit=10)
        intent_hint = self._format_proactive_generation_intent_hint(
            user,
            reason=reason,
            action=action,
            motive=motive,
            action_context=review_context,
        )
        proactive_voice = self._format_proactive_voice_prompt() if callable(getattr(self, "_format_proactive_voice_prompt", None)) else ""
        expression_formatter = getattr(self, "_format_expression_voice_for_prompt", None)
        expression_voice = (
            expression_formatter(
                scope="proactive",
                target_id=_single_line(user.get("user_id") or user.get("id"), 80),
                context_owner=user,
                stage_owner=user,
            )
            if callable(expression_formatter)
            else ""
        )
        recipient_identity = self._format_proactive_recipient_identity_guard(
            user,
            _single_line(user.get("nickname"), 40),
        )
        runtime_context = self._format_proactive_review_runtime_context(user)
        has_verified_fact_source = self._proactive_has_verified_recent_fact_source(
            reason=reason,
            action=action,
            action_context=review_context,
        )
        fact_source_context = (
            f"本轮存在可核验动作/来源：{review_context}"
            if has_verified_fact_source
            else "本轮没有可核验的近期动作或外部来源；不得声称自己刚刚看见、刷到、听到、收到或完成了某件事。"
        )
        local_context = "；".join(
            part
            for part in (
                f"本地结论={local_decision or 'send'}",
                f"说明={_single_line(local.get('reason'), 100)}" if local.get("reason") else "",
                "硬风险=yes" if local_hard_block else "硬风险=no",
                f"本地建议文本={_single_line(local.get('text'), 120)}" if local.get("text") else "",
            )
            if part
        )
        prompt = f"""
You are the final content gate immediately before one proactive private message is sent.
Return JSON only. You must decide exactly one of send, rewrite, or drop.

Decision contract:
- send: the candidate is natural, persona-consistent, useful now, and ready to send unchanged. Leave text empty.
- rewrite: the message still has a concrete reason to exist, but needs a small rewrite to sound natural in this exact conversation. text must be the complete sendable final message.
- drop: do not send this candidate. Use it for weak, generic, intrusive, fabricated, context-conflicting, reply-to-nothing, internal-status, tool-result, or unsafe content.

Rules:
- This is a content gate, not a scheduler. Never output defer, waiting, or a delay.
- Read the recent conversation and runtime context first. The candidate must read like a natural message from the current persona, not a system-triggered interruption.
- Do not invent facts or promise tools, searches, media, relays, or actions that were not actually performed.
- Planned schedules, persona continuity, and message seeds are narrative inspiration, not evidence that an action happened.
- Relative dates such as yesterday must be supported by the recent conversation or an explicitly dated reliable source.
- Preserve real media context. Do not claim an image exists when none is attached.
- A rewrite must be shorter or similarly sized and must not add new factual claims.
- If a user has just been discussing something and the candidate cannot naturally fit, drop it; do not defer it.

[Recent conversation]
{history or "(none)"}

[Runtime state]
{runtime_context}

[Verified fact boundary]
{fact_source_context}

[Local safety result]
{local_context or "local gate passed"}

[Proactive source]
reason={reason or "check_in"}; action={action or "message"}; topic={_single_line(topic, 80) or "none"}; motive={_single_line(motive, 120) or "none"}; summary={_single_line(action_summary, 80) or "none"}

[Full persona]
{persona[:2600] if persona else "(No explicit persona was resolved. Preserve the candidate instead of inventing a new voice.)"}

[Persona and intent constraints]
{intent_hint or "(none)"}

[Proactive voice]
{proactive_voice or "(natural, low-pressure private chat)"}

[Learned expression voice]
{expression_voice or "(none)"}

[Recipient identity boundary]
{recipient_identity or "Use only the current recipient identity. Do not guess or copy an exclusive name from persona examples."}

[Candidate]
{text}

Output:
{{"decision":"send|rewrite|drop","text":"","reason":"brief reason"}}
""".strip()
        started = time.perf_counter()
        review_provider_id = self._task_provider(self.response_review_provider_id, self.mai_style_provider_id)
        timeout_seconds = 8.0
        timeout_getter = getattr(self, "_model_timeout_seconds_for_call", None)
        timeout_override = (
            timeout_getter(
                task="proactive_send_review",
                provider_id=review_provider_id,
                timeout_key="RESPONSE_REVIEW_PROVIDER_ID",
            )
            if callable(timeout_getter)
            else None
        )
        if timeout_override is not None:
            timeout_seconds = float(timeout_override)
        try:
            raw = await asyncio.wait_for(
                self._llm_call(
                    prompt,
                    max_tokens=220,
                    provider_id=review_provider_id,
                    task="proactive_send_review",
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            now = time.time()
            last_log_at = float(getattr(self, "_proactive_review_fallback_log_at", 0.0) or 0.0)
            if now - last_log_at >= 600:
                self._proactive_review_fallback_log_at = now
                logger.info(
                    "[PrivateCompanion] 主动最终内容复核模型暂不可用，已安全回退本地复核（同类日志 10 分钟内不重复）: %s",
                    self._format_send_exception(exc),
                )
            return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
        payload = self._parse_json_object(raw)
        if not isinstance(payload, dict):
            return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"send", "rewrite", "drop"}:
            return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
        reviewed_text = str(payload.get("text") or "").strip()
        note = _single_line(payload.get("reason"), 120)
        original_decision = decision
        if decision == "rewrite":
            if not reviewed_text:
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            reviewed_text = self._sanitize_action_boundaries(
                self._sanitize_proactive_text(reviewed_text),
                reason=reason,
                action=action,
                action_context=review_context,
                has_real_image=bool(image_path) or "真实图片文件：" in review_context or "图片路径：" in review_context,
            )
            reviewed_text = self._normalize_proactive_sentence_flow(reviewed_text)
            reviewed_text, repaired_address = self._repair_proactive_recipient_address(
                reviewed_text,
                user,
                _single_line(user.get("nickname"), 40),
            )
            if repaired_address:
                logger.warning(
                    "[PrivateCompanion] 主动发送前复核改写已纠正串用户称呼: user=%s wrong=%s",
                    _single_line(user.get("user_id"), 40),
                    repaired_address,
                )
            if not reviewed_text:
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            meta_leak_checker = getattr(self, "_response_review_meta_leak_reason", None)
            if callable(meta_leak_checker) and meta_leak_checker(reviewed_text):
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            if self._framework_agent_meta_summary_leak(reviewed_text):
                return {
                    "decision": "drop",
                    "text": "",
                    "reason": "主动候选疑似工具循环/内部发送摘要泄漏",
                }
            if len(reviewed_text) > max(len(text) + 60, 240):
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            if re.search(r"(提示词|系统|JSON|模型|工具调用|主动消息|无文字|附加组件)", reviewed_text, re.IGNORECASE):
                return self._normalize_proactive_review_decision_policy(user, local, strength=strength, source="local")
            if reason in {"bili_video_share", "news_share", "web_exploration_share"}:
                rewritten_source_issue = self._external_share_source_consistency_decision(
                    user,
                    reviewed_text,
                    reason=reason,
                    topic=topic,
                    motive=motive,
                    action_context=review_context,
                )
                if rewritten_source_issue:
                    original_source_issue = self._external_share_source_consistency_decision(
                        user,
                        text,
                        reason=reason,
                        topic=topic,
                        motive=motive,
                        action_context=review_context,
                    )
                    if original_source_issue is None:
                        reviewed_text = text
                        note = "终审改写破坏了真实来源，已恢复复核前原文"
                    else:
                        source_text = str(rewritten_source_issue.get("source_text") or "").strip()
                        safe_reference = self._external_share_fallback_reference(source_text)
                        if not safe_reference:
                            return {
                                "decision": "drop",
                                "text": "",
                                "reason": "终审改写后的来源不一致且无法恢复真实来源",
                                "hard": True,
                            }
                        reviewed_text = safe_reference
                        note = "终审改写破坏了真实来源，已恢复确定性来源文本"
        normalized_payload = self._normalize_proactive_review_decision_policy(
            user,
            {
                "decision": decision,
                "text": reviewed_text,
                "reason": note,
            },
            strength=strength,
            source="model",
        )
        decision = str(normalized_payload.get("decision") or decision).strip().lower()
        reviewed_text = str(normalized_payload.get("text") or reviewed_text or "").strip()
        note = _single_line(normalized_payload.get("reason") or note, 120)
        if decision == "send" and str(local.get("decision") or "") == "rewrite" and str(local.get("text") or "").strip():
            reviewed_text = str(local.get("text") or "").strip()
            decision = "rewrite"
            note = _single_line(note or local.get("reason") or "本地轻改写后放行", 120)
        final_text = reviewed_text if decision == "rewrite" and reviewed_text else text
        link_platform_mismatch = self._proactive_link_platform_mismatch_reason(final_text)
        if decision in {"send", "rewrite"} and link_platform_mismatch:
            decision = "drop"
            reviewed_text = ""
            note = link_platform_mismatch
        if decision in {"send", "rewrite"} and self._framework_agent_meta_summary_leak(final_text):
            decision = "drop"
            reviewed_text = ""
            note = "主动候选疑似工具循环/内部发送摘要泄漏"
        logger.info(
            "[PrivateCompanion] Proactive final content gate: decision=%s raw=%s strength=%s elapsed=%dms reason=%s",
            decision,
            original_decision,
            strength,
            int((time.perf_counter() - started) * 1000),
            note or "-",
        )
        return {
            "decision": decision,
            "text": reviewed_text,
            "reason": note or "主动发送前价值复核",
        }

    def _pop_framework_captured_send_payload(
        self,
        umo: str,
    ) -> tuple[str, str, list[Any]]:
        captured = self._framework_captured_send_cache.pop(str(umo or ""), [])
        if not captured:
            return "", "", []
        text_parts: list[str] = []
        image_path = ""
        extra_components: list[Any] = []
        for call in captured:
            messages = getattr(call, "messages", [])
            if not isinstance(messages, list):
                continue
            for item in messages:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").strip().lower()
                if item_type == "plain":
                    text_value = self._sanitize_captured_plain_text(item.get("text"))
                    if text_value:
                        text_parts.append(text_value)
                    continue
                if item_type == "image":
                    path_value = str(item.get("path") or "").strip()
                    if path_value and os.path.exists(path_value) and not image_path:
                        image_path = path_value
                        continue
                component = self._captured_framework_message_component(item)
                if component is not None:
                    extra_components.append(component)
        return "\n".join(part for part in text_parts if part).strip(), image_path, extra_components

    def _captured_framework_message_component(self, item: dict[str, Any]) -> Any | None:
        item_type = str(item.get("type") or "").strip().lower()
        path_value = str(item.get("path") or "").strip()
        url_value = str(item.get("url") or "").strip()
        if item_type == "mention_user":
            mention_user_id = item.get("mention_user_id")
            return At(qq=mention_user_id) if mention_user_id else None
        if item_type == "image":
            if url_value:
                try:
                    return Image.fromURL(url_value)
                except Exception:
                    return None
            return None
        if CoreMessageComponents is None:
            return None
        if item_type in {"record", "video"}:
            component_cls = getattr(CoreMessageComponents, item_type.capitalize(), None)
            if component_cls is None:
                return None
            try:
                if path_value and os.path.exists(path_value):
                    return component_cls.fromFileSystem(path_value)
                if url_value:
                    return component_cls.fromURL(url_value)
            except Exception:
                return None
            return None
        if item_type == "file":
            component_cls = getattr(CoreMessageComponents, "File", None)
            if component_cls is None:
                return None
            name = _single_line(item.get("text"), 120) or os.path.basename(path_value or url_value) or "file"
            if path_value and os.path.exists(path_value):
                return component_cls(name=name, file=path_value)
            if url_value:
                return component_cls(name=name, url=url_value)
        return None

    def _sanitize_captured_plain_text(self, raw_text: Any) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return ""
        kept: list[str] = []
        for raw_line in text.replace("\r", "\n").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._is_proactive_delivery_receipt_text(line):
                continue
            if self._looks_like_internal_provider_error_text(line):
                continue
            kept.append(line)
        cleaned = "\n".join(kept).strip().strip('"').strip("'")
        cleaned = cleaned.replace("（图片已送达）", "").replace("(图片已送达)", "")
        tts_cleaner = getattr(self, "_clean_tool_plain_text_tts_markup", None)
        if callable(tts_cleaner):
            cleaned = tts_cleaner(cleaned)
        else:
            cleaned = re.sub(r"</?(?:pc[_-]?tts|t{2,}s)\b[^>]*>", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if self._looks_like_internal_provider_error_text(cleaned):
            return ""
        return cleaned[:260]

    async def _generate_voice_note_via_framework(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        *,
        target: str,
        strict_tts: bool = False,
    ) -> str:
        umo = str(user.get("umo") or target or "").strip()
        if not umo:
            return ""
        prompt = self._build_framework_voice_prompt(
            user=user,
            name=name,
            reason=reason,
            target=target,
            strict_tts=strict_tts,
        )
        try:
            raw_text = await self._run_framework_agent_text(
                umo=umo,
                prompt=prompt,
                name=name,
                label="proactive_voice",
                max_steps=20,
            )
            return str(raw_text or "").strip()
        except Exception as exc:
            if self._is_sqlite_locked_error(exc):
                logger.warning("[PrivateCompanion] 主动语音主链被会话数据库锁住,本轮跳过并等待下次调度: %s", _single_line(umo, 120))
            else:
                logger.warning("[PrivateCompanion] 主动语音主链内容生成失败: %s", exc)
            return ""

    async def _generate_proactive_message_with_llm(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        action_context: str = "",
        action: str = "message",
        motive: str = "",
    ) -> str:
        user.pop("_proactive_render_failure_stage", None)
        if not self.enable_llm_proactive_message:
            user["_proactive_render_failure_stage"] = "主动消息模型生成已关闭"
            return ""
        raw_text = await self._generate_proactive_message_via_framework(
            user,
            name,
            reason,
            action_context=action_context,
            action=action,
            motive=motive,
        )
        failure_stages: list[str] = []
        if raw_text:
            finalized, failure_stage = await self._finalize_proactive_generated_text(
                user,
                raw_text,
                name=name,
                reason=reason,
                action=action,
                action_context=action_context,
                motive=motive,
            )
            if finalized:
                return finalized
            failure_stages.append(f"框架主链{failure_stage or '处理后为空'}")
        else:
            failure_stages.append("框架主链返回空文本")

        fallback_text = await self._generate_proactive_message_direct_fallback(
            user,
            name=name,
            reason=reason,
            action=action,
            action_context=action_context,
            motive=motive,
        )
        if fallback_text:
            finalized, failure_stage = await self._finalize_proactive_generated_text(
                user,
                fallback_text,
                name=name,
                reason=reason,
                action=action,
                action_context=action_context,
                motive=motive,
            )
            if finalized:
                logger.info(
                    "[PrivateCompanion] 主动框架主链为空后已由直接人格化兜底恢复: user=%s reason=%s",
                    _single_line(user.get("user_id"), 40),
                    reason,
                )
                return finalized
            failure_stages.append(f"直接人格化兜底{failure_stage or '处理后为空'}")
        else:
            failure_stages.append("直接人格化兜底返回空文本")

        failure_detail = "；".join(failure_stages)[:240]
        user["_proactive_render_failure_stage"] = failure_detail
        logger.warning(
            "[PrivateCompanion] 主动正文两级生成均未产出: user=%s reason=%s stage=%s",
            _single_line(user.get("user_id"), 40),
            reason,
            failure_detail,
        )
        return ""

    async def _generate_proactive_message_direct_fallback(
        self,
        user: dict[str, Any],
        *,
        name: str,
        reason: str,
        action: str,
        action_context: str = "",
        motive: str = "",
    ) -> str:
        relationship_sanitizer = getattr(self, "_sanitize_generation_relationship_context", None)

        def sanitize_relationship_source(value: Any, source: str) -> str:
            if callable(relationship_sanitizer):
                try:
                    return relationship_sanitizer(value, source=source)
                except Exception:
                    pass
            return str(value or "").strip()

        topic = _single_line(
            sanitize_relationship_source(user.get("planned_proactive_topic"), "proactive_fallback.topic"),
            120,
        )
        planned_motive = _single_line(
            sanitize_relationship_source(
                motive or user.get("planned_proactive_motive"),
                "proactive_fallback.motive",
            ),
            220,
        )
        context = sanitize_relationship_source(
            self._format_action_prompt_context(action, action_context),
            "proactive_fallback.action_context",
        )
        if (
            (context.startswith("message：") and "图片动作本轮未产出" not in context)
            or context in {"普通文字", "普通私聊文本"}
        ):
            context = ""
        reference = "\n".join(
            part
            for part in (
                f"主动话题：{topic}" if topic else "",
                f"想表达：{planned_motive}" if planned_motive else "",
                f"真实动作上下文：{context}" if context else "",
            )
            if part
        )
        balance_hint_getter = getattr(self, "_format_balance_awareness_prompt", None)
        if reason == "low_balance" and callable(balance_hint_getter):
            balance_hint = balance_hint_getter(user, reason=reason)
            if balance_hint:
                reference = f"{reference}\n{balance_hint}" if reference else balance_hint
        environment_hint_getter = getattr(self, "_format_environment_change_prompt", None)
        if reason == "environment_change" and callable(environment_hint_getter):
            environment_hint = environment_hint_getter(user, reason=reason)
            if environment_hint:
                reference = f"{reference}\n{environment_hint}" if reference else environment_hint
        personal_goal_hint_getter = getattr(self, "_format_personal_goal_prompt", None)
        if reason == "personal_goal_progress" and callable(personal_goal_hint_getter):
            personal_goal_hint = personal_goal_hint_getter(user, reason=reason)
            if personal_goal_hint:
                reference = f"{reference}\n{personal_goal_hint}" if reference else personal_goal_hint
        memo_hint_getter = getattr(self, "_format_memo_note_prompt", None)
        if reason == "memo_note_reminder" and callable(memo_hint_getter):
            memo_hint = memo_hint_getter(user, reason=reason)
            if memo_hint:
                reference = f"{reference}\n{memo_hint}" if reference else memo_hint
        if not reference:
            reference = f"自然地向{name or '对方'}主动说一句与当前状态有关、低压力且无需立即回复的话。"
        reference = sanitize_relationship_source(reference, "proactive_fallback.reference")
        if not reference:
            reference = f"自然地向{name or '对方'}主动说一句低压力且无需立即回复的话。"
        return await self._rewrite_reference_reply_with_persona(
            reference,
            scene=f"主动开口；原因={reason or 'check_in'}；动作={action or 'message'}",
            user=user,
            fallback_text="",
            task="proactive_message_fallback",
            max_chars=180,
            allow_fallback=False,
        )

    async def _finalize_proactive_generated_text(
        self,
        user: dict[str, Any],
        raw_text: str,
        *,
        name: str,
        reason: str,
        action: str,
        action_context: str = "",
        motive: str = "",
    ) -> tuple[str, str]:
        cleaned = self._sanitize_action_boundaries(
            self._sanitize_proactive_text(raw_text),
            reason=reason,
            action=action,
            action_context=action_context,
            has_real_image="真实图片文件：" in action_context or "图片路径：" in action_context,
        )
        if not cleaned:
            return "", "在动作边界清洗后为空"
        cleaned, repaired_address = self._repair_proactive_recipient_address(cleaned, user, name)
        if repaired_address:
            logger.warning(
                "[PrivateCompanion] 主动消息已纠正串用户句首称呼: user=%s wrong=%s replacement=%s",
                _single_line(user.get("user_id"), 40),
                repaired_address,
                _single_line(name or user.get("nickname"), 40) or "你",
            )
        remaining_wrong_address = self._wrong_proactive_recipient_address(cleaned, user, name)
        if remaining_wrong_address:
            return "", f"含其他用户专属称呼：{remaining_wrong_address}"
        if self._is_overabstract_proactive_text(cleaned, action=action):
            cleaned = self._ground_proactive_text(
                cleaned,
                reason=reason,
                action=action,
                action_context=action_context,
            )
        cleaned = self._apply_proactive_style_variation(cleaned, user)
        cleaned = self._collapse_multi_candidate_proactive_text(cleaned, user=user, name=name)
        cleaned = self._repair_proactive_subject_drift(cleaned, reason=reason, action=action, action_context=action_context)
        if reason == "morning_greeting":
            cleaned = self._strip_morning_meal_questions(cleaned)
        cleaned = self._visible_text_without_tts_reading(cleaned, limit=1000)
        if not cleaned:
            return "", "在主客体/可见文本清洗后为空"
        relay_claim_note = self._unexecuted_relay_claim_reason(cleaned, action_context=action_context)
        if relay_claim_note:
            logger.info(
                "[PrivateCompanion] 主动消息含未执行转述承诺,已丢弃: reason=%s text=%s",
                relay_claim_note,
                _single_line(cleaned, 120),
            )
            return "", f"含未执行转述承诺：{_single_line(relay_claim_note, 80)}"
        if self._should_drop_vague_generic_proactive(user, reason=reason, action=action, action_context=action_context, text=cleaned):
            return "", "泛化主动缺少具体由头"
        if self._should_drop_misstaged_proactive_text(cleaned, reason=reason, action=action):
            return "", "错接旧对话或时段"
        reviewed = await self._review_proactive_message_stance(
            user,
            cleaned,
            reason=reason,
            action=action,
            action_context=action_context,
            motive=motive,
        )
        if not reviewed:
            return "", "回复空气复核后为空"
        reviewed, repaired_review_address = self._repair_proactive_recipient_address(reviewed, user, name)
        if repaired_review_address:
            logger.warning(
                "[PrivateCompanion] 主动复核结果已纠正串用户称呼: user=%s wrong=%s",
                _single_line(user.get("user_id"), 40),
                repaired_review_address,
            )
        remaining_review_address = self._wrong_proactive_recipient_address(reviewed, user, name)
        if remaining_review_address:
            return "", f"回复空气复核引入其他用户专属称呼：{remaining_review_address}"
        reviewed = self._trim_proactive_status_inventory(reviewed)
        reviewed = self._trim_performative_self_state_tail(reviewed)
        if reason == "morning_greeting":
            reviewed = self._strip_morning_meal_questions(reviewed)
        finalized = self._normalize_proactive_sentence_flow(reviewed)
        return (finalized, "") if finalized else ("", "最终句式整理后为空")

    @staticmethod
    def _strip_morning_meal_questions(text: str) -> str:
        """Keep a morning greeting while removing an accidentally appended meal question."""
        source = str(text or "").strip()
        if not source:
            return ""
        query_pattern = re.compile(
            r"(?:早餐|早饭).{0,12}(?:吗|没|没有|什么|啥|呢|[？?])"
            r"|(?:吃|喝).{0,6}(?:了吗|了没|没有|什么|啥)(?:呢|[？?])?"
        )
        kept: list[str] = []
        for unit in re.split(r"(?<=[。！？!?])\s*|\n+", source):
            candidate = unit.strip()
            if not candidate:
                continue
            match = query_pattern.search(candidate)
            if not match:
                kept.append(candidate)
                continue
            prefix = candidate[: match.start()].rstrip(" ，,；;、")
            if prefix:
                kept.append(prefix)
        return "\n".join(kept).strip()

    def _proactive_reply_air_flags(
        self,
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str = "",
    ) -> list[str]:
        cleaned = _single_line(text, 260)
        if not cleaned or action not in {"message", "photo_text"}:
            return []
        flags: list[str] = []
        reply_opener_pattern = (
            r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就|你说呢|要不|不然|"
            r"确实|对呀|对啊|是吧|也是|哈哈[,，\s]*我也|我也觉得|你说得对)"
        )
        if re.search(reply_opener_pattern, cleaned):
            flags.append("reply_air_opener")
        if re.search(r"(?:刚看到|才看到|刚才看到|看到你(?:刚刚|刚才)?发|看到你说)", cleaned):
            flags.append("pretends_recent_inbound")
        if re.search(r"你(?:刚刚|刚才|现在)?(?:叫|喊|问|说|发|来找|找|催)我", cleaned):
            flags.append("inverts_initiator")
        if re.search(r"(?:你问|你说|你刚才说|你刚刚说)[^。！？\n]{0,24}(?:我觉得|我也|确实|可以|好呀|好啊)", cleaned):
            flags.append("answers_old_context")
        if self._is_proactive_delivery_receipt_text(cleaned):
            flags.append("delivery_receipt")
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting", "check_in"} and re.search(
            r"(?:一直等着|等你问|你到时候|到时候叫|到时候喊|那就这么说定|按你说的)",
            cleaned,
        ):
            flags.append("stale_agreement")
        if "真实图片文件：" not in str(action_context or "") and "图片路径：" not in str(action_context or ""):
            if re.search(r"(?:发你看|给你看图|看图|图里|照片里|图片里)", cleaned):
                flags.append("claims_missing_media")
        return list(dict.fromkeys(flags))

    async def _review_proactive_message_stance(
        self,
        user: dict[str, Any],
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str = "",
        motive: str = "",
    ) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        relationship_sanitizer = getattr(self, "_sanitize_generation_relationship_context", None)

        def sanitize_relationship_source(value: Any, source: str) -> str:
            if callable(relationship_sanitizer):
                try:
                    return relationship_sanitizer(value, source=source)
                except Exception:
                    pass
            return str(value or "").strip()

        flags = self._proactive_reply_air_flags(
            cleaned,
            reason=reason,
            action=action,
            action_context=action_context,
        )
        if not flags:
            return cleaned
        if not bool(getattr(self, "enable_proactive_message_review", True)):
            logger.info(
                "[PrivateCompanion] 主动消息疑似回复空气,主动终审关闭已丢弃: flags=%s text=%s",
                ",".join(flags),
                _single_line(cleaned, 120),
            )
            return ""
        mode = self._effective_proactive_review_mode()
        if mode == "local_only":
            logger.info(
                "[PrivateCompanion] 主动消息疑似回复空气,仅本地保护已丢弃: flags=%s text=%s",
                ",".join(flags),
                _single_line(cleaned, 120),
            )
            return ""
        intent_hint = self._format_proactive_generation_intent_hint(
            user,
            reason=reason,
            action=action,
            motive=motive,
            action_context=action_context,
        )
        intent_hint = sanitize_relationship_source(intent_hint, "proactive_review.intent")
        review_motive = _single_line(
            sanitize_relationship_source(
                motive or user.get("planned_proactive_motive"),
                "proactive_review.motive",
            ),
            160,
        )
        review_topic = _single_line(
            sanitize_relationship_source(
                user.get("planned_proactive_topic"),
                "proactive_review.topic",
            ),
            120,
        )
        review_action_context = _single_line(
            sanitize_relationship_source(action_context, "proactive_review.action_context"),
            260,
        )
        persona = await self._resolve_proactive_persona_prompt(user)
        proactive_voice = self._format_proactive_voice_prompt() if callable(getattr(self, "_format_proactive_voice_prompt", None)) else ""
        expression_formatter = getattr(self, "_format_expression_voice_for_prompt", None)
        expression_voice = (
            expression_formatter(
                scope="proactive",
                target_id=_single_line(user.get("user_id") or user.get("id"), 80),
                context_owner=user,
                stage_owner=user,
            )
            if callable(expression_formatter)
            else ""
        )
        recipient_identity = self._format_proactive_recipient_identity_guard(
            user,
            _single_line(user.get("nickname"), 40),
        )
        prompt = f"""
把下面这条主动私聊消息改成真正的主动开口。
它不是在回复用户刚发来的消息；聊天历史只能当背景。

【原主动消息】
{cleaned}

【问题】
{", ".join(flags)}

【主动原因】
{reason or "check_in"}

【动机/话题】
{review_motive}
{review_topic}

【动作上下文】
{review_action_context or "（无）"}

【内在约束】
{intent_hint or "（无额外约束）"}

【完整人格】
{persona[:2600] if persona else "（没有解析到显式人格；尽量保留原文语气，不要另造一种通用陪伴人格）"}

【主动开口风格】
{proactive_voice or "（无额外主动风格；保持原文已有的人格语气）"}

【已形成的表达底色】
{expression_voice or "（无额外表达底色）"}

【当前收件人】
{recipient_identity or "不要猜名字或套用其他对象的专属称呼。"}

要求：
- 只输出要发送的正文
- 不要把“用户”“对方”“收信人”这类内部称呼写进正文；需要称呼时用自然的“你”或对方昵称
- 不要写成“好呀/确实/我也觉得/刚看到/你刚刚问我/你来找我了”
- 不要把历史消息当成当前正在发生的对话
- 没有真实图片或工具结果时，只写聊天内容本身，不描述动作结果
- 如果原文只是过程状态或工具结果，请不要改写成另一种状态汇报；改不成自然聊天就输出空文本
- 改写后仍要贴合内在约束里的候选语义；不能把分享型改成泛泛问候，也不能把低压关心改成追问
- 只修正“回复空气”的问题；不得把原文改成另一种人格，也不得降低或升级当前关系亲密度
- 尽量 1 到 2 句，像自然想起对方后随手说一句
""".strip()
        started = time.perf_counter()
        rewritten = await self._llm_call(
            prompt,
            max_tokens=180,
            provider_id=self._task_provider(self.response_review_provider_id, self.mai_style_provider_id),
            task="response_review",
        )
        candidate = self._sanitize_proactive_text(str(rewritten or "").strip())
        candidate = self._sanitize_action_boundaries(
            candidate,
            reason=reason,
            action=action,
            action_context=action_context,
            has_real_image="真实图片文件：" in action_context or "图片路径：" in action_context,
        )
        meta_leak_checker = getattr(self, "_response_review_meta_leak_reason", None)
        if callable(meta_leak_checker) and meta_leak_checker(candidate):
            logger.error(
                "[PrivateCompanion] 回复/主动复核返回内部判断，已丢弃: output=%s",
                _single_line(candidate, 180),
            )
            return ""
        logger.info(
            "[PrivateCompanion] 回复/主动复核完成: mode=%s flags=%s elapsed=%dms before=%s after=%s",
            mode,
            ",".join(flags),
            int((time.perf_counter() - started) * 1000),
            _single_line(cleaned, 100),
            _single_line(candidate, 100),
        )
        if not candidate:
            return ""
        if len(candidate) > max(len(cleaned) + 80, 260):
            return ""
        if re.search(r"(提示词|系统|JSON|改写后|以下是|主动消息|聊天历史)", candidate, re.IGNORECASE):
            return ""
        remaining_flags = self._proactive_reply_air_flags(
            candidate,
            reason=reason,
            action=action,
            action_context=action_context,
        )
        if remaining_flags:
            logger.info(
                "[PrivateCompanion] 回复/主动复核后仍疑似回复空气,已丢弃: flags=%s text=%s",
                ",".join(remaining_flags),
                _single_line(candidate, 120),
            )
            return ""
        return candidate

    def _repair_proactive_subject_drift(
        self,
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str = "",
    ) -> str:
        cleaned = str(text or "").strip()
        if not cleaned or action != "message":
            return cleaned
        state_context = "\n".join(
            _single_line(part, 260)
            for part in (
                action_context,
                self._format_schedule_context_for_prompt(),
                self._format_plan_item_for_prompt(self._get_current_plan_item(self._native_daily_plan_view({}))),
            )
            if _single_line(part, 260)
        )
        bot_task_markers = (
            "作业", "写题", "题", "上课", "放学", "课本", "书桌", "试卷", "复习", "预习",
            "任务", "代码", "创作", "草稿", "报告", "练习",
        )
        if not any(token in state_context for token in bot_task_markers):
            return cleaned
        user_progress_patterns = (
            r"你[^。！？\n]{0,12}(?:作业|题|试卷|课|任务|代码|报告|草稿|练习)[^。！？\n]{0,18}(?:还差多少|写完了吗|做完了吗|弄完了吗|忙完了吗|上完了吗|差多少|完成了吗|怎么样了)[呀啊嘛呢了]*[？?。!！]?",
            r"(?:作业|题|试卷|课|任务|代码|报告|草稿|练习)[^。！？\n]{0,12}(?:还差多少|写完了吗|做完了吗|弄完了吗|忙完了吗|上完了吗|差多少|完成了吗)[呀啊嘛呢了]*[？?。!！]?",
        )
        repaired = cleaned
        changed = False
        for pattern in user_progress_patterns:
            repaired, count = re.subn(pattern, "", repaired)
            changed = changed or count > 0
        if not changed:
            return cleaned
        repaired = re.sub(r"\s+", " ", repaired).strip(" ，,。！？!?、")
        if repaired:
            logger.info(
                "[PrivateCompanion] 主动消息修正主客体错位问句: reason=%s before=%s after=%s",
                reason,
                _single_line(cleaned, 120),
                _single_line(repaired, 120),
            )
            return repaired
        logger.info(
            "[PrivateCompanion] 主动消息主客体错位且无剩余自然内容,已丢弃本轮生成: reason=%s text=%s",
            reason,
            _single_line(cleaned, 120),
        )
        return ""

    def _should_drop_misstaged_proactive_text(self, text: str, *, reason: str, action: str) -> bool:
        cleaned = _single_line(text, 220)
        if not cleaned:
            return True
        if action != "message" or reason not in {"morning_greeting", "noon_greeting", "evening_greeting", "check_in"}:
            return False
        reply_openers = ("好呀", "好啊", "可以呀", "可以啊", "行呀", "行啊", "嗯好", "那就", "你说呢", "要不", "不然")
        old_invite_markers = (
            "下午陪你", "陪你出去", "出去走走", "五点", "放学之后", "下班之后",
            "到时候叫我", "到时候喊我", "到时候", "垫上", "我哪来的钱",
            "一直等着", "等着呢", "想去哪", "去哪儿", "去哪逛", "哪儿逛", "哪里逛", "去逛",
        )
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting"} and cleaned.startswith(reply_openers) and any(token in cleaned for token in old_invite_markers):
            logger.info(
                "[PrivateCompanion] 主动消息疑似把旧邀约当成当前回复,已丢弃: reason=%s text=%s",
                reason,
                cleaned,
            )
            return True
        if reason in {"morning_greeting", "noon_greeting", "evening_greeting"}:
            stale_reply_patterns = (
                r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就).{0,30}(?:你到时候|到时候你|到时候叫|到时候喊)",
                r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就).{0,30}(?:我得|我得等|我只能|我可以).{0,18}(?:之后|以后|才行)",
                r"^(?:你说呢|要不|不然).{0,30}(?:我哪来|哪来的钱|先帮我|帮我垫|垫上)",
                r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就|你说呢|要不|不然).{0,36}(?:下午|五点|放学|下班|垫上|哪来的钱)",
                r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就).{0,30}(?:一直等|等着呢|等你).{0,30}(?:去哪|哪儿|哪里|逛|走走)",
                r"^(?:好呀|好啊|可以呀|可以啊|行呀|行啊|嗯好|那就).{0,36}(?:想去哪|去哪儿|去哪逛|哪儿逛|哪里逛|去逛)",
            )
            if any(re.search(pattern, cleaned) for pattern in stale_reply_patterns):
                logger.info(
                    "[PrivateCompanion] 主动消息疑似接续旧对话而非主动开口,已丢弃: reason=%s text=%s",
                    reason,
                    cleaned,
                )
                return True
        return False

    def _proactive_time_mismatch_reason(self, text: str, *, reason: str, action: str) -> str:
        if str(action or "message").strip() != "message":
            return ""
        cleaned = _single_line(text, 240)
        if not cleaned:
            return ""
        now = self._environment_now()
        minutes = now.hour * 60 + now.minute
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        current_text = _single_line(self._format_plan_item_for_prompt(current_item), 180)
        current_is_school_or_afternoon = bool(re.search(r"(上课|课间|放学|校门|教室|作业|书包|回家路上)", current_text))
        if reason == "morning_greeting" and re.search(r"(晚上|晚安|睡觉|好梦|睡前|夜里|放学|下班)", cleaned):
            return f"早间主动含有非早间场景: {cleaned}"
        if reason == "noon_greeting" and re.search(r"(早安|刚醒|赖床|晚安|好梦|睡觉|夜里)", cleaned):
            return f"午间主动含有错时问候: {cleaned}"
        if reason == "evening_greeting" and re.search(r"(早安|刚醒|赖床|上午|中午吃了吗)", cleaned):
            return f"晚间主动含有错时问候: {cleaned}"
        if minutes < 12 * 60 and re.search(r"(放学|放学就|放学后|放学回来|下课回来|下午回来|傍晚回来|晚上回来)", cleaned):
            return f"上午主动提前叙述放学/傍晚场景: {cleaned}"
        if minutes < 15 * 60 and re.search(r"(五点|5点|17点|下午五点|傍晚|晚上见|晚点回来找你)", cleaned):
            return f"当前时段过早,主动含有傍晚/五点场景: {cleaned}"
        if minutes >= 22 * 60 and re.search(r"(放学|下课|下午|傍晚|出去走走|等我回来找你)", cleaned):
            return f"夜间主动含有已过时段场景: {cleaned}"
        if re.search(r"(放学|下课|校门|教室|书包|回家路上)", cleaned) and not current_is_school_or_afternoon and not (14 * 60 <= minutes <= 19 * 60):
            return f"主动文本与当前日程不匹配: 当前={current_text or '无'} 文本={cleaned}"
        return ""


    def _collapse_multi_candidate_proactive_text(self, text: str, *, user: dict[str, Any], name: str = "") -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if len(lines) >= 2:
            collapsed_lines = self._collapse_near_duplicate_proactive_lines(lines)
            if len(collapsed_lines) < len(lines):
                result = "\n".join(collapsed_lines).strip()
                logger.info(
                    "[PrivateCompanion] 主动消息已合并同轮近似候选: before=%s after=%s",
                    _single_line(cleaned, 180),
                    _single_line(result, 160),
                )
                return result or cleaned
        units: list[str] = []
        for line in lines or [cleaned]:
            units.extend(self._split_proactive_sentence_units(line))
        units = [unit.strip() for unit in units if unit and unit.strip()]
        if len(units) <= 2:
            return cleaned

        opener_tokens = [
            _single_line(name, 16),
            _single_line(user.get("nickname") if isinstance(user, dict) else "", 16),
            _single_line(getattr(self, "default_nickname", ""), 16),
        ]
        first_opener = ""
        match = re.match(r"^([\w\u4e00-\u9fffぁ-んァ-ヶー]{1,8})[，,、\s]", units[0])
        if match:
            first_opener = match.group(1)
            opener_tokens.append(first_opener)
        opener_tokens = [token for token in dict.fromkeys(opener_tokens) if token]

        repeated_opener_index = 0
        for index, unit in enumerate(units[1:], start=1):
            if any(unit.startswith(token) and index >= 2 for token in opener_tokens):
                repeated_opener_index = index
                break
        if repeated_opener_index:
            units = units[:repeated_opener_index]

        if self._private_user_role(user) == "friend" and len(units) > 2:
            units = units[:2]
        return "\n".join(units).strip() or cleaned

    def _proactive_candidate_core_text(self, text: str) -> str:
        cleaned = _single_line(text, 260)
        if not cleaned:
            return ""
        cleaned = re.sub(r"^[\w\u4e00-\u9fffぁ-んァ-ヶー]{1,8}[，,、\s]+", "", cleaned)
        cleaned = re.sub(r"^(?:早上好|早安|上午好|中午好|午安|下午好|晚上好)[。！？!?…~～,，\s]*", "", cleaned)
        cleaned = re.sub(r"^(?:唔|嗯|诶|欸|啊|嗨|嘿)[。！？!?…~～,，\s]*", "", cleaned)
        cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", cleaned)
        filler_tokens = ("刚刚", "刚才", "现在", "今天", "这会儿", "好像", "感觉", "一点", "有点")
        for token in filler_tokens:
            cleaned = cleaned.replace(token, "")
        return cleaned

    def _proactive_candidate_bigrams(self, text: str) -> set[str]:
        cleaned = self._proactive_candidate_core_text(text)
        if len(cleaned) < 2:
            return set()
        return {cleaned[index : index + 2] for index in range(len(cleaned) - 1)}

    def _collapse_near_duplicate_proactive_lines(self, lines: list[str]) -> list[str]:
        kept: list[str] = []
        for line in lines:
            current = line.strip()
            if not current:
                continue
            current_core = self._proactive_candidate_core_text(current)
            duplicate_index = -1
            for index, old in enumerate(kept):
                old_core = self._proactive_candidate_core_text(old)
                if not current_core or not old_core:
                    continue
                shorter = min(len(current_core), len(old_core))
                if shorter < 8:
                    continue
                same_core = current_core == old_core
                contained = current_core in old_core or old_core in current_core
                current_bigrams = self._proactive_candidate_bigrams(current)
                old_bigrams = self._proactive_candidate_bigrams(old)
                bigram_overlap = 0.0
                if current_bigrams and old_bigrams:
                    bigram_overlap = len(current_bigrams & old_bigrams) / max(1, min(len(current_bigrams), len(old_bigrams)))
                if same_core or contained or bigram_overlap >= 0.86:
                    duplicate_index = index
                    break
            if duplicate_index < 0:
                kept.append(current)
                continue
            old = kept[duplicate_index]
            old_core = self._proactive_candidate_core_text(old)
            prefer_current = (
                len(current_core) < len(old_core)
                or (len(current) + 6 < len(old) and not re.search(r"^(?:早上好|早安|上午好|中午好|午安|下午好|晚上好)", current))
            )
            if prefer_current:
                kept[duplicate_index] = current
        return kept

    def _should_drop_vague_generic_proactive(
        self,
        user: dict[str, Any],
        *,
        reason: str,
        action: str,
        action_context: str = "",
        text: str = "",
    ) -> bool:
        if reason != "check_in" or action != "message":
            return False
        if _safe_int(user.get("ignored_streak"), 0, 0) < 2:
            return False
        context = _single_line(action_context, 180)
        if context and not context.startswith("message") and "普通私聊文本" not in context:
            return False
        cleaned = _single_line(text, 160)
        if not cleaned:
            return True
        vague_tokens = ("想找你", "来看看你", "刷存在感", "最近忙不忙", "辛苦了", "在吗", "有点想你", "没什么事", "就是想")
        concrete_markers = ("刚", "路上", "窗", "雨", "书", "饭", "水", "图", "群", "视频", "作业", "游戏", "梦")
        return any(token in cleaned for token in vague_tokens) and not any(token in cleaned for token in concrete_markers)

    def _apply_proactive_style_variation(self, text: str, user: dict[str, Any]) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        items = user.get("action_consequences")
        if not isinstance(items, list):
            return cleaned
        recent_texts = [
            _single_line(item.get("text"), 80)
            for item in items[-12:]
            if isinstance(item, dict) and _single_line(item.get("text"), 80)
        ]
        if not recent_texts:
            return cleaned
        current_opening = re.split(r"[，,。！？!?…\s]", _single_line(cleaned, 80), maxsplit=1)[0][:6]
        repeated_opening = current_opening and any(
            re.split(r"[，,。！？!?…\s]", text, maxsplit=1)[0][:6] == current_opening
            for text in recent_texts
        )
        proactive_voice = str(getattr(self, "persona_proactive_voice_prompt", "") or "")
        # Repetition control must not erase an opening explicitly defined by the persona.
        if repeated_opening and current_opening not in proactive_voice:
            cleaned = re.sub(r"^(唔|嗯|诶|啊|欸)[…\.。!！?？~～\s，,]*", "", cleaned).strip()
            cleaned = re.sub(r"^(刚好|突然|我就是|我来|来找你)[^，,。！？!?…\n]{0,16}[，,。！？!?…\s]*", "", cleaned).strip()
        if sum(cleaned.count(token) for token in ("唔", "嗯", "诶", "呀", "啦", "嘛", "哦", "呢")) >= 5:
            cleaned = re.sub(r"(呀|啦|嘛|哦|呢)(?=.*\1)", "", cleaned)
        # 整句重复检测：若与最近 12 条完全相同，做轻微变换
        normalized_current = re.sub(r"[\s，,。！？!?…]+", "", cleaned)[:40]
        if normalized_current and len(normalized_current) >= 8:
            for hist in recent_texts:
                normalized_hist = re.sub(r"[\s，,。！？!?…]+", "", hist)[:40]
                if normalized_current == normalized_hist:
                    import random as _rnd
                    cleaned = _rnd.choice(["说起来，", "对了，", "话说，", "刚刚想到，"]) + cleaned
                    break
        return cleaned or str(text or "").strip()

    def _format_action_prompt_context(self, action: str, action_context: str) -> str:
        context = str(action_context or "").strip()
        if not context:
            return "普通文字"
        return _single_line(self._sanitize_action_context_text(action, context), 420)

    def _sanitize_action_boundaries(
        self,
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str = "",
        has_real_image: bool = False,
    ) -> str:
        cleaned = self._soften_social_proactive_text(text, action=action)
        if not cleaned:
            return ""
        if not has_real_image and "photo_text" not in action:
            cleaned = self._remove_unbacked_media_claims(cleaned)
        if "screen_peek" in action:
            photo_patterns = (
                "拍了张照片",
                "拍了照片",
                "拍了自拍",
                "自拍",
                "风景照",
                "窗外阳光",
                "要看看吗",
                "给你看照片",
                "发你照片",
                "看图",
            )
            if any(pattern in cleaned for pattern in photo_patterns):
                return ""
        if "poke" in action and "photo_text" not in action and "voice" not in action:
            cleaned = cleaned.replace("戳一戳", "戳你一下")
            cleaned = cleaned.replace("我刚刚戳了你", "我刚戳你了")
            cleaned = cleaned.replace("我刚刚戳了你一下", "我刚戳你了")
        if action == "voice":
            cleaned = cleaned.replace("我给你发了一条语音", "刚给你发了条语音")
            cleaned = cleaned.replace("我发了一条语音", "刚给你发了条语音")
            cleaned = cleaned.replace("我生成了一条语音", "刚给你发了条语音")
            cleaned = cleaned.replace("我合成了一条语音", "刚给你发了条语音")
            cleaned = cleaned.replace("要不要听", "你有空再听嘛")
            cleaned = cleaned.replace("要听吗", "你有空再听嘛")
        if action == "photo_text":
            if has_real_image:
                if reason not in {"bili_video_share", "news_share", "web_exploration_share"}:
                    cleaned = self._repair_non_external_title_share_text(
                        cleaned,
                        reason=reason,
                        action_context=action_context,
                    )
                replacements = {
                    "我画了一张图": "这个画面",
                    "我刚画了张图": "这个画面",
                    "我生成了一张图": "这个画面",
                    "我做了张图": "这个画面",
                    "我生了一张图": "这个画面",
                    "我渲染了一张图": "这个画面",
                    "画面是": "画面里是",
                }
                for old, new in replacements.items():
                    cleaned = cleaned.replace(old, new)
                queue_replacements = {
                    "图好了": "",
                    "图片好了": "",
                    "照片好了": "",
                    "图生成好了": "",
                    "图片生成好了": "",
                    "还在队列里": "",
                    "还在排队": "",
                    "等图出来": "",
                    "等图片出来": "",
                    "已经发过去啦": "",
                    "已经发过去了": "",
                }
                for old, new in queue_replacements.items():
                    cleaned = cleaned.replace(old, new)
                for old in ("要看看吗", "要看吗", "想看吗"):
                    cleaned = cleaned.replace(old, "")
                cleaned = self._deemphasize_state_report_preamble(cleaned, reason=reason)
                return self._soften_social_proactive_text(cleaned, action=action)
            replacements = {
                "拍了张照片": "想到一个画面",
                "拍了照片": "想到一个画面",
                "拍了美美的照片": "想到一个挺想拍下来的画面",
                "发你照片": "想跟你说说刚才那个画面",
                "给你看照片": "想跟你说说刚才那个画面",
                "要看看吗": "先跟你说一下",
                "要看吗": "先跟你说一下",
            }
            for old, new in replacements.items():
                cleaned = cleaned.replace(old, new)
        cleaned = self._deemphasize_state_report_preamble(cleaned, reason=reason)
        return self._soften_social_proactive_text(cleaned, action=action)

    def _repair_non_external_title_share_text(
        self,
        text: str,
        *,
        reason: str = "",
        action_context: str = "",
    ) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if reason in {"bili_video_share", "news_share", "web_exploration_share"}:
            return cleaned
        title_leak_pattern = r"刚看到[，,、\s]*[“\"『「].{2,60}[”\"』」](?:这个)?标题"
        if not re.search(title_leak_pattern, cleaned):
            return cleaned
        context = _single_line(action_context, 520)
        if reason == "group_share" or "群" in context:
            repaired = re.sub(rf"{title_leak_pattern}[，,。！？!?\s]*", "", cleaned, count=1).strip()
            return repaired if len(repaired) >= 2 else ""
        if "图片路径：" in context or "真实图片文件：" in context or "photo_text" in context:
            repaired = re.sub(rf"{title_leak_pattern}[，,。！？!?\s]*", "", cleaned, count=1).strip()
            return repaired if len(repaired) >= 2 else ""
        repaired = re.sub(
            r"刚看到[，,、\s]*[“\"『「]([^”\"』」]{2,60})[”\"』」](?:这个)?标题[，,。！？!?\s]*",
            "",
            cleaned,
            count=1,
        )
        return repaired.strip()

    def _remove_unbacked_media_claims(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        replacements = {
            "我拍了张照片": "我看到一个画面",
            "我拍了照片": "我看到一个画面",
            "拍了张照片": "看到一个画面",
            "拍了照片": "看到一个画面",
            "拍了张照": "看到一个画面",
            "拍了照": "看到一个画面",
            "给你拍了张照片": "看到一个画面就想到你",
            "给你拍了照片": "看到一个画面就想到你",
            "给你拍了张照": "看到一个画面就想到你",
            "给你拍了照": "看到一个画面就想到你",
            "发你看看": "跟你说一下",
            "发给你看看": "跟你说一下",
            "发你看": "跟你说一下",
            "发给你看": "跟你说一下",
            "给你看照片": "跟你说说这个画面",
            "给你看图": "跟你说说这个画面",
            "看图": "听我说",
            "你看看喜不喜欢": "你应该会喜欢",
            "你看看喜欢吗": "你应该会喜欢",
            "你看看": "跟你说一下",
        }
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        cleaned = re.sub(r"[，,、\s]*(?:照片|图片|图)(?:里|上)?[，,、\s]*(?=被|看着|颜色|特别|挺)", "画面", cleaned)
        cleaned = re.sub(r"(?:这张|那张|这幅|那幅)(?:照片|图片|图)", "这个画面", cleaned)
        cleaned = cleaned.replace("[图片]", "").replace("【图片】", "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。")
        return cleaned

    def _is_overabstract_proactive_text(self, text: str, *, action: str) -> bool:
        cleaned = _single_line(text, 220)
        if not cleaned:
            return False
        weak_patterns = (
            "最近忙不忙",
            "发现你好像在忙",
            "数据有意思吗",
            "刚好想到你",
            "来找你一下",
            "碰你一下",
            "我就是来一下",
            "顺手来一下",
        )
        if any(token in cleaned for token in weak_patterns):
            return True
        if "screen_peek" in action and any(token in cleaned for token in ("还在忙啊", "看你在忙", "你好像在忙")):
            return True
        return False

    def _ground_proactive_text(
        self,
        text: str,
        *,
        reason: str,
        action: str,
        action_context: str,
    ) -> str:
        context = str(action_context or "")
        if "screen_peek" in action:
            if "逻辑分支" in context:
                return "你还在跟那个逻辑分支较劲啊。先别急,慢慢捋嘛。"
            if any(token in context for token in ("测试", "进度", "插件")):
                return "你还在盯那个进度啊。眼睛先歇一下啦。"
            return "你半天都没抬头了诶。先缓一口气。"
        if "poke" in action:
            return "我刚戳你了。怎么又不出声啦。"
        if "photo_text" in action:
            return text
        if "voice" in action:
            return "刚给你发了条语音。你有空再听嘛。"
        if reason == "quiet_care":
            return "感觉你这阵子都没怎么松下来。歇一小会儿嘛,又不会怎样。"
        if reason == "evening_greeting":
            return "都这个点了,你还没收工吗。别一直绷着啦。"
        if reason == "noon_greeting":
            return "中午了诶。你吃东西没有,别又随便糊弄过去。"
        if reason in {"meal_care", "meal_care_followup"}:
            return "到饭点了。你吃东西没有呀？"
        if reason in {"activity_share", "diary_share", "background_schedule"}:
            return "有件小事想跟你说一下。"
        return "刚好到能休息一小会儿的时候,想问你一句。"

    async def _execute_proactive_action(
        self,
        action: str,
        user: dict[str, Any],
        name: str,
        reason: str,
    ) -> dict[str, Any]:
        normalized = str(action or "message").strip() or "message"
        parts = [part.strip() for part in normalized.split("+") if part.strip()]
        if not parts:
            parts = ["message"]
        contexts: list[str] = []
        extra_components: list[Any] = []
        summary_parts: list[str] = []
        effective_parts: list[str] = []
        for part in parts:
            payload = await self._execute_single_action(part, user, name, reason)
            contexts.append(str(payload.get("context") or "").strip())
            extra_components.extend(list(payload.get("extra_components") or []))
            summary = _single_line(payload.get("summary") or part, 60)
            if summary:
                summary_parts.append(summary)
            effective_action = _single_line(payload.get("effective_action") or part, 40)
            if effective_action:
                effective_parts.append(effective_action)
            if not bool(payload.get("success", True)):
                return {
                    "success": False,
                    "context": "\n".join(item for item in contexts if item),
                    "extra_components": [],
                    "summary": " + ".join(summary_parts) or normalized,
                    "effective_action": "+".join(effective_parts) or normalized,
                }
        return {
            "success": True,
            "context": "\n".join(item for item in contexts if item) or "message：只发送私聊文本",
            "extra_components": extra_components,
            "summary": " + ".join(summary_parts) or normalized,
            "effective_action": "+".join(effective_parts) or normalized,
        }

    async def _execute_single_action(
        self,
        action: str,
        user: dict[str, Any],
        name: str,
        reason: str,
    ) -> dict[str, Any]:
        fallback_action = self._fallback_action_for_unavailable(action, user)
        if fallback_action != action:
            logger.info(
                "[PrivateCompanion] 主动行为依赖不可用,已回退: requested=%s fallback=%s user=%s",
                action,
                fallback_action,
                str(user.get("user_id") or ""),
            )
            if fallback_action == "message":
                return {
                    "success": True,
                    "context": "message：只发送普通私聊文本",
                    "extra_components": [],
                    "summary": "文字",
                    "effective_action": "message",
                }
            return await self._execute_single_action(fallback_action, user, name, reason)
        if action == "screen_peek":
            context = await self._run_screen_peek_action(
                user,
                name,
                reason,
                quota_exempt=bool(user.get("planned_proactive_quota_exempt")),
            )
            return {
                "success": not self._is_unusable_screen_peek_context(context),
                "context": context,
                "extra_components": [],
                "summary": "窥屏",
                "effective_action": "screen_peek",
            }
        if action == "photo_text":
            context = await self._run_photo_text_action(user, name, reason)
            image_ready = "真实图片" in context and "图片路径：" in context
            if not image_ready and reason == "birthday_celebration":
                return {
                    "success": True,
                    "context": "message：生日卡未生成，改为只发送生日祝福正文",
                    "extra_components": [],
                    "summary": "生日祝福文字",
                    "effective_action": "message",
                }
            return {
                "success": image_ready,
                "context": context,
                "extra_components": [],
                "summary": "发图",
                "effective_action": "photo_text",
            }
        if action == "poke":
            context = await self._run_poke_action(user, name, reason)
            return {
                "success": context.startswith("poke：已"),
                "context": context,
                "extra_components": [],
                "summary": "戳了你一下",
                "effective_action": "poke",
            }
        if "voice" in action and "photo_text" not in action:
            payload = await self._run_voice_action(user, name, reason)
            payload.setdefault("summary", "留了句语音")
            payload.setdefault("effective_action", "voice")
            return payload
        if action == "jm_cosmos_read":
            result = await self._run_jm_cosmos_read_action(user)
            if isinstance(result, dict):
                user["jm_cosmos_reading_context"] = result
                return {
                    "success": True,
                    "context": self._format_jm_cosmos_action_context(user),
                    "extra_components": [],
                    "summary": "私下翻了会儿漫画",
                    "effective_action": "jm_cosmos_read",
                }
            return {
                "success": False,
                "context": "私密阅读线索：这次没有找到适合继续看的内容",
                "extra_components": [],
                "summary": "没有读到合适内容",
                "effective_action": "jm_cosmos_read",
            }
        if action.startswith("external:"):
            return await self._execute_external_proactive_ability(action.split(":", 1)[1], user, name, reason)
        return {"success": True, "context": "message：只发送私聊文本", "extra_components": [], "summary": "文字", "effective_action": "message"}

    async def _execute_external_proactive_ability(
        self,
        ability_name: str,
        user: dict[str, Any],
        display_name: str,
        reason: str,
    ) -> dict[str, Any]:
        name = self._normalize_external_ability_name(ability_name)
        runtime = self._external_proactive_abilities.get(name)
        if not isinstance(runtime, dict) or not callable(runtime.get("executor")):
            return {"success": False, "context": "external：外部主动能力未注册或不可用", "extra_components": [], "summary": "外部能力不可用", "effective_action": "message"}
        config = self._external_ability_config(name)
        call_context = {
            "user": dict(user or {}),
            "display_name": display_name,
            "reason": reason,
            "bot_name": self.bot_name,
            "state": deepcopy(self.data.get("daily_state", {})),
            "current_plan_item": deepcopy(self._get_current_plan_item(self._native_daily_plan_view({})) or {}),
            "config": config,
            "plugin": self,
        }
        try:
            result = runtime["executor"](call_context)
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:
            logger.warning("[PrivateCompanion] 外部主动能力执行失败: %s: %s", name, exc, exc_info=True)
            self._note_external_ability_execution(name, success=False, status=f"执行失败: {exc}")
            return {"success": False, "context": f"external:{name}：执行失败", "extra_components": [], "summary": "外部能力失败", "effective_action": f"external:{name}"}
        payload = result if isinstance(result, dict) else {"text": str(result or "")}
        success = bool(payload.get("ok", payload.get("success", True)))
        text = _single_line(payload.get("text"), 500)
        context = str(payload.get("context") or payload.get("summary") or text or "").strip()
        image_path = str(payload.get("image_path") or "").strip()
        extra_components = list(payload.get("extra_components") or []) if isinstance(payload.get("extra_components"), list) else []
        if image_path and os.path.exists(image_path):
            extra_components.extend(self._build_outbound_chain("", image_path))
        memory = _single_line(payload.get("memory"), 500)
        if memory:
            user.setdefault("external_proactive_memory", [])
            memories = user.get("external_proactive_memory")
            if not isinstance(memories, list):
                memories = []
                user["external_proactive_memory"] = memories
            memories.append({"name": name, "ts": _now_ts(), "memory": memory})
            del memories[:-12]
        self._note_external_ability_execution(name, success=success, status=_single_line(payload.get("status") or context, 120), summary=_single_line(payload.get("summary") or text, 120))
        return {
            "success": success,
            "context": f"external:{name}：{context or '外部能力已执行'}",
            "extra_components": extra_components,
            "summary": _single_line(payload.get("summary") or runtime.get("label") or name, 60),
            "effective_action": f"external:{name}",
        }

    def _note_external_ability_execution(self, name: str, *, success: bool, status: str = "", summary: str = "") -> None:
        try:
            store = self._external_ability_store()
            item = store.get(name) if isinstance(store.get(name), dict) else {"name": name}
            item["last_executed_ts"] = _now_ts()
            item["last_status"] = status
            item["last_summary"] = summary
            item["success_count"] = _safe_int(item.get("success_count"), 0, 0) + (1 if success else 0)
            item["failure_count"] = _safe_int(item.get("failure_count"), 0, 0) + (0 if success else 1)
            store[name] = item
            self._save_data_sync()
        except Exception:
            pass

    def _is_unusable_screen_peek_context(self, context: str) -> bool:
        text = str(context or "").strip()
        if not text:
            return True
        fail_tokens = (
            "screen_peek：失败",
            "屏幕插件不可用",
            "未授权",
            "不可用",
            "Invalid base64 image_url",
            "图片预处理结果为空",
            "所有视觉链路都失败",
            "视觉 provider 调用失败",
            "当前 provider 不支持原生视频上传",
            "没看清",
            "稍后再让我看看",
            "没有得到屏幕观察结果",
            "识屏分析失败",
        )
        return any(token in text for token in fail_tokens)

    def _is_screen_peek_provider_failure(self, context: str) -> bool:
        text = str(context or "")
        fail_tokens = (
            "Invalid base64 image_url",
            "图片预处理结果为空",
            "所有视觉链路都失败",
            "视觉 provider 调用失败",
            "Asset upload returned",
            "BadRequest",
            "InvalidParameter",
        )
        return any(token in text for token in fail_tokens)

    async def _run_screen_peek_action(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        *,
        quota_exempt: bool = False,
    ) -> str:
        if not self.enable_screen_glance_action:
            return "screen_peek：未授权,跳过"
        plugin = self._get_screen_companion_plugin()
        if plugin is None:
            return "screen_peek：屏幕插件不可用"
        target = str(user.get("umo") or "").strip()
        if not self._screen_glance_available(user, ignore_daily_limit=quota_exempt):
            return "screen_peek：今日额度或冷却未满足,跳过"
        async with self._data_lock:
            self._note_screen_peek_attempt(
                str(user.get("user_id") or user.get("umo") or name),
                reason=reason,
                count_daily=not quota_exempt,
            )
            self._save_data_sync()
        event = None
        if target and hasattr(plugin, "_create_virtual_event"):
            try:
                event = plugin._create_virtual_event(target)
            except Exception as e:
                logger.debug(f"[PrivateCompanion] 创建屏幕虚拟事件失败: {e}")
        prompt = (
            f"这是一次用户已授权的主动陪伴行为。请只做视觉观察,"
            f"用很短的话描述用户电脑当前大概在看什么、做什么、是不是像在忙。"
            f"不要直接对用户说话,不要安慰、提醒、关心、陪伴,不要输出隐私细节、账号、完整文本、聊天内容。"
            f"只留一个内部观察印象。主动原因：{reason}"
        )
        try:
            result = await plugin._invoke_screen_skill(
                event,
                request_prompt=prompt,
                history_user_text=f"主动陪伴想轻轻看一眼 {name} 现在在忙什么。",
                task_id="private_companion_screen_peek",
            )
            context = "screen_peek：\n" + (_single_line(result, 300) if result else "没有得到屏幕观察结果")
            if self._is_screen_peek_provider_failure(context):
                self._note_screen_peek_failure(user, context)
            return context
        except Exception as e:
            error_text = _single_line(e, 240)
            logger.warning(f"[PrivateCompanion] screen_peek 主动行为失败: {error_text}")
            context = f"screen_peek：失败,{error_text}"
            if self._is_screen_peek_provider_failure(context):
                self._note_screen_peek_failure(user, context)
            return context

    def _get_screen_companion_plugin(self) -> Any:
        for module_name in ("astrbot_plugin_screen_companion.main", "data.plugins.astrbot_plugin_screen_companion.main"):
            try:
                module = importlib.import_module(module_name)
                plugin = getattr(module, "_screen_companion_tool_plugin", None)
                if plugin is not None and callable(getattr(plugin, "_invoke_screen_skill", None)):
                    return plugin
            except Exception:
                continue
        for module in list(sys.modules.values()):
            try:
                plugin = getattr(module, "_screen_companion_tool_plugin", None)
                if plugin is not None and callable(getattr(plugin, "_invoke_screen_skill", None)):
                    return plugin
            except Exception:
                continue
        return None

    def _poke_action_cooldown_remaining(self, user: dict[str, Any] | None, *, now: float | None = None) -> float:
        if not isinstance(user, dict):
            return 0.0
        current_ts = float(now if now is not None else _now_ts())
        inflight_until = _safe_float(user.get("poke_action_inflight_until"), 0.0)
        if inflight_until > current_ts:
            return inflight_until - current_ts
        cooldown_seconds = max(0, _safe_int(getattr(self, "poke_action_cooldown_minutes", 30), 30, 0, 1440)) * 60
        last_at = _safe_float(user.get("last_poke_action_at"), 0.0)
        return max(0.0, last_at + cooldown_seconds - current_ts) if cooldown_seconds > 0 and last_at > 0 else 0.0

    async def _send_single_poke(self, client: Any, *, user_id: str, group_id: str) -> None:
        if group_id and callable(getattr(client, "group_poke", None)):
            await client.group_poke(group_id=int(group_id), user_id=int(user_id))
            return
        if not group_id and callable(getattr(client, "friend_poke", None)):
            await client.friend_poke(user_id=int(user_id))
            return
        try:
            from data.plugins.astrbot_plugin_pokepro.core.send_poke import PokeSender
        except Exception:
            from astrbot_plugin_pokepro.core.send_poke import PokeSender
        await PokeSender.poke_func(client=client, user_id=user_id, group_id=group_id or None)

    async def _run_poke_action(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        *,
        explicit_count: int | None = None,
    ) -> str:
        if not self.enable_poke_action:
            return "poke：未启用"
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return "poke：未找到可用的 QQ 客户端"
        user_id = str(user.get("user_id") or "").strip()
        if not user_id.isdigit():
            return "poke：目标 QQ 号无效"
        group_id = self._extract_group_id_from_umo(str(user.get("umo") or ""))
        max_count = min(3, max(0, self._effective_user_poke_daily_limit(user)))
        if max_count <= 0:
            return "poke：当前用户未允许主动戳一戳"
        requested_count = int(explicit_count) if explicit_count is not None else self._choose_poke_repeat_count(user, reason)
        poke_count = max(1, min(max_count, requested_count))
        reserved = False
        try:
            async with self._data_lock:
                current = self._get_user(user_id)
                now = _now_ts()
                remaining = self._poke_action_cooldown_remaining(current, now=now)
                if remaining > 0:
                    return f"poke：冷却中，约 {max(1, math.ceil(remaining / 60))} 分钟后可再次执行"
                current["poke_action_inflight_until"] = now + max(30.0, poke_count * 3.0)
                current["poke_echo_suppress_until"] = now + max(30.0, poke_count * 3.0)
                self._save_data_sync()
                reserved = True
            for index in range(poke_count):
                await self._send_single_poke(client, user_id=user_id, group_id=group_id)
                if index + 1 < poke_count:
                    await asyncio.sleep(random.uniform(0.35, 0.9))
            async with self._data_lock:
                current = self._get_user(user_id)
                current["last_poke_action_at"] = _now_ts()
                current["poke_action_inflight_until"] = 0
                self._save_data_sync()
            if poke_count <= 1:
                return f"poke：已轻轻戳了 {name} 一下\n主动原因：{reason}"
            return f"poke：已轻轻连着戳了 {name} {poke_count} 下\n主动原因：{reason}"
        except Exception as e:
            if reserved:
                try:
                    async with self._data_lock:
                        current = self._get_user(user_id)
                        current["poke_action_inflight_until"] = 0
                        self._save_data_sync()
                except Exception:
                    pass
            logger.warning(f"[PrivateCompanion] poke 主动行为失败: {e}")
            return f"poke：失败,{e}"

    def _choose_poke_repeat_count(self, user: dict[str, Any], reason: str) -> int:
        max_times = self._effective_user_poke_daily_limit(user)
        if max_times <= 0:
            return 0
        if max_times <= 1:
            return 1
        motive = _single_line(
            user.get("planned_proactive_motive") or user.get("last_proactive_motive"),
            120,
        )
        profile = self._persona_action_profile()
        weights: list[tuple[int, float]] = [(1, 1.0)]
        second_weight = 0.45
        third_weight = 0.12
        if profile.get("playful"):
            second_weight += 0.22
            third_weight += 0.1
        if profile.get("clingy"):
            second_weight += 0.12
            third_weight += 0.06
        if reason in {"quiet_care", "check_in"}:
            second_weight += 0.08
        if any(token in motive for token in ("轻轻叫你", "刷存在感", "碰你一下", "没忍住", "冒个头")):
            second_weight += 0.15
        if any(token in motive for token in ("偷偷看", "放心不下", "想起你", "不想吵你")):
            third_weight += 0.04
        weights.append((2, second_weight))
        if max_times >= 3:
            weights.append((3, third_weight))
        return int(self._weighted_choice([(str(count), weight) for count, weight in weights]))

    def _choose_pre_message_poke_count(
        self,
        user: dict[str, Any],
        reason: str,
        *,
        action: str = "message",
        motive: str = "",
    ) -> int:
        if "poke" in {part.strip() for part in str(action or "").split("+") if part.strip()}:
            return 0
        if (
            not self._poke_available()
            or self._effective_user_poke_daily_limit(user) <= 0
            or self._poke_action_cooldown_remaining(user) > 0
        ):
            return 0
        profile = self._persona_action_profile()
        probability = 0.12
        if reason in {"check_in", "quiet_care", "important_date_share"}:
            probability += 0.22
        if profile.get("playful"):
            probability += 0.14
        if profile.get("clingy"):
            probability += 0.08
        if action in {"voice", "photo_text"}:
            probability -= 0.02
        motive_text = str(motive or user.get("planned_proactive_motive") or "")
        if any(token in motive_text for token in ("轻轻叫你", "戳", "碰碰你", "确认一下", "放心不下", "叫你一声")):
            probability += 0.08
        probability = max(0.0, min(0.72, probability))
        if random.random() >= probability:
            return 0
        return self._choose_poke_repeat_count(user, reason)

    async def _maybe_run_pre_message_poke(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        *,
        action: str = "message",
        motive: str = "",
    ) -> tuple[int, str]:
        poke_count = self._choose_pre_message_poke_count(
            user,
            reason,
            action=action,
            motive=motive,
        )
        if poke_count <= 0:
            return 0, ""
        context = await self._run_poke_action(user, name, reason, explicit_count=poke_count)
        if not context.startswith("poke：已"):
            return 0, context
        return poke_count, context

    async def _run_voice_action(self, user: dict[str, Any], name: str, reason: str) -> dict[str, Any]:
        if not self.enable_voice_action:
            return {"success": False, "context": "voice：未启用", "extra_components": [], "summary": "语音"}
        target = str(user.get("umo") or "").strip()
        if not target:
            return {"success": False, "context": "voice：缺少目标会话,无法发送语音", "extra_components": [], "summary": "语音"}
        voice_text = await self._build_voice_note_text(user, name, reason, target=target)
        components, audio_note = await self._create_voice_record_component(target, voice_text)
        if not components:
            return {
                "success": False,
                "context": (
                    "voice：语音生成失败\n"
                    f"想说的话：{voice_text}\n"
                    f"失败原因：{_single_line(audio_note, 160)}"
                ),
                "extra_components": [],
                "summary": "语音",
            }
        return {
            "success": True,
            "context": (
                "voice：已生成真实语音\n"
                f"语音内容：{self._strip_tts_markup(voice_text)}\n"
                f"真实语音文件：{audio_note}"
            ),
            "extra_components": components,
            "summary": "留了句语音",
        }

    def _resolve_aiocqhttp_client(self) -> Any:
        platform_manager = getattr(self.context, "platform_manager", None)
        platforms: list[Any] = []
        if platform_manager is not None:
            try:
                platforms = list(platform_manager.get_insts())
            except Exception:
                platforms = list(getattr(platform_manager, "platform_insts", []) or [])
        for platform in platforms:
            platform_names = set()
            try:
                meta = platform.meta()
                platform_names.add(str(getattr(meta, "id", "") or "").strip())
                platform_names.add(str(getattr(meta, "name", "") or "").strip())
            except Exception:
                pass
            platform_desc = f"{platform.__class__.__module__}.{platform.__class__.__name__}".lower()
            for attr in ("bot", "client", "_bot", "_client", "cqhttp"):
                client = getattr(platform, attr, None)
                client_desc = f"{client.__class__.__module__}.{client.__class__.__name__}".lower() if client is not None else ""
                if client is not None and (
                    "aiocqhttp" in platform_names
                    or "default(aiocqhttp)" in platform_names
                    or "aiocqhttp" in platform_desc
                    or "aiocqhttp" in client_desc
                    or (hasattr(client, "send_private_msg") and hasattr(client, "send_group_msg"))
                    or hasattr(client, "friend_poke")
                    or hasattr(client, "group_poke")
                ):
                    return client
        return None

    def _onebot_action_result_ok(self, result: Any) -> bool:
        if result is None:
            return True
        if isinstance(result, dict):
            status = str(result.get("status") or result.get("result") or "").strip().lower()
            if status in {"failed", "fail", "error", "nok"}:
                return False
            retcode = result.get("retcode", result.get("code", None))
            if retcode is not None:
                try:
                    return int(retcode) == 0
                except Exception:
                    return False
        return True

    async def _call_onebot_action(self, client: Any, action: str, **params: Any) -> bool:
        ok, _ = await self._call_onebot_action_with_error(client, action, **params)
        return ok

    async def _call_onebot_action_with_error(self, client: Any, action: str, *,
                                             _companion_single_dispatch: bool = False, **params: Any) -> tuple[bool, str]:
        candidates = (
            "call_action",
            "call_api",
            "api",
        )
        last_error = ""
        for attr in candidates:
            func = getattr(client, attr, None)
            if not callable(func):
                continue
            try:
                result = func(action, **params)
                if hasattr(result, "__await__"):
                    result = await result
                if self._onebot_action_result_ok(result):
                    return True, ""
                last_error = f"{attr} 返回失败: {_single_line(result, 180)}"
                if self._is_onebot_event_checker_send_rejection(result):
                    return False, self._onebot_event_checker_rejection_summary()
                if _companion_single_dispatch:
                    return False, last_error
            except asyncio.CancelledError as exc:
                if _companion_single_dispatch:
                    self._companion_mark_uncertain_cancellation('onebot_direct', exc)
                raise
            except TypeError as exc:
                if _companion_single_dispatch:
                    raise self._companion_delivery_uncertain_exception('onebot_direct', exc) from exc
                try:
                    result = func(action, params)
                    if hasattr(result, "__await__"):
                        result = await result
                    if self._onebot_action_result_ok(result):
                        return True, ""
                    last_error = f"{attr} 返回失败: {_single_line(result, 180)}"
                    if self._is_onebot_event_checker_send_rejection(result):
                        return False, self._onebot_event_checker_rejection_summary()
                except Exception as exc:
                    if self._is_onebot_event_checker_send_rejection(exc):
                        return False, self._onebot_event_checker_rejection_summary()
                    last_error = self._format_send_exception(exc)
                    continue
            except Exception as exc:
                if self._is_onebot_event_checker_send_rejection(exc):
                    return False, self._onebot_event_checker_rejection_summary()
                if _companion_single_dispatch:
                    raise self._companion_delivery_uncertain_exception('onebot_direct', exc) from exc
                last_error = self._format_send_exception(exc)
                continue
        func = getattr(client, action, None)
        if callable(func):
            try:
                result = func(**params)
                if hasattr(result, "__await__"):
                    result = await result
                if self._onebot_action_result_ok(result):
                    return True, ""
                return False, f"{action} 返回失败: {_single_line(result, 180)}"
            except asyncio.CancelledError as exc:
                if _companion_single_dispatch:
                    self._companion_mark_uncertain_cancellation('onebot_direct', exc)
                raise
            except Exception as exc:
                if _companion_single_dispatch:
                    raise self._companion_delivery_uncertain_exception('onebot_direct', exc) from exc
                return False, self._format_send_exception(exc)
        return False, last_error or f"OneBot 客户端不支持动作 {action}"

    def _input_status_user_id_from_umo(self, umo: str) -> str:
        if not umo or ":FriendMessage:" not in str(umo):
            return ""
        session = self._parse_message_session(umo)
        if not session:
            return ""
        user_id = str(getattr(session, "session_id", "") or "").strip()
        return user_id if user_id.isdigit() else ""

    async def _send_input_status_once(self, user_id: str, *, client: Any | None = None) -> bool:
        user_id = str(user_id or "").strip()
        if not user_id.isdigit():
            return False
        if client is None:
            client = self._resolve_aiocqhttp_client()
        if client is None:
            return False
        variants = (
            {"user_id": int(user_id), "event_type": 1},
            {"user_id": int(user_id), "status": 1},
            {"user_id": int(user_id), "typing": True},
        )
        for params in variants:
            if await self._call_onebot_action(client, "set_input_status", **params):
                self._last_input_status_at[user_id] = _now_ts()
                return True
        return False

    async def _maybe_send_input_status(self, umo: str, text: str = "") -> None:
        user_id = self._input_status_user_id_from_umo(umo)
        if not user_id:
            return
        now = _now_ts()
        last_at = _safe_float(self._last_input_status_at.get(user_id), 0)
        if now - last_at < 45:
            return
        duration = max(1.2, min(4.5, len(str(text or "")) / 18))
        if not await self._send_input_status_once(user_id):
            return
        self._last_input_status_at[user_id] = now
        await asyncio.sleep(random.uniform(duration * 0.55, duration))

    async def _passive_input_status_loop(self, user_id: str, *, max_seconds: float = 90.0) -> None:
        user_id = str(user_id or "").strip()
        if not user_id.isdigit():
            return
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return
        started_at = _now_ts()
        while not bool(getattr(self, "_stop_event", asyncio.Event()).is_set()):
            if _now_ts() - started_at > max_seconds:
                return
            try:
                await self._send_input_status_once(user_id, client=client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("[PrivateCompanion] 私聊输入状态刷新失败: %s", _single_line(exc, 120))
                return
            await asyncio.sleep(random.uniform(3.2, 4.8))

    def _start_passive_input_status_loop(self, event: AstrMessageEvent, user_id: str = "") -> None:
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        parsed_user_id = self._input_status_user_id_from_umo(umo)
        user_id = str(user_id or parsed_user_id or "").strip()
        if not parsed_user_id or parsed_user_id != user_id or not user_id.isdigit():
            return
        tasks = getattr(self, "_passive_input_status_tasks", None)
        if not isinstance(tasks, dict):
            tasks = {}
            self._passive_input_status_tasks = tasks
        old_task = tasks.get(user_id)
        if isinstance(old_task, asyncio.Task) and not old_task.done():
            old_task.cancel()
        task = asyncio.create_task(self._passive_input_status_loop(user_id))
        tasks[user_id] = task
        try:
            setattr(event, "private_companion_input_status_user_id", user_id)
        except Exception:
            pass

        def _cleanup(done_task: asyncio.Task) -> None:
            current = tasks.get(user_id)
            if current is done_task:
                tasks.pop(user_id, None)

        task.add_done_callback(_cleanup)

    def _stop_passive_input_status_loop(self, event_or_user: Any) -> None:
        user_id = ""
        if isinstance(event_or_user, str):
            user_id = event_or_user.strip()
        else:
            user_id = str(getattr(event_or_user, "private_companion_input_status_user_id", "") or "").strip()
            if not user_id:
                try:
                    user_id = str(event_or_user.get_sender_id()).strip()
                except Exception:
                    user_id = ""
        if not user_id:
            return
        tasks = getattr(self, "_passive_input_status_tasks", None)
        if not isinstance(tasks, dict):
            return
        task = tasks.pop(user_id, None)
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()

    def _qq_presence_codes(self, mode: str) -> tuple[int, int, str]:
        normalized = str(mode or "").strip().lower()
        table = {
            "online": (10, 0, "在线"),
            "away": (30, 0, "离开"),
            "busy": (50, 0, "忙碌"),
            "invisible": (40, 0, "隐身"),
        }
        return table.get(normalized, table["online"])

    async def _set_qq_online_presence(self, mode: str) -> tuple[bool, str]:
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return False, "未找到可用 QQ 客户端"
        status, ext_status, label = self._qq_presence_codes(mode)
        variants = (
            {"status": status, "ext_status": ext_status, "battery_status": 0},
            {"status": status, "ext_status": ext_status},
            {"status": status},
            {"status_id": status},
            {"mode": str(mode or "online")},
        )
        for params in variants:
            if await self._call_onebot_action(client, "set_online_status", **params):
                return True, label
        return False, f"平台不支持 set_online_status：{label}"

    async def _set_qq_custom_presence(self, text: str) -> tuple[bool, str]:
        if not getattr(self, "enable_qq_custom_presence_sync", False):
            return False, "QQ 自定义短状态未开启"
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return False, "未找到可用 QQ 客户端"
        custom_text = _single_line(text, 8)
        if not custom_text:
            return False, "自定义状态文本为空,跳过同步"
        # Avoid set_custom_online_status: some OneBot adapters disconnect on this unsupported extension API.
        variants = (
            ("set_diy_online_status", {"face_id": 21, "face_type": 1, "wording": custom_text}),
            ("set_diy_online_status", {"face_id": "21", "face_type": "1", "wording": custom_text}),
            ("set_diy_online_status", {"faceId": 21, "faceType": 1, "wording": custom_text}),
            ("set_diy_online_status", {"id": 21, "face_type": 1, "wording": custom_text}),
            ("set_diy_online_status", {"wording": custom_text}),
            ("set_diy_online_status", {"face_id": 21, "text": custom_text}),
            ("set_diy_online_status", {"faceId": 21, "text": custom_text}),
            ("set_diy_online_status", {"id": 21, "text": custom_text}),
            ("set_diy_online_status", {"text": custom_text}),
        )
        for action, params in variants:
            if await self._call_onebot_action(client, action, **params):
                return True, f"自定义状态：{custom_text}"
        return False, f"平台不支持自定义状态：{custom_text}"

    async def _reset_stale_qq_presence_if_needed(self) -> None:
        if not self.enable_qq_presence_sync:
            return
        await asyncio.sleep(2)
        try:
            await self._ensure_current_detail_presence_status()
        except Exception as exc:
            logger.debug("[PrivateCompanion] 启动同步当前 QQ 状态失败: %s", exc)
        async with self._data_lock:
            state = self.data.get("qq_presence_state", {})
            if not isinstance(state, dict) or str(state.get("date") or "") == _today_key():
                return
            previous_mode = str(state.get("mode") or "")
        ok, note = await self._set_qq_online_presence("online")
        async with self._data_lock:
            state = self.data.setdefault("qq_presence_state", {})
            if not isinstance(state, dict):
                state = {}
                self.data["qq_presence_state"] = state
            state.update(
                {
                    "date": _today_key(),
                    "plan_date": "",
                    "detail_key": "",
                    "mode": "online",
                    "custom_text": "",
                    "reason": "清理跨日 QQ 状态",
                    "updated_at": _now_ts(),
                    "ok": bool(ok),
                    "note": _single_line(f"跨日重置：{previous_mode or 'unknown'} -> {note}", 120),
                }
            )
            self._save_data_sync()

    def _extract_group_id_from_umo(self, target: str) -> int | None:
        text = str(target or "").strip()
        match = re.search(r":GroupMessage:(\d+)$", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    async def _build_voice_note_text(
        self,
        user: dict[str, Any],
        name: str,
        reason: str,
        *,
        target: str = "",
    ) -> str:
        requirement = self._voice_requirement_profile(target)
        framework_text = await self._generate_voice_note_via_framework(
            user,
            name,
            reason,
            target=target,
        )
        if framework_text:
            spoken = str(framework_text).strip()
            if requirement["strict"] and not self._voice_text_matches_requirement(spoken, requirement):
                logger.info(
                    "[PrivateCompanion] 主动语音未命中格式要求,进行框架严格重试: target=%s summary=%s",
                    target,
                    requirement["summary"],
                )
                retry_text = await self._generate_voice_note_via_framework(
                    user,
                    name,
                    reason,
                    target=target,
                    strict_tts=True,
                )
                if retry_text:
                    spoken = str(retry_text).strip()
            if "<tts>" not in spoken:
                spoken = _single_line(spoken, self.voice_action_max_chars)
                spoken = re.sub(r"[“”\"'`]", "", spoken).strip()
            if requirement["strict"] and not self._voice_text_matches_requirement(spoken, requirement):
                repair_prompt = self._build_voice_repair_prompt(
                    spoken=spoken,
                    requirement=requirement,
                    target=target,
                )
                repaired = await self._llm_call(
                    repair_prompt,
                    max_tokens=140,
                    provider_id=self._task_provider(self.voice_prompt_provider_id, self.mai_style_provider_id),
                    task="voice_repair",
                )
                if repaired:
                    spoken = str(repaired).strip()
                    if "<tts>" not in spoken:
                        spoken = _single_line(spoken, self.voice_action_max_chars)
                        spoken = re.sub(r"[“”\"'`]", "", spoken).strip()
            if requirement["strict"] and not self._voice_text_matches_requirement(spoken, requirement):
                logger.warning(
                    "[PrivateCompanion] 主动语音仍未完全命中格式要求,保留当前结果: target=%s summary=%s text=%s",
                    target,
                    requirement["summary"],
                    self._strip_tts_markup(spoken),
                )
            else:
                logger.info(
                    "[PrivateCompanion] 主动语音最终文本已命中格式要求: target=%s text=%s",
                    target,
                    self._strip_tts_markup(spoken),
                )
            return spoken
        persona = self._get_default_persona_prompt()
        state = self.data.get("daily_state", {})
        last_user_message = _single_line(user.get("last_user_message"), 80)
        profile = self._relationship_profile(user)
        tts_prompt = self._get_tts_prompt_text(target)
        prompt = f"""
你正在替角色写一条马上要发出去的语音。这条语音是真的会被 TTS 念出来,不是文字陪聊。

【人格】
{persona}

【对象】
称呼：{name}
关系：{profile['level']}｜偏好：{profile['preference']}
最近一句：{last_user_message or '（暂无）'}

【主动原因】
{reason}

【当前状态】
{self._format_state_for_prompt(state if isinstance(state, dict) else {})}

【当前会话 TTS 规则】
{tts_prompt or "（当前没有额外 TTS 提示词,就按人格自己的语音习惯来）"}

要求：
1. 优先遵守人格里自己写的特殊 TTS 规则；如果人格或当前会话 TTS 规则要求使用 <tts>...</tts>、日语、情绪标签或双语格式,就按那个格式输出。
2. 如果没有明确格式要求,就只输出适合真正念出来的一小句语音内容,不要解释。
3. 整体要短,适合私聊语音,不像朗读稿,也不要太正式；纯中文可控制在 {self.voice_action_max_chars} 个字以内。
4. 可以有一点嘴硬、黏人、藏着的想念,但不要把喜欢说满。
5. 不要提 AI、模型、插件、TTS、语音合成这些词。
""".strip()
        text = await self._llm_call(
            prompt,
            max_tokens=120,
            provider_id=self._task_provider(self.voice_prompt_provider_id, self.mai_style_provider_id),
            task="voice",
        )
        spoken = str(text or "").strip()
        if not spoken:
            spoken = random.choice(VOICE_FALLBACK_TEMPLATES)
        if "<tts>" not in spoken:
            spoken = _single_line(spoken, self.voice_action_max_chars)
            spoken = re.sub(r"[“”\"'`]", "", spoken).strip()
        if requirement["strict"] and not self._voice_text_matches_requirement(spoken, requirement):
            repair_prompt = self._build_voice_repair_prompt(
                spoken=spoken,
                requirement=requirement,
                target=target,
            )
            repaired = await self._llm_call(
                repair_prompt,
                max_tokens=140,
                provider_id=self._task_provider(self.voice_prompt_provider_id, self.mai_style_provider_id),
                task="voice_repair",
            )
            if repaired:
                spoken = str(repaired).strip()
                if "<tts>" not in spoken:
                    spoken = _single_line(spoken, self.voice_action_max_chars)
                    spoken = re.sub(r"[“”\"'`]", "", spoken).strip()
        return spoken

    async def _create_voice_record_component(self, target: str, spoken_text: str) -> tuple[list[Any], str]:
        if not spoken_text:
            return [], "语音内容为空"
        try:
            config = self.context.get_config(target)
        except Exception:
            try:
                config = self.context.get_config()
            except Exception as e:
                return [], f"读取配置失败：{e}"
        provider_settings = dict(config.get("provider_tts_settings", {}) or {})
        if not provider_settings.get("enable", False):
            return [], "当前会话未启用 TTS"
        try:
            tts_provider = self.context.get_using_tts_provider(target)
        except Exception as e:
            return [], f"读取 TTS provider 失败：{e}"
        if not tts_provider:
            return [], "当前会话没有可用的 TTS provider"
        if "<tts>" in spoken_text and "</tts>" in spoken_text:
            components, note = await self._build_tts_modify_components(
                spoken_text,
                tts_provider,
                provider_settings,
                config,
            )
            records = [component for component in components if isinstance(component, Record)]
            if records:
                # The proactive message generator supplies the visible companion text.
                # Keep only the prebuilt audio here so it cannot be sent twice.
                return records, note
        record_builder = getattr(self, "_tts_record_component", None)
        if callable(record_builder):
            record = await record_builder(
                spoken_text,
                tts_provider,
                provider_settings,
                config,
                source_text=spoken_text,
                source="private_companion",
            )
            if record is not None:
                return [record], self._extract_record_note([record]) or "已通过 TTS强化生成语音"
            return [], "TTS 没有返回音频文件"
        try:
            audio_path = await tts_provider.get_audio(spoken_text)
        except Exception as e:
            logger.warning(f"[PrivateCompanion] voice 主动行为生成失败: {e}")
            return [], str(e)
        if not audio_path:
            return [], "TTS 没有返回音频文件"
        try:
            audio_file = Path(audio_path).resolve()
            expected_dir = Path(get_astrbot_data_path()).resolve()
            if not audio_file.is_relative_to(expected_dir):
                return [], f"语音文件路径不安全：{audio_path}"
        except Exception as e:
            return [], str(e)
        final_ref = str(audio_path)
        if provider_settings.get("use_file_service", False):
            callback_api_base = str(config.get("callback_api_base", "") or "").strip()
            if callback_api_base:
                try:
                    token = await file_token_service.register_file(str(audio_path))
                    final_ref = f"{callback_api_base}/api/file/{token}"
                except Exception as e:
                    logger.warning(f"[PrivateCompanion] 注册语音文件失败,将回退到本地路径: {e}")
        try:
            component = Record(file=final_ref, url=final_ref)
        except TypeError:
            try:
                component = Record(file=final_ref)
            except TypeError:
                component = Record.fromFileSystem(str(audio_path))
        self._annotate_tts_record_component(component, spoken_text, source_text=spoken_text)
        return [component], str(audio_path)

    def _get_tts_prompt_text(self, target: str) -> str:
        if getattr(self, "enable_tts_enhancement", False):
            builder = getattr(self, "_build_tts_rule_prompt", None)
            if callable(builder):
                return str(builder("generic") or "").strip()
        return ""

    def _voice_requirement_profile(self, target: str) -> dict[str, Any]:
        persona = self._get_default_persona_prompt()
        tts_prompt = self._get_tts_prompt_text(target)
        combined = f"{persona}\n{tts_prompt}".lower()
        require_tts_tags = "<tts>" in combined or "</tts>" in combined
        japanese_markers = ("日语", "日文", "日本語", "假名", "片假名", "平假名", "日语语音", "日文语音")
        bilingual_markers = ("双语", "中日双语", "中文文本", "中文显示", "日语语音")
        prefer_japanese = any(marker in combined for marker in japanese_markers)
        prefer_bilingual = any(marker in combined for marker in bilingual_markers)
        strict = require_tts_tags or prefer_japanese or prefer_bilingual
        parts: list[str] = []
        if require_tts_tags:
            parts.append("需要 <tts> 标签")
        if prefer_japanese:
            parts.append("语音正文优先日语")
        if prefer_bilingual:
            parts.append("可能需要双语/日中并存格式")
        if not parts:
            parts.append("没有明显额外语音格式要求")
        return {
            "strict": strict,
            "require_tts_tags": require_tts_tags,
            "prefer_japanese": prefer_japanese,
            "prefer_bilingual": prefer_bilingual,
            "summary": "；".join(parts),
        }

    def _voice_text_matches_requirement(self, spoken: str, requirement: dict[str, Any]) -> bool:
        text = str(spoken or "").strip()
        if not text:
            return False
        if requirement.get("require_tts_tags") and ("<tts>" not in text.lower() or "</tts>" not in text.lower()):
            return False
        core = self._strip_tts_markup(text)
        if requirement.get("prefer_japanese"):
            if not re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", core):
                return False
        return True

    def _build_voice_repair_prompt(
        self,
        *,
        spoken: str,
        requirement: dict[str, Any],
        target: str,
    ) -> str:
        persona = self._get_default_persona_prompt()
        tts_prompt = self._get_tts_prompt_text(target)
        return f"""
你要把下面这句主动语音修正成符合当前语音规则的最终版本。

【人格】
{persona}

【当前会话 TTS 规则】
{tts_prompt or "（当前没有额外 TTS 提示词）"}

【必须满足的格式重点】
{requirement.get("summary") or "按人格自己的语音习惯处理"}

【当前版本】
{spoken}

要求：
1. 只输出修正后的最终语音内容，不要解释。
2. 如果需要 <tts>...</tts>，必须补齐。
3. 如果要求日语语音，就让真正会被念出来的那一部分变成自然的日语，而不是普通中文。
4. 如果没有强制格式，也保持私聊语音的自然感。
""".strip()

    async def _build_tts_modify_components(
        self,
        spoken_text: str,
        tts_provider: Any,
        provider_settings: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[list[Any], str]:
        try:
            processor = getattr(self, "_process_tts_tags", None)
            if not callable(processor):
                return [], "TTS强化未接入"
            components = await processor(
                spoken_text,
                tts_provider,
                provider_settings,
                config,
            )
        except Exception as e:
            logger.warning(f"[PrivateCompanion] TTS强化处理主动语音失败: {e}")
            return [], str(e)
        audio_note = self._extract_record_note(components)
        return components or [], audio_note or "已通过 TTS强化生成语音"

    def _get_tts_modify_plugin(self, config: dict[str, Any]) -> Any:
        for module_name in ("astrbot_plugin_tts_modify.main", "data.plugins.astrbot_plugin_tts_modify.main"):
            try:
                module = importlib.import_module(module_name)
                plugin_cls = getattr(module, "TTSModifyPlugin", None)
                if plugin_cls is not None:
                    return plugin_cls(self.context, config)
            except Exception:
                continue
        return None

    def _extract_record_note(self, components: list[Any]) -> str:
        for component in components or []:
            file_value = str(getattr(component, "file", "") or "").strip()
            url_value = str(getattr(component, "url", "") or "").strip()
            if file_value:
                return file_value
            if url_value:
                return url_value
        return ""

    def _strip_tts_markup(self, text: str) -> str:
        stripped = self._visible_text_without_tts_reading(text)
        stripped = stripped.replace("\r", "\n")
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        return _single_line(" ".join(lines), 120)

    def _visible_text_without_tts_reading(self, text: str, *, limit: int = 1000) -> str:
        source = str(text or "").strip()
        if not source:
            return ""
        if self._is_proactive_delivery_receipt_text(source):
            return ""
        placeholder_cleaner = getattr(self, "_sanitize_orphan_tts_placeholders", None)
        if callable(placeholder_cleaner):
            source = placeholder_cleaner(source)
        normalizer = getattr(self, "_normalize_tts_tags", None)
        if callable(normalizer) and re.search(r"</?t{2,}s\b", source, flags=re.IGNORECASE):
            try:
                source = str(normalizer(source) or source).strip()
            except Exception:
                pass
        if re.search(r"<tts\b[^>]*>.*?</tts>", source, flags=re.IGNORECASE | re.DOTALL):
            outside = re.sub(r"<tts\b[^>]*>.*?</tts>", "", source, flags=re.IGNORECASE | re.DOTALL)
            outside = re.sub(r"</?t{2,}s\b[^>]*>", "", outside, flags=re.IGNORECASE).strip()
            if re.search(r"[\u4e00-\u9fff]", outside):
                return _single_line(_strip_internal_message_blocks(outside), limit)
            source = re.sub(r"</?t{2,}s\b[^>]*>", "", source, flags=re.IGNORECASE).strip()
        has_kana = bool(re.search(r"[\u3040-\u30ff]", source))
        has_cjk = bool(re.search(r"[\u4e00-\u9fff]", source))
        if has_kana and has_cjk and getattr(self, "tts_voice_language", "ja") != "zh":
            units = re.findall(r".*?[。！？!?…~～]+|.+$", source, flags=re.DOTALL)
            kept: list[str] = []
            dropped = False
            for unit in units:
                cleaned = str(unit or "").strip()
                if not cleaned:
                    continue
                if re.search(r"[\u3040-\u30ff]", cleaned):
                    dropped = True
                    continue
                kept.append(cleaned)
            if dropped and kept and any(re.search(r"[\u4e00-\u9fff]", item) for item in kept):
                return _single_line(_strip_internal_message_blocks("".join(kept)), limit)
        return _single_line(_strip_internal_message_blocks(source), limit)

    def _find_photo_workflow_with_text_count(
        self,
        module: Any,
        workflow_dir: Any,
        workflow_name: str,
        image_count: int = 0,
    ) -> tuple[str, int, int]:
        if not hasattr(module, "list_workflows_in_dir"):
            return "", 0, 0
        try:
            workflows = module.list_workflows_in_dir(workflow_dir)
        except Exception:
            return "", 0, 0
        candidates = []
        expected_images = max(0, int(image_count or 0))
        for item in workflows or []:
            if not isinstance(item, dict):
                continue
            if item.get("name") != workflow_name:
                continue
            if _safe_int(item.get("images"), 0) != expected_images:
                continue
            if _safe_int(item.get("videos"), 0) != 0:
                continue
            text_count = max(1, _safe_int(item.get("texts"), 1, 1))
            filename = str(item.get("filename") or "").strip()
            if not filename:
                continue
            path = os.path.join(str(workflow_dir), filename)
            if os.path.exists(path):
                candidates.append((text_count, path))
        if not candidates:
            return "", 0, 0
        candidates.sort(key=lambda value: value[0])
        return candidates[0][1], candidates[0][0], expected_images

    def _get_comfyui_module(self) -> Any:
        for module_name in (
            "astrbot_plugin_comfyui.main",
            "data.plugins.astrbot_plugin_comfyui.main",
        ):
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "ComfyUIWorkflow"):
                    return module
            except Exception:
                continue
        for module in list(sys.modules.values()):
            try:
                if hasattr(module, "ComfyUIWorkflow") and hasattr(module, "_get_result_for_prompt"):
                    return module
            except Exception:
                continue
        return None

    def _extract_action_image_path(self, action_context: str) -> str:
        text = str(action_context or "")
        match = re.search(r"(?:图片路径|真实图片文件)[:：]\s*(.+)", text)
        if not match:
            return ""
        path = match.group(1).strip().splitlines()[0].strip()
        return path if path and os.path.exists(path) else ""

    def _extract_action_photo_caption(self, action_context: str) -> str:
        text = str(action_context or "")
        match = re.search(r"(?:画面|图片画面|画面草稿)[:：]\s*(.+)", text)
        if not match:
            return ""
        return _single_line(match.group(1).splitlines()[0], 220)

    def _extract_action_photo_subject_owner(self, action_context: str) -> str:
        text = str(action_context or "")
        match = re.search(r"(?:图片主体归属|画面主体归属)[:：]\s*([^\r\n]+)", text)
        if not match:
            return ""
        return _normalize_photo_subject_owner(match.group(1))

    def _build_outbound_chain(
        self,
        text: str,
        image_path: str = "",
        extra_components: list[Any] | None = None,
    ) -> list[Any]:
        chain: list[Any] = []
        if text:
            chain.append(Plain(text))
        for component in extra_components or []:
            if component is not None:
                chain.append(component)
        if image_path and os.path.exists(image_path):
            try:
                chain.append(Image.fromFileSystem(image_path))
            except AttributeError:
                chain.append(Image.from_file_system(image_path))
        if not chain:
            chain.append(Plain(""))
        return chain

    def _parse_message_session(self, umo: str) -> MessageSession | None:
        try:
            return MessageSession.from_str(str(umo or ""))
        except Exception:
            return None

    def _platform_instance_id(self, platform: Any | None) -> str:
        if platform is None:
            return ""
        try:
            meta = platform.meta()
        except Exception:
            return ""
        return str(getattr(meta, "id", "") or getattr(meta, "name", "") or "").strip()

    def _session_for_platform(self, session: MessageSession, platform: Any | None = None) -> MessageSession:
        platform_id = self._platform_instance_id(platform) or str(getattr(session, "platform_id", "") or "")
        return MessageSession(
            platform_name=platform_id,
            message_type=self._message_type_for_session(session),
            session_id=str(getattr(session, "session_id", "") or ""),
        )

    def _get_platform_for_session(self, session: MessageSession) -> Any | None:
        platform_id = str(getattr(session, "platform_id", "") or "")
        manager = getattr(self.context, "platform_manager", None)
        if not platform_id or not manager:
            return None
        platforms = []
        try:
            platforms = list(manager.get_insts())
        except Exception:
            platforms = list(getattr(manager, "platform_insts", []) or [])
        for platform in platforms:
            try:
                meta = platform.meta()
            except Exception:
                continue
            if getattr(meta, "id", "") == platform_id or getattr(meta, "name", "") == platform_id:
                return platform
        return None

    def _message_type_for_session(self, session: MessageSession) -> MessageType:
        msg_type = getattr(session, "message_type", MessageType.FRIEND_MESSAGE)
        if isinstance(msg_type, MessageType):
            return msg_type
        msg_type_text = str(msg_type or "")
        if "Group" in msg_type_text or "GROUP" in msg_type_text:
            return MessageType.GROUP_MESSAGE
        return MessageType.FRIEND_MESSAGE

    def _format_send_exception(self, exc: Exception | BaseException | None) -> str:
        if exc is None:
            return ""
        text = _single_line(str(exc), 180)
        if text:
            return f"{exc.__class__.__name__}: {text}"
        return repr(exc)

    @staticmethod
    def _is_onebot_event_checker_send_rejection(error: Any) -> bool:
        """Identify the NTQQ sendMsg rejection shared by every aiocqhttp send route."""
        text = str(error or "").strip().lower()
        compact = re.sub(r"\s+", "", text)
        has_retcode = any(
            token in compact
            for token in ("retcode=1200", "retcode:1200", "'retcode':1200", '\"retcode\":1200')
        )
        return bool(
            has_retcode
            and "eventcheckerfailed" in compact
            and ("sendmsg" in compact or "nodeikernelmsgservice" in compact)
        )

    @staticmethod
    def _onebot_event_checker_rejection_summary() -> str:
        return "QQ/NTQQ 拒绝发送（retcode=1200，EventChecker sendMsg）；目标可能暂时不可私聊、好友状态已变化，或 QQ 客户端正处于异常状态"

    def _describe_send_target(self, umo: str, session: MessageSession | None, platform: Any | None) -> str:
        if session is None:
            return f"umo={_single_line(umo, 140) or '-'} session=unparsed platform=-"
        platform_id = _single_line(getattr(session, "platform_id", ""), 60)
        session_id = _single_line(getattr(session, "session_id", ""), 80)
        message_type = _single_line(getattr(session, "message_type", ""), 60)
        platform_desc = "found" if platform else "missing"
        if platform:
            platform_desc = _single_line(self._platform_instance_id(platform), 80) or platform.__class__.__name__
        return (
            f"umo={_single_line(umo, 140) or '-'} "
            f"platform_id={platform_id or '-'} type={message_type or '-'} session_id={session_id or '-'} platform={platform_desc}"
        )

    async def _trigger_proactive_decorating_hooks(self, umo: str, chain: list[Any]) -> list[Any]:
        if not self.enable_proactive_decorating_hooks or not chain:
            return chain
        session = self._parse_message_session(umo)
        if not session:
            return chain
        platform = self._get_platform_for_session(session)
        if not platform:
            return chain
        try:
            message_obj = AstrBotMessage()
            message_obj.type = self._message_type_for_session(session)
            message_obj.self_id = str(getattr(session, "session_id", "") or "")
            message_obj.session_id = str(getattr(session, "session_id", "") or "")
            message_obj.message_id = f"private_companion_proactive_{uuid.uuid4().hex}"
            message_obj.sender = MessageMember(user_id=message_obj.session_id)
            message_obj.message = chain
            message_obj.message_str = ""
            message_obj.raw_message = None
            message_obj.timestamp = int(time.time())
            event = AstrMessageEvent("", message_obj, platform.meta(), message_obj.session_id)
            event.set_result(self._build_result_from_chain(chain))
            for component in chain:
                raw_full_text = getattr(component, "_private_companion_proactive_full_text", "")
                if not raw_full_text:
                    continue
                setattr(event, "_private_companion_proactive_full_text", raw_full_text)
                setattr(
                    event,
                    "_private_companion_proactive_segment_index",
                    max(0, int(getattr(component, "_private_companion_proactive_segment_index", 0) or 0)),
                )
                setattr(
                    event,
                    "_private_companion_proactive_segment_count",
                    max(1, int(getattr(component, "_private_companion_proactive_segment_count", 1) or 1)),
                )
                break
            if any(
                bool(getattr(component, "_private_companion_skip_tts_enhancement", False))
                for component in chain
            ):
                setattr(event, "_private_companion_skip_tts_enhancement", "proactive_prebuilt_voice")
        except Exception as e:
            logger.debug("[PrivateCompanion] 构造主动消息装饰事件失败,跳过 hooks: %s", e)
            return chain
        try:
            handlers = star_handlers_registry.get_handlers_by_event_type(
                EventType.OnDecoratingResultEvent
            )
        except Exception as e:
            logger.debug("[PrivateCompanion] 获取装饰 hooks 失败: %s", e)
            return chain
        for handler in handlers:
            try:
                await handler.handler(event)
            except Exception as e:
                logger.warning(
                    "[PrivateCompanion] 主动消息装饰 hook 失败: %s: %s",
                    getattr(handler, "handler_full_name", "unknown"),
                    e,
                )
        result = event.get_result()
        processed = getattr(result, "chain", None) if result is not None else None
        processed_chain = list(processed or []) if processed is not None else chain
        return self._filter_decorated_proactive_chain(chain, processed_chain)

    def _proactive_plain_segment_component(
        self,
        text: str,
        *,
        full_text: str = "",
        index: int = 0,
        count: int = 1,
        suppress_tts: bool = False,
    ) -> Plain:
        comp = Plain(text)
        clean_full = _single_line(full_text, max(1200, len(str(full_text or "")) + 32))
        if clean_full:
            try:
                object.__setattr__(comp, "_private_companion_proactive_full_text", clean_full)
                object.__setattr__(comp, "_private_companion_proactive_segment_index", max(0, int(index)))
                object.__setattr__(comp, "_private_companion_proactive_segment_count", max(1, int(count)))
            except Exception:
                pass
        if suppress_tts:
            try:
                object.__setattr__(comp, "_private_companion_skip_tts_enhancement", True)
            except Exception:
                pass
        return comp

    def _filter_decorated_proactive_chain(self, original_chain: list[Any], processed_chain: list[Any]) -> list[Any]:
        if not processed_chain:
            return original_chain

        filtered: list[Any] = []
        removed_any = False
        for component in processed_chain:
            if isinstance(component, Plain):
                text = self._plain_component_text(component)
                if self._is_proactive_delivery_receipt_text(text):
                    removed_any = True
                    continue
                cleaned = self._strip_proactive_delivery_receipt_lines(text)
                if not cleaned:
                    removed_any = True
                    continue
                if cleaned != text:
                    removed_any = True
                    filtered.append(Plain(cleaned))
                else:
                    filtered.append(component)
                continue
            filtered.append(component)

        if filtered:
            return filtered
        return original_chain if removed_any else processed_chain

    @staticmethod
    def _plain_component_text(component: Any) -> str:
        for attr in ("text", "content", "message"):
            value = getattr(component, attr, None)
            if isinstance(value, str):
                return value
        return str(component or "")

    @staticmethod
    def _contains_inline_image_tag(text: str) -> bool:
        return bool(re.search(r"<img\b[^>]*\bsrc\s*=", str(text or ""), flags=re.IGNORECASE))

    @staticmethod
    def _is_proactive_delivery_receipt_text(text: str) -> bool:
        raw = _single_line(text, 240)
        if not raw:
            return False
        compact = re.sub(r"[\s。.!！?？,，；;:：、~～\"'“”‘’（）()【】\[\]]+", "", raw).lower()
        if not compact:
            return False
        if compact in {
            "已发送",
            "发送成功",
            "发送完成",
            "发送完毕",
            "已成功发送",
            "消息已发送",
            "消息发送成功",
            "messagesent",
            "sent",
        }:
            return True
        receipt_prefixes = (
            "消息已发送给",
            "消息发送给",
            "已发送给",
            "已经发送给",
            "已向",
            "已经向",
        )
        receipt_descriptors = (
            "讲的是",
            "说的是",
            "内容是",
            "内容就是",
            "发的是",
            "转述的是",
            "分享的是",
            "告诉的是",
        )
        if compact.startswith(receipt_prefixes) and any(token in compact for token in receipt_descriptors):
            return True
        long_receipt_markers = (
            ("已经把", "转给"),
            ("已把", "转给"),
            ("已经将", "转给"),
            ("已将", "转给"),
            ("已经发给", "就假装"),
            ("已经发送给", "就假装"),
            ("就假装", "语气很自然"),
            ("随手分享", "语气很自然"),
        )
        if any(all(token in raw for token in pair) for pair in long_receipt_markers):
            return True
        if (
            any(token in compact for token in ("视频链接转给", "链接转给", "消息转给", "内容转给"))
            and any(token in compact for token in ("已经", "已", "完成", "成功"))
        ):
            return True
        return (
            len(compact) <= 32
            and any(token in compact for token in ("发送给用户", "发给用户", "发送给对方", "发给对方", "发出去了"))
            and any(token in compact for token in ("已", "已经", "完成", "成功"))
        )

    @staticmethod
    def _is_proactive_instruction_leak_text(text: str) -> bool:
        raw = _single_line(text, 360)
        if not raw:
            return False
        compact = re.sub(r"[\s。.!！?？,，；;:：、~～\"'“”‘’（）()【】\[\]<>《》]+", "", raw).lower()
        if not compact:
            return False
        exact_leaks = {
            "直接在当前对话中输出这条主动消息",
            "请直接在当前对话中输出这条主动消息",
            "在当前对话中输出这条主动消息",
            "直接输出这条主动消息",
            "输出这条主动消息",
            "发送这条主动消息",
            "sendthisproactivemessage",
            "outputthisproactivemessage",
        }
        if compact in exact_leaks:
            return True
        has_proactive_target = "主动消息" in raw or "proactive message" in raw.lower()
        has_delivery_command = any(
            token in compact
            for token in (
                "直接输出",
                "请输出",
                "输出这条",
                "输出本条",
                "直接发送",
                "请发送",
                "发送这条",
                "发出这条",
                "sendthis",
                "outputthis",
            )
        )
        has_instruction_context = any(
            token in compact
            for token in (
                "当前对话",
                "当前聊天",
                "本轮对话",
                "用户对话",
                "聊天窗口",
                "给用户",
                "touser",
                "currentchat",
                "currentconversation",
            )
        )
        if has_proactive_target and has_delivery_command and (has_instruction_context or len(compact) <= 36):
            return True
        if len(compact) <= 44 and has_delivery_command and has_instruction_context and any(
            token in compact for token in ("消息", "正文", "文本", "content", "message")
        ):
            return True
        return False

    def _strip_proactive_delivery_receipt_lines(self, text: str) -> str:
        kept: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._is_proactive_delivery_receipt_text(line):
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _validate_proactive_outbound_candidate(
        self,
        text: str,
        *,
        image_path: str = "",
        extra_components: list[Any] | None = None,
        reason: str = "",
        action: str = "",
        source: str = "send",
    ) -> dict[str, Any]:
        raw = str(text or "").strip()
        has_media = bool(_single_line(image_path, 260)) or bool(extra_components)
        if not raw:
            if has_media:
                return {"decision": "send", "text": "", "reason": ""}
            return {"decision": "drop", "text": "", "reason": "主动行为没有产出可发送内容", "hard": True}
        if self._looks_like_internal_provider_error_text(raw):
            return {"decision": "drop", "text": "", "reason": "主动正文是模型/工具调用失败信息", "hard": True}

        kept_lines: list[str] = []
        removed_leak = False
        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if (
                self._is_proactive_delivery_receipt_text(line)
                or self._is_proactive_instruction_leak_text(line)
                or self._framework_agent_meta_summary_leak(line)
            ):
                removed_leak = True
                continue
            kept_lines.append(line)
        if removed_leak:
            cleaned = "\n".join(kept_lines).strip()
            if cleaned:
                return {"decision": "rewrite", "text": cleaned, "reason": "已清理主动正文中的内部提示词/执行回执残留"}
            if has_media:
                return {"decision": "rewrite", "text": "", "reason": "已清理主动正文中的内部提示词/执行回执残留"}
            return {"decision": "drop", "text": "", "reason": "主动正文只剩内部提示词/执行回执残留", "hard": True}

        if self._is_proactive_delivery_receipt_text(raw):
            return {"decision": "drop", "text": "", "reason": "主动正文是工具/执行状态回执", "hard": True}
        if self._is_proactive_instruction_leak_text(raw):
            return {"decision": "drop", "text": "", "reason": "主动正文疑似内部提示词/发送指令泄漏", "hard": True}
        if self._framework_agent_meta_summary_leak(raw):
            return {"decision": "drop", "text": "", "reason": "主动正文疑似工具循环/内部发送摘要泄漏", "hard": True}

        return {"decision": "send", "text": raw, "reason": ""}

    def _proactive_archive_context_text(self, text: str) -> bool:
        cleaned = _single_line(text, 500)
        if not cleaned:
            return False
        if "【主动承接占位】" in cleaned or "下一条是 Bot 主动发出的内容" in cleaned:
            return True
        if self._is_proactive_delivery_receipt_text(cleaned):
            return True
        return False

    @staticmethod
    def _strip_leading_sentence_boundary_artifacts(text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"^(?:[。！？!?；;，,、：:]+[\s\u3000]*)+", "", cleaned).strip()
        return cleaned

    def _forward_sender_id_for_segments(self, event: Any | None = None) -> str:
        if event is not None:
            try:
                sender_id = _single_line(self._event_self_id(event), 40)
                if sender_id:
                    return sender_id
            except Exception:
                pass
        for sender_id in self._known_bot_self_ids():
            if sender_id:
                return sender_id
        return "0"

    def _forward_nodes_for_segments(self, segments: list[str], *, event: Any | None = None) -> list[dict[str, Any]]:
        sender_name = _single_line(getattr(self, "bot_name", ""), 40) or "PrivateCompanion"
        sender_id = self._forward_sender_id_for_segments(event)
        nodes: list[dict[str, Any]] = []
        for segment in segments:
            text = str(segment or "").strip()
            if not text:
                continue
            nodes.append(
                {
                    "type": "node",
                    "data": {
                        "name": sender_name,
                        "uin": sender_id,
                        "content": [{"type": "text", "data": {"text": text}}],
                    },
                }
            )
        return nodes

    def _clean_forward_segment_texts(self, segments: list[str]) -> list[str]:
        cleaned: list[str] = []
        for segment in segments:
            text = re.sub(r"</?t{2,}s\b[^>]*>", "", str(segment or ""), flags=re.IGNORECASE).strip()
            text = self._strip_leading_sentence_boundary_artifacts(text)
            if text:
                cleaned.append(text)
        return cleaned

    def _onebot_forward_action_result_ok(self, result: Any) -> bool:
        if result is None:
            return False
        if isinstance(result, dict):
            status = str(result.get("status") or result.get("result") or "").strip().lower()
            if status in {"failed", "fail", "error", "nok"}:
                return False
            retcode = result.get("retcode", result.get("code", None))
            if retcode is not None:
                try:
                    return int(retcode) == 0
                except Exception:
                    return False
            data = result.get("data")
            if isinstance(data, dict) and any(data.get(key) for key in ("message_id", "forward_id", "res_id", "resid")):
                return True
            return any(result.get(key) for key in ("message_id", "forward_id", "res_id", "resid"))
        return bool(result)

    async def _call_onebot_forward_action(self, client: Any, action: str, **params: Any) -> bool:
        for attr in ("call_action", "call_api", "api"):
            func = getattr(client, attr, None)
            if not callable(func):
                continue
            try:
                result = func(action, **params)
                if hasattr(result, "__await__"):
                    result = await result
                if self._onebot_forward_action_result_ok(result):
                    return True
            except TypeError:
                try:
                    result = func(action, params)
                    if hasattr(result, "__await__"):
                        result = await result
                    if self._onebot_forward_action_result_ok(result):
                        return True
                except Exception:
                    continue
            except Exception:
                continue
        func = getattr(client, action, None)
        if callable(func):
            try:
                result = func(**params)
                if hasattr(result, "__await__"):
                    result = await result
                return self._onebot_forward_action_result_ok(result)
            except Exception:
                return False
        return False

    async def _send_segmented_forward_message(
        self,
        *,
        target_type: str,
        target_id: str,
        segments: list[str],
        event: Any | None = None,
        source: str = "",
        report_delivery: bool = False,
    ) -> bool | None:
        """True: sent/handled; False: unavailable; None: blocked in delivery mode."""
        if not getattr(self, "segmented_proactive_send_as_forward", False):
            return False
        target_type = str(target_type or "").strip().lower()
        target_id = _single_line(target_id, 80)
        if target_type not in {"private", "group"} or not target_id:
            return False
        raw_segments = [_redact_outbound_secrets(item, self).strip() for item in segments if str(item or "").strip()]
        if len(raw_segments) <= 1:
            return False
        if getattr(self, "enable_tts_enhancement", False) and any(re.search(r"</?t{2,}s\b", item, flags=re.IGNORECASE) for item in raw_segments):
            logger.info("[PrivateCompanion] 分段合并消息跳过 TTS 内容: source=%s target=%s:%s", source or "unknown", target_type, target_id)
            return False
        cleaned_segments = self._clean_forward_segment_texts(raw_segments)
        if len(cleaned_segments) <= 1:
            return False
        hit = self._forbidden_recall_hit("\n".join(cleaned_segments))
        if hit:
            logger.warning(
                "[PrivateCompanion] 分段合并消息命中违禁词，已拦截发送: source=%s target=%s:%s word=%s",
                source or "unknown",
                target_type,
                target_id,
                _single_line(hit, 40),
            )
            return None if report_delivery else True
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return False
        nodes = self._forward_nodes_for_segments(cleaned_segments, event=event)
        if len(nodes) <= 1:
            return False
        target_value: Any = target_id
        try:
            target_value = int(target_id)
        except Exception:
            pass
        if target_type == "group":
            attempts = [
                ("send_group_forward_msg", {"group_id": target_value, "messages": nodes}),
                ("send_group_forward_msg", {"group_id": target_value, "nodes": nodes}),
                ("send_forward_msg", {"group_id": target_value, "messages": nodes}),
                ("send_forward_msg", {"group_id": target_value, "nodes": nodes}),
            ]
        else:
            attempts = [
                ("send_private_forward_msg", {"user_id": target_value, "messages": nodes}),
                ("send_private_forward_msg", {"user_id": target_value, "nodes": nodes}),
                ("send_forward_msg", {"user_id": target_value, "messages": nodes}),
                ("send_forward_msg", {"user_id": target_value, "nodes": nodes}),
            ]
        for action, params in attempts:
            if await self._call_onebot_forward_action(client, action, **params):
                logger.info(
                    "[PrivateCompanion] 分段消息已合并转发发送: source=%s target=%s:%s segments=%s",
                    source or "unknown",
                    target_type,
                    target_id,
                    len(cleaned_segments),
                )
                return True
        logger.info(
            "[PrivateCompanion] 分段合并转发发送不可用，回退普通分段: source=%s target=%s:%s segments=%s",
            source or "unknown",
            target_type,
            target_id,
            len(cleaned_segments),
        )
        return False

    async def _send_segmented_proactive_forward_message(self, umo: str, segments: list[str], *, source: str = "proactive") -> bool | None:
        session = self._parse_message_session(umo)
        if not session:
            return False
        target_id = _single_line(getattr(session, "session_id", ""), 80)
        if not target_id:
            return False
        target_type = "group" if self._message_type_for_session(session) == MessageType.GROUP_MESSAGE else "private"
        return await self._send_segmented_forward_message(
            target_type=target_type,
            target_id=target_id,
            segments=segments,
            source=source,
            report_delivery=True,
        )

    async def _send_segmented_event_forward_message(self, event: AstrMessageEvent, segments: list[str], *, source: str = "decorating_result") -> bool:
        try:
            if bool(getattr(event, "is_private_chat", lambda: False)()):
                user_id = _single_line(event.get_sender_id(), 80)
                if user_id:
                    return await self._send_segmented_forward_message(
                        target_type="private",
                        target_id=user_id,
                        segments=segments,
                        event=event,
                        source=source,
                    )
        except Exception:
            pass
        group_id = self._extract_group_id_from_event(event)
        if group_id:
            return await self._send_segmented_forward_message(
                target_type="group",
                target_id=group_id,
                segments=segments,
                event=event,
                source=source,
            )
        return False

    def _segmented_chat_scope_allows(self, chat_type: str) -> bool:
        scope = str(getattr(self, "segmented_proactive_chat_scope", "all") or "all").strip().lower()
        if scope not in {"all", "private", "group"}:
            scope = "all"
        chat_type = str(chat_type or "").strip().lower()
        return scope == "all" or scope == chat_type

    def _segmented_scope_allows_umo(self, umo: str) -> bool:
        session = self._parse_message_session(umo)
        if not session:
            return self._segmented_chat_scope_allows("private")
        chat_type = "group" if self._message_type_for_session(session) == MessageType.GROUP_MESSAGE else "private"
        return self._segmented_chat_scope_allows(chat_type)

    def _segmented_scope_allows_event(self, event: AstrMessageEvent) -> bool:
        try:
            if bool(getattr(event, "is_private_chat", lambda: False)()):
                return self._segmented_chat_scope_allows("private")
        except Exception:
            pass
        if self._extract_group_id_from_event(event):
            return self._segmented_chat_scope_allows("group")
        return self._segmented_chat_scope_allows("private")

    async def _onebot_messages_from_chain(self, chain: list[Any]) -> tuple[list[dict[str, Any]], str]:
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

            messages = await AiocqhttpMessageEvent._parse_onebot_json(MessageChain(chain))
            return list(messages or []), ""
        except Exception as exc:
            return [], self._format_send_exception(exc)

    async def _send_chain_components_via_onebot_direct(
        self,
        umo: str,
        session: MessageSession | None,
        chain: list[Any],
        *, require_companion_image: bool = False,
    ) -> tuple[bool, str]:
        if session is None:
            return False, "UMO 无法解析，不能使用 OneBot 原生兜底"
        target_id = _single_line(getattr(session, "session_id", ""), 80)
        if not target_id or not target_id.isdigit():
            return False, f"session_id 不是纯数字，不能使用 OneBot 原生兜底: {target_id or '-'}"
        client = self._resolve_aiocqhttp_client()
        if client is None:
            return False, "没有找到可用的 aiocqhttp/OneBot 客户端"
        messages, parse_error = await self._onebot_messages_from_chain(chain)
        if not messages:
            return False, parse_error or "消息链无法转换为 OneBot 消息段"
        target_value: Any = target_id
        try:
            target_value = int(target_id)
        except Exception:
            pass
        is_group = self._message_type_for_session(session) == MessageType.GROUP_MESSAGE
        action = "send_group_msg" if is_group else "send_private_msg"
        params = {"group_id": target_value, "message": messages} if is_group else {"user_id": target_value, "message": messages}
        ok, error = await self._call_onebot_action_with_error(
            client, action, _companion_single_dispatch=require_companion_image, **params)
        if ok:
            logger.info(
                "[PrivateCompanion] 主动消息已通过 OneBot 原生兜底发送: action=%s target=%s segments=%s umo=%s",
                action,
                target_id,
                len(messages),
                _single_line(umo, 140),
            )
            return True, ""
        return False, error or f"OneBot 原生动作 {action} 返回失败"

    async def _send_chain_components(self, umo: str, chain: list[Any], *, require_companion_image: bool = False) -> bool:
        """Return True only after delivery; blocked/empty chains return False."""
        if not chain:
            return False
        chain_redactor = getattr(self, "_redact_outbound_chain_secrets", None)
        if callable(chain_redactor):
            chain, redacted = chain_redactor(chain)
            if redacted:
                logger.error("[PrivateCompanion] 主动发送前检测到敏感凭据并已脱敏: umo=%s stage=before_hooks", _single_line(umo, 120))
        hit = self._forbidden_recall_hit(self._chain_text_for_forbidden_recall(chain))
        if hit:
            logger.warning(
                "[PrivateCompanion] 主动待发送消息命中违禁词，已拦截发送: umo=%s word=%s",
                umo,
                _single_line(hit, 40),
            )
            notifier = getattr(self, "_schedule_reply_interception_forward", None)
            if callable(notifier):
                notifier(
                    "proactive_block",
                    source="主动发送组件校验",
                    reason=f"命中违禁词：{_single_line(hit, 40)}",
                    source_session=umo,
                    before=self._chain_text_for_forbidden_recall(chain),
                )
            return False
        if require_companion_image:
            from copy import deepcopy
            approved_chain = deepcopy(chain)
            approved_fingerprint = self._companion_delivery_fingerprint(approved_chain)
            for component in chain:
                if isinstance(component, Plain):
                    object.__setattr__(component, '_private_companion_skip_tts_enhancement', True)
        processed_chain = await self._trigger_proactive_decorating_hooks(umo, chain)
        if require_companion_image:
            processed_chain = list(processed_chain or [])
        if not processed_chain and not require_companion_image:
            notifier = getattr(self, "_schedule_reply_interception_forward", None)
            if callable(notifier):
                notifier(
                    "proactive_block",
                    source="主动发送装饰钩子",
                    reason="装饰钩子清空了待发送消息",
                    source_session=umo,
                    before=self._chain_text_for_forbidden_recall(chain),
                )
            return False
        if callable(chain_redactor):
            processed_chain, redacted = chain_redactor(processed_chain)
            if redacted:
                logger.error("[PrivateCompanion] 主动装饰后检测到敏感凭据并已脱敏: umo=%s stage=after_hooks", _single_line(umo, 120))
        if not processed_chain and not require_companion_image:
            return False
        tts_chain_guard = getattr(self, "_sanitize_outbound_tts_chain_without_event", None)
        if callable(tts_chain_guard):
            processed_chain = await tts_chain_guard(processed_chain, umo=umo)
            if not processed_chain and not require_companion_image:
                notifier = getattr(self, "_schedule_reply_interception_forward", None)
                if callable(notifier):
                    notifier("proactive_block", source="主动发送 TTS 校验", reason="TTS 校验清空了待发送消息", source_session=umo)
                return False
        if require_companion_image:
            # Decorators may rewrite text or drop a picture. Restore only the
            # already validated image/plain from this approved delivery.
            processed_chain = self._restore_companion_delivery_chain(
                approved_chain, list(processed_chain or []), fingerprint=approved_fingerprint)
            if not self._companion_chain_has_image_and_text(processed_chain):
                return False
            if self._companion_final_send_block_reason(umo):
                return False
        hit = self._forbidden_recall_hit(self._chain_text_for_forbidden_recall(processed_chain))
        if hit:
            logger.warning(
                "[PrivateCompanion] 主动装饰后消息命中违禁词，已拦截发送: umo=%s word=%s",
                umo,
                _single_line(hit, 40),
            )
            notifier = getattr(self, "_schedule_reply_interception_forward", None)
            if callable(notifier):
                notifier(
                    "proactive_block",
                    source="主动装饰后校验",
                    reason=f"装饰后命中违禁词：{_single_line(hit, 40)}",
                    source_session=umo,
                    before=self._chain_text_for_forbidden_recall(processed_chain),
                )
            return False
        session = self._parse_message_session(umo)
        platform = self._get_platform_for_session(session) if session else None
        precise_error: Exception | None = None
        if self.enable_precise_platform_send and session and platform:
            try:
                status = getattr(platform, "status", None)
                if status is not None and status != PlatformStatus.RUNNING:
                    logger.warning("[PrivateCompanion] 目标平台未运行,跳过主动发送: %s", umo)
                    notifier = getattr(self, "_schedule_reply_interception_forward", None)
                    if callable(notifier):
                        notifier("proactive_block", source="主动发送平台校验", reason="目标平台未运行", source_session=umo, before=self._chain_text_for_forbidden_recall(processed_chain))
                    return False
                session_obj = self._session_for_platform(session, platform)
                precise_result = await platform.send_by_session(session_obj, MessageChain(processed_chain))
                if precise_result is not False or not require_companion_image:
                    return True
                # An explicit False is a confirmed non-delivery, unlike a
                # timeout after dispatch; the established safe fallback is OK.
            except asyncio.CancelledError as exc:
                if require_companion_image:
                    self._companion_mark_uncertain_cancellation('precise_platform', exc)
                raise
            except Exception as e:
                precise_error = e
                if self._is_onebot_event_checker_send_rejection(e):
                    summary = self._onebot_event_checker_rejection_summary()
                    logger.info(
                        "[PrivateCompanion] 主动发送被 QQ/NTQQ 底层拒绝，停止对同一 sendMsg 链路的立即重复尝试: target=%s",
                        self._describe_send_target(umo, session, platform),
                    )
                    raise RuntimeError(summary) from e
                if require_companion_image:
                    raise self._companion_delivery_uncertain_exception('precise_platform', e) from e
                logger.warning(
                    "[PrivateCompanion] 精确平台发送失败,回退核心发送: target=%s error=%s",
                    self._describe_send_target(umo, session, platform),
                    self._format_send_exception(e),
                )
        core_error: Exception | None = None
        core_result: Any = None
        core_session: str | MessageSession = umo
        if session and platform:
            core_session = self._session_for_platform(session, platform)
        try:
            core_result = await self.context.send_message(core_session, self._build_result_from_chain(processed_chain))
            if core_result is not False:
                return True
            logger.warning(
                "[PrivateCompanion] 主动核心发送未找到匹配平台,尝试 OneBot 原生兜底: target=%s",
                self._describe_send_target(umo, session, platform),
            )
        except asyncio.CancelledError as exc:
            if require_companion_image:
                self._companion_mark_uncertain_cancellation('astrbot_core', exc)
            raise
        except Exception as e:
            core_error = e
            if self._is_onebot_event_checker_send_rejection(e):
                logger.info(
                    "[PrivateCompanion] 主动核心发送被 QQ/NTQQ 底层拒绝，停止同链立即重试: target=%s",
                    self._describe_send_target(umo, session, platform),
                )
                raise RuntimeError(self._onebot_event_checker_rejection_summary()) from e
            if require_companion_image:
                raise self._companion_delivery_uncertain_exception('astrbot_core', e) from e
            target = self._describe_send_target(umo, session, platform)
            precise_text = self._format_send_exception(precise_error) or "未尝试或未失败"
            fallback_text = self._format_send_exception(e)
            logger.warning(
                "[PrivateCompanion] 主动核心发送失败: target=%s precise_error=%s fallback_error=%s",
                target,
                precise_text,
                fallback_text,
            )
        if require_companion_image:
            direct_ok, direct_error = await self._send_chain_components_via_onebot_direct(
                umo, session, processed_chain, require_companion_image=True)
        else:
            direct_ok, direct_error = await self._send_chain_components_via_onebot_direct(umo, session, processed_chain)
        if direct_ok:
            return True
        if self._is_onebot_event_checker_send_rejection(direct_error):
            raise RuntimeError(self._onebot_event_checker_rejection_summary())
        target = self._describe_send_target(umo, session, platform)
        precise_text = self._format_send_exception(precise_error) or "未尝试或未失败"
        if core_error is not None:
            fallback_text = self._format_send_exception(core_error)
        elif core_result is False:
            fallback_text = "AstrBot 核心发送返回 False（未找到匹配平台或平台拒绝发送）"
        else:
            fallback_text = "未尝试或未失败"
        logger.warning(
            "[PrivateCompanion] 主动发送兜底也失败: target=%s precise_error=%s fallback_error=%s direct_error=%s",
            target,
            precise_text,
            fallback_text,
            direct_error,
        )
        raise RuntimeError(
            f"主动消息发送失败: {target}; precise={precise_text}; fallback={fallback_text}; direct={direct_error}"
        ) from core_error

    async def _send_media_proactive_chain(
        self,
        umo: str,
        text: str,
        image_path: str = "",
        *,
        extra_components: list[Any] | None = None,
        quote_message_id: str = "",
        disable_segmenting: bool = False,
    ) -> bool:
        sent_any = False
        trigger_message_id = _single_line(quote_message_id, 120)
        has_prebuilt_voice = any(isinstance(component, Record) for component in (extra_components or []))
        if self._contains_inline_image_tag(text):
            image_path = ""
            extra_components = []
        if text:
            await self._maybe_send_input_status(umo, text)
        segments = self._split_proactive_text(
            text,
            image_path="",
            extra_components=None,
            disable_segmenting=disable_segmenting or not self._segmented_scope_allows_umo(umo),
        )
        if len(segments) > 1:
            logger.info(
                "[PrivateCompanion] 主动媒体文本已分段: umo=%s segments=%s lengths=%s",
                _single_line(umo, 140),
                len(segments),
                [len(segment) for segment in segments],
            )
        if len(segments) <= 1:
            outbound_text = segments[0] if segments else ""
            if quote_message_id and self._quote_skip_reason_for_short_reply(outbound_text):
                quote_message_id = ""
            if outbound_text:
                recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
                if recalled_message_id:
                    logger.info("[PrivateCompanion] 触发消息已撤回，取消主动文本发送: umo=%s message_id=%s", umo, recalled_message_id)
                    return False
                delivered = await self._send_chain_components(
                    umo,
                    self._with_optional_reply(
                        [
                            self._proactive_plain_segment_component(
                                outbound_text,
                                full_text=text,
                                index=0,
                                count=1,
                                suppress_tts=has_prebuilt_voice,
                            )
                        ],
                        quote_message_id,
                    ),
                )
                if not delivered:
                    return False
                sent_any = True
                quote_message_id = ""
        else:
            recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
            if recalled_message_id:
                logger.info("[PrivateCompanion] 触发消息已撤回，取消主动合并分段发送: umo=%s message_id=%s", umo, recalled_message_id)
                return False
            forward_result = await self._send_segmented_proactive_forward_message(umo, segments, source="proactive_media_text")
            if forward_result is None:
                return False
            if forward_result:
                sent_any = True
                quote_message_id = ""
            else:
                for index, segment in enumerate(segments):
                    if index == 0 and quote_message_id and self._quote_skip_reason_for_short_reply(segment):
                        quote_message_id = ""
                    recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
                    if recalled_message_id:
                        logger.info("[PrivateCompanion] 触发消息已撤回，停止主动分段发送: umo=%s message_id=%s index=%s", umo, recalled_message_id, index + 1)
                        return False
                    segment_comp = self._proactive_plain_segment_component(
                        segment,
                        full_text=text,
                        index=index,
                        count=len(segments),
                        suppress_tts=has_prebuilt_voice,
                    )
                    chain = self._with_optional_reply([segment_comp], quote_message_id) if index == 0 else [segment_comp]
                    if not await self._send_chain_components(umo, chain):
                        return False
                    sent_any = True
                    quote_message_id = ""
                    if index < len(segments) - 1:
                        await asyncio.sleep(await self._calc_segmented_proactive_interval(segment))
        has_media = bool((extra_components or []) or (image_path and os.path.exists(image_path)))
        if has_media:
            logger.info(
                "[PrivateCompanion] 主动媒体发送: text_segments=%s image=%s extra_components=%s",
                len(segments),
                bool(image_path and os.path.exists(image_path)),
                len(extra_components or []),
            )
            recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
            if recalled_message_id:
                logger.info("[PrivateCompanion] 触发消息已撤回，取消主动媒体发送: umo=%s message_id=%s", umo, recalled_message_id)
                return False
            media_chain = self._build_outbound_chain("", image_path, extra_components=extra_components)
            media_chain = self._with_optional_reply(media_chain, quote_message_id)
            if not await self._send_chain_components(umo, media_chain):
                return False
            sent_any = True
        return sent_any

    def _separate_narration_and_dialogue(self, text: str) -> tuple[str, str] | None:
        """将文本中的旁白（括号内动作描写）与对话（引号内话语）分离。

        旁白：被中文括号\uff08\uff09、英文括号()、【】、[]包裹的片段。
        对话：被日式引号\u300c\u300d\u300e\u300f或普通引号包裹的片段，以及无包裹纯文本。
        本方法为主动消息旁白分离发送而设计，独立于 _split_proactive_text 内部的
        嵌套函数 _protected_cleanup_chunks（后者无法通过 self 调用）。

        Returns:
            (narration_text, dialogue_text) 若存在旁白；None 表示纯对话/无可分离内容。
        """
        try:
            if not text or not text.strip():
                return None

            bracket_pairs = {
                "\uff08": "\uff09",
                "(": ")",
                "\u3010": "\u3011",
                "[": "]",
            }
            quote_pairs = {
                "\u300c": "\u300d",
                "\u300e": "\u300f",
                "\u201c": "\u201d",
                "\"": "\"",
                "\u2018": "\u2019",
                "'": "'",
            }

            narration_parts: list[str] = []
            dialogue_parts: list[str] = []
            has_narration = False

            i = 0
            n = len(text)
            while i < n:
                ch = text[i]
                if ch in bracket_pairs:
                    close = bracket_pairs[ch]
                    j = i + 1
                    depth = 1
                    while j < n and depth > 0:
                        if text[j] == ch:
                            depth += 1
                        elif text[j] == close:
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    segment = text[i:j + 1] if j < n else text[i:]
                    narration_parts.append(segment)
                    has_narration = True
                    i = j + 1
                elif ch in quote_pairs:
                    close = quote_pairs[ch]
                    j = i + 1
                    while j < n and text[j] != close:
                        j += 1
                    segment = text[i:j + 1] if j < n else text[i:]
                    dialogue_parts.append(segment)
                    i = j + 1
                else:
                    j = i
                    while j < n and text[j] not in bracket_pairs and text[j] not in quote_pairs:
                        j += 1
                    segment = text[i:j]
                    if segment.strip():
                        dialogue_parts.append(segment)
                    i = j

            if not has_narration:
                return None

            narration_text = "".join(narration_parts).strip()
            dialogue_text = "".join(dialogue_parts).strip()

            if not narration_text:
                return None

            return (narration_text, dialogue_text)
        except Exception:
            return None

    async def _send_proactive_message_chain(
        self,
        umo: str,
        text: str,
        image_path: str = "",
        *,
        extra_components: list[Any] | None = None,
        quote_message_id: str = "",
        disable_segmenting: bool = False,
        require_companion_image: bool = False,
    ) -> bool:
        """Return True only when all requested outbound parts were delivered."""
        if require_companion_image:
            if not text or not image_path:
                return False
            if self._should_cancel_reply_for_recalled_message_ids(_single_line(quote_message_id, 120)):
                return False
            cleaner = getattr(self, '_tts_visible_fallback_text', None)
            visible = cleaner(text) if callable(cleaner) else text
            components = [Image.fromFileSystem(image_path), self._proactive_plain_segment_component(visible, suppress_tts=True)]
            components.extend(c for c in (extra_components or [])
                              if not isinstance(c, (Plain, Image)) and not self._companion_component_has_nested_image(c))
            user = self._companion_delivery_user(umo)
            receipt = None
            if isinstance(user, dict) and user.get('companion_timer_retry_id') and user.get('companion_timer_retry_text') == text:
                receipt = (str(user['companion_timer_retry_id']), str(user['companion_timer_retry_text']))
            return await self._send_companion_chain_atomic(umo, components, timer_receipt=receipt)
        trigger_message_id = _single_line(quote_message_id, 120)
        placeholder_cleaner = getattr(self, "_sanitize_orphan_tts_placeholders", None)
        if callable(placeholder_cleaner):
            cleaned_text = placeholder_cleaner(text)
            if cleaned_text != text:
                logger.warning(
                    "[PrivateCompanion] 主动发送前清理孤儿 TTS 占位符: umo=%s before=%s after=%s",
                    _single_line(umo, 120),
                    _single_line(text, 120),
                    _single_line(cleaned_text, 120),
                )
                text = cleaned_text
        if image_path or extra_components:
            return await self._send_media_proactive_chain(
                umo,
                text,
                image_path,
                extra_components=extra_components,
                quote_message_id=quote_message_id,
                disable_segmenting=disable_segmenting,
            )
        if not text or not text.strip():
            return False
        if text:
            await self._maybe_send_input_status(umo, text)
        # 旁白与对话分离发送：先发旁白，间隔后再发对话
        narration_dialogue = self._separate_narration_and_dialogue(text)
        if narration_dialogue:
            narration_text, dialogue_text = narration_dialogue
            if narration_text.strip():
                narration_chain = self._proactive_plain_segment_component(narration_text, suppress_tts=False)
                if not await self._send_chain_components(umo, [narration_chain]):
                    return False
                await asyncio.sleep(await self._calc_segmented_proactive_interval(narration_text))
            if dialogue_text.strip():
                dialogue_chain = self._proactive_plain_segment_component(dialogue_text, suppress_tts=False)
                if not await self._send_chain_components(umo, [dialogue_chain]):
                    return False
            return True
        segments = self._split_proactive_text(
            text,
            image_path="",
            extra_components=None,
            disable_segmenting=disable_segmenting or not self._segmented_scope_allows_umo(umo),
        )
        if len(segments) > 1:
            logger.info(
                "[PrivateCompanion] 主动文本已分段: umo=%s segments=%s lengths=%s",
                _single_line(umo, 140),
                len(segments),
                [len(segment) for segment in segments],
            )
        if len(segments) <= 1:
            outbound_text = segments[0] if segments else text
            if quote_message_id and self._quote_skip_reason_for_short_reply(outbound_text):
                quote_message_id = ""
            recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
            if recalled_message_id:
                logger.info("[PrivateCompanion] 触发消息已撤回，取消主动消息发送: umo=%s message_id=%s", umo, recalled_message_id)
                return False
            return await self._send_chain_components(
                umo,
                self._with_optional_reply(
                    [
                        self._proactive_plain_segment_component(outbound_text, full_text=text, index=0, count=1)
                    ],
                    quote_message_id,
                ),
            )
        recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
        if recalled_message_id:
            logger.info("[PrivateCompanion] 触发消息已撤回，取消主动合并分段发送: umo=%s message_id=%s", umo, recalled_message_id)
            return False
        forward_result = await self._send_segmented_proactive_forward_message(umo, segments, source="proactive_text")
        if forward_result is None:
            return False
        if forward_result:
            return True
        for index, segment in enumerate(segments):
            if index == 0 and quote_message_id and self._quote_skip_reason_for_short_reply(segment):
                quote_message_id = ""
            recalled_message_id = self._should_cancel_reply_for_recalled_message_ids(trigger_message_id)
            if recalled_message_id:
                logger.info("[PrivateCompanion] 触发消息已撤回，停止主动消息分段发送: umo=%s message_id=%s index=%s", umo, recalled_message_id, index + 1)
                return False
            segment_comp = self._proactive_plain_segment_component(segment, full_text=text, index=index, count=len(segments))
            chain = self._with_optional_reply([segment_comp], quote_message_id) if index == 0 else [segment_comp]
            if not await self._send_chain_components(umo, chain):
                return False
            quote_message_id = ""
            if index < len(segments) - 1:
                await asyncio.sleep(await self._calc_segmented_proactive_interval(segment))
        return True

    def _build_outbound_result(
        self,
        text: str,
        image_path: str = "",
        extra_components: list[Any] | None = None,
    ) -> Any:
        chain = self._build_outbound_chain(text, image_path, extra_components=extra_components)
        return self._build_result_from_chain(chain)

    def _build_proactive_archive_user_prompt(
        self,
        *,
        reason: str,
        action: str,
        motive: str = "",
        action_summary: str = "",
    ) -> str:
        # AstrBot history is stored as user/assistant pairs, so proactive sends
        # need a tiny synthetic user side. Keep it neutral: internal reason,
        # motive and action details stay in plugin state instead of visible chat.
        return "【主动承接占位】用户还没发来新消息；下一条是 Bot 主动发出的内容。后续如果用户回应，顺着上一条主动消息自然接住就好。"

    def _build_proactive_archive_assistant_text(
        self,
        *,
        text: str,
        image_path: str = "",
        extra_components: list[Any] | None = None,
        action_summary: str = "",
        photo_subject_owner: str = "",
    ) -> str:
        original_is_receipt = self._is_proactive_delivery_receipt_text(text)
        message_text = self._visible_text_without_tts_reading(text, limit=1000)
        attachment_notes: list[str] = []
        if image_path:
            attachment_notes.append("随消息发送了一张图片")
            photo_caption = ""
            if "：" in str(action_summary or "") or ":" in str(action_summary or ""):
                photo_caption = _single_line(re.split(r"[:：]", str(action_summary), maxsplit=1)[-1], 220)
            if photo_caption and photo_caption not in {"发图", "图片", "photo_text"}:
                attachment_notes.append(f"图片画面：{photo_caption}")
            normalized_owner = _normalize_photo_subject_owner(photo_subject_owner)
            if normalized_owner:
                attachment_notes.append(f"图片主体：{_photo_subject_owner_prompt_label(normalized_owner)}")
        if extra_components:
            tts_notes: list[str] = []
            note_builder = getattr(self, "_tts_component_log_note", None)
            for comp in extra_components:
                if isinstance(comp, Record) and callable(note_builder):
                    note = _single_line(note_builder(comp), 220)
                    if note:
                        tts_notes.append(note)
            if tts_notes:
                attachment_notes.extend(tts_notes[:3])
            else:
                attachment_notes.append(f"随消息发送了 {len(extra_components)} 个附加消息组件")
        if attachment_notes:
            suffix = "（" + ",".join(attachment_notes) + "）"
            message_text = f"{message_text}{suffix}" if message_text else suffix
        if message_text:
            return message_text
        if original_is_receipt:
            return ""
        return _single_line(action_summary, 160) or "主动向用户发送了一条消息。"

    async def _archive_proactive_message_to_conversation(
        self,
        *,
        user: dict[str, Any],
        user_prompt: str,
        assistant_response: str,
    ) -> None:
        umo = str(user.get("umo") or "").strip()
        if not umo or not assistant_response:
            return
        for attempt in range(4):
            try:
                user_msg_obj = UserMessageSegment(content=str(user_prompt or ""))
                assistant_msg_obj = AssistantMessageSegment(content=str(assistant_response or ""))
                async def _write():
                    conv_id = await self._ensure_conversation_id_for_umo(umo, title="Private Companion 主动消息")
                    if not conv_id:
                        return False
                    await self.context.conversation_manager.add_message_pair(
                        cid=conv_id,
                        user_message=user_msg_obj,
                        assistant_message=assistant_msg_obj,
                    )
                    return True

                written = await self._conversation_db_operation("archive_proactive_message", _write)
                if not written:
                    logger.warning("[PrivateCompanion] 主动消息存档失败: 无法获取或创建 AstrBot 会话 history umo=%s", _single_line(umo, 140))
                    return
                if attempt > 0:
                    logger.info("[PrivateCompanion] 主动消息写入 AstrBot 会话历史成功: %s retry=%s", umo, attempt)
                else:
                    logger.info("[PrivateCompanion] 已将主动消息写入 AstrBot 会话历史: %s", umo)
                return
            except Exception as e:
                text = str(e or "").lower()
                if ("database is locked" in text or "sqlite3.operationalerror" in text) and attempt < 3:
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                logger.warning("[PrivateCompanion] 主动消息写入会话历史失败: %s", e)
                return

    def _format_story_plan_for_prompt(self) -> str:
        plan = self.data.get("daily_story_plan", {})
        if not isinstance(plan, dict) or plan.get("date") != _today_key():
            return "（暂无）"
        lines = []
        now_minutes = self._environment_now_minutes()
        events = plan.get("today_events", [])
        if isinstance(events, list) and events:
            nearby_events = [
                item for item in events
                if isinstance(item, dict) and self._story_item_relevant_to_now(item, now_minutes)
            ][:6]
            if nearby_events:
                lines.append("附近可能发生：")
                for item in nearby_events:
                    lines.append(f"- {item.get('window', '')}｜{item.get('event', '')}｜{item.get('mood', '')}")
        proactive = plan.get("proactive_events", [])
        if isinstance(proactive, list) and proactive:
            nearby_proactive = [
                item for item in proactive
                if isinstance(item, dict) and self._story_item_relevant_to_now(item, now_minutes, future_minutes=240)
            ][:6]
            if nearby_proactive:
                lines.append("附近主动计划：")
                for item in nearby_proactive:
                    lines.append(
                        f"- {item.get('window', '')}｜{item.get('reason', '')}｜{item.get('action', 'message')}｜"
                        f"{item.get('why', '')}｜{item.get('topic', '')}｜{item.get('motive', '')}｜"
                        f"{item.get('scene', '')}｜{item.get('tone', '')}｜{item.get('impulse', '')}"
                    )
        long_term = plan.get("long_term_events", [])
        if isinstance(long_term, list) and long_term:
            lines.append("长线事件：")
            for item in long_term[:4]:
                if isinstance(item, dict):
                    lines.append(
                        f"- {item.get('title', '')}｜{item.get('status', '')}｜"
                        f"{item.get('tendency', '')}｜{item.get('next_hint', '')}"
                    )
        return "\n".join(lines) if lines else "（暂无）"

    def _story_item_relevant_to_now(
        self,
        item: dict[str, Any],
        now_minutes: int,
        *,
        past_minutes: int = 90,
        future_minutes: int = 180,
    ) -> bool:
        start, end = self._parse_window_minutes(str(item.get("window") or ""))
        if start is None or end is None:
            return False
        candidates = [(start, end)]
        if end < start:
            candidates = [(start, end + 24 * 60), (start - 24 * 60, end)]
        for item_start, item_end in candidates:
            if item_end >= now_minutes - past_minutes and item_start <= now_minutes + future_minutes:
                return True
        return False

    def _format_plan_item_for_prompt(self, item: dict[str, Any] | None) -> str:
        if not isinstance(item, dict):
            return "（暂无）"
        parts = [
            str(item.get("time", "")).strip(),
            str(item.get("activity", "")).strip(),
            f"情绪：{item.get('mood', '')}".strip(),
        ]
        seed = _single_line(item.get("message_seed"), 120)
        if seed:
            parts.append(f"可分享碎片：{seed}")
        return "｜".join(part for part in parts if part)

    def _sanitize_proactive_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"<img\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</img>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>\n]{0,200}>", "", cleaned)
        cleaned = cleaned.replace("[图片]", "").replace("【图片】", "")
        cleaned = cleaned.replace("（图片已送达）", "").replace("(图片已送达)", "")
        cleaned = self._strip_internal_identity_anchors(cleaned)
        cleaned = re.sub(r"^```(?:text)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip().strip('"').strip("'")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        lines = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.fullmatch(r"[（(].{0,40}语音消息.{0,20}[)）]", line):
                continue
            if re.match(r"^(?:图片发过去了|希望他看到的时候|然后过了好一会儿)", line):
                continue
            if self._is_proactive_instruction_leak_text(line):
                continue
            if re.match(r"^[（(].{0,80}(?:翻了个身|裹紧了些|眼睛微微眯起来).*[）)]$", line):
                continue
            line = self._strip_parenthetical_stage_directions(line)
            if not line:
                continue
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(lines[:3])[:260]

    def _strip_parenthetical_stage_directions(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        stage_tokens = (
            "搅", "夹", "咬", "嚼", "喝", "抿", "吞", "放下", "拿起",
            "叹", "笑", "眨", "盯", "看", "望", "低头", "抬头", "偏头",
            "小声", "轻轻", "慢慢", "默默", "皱眉", "挑眉", "眯眼",
            "伸手", "缩", "靠", "蹭", "戳", "敲", "揉", "摸", "抱",
            "翻身", "裹", "坐", "站", "躺", "走", "晃", "顿了顿",
            # P3 新增词表
            "侧头", "歪头", "点头", "摇头", "转头", "回过头", "回身",
            "抿嘴", "嘟嘴", "咧嘴", "咬唇", "咬紧", "抿唇", "撇嘴",
            "弯腰", "俯身", "起身", "蹲下", "弯下",
            "挥手", "摆手", "招手", "握拳", "松开", "攥紧", "摊手",
            "踮脚", "跺脚", "踢", "跨", "迈步",
            "打哈欠", "伸懒腰", "揉眼", "捏鼻梁", "揉太阳穴",
            "深呼吸", "吐气", "吸气",
            "嘴角", "眉眼", "眼神", "目光",
            "凑近", "靠近", "退后", "转身",
            "托腮", "撑着", "倚着",
            "拉住", "拽住", "抓住", "牵着",
            "抬头望", "低头看", "别过脸", "移开视线",
            "轻声", "低声", "喃喃", "嘀咕",
        )

        def _replace(match: re.Match[str]) -> str:
            inner = (match.group(1) or "").strip()
            if not inner:
                return ""
            if any(token in inner for token in stage_tokens):
                return ""
            return match.group(0)

        cleaned = re.sub(r"^[（(]\s*[^()（）\n]{1,50}\s*[）)]\s*", "", cleaned)
        cleaned = re.sub(r"[（(]\s*([^()（）\n]{1,50})\s*[）)]", _replace, cleaned)
        return self._strip_leading_sentence_boundary_artifacts(re.sub(r"\s+", " ", cleaned).strip())

    def _normalize_proactive_sentence_flow(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        cleaned = self._strip_unsupported_proactive_agreement(cleaned)
        cleaned = self._trim_abrupt_closing_topic_shift(cleaned)
        cleaned = _normalize_outbound_punctuation_flow(cleaned)
        cleaned = cleaned.replace("！?", "！？").replace("？!", "？！")
        cleaned = re.sub(
            r"([A-Za-z0-9_\-]{1,40})[。！？!?]\s+(呢|呀|啊|嘛|吧|哦|喔|诶)(?=[，,。！？!?~～\s]|$)",
            r"\1\2",
            cleaned,
        )
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        raw_units: list[str] = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            raw_units.extend(self._split_proactive_sentence_units(line))

        if not raw_units:
            return ""

        merged: list[str] = []
        continuation_prefixes = (
            "又", "还", "也", "就", "才", "只是", "但", "但是", "不过", "然后", "所以",
            "有点", "有一点", "不想", "没想", "想着", "顺手",
        )
        for unit in raw_units:
            unit = unit.strip(" ,，、")
            if not unit:
                continue
            is_continuation = unit.startswith(continuation_prefixes)
            if merged and is_continuation:
                merged[-1] = merged[-1].rstrip("。！？!?；;，,") + "，" + unit
            else:
                merged.append(unit)

        normalized = [self._ensure_chat_sentence_punctuation(item) for item in merged]
        normalized = [item for item in normalized if item]
        if len(normalized) <= 3:
            return "\n".join(normalized)[:260]
        head = normalized[:2]
        tail = "".join(normalized[2:])
        return "\n".join(head + [tail])[:260]

    def _group_share_text_has_life_sidecar(self, text: str) -> bool:
        cleaned = _single_line(text, 500)
        if "群" not in cleaned:
            return False
        life_tokens = (
            "课", "老师", "同学", "作业", "草稿纸", "书", "笔", "桌", "窗", "路上",
            "小猫", "猫", "饭", "吃", "喝", "杯", "天气", "雨", "太阳", "云", "风",
            "困", "饿", "刚刚", "刚才", "这会儿",
        )
        return any(token in cleaned for token in life_tokens)

    def _strip_unsupported_proactive_agreement(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        patterns = (
            r"^(?:哈哈|哈|嘿|嗯嗯|嗯|唔|诶|欸)[，,。.\s]*(?:我也觉得|确实|对吧|是吧|真的)[，,。.\s]*",
            r"^(?:我也觉得|确实|对吧|是吧|真的)[，,。.\s]*",
            r"^(?:哈哈|哈)[，,。.\s]*(?=(?:今天|刚刚|刚才|现在|窗外|路上|云|天气|太阳|雨|风))",
        )
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or str(text or "").strip()

    def _trim_performative_self_state_tail(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        tail_clause_match = re.search(
            r"([，,；;。！？!?]\s*)"
            r"((?:我)?(?:刚刚|刚才|刚|这会儿|现在)?"
            r"(?:在|还在|正|正在)?"
            r"[^。！？!?；;\n，,]{0,14}"
            r"(?:发呆|发怔|晃神|躺着|趴着|盯着|望着|看着天花板|看天花板|刷手机|摸鱼|犯困|醒着|睡不着|放空|走神|缓神)"
            r"[^。！？!?；;\n，,]{0,18}"
            r"(?:来着|而已|呢|啦|。|！|？|~|～)?$)",
            cleaned,
        )
        if tail_clause_match:
            kept = cleaned[: tail_clause_match.start()].strip(" ,，、；;")
            if kept:
                result = self._finish_trimmed_proactive_text(kept)
                logger.info(
                    "[PrivateCompanion] 主动消息已去除刻意状态尾巴: before=%s after=%s",
                    _single_line(cleaned, 160),
                    _single_line(result, 160),
                )
                return result
        units: list[str] = []
        for line in cleaned.splitlines():
            line = line.strip()
            if line:
                units.extend(self._split_proactive_sentence_units(line))
        units = [unit.strip(" ,，、") for unit in units if unit.strip(" ,，、")]
        if len(units) <= 1:
            return cleaned
        tail = units[-1].strip()
        if not tail:
            return cleaned
        asks_user = bool(re.search(r"(你那边|你呢|你那儿|你那里|你现在|你今天|你还|你有没有|你要不要|你是不是)", tail))
        if asks_user:
            return cleaned
        performative_tail = bool(
            re.search(
                r"^(?:我)?(?:刚刚|刚才|刚|这会儿|现在)?"
                r"(?:在|还在|正|正在)?"
                r"[^。！？!?；;\n]{0,12}"
                r"(?:发呆|躺着|趴着|盯着|望着|看着天花板|看天花板|刷手机|摸鱼|犯困|醒着|睡不着|放空|走神|缓神)"
                r"[^。！？!?；;\n]{0,18}"
                r"(?:来着|而已|呢|啦|。|！|？|~|～)?$",
                tail,
            )
        )
        if not performative_tail:
            return cleaned
        kept = units[:-1]
        if not kept:
            return cleaned
        result = "\n".join(self._finish_trimmed_proactive_text(unit) for unit in kept if unit)
        result = result.strip()
        if result:
            logger.info(
                "[PrivateCompanion] 主动消息已去除刻意状态尾巴: before=%s after=%s",
                _single_line(cleaned, 160),
                _single_line(result, 160),
            )
            return result
        return cleaned

    def _proactive_status_inventory_kind(self, unit: str) -> str:
        cleaned = _single_line(unit, 140).strip(" ，,。！？!?~～")
        if not cleaned:
            return ""
        opener_match = re.match(r"^([\w\u4e00-\u9fffぁ-んァ-ヶー]{1,8})[，,]\s*", cleaned)
        if opener_match:
            opener_text = opener_match.group(1)
            if len(opener_text) <= 4 and not re.search(r"(窗外|外面|雨声|风声|天气|今天|现在|刚刚|刚才)", opener_text):
                cleaned = cleaned[opener_match.end():].strip()
        if re.search(r"(你|主人).{0,12}(吗|呢|呀|要不要|有没有)", cleaned):
            return ""
        if re.search(r"(窗外|外面|雨声|风声|雨|下雨|小雨|大雨|风|云|天色|阳光|太阳|月亮|路灯|杯沿|书页|桌边)", cleaned):
            return "scene"
        if re.search(r"^(?:我)?(?:刚刚|刚才|刚|才|已经|这会儿)?(?:洗漱|洗完|洗澡|刷牙|起床|醒|到家|出门|回家|吃完|喝完|写完|收拾完|换好|换完)", cleaned):
            return "routine"
        if re.search(r"^(?:我)?(?:今天|现在|刚刚|刚才|刚|才)?(?:穿了|穿着|换了|换成|披了|套了|戴了|拿了)", cleaned):
            return "clothing"
        if re.search(r"(舒服|安静|困|累|清醒|迷糊|开心|烦|平稳|舒服)", cleaned) and len(cleaned) <= 22:
            return "state"
        return ""

    def _trim_proactive_status_inventory(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        units: list[str] = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if line:
                units.extend(self._split_proactive_sentence_units(line))
        units = [unit.strip(" ，,、") for unit in units if unit.strip(" ，,、")]
        if len(units) < 2:
            return cleaned
        kinds = [self._proactive_status_inventory_kind(unit) for unit in units]
        inventory_count = sum(1 for kind in kinds if kind)
        if inventory_count < 2:
            return cleaned
        if len(units) == 2 and inventory_count < len(units):
            return cleaned
        opener = ""
        opener_match = re.match(r"^([\w\u4e00-\u9fffぁ-んァ-ヶー]{1,4}[，,])", units[0])
        if opener_match:
            opener = opener_match.group(1)
        priority = {"scene": 4, "clothing": 3, "routine": 2, "state": 1}
        best_index = max(
            range(len(units)),
            key=lambda index: (priority.get(kinds[index], 0), index),
        )
        chosen = units[best_index].strip()
        if opener:
            chosen = re.sub(r"^[\w\u4e00-\u9fffぁ-んァ-ヶー]{1,4}[，,]\s*", "", chosen).strip()
            if chosen:
                chosen = f"{opener}{chosen}"
        chosen = self._ensure_chat_sentence_punctuation(chosen)
        if chosen and chosen != cleaned:
            logger.info(
                "[PrivateCompanion] 主动消息已收束状态清单: before=%s after=%s",
                _single_line(cleaned, 180),
                _single_line(chosen, 160),
            )
            return chosen
        return cleaned

    def _finish_trimmed_proactive_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        lines = [line.strip(" ,，、；;") for line in cleaned.splitlines() if line.strip(" ,，、；;")]
        if not lines:
            return ""
        return "\n".join(self._ensure_chat_sentence_punctuation(line) for line in lines)

    def _has_abrupt_closing_topic_shift(self, text: str, *, inbound_text: str = "") -> bool:
        original = str(text or "").strip()
        if not original:
            return False
        trimmed = self._trim_abrupt_closing_topic_shift(original, inbound_text=inbound_text)
        return bool(trimmed and trimmed != original)

    def _trim_abrupt_closing_topic_shift(self, text: str, *, inbound_text: str = "") -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        units = []
        for line in cleaned.splitlines():
            line = line.strip()
            if line:
                units.extend(self._split_proactive_sentence_units(line))
        units = [unit.strip(" ,，、") for unit in units if unit.strip(" ,，、")]
        if len(units) <= 1:
            return cleaned
        inbound = _single_line(inbound_text, 260)
        inbound_is_sleep_context = bool(re.search(r"(晚安|睡了|睡觉|做梦|好梦|困了|休息|先睡|去睡|早点睡)", inbound))
        closing_index = -1
        for index, unit in enumerate(units):
            if re.search(r"(晚安|好梦|做个梦|做梦|睡吧|睡觉|去睡|早点睡|休息吧|明天见|(?:先)?(?:别|不)(?:吵|打扰|烦))", unit):
                closing_index = index
                break
        if closing_index < 0 or closing_index >= len(units) - 1:
            return cleaned
        tail = "".join(units[closing_index + 1 :])
        if not tail:
            return cleaned
        tail_continues_closing = bool(re.search(r"(梦|睡|晚安|明天|醒来|休息|被窝|枕头|月亮|星星)", tail))
        if tail_continues_closing and inbound_is_sleep_context:
            return cleaned
        abrupt_markers = (
            "今天", "刚刚", "刚才", "现在", "天气", "云", "太阳", "雨", "风", "作业", "阅读",
            "视频", "新闻", "群里", "书柜", "日程", "吃", "喝", "路上", "窗外", "看到", "觉得",
        )
        looks_abrupt = any(marker in tail for marker in abrupt_markers) or len(tail) >= 6
        if not looks_abrupt:
            return cleaned
        kept = units[: closing_index + 1]
        result = "\n".join(self._ensure_chat_sentence_punctuation(unit) for unit in kept if unit)
        return result.strip() or cleaned

    def _ensure_chat_sentence_punctuation(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if re.search(r"[。！？!?…~～]$", cleaned):
            return cleaned
        question_tokens = (
            "吗", "嘛", "么", "什么", "怎么", "咋", "有没有", "是不是", "要不要",
            "忙什么", "吃东西了吗", "睡了吗", "醒了吗", "你呢", "你那边呢", "你那里呢", "你那儿呢",
        )
        if any(token in cleaned for token in question_tokens):
            return cleaned + "？"
        soft_endings = ("呀", "啦", "嘛", "呢", "吧", "哦", "喔", "诶", "啊")
        if cleaned.endswith(soft_endings):
            return cleaned + "。"
        return cleaned + "。"

    def _split_proactive_sentence_units(self, text: str) -> list[str]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return []
        units: list[str] = []
        for part in [item.strip() for item in re.split(r"\s+", cleaned) if item.strip()]:
            if re.search(r"[。！？!?；;…~～]", part):
                matches = re.findall(r"[^。！？!?；;…~～]+[。！？!?；;…~～]+|[^。！？!?；;…~～]+$", part)
                units.extend(match.strip() for match in matches if match.strip())
            else:
                units.append(part)
        return units

    def _soften_social_proactive_text(self, text: str, *, action: str = "message") -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        cleaned = self._strip_parenthetical_stage_directions(cleaned)
        if not cleaned:
            return ""
        cleaned = self._trim_proactive_status_inventory(cleaned)
        cleaned = self._trim_performative_self_state_tail(cleaned)
        cleaned = re.sub(r"^(?:早上好|早安|上午好|中午好|午安|下午好|晚上好)[,,\s]*", "", cleaned)

        _SOCIAL_REPLACEMENTS = [
            ("刷一下存在感", ""),
            ("冒个泡", ""),
            ("冒个头", ""),
            ("顺手冒了个头", ""),
            ("没什么大不了的,就是", ""),
            ("没什么大道理,就是", ""),
            ("免得你又忘了我", ""),
            ("最近忙不忙？", ""),
            ("最近忙不忙", ""),
            ("数据有意思吗？", ""),
            ("数据有意思吗", ""),
            ("发现你好像在忙。", ""),
            ("发现你好像在忙", ""),
            ("请注意休息", "记得歇会儿"),
        ]
        for old, new in _SOCIAL_REPLACEMENTS:
            cleaned = cleaned.replace(old, new)

        cleaned = re.sub(r"你在忙(.{0,24})吗？感觉你[^。！？\n]*专注[^。！？\n]*[。！？]?", r"还在忙\1啊。", cleaned)
        cleaned = re.sub(r"你在忙(.{0,24})吗？", r"还在忙\1啊。", cleaned)
        cleaned = re.sub(r"感觉你[^。！？\n]*专注[^。！？\n]*[。！？]?", "", cleaned)
        cleaned = re.sub(r"感觉你[^。！？\n]{0,28}呢[。！？]?", "", cleaned)
        cleaned = re.sub(r"(?:我看你|看你)又?在忙", "还在忙", cleaned)

        _ACTION_SPECIFIC_REPLACEMENTS = {
            "screen_peek": [
                ("逻辑分支的工作", "那个逻辑分支"),
                ("工作吗？", "啊。"),
                ("工作啊。", "啊。"),
                ("感觉你投入的样子很专注呢。", ""),
                ("感觉你很投入呢。", ""),
                ("还在忙啊。", "还没从那边抬头啊。"),
            ],
            "poke": [
                ("我就戳一下", "就戳你一下"),
                ("所以来戳你一下", "所以来碰你一下"),
            ],
            "voice": [
                ("给你留了句语音。", "给你留了句语音。"),
                ("刚给你留了句语音,", "刚给你留了句语音,"),
            ],
            "photo_text": [
                ("路边的植物看着很有生机,给你拍了张照片。", "路边那点绿刚好有点顺眼。"),
                ("给你拍了张照片。", ""),
                ("给你拍了张照片", ""),
                ("给你拍了照片", ""),
                ("发给你啦。", ""),
            ],
        }
        if action in _ACTION_SPECIFIC_REPLACEMENTS:
            for old, new in _ACTION_SPECIFIC_REPLACEMENTS[action]:
                cleaned = cleaned.replace(old, new)
        if "photo_text" in action:
            cleaned = re.sub(r"^(?:今天天气[^。！？\n]{0,30}[,,])", "", cleaned)
            cleaned = cleaned.replace("（图片已送达）", "").replace("(图片已送达)", "")

        cleaned = re.sub(r"(?:来找你一下[,,、\s]*){2,}", "来找你一下,", cleaned)
        cleaned = re.sub(r"^[嗨哈喂欸诶]{1,2}[,,\s]+", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"([。！？])\1+", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[,。！？、\s]+", "", cleaned)
        cleaned = self._strip_parenthetical_stage_directions(cleaned)
        return cleaned

    def _deemphasize_state_report_preamble(self, text: str, *, reason: str = "") -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if reason == "important_date_share":
            return cleaned

        date_report_patterns = (
            r"^(?:今天|现在)(?:是)?[^。！？\n]{0,18}(?:五一|劳动节|周末|休息日|假期|放假)[^。！？\n]{0,24}[。！？,\s]*",
            r"^(?:今天|现在)[^。！？\n]{0,16}(?:不用|不用去|不需要)(?:上学|上班|工作|补课)[^。！？\n]{0,18}[。！？,\s]*",
        )
        for pattern in date_report_patterns:
            cleaned = re.sub(pattern, "", cleaned)

        cleaned = re.sub(r"(?:所以|因此)[,，、\s]*(?=我|先|就|你)", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[,，。！？、\s]+", "", cleaned)
        return cleaned

    def _choose_proactive_message(
        self,
        user: dict[str, Any],
        name: str,
        planned_reason: str = "",
    ) -> tuple[str, str]:
        """Pick the proactive reason and return an internal intent note.

        The second value is deliberately not outbound copy. The actual message
        must still be generated by the framework chain and pass send review.
        """
        state = self.data.get("daily_state", {})
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        can_do = self.data.get("can_do", [])
        energy = _safe_int(state.get("energy") if isinstance(state, dict) else 70, 70, 0, 100)
        mood = _single_line(state.get("mood_bias") if isinstance(state, dict) else "平稳", 20)
        active_conditions = state.get("conditions", []) if isinstance(state, dict) else []

        reasons = [planned_reason] if planned_reason else []
        if self._is_quiet_time() and self._has_active_insomnia_state():
            reasons.append("insomnia_night")
        if active_conditions and random.random() < 0.45:
            reasons.append("quiet_care")
        if energy < 45 and random.random() < 0.55:
            reasons.append("quiet_care")
        share_probability = self.proactive_share_probability
        activity_share_blocked = False
        block_checker = getattr(self, "_activity_share_duplicate_block_remaining", None)
        if callable(block_checker):
            try:
                activity_share_blocked = block_checker(user) > 0
            except Exception:
                activity_share_blocked = False
        if can_do and not activity_share_blocked and random.random() < max(0.05, min(0.85, share_probability)):
            reasons.append("activity_share")
        if self.data.get("bot_diaries") and random.random() < max(0.08, share_probability * 0.55):
            reasons.append("diary_share")
        upcoming_dates = self._get_relevant_important_dates()
        if upcoming_dates and random.random() < 0.35:
            reasons.append("important_date_share")
        if current_item and self.include_schedule_in_messages and random.random() < 0.22:
            reasons.append("background_schedule")
        if not reasons:
            reasons.append("check_in")
        elif _safe_int(user.get("ignored_streak"), 0, 0) <= 0 and random.random() < 0.12:
            reasons.append("check_in")
        reason = planned_reason if planned_reason and self._is_reason_allowed_now(planned_reason) else random.choice(reasons)

        if reason == "insomnia_night":
            return reason, "夜间清醒时的一句短开场；不报时、不追问、不拉长。"

        if reason == "quiet_care":
            return reason, "低能量或状态余波下的轻量问候；只给一个具体切口，不写成关心清单。"

        if reason == "morning_greeting":
            return reason, "当前时段的首次早间开口；贴近早晨片段，只做普通问候，不问早餐、吃了吗或吃什么，等用户回应后再关心。"

        if reason == "noon_greeting":
            return reason, "午间短开口；可以围绕吃饭、午休或短暂放松，不催促。"

        if reason == "evening_greeting":
            return reason, "傍晚或夜间收尾时的一句轻开口；不汇报日程，不追问。"


        if reason == "activity_share":
            activity = _single_line(random.choice(can_do), 40) if isinstance(can_do, list) and can_do else "刚才那点小事"
            return reason, f"围绕可做事项“{activity}”分享一个很小的进展或片段；不要写成自证或汇报。"

        if reason == "diary_share":
            fragment = self._pick_diary_fragment()
            if fragment:
                return reason, f"可引用日记碎片“{_single_line(fragment, 80)}”；只取一句自然分享，不写成报告。"

        if reason == "important_date_share" and upcoming_dates:
            entry = upcoming_dates[0]
            days = _safe_int(entry.get("_days_until"), 0)
            title = _single_line(entry.get("title"), 40)
            note = _single_line(entry.get("note"), 80)
            if days == 0:
                detail = f"今天是「{title}」"
            else:
                detail = f"「{title}」还有 {days} 天"
            if note:
                detail = f"{detail}；备注：{note}"
            return reason, f"重要日期提醒：{detail}；一句说清，不责备用户。"

        if reason == "background_schedule" and current_item:
            activity = _single_line(current_item.get("activity"), 40)
            seed = self._deemphasize_state_report_preamble(
                _single_line(current_item.get("message_seed"), 60),
                reason=reason,
            )
            detail = "；".join(part for part in (activity, seed) if part)
            return reason, f"当前日程片段：{detail or '没有明确片段'}；只取一个生活切口，不逐项汇报。"

        style = _single_line(user.get("style") or self.default_style, 24)
        style_hint = f"；参考语气偏好：{style}" if style else ""
        return "check_in", f"无明确来源时的轻量开场{style_hint}；优先贴近关系事实、当前状态或当前日程，不使用固定模板。"
