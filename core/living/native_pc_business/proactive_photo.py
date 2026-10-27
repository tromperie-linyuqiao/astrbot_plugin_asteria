# -*- coding: utf-8 -*-
"""
ProactivePhotoMixin — 主动照片子域（每日穿搭 / ComfyUI / SDGen / 外部图像 API）

由 proactive_message.py 的照片区块（原 6677-10933）拆出；方法名与方法体逐字保持不变。
SyntheticPrivateWakeEvent 等模块级辅助类与统一常量位于 .proactive。
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
from .photo_clothing import merge_photo_prompt, ensure_character_clothing
from .photo_request_policy import build_openai_image_payload
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


from .proactive import SyntheticPrivateWakeEvent


class ProactivePhotoMixin:
    """主动照片子域：每日穿搭、ComfyUI、SDGen 与外部图像 API 生成链路（原 proactive_message.py 照片区块）。"""

    # ===== 照片子域（原 proactive_message.py 6677-10933，方法名不变）=====
    async def _run_photo_text_action(self, user: dict[str, Any], name: str, reason: str) -> str:
        if not self.enable_photo_text_action:
            return "photo_text：未启用"
        if self._private_user_role(user) == "friend":
            return "photo_text：次要用户关系不使用主动生图或复用主要用户图片,不能假装已经拍照"
        load_defer_note = self._photo_text_load_defer_note("photo_text", force_refresh=True)
        if load_defer_note:
            return f"photo_text：{load_defer_note},不能假装已经拍照"
        if not self._photo_text_available(user):
            return "photo_text：今日发图额度已用完或生图后端不可用,不能假装已经拍照"
        if not self._photo_text_available():
            return "photo_text：当前没有可用的生图后端,不能假装已经拍照"

        scene = await self._build_photo_scene_prompt(user, name, reason)
        workflow_kind = scene.get("kind", "text2img")
        subject_owner = _normalize_photo_subject_owner(scene.get("subject_owner"))
        if not subject_owner:
            subject_owner = "bot" if bool(scene.get("use_persona_reference")) or workflow_kind == "selfie" else "scene"
        session_key = str(user.get("umo") or user.get("user_id") or name)
        reference_image_path = ""
        if bool(scene.get("use_persona_reference")):
            # Character-bearing photo_text scenes need identity continuity even when
            # their rendering workflow is text2img rather than selfie.
            reference_image_path = await self._photo_persona_reference_image_for_kind_async(
                "selfie",
                allow_daily_outfit=True,
            )
        backend_name, image_path, workflow_note = await self._generate_photo_image(
            workflow_kind=workflow_kind,
            prompt_text=scene["prompt"],
            session_key=session_key,
            reference_image_path=reference_image_path,
        )
        if not image_path:
            counted_attempt = self._photo_generation_failure_counts_as_attempt(workflow_note)
            if counted_attempt:
                async with self._data_lock:
                    self._note_photo_generation_attempt(str(user.get("user_id") or ""), image_path="")
                    self._save_data_sync()
            return (
                "photo_text：生图失败,不能假装已经拍照\n"
                f"画面草稿：{scene['caption']}\n"
                f"失败原因：{_single_line(workflow_note, 160)}"
                + ("\n本次已计入今日生图尝试额度,避免接口失败时反复请求。" if counted_attempt else "")
            )
        async with self._data_lock:
            self._note_photo_generation_attempt(str(user.get("user_id") or ""), image_path=image_path)
            self._save_data_sync()
        return (
            f"photo_text：已通过 {backend_name} 生成真实图片\n"
            f"图片类型：{workflow_kind}\n"
            f"后端：{backend_name}\n"
            f"图片路径：{image_path}\n"
            f"画面：{scene['caption']}\n"
            f"图片主体归属：{subject_owner}\n"
            f"人物参考图：{'已使用' if reference_image_path else '未使用'}\n"
            f"生图提示：{_single_line(scene['prompt'], 240)}"
        )

    def _photo_generation_failure_counts_as_attempt(self, note: str) -> bool:
        text = _single_line(note, 500)
        if not text:
            return False
        count_tokens = (
            "HTTP",
            "超时",
            "请求",
            "接口",
            "上游",
            "upstream",
            "返回格式",
            "未返回",
            "返回空",
            "下载",
            "保存",
            "响应不是图片",
            "输出不是图片",
            "工作流完成但图片",
            "Error code",
            "Exception",
        )
        if any(token in text for token in count_tokens):
            return True
        skip_tokens = (
            "未启用",
            "未配置",
            "不可用或未配置",
            "后端不可用",
            "插件不可用",
            "工作流名",
            "未找到匹配工作流",
            "电脑高负荷",
            "负载偏高",
            "今日发图额度",
            "文本/聊天模型",
            "请改成图片模型",
        )
        return not any(token in text for token in skip_tokens)

    async def _ensure_daily_outfit_photo(
        self,
        diary: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> dict[str, Any] | None:
        if not force and not getattr(self, "enable_daily_outfit_photo", False):
            return None
        today = _today_key()
        async with self._data_lock:
            existing = self.data.get("daily_outfit_photo") if isinstance(self.data.get("daily_outfit_photo"), dict) else {}
            if not force and existing.get("date") == today:
                return dict(existing)
        lock = getattr(self, "_daily_outfit_photo_generation_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._daily_outfit_photo_generation_lock = lock
        async with lock:
            async with self._data_lock:
                existing = self.data.get("daily_outfit_photo") if isinstance(self.data.get("daily_outfit_photo"), dict) else {}
                if not force and existing.get("date") == today:
                    return dict(existing)
            return await self._ensure_daily_outfit_photo_unlocked(diary, force=force, today=today)

    async def _ensure_daily_outfit_photo_unlocked(
        self,
        diary: dict[str, Any] | None = None,
        *,
        force: bool = False,
        today: str = "",
    ) -> dict[str, Any] | None:
        today = today or _today_key()
        if not self.enable_photo_text_action:
            return await self._record_daily_outfit_photo_result(today, "", "主动拍照/生图未开启")
        if not self._photo_text_available():
            return await self._record_daily_outfit_photo_result(today, "", "当前没有可用的生图后端")
        memory_context = ""
        composer = getattr(self, "_memory_companion_compose_feature_context", None)
        if callable(composer):
            try:
                memory_context = await composer(
                    kind="daily_outfit_photo",
                    query=(
                        "今日穿搭生成：历史穿搭、今天日程、天气、地点、用户常问衣服颜色、"
                        "最近自拍、服装连续性、需要避免的造型重复"
                    ),
                    top_k=5,
                    max_chars=900,
                )
            except Exception as exc:
                logger.debug("[PrivateCompanion] 每日穿搭 我会牢牢记住你 上下文读取失败: %s", _single_line(exc, 120))
        schedule_hint = self._daily_outfit_schedule_text()
        weather = self._format_weather_for_prompt() if callable(getattr(self, "_format_weather_for_prompt", None)) else ""
        outfit_profile = self._select_daily_outfit_profile(
            schedule_hint=schedule_hint,
            weather=weather,
            date_key=today,
        )
        prompt_text = self._build_daily_outfit_photo_prompt(
            diary if isinstance(diary, dict) else {},
            memory_context=memory_context,
            outfit_profile=outfit_profile,
        )
        backend_name, image_path, note = await self._generate_photo_image(
            workflow_kind="selfie",
            prompt_text=prompt_text,
            session_key="daily_outfit",
            image_size="1024x1024",
            allow_daily_outfit_reference=False,
        )
        if image_path:
            return await self._record_daily_outfit_photo_result(
                today,
                image_path,
                "",
                backend=backend_name,
                prompt=prompt_text,
                note=note,
                outfit_profile=outfit_profile,
            )
        return await self._record_daily_outfit_photo_result(
            today,
            "",
            _single_line(note, 220) or "生图失败",
            backend=backend_name,
            prompt=prompt_text,
            note=note,
            outfit_profile=outfit_profile,
        )

    async def _record_daily_outfit_photo_result(
        self,
        date_key: str,
        image_path: str,
        error: str = "",
        *,
        backend: str = "",
        prompt: str = "",
        note: str = "",
        outfit_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = {
            "date": _single_line(date_key, 20),
            "path": _single_line(image_path, 300),
            "error": _single_line(error, 240),
            "backend": _single_line(backend, 80),
            "prompt": _single_line(prompt, 500),
            "note": _single_line(note, 220),
            "generated_at": _now_ts(),
            "outfit_profile": self._normalize_daily_outfit_profile(outfit_profile),
        }
        async with self._data_lock:
            history = self._daily_outfit_history_items(include_current=True)
            if image_path:
                history.insert(0, dict(item))
            self.data["daily_outfit_history"] = history[:30]
            self.data["daily_outfit_photo"] = item
            self._save_data_sync()
        if image_path:
            await self._memory_companion_record_daily_outfit(item)
            logger.info(
                "[PrivateCompanion] 每日穿搭照片已生成: backend=%s path=%s",
                _single_line(backend, 80) or "-",
                _single_line(image_path, 160),
            )
        else:
            logger.info("[PrivateCompanion] 每日穿搭照片未生成: %s", _single_line(error or note, 180))
        return item

    def _daily_outfit_schedule_text(self) -> str:
        plan = self._native_daily_plan_view({}) if isinstance(getattr(self, "data", {}), dict) else {}
        if not isinstance(plan, dict):
            return ""
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            return ""
        lines: list[str] = []
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            time_text = _single_line(item.get("time"), 12)
            activity = _single_line(item.get("activity"), 120)
            mood = _single_line(item.get("mood"), 24)
            if not activity:
                continue
            line = f"{time_text} {activity}".strip()
            if mood:
                line = f"{line}（{mood}）"
            lines.append(line)
        return _single_line("；".join(lines), 620)

    @staticmethod
    def _normalize_daily_outfit_profile(profile: Any) -> dict[str, str]:
        if not isinstance(profile, dict):
            return {}
        limits = {
            "look_id": 80,
            "scene": 32,
            "weather": 32,
            "palette": 120,
            "silhouette": 120,
            "top": 160,
            "outer": 160,
            "bottom": 140,
            "accessory": 140,
        }
        return {
            key: value
            for key, maximum in limits.items()
            if (value := _single_line(profile.get(key), maximum))
        }

    def _daily_outfit_history_items(self, *, include_current: bool = True) -> list[dict[str, Any]]:
        data = self.data if isinstance(getattr(self, "data", {}), dict) else {}
        candidates: list[Any] = []
        if include_current:
            candidates.append(data.get("daily_outfit_photo"))
        raw_history = data.get("daily_outfit_history")
        if isinstance(raw_history, list):
            candidates.extend(raw_history)

        history: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_item in candidates:
            if not isinstance(raw_item, dict):
                continue
            path = _single_line(raw_item.get("path"), 300)
            if not path:
                continue
            profile = self._normalize_daily_outfit_profile(raw_item.get("outfit_profile"))
            item = {
                "date": _single_line(raw_item.get("date"), 20),
                "path": path,
                "generated_at": _single_line(raw_item.get("generated_at"), 40),
                "outfit_profile": profile,
            }
            identity = "|".join(
                (
                    item["path"],
                    item["generated_at"],
                    item["date"],
                    profile.get("look_id", ""),
                )
            )
            if identity in seen:
                continue
            seen.add(identity)
            history.append(item)
        return history[:30]

    def _daily_outfit_rotation_history(self) -> list[dict[str, Any]]:
        rotation_days = _safe_int(getattr(self, "daily_outfit_rotation_days", 10), 10, 1, 30)
        cutoff = date.today() - timedelta(days=rotation_days - 1)
        history: list[dict[str, Any]] = []
        for item in self._daily_outfit_history_items():
            profile = self._normalize_daily_outfit_profile(item.get("outfit_profile"))
            if not profile:
                continue
            date_key = _single_line(item.get("date"), 20)
            try:
                item_date = datetime.strptime(date_key, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                item_date = None
            if item_date and item_date < cutoff:
                continue
            history.append({**item, "outfit_profile": profile})
        return history[:30]

    @staticmethod
    def _daily_outfit_scene_kind(schedule_hint: str, weather: str) -> str:
        text = f"{schedule_hint} {weather}".lower()
        if any(token in text for token in ("运动", "跑步", "健身", "体育", "workout", "gym", "running")):
            return "sport"
        if any(token in text for token in ("校服", "上课", "教室", "学校", "自习", "放学", "school", "class")):
            return "school"
        if any(token in text for token in ("上班", "工作", "会议", "通勤", "办公室", "office", "commute", "meeting")):
            return "commute"
        if any(token in text for token in ("家", "房间", "卧室", "午休", "起床", "睡前", "入睡", "home", "bedroom")):
            return "home"
        return "daily"

    @staticmethod
    def _daily_outfit_weather_kind(weather: str) -> str:
        text = _single_line(weather, 240).lower()
        if any(token in text for token in ("冷", "降温", "低温", "寒", "雪", "snow", "cold")):
            return "cold"
        if any(token in text for token in ("热", "高温", "闷", "暑", "hot", "heat")):
            return "hot"
        if any(token in text for token in ("雨", "阵雨", "雷", "storm", "rain", "wet")):
            return "rainy"
        return "mild"

    @staticmethod
    def _daily_outfit_outer_options(scene: str, weather_kind: str) -> list[str]:
        if scene == "sport":
            options = {
                "cold": [
                    "lightweight insulated track jacket",
                    "technical hooded running jacket",
                    "short quilted sports jacket",
                    "fleece zip-up athletic layer",
                ],
                "hot": [
                    "no heavy outer layer, breathable short-sleeve overshirt",
                    "no outer layer, airy sun-protection layer tied at the waist",
                    "no outer layer, light mesh sports layer",
                    "no outer layer, sleeveless technical vest",
                ],
                "rainy": [
                    "water-resistant hooded running jacket",
                    "compact rain shell with reflective trim",
                    "light technical windbreaker",
                    "hooded quick-dry sports jacket",
                ],
                "mild": [
                    "clean zip-up track jacket",
                    "lightweight athletic windbreaker",
                    "soft cropped sports jacket",
                    "open technical overshirt",
                ],
            }
            return options[weather_kind]
        if scene == "home":
            options = {
                "cold": [
                    "soft oversized knit cardigan",
                    "warm zip-up hoodie",
                    "light quilted home jacket",
                    "plush lounge cardigan",
                ],
                "hot": [
                    "no outer layer, loose breathable overshirt",
                    "no outer layer, thin open cotton shirt",
                    "no outer layer, airy short-sleeve layer",
                    "no outer layer, light linen cardigan",
                ],
                "rainy": [
                    "soft hooded cardigan for a rainy day indoors",
                    "light zip-up hoodie",
                    "cozy knit cardigan",
                    "thin water-resistant overshirt near the doorway",
                ],
                "mild": [
                    "soft open cardigan",
                    "light zip-up hoodie",
                    "relaxed cotton overshirt",
                    "thin knit vest",
                ],
            }
            return options[weather_kind]
        options = {
            "cold": [
                "camel wool coat with a soft scarf",
                "short dark quilted jacket",
                "navy duffle coat",
                "light gray padded jacket",
            ],
            "hot": [
                "no heavy outer layer, breathable overshirt left open",
                "no outer layer, thin sun-protection cardigan",
                "no outer layer, rolled-sleeve linen overshirt",
                "no outer layer, light short-sleeve shirt layer",
            ],
            "rainy": [
                "water-resistant hooded jacket",
                "light trench coat suitable for rain",
                "compact windbreaker with a hood",
                "short rain shell with clean lines",
            ],
            "mild": [
                "soft knit cardigan",
                "light denim jacket",
                "short bomber jacket",
                "unstructured lightweight blazer",
            ],
        }
        return options[weather_kind]

    def _daily_outfit_candidate_profiles(self, scene: str, weather_kind: str) -> list[dict[str, str]]:
        base_options: dict[str, list[dict[str, str]]] = {
            "school": [
                {"palette": "navy, ivory, and muted burgundy", "silhouette": "neat layered campus silhouette", "top": "crisp white shirt with a navy knit vest", "bottom": "straight-cut charcoal trousers", "accessory": "small burgundy ribbon and a simple watch"},
                {"palette": "pale blue, gray, and silver", "silhouette": "clean relaxed academic silhouette", "top": "pale blue oxford shirt under a fine gray cardigan", "bottom": "neat navy trousers", "accessory": "slim silver hair clip or lapel pin"},
                {"palette": "cream, forest green, and warm brown", "silhouette": "soft collegiate silhouette", "top": "cream sweatshirt with a collared shirt edge showing", "bottom": "tailored brown trousers", "accessory": "small canvas shoulder bag"},
                {"palette": "black, white, and dusty rose", "silhouette": "compact modern campus silhouette", "top": "fine striped tee beneath a clean black overshirt", "bottom": "straight dark jeans", "accessory": "subtle rose-toned hair tie or keychain"},
                {"palette": "sage green, ivory, and charcoal", "silhouette": "quiet knitwear silhouette", "top": "sage knit polo layered over a light tee", "bottom": "relaxed charcoal slacks", "accessory": "small geometric earrings or a simple ring"},
                {"palette": "lavender, cream, and deep gray", "silhouette": "light preppy silhouette", "top": "lavender crewneck knit over a white collar", "bottom": "clean deep-gray trousers", "accessory": "thin patterned scarf or a neat ribbon"},
            ],
            "commute": [
                {"palette": "charcoal, ivory, and cobalt blue", "silhouette": "clean tailored commute silhouette", "top": "ivory ribbed knit top with a cobalt accent", "bottom": "straight charcoal trousers", "accessory": "minimal metal watch and structured tote"},
                {"palette": "sand, white, and muted olive", "silhouette": "relaxed smart-casual silhouette", "top": "white shirt under a muted olive knit vest", "bottom": "sand-colored tapered trousers", "accessory": "small leather crossbody bag"},
                {"palette": "black, soft gray, and wine red", "silhouette": "sleek layered city silhouette", "top": "soft gray mock-neck top with a wine-red scarf accent", "bottom": "black straight-leg pants", "accessory": "simple silver earrings or cufflinks"},
                {"palette": "dusty blue, cream, and camel", "silhouette": "light professional silhouette", "top": "dusty-blue blouse or shirt with a cream knit layer", "bottom": "camel tailored trousers", "accessory": "thin belt and understated wristwatch"},
                {"palette": "deep green, black, and ivory", "silhouette": "structured modern silhouette", "top": "deep-green fine knit with a crisp ivory collar", "bottom": "black pleated trousers", "accessory": "small enamel pin and clean shoulder bag"},
                {"palette": "warm taupe, navy, and white", "silhouette": "comfortable polished silhouette", "top": "warm taupe long-sleeve tee beneath a navy overshirt", "bottom": "white or light-stone straight trousers", "accessory": "subtle patterned scarf"},
            ],
            "sport": [
                {"palette": "cobalt blue, white, and graphite", "silhouette": "clean athletic silhouette", "top": "cobalt quick-dry training tee", "bottom": "graphite track pants", "accessory": "simple sports watch and compact water bottle"},
                {"palette": "black, lime green, and gray", "silhouette": "light running silhouette", "top": "black technical long-sleeve top with lime trim", "bottom": "gray joggers", "accessory": "small sweatband and running watch"},
                {"palette": "coral, navy, and white", "silhouette": "bright casual sports silhouette", "top": "coral breathable tee under a navy sleeveless layer", "bottom": "navy athletic pants", "accessory": "minimal cap or hair band"},
                {"palette": "sage green, cream, and black", "silhouette": "relaxed outdoor exercise silhouette", "top": "sage performance polo with a cream inner layer", "bottom": "black tapered joggers", "accessory": "small crossbody sports pouch"},
                {"palette": "lavender, charcoal, and silver", "silhouette": "soft technical silhouette", "top": "lavender moisture-wicking zip collar top", "bottom": "charcoal training pants", "accessory": "reflective wrist band"},
                {"palette": "rust orange, white, and deep blue", "silhouette": "energetic training silhouette", "top": "rust-orange athletic tee with a white panel", "bottom": "deep-blue track pants", "accessory": "compact earbud case or sports watch"},
            ],
            "home": [
                {"palette": "cream, pale blue, and soft gray", "silhouette": "soft relaxed home silhouette", "top": "cream cotton lounge top", "bottom": "pale-blue relaxed pants", "accessory": "simple fabric hair band or soft slippers"},
                {"palette": "sage green, ivory, and warm brown", "silhouette": "cozy knitwear silhouette", "top": "sage knit tee over an ivory inner layer", "bottom": "warm-brown lounge trousers", "accessory": "small mug held naturally"},
                {"palette": "lavender, charcoal, and white", "silhouette": "quiet oversized silhouette", "top": "lavender oversized sweatshirt", "bottom": "charcoal soft joggers", "accessory": "thin reading glasses or a simple hair clip"},
                {"palette": "dusty rose, cream, and gray", "silhouette": "light comfortable silhouette", "top": "dusty-rose long-sleeve tee", "bottom": "cream cotton pants", "accessory": "small pendant necklace"},
                {"palette": "navy, light gray, and muted yellow", "silhouette": "casual layered home silhouette", "top": "navy striped lounge shirt", "bottom": "light-gray relaxed pants", "accessory": "muted-yellow blanket edge or soft socks"},
                {"palette": "white, olive, and soft black", "silhouette": "minimal restful silhouette", "top": "white breathable henley shirt", "bottom": "olive lounge pants", "accessory": "small wireless earbud case"},
            ],
            "daily": [
                {"palette": "denim blue, white, and red", "silhouette": "casual layered street silhouette", "top": "white tee under a denim-blue overshirt", "bottom": "dark straight-leg jeans", "accessory": "small red hair tie or keychain"},
                {"palette": "cream, black, and forest green", "silhouette": "clean relaxed silhouette", "top": "cream ribbed knit top with a forest-green collar layer", "bottom": "black tapered trousers", "accessory": "minimal canvas crossbody bag"},
                {"palette": "dusty rose, charcoal, and ivory", "silhouette": "soft modern silhouette", "top": "dusty-rose sweatshirt over an ivory tee", "bottom": "charcoal straight trousers", "accessory": "small silver pendant"},
                {"palette": "sage green, navy, and light gray", "silhouette": "easy outdoor silhouette", "top": "sage polo layered with a light-gray tee", "bottom": "navy relaxed trousers", "accessory": "simple cap or structured backpack"},
                {"palette": "lavender, white, and deep blue", "silhouette": "light casual silhouette", "top": "lavender knit tee with a white collar detail", "bottom": "deep-blue jeans", "accessory": "thin patterned scarf"},
                {"palette": "warm brown, ivory, and muted orange", "silhouette": "textured everyday silhouette", "top": "ivory henley shirt beneath a warm-brown knit vest", "bottom": "muted-orange straight trousers", "accessory": "small leather bracelet or watch"},
            ],
        }
        outer_options = self._daily_outfit_outer_options(scene, weather_kind)
        candidates: list[dict[str, str]] = []
        for base_index, base in enumerate(base_options.get(scene, base_options["daily"])):
            for outer_index, outer in enumerate(outer_options):
                candidates.append(
                    {
                        **base,
                        "scene": scene,
                        "weather": weather_kind,
                        "outer": outer,
                        "look_id": f"{scene}-{base_index + 1}-{outer_index + 1}",
                    }
                )
        return candidates

    def _select_daily_outfit_profile(
        self,
        *,
        schedule_hint: str,
        weather: str,
        date_key: str = "",
    ) -> dict[str, str]:
        scene = self._daily_outfit_scene_kind(schedule_hint, weather)
        weather_kind = self._daily_outfit_weather_kind(weather)
        candidates = self._daily_outfit_candidate_profiles(scene, weather_kind)
        if not candidates:
            return {}
        history = self._daily_outfit_rotation_history()
        fields = ("palette", "silhouette", "top", "outer", "bottom", "accessory")
        weights = {
            "palette": 16,
            "silhouette": 12,
            "top": 20,
            "outer": 18,
            "bottom": 10,
            "accessory": 8,
        }

        def cooldown_score(candidate: dict[str, str]) -> int:
            score = 0
            for index, item in enumerate(history):
                previous = self._normalize_daily_outfit_profile(item.get("outfit_profile"))
                if not previous:
                    continue
                recency_weight = max(1, 8 - index)
                matching_fields = sum(
                    1
                    for field in fields
                    if candidate.get(field) and candidate.get(field) == previous.get(field)
                )
                score += sum(
                    weights[field] * recency_weight
                    for field in fields
                    if candidate.get(field) and candidate.get(field) == previous.get(field)
                )
                if candidate.get("look_id") == previous.get("look_id"):
                    score += 600 * recency_weight
                if index == 0:
                    changed_fields = len(fields) - matching_fields
                    if changed_fields < 2:
                        score += 10000
                    elif changed_fields < 3:
                        score += 800
            return score

        rotation_seed = f"{date_key or _today_key()}|{len(history)}"

        def tie_breaker(candidate: dict[str, str]) -> int:
            digest = hashlib.sha1(
                f"{rotation_seed}|{candidate.get('look_id', '')}".encode("utf-8")
            ).hexdigest()
            return int(digest[:12], 16)

        return min(candidates, key=lambda candidate: (cooldown_score(candidate), tie_breaker(candidate)))

    def _daily_outfit_rotation_reference(self) -> str:
        history = self._daily_outfit_rotation_history()
        if not history:
            return ""
        labels = {
            "palette": "color palettes",
            "outer": "outer layers",
            "silhouette": "silhouettes",
        }
        fragments: list[str] = []
        for field, label in labels.items():
            values: list[str] = []
            for item in history:
                profile = self._normalize_daily_outfit_profile(item.get("outfit_profile"))
                value = _single_line(profile.get(field), 56)
                if value and value not in values:
                    values.append(value)
                if len(values) >= 2:
                    break
            if values:
                fragments.append(f"{label}: {' / '.join(values)}")
        return _single_line("; ".join(fragments), 280)

    def _format_weather_for_prompt(self) -> str:
        data = getattr(self, "data", None)
        weather = data.get("daily_weather") if isinstance(data, dict) else None
        if not isinstance(weather, dict):
            return ""
        formatter = getattr(self, "_weather_summary_text", None)
        if callable(formatter):
            try:
                text = _single_line(formatter(weather), 120)
                if text and text != "暂无天气信息":
                    return text
            except Exception:
                pass
        text = _single_line(weather.get("prompt"), 120)
        return "" if text == "暂无天气信息" else text

    def _build_daily_outfit_photo_prompt(
        self,
        diary: dict[str, Any],
        *,
        memory_context: str = "",
        outfit_profile: dict[str, Any] | None = None,
    ) -> str:
        persona = self._daily_outfit_role_appearance_text()
        style_name, style_instruction = self._get_photo_style_instruction()
        style_prompt = self._photo_style_prompt_en(style_name, style_instruction)
        state = self.data.get("daily_state", {}) if isinstance(getattr(self, "data", {}), dict) else {}
        weather = self._format_weather_for_prompt() if callable(getattr(self, "_format_weather_for_prompt", None)) else ""
        schedule_hint = self._daily_outfit_schedule_text()
        state_visual = self._daily_outfit_visual_state_text(state if isinstance(state, dict) else {})
        outfit_profile = self._normalize_daily_outfit_profile(outfit_profile)
        if not outfit_profile:
            outfit_profile = self._select_daily_outfit_profile(schedule_hint=schedule_hint, weather=weather)
        outfit_hint = self._daily_outfit_outfit_hint(
            schedule_hint=schedule_hint,
            weather=weather,
            outfit_profile=outfit_profile,
        )
        rotation_reference = self._daily_outfit_rotation_reference()
        scene_hint = self._daily_outfit_scene_hint(state if isinstance(state, dict) else {}, schedule_hint=schedule_hint, weather=weather)
        visual_memory = ""
        visual_memory_getter = getattr(self, "_visual_photo_memory_context", None)
        if callable(visual_memory_getter):
            try:
                visual_memory = visual_memory_getter(memory_context, limit=260)
            except Exception:
                visual_memory = ""
        diary_hint = _single_line(
            (diary or {}).get("summary")
            or (diary or {}).get("share_seed")
            or (diary or {}).get("body"),
            80,
        )
        custom = _single_line(getattr(self, "daily_outfit_photo_prompt", ""), 220)
        positive = [
            "single character",
            "daily outfit selfie",
            "selfie outfit photo",
            "non-mirror handheld selfie or natural environmental outfit portrait",
            "solo",
            "visible face",
            "complete head and hair",
            "clear eyes",
            "natural expression",
            "upper body to three-quarter body portrait, not a full-length mirror shot",
            "centered composition",
            "1:1 square cover composition",
            "safe margins around head and body",
            "natural phone snapshot",
            "soft natural light",
            "clean background",
            "lifelike daily atmosphere",
            persona or "keep the face, hairstyle, hair color, eye color, and key traits consistent with the reference image",
            outfit_hint,
            scene_hint,
            state_visual or "relaxed natural mood",
            style_prompt,
        ]
        if rotation_reference:
            positive.append(
                "wardrobe rotation: show exactly one character wearing one coherent new outfit in this single image; "
                "make that one outfit differ from recent daily outfit photos in at least two design dimensions, "
                f"but never display the old outfit or multiple alternatives; avoid repeating {rotation_reference}"
            )
        if diary_hint:
            positive.append(f"daily mood cue: {diary_hint}")
        if visual_memory:
            positive.append(f"visual continuity reference: {visual_memory}")
        if custom:
            positive.append(f"additional outfit preference: {custom}")
        negative = [
            "cropped head",
            "headless",
            "faceless",
            "face hidden",
            "extreme close-up",
            "arm in foreground",
            "body only",
            "outfit only",
            "back view",
            "mirror selfie",
            "full-length mirror selfie",
            "full body mirror shot",
            "standing in front of a mirror",
            "dressing room mirror",
            "phone covering face",
            "cut off face",
            "bad hands",
            "extra fingers",
            "text",
            "caption",
            "label",
            "watermark",
            "logo",
            "other people",
            "duplicate character",
            "twins",
            "multiple people",
            "multiple outfits",
            "outfit comparison",
            "before and after",
            "split screen",
            "side-by-side panels",
            "diptych",
            "collage",
            "character sheet",
            "user in frame",
            "private screen",
            "nsfw",
            "revealing outfit",
        ]
        if rotation_reference:
            negative.extend(
                [
                    "same outfit as a recent daily outfit photo",
                    f"repeat any recently used outfit element: {rotation_reference}",
                ]
            )
        prompt = (
            "Positive prompt: "
            + ", ".join(_single_line(part, 220) for part in positive if _single_line(part, 220))
            + ". Negative prompt: "
            + ", ".join(negative)
            + "."
        )
        return _single_line(prompt, 1400)

    def _photo_style_prompt_en(self, style_name: str, style_instruction: str = "") -> str:
        name = _single_line(style_name, 40)
        instruction = _single_line(style_instruction, 220)
        if name == "二次元":
            return "anime illustration style, clean detailed character art, soft colors, slice-of-life feeling"
        if name == "真实":
            return "realistic photography style, believable phone photo, natural lighting, realistic fabric details"
        if instruction:
            return instruction
        return "consistent visual style, natural daily-life feeling"

    def _daily_outfit_visual_state_text(self, state: dict[str, Any]) -> str:
        fragments: list[str] = []
        energy = _safe_int((state or {}).get("energy"), 70, 0, 100)
        if energy < 40:
            fragments.append("slightly sleepy, soft expression")
        elif energy > 82:
            fragments.append("fresh and energetic, bright eyes")
        mood = _single_line((state or {}).get("mood_bias"), 20).replace("黏人", "粘人")
        mood_map = {
            "开心": "gentle happy mood",
            "轻快": "light cheerful mood",
            "柔和": "soft gentle mood",
            "安静": "quiet calm mood",
            "疲惫": "tired but gentle mood",
            "困": "sleepy mood",
            "困倦": "sleepy mood",
            "低落": "subdued mood",
            "敏感": "delicate sensitive mood",
            "粘人": "soft attached mood",
        }
        if mood and mood not in {"平稳", "中性"}:
            fragments.append(mood_map.get(mood, f"{mood} mood"))
        conditions = (state or {}).get("conditions")
        visual_tokens = ("雨", "风", "冷", "热", "困", "疲", "生理期", "感冒", "发烧", "头痛", "胃", "睡", "醒")
        if isinstance(conditions, list):
            for cond in conditions[:6]:
                if not isinstance(cond, dict):
                    continue
                label = _single_line(cond.get("label") or cond.get("title") or cond.get("kind"), 30)
                if label and any(token in label for token in visual_tokens):
                    fragments.append(self._daily_outfit_condition_hint_en(label))
                if len(fragments) >= 3:
                    break
        return _single_line(", ".join(dict.fromkeys(item for item in fragments if item)), 140)

    def _daily_outfit_condition_hint_en(self, text: str) -> str:
        value = _single_line(text, 60).lower()
        if any(token in value for token in ("雨", "rain", "淋")):
            return "rainy-day softness"
        if any(token in value for token in ("风", "wind")):
            return "slight wind-blown hair"
        if any(token in value for token in ("冷", "寒", "snow")):
            return "cold-weather outfit"
        if any(token in value for token in ("热", "暑", "hot")):
            return "light breathable outfit"
        if any(token in value for token in ("困", "疲", "睡", "醒")):
            return "sleepy gentle expression"
        if any(token in value for token in ("生理期", "胃", "感冒", "发烧", "头痛")):
            return "soft low-energy expression"
        return _single_line(text, 60)

    def _daily_outfit_scene_hint(self, state: dict[str, Any], *, schedule_hint: str = "", weather: str = "") -> str:
        location = ""
        try:
            location = _single_line(self._current_location_state_text(state), 60)
            coarse = _single_line(self._coarse_roleplay_location_text(location), 40)
            location = coarse or location
        except Exception:
            location = ""
        text = f"{schedule_hint} {weather}".lower()
        if not location:
            if any(token in text for token in ("上课", "教室", "学校", "校门", "放学", "自习")):
                location = "school or commute-to-school setting"
            elif any(token in text for token in ("出门", "路上", "街", "公交", "地铁", "下班", "回家")):
                location = "outdoor street or commute setting"
            elif any(token in text for token in ("家", "房间", "卧室", "起床", "午休", "睡")):
                location = "home or bedroom setting"
            else:
                location = "daily-life setting"
        else:
            location = self._daily_outfit_location_hint_en(location)
        weather_hint = self._daily_outfit_weather_visual_hint(weather)
        return _single_line(", ".join(part for part in [location, weather_hint, "simple background, lived-in daily atmosphere"] if part), 180)

    def _daily_outfit_location_hint_en(self, location: str) -> str:
        text = _single_line(location, 80).lower()
        if any(token in text for token in ("学校", "教室", "上课", "school", "classroom")):
            return "school or classroom setting"
        if any(token in text for token in ("家", "房间", "卧室", "home", "room", "bedroom")):
            return "home or bedroom setting"
        if any(token in text for token in ("工作", "office", "公司")):
            return "workplace or office setting"
        if any(token in text for token in ("外面", "路", "街", "通勤", "outside", "street")):
            return "outdoor street or commute setting"
        return _single_line(location, 80)

    def _daily_outfit_weather_visual_hint(self, weather: str) -> str:
        text = _single_line(weather, 200).lower()
        if not text:
            return ""
        hints: list[str] = []
        if any(token in text for token in ("雨", "阵雨", "雷", "storm", "rain")):
            hints.append("rainy-day atmosphere, umbrella or damp ground, light jacket")
        if any(token in text for token in ("风", "大风", "强对流", "wind")):
            hints.append("windy feeling, slightly wind-blown hair and hem")
        if any(token in text for token in ("冷", "降温", "低温", "寒", "snow")):
            hints.append("cold weather, warm outerwear")
        if any(token in text for token in ("热", "高温", "闷", "暑", "hot")):
            hints.append("hot weather, light breathable clothes")
        return _single_line(", ".join(dict.fromkeys(hints)), 140)

    def _daily_outfit_outfit_hint(
        self,
        *,
        schedule_hint: str = "",
        weather: str = "",
        outfit_profile: dict[str, Any] | None = None,
    ) -> str:
        profile = self._normalize_daily_outfit_profile(outfit_profile)
        if profile:
            fields = (
                ("palette", "color palette"),
                ("silhouette", "silhouette"),
                ("top", "top"),
                ("outer", "outer layer"),
                ("bottom", "bottoms"),
                ("accessory", "accessories"),
            )
            hints = ["intentionally distinct coordinated daily outfit"]
            hints.extend(
                f"{label}: {profile[key]}"
                for key, label in fields
                if profile.get(key)
            )
            return _single_line(", ".join(hints), 620)
        text = f"{schedule_hint} {weather}".lower()
        hints: list[str] = []
        if any(token in text for token in ("校服", "上课", "教室", "学校", "高一", "自习", "放学")):
            hints.append("neat school outfit or school-uniform inspired outfit")
        if any(token in text for token in ("上班", "工作", "会议", "通勤")):
            hints.append("clean daily commute outfit")
        if any(token in text for token in ("运动", "跑步", "健身", "体育")):
            hints.append("light sporty outfit")
        if any(token in text for token in ("家", "房间", "午休", "整理", "起床")) and not hints:
            hints.append("soft casual home outfit")
        if any(token in text for token in ("睡衣", "睡前", "入睡", "刚醒")) and not any(token in text for token in ("上课", "上班", "出门", "通勤")):
            hints.append("comfortable pajamas or loungewear")
        weather_hint = self._daily_outfit_weather_visual_hint(weather)
        if weather_hint:
            hints.append(weather_hint)
        if not hints:
            hints.append("natural daily outfit, coordinated colors, clear clothing layers")
        return _single_line(", ".join(dict.fromkeys(hints)), 180)

    def _daily_outfit_role_appearance_text(self) -> str:
        persona = str(getattr(self, "schedule_persona_prompt", "") or "")
        recognition = str(getattr(self, "private_image_self_recognition_hint", "") or "")
        labels = {
            "性别": "gender",
            "识别点": "key visual traits",
            "外貌": "appearance",
            "主要识别点": "key visual traits",
            "发型发色": "hairstyle and hair color",
            "发色": "hair color",
            "发型": "hairstyle",
            "瞳色": "eye color",
            "眼睛": "eyes",
            "服饰风格": "clothing style",
            "服装": "clothing",
            "衣着": "outfit",
        }
        parts: list[str] = []
        for line in persona.replace("\r", "\n").split("\n"):
            text = line.strip()
            if not text or ("：" not in text and ":" not in text):
                continue
            label, value = text.split("：", 1) if "：" in text else text.split(":", 1)
            label = label.strip()
            value = _single_line(value, 160)
            english_label = labels.get(label)
            if english_label and value:
                parts.append(f"{english_label}: {value}")
        if recognition:
            parts.append(f"additional visual recognition notes: {_single_line(recognition, 180)}")
        seen: set[str] = set()
        unique = []
        for item in parts:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return _single_line(", ".join(unique), 620)

    def _choose_photo_workflow_name(self, kind: str) -> str:
        normalized = str(kind or "").strip().lower()
        if normalized in {"selfie", "portrait", "自拍", "人像"}:
            return self.comfyui_selfie_workflow_name or self.comfyui_text2img_workflow_name
        return self.comfyui_text2img_workflow_name or self.comfyui_selfie_workflow_name

    def _photo_generation_trace_id(self, session_key: str, workflow_kind: str) -> str:
        seed = f"{session_key}|{workflow_kind}|{_now_ts()}|{uuid.uuid4().hex[:8]}"
        return hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:10]

    def _photo_generation_file_detail(self, image_path: str) -> str:
        path_text = _single_line(image_path, 260)
        if not path_text:
            return "path=- exists=false size=0"
        if re.match(r"^(?:https?://|data:|base64://)", path_text, flags=re.I):
            return f"path={_single_line(path_text, 120)} exists=remote size=-"
        local_text = path_text[len("file://"):] if path_text.startswith("file://") else path_text
        try:
            path = Path(local_text)
            exists = path.exists() and path.is_file()
            size = path.stat().st_size if exists else 0
            return f"path={_single_line(str(path), 160)} exists={str(exists).lower()} size={size}"
        except Exception:
            return f"path={_single_line(path_text, 120)} exists=unknown size=-"

    def _photo_generation_backend_config_summary(self) -> str:
        configured_endpoints = getattr(self, "external_image_api_endpoints", [])
        if isinstance(configured_endpoints, list) and configured_endpoints:
            queue_getter = getattr(self, "_external_image_api_endpoint_queue", None)
            endpoints: list[dict[str, Any]] = []
            if callable(queue_getter):
                try:
                    endpoints = [
                        endpoint
                        for endpoint in queue_getter(include_incomplete=True, include_disabled=True)
                        if isinstance(endpoint, dict)
                    ]
                except Exception:
                    endpoints = []
            endpoint_bits = []
            for index, endpoint in enumerate(endpoints[:6]):
                ready = not bool(self._external_image_api_endpoint_unavailable_note(endpoint))
                endpoint_bits.append(
                    f"{index + 1}:{_single_line(endpoint.get('name') or endpoint.get('model'), 40) or '-'}"
                    f"/{_single_line(endpoint.get('platform'), 20) or 'auto'}"
                    f"/{'ready' if ready else 'unready'}"
                )
            return (
                f"preferred={_single_line(getattr(self, 'photo_generation_backend', ''), 30) or 'auto'} "
                f"comfyui={self._comfyui_photo_available()} "
                f"sdgen={self._sdgen_photo_available()} "
                f"external={self._external_photo_available()} "
                f"external_queue={len(endpoints)} "
                f"external_queue_items={';'.join(endpoint_bits) or '-'} "
                f"backup_note={_single_line(self._backup_external_photo_unavailable_note(), 80) or '-'} "
                f"tool_call={self._custom_tool_photo_available()} "
                f"tool_name={_single_line(getattr(self, 'custom_photo_tool_name', ''), 80) or '-'}"
            )
        external_base = _single_line(self._normalized_external_image_api_base_url(), 120)
        if external_base:
            external_base = re.sub(r"([?&](?:key|token|access_token|api_key)=)[^&]+", r"\1***", external_base, flags=re.I)
        backup_base = _single_line(getattr(self, "backup_external_image_api_base_url", ""), 120)
        if backup_base:
            backup_base = re.sub(r"([?&](?:key|token|access_token|api_key)=)[^&]+", r"\1***", backup_base, flags=re.I)
        return (
            f"preferred={_single_line(getattr(self, 'photo_generation_backend', ''), 30) or 'auto'} "
            f"comfyui={self._comfyui_photo_available()} "
            f"sdgen={self._sdgen_photo_available()} "
            f"external={self._external_photo_available()} "
            f"external_platform={self._resolved_external_image_api_platform()} "
            f"external_model={_single_line(getattr(self, 'external_image_api_model', ''), 80) or '-'} "
            f"external_size={_single_line(getattr(self, 'external_image_api_size', ''), 40) or '-'} "
            f"external_base={external_base or '-'} "
            f"backup_external={self._backup_external_photo_available()} "
            f"backup_platform={_single_line(getattr(self, 'backup_external_image_api_platform', ''), 30) or '-'} "
            f"backup_model={_single_line(getattr(self, 'backup_external_image_api_model', ''), 80) or '-'} "
            f"backup_base={backup_base or '-'} "
            f"backup_note={_single_line(self._backup_external_photo_unavailable_note(), 80) or '-'} "
            f"tool_call={self._custom_tool_photo_available()} "
            f"tool_name={_single_line(getattr(self, 'custom_photo_tool_name', ''), 80) or '-'}"
        )

    def _record_recent_photo_generation(
        self,
        *,
        trace_id: str,
        session_key: str,
        workflow_kind: str,
        backend: str,
        ok: bool,
        prompt_text: str,
        image_path: str = "",
        note: str = "",
        reference_image_path: str = "",
        image_size: str = "",
        elapsed_ms: int = 0,
        presets: list[str] | None = None,
    ) -> None:
        try:
            item = {
                "ts": _now_ts(),
                "trace": _single_line(trace_id, 40),
                "session": _single_line(session_key, 100),
                "kind": _single_line(workflow_kind, 30),
                "backend": _single_line(backend, 80),
                "ok": bool(ok),
                "prompt": _single_line(prompt_text, 900),
                "path": _single_line(image_path, 260),
                "note": _single_line(note, 240),
                "reference": bool(reference_image_path),
                "reference_path": _single_line(reference_image_path, 260),
                "image_size": _single_line(image_size, 40),
                "elapsed_ms": int(max(0, elapsed_ms or 0)),
                "presets": [_single_line(name, 40) for name in (presets or []) if _single_line(name, 40)][:6],
            }
            raw = self.data.setdefault("recent_photo_generations", [])
            if not isinstance(raw, list):
                raw = []
                self.data["recent_photo_generations"] = raw
            raw.insert(0, item)
            del raw[12:]
            self._save_data_sync()
        except Exception as exc:
            logger.debug("[PrivateCompanion] 记录最近生图提示词失败: %s", _single_line(exc, 120))

    def _annotate_recent_photo_generation(
        self,
        *,
        image_path: str = "",
        session_key: str = "",
        trigger: str = "",
        intent_kind: str = "",
        sent: bool | None = None,
        caption: str = "",
        scene_preset: str = "",
        tool_name: str = "",
    ) -> None:
        try:
            raw = self.data.get("recent_photo_generations")
            if not isinstance(raw, list):
                return
            target_path = _single_line(image_path, 260)
            target_session = _single_line(session_key, 100)
            for item in raw:
                if not isinstance(item, dict):
                    continue
                same_path = bool(target_path and _single_line(item.get("path"), 260) == target_path)
                same_session = bool(target_session and _single_line(item.get("session"), 100) == target_session)
                if not same_path and not same_session:
                    continue
                if trigger:
                    item["trigger"] = _single_line(trigger, 40)
                if intent_kind:
                    item["intent_kind"] = _single_line(intent_kind, 30)
                if sent is not None:
                    item["sent"] = bool(sent)
                if caption:
                    item["caption"] = _single_line(caption, 120)
                if scene_preset:
                    item["scene_preset"] = _single_line(scene_preset, 80)
                if tool_name:
                    item["tool_name"] = _single_line(tool_name, 60)
                item["annotated_at"] = _now_ts()
                self._save_data_sync()
                return
        except Exception as exc:
            logger.debug("[PrivateCompanion] 标注最近生图记录失败: %s", _single_line(exc, 120))

    def _apply_photo_generation_fixed_prompt(self, prompt_text: str) -> str:
        prompt = str(prompt_text or "").strip()
        fixed = _single_line(getattr(self, "photo_generation_fixed_prompt", ""), 500)
        if not fixed:
            return merge_photo_prompt(prompt)
        if fixed in prompt:
            return merge_photo_prompt(prompt)
        return merge_photo_prompt(prompt, positive_extra=f"Additional fixed prompt: {fixed}")

    def _photo_generation_selfie_schedule_scene_hint(self) -> str:
        plan = self._native_daily_plan_view({}) if isinstance(getattr(self, "data", {}), dict) else {}
        plan = plan if isinstance(plan, dict) else {}
        state = self.data.get("daily_state", {}) if isinstance(getattr(self, "data", {}), dict) else {}
        state = state if isinstance(state, dict) else {}

        current_schedule = ""
        try:
            current_item = self._get_current_plan_item(plan)
            if isinstance(current_item, dict):
                current_schedule = _single_line(self._format_plan_item_for_prompt(current_item), 260)
        except Exception:
            current_schedule = ""
        if not current_schedule and callable(getattr(self, "_format_schedule_context_for_prompt", None)):
            try:
                current_schedule = _single_line(self._format_schedule_context_for_prompt(plan), 260)
            except Exception:
                current_schedule = ""

        location = ""
        if callable(getattr(self, "_current_location_state_text", None)):
            try:
                location = _single_line(self._current_location_state_text(state), 60)
            except Exception:
                location = ""
        coarse_location = ""
        if location and callable(getattr(self, "_coarse_roleplay_location_text", None)):
            try:
                coarse_location = _single_line(self._coarse_roleplay_location_text(location), 40)
            except Exception:
                coarse_location = ""
        location_text = coarse_location or location
        if location and coarse_location and location != coarse_location:
            location_text = f"{coarse_location}（{location}）"

        parts: list[str] = []
        if current_schedule:
            parts.append(f"当前日程：{current_schedule}")
        if location_text:
            parts.append(f"当前位置：{location_text}")
        return _single_line("；".join(parts), 460)

    def _apply_photo_generation_selfie_schedule_scene_prompt(
        self,
        prompt_text: str,
        workflow_kind: str,
        *,
        allow_daily_outfit_reference: bool = True,
    ) -> tuple[str, str]:
        prompt = str(prompt_text or "").strip()
        normalized = str(workflow_kind or "").strip().lower()
        if normalized not in {"selfie", "portrait", "自拍", "人像"}:
            return merge_photo_prompt(prompt), ""
        if not allow_daily_outfit_reference:
            return merge_photo_prompt(prompt), ""
        if "【自拍当前场景约束】" in prompt:
            return merge_photo_prompt(prompt), ""
        if any(token in prompt for token in ("基于用户提供或引用的参考图进行改图", "保留用户未要求修改的主体", "只改变明确要求的部分")):
            return merge_photo_prompt(prompt), ""

        scene_hint = self._photo_generation_selfie_schedule_scene_hint()
        if not scene_hint:
            return merge_photo_prompt(prompt), ""
        outfit_reference = self._daily_outfit_reference_image_path()
        outfit_hint = (
            "use today's outfit reference image; keep the clothes, accessories, and overall outfit consistent"
            if outfit_reference
            else "keep the character face, hairstyle, outfit, and accessories consistent with the available reference image"
        )
        extra = (
            "Current selfie scene constraint: "
            f"{outfit_hint}; "
            f"place the selfie in the current schedule/location context: {scene_hint}; "
            "a handheld selfie or natural environmental portrait with a visible face and upper-body to three-quarter framing."
        )
        return merge_photo_prompt(
            prompt, positive_extra=extra,
            negative_terms=("studio backdrop", "unrelated bedroom", "default empty room", "unrelated location"),
        ), scene_hint

    @staticmethod
    def _photo_generation_explicit_mirror_request(text: str) -> bool:
        raw = _single_line(text, 1200)
        if not raw:
            return False
        lowered = raw.lower()
        detection_text = re.split(r"negative prompt\s*:", lowered, maxsplit=1, flags=re.I)[0]
        positive_scan = re.sub(
            r"(?:不要|避免|别|不许|禁止).{0,18}(?:镜前|对镜|镜中|镜子|全身镜|穿衣镜|试衣镜)",
            " ",
            detection_text,
            flags=re.I,
        )
        positive_scan = re.sub(
            r"(?:no|not|avoid|without)\s+(?:a\s+)?(?:mirror|mirror\s+selfie|full[-\s]?length\s+mirror|"
            r"full[-\s]?body\s+mirror|mirror\s+shot|mirror\s+photo|mirror\s+portrait)[^,.;；。]*",
            " ",
            positive_scan,
            flags=re.I,
        )
        positive_scan = re.sub(r"unless[^,.;；。]*mirror[^,.;；。]*", " ", positive_scan, flags=re.I)
        if re.search(
            r"镜前|对镜|镜中|镜子|全身镜|穿衣镜|试衣镜|\bmirror\b|looking\s+in\s+the\s+mirror|in\s+front\s+of\s+(?:a\s+)?mirror",
            positive_scan,
            flags=re.I,
        ):
            return True
        return False

    @staticmethod
    def _append_photo_negative_terms(prompt_text: str, terms: list[str], *, limit: int = 1800) -> str:
        if not str(prompt_text or "").strip():
            return ""
        return merge_photo_prompt(prompt_text, negative_terms=terms, limit=limit)

    def _sanitize_unrequested_mirror_selfie_prompt(
        self,
        prompt_text: str,
        *,
        context_text: str = "",
        limit: int = 1800,
    ) -> str:
        prompt = str(prompt_text or "").strip()
        if not prompt:
            return ""
        if self._photo_generation_explicit_mirror_request(context_text):
            return _single_line(prompt, limit)
        replacements = (
            (r"\bfull[-\s]?length\s+mirror\s+(?:selfie|shot|photo|portrait)\b", "natural upper-body to three-quarter portrait"),
            (r"\bfull[-\s]?body\s+mirror\s+(?:selfie|shot|photo|portrait)\b", "natural upper-body to three-quarter portrait"),
            (r"\bmirror\s+(?:selfie|shot|photo|portrait)\b", "handheld selfie or natural environmental portrait"),
            (r"\bstanding\s+in\s+front\s+of\s+(?:a\s+)?mirror\b", "standing naturally in the current location"),
            (r"\bdressing[-\s]?room\s+mirror\b", "current-location background"),
            (r"\bphone\s+covering\s+(?:the\s+)?face\b", "visible face"),
            (r"全身镜自拍|全身对镜|对镜自拍|镜前自拍|镜中自拍|穿衣镜|试衣镜", "自然半身或四分之三身随手拍"),
        )
        cleaned = prompt
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;；")
        negative_terms = [
            "mirror selfie",
            "full-length mirror selfie",
            "full body mirror shot",
            "dressing room mirror",
            "phone covering face",
        ]
        return self._append_photo_negative_terms(cleaned or prompt, negative_terms, limit=limit)

    def _apply_photo_generation_selfie_composition_guard(self, prompt_text: str, workflow_kind: str) -> str:
        prompt = str(prompt_text or "").strip()
        normalized = str(workflow_kind or "").strip().lower()
        if normalized not in {"selfie", "portrait", "自拍", "人像"}:
            return merge_photo_prompt(prompt)
        explicit_mirror = self._photo_generation_explicit_mirror_request(prompt)
        if explicit_mirror:
            guard = (
                "Selfie composition guard: exactly one real character wearing exactly one coherent outfit in one continuous scene; "
                "a single mirror reflection of that same outfit, one image, visible face, natural upper-body to three-quarter framing."
            )
        else:
            guard = (
                "Default selfie composition guard: exactly one character wearing exactly one coherent outfit in one continuous scene; "
                "one image, visible face, upper-body to three-quarter framing, character naturally placed in the current scene."
            )
        merged = merge_photo_prompt(prompt, positive_extra=guard)
        negative_terms = [
            "duplicate character",
            "twins",
            "multiple people",
            "multiple outfits",
            "outfit comparison",
            "before and after",
            "split screen",
            "side-by-side panels",
            "diptych",
            "collage",
            "character sheet",
        ]
        if not explicit_mirror:
            negative_terms.extend(
                ["mirror selfie", "full-length mirror selfie", "full body mirror shot", "dressing room mirror"]
            )
        negative_terms.append("phone covering face")
        return self._append_photo_negative_terms(
            merged,
            negative_terms,
            limit=1800,
        )

    def _builtin_photo_generation_scene_presets(self) -> dict[str, str]:
        return {
            "角色自拍": (
                "natural casual selfie, single character, face visible, clear face, hair, expression, neck and shoulders, "
                "phone snapshot feeling, lifelike composition, no cropped head, no hidden face, no back view, no body-only framing"
            ),
            "COS自拍": (
                "cosplay themed selfie, keep the character's own face, hair color, eye color, and key visual traits, "
                "clear costume theme, tasteful outfit, convention snapshot or room fitting photo feeling"
            ),
            "日常穿搭": (
                "daily outfit portrait without mirror, exactly one character wearing one coherent outfit in one continuous frame, "
                "no outfit comparison, no split screen, no side-by-side panels, handheld selfie or natural environmental portrait, "
                "upper-body to three-quarter framing, visible face, clear clothing layers and color palette, "
                "location-appropriate background, no phone covering face, not body-only"
            ),
            "镜前穿搭": (
                "explicitly requested mirror outfit photo, half-body to three-quarter mirror composition, "
                "clear clothes, jacket, accessories and color palette, complete visible face, no phone covering face, "
                "subject inside square safe area, not full-length body-only, not outfit-only, not clothing close-up"
            ),
            "头像特写": (
                "avatar-ready face close-up, clear hair, eyes and expression, clean background, centered face, enough margin, "
                "no text, no watermark, no cluttered props"
            ),
            "房间日常": (
                "indoor slice-of-life photo, natural desk objects, books, cup, window side or bedside details, "
                "one clear subject, calm lived-in atmosphere, avoid overcrowded composition"
            ),
            "可拍画面": (
                "casual photo shared with a close friend, concrete visual subject, natural lighting, not a vague landscape, "
                "not a weather report, no private screen, no real personal information, no unrelated text, no watermark"
            ),
            "表情包场景": (
                "single sticker-like image for chat, clear emotion, simple composition, cute exaggerated expression, "
                "character remains recognizable, only include short text if the user explicitly requested it"
            ),
        }

    def _parse_photo_generation_scene_presets(self, raw: Any) -> dict[str, str]:
        presets: dict[str, str] = {}
        if isinstance(raw, dict):
            iterable = raw.items()
            for key, value in iterable:
                name = _single_line(key, 40)
                prompt = _single_line(value, 900)
                if name and prompt:
                    presets[name] = prompt
            return presets
        items: list[Any] = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, str):
            text = raw.replace("\r\n", "\n").replace("\r", "\n")
            items = [line for line in text.split("\n") if str(line or "").strip()]
        for item in items:
            if isinstance(item, dict):
                name = _single_line(item.get("name") or item.get("key") or item.get("title"), 40)
                prompt = _single_line(item.get("prompt") or item.get("value") or item.get("content"), 900)
            else:
                text = str(item or "").strip()
                if ":" in text:
                    name, prompt = text.split(":", 1)
                elif "：" in text:
                    name, prompt = text.split("：", 1)
                else:
                    continue
                name = _single_line(name, 40)
                prompt = _single_line(prompt, 900)
            if name and prompt:
                presets[name] = prompt
        return presets

    def _photo_generation_scene_presets(self) -> dict[str, str]:
        presets = self._builtin_photo_generation_scene_presets()
        presets.update(self._parse_photo_generation_scene_presets(getattr(self, "photo_generation_scene_presets", "")))
        return presets

    def _photo_generation_preset_names_for_prompt(self, workflow_kind: str, prompt_text: str) -> list[str]:
        kind = str(workflow_kind or "").strip().lower()
        text = _single_line(prompt_text, 1200).lower()
        names: list[str] = []
        if kind in {"selfie", "portrait", "自拍", "人像"}:
            if any(token in text for token in ("表情包", "贴纸", "sticker", "meme")):
                names.append("表情包场景")
            elif re.search(r"\bcos\b|cosplay|角色扮演|扮成|神灯|制服|女仆|巫女|魔法少女", text, flags=re.I):
                names.append("COS自拍")
            elif self._photo_generation_explicit_mirror_request(text):
                names.append("镜前穿搭")
            elif any(token in text for token in ("穿搭", "衣服", "外套", "校服", "裙", "outfit", "clothes", "jacket", "uniform", "skirt")):
                names.append("日常穿搭")
            elif any(token in text for token in ("头像", "特写", "大头", "avatar", "close-up", "closeup", "profile picture")):
                names.append("头像特写")
            else:
                names.append("角色自拍")
        else:
            if any(token in text for token in ("表情包", "贴纸", "sticker", "meme")):
                names.append("表情包场景")
            elif any(token in text for token in ("房间", "桌", "书", "杯", "床", "窗边", "室内", "room", "desk", "book", "cup", "bed", "window", "indoor")):
                names.append("房间日常")
            else:
                names.append("可拍画面")
        return list(dict.fromkeys(names))[:3]

    def _apply_photo_generation_scene_presets(self, prompt_text: str, workflow_kind: str) -> tuple[str, list[str]]:
        prompt = str(prompt_text or "").strip()
        presets = self._photo_generation_scene_presets()
        names = [name for name in self._photo_generation_preset_names_for_prompt(workflow_kind, prompt) if name in presets]
        if not names:
            return merge_photo_prompt(prompt), []
        blocks = []
        for name in names:
            content = _single_line(presets.get(name), 900)
            if content and content not in prompt:
                blocks.append(f"{self._photo_generation_scene_preset_label_en(name)}: {content}")
        if not blocks:
            return merge_photo_prompt(prompt), names
        merged = merge_photo_prompt(prompt, positive_extra="Scene preset: " + "; ".join(blocks))
        return merged, names

    def _photo_generation_scene_preset_label_en(self, name: str) -> str:
        return {
            "角色自拍": "casual character selfie",
            "COS自拍": "cosplay selfie",
            "日常穿搭": "daily outfit portrait",
            "镜前穿搭": "mirror outfit photo",
            "头像特写": "avatar close-up",
            "房间日常": "indoor slice-of-life",
            "可拍画面": "casual shareable photo",
            "表情包场景": "sticker scene",
        }.get(_single_line(name, 40), _single_line(name, 40) or "scene preset")

    def _photo_current_clothing_hint(self) -> str:
        """Use today's actual outfit, then explicit persona clothing; no body inference."""
        data = self.data if isinstance(getattr(self, "data", None), dict) else {}
        outfit = data.get("daily_outfit_photo")
        try:
            today = self._environment_now().strftime("%Y-%m-%d")
        except Exception:
            today = _today_key()
        if isinstance(outfit, dict) and outfit.get("date") == today:
            profile = self._normalize_daily_outfit_profile(outfit.get("outfit_profile"))
            if profile:
                return self._daily_outfit_outfit_hint(outfit_profile=profile)
        persona = str(getattr(self, "schedule_persona_prompt", "") or "")
        values = []
        for line in persona.splitlines():
            match = re.match(r"\s*(?:服装|衣着|服饰风格|clothing|outfit)\s*[:：]\s*(.+)", line, flags=re.I)
            if match:
                values.append(match.group(1).strip())
        return _single_line("; ".join(values), 360)

    async def _generate_photo_image(
        self,
        *,
        workflow_kind: str,
        prompt_text: str,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
        allow_daily_outfit_reference: bool = True,
        clothing_request_text: str = "",
    ) -> tuple[str, str, str]:
        started = time.time()
        trace_id = self._photo_generation_trace_id(session_key, workflow_kind)
        original_scene_prompt = prompt_text
        prompt_text, preset_names = self._apply_photo_generation_scene_presets(prompt_text, workflow_kind)
        prompt_text, selfie_scene_hint = self._apply_photo_generation_selfie_schedule_scene_prompt(
            prompt_text,
            workflow_kind,
            allow_daily_outfit_reference=allow_daily_outfit_reference,
        )
        prompt_text = self._apply_photo_generation_selfie_composition_guard(prompt_text, workflow_kind)
        prompt_text = self._apply_photo_generation_fixed_prompt(prompt_text)
        style_name, style_instruction = self._get_photo_style_instruction()
        style_prompt = self._photo_style_prompt_en(style_name, style_instruction)
        prompt_text = merge_photo_prompt(
            prompt_text, positive_extra="Image style: " + _single_line(style_prompt, 220),
        )
        prompt_text = ensure_character_clothing(
            prompt_text, workflow_kind,
            clothing_hint=self._photo_current_clothing_hint() if allow_daily_outfit_reference else "",
            request_text=clothing_request_text or original_scene_prompt,
        )
        reference_image_path = _single_line(reference_image_path, 260)
        if not reference_image_path:
            reference_image_path = await self._photo_persona_reference_image_for_kind_async(
                workflow_kind,
                allow_daily_outfit=allow_daily_outfit_reference,
            )
        if selfie_scene_hint:
            logger.info(
                "[PrivateCompanion] 自拍生图已加入当前日程地点约束: trace=%s session=%s hint=%s reference=%s",
                trace_id,
                _single_line(session_key, 80),
                _single_line(selfie_scene_hint, 180),
                bool(reference_image_path),
            )
        preferred = self.photo_generation_backend
        try:
            reference_exists = bool(reference_image_path and Path(reference_image_path).exists())
        except (OSError, ValueError):
            reference_exists = False
        logger.info(
            "[PrivateCompanion] 生图开始: trace=%s session=%s kind=%s presets=%s prompt_chars=%s prompt_preview_chars=%s prompt_preview=%s reference=%s reference_exists=%s image_size=%s %s",
            trace_id,
            _single_line(session_key, 80),
            _single_line(workflow_kind, 30),
            ",".join(preset_names) or "-",
            len(str(prompt_text or "")),
            180,
            _single_line(prompt_text, 180),
            bool(reference_image_path),
            reference_exists,
            _single_line(image_size, 40) or "-",
            self._photo_generation_backend_config_summary(),
        )

        def finish(backend: str, image_path: str, note: str) -> tuple[str, str, str]:
            elapsed_ms = int((time.time() - started) * 1000)
            ok = bool(image_path)
            self._record_recent_photo_generation(
                trace_id=trace_id,
                session_key=session_key,
                workflow_kind=workflow_kind,
                backend=backend,
                ok=ok,
                prompt_text=prompt_text,
                image_path=image_path,
                note=note,
                reference_image_path=reference_image_path,
                image_size=image_size,
                elapsed_ms=elapsed_ms,
                presets=preset_names,
            )
            logger.info(
                "[PrivateCompanion] 生图结束: trace=%s ok=%s backend=%s elapsed=%sms note=%s %s",
                trace_id,
                ok,
                _single_line(backend, 60),
                elapsed_ms,
                _single_line(note, 220),
                self._photo_generation_file_detail(image_path),
            )
            return backend, image_path, note

        if reference_image_path and not reference_exists:
            return finish("参考图", "", f"参考图路径不可用或文件不存在：{_single_line(reference_image_path, 160)}")

        if preferred == "comfyui":
            if not self._comfyui_photo_available():
                return finish("ComfyUI", "", "ComfyUI 后端不可用或未配置")
            busy_state = self._local_photo_generation_busy_state(force_refresh=True)
            if busy_state:
                return finish("ComfyUI", "", f"电脑高负荷,已跳过本地生图（{busy_state.get('reason') or '负载偏高'}）")
            workflow_name = self._choose_photo_workflow_name(workflow_kind)
            if not workflow_name:
                return finish("ComfyUI", "", f"未配置 {workflow_kind} 对应的 ComfyUI 工作流")
            image_path, note = await self._run_comfyui_photo_workflow(
                workflow_name,
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
            )
            return finish("ComfyUI", image_path, note)
        if preferred == "sdgen":
            if not self._sdgen_photo_available():
                return finish("SDGen", "", "SDGen 插件不可用或未配置")
            if reference_image_path:
                return finish("SDGen", "", "SDGen 后端不支持参考图输入，请改用在线参考图接口或 ComfyUI images=1 自拍工作流")
            busy_state = self._local_photo_generation_busy_state(force_refresh=True)
            if busy_state:
                return finish("SDGen", "", f"电脑高负荷,已跳过本地生图（{busy_state.get('reason') or '负载偏高'}）")
            image_path, note = await self._run_sdgen_photo_generation(
                prompt_text,
                session_key=session_key,
            )
            return finish("SDGen", image_path, note)
        if preferred == "tool_call":
            if not self._custom_tool_photo_available():
                return finish("函数工具", "", "自定义生图函数工具不可用或未配置")
            image_path, note = await self._run_custom_tool_photo_generation(
                prompt_text,
                session_key=session_key,
                workflow_kind=workflow_kind,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if image_path:
                return finish("函数工具", image_path, note)
            can_fallback = self._external_photo_available() or self._comfyui_photo_available() or (not reference_image_path and self._sdgen_photo_available())
            if not can_fallback:
                return finish("函数工具", "", note)
            logger.info("[PrivateCompanion] 函数工具生图未成功,继续尝试可用后端回退: trace=%s note=%s", trace_id, _single_line(note, 180))
        if preferred == "external":
            if not self._external_photo_available():
                return finish("在线图片 API", "", "在线图片 API 后端不可用或未配置")
            image_path, note = await self._run_external_photo_generation(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if image_path:
                return finish("在线图片 API", image_path, note)
            can_fallback = self._comfyui_photo_available() or (not reference_image_path and self._sdgen_photo_available())
            if not can_fallback:
                return finish("在线图片 API", "", note)
            logger.info("[PrivateCompanion] 固定在线图片 API 未成功,继续尝试可用后端回退: trace=%s note=%s", trace_id, _single_line(note, 180))
        external_note = ""
        if preferred == "external":
            external_note = note
        elif self._external_photo_available():
            image_path, note = await self._run_external_photo_generation(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if image_path:
                return finish("在线图片 API", image_path, note)
            external_note = note
            logger.info("[PrivateCompanion] 生图后端回退: trace=%s backend=external note=%s", trace_id, _single_line(note, 180))
        else:
            external_note = "在线图片 API 后端不可用或未配置"
            logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=external note=%s", trace_id, external_note)
        if self._comfyui_photo_available():
            busy_state = self._local_photo_generation_busy_state(force_refresh=True)
            if busy_state:
                comfyui_note = f"电脑高负荷,已跳过本地生图（{busy_state.get('reason') or '负载偏高'}）"
                logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=comfyui note=%s", trace_id, _single_line(comfyui_note, 180))
            else:
                workflow_name = self._choose_photo_workflow_name(workflow_kind)
                if workflow_name:
                    image_path, note = await self._run_comfyui_photo_workflow(
                        workflow_name,
                        prompt_text,
                        session_key=session_key,
                        reference_image_path=reference_image_path,
                    )
                    if image_path:
                        return finish("ComfyUI", image_path, note)
                    comfyui_note = note
                    logger.info("[PrivateCompanion] 生图后端回退: trace=%s backend=comfyui note=%s", trace_id, _single_line(note, 180))
                else:
                    comfyui_note = f"未配置 {workflow_kind} 对应的 ComfyUI 工作流"
                    logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=comfyui note=%s", trace_id, _single_line(comfyui_note, 180))
        else:
            comfyui_note = "ComfyUI 后端不可用或未配置"
            logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=comfyui note=%s", trace_id, comfyui_note)
        if reference_image_path:
            sdgen_note = "本次需要参考图，已跳过不支持参考图输入的 SDGen 纯文生图"
            logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=sdgen note=%s", trace_id, sdgen_note)
        elif self._sdgen_photo_available():
            busy_state = self._local_photo_generation_busy_state(force_refresh=True)
            if busy_state:
                sdgen_note = f"电脑高负荷,已跳过本地生图（{busy_state.get('reason') or '负载偏高'}）"
                logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=sdgen note=%s", trace_id, _single_line(sdgen_note, 180))
            else:
                image_path, note = await self._run_sdgen_photo_generation(
                    prompt_text,
                    session_key=session_key,
                )
                if image_path:
                    return finish("SDGen", image_path, note)
                sdgen_note = note
                logger.info("[PrivateCompanion] 生图后端回退: trace=%s backend=sdgen note=%s", trace_id, _single_line(note, 180))
        else:
            sdgen_note = "SDGen 插件不可用或未配置"
            logger.info("[PrivateCompanion] 生图后端跳过: trace=%s backend=sdgen note=%s", trace_id, sdgen_note)
        return finish("在线图片 API", "", f"在线图片 API 失败：{external_note}；ComfyUI 失败：{comfyui_note}；SDGen 失败：{sdgen_note}")

    async def _build_photo_scene_prompt(
        self, user: dict[str, Any], name: str, reason: str
    ) -> dict[str, Any]:
        persona = self._get_default_persona_prompt()
        state = self.data.get("daily_state", {})
        current_item = self._get_current_plan_item(self._native_daily_plan_view({}))
        style_name, style_instruction = self._get_photo_style_instruction()
        topic_hint = _single_line(user.get("planned_proactive_topic"), 60)
        motive_hint = _single_line(user.get("planned_proactive_motive"), 120)
        schedule_context = self._format_plan_item_for_prompt(current_item)
        delayed_scene = bool(self._deferred_immediate_share_tense_hint(user, "photo_text"))
        if delayed_scene:
            schedule_context = "本次画面对应较早的生活片段；日程只用于保持人物与场景连续，不可作为发送当下的事实依据。"
        prompt = f"""
请根据 AstrBot 默认人格和主动原因,生成一张要通过生图后端制作的“社交媒体随手拍/自拍/生活碎片图”提示词。

【人格】
{persona}

【收信人】
{name}

【当前拟人状态】
{self._format_state_for_prompt(state if isinstance(state, dict) else {})}

【当前日程背景】
{schedule_context}

【这次想分享的画面钩子】
话题：{topic_hint or '（未指定）'}
那一刻的小动机：{motive_hint or '（未指定）'}

【生日卡特殊规则】
{"如果主动原因是 birthday_celebration：制作一张没有文字、没有姓名、没有日期的温柔生日小卡。只选一个与人格和用户偏好相称的具体意象，不画蛋糕上文字、不出现年龄、不要节庆海报或营销风。" if reason == "birthday_celebration" else "（非生日卡）"}

【内容选择菜单】
{self._format_content_choice_options_for_prompt("photo_text")}

【生图风格】
{style_name}
风格要求：{style_instruction}

主动原因：{reason}

输出 JSON：
{{
  "kind": "selfie 或 text2img；自拍/人像用 selfie,其他随手拍用 text2img",
  "use_persona_reference": true,
  "prompt": "English image-generation prompt in this form: Positive prompt: subject, appearance, outfit, scene, lighting, camera, composition, style. Negative prompt: cropped head, faceless, mirror selfie unless explicitly requested, full-length mirror shot, phone covering face, text, watermark, logo, nsfw. Do not write chat tone or explanations.",
  "caption": "图片完成后可转述给最终私聊模型的一句话画面描述"
}}

要求：
1. 画面必须符合当前时间、日程和人格,不要把身份设定里没有的场景、职业、服装或外观细节写进去。日程是背景参考，不可单独当作动作已经发生的证明。
2. 图片不要总是天气或窗外。先从“内容选择菜单”里单选一个视觉锚点；当前日程、话题和人格只用于筛选主体和调整画面气质,不要把多个主体拼在一张图里。若本次来自延后候选，画面应与原话题连续，不应伪装成发送当下的新现场。
3. 可以是路上风景、桌面小物、随手自拍、偶遇小动物等,但不要每次都是自拍；没有明确自拍动机时优先 text2img。
4. `prompt` 必须使用英文生图提示词形式,优先短语和逗号分隔标签；可以把必要中文专名作为 visual note 保留,但不要写任务说明。
5. `prompt` 里要明确体现上面的风格要求。
6. 不要包含 NSFW、隐私信息、用户真实电脑画面。
7. 如果“话题”已经很具体,就优先把那个具体视觉主体画出来；如果话题很抽象,从菜单里另选一个适合拍照的具体画面。不要退回成泛泛的天气图、手部动作或普通记录照。
8. 不要默认生成全身镜/对镜自拍/手机挡脸自拍；只有话题、动机或当前日程明确出现“镜前/对镜/镜子/全身镜/mirror”时才允许。普通穿搭图用当前地点里的手持自拍、半身或四分之三身环境人像。
9. `use_persona_reference` 仅表示画面中是否出现 Bot 本人：自拍、人物生活照、人物穿搭图填 true；纯风景、食物、桌面物品、动物、手机屏幕或生日卡填 false。
""".strip()
        text = await self._llm_call(
            prompt,
            max_tokens=260,
            provider_id=self._task_provider(self.photo_prompt_provider_id, self.mai_style_provider_id),
            task="photo_prompt",
        )
        payload = self._extract_json_payload(text or "")
        if isinstance(payload, dict):
            kind = _single_line(payload.get("kind"), 20).lower()
            image_prompt = _single_line(payload.get("prompt"), 600)
            caption = _single_line(payload.get("caption"), 180)
            raw_use_reference = payload.get("use_persona_reference")
            if isinstance(raw_use_reference, bool):
                use_persona_reference = raw_use_reference
            elif str(raw_use_reference or "").strip().lower() in {"true", "1", "yes", "是", "使用"}:
                use_persona_reference = True
            elif str(raw_use_reference or "").strip().lower() in {"false", "0", "no", "否", "不使用"}:
                use_persona_reference = False
            else:
                use_persona_reference = False
        else:
            kind = "text2img"
            image_prompt = _single_line(text, 600)
            caption = image_prompt
            # When the scene model is unavailable, prefer a stable character photo
            # for ordinary proactive sharing instead of allowing an arbitrary face.
            use_persona_reference = reason != "birthday_celebration"
        if kind not in {"selfie", "portrait", "自拍", "人像", "text2img", "scene", "photo", "风景"}:
            kind = "text2img"
        if kind in {"portrait", "自拍", "人像"}:
            kind = "selfie"
        if kind in {"scene", "photo", "风景"}:
            kind = "text2img"
        if kind == "selfie":
            use_persona_reference = True
        elif isinstance(payload, dict) and payload.get("use_persona_reference") is None:
            character_text = f"{image_prompt} {caption}"
            use_persona_reference = bool(
                re.search(
                    r"\b(?:girl|woman|female|character|portrait|solo|face|hairstyle|outfit)\b",
                    character_text,
                    flags=re.I,
                )
                or any(token in character_text for token in ("人物", "角色", "女孩", "少女", "自拍", "人像", "穿搭"))
            )
        if not image_prompt:
            current = schedule_context
            image_prompt = (
                f"社交媒体随手拍,当前背景：{current},温柔自然的生活感,"
                f"清晰构图,柔和光线,{style_instruction}"
            )
        if kind == "selfie":
            mirror_context = "；".join(
                part
                for part in (
                    f"reason={reason}",
                    f"topic={topic_hint}",
                    f"motive={motive_hint}",
                    f"schedule={schedule_context}",
                )
                if _single_line(part, 260)
            )
            image_prompt = self._sanitize_unrequested_mirror_selfie_prompt(
                image_prompt,
                context_text=mirror_context,
                limit=900,
            )
        if not caption:
            caption = "今天看到一个很适合拍下来分享的小画面。"
        if use_persona_reference:
            subject_owner = "bot"
        else:
            character_text = f"{image_prompt} {caption}"
            subject_owner = (
                "third_party"
                if re.search(r"\b(?:person|people|man|woman|boy|girl|character|human)\b", character_text, flags=re.I)
                or any(token in character_text for token in ("人物", "男人", "女人", "男生", "女生", "男孩", "女孩", "路人"))
                else "scene"
            )
        return {
            "kind": kind,
            "prompt": image_prompt,
            "caption": caption,
            "use_persona_reference": use_persona_reference,
            "subject_owner": subject_owner,
        }

    def _get_photo_style_instruction(self) -> tuple[str, str]:
        style = str(self.photo_generation_style or "真实").strip()
        if style == "二次元":
            return "二次元", "日系二次元插画风,人物与场景干净细腻,保留生活感,不要写实摄影质感"
        if style == "其他":
            custom = _single_line(self.photo_generation_style_custom_prompt, 200)
            if custom:
                return "其他", custom
            return "其他", "保持统一审美风格,自然生活感,避免默认写实照片风格"
        return "真实", "真实摄影风格,像手机随手拍到的生活照片,光线自然,细节可信"

    def _photo_persona_reference_image_path(self) -> str:
        raw = _single_line(getattr(self, "photo_persona_reference_image_path", ""), 1000)
        if not raw:
            return ""
        raw = raw.strip().strip('"').strip("'")
        if re.match(r"^https?://", raw, flags=re.I):
            return ""
        candidates = [Path(raw).expanduser()]
        if not candidates[0].is_absolute():
            candidates.append(Path(self.data_dir) / raw)
        for candidate in candidates:
            try:
                path = candidate.resolve()
            except Exception:
                path = candidate
            if not path.exists() or not path.is_file():
                continue
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            return str(path)
        return ""

    def _daily_outfit_reference_image_path(self) -> str:
        item = self.data.get("daily_outfit_photo") if isinstance(getattr(self, "data", None), dict) else {}
        if not isinstance(item, dict):
            return ""
        if _single_line(item.get("date"), 20) != _today_key():
            return ""
        raw = _single_line(item.get("path"), 500).strip().strip('"').strip("'")
        if not raw:
            return ""
        try:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path(self.data_dir) / raw
            path = path.resolve()
        except Exception:
            path = Path(raw)
        try:
            if not path.exists() or not path.is_file():
                return ""
        except (OSError, ValueError):
            return ""
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return ""
        return str(path)

    def _photo_persona_reference_image_for_kind(self, workflow_kind: str, *, allow_daily_outfit: bool = True) -> str:
        if not bool(getattr(self, "enable_photo_reference_image", False)):
            return ""
        if str(workflow_kind or "").strip().lower() not in {"selfie", "portrait", "自拍", "人像"}:
            return ""
        if allow_daily_outfit:
            outfit_path = self._daily_outfit_reference_image_path()
            if outfit_path:
                return outfit_path
        return self._photo_persona_reference_image_path()

    async def _photo_persona_reference_image_path_async(self) -> str:
        if not bool(getattr(self, "enable_photo_reference_image", False)):
            return ""
        local_path = self._photo_persona_reference_image_path()
        if local_path:
            return local_path
        raw = _single_line(getattr(self, "photo_persona_reference_image_path", ""), 1000).strip().strip('"').strip("'")
        if not raw or not re.match(r"^https?://", raw, flags=re.I):
            return ""
        resolver = getattr(self, "_photo_reference_source_to_stable_path", None)
        if not callable(resolver):
            return ""
        try:
            stable_path = await resolver(raw, stem="config_url_reference")
        except Exception as exc:
            logger.info("[PrivateCompanion] 配置页人设参考图 URL 下载失败: %s url=%s", _single_line(exc, 120), _single_line(raw, 120))
            return ""
        if not stable_path:
            logger.info("[PrivateCompanion] 配置页人设参考图 URL 未能转为本地参考图: url=%s", _single_line(raw, 120))
            return ""
        setter = getattr(self, "_set_photo_reference_config_path", None)
        if callable(setter):
            try:
                setter(stable_path)
            except Exception as exc:
                logger.info("[PrivateCompanion] 配置页人设参考图 URL 已下载但回写失败: %s path=%s", _single_line(exc, 120), _single_line(stable_path, 160))
        logger.info("[PrivateCompanion] 配置页人设参考图 URL 已缓存为本地文件: path=%s", _single_line(stable_path, 160))
        return stable_path

    async def _photo_persona_reference_image_for_kind_async(
        self,
        workflow_kind: str,
        *,
        allow_daily_outfit: bool = True,
    ) -> str:
        if not bool(getattr(self, "enable_photo_reference_image", False)):
            return ""
        if str(workflow_kind or "").strip().lower() not in {"selfie", "portrait", "自拍", "人像"}:
            return ""
        if allow_daily_outfit:
            outfit_path = self._daily_outfit_reference_image_path()
            if outfit_path:
                logger.info(
                    "[PrivateCompanion] 自拍参考图优先使用今日穿搭图: path=%s",
                    _single_line(outfit_path, 160),
                )
                return outfit_path
        return await self._photo_persona_reference_image_path_async()

    async def _run_comfyui_photo_workflow(
        self,
        workflow_name: str,
        prompt_text: str,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        module = self._get_comfyui_module()
        if module is None:
            return "", "ComfyUI 插件不可用"
        config = getattr(module, "_plugin_config", None)
        if not config:
            return "", "ComfyUI 插件配置不可用"
        try:
            server_ip, client_id = module._get_server_config(config)
            workflow_dir = module._get_workflow_dir()
            reference_image_path = _single_line(reference_image_path, 260)
            use_reference_image = bool(reference_image_path and os.path.exists(reference_image_path))
            workflow_file = ""
            text_count = 1
            image_count = 0
            if use_reference_image:
                workflow_file = module.find_workflow_file(
                    workflow_name,
                    1,
                    1,
                    0,
                    workflow_dir,
                )
                image_count = 1 if workflow_file else 0
                if not workflow_file:
                    workflow_file, text_count, image_count = self._find_photo_workflow_with_text_count(
                        module,
                        workflow_dir,
                        workflow_name,
                        image_count=1,
                    )
                if not workflow_file:
                    return "", (
                        f"已找到参考图，但 ComfyUI 工作流 {workflow_name} 不接收图片输入。"
                        "请配置 images=1 的自拍/改图工作流，避免回退成不使用参考图的纯文生图。"
                    )
            if not workflow_file:
                workflow_file = module.find_workflow_file(
                    workflow_name,
                    1,
                    0,
                    0,
                    workflow_dir,
                )
                image_count = 0
            if not workflow_file:
                workflow_file, text_count, image_count = self._find_photo_workflow_with_text_count(
                    module,
                    workflow_dir,
                    workflow_name,
                    image_count=0,
                )
            if not workflow_file:
                need = "images=1 或 images=0" if use_reference_image else "images=0"
                return "", f"未找到匹配工作流 {workflow_name}（需要 texts>=1、{need}、videos=0）"
            logger.info(
                "[PrivateCompanion] ComfyUI 生图提交准备: workflow=%s file=%s text_count=%s image_count=%s reference=%s wait=%ss prompt_preview=%s",
                _single_line(workflow_name, 80),
                _single_line(workflow_file, 160),
                text_count,
                image_count,
                use_reference_image,
                self.comfyui_photo_wait_seconds,
                _single_line(prompt_text, 180),
            )
            debug = bool(
                getattr(config, "debug_mode", False)
                if not isinstance(config, dict)
                else config.get("debug_mode", False)
            )
            workflow = module.ComfyUIWorkflow(server_ip, client_id)
            workflow.load_workflow_api(workflow_file)
            input_images = [reference_image_path] if image_count > 0 and use_reference_image else []
            reference_note = ""
            if input_images:
                reference_note = "；已使用本地人设参考图"
            elif use_reference_image:
                return "", (
                    f"已找到参考图，但 ComfyUI 工作流 {workflow_name} 实际没有接收图片输入。"
                    "请检查工作流 images 参数数量。"
                )
            prompt_id = await workflow.submit_only(
                input_images,
                [prompt_text] * max(1, text_count),
                [],
                debug=debug,
            )
            logger.info(
                "[PrivateCompanion] ComfyUI 生图已提交: workflow=%s prompt_id=%s input_images=%s text_count=%s",
                _single_line(workflow_name, 80),
                _single_line(prompt_id, 80),
                len(input_images),
                text_count,
            )
            deadline = _now_ts() + self.comfyui_photo_wait_seconds
            while _now_ts() < deadline:
                url, file_type, texts = await module._get_result_for_prompt(server_ip, prompt_id)
                if url and file_type == "image":
                    temp_path = await module._download_image_to_temp(url)
                    if not temp_path:
                        return "", "工作流完成但图片下载失败"
                    persistent_path = await module._save_image_to_persistent_path(
                        temp_path,
                        session_key or "private_companion",
                    )
                    logger.info(
                        "[PrivateCompanion] ComfyUI 生图完成: prompt_id=%s temp=%s persistent=%s note=%s",
                        _single_line(prompt_id, 80),
                        _single_line(temp_path, 160),
                        _single_line(persistent_path, 160),
                        reference_note or "ok",
                    )
                    return persistent_path or temp_path, "ok" + reference_note
                if url and file_type != "image":
                    logger.info(
                        "[PrivateCompanion] ComfyUI 生图输出类型不符: prompt_id=%s file_type=%s url=%s",
                        _single_line(prompt_id, 80),
                        _single_line(file_type, 40),
                        _single_line(url, 160),
                    )
                    return "", f"工作流输出不是图片：{file_type}"
                await asyncio.sleep(2)
            logger.info(
                "[PrivateCompanion] ComfyUI 生图等待超时: workflow=%s prompt_id=%s wait=%ss",
                _single_line(workflow_name, 80),
                _single_line(prompt_id, 80),
                self.comfyui_photo_wait_seconds,
            )
            return "", f"等待 ComfyUI 结果超时（{self.comfyui_photo_wait_seconds}s）"
        except Exception as e:
            logger.warning(f"[PrivateCompanion] photo_text 生图失败: {e}", exc_info=True)
            return "", str(e)

    def _find_sdgen_plugin(self) -> Any | None:
        try:
            getter = getattr(getattr(self, "context", None), "get_registered_star", None)
            if callable(getter):
                for name in ("SDGen", "astrbot_plugin_sdgen"):
                    plugin = getter(name)
                    if plugin is not None and callable(getattr(plugin, "_call_t2i_api", None)):
                        return plugin
        except Exception:
            pass
        for obj in gc.get_objects():
            try:
                cls = obj.__class__
                module = str(getattr(cls, "__module__", ""))
                if "astrbot_plugin_sdgen" not in module:
                    continue
                if callable(getattr(obj, "_call_t2i_api", None)):
                    return obj
            except Exception:
                continue
        return None

    async def _run_sdgen_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
    ) -> tuple[str, str]:
        plugin = self._find_sdgen_plugin()
        if plugin is None:
            return "", "SDGen 插件不可用"
        checker = getattr(plugin, "_check_webui_available", None)
        if callable(checker):
            try:
                available, status = await checker()
                if not available:
                    return "", f"Stable Diffusion WebUI 不可用（status={status}）"
            except Exception as exc:
                return "", f"检查 Stable Diffusion WebUI 失败：{_single_line(exc, 120)}"
        try:
            positive_prompt = prompt_text
            build_prompt = getattr(plugin, "_build_positive_prompt", None)
            if callable(build_prompt):
                positive_prompt = build_prompt(prompt_text, "")
            logger.info(
                "[PrivateCompanion] SDGen 生图提交: session=%s prompt_preview=%s positive_chars=%s",
                _single_line(session_key, 80),
                _single_line(prompt_text, 180),
                len(str(positive_prompt or "")),
            )
            response = await plugin._call_t2i_api(positive_prompt)
            images = response.get("images") if isinstance(response, dict) else None
            if not isinstance(images, list) or not images:
                logger.info("[PrivateCompanion] SDGen 生图未返回图片: response_type=%s", type(response).__name__)
                return "", "SDGen 未返回图片"
            image = str(images[0] or "").strip()
            if not image:
                logger.info("[PrivateCompanion] SDGen 生图返回空图片字段")
                return "", "SDGen 返回空图片"
            config = getattr(plugin, "config", {}) or {}
            try:
                enable_upscale = bool(config.get("enable_upscale", False))
            except Exception:
                enable_upscale = False
            processor = getattr(plugin, "_apply_image_processing", None)
            if enable_upscale and callable(processor):
                image = await processor(image)
            if "," in image and image.lower().lstrip().startswith("data:image"):
                image = image.split(",", 1)[1].strip()
            image_bytes = base64.b64decode(image)
            path = await self._save_external_generated_image(
                image_bytes,
                session_key=session_key,
                ext=".png",
            )
            logger.info(
                "[PrivateCompanion] SDGen 生图完成: images=%s path=%s bytes=%s",
                len(images),
                _single_line(path, 160),
                len(image_bytes),
            )
            return path, "ok" if path else "保存 SDGen 图片失败"
        except Exception as e:
            logger.warning(f"[PrivateCompanion] SDGen 生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_custom_tool_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        workflow_kind: str = "text2img",
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        handler = self._find_custom_photo_tool_handler()
        if handler is None:
            return "", "未找到配置的生图函数工具"
        prompt_param = _single_line(getattr(self, "custom_photo_tool_prompt_param", "prompt"), 60) or "prompt"
        kind_param = _single_line(getattr(self, "custom_photo_tool_kind_param", ""), 60)
        reference_param = _single_line(getattr(self, "custom_photo_tool_reference_param", ""), 60)
        extra_params_text = _single_line(getattr(self, "custom_photo_tool_extra_params", ""), 2000)
        tool_name = _single_line(getattr(self, "custom_photo_tool_name", ""), 120)
        kwargs: dict[str, Any] = {prompt_param: prompt_text}
        if kind_param:
            kwargs[kind_param] = workflow_kind
        if reference_param and reference_image_path:
            kwargs[reference_param] = reference_image_path
        if extra_params_text:
            try:
                extra = json.loads(extra_params_text)
                if isinstance(extra, dict):
                    for ek, ev in extra.items():
                        if ek not in kwargs:
                            kwargs[ek] = ev
            except Exception:
                logger.warning("[PrivateCompanion] 自定义生图工具额外参数解析失败,已忽略: tool=%s", _single_line(tool_name, 80))
        try:
            session = self._parse_message_session(session_key)
            if session is None:
                session = MessageSession(
                    platform_name="private_companion",
                    message_type=MessageType.FRIEND_MESSAGE,
                    session_id=str(session_key or "custom_tool"),
                )
            event = SyntheticPrivateWakeEvent(
                context=self.context,
                session=session,
                message="",
                sender_name="PrivateCompanion",
            )
        except Exception as exc:
            logger.warning("[PrivateCompanion] 构造自定义工具事件失败: %s", _single_line(exc, 160))
            return "", f"无法为函数工具构造事件上下文：{_single_line(exc, 120)}"
        logger.info(
            "[PrivateCompanion] 自定义工具生图提交: tool=%s session=%s kind=%s prompt_chars=%s reference=%s params=%s",
            _single_line(tool_name, 80),
            _single_line(session_key, 80),
            _single_line(workflow_kind, 30),
            len(str(prompt_text or "")),
            bool(reference_image_path),
            list(kwargs.keys()),
        )
        try:
            result = await handler(event, **kwargs)
        except TypeError:
            try:
                result = await handler(event=event, **kwargs)
            except Exception as exc:
                logger.warning("[PrivateCompanion] 自定义工具生图调用失败(keyword): %s", _single_line(exc, 200))
                return "", f"函数工具调用失败：{_single_line(exc, 160)}"
        except Exception as exc:
            logger.warning("[PrivateCompanion] 自定义工具生图调用失败: %s", _single_line(exc, 200))
            return "", f"函数工具调用失败：{_single_line(exc, 160)}"
        result_text = str(result or "") if not isinstance(result, str) else result
        if not result_text.strip():
            return "", "函数工具返回空结果"
        image_path, parse_note = await self._parse_custom_tool_photo_result(result_text, session_key=session_key)
        if image_path:
            logger.info(
                "[PrivateCompanion] 自定义工具生图完成: tool=%s path=%s note=%s result_preview=%s",
                _single_line(tool_name, 80),
                _single_line(image_path, 180),
                _single_line(parse_note, 120),
                _single_line(result_text, 180),
            )
            return image_path, f"ok ({_single_line(tool_name, 60)})"
        logger.info(
            "[PrivateCompanion] 自定义工具生图未解析到图片: tool=%s result_preview=%s",
            _single_line(tool_name, 80),
            _single_line(result_text, 220),
        )
        return "", f"函数工具返回结果未包含可识别的图片路径或数据：{_single_line(result_text, 160)}"

    async def _parse_custom_tool_photo_result(
        self,
        result_text: str,
        *,
        session_key: str,
    ) -> tuple[str, str]:
        text = str(result_text or "").strip()
        if not text:
            return "", "结果为空"
        json_data: Any = None
        try:
            json_data = json.loads(text)
        except Exception:
            pass
        if isinstance(json_data, dict):
            for key in ("image_path", "path", "file_path", "file", "image", "image_url", "url", "image_base64", "base64", "data"):
                val = json_data.get(key)
                if not val:
                    continue
                val_str = str(val).strip()
                if not val_str:
                    continue
                resolved, note = await self._resolve_custom_tool_image_candidate(val_str, session_key=session_key)
                if resolved:
                    return resolved, note
            for val in json_data.values():
                if not isinstance(val, str):
                    continue
                resolved, note = await self._resolve_custom_tool_image_candidate(val, session_key=session_key)
                if resolved:
                    return resolved, note
        url_matches = re.findall(r'https?://[^\s"\'<>\]\\]+', text)
        for url in url_matches:
            resolved, note = await self._resolve_custom_tool_image_candidate(url, session_key=session_key)
            if resolved:
                return resolved, note
        path_matches = re.findall(r'(?:[/\\][A-Za-z]:[\\/]|[A-Za-z]:[\\/]|/[\w\-./]+|[\w\-./]+\.(?:png|jpg|jpeg|webp|gif|bmp))', text)
        for path_str in path_matches:
            resolved, note = await self._resolve_custom_tool_image_candidate(path_str, session_key=session_key)
            if resolved:
                return resolved, note
        b64_match = re.search(r'(?:data:image/[a-z]+;base64,)?([A-Za-z0-9+/]{256,}={0,2})', text)
        if b64_match:
            b64_data = b64_match.group(1)
            try:
                image_bytes = base64.b64decode(b64_data)
                if image_bytes and len(image_bytes) > 100:
                    path = await self._save_external_generated_image(image_bytes, session_key=session_key, ext=".png")
                    if path:
                        return path, "base64 已保存"
            except Exception:
                pass
        return "", "未找到可识别的图片"

    async def _resolve_custom_tool_image_candidate(
        self,
        candidate: str,
        *,
        session_key: str,
    ) -> tuple[str, str]:
        text = str(candidate or "").strip().strip('"').strip("'").strip()
        if not text or len(text) < 3:
            return "", "候选为空"
        if text.lower().startswith(("http://", "https://")):
            path, note = await self._download_external_image_url(text, session_key=session_key)
            return path, note
        try:
            path = Path(text)
            if path.exists() and path.is_file():
                size = path.stat().st_size
                if size > 100:
                    return str(path), "本地文件"
        except Exception:
            pass
        if re.match(r'^[A-Za-z0-9+/]{256,}={0,2}$', text):
            try:
                image_bytes = base64.b64decode(text)
                if image_bytes and len(image_bytes) > 100:
                    path = await self._save_external_generated_image(image_bytes, session_key=session_key, ext=".png")
                    if path:
                        return path, "base64 已保存"
            except Exception:
                pass
        return "", "候选不可用"

    def _resolved_external_image_api_platform(self) -> str:
        normalizer = getattr(self, "_normalize_external_image_api_platform", None)
        configured = getattr(self, "external_image_api_platform", "auto")
        platform = normalizer(configured) if callable(normalizer) else str(configured or "auto").strip().lower()
        if platform in {"openai", "bailian", "modelscope", "doubao", "gemini", "sensenova"}:
            return platform
        base = self._normalized_external_image_api_base_url(platform=platform).lower()
        model = str(getattr(self, "external_image_api_model", "") or "").strip().lower()
        if "token.sensenova.cn" in base or model in {"senova-u1-fast", "sensenova-u1-fast"}:
            return "sensenova"
        if any(token in base for token in ("volces.com", "volcengine.com", "ark.cn-", "ark.ap-", "visual.volcengineapi.com")):
            return "doubao"
        if model.startswith(("doubao", "seedream")) or "seedream" in model:
            return "doubao"
        if any(token in base for token in ("generativelanguage.googleapis.com", "googleapis.com/v1beta/models")):
            return "gemini"
        if model.startswith(("gemini", "imagen")) or "nano-banana" in model:
            return "gemini"
        if "modelscope" in base or "api-inference" in base:
            return "modelscope"
        if any(token in base for token in ("dashscope.aliyuncs.com", "/services/aigc/", "/api/v1/tasks", "model-studio")):
            return "bailian"
        if model.startswith(("qwen-image", "wanx", "wan-", "wan2.", "wan2x", "wan")):
            return "bailian"
        return "openai"

    def _normalized_external_image_api_base_url(self, value: str = "", *, platform: str = "") -> str:
        raw = str(value or getattr(self, "external_image_api_base_url", "") or "").strip()
        if not raw:
            return ""
        if platform:
            resolved_platform = str(platform).strip().lower()
        else:
            normalizer = getattr(self, "_normalize_external_image_api_platform", None)
            configured = getattr(self, "external_image_api_platform", "auto")
            resolved_platform = normalizer(configured) if callable(normalizer) else str(configured or "auto").strip().lower()
        parsed = urlparse(raw)
        host = (parsed.netloc or "").strip().lower()
        path = (parsed.path or "").strip()

        console_hosts = {
            "bailian.console.aliyun.com",
            "modelstudio.console.aliyun.com",
            "bailian.console.alibabacloud.com",
            "modelstudio.console.alibabacloud.com",
        }
        shared_host_by_region = {
            "cn-beijing": "dashscope.aliyuncs.com",
            "ap-southeast-1": "dashscope-intl.aliyuncs.com",
            "us-east-1": "dashscope-us.aliyuncs.com",
            "us-virginia": "dashscope-us.aliyuncs.com",
        }

        def _root_with_host(target_host: str) -> str:
            if not target_host:
                return raw.rstrip("/")
            scheme = parsed.scheme or "https"
            suffix = "/compatible-mode/v1" if resolved_platform in {"openai", "doubao"} else "/api/v1"
            return f"{scheme}://{target_host}{suffix}"

        if host in console_hosts:
            region = ""
            parts = [part for part in path.split("/") if part]
            if parts:
                first = parts[0].strip().lower()
                if re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+", first):
                    region = first
            if not region:
                fragment = str(parsed.fragment or "")
                region_match = re.search(r"\b(cn-beijing|ap-southeast-1|us-east-1|us-virginia)\b", raw, flags=re.I)
                if region_match:
                    region = region_match.group(1).lower()
                elif fragment:
                    fragment_match = re.search(r"\b(cn-beijing|ap-southeast-1|us-east-1|us-virginia)\b", fragment, flags=re.I)
                    if fragment_match:
                        region = fragment_match.group(1).lower()
            mapped_host = shared_host_by_region.get(region, "dashscope.aliyuncs.com")
            return _root_with_host(mapped_host)

        if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"} or host.endswith(".maas.aliyuncs.com"):
            if resolved_platform == "openai":
                if "/images/" in path or path.endswith("/chat/completions") or "/audio/" in path:
                    prefix_match = re.match(r"^(.*?/compatible-mode/v1)(?:/.*)?$", path, flags=re.I)
                    prefix = prefix_match.group(1) if prefix_match else "/compatible-mode/v1"
                    return f"{parsed.scheme or 'https'}://{host}{prefix}"
                return f"{parsed.scheme or 'https'}://{host}/compatible-mode/v1"
            if path.startswith("/api/v1"):
                api_root = re.match(r"^(.*?/api/v1)(?:/.*)?$", path, flags=re.I)
                if api_root:
                    return f"{parsed.scheme or 'https'}://{host}{api_root.group(1)}"
            return f"{parsed.scheme or 'https'}://{host}/api/v1"

        if resolved_platform == "modelscope":
            if host and "modelscope" in host:
                scheme = parsed.scheme or "https"
                if path.startswith("/v1"):
                    api_root = re.match(r"^(.*?/v1)(?:/.*)?$", path, flags=re.I)
                    if api_root:
                        return f"{scheme}://{host}{api_root.group(1)}"
                return f"{scheme}://{host}/v1"
            if re.search(r"/v1(?:/(?:images|tasks).*)?$", raw, flags=re.I):
                root = re.sub(r"/v1(?:/(?:images|tasks).*)?$", "/v1", raw, flags=re.I).rstrip("/")
                return root
        if resolved_platform == "doubao":
            if host and ("volces.com" in host or "volcengine.com" in host):
                scheme = parsed.scheme or "https"
                if path.startswith("/api/v3"):
                    api_root = re.match(r"^(.*?/api/v3)(?:/.*)?$", path, flags=re.I)
                    if api_root:
                        return f"{scheme}://{host}{api_root.group(1)}"
                return f"{scheme}://{host}/api/v3"
            if re.search(r"/api/v3(?:/images(?:/generations|/edits)?)?$", raw, flags=re.I):
                return re.sub(r"/api/v3(?:/images(?:/generations|/edits)?)?$", "/api/v3", raw, flags=re.I).rstrip("/")
        if resolved_platform == "gemini":
            if host and "googleapis.com" in host:
                scheme = parsed.scheme or "https"
                if "/models/" in path:
                    return f"{scheme}://{host}{path.rstrip('/')}"
                api_root = re.match(r"^(/v[0-9A-Za-z]+(?:beta)?)(?:/.*)?$", path, flags=re.I)
                prefix = api_root.group(1) if api_root else "/v1beta"
                return f"{scheme}://{host}{prefix}"
            if re.search(r"/v[0-9A-Za-z]+(?:beta)?(?:/models/.*)?$", raw, flags=re.I):
                return raw.rstrip("/")
        if resolved_platform == "bailian":
            if "/compatible-mode/v1" in raw.lower():
                return re.sub(r"/compatible-mode/v1(?:/.*)?$", "/api/v1", raw, flags=re.I).rstrip("/")
            task_root = re.sub(r"/tasks(?:/.*)?$", "", raw, flags=re.I)
            if task_root != raw:
                return task_root.rstrip("/")
        elif resolved_platform == "openai":
            if re.search(r"/api/v1(?:/services/aigc/.*)?$", raw, flags=re.I):
                root = re.sub(r"/api/v1(?:/services/aigc/.*)?$", "", raw, flags=re.I).rstrip("/")
                return f"{root}/compatible-mode/v1"

        return raw.rstrip("/")

    def _external_image_platform_label(self, platform: str = "") -> str:
        resolved = str(platform or self._resolved_external_image_api_platform() or "").strip().lower()
        if resolved == "bailian":
            return "阿里云百炼"
        if resolved == "modelscope":
            return "魔搭社区"
        if resolved == "doubao":
            return "豆包/火山方舟"
        if resolved == "gemini":
            return "Gemini"
        if resolved == "openai":
            return "OpenAI 兼容"
        if resolved == "sensenova":
            return "SenseNova 日日新"
        return "在线图片 API"

    def _external_image_endpoint(self, endpoint_type: str = "generations") -> str:
        base = self._normalized_external_image_api_base_url(platform="openai").rstrip("/")
        if not base:
            return ""
        endpoint_type = str(endpoint_type or "generations").strip().lower()
        target = "edits" if endpoint_type == "edits" else "generations"
        if base.endswith(f"/images/{target}"):
            return base
        if base.endswith("/images/generations") or base.endswith("/images/edits"):
            return re.sub(r"/images/(?:generations|edits)$", f"/images/{target}", base)
        return f"{base}/images/{target}"

    def _external_image_endpoint_candidates(self, endpoint_type: str = "generations") -> list[str]:
        primary = self._external_image_endpoint(endpoint_type)
        if not primary:
            return []
        candidates = [primary]
        base = self._normalized_external_image_api_base_url(platform="openai").rstrip("/")
        endpoint_type = str(endpoint_type or "generations").strip().lower()
        target = "edits" if endpoint_type == "edits" else "generations"
        lowered_base = base.lower()
        if (
            base
            and "/v1" not in lowered_base
            and "/compatible-mode/v1" not in lowered_base
            and not re.search(r"/images/(?:generations|edits)$", lowered_base)
        ):
            candidates.append(f"{base}/v1/images/{target}")
        deduped: list[str] = []
        for item in candidates:
            clean = str(item or "").strip()
            if clean and clean not in deduped:
                deduped.append(clean)
        return deduped

    def _sanitize_external_image_size(self, override: str = "") -> str:
        raw = str(override or self.external_image_api_size or "1024x1024").strip().lower()
        if re.fullmatch(r"\d{2,5}x\d{2,5}", raw):
            return raw
        return "1024x1024"

    def _sanitize_bailian_image_size(self, override: str = "") -> str:
        size = self._sanitize_external_image_size(override)
        return size.replace("x", "*")

    def _sanitize_sensenova_image_size(self, override: str = "") -> str:
        supported = (
            (1664, 2496), (2496, 1664), (1760, 2368), (2368, 1760),
            (1824, 2272), (2272, 1824), (2048, 2048), (2752, 1536),
            (1536, 2752), (3072, 1376), (1344, 3136),
        )
        raw = str(override or getattr(self, "external_image_api_size", "") or "2752x1536").strip().lower()
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", raw)
        if not match:
            return "2752x1536"
        width, height = int(match.group(1)), int(match.group(2))
        if (width, height) in supported:
            return f"{width}x{height}"
        ratio = width / max(1, height)
        closest = min(supported, key=lambda item: abs((item[0] / item[1]) - ratio))
        return f"{closest[0]}x{closest[1]}"

    def _sensenova_image_model(self) -> str:
        model = str(getattr(self, "external_image_api_model", "") or "").strip()
        return "sensenova-u1-fast" if model.lower() == "senova-u1-fast" else model

    def _bailian_api_root(self) -> str:
        base = self._normalized_external_image_api_base_url(platform="bailian").rstrip("/")
        if not base:
            return ""
        known_suffixes = (
            "/services/aigc/multimodal-generation/generation",
            "/services/aigc/image-generation/generation",
            "/services/aigc/text2image/image-synthesis",
        )
        for suffix in known_suffixes:
            if base.endswith(suffix):
                return base[: -len(suffix)]
        task_match = re.match(r"^(https?://.+?/api/v1)/tasks(?:/.*)?$", base, flags=re.I)
        if task_match:
            return task_match.group(1).rstrip("/")
        api_match = re.match(r"^(https?://.+?/api/v1)(?:/.*)?$", base, flags=re.I)
        if api_match:
            return api_match.group(1).rstrip("/")
        if re.match(r"^https?://[^/]+$", base, flags=re.I):
            return f"{base}/api/v1"
        return base if base.endswith("/api/v1") else f"{base}/api/v1"

    def _bailian_multimodal_endpoint(self) -> str:
        base = str(self.external_image_api_base_url or "").strip().rstrip("/")
        if base.endswith("/services/aigc/multimodal-generation/generation"):
            return base
        root = self._bailian_api_root()
        return f"{root}/services/aigc/multimodal-generation/generation" if root else ""

    def _bailian_async_generation_endpoints(self) -> list[str]:
        base = str(self.external_image_api_base_url or "").strip().rstrip("/")
        root = self._bailian_api_root()
        candidates: list[str] = []
        for value in (
            base if base.endswith("/services/aigc/image-generation/generation") else "",
            base if base.endswith("/services/aigc/text2image/image-synthesis") else "",
            f"{root}/services/aigc/image-generation/generation" if root else "",
            f"{root}/services/aigc/text2image/image-synthesis" if root else "",
        ):
            cleaned = str(value or "").strip().rstrip("/")
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)
        return candidates

    def _bailian_task_endpoint(self, task_id: str) -> str:
        root = self._bailian_api_root()
        safe_task_id = quote(str(task_id or "").strip(), safe="")
        return f"{root}/tasks/{safe_task_id}" if root and safe_task_id else ""

    def _bailian_prefers_multimodal(self) -> bool:
        model = str(getattr(self, "external_image_api_model", "") or "").strip().lower()
        return "qwen-image" in model or "image-edit" in model

    def _modelscope_api_root(self) -> str:
        base = self._normalized_external_image_api_base_url(platform="modelscope").rstrip("/")
        if not base:
            return ""
        if base.endswith("/v1"):
            return base
        if re.match(r"^https?://[^/]+$", base, flags=re.I):
            return f"{base}/v1"
        return re.sub(r"/v1(?:/.*)?$", "/v1", base, flags=re.I).rstrip("/")

    def _modelscope_generation_endpoint(self) -> str:
        base = str(self.external_image_api_base_url or "").strip().rstrip("/")
        if base.endswith("/v1/images/generations"):
            return base
        root = self._modelscope_api_root()
        return f"{root}/images/generations" if root else ""

    def _modelscope_task_endpoint(self, task_id: str) -> str:
        root = self._modelscope_api_root()
        safe_task_id = quote(str(task_id or "").strip(), safe="")
        return f"{root}/tasks/{safe_task_id}" if root and safe_task_id else ""

    def _doubao_api_root(self) -> str:
        base = self._normalized_external_image_api_base_url(platform="doubao").rstrip("/")
        if not base:
            return ""
        if re.match(r"^https?://[^/]+$", base, flags=re.I):
            return f"{base}/api/v3"
        api_match = re.match(r"^(https?://.+?/api/v3)(?:/.*)?$", base, flags=re.I)
        if api_match:
            return api_match.group(1).rstrip("/")
        return base if base.endswith("/api/v3") else f"{base}/api/v3"

    def _doubao_generation_endpoint(self) -> str:
        base = str(self.external_image_api_base_url or "").strip().rstrip("/")
        if base.endswith("/images/generations"):
            return base
        root = self._doubao_api_root()
        return f"{root}/images/generations" if root else ""

    def _gemini_api_root(self) -> str:
        base = self._normalized_external_image_api_base_url(platform="gemini").rstrip("/")
        if not base:
            return ""
        if re.match(r"^https?://[^/]+$", base, flags=re.I):
            return f"{base}/v1beta"
        model_match = re.match(r"^(https?://.+?)/v[0-9A-Za-z]+(?:beta)?/models/.*$", base, flags=re.I)
        if model_match:
            return base
        api_match = re.match(r"^(https?://.+?/v[0-9A-Za-z]+(?:beta)?)(?:/.*)?$", base, flags=re.I)
        if api_match:
            return api_match.group(1).rstrip("/")
        return base

    def _gemini_generate_content_endpoint(self) -> str:
        base = str(self.external_image_api_base_url or "").strip().rstrip("/")
        model = quote(str(getattr(self, "external_image_api_model", "") or "").strip(), safe="-_.~")
        if not model:
            return ""
        if base.endswith(":generateContent"):
            return base
        if re.search(r"/models/[^/]+$", base, flags=re.I):
            return f"{base}:generateContent"
        root = self._gemini_api_root()
        if re.search(r"/models/[^/]+$", root, flags=re.I):
            return f"{root}:generateContent"
        return f"{root}/models/{model}:generateContent" if root else ""

    def _extract_gemini_inline_images(self, payload: Any) -> list[tuple[str, str]]:
        images: list[tuple[str, str]] = []

        def walk(value: Any, depth: int = 0) -> None:
            if depth > 10:
                return
            if isinstance(value, dict):
                inline = value.get("inlineData") or value.get("inline_data")
                if isinstance(inline, dict):
                    data = str(inline.get("data") or "").strip()
                    mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png").strip()
                    if data:
                        images.append((data, mime))
                file_data = value.get("fileData") or value.get("file_data")
                if isinstance(file_data, dict):
                    uri = str(file_data.get("fileUri") or file_data.get("file_uri") or "").strip()
                    if uri:
                        images.append((uri, ""))
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    walk(child, depth + 1)

        walk(payload)
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for data, mime in images:
            if data in seen:
                continue
            seen.add(data)
            deduped.append((data, mime))
        return deduped

    def _external_payload_first_value(self, payload: Any, keys: tuple[str, ...], *, _depth: int = 0) -> Any:
        if payload is None or _depth > 8:
            return None
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and payload.get(key) not in (None, ""):
                    return payload.get(key)
            for value in payload.values():
                found = self._external_payload_first_value(value, keys, _depth=_depth + 1)
                if found not in (None, ""):
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = self._external_payload_first_value(value, keys, _depth=_depth + 1)
                if found not in (None, ""):
                    return found
        return None

    def _external_payload_image_values(self, payload: Any, *, _depth: int = 0) -> list[Any]:
        if payload is None or _depth > 8:
            return []
        values: list[Any] = []
        image_keys = (
            "url",
            "image",
            "image_url",
            "imageUrl",
            "output_image",
            "outputImage",
            "result",
            "b64_json",
            "base64",
            "base64_image",
            "data_url",
        )
        image_list_keys = (
            "data",
            "images",
            "image_urls",
            "imageUrls",
            "output_images",
            "outputImages",
            "results",
            "outputs",
        )
        if isinstance(payload, dict):
            for key in image_keys:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)
            for key in image_list_keys:
                value = payload.get(key)
                if isinstance(value, list):
                    for item in value:
                        values.extend(self._external_payload_image_values(item, _depth=_depth + 1))
                elif isinstance(value, dict):
                    values.extend(self._external_payload_image_values(value, _depth=_depth + 1))
                elif isinstance(value, str) and value.strip():
                    values.append(value)
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    values.extend(self._external_payload_image_values(value, _depth=_depth + 1))
        elif isinstance(payload, list):
            for item in payload:
                values.extend(self._external_payload_image_values(item, _depth=_depth + 1))
        elif isinstance(payload, str):
            text = payload.strip()
            if text.startswith(("http://", "https://", "data:image")) or len(text) > 128:
                values.append(text)
        deduped: list[Any] = []
        seen: set[str] = set()
        for value in values:
            marker = str(value)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(value)
        return deduped

    async def _reference_image_to_data_url(self, reference_image_path: str) -> str:
        path = Path(str(reference_image_path or ""))
        if not path.exists() or not path.is_file():
            return ""
        suffix = path.suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix)
        if not mime_type:
            return ""
        image_bytes = await asyncio.to_thread(path.read_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    async def _materialize_external_image_value(
        self,
        image_value: Any,
        *,
        session_key: str,
        success_note: str = "ok",
    ) -> tuple[str, str]:
        if isinstance(image_value, dict):
            image_value = (
                image_value.get("url")
                or image_value.get("image")
                or image_value.get("image_url")
                or image_value.get("imageUrl")
                or image_value.get("output_image")
                or image_value.get("outputImage")
                or image_value.get("result")
                or image_value.get("b64_json")
                or image_value.get("base64")
                or image_value.get("base64_image")
                or image_value.get("data_url")
                or ""
            )
        raw = str(image_value or "").strip()
        if not raw:
            return "", "图片结果为空"
        if raw.lower().startswith("data:image") and "," in raw:
            header, encoded = raw.split(",", 1)
            mime_match = re.match(r"data:(image/[a-z0-9.+-]+);base64$", header.strip(), flags=re.I)
            ext = ".png"
            if mime_match:
                mime_type = mime_match.group(1).lower()
                if "jpeg" in mime_type or "jpg" in mime_type:
                    ext = ".jpg"
                elif "webp" in mime_type:
                    ext = ".webp"
            image_bytes = base64.b64decode(encoded)
            saved = await self._save_external_generated_image(image_bytes, session_key=session_key, ext=ext)
            return saved, success_note if saved else "保存在线图片失败"
        if re.fullmatch(r"[A-Za-z0-9+/=\\s]+", raw) and len(raw) > 128:
            try:
                image_bytes = base64.b64decode(raw)
                saved = await self._save_external_generated_image(image_bytes, session_key=session_key, ext=".png")
                if saved:
                    return saved, success_note
            except Exception:
                pass
        saved, note = await self._download_external_image_url(raw, session_key=session_key)
        return saved, success_note if saved else note

    def _external_image_model_misconfiguration_note(self) -> str:
        model = _single_line(getattr(self, "external_image_api_model", ""), 120)
        if not model:
            return "未配置在线图片模型"
        lowered = model.lower()
        platform = self._resolved_external_image_api_platform()
        image_tokens = ("image", "img", "dall", "flux", "sd", "stable-diffusion", "midjourney", "mj", "kolors", "wanx", "wan", "seedream", "imagen", "nano-banana")
        text_model_prefixes = ("gpt-", "claude", "gemini", "deepseek", "qwen", "glm", "moonshot", "kimi", "yi-", "doubao")
        if platform == "bailian" and (lowered.startswith("qwen-image") or lowered.startswith("wan")):
            return ""
        if platform == "doubao" and (lowered.startswith(("doubao-seedream", "seedream")) or "seedream" in lowered):
            return ""
        if platform == "gemini" and any(token in lowered for token in ("image", "imagen", "nano-banana")):
            return ""
        if platform == "sensenova":
            if lowered in {"senova-u1-fast", "sensenova-u1-fast"}:
                return ""
            return "SenseNova 日日新信息图模型必须填写官方 Model ID：sensenova-u1-fast"
        if lowered.startswith(text_model_prefixes) and not any(token in lowered for token in image_tokens):
            return f"在线图片模型填成了文本/聊天模型：{model}。请改成该平台的图片模型名，例如支持 /images/generations 或 /images/edits 的模型。"
        return ""

    def _external_image_api_error_note(self, status: int, text: str, *, reference: bool = False, endpoint: str = "") -> str:
        raw = _single_line(text, 260)
        lowered = raw.lower()
        if "requires an image model" in lowered or "image model" in lowered and "got" in lowered:
            return self._external_image_model_misconfiguration_note() or (
                f"在线图片模型不支持 images 接口。当前模型：{_single_line(getattr(self, 'external_image_api_model', ''), 80) or '-'}，请改成图片模型。"
            )
        prefix = "参考图接口" if reference else ""
        endpoint_note = f"端点 {endpoint} " if endpoint else ""
        platform_getter = getattr(self, "_resolved_external_image_api_platform", None)
        platform = platform_getter() if callable(platform_getter) else ""
        if platform == "sensenova" and int(status) == 403:
            return (
                f"{prefix}{endpoint_note}HTTP 403：SenseNova 官方错误码表示当前请求语言不受支持。"
                "请把提示词改为中文或英文，并避免仅使用无法识别的混合符号/小语种后重试。"
                f"返回：{_single_line(text, 120)}"
            )
        if platform == "sensenova" and int(status) == 401:
            if "authorization not found" in lowered or "missing authorization" in lowered:
                return (
                    f"{prefix}{endpoint_note}HTTP 401：SenseNova 未识别到 Authorization。"
                    "应使用 Authorization: Bearer <控制台 API Key>。"
                )
            return (
                f"{prefix}{endpoint_note}HTTP 401：SenseNova 已收到 Bearer，但 API Key 无效或当前额度不足。"
                "请在 platform.sensenova.cn 控制台检查 Key 状态与 Token Plan。"
                f"返回：{_single_line(text, 120)}"
            )
        if int(status) in {401, 403}:
            if "authorization not found" in lowered or "missing authorization" in lowered:
                return (
                    f"{prefix}{endpoint_note}HTTP {status}：服务未识别到鉴权信息。"
                    "OpenAI 兼容链路应使用 Authorization: Bearer <API Key>；请检查自定义请求头是否覆盖或删除了 Authorization。"
                )
            permission_causes = "API Key 无效、已过期、被停用，或没有该图片模型/接口权限"
            if int(status) == 403:
                permission_causes += "；也可能命中账号/IP 白名单或网关 WAF"
            return (
                f"{prefix}{endpoint_note}HTTP {status}：鉴权已送达但服务拒绝访问。"
                f"常见原因：{permission_causes}。返回：{_single_line(text, 120)}"
            )
        if int(status) == 404:
            return (
                f"{prefix}{endpoint_note}HTTP 404：未找到生图接口。"
                "请检查在线 API 地址是否需要 /v1，或该代理是否支持 /images/generations。"
                f"返回：{_single_line(text, 120)}"
            )
        return f"{prefix}{endpoint_note}HTTP {status}: {_single_line(text, 180)}"

    def _url_same_origin(self, left: str, right: str) -> bool:
        try:
            l_parsed = urlparse(str(left or ""))
            r_parsed = urlparse(str(right or ""))
        except Exception:
            return False
        return bool(
            l_parsed.scheme
            and r_parsed.scheme
            and l_parsed.scheme.lower() == r_parsed.scheme.lower()
            and l_parsed.netloc.lower() == r_parsed.netloc.lower()
        )

    def _external_image_download_headers(self, target_url: str) -> tuple[dict[str, str], str]:
        headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 AstrBot PrivateCompanion/5.0.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        api_endpoint = self._external_image_endpoint("generations")
        api_base = str(getattr(self, "external_image_api_base_url", "") or "").strip()
        same_origin = self._url_same_origin(target_url, api_endpoint) or self._url_same_origin(target_url, api_base)
        custom_count = 0
        auth_sent = False
        if same_origin:
            if getattr(self, "external_image_api_key", ""):
                headers["Authorization"] = f"Bearer {self.external_image_api_key}"
                auth_sent = True
            for key, value in self._external_image_custom_headers().items():
                normalized = str(key or "").strip()
                if normalized.lower() in {"content-length", "content-type", "host", "connection", "transfer-encoding"}:
                    continue
                headers[normalized] = str(value)
                custom_count += 1
            if not any(key.lower() == "referer" for key in headers):
                referer = api_endpoint or api_base
                if referer:
                    headers["Referer"] = referer
        note = f"same_origin={same_origin},auth={auth_sent},custom={custom_count},referer={any(key.lower() == 'referer' for key in headers)}"
        return headers, note

    def _external_image_download_target(self, target_url: str) -> tuple[Any, bool]:
        """Preserve the exact encoding of temporary object-storage signed URLs."""
        target = str(target_url or "").strip()
        lowered = target.lower()
        signed_markers = (
            "x-amz-algorithm=",
            "x-amz-credential=",
            "x-amz-signature=",
            "x-oss-signature=",
        )
        if not any(marker in lowered for marker in signed_markers):
            return target, False
        try:
            from yarl import URL

            # aiohttp normally canonicalizes URLs. Re-quoting even one signed path or
            # query byte makes OSS/S3 reject an otherwise valid temporary URL with 403.
            return URL(target, encoded=True), True
        except Exception:
            return target, False

    def _external_image_timeout_note(self, *, reference: bool = False, download: bool = False, label: str = "") -> str:
        timeout_seconds = _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1)
        if label:
            target = label
        elif download:
            target = "下载在线图片结果"
        elif reference:
            target = "在线图片 API 参考图接口"
        else:
            target = "在线图片 API"
        return f"{target}超时（{timeout_seconds}秒内没有返回），可调高在线生图超时秒数或切换/回退本地生图后端"

    def _external_generated_image_output_path(self, *, session_key: str, ext: str = ".png") -> Path:
        safe_ext = ext if ext.startswith(".") else f".{ext}"
        if safe_ext.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            safe_ext = ".png"
        out_dir = Path(self.data_dir) / "generated_photos"
        out_dir.mkdir(parents=True, exist_ok=True)
        session_part = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(session_key or "private_companion"))[:60] or "private_companion"
        return out_dir / f"{session_part}_{self._environment_now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{safe_ext}"

    async def _save_external_generated_image(
        self,
        image_bytes: bytes,
        *,
        session_key: str,
        ext: str = ".png",
    ) -> str:
        if not image_bytes:
            return ""
        file_path = self._external_generated_image_output_path(session_key=session_key, ext=ext)
        await asyncio.to_thread(file_path.write_bytes, image_bytes)
        logger.info(
            "[PrivateCompanion] 生图文件已保存: session=%s path=%s bytes=%s",
            _single_line(session_key, 80),
            _single_line(str(file_path), 180),
            len(image_bytes),
        )
        return str(file_path)

    def _external_image_download_proxy_url(self) -> str:
        proxy = str(getattr(self, "external_image_download_proxy", "") or "").strip()
        if not proxy:
            return ""
        try:
            parsed = urlparse(proxy)
        except Exception:
            parsed = None
        if not parsed or parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            logger.warning("[PrivateCompanion] 在线图片下载代理格式无效，已忽略")
            return ""
        return proxy

    async def _get_external_image_download_session(self, *, use_environment_proxy: bool) -> tuple[Any, bool]:
        import aiohttp

        session = getattr(self, "_external_image_download_session", None)
        session_trust_env = getattr(self, "_external_image_download_session_trust_env", None)
        if session is not None and not session.closed and session_trust_env == use_environment_proxy:
            return session, True

        lock = getattr(self, "_external_image_download_session_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._external_image_download_session_lock = lock
        async with lock:
            session = getattr(self, "_external_image_download_session", None)
            session_trust_env = getattr(self, "_external_image_download_session_trust_env", None)
            if session is not None and not session.closed and session_trust_env == use_environment_proxy:
                return session, True
            if session is not None and not session.closed:
                await session.close()
            connector = aiohttp.TCPConnector(limit=8, limit_per_host=4, ttl_dns_cache=300)
            session = aiohttp.ClientSession(connector=connector, trust_env=use_environment_proxy)
            self._external_image_download_session = session
            self._external_image_download_session_trust_env = use_environment_proxy
            return session, False

    async def _close_external_image_download_session(self) -> None:
        session = getattr(self, "_external_image_download_session", None)
        self._external_image_download_session = None
        self._external_image_download_session_trust_env = None
        if session is not None and not session.closed:
            await session.close()

    async def _download_external_image_url(self, url: str, *, session_key: str) -> tuple[str, str]:
        target = str(url or "").strip()
        if not target:
            return "", "图片地址为空"
        configured_timeout = _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 20, 600)
        # Keep URL retrieval independent from the longer image-generation request.
        download_timeout = min(configured_timeout, 75)
        max_bytes = 32 * 1024 * 1024
        started_at = time.perf_counter()
        temporary_path: Path | None = None
        try:
            import aiohttp

            headers, header_note = self._external_image_download_headers(target)
            request_target, signed_url_preserved = self._external_image_download_target(target)
            header_note = f"{header_note},signed_url_preserved={signed_url_preserved}"
            use_environment_proxy = bool(getattr(self, "external_image_download_use_environment_proxy", False))
            proxy_url = self._external_image_download_proxy_url()
            timeout = aiohttp.ClientTimeout(
                total=float(download_timeout),
                sock_connect=min(15.0, float(download_timeout)),
                sock_read=min(30.0, float(download_timeout)),
            )
            session, session_reused = await self._get_external_image_download_session(
                use_environment_proxy=use_environment_proxy,
            )
            request_options: dict[str, Any] = {"headers": headers, "timeout": timeout}
            if proxy_url:
                request_options["proxy"] = proxy_url
            async with session.get(request_target, **request_options) as response:
                if response.status >= 400:
                    logger.info(
                        "[PrivateCompanion] 下载在线生图结果失败: status=%s headers=%s url=%s",
                        response.status,
                        header_note,
                        _single_line(target, 180),
                    )
                    return "", f"下载图片失败：HTTP {response.status}"
                content_type = str(response.headers.get("Content-Type", "") or "").lower()
                declared_size = _safe_int(response.headers.get("Content-Length"), 0, 0)
                if declared_size > max_bytes:
                    logger.info(
                        "[PrivateCompanion] 下载在线生图结果过大,已停止: bytes=%s limit=%s url=%s",
                        declared_size,
                        max_bytes,
                        _single_line(target, 180),
                    )
                    return "", f"下载图片过大（超过 {max_bytes // (1024 * 1024)} MB）"
                ext = ".png"
                if "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                elif "webp" in content_type:
                    ext = ".webp"
                output_path = self._external_generated_image_output_path(session_key=session_key, ext=ext)
                temporary_path = output_path.with_name(f"{output_path.name}.part")
                received_size = 0
                with temporary_path.open("wb") as output:
                    async for chunk in response.content.iter_chunked(128 * 1024):
                        received_size += len(chunk)
                        if received_size > max_bytes:
                            logger.info(
                                "[PrivateCompanion] 下载在线生图结果超过大小上限,已停止: bytes=%s limit=%s url=%s",
                                received_size,
                                max_bytes,
                                _single_line(target, 180),
                            )
                            return "", f"下载图片过大（超过 {max_bytes // (1024 * 1024)} MB）"
                        output.write(chunk)
                if received_size <= 0:
                    return "", "下载图片为空"
                await asyncio.to_thread(temporary_path.replace, output_path)
                temporary_path = None
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "[PrivateCompanion] 下载在线生图结果完成: status=%s content_type=%s bytes=%s elapsed=%sms reused=%s proxy=%s env_proxy=%s timeout=%ss url=%s",
                response.status,
                _single_line(content_type, 80),
                received_size,
                elapsed_ms,
                session_reused,
                bool(proxy_url),
                use_environment_proxy,
                download_timeout,
                _single_line(target, 180),
            )
            logger.info(
                "[PrivateCompanion] 生图文件已保存: session=%s path=%s bytes=%s",
                _single_line(session_key, 80),
                _single_line(str(output_path), 180),
                received_size,
            )
            return str(output_path), "ok"
        except asyncio.TimeoutError:
            note = f"下载在线图片结果超时（{download_timeout} 秒内未完成），请检查运行 Bot 的服务器是否能直连该图片 URL"
            logger.info("[PrivateCompanion] 下载在线生图结果超时: url=%s note=%s", _single_line(target, 180), note)
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 下载在线生图结果失败: {e}", exc_info=True)
            return "", str(e)
        finally:
            if temporary_path is not None:
                try:
                    if temporary_path.exists():
                        await asyncio.to_thread(temporary_path.unlink)
                except Exception:
                    pass

    async def _run_bailian_multimodal_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoint = self._bailian_multimodal_endpoint()
        if not endpoint:
            return "", "未配置百炼 API 地址"
        try:
            import aiohttp

            content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
            used_reference = False
            if reference_image_path:
                reference_value = reference_image_path
                if not re.match(r"^https?://", reference_value, flags=re.I):
                    reference_value = await self._reference_image_to_data_url(reference_value)
                if reference_value:
                    content.append({"type": "image", "image": reference_value})
                    used_reference = True
            payload = {
                "model": self.external_image_api_model,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": self._sanitize_bailian_image_size(image_size)},
            }
            headers = {
                "Authorization": f"Bearer {self.external_image_api_key}",
                "Content-Type": "application/json",
            }
            headers.update(self._external_image_custom_headers())
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            logger.info(
                "[PrivateCompanion] 百炼多模态生图提交: endpoint=%s model=%s size=%s reference=%s prompt_preview=%s",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _single_line(payload["parameters"]["size"], 40),
                used_reference,
                _single_line(prompt_text, 180),
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, headers=headers, json=payload) as response:
                    text = await response.text()
                    logger.info(
                        "[PrivateCompanion] 百炼多模态生图响应: status=%s chars=%s preview=%s",
                        response.status,
                        len(text or ""),
                        _single_line(text, 220),
                    )
                    if response.status >= 400:
                        return "", f"百炼多模态生图 HTTP {response.status}: {_single_line(text, 180)}"
            data = self._extract_json_payload(text) if text else {}
            if not isinstance(data, dict):
                return "", "百炼多模态生图返回格式无效"
            output = data.get("output") if isinstance(data.get("output"), dict) else {}
            choices = output.get("choices")
            if not isinstance(choices, list) or not choices:
                return "", "百炼多模态生图未返回 choices"
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
            items = message.get("content")
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                return "", "百炼多模态生图未返回图片内容"
            for item in items:
                if not isinstance(item, dict):
                    continue
                image_value = (
                    item.get("image")
                    or item.get("image_url")
                    or item.get("url")
                    or (item.get("result") if isinstance(item.get("result"), str) else "")
                )
                if image_value:
                    note = "ok；已使用本地人设参考图" if used_reference else "ok"
                    return await self._materialize_external_image_value(
                        image_value,
                        session_key=session_key,
                        success_note=note,
                    )
            return "", "百炼多模态生图未返回图片地址"
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(label="百炼多模态生图接口")
            logger.info(
                "[PrivateCompanion] 百炼多模态生图超时: endpoint=%s model=%s timeout=%ss",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 百炼多模态生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_bailian_async_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoints = self._bailian_async_generation_endpoints()
        if not endpoints:
            return "", "未配置百炼 API 地址"
        try:
            import aiohttp

            headers = {
                "Authorization": f"Bearer {self.external_image_api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            headers.update(self._external_image_custom_headers())
            payload = {
                "model": self.external_image_api_model,
                "input": {"prompt": prompt_text},
                "parameters": {"size": self._sanitize_bailian_image_size(image_size)},
            }
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            task_id = ""
            submit_note = ""
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for endpoint in endpoints:
                    logger.info(
                        "[PrivateCompanion] 百炼异步生图提交: endpoint=%s model=%s size=%s prompt_preview=%s",
                        _single_line(endpoint, 160),
                        _single_line(self.external_image_api_model, 80),
                        _single_line(payload["parameters"]["size"], 40),
                        _single_line(prompt_text, 180),
                    )
                    async with session.post(endpoint, headers=headers, json=payload) as response:
                        text = await response.text()
                        logger.info(
                            "[PrivateCompanion] 百炼异步生图响应: status=%s chars=%s preview=%s",
                            response.status,
                            len(text or ""),
                            _single_line(text, 220),
                        )
                        if response.status >= 400:
                            submit_note = f"百炼异步生图 HTTP {response.status}: {_single_line(text, 180)}"
                            if response.status in {404, 405}:
                                continue
                            return "", submit_note
                    data = self._extract_json_payload(text) if text else {}
                    if not isinstance(data, dict):
                        submit_note = "百炼异步生图返回格式无效"
                        continue
                    output = data.get("output") if isinstance(data.get("output"), dict) else {}
                    task_id = str(output.get("task_id") or data.get("task_id") or "").strip()
                    if task_id:
                        break
                    submit_note = _single_line(
                        output.get("message") or data.get("message") or "百炼异步生图未返回任务 ID",
                        180,
                    )
                if not task_id:
                    return "", submit_note or "百炼异步生图未返回任务 ID"

                task_endpoint = self._bailian_task_endpoint(task_id)
                if not task_endpoint:
                    return "", "无法生成百炼任务查询地址"

                deadline = time.monotonic() + float(self.external_image_api_timeout_seconds)
                while True:
                    if time.monotonic() >= deadline:
                        return "", self._external_image_timeout_note(label="百炼异步生图任务轮询")
                    task_headers = {
                        "Authorization": f"Bearer {self.external_image_api_key}",
                        **self._external_image_custom_headers(),
                    }
                    async with session.get(task_endpoint, headers=task_headers) as response:
                        text = await response.text()
                        logger.info(
                            "[PrivateCompanion] 百炼任务查询响应: status=%s task=%s chars=%s preview=%s",
                            response.status,
                            _single_line(task_id, 80),
                            len(text or ""),
                            _single_line(text, 220),
                        )
                        if response.status >= 400:
                            return "", f"百炼任务查询 HTTP {response.status}: {_single_line(text, 180)}"
                    data = self._extract_json_payload(text) if text else {}
                    if not isinstance(data, dict):
                        await asyncio.sleep(2)
                        continue
                    output = data.get("output") if isinstance(data.get("output"), dict) else {}
                    task_status = str(output.get("task_status") or data.get("task_status") or output.get("status") or "").strip().upper()
                    if task_status in {"SUCCEEDED", "SUCCESS"}:
                        results = output.get("results")
                        if isinstance(results, list):
                            for item in results:
                                if not isinstance(item, dict):
                                    continue
                                image_value = item.get("url") or item.get("image") or item.get("image_url")
                                if image_value:
                                    return await self._materialize_external_image_value(
                                        image_value,
                                        session_key=session_key,
                                        success_note="ok",
                                    )
                        choices = output.get("choices")
                        if isinstance(choices, list):
                            for item in choices:
                                if not isinstance(item, dict):
                                    continue
                                message = item.get("message") if isinstance(item.get("message"), dict) else {}
                                content = message.get("content")
                                if isinstance(content, dict):
                                    content = [content]
                                if not isinstance(content, list):
                                    continue
                                for part in content:
                                    if not isinstance(part, dict):
                                        continue
                                    image_value = part.get("image") or part.get("image_url") or part.get("url")
                                    if image_value:
                                        return await self._materialize_external_image_value(
                                            image_value,
                                            session_key=session_key,
                                            success_note="ok",
                                        )
                        return "", "百炼任务成功但未返回图片地址"
                    if task_status in {"FAILED", "FAIL", "CANCELED", "CANCELLED"}:
                        return "", _single_line(
                            output.get("message") or data.get("message") or "百炼异步生图任务失败",
                            180,
                        )
                    await asyncio.sleep(2)
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(label="百炼异步生图接口")
            logger.info(
                "[PrivateCompanion] 百炼异步生图超时: model=%s timeout=%ss",
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 百炼异步生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_modelscope_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoint = self._modelscope_generation_endpoint()
        if not endpoint:
            return "", "未配置魔搭社区 API 地址"
        try:
            import aiohttp

            headers = {
                "Authorization": f"Bearer {self.external_image_api_key}",
                "Content-Type": "application/json",
                "X-ModelScope-Async-Mode": "true",
                "X-ModelScope-Task-Type": "text-to-image-generation",
            }
            headers.update(self._external_image_custom_headers())
            payload = {
                "model": self.external_image_api_model,
                "prompt": prompt_text,
                "size": self._sanitize_external_image_size(image_size),
            }
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                logger.info(
                    "[PrivateCompanion] 魔搭异步生图提交: endpoint=%s model=%s size=%s prompt_preview=%s",
                    _single_line(endpoint, 160),
                    _single_line(self.external_image_api_model, 80),
                    _single_line(payload["size"], 40),
                    _single_line(prompt_text, 180),
                )
                async with session.post(endpoint, headers=headers, json=payload) as response:
                    text = await response.text()
                    logger.info(
                        "[PrivateCompanion] 魔搭生图提交响应: status=%s chars=%s preview=%s",
                        response.status,
                        len(text or ""),
                        _single_line(text, 220),
                    )
                    if response.status >= 400:
                        return "", f"魔搭生图 HTTP {response.status}: {_single_line(text, 180)}"
                data = self._extract_json_payload(text) if text else {}
                if not isinstance(data, dict):
                    return "", "魔搭生图返回格式无效"
                for image_value in self._external_payload_image_values(data):
                    return await self._materialize_external_image_value(
                        image_value,
                        session_key=session_key,
                        success_note="ok",
                    )
                task_id = str(
                    self._external_payload_first_value(data, ("task_id", "taskId", "id", "task"))
                    or ""
                ).strip()
                if not task_id:
                    message = self._external_payload_first_value(data, ("message", "msg", "error", "error_message"))
                    return "", _single_line(message or "魔搭生图未返回任务 ID 或图片结果", 180)

                task_endpoint = self._modelscope_task_endpoint(task_id)
                if not task_endpoint:
                    return "", "无法生成魔搭任务查询地址"
                deadline = time.monotonic() + float(self.external_image_api_timeout_seconds)
                while True:
                    if time.monotonic() >= deadline:
                        return "", self._external_image_timeout_note(label="魔搭异步生图任务轮询")
                    async with session.get(task_endpoint, headers=headers) as response:
                        poll_text = await response.text()
                        logger.info(
                            "[PrivateCompanion] 魔搭任务查询响应: status=%s task=%s chars=%s preview=%s",
                            response.status,
                            _single_line(task_id, 80),
                            len(poll_text or ""),
                            _single_line(poll_text, 220),
                        )
                        if response.status >= 400:
                            return "", f"魔搭任务查询 HTTP {response.status}: {_single_line(poll_text, 180)}"
                    poll_data = self._extract_json_payload(poll_text) if poll_text else {}
                    if not isinstance(poll_data, dict):
                        await asyncio.sleep(2)
                        continue
                    for image_value in self._external_payload_image_values(poll_data):
                        return await self._materialize_external_image_value(
                            image_value,
                            session_key=session_key,
                            success_note="ok",
                        )
                    status = str(
                        self._external_payload_first_value(
                            poll_data,
                            ("task_status", "taskStatus", "status", "state"),
                        )
                        or ""
                    ).strip().upper()
                    if status in {"SUCCEED", "SUCCEEDED", "SUCCESS", "COMPLETED", "FINISHED", "DONE"}:
                        return "", "魔搭任务成功但未返回图片地址"
                    if status in {"FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED"}:
                        message = self._external_payload_first_value(
                            poll_data,
                            ("message", "msg", "error", "error_message", "task_message"),
                        )
                        return "", _single_line(message or "魔搭异步生图任务失败", 180)
                    await asyncio.sleep(2)
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(label="魔搭异步生图接口")
            logger.info(
                "[PrivateCompanion] 魔搭异步生图超时: model=%s timeout=%ss",
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 魔搭异步生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_doubao_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoint = self._doubao_generation_endpoint()
        if not endpoint:
            return "", "未配置豆包/火山方舟 API 地址"
        try:
            import aiohttp

            payload = {
                "model": self.external_image_api_model,
                "prompt": prompt_text,
                "size": self._sanitize_external_image_size(image_size),
            }
            headers = {
                "Authorization": f"Bearer {self.external_image_api_key}",
                "Content-Type": "application/json",
            }
            headers.update(self._external_image_custom_headers())
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            logger.info(
                "[PrivateCompanion] 豆包/火山方舟生图提交: endpoint=%s model=%s size=%s prompt_preview=%s",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _single_line(payload["size"], 40),
                _single_line(prompt_text, 180),
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, headers=headers, json=payload) as response:
                    text = await response.text()
                    logger.info(
                        "[PrivateCompanion] 豆包/火山方舟生图响应: status=%s chars=%s preview=%s",
                        response.status,
                        len(text or ""),
                        _single_line(text, 220),
                    )
                    if response.status >= 400:
                        return "", f"豆包/火山方舟生图 HTTP {response.status}: {_single_line(text, 180)}"
            data = self._extract_json_payload(text) if text else {}
            if not isinstance(data, dict):
                return "", "豆包/火山方舟生图返回格式无效"
            for image_value in self._external_payload_image_values(data):
                return await self._materialize_external_image_value(
                    image_value,
                    session_key=session_key,
                    success_note="ok",
                )
            return "", "豆包/火山方舟生图未返回图片数据"
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(label="豆包/火山方舟生图接口")
            logger.info(
                "[PrivateCompanion] 豆包/火山方舟生图超时: model=%s timeout=%ss",
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 豆包/火山方舟生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_gemini_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoint = self._gemini_generate_content_endpoint()
        if not endpoint:
            return "", "未配置 Gemini API 地址"
        try:
            import aiohttp

            prompt_parts: list[dict[str, Any]] = [{"text": prompt_text}]
            used_reference = False
            reference_value = ""
            if reference_image_path and os.path.exists(reference_image_path):
                reference_value = await self._reference_image_to_data_url(reference_image_path)
            elif re.match(r"^data:image/[a-z0-9.+-]+;base64,", str(reference_image_path or ""), flags=re.I):
                reference_value = str(reference_image_path or "").strip()
            if reference_value and "," in reference_value:
                header, encoded = reference_value.split(",", 1)
                mime_match = re.match(r"data:(image/[a-z0-9.+-]+);base64", header, flags=re.I)
                prompt_parts.append(
                    {
                        "inlineData": {
                            "mimeType": mime_match.group(1) if mime_match else "image/png",
                            "data": encoded,
                        }
                    }
                )
                used_reference = True
            size_hint = self._sanitize_external_image_size(image_size)
            payload = {
                "contents": [{"role": "user", "parts": prompt_parts}],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                },
            }
            if size_hint:
                payload["contents"][0]["parts"][0]["text"] = f"{prompt_text}\n\nTarget image size: {size_hint}."
            headers = {"Content-Type": "application/json"}
            headers.update(self._external_image_custom_headers())
            query = {}
            if not any(key.lower() in {"x-goog-api-key"} for key in headers):
                query["key"] = self.external_image_api_key
            else:
                query = {}
            if self.external_image_api_key and "key" not in query:
                headers.setdefault("x-goog-api-key", self.external_image_api_key)
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            logger.info(
                "[PrivateCompanion] Gemini 生图提交: endpoint=%s model=%s size=%s reference=%s prompt_preview=%s",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _single_line(size_hint, 40),
                used_reference,
                _single_line(prompt_text, 180),
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, headers=headers, params=query, json=payload) as response:
                    text = await response.text()
                    logger.info(
                        "[PrivateCompanion] Gemini 生图响应: status=%s chars=%s preview=%s",
                        response.status,
                        len(text or ""),
                        _single_line(text, 220),
                    )
                    if response.status >= 400:
                        return "", f"Gemini 生图 HTTP {response.status}: {_single_line(text, 180)}"
            data = self._extract_json_payload(text) if text else {}
            if not isinstance(data, dict):
                return "", "Gemini 生图返回格式无效"
            for encoded, mime_type in self._extract_gemini_inline_images(data):
                if encoded.startswith(("http://", "https://", "data:image")):
                    return await self._materialize_external_image_value(
                        encoded,
                        session_key=session_key,
                        success_note="ok；已使用本地人设参考图" if used_reference else "ok",
                    )
                ext = ".png"
                lowered_mime = str(mime_type or "").lower()
                if "jpeg" in lowered_mime or "jpg" in lowered_mime:
                    ext = ".jpg"
                elif "webp" in lowered_mime:
                    ext = ".webp"
                image_bytes = base64.b64decode(encoded)
                saved = await self._save_external_generated_image(image_bytes, session_key=session_key, ext=ext)
                note = "ok；已使用本地人设参考图" if used_reference else "ok"
                return saved, note if saved else "保存 Gemini 图片失败"
            for image_value in self._external_payload_image_values(data):
                return await self._materialize_external_image_value(
                    image_value,
                    session_key=session_key,
                    success_note="ok；已使用本地人设参考图" if used_reference else "ok",
                )
            message = self._external_payload_first_value(data, ("message", "error", "error_message", "finishReason", "finish_reason"))
            return "", _single_line(message or "Gemini 生图未返回图片内容", 180)
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(label="Gemini 生图接口")
            logger.info(
                "[PrivateCompanion] Gemini 生图超时: model=%s timeout=%ss",
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] Gemini 生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_external_photo_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        lock = getattr(self, "_external_image_api_runtime_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._external_image_api_runtime_lock = lock
        wait_started = time.monotonic()
        async with lock:
            waited_ms = int((time.monotonic() - wait_started) * 1000)
            if waited_ms > 500:
                logger.info(
                    "[PrivateCompanion] 在线图片 API 等待串行锁: session=%s waited=%sms",
                    _single_line(session_key, 80),
                    waited_ms,
                )
            image_path, note = await self._run_external_photo_generation_serial(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if waited_ms > 500:
                note = f"{note}；在线图片 API 排队等待 {waited_ms}ms"
            return image_path, note

    def _parse_custom_headers(self, raw: str) -> dict[str, str]:
        """Parse custom HTTP headers from multi-line 'Key: Value' text."""
        result: dict[str, str] = {}
        if not raw or not isinstance(raw, str):
            return result
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            idx = line.find(":")
            if idx <= 0:
                continue
            key = line[:idx].strip()
            value = line[idx + 1:].strip()
            if key:
                result[key] = value
        return result

    def _external_image_custom_headers(self) -> dict[str, str]:
        """Return parsed custom headers for the currently active (primary or backup) image API."""
        return self._parse_custom_headers(getattr(self, "external_image_api_custom_headers", ""))

    def _external_image_api_runtime_keys(self) -> tuple[str, ...]:
        return (
            "external_image_api_platform",
            "external_image_api_base_url",
            "external_image_api_key",
            "external_image_api_model",
            "external_image_api_size",
            "external_image_api_timeout_seconds",
            "external_image_api_custom_headers",
        )

    def _legacy_external_image_api_endpoint(self, *, backup: bool = False) -> dict[str, Any]:
        prefix = "backup_" if backup else ""
        endpoint = {
            "name": "备选在线 API" if backup else "主在线 API",
            "enabled": bool(getattr(self, "enable_backup_external_image_api", False)) if backup else True,
            "platform": getattr(self, f"{prefix}external_image_api_platform", "auto"),
            "base_url": getattr(self, f"{prefix}external_image_api_base_url", ""),
            "api_key": getattr(self, f"{prefix}external_image_api_key", ""),
            "model": getattr(self, f"{prefix}external_image_api_model", ""),
            "size": getattr(self, f"{prefix}external_image_api_size", "1024x1024"),
            "timeout_seconds": getattr(self, f"{prefix}external_image_api_timeout_seconds", 180),
            "custom_headers": getattr(self, f"{prefix}external_image_api_custom_headers", ""),
        }
        normalizer = getattr(self, "_normalize_external_image_api_endpoint", None)
        return normalizer(endpoint, index=1 if backup else 0) if callable(normalizer) else endpoint

    def _external_image_api_endpoint_label(self, endpoint: dict[str, Any], index: int = 0) -> str:
        name = _single_line(endpoint.get("name"), 60) if isinstance(endpoint, dict) else ""
        if name:
            return name
        model = _single_line(endpoint.get("model"), 60) if isinstance(endpoint, dict) else ""
        return f"在线 API #{index + 1}" + (f"({model})" if model else "")

    def _external_image_api_endpoint_signature(self, endpoint: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(endpoint.get("platform") or "auto").lower(),
            str(endpoint.get("base_url") or "").strip().rstrip("/"),
            str(endpoint.get("model") or "").strip(),
            str(endpoint.get("api_key") or "").strip()[:12],
        )

    def _external_image_api_endpoint_queue(
        self,
        *,
        include_incomplete: bool = False,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        normalizer = getattr(self, "_normalize_external_image_api_endpoints", None)
        configured = getattr(self, "external_image_api_endpoints", [])
        configured = normalizer(configured) if callable(normalizer) else configured
        raw_endpoints = list(configured or []) if isinstance(configured, list) else []
        if not raw_endpoints:
            raw_endpoints = [
                self._legacy_external_image_api_endpoint(backup=False),
                self._legacy_external_image_api_endpoint(backup=True),
            ]
        endpoints: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for endpoint in raw_endpoints[:12]:
            if not isinstance(endpoint, dict):
                continue
            normalized = normalizer([endpoint]) if callable(normalizer) else [endpoint]
            endpoint = normalized[0] if normalized else dict(endpoint)
            if not include_disabled and not bool(endpoint.get("enabled", True)):
                continue
            if not include_incomplete and self._external_image_api_endpoint_unavailable_note(endpoint):
                continue
            signature = self._external_image_api_endpoint_signature(endpoint)
            if signature in seen:
                continue
            seen.add(signature)
            endpoints.append(endpoint)
        return endpoints

    def _external_image_api_endpoint_unavailable_note(self, endpoint: dict[str, Any]) -> str:
        if not isinstance(endpoint, dict):
            return "invalid"
        if not bool(endpoint.get("enabled", True)):
            return "disabled"
        missing = []
        if not str(endpoint.get("base_url") or "").strip():
            missing.append("base_url")
        if not str(endpoint.get("api_key") or "").strip():
            missing.append("api_key")
        if not str(endpoint.get("model") or "").strip():
            missing.append("model")
        if missing:
            return "missing_" + ",".join(missing)
        checker = getattr(self, "_external_image_model_misconfiguration_note", None)
        if not callable(checker):
            return ""
        old_values = {key: getattr(self, key, None) for key in self._external_image_api_runtime_keys()}
        try:
            self._apply_external_image_api_endpoint_runtime(endpoint)
            note = checker()
            return _single_line(note, 160) if note else ""
        except Exception:
            return ""
        finally:
            for key, value in old_values.items():
                setattr(self, key, value)

    def _apply_external_image_api_endpoint_runtime(self, endpoint: dict[str, Any]) -> None:
        normalizer = getattr(self, "_normalize_external_image_api_platform", None)
        platform = endpoint.get("platform", "auto")
        setattr(
            self,
            "external_image_api_platform",
            normalizer(platform) if callable(normalizer) else str(platform or "auto").strip().lower(),
        )
        setattr(self, "external_image_api_base_url", str(endpoint.get("base_url") or "").strip())
        setattr(self, "external_image_api_key", str(endpoint.get("api_key") or "").strip())
        setattr(self, "external_image_api_model", str(endpoint.get("model") or "").strip())
        setattr(self, "external_image_api_size", str(endpoint.get("size") or "1024x1024").strip() or "1024x1024")
        setattr(self, "external_image_api_timeout_seconds", _safe_int(endpoint.get("timeout_seconds"), 180, 20, 600))
        setattr(self, "external_image_api_custom_headers", str(endpoint.get("custom_headers") or "").strip())

    async def _run_external_photo_generation_serial(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoints = self._external_image_api_endpoint_queue(include_incomplete=True)
        if not endpoints:
            return "", "在线图片 API 未配置完整"
        notes: list[str] = []
        for index, endpoint in enumerate(endpoints):
            label = self._external_image_api_endpoint_label(endpoint, index)
            unavailable = self._external_image_api_endpoint_unavailable_note(endpoint)
            if unavailable:
                note = f"{label}不可用：{unavailable}"
                notes.append(note)
                logger.info("[PrivateCompanion] 在线图片 API 端点跳过: endpoint=%s note=%s", label, _single_line(unavailable, 160))
                continue
            logger.info(
                "[PrivateCompanion] 尝试在线图片 API 端点: index=%s/%s name=%s platform=%s model=%s",
                index + 1,
                len(endpoints),
                _single_line(label, 80),
                _single_line(endpoint.get("platform"), 30) or "auto",
                _single_line(endpoint.get("model"), 80) or "-",
            )
            image_path, note = await self._run_external_photo_generation_with_endpoint(
                endpoint,
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if image_path:
                return image_path, f"{note}；已使用{label}"
            notes.append(f"{label}失败：{_single_line(note, 220)}")
        return "", "；".join(notes[-6:]) or "在线图片 API 未返回可用图片"

    async def _run_external_photo_generation_with_backup(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        return await self._run_external_photo_generation_with_endpoint(
            self._legacy_external_image_api_endpoint(backup=True),
            prompt_text,
            session_key=session_key,
            reference_image_path=reference_image_path,
            image_size=image_size,
        )

    async def _run_external_photo_generation_with_endpoint(
        self,
        endpoint: dict[str, Any],
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        old_values = {key: getattr(self, key, None) for key in self._external_image_api_runtime_keys()}
        try:
            self._apply_external_image_api_endpoint_runtime(endpoint)
            return await self._run_external_photo_generation_once(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
        finally:
            for key, value in old_values.items():
                setattr(self, key, value)

    async def _run_external_photo_generation_once(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str = "",
        image_size: str = "",
    ) -> tuple[str, str]:
        platform = self._resolved_external_image_api_platform()
        endpoint = self._external_image_endpoint()
        if platform == "bailian":
            endpoint = self._bailian_multimodal_endpoint() or self._bailian_api_root()
        elif platform == "modelscope":
            endpoint = self._modelscope_generation_endpoint()
        elif platform == "doubao":
            endpoint = self._doubao_generation_endpoint()
        elif platform == "gemini":
            endpoint = self._gemini_generate_content_endpoint()
        if not endpoint:
            return "", f"未配置{self._external_image_platform_label(platform)} API 地址"
        if not self.external_image_api_key:
            return "", f"未配置{self._external_image_platform_label(platform)} API Key"
        if not self.external_image_api_model:
            return "", f"未配置{self._external_image_platform_label(platform)}图片模型"
        model_note = self._external_image_model_misconfiguration_note()
        if model_note:
            return "", model_note
        reference_image_path = _single_line(reference_image_path, 260)
        if platform == "bailian":
            multimodal_first = bool(reference_image_path) or self._bailian_prefers_multimodal()
            bailian_note = ""
            if multimodal_first:
                image_path, note = await self._run_bailian_multimodal_photo_generation(
                    prompt_text,
                    session_key=session_key,
                    reference_image_path=reference_image_path,
                    image_size=image_size,
                )
                if image_path:
                    return image_path, note
                bailian_note = note
                logger.info(
                    "[PrivateCompanion] 百炼多模态生图失败,回退异步文生图: %s",
                    _single_line(note, 180),
                )
                if "超时" in str(note or ""):
                    return "", note
            image_path, note = await self._run_bailian_async_photo_generation(
                prompt_text,
                session_key=session_key,
                image_size=image_size,
            )
            if image_path:
                return image_path, note
            if bailian_note:
                return "", f"{note}；多模态回退原因：{_single_line(bailian_note, 120)}"
            return "", note
        if platform == "modelscope":
            if reference_image_path:
                return "", "魔搭社区文生图接口暂不支持参考图输入，请改用 OpenAI 兼容参考图接口或 ComfyUI images=1 工作流"
            return await self._run_modelscope_photo_generation(
                prompt_text,
                session_key=session_key,
                image_size=image_size,
            )
        if platform == "doubao":
            if reference_image_path:
                return "", "豆包/火山方舟文生图接口暂不支持参考图输入，请改用 Gemini、OpenAI 兼容参考图接口或 ComfyUI images=1 工作流"
            return await self._run_doubao_photo_generation(
                prompt_text,
                session_key=session_key,
                image_size=image_size,
            )
        if platform == "gemini":
            return await self._run_gemini_photo_generation(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
        if platform == "sensenova" and reference_image_path:
            return "", "SenseNova U1 Fast 官方接口不支持参考图输入，请使用纯文生图或切换其他参考图后端"
        if reference_image_path and os.path.exists(reference_image_path):
            logger.info(
                "[PrivateCompanion] 在线图片 API 尝试参考图接口: endpoint=%s model=%s size=%s reference=%s prompt_preview=%s",
                _single_line(self._external_image_endpoint("edits"), 160),
                _single_line(self.external_image_api_model, 80),
                self._sanitize_external_image_size(image_size),
                _single_line(reference_image_path, 160),
                _single_line(prompt_text, 180),
            )
            image_path, note = await self._run_external_photo_edit_generation(
                prompt_text,
                session_key=session_key,
                reference_image_path=reference_image_path,
                image_size=image_size,
            )
            if image_path:
                return image_path, note
            logger.info(
                "[PrivateCompanion] 在线图片 API 参考图生图失败,停止纯文回退: %s",
                _single_line(note, 180),
            )
            return "", f"参考图接口失败：{_single_line(note, 180)}"
        try:
            import aiohttp

            payload = build_openai_image_payload(
                model=self._sensenova_image_model() if platform == "sensenova" else self.external_image_api_model,
                platform=platform,
                prompt=prompt_text,
                size=self._sanitize_sensenova_image_size(image_size) if platform == "sensenova" else self._sanitize_external_image_size(image_size),
            )
            headers = {
                "Authorization": f"Bearer {self.external_image_api_key}",
                "Content-Type": "application/json",
            }
            headers.update(self._external_image_custom_headers())
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            endpoints = self._external_image_endpoint_candidates("generations") or [endpoint]
            last_error_note = ""
            data: dict[str, Any] | None = None
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for index, candidate_endpoint in enumerate(endpoints):
                    logger.info(
                        "[PrivateCompanion] 在线图片 API 生图提交: endpoint=%s model=%s size=%s prompt_chars=%s prompt_preview_chars=%s prompt_preview=%s",
                        _single_line(candidate_endpoint, 160),
                        _single_line(self.external_image_api_model, 80),
                        payload["size"],
                        len(str(prompt_text or "")),
                        180,
                        _single_line(prompt_text, 180),
                    )
                    async with session.post(candidate_endpoint, headers=headers, json=payload) as response:
                        text = await response.text()
                        logger.info(
                            "[PrivateCompanion] 在线图片 API 生图响应: endpoint=%s status=%s chars=%s preview=%s",
                            _single_line(candidate_endpoint, 160),
                            response.status,
                            len(text or ""),
                            _single_line(text, 220),
                        )
                        if response.status >= 400:
                            last_error_note = self._external_image_api_error_note(response.status, text, endpoint=candidate_endpoint)
                            if response.status == 404 and index + 1 < len(endpoints):
                                logger.info(
                                    "[PrivateCompanion] 在线图片 API 生图端点 404,尝试候选端点: failed=%s next=%s",
                                    _single_line(candidate_endpoint, 160),
                                    _single_line(endpoints[index + 1], 160),
                                )
                                continue
                            return "", last_error_note
                    data = self._extract_json_payload(text) if text else {}
                    break
            if data is None:
                return "", last_error_note or "在线图片 API 未返回数据"
            if not isinstance(data, dict):
                return "", "在线图片 API 返回格式无效"
            first = None
            items = data.get("data")
            if isinstance(items, list) and items:
                first = items[0]
            if not isinstance(first, dict):
                return "", "在线图片 API 未返回图片数据"
            b64 = str(first.get("b64_json") or "").strip()
            if b64:
                image_bytes = base64.b64decode(b64)
                path = await self._save_external_generated_image(
                    image_bytes,
                    session_key=session_key,
                    ext=".png",
                )
                logger.info(
                    "[PrivateCompanion] 在线图片 API 生图返回 base64: bytes=%s path=%s",
                    len(image_bytes),
                    _single_line(path, 160),
                )
                return path, "ok" if path else "保存在线图片失败"
            image_url = str(first.get("url") or "").strip()
            if image_url:
                logger.info("[PrivateCompanion] 在线图片 API 生图返回 URL: %s", _single_line(image_url, 180))
                return await self._download_external_image_url(
                    image_url,
                    session_key=session_key,
                )
            return "", "在线图片 API 未返回 url 或 b64_json"
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note()
            logger.info(
                "[PrivateCompanion] 在线图片 API 生图超时: endpoint=%s model=%s timeout=%ss",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 在线图片 API 生图失败: {e}", exc_info=True)
            return "", str(e)

    async def _run_external_photo_edit_generation(
        self,
        prompt_text: str,
        *,
        session_key: str,
        reference_image_path: str,
        image_size: str = "",
    ) -> tuple[str, str]:
        endpoint = self._external_image_endpoint("edits")
        if not endpoint:
            return "", "未配置在线图片 API 地址"
        path = Path(str(reference_image_path or ""))
        if not path.exists() or not path.is_file():
            return "", "参考图路径不可用"
        suffix = path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            return "", "参考图格式不支持"
        try:
            import aiohttp

            image_bytes = await asyncio.to_thread(path.read_bytes)
            content_type = "image/png"
            if suffix in {".jpg", ".jpeg"}:
                content_type = "image/jpeg"
            elif suffix == ".webp":
                content_type = "image/webp"

            policy = build_openai_image_payload(
                model=self.external_image_api_model,
                platform=self._resolved_external_image_api_platform(),
                prompt=prompt_text,
                size=self._sanitize_external_image_size(image_size),
            )
            def build_form() -> Any:
                # Keep the established multipart reference-image contract. NAI
                # gets a clean positive prompt; its multipart negative channel
                # is provider-specific and has not been verified here.
                form = aiohttp.FormData()
                form.add_field("model", str(policy["model"]))
                form.add_field("prompt", str(policy["prompt"]))
                form.add_field("size", str(policy["size"]))
                form.add_field("n", str(policy["n"]))
                form.add_field(
                    "image",
                    image_bytes,
                    filename=f"persona_reference{suffix}",
                    content_type=content_type,
                )
                return form

            headers = {"Authorization": f"Bearer {self.external_image_api_key}"}
            headers.update(self._external_image_custom_headers())
            timeout = aiohttp.ClientTimeout(total=float(self.external_image_api_timeout_seconds))
            endpoints = self._external_image_endpoint_candidates("edits") or [endpoint]
            last_error_note = ""
            data: dict[str, Any] | None = None
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for index, candidate_endpoint in enumerate(endpoints):
                    logger.info(
                        "[PrivateCompanion] 在线图片 API 参考图提交: endpoint=%s model=%s size=%s reference=%s bytes=%s prompt_preview=%s",
                        _single_line(candidate_endpoint, 160),
                        _single_line(self.external_image_api_model, 80),
                        self._sanitize_external_image_size(image_size),
                        _single_line(str(path), 160),
                        len(image_bytes),
                        _single_line(prompt_text, 180),
                    )
                    async with session.post(candidate_endpoint, headers=headers, data=build_form()) as response:
                        text = await response.text()
                        logger.info(
                            "[PrivateCompanion] 在线图片 API 参考图响应: endpoint=%s status=%s chars=%s preview=%s",
                            _single_line(candidate_endpoint, 160),
                            response.status,
                            len(text or ""),
                            _single_line(text, 220),
                        )
                        if response.status >= 400:
                            last_error_note = self._external_image_api_error_note(response.status, text, reference=True, endpoint=candidate_endpoint)
                            if response.status == 404 and index + 1 < len(endpoints):
                                logger.info(
                                    "[PrivateCompanion] 在线图片 API 参考图端点 404,尝试候选端点: failed=%s next=%s",
                                    _single_line(candidate_endpoint, 160),
                                    _single_line(endpoints[index + 1], 160),
                                )
                                continue
                            return "", last_error_note
                    data = self._extract_json_payload(text) if text else {}
                    break
            if data is None:
                return "", last_error_note or "参考图接口未返回数据"
            if not isinstance(data, dict):
                return "", "参考图接口返回格式无效"
            first = None
            items = data.get("data")
            if isinstance(items, list) and items:
                first = items[0]
            if not isinstance(first, dict):
                return "", "参考图接口未返回图片数据"
            b64 = str(first.get("b64_json") or "").strip()
            if b64:
                generated_bytes = base64.b64decode(b64)
                saved = await self._save_external_generated_image(
                    generated_bytes,
                    session_key=session_key,
                    ext=".png",
                )
                logger.info(
                    "[PrivateCompanion] 在线图片 API 参考图返回 base64: bytes=%s path=%s",
                    len(generated_bytes),
                    _single_line(saved, 160),
                )
                return saved, "ok；已使用本地人设参考图" if saved else "保存在线参考图生图失败"
            image_url = str(first.get("url") or "").strip()
            if image_url:
                logger.info("[PrivateCompanion] 在线图片 API 参考图返回 URL: %s", _single_line(image_url, 180))
                saved, note = await self._download_external_image_url(
                    image_url,
                    session_key=session_key,
                )
                return saved, ("ok；已使用本地人设参考图" if saved else note)
            return "", "参考图接口未返回 url 或 b64_json"
        except asyncio.TimeoutError:
            note = self._external_image_timeout_note(reference=True)
            logger.info(
                "[PrivateCompanion] 在线图片 API 参考图生图超时: endpoint=%s model=%s timeout=%ss reference=%s",
                _single_line(endpoint, 160),
                _single_line(self.external_image_api_model, 80),
                _safe_int(getattr(self, "external_image_api_timeout_seconds", 180), 180, 1),
                _single_line(str(path), 160),
            )
            return "", note
        except Exception as e:
            logger.warning(f"[PrivateCompanion] 在线图片 API 参考图生图失败: {e}", exc_info=True)
            return "", str(e)
