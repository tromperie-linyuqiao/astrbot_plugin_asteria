# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import math
import time
import re
import shutil
import base64
import hashlib
import mimetypes
import secrets
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from quart import request, send_file

from .constants import DEFAULT_DAILY_PLAN_ITEMS, PAGE_FONT_NAMES, PAGE_THEME_NAMES, _REASON_TEXT
from .config_migration import _ensure_config_parent_dir
from .helpers import _flat_get, _normalize_timezone_name, _safe_int, _set_into_config, _set_today_key_timezone, _strip_internal_message_blocks, _text_looks_garbled, _text_similarity, _today_key
from .page_api_qzone import PrivateCompanionPageApiQzoneMixin
from .page_api_users_groups import PrivateCompanionPageApiUsersGroupsMixin
from .planning import evaluate_daily_plan_quality, generate_daily_plan, generate_detail_enhancement
from .memo_notes import (
    apply_memo_note_action,
    memo_note_due_state,
    memo_note_sort_key,
    normalize_memo_note,
)

PLUGIN_NAME = "astrbot_plugin_private_companion"
PAGE_API_PREFIX = "/astrbot_plugin_virtual_body/page/pc"

# 拆分的 mixin(方法体自本文件逐字搬运; 路由注册仍统一留在下方 register_routes)
from . import page_api_images, page_api_life, page_api_summary
from .page_api_images import PrivateCompanionPageApiImagesMixin
from .page_api_proactive import PrivateCompanionPageApiProactiveMixin
from .page_api_trouble import PrivateCompanionPageApiTroubleMixin
from .page_api_books import PrivateCompanionPageApiBooksMixin
from .page_api_life import PrivateCompanionPageApiLifeMixin
from .page_api_roleplay import PrivateCompanionPageApiRoleplayMixin
from .page_api_summary import PrivateCompanionPageApiSummaryMixin


class PrivateCompanionPageApi(
    PrivateCompanionPageApiQzoneMixin,
    PrivateCompanionPageApiUsersGroupsMixin,
    PrivateCompanionPageApiImagesMixin,
    PrivateCompanionPageApiProactiveMixin,
    PrivateCompanionPageApiTroubleMixin,
    PrivateCompanionPageApiBooksMixin,
    PrivateCompanionPageApiLifeMixin,
    PrivateCompanionPageApiRoleplayMixin,
    PrivateCompanionPageApiSummaryMixin,
):
    """AstrBot 官方插件拓展页面 API。"""

    PERCENT_PROBABILITY_KEYS = {
        "group_repeat_follow_probability",
        "group_repeat_interrupt_probability",
        "group_repeat_interrupt_probability_step",
        "group_wakeup_interest_probability",
        "group_wakeup_topic_interest_max_boost",
        "group_wakeup_debounce_pending_penalty",
        "tts_trigger_probability",
        "auto_voice_probability",
        "main_user_mention_voice_probability",
        "rest_reply_probability",
        "proactive_photo_text_probability",
        "proactive_share_probability",
    }
    INHERIT_PERCENT_PROBABILITY_KEYS = {
        "tts_private_trigger_probability",
        "tts_group_trigger_probability",
        "main_user_voice_probability",
    }
    FRACTIONAL_PERCENT_SETTING_KEYS = {
        "bilibili_share_probability",
        "news_share_probability",
        "external_event_self_link_probability",
        "web_exploration_share_probability",
        "qzone_life_publish_probability",
        "qzone_generated_image_probability",
        "qzone_emotional_vent_probability",
        "proactive_review_hard_risk_threshold",
        "proactive_review_low_score_threshold",
        "proactive_review_pressure_threshold",
        "smart_silence_min_confidence",
        "private_reading_share_probability",
        "private_reading_ask_probability",
        "creative_inspiration_probability",
        "creative_share_probability",
        "skill_growth_schedule_influence_strength",
    }
    PERSONALITY_AUTO_TUNE_KEYS = {
        "proactive_intensity_preset",
        "max_daily_messages",
        "idle_minutes",
        "min_interval_minutes",
        "proactive_persona_judge_send_threshold",
        "proactive_review_strength",
    }

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self._schema_key_index_cache: dict[str, Any] | None = None

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        routes = [
            ("/overview", self.get_overview, ["GET"], "Private Companion Page overview"),
            ("/expression-library", self.get_expression_library, ["GET"], "Private Companion Page expression library"),
            ("/expression-library/update", self.update_expression_library, ["POST"], "Private Companion Page update expression library"),
            ("/users", self.list_users, ["GET"], "Private Companion Page users"),
            ("/user", self.get_user, ["GET"], "Private Companion Page user detail"),
            ("/user/update", self.update_user, ["POST"], "Private Companion Page update user"),
            ("/user/delete", self.delete_user, ["POST"], "Private Companion Page delete user"),
            ("/groups", self.list_groups, ["GET"], "Private Companion Page groups"),
            ("/group", self.get_group, ["GET"], "Private Companion Page group detail"),
            ("/group/update", self.update_group, ["POST"], "Private Companion Page update group"),
            ("/group/delete", self.delete_group, ["POST"], "Private Companion Page delete group"),
            ("/group/slang/update", self.update_group_slang, ["POST"], "Private Companion Page update group slang"),
            ("/settings/update", self.update_settings, ["POST"], "Private Companion Page update settings"),
            ("/settings/swap_image_api", self.swap_image_api_settings, ["POST"], "Private Companion Page swap image API settings"),
            ("/config/export", self.export_migration_config, ["GET"], "Private Companion Page export migration config"),
            ("/config/backups", self.list_migration_backups, ["GET"], "Private Companion Page list migration backups"),
            ("/config/restore", self.restore_migration_backup, ["POST"], "Private Companion Page restore migration backup"),
            ("/config/import/preview", self.preview_migration_config_import, ["POST"], "Private Companion Page preview migration config import"),
            ("/config/import/apply", self.apply_migration_config_import, ["POST"], "Private Companion Page apply migration config import"),
            ("/proactive_only/unlock", self.update_proactive_only_unlock, ["POST"], "Private Companion Page proactive-only temporary unlock"),
            ("/proactive/candidate/delete", self.delete_proactive_candidate, ["POST"], "Private Companion Page delete proactive candidate"),
            ("/proactive/candidate/prune", self.prune_proactive_candidates, ["POST"], "Private Companion Page prune proactive candidates"),
            ("/diagnostics", self.get_diagnostics, ["GET"], "Private Companion Page diagnostics"),
            ("/troubleshooting", self.get_troubleshooting, ["GET"], "Private Companion Page troubleshooting"),
            ("/troubleshooting/warnings/update", self.update_troubleshooting_warning_suppression, ["POST"], "Private Companion Page update troubleshooting warning suppression"),
            ("/troubleshooting/test", self.run_troubleshooting_test, ["POST"], "Private Companion Page troubleshooting test"),
            ("/token/stats", self.get_token_stats, ["GET"], "Private Companion Page token stats"),
            ("/token/reset", self.reset_token_stats, ["POST"], "Private Companion Page reset token stats"),
            ("/image_cache/list", self.list_image_cache, ["GET"], "Private Companion Page image cache list"),
            ("/image_cache/preview", self.get_image_cache_preview, ["GET"], "Private Companion Page image cache preview"),
            ("/image_cache/update", self.update_image_cache_item, ["POST"], "Private Companion Page update image cache item"),
            ("/image_cache/delete", self.delete_image_cache_item, ["POST"], "Private Companion Page delete image cache item"),
            ("/daily_outfit/image", self.get_daily_outfit_image, ["GET"], "Private Companion Page daily outfit image"),
            ("/daily_outfit/image_data", self.get_daily_outfit_image_data, ["GET"], "Private Companion Page daily outfit image data"),
            ("/bookshelf/unlock", self.unlock_bookshelf, ["POST"], "Private Companion Page unlock bookshelf"),
            ("/bookshelf/image", self.get_bookshelf_image, ["GET"], "Private Companion Page bookshelf image"),
            ("/bookshelf/image_data", self.get_bookshelf_image_data, ["GET"], "Private Companion Page bookshelf image data"),
            ("/bookshelf/delete", self.delete_bookshelf_item, ["POST"], "Private Companion Page delete bookshelf item"),
            ("/bookshelf/rate", self.rate_bookshelf_item, ["POST"], "Private Companion Page rate bookshelf item"),
            ("/bookshelf/tags", self.update_bookshelf_item_tags, ["POST"], "Private Companion Page update bookshelf item tags"),
            ("/bookshelf/comments/update", self.update_bookshelf_item_comments, ["POST"], "Private Companion Page update bookshelf item comments"),
            ("/bookshelf/reading_state", self.update_bookshelf_reading_state, ["POST"], "Private Companion Page update bookshelf reading state"),
            ("/memo/list", self.list_memo_notes, ["GET"], "Private Companion Page list memo notes"),
            ("/memo/update", self.update_memo_note, ["POST"], "Private Companion Page update memo note"),
            ("/qzone/status", self.get_qzone_status, ["GET"], "Private Companion Page qzone status"),
            ("/qzone/health", self.get_qzone_status, ["GET"], "Private Companion Page qzone status alias"),
            ("/qzone/summary", self.get_qzone_status, ["GET"], "Private Companion Page qzone status alias"),
            ("/qzone/state", self.get_qzone_status, ["GET"], "Private Companion Page qzone status alias"),
            ("/qzone/feed", self.get_qzone_feed, ["GET"], "Private Companion Page qzone feed"),
            ("/qzone/feeds", self.get_qzone_feed, ["GET"], "Private Companion Page qzone feed alias"),
            ("/qzone/list", self.get_qzone_feed, ["GET"], "Private Companion Page qzone feed alias"),
            ("/qzone/detail", self.get_qzone_detail, ["GET"], "Private Companion Page qzone detail"),
            ("/qzone/post", self.get_qzone_detail, ["GET"], "Private Companion Page qzone detail alias"),
            ("/qzone/item", self.get_qzone_detail, ["GET"], "Private Companion Page qzone detail alias"),
            ("/qzone/refresh_cookies", self.refresh_qzone_cookies, ["POST"], "Private Companion Page qzone refresh cookies"),
            ("/qzone/refresh-cookies", self.refresh_qzone_cookies, ["POST"], "Private Companion Page qzone refresh cookies alias"),
            ("/qzone/cookies/refresh", self.refresh_qzone_cookies, ["POST"], "Private Companion Page qzone refresh cookies alias"),
            ("/qzone/cookie/refresh", self.refresh_qzone_cookies, ["POST"], "Private Companion Page qzone refresh cookies alias"),
            ("/qzone/refresh", self.refresh_qzone_cookies, ["POST"], "Private Companion Page qzone refresh cookies alias"),
            ("/qzone/publish", self.publish_qzone_post, ["POST"], "Private Companion Page qzone publish"),
            ("/qzone/post/publish", self.publish_qzone_post, ["POST"], "Private Companion Page qzone publish alias"),
            ("/qzone/post", self.publish_qzone_post, ["POST"], "Private Companion Page qzone publish alias"),
            ("/qzone/like", self.like_qzone_post, ["POST"], "Private Companion Page qzone like"),
            ("/qzone/post/like", self.like_qzone_post, ["POST"], "Private Companion Page qzone like alias"),
            ("/qzone/comment", self.comment_qzone_post, ["POST"], "Private Companion Page qzone comment"),
            ("/qzone/post/comment", self.comment_qzone_post, ["POST"], "Private Companion Page qzone comment alias"),
            ("/qzone/delete", self.delete_qzone_post, ["POST"], "Private Companion Page qzone delete"),
            ("/qzone/post/delete", self.delete_qzone_post, ["POST"], "Private Companion Page qzone delete alias"),
            ("/creative/project", self.get_creative_project, ["GET"], "Private Companion Page creative project detail"),
            ("/creative/project/cover", self.get_creative_project_cover, ["GET"], "Private Companion Page creative project cover"),
            ("/creative/project/cover_data", self.get_creative_project_cover_data, ["GET"], "Private Companion Page creative project cover data"),
            ("/creative/project/update", self.update_creative_project, ["POST"], "Private Companion Page update creative project"),
            ("/creative/project/chunk/update", self.update_creative_chunk, ["POST"], "Private Companion Page update creative chunk"),
            ("/creative/project/outline/update", self.update_creative_outline, ["POST"], "Private Companion Page update creative outline"),
            ("/creative/project/characters/update", self.update_creative_characters, ["POST"], "Private Companion Page update creative characters"),
            ("/creative/project/reanalyze", self.reanalyze_creative_project, ["POST"], "Private Companion Page reanalyze creative project"),
            ("/creative/project/rebuild_memory", self.rebuild_creative_memory, ["POST"], "Private Companion Page rebuild creative memory"),
            ("/creative/project/delete", self.delete_creative_project, ["POST"], "Private Companion Page delete creative project"),
            ("/worldbook/import", self.import_worldbook, ["POST"], "Private Companion Page import worldbook"),
            ("/worldbook/member/livingmemory", self.get_worldbook_member_livingmemory, ["GET"], "Private Companion Page worldbook member LivingMemory"),
            ("/worldbook/member/update", self.update_worldbook_member, ["POST"], "Private Companion Page update worldbook member"),
            ("/worldbook/observations/clear", self.clear_worldbook_pending_observations, ["POST"], "Private Companion Page clear worldbook pending observations"),
            ("/worldbook/group/update", self.update_worldbook_group, ["POST"], "Private Companion Page update worldbook group"),
            ("/skill/update", self.update_skill_growth, ["POST"], "Private Companion Page update skill growth"),
            ("/personal_goal/update", self.update_personal_goal, ["POST"], "Private Companion Page update personal goal"),
            ("/food_menu/update", self.update_food_menu, ["POST"], "Private Companion Page update food menu"),
            ("/food_menu/bulk_update", self.bulk_update_food_menu, ["POST"], "Private Companion Page bulk update food menu"),
            ("/food_menu/bulk_delete", self.bulk_delete_food_menu, ["POST"], "Private Companion Page bulk delete food menu"),
            ("/external_ability/update", self.update_external_ability, ["POST"], "Private Companion Page update external proactive ability"),
            ("/setup/apply", self.apply_setup_guide, ["POST"], "Private Companion Page apply first setup guide"),
            ("/setup/daily/run", self.run_setup_daily_generation, ["POST"], "Private Companion Page setup guide daily generation"),
            ("/daily/detail/regenerate", self.regenerate_daily_detail_segment, ["POST"], "Private Companion Page regenerate one daily detail segment"),
            ("/roleplay/personas", self.list_roleplay_personas, ["GET"], "Private Companion Page roleplay personas"),
            ("/roleplay/draft_from_persona", self.generate_roleplay_draft_from_persona, ["POST"], "Private Companion Page roleplay draft from persona"),
            ("/roleplay/standardize_persona", self.standardize_persona_from_questionnaire, ["POST"], "Private Companion Page roleplay persona standardization"),
            ("/roleplay/persona_style_scenarios", self.generate_persona_style_scenarios, ["POST"], "Private Companion Page roleplay persona style scenarios"),
            ("/roleplay/persona_style_scenario_retry", self.retry_persona_style_scenario, ["POST"], "Private Companion Page roleplay persona style scenario retry"),
            ("/roleplay/persona_style_summary", self.generate_persona_style_summary, ["POST"], "Private Companion Page roleplay persona style summary"),
            ("/preset/apply", self.apply_preset, ["POST"], "Private Companion Page apply preset"),
            ("/providers/available", self.list_available_providers, ["GET"], "Private Companion Page available providers"),
            ("/provider/test", self.test_provider, ["POST"], "Private Companion Page test provider"),
        ]
        for path, handler, methods, desc in routes:
            register(f"{PAGE_API_PREFIX}{path}", handler, methods, desc)

    async def get_overview(self) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            async with self.plugin._data_lock:
                refresher = getattr(self.plugin, "_refresh_sleep_runtime_state", None)
                if callable(refresher):
                    refresher()
                schedule_content_changed = False
                plan_sanitizer = getattr(self.plugin, "_sanitize_daily_plan_inplace", None)
                plan = self.plugin._native_daily_plan_view()
                if callable(plan_sanitizer) and isinstance(plan, dict) and plan_sanitizer(plan):
                    schedule_content_changed = True
                if isinstance(plan, dict) and isinstance(plan.get("items"), list) and not isinstance(plan.get("quality"), dict):
                    plan["quality"] = evaluate_daily_plan_quality(self.plugin, plan.get("items"))
                    schedule_content_changed = True
                detail_sanitizer = getattr(self.plugin, "_sanitize_detail_enhanced_segments_inplace", None)
                enhanced = self.plugin.data.get("detail_enhanced_segments")
                if callable(detail_sanitizer) and isinstance(enhanced, dict) and detail_sanitizer(enhanced):
                    schedule_content_changed = True
                story_sanitizer = getattr(self.plugin, "_sanitize_story_plan_social_facts_inplace", None)
                story = self.plugin.data.get("daily_story_plan")
                if callable(story_sanitizer) and isinstance(story, dict) and story_sanitizer(story):
                    schedule_content_changed = True
                expression_profile_getter = getattr(self.plugin, "_expression_voice_profile", None)
                if callable(expression_profile_getter):
                    expression_profile_getter()
                if schedule_content_changed:
                    self.plugin._save_data_sync()
                data = self._overview_data_snapshot_locked(self.plugin.data)
                token_stats = self._token_overview_payload(
                    self.plugin.data.get("token_usage", {}),
                    self.plugin.data.get("balance_awareness", {}),
                )
            users = data.get("users") if isinstance(data.get("users"), dict) else {}
            groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
            enabled_users = sum(1 for item in users.values() if isinstance(item, dict) and item.get("enabled", True))
            visible_groups = {
                str(group_id): group
                for group_id, group in groups.items()
                if isinstance(group, dict) and not self._looks_like_member_shadow_group(str(group_id), group)
            }
            enabled_groups = sum(1 for item in visible_groups.values() if isinstance(item, dict) and item.get("enabled", True))
            payload = {
                "plugin": {
                    "enabled": bool(getattr(self.plugin, "enabled", False)),
                    "bot_name": getattr(self.plugin, "bot_name", ""),
                    "data_file": getattr(self.plugin, "data_file", ""),
                    "storage_backend": getattr(self.plugin, "storage_backend", "json"),
                    "storage_sqlite_path": getattr(
                        self.plugin,
                        "storage_sqlite_effective_path",
                        getattr(self.plugin, "storage_sqlite_path", ""),
                    ),
                    "enable_store_control_tag_sanitization": bool(
                        getattr(self.plugin, "enable_store_control_tag_sanitization", True)
                    ),
                    "data_version": data.get("version"),
                },
                "private": {
                    "user_count": len(users),
                    "enabled_user_count": enabled_users,
                    "require_opt_in": bool(getattr(self.plugin, "require_private_opt_in", True)),
                    "admin_ids": list(self.plugin._configured_admin_ids()) if hasattr(self.plugin, "_configured_admin_ids") else [],
                    "target_user_ids": list(self.plugin._configured_target_ids()) if hasattr(self.plugin, "_configured_target_ids") else [],
                    "relationship_owner_ids": list(self.plugin._relationship_owner_user_ids()) if hasattr(self.plugin, "_relationship_owner_user_ids") else [],
                    "max_daily_messages": getattr(self.plugin, "max_daily_messages", 0),
                    "idle_minutes": getattr(self.plugin, "idle_minutes", 0),
                    "min_interval_minutes": getattr(self.plugin, "min_interval_minutes", 0),
                },
                "group": {
                    "enabled": bool(getattr(self.plugin, "enable_group_companion", False)),
                    "group_count": len(visible_groups),
                    "enabled_group_count": enabled_groups,
                    "shadow_group_count": max(0, len(groups) - len(visible_groups)),
                    "access_mode": getattr(self.plugin, "group_access_mode", "whitelist"),
                    "whitelist": self.plugin._configured_group_ids(),
                    "blacklist": self.plugin._configured_group_blacklist_ids(),
                    "interjection_enabled": bool(getattr(self.plugin, "enable_group_interjection", False)),
                    "repeat_follow_enabled": bool(getattr(self.plugin, "enable_group_repeat_follow", False)),
                },
                "features": self._feature_flags(),
                "proactive_intensity": self._proactive_intensity_summary(),
                "proactive_only": self._proactive_only_mode_snapshot(),
                "proactive_chat": self._proactive_chat_summary(data),
                "expression_scope": self._expression_learning_scope_summary(data),
                "providers": self._provider_settings(),
                "settings": self._runtime_settings(),
                "deepseek_peak_routing": self._deepseek_peak_routing_summary(),
                "cache": self._cache_summary(data),
                "livingmemory": self._livingmemory_summary(),
                "screen_companion": self._screen_companion_summary(data),
                "knowledge": self.plugin._roleplay_knowledge_summary(),
                "worldbook": self._worldbook_summary(data),
                "proactive_candidates": self._proactive_candidate_summary(data),
                "proactive_tasks": self._proactive_task_summary(data),
                "message_debounce": self._message_debounce_summary(data),
                "bilibili": self._bilibili_summary(data),
                "news": self._news_summary(data),
                "web_exploration": self._web_exploration_summary(data),
                "qzone": self._qzone_summary(data),
                "private_reading": self._jm_cosmos_summary(data),
                "creative": self._creative_summary(data),
                "bookshelf": await self._bookshelf_summary(data, unlocked=False),
                "skill_growth": self._skill_growth_summary(data),
                "personal_goals": self._personal_goal_summary(data),
                "food_menu": self._food_menu_summary(data),
                "external_abilities": self._external_ability_summary(data),
                "life_observation": self._life_observation_summary(data),
                "daily_state": self._daily_state_summary(data.get("daily_state")),
                "daily_timeline": self._daily_timeline_summary(data),
                "daily_outfit": self._daily_outfit_summary(data),
                "token_stats": token_stats,
            }
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if elapsed_ms > 1200:
                logger.warning(
                    "[PrivateCompanionPage] 总览接口耗时较高: elapsed=%sms users=%s groups=%s",
                    elapsed_ms,
                    len(users),
                    len(visible_groups),
                )
            return self._ok(payload)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取总览失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _token_overview_payload(self, usage: Any, balance_state: Any = None) -> dict[str, Any]:
        if not isinstance(usage, dict):
            usage = {}
        today_key = _today_key()
        totals = self._token_bucket(usage.get("totals"))
        today_bucket = usage.get("by_day", {}).get(today_key, {}) if isinstance(usage.get("by_day"), dict) else {}
        today_total_tokens = self._int(today_bucket.get("total_tokens")) if isinstance(today_bucket, dict) else 0
        exempt_by_day = usage.get("budget_exempt_by_day") if isinstance(usage.get("budget_exempt_by_day"), dict) else {}
        today_exempt_bucket = exempt_by_day.get(today_key, {}) if isinstance(exempt_by_day, dict) else {}
        today_exempt_tokens = self._int(today_exempt_bucket.get("total_tokens")) if isinstance(today_exempt_bucket, dict) else 0
        if today_exempt_tokens <= 0:
            by_day_task = usage.get("by_day_task") if isinstance(usage.get("by_day_task"), dict) else {}
            today_tasks = by_day_task.get(today_key, {}) if isinstance(by_day_task, dict) else {}
            if isinstance(today_tasks, dict):
                is_exempt_task = getattr(self.plugin, "_is_llm_budget_exempt_task", None)
                today_exempt_tokens = sum(
                    self._int(bucket.get("total_tokens"))
                    for task, bucket in today_tasks.items()
                    if isinstance(bucket, dict)
                    and (
                        (callable(is_exempt_task) and is_exempt_task(task))
                        or (not callable(is_exempt_task) and str(task) in {"proactive_framework", "voice_framework"})
                    )
                )
        today_tokens = max(0, today_total_tokens - today_exempt_tokens)
        daily_limit = self._int(getattr(self.plugin, "daily_token_limit", 0))
        soft_limit = self._int(getattr(self.plugin, "daily_token_soft_limit", 0))
        soft_enabled = bool(getattr(self.plugin, "enable_daily_token_soft_limit", True))
        budget_skips = usage.get("budget_skips", {}) if isinstance(usage.get("budget_skips"), dict) else {}
        today_skips = budget_skips.get(today_key, {}) if isinstance(budget_skips, dict) else {}
        budget = {
            "day": today_key,
            "limit": daily_limit,
            "soft_limit": soft_limit,
            "soft_enabled": soft_enabled,
            "soft_active": bool(soft_enabled and soft_limit > 0 and today_tokens >= soft_limit),
            "used": today_tokens,
            "total_used": today_total_tokens,
            "exempt_used": today_exempt_tokens,
            "remaining": max(0, daily_limit - today_tokens) if daily_limit > 0 else None,
            "soft_remaining": max(0, soft_limit - today_tokens) if soft_enabled and soft_limit > 0 else None,
            "ratio": round(today_tokens / daily_limit, 4) if daily_limit > 0 else 0,
            "soft_ratio": round(today_tokens / soft_limit, 4) if soft_enabled and soft_limit > 0 else 0,
            "exceeded": bool(daily_limit > 0 and today_tokens >= daily_limit),
            "deferred_calls": (
                self._int(today_skips.get("daily_token_soft_limit_deferred"))
                + self._int(today_skips.get("maintenance_token_saver_deferred"))
            )
            if isinstance(today_skips, dict)
            else 0,
            "skipped_calls": self._int(today_skips.get("count")) if isinstance(today_skips, dict) else 0,
        }
        return {
            "updated_at": self._single_line(usage.get("updated_at"), 24),
            "totals": totals,
            "budget": budget,
            "balance": self._balance_status_payload(balance_state),
            "memory_plugin": self._token_memory_plugin_payload(self._memory_plugin_token_usage_raw()),
            "partial": True,
        }

    def _overview_data_snapshot_locked(self, raw_data: Any) -> dict[str, Any]:
        """Build a light read-only snapshot for the dashboard.

        The full data store can contain large image/news/bookshelf/history blobs. The
        overview only needs recent slices and counters, so avoid deepcopying the
        entire store while holding the data lock.
        """
        if not isinstance(raw_data, dict):
            return {}

        def shallow_dict(value: Any) -> dict[str, Any]:
            return dict(value) if isinstance(value, dict) else {}

        def list_tail(value: Any, limit: int) -> list[Any]:
            if not isinstance(value, list):
                return []
            if limit <= 0:
                return []
            return list(value[-limit:])

        scalar_user_keys = (
            "enabled",
            "manual_enabled",
            "manual_disabled",
            "nickname",
            "style",
            "umo",
            "relationship_role",
            "last_seen",
            "last_sent",
            "proactive_chat_bridge_last_sent_at",
            "sent_today",
            "sent_day",
            "last_proactive_skip_at",
            "last_proactive_skip_reason",
            "last_proactive_skip_prefix",
            "proactive_daily_limit",
            "proactive_idle_minutes",
            "proactive_min_interval_minutes",
            "photo_daily_limit",
            "screen_peek_daily_limit",
            "poke_daily_limit",
            "proactive_boundary_note",
            "inbound_count",
            "reply_count",
            "proactive_sent_count",
            "relationship_score",
            "planned_proactive_reason",
            "planned_proactive_action",
            "planned_proactive_source",
            "planned_proactive_topic",
            "planned_proactive_motive",
            "planned_proactive_impulse_id",
            "planned_candidate_id",
            "planned_proactive_semantic_kind",
            "planned_proactive_anchor_type",
            "planned_proactive_semantic_score",
            "planned_proactive_semantic_note",
            "planned_proactive_window_start_at",
            "planned_proactive_best_until_at",
            "planned_proactive_expire_at",
            "planned_proactive_model_judge_at",
            "next_proactive_at",
            "proactive_sending",
            "last_proactive_hesitation_at",
            "last_proactive_hesitation_note",
        )

        def user_snapshot(value: Any) -> dict[str, Any]:
            if not isinstance(value, dict):
                return {}
            snapshot = {key: value.get(key) for key in scalar_user_keys if key in value}
            for key in (
                "relationship_state",
                "persona_relationship",
                "llm_timer_event",
                "planned_proactive_model_judge_result",
                "proactive_afterglow",
            ):
                raw = value.get(key)
                if isinstance(raw, dict):
                    snapshot[key] = dict(raw)
            aliases = value.get("alias_user_ids")
            if isinstance(aliases, list):
                snapshot["alias_user_ids"] = list(aliases[:8])
            hesitations = value.get("recent_proactive_hesitations")
            if isinstance(hesitations, list):
                snapshot["recent_proactive_hesitations"] = [
                    dict(item) for item in hesitations[-3:] if isinstance(item, dict)
                ]
            return snapshot

        data: dict[str, Any] = {
            "version": raw_data.get("version"),
            "users": {str(key): user_snapshot(value) for key, value in raw_data.get("users", {}).items() if isinstance(value, dict)}
            if isinstance(raw_data.get("users"), dict)
            else {},
            "groups": {
                str(key): {
                    "enabled": bool(value.get("enabled", True)),
                    "name": value.get("name") or value.get("group_name") or "",
                }
                for key, value in raw_data.get("groups", {}).items()
                if isinstance(value, dict)
            }
            if isinstance(raw_data.get("groups"), dict)
            else {},
        }

        for key in (
            "daily_state",
            "daily_plan",
            "daily_story_plan",
            "daily_dream",
            "daily_outfit_photo",
            "detail_enhanced_segments",
            "qq_presence_state",
            "screen_diary_context",
            "worldbook_import_state",
            "worldbook_group_profiles",
            "qzone_integration",
            "jm_cosmos_integration",
            "private_reading_state",
            "skill_growth",
            "personal_goal_state",
            "food_menu",
            "external_proactive_abilities",
            "proactive_runtime",
            "message_debounce",
            "smart_message_debounce",
            "expression_voice_profile",
        ):
            value = raw_data.get(key)
            if isinstance(value, dict):
                data[key] = dict(value)
            elif value is not None:
                data[key] = value

        for key, limit in (
            ("proactive_candidate_pool", 240),
            ("proactive_audit_log", 120),
            ("bot_diaries", 8),
            ("dream_fragments", 40),
            ("schedule_adjustments", 24),
            ("bookshelf_items", 60),
            ("creative_projects", 24),
            ("personal_goals", 80),
            ("external_event_pool", 80),
        ):
            data[key] = list_tail(raw_data.get(key), limit)

        image_cache = raw_data.get("private_image_vision_cache")
        data["private_image_vision_cache_count"] = len(image_cache) if isinstance(image_cache, dict) else 0
        data["private_image_vision_cache"] = {}

        profiles = raw_data.get("worldbook_member_profiles")
        if isinstance(profiles, dict):
            profile_items = [(str(key), value) for key, value in profiles.items() if isinstance(value, dict)]
            data["worldbook_member_profile_count"] = len(profile_items)
            data["worldbook_enabled_member_profile_count"] = sum(1 for _, value in profile_items if bool(value.get("enabled", True)))
            data["worldbook_pending_observation_total"] = sum(
                len(value.get("pending_observations"))
                for _, value in profile_items
                if isinstance(value.get("pending_observations"), list)
            )
            data["worldbook_member_profiles"] = {key: value for key, value in profile_items[:160]}
        else:
            data["worldbook_member_profile_count"] = 0
            data["worldbook_enabled_member_profile_count"] = 0
            data["worldbook_pending_observation_total"] = 0
            data["worldbook_member_profiles"] = {}
        worldbook_groups = raw_data.get("worldbook_group_profiles")
        if isinstance(worldbook_groups, dict):
            group_items = [(str(key), value) for key, value in worldbook_groups.items() if isinstance(value, dict)]
            data["worldbook_group_profile_count"] = len(group_items)
            data["worldbook_group_profiles"] = {key: value for key, value in group_items[:120]}
        else:
            data["worldbook_group_profile_count"] = 0
            data["worldbook_group_profiles"] = {}
        entries = raw_data.get("worldbook_entries")
        data["worldbook_entry_count"] = len(entries) if isinstance(entries, list) else 0
        data["worldbook_entries"] = list_tail(entries, 300) if isinstance(entries, list) else []

        news_state = shallow_dict(raw_data.get("news_integration"))
        if news_state:
            news_state["latest_items"] = list_tail(news_state.get("latest_items"), 12)
            news_state["digests"] = list_tail(news_state.get("digests"), 40)
            ai_daily = shallow_dict(news_state.get("ai_daily"))
            if ai_daily:
                ai_digest = shallow_dict(ai_daily.get("last_digest"))
                if ai_digest:
                    ai_digest["items"] = list_tail(ai_digest.get("items"), 3)
                    ai_daily["last_digest"] = ai_digest
                news_state["ai_daily"] = ai_daily
            data["news_integration"] = news_state

        web_state = shallow_dict(raw_data.get("web_exploration"))
        if web_state:
            web_state["notes"] = list_tail(web_state.get("notes"), 40)
            web_state["latest_results"] = list_tail(web_state.get("latest_results"), 8)
            data["web_exploration"] = web_state

        bilibili_state = shallow_dict(raw_data.get("bilibili_integration"))
        if bilibili_state:
            data["bilibili_integration"] = bilibili_state

        return data

    def _daily_outfit_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        item = data.get("daily_outfit_photo") if isinstance(data.get("daily_outfit_photo"), dict) else {}
        path = self._single_line(item.get("path"), 300)
        exists = False
        if path:
            try:
                exists = Path(path).exists() and Path(path).is_file()
            except Exception:
                exists = False
        date_key = self._single_line(item.get("date"), 20)
        image_query = f"?date={quote(date_key)}&ts={self._single_line(item.get('generated_at'), 40)}" if exists else ""
        return {
            "enabled": bool(getattr(self.plugin, "enable_daily_outfit_photo", False)),
            "date": date_key,
            "available": bool(exists),
            "path": path if exists else "",
            "image_url": f"/daily_outfit/image{image_query}" if exists else "",
            "image_data_url": f"/daily_outfit/image_data{image_query}" if exists else "",
            "backend": self._single_line(item.get("backend"), 80),
            "error": self._single_line(item.get("error"), 220),
            "generated_at": self.plugin._format_timestamp_elapsed(item.get("generated_at", 0)) if item else "",
            "retry_count": int(item.get("retry_count", 0) or 0),
            "retry_max": 5,
        }

    def _daily_outfit_image_path(self) -> Path | None:
        data = getattr(self.plugin, "data", {}) if isinstance(getattr(self.plugin, "data", {}), dict) else {}
        item = data.get("daily_outfit_photo") if isinstance(data.get("daily_outfit_photo"), dict) else {}
        path_text = self._single_line(item.get("path"), 500)
        if not path_text:
            return None
        try:
            path = Path(path_text).resolve()
        except Exception:
            return None
        if not path.exists() or not path.is_file():
            return None
        return path

    async def get_daily_outfit_image(self):
        path = self._daily_outfit_image_path()
        if path is None:
            return self._error("今日穿搭图片不存在")
        response = await send_file(str(path))
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    async def get_daily_outfit_image_data(self) -> dict[str, Any]:
        path = self._daily_outfit_image_path()
        if path is None:
            return self._error("今日穿搭图片不存在")
        try:
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            raw = await asyncio.to_thread(path.read_bytes)
            return self._ok(
                {
                    "mime": mime,
                    "size": len(raw),
                    "data_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                }
            )
        except Exception as exc:
            logger.warning("[PrivateCompanionPage] 读取每日穿搭图片失败: %s", self._single_line(exc, 160))
            return self._error("读取每日穿搭图片失败")

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"success": True, "data": data, "ts": int(time.time())}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"success": False, "error": str(message), "ts": int(time.time())}


# ---------------------------------------------------------------------------
# 拆分补充: 部分 mixin 的方法在模块级裸引用 PAGE_API_PREFIX / PLUGIN_NAME 常量,
# 以及以 `PrivateCompanionPageApi.<staticmethod>` 形式引用组装类名。类定义在
# mixin import 之后, mixin 文件头无法直接 import 这些名字, 故在此统一回填。
# ---------------------------------------------------------------------------
page_api_images.PAGE_API_PREFIX = PAGE_API_PREFIX
page_api_images.PrivateCompanionPageApi = PrivateCompanionPageApi
page_api_life.PrivateCompanionPageApi = PrivateCompanionPageApi
page_api_summary.PAGE_API_PREFIX = PAGE_API_PREFIX
page_api_summary.PLUGIN_NAME = PLUGIN_NAME
