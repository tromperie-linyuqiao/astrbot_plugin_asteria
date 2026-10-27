# -*- coding: utf-8 -*-
"""Private Companion Page API - Summary 聚合层与创作项目 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import secrets
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from astrbot.api import logger
from quart import request, send_file

from .config_migration import _ensure_config_parent_dir
from .constants import PAGE_FONT_NAMES, PAGE_THEME_NAMES, _REASON_TEXT
from .helpers import _flat_get, _normalize_timezone_name, _safe_int, _set_into_config, _set_today_key_timezone, _strip_internal_message_blocks, _text_similarity, _today_key

# PAGE_API_PREFIX / PLUGIN_NAME
# 由 page_api.py 在类定义完成后回填注入(见该文件末尾), 方法体保持逐字搬运。


class PrivateCompanionPageApiSummaryMixin:
    def _user_summary(self, user_id: str, user: dict[str, Any]) -> dict[str, Any]:
        last_seen = user.get("last_seen", 0)
        last_sent = user.get("last_sent", 0)
        user_id_text = str(user_id)
        is_qq_user = user_id_text.isdigit()
        umo = str(user.get("umo", "") or "")
        source = self._single_line(umo.split(":", 1)[0], 40) if ":" in umo else ""
        nickname = self._single_line(user.get("nickname"), 40)
        generic_names = {"用户", "主人", "主要用户", "默认用户"}
        if is_qq_user:
            display_name = nickname if nickname and nickname not in generic_names else user_id_text
        else:
            display_name = f"临时会话 · {user_id_text[:8]}"
        relationship_stage = ""
        rel_state = user.get("relationship_state") if isinstance(user.get("relationship_state"), dict) else {}
        if isinstance(rel_state, dict):
            relationship_stage = self._single_line(rel_state.get("stage"), 12)
        profile_getter = getattr(self.plugin, "_relationship_profile", None)
        if not relationship_stage and callable(profile_getter):
            try:
                profile = profile_getter(user)
                if isinstance(profile, dict):
                    relationship_stage = self._single_line(profile.get("level"), 12)
            except Exception:
                relationship_stage = ""
        if relationship_stage not in {"亲近", "熟悉", "陌生"}:
            persona_profile = user.get("persona_relationship") if isinstance(user.get("persona_relationship"), dict) else {}
            relationship_stage = self._single_line(persona_profile.get("level"), 12) if isinstance(persona_profile, dict) else ""
        if relationship_stage not in {"亲近", "熟悉", "陌生"}:
            score = self._int(user.get("relationship_score"))
            inbound_count = self._int(user.get("inbound_count"))
            proactive_count = self._int(user.get("proactive_sent_count"))
            reply_count = self._int(user.get("reply_count"))
            reply_rate = reply_count / proactive_count if proactive_count > 0 else 0.0
            if score >= 16 and reply_rate >= 0.35:
                relationship_stage = "亲近"
            elif score >= 3 or inbound_count >= 1 or reply_rate >= 0.2:
                relationship_stage = "熟悉"
            else:
                relationship_stage = "陌生"
        role = self.plugin._private_user_role(user, user_id_text) if hasattr(self.plugin, "_private_user_role") else ""
        role_labeler = getattr(self.plugin, "_private_user_role_label", None)
        role_label = role_labeler(role) if callable(role_labeler) else ("主要用户" if role == "owner" else "次要用户")
        relationship_state = self._emotion_relationship_state_summary(rel_state)
        pending_emotion_judgement = self._emotion_pending_judgement_summary(user.get("pending_emotion_judgement"))
        last_emotion_judgement_error = self._single_line(user.get("last_emotion_judgement_error"), 160)
        return {
            "user_id": user_id_text,
            "display_name": display_name,
            "is_qq_user": is_qq_user,
            "source": source,
            "enabled": bool(user.get("enabled", True)),
            "relationship_role": role,
            "relationship_role_label": role_label,
            "nickname": user.get("nickname", ""),
            "style": user.get("style", ""),
            "umo": user.get("umo", ""),
            "last_seen_ts": last_seen,
            "last_seen": self.plugin._format_timestamp_elapsed(last_seen),
            "last_sent_ts": last_sent,
            "last_sent": self.plugin._format_timestamp_elapsed(last_sent),
            "sent_today": user.get("sent_today", 0),
            "last_proactive_skip_ts": self._float(user.get("last_proactive_skip_at")),
            "last_proactive_skip": self.plugin._format_timestamp_elapsed(user.get("last_proactive_skip_at", 0)),
            "last_proactive_skip_reason": self._single_line(user.get("last_proactive_skip_reason"), 120),
            "last_proactive_skip_prefix": self._single_line(user.get("last_proactive_skip_prefix"), 20),
            "effective_daily_limit": (
                self.plugin._effective_user_daily_limit(user)
                if hasattr(self.plugin, "_effective_user_daily_limit")
                else getattr(self.plugin, "max_daily_messages", 0)
            ),
            "effective_daily_limit_text": (
                self.plugin._format_proactive_daily_limit(self.plugin._effective_user_daily_limit(user))
                if hasattr(self.plugin, "_format_proactive_daily_limit") and hasattr(self.plugin, "_effective_user_daily_limit")
                else str(getattr(self.plugin, "max_daily_messages", 0))
            ),
            "effective_daily_limit_unlimited": (
                self.plugin._proactive_daily_limit_is_unlimited(self.plugin._effective_user_daily_limit(user))
                if hasattr(self.plugin, "_proactive_daily_limit_is_unlimited") and hasattr(self.plugin, "_effective_user_daily_limit")
                else False
            ),
            "effective_idle_minutes": (
                self.plugin._effective_user_idle_minutes(user)
                if hasattr(self.plugin, "_effective_user_idle_minutes")
                else getattr(self.plugin, "idle_minutes", 0)
            ),
            "effective_min_interval_minutes": (
                self.plugin._effective_user_min_interval_minutes(user)
                if hasattr(self.plugin, "_effective_user_min_interval_minutes")
                else getattr(self.plugin, "min_interval_minutes", 0)
            ),
            "effective_screen_peek_daily_limit": (
                self.plugin._effective_user_screen_peek_daily_limit(user)
                if hasattr(self.plugin, "_effective_user_screen_peek_daily_limit")
                else getattr(self.plugin, "screen_peek_max_daily", 0)
            ),
            "effective_photo_daily_limit": (
                self.plugin._effective_user_photo_daily_limit(user)
                if hasattr(self.plugin, "_effective_user_photo_daily_limit")
                else getattr(self.plugin, "photo_action_max_daily", 0)
            ),
            "proactive_daily_limit": user.get("proactive_daily_limit", -1),
            "proactive_idle_minutes": user.get("proactive_idle_minutes", -1),
            "proactive_min_interval_minutes": user.get("proactive_min_interval_minutes", -1),
            "photo_daily_limit": user.get("photo_daily_limit", -1),
            "screen_peek_daily_limit": user.get("screen_peek_daily_limit", -1),
            "poke_daily_limit": user.get("poke_daily_limit", -1),
            "proactive_boundary_note": user.get("proactive_boundary_note", ""),
            "inbound_count": user.get("inbound_count", 0),
            "reply_count": user.get("reply_count", 0),
            "proactive_sent_count": user.get("proactive_sent_count", 0),
            "relationship_score": user.get("relationship_score", 0),
            "relationship_stage": relationship_stage,
            "relationship_state": relationship_state,
            "pending_emotion_judgement": pending_emotion_judgement,
            "last_emotion_judgement_error": last_emotion_judgement_error,
            "planned_reason": user.get("planned_proactive_reason", ""),
            "planned_action": user.get("planned_proactive_action", ""),
            "next_proactive_ts": user.get("next_proactive_at", 0),
            "next_proactive": self.plugin._format_next_proactive(user),
            "memory_items": self._memory_item_count(user.get("companion_memory")),
            "dialogue_episode_count": len(user.get("dialogue_episodes") or []),
            "open_loop_count": len(user.get("open_loops") or []),
            "habit_count": len(self._behavior_habit_summary(user).get("items", [])),
            "alias_user_ids": [
                self._single_line(item, 80)
                for item in (user.get("alias_user_ids") if isinstance(user.get("alias_user_ids"), list) else [])
                if self._single_line(item, 80)
            ],
        }

    def _emotion_relationship_state_summary(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            return {}
        scalar_limits = {
            "mode": 24,
            "stage": 24,
            "last_intent": 40,
            "last_emotion": 40,
            "last_emotion_event": 40,
            "last_emotion_reason": 120,
            "last_emotion_target": 40,
            "last_emotion_rule": 60,
            "last_hurt_reason": 120,
            "last_hurt_text": 180,
            "updated_at": 40,
        }
        numeric_keys = {
            "mood_score",
            "mood_updated_ts",
            "hurt_until",
            "emotion_min_until",
            "silence_turns",
            "last_pressure",
            "last_emotion_intensity",
            "last_intent_confidence",
            "last_emotion_confidence",
        }
        summary: dict[str, Any] = {}
        for key, limit in scalar_limits.items():
            if key in state:
                summary[key] = self._single_line(state.get(key), limit)
        for key in numeric_keys:
            if key in state:
                summary[key] = state.get(key)
        dims = state.get("emotion_dimensions")
        if isinstance(dims, dict):
            summary["emotion_dimensions"] = {
                key: dims.get(key)
                for key in ("pleasantness", "tension", "arousal", "certainty")
                if key in dims
            }
        plutchik_emotions = state.get("plutchik_emotions")
        if isinstance(plutchik_emotions, dict):
            summary["plutchik_emotions"] = {
                key: plutchik_emotions.get(key)
                for key in ("joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation")
                if key in plutchik_emotions
            }
        plutchik = state.get("plutchik_profile")
        if isinstance(plutchik, dict):
            profile = {
                key: plutchik.get(key)
                for key in (
                    "dominant",
                    "dominant_label",
                    "dominant_value",
                    "blend_key",
                    "blend_label",
                    "blend_value",
                    "updated_at",
                )
                if key in plutchik
            }
            active = plutchik.get("active")
            if isinstance(active, list):
                profile["active"] = [dict(item) for item in active[:8] if isinstance(item, dict)]
            summary["plutchik_profile"] = profile
        regulation = state.get("emotion_regulation")
        if isinstance(regulation, dict):
            reg = {
                key: regulation.get(key)
                for key in ("strategy", "strategy_label", "intensity", "reason", "updated_at")
                if key in regulation
            }
            stack = regulation.get("strategy_stack")
            if isinstance(stack, list):
                reg["strategy_stack"] = [dict(item) for item in stack[:5] if isinstance(item, dict)]
            summary["emotion_regulation"] = reg
        return summary

    def _emotion_pending_judgement_summary(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        text = self._single_line(value.get("text"), 180)
        created_at = self._float(value.get("created_at"))
        local = value.get("local") if isinstance(value.get("local"), dict) else {}
        result: dict[str, Any] = {
            "text": text,
            "created_at": created_at,
            "created_at_text": self.plugin._format_timestamp_elapsed(created_at) if created_at else "",
        }
        if local:
            result["local"] = {
                "emotion_event": self._single_line(local.get("emotion_event"), 40),
                "emotion_target": self._single_line(local.get("emotion_target"), 40),
                "emotion_intensity": local.get("emotion_intensity"),
                "emotion_confidence": local.get("emotion_confidence"),
                "emotion_reason": self._single_line(local.get("emotion_reason"), 100),
            }
        return result if text or created_at or local else {}

    def _worldbook_member_for_private_user_locked(
        self,
        data: dict[str, Any],
        user_id: str,
        user: dict[str, Any],
    ) -> dict[str, Any] | None:
        profiles = data.get("worldbook_member_profiles") if isinstance(data.get("worldbook_member_profiles"), dict) else {}
        if not profiles:
            return None
        candidate_ids = [str(user_id)]
        if isinstance(user, dict):
            candidate_ids.extend(
                self._single_line(item, 80)
                for item in (user.get("alias_user_ids") if isinstance(user.get("alias_user_ids"), list) else [])
                if self._single_line(item, 80)
            )
        for candidate_id in candidate_ids:
            profile = profiles.get(candidate_id)
            if isinstance(profile, dict):
                return self._worldbook_member_profile_summary(candidate_id, profile)
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            linked_id = self._single_line(profile.get("linked_qq_user_id") or profile.get("merged_into_user_id"), 80)
            external_ids = profile.get("external_ids") if isinstance(profile.get("external_ids"), list) else []
            external_id_set = {self._single_line(item, 80) for item in external_ids if self._single_line(item, 80)}
            if linked_id in candidate_ids or any(candidate_id in external_id_set for candidate_id in candidate_ids):
                return self._worldbook_member_profile_summary(str(profile_id), profile)
        return None

    def _worldbook_member_profile_summary(self, user_id: str, item: dict[str, Any]) -> dict[str, Any]:
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        observed = item.get("observed_names") if isinstance(item.get("observed_names"), list) else []
        external_ids = item.get("external_ids") if isinstance(item.get("external_ids"), list) else []
        memories = self._normalize_important_memories(item.get("important_memories"))
        pending = item.get("pending_observations") if isinstance(item.get("pending_observations"), list) else []
        return {
            "user_id": self._single_line(user_id, 40),
            "identity_type": self._single_line(item.get("identity_type") or ("qq" if str(user_id).isdigit() else "external"), 20),
            "name": self._single_line(item.get("name"), 60),
            "gender": self._single_line(item.get("gender"), 40),
            "enabled": bool(item.get("enabled", True)),
            "priority": item.get("priority", 120),
            "aliases": [self._single_line(alias, 40) for alias in aliases if self._single_line(alias, 40)],
            "observed_names": [self._single_line(name, 40) for name in observed if self._single_line(name, 40)],
            "external_ids": [self._single_line(ext, 80) for ext in external_ids if self._single_line(ext, 80)],
            "linked_qq_user_id": self._single_line(item.get("linked_qq_user_id") or item.get("merged_into_user_id"), 40),
            "linked_bili_profile_id": self._single_line(item.get("linked_bili_profile_id"), 80),
            "content": self._single_line(item.get("content"), 260),
            "identity_note": self._single_line(item.get("identity_note") or item.get("note") or item.get("content"), 500),
            "boundary_note": self._single_line(item.get("boundary_note"), 500),
            "important_memories": memories[:6],
            "pending_observation_count": len(pending),
            "source_entries": item.get("source_entries") if isinstance(item.get("source_entries"), list) else [],
            "note": self._single_line(item.get("note"), 500),
        }

    def _behavior_habit_summary(self, user: dict[str, Any]) -> dict[str, Any]:
        formatter = getattr(self.plugin, "_qualified_user_behavior_habits", None)
        if callable(formatter):
            try:
                items = formatter(user)
            except Exception:
                items = []
        else:
            raw = user.get("behavior_habits") if isinstance(user.get("behavior_habits"), dict) else {}
            patterns = raw.get("patterns") if isinstance(raw.get("patterns"), list) else []
            items = [item for item in patterns if isinstance(item, dict)]
        normalized = []
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "bucket": self._single_line(item.get("bucket"), 12),
                    "category": self._single_line(item.get("category"), 20),
                    "topic": self._single_line(item.get("topic"), 80),
                    "count": self._int(item.get("count")),
                    "avg_time": self.plugin._format_user_habit_time(item.get("avg_minute")) if hasattr(self.plugin, "_format_user_habit_time") else "",
                    "last_seen": self.plugin._format_timestamp_elapsed(item.get("last_seen_ts", 0)),
                    "last_seen_text": self._single_line(item.get("last_seen_text"), 100),
                }
            )
        raw_habits = user.get("behavior_habits") if isinstance(user.get("behavior_habits"), dict) else {}
        return {
            "enabled": bool(getattr(self.plugin, "enable_user_habit_learning", False)),
            "updated_at": self._single_line(raw_habits.get("updated_at"), 30) if isinstance(raw_habits, dict) else "",
            "items": normalized,
        }

    def _expression_learning_scope_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        scope_ids = getattr(self.plugin, "_expression_scope_ids", None)

        def ids(key: str, *, group: bool = False) -> list[str]:
            if callable(scope_ids):
                try:
                    return sorted(scope_ids(key, group=group))
                except Exception:
                    pass
            raw = getattr(self.plugin, key, [])
            return sorted(self._normalize_id_list(raw))

        voice = data.get("expression_voice_profile") if isinstance(data.get("expression_voice_profile"), dict) else {}
        actions = voice.get("actions") if isinstance(voice.get("actions"), list) else []
        runtime = data.get("expression_learning_runtime") if isinstance(data.get("expression_learning_runtime"), dict) else {}
        by_day = runtime.get("group_batches_by_day") if isinstance(runtime.get("group_batches_by_day"), dict) else {}
        group_daily_limit = self._int(getattr(self.plugin, "expression_group_learning_daily_batch_limit", 6)) or 6
        group_used_today = self._int(by_day.get(_today_key()))
        return {
            "enabled": bool(getattr(self.plugin, "enable_expression_learning", False)),
            "private_learning": {
                "mode": self._single_line(getattr(self.plugin, "expression_private_learning_source_mode", "owner"), 20),
                "ids": ids("expression_private_learning_source_ids"),
            },
            "group_learning": {
                "mode": self._single_line(getattr(self.plugin, "expression_group_learning_source_mode", "disabled"), 20),
                "ids": ids("expression_group_learning_source_ids", group=True),
            },
            "private_application": {
                "mode": self._single_line(getattr(self.plugin, "expression_private_application_mode", "all"), 20),
                "ids": ids("expression_private_application_user_ids"),
            },
            "group_application": {
                "mode": self._single_line(getattr(self.plugin, "expression_group_application_mode", "all"), 20),
                "ids": ids("expression_group_application_ids", group=True),
            },
            "group_budget": {
                "daily_limit": group_daily_limit,
                "used_today": group_used_today,
                "remaining_today": max(0, group_daily_limit - group_used_today),
                "min_new_messages": self._int(
                    getattr(self.plugin, "expression_group_learning_min_new_messages", 20)
                ) or 20,
                "last_batch_at": self._single_line(runtime.get("last_group_batch_at"), 30),
                "last_defer_reason": self._single_line(runtime.get("last_group_defer_reason"), 40),
            },
            "voice": {
                "sample_count": self._int(voice.get("sample_count")),
                "private_source_count": self._int(voice.get("private_source_count")),
                "group_source_count": self._int(voice.get("group_source_count")),
                "actions": [self._single_line(item, 120) for item in actions[:4] if self._single_line(item, 120)],
                "updated_at": self._single_line(voice.get("updated_at"), 30),
            },
        }

    def _expression_rule_group_rows(self, rules: Any) -> list[dict[str, Any]]:
        rows = [dict(item) for item in rules if isinstance(item, dict)] if isinstance(rules, list) else []
        if not rows:
            return []
        grouper = getattr(self.plugin, "_expression_rule_groups", None)
        bundler = getattr(self.plugin, "_expression_rule_runtime_bundle", None)
        raw_groups = grouper(rows) if callable(grouper) else [[item] for item in rows]
        result: list[dict[str, Any]] = []
        for raw_group in raw_groups:
            if not isinstance(raw_group, list) or not raw_group:
                continue
            bundle = bundler(raw_group) if callable(bundler) else dict(raw_group[0])
            if not isinstance(bundle, dict) or not bundle:
                continue
            items = [dict(item) for item in raw_group if isinstance(item, dict)]
            style_rule = next((item for item in items if item.get("kind") == "style"), None)
            grammar_rule = next((item for item in items if item.get("kind") == "grammar"), None)
            review_statuses = {self._single_line(item.get("review_status"), 24).lower() for item in items}
            review_status = "needs_review" if "needs_review" in review_statuses else (
                "pending" if "pending" in review_statuses else "approved"
            )
            group_row = {
                **bundle,
                "id": self._single_line(bundle.get("family_id") or bundle.get("id"), 100),
                "family_id": self._single_line(bundle.get("family_id"), 100),
                "label": self._single_line(
                    (style_rule or {}).get("label") or (grammar_rule or {}).get("label") or bundle.get("label"),
                    100,
                ),
                "situation": self._single_line(
                    (style_rule or {}).get("situation") or (grammar_rule or {}).get("situation") or bundle.get("situation"),
                    100,
                ),
                "kind": "combined" if style_rule and grammar_rule else self._single_line(bundle.get("kind"), 24),
                "kind_label": "组合规则" if style_rule and grammar_rule else (
                    "情境表达" if style_rule else "语法习惯"
                ),
                "component_count": len(items),
                "component_kinds": [kind for kind in ("style", "grammar") if any(item.get("kind") == kind for item in items)],
                "items": items,
                "component_rules": items,
                "style_rule": dict(style_rule) if style_rule else None,
                "grammar_rule": dict(grammar_rule) if grammar_rule else None,
                "review_status": review_status,
                "review_reason": self._single_line(
                    next((item.get("review_reason") for item in items if item.get("review_reason")), ""),
                    180,
                ),
                "evidence_count": max(self._int(item.get("evidence_count")) for item in items),
            }
            result.append(group_row)
        result.sort(key=lambda item: (-self._int(item.get("evidence_count")), self._single_line(item.get("situation"), 100)))
        return result

    def _expression_profile_summary(self, user: dict[str, Any], *, source_type: str = "private") -> dict[str, Any]:
        profile = user.get("expression_profile") if isinstance(user.get("expression_profile"), dict) else {}
        scene_label = getattr(self.plugin, "_expression_scene_label", None)
        feature_labels = {
            "short": "短句",
            "casual_opener": "随口开头",
            "playful": "轻松感",
            "laugh_marker": "笑声口语",
            "reduplication": "自然叠词",
            "soft_wave": "波浪收束",
            "soft_ending": "柔和收尾",
            "pause": "留白停顿",
            "question": "问句推进",
        }

        def sample_row(item: Any, index: int) -> dict[str, Any]:
            raw = item if isinstance(item, dict) else {}
            text = self._single_line(raw.get("text") or raw.get("phrase") or raw.get("ending"), 120)
            punctuation = raw.get("punctuation") if isinstance(raw.get("punctuation"), dict) else {}
            marks = "".join(f"{key}{value}" for key, value in punctuation.items() if self._int(value) > 0)
            scene = self._single_line(
                scene_label(raw.get("scene")) if callable(scene_label) else raw.get("scene"),
                32,
            )
            feature_values = [
                self._single_line(feature_labels.get(str(feature), str(feature)), 24)
                for feature in raw.get("features", [])
                if self._single_line(feature, 24)
            ] if isinstance(raw.get("features"), list) else []
            distinctive_features = [item for item in feature_values if item not in {"短句", "问句推进"}]
            pattern_label = scene
            if source_type == "group":
                if distinctive_features:
                    pattern_label = f"{scene or '日常交流'}中的{'与'.join(distinctive_features[:2])}"
                elif scene:
                    pattern_label = f"{scene}表达模式"
            observation_status = "supported" if self._int(raw.get("evidence_count")) >= 2 else "single"
            return {
                "id": self._single_line(raw.get("id"), 40) or str(index),
                "index": index,
                "text": text,
                "phrase": self._single_line(raw.get("phrase"), 80),
                "ending": self._single_line(raw.get("ending"), 20),
                "scene": scene,
                "features": feature_values,
                "length": self._int(raw.get("length")),
                "length_bucket": self._single_line(raw.get("length_bucket"), 20),
                "punctuation": marks,
                "evidence_count": max(1, self._int(raw.get("evidence_count"))),
                "pattern_status": observation_status,
                "observation_status": observation_status,
                "pattern_label": pattern_label,
                "created_at": self._single_line(raw.get("created_at"), 30),
                "ts": self._float(raw.get("ts")),
                "time": self.plugin._format_timestamp_elapsed(raw.get("ts", 0)),
            }

        samples = profile.get("samples") if isinstance(profile.get("samples"), list) else []
        pending = profile.get("pending_samples") if isinstance(profile.get("pending_samples"), list) else []
        formatter = getattr(self.plugin, "_format_expression_profile_for_prompt", None)
        try:
            prompt_preview = formatter(user) if callable(formatter) else ""
        except Exception:
            prompt_preview = ""
        rules: list[dict[str, Any]] = []
        def semantic_rule_row(raw_rule: dict[str, Any], *, pending_review: bool) -> dict[str, Any] | None:
            if not isinstance(raw_rule, dict):
                return None
            validator = getattr(self.plugin, "_expression_rule_definition_is_valid", None)
            if callable(validator) and not validator(raw_rule):
                return None
            evidence_count = self._int(raw_rule.get("evidence_count"))
            if evidence_count < 1:
                return None
            situation = self._single_line(raw_rule.get("situation"), 100)
            instruction = self._single_line(raw_rule.get("instruction"), 300)
            pattern = self._single_line(raw_rule.get("pattern"), 180)
            kind = self._single_line(raw_rule.get("kind"), 24).lower()
            if kind not in {"style", "grammar"} or not situation or not pattern or not instruction:
                return None
            review_status = self._single_line(raw_rule.get("review_status"), 24).lower()
            if not review_status:
                review_status = "pending" if pending_review else "approved"
            return {
                "id": self._single_line(raw_rule.get("id"), 100),
                "family_id": self._single_line(raw_rule.get("family_id"), 100),
                "family_key": self._single_line(raw_rule.get("family_key"), 80),
                "scene": self._single_line(raw_rule.get("kind"), 24),
                "label": situation or "语义表达规则",
                "situation": situation,
                "pattern": pattern,
                "instruction": instruction,
                "evidence_count": evidence_count,
                "confidence": min(0.98, round(0.52 + min(8, evidence_count) * 0.055, 2)),
                "signals": [
                    self._single_line(item, 24)
                    for item in (raw_rule.get("keywords") or raw_rule.get("tags") or [])
                    if self._single_line(item, 24)
                ] if isinstance(raw_rule.get("keywords") or raw_rule.get("tags"), list) else [],
                "rule_type": "semantic",
                "kind": kind,
                "kind_label": "情境表达" if kind == "style" else "语法习惯",
                "evidence_examples": [
                    self._single_line(item, 80)
                    for item in raw_rule.get("evidence_examples", [])
                    if self._single_line(item, 80)
                ][:3] if isinstance(raw_rule.get("evidence_examples"), list) else [],
                "pattern_status": review_status if pending_review else "active",
                "review_status": review_status,
                "review_reason": self._single_line(raw_rule.get("review_reason"), 180),
                "channels": [
                    self._single_line(item, 24).lower()
                    for item in raw_rule.get("channels", [])
                    if self._single_line(item, 24)
                ] if isinstance(raw_rule.get("channels"), list) else [],
                "relationship_stages": [
                    self._single_line(item, 24).lower()
                    for item in raw_rule.get("relationship_stages", [])
                    if self._single_line(item, 24)
                ] if isinstance(raw_rule.get("relationship_stages"), list) else [],
                "emotion_gates": [
                    self._single_line(item, 24).lower()
                    for item in raw_rule.get("emotion_gates", [])
                    if self._single_line(item, 24)
                ] if isinstance(raw_rule.get("emotion_gates"), list) else [],
                "intent": self._single_line(raw_rule.get("intent"), 32).lower() or "any",
                "avoid": self._single_line(raw_rule.get("avoid"), 220),
                "persona_conflict": raw_rule.get("persona_conflict") is True
                or self._single_line(raw_rule.get("persona_conflict"), 12).lower() in {"1", "true", "yes", "on", "是", "冲突"},
                "positive_feedback": self._int(raw_rule.get("positive_feedback")),
                "negative_feedback": self._int(raw_rule.get("negative_feedback")),
                "use_count": self._int(raw_rule.get("use_count")),
                "last_used_time": self.plugin._format_timestamp_elapsed(raw_rule.get("last_used_ts", 0))
                if self._float(raw_rule.get("last_used_ts")) > 0 else "",
            }

        learned_rules = profile.get("learned_rules") if isinstance(profile.get("learned_rules"), list) else []
        for raw_rule in learned_rules:
            row = semantic_rule_row(raw_rule, pending_review=False)
            if row:
                rules.append(row)
        pending_rules = profile.get("pending_rules") if isinstance(profile.get("pending_rules"), list) else []
        pending_rule_rows = [
            row
            for raw_rule in pending_rules
            if (row := semantic_rule_row(raw_rule, pending_review=True)) is not None
        ]
        rules.sort(key=lambda item: (-self._int(item.get("evidence_count")), self._single_line(item.get("scene"), 32)))
        rule_groups = self._expression_rule_group_rows(rules)
        pending_rule_groups = self._expression_rule_group_rows(pending_rule_rows)
        raw_usage = profile.get("usage") if isinstance(profile.get("usage"), dict) else {}
        raw_last_injection = raw_usage.get("last_injection") if isinstance(raw_usage.get("last_injection"), dict) else {}
        usage = {
            "injected_count": self._int(raw_usage.get("injected_count")),
            "visible_match_count": self._int(raw_usage.get("visible_match_count")),
            "semantic_injected_count": self._int(raw_usage.get("semantic_injected_count")),
            "feedback_positive": self._int(raw_usage.get("feedback_positive")),
            "feedback_negative": self._int(raw_usage.get("feedback_negative")),
            "last_injection": {
                "time": self.plugin._format_timestamp_elapsed(raw_last_injection.get("ts", 0)) if raw_last_injection else "",
                "at": self._single_line(raw_last_injection.get("at"), 30),
                "rule_id": self._single_line(raw_last_injection.get("rule_id"), 100),
                "scene": self._single_line(raw_last_injection.get("scene"), 32),
                "label": self._single_line(raw_last_injection.get("label"), 32),
                "instruction": self._single_line(raw_last_injection.get("instruction"), 300),
                "evidence_count": self._int(raw_last_injection.get("evidence_count")),
                "confidence": max(0.0, min(1.0, self._float(raw_last_injection.get("confidence")))),
                "expected_signals": [
                    self._single_line(feature_labels.get(str(signal), str(signal)), 24)
                    for signal in raw_last_injection.get("expected_signals", [])
                    if self._single_line(signal, 24)
                ] if isinstance(raw_last_injection.get("expected_signals"), list) else [],
                "visible_signals": [
                    self._single_line(feature_labels.get(str(signal), str(signal)), 24)
                    for signal in raw_last_injection.get("visible_signals", [])
                    if self._single_line(signal, 24)
                ] if isinstance(raw_last_injection.get("visible_signals"), list) else [],
                "rule_type": self._single_line(raw_last_injection.get("rule_type"), 24),
                "semantic_rule_count": self._int(raw_last_injection.get("semantic_rule_count")),
                "channel": self._single_line(raw_last_injection.get("channel"), 24),
                "relationship_stage": self._single_line(raw_last_injection.get("relationship_stage"), 24),
                "emotion_gate": self._single_line(raw_last_injection.get("emotion_gate"), 24),
                "intent": self._single_line(raw_last_injection.get("intent"), 32),
            } if raw_last_injection else {},
        }
        raw_scene_profiles = profile.get("scene_profiles") if isinstance(profile.get("scene_profiles"), dict) else {}
        scene_profiles = []
        for scene, item in raw_scene_profiles.items():
            if not isinstance(item, dict):
                continue
            count = self._int(item.get("count"))
            if count <= 0:
                continue
            label = scene_label(scene) if callable(scene_label) else self._single_line(scene, 32)
            scene_profiles.append(
                {
                    "scene": self._single_line(scene, 32),
                    "label": self._single_line(label, 32),
                    "count": count,
                    "short_ratio": float(item.get("short_ratio") or 0),
                    "feature_counts": item.get("feature_counts") if isinstance(item.get("feature_counts"), dict) else {},
                }
            )
        scene_profiles.sort(key=lambda item: (-self._int(item.get("count")), self._single_line(item.get("scene"), 32)))
        sample_limit = max(
            4,
            min(60, self._int(getattr(self.plugin, "max_learned_expression_items", 60)) or 60),
        )
        return {
            "enabled": bool(getattr(self.plugin, "enable_expression_learning", False)),
            "mode": self._single_line(getattr(self.plugin, "expression_learning_mode", "balanced"), 20),
            "manual_review": bool(getattr(self.plugin, "enable_expression_manual_review", False)),
            "style_review": bool(getattr(self.plugin, "enable_expression_style_review", True)),
            "updated_at": self._single_line(profile.get("updated_at"), 30),
            "sample_count": len(samples),
            "observation_count": len(samples),
            "observation_evidence_count": sum(max(1, self._int(item.get("evidence_count"))) for item in samples if isinstance(item, dict)),
            "pattern_count": len(rules),
            "rule_count": len(rules),
            "rule_evidence_count": sum(self._int(item.get("evidence_count")) for item in rule_groups),
            "style_rule_count": sum(1 for item in rules if item.get("kind") == "style"),
            "grammar_rule_count": sum(1 for item in rules if item.get("kind") == "grammar"),
            "rule_group_count": len(rule_groups),
            "pending_count": len(pending),
            "pending_rule_count": len(pending_rule_rows),
            "pending_rule_group_count": len(pending_rule_groups),
            "pending_style_count": sum(1 for item in pending_rule_rows if item.get("kind") == "style"),
            "pending_grammar_count": sum(1 for item in pending_rule_rows if item.get("kind") == "grammar"),
            "short_count": self._int(profile.get("short_count")),
            "endings": [self._single_line(item, 20) for item in (profile.get("endings") if isinstance(profile.get("endings"), list) else [])[:8]],
            "recent_phrases": [self._single_line(item, 80) for item in (profile.get("recent_phrases") if isinstance(profile.get("recent_phrases"), list) else [])[:8]],
            "scene_profiles": scene_profiles[:6],
            "rules": rules[: max(6, min(60, sample_limit * 2))],
            "pending_rules": pending_rule_rows[: max(6, min(60, sample_limit * 2))],
            "rule_groups": rule_groups[: max(6, min(60, sample_limit * 2))],
            "pending_rule_groups": pending_rule_groups[: max(6, min(60, sample_limit * 2))],
            "usage": usage,
            "samples": [sample_row(item, idx) for idx, item in enumerate(samples[:sample_limit])],
            "pending_samples": [sample_row(item, idx) for idx, item in enumerate(pending[:24])],
            "prompt_preview": self._multi_line(prompt_preview, 500),
        }

    def _expression_library_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        pending_samples: list[dict[str, Any]] = []
        pending_rules: list[dict[str, Any]] = []
        rules: list[dict[str, Any]] = []
        pending_rule_groups: list[dict[str, Any]] = []
        rule_groups: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        scene_totals: dict[str, dict[str, Any]] = {}
        sample_count = 0
        observation_evidence_count = 0
        rule_evidence_count = 0
        pending_count = 0
        injected_count = 0
        positive_feedback_count = 0
        negative_feedback_count = 0
        style_rule_count = 0
        grammar_rule_count = 0
        pending_style_count = 0
        pending_grammar_count = 0

        def collect(source_type: str, source_id: str, item: dict[str, Any]) -> None:
            nonlocal sample_count, observation_evidence_count, rule_evidence_count, pending_count
            nonlocal injected_count, positive_feedback_count, negative_feedback_count
            nonlocal style_rule_count, grammar_rule_count, pending_style_count, pending_grammar_count
            summary = self._expression_profile_summary(item, source_type=source_type)
            if source_type == "group":
                source_name = self._single_line(
                    item.get("name") or item.get("group_name") or item.get("display_name"),
                    80,
                ) or "未命名群聊"
                active = bool(self.plugin._expression_group_learning_source_enabled(source_id))
                source_kind_label = "群聊"
            else:
                source_name = self._single_line(
                    item.get("display_name") or item.get("nickname") or item.get("name"),
                    80,
                ) or source_id
                active = bool(self.plugin._expression_private_learning_source_enabled(item, source_id))
                source_kind_label = "私聊"
            source = {
                "source_type": source_type,
                "source_kind_label": source_kind_label,
                "source_id": source_id,
                "source_name": source_name,
                "source_active": active,
            }
            source_sample_count = self._int(summary.get("sample_count"))
            source_pending_sample_count = self._int(summary.get("pending_count"))
            source_pending_rule_count = self._int(summary.get("pending_rule_count"))
            source_pending_count = source_pending_sample_count + source_pending_rule_count
            source_rules = summary.get("rules") if isinstance(summary.get("rules"), list) else []
            source_pending_rules = summary.get("pending_rules") if isinstance(summary.get("pending_rules"), list) else []
            source_rule_groups = summary.get("rule_groups") if isinstance(summary.get("rule_groups"), list) else []
            source_pending_rule_groups = summary.get("pending_rule_groups") if isinstance(summary.get("pending_rule_groups"), list) else []
            if source_sample_count <= 0 and source_pending_count <= 0 and not source_rules and not source_pending_rules:
                return
            sources.append(
                {
                    **source,
                    "sample_count": source_sample_count,
                    "observation_count": source_sample_count,
                    "pending_count": source_pending_count,
                    "pending_rule_count": source_pending_rule_count,
                    "rule_count": len(source_rules),
                    "rule_group_count": len(source_rule_groups),
                    "pending_rule_group_count": len(source_pending_rule_groups),
                    "style_rule_count": self._int(summary.get("style_rule_count")),
                    "grammar_rule_count": self._int(summary.get("grammar_rule_count")),
                }
            )
            sample_count += source_sample_count
            observation_evidence_count += self._int(summary.get("observation_evidence_count"))
            rule_evidence_count += self._int(summary.get("rule_evidence_count"))
            pending_count += source_pending_count
            style_rule_count += self._int(summary.get("style_rule_count"))
            grammar_rule_count += self._int(summary.get("grammar_rule_count"))
            pending_style_count += self._int(summary.get("pending_style_count"))
            pending_grammar_count += self._int(summary.get("pending_grammar_count"))
            injected_count += self._int((summary.get("usage") or {}).get("injected_count"))
            for row in summary.get("samples") or []:
                if isinstance(row, dict):
                    samples.append({**row, **source})
            for row in summary.get("pending_samples") or []:
                if isinstance(row, dict):
                    pending_samples.append({**row, **source})
            for row in source_pending_rules:
                if isinstance(row, dict):
                    pending_rules.append({**row, **source})
            for row in source_pending_rule_groups:
                if isinstance(row, dict):
                    pending_rule_groups.append({**row, **source})
            for row in source_rules:
                if isinstance(row, dict):
                    rules.append({**row, **source})
                    if row.get("rule_type") == "semantic":
                        positive_feedback_count += self._int(row.get("positive_feedback"))
                        negative_feedback_count += self._int(row.get("negative_feedback"))
            for row in source_rule_groups:
                if isinstance(row, dict):
                    rule_groups.append({**row, **source})
            for scene in summary.get("scene_profiles") or []:
                if not isinstance(scene, dict):
                    continue
                key = self._single_line(scene.get("scene") or scene.get("label"), 32)
                if not key:
                    continue
                bucket = scene_totals.setdefault(
                    key,
                    {
                        "scene": key,
                        "label": self._single_line(scene.get("label") or key, 32),
                        "count": 0,
                    },
                )
                bucket["count"] += self._int(scene.get("count"))

        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        for user_id, user in users.items():
            if isinstance(user, dict):
                collect("private", self._single_line(user_id, 80), user)
        groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
        for group_id, group in groups.items():
            if isinstance(group, dict):
                collect("group", self._single_line(group_id, 80), group)

        samples.sort(key=lambda row: (-self._float(row.get("ts")), row.get("source_type") or "", row.get("source_id") or ""))
        pending_samples.sort(key=lambda row: (-self._float(row.get("ts")), row.get("source_type") or "", row.get("source_id") or ""))
        pending_rules.sort(key=lambda row: (-self._int(row.get("evidence_count")), row.get("source_type") or "", row.get("source_id") or ""))
        rules.sort(key=lambda row: (-self._int(row.get("evidence_count")), row.get("source_type") or "", row.get("source_id") or ""))
        pending_rule_groups.sort(key=lambda row: (-self._int(row.get("evidence_count")), row.get("source_type") or "", row.get("source_id") or ""))
        rule_groups.sort(key=lambda row: (-self._int(row.get("evidence_count")), row.get("source_type") or "", row.get("source_id") or ""))
        sources.sort(key=lambda row: (not bool(row.get("source_active")), row.get("source_type") or "", row.get("source_name") or ""))
        scene_profiles = sorted(
            scene_totals.values(),
            key=lambda row: (-self._int(row.get("count")), row.get("label") or ""),
        )
        return {
            "enabled": bool(getattr(self.plugin, "enable_expression_learning", False)),
            "mode": self._single_line(getattr(self.plugin, "expression_learning_mode", "balanced"), 20),
            "manual_review": bool(getattr(self.plugin, "enable_expression_manual_review", False)),
            "style_review": bool(getattr(self.plugin, "enable_expression_style_review", True)),
            "sample_count": sample_count,
            "observation_count": sample_count,
            "observation_evidence_count": observation_evidence_count,
            "pattern_count": len(rules),
            "rule_count": len(rules),
            "rule_group_count": len(rule_groups),
            "style_rule_count": style_rule_count,
            "grammar_rule_count": grammar_rule_count,
            "rule_evidence_count": rule_evidence_count,
            "evidence_count": rule_evidence_count,
            "pending_count": pending_count,
            "source_count": len(sources),
            "private_source_count": sum(1 for source in sources if source.get("source_type") == "private"),
            "group_source_count": sum(1 for source in sources if source.get("source_type") == "group"),
            "active_source_count": sum(1 for source in sources if source.get("source_active")),
            "samples": samples,
            "pending_samples": pending_samples,
            "pending_rules": pending_rules,
            "pending_rule_count": len(pending_rules),
            "pending_rule_groups": pending_rule_groups,
            "pending_rule_group_count": len(pending_rule_groups),
            "pending_style_count": pending_style_count,
            "pending_grammar_count": pending_grammar_count,
            "rules": rules,
            "rule_groups": rule_groups,
            "scene_profiles": scene_profiles[:8],
            "sources": sources,
            "usage": {
                "injected_count": injected_count,
                "feedback_positive": positive_feedback_count,
                "feedback_negative": negative_feedback_count,
            },
        }

    async def get_expression_library(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                changed = False
                normalizer = getattr(self.plugin, "_normalize_group_expression_profile", None)
                pruner = getattr(self.plugin, "_prune_invalid_expression_rules", None)
                family_backfiller = getattr(self.plugin, "_backfill_expression_rule_families", None)
                for collection_key in ("users", "groups"):
                    collection = self.plugin.data.get(collection_key)
                    if not isinstance(collection, dict):
                        continue
                    for item in collection.values():
                        profile = item.get("expression_profile") if isinstance(item, dict) else None
                        if not isinstance(profile, dict):
                            continue
                        if collection_key == "groups" and callable(normalizer) and normalizer(profile):
                            changed = True
                        if callable(pruner) and pruner(profile):
                            changed = True
                        if callable(family_backfiller) and family_backfiller(profile):
                            changed = True
                if changed:
                    self.plugin._save_data_sync()
                snapshot = deepcopy(self.plugin.data)
            return self._ok(self._expression_library_summary(snapshot))
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取统一表达学习库失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_expression_library(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        source_type = self._single_line(payload.get("source_type"), 16)
        source_id = self._single_line(payload.get("source_id"), 80)
        action = self._single_line(payload.get("expression_action"), 40)
        if action == "clear_all_pending":
            try:
                async with self.plugin._data_lock:
                    cleared = 0
                    for collection_key in ("users", "groups"):
                        collection = self.plugin.data.get(collection_key)
                        if not isinstance(collection, dict):
                            continue
                        for item in collection.values():
                            if not isinstance(item, dict):
                                continue
                            profile = item.get("expression_profile")
                            pending = profile.get("pending_samples") if isinstance(profile, dict) else None
                            pending_rules = profile.get("pending_rules") if isinstance(profile, dict) else None
                            item_count = (len(pending) if isinstance(pending, list) else 0) + (
                                len(pending_rules) if isinstance(pending_rules, list) else 0
                            )
                            if item_count:
                                cleared += item_count
                                self._apply_expression_profile_action(item, {"expression_action": "clear_pending"})
                    self.plugin._save_data_sync()
                    snapshot = deepcopy(self.plugin.data)
                result = self._expression_library_summary(snapshot)
                result["message"] = f"已清空 {cleared} 条待审核表达资料"
                return self._ok(result)
            except Exception as exc:
                logger.error(f"[PrivateCompanionPage] 清空统一表达待审样本失败: {exc}", exc_info=True)
                return self._error(str(exc))
        if source_type not in {"private", "group"} or not source_id:
            return self._error("缺少有效的表达样本来源")
        if action not in {
            "approve", "reject", "approve_rule", "reject_rule", "delete_sample", "delete_rule",
            "approve_rule_group", "reject_rule_group", "delete_rule_group",
        }:
            return self._error("不支持的表达样本操作")
        try:
            async with self.plugin._data_lock:
                collection_key = "groups" if source_type == "group" else "users"
                collection = self.plugin.data.get(collection_key)
                item = collection.get(source_id) if isinstance(collection, dict) else None
                if not isinstance(item, dict):
                    return self._error("表达样本来源不存在")
                if source_type == "group":
                    normalizer = getattr(self.plugin, "_normalize_group_expression_profile", None)
                    profile = item.get("expression_profile")
                    if callable(normalizer) and isinstance(profile, dict):
                        normalizer(profile)
                payload["source_type"] = source_type
                action_message = self._apply_expression_profile_action(item, payload)
                if action in {
                    "approve", "approve_rule", "approve_rule_group", "delete_sample", "delete_rule", "delete_rule_group",
                }:
                    voice_refresher = getattr(self.plugin, "_refresh_expression_voice_profile", None)
                    if callable(voice_refresher):
                        voice_refresher()
                self.plugin._save_data_sync()
                snapshot = deepcopy(self.plugin.data)
            result = self._expression_library_summary(snapshot)
            result["message"] = action_message
            return self._ok(result)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新统一表达学习库失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _apply_expression_profile_action(self, user: dict[str, Any], payload: dict[str, Any]) -> str:
        profile = user.setdefault("expression_profile", {})
        if not isinstance(profile, dict):
            profile = {}
            user["expression_profile"] = profile
        action = self._single_line(payload.get("expression_action"), 40)
        family_backfiller = getattr(self.plugin, "_backfill_expression_rule_families", None)
        if callable(family_backfiller):
            family_backfiller(profile)
        pending = profile.get("pending_samples") if isinstance(profile.get("pending_samples"), list) else []
        pending_rules = profile.get("pending_rules") if isinstance(profile.get("pending_rules"), list) else []
        samples = profile.get("samples") if isinstance(profile.get("samples"), list) else []
        sample_id = self._single_line(payload.get("sample_id"), 40)
        rule_id = self._single_line(payload.get("rule_id"), 100)
        rule_family_id = self._single_line(payload.get("rule_family_id"), 100)
        sample_index = self._int(payload.get("sample_index"))

        def find_index(items: list[Any]) -> int:
            if sample_id:
                for idx, item in enumerate(items):
                    if isinstance(item, dict) and self._single_line(item.get("id"), 40) == sample_id:
                        return idx
            if 0 <= sample_index < len(items):
                return sample_index
            return -1

        def find_rule_index(items: list[Any]) -> int:
            if not rule_id:
                return -1
            for idx, item in enumerate(items):
                if isinstance(item, dict) and self._single_line(item.get("id"), 100) == rule_id:
                    return idx
            return -1

        if action == "clear_pending":
            profile["pending_samples"] = []
            profile["pending_rules"] = []
            profile["pending_count"] = 0
            profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return "已清空待审核表达资料"
        if action in {"approve", "reject"}:
            idx = find_index(pending)
            if idx < 0:
                return "没有找到待审核样本"
            item = pending.pop(idx)
            profile["pending_samples"] = pending
            profile["pending_count"] = len(pending)
            if action == "reject":
                profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                return "已删除待审核样本"
            if isinstance(item, dict):
                approved = dict(item)
                approved.pop("review_status", None)
                approved["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                samples.insert(0, approved)
                limit = max(12, int(getattr(self.plugin, "max_learned_expression_items", 60) or 60))
                profile["samples"] = samples[:limit]
                refresher = getattr(self.plugin, "_refresh_expression_profile_legacy_summary", None)
                if callable(refresher):
                    refresher(profile)
                profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                voice_refresher = getattr(self.plugin, "_refresh_expression_voice_profile", None)
                if callable(voice_refresher):
                    voice_refresher()
                return "已通过表达样本"
            return "待审核样本格式异常"
        if action in {"approve_rule", "reject_rule"}:
            idx = find_rule_index(pending_rules)
            if idx < 0:
                return "没有找到待审核规则"
            item = pending_rules.pop(idx)
            profile["pending_rules"] = pending_rules
            if action == "reject_rule":
                profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                return "已拒绝归纳规则"
            if not isinstance(item, dict):
                return "待审核规则格式异常"
            validator = getattr(self.plugin, "_expression_rule_definition_is_valid", None)
            if callable(validator) and not validator(item):
                profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                return "该规则不是可复用表达或具体语法，已从待审核区移除"
            approved = dict(item)
            approved["review_status"] = "approved"
            if self._single_line(item.get("review_status"), 24).lower() == "needs_review":
                approved["negative_feedback_before_review"] = self._int(item.get("negative_feedback"))
                approved["negative_feedback"] = 0
                approved["review_cycles"] = self._int(item.get("review_cycles")) + 1
                approved.pop("review_reason", None)
            approved["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            merger = getattr(self.plugin, "_merge_learned_expression_rules", None)
            if callable(merger):
                merger(
                    profile,
                    [approved],
                    batch_key=f"approve:{self._single_line(item.get('last_batch_key'), 40) or rule_id}",
                    now=time.time(),
                )
            else:
                learned_rules = profile.get("learned_rules") if isinstance(profile.get("learned_rules"), list) else []
                learned_rules.insert(0, approved)
                profile["learned_rules"] = learned_rules[: max(12, int(getattr(self.plugin, "max_learned_expression_items", 60) or 60))]
            profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return "已通过表达规则，后续匹配情境时可以使用"
        if action in {"approve_rule_group", "reject_rule_group"}:
            if not rule_family_id:
                return "缺少规则组标识"
            matched = [
                item
                for item in pending_rules
                if isinstance(item, dict) and self._single_line(item.get("family_id"), 100) == rule_family_id
            ]
            if not matched:
                return "没有找到待审核规则组"
            profile["pending_rules"] = [
                item
                for item in pending_rules
                if not isinstance(item, dict) or self._single_line(item.get("family_id"), 100) != rule_family_id
            ]
            if action == "reject_rule_group":
                profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                return f"已拒绝规则组中的 {len(matched)} 条归纳规则"
            validator = getattr(self.plugin, "_expression_rule_definition_is_valid", None)
            approved_items: list[dict[str, Any]] = []
            approved_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            for item in matched:
                if callable(validator) and not validator(item):
                    continue
                approved = dict(item)
                approved["review_status"] = "approved"
                if self._single_line(item.get("review_status"), 24).lower() == "needs_review":
                    approved["negative_feedback_before_review"] = self._int(item.get("negative_feedback"))
                    approved["negative_feedback"] = 0
                    approved["review_cycles"] = self._int(item.get("review_cycles")) + 1
                    approved.pop("review_reason", None)
                approved["approved_at"] = approved_at
                approved_items.append(approved)
            if not approved_items:
                profile["updated_at"] = approved_at
                return "规则组中没有可复用规则，已从待审核区移除"
            merger = getattr(self.plugin, "_merge_learned_expression_rules", None)
            if callable(merger):
                merger(
                    profile,
                    approved_items,
                    batch_key=f"approve-family:{rule_family_id}",
                    now=time.time(),
                )
            else:
                learned_rules = profile.get("learned_rules") if isinstance(profile.get("learned_rules"), list) else []
                learned_rules[0:0] = approved_items
                profile["learned_rules"] = learned_rules[: max(12, int(getattr(self.plugin, "max_learned_expression_items", 60) or 60))]
            profile["updated_at"] = approved_at
            return f"已通过规则组，共启用 {len(approved_items)} 条互补规则"
        if action == "delete_sample":
            idx = find_index(samples)
            if idx < 0:
                return "没有找到已入库样本"
            samples.pop(idx)
            profile["samples"] = samples
            refresher = getattr(self.plugin, "_refresh_expression_profile_legacy_summary", None)
            if callable(refresher):
                refresher(profile)
            profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            voice_refresher = getattr(self.plugin, "_refresh_expression_voice_profile", None)
            if callable(voice_refresher):
                voice_refresher()
            return "已删除表达样本"
        if action == "delete_rule":
            learned_rules = profile.get("learned_rules") if isinstance(profile.get("learned_rules"), list) else []
            kept = [
                item
                for item in learned_rules
                if not isinstance(item, dict) or self._single_line(item.get("id"), 100) != rule_id
            ]
            if len(kept) == len(learned_rules):
                return "没有找到归纳规则"
            profile["learned_rules"] = kept
            profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return "已删除归纳规则"
        if action == "delete_rule_group":
            if not rule_family_id:
                return "缺少规则组标识"
            learned_rules = profile.get("learned_rules") if isinstance(profile.get("learned_rules"), list) else []
            kept = [
                item
                for item in learned_rules
                if not isinstance(item, dict) or self._single_line(item.get("family_id"), 100) != rule_family_id
            ]
            removed = len(learned_rules) - len(kept)
            if removed <= 0:
                return "没有找到归纳规则组"
            profile["learned_rules"] = kept
            profile["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return f"已删除规则组中的 {removed} 条规则"
        return "未知表达样本操作"

    @classmethod
    def _display_message_text(cls, value: Any, limit: int = 500) -> str:
        source = str(value or "").strip()
        source = source.strip("\"'“”‘’` ")
        if cls._looks_like_internal_delivery_receipt(source):
            return ""
        if re.fullmatch(r"[.。…~～\s\"'“”‘’`-]{0,12}", source):
            return ""
        if re.search(r"<t{2,}s\b[^>]*>.*?</t{2,}s>", source, flags=re.IGNORECASE | re.DOTALL):
            outside = re.sub(r"<t{2,}s\b[^>]*>.*?</t{2,}s>", "", source, flags=re.IGNORECASE | re.DOTALL)
            outside = re.sub(r"</?t{2,}s\b[^>]*>", "", outside, flags=re.IGNORECASE).strip()
            if re.search(r"[\u4e00-\u9fff]", outside):
                source = outside
            else:
                source = re.sub(r"</?t{2,}s\b[^>]*>", "", source, flags=re.IGNORECASE)
        if re.search(r"[\u3040-\u30ff]", source) and re.search(r"[\u4e00-\u9fff]", source):
            units = re.findall(r".*?[。！？!?…~～]+|.+$", source, flags=re.DOTALL)
            kept = [unit.strip() for unit in units if unit.strip() and not re.search(r"[\u3040-\u30ff]", unit)]
            if kept and any(re.search(r"[\u4e00-\u9fff]", item) for item in kept):
                source = "".join(kept)
        return cls._single_line(_strip_internal_message_blocks(source), limit)

    @staticmethod
    def _looks_like_internal_delivery_receipt(text: Any) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        compact = re.sub(r"[\s。.!！?？,，；;:：、~～\"'“”‘’（）()【】\[\]]+", "", raw).lower()
        if compact in {"已发送", "发送成功", "发送完成", "发送完毕", "已成功发送", "消息已发送", "消息发送成功"}:
            return True
        markers = (
            ("已经把", "转给"),
            ("已把", "转给"),
            ("已经将", "转给"),
            ("已将", "转给"),
            ("已经发给", "就假装"),
            ("已经发送给", "就假装"),
            ("就假装", "语气很自然"),
            ("随手分享", "语气很自然"),
        )
        if any(all(token in raw for token in pair) for pair in markers):
            return True
        return (
            any(token in compact for token in ("视频链接转给", "链接转给", "消息转给", "内容转给"))
            and any(token in compact for token in ("已经", "已", "完成", "成功"))
        )

    def _group_wakeup_runtime(self, group: dict[str, Any]) -> dict[str, Any]:
        fatigue = group.get("group_wakeup_fatigue") if isinstance(group.get("group_wakeup_fatigue"), dict) else {}
        high_intensity = {}
        if hasattr(self.plugin, "_group_high_intensity_state"):
            try:
                high_intensity = self.plugin._group_high_intensity_state(group, mutate=False)
            except Exception:
                high_intensity = {}
        value = self._float(fatigue.get("value"))
        limit = self._int(fatigue.get("limit")) or int(getattr(self.plugin, "group_wakeup_fatigue_limit", 5) or 5)
        ratio = max(0.0, min(1.0, value / max(1, limit)))
        if ratio >= 1.0:
            label = "疲劳高"
            level = "high"
        elif ratio >= 0.55:
            label = "有点累"
            level = "medium"
        elif value >= 0.4:
            label = "轻微"
            level = "low"
        else:
            label = "无"
            level = "none"
        return {
            "value": round(value, 2),
            "limit": limit,
            "ratio": round(ratio, 3),
            "label": label,
            "level": level,
            "updated": self.plugin._format_timestamp_elapsed(fatigue.get("updated_ts", 0)),
            "high_intensity": {
                "active": bool(high_intensity.get("active")) if isinstance(high_intensity, dict) else False,
                "merge_active": bool(high_intensity.get("merge_active")) if isinstance(high_intensity, dict) else False,
                "reason": self._single_line(high_intensity.get("reason"), 40) if isinstance(high_intensity, dict) else "",
                "recent_wakeups": self._int(high_intensity.get("recent_wakeups")) if isinstance(high_intensity, dict) else 0,
                "threshold": self._int(high_intensity.get("threshold")) if isinstance(high_intensity, dict) else 0,
                "merge_recent_floor": self._int(high_intensity.get("merge_recent_floor")) if isinstance(high_intensity, dict) else 0,
                "remaining_seconds": self._float(high_intensity.get("remaining_seconds")) if isinstance(high_intensity, dict) else 0.0,
                "merge_seconds": self._float(getattr(self.plugin, "group_high_intensity_merge_seconds", 8)),
                "max_merge_messages": self._int(getattr(self.plugin, "group_high_intensity_max_merge_messages", 8)),
                "merge_scope": self._single_line(getattr(self.plugin, "group_high_intensity_merge_scope", "group"), 20),
            },
        }

    def _group_wakeup_logs(self, group: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        logs = group.get("group_wakeup_logs") if isinstance(group.get("group_wakeup_logs"), list) else []
        items: list[dict[str, Any]] = []
        for raw in reversed(logs[-limit:]):
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    "ts": self._float(raw.get("ts")),
                    "time": self.plugin._format_timestamp_elapsed(raw.get("ts", 0)),
                    "result": self._single_line(raw.get("result"), 32),
                    "type": self._single_line(raw.get("type"), 40),
                    "word": self._single_line(raw.get("word"), 60),
                    "strength": self._single_line(raw.get("strength"), 24),
                    "strength_label": self._single_line(raw.get("strength_label"), 24),
                    "probability": round(self._float(raw.get("probability")), 3),
                    "score": self._int(raw.get("score")),
                    "threshold": self._int(raw.get("threshold")),
                    "intensity": self._single_line(raw.get("intensity"), 20),
                    "help_type": self._single_line(raw.get("help_type"), 30),
                    "reason": self._single_line(raw.get("reason"), 80),
                    "reason_label": self._single_line(raw.get("reason_label"), 80),
                    "reason_detail": self._single_line(raw.get("reason_detail"), 180),
                    "topic_weight": raw.get("topic_weight") if isinstance(raw.get("topic_weight"), dict) else {},
                    "note": self._single_line(raw.get("note"), 180),
                    "sender_id": self._single_line(raw.get("sender_id"), 40),
                    "sender_name": self._single_line(raw.get("sender_name"), 40),
                    "text": self._display_message_text(raw.get("text"), 160),
                    "fatigue_value": round(self._float(raw.get("fatigue_value")), 2),
                    "fatigue_label": self._single_line(raw.get("fatigue_label"), 20),
                }
            )
        return items

    def _group_slang_items(self, group: dict[str, Any], limit: int = 120) -> list[dict[str, Any]]:
        terms = group.get("slang_terms") if isinstance(group.get("slang_terms"), list) else []
        meanings = group.get("slang_meanings") if isinstance(group.get("slang_meanings"), dict) else {}
        indexed: dict[str, dict[str, Any]] = {}
        for raw in terms:
            if isinstance(raw, dict):
                term = self._single_line(raw.get("term"), 40)
                if not term:
                    continue
                indexed[term] = {
                    "term": term,
                    "count": self._int(raw.get("count")),
                    "last_seen_ts": self._float(raw.get("last_seen")),
                    "last_seen": self.plugin._format_timestamp_elapsed(raw.get("last_seen", 0)),
                    "learned": True,
                }
            else:
                term = self._single_line(raw, 40)
                if term:
                    indexed[term] = {"term": term, "count": 0, "last_seen_ts": 0.0, "last_seen": "", "learned": True}
        for term, raw in meanings.items():
            key = self._single_line(term, 40)
            if key and key not in indexed:
                indexed[key] = {"term": key, "count": 0, "last_seen_ts": 0.0, "last_seen": "", "learned": False}

        uncertain_checker = getattr(self.plugin, "_is_uncertain_group_slang_meaning", None)
        items: list[dict[str, Any]] = []
        for term, base in indexed.items():
            raw_meaning = meanings.get(term) if isinstance(meanings.get(term), dict) else {}
            meaning = self._single_line(raw_meaning.get("meaning"), 120) if isinstance(raw_meaning, dict) else ""
            usage = self._single_line(raw_meaning.get("usage"), 120) if isinstance(raw_meaning, dict) else ""
            confidence = min(1.0, self._float(raw_meaning.get("confidence"))) if isinstance(raw_meaning, dict) else 0.0
            web_match = min(1.0, self._float(raw_meaning.get("web_match"))) if isinstance(raw_meaning, dict) else 0.0
            is_uncertain = True
            if meaning:
                if callable(uncertain_checker):
                    is_uncertain = bool(uncertain_checker(meaning, usage))
                else:
                    is_uncertain = any(marker in f"{meaning} {usage}" for marker in ("不确定", "无法判断", "语境不明", "可能是"))
            if meaning and confidence >= 0.55 and not is_uncertain:
                status = "injectable"
                status_label = "会注入"
            elif meaning and confidence < 0.55:
                status = "low_confidence"
                status_label = "低置信度"
            elif meaning and is_uncertain:
                status = "uncertain"
                status_label = "释义不足"
            else:
                status = "pending"
                status_label = "尚未释义"
            items.append(
                {
                    **base,
                    "meaning": meaning,
                    "usage": usage,
                    "type": self._single_line(raw_meaning.get("type"), 24) if isinstance(raw_meaning, dict) else "",
                    "not_owner": self._single_line(raw_meaning.get("not_owner"), 90) if isinstance(raw_meaning, dict) else "",
                    "evidence": self._single_line(raw_meaning.get("evidence"), 160) if isinstance(raw_meaning, dict) else "",
                    "source": self._single_line(raw_meaning.get("source"), 32) if isinstance(raw_meaning, dict) else "",
                    "updated_at": self._single_line(raw_meaning.get("updated_at"), 32) if isinstance(raw_meaning, dict) else "",
                    "confidence": round(confidence, 2),
                    "web_match": round(web_match, 2),
                    "web_evidence": self._single_line(raw_meaning.get("web_evidence"), 220) if isinstance(raw_meaning, dict) else "",
                    "status": status,
                    "status_label": status_label,
                }
            )
        items.sort(
            key=lambda item: (
                item.get("status") != "injectable",
                -self._int(item.get("count")),
                -self._float(item.get("last_seen_ts")),
                item.get("term") or "",
            )
        )
        return items[:limit]

    def _group_summary(self, group_id: str, group: dict[str, Any]) -> dict[str, Any]:
        atmosphere = group.get("atmosphere") if isinstance(group.get("atmosphere"), dict) else {}
        slang_terms = group.get("slang_terms") if isinstance(group.get("slang_terms"), list) else []
        slang_meanings = group.get("slang_meanings") if isinstance(group.get("slang_meanings"), dict) else {}
        members = group.get("members") if isinstance(group.get("members"), dict) else {}
        group_for_filter = group
        group_id_text = str(group_id)
        group_name = self._single_line(group.get("name") or group.get("group_name") or group.get("display_name"), 80)
        if group_name == group_id_text:
            group_name = ""
        cleaner = getattr(self.plugin, "_cleanup_group_slang_terms", None)
        if callable(cleaner):
            try:
                group_for_filter = {
                    "slang_terms": [dict(item) if isinstance(item, dict) else item for item in slang_terms],
                    "slang_meanings": {str(key): dict(value) if isinstance(value, dict) else value for key, value in slang_meanings.items()},
                    "members": {
                        str(user_id): {
                            key: member.get(key)
                            for key in ("name", "identity_name", "display_name", "nickname", "card")
                            if isinstance(member, dict) and key in member
                        }
                        for user_id, member in members.items()
                        if isinstance(member, dict)
                    },
                }
                if cleaner(group_for_filter):
                    slang_terms = group_for_filter.get("slang_terms") if isinstance(group_for_filter.get("slang_terms"), list) else []
            except Exception:
                pass
        promoter = getattr(self.plugin, "_group_slang_term_is_promoted", None)
        if callable(promoter):
            visible_terms: list[Any] = []
            for item in slang_terms:
                try:
                    if not promoter(group_for_filter, item):
                        continue
                except Exception:
                    continue
                if isinstance(item, dict):
                    visible_terms.append({**item, "promoted": True})
                else:
                    visible_terms.append(item)
            slang_terms = visible_terms
        identity_count = sum(1 for item in members.values() if isinstance(item, dict) and item.get("identity_known"))
        wakeup_logs = group.get("group_wakeup_logs") if isinstance(group.get("group_wakeup_logs"), list) else []
        last_wakeup = group.get("last_group_wakeup") if isinstance(group.get("last_group_wakeup"), dict) else {}
        last_interjection = self._sanitize_last_bot_interjection(group.get("last_bot_interjection"))
        return {
            "group_id": group_id_text,
            "name": group_name,
            "group_name": group_name,
            "display_name": group_name or "未命名群聊",
            "enabled": bool(group.get("enabled", True)),
            "allowed_by_mode": self.plugin._group_allowed_by_access_mode(group_id_text),
            "message_count": group.get("message_count", 0),
            "last_seen_ts": group.get("last_seen", 0),
            "last_seen": self.plugin._format_timestamp_elapsed(group.get("last_seen", 0)),
            "member_count": len(members),
            "recognized_member_count": identity_count,
            "recent_message_count": len(group.get("recent_messages") or []),
            "slang_count": len(slang_terms),
            "slang_meaning_count": len(slang_meanings),
            "slang_terms": slang_terms[:16],
            "topic_count": len(group.get("topic_threads") or []),
            "episode_count": len(group.get("group_episodes") or []),
            "relationship_edge_count": len(group.get("relationship_edges") or {}),
            "interject_today": group.get("interject_today", 0),
            "effective_interject_max_daily": (
                self.plugin._effective_group_interject_max_daily()
                if hasattr(self.plugin, "_effective_group_interject_max_daily")
                else getattr(self.plugin, "group_interject_max_daily", 0)
            ),
            "effective_interject_min_interval_minutes": (
                self.plugin._effective_group_interject_min_interval_minutes()
                if hasattr(self.plugin, "_effective_group_interject_min_interval_minutes")
                else getattr(self.plugin, "group_interject_min_interval_minutes", 0)
            ),
            "last_interject": self.plugin._format_timestamp_elapsed(group.get("last_interject_at", 0)),
            "last_bot_interjection": last_interjection,
            "wakeup_log_count": len(wakeup_logs),
            "wakeup_fatigue": self._group_wakeup_runtime(group),
            "last_group_wakeup": {
                "time": self.plugin._format_timestamp_elapsed(last_wakeup.get("ts", 0)),
                "type": self._single_line(last_wakeup.get("type"), 40),
                "word": self._single_line(last_wakeup.get("word"), 60),
                "strength_label": self._single_line(last_wakeup.get("strength_label"), 24),
                "score": self._int(last_wakeup.get("score")),
                "threshold": self._int(last_wakeup.get("threshold")),
                "intensity": self._single_line(last_wakeup.get("intensity"), 20),
                "help_type": self._single_line(last_wakeup.get("help_type"), 30),
                "reason": self._single_line(last_wakeup.get("reason"), 80),
                "reason_label": self._single_line(last_wakeup.get("reason_label"), 80),
                "reason_detail": self._single_line(last_wakeup.get("reason_detail"), 180),
                "sender_name": self._single_line(last_wakeup.get("sender_name"), 40),
                "text": self._display_message_text(last_wakeup.get("text"), 120),
            } if last_wakeup else {},
            "atmosphere": {
                "mood": atmosphere.get("mood", ""),
                "heat": atmosphere.get("heat", ""),
                "last_summary": atmosphere.get("summary", ""),
            },
        }

    def _sanitize_last_bot_interjection(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            return {}
        item = dict(value)
        item["text"] = self._display_message_text(item.get("text"), 120)
        if not item["text"] and not item.get("has_image"):
            return {}
        return item

    def _group_topic_thread_items(self, group: dict[str, Any], limit: int = 16) -> list[dict[str, Any]]:
        threads = group.get("topic_threads") if isinstance(group.get("topic_threads"), list) else []
        members = group.get("members") if isinstance(group.get("members"), dict) else {}
        now = time.time()
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(threads[:limit]):
            if not isinstance(raw, dict):
                continue
            started_ts = self._float(raw.get("started_ts"))
            last_ts = self._float(raw.get("last_ts"))
            duration_seconds = max(0.0, (last_ts or started_ts) - started_ts) if started_ts else 0.0
            participants = raw.get("participants") if isinstance(raw.get("participants"), list) else []
            participant_items = []
            for user_id in participants[:8]:
                uid = self._single_line(user_id, 40)
                member = members.get(uid) if isinstance(members.get(uid), dict) else {}
                name = self._single_line(
                    member.get("display_name")
                    or member.get("nickname")
                    or member.get("name")
                    or member.get("card")
                    or uid,
                    24,
                )
                if uid:
                    participant_items.append({"id": uid, "name": name or uid})
            examples = []
            for example in (raw.get("recent_examples") if isinstance(raw.get("recent_examples"), list) else [])[-4:]:
                if not isinstance(example, dict):
                    continue
                examples.append(
                    {
                        "name": self._single_line(example.get("name"), 24),
                        "text": self._single_line(example.get("text"), 120),
                        "time": self.plugin._format_timestamp_elapsed(example.get("ts", 0)),
                    }
                )
            message_count = self._int(raw.get("message_count"))
            freshness = max(0.0, now - last_ts) if last_ts else 0.0
            heat = min(100, max(8, message_count * 10 + len(participant_items) * 8 - int(freshness / 600) * 5))
            status = "活跃" if freshness <= 15 * 60 else "刚冷却" if freshness <= 90 * 60 else "历史"
            title = self._single_line(raw.get("title") or raw.get("topic") or raw.get("summary"), 80)
            items.append(
                {
                    "rank": index + 1,
                    "title": title or "未命名话题",
                    "summary": self._single_line(raw.get("summary"), 180),
                    "message_count": message_count,
                    "participant_count": len(participants),
                    "participants": participant_items,
                    "recent_examples": examples,
                    "started": self.plugin._format_timestamp_elapsed(started_ts),
                    "last_seen": self.plugin._format_timestamp_elapsed(last_ts),
                    "duration": self._format_duration(duration_seconds),
                    "heat": heat,
                    "status": status,
                    "bot_joined": bool(raw.get("bot_joined")),
                }
            )
        return items

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(0, int(seconds or 0))
        if seconds < 60:
            return "不到 1 分钟"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} 分钟"
        hours = minutes // 60
        rest = minutes % 60
        return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"

    def _skill_growth_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("skill_growth") if isinstance(data.get("skill_growth"), dict) else {}
        skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
        items: list[dict[str, Any]] = []
        for raw in skills.values():
            if not isinstance(raw, dict):
                continue
            level = self._int(raw.get("level")) or 1
            exp = self._float(raw.get("exp"))
            next_exp = self.plugin._skill_next_exp(level) if hasattr(self.plugin, "_skill_next_exp") else None
            prev_exp = {1: 0, 2: 100, 3: 260, 4: 520, 5: 900, 6: 1400}.get(level, 0)
            if next_exp:
                progress = max(0, min(100, int(((exp - prev_exp) / max(1, next_exp - prev_exp)) * 100)))
            else:
                progress = 100
            logs = raw.get("recent_logs") if isinstance(raw.get("recent_logs"), list) else []
            keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
            aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
            items.append(
                {
                    "id": self._single_line(raw.get("id"), 32),
                    "name": self._single_line(raw.get("name"), 32),
                    "category": self._single_line(raw.get("category"), 24),
                    "keywords": [self._single_line(item, 24) for item in keywords if self._single_line(item, 24)][:16],
                    "aliases": [self._single_line(item, 24) for item in aliases if self._single_line(item, 24)][:12],
                    "hidden": bool(raw.get("hidden")),
                    "frozen": bool(raw.get("frozen")),
                    "level": level,
                    "level_title": self.plugin._skill_level_title(level) if hasattr(self.plugin, "_skill_level_title") else self._single_line(raw.get("level_title"), 24),
                    "description": self.plugin._skill_level_description(level) if hasattr(self.plugin, "_skill_level_description") else "",
                    "exp": round(exp, 2),
                    "next_exp": next_exp,
                    "progress": progress,
                    "training_count": self._int(raw.get("training_count")),
                    "last_trained": self.plugin._format_timestamp_elapsed(raw.get("last_trained_ts", 0)),
                    "recent_logs": [
                        {
                            "activity": self._single_line(log.get("activity"), 80),
                            "exp": self._float(log.get("exp")),
                            "time": self.plugin._format_timestamp_elapsed(log.get("ts", 0)),
                            "level_up": bool(log.get("level_up")),
                        }
                        for log in logs[-4:]
                        if isinstance(log, dict)
                    ],
                }
            )
        items.sort(key=lambda item: (bool(item.get("hidden")), -item["level"], -item["exp"], -item["training_count"], item.get("category") or "", item.get("name") or ""))
        return {
            "enabled": bool(getattr(self.plugin, "enable_skill_growth_simulation", False)),
            "rate": float(getattr(self.plugin, "skill_growth_rate", 1.0) or 1.0),
            "passive_injection": bool(getattr(self.plugin, "enable_skill_growth_passive_injection", False)),
            "schedule_influence": bool(getattr(self.plugin, "enable_skill_growth_schedule_influence", False)),
            "schedule_influence_strength": float(getattr(self.plugin, "skill_growth_schedule_influence_strength", 0.35) or 0.0),
            "updated": self.plugin._format_timestamp_elapsed(state.get("updated_ts", 0)),
            "skill_count": len(items),
            "hidden_count": sum(1 for item in items if item.get("hidden")),
            "frozen_count": sum(1 for item in items if item.get("frozen")),
            "items": items[:120],
        }

    def _personal_goal_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        goals = data.get("personal_goals") if isinstance(data.get("personal_goals"), list) else []
        items: list[dict[str, Any]] = []
        status_labels = {"active": "进行中", "paused": "已暂停", "completed": "已完成", "abandoned": "已放弃"}
        for raw in goals:
            if not isinstance(raw, dict):
                continue
            status = self.plugin._personal_goal_status(raw.get("status"))
            logs = raw.get("recent_logs") if isinstance(raw.get("recent_logs"), list) else []
            items.append(
                {
                    "id": self._single_line(raw.get("id"), 40),
                    "title": self._single_line(raw.get("title"), 60),
                    "category": self._single_line(raw.get("category"), 24) or "生活",
                    "status": status,
                    "status_label": status_labels.get(status, status),
                    "progress": max(0, min(100, self._int(raw.get("progress")))),
                    "next_step": self._single_line(raw.get("next_step"), 100),
                    "note": self._single_line(raw.get("note"), 160),
                    "keywords": [self._single_line(item, 32) for item in (raw.get("keywords") or []) if self._single_line(item, 32)][:16],
                    "auto_step": max(1, min(50, self._int(raw.get("auto_step")) or 10)),
                    "created": self.plugin._format_timestamp_elapsed(raw.get("created_at", 0)),
                    "updated": self.plugin._format_timestamp_elapsed(raw.get("updated_at", 0)),
                    "last_progress": self.plugin._format_timestamp_elapsed(raw.get("last_progress_at", 0)),
                    "recent_logs": [
                        {
                            "kind": self._single_line(log.get("kind"), 24),
                            "progress": self._int(log.get("progress")),
                            "evidence": self._single_line(log.get("evidence"), 100),
                            "time": self.plugin._format_timestamp_elapsed(log.get("ts", 0)),
                        }
                        for log in logs[-5:]
                        if isinstance(log, dict)
                    ],
                }
            )
        items.sort(key=lambda item: ({"active": 0, "paused": 1, "completed": 2, "abandoned": 3}.get(item["status"], 4), -item["progress"], item["title"]))
        return {
            "enabled": bool(getattr(self.plugin, "enable_personal_goals", True)),
            "auto_progress": bool(getattr(self.plugin, "enable_personal_goal_auto_progress", True)),
            "share_cooldown_hours": float(getattr(self.plugin, "personal_goal_share_cooldown_hours", 12.0) or 12.0),
            "stall_days": int(getattr(self.plugin, "personal_goal_stall_days", 3) or 3),
            "active_count": sum(1 for item in items if item["status"] == "active"),
            "completed_count": sum(1 for item in items if item["status"] == "completed"),
            "items": items[:80],
        }

    def _food_menu_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("food_menu") if isinstance(data.get("food_menu"), dict) else {}
        raw_items = state.get("items") if isinstance(state.get("items"), list) else []
        type_label = getattr(self.plugin, "_food_menu_type_label", None)
        time_label = getattr(self.plugin, "_food_menu_time_label", None)

        def _list(value: Any, *, limit: int = 12, item_limit: int = 24) -> list[str]:
            raw = value if isinstance(value, list) else re.split(r"[,，、\n/|]+", str(value or ""))
            items: list[str] = []
            for part in raw:
                item = self._single_line(part, item_limit)
                if item and item not in items:
                    items.append(item)
            return items[:limit]

        items: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            name = self._single_line(raw.get("name"), 40)
            if not name:
                continue
            item_type = self._single_line(raw.get("type"), 20) or "dish"
            counts[item_type] = counts.get(item_type, 0) + 1
            times = _list(raw.get("times"), limit=5, item_limit=16)
            items.append(
                {
                    "id": self._single_line(raw.get("id"), 48),
                    "name": name,
                    "type": item_type,
                    "type_label": type_label(item_type) if callable(type_label) else item_type,
                    "category": self._single_line(raw.get("category"), 24),
                    "tags": _list(raw.get("tags"), limit=10, item_limit=16),
                    "times": times,
                    "time_labels": [time_label(value) if callable(time_label) else value for value in times],
                    "avoid": _list(raw.get("avoid"), limit=8, item_limit=24),
                    "aliases": _list(raw.get("aliases"), limit=10, item_limit=24),
                    "note": self._single_line(raw.get("note"), 100),
                    "favorite": bool(raw.get("favorite")),
                    "hidden": bool(raw.get("hidden")),
                    "use_count": self._int(raw.get("use_count")),
                    "last_used": self.plugin._format_timestamp_elapsed(raw.get("last_used_at", 0)),
                    "last_recommended": self.plugin._format_timestamp_elapsed(raw.get("last_recommended_at", 0)),
                    "updated": self.plugin._format_timestamp_elapsed(raw.get("updated_ts", 0)),
                }
            )
        items.sort(key=lambda item: (bool(item.get("hidden")), not bool(item.get("favorite")), item.get("type_label", ""), item.get("name", "")))
        return {
            "items": items[:160],
            "total": len(items),
            "visible_count": sum(1 for item in items if not item.get("hidden")),
            "favorite_count": sum(1 for item in items if item.get("favorite")),
            "hidden_count": sum(1 for item in items if item.get("hidden")),
            "counts": counts,
            "updated": self.plugin._format_timestamp_elapsed(state.get("updated_ts", 0)),
        }

    def _external_ability_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        runtime_getter = getattr(self.plugin, "external_proactive_abilities", None)
        if callable(runtime_getter):
            raw_items = runtime_getter()
        else:
            store = data.get("external_proactive_abilities") if isinstance(data.get("external_proactive_abilities"), dict) else {}
            raw_items = list(store.values()) if isinstance(store, dict) else []
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
            schema = raw.get("config_schema") if isinstance(raw.get("config_schema"), dict) else {}
            items.append(
                {
                    "name": self._single_line(raw.get("name"), 64),
                    "module": self._single_line(raw.get("module"), 24) or "外部主动能力",
                    "label": self._single_line(raw.get("label"), 32) or self._single_line(raw.get("name"), 64),
                    "description": self._single_line(raw.get("description"), 180),
                    "when": self._single_line(raw.get("when"), 140),
                    "use_for": self._single_line(raw.get("use_for"), 140),
                    "avoid": self._single_line(raw.get("avoid"), 140),
                    "enabled": bool(raw.get("enabled")),
                    "available": bool(raw.get("available")),
                    "registered": bool(raw.get("registered")),
                    "share_probability": max(0.0, min(1.0, self._float(raw.get("share_probability")))),
                    "min_interval_hours": max(0.0, self._float(raw.get("min_interval_hours"))),
                    "config": config,
                    "config_schema": schema,
                    "last_executed": self.plugin._format_timestamp_elapsed(raw.get("last_executed_ts", 0)),
                    "last_status": self._single_line(raw.get("last_status"), 160),
                    "last_summary": self._single_line(raw.get("last_summary"), 160),
                    "success_count": self._int(raw.get("success_count")),
                    "failure_count": self._int(raw.get("failure_count")),
                    "updated": self.plugin._format_timestamp_elapsed(raw.get("updated_ts", 0)),
                }
            )
        items.sort(key=lambda item: (not item["enabled"], not item["available"], item["module"], item["label"]))
        return {
            "total": len(items),
            "enabled_count": sum(1 for item in items if item["enabled"]),
            "available_count": sum(1 for item in items if item["available"]),
            "items": items,
        }

    def _proactive_chat_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        installed = False
        detector = getattr(self.plugin, "_integrated_plugin_installed", None)
        if callable(detector):
            try:
                installed = bool(detector("astrbot_plugin_proactive_chat"))
            except Exception:
                installed = False
        enabled = bool(getattr(self.plugin, "enable_proactive_chat_integration", True))
        review_mode = str(getattr(self.plugin, "proactive_chat_bridge_review_mode", "local") or "local")
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        linked_users = 0
        last_sent_at = 0.0
        for user in users.values():
            if not isinstance(user, dict):
                continue
            sent_at = self._float(user.get("proactive_chat_bridge_last_sent_at"))
            if sent_at <= 0:
                continue
            linked_users += 1
            last_sent_at = max(last_sent_at, sent_at)
        formatter = getattr(self.plugin, "_format_timestamp_elapsed", None)
        last_sent = formatter(last_sent_at) if last_sent_at > 0 and callable(formatter) else ""
        runtime_status: dict[str, Any] = {}
        runtime_bridge = getattr(self.plugin, "_proactive_chat_runtime_bridge", None)
        status_getter = getattr(runtime_bridge, "status", None)
        if callable(status_getter):
            try:
                value = status_getter()
                runtime_status = value if isinstance(value, dict) else {}
            except Exception as exc:
                runtime_status = {
                    "mode": "fallback",
                    "mode_label": "发送前兼容",
                    "last_error": self._single_line(exc, 160),
                }
        runtime_mode = str(runtime_status.get("mode") or ("fallback" if installed and enabled else "waiting"))
        runtime_label = str(runtime_status.get("mode_label") or ("发送前兼容" if installed and enabled else "等待运行实例"))
        return {
            "installed": installed,
            "enabled": enabled,
            "active": bool(installed and enabled),
            "deep_active": bool(runtime_status.get("attached")),
            "runtime_mode": runtime_mode,
            "runtime_mode_label": runtime_label,
            "runtime_version": self._single_line(runtime_status.get("version"), 40),
            "runtime_method_count": self._int(runtime_status.get("method_count")),
            "runtime_methods": list(runtime_status.get("methods") or []),
            "runtime_last_event": self._single_line(runtime_status.get("last_event"), 180),
            "runtime_last_error": self._single_line(runtime_status.get("last_error"), 180),
            "runtime_open_attempts": self._int(runtime_status.get("open_attempt_count")),
            "runtime_counters": dict(runtime_status.get("counters") or {}),
            "scope": "private",
            "review_mode": review_mode,
            "review_mode_label": "跟随主动终审" if review_mode == "follow_proactive_review" else "轻量本地复核",
            "linked_user_count": linked_users,
            "last_sent_at": last_sent_at,
            "last_sent": last_sent,
        }

    def _feature_flags(self) -> dict[str, bool]:
        keys = [
            "enable_proactive_only_mode",
            "enable_proactive_chat_integration",
            "enable_mai_style_integration",
            "enable_companion_memory",
            "enable_expression_learning",
            "enable_intent_emotion_analysis",
            "enable_passive_response_review",
            "enable_proactive_message_review",
            "enable_smart_silence",
            "enable_llm_proactive_message",
            "enable_llm_proactive_persona_judge",
            "enable_maslow_motivation_experiment",
            "enable_experimental_motivation_model",
            "enable_personality_iteration_experiment",
            "enable_passive_topic_suppression",
            "enable_relationship_state_machine",
            "enable_emotion_simulation",
            "enable_dialogue_episode_memory",
            "enable_open_loop_tracking",
            "enable_user_habit_learning",
            "enable_food_menu_recommendation",
            "enable_personal_goals",
            "enable_humanized_states",
            "enable_health_state",
            "enable_hunger_state",
            "enable_segmented_proactive_reply",
            "enable_proactive_quote_trigger_message",
            "enable_quote_group_reply",
            "enable_quote_group_interjection",
            "enable_quote_private_proactive",
            "enable_photo_text_action",
            "enable_screen_glance_action",
            "enable_poke_action",
            "enable_voice_action",
            "enable_photo_reference_image",
            "inject_passive_states",
            "enable_passive_state_delta_injection",
            "enable_cycle_state",
            "enable_skill_growth_simulation",
            "enable_skill_growth_passive_injection",
            "enable_personal_goals",
            "enable_message_debounce",
            "enable_smart_message_debounce",
            "enable_recall_enhancement",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "enable_forbidden_word_recall",
            "enable_semantic_message_debounce",
            "enable_environment_perception",
            "enable_balance_awareness",
            "enable_holiday_perception",
            "enable_platform_perception",
            "enable_model_perception",
            "enable_worldview_perception",
            "enable_lunar_perception",
            "enable_solar_term_perception",
            "enable_almanac_perception",
            "enable_group_companion",
            "enable_group_slang_learning",
            "enable_group_member_profiles",
            "enable_group_context_injection",
            "enable_group_injection_guard",
            "enable_group_persona_denoise",
            "enable_forward_message_adaptation",
            "enable_group_scene_awareness",
            "enable_group_reality_promise_guard",
            "enable_group_wakeup_enhancement",
            "enable_group_wakeup_question",
            "enable_group_wakeup_cold_group",
            "enable_group_high_intensity_mode",
            "enable_group_air_reply_guard",
            "enable_private_image_self_recognition",
            "enable_backup_external_image_api",
            "enable_private_image_gif_enhancement",
            "enable_group_conversation_followup",
            "enable_group_interjection",
            "enable_group_repeat_follow",
            "group_repeat_count_distinct_users_only",
            "enable_group_topic_threads",
            "enable_group_episode_memory",
            "enable_group_interjection_feedback",
            "enable_group_slang_meanings",
            "enable_group_slang_web_search",
            "enable_group_relationship_graph",
            "enable_group_privacy_guard",
            "enable_worldbook_member_recognition",
            "enable_cross_user_memory_bridge",
            "enable_atrelay_tools",
            "enable_livingmemory_integration",
            "enable_bilibili_integration",
            "enable_bilibili_boredom_watch",
            "enable_news_integration",
            "enable_news_daily_hot_read",
            "enable_news_boredom_read",
            "enable_ai_daily_watch",
            "enable_external_event_self_link",
            "enable_web_exploration",
            "enable_web_exploration_boredom_search",
            "enable_qzone_integration",
            "enable_qzone_life_publish",
            "enable_qzone_generated_image_publish",
            "enable_qzone_comment_inbox",
            "enable_qzone_emotional_vent_publish",
            "enable_private_reading_integration",
            "enable_private_reading_boredom_read",
            "enable_private_reading_ask_recommendation",
            "enable_private_reading_preference_influence",
            "enable_unanswered_screen_peek_followup",
            "enable_screen_glance_action",
            "enable_poke_action",
            "enable_voice_action",
            "enable_yesterday_screen_diary_context",
            "enable_tts_enhancement",
            "enable_creative_writing",
            "creative_hidden_mode",
            "enable_reply_interception_forward",
        ]
        values = {key: bool(getattr(self.plugin, key, False)) for key in keys}
        try:
            bilibili_available = bool(getattr(self.plugin, "_bilibili_available", lambda: False)())
        except Exception:
            bilibili_available = False
        try:
            screen_companion_available = bool(self._screen_companion_available())
        except Exception:
            screen_companion_available = False
        try:
            private_reading_available = bool(getattr(self.plugin, "_jm_cosmos_available", lambda: False)())
        except Exception:
            private_reading_available = False
        values["enable_livingmemory_integration"] = bool(getattr(self.plugin, "enable_livingmemory_integration", False))
        values["enable_bilibili_integration"] = bool(bilibili_available and getattr(self.plugin, "enable_bilibili_integration", False))
        values["enable_bilibili_boredom_watch"] = bool(bilibili_available and getattr(self.plugin, "enable_bilibili_boredom_watch", False))
        values["enable_qzone_integration"] = bool(getattr(self.plugin, "enable_qzone_integration", False))
        values["enable_qzone_life_publish"] = bool(getattr(self.plugin, "enable_qzone_life_publish", False))
        values["enable_qzone_generated_image_publish"] = bool(getattr(self.plugin, "enable_qzone_generated_image_publish", False))
        values["enable_qzone_comment_inbox"] = bool(getattr(self.plugin, "enable_qzone_comment_inbox", False))
        values["enable_qzone_emotional_vent_publish"] = bool(getattr(self.plugin, "enable_qzone_emotional_vent_publish", False))
        values["enable_yesterday_screen_diary_context"] = bool(screen_companion_available and getattr(self.plugin, "enable_yesterday_screen_diary_context", False))
        values["enable_private_reading_integration"] = bool(private_reading_available and getattr(self.plugin, "enable_jm_cosmos_integration", False))
        values["enable_private_reading_boredom_read"] = bool(private_reading_available and getattr(self.plugin, "enable_jm_cosmos_boredom_read", False))
        values["enable_private_reading_ask_recommendation"] = bool(private_reading_available and getattr(self.plugin, "enable_private_reading_ask_recommendation", False))
        values["enable_private_reading_preference_influence"] = bool(private_reading_available and getattr(self.plugin, "enable_private_reading_preference_influence", True))
        return values

    def _proactive_only_mode_snapshot(self) -> dict[str, Any]:
        clearer = getattr(self.plugin, "_clear_proactive_only_temp_unlocks_if_mode_off", None)
        if callable(clearer):
            clearer()
        unlocks_getter = getattr(self.plugin, "_proactive_only_unlock_store", None)
        label_getter = getattr(self.plugin, "_proactive_only_unlock_label", None)
        related_getter = getattr(self.plugin, "_related_proactive_only_unlock_keys", None)
        unlocks = sorted(unlocks_getter() if callable(unlocks_getter) else [])

        def label(key: str) -> str:
            return label_getter(key) if callable(label_getter) else key

        related: dict[str, list[dict[str, str]]] = {}
        locked_keys = [
            "inject_passive_states",
            "enable_intent_emotion_analysis",
            "enable_passive_topic_suppression",
            "enable_environment_perception",
            "enable_message_debounce",
            "enable_recall_enhancement",
            "enable_private_image_self_recognition",
            "enable_forward_message_adaptation",
            "enable_group_companion",
            "enable_skill_growth_passive_injection",
            "enable_food_menu_recommendation",
            "enable_private_reading_preference_influence",
            "enable_worldbook_member_recognition",
            "enable_atrelay_tools",
            "enable_livingmemory_integration",
            "enable_tts_enhancement",
            "enable_segmented_proactive_reply",
        ]
        for key in locked_keys:
            keys = related_getter(key) if callable(related_getter) else []
            related[key] = [{"key": item, "label": label(item)} for item in keys]
        return {
            "enabled": bool(getattr(self.plugin, "enable_proactive_only_mode", False)),
            "unlocked": [{"key": key, "label": label(key)} for key in unlocks],
            "related": related,
        }

    def _provider_settings(self) -> dict[str, str]:
        keys = [
            "FAST_RESPONSE_PROVIDER_ID",
            "COMPLEX_REASONING_PROVIDER_ID",
            "CREATIVE_MODEL_PROVIDER_ID",
            "LLM_PROVIDER_ID",
            "MAI_STYLE_PROVIDER_ID",
            "DAILY_PLAN_PROVIDER_ID",
            "DETAIL_ENHANCEMENT_PROVIDER_ID",
            "DREAM_DIARY_PROVIDER_ID",
            "CREATIVE_PROVIDER_ID",
            "CREATIVE_OUTLINE_PROVIDER_ID",
            "CREATIVE_REVIEW_PROVIDER_ID",
            "VOICE_PROMPT_PROVIDER_ID",
            "tts_conversion_provider_id",
            "PHOTO_PROMPT_PROVIDER_ID",
            "NARRATION_PROVIDER_ID",
            "HISTORY_SUMMARY_PROVIDER_ID",
            "RESPONSE_REVIEW_PROVIDER_ID",
            "SMART_SILENCE_PROVIDER_ID",
            "PROACTIVE_PERSONA_JUDGE_PROVIDER_ID",
            "TROUBLESHOOTING_PROVIDER_ID",
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID",
            "REST_WAKEUP_PROVIDER_ID",
            "RELATIONSHIP_ANALYSIS_PROVIDER_ID",
            "EMOTION_JUDGEMENT_PROVIDER_ID",
            "COMPANION_MEMORY_PROVIDER_ID",
            "DIALOGUE_EPISODE_PROVIDER_ID",
            "GROUP_INTERJECT_PROVIDER_ID",
            "GROUP_EPISODE_PROVIDER_ID",
            "GROUP_SLANG_PROVIDER_ID",
            "GROUP_FOLLOWUP_JUDGE_PROVIDER_ID",
            "FORWARD_MESSAGE_PROVIDER_ID",
            "PLUGIN_VISION_PROVIDER_ID",
            "PRIVATE_READING_VISION_PROVIDER_ID",
            "NEWS_PROVIDER_ID",
            "WEB_EXPLORATION_PROVIDER_ID",
        ]
        for key in sorted(self._schema_provider_keys(public_only=True)):
            if key not in keys:
                keys.append(key)
        values = {key: self._config_get(key) for key in keys}
        if not values.get("FAST_RESPONSE_PROVIDER_ID"):
            values["FAST_RESPONSE_PROVIDER_ID"] = str(getattr(self.plugin, "fast_response_provider_id", "") or "")
        if not values.get("COMPLEX_REASONING_PROVIDER_ID"):
            values["COMPLEX_REASONING_PROVIDER_ID"] = str(getattr(self.plugin, "complex_reasoning_provider_id", "") or "")
        if not values.get("CREATIVE_MODEL_PROVIDER_ID"):
            values["CREATIVE_MODEL_PROVIDER_ID"] = str(getattr(self.plugin, "creative_model_provider_id", "") or "")
        if not values.get("PLUGIN_VISION_PROVIDER_ID"):
            values["PLUGIN_VISION_PROVIDER_ID"] = str(getattr(self.plugin, "plugin_vision_provider_id", "") or "")
        if not values.get("PRIVATE_READING_VISION_PROVIDER_ID"):
            values["PRIVATE_READING_VISION_PROVIDER_ID"] = str(getattr(self.plugin, "jm_cosmos_vision_provider_id", "") or "")
        if not values.get("DREAM_DIARY_PROVIDER_ID"):
            values["DREAM_DIARY_PROVIDER_ID"] = str(getattr(self.plugin, "dream_diary_provider_id", "") or "")
        if not values.get("SMART_MESSAGE_DEBOUNCE_PROVIDER_ID"):
            values["SMART_MESSAGE_DEBOUNCE_PROVIDER_ID"] = str(getattr(self.plugin, "smart_message_debounce_provider_id", "") or "")
        if not values.get("SMART_SILENCE_PROVIDER_ID"):
            values["SMART_SILENCE_PROVIDER_ID"] = str(getattr(self.plugin, "smart_silence_provider_id", "") or "")
        if not values.get("REST_WAKEUP_PROVIDER_ID"):
            values["REST_WAKEUP_PROVIDER_ID"] = str(getattr(self.plugin, "rest_wakeup_provider_id", "") or "")
        if not values.get("PROACTIVE_PERSONA_JUDGE_PROVIDER_ID"):
            values["PROACTIVE_PERSONA_JUDGE_PROVIDER_ID"] = str(getattr(self.plugin, "proactive_persona_judge_provider_id", "") or "")
        if not values.get("tts_conversion_provider_id"):
            values["tts_conversion_provider_id"] = str(getattr(self.plugin, "tts_conversion_provider_id", "") or "")
        return values

    def _deepseek_peak_routing_summary(self) -> dict[str, Any]:
        getter = getattr(self.plugin, "_deepseek_peak_status", None)
        if not callable(getter):
            return {"enabled": False, "active": False, "configured": False}
        try:
            return dict(getter())
        except Exception as exc:
            return {
                "enabled": bool(getattr(self.plugin, "enable_deepseek_peak_replacement", False)),
                "active": False,
                "configured": False,
                "error": self._single_line(exc, 160),
            }

    @staticmethod
    def _normalize_provider_mode_value(value: Any) -> str:
        text = str(value or "").strip().lower()
        return "precision" if text in {"precision", "precise", "advanced", "精准", "精准配置", "分流"} else "quick"

    def _precision_bundle_from_quick(self, values: dict[str, str]) -> dict[str, str]:
        fast = self._single_line(values.get("FAST_RESPONSE_PROVIDER_ID"), 160)
        complex_model = self._single_line(values.get("COMPLEX_REASONING_PROVIDER_ID") or values.get("LLM_PROVIDER_ID"), 160)
        creative = self._single_line(values.get("CREATIVE_MODEL_PROVIDER_ID"), 160)
        plugin_vision = self._single_line(values.get("PLUGIN_VISION_PROVIDER_ID"), 160)
        return {
            "LLM_PROVIDER_ID": complex_model,
            "MAI_STYLE_PROVIDER_ID": fast or complex_model,
            "DAILY_PLAN_PROVIDER_ID": complex_model,
            "DETAIL_ENHANCEMENT_PROVIDER_ID": complex_model,
            "HISTORY_SUMMARY_PROVIDER_ID": complex_model,
            "RELATIONSHIP_ANALYSIS_PROVIDER_ID": complex_model,
            "COMPANION_MEMORY_PROVIDER_ID": complex_model,
            "DIALOGUE_EPISODE_PROVIDER_ID": complex_model,
            "GROUP_EPISODE_PROVIDER_ID": complex_model,
            "FORWARD_MESSAGE_PROVIDER_ID": complex_model,
            "PROACTIVE_PERSONA_JUDGE_PROVIDER_ID": complex_model,
            "RESPONSE_REVIEW_PROVIDER_ID": fast or complex_model,
            "SMART_SILENCE_PROVIDER_ID": fast or complex_model,
            "TROUBLESHOOTING_PROVIDER_ID": fast or complex_model,
            "EMOTION_JUDGEMENT_PROVIDER_ID": fast or complex_model,
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID": fast or complex_model,
            "REST_WAKEUP_PROVIDER_ID": fast or complex_model,
            "GROUP_FOLLOWUP_JUDGE_PROVIDER_ID": fast,
            "GROUP_INTERJECT_PROVIDER_ID": fast or complex_model,
            "GROUP_SLANG_PROVIDER_ID": fast or complex_model,
            "VOICE_PROMPT_PROVIDER_ID": fast or complex_model,
            "tts_conversion_provider_id": fast or complex_model,
            "NARRATION_PROVIDER_ID": fast or complex_model,
            "NEWS_PROVIDER_ID": fast or complex_model,
            "WEB_EXPLORATION_PROVIDER_ID": fast or complex_model,
            "CREATIVE_PROVIDER_ID": creative or complex_model,
            "CREATIVE_OUTLINE_PROVIDER_ID": creative or complex_model,
            "CREATIVE_REVIEW_PROVIDER_ID": creative or complex_model,
            "DREAM_DIARY_PROVIDER_ID": creative or complex_model,
            "PHOTO_PROMPT_PROVIDER_ID": creative or complex_model,
            "PRIVATE_READING_VISION_PROVIDER_ID": plugin_vision,
        }

    def _quick_bundle_from_precision(self, values: dict[str, str]) -> dict[str, str]:
        fast = self._single_line(
            values.get("FAST_RESPONSE_PROVIDER_ID")
            or values.get("RESPONSE_REVIEW_PROVIDER_ID")
            or values.get("SMART_MESSAGE_DEBOUNCE_PROVIDER_ID")
            or values.get("SMART_SILENCE_PROVIDER_ID")
            or values.get("MAI_STYLE_PROVIDER_ID"),
            160,
        )
        complex_model = self._single_line(
            values.get("COMPLEX_REASONING_PROVIDER_ID")
            or values.get("LLM_PROVIDER_ID")
            or values.get("DAILY_PLAN_PROVIDER_ID")
            or values.get("COMPANION_MEMORY_PROVIDER_ID")
            or values.get("MAI_STYLE_PROVIDER_ID"),
            160,
        )
        creative = self._single_line(
            values.get("CREATIVE_MODEL_PROVIDER_ID")
            or values.get("CREATIVE_PROVIDER_ID")
            or values.get("DREAM_DIARY_PROVIDER_ID")
            or values.get("PHOTO_PROMPT_PROVIDER_ID")
            or complex_model,
            160,
        )
        plugin_vision = self._single_line(
            values.get("PLUGIN_VISION_PROVIDER_ID")
            or values.get("PRIVATE_READING_VISION_PROVIDER_ID")
            or values.get("NARRATION_PROVIDER_ID"),
            160,
        )
        return {
            "FAST_RESPONSE_PROVIDER_ID": fast,
            "COMPLEX_REASONING_PROVIDER_ID": complex_model,
            "CREATIVE_MODEL_PROVIDER_ID": creative,
            "PLUGIN_VISION_PROVIDER_ID": plugin_vision,
        }

    def _expand_provider_overwrite_bundle(self, mode: str, values: dict[str, str]) -> dict[str, str]:
        merged = {key: self._single_line(value, 160) for key, value in self._provider_settings().items()}
        for key, value in values.items():
            if key in self._allowed_provider_keys():
                merged[key] = self._single_line(value, 160)
        if self._normalize_provider_mode_value(mode) == "quick":
            merged.update(self._precision_bundle_from_quick(merged))
        else:
            merged.update(self._quick_bundle_from_precision(merged))
        return {key: self._single_line(value, 160) for key, value in merged.items() if key in self._allowed_provider_keys()}

    def _migration_export_options_from_request(self) -> set[str]:
        raw = request.args.get("sections") or ""
        if not raw:
            return {"basic", "relations", "food_skills"}
        options = {part.strip().lower() for part in re.split(r"[,，\s]+", raw) if part.strip()}
        allowed = {"basic", "relations", "food_skills", "providers", "sensitive"}
        selected = {item for item in options if item in allowed}
        return selected or {"basic", "relations", "food_skills"}

    async def _apply_migration_normalized(self, normalized: dict[str, Any], *, mode: str, conflict: str) -> dict[str, Any]:
        before = await self._build_migration_package(include_all=True)
        backup_path = self._write_migration_backup(before)

        changed_config: dict[str, Any] = {}
        for key, value in normalized.get("features", {}).items():
            normalized_value = self._normalize_bool_value(value)
            current_value = self._normalize_bool_value(getattr(self.plugin, key, self._config_get(key)))
            if self._should_apply_migration_value(current_value, normalized_value, conflict):
                changed_config[key] = normalized_value
        for key, value in normalized.get("providers", {}).items():
            normalized_value = self._single_line(value, 160)
            current_value = self._single_line(self._provider_settings().get(key, ""), 160)
            if self._should_apply_migration_value(current_value, normalized_value, conflict):
                changed_config[key] = normalized_value
        for key, value in normalized.get("settings", {}).items():
            if key in {"storage_backend", "storage_sqlite_path"}:
                continue
            if key in {"group_whitelist_ids", "group_blacklist_ids"}:
                normalized_value = self._normalize_id_list(value)
            elif key == "group_access_mode":
                normalized_mode = str(value or "").strip().lower()
                normalized_value = normalized_mode if normalized_mode in {"whitelist", "blacklist"} else "whitelist"
            else:
                normalized_value = self._normalize_setting_value(key, value)
            current_value = self._migration_current_setting_value(key)
            if self._should_apply_migration_value(current_value, normalized_value, conflict):
                changed_config[key] = normalized_value
        for key, value in changed_config.items():
            self._apply_config_value(key, value, changed_config)
        if any(key in self._allowed_provider_keys() for key in changed_config) or "provider_config_mode" in changed_config:
            apply_quick = getattr(self.plugin, "_apply_quick_provider_defaults", None)
            if callable(apply_quick):
                apply_quick()
        config_saved = True
        if changed_config:
            config_saved = await self._save_config_if_possible()

        applied_sections: list[dict[str, Any]] = []
        data_payload = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
        if data_payload:
            async with self.plugin._data_lock:
                for section, imported_value in data_payload.items():
                    current_value = self.plugin.data.get(section)
                    if mode == "replace" or not isinstance(current_value, dict) or not isinstance(imported_value, dict):
                        self.plugin.data[section] = deepcopy(imported_value)
                    else:
                        merged = deepcopy(current_value)
                        self._deep_merge_dict(merged, imported_value, conflict=conflict)
                        self.plugin.data[section] = merged
                    applied_sections.append(
                        {
                            "key": section,
                            "label": self._migration_section_label(section),
                            "count": self._migration_count_items(imported_value),
                        }
                    )
                self.plugin._save_data_sync()
            self._refresh_migration_runtime_caches(data_payload)

        overview = await self.get_overview()
        data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
        checks = await self._migration_post_import_checks(config_saved=config_saved)
        data["message"] = "配置已导入。"
        data["mode"] = mode
        data["conflict"] = conflict
        data["backup_path"] = backup_path
        data["config_saved"] = config_saved
        data["changed_config_count"] = len(changed_config)
        data["applied_sections"] = applied_sections
        data["post_import_checks"] = checks
        data["migration_backups"] = self._list_migration_backup_items(limit=8)
        overview["data"] = data
        return overview

    async def _build_migration_package(self, options: set[str] | None = None, *, include_all: bool = False) -> dict[str, Any]:
        selected = {"basic", "relations", "food_skills", "providers", "sensitive"} if include_all else (options or {"basic", "relations", "food_skills"})
        async with self.plugin._data_lock:
            raw_data = deepcopy(self.plugin.data)
        package = {
            "kind": "private_companion_config_backup",
            "plugin": PLUGIN_NAME,
            "schema": 1,
            "version": self._plugin_version(),
            "exported_at": int(time.time()),
            "included_sections": sorted(selected),
            "settings": self._migration_settings_snapshot(selected),
            "features": self._migration_feature_snapshot(selected),
            "data": self._migration_data_snapshot(raw_data, selected),
            "excluded": [
                "Token 消耗统计",
                "图片/视觉摘要缓存",
                "最近消息和输入状态",
                "主动消息审计与冷却队列",
                "临时任务、排障记录和运行时缓存",
                "本机存储后端与 SQLite 路径",
            ],
        }
        if "providers" in selected:
            package["providers"] = self._migration_provider_snapshot()
        package["checksum_algorithm"] = "sha256"
        package["checksum"] = self._migration_checksum(package)
        return package

    def _migration_settings_snapshot(self, selected: set[str]) -> dict[str, Any]:
        if "basic" not in selected and "sensitive" not in selected:
            return {}
        runtime = self._runtime_settings()
        allowed = self._allowed_setting_keys()
        settings = {}
        for key, value in runtime.items():
            if key in {"storage_backend", "storage_sqlite_path"}:
                continue
            if key not in allowed:
                continue
            group = self._migration_setting_group(key)
            if group == "sensitive":
                if "sensitive" in selected:
                    settings[key] = deepcopy(value)
            elif group == "providers":
                if "providers" in selected:
                    settings[key] = deepcopy(value)
            elif "basic" in selected:
                settings[key] = deepcopy(value)
        if "basic" in selected:
            settings["group_access_mode"] = str(getattr(self.plugin, "group_access_mode", "whitelist") or "whitelist")
            settings["group_whitelist_ids"] = list(getattr(self.plugin, "group_whitelist_ids", []) or [])
            settings["group_blacklist_ids"] = list(getattr(self.plugin, "group_blacklist_ids", []) or [])
        if "sensitive" in selected:
            qzone_cookie = self._config_get("QZONE_COOKIE") or str(getattr(self.plugin, "qzone_cookie", "") or "")
            if qzone_cookie:
                settings["QZONE_COOKIE"] = qzone_cookie
            search_api_key = self._config_get("WEB_EXPLORATION_API_KEY") or str(getattr(self.plugin, "web_exploration_api_key", "") or "")
            if search_api_key:
                settings["WEB_EXPLORATION_API_KEY"] = search_api_key
        return settings

    def _migration_feature_snapshot(self, selected: set[str]) -> dict[str, bool]:
        if "basic" not in selected and "sensitive" not in selected:
            return {}
        features: dict[str, bool] = {}
        for key in sorted(self._allowed_feature_keys()):
            group = self._migration_setting_group(key)
            if group == "sensitive" and "sensitive" not in selected:
                continue
            if group == "providers" and "providers" not in selected:
                continue
            if group not in {"sensitive", "providers"} and "basic" not in selected:
                continue
            if hasattr(self.plugin, key):
                features[key] = self._normalize_bool_value(getattr(self.plugin, key))
                continue
            raw = self._config_get(key)
            if raw != "":
                features[key] = self._normalize_bool_value(raw)
        return features

    def _migration_provider_snapshot(self) -> dict[str, str]:
        allowed = self._allowed_provider_keys()
        return {key: value for key, value in self._provider_settings().items() if key in allowed}

    def _migration_data_snapshot(self, raw_data: dict[str, Any], selected: set[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for section in self._migration_data_sections(selected):
            if section not in raw_data:
                continue
            value = deepcopy(raw_data.get(section))
            if section in {"users", "groups"}:
                value = self._strip_runtime_data(value)
            if self._migration_count_items(value) > 0:
                result[section] = value
        return result

    @classmethod
    def _migration_data_sections(cls, selected: set[str] | None = None) -> tuple[str, ...]:
        selected = selected or {"basic", "relations", "food_skills"}
        sections: list[str] = []
        if "relations" in selected:
            sections.extend(
                [
                    "users",
                    "groups",
                    "worldbook_entries",
                    "worldbook_member_profiles",
                    "worldbook_group_profiles",
                ]
            )
        if "food_skills" in selected:
            sections.extend(["skill_growth", "food_menu", "external_proactive_abilities", "important_dates", "can_do"])
        if "sensitive" in selected:
            sections.extend(["jm_cosmos_integration", "bookshelf_items"])
        return tuple(sections)

    @staticmethod
    def _migration_setting_group(key: str) -> str:
        text = str(key)
        if text in {"storage_backend", "storage_sqlite_path"}:
            return "environment"
        if text == "provider_config_mode":
            return "providers"
        if text == "QZONE_COOKIE":
            return "sensitive"
        if text == "WEB_EXPLORATION_API_KEY":
            return "sensitive"
        if text.startswith("private_reading_") or text.startswith("enable_private_reading_"):
            return "sensitive"
        if text in {"PRIVATE_READING_VISION_PROVIDER_ID"}:
            return "sensitive"
        if text.endswith("_PROVIDER_ID") or text in {"LLM_PROVIDER_ID", "tts_conversion_provider_id"}:
            return "providers"
        return "basic"

    @staticmethod
    def _migration_section_label(key: str) -> str:
        return {
            "users": "私聊对象资料",
            "groups": "群聊观测资料",
            "worldbook_entries": "关系网原始条目",
            "worldbook_member_profiles": "关系网成员资料",
            "worldbook_group_profiles": "关系网群资料",
            "skill_growth": "技能熟练度",
            "food_menu": "吃什么候选菜单",
            "external_proactive_abilities": "外部主动能力",
            "important_dates": "重要日期",
            "can_do": "自定义能力",
            "jm_cosmos_integration": "私密阅读状态",
            "bookshelf_items": "书柜阅读记录",
        }.get(key, key)

    def _extract_migration_package(self, payload: Any, *, allow_checksum_mismatch: bool = False) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("导入内容必须是 JSON 对象")
        package = self._unwrap_migration_package_payload(payload)
        if not isinstance(package, dict):
            raise ValueError("没有读取到可导入的配置备份")
        if package.get("kind") != "private_companion_config_backup" or package.get("plugin") != PLUGIN_NAME:
            legacy = self._legacy_snapshot_to_migration_package(package)
            if legacy is None:
                raise ValueError("这不是 Private Companion 的配置备份")
            return legacy
        checksum = str(package.get("checksum") or "").strip()
        if checksum and not self._migration_checksum_matches(package, checksum):
            if not allow_checksum_mismatch:
                raise ValueError("备份校验失败：文件可能被截断或手动修改过。如确认只是手动脱敏/删改敏感字段，请勾选“校验失败仍继续预览/导入”。")
            package = deepcopy(package)
            package["_checksum_mismatch_allowed"] = True
        return package

    def _unwrap_migration_package_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = payload
        for _ in range(4):
            if not isinstance(current, dict):
                return {}
            if current.get("kind") == "private_companion_config_backup" or (
                isinstance(current.get("overview"), dict)
                and ("users" in current or "groups" in current)
            ):
                return current
            for key in ("package", "data", "payload", "result"):
                nested = current.get(key)
                if isinstance(nested, dict):
                    current = nested
                    break
            else:
                return current
        return current if isinstance(current, dict) else {}

    def _legacy_snapshot_to_migration_package(self, package: dict[str, Any]) -> dict[str, Any] | None:
        overview = package.get("overview") if isinstance(package.get("overview"), dict) else {}
        has_snapshot_shape = bool(overview) and ("users" in package or "groups" in package)
        if not has_snapshot_shape:
            return None

        settings: dict[str, Any] = {}
        raw_settings = overview.get("settings") if isinstance(overview.get("settings"), dict) else {}
        for key, value in raw_settings.items():
            if key in {"storage_backend", "storage_sqlite_path"}:
                continue
            if key in self._allowed_setting_keys():
                settings[key] = deepcopy(value)
        group_overview = overview.get("group") if isinstance(overview.get("group"), dict) else {}
        if group_overview:
            settings["group_access_mode"] = str(group_overview.get("access_mode") or "whitelist")
            settings["group_whitelist_ids"] = self._normalize_id_list(group_overview.get("whitelist"))
            settings["group_blacklist_ids"] = self._normalize_id_list(group_overview.get("blacklist"))

        features: dict[str, bool] = {}
        raw_features = overview.get("features") if isinstance(overview.get("features"), dict) else {}
        for key, value in raw_features.items():
            if key in self._allowed_feature_keys():
                features[key] = self._normalize_bool_value(value)

        providers: dict[str, str] = {}
        raw_providers = overview.get("providers") if isinstance(overview.get("providers"), dict) else {}
        for key, value in raw_providers.items():
            if key in self._allowed_provider_keys():
                providers[key] = self._single_line(value, 160)

        converted = {
            "kind": "private_companion_config_backup",
            "plugin": PLUGIN_NAME,
            "schema": 1,
            "version": str(package.get("version") or overview.get("plugin", {}).get("version") or self._plugin_version()),
            "exported_at": int(time.time()),
            "included_sections": ["basic", "relations"],
            "settings": settings,
            "features": features,
            "providers": providers,
            "data": {},
            "legacy_snapshot": True,
            "excluded": [
                "由旧版页面快照转换；仅导入快照中可识别的配置、名单、开关和模型指向",
                "旧版页面快照中的私聊/群聊列表是展示摘要，不会写回数据文件",
                "最近消息、缓存、Token、运行日志和临时队列不会导入",
            ],
        }
        converted["checksum_algorithm"] = "sha256"
        converted["checksum"] = self._migration_checksum(converted)
        return converted

    def _normalize_migration_package(self, package: dict[str, Any]) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        features: dict[str, bool] = {}
        providers: dict[str, str] = {}
        ignored: list[str] = []

        raw_settings = package.get("settings") if isinstance(package.get("settings"), dict) else {}
        for key, value in raw_settings.items():
            if key in {"storage_backend", "storage_sqlite_path"}:
                ignored.append(str(key))
                continue
            if key == "group_access_mode":
                mode = str(value or "").strip().lower()
                if mode in {"whitelist", "blacklist"}:
                    settings[key] = mode
                continue
            if key in {"group_whitelist_ids", "group_blacklist_ids"}:
                settings[key] = self._normalize_id_list(value)
                continue
            if key in self._allowed_setting_keys():
                settings[key] = self._normalize_setting_value(key, value)
            else:
                ignored.append(str(key))

        raw_features = package.get("features") if isinstance(package.get("features"), dict) else {}
        for key, value in raw_features.items():
            if key in self._allowed_feature_keys():
                features[key] = self._normalize_bool_value(value)
            else:
                ignored.append(str(key))

        raw_providers = package.get("providers") if isinstance(package.get("providers"), dict) else {}
        for key, value in raw_providers.items():
            if key in self._allowed_provider_keys():
                providers[key] = self._single_line(value, 160)
            else:
                ignored.append(str(key))

        raw_data = package.get("data") if isinstance(package.get("data"), dict) else {}
        data: dict[str, Any] = {}
        for section in self._migration_data_sections({"relations", "food_skills", "sensitive"}):
            if section not in raw_data:
                continue
            value = deepcopy(raw_data.get(section))
            if section in {"users", "groups"}:
                value = self._strip_runtime_data(value)
            data[section] = value
        for section in raw_data:
            if section not in data:
                ignored.append(str(section))

        return {
            "version": package.get("version"),
            "exported_at": package.get("exported_at"),
            "included_sections": [str(item) for item in package.get("included_sections", []) if str(item).strip()],
            "checksum": str(package.get("checksum") or ""),
            "checksum_ok": bool(package.get("checksum")) and self._migration_checksum_matches(package, str(package.get("checksum") or "")),
            "checksum_bypassed": bool(package.get("_checksum_mismatch_allowed")),
            "legacy_snapshot": bool(package.get("legacy_snapshot")),
            "settings": settings,
            "features": features,
            "providers": providers,
            "data": data,
            "ignored": sorted(set(ignored))[:80],
        }

    async def _migration_import_summary(self, normalized: dict[str, Any]) -> dict[str, Any]:
        async with self.plugin._data_lock:
            current_data = deepcopy(self.plugin.data)
        config_diff = self._migration_config_diff(normalized)
        config_count = len(normalized.get("settings", {})) + len(normalized.get("features", {})) + len(normalized.get("providers", {}))
        compatibility = self._migration_compatibility(normalized.get("version"))
        sections: list[dict[str, Any]] = []
        for key, value in (normalized.get("data") or {}).items():
            current_value = current_data.get(key)
            diff = self._migration_diff_counts(current_value, value)
            sections.append(
                {
                    "key": key,
                    "label": self._migration_section_label(key),
                    "count": self._migration_count_items(value),
                    "current_count": self._migration_count_items(current_value),
                    **diff,
                }
            )
        return {
            "version": normalized.get("version") or "",
            "current_version": self._plugin_version(),
            "compatibility": compatibility,
            "exported_at": normalized.get("exported_at") or 0,
            "included_sections": normalized.get("included_sections", []),
            "checksum": normalized.get("checksum") or "",
            "checksum_ok": bool(normalized.get("checksum_ok")),
            "checksum_bypassed": bool(normalized.get("checksum_bypassed")),
            "legacy_snapshot": bool(normalized.get("legacy_snapshot")),
            "config_count": config_count,
            "config_diff": config_diff,
            "settings_count": len(normalized.get("settings", {})),
            "features_count": len(normalized.get("features", {})),
            "providers_count": len(normalized.get("providers", {})),
            "sections": sections,
            "ignored": normalized.get("ignored", []),
            "excluded": [
                "不会导入 Token 统计、缓存、最近消息、审计日志和临时队列。",
                "导入前会自动保存一份当前可迁移配置备份。",
            ],
        }

    def _write_migration_backup(self, package: dict[str, Any]) -> str:
        data_dir = Path(getattr(self.plugin, "data_dir", "") or Path(getattr(self.plugin, "data_file", ".")).parent)
        backup_dir = data_dir / "config_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = backup_dir / f"private_companion_before_import_{stamp}_{secrets.token_hex(3)}.json"
        if not package.get("checksum"):
            package["checksum_algorithm"] = "sha256"
            package["checksum"] = self._migration_checksum(package)
        path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _migration_backup_dir(self) -> Path:
        data_dir = Path(getattr(self.plugin, "data_dir", "") or Path(getattr(self.plugin, "data_file", ".")).parent)
        return data_dir / "config_backups"

    def _resolve_migration_backup_path(self, backup_id: str) -> Path:
        safe_name = Path(str(backup_id or "")).name
        if not safe_name or not safe_name.endswith(".json"):
            raise ValueError("没有找到要恢复的备份文件")
        path = (self._migration_backup_dir() / safe_name).resolve()
        root = self._migration_backup_dir().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("备份路径不合法") from exc
        if not path.exists() or not path.is_file():
            raise ValueError("备份文件不存在")
        return path

    def _list_migration_backup_items(self, *, limit: int = 8) -> list[dict[str, Any]]:
        backup_dir = self._migration_backup_dir()
        if not backup_dir.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(backup_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[: max(1, limit)]:
            stat = path.stat()
            item: dict[str, Any] = {
                "id": path.name,
                "name": path.name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "version": "",
                "exported_at": 0,
                "checksum_ok": False,
            }
            try:
                package = json.loads(path.read_text(encoding="utf-8-sig"))
                item["version"] = str(package.get("version") or "")
                item["exported_at"] = int(float(package.get("exported_at") or 0))
                item["included_sections"] = [str(value) for value in package.get("included_sections", []) if str(value).strip()]
                checksum = str(package.get("checksum") or "")
                item["checksum_ok"] = bool(checksum) and self._migration_checksum_matches(package, checksum)
            except Exception as exc:
                item["error"] = self._single_line(exc, 120)
            items.append(item)
        return items

    def _migration_checksum(self, package: dict[str, Any]) -> str:
        payload = deepcopy(package)
        payload.pop("checksum", None)
        payload.pop("checksum_algorithm", None)
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _migration_checksum_digest(payload: dict[str, Any], *, sort_keys: bool, compact: bool) -> str:
        separators = (",", ":") if compact else None
        text = json.dumps(payload, ensure_ascii=False, sort_keys=sort_keys, separators=separators)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _migration_checksum_candidates(self, package: dict[str, Any]) -> set[str]:
        candidates: set[str] = set()
        for remove_algorithm in (True, False):
            payload = deepcopy(package)
            payload.pop("checksum", None)
            if remove_algorithm:
                payload.pop("checksum_algorithm", None)
            for sort_keys in (True, False):
                for compact in (True, False):
                    try:
                        candidates.add(
                            self._migration_checksum_digest(
                                payload,
                                sort_keys=sort_keys,
                                compact=compact,
                            )
                        )
                    except Exception:
                        continue
        return candidates

    def _migration_checksum_matches(self, package: dict[str, Any], expected: str) -> bool:
        checksum = str(expected or "").strip().lower()
        if not checksum:
            return False
        return checksum in self._migration_checksum_candidates(package)

    def _plugin_version(self) -> str:
        for source in (self.plugin, getattr(self.plugin, "metadata", None)):
            for attr in ("version", "__version__", "plugin_version"):
                value = getattr(source, attr, None)
                if value:
                    return str(value).strip()
        try:
            metadata_path = Path(__file__).with_name("metadata.yaml")
            text = metadata_path.read_text(encoding="utf-8")
            match = re.search(r"(?m)^version:\s*['\"]?([^'\"\s#]+)", text)
            if match:
                return match.group(1).strip()
        except Exception:
            pass
        return "unknown"

    def _parse_migration_version(self, value: Any) -> tuple[int, int, int] | None:
        match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value or ""))
        if not match:
            return None
        return tuple(int(part or 0) for part in match.groups())

    def _migration_compatibility(self, backup_version: Any) -> dict[str, Any]:
        current_text = self._plugin_version()
        backup_text = str(backup_version or "")
        current = self._parse_migration_version(current_text)
        backup = self._parse_migration_version(backup_text)
        level = "ok"
        message = "版本接近，可以按预览结果导入。"
        if not backup or not current:
            level = "unknown"
            message = "无法判断版本跨度，建议合并导入，不建议覆盖。"
        elif backup[0] != current[0] or abs((current[1] if len(current) > 1 else 0) - (backup[1] if len(backup) > 1 else 0)) >= 2:
            level = "warn"
            message = "版本跨度较大，建议合并导入，不建议覆盖。"
        elif backup > current:
            level = "warn"
            message = "备份来自更新版本，建议合并导入，不建议覆盖。"
        return {
            "level": level,
            "backup_version": backup_text or "未知",
            "current_version": current_text,
            "message": message,
        }

    async def _migration_post_import_checks(self, *, config_saved: bool) -> list[dict[str, str]]:
        async with self.plugin._data_lock:
            data = deepcopy(self.plugin.data)
        checks: list[dict[str, str]] = []

        def add(level: str, title: str, detail: str) -> None:
            checks.append({"level": level, "title": title, "detail": detail})

        add("ok" if config_saved else "warn", "配置保存", "配置已写入并保存。" if config_saved else "运行态已写入，但配置持久化可能失败。")
        mode = str(getattr(self.plugin, "group_access_mode", "whitelist") or "whitelist")
        whitelist = list(getattr(self.plugin, "group_whitelist_ids", []) or [])
        blacklist = list(getattr(self.plugin, "group_blacklist_ids", []) or [])
        if mode == "whitelist" and not whitelist:
            add("warn", "群聊名单", "当前是白名单模式，但白名单为空；群聊能力可能不会生效。")
        else:
            add("ok", "群聊名单", f"当前为{'白名单' if mode == 'whitelist' else '黑名单'}模式，白名单 {len(whitelist)} 个，黑名单 {len(blacklist)} 个。")

        available_ids = {str(item.get("id") or "") for item in self._available_provider_items()}
        configured = {key: value for key, value in self._provider_settings().items() if str(value or "").strip()}
        missing = [value for value in configured.values() if available_ids and value not in available_ids]
        if configured and not available_ids:
            add("warn", "模型配置", f"已配置 {len(configured)} 个模型指向，但当前无法读取 AstrBot Provider 列表，暂不能校验是否存在。")
        elif missing:
            add("warn", "模型配置", f"有 {len(missing)} 个 Provider ID 当前未在 AstrBot 中找到。")
        else:
            add("ok", "模型配置", f"已配置 {len(configured)} 个模型指向，当前未发现缺失 Provider。")

        members = data.get("worldbook_member_profiles") if isinstance(data.get("worldbook_member_profiles"), dict) else {}
        groups = data.get("worldbook_group_profiles") if isinstance(data.get("worldbook_group_profiles"), dict) else {}
        if not members and not groups:
            add("warn", "关系网", "当前没有关系网成员或群资料；如果刚导入关系网备份，可能需要检查导入内容。")
        else:
            add("ok", "关系网", f"成员资料 {len(members)} 个，群资料 {len(groups)} 个。")

        food = data.get("food_menu") if isinstance(data.get("food_menu"), dict) else {}
        food_items = food.get("items") if isinstance(food.get("items"), dict) else food
        if isinstance(food_items, dict):
            add("ok" if food_items else "warn", "吃什么候选", f"候选菜单可读取，当前 {len(food_items)} 项。")
        else:
            add("warn", "吃什么候选", "候选菜单结构不是预期格式，请到功能页检查。")
        return checks

    def _strip_runtime_data(self, value: Any) -> Any:
        runtime_keys = {
            "recent_messages",
            "recent_message_ids",
            "recent_replies",
            "recent_group_messages",
            "proactive_sending",
            "proactive_audit_log",
            "proactive_candidates",
            "pending_followup_event",
            "pending_timer_events",
            "pending_atrelay_requests",
            "suspended_proactive",
            "input_status",
            "current_input_status",
            "recall_message_cache",
            "image_cache",
            "visual_summary_cache",
            "token_usage",
            "token_stats",
            "troubleshooting_records",
            "maintenance_records",
        }
        runtime_prefixes = (
            "recent_",
            "pending_",
            "last_message",
            "last_reply",
            "last_sent",
            "last_proactive",
            "cooldown_",
            "session_",
        )
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if key_text in runtime_keys or any(key_text.startswith(prefix) for prefix in runtime_prefixes):
                    continue
                if key_text.endswith("_cache") or key_text.endswith("_audit_log"):
                    continue
                cleaned[key_text] = self._strip_runtime_data(item)
            return cleaned
        if isinstance(value, list):
            return [self._strip_runtime_data(item) for item in value]
        return value

    @staticmethod
    def _migration_count_items(value: Any) -> int:
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, list):
            return len(value)
        return 1 if value not in (None, "", [], {}) else 0

    def _migration_current_setting_value(self, key: str) -> Any:
        if key == "group_access_mode":
            return str(getattr(self.plugin, "group_access_mode", "whitelist") or "whitelist")
        if key == "group_whitelist_ids":
            return list(getattr(self.plugin, "group_whitelist_ids", []) or [])
        if key == "group_blacklist_ids":
            return list(getattr(self.plugin, "group_blacklist_ids", []) or [])
        if hasattr(self.plugin, key):
            return deepcopy(getattr(self.plugin, key))
        return self._config_get(key)

    @staticmethod
    def _migration_value_empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    def _should_apply_migration_value(self, current_value: Any, incoming_value: Any, conflict: str) -> bool:
        if current_value == incoming_value:
            return False
        if conflict == "keep_current":
            return False
        if conflict == "fill_empty":
            return self._migration_value_empty(current_value)
        return True

    def _migration_diff_counts(self, current: Any, incoming: Any) -> dict[str, int]:
        if isinstance(incoming, dict):
            current_dict = current if isinstance(current, dict) else {}
            added = 0
            overwritten = 0
            unchanged = 0
            for key, value in incoming.items():
                if key not in current_dict:
                    added += 1
                elif current_dict.get(key) == value:
                    unchanged += 1
                else:
                    overwritten += 1
            return {"added": added, "overwritten": overwritten, "unchanged": unchanged}
        if isinstance(incoming, list):
            if not isinstance(current, list) or not current:
                return {"added": len(incoming), "overwritten": 0, "unchanged": 0}
            if current == incoming:
                return {"added": 0, "overwritten": 0, "unchanged": len(incoming)}
            return {"added": 0, "overwritten": len(incoming), "unchanged": 0}
        return {
            "added": 1 if self._migration_value_empty(current) and not self._migration_value_empty(incoming) else 0,
            "overwritten": 1 if not self._migration_value_empty(current) and current != incoming else 0,
            "unchanged": 1 if current == incoming else 0,
        }

    def _migration_config_diff(self, normalized: dict[str, Any]) -> dict[str, int]:
        counts = {"added": 0, "overwritten": 0, "unchanged": 0}
        for key, value in (normalized.get("settings") or {}).items():
            diff = self._migration_diff_counts(self._migration_current_setting_value(key), value)
            for item in counts:
                counts[item] += diff[item]
        provider_snapshot = self._provider_settings()
        for key, value in (normalized.get("providers") or {}).items():
            diff = self._migration_diff_counts(provider_snapshot.get(key, ""), value)
            for item in counts:
                counts[item] += diff[item]
        for key, value in (normalized.get("features") or {}).items():
            diff = self._migration_diff_counts(self._normalize_bool_value(getattr(self.plugin, key, self._config_get(key))), self._normalize_bool_value(value))
            for item in counts:
                counts[item] += diff[item]
        return counts

    def _deep_merge_dict(self, target: dict[str, Any], incoming: dict[str, Any], *, conflict: str = "use_backup") -> None:
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge_dict(target[key], value, conflict=conflict)
            elif key in target and not self._should_apply_migration_value(target.get(key), value, conflict):
                continue
            else:
                target[key] = deepcopy(value)

    def _refresh_migration_runtime_caches(self, data_payload: dict[str, Any]) -> None:
        if "external_proactive_abilities" in data_payload and hasattr(self.plugin, "_external_proactive_abilities"):
            store = self.plugin.data.get("external_proactive_abilities")
            if isinstance(store, dict):
                self.plugin._external_proactive_abilities = deepcopy(store)

    def _available_provider_items(self) -> list[dict[str, Any]]:
        providers: list[Any] = []
        context = getattr(self.plugin, "context", None)
        get_all = getattr(context, "get_all_providers", None)
        if callable(get_all):
            try:
                providers = list(get_all() or [])
            except Exception:
                providers = []
        if not providers:
            manager = getattr(context, "provider_manager", None)
            inst_map = getattr(manager, "inst_map", None)
            if isinstance(inst_map, dict):
                providers = list(inst_map.values())

        using_id = ""
        get_using = getattr(context, "get_using_provider", None)
        if callable(get_using):
            try:
                using_id = self._provider_id(get_using())
            except Exception:
                using_id = ""

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for provider in providers:
            provider_id = self._provider_id(provider)
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            items.append(
                {
                    "id": provider_id,
                    "name": self._provider_name(provider, provider_id),
                    "type": self._provider_type(provider),
                    "model": self._provider_model(provider),
                    "is_default": provider_id == using_id,
                }
            )
        items.sort(key=lambda item: (not item["is_default"], item["name"].lower(), item["id"].lower()))
        return items

    @staticmethod
    def _provider_config(provider: Any) -> Any:
        return getattr(provider, "provider_config", None) or getattr(provider, "config", None) or {}

    @classmethod
    def _provider_config_value(cls, provider: Any, *keys: str) -> str:
        config = cls._provider_config(provider)
        for key in keys:
            value = ""
            if isinstance(config, dict):
                value = str(config.get(key, "") or "")
            else:
                value = str(getattr(config, key, "") or "")
            if value:
                return value.strip()
        return ""

    @classmethod
    def _provider_id(cls, provider: Any) -> str:
        if provider is None:
            return ""
        return (
            cls._provider_config_value(provider, "id", "provider_id")
            or str(getattr(provider, "provider_id", "") or "").strip()
            or str(getattr(provider, "id", "") or "").strip()
        )

    @classmethod
    def _provider_name(cls, provider: Any, provider_id: str) -> str:
        explicit_name = (
            cls._provider_config_value(provider, "name", "display_name", "label", "title")
            or str(getattr(provider, "name", "") or "").strip()
            or str(getattr(provider, "display_name", "") or "").strip()
        )
        if explicit_name and not cls._provider_name_is_protocol(explicit_name):
            return explicit_name
        if provider_id and not cls._provider_name_is_protocol(provider_id):
            return provider_id
        inferred = cls._provider_vendor_from_config(provider)
        if inferred:
            return inferred
        protocol_name = cls._provider_config_value(provider, "provider", "type", "provider_type")
        return explicit_name or protocol_name or provider_id

    @staticmethod
    def _provider_name_is_protocol(value: Any) -> bool:
        text = str(value or "").strip().lower()
        normalized = re.sub(r"[\s_\-]+", "", text)
        return normalized in {
            "openai",
            "openai兼容",
            "openai-compatible",
            "openaicompatible",
            "compatible",
            "兼容",
            "兼容模式",
        }

    @classmethod
    def _provider_vendor_from_config(cls, provider: Any) -> str:
        source = " ".join(
            cls._provider_config_value(
                provider,
                "api_base",
                "base_url",
                "api_base_url",
                "api_url",
                "endpoint",
                "url",
                "model",
                "model_name",
                "api_model",
                "model_id",
            ).split()
        ).lower()
        if not source:
            return ""
        try:
            parsed = urlparse(source if "://" in source else f"https://{source}")
            host = parsed.netloc.lower()
        except Exception:
            host = ""
        haystack = f"{source} {host}"
        vendors = [
            ("火山引擎", ("volces.com", "volcengine", "huoshan", "火山", "doubao", "ark.cn-beijing")),
            ("DeepSeek", ("deepseek.com", "deepseek")),
            ("阿里云百炼", ("dashscope", "aliyuncs.com", "bailian", "百炼", "qwen", "tongyi")),
            ("魔搭社区", ("modelscope", "api-inference", "魔搭")),
            ("OpenRouter", ("openrouter.ai", "openrouter")),
            ("硅基流动", ("siliconflow.cn", "siliconflow")),
            ("智谱", ("bigmodel.cn", "zhipu", "glm")),
            ("月之暗面", ("moonshot.cn", "moonshot", "kimi")),
            ("Google", ("generativelanguage.googleapis.com", "googleapis.com", "gemini")),
            ("Anthropic", ("anthropic.com", "claude")),
            ("OpenAI", ("api.openai.com", "openai.com", "gpt-")),
        ]
        for label, needles in vendors:
            if any(needle in haystack for needle in needles):
                return label
        if host:
            core = host.split(":")[0]
            for prefix in ("api.", "ark.", "www."):
                if core.startswith(prefix):
                    core = core[len(prefix):]
            return core.split(".")[0] or ""
        return ""

    @classmethod
    def _provider_model(cls, provider: Any) -> str:
        return cls._provider_config_value(provider, "model", "model_name", "api_model", "model_id")

    @classmethod
    def _provider_type(cls, provider: Any) -> str:
        return (
            cls._provider_config_value(provider, "type", "provider_type")
            or provider.__class__.__name__
        )

    def _runtime_settings(self) -> dict[str, Any]:
        keys = [
            "bot_name",
            "page_font_family",
            "page_theme",
            "provider_config_mode",
            "model_timeout_overrides",
            "model_fallback_overrides",
            "enable_deepseek_peak_replacement",
            "deepseek_peak_windows",
            "deepseek_peak_timezone",
            "deepseek_peak_match_keywords",
            "plugin_specific_persona_id",
            "target_user_ids",
            "private_user_aliases",
            "private_user_delivery_aliases",
            "target_platform",
            "require_private_opt_in",
            "environment_perception_timezone",
            "holiday_country",
            "enable_environment_perception",
            "enable_balance_awareness",
            "enable_holiday_perception",
            "enable_platform_perception",
            "enable_model_perception",
            "enable_worldview_perception",
            "enable_lunar_perception",
            "enable_solar_term_perception",
            "enable_almanac_perception",
            "default_nickname",
            "default_style",
            "reply_style_prompt",
            "enable_persona_voice_channels",
            "persona_conversation_voice_prompt",
            "persona_creative_voice_prompt",
            "persona_planning_voice_prompt",
            "persona_inner_voice_prompt",
            "persona_proactive_voice_prompt",
            "proactive_prompt_template",
            "proactive_persona_judge_send_threshold",
            "proactive_persona_judge_cache_minutes",
            "proactive_persona_judge_max_daily",
            "schedule_persona_prompt",
            "schedule_worldview_prompt",
            "roleplay_user_profile_prompt",
            "roleplay_knowledge_source_ids",
            "worldview_adaptation_mode",
            "worldview_adaptation_prompt",
            "quiet_hours",
            "passive_injection_position",
            "passive_review_mode",
            "passive_review_strength",
            "proactive_review_mode",
            "smart_silence_judge_mode",
            "smart_silence_min_confidence",
            "smart_silence_model_timeout_seconds",
            "proactive_review_strength",
            "proactive_review_hard_risk_threshold",
            "proactive_review_low_score_threshold",
            "proactive_review_pressure_threshold",
            "response_review_max_chars",
            "passive_topic_memory_hours",
            "tts_generation_mode",
            "tts_voice_language",
            "tts_delivery_mode",
            "tts_foreign_text_mode",
            "tts_conversion_scope",
            "tts_conversion_provider_id",
            "tts_extra_prompt",
            "tts_frequency_control_mode",
            "tts_constraint_mode",
            "tts_session_min_interval_seconds",
            "tts_private_min_interval_seconds",
            "tts_group_min_interval_seconds",
            "tts_trigger_probability",
            "tts_private_trigger_probability",
            "tts_group_trigger_probability",
            "enable_tts_local_playback",
            "enable_tts_local_playback_live_only",
            "enable_tts_live_subtitle_sync",
            "tts_live_subtitle_url",
            "tts_local_playback_volume",
            "tts_local_playback_min_interval_seconds",
            "auto_voice_enabled",
            "auto_voice_full_conversion_enabled",
            "auto_voice_probability",
            "auto_voice_max_chars",
            "auto_voice_cooldown_seconds",
            "main_user_voice_probability",
            "main_user_mention_voice_keywords",
            "main_user_mention_voice_probability",
            "main_user_mention_voice_prompt",
            "daily_token_limit",
            "enable_daily_token_soft_limit",
            "daily_token_soft_limit",
            "humanized_state_intensity",
            "enable_health_state",
            "enable_hunger_state",
            "enable_rest_reply_simulation",
            "rest_reply_mode",
            "rest_reply_probability",
            "rest_reply_llm_threshold",
            "rest_reply_active_windows",
            "rest_reply_awake_grace_minutes",
            "enable_rest_backlog_reply",
            "rest_backlog_max_messages",
            "REST_WAKEUP_PROVIDER_ID",
            "check_interval_seconds",
            "proactive_intensity_preset",
            "idle_minutes",
            "min_interval_minutes",
            "proactive_unanswered_slowdown_start",
            "proactive_unanswered_max_interval_multiplier",
            "friend_unanswered_max_cooldown_hours",
            "max_daily_messages",
            "proactive_photo_text_probability",
            "inbound_message_debounce_seconds",
            "enable_message_debounce",
            "enable_smart_message_debounce",
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID",
            "smart_message_debounce_model_timeout_seconds",
            "smart_message_debounce_wait_seconds",
            "smart_message_debounce_learning_window_seconds",
            "smart_message_debounce_examples_limit",
            "enable_recall_enhancement",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "enable_forbidden_word_recall",
            "recall_forbidden_words",
            "recall_forbidden_scope",
            "recall_forbidden_word_case_sensitive",
            "text_message_debounce_seconds",
            "image_message_debounce_seconds",
            "forward_message_debounce_seconds",
            "text_message_debounce_max_wait_seconds",
            "message_debounce_max_merge_messages",
            "enable_semantic_message_debounce",
            "semantic_message_debounce_seconds",
            "enable_proactive_quote_trigger_message",
            "enable_quote_group_reply",
            "enable_quote_group_interjection",
            "enable_quote_private_proactive",
            "quote_skip_short_reply_chars",
            "quote_target_strategy",
            "enable_photo_text_action",
            "enable_photo_reference_image",
            "photo_action_max_daily",
            "photo_generation_backend",
            "custom_photo_tool_name",
            "custom_photo_tool_prompt_param",
            "custom_photo_tool_kind_param",
            "custom_photo_tool_reference_param",
            "custom_photo_tool_extra_params",
            "COMFYUI_TEXT2IMG_WORKFLOW_NAME",
            "COMFYUI_SELFIE_WORKFLOW_NAME",
            "photo_persona_reference_image_path",
            "enable_daily_outfit_photo",
            "enable_creative_cover_generation",
            "daily_outfit_photo_prompt",
            "daily_outfit_rotation_days",
            "enable_natural_language_photo_generation",
            "natural_language_photo_generation_mode",
            "natural_language_photo_generation_max_daily",
            "natural_language_photo_extra_prompt",
            "comfyui_photo_wait_seconds",
            "enable_local_photo_load_guard",
            "local_photo_cpu_busy_percent",
            "local_photo_memory_busy_percent",
            "local_photo_defer_minutes",
            "external_image_api_platform",
            "EXTERNAL_IMAGE_API_BASE_URL",
            "EXTERNAL_IMAGE_API_KEY",
            "EXTERNAL_IMAGE_API_MODEL",
            "external_image_api_size",
            "external_image_api_timeout_seconds",
            "external_image_api_custom_headers",
            "external_image_download_proxy",
            "external_image_download_use_environment_proxy",
            "external_image_api_endpoints",
            "enable_backup_external_image_api",
            "backup_external_image_api_platform",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL",
            "BACKUP_EXTERNAL_IMAGE_API_KEY",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL",
            "backup_external_image_api_size",
            "backup_external_image_api_timeout_seconds",
            "backup_external_image_api_custom_headers",
            "photo_generation_style",
            "photo_generation_style_custom_prompt",
            "photo_generation_fixed_prompt",
            "photo_generation_scene_presets",
            "private_image_vision_wait_seconds",
            "enable_context_image_captioning",
            "context_image_caption_max_items",
            "context_image_caption_timeout_seconds",
            "enable_private_image_gif_enhancement",
            "private_image_gif_max_frames",
            "enable_private_image_self_recognition",
            "private_image_self_recognition_hint",
            "enable_private_image_vision_cache",
            "private_image_vision_cache_max_items",
            "screen_diary_context_max_chars",
            "enable_segmented_proactive_reply",
            "segmented_proactive_scope",
            "segmented_proactive_chat_scope",
            "segmented_proactive_threshold",
            "segmented_proactive_min_segment_chars",
            "segmented_proactive_max_segments",
            "segmented_proactive_send_as_forward",
            "segmented_proactive_split_mode",
            "segmented_proactive_regex",
            "segmented_proactive_split_words",
            "enable_segmented_proactive_content_cleanup",
            "segmented_proactive_content_cleanup_scope",
            "segmented_proactive_content_cleanup_rule",
            "segmented_proactive_content_cleanup_words",
            "enable_segmented_proactive_content_replacement",
            "segmented_proactive_content_replacements",
            "segmented_proactive_interval_method",
            "segmented_proactive_interval_min",
            "segmented_proactive_interval_max",
            "segmented_proactive_log_base",
            "group_conversation_followup_seconds",
            "group_conversation_followup_max_turns",
            "enable_group_conversation_followup",
            "enable_group_repeat_follow",
            "group_repeat_trigger_threshold",
            "group_repeat_count_distinct_users_only",
            "group_interject_min_interval_minutes",
            "group_interject_max_daily",
            "group_repeat_follow_probability",
            "group_repeat_interrupt_probability",
            "group_repeat_interrupt_probability_step",
            "group_repeat_interrupt_text",
            "group_repeat_interrupt_image_path",
            "group_scene_recent_limit",
            "enable_group_reality_promise_guard",
            "group_wakeup_direct_words",
            "group_wakeup_context_words",
            "group_wakeup_interest_keywords",
            "group_wakeup_interest_probability",
            "group_wakeup_short_text_wait_seconds",
            "group_wakeup_question_threshold",
            "group_wakeup_cold_group_threshold",
            "group_wakeup_cooldown_seconds",
            "group_wakeup_cold_group_idle_minutes",
            "group_wakeup_generated_keyword_limit",
            "group_wakeup_topic_interest_max_boost",
            "group_wakeup_debounce_pending_penalty",
            "group_wakeup_fatigue_limit",
            "group_wakeup_fatigue_decay_minutes",
            "group_wakeup_log_limit",
            "enable_group_high_intensity_mode",
            "group_high_intensity_wakeup_window_seconds",
            "group_high_intensity_wakeup_threshold",
            "group_high_intensity_cooldown_seconds",
            "group_high_intensity_merge_seconds",
            "group_high_intensity_max_merge_messages",
            "group_high_intensity_merge_scope",
            "enable_forward_message_adaptation",
            "forward_message_mode",
            "forward_message_max_messages",
            "forward_message_max_chars",
            "forward_message_parse_nested",
            "forward_message_image_vision",
            "forward_message_image_limit",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "recall_message_cache_ttl_seconds",
            "recall_message_cache_max_items",
            "recall_message_image_cache_max_mb",
            "enable_forbidden_word_recall",
            "recall_forbidden_words",
            "recall_forbidden_scope",
            "recall_forbidden_word_case_sensitive",
            "screen_diary_context_max_chars",
            "max_group_recent_messages",
            "max_group_slang_terms",
            "group_slang_web_search_terms",
            "group_slang_web_search_results",
            "memory_refresh_interval_minutes",
            "episode_memory_refresh_messages",
            "episode_memory_refresh_minutes",
            "max_companion_memory_items",
            "max_learned_expression_items",
            "expression_learning_mode",
            "enable_expression_manual_review",
            "enable_expression_style_review",
            "expression_private_learning_source_mode",
            "expression_private_learning_source_ids",
            "expression_group_learning_source_mode",
            "expression_group_learning_source_ids",
            "expression_group_learning_daily_batch_limit",
            "expression_group_learning_min_new_messages",
            "expression_private_application_mode",
            "expression_private_application_user_ids",
            "expression_group_application_mode",
            "expression_group_application_ids",
            "max_dialogue_episodes",
            "user_habit_min_count",
            "user_habit_max_items",
            "emotional_gate_hurt_threshold",
            "emotional_gate_refuse_threshold",
            "emotional_gate_recovery_per_hour",
            "emotional_gate_max_hurt_minutes",
            "enable_llm_emotion_judgement",
            "emotion_judgement_mode",
            "enable_skill_growth_simulation",
            "skill_growth_rate",
            "skill_growth_custom_skills",
            "enable_skill_growth_passive_injection",
            "enable_skill_growth_schedule_influence",
            "skill_growth_schedule_influence_strength",
            "enable_bilibili_integration",
            "enable_bilibili_boredom_watch",
            "bilibili_boredom_min_interval_hours",
            "bilibili_share_probability",
            "bilibili_share_min_score",
            "enable_news_integration",
            "enable_news_boredom_read",
            "enable_news_daily_hot_read",
            "enable_ai_daily_watch",
            "ai_daily_sources",
            "ai_daily_prefer_text_version",
            "enable_external_event_self_link",
            "news_min_interval_hours",
            "news_share_probability",
            "external_event_self_link_probability",
            "external_event_self_link_cooldown_hours",
            "external_link_share_cooldown_hours",
            "news_max_items_per_source",
            "news_sources",
            "news_hot_sources",
            "news_hot_max_items",
            "enable_web_exploration",
            "enable_web_exploration_boredom_search",
            "web_exploration_min_interval_hours",
            "web_exploration_share_probability",
            "web_exploration_max_results",
            "web_exploration_interests",
            "WEB_EXPLORATION_API_BASE_URL",
            "WEB_EXPLORATION_API_KEY",
            "WEB_EXPLORATION_API_MODEL",
            "enable_qzone_integration",
            "QZONE_COOKIE",
            "enable_qzone_life_publish",
            "qzone_life_publish_min_interval_hours",
            "qzone_life_publish_probability",
            "qzone_publish_style_prompt",
            "enable_qzone_generated_image_publish",
            "qzone_generated_image_probability",
            "qzone_publish_image_style_prompt",
            "enable_qzone_comment_inbox",
            "qzone_comment_inbox_interval_minutes",
            "qzone_comment_inbox_recent_posts",
            "qzone_comment_inbox_max_replies_per_tick",
            "enable_qzone_emotional_vent_publish",
            "qzone_emotional_vent_threshold",
            "qzone_emotional_vent_cooldown_hours",
            "qzone_emotional_vent_probability",
            "enable_private_reading_integration",
            "enable_private_reading_boredom_read",
            "enable_private_reading_ask_recommendation",
            "enable_private_reading_preference_influence",
            "enable_unanswered_screen_peek_followup",
            "unanswered_screen_peek_after_minutes",
            "unanswered_screen_peek_cooldown_minutes",
            "private_reading_min_interval_hours",
            "private_reading_max_photo_count",
            "private_reading_share_probability",
            "private_reading_ask_probability",
            "private_reading_preference_min_ratings",
            "private_reading_preference_max_terms",
            "private_reading_default_keywords",
            "private_reading_blocked_tags",
            "enable_unanswered_screen_peek_followup",
            "unanswered_screen_peek_after_minutes",
            "unanswered_screen_peek_cooldown_minutes",
            "enable_creative_writing",
            "creative_inspiration_probability",
            "creative_share_probability",
            "creative_chars_per_session",
            "creative_max_active_projects",
            "creative_hidden_mode",
            "creative_direction_prompt",
            "enable_worldbook_member_recognition",
            "worldbook_auto_import",
            "worldbook_member_match_aliases",
            "worldbook_self_registration",
            "worldbook_self_registration_block_words",
            "worldbook_self_registration_block_reply",
            "worldbook_auto_pending_observations",
            "worldbook_member_inject_limit",
            "worldbook_config_paths",
            "cross_user_memory_owner_only",
            "enable_atrelay_tools",
            "atrelay_require_worldbook_first",
            "atrelay_member_cache_minutes",
            "atrelay_sensitive_confirm",
            "enable_atrelay_llm_rewrite",
            "atrelay_default_relay_style",
            "atrelay_multi_target_limit",
        ]
        provider_keys = self._schema_provider_keys(public_only=True)
        for key in sorted(self._schema_setting_keys(public_only=True)):
            if key not in keys and key not in provider_keys:
                keys.append(key)
        values = {key: getattr(self.plugin, key, self._config_get(key)) for key in keys}
        values["private_user_aliases"] = self._private_alias_config_text("private_user_aliases")
        values["private_user_delivery_aliases"] = self._private_alias_config_text("private_user_delivery_aliases")
        values.update(
            {
                "enable_private_reading_integration": bool(getattr(self.plugin, "enable_jm_cosmos_integration", False)),
                "enable_private_reading_boredom_read": bool(getattr(self.plugin, "enable_jm_cosmos_boredom_read", False)),
                "enable_private_reading_ask_recommendation": bool(getattr(self.plugin, "enable_private_reading_ask_recommendation", False)),
                "enable_private_reading_preference_influence": bool(getattr(self.plugin, "enable_private_reading_preference_influence", True)),
                "private_reading_min_interval_hours": getattr(self.plugin, "jm_cosmos_min_interval_hours", 18),
                "private_reading_max_photo_count": getattr(self.plugin, "jm_cosmos_max_photo_count", 60),
                "private_reading_share_probability": getattr(self.plugin, "jm_cosmos_share_probability", 0.18),
                "private_reading_ask_probability": getattr(self.plugin, "private_reading_ask_probability", 0.16),
                "private_reading_preference_min_ratings": getattr(self.plugin, "private_reading_preference_min_ratings", 5),
                "private_reading_preference_max_terms": getattr(self.plugin, "private_reading_preference_max_terms", 8),
                "private_reading_default_keywords": getattr(self.plugin, "jm_cosmos_default_keywords", ""),
                "private_reading_blocked_tags": getattr(self.plugin, "private_reading_blocked_tags", "連載中,長篇,青年漫"),
                "group_repeat_trigger_threshold": int(getattr(self.plugin, "group_repeat_trigger_threshold", 4) or 4),
                "group_repeat_count_distinct_users_only": bool(getattr(self.plugin, "group_repeat_count_distinct_users_only", False)),
                "group_repeat_follow_probability": int(round(float(getattr(self.plugin, "group_repeat_follow_probability", 0.18) or 0) * 100)),
                "group_repeat_interrupt_probability": int(round(float(getattr(self.plugin, "group_repeat_interrupt_probability", 0.10) or 0) * 100)),
                "group_repeat_interrupt_probability_step": int(round(float(getattr(self.plugin, "group_repeat_interrupt_probability_step", 0.12) or 0) * 100)),
            }
        )
        def _percent_attr(name: str, default: float = 0.0, *, inherit: bool = False) -> int:
            try:
                raw = float(getattr(self.plugin, name, default) or 0.0)
            except (TypeError, ValueError):
                raw = default
            if inherit and raw < 0:
                return -1
            if raw <= 1:
                raw *= 100
            return max(-1 if inherit else 0, min(100, int(round(raw))))

        values.update(
            {
                "tts_trigger_probability": _percent_attr("tts_trigger_probability", 0.25),
                "tts_private_trigger_probability": _percent_attr("tts_private_trigger_probability", -0.01, inherit=True),
                "tts_group_trigger_probability": _percent_attr("tts_group_trigger_probability", -0.01, inherit=True),
                "auto_voice_probability": _percent_attr("auto_voice_probability", 0.25),
                "main_user_voice_probability": _percent_attr("main_user_voice_probability", -0.01, inherit=True),
                "main_user_mention_voice_probability": _percent_attr("main_user_mention_voice_probability", 0.0),
                "rest_reply_probability": _percent_attr("rest_reply_probability", 0.18),
            }
        )
        for key in self._schema_bool_keys():
            if key in values:
                values[key] = self._normalize_bool_value(values[key])
        return values

    def _proactive_intensity_summary(self) -> dict[str, Any]:
        runtime_getter = getattr(self.plugin, "_proactive_intensity_runtime", None)
        runtime = runtime_getter() if callable(runtime_getter) else {}
        if not isinstance(runtime, dict):
            runtime = {}
        effects = runtime.get("effects") if isinstance(runtime.get("effects"), dict) else {}

        def call_or_attr(method_name: str, attr_name: str, default: Any) -> Any:
            method = getattr(self.plugin, method_name, None)
            if callable(method):
                try:
                    return method()
                except Exception:
                    pass
            return getattr(self.plugin, attr_name, default)

        effective_max_daily = call_or_attr("_runtime_max_daily_messages", "max_daily_messages", 0)
        effective_group_interject_max_daily = call_or_attr(
            "_effective_group_interject_max_daily",
            "group_interject_max_daily",
            2,
        )
        limit_is_unlimited = getattr(self.plugin, "_proactive_daily_limit_is_unlimited", None)
        limit_formatter = getattr(self.plugin, "_format_proactive_daily_limit", None)
        max_daily_unlimited = bool(limit_is_unlimited(effective_max_daily)) if callable(limit_is_unlimited) else False
        group_interject_unlimited = bool(limit_is_unlimited(effective_group_interject_max_daily)) if callable(limit_is_unlimited) else False
        effective = {
            "max_daily_messages": effective_max_daily,
            "max_daily_messages_text": limit_formatter(effective_max_daily) if callable(limit_formatter) else str(effective_max_daily),
            "max_daily_messages_unlimited": max_daily_unlimited,
            "idle_minutes": effects.get("idle_minutes", getattr(self.plugin, "idle_minutes", 0)),
            "min_interval_minutes": effects.get("min_interval_minutes", getattr(self.plugin, "min_interval_minutes", 0)),
            "proactive_persona_judge_send_threshold": call_or_attr(
                "_effective_proactive_persona_judge_send_threshold",
                "proactive_persona_judge_send_threshold",
                62,
            ),
            "proactive_review_strength": call_or_attr("_effective_proactive_review_strength", "proactive_review_strength", "lenient"),
            "group_wakeup_cooldown_seconds": call_or_attr(
                "_effective_group_wakeup_cooldown_seconds",
                "group_wakeup_cooldown_seconds",
                90,
            ),
            "group_high_intensity_cooldown_seconds": call_or_attr(
                "_effective_group_high_intensity_cooldown_seconds",
                "group_high_intensity_cooldown_seconds",
                150,
            ),
            "group_interject_min_interval_minutes": call_or_attr(
                "_effective_group_interject_min_interval_minutes",
                "group_interject_min_interval_minutes",
                180,
            ),
            "group_interject_max_daily": effective_group_interject_max_daily,
            "group_interject_max_daily_text": limit_formatter(effective_group_interject_max_daily) if callable(limit_formatter) else str(effective_group_interject_max_daily),
            "group_interject_max_daily_unlimited": group_interject_unlimited,
            "group_wakeup_interest_probability": call_or_attr(
                "_effective_group_wakeup_interest_probability",
                "group_wakeup_interest_probability",
                0.18,
            ),
            "group_wakeup_question_threshold": call_or_attr(
                "_effective_group_wakeup_question_threshold",
                "group_wakeup_question_threshold",
                65,
            ),
            "group_wakeup_cold_group_threshold": call_or_attr(
                "_effective_group_wakeup_cold_group_threshold",
                "group_wakeup_cold_group_threshold",
                65,
            ),
            "ignore_token_soft_limit": bool(effects.get("ignore_token_soft_limit", False)),
            "ignore_daily_limit": bool(call_or_attr("_proactive_intensity_ignores_daily_limit", "ignore_daily_limit", False)),
        }
        # Display the same user-aware timing helpers used by the scheduler.
        # Copies prevent diagnostic role normalization from mutating live users.
        representative = None
        runtime_data = getattr(self.plugin, "data", {})
        raw_users = runtime_data.get("users", {}) if isinstance(runtime_data, dict) else {}
        role_getter = getattr(self.plugin, "_private_user_role", None)
        for value in raw_users.values() if isinstance(raw_users, dict) else []:
            if not isinstance(value, dict) or value.get("enabled") is False or value.get("manual_disabled"):
                continue
            candidate = deepcopy(value)
            if representative is None:
                representative = candidate
            try:
                if callable(role_getter) and role_getter(candidate) == "owner":
                    representative = candidate
                    break
            except Exception:
                pass
        companion_enabled_getter = getattr(self.plugin, "_companion_frequency_enabled", None)
        companion_enabled = bool(companion_enabled_getter()) if callable(companion_enabled_getter) else False
        effective["frequency_source"] = "companion" if companion_enabled else ("preset" if runtime.get("enabled") else "manual")
        effective["profile_scope"] = "managed_private" if representative is not None else "configuration_floor"
        for field, method_name in (("idle_minutes", "_effective_user_idle_minutes"),
                                   ("min_interval_minutes", "_effective_user_min_interval_minutes")):
            method = getattr(self.plugin, method_name, None)
            if representative is not None and callable(method):
                try:
                    effective[field] = method(deepcopy(representative))
                    continue
                except Exception:
                    pass
            if companion_enabled:
                attribute = "companion_recent_chat_minutes" if field == "idle_minutes" else "companion_min_interval_minutes"
                fallback = 20 if field == "idle_minutes" else 45
                effective[field] = max(int(getattr(self.plugin, attribute, fallback)), int(getattr(self.plugin, field, 0)))
        interval_getter = getattr(self.plugin, "_effective_min_interval_seconds", None)
        if representative is not None and callable(interval_getter):
            try:
                effective["current_min_interval_minutes"] = interval_getter(deepcopy(representative)) / 60
            except Exception:
                pass
        configured = {
            "max_daily_messages": getattr(self.plugin, "max_daily_messages", 0),
            "max_daily_messages_text": str(getattr(self.plugin, "max_daily_messages", 0)),
            "max_daily_messages_unlimited": False,
            "idle_minutes": getattr(self.plugin, "idle_minutes", 0),
            "min_interval_minutes": getattr(self.plugin, "min_interval_minutes", 0),
            "proactive_persona_judge_send_threshold": getattr(self.plugin, "proactive_persona_judge_send_threshold", 62),
            "proactive_review_strength": getattr(self.plugin, "proactive_review_strength", "lenient"),
            "group_wakeup_cooldown_seconds": getattr(self.plugin, "group_wakeup_cooldown_seconds", 90),
            "group_high_intensity_cooldown_seconds": getattr(self.plugin, "group_high_intensity_cooldown_seconds", 150),
            "group_interject_min_interval_minutes": getattr(self.plugin, "group_interject_min_interval_minutes", 180),
            "group_interject_max_daily": getattr(self.plugin, "group_interject_max_daily", 2),
            "group_interject_max_daily_text": str(getattr(self.plugin, "group_interject_max_daily", 2)),
            "group_interject_max_daily_unlimited": False,
            "group_wakeup_interest_probability": getattr(self.plugin, "group_wakeup_interest_probability", 0.18),
            "group_wakeup_question_threshold": getattr(self.plugin, "group_wakeup_question_threshold", 65),
            "group_wakeup_cold_group_threshold": getattr(self.plugin, "group_wakeup_cold_group_threshold", 65),
            "ignore_token_soft_limit": False,
            "ignore_daily_limit": False,
        }
        changed = [
            key
            for key, value in effective.items()
            if str(value) != str(configured.get(key))
        ]
        return {
            "preset": self._single_line(runtime.get("preset") or "off", 40),
            "enabled": bool(runtime.get("enabled")),
            "label": self._single_line(runtime.get("label") or "关闭预设", 40),
            "description": self._single_line(runtime.get("description"), 160),
            "configured": configured,
            "effective": effective,
            "changed_keys": changed,
            "note": (
                "私聊频率由统一陪伴规则和用户设置共同决定，旧预设不能突破陪伴上限或缩短最小间隔；未回应退避仍可延长实际间隔。"
                if companion_enabled else
                "显示当前调度器实际使用的频率；免打扰、休息、用户拒绝、隐私和每日 Token 硬限额仍然生效。"
            ),
        }

    async def _record_personality_auto_tune_manual_values(self, changed: dict[str, Any]) -> None:
        manual_changes = {
            key: deepcopy(value)
            for key, value in (changed or {}).items()
            if key in self.PERSONALITY_AUTO_TUNE_KEYS
        }
        if not manual_changes:
            return
        async with self.plugin._data_lock:
            state = self.plugin.data.setdefault("personality_iteration_auto_tune", {})
            if not isinstance(state, dict):
                state = {}
                self.plugin.data["personality_iteration_auto_tune"] = state
            manual_values = state.setdefault("manual_values", {})
            if not isinstance(manual_values, dict):
                manual_values = {}
                state["manual_values"] = manual_values
            applied = state.setdefault("applied", {})
            if not isinstance(applied, dict):
                applied = {}
                state["applied"] = applied
            for key, value in manual_changes.items():
                manual_values[key] = deepcopy(value)
                applied.pop(key, None)
            state["manual_updated_at"] = time.time()
            state["last_manual_changes"] = deepcopy(manual_changes)
            self.plugin._save_data_sync()

    async def _maybe_apply_personality_iteration_auto_tune(self, users: dict[str, Any], groups: dict[str, Any]) -> dict[str, Any]:
        if not bool(getattr(self.plugin, "enable_personality_iteration_experiment", False)):
            return await self._restore_personality_iteration_auto_tune("角色贴合校准已关闭")
        if not bool(getattr(self.plugin, "enable_personality_iteration_auto_tune", False)):
            return await self._restore_personality_iteration_auto_tune("角色贴合自主调节已关闭")

        suggestions = self._personality_iteration_suggestions(users, groups)
        state_snapshot = await self._personality_auto_tune_state_snapshot()
        manual_values = state_snapshot.get("manual_values") if isinstance(state_snapshot.get("manual_values"), dict) else {}
        applied_for_sync = state_snapshot.get("applied") if isinstance(state_snapshot.get("applied"), dict) else {}
        manual_values, applied_for_sync = await self._sync_personality_auto_tune_manual_snapshot(manual_values, applied_for_sync)
        reference_values = {
            key: deepcopy(manual_values.get(key, self._personality_auto_tune_current_value(key)))
            for key in self.PERSONALITY_AUTO_TUNE_KEYS
        }
        plan = self._personality_iteration_auto_tune_plan(suggestions, reference_values)
        applied_snapshot = applied_for_sync

        if not plan:
            if applied_snapshot:
                return await self._restore_personality_iteration_auto_tune("当前没有需要自主调节的角色贴合问题")
            await self._remember_personality_auto_tune_status(
                {
                    "changed": False,
                    "reason": "暂无需要自主调节的角色贴合问题",
                    "suggestion_count": len(suggestions),
                    "updated_at": time.time(),
                }
            )
            return {"changed": False, "reason": "暂无需要自主调节的角色贴合问题", "suggestion_count": len(suggestions)}

        restore_keys = [key for key in applied_snapshot if key in self.PERSONALITY_AUTO_TUNE_KEYS and key not in plan]
        restored_result: dict[str, Any] = {}
        if restore_keys:
            restored_result = await self._restore_personality_iteration_auto_tune(
                "对应角色贴合问题已消失",
                keys=restore_keys,
                keep_state=True,
            )

        changes: list[dict[str, Any]] = []
        async with self.plugin._data_lock:
            state = self.plugin.data.setdefault("personality_iteration_auto_tune", {})
            if not isinstance(state, dict):
                state = {}
                self.plugin.data["personality_iteration_auto_tune"] = state
            manual_values = state.setdefault("manual_values", {})
            if not isinstance(manual_values, dict):
                manual_values = {}
                state["manual_values"] = manual_values
            applied = state.setdefault("applied", {})
            if not isinstance(applied, dict):
                applied = {}
                state["applied"] = applied
            for key in self.PERSONALITY_AUTO_TUNE_KEYS:
                current_value = self._personality_auto_tune_current_value(key)
                applied_value = applied.get(key)
                manual_value = manual_values.get(key)
                if key not in manual_values:
                    manual_values[key] = deepcopy(current_value)
                elif key in applied and current_value != applied_value and current_value != manual_value:
                    # The value changed outside the auto tuner, so treat it as the user's new manual baseline.
                    manual_values[key] = deepcopy(current_value)
                    applied.pop(key, None)
                elif key not in applied and current_value != manual_value:
                    # The official config page can change values without calling this page's update endpoint.
                    manual_values[key] = deepcopy(current_value)
            for key, item in plan.items():
                if key not in self.PERSONALITY_AUTO_TUNE_KEYS:
                    continue
                next_value = self._normalize_setting_value(key, item.get("value"))
                current_value = self._personality_auto_tune_current_value(key)
                if current_value == next_value:
                    applied[key] = deepcopy(next_value)
                    continue
                applied[key] = deepcopy(next_value)
                changes.append(
                    {
                        "key": key,
                        "label": self._personality_auto_tune_label(key),
                        "from": current_value,
                        "to": next_value,
                        "manual": deepcopy(manual_values.get(key)),
                        "reason": self._single_line(item.get("reason"), 120),
                    }
                )
            state["enabled"] = True
            state["last_suggestion_count"] = len(suggestions)
            state["last_tuned_at"] = time.time()
            if changes:
                state["last_changes"] = deepcopy(changes)
            self.plugin._save_data_sync()

        for change in changes:
            self._apply_config_value(change["key"], change["to"])
        config_saved = await self._save_config_if_possible() if changes else True
        result = {
            "changed": bool(changes),
            "changes": changes,
            "restored_changes": restored_result.get("changes", []) if isinstance(restored_result, dict) else [],
            "config_saved": config_saved,
            "suggestion_count": len(suggestions),
            "reason": "已按角色贴合诊断临时覆盖参数" if changes else "当前自动覆盖值已经符合目标",
        }
        await self._remember_personality_auto_tune_status(result)
        if changes:
            logger.info(
                "[PrivateCompanionPage] 角色贴合校准已自主调节参数: %s",
                "; ".join(f"{item['key']}={item['from']}->{item['to']}" for item in changes),
            )
        return result

    async def _personality_auto_tune_state_snapshot(self) -> dict[str, Any]:
        async with self.plugin._data_lock:
            state = self.plugin.data.get("personality_iteration_auto_tune")
            return deepcopy(state) if isinstance(state, dict) else {}

    async def _sync_personality_auto_tune_manual_snapshot(
        self,
        manual_values: dict[str, Any],
        applied: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        manual_values = dict(manual_values or {})
        applied = dict(applied or {})
        touched = False
        for key in self.PERSONALITY_AUTO_TUNE_KEYS:
            current_value = self._personality_auto_tune_current_value(key)
            manual_value = manual_values.get(key)
            applied_value = applied.get(key)
            if key not in manual_values:
                manual_values[key] = deepcopy(current_value)
                touched = True
            elif key in applied and current_value != applied_value and current_value != manual_value:
                manual_values[key] = deepcopy(current_value)
                applied.pop(key, None)
                touched = True
            elif key not in applied and current_value != manual_value:
                manual_values[key] = deepcopy(current_value)
                touched = True
        if touched:
            async with self.plugin._data_lock:
                state = self.plugin.data.setdefault("personality_iteration_auto_tune", {})
                if not isinstance(state, dict):
                    state = {}
                    self.plugin.data["personality_iteration_auto_tune"] = state
                state["manual_values"] = deepcopy(manual_values)
                state["applied"] = deepcopy(applied)
                state["manual_synced_at"] = time.time()
                self.plugin._save_data_sync()
        return manual_values, applied

    async def _remember_personality_auto_tune_status(self, status: dict[str, Any]) -> None:
        async with self.plugin._data_lock:
            state = self.plugin.data.setdefault("personality_iteration_auto_tune", {})
            if not isinstance(state, dict):
                state = {}
                self.plugin.data["personality_iteration_auto_tune"] = state
            state["last_status"] = deepcopy(status)
            state["last_status_at"] = time.time()
            self.plugin._save_data_sync()

    async def _restore_personality_iteration_auto_tune(
        self,
        reason: str = "",
        *,
        keys: list[str] | None = None,
        keep_state: bool = False,
    ) -> dict[str, Any]:
        async with self.plugin._data_lock:
            state = self.plugin.data.get("personality_iteration_auto_tune")
            if not isinstance(state, dict):
                return {}
            manual_values = state.get("manual_values")
            if not isinstance(manual_values, dict):
                manual_values = state.get("baseline") if isinstance(state.get("baseline"), dict) else {}
            applied = state.get("applied") if isinstance(state.get("applied"), dict) else {}
            target_keys = [key for key in (keys or list(applied.keys())) if key in self.PERSONALITY_AUTO_TUNE_KEYS]
            restore_values = {
                key: deepcopy(manual_values.get(key))
                for key in target_keys
                if key in manual_values
            }
        if not restore_values:
            return {}

        restored: dict[str, Any] = {}
        changes: list[dict[str, Any]] = []
        for key, manual_value in restore_values.items():
            current_value = self._personality_auto_tune_current_value(key)
            normalized = self._normalize_setting_value(key, manual_value)
            self._apply_config_value(key, normalized)
            restored[key] = normalized
            if current_value != normalized:
                changes.append(
                    {
                        "key": key,
                        "label": self._personality_auto_tune_label(key),
                        "from": current_value,
                        "to": normalized,
                        "reason": self._single_line(reason, 120) or "恢复用户最后一次手动设置",
                    }
                )
        config_saved = await self._save_config_if_possible()
        async with self.plugin._data_lock:
            state = self.plugin.data.setdefault("personality_iteration_auto_tune", {})
            if keep_state:
                applied = state.get("applied") if isinstance(state.get("applied"), dict) else {}
                for key in restored:
                    applied.pop(key, None)
                state["applied"] = applied
            else:
                state.clear()
            state["last_restore"] = {
                "restored": deepcopy(restored),
                "changes": deepcopy(changes),
                "reason": self._single_line(reason, 160),
                "restored_at": time.time(),
                "config_saved": config_saved,
            }
            self.plugin._save_data_sync()
        if changes:
            logger.info(
                "[PrivateCompanionPage] 角色贴合校准已恢复用户手动参数: %s",
                "; ".join(f"{item['key']}={item['from']}->{item['to']}" for item in changes),
            )
        return {
            "restored": restored,
            "changes": changes,
            "reason": self._single_line(reason, 160),
            "config_saved": config_saved,
        }

    def _personality_iteration_auto_tune_plan(
        self,
        suggestions: list[dict[str, str]],
        reference_values: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        reference_values = reference_values or {}
        plan: dict[str, dict[str, Any]] = {}

        def current_int(key: str, default: int = 0) -> int:
            return self._int(reference_values.get(key, getattr(self.plugin, key, default)), default)

        def current_text(key: str, default: str = "") -> str:
            return str(reference_values.get(key, getattr(self.plugin, key, default)) or default).strip()

        def propose(key: str, value: Any, reason: str) -> None:
            normalized = self._normalize_setting_value(key, value)
            if self._normalize_setting_value(key, reference_values.get(key, self._personality_auto_tune_current_value(key))) == normalized:
                return
            existing = plan.get(key)
            if existing:
                existing["value"] = normalized
                existing["reason"] = f"{existing.get('reason')}; {reason}"
            else:
                plan[key] = {"value": normalized, "reason": reason}

        def raise_to(key: str, target: int, step: int, reason: str, default: int = 0) -> None:
            current = current_int(key, default)
            if current < target:
                propose(key, min(target, current + step), reason)

        def lower_to(key: str, target: int, step: int, reason: str, default: int = 0) -> None:
            current = current_int(key, default)
            if current > target:
                propose(key, max(target, current - step), reason)

        def set_review_balanced(reason: str) -> None:
            if current_text("proactive_review_strength", "lenient") == "lenient":
                propose("proactive_review_strength", "balanced", reason)

        def soften_high_preset(reason: str) -> None:
            preset = current_text("proactive_intensity_preset", "off")
            if preset in {"live", "high_private"}:
                propose("proactive_intensity_preset", "balanced", reason)

        for suggestion in suggestions:
            dimension = self._single_line(suggestion.get("dimension"), 80)
            level = self._single_line(suggestion.get("level"), 16)
            if level not in {"warn", "error", "info"}:
                continue
            if "外向性表现偏高" in dimension:
                soften_high_preset("外向性偏高时先从最高主动预设退到标准偏主动")
                lower_to("max_daily_messages", 8, 2, "外向性偏高，降低每日私聊主动上限", 8)
                raise_to("idle_minutes", 45, 15, "外向性偏高，拉长空闲判定", 60)
                raise_to("min_interval_minutes", 90, 30, "外向性偏高，拉长主动最小间隔", 120)
                raise_to("proactive_persona_judge_send_threshold", 58, 4, "外向性偏高，提高主动人格放行阈值", 62)
            elif "焦虑型追问倾向" in dimension:
                soften_high_preset("沉默后仍追问时先从最高主动预设退到标准偏主动")
                lower_to("max_daily_messages", 6, 2, "焦虑型追问倾向，降低每日主动上限", 8)
                raise_to("min_interval_minutes", 180, 60, "焦虑型追问倾向，显著拉长主动间隔", 120)
                raise_to("proactive_persona_judge_send_threshold", 64, 6, "焦虑型追问倾向，提高主动放行阈值", 62)
                set_review_balanced("焦虑型追问倾向，主动复核由宽松改为标准")
            elif "回避型收缩风险" in dimension:
                lower_to("min_interval_minutes", 240, 60, "回避型收缩风险，保留低打扰入口", 120)
                lower_to("idle_minutes", 120, 30, "回避型收缩风险，避免完全退开", 60)
                if 0 < current_int("max_daily_messages", 8) < 2:
                    propose("max_daily_messages", 2, "回避型收缩风险，保留很低频主动上限")
                if current_int("proactive_persona_judge_send_threshold", 62) > 70:
                    lower_to("proactive_persona_judge_send_threshold", 66, 4, "回避型收缩风险，放宽过高的主动阈值", 62)
            elif "动机质量偏低" in dimension:
                raise_to("proactive_persona_judge_send_threshold", 60, 4, "主动由头偏弱，提高放行阈值", 62)
                set_review_balanced("主动由头偏弱，主动复核由宽松改为标准")
            elif "讨好型修复倾向" in dimension:
                raise_to("proactive_persona_judge_send_threshold", 62, 4, "讨好型修复倾向，提高主动放行阈值", 62)
                set_review_balanced("讨好型修复倾向，主动复核由宽松改为标准")
        return plan

    def _personality_auto_tune_current_value(self, key: str) -> Any:
        return getattr(self.plugin, key, self._config_get(key))

    @staticmethod
    def _personality_auto_tune_label(key: str) -> str:
        labels = {
            "proactive_intensity_preset": "主动强度预设",
            "max_daily_messages": "每日私聊主动上限",
            "idle_minutes": "空闲判定分钟",
            "min_interval_minutes": "主动最小间隔分钟",
            "proactive_persona_judge_send_threshold": "主动人格放行阈值",
            "proactive_review_strength": "主动复核强度",
        }
        return labels.get(key, key)

    def _personality_auto_tune_diagnostic_item(self, result: dict[str, Any] | None) -> dict[str, str] | None:
        if not isinstance(result, dict) or not result:
            return None
        changes = result.get("changes") if isinstance(result.get("changes"), list) else []
        restored_changes = result.get("restored_changes") if isinstance(result.get("restored_changes"), list) else []
        if result.get("restored") is not None:
            restored_changes = changes
        if restored_changes:
            text = "；".join(
                f"{self._single_line(item.get('label'), 30)}：{item.get('from')} → {item.get('to')}"
                for item in restored_changes[:6]
            )
            return {
                "level": "ok",
                "title": "角色贴合校准：已恢复用户手动参数",
                "text": text,
                "action": "关闭角色贴合校准、关闭自主调节，或对应问题消失后，会恢复到用户最后一次手动设置的值。",
            }
        if not result.get("changed") or not changes:
            return None
        text = "；".join(
            f"{self._single_line(item.get('label'), 30)}：{item.get('from')} → {item.get('to')}（手动值 {item.get('manual')}；{self._single_line(item.get('reason'), 60)}）"
            for item in changes[:6]
        )
        return {
            "level": "info",
            "title": "角色贴合校准：已自主调节参数",
            "text": text,
            "action": "这是临时覆盖；用户再次手动调整后会更新手动值，关闭功能时恢复到最新手动值。",
        }

    def _build_diagnostics(self, users: dict[str, Any], groups: dict[str, Any]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []

        def add(level: str, title: str, text: str, action: str = "", warning_code: str = "") -> None:
            item = {"level": level, "title": title, "text": text, "action": action}
            if warning_code:
                item["warning_code"] = warning_code
                item["warning_type"] = self._troubleshooting_semantic_warning_type(warning_code)
            items.append(item)

        features = self._feature_flags()
        providers = self._provider_settings()
        group_mode = str(getattr(self.plugin, "group_access_mode", "whitelist") or "whitelist")
        whitelist = self.plugin._configured_group_ids()
        blacklist = self.plugin._configured_group_blacklist_ids()
        enabled_users = sum(1 for item in users.values() if isinstance(item, dict) and item.get("enabled", True))
        enabled_groups = sum(1 for item in groups.values() if isinstance(item, dict) and item.get("enabled", True))

        if getattr(self.plugin, "enabled", False):
            add("ok", "插件已启用", "后台主动检查与事件处理会正常运行")
        else:
            add("error", "插件未启用", "当前不会进行私聊主动陪伴或群聊观察", "在配置中打开 enabled")

        if providers.get("LLM_PROVIDER_ID") or getattr(self.plugin, "llm_provider_id", ""):
            add("ok", "主模型可见", providers.get("LLM_PROVIDER_ID") or "运行态已配置")
        else:
            add("info", "主模型留空", "会回退到 AstrBot 默认模型；建议为陪伴插件单独配置主模型")

        intensity = self._proactive_intensity_summary()
        if intensity.get("enabled"):
            effective = intensity.get("effective") if isinstance(intensity.get("effective"), dict) else {}
            add(
                "info",
                f"正在使用主动强度预设：{intensity.get('label') or intensity.get('preset')}",
                (
                    f"私聊有效上限 {effective.get('max_daily_messages_text') or effective.get('max_daily_messages')}，"
                    f"空闲 {effective.get('idle_minutes')} 分钟，"
                    f"最小间隔 {effective.get('min_interval_minutes')} 分钟；"
                    f"群唤醒冷却 {effective.get('group_wakeup_cooldown_seconds')} 秒，"
                    f"群插话间隔 {effective.get('group_interject_min_interval_minutes')} 分钟，"
                    f"群插话上限 {effective.get('group_interject_max_daily_text') or effective.get('group_interject_max_daily')}，"
                    f"兴趣唤醒概率 {round(float(effective.get('group_wakeup_interest_probability') or 0) * 100)}%。"
                    f"{'当前最高档会忽略 Token 软限额降载；' if effective.get('ignore_token_soft_limit') else ''}"
                    "启用预设是正常配置状态。私聊以当前陪伴规则与用户设置为准，不会绕过免打扰、休息、用户拒绝、隐私和硬限额。"
                ),
                "需要恢复原配置时，将“主动强度预设”改为关闭",
                "proactive.intensity_preset",
            )
        else:
            add(
                "info",
                "主动强度预设未启用",
                "当前私聊使用统一陪伴规则与用户设置；未启用旧强度预设。"
                if intensity.get("effective", {}).get("frequency_source") == "companion" else
                "当前沿用手动主动频率参数。",
            )

        tts_summary = self._tts_runtime_summary(users)
        if tts_summary.get("enhancement_enabled"):
            if tts_summary.get("provider_available"):
                add(
                    "ok",
                    "TTS 语音链路可用",
                    f"模式 {tts_summary.get('mode')}，语种 {tts_summary.get('language')}，真实 TTS provider：{tts_summary.get('provider_label')}",
                )
            elif tts_summary.get("settings_enabled"):
                add(
                    "warn",
                    "TTS 配置已开但 provider 不可用",
                    f"会话 {tts_summary.get('umo') or '-'} 已启用 TTS 设置，但当前取不到可用 TTS provider",
                    "在 AstrBot 会话 TTS 配置里选择并启用真实语音合成 provider",
                    "tts.provider_unavailable",
                )
            else:
                add(
                    "warn",
                    "TTS 强化已开但会话 TTS 未启用",
                    "本插件只能处理 <tts> 标签和文本转换；真正合成音频需要 AstrBot 当前会话启用 TTS provider",
                    "到 AstrBot 配置中为目标会话启用 TTS provider",
                    "tts.provider_unavailable",
                )
        else:
            add(
                "info",
                "TTS 强化未开启",
                "VOICE_PROMPT_PROVIDER_ID / TTS文本转换模型都是文本模型；语音合成模型请在 AstrBot TTS provider 中配置",
            )

        if enabled_users:
            add("ok", "私聊对象已就绪", f"已启用 {enabled_users} 个私聊对象")
        else:
            add("warn", "暂无启用的私聊对象", "私聊主动陪伴没有明确目标", "在私聊页新增对象或配置 target_user_ids", "proactive.no_enabled_users")

        max_daily = int(getattr(self.plugin, "max_daily_messages", 0) or 0)
        effective_max_daily = max_daily
        max_daily_getter = getattr(self.plugin, "_runtime_max_daily_messages", None)
        if callable(max_daily_getter):
            try:
                effective_max_daily = int(max_daily_getter() or 0)
            except Exception:
                effective_max_daily = max_daily
        if effective_max_daily > 0:
            limit_formatter = getattr(self.plugin, "_format_proactive_daily_limit", None)
            limit_is_unlimited = getattr(self.plugin, "_proactive_daily_limit_is_unlimited", None)
            effective_limit_text = limit_formatter(effective_max_daily) if callable(limit_formatter) else str(effective_max_daily)
            detail = f"每日有效上限 {effective_limit_text}"
            if effective_max_daily != max_daily:
                detail += f"（手动配置 {max_daily} 条）"
            if callable(limit_is_unlimited) and limit_is_unlimited(effective_max_daily):
                detail += "，当前最高档不按每日主动次数封顶"
            add("ok", "私聊主动额度可用", detail)
        else:
            add("warn", "私聊主动已关闭", "每日主动上限为 0", "在模块配置里调高每日主动上限", "proactive.daily_limit_zero")

        if getattr(self.plugin, "enable_daily_token_soft_limit", True):
            soft_limit = int(getattr(self.plugin, "daily_token_soft_limit", 0) or 0)
            today_tokens = int(getattr(self.plugin, "_today_llm_token_total", lambda: 0)() or 0)
            ignore_soft_limit = bool(self._proactive_intensity_summary().get("effective", {}).get("ignore_token_soft_limit"))
            if soft_limit > 0 and today_tokens >= soft_limit:
                if ignore_soft_limit:
                    add(
                        "warn",
                        "Token 软限额已触发但最高档放行",
                        f"今日已用约 {today_tokens} Token；当前主动强度最高档会忽略软限额降载，低优先级任务仍可继续运行",
                        warning_code="token.soft_limit_ignored",
                    )
                else:
                    add(
                        "warn",
                        "每日 Token 软限额已接管",
                        f"今日已用约 {today_tokens} Token，低优先级后台 LLM 任务会暂缓",
                        warning_code="token.soft_limit_active",
                    )
            elif soft_limit > 0:
                add("ok", "每日 Token 软限额已启用", f"软限额 {soft_limit}，当前约 {today_tokens}")
            else:
                add("info", "每日 Token 软限额未设置", "只使用每日硬限额")
        else:
            add("info", "每日 Token 软限额已关闭", "功能全开时后台任务会按各自开关正常运行")

        if features.get("enable_companion_memory"):
            add("ok", "私聊长期画像已启用", "按私聊对象整理偏好、边界、关系线索和重要事实")
        else:
            add("info", "私聊长期画像已关闭", "不会新增私聊长期画像，已有资料仍可管理")
        if features.get("enable_expression_learning"):
            add("ok", "通用表达学习已启用", "按学习页设置的来源与范围用于私聊、主动私聊和群聊")
        else:
            add("info", "通用表达学习已关闭", "不会继续归纳或注入表达规则")

        if features.get("enable_livingmemory_integration"):
            living_summary = self._livingmemory_summary()
            living_level = "warn" if living_summary.get("conflict") else ("ok" if living_summary.get("compatible_available") else "warn")
            if living_summary.get("coexistence_detected"):
                living_level = "info"
                living_text = str(living_summary.get("coexistence_note") or "记忆沉淀与书架按需检索同时可用；共存本身不代表故障。")
            elif living_summary.get("conflict_warning"):
                living_text = str(living_summary.get("conflict_warning") or "")
            elif living_summary.get("selected_plugin_name"):
                living_text = f"当前使用：{living_summary.get('selected_plugin_name')}"
            else:
                living_text = "已启用协同，但当前未检测到可用记忆插件"
            add(
                living_level,
                "记忆插件协同",
                living_text,
                warning_code=("memory.capabilities_coexist" if living_summary.get("coexistence_detected") else
                              "memory.integration_conflict" if living_summary.get("conflict") else
                              "memory.integration_available" if living_summary.get("compatible_available") else "memory.integration_unavailable"),
            )

        if features.get("enable_bilibili_integration"):
            bili_available = bool(getattr(self.plugin, "_bilibili_available", lambda: False)())
            add(
                "ok" if bili_available else "info",
                "B站 AI Bot 联动",
                "已检测到 B站 AI Bot 或观看日志" if bili_available else "联动开关已开，但暂未检测到 B站 AI Bot 实例或日志",
            )

        if features.get("enable_private_reading_integration"):
            jm_available = bool(getattr(self.plugin, "_jm_cosmos_available", lambda: False)())
            add(
                "ok" if jm_available else "info",
                "夹层阅读素材",
                "已检测到可用素材能力" if jm_available else "开关已开，但暂未检测到可用素材能力",
            )

        if features.get("enable_photo_text_action") and getattr(self.plugin, "enable_local_photo_load_guard", False):
            load_state = getattr(self.plugin, "_local_photo_generation_load_state", lambda: {})()
            if isinstance(load_state, dict):
                if load_state.get("available"):
                    add(
                        "warn" if load_state.get("busy") else "ok",
                        "本地生图负载保护",
                        str(load_state.get("reason") or "负载正常"),
                        warning_code="image.local_load_busy" if load_state.get("busy") else "",
                    )
                else:
                    add("info", "本地生图负载保护未采样", str(load_state.get("reason") or "无法读取系统负载"))

        if features.get("enable_photo_text_action") and getattr(self.plugin, "_external_photo_available", lambda: False)():
            model_checker = getattr(self.plugin, "_external_image_model_misconfiguration_note", None)
            model_note = model_checker() if callable(model_checker) else ""
            if model_note:
                add(
                    "error",
                    "在线图片模型配置错误",
                    model_note,
                    "把 EXTERNAL_IMAGE_API_MODEL 改成该平台的图片模型名，不要填聊天模型",
                )

        llm_perception_available = bool(getattr(self.plugin, "_llmperception_available", lambda: False)())
        if llm_perception_available:
            if features.get("enable_environment_perception"):
                add(
                    "warn",
                    "检测到 LLMPerception 插件",
                    "本插件已内置时间、节假日、农历节气和平台环境感知；两者同时启用会重复注入并增加 Token 消耗",
                    "建议手动二选一；本插件不会再自动改写 enable_environment_perception",
                    "integration.environment_duplicate",
                )
            else:
                add("ok", "环境感知由外部插件接管", "检测到 LLMPerception，且本插件内置环境感知当前为关闭")

        if features.get("enable_creative_writing"):
            projects = self._creative_summary({"creative_projects": getattr(self.plugin, "data", {}).get("creative_projects", [])})
            active = projects.get("active_projects", 0)
            add(
                "ok" if active else "info",
                "私下创作行为",
                f"当前进行中创作 {active} 个" if active else "已开启；会在生活/梦境触发后慢慢开坑",
            )

        if getattr(self.plugin, "enable_group_companion", False):
            if group_mode == "whitelist" and not whitelist:
                add("warn", "群聊白名单为空", "白名单模式下所有群都会被拦截", "在配置页加入群号或切换为黑名单模式", "group.whitelist_empty")
            elif group_mode == "blacklist":
                add("ok", "群聊黑名单模式", f"已屏蔽 {len(blacklist)} 个群，其余群可观察")
            else:
                add("ok", "群聊白名单模式", f"允许 {len(whitelist)} 个群")

            if enabled_groups:
                add("ok", "已有群聊观测数据", f"已启用 {enabled_groups} 个群")
            else:
                add("info", "暂无群聊观测数据", "收到群消息后会逐步建立群内观察")
        else:
            add("info", "群聊陪伴未开启", "当前不会记录群聊上下文")

        if features.get("enable_group_interjection"):
            limit_getter = getattr(self.plugin, "_effective_group_interject_max_daily", None)
            limit = int(limit_getter() if callable(limit_getter) else getattr(self.plugin, "group_interject_max_daily", 0) or 0)
            if limit > 0:
                limit_formatter = getattr(self.plugin, "_format_proactive_daily_limit", None)
                limit_text = limit_formatter(limit) if callable(limit_formatter) else str(limit)
                suffix = "" if limit_text == "不限" else " 次"
                add("ok", "群聊插话可用", f"每群每日上限 {limit_text}{suffix}")
            else:
                add("warn", "群聊插话开关已开但额度为 0", "功能不会真正触发", "在模块配置里调高每群每日插话上限", "group.interject_limit_zero")
        elif getattr(self.plugin, "enable_group_companion", False):
            add("info", "群聊以观察为主", "当前只积累群上下文，不主动插话")

        context_aware_installed = bool(getattr(self.plugin, "_context_aware_available", lambda: False)())
        if context_aware_installed:
            if features.get("enable_group_scene_awareness"):
                add(
                    "warn",
                    "检测到上下文场景感知增强插件",
                    "不会造成代码级冲突，但若两个插件同时注入群聊场景，会增加重复上下文和 Token 消耗",
                    "建议手动二选一；本插件不会再自动改写 enable_group_scene_awareness",
                    "integration.context_aware_duplicate",
                )
            else:
                add("ok", "群聊场景感知由外部插件接管", "检测到 context_aware，且本插件对应内置功能当前为关闭")

        atrelay_installed = bool(getattr(self.plugin, "_atrelay_plugin_available", lambda: False)())
        if atrelay_installed:
            if features.get("enable_atrelay_tools"):
                add(
                    "warn",
                    "检测到艾特群友插件",
                    "本插件已内置跨群转述与 @ 群友工具；两者同时启用可能让模型看到重复工具",
                    "建议手动二选一；本插件不会再自动改写 enable_atrelay_tools",
                    "integration.atrelay_duplicate",
                )
            else:
                add("ok", "跨群转述由外部插件接管", "检测到 atrelay，且本插件对应内置工具当前为关闭")

        if not features.get("enable_group_privacy_guard"):
            add("warn", "群聊隐私保护未开启", "私聊记忆注入群聊时缺少额外防护", "建议打开 enable_group_privacy_guard", "group.privacy_guard_disabled")

        refresh_minutes = int(getattr(self.plugin, "memory_refresh_interval_minutes", 0) or 0)
        if refresh_minutes and refresh_minutes < 60:
            add("warn", "长期记忆整理过于频繁", f"当前 {refresh_minutes} 分钟，可能增加模型调用量", "建议设置为 120 分钟以上", "memory.refresh_too_frequent")

        if features.get("enable_personality_iteration_experiment"):
            suggestions = self._personality_iteration_suggestions(users, groups)
            if suggestions:
                for suggestion in suggestions:
                    dimension = self._single_line(suggestion.get("dimension"), 40)
                    dimension_code = hashlib.sha256(dimension.encode("utf-8")).hexdigest()[:12]
                    add(
                        self._single_line(suggestion.get("level"), 12) or "info",
                        f"角色贴合校准：{dimension}",
                        self._single_line(suggestion.get("text"), 260),
                        self._single_line(suggestion.get("action"), 160),
                        f"personality.{dimension_code}",
                    )
            else:
                add(
                    "ok",
                    "角色贴合校准",
                    "已启用理论检查，暂未从运行态观察到需要调整的角色贴合问题；该功能只帮助用户定位调整方向，不会自动修改 AstrBot 人格。",
                )

        return items

    def _personality_iteration_suggestions(self, users: dict[str, Any], groups: dict[str, Any]) -> list[dict[str, str]]:
        data = getattr(self.plugin, "data", {}) if isinstance(getattr(self.plugin, "data", {}), dict) else {}
        raw_candidates = data.get("proactive_candidate_pool") if isinstance(data.get("proactive_candidate_pool"), list) else []
        recent_candidates = [item for item in raw_candidates[-80:] if isinstance(item, dict)]
        suggestions: list[dict[str, str]] = []

        def add(level: str, dimension: str, evidence: str, risk: str, suggestion: str, scope: str, confidence: str = "中") -> None:
            text = f"校准依据：{dimension}；运行证据：{evidence}；可能不贴合：{risk}；调整位置：{scope}；建议写法：{suggestion}；置信度：{confidence}。"
            suggestions.append(
                {
                    "level": level,
                    "dimension": dimension,
                    "text": text,
                    "action": suggestion,
                }
            )

        def candidate_text(item: dict[str, Any]) -> str:
            parts = [
                item.get("reason"),
                item.get("action"),
                item.get("topic"),
                item.get("motive"),
                item.get("note"),
                item.get("semantic_kind"),
                item.get("semantic_note"),
            ]
            return " ".join(self._single_line(part, 120) for part in parts if part)

        candidate_texts = [candidate_text(item) for item in recent_candidates]
        joined_candidates = "\n".join(candidate_texts[-40:])
        generic_markers = (
            "check_in",
            "greeting",
            "morning",
            "evening",
            "近况",
            "问候",
            "早安",
            "晚安",
            "在吗",
            "忙不忙",
            "还好吗",
            "有没有空",
        )
        concrete_markers = (
            "qzone",
            "news",
            "bilibili",
            "reading",
            "web",
            "日程",
            "空间",
            "新闻",
            "视频",
            "阅读",
            "创作",
            "天气",
            "通勤",
            "图片",
            "照片",
            "说说",
        )
        generic_count = sum(1 for text in candidate_texts if any(marker in text.lower() for marker in generic_markers))
        concrete_count = sum(1 for text in candidate_texts if any(marker in text.lower() for marker in concrete_markers))
        pending_generic = [
            item
            for item in recent_candidates
            if self._single_line(item.get("status"), 24).lower() in {"", "accepted", "deferred", "queued", "pending", "unknown"}
            and any(marker in candidate_text(item).lower() for marker in generic_markers)
        ]

        enabled_user_items = [item for item in users.values() if isinstance(item, dict) and item.get("enabled", True)]
        active_users: list[dict[str, Any]] = []
        unanswered_users: list[dict[str, Any]] = []
        high_sent_users: list[dict[str, Any]] = []
        for user in enabled_user_items:
            if bool(getattr(self.plugin, "_user_enabled_for_proactive", lambda uid, profile: bool(profile and profile.get("enabled", True)))(
                str(user.get("user_id") or ""),
                user,
            )):
                active_users.append(user)
            ignored = self._int(user.get("ignored_streak"))
            sent_today = self._int(user.get("sent_today"))
            if ignored >= 2:
                unanswered_users.append(user)
            if sent_today >= 4:
                high_sent_users.append(user)

        effective_max_daily = self._int(getattr(self.plugin, "max_daily_messages", 0))
        max_daily_getter = getattr(self.plugin, "_runtime_max_daily_messages", None)
        if callable(max_daily_getter):
            try:
                effective_max_daily = self._int(max_daily_getter())
            except Exception:
                pass
        idle_minutes = self._int(getattr(self.plugin, "idle_minutes", 0))
        min_interval = self._int(getattr(self.plugin, "min_interval_minutes", 0))

        if active_users and (effective_max_daily >= 10 or (idle_minutes and idle_minutes <= 30) or high_sent_users):
            evidence_parts = []
            if effective_max_daily >= 10:
                evidence_parts.append(f"私聊主动上限 {effective_max_daily}")
            if idle_minutes and idle_minutes <= 30:
                evidence_parts.append(f"空闲 {idle_minutes} 分钟即可主动")
            if high_sent_users:
                labels = [self._single_line(item.get("nickname") or item.get("user_id"), 32) for item in high_sent_users[:3]]
                evidence_parts.append(f"今日主动较多：{'、'.join(labels)}")
            add(
                "warn",
                "艾森克 PEN：外向性表现偏高",
                "，".join(evidence_parts) or "主动频率较高",
                "如果角色基线不是高外向，容易从“自然有生活”变成“总想找人说话”。",
                "主动靠近需要具体由头；连续无人回应时优先安静生活，不继续泛泛问候。",
                "AstrBot 人格 / 主动策略",
                "中",
            )

        if unanswered_users and (pending_generic or generic_count >= 3):
            labels = [self._single_line(item.get("nickname") or item.get("user_id"), 32) for item in unanswered_users[:3]]
            add(
                "warn",
                "依恋风格：焦虑型追问倾向",
                f"{'、'.join(labels)} 未回应次数较高；近期仍存在 {len(pending_generic) or generic_count} 条问候/近况类主动候选",
                "如果角色应当给人稳定感，沉默后追问会像在索取回应。",
                "对方沉默时先降频；只在有明确事件、共同约定或用户关心的内容时再开口。",
                "AstrBot 人格 / 私聊主动强度 / 关系策略",
                "高" if len(unanswered_users) >= 2 else "中",
            )

        if unanswered_users and min_interval >= 360 and not pending_generic:
            labels = [self._single_line(item.get("nickname") or item.get("user_id"), 32) for item in unanswered_users[:3]]
            add(
                "info",
                "依恋风格：回避型收缩风险",
                f"{'、'.join(labels)} 已有未回应记录；当前最小主动间隔 {min_interval} 分钟，且近期没有可解释的轻量候选",
                "如果角色基线是亲近但有边界，完全退开会显得忽冷忽热。",
                "保留低打扰入口：只在日程节点、共同约定或用户明确关心的事情上轻轻接一次。",
                "私聊主动强度 / 关系策略",
                "低",
            )

        if recent_candidates and generic_count >= 4 and concrete_count <= max(1, generic_count // 3):
            add(
                "warn",
                "自我决定理论：动机质量偏低",
                f"近期主动候选里泛问候约 {generic_count} 条，具体生活/外部事件锚点约 {concrete_count} 条",
                "主动缺少关系感、能力感或自主感来源时，会像模板关心而不是角色自然想说。",
                "主动来源优先写成三类：共同经历、用户正在做的事、角色自己的生活发现；没有锚点宁可不发。",
                "世界知识 / 主动来源 / 日程细化",
                "中",
            )

        if getattr(self.plugin, "enable_group_companion", False) and not bool(getattr(self.plugin, "enable_group_persona_denoise", False)):
            add(
                "info",
                "大五人格：宜人性与公开边界",
                "群聊陪伴已启用，但群聊人格去噪未开启",
                "如果角色私聊很亲近，群聊里照搬亲密语气会破坏公开场合边界。",
                "开启群聊人格去噪；或写明：私聊可亲近，群聊公开场合更克制、更少暧昧和私密称呼。",
                "群聊页 / AstrBot 人格",
                "低",
            )

        if bool(getattr(self.plugin, "enable_emotion_simulation", False)) and bool(getattr(self.plugin, "enable_qzone_emotional_vent_publish", False)):
            add(
                "info",
                "艾森克 PEN：情绪稳定性外显",
                "情绪模拟和 QQ 空间情绪宣泄动态同时开启",
                "如果角色不是高敏感外显型，公开宣泄会显得比设定更戏剧化。",
                "公开动态偏生活化；强烈情绪先私下整理，不把用户压力公开化。",
                "QQ 空间配置 / 世界知识 / AstrBot 人格",
                "低",
            )

        if joined_candidates and ("抱歉" in joined_candidates or "对不起" in joined_candidates) and generic_count >= 2:
            add(
                "info",
                "依恋风格：讨好型修复倾向",
                "近期主动候选同时出现道歉/修复表达和泛问候",
                "角色可能把普通沉默解释成自己做错了，导致姿态过低。",
                "只有用户明确不适或发生冲突时才道歉；日常沉默按对方忙处理。",
                "AstrBot 人格 / 回复策略 / 主动策略",
                "低",
            )

        return suggestions[:5]

    def _tts_runtime_summary(self, users: dict[str, Any]) -> dict[str, Any]:
        enabled_user = None
        for item in users.values():
            if isinstance(item, dict) and item.get("enabled", True) and item.get("umo"):
                enabled_user = item
                if self.plugin._private_user_role(item, str(item.get("user_id") or "")) == "owner":
                    break
        umo = self._single_line((enabled_user or {}).get("umo"), 180) if isinstance(enabled_user, dict) else ""
        config: dict[str, Any] = {}
        provider_settings: dict[str, Any] = {}
        provider = None
        context = getattr(self.plugin, "context", None)
        if context is not None:
            getter = getattr(context, "get_config", None)
            if callable(getter):
                try:
                    config = getter(umo) if umo else getter()
                    if not isinstance(config, dict):
                        config = {}
                except Exception:
                    config = {}
            provider_settings = dict((config or {}).get("provider_tts_settings", {}) or {})
            provider_getter = getattr(context, "get_using_tts_provider", None)
            if callable(provider_getter):
                try:
                    provider = provider_getter(umo) if umo else provider_getter()
                except Exception:
                    provider = None
        provider_label = ""
        if provider is not None:
            provider_id = self._provider_id(provider)
            provider_label = self._provider_name(provider, provider_id) if provider_id else getattr(provider, "__class__", type(provider)).__name__
        return {
            "enhancement_enabled": bool(getattr(self.plugin, "enable_tts_enhancement", False)),
            "mode": self._single_line(getattr(self.plugin, "tts_generation_mode", ""), 24) or "fast_tag",
            "language": self.plugin._tts_language_label() if hasattr(self.plugin, "_tts_language_label") else "",
            "delivery_mode": self._single_line(getattr(self.plugin, "tts_delivery_mode", ""), 32) or "voice_and_text",
            "foreign_text_mode": self._single_line(getattr(self.plugin, "tts_foreign_text_mode", ""), 32) or "translation",
            "conversion_scope": self._single_line(getattr(self.plugin, "tts_conversion_scope", ""), 24) or "partial",
            "umo": umo,
            "settings_enabled": bool(provider_settings.get("enable", False)),
            "provider_available": provider is not None,
            "provider_label": self._single_line(provider_label, 80) or "未知 provider",
        }

    def _message_debounce_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("smart_message_debounce")
        if not isinstance(raw, dict):
            raw = {}
        logs_raw = raw.get("recent_logs") if isinstance(raw.get("recent_logs"), list) else []
        examples_raw = raw.get("examples") if isinstance(raw.get("examples"), list) else []
        logs: list[dict[str, Any]] = []
        for item in logs_raw[-30:][::-1]:
            if not isinstance(item, dict):
                continue
            logs.append(
                {
                    "ts": self._float(item.get("ts")),
                    "time": self.plugin._format_timestamp_elapsed(self._float(item.get("ts"))) if self._float(item.get("ts")) else "",
                    "scope": self._single_line(item.get("scope"), 80),
                    "sender_id": self._single_line(item.get("sender_id"), 40),
                    "chat": self._single_line(item.get("chat"), 20),
                    "text": self._single_line(item.get("text"), 180),
                    "decision": self._single_line(item.get("decision"), 40),
                    "confidence": self._float(item.get("confidence")),
                    "reason": self._single_line(item.get("reason"), 120),
                    "wait_seconds": self._float(item.get("wait_seconds")),
                    "outcome": self._single_line(item.get("outcome"), 40),
                    "note": self._single_line(item.get("note"), 160),
                    "source": self._single_line(item.get("source"), 40),
                    "raw": self._single_line(item.get("raw"), 180),
                    "message_count": self._int(item.get("message_count")),
                }
            )
        examples: list[dict[str, Any]] = []
        for item in examples_raw[-10:][::-1]:
            if not isinstance(item, dict):
                continue
            messages = item.get("messages") if isinstance(item.get("messages"), list) else []
            examples.append(
                {
                    "time": self.plugin._format_timestamp_elapsed(self._float(item.get("ts"))) if self._float(item.get("ts")) else "",
                    "kind": self._single_line(item.get("kind"), 40),
                    "scope": self._single_line(item.get("scope"), 80),
                    "sender_id": self._single_line(item.get("sender_id"), 40),
                    "messages": [self._single_line(message, 120) for message in messages[:4]],
                    "previous_decision": self._single_line(item.get("previous_decision"), 40),
                    "note": self._single_line(item.get("note"), 120),
                }
            )
        return {
            "enabled": bool(getattr(self.plugin, "enable_message_debounce", False)),
            "smart_enabled": bool(getattr(self.plugin, "enable_smart_message_debounce", False)),
            "text_wait": self._float(getattr(self.plugin, "text_message_debounce_seconds", 0.0)),
            "max_wait": self._float(getattr(self.plugin, "text_message_debounce_max_wait_seconds", 0.0)),
            "max_merge": self._int(getattr(self.plugin, "message_debounce_max_merge_messages", 0)),
            "smart_wait": self._float(getattr(self.plugin, "smart_message_debounce_wait_seconds", 0.0)),
            "learning_window": self._float(getattr(self.plugin, "smart_message_debounce_learning_window_seconds", 0.0)),
            "provider_id": self._single_line(getattr(self.plugin, "smart_message_debounce_provider_id", ""), 160),
            "recent_logs": logs,
            "examples": examples,
        }

    @staticmethod
    def _presets() -> dict[str, dict[str, Any]]:
        return {
            "safe": {
                "label": "保守低打扰",
                "settings": {
                    "max_daily_messages": 3,
                    "idle_minutes": 180,
                    "min_interval_minutes": 360,
                    "group_interject_max_daily": 0,
                    "group_interject_min_interval_minutes": 360,
                    "memory_refresh_interval_minutes": 720,
                    "episode_memory_refresh_messages": 12,
                    "episode_memory_refresh_minutes": 180,
                },
                "features": {
                    "enable_group_companion": True,
                    "enable_group_interjection": False,
                    "enable_companion_memory": True,
                    "enable_expression_learning": True,
                    "enable_passive_response_review": True,
                    "enable_proactive_message_review": True,
                    "enable_livingmemory_integration": True,
                },
            },
            "standard": {
                "label": "标准陪伴",
                "settings": {
                    "max_daily_messages": 6,
                    "idle_minutes": 60,
                    "min_interval_minutes": 120,
                    "group_interject_max_daily": 1,
                    "group_interject_min_interval_minutes": 240,
                    "memory_refresh_interval_minutes": 360,
                    "episode_memory_refresh_messages": 8,
                    "episode_memory_refresh_minutes": 90,
                },
                "features": {
                    "enable_group_companion": True,
                    "enable_group_interjection": False,
                    "enable_group_context_injection": True,
                    "enable_group_injection_guard": True,
                    "enable_companion_memory": True,
                    "enable_expression_learning": True,
                    "enable_dialogue_episode_memory": True,
                    "enable_open_loop_tracking": True,
                    "enable_passive_response_review": True,
                    "enable_proactive_message_review": True,
                },
            },
            "active": {
                "label": "高互动学习",
                "settings": {
                    "max_daily_messages": 10,
                    "idle_minutes": 30,
                    "min_interval_minutes": 60,
                    "group_interject_max_daily": 2,
                    "group_interject_min_interval_minutes": 180,
                    "memory_refresh_interval_minutes": 240,
                    "episode_memory_refresh_messages": 5,
                    "episode_memory_refresh_minutes": 60,
                },
                "features": {
                    "enable_group_companion": True,
                    "enable_group_injection_guard": True,
                    "enable_companion_memory": True,
                    "enable_expression_learning": True,
                    "enable_intent_emotion_analysis": True,
                    "enable_passive_response_review": True,
                    "enable_proactive_message_review": True,
                    "enable_dialogue_episode_memory": True,
                    "enable_open_loop_tracking": True,
                    "enable_group_interjection": True,
                    "enable_group_interjection_feedback": True,
                },
            },
            "group_observer": {
                "label": "群聊观察优先",
                "settings": {
                    "max_daily_messages": 4,
                    "idle_minutes": 90,
                    "min_interval_minutes": 180,
                    "group_interject_max_daily": 0,
                    "group_interject_min_interval_minutes": 240,
                    "max_group_recent_messages": 120,
                    "max_group_slang_terms": 80,
                },
                "features": {
                    "enable_group_companion": True,
                    "enable_group_context_injection": True,
                    "enable_group_injection_guard": True,
                    "enable_group_slang_learning": True,
                    "enable_group_member_profiles": True,
                    "enable_group_topic_threads": True,
                    "enable_group_episode_memory": True,
                    "enable_group_slang_meanings": True,
                    "enable_group_relationship_graph": True,
                    "enable_group_privacy_guard": True,
                    "enable_group_interjection": False,
                },
            },
        }

    def _apply_config_value(self, key: str, value: Any, overrides: dict[str, Any] | None = None) -> None:
        self._set_config_value(key, value)
        if key == "external_image_api_endpoints":
            normalizer = getattr(self.plugin, "_normalize_external_image_api_endpoints", None)
            endpoints = normalizer(value) if callable(normalizer) else (value if isinstance(value, list) else [])
            self.plugin.external_image_api_endpoints = endpoints
            self._sync_legacy_external_image_api_config_from_endpoints(endpoints)
            return
        if key == "external_image_download_use_environment_proxy":
            self.plugin.external_image_download_use_environment_proxy = self._normalize_bool_value(value)
            return
        if key == "provider_config_mode":
            normalizer = getattr(self.plugin, "_normalize_provider_config_mode", None)
            self.plugin.provider_config_mode = (
                normalizer(value, getattr(self.plugin, "config", None))
                if callable(normalizer)
                else str(value or "quick").strip().lower()
            )
            return
        if key == "model_timeout_overrides":
            normalizer = getattr(self.plugin, "_normalize_model_timeout_overrides", None)
            self.plugin.model_timeout_overrides = normalizer(value) if callable(normalizer) else {}
            return
        if key == "model_fallback_overrides":
            normalizer = getattr(self.plugin, "_normalize_model_fallback_overrides", None)
            self.plugin.model_fallback_overrides = normalizer(value) if callable(normalizer) else {}
            return
        if key == "environment_perception_timezone":
            timezone_name = _normalize_timezone_name(value)
            self.plugin.environment_perception_timezone = timezone_name
            _set_today_key_timezone(timezone_name)
            return
        if key == "enable_deepseek_peak_replacement":
            self.plugin.enable_deepseek_peak_replacement = self._normalize_bool_value(value)
            return
        if key in {"deepseek_peak_windows", "deepseek_peak_timezone", "deepseek_peak_match_keywords"}:
            setattr(self.plugin, key, str(value or "").strip())
            return
        if key == "proactive_intensity_preset":
            normalizer = getattr(self.plugin, "_normalize_proactive_intensity_preset", None)
            self.plugin.proactive_intensity_preset = (
                normalizer(value)
                if callable(normalizer)
                else str(value or "off").strip().lower()
            )
            return
        if key == "max_daily_messages":
            self.plugin.max_daily_messages = max(0, self._int(value))
            kicker = getattr(self.plugin, "_kick_proactive_loop_once", None)
            if callable(kicker):
                try:
                    asyncio.create_task(kicker())
                except RuntimeError:
                    pass
            return
        if key == "page_font_family":
            text = str(value or "original").strip().lower()
            self.plugin.page_font_family = text if text in PAGE_FONT_NAMES else "original"
            return
        if key == "page_theme":
            text = str(value or "classic").strip().lower()
            self.plugin.page_theme = text if text in PAGE_THEME_NAMES else "classic"
            return
        if key == "storage_backend":
            backend = str(value or "json").strip().lower() or "json"
            self.plugin.storage_backend = backend if backend in {"json", "sqlite"} else "json"
            rebuild = getattr(self.plugin, "_rebuild_store_manager", None)
            if callable(rebuild) and not bool((overrides or {}).get("__defer_storage_rebuild")):
                rebuild(reload_data=True)
            return
        if key == "storage_sqlite_path":
            self.plugin.storage_sqlite_path = str(value or "").strip()
            rebuild = getattr(self.plugin, "_rebuild_store_manager", None)
            if callable(rebuild) and not bool((overrides or {}).get("__defer_storage_rebuild")):
                rebuild(reload_data=True)
            return
        attr_map = {
            "FAST_RESPONSE_PROVIDER_ID": "fast_response_provider_id",
            "COMPLEX_REASONING_PROVIDER_ID": "complex_reasoning_provider_id",
            "CREATIVE_MODEL_PROVIDER_ID": "creative_model_provider_id",
            "LLM_PROVIDER_ID": "llm_provider_id",
            "MAI_STYLE_PROVIDER_ID": "mai_style_provider_id",
            "DAILY_PLAN_PROVIDER_ID": "daily_plan_provider_id",
            "DETAIL_ENHANCEMENT_PROVIDER_ID": "detail_enhancement_provider_id",
            "DREAM_DIARY_PROVIDER_ID": "dream_diary_provider_id",
            "CREATIVE_PROVIDER_ID": "creative_provider_id",
            "CREATIVE_OUTLINE_PROVIDER_ID": "creative_outline_provider_id",
            "CREATIVE_REVIEW_PROVIDER_ID": "creative_review_provider_id",
            "VOICE_PROMPT_PROVIDER_ID": "voice_prompt_provider_id",
            "PHOTO_PROMPT_PROVIDER_ID": "photo_prompt_provider_id",
            "NARRATION_PROVIDER_ID": "narration_provider_id",
            "HISTORY_SUMMARY_PROVIDER_ID": "history_summary_provider_id",
            "RESPONSE_REVIEW_PROVIDER_ID": "response_review_provider_id",
            "SMART_SILENCE_PROVIDER_ID": "smart_silence_provider_id",
            "PROACTIVE_PERSONA_JUDGE_PROVIDER_ID": "proactive_persona_judge_provider_id",
            "TROUBLESHOOTING_PROVIDER_ID": "troubleshooting_provider_id",
            "RELATIONSHIP_ANALYSIS_PROVIDER_ID": "relationship_analysis_provider_id",
            "EMOTION_JUDGEMENT_PROVIDER_ID": "emotion_judgement_provider_id",
            "COMPANION_MEMORY_PROVIDER_ID": "companion_memory_provider_id",
            "DIALOGUE_EPISODE_PROVIDER_ID": "dialogue_episode_provider_id",
            "GROUP_INTERJECT_PROVIDER_ID": "group_interject_provider_id",
            "GROUP_EPISODE_PROVIDER_ID": "group_episode_provider_id",
            "GROUP_SLANG_PROVIDER_ID": "group_slang_provider_id",
            "GROUP_FOLLOWUP_JUDGE_PROVIDER_ID": "group_followup_judge_provider_id",
            "FORWARD_MESSAGE_PROVIDER_ID": "forward_message_provider_id",
            "PLUGIN_VISION_PROVIDER_ID": "plugin_vision_provider_id",
            "PRIVATE_READING_VISION_PROVIDER_ID": "jm_cosmos_vision_provider_id",
            "NEWS_PROVIDER_ID": "news_provider_id",
            "WEB_EXPLORATION_PROVIDER_ID": "web_exploration_provider_id",
            "DEEPSEEK_PEAK_REPLACEMENT_PROVIDER_ID": "deepseek_peak_replacement_provider_id",
            "WEB_EXPLORATION_API_BASE_URL": "web_exploration_api_base_url",
            "WEB_EXPLORATION_API_KEY": "web_exploration_api_key",
            "WEB_EXPLORATION_API_MODEL": "web_exploration_api_model",
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID": "smart_message_debounce_provider_id",
            "REST_WAKEUP_PROVIDER_ID": "rest_wakeup_provider_id",
            "COMFYUI_TEXT2IMG_WORKFLOW_NAME": "comfyui_text2img_workflow_name",
            "COMFYUI_SELFIE_WORKFLOW_NAME": "comfyui_selfie_workflow_name",
            "external_image_api_platform": "external_image_api_platform",
            "EXTERNAL_IMAGE_API_BASE_URL": "external_image_api_base_url",
            "EXTERNAL_IMAGE_API_KEY": "external_image_api_key",
            "EXTERNAL_IMAGE_API_MODEL": "external_image_api_model",
            "external_image_api_custom_headers": "external_image_api_custom_headers",
            "external_image_download_proxy": "external_image_download_proxy",
            "backup_external_image_api_platform": "backup_external_image_api_platform",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL": "backup_external_image_api_base_url",
            "BACKUP_EXTERNAL_IMAGE_API_KEY": "backup_external_image_api_key",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL": "backup_external_image_api_model",
            "backup_external_image_api_custom_headers": "backup_external_image_api_custom_headers",
        }
        if key in attr_map:
            setattr(self.plugin, attr_map[key], str(value or "").strip())
            if key == "DREAM_DIARY_PROVIDER_ID":
                shared = str(value or "").strip()
                self.plugin.dream_provider_id = shared
                self.plugin.diary_provider_id = shared
            return
        if key == "group_access_mode":
            self.plugin.group_access_mode = str(value or "whitelist").lower()
            return
        if key == "group_whitelist_ids":
            self.plugin.group_whitelist_ids = list(value or [])
            return
        if key == "group_blacklist_ids":
            self.plugin.group_blacklist_ids = list(value or [])
            return
        if key == "target_user_ids":
            self.plugin.target_user_ids = self._normalize_private_target_id_list(value)
            return
        if key == "QZONE_COOKIE":
            self.plugin.qzone_cookie = str(value or "").strip()
            return
        if key == "roleplay_knowledge_source_ids":
            normalizer = getattr(self.plugin, "_normalize_roleplay_knowledge_source_ids", None)
            self.plugin.roleplay_knowledge_source_ids = normalizer(value) if callable(normalizer) else list(value or [])
            return
        private_reading_attr_map = {
            "enable_private_reading_integration": "enable_jm_cosmos_integration",
            "enable_private_reading_boredom_read": "enable_jm_cosmos_boredom_read",
            "enable_private_reading_ask_recommendation": "enable_private_reading_ask_recommendation",
            "enable_private_reading_preference_influence": "enable_private_reading_preference_influence",
            "private_reading_min_interval_hours": "jm_cosmos_min_interval_hours",
            "private_reading_max_photo_count": "jm_cosmos_max_photo_count",
            "private_reading_share_probability": "jm_cosmos_share_probability",
            "private_reading_ask_probability": "private_reading_ask_probability",
            "private_reading_preference_min_ratings": "private_reading_preference_min_ratings",
            "private_reading_preference_max_terms": "private_reading_preference_max_terms",
            "private_reading_default_keywords": "jm_cosmos_default_keywords",
            "private_reading_blocked_tags": "private_reading_blocked_tags",
        }
        if key in private_reading_attr_map:
            setattr(self.plugin, private_reading_attr_map[key], value)
            return
        if key == "plugin_specific_persona_id":
            self.plugin.plugin_specific_persona_id = str(value or "").strip()
            self.plugin._default_persona_prompt_cache = ""
            self.plugin._default_persona_prompt_cache_persona_id = ""
            self.plugin._default_persona_prompt_cache_by_scope = {}
            return
        if key == "private_user_aliases":
            self.plugin.private_user_aliases = self.plugin._parse_private_user_aliases(value)
            if self.plugin._merge_private_user_alias_records():
                self.plugin._save_data_sync()
            return
        if key == "private_user_delivery_aliases":
            self.plugin.private_user_delivery_aliases = self.plugin._parse_private_user_aliases(value)
            users = self.plugin.data.get("users", {})
            if isinstance(users, dict):
                for raw_user_id, user in users.items():
                    if isinstance(user, dict):
                        self.plugin._ensure_private_user_umo(str(raw_user_id), user)
                self.plugin._save_data_sync()
            return
        if key == "worldbook_self_registration_block_words":
            parser = getattr(self.plugin, "_parse_text_list_config", None)
            if callable(parser):
                self.plugin.worldbook_self_registration_block_words = parser(value, limit=120)
            else:
                self.plugin.worldbook_self_registration_block_words = value
            return
        if key == "worldbook_self_registration_block_reply":
            reply = str(value or "").strip()
            self.plugin.worldbook_self_registration_block_reply = "这个称呼我不记。" if reply in {"这个称呼我先不记。", "你是小猪"} else reply
            return
        if key in {"group_repeat_follow_probability", "group_repeat_interrupt_probability", "group_repeat_interrupt_probability_step"}:
            raw = float(value or 0)
            setattr(self.plugin, key, max(0.0, min(1.0, raw / 100.0 if raw > 1 else raw)))
            return
        if key == "rest_reply_probability":
            raw = float(value or 0)
            setattr(self.plugin, key, max(0.0, min(1.0, raw / 100.0 if raw > 1 else raw)))
            return
        if key in {"proactive_photo_text_probability", "proactive_share_probability"}:
            raw = float(value or 0)
            setattr(self.plugin, key, max(0.0, min(1.0, raw / 100.0 if raw > 1 else raw)))
            return
        tts_runtime_keys = {
            "tts_generation_mode",
            "tts_voice_language",
            "tts_delivery_mode",
            "tts_foreign_text_mode",
            "tts_conversion_scope",
            "tts_conversion_provider_id",
            "tts_extra_prompt",
            "tts_frequency_control_mode",
            "tts_constraint_mode",
            "tts_session_min_interval_seconds",
            "tts_private_min_interval_seconds",
            "tts_group_min_interval_seconds",
            "tts_trigger_probability",
            "tts_private_trigger_probability",
            "tts_group_trigger_probability",
            "enable_tts_local_playback",
            "enable_tts_local_playback_live_only",
            "enable_tts_live_subtitle_sync",
            "tts_live_subtitle_url",
            "tts_local_playback_volume",
            "tts_local_playback_min_interval_seconds",
            "auto_voice_enabled",
            "auto_voice_full_conversion_enabled",
            "auto_voice_probability",
            "auto_voice_max_chars",
            "auto_voice_cooldown_seconds",
            "main_user_voice_probability",
            "main_user_mention_voice_keywords",
            "main_user_mention_voice_probability",
            "main_user_mention_voice_prompt",
        }
        if key == "enable_tts_enhancement" or key in tts_runtime_keys:
            loader = getattr(self.plugin, "_load_tts_enhancement_config", None)
            if callable(loader):
                loader(self._config_overlay(overrides or {key: value}))
            else:
                setattr(self.plugin, key, value)
            if key == "tts_generation_mode":
                # Keep the live value authoritative even when AstrBot's config wrapper
                # still exposes a stale grouped/default value during the same request.
                normalized_mode = self._normalize_setting_value("tts_generation_mode", value)
                self.plugin.tts_generation_mode = normalized_mode
            return
        if key == "enable_passive_response_review":
            normalized = self._normalize_bool_value(value)
            self.plugin.enable_passive_response_review = normalized
            self.plugin.enable_response_self_review = normalized
            return
        if key == "passive_review_mode":
            normalized = self._normalize_setting_value(key, value)
            self.plugin.passive_review_mode = normalized
            self.plugin.response_review_mode = normalized
            return
        if key in self._allowed_feature_keys():
            setattr(self.plugin, key, self._normalize_bool_value(value))
            return
        if key in self._allowed_setting_keys():
            setattr(self.plugin, key, value)

    def _sync_legacy_external_image_api_config_from_endpoints(self, endpoints: list[dict[str, Any]]) -> None:
        normalized = endpoints if isinstance(endpoints, list) else []
        first = normalized[0] if len(normalized) >= 1 and isinstance(normalized[0], dict) else {}
        second = normalized[1] if len(normalized) >= 2 and isinstance(normalized[1], dict) else {}

        def endpoint_complete(endpoint: dict[str, Any]) -> bool:
            return bool(
                endpoint
                and endpoint.get("enabled", True)
                and str(endpoint.get("base_url") or "").strip()
                and str(endpoint.get("api_key") or "").strip()
                and str(endpoint.get("model") or "").strip()
            )

        updates = {
            "external_image_api_platform": first.get("platform", "auto") if first else "auto",
            "EXTERNAL_IMAGE_API_BASE_URL": first.get("base_url", "") if first else "",
            "EXTERNAL_IMAGE_API_KEY": first.get("api_key", "") if first else "",
            "EXTERNAL_IMAGE_API_MODEL": first.get("model", "") if first else "",
            "external_image_api_size": first.get("size", "1024x1024") if first else "1024x1024",
            "external_image_api_timeout_seconds": self._int(first.get("timeout_seconds"), 180, 20, 600) if first else 180,
            "external_image_api_custom_headers": first.get("custom_headers", "") if first else "",
            "enable_backup_external_image_api": endpoint_complete(second),
            "backup_external_image_api_platform": second.get("platform", "auto") if second else "auto",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL": second.get("base_url", "") if second else "",
            "BACKUP_EXTERNAL_IMAGE_API_KEY": second.get("api_key", "") if second else "",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL": second.get("model", "") if second else "",
            "backup_external_image_api_size": second.get("size", "1024x1024") if second else "1024x1024",
            "backup_external_image_api_timeout_seconds": self._int(second.get("timeout_seconds"), 180, 20, 600) if second else 180,
            "backup_external_image_api_custom_headers": second.get("custom_headers", "") if second else "",
        }
        attr_map = {
            "external_image_api_platform": "external_image_api_platform",
            "EXTERNAL_IMAGE_API_BASE_URL": "external_image_api_base_url",
            "EXTERNAL_IMAGE_API_KEY": "external_image_api_key",
            "EXTERNAL_IMAGE_API_MODEL": "external_image_api_model",
            "external_image_api_size": "external_image_api_size",
            "external_image_api_timeout_seconds": "external_image_api_timeout_seconds",
            "external_image_api_custom_headers": "external_image_api_custom_headers",
            "enable_backup_external_image_api": "enable_backup_external_image_api",
            "backup_external_image_api_platform": "backup_external_image_api_platform",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL": "backup_external_image_api_base_url",
            "BACKUP_EXTERNAL_IMAGE_API_KEY": "backup_external_image_api_key",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL": "backup_external_image_api_model",
            "backup_external_image_api_size": "backup_external_image_api_size",
            "backup_external_image_api_timeout_seconds": "backup_external_image_api_timeout_seconds",
            "backup_external_image_api_custom_headers": "backup_external_image_api_custom_headers",
        }
        for key, value in updates.items():
            self._set_config_value(key, value)
            setattr(self.plugin, attr_map[key], value)

    def _sync_photo_generation_runtime_config(self) -> None:
        reference_enabled = self._config_get("enable_photo_reference_image")
        if reference_enabled not in ("", None):
            self.plugin.enable_photo_reference_image = self._normalize_bool_value(reference_enabled)
        enabled_backup = self._config_get("enable_backup_external_image_api")
        if enabled_backup not in ("", None):
            self.plugin.enable_backup_external_image_api = self._normalize_bool_value(enabled_backup)
        use_environment_proxy = self._config_get("external_image_download_use_environment_proxy")
        if use_environment_proxy not in ("", None):
            self.plugin.external_image_download_use_environment_proxy = self._normalize_bool_value(use_environment_proxy)
        mapping = {
            "photo_generation_backend": "photo_generation_backend",
            "custom_photo_tool_name": "custom_photo_tool_name",
            "custom_photo_tool_prompt_param": "custom_photo_tool_prompt_param",
            "custom_photo_tool_kind_param": "custom_photo_tool_kind_param",
            "custom_photo_tool_reference_param": "custom_photo_tool_reference_param",
            "custom_photo_tool_extra_params": "custom_photo_tool_extra_params",
            "COMFYUI_TEXT2IMG_WORKFLOW_NAME": "comfyui_text2img_workflow_name",
            "COMFYUI_SELFIE_WORKFLOW_NAME": "comfyui_selfie_workflow_name",
            "photo_persona_reference_image_path": "photo_persona_reference_image_path",
            "daily_outfit_photo_prompt": "daily_outfit_photo_prompt",
            "daily_outfit_rotation_days": "daily_outfit_rotation_days",
            "external_image_api_platform": "external_image_api_platform",
            "EXTERNAL_IMAGE_API_BASE_URL": "external_image_api_base_url",
            "EXTERNAL_IMAGE_API_KEY": "external_image_api_key",
            "EXTERNAL_IMAGE_API_MODEL": "external_image_api_model",
            "external_image_api_size": "external_image_api_size",
            "external_image_api_custom_headers": "external_image_api_custom_headers",
            "external_image_download_proxy": "external_image_download_proxy",
            "backup_external_image_api_platform": "backup_external_image_api_platform",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL": "backup_external_image_api_base_url",
            "BACKUP_EXTERNAL_IMAGE_API_KEY": "backup_external_image_api_key",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL": "backup_external_image_api_model",
            "backup_external_image_api_size": "backup_external_image_api_size",
            "backup_external_image_api_custom_headers": "backup_external_image_api_custom_headers",
            "external_image_api_endpoints": "external_image_api_endpoints",
            "photo_generation_style": "photo_generation_style",
            "photo_generation_style_custom_prompt": "photo_generation_style_custom_prompt",
            "photo_generation_fixed_prompt": "photo_generation_fixed_prompt",
            "photo_generation_scene_presets": "photo_generation_scene_presets",
        }
        for key, attr in mapping.items():
            value = self._config_get_raw(key) if key == "external_image_api_endpoints" else self._config_get(key)
            if key == "external_image_api_endpoints":
                normalizer = getattr(self.plugin, "_normalize_external_image_api_endpoints", None)
                endpoints = normalizer(value) if callable(normalizer) else (value if isinstance(value, list) else [])
                self.plugin.external_image_api_endpoints = endpoints
                continue
            if key == "photo_persona_reference_image_path":
                setattr(self.plugin, attr, str(value or "").strip())
                continue
            if value not in ("", None):
                text = str(value).strip()
                if key == "photo_generation_backend":
                    text = text.lower()
                    if text not in {"auto", "comfyui", "sdgen", "external", "tool_call"}:
                        text = "auto"
                elif key in {"external_image_api_platform", "backup_external_image_api_platform"}:
                    normalizer = getattr(self.plugin, "_normalize_external_image_api_platform", None)
                    text = normalizer(text) if callable(normalizer) else text.lower()
                    if text not in {"auto", "openai", "bailian", "modelscope", "doubao", "gemini"}:
                        text = "auto"
                setattr(self.plugin, attr, text)
        timeout = self._config_get("external_image_api_timeout_seconds")
        if timeout not in ("", None):
            try:
                self.plugin.external_image_api_timeout_seconds = max(20, min(600, int(float(timeout))))
            except Exception:
                pass
        backup_timeout = self._config_get("backup_external_image_api_timeout_seconds")
        if backup_timeout not in ("", None):
            try:
                self.plugin.backup_external_image_api_timeout_seconds = max(20, min(600, int(float(backup_timeout))))
            except Exception:
                pass
        wait_seconds = self._config_get("comfyui_photo_wait_seconds")
        if wait_seconds not in ("", None):
            try:
                self.plugin.comfyui_photo_wait_seconds = max(5, min(600, int(float(wait_seconds))))
            except Exception:
                pass

    @staticmethod
    def _normalize_bool_value(value: Any) -> bool:
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"true", "1", "yes", "y", "on", "enable", "enabled", "启用", "开启", "开", "是"}:
                return True
            if text in {"false", "0", "no", "n", "off", "disable", "disabled", "停用", "关闭", "关", "否", ""}:
                return False
        return bool(value)

    def _set_config_value(self, key: str, value: Any) -> None:
        config = getattr(self.plugin, "config", None)
        if config is None:
            return
        if key == "provider_config_mode":
            self._set_provider_config_mode_value(config, value)
            return
        if key == "proactive_intensity_preset":
            self._set_schema_compat_value(config, key, value)
            return
        if key in {"page_font_family", "page_theme"}:
            self._set_schema_compat_value(config, key, value)
            return
        updated_existing = _set_into_config(config, key, value, allow_flat_fallback=False)
        updated_group = self._set_schema_group_config_value(config, key, value, create_group=True)
        if updated_existing or updated_group:
            return
        _set_into_config(config, key, value)
        return

    def _set_provider_config_mode_value(self, config: Any, value: Any) -> None:
        # Keep the visible schema group and the hidden legacy flat key in sync.
        # AstrBot validates unknown flat keys during plugin load, while older
        # page/API paths still read or write the flat name directly.
        self._set_schema_group_config_value(config, "provider_config_mode", value, create_group=True)
        _set_into_config(config, "provider_config_mode", value)

    def _set_schema_compat_value(self, config: Any, key: str, value: Any) -> None:
        self._set_schema_group_config_value(config, key, value, create_group=True)
        _set_into_config(config, key, value)

    def _set_schema_group_config_value(self, config: Any, key: str, value: Any, *, create_group: bool = False) -> bool:
        group_key = self._schema_group_for_key(key)
        if not group_key:
            return False

        def set_in_group(target: dict[str, Any]) -> bool:
            group = target.get(group_key)
            if isinstance(group, dict):
                group[key] = value
                return True
            if create_group:
                target[group_key] = {key: value}
                return True
            return False

        if isinstance(config, dict) and set_in_group(config):
            return True
        for attr in ("data", "config"):
            target = getattr(config, attr, None)
            if isinstance(target, dict) and set_in_group(target):
                return True
        return False

    def _config_overlay(self, overrides: dict[str, Any]) -> Any:
        base = getattr(self.plugin, "config", {}) or {}

        class _Overlay:
            def get(self, item: str, default: Any = None) -> Any:
                if item in overrides:
                    return overrides[item]
                return _flat_get(base, item, getattr(base, item, default))

        return _Overlay()

    def _config_get_raw(self, key: str, default: Any = None) -> Any:
        config = getattr(self.plugin, "config", None)
        value = _flat_get(config, key, None)
        if value not in (None, ""):
            return value
        data = getattr(config, "data", None)
        if isinstance(data, dict):
            value = _flat_get(data, key, None)
            if value not in (None, ""):
                return value
        raw = getattr(config, "config", None)
        if isinstance(raw, dict):
            value = _flat_get(raw, key, None)
            if value not in (None, ""):
                return value
        try:
            return getattr(config, key, default)
        except Exception:
            return default

    def _config_get(self, key: str) -> str:
        value = self._config_get_raw(key, "")
        if isinstance(value, (list, dict)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value or "")

    def _private_alias_config_text(self, key: str) -> str:
        raw = self._config_get(key)
        if raw:
            return raw
        mapping = getattr(self.plugin, key, None)
        if not isinstance(mapping, dict):
            return ""
        lines: list[str] = []
        for alias, target in mapping.items():
            left = str(alias or "").strip()
            right = str(target or "").strip()
            if left and right:
                lines.append(f"{left}={right}")
        return "\n".join(lines)

    async def _save_config_if_possible(self) -> bool:
        config = getattr(self.plugin, "config", None)
        for method_name in ("save_config", "save", "save_conf"):
            save = getattr(config, method_name, None)
            if callable(save):
                try:
                    _ensure_config_parent_dir(config, logger=logger)
                    result = save()
                    if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                        await result
                    return True
                except TypeError:
                    continue
                except FileNotFoundError as exc:
                    if _ensure_config_parent_dir(config, error=exc, logger=logger):
                        try:
                            result = save()
                            if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
                                await result
                            return True
                        except Exception as retry_exc:
                            logger.warning("[PrivateCompanionPage] 配置保存重试失败(%s): %s", method_name, self._single_line(retry_exc, 160))
                            return False
                    logger.warning("[PrivateCompanionPage] 配置保存失败(%s): %s", method_name, self._single_line(exc, 160))
                    return False
                except Exception as exc:
                    logger.warning("[PrivateCompanionPage] 配置保存失败(%s): %s", method_name, self._single_line(exc, 160))
                    return False
        logger.warning("[PrivateCompanionPage] 当前配置对象没有可用保存方法,本次改动可能只在运行态生效")
        return False

    def _can_save_config(self) -> bool:
        config = getattr(self.plugin, "config", None)
        return any(callable(getattr(config, method_name, None)) for method_name in ("save_config", "save", "save_conf"))

    def _allowed_feature_keys(self) -> set[str]:
        return {
            "enable_proactive_only_mode",
            "enable_mai_style_integration",
            "enable_companion_memory",
            "enable_expression_learning",
            "enable_intent_emotion_analysis",
            "enable_response_self_review",
            "enable_passive_response_review",
            "enable_proactive_message_review",
            "enable_smart_silence",
            "enable_llm_proactive_message",
            "enable_llm_proactive_persona_judge",
            "enable_maslow_motivation_experiment",
            "enable_experimental_motivation_model",
            "enable_personality_iteration_experiment",
            "enable_passive_topic_suppression",
            "enable_relationship_state_machine",
            "enable_emotion_simulation",
            "enable_dialogue_episode_memory",
            "enable_open_loop_tracking",
            "enable_user_habit_learning",
            "enable_food_menu_recommendation",
            "enable_personal_goals",
            "enable_humanized_states",
            "enable_health_state",
            "enable_hunger_state",
            "enable_segmented_proactive_reply",
            "enable_proactive_quote_trigger_message",
            "enable_quote_group_reply",
            "enable_quote_group_interjection",
            "enable_quote_private_proactive",
            "enable_photo_text_action",
            "inject_passive_states",
            "enable_passive_state_delta_injection",
            "enable_cycle_state",
            "enable_skill_growth_simulation",
            "enable_skill_growth_passive_injection",
            "enable_message_debounce",
            "enable_smart_message_debounce",
            "enable_recall_enhancement",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "enable_forbidden_word_recall",
            "enable_semantic_message_debounce",
            "enable_environment_perception",
            "enable_balance_awareness",
            "enable_holiday_perception",
            "enable_platform_perception",
            "enable_model_perception",
            "enable_worldview_perception",
            "enable_lunar_perception",
            "enable_solar_term_perception",
            "enable_almanac_perception",
            "enable_group_companion",
            "enable_group_slang_learning",
            "enable_group_member_profiles",
            "enable_group_context_injection",
            "enable_group_injection_guard",
            "enable_group_persona_denoise",
            "enable_forward_message_adaptation",
            "enable_group_reality_promise_guard",
            "enable_group_wakeup_enhancement",
            "enable_group_wakeup_question",
            "enable_group_wakeup_cold_group",
            "enable_group_high_intensity_mode",
            "enable_group_air_reply_guard",
            "enable_private_image_self_recognition",
            "enable_private_image_gif_enhancement",
            "enable_group_conversation_followup",
            "enable_group_interjection",
            "enable_group_repeat_follow",
            "group_repeat_count_distinct_users_only",
            "enable_group_topic_threads",
            "enable_group_episode_memory",
            "enable_group_interjection_feedback",
            "enable_group_slang_meanings",
            "enable_group_slang_web_search",
            "enable_group_relationship_graph",
            "enable_group_privacy_guard",
            "enable_worldbook_member_recognition",
            "enable_cross_user_memory_bridge",
            "enable_group_scene_awareness",
            "enable_group_reality_promise_guard",
            "enable_atrelay_tools",
            "enable_livingmemory_integration",
            "enable_bilibili_integration",
            "enable_bilibili_boredom_watch",
            "enable_news_integration",
            "enable_news_boredom_read",
            "enable_news_daily_hot_read",
            "enable_ai_daily_watch",
            "enable_external_event_self_link",
            "enable_web_exploration",
            "enable_web_exploration_boredom_search",
            "enable_qzone_integration",
            "enable_qzone_life_publish",
            "enable_qzone_generated_image_publish",
            "enable_qzone_comment_inbox",
            "enable_qzone_emotional_vent_publish",
            "enable_private_reading_integration",
            "enable_private_reading_boredom_read",
            "enable_private_reading_ask_recommendation",
            "enable_private_reading_preference_influence",
            "enable_unanswered_screen_peek_followup",
            "enable_screen_glance_action",
            "enable_poke_action",
            "enable_voice_action",
            "enable_yesterday_screen_diary_context",
            "enable_tts_enhancement",
            "enable_creative_writing",
            "creative_hidden_mode",
            "enable_reply_interception_forward",
        }

    def _allowed_provider_keys(self) -> set[str]:
        keys = {
            "FAST_RESPONSE_PROVIDER_ID",
            "COMPLEX_REASONING_PROVIDER_ID",
            "CREATIVE_MODEL_PROVIDER_ID",
            "LLM_PROVIDER_ID",
            "MAI_STYLE_PROVIDER_ID",
            "DAILY_PLAN_PROVIDER_ID",
            "DETAIL_ENHANCEMENT_PROVIDER_ID",
            "DREAM_DIARY_PROVIDER_ID",
            "CREATIVE_PROVIDER_ID",
            "CREATIVE_OUTLINE_PROVIDER_ID",
            "CREATIVE_REVIEW_PROVIDER_ID",
            "VOICE_PROMPT_PROVIDER_ID",
            "tts_conversion_provider_id",
            "PHOTO_PROMPT_PROVIDER_ID",
            "NARRATION_PROVIDER_ID",
            "HISTORY_SUMMARY_PROVIDER_ID",
            "RESPONSE_REVIEW_PROVIDER_ID",
            "SMART_SILENCE_PROVIDER_ID",
            "PROACTIVE_PERSONA_JUDGE_PROVIDER_ID",
            "TROUBLESHOOTING_PROVIDER_ID",
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID",
            "REST_WAKEUP_PROVIDER_ID",
            "RELATIONSHIP_ANALYSIS_PROVIDER_ID",
            "COMPANION_MEMORY_PROVIDER_ID",
            "DIALOGUE_EPISODE_PROVIDER_ID",
            "GROUP_INTERJECT_PROVIDER_ID",
            "GROUP_EPISODE_PROVIDER_ID",
            "GROUP_SLANG_PROVIDER_ID",
            "GROUP_FOLLOWUP_JUDGE_PROVIDER_ID",
            "FORWARD_MESSAGE_PROVIDER_ID",
            "PLUGIN_VISION_PROVIDER_ID",
            "PRIVATE_READING_VISION_PROVIDER_ID",
            "NEWS_PROVIDER_ID",
            "WEB_EXPLORATION_PROVIDER_ID",
            "EMOTION_JUDGEMENT_PROVIDER_ID",
        }
        keys.update(self._schema_provider_keys(public_only=True))
        return keys

    def _allowed_setting_keys(self) -> set[str]:
        keys = {
            "expression_private_learning_source_mode",
            "expression_private_learning_source_ids",
            "expression_group_learning_source_mode",
            "expression_group_learning_source_ids",
            "expression_group_learning_daily_batch_limit",
            "expression_group_learning_min_new_messages",
            "expression_private_application_mode",
            "expression_private_application_user_ids",
            "expression_group_application_mode",
            "expression_group_application_ids",
            "bot_name",
            "page_font_family",
            "page_theme",
            "provider_config_mode",
            "model_timeout_overrides",
            "model_fallback_overrides",
            "enable_deepseek_peak_replacement",
            "deepseek_peak_windows",
            "deepseek_peak_timezone",
            "deepseek_peak_match_keywords",
            "enable_proactive_only_mode",
            "plugin_specific_persona_id",
            "target_user_ids",
            "private_user_aliases",
            "private_user_delivery_aliases",
            "target_platform",
            "require_private_opt_in",
            "environment_perception_timezone",
            "holiday_country",
            "enable_environment_perception",
            "enable_holiday_perception",
            "enable_platform_perception",
            "enable_model_perception",
            "enable_worldview_perception",
            "enable_lunar_perception",
            "enable_solar_term_perception",
            "enable_almanac_perception",
            "default_nickname",
            "default_style",
            "reply_style_prompt",
            "enable_persona_voice_channels",
            "persona_conversation_voice_prompt",
            "persona_creative_voice_prompt",
            "persona_planning_voice_prompt",
            "persona_inner_voice_prompt",
            "persona_proactive_voice_prompt",
            "response_review_mode",
            "passive_review_mode",
            "passive_review_strength",
            "proactive_review_mode",
            "smart_silence_judge_mode",
            "smart_silence_min_confidence",
            "smart_silence_model_timeout_seconds",
            "proactive_review_strength",
            "proactive_review_hard_risk_threshold",
            "proactive_review_low_score_threshold",
            "proactive_review_pressure_threshold",
            "response_review_max_chars",
            "enable_personal_goal_auto_progress",
            "personal_goal_share_cooldown_hours",
            "personal_goal_stall_days",
            "enable_llm_emotion_judgement",
            "emotion_judgement_mode",
            "schedule_persona_prompt",
            "schedule_worldview_prompt",
            "roleplay_user_profile_prompt",
            "roleplay_knowledge_source_ids",
            "worldview_adaptation_mode",
            "worldview_adaptation_prompt",
            "quiet_hours",
            "proactive_intensity_preset",
            "proactive_prompt_template",
            "proactive_persona_judge_send_threshold",
            "proactive_persona_judge_cache_minutes",
            "proactive_persona_judge_max_daily",
            "enable_experimental_motivation_model",
            "enable_personality_iteration_experiment",
            "enable_personality_iteration_auto_tune",
            "enable_maslow_schedule_influence",
            "maslow_motivation_strength",
            "proactive_photo_text_probability",
            "memory_companion_context_timeout_seconds",
            "enable_memory_companion_emotional_drift",
            "enable_memory_companion_cross_window_emotion",
            "enable_memory_companion_dream_fragment",
            "enable_memory_companion_open_loop_search",
            "enable_memory_companion_feature_context",
            "memory_companion_context_top_k",
            "memory_companion_context_max_chars",
            "passive_topic_memory_hours",
            "tts_generation_mode",
            "tts_voice_language",
            "tts_delivery_mode",
            "tts_foreign_text_mode",
            "tts_conversion_scope",
            "tts_conversion_provider_id",
            "tts_extra_prompt",
            "tts_frequency_control_mode",
            "tts_constraint_mode",
            "tts_session_min_interval_seconds",
            "tts_private_min_interval_seconds",
            "tts_group_min_interval_seconds",
            "tts_trigger_probability",
            "tts_private_trigger_probability",
            "tts_group_trigger_probability",
            "enable_tts_local_playback",
            "enable_tts_local_playback_live_only",
            "enable_tts_live_subtitle_sync",
            "tts_live_subtitle_url",
            "tts_local_playback_volume",
            "tts_local_playback_min_interval_seconds",
            "auto_voice_enabled",
            "auto_voice_full_conversion_enabled",
            "auto_voice_probability",
            "auto_voice_max_chars",
            "auto_voice_cooldown_seconds",
            "main_user_voice_probability",
            "main_user_mention_voice_keywords",
            "main_user_mention_voice_probability",
            "main_user_mention_voice_prompt",
            "daily_token_limit",
            "enable_daily_token_soft_limit",
            "daily_token_soft_limit",
            "humanized_state_intensity",
            "passive_injection_position",
            "enable_rest_reply_simulation",
            "rest_reply_mode",
            "rest_reply_probability",
            "rest_reply_llm_threshold",
            "rest_reply_active_windows",
            "rest_reply_awake_grace_minutes",
            "enable_rest_backlog_reply",
            "rest_backlog_max_messages",
            "REST_WAKEUP_PROVIDER_ID",
            "check_interval_seconds",
            "idle_minutes",
            "min_interval_minutes",
            "proactive_unanswered_slowdown_start",
            "proactive_unanswered_max_interval_multiplier",
            "friend_unanswered_max_cooldown_hours",
            "max_daily_messages",
            "inbound_message_debounce_seconds",
            "enable_message_debounce",
            "enable_smart_message_debounce",
            "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID",
            "smart_message_debounce_model_timeout_seconds",
            "smart_message_debounce_wait_seconds",
            "smart_message_debounce_learning_window_seconds",
            "smart_message_debounce_examples_limit",
            "text_message_debounce_seconds",
            "image_message_debounce_seconds",
            "forward_message_debounce_seconds",
            "text_message_debounce_max_wait_seconds",
            "message_debounce_max_merge_messages",
            "enable_semantic_message_debounce",
            "semantic_message_debounce_seconds",
            "enable_proactive_quote_trigger_message",
            "enable_quote_group_reply",
            "enable_quote_group_interjection",
            "enable_quote_private_proactive",
            "quote_skip_short_reply_chars",
            "quote_target_strategy",
            "photo_action_max_daily",
            "photo_generation_backend",
            "custom_photo_tool_name",
            "custom_photo_tool_prompt_param",
            "custom_photo_tool_kind_param",
            "custom_photo_tool_reference_param",
            "custom_photo_tool_extra_params",
            "COMFYUI_TEXT2IMG_WORKFLOW_NAME",
            "COMFYUI_SELFIE_WORKFLOW_NAME",
            "enable_photo_reference_image",
            "photo_persona_reference_image_path",
            "enable_daily_outfit_photo",
            "enable_creative_cover_generation",
            "daily_outfit_photo_prompt",
            "daily_outfit_rotation_days",
            "enable_natural_language_photo_generation",
            "natural_language_photo_generation_mode",
            "natural_language_photo_generation_max_daily",
            "natural_language_photo_extra_prompt",
            "comfyui_photo_wait_seconds",
            "enable_local_photo_load_guard",
            "local_photo_cpu_busy_percent",
            "local_photo_memory_busy_percent",
            "local_photo_defer_minutes",
            "external_image_api_platform",
            "EXTERNAL_IMAGE_API_BASE_URL",
            "EXTERNAL_IMAGE_API_KEY",
            "EXTERNAL_IMAGE_API_MODEL",
            "external_image_api_size",
            "external_image_api_timeout_seconds",
            "external_image_api_custom_headers",
            "external_image_download_proxy",
            "external_image_download_use_environment_proxy",
            "external_image_api_endpoints",
            "enable_backup_external_image_api",
            "backup_external_image_api_platform",
            "BACKUP_EXTERNAL_IMAGE_API_BASE_URL",
            "BACKUP_EXTERNAL_IMAGE_API_KEY",
            "BACKUP_EXTERNAL_IMAGE_API_MODEL",
            "backup_external_image_api_size",
            "backup_external_image_api_timeout_seconds",
            "backup_external_image_api_custom_headers",
            "photo_generation_style",
            "photo_generation_style_custom_prompt",
            "photo_generation_fixed_prompt",
            "photo_generation_scene_presets",
            "private_image_vision_wait_seconds",
            "enable_context_image_captioning",
            "context_image_caption_max_items",
            "context_image_caption_timeout_seconds",
            "enable_private_image_gif_enhancement",
            "private_image_gif_max_frames",
            "enable_private_image_self_recognition",
            "private_image_self_recognition_hint",
            "enable_private_image_vision_cache",
            "private_image_vision_cache_max_items",
            "enable_segmented_proactive_reply",
            "segmented_proactive_scope",
            "segmented_proactive_chat_scope",
            "segmented_proactive_threshold",
            "segmented_proactive_min_segment_chars",
            "segmented_proactive_max_segments",
            "segmented_proactive_send_as_forward",
            "segmented_proactive_split_mode",
            "segmented_proactive_regex",
            "segmented_proactive_split_words",
            "enable_segmented_proactive_content_cleanup",
            "segmented_proactive_content_cleanup_scope",
            "segmented_proactive_content_cleanup_rule",
            "segmented_proactive_content_cleanup_words",
            "enable_segmented_proactive_content_replacement",
            "segmented_proactive_content_replacements",
            "segmented_proactive_interval_method",
            "segmented_proactive_interval_min",
            "segmented_proactive_interval_max",
            "segmented_proactive_log_base",
            "group_conversation_followup_seconds",
            "group_conversation_followup_max_turns",
            "enable_group_conversation_followup",
            "enable_group_repeat_follow",
            "group_repeat_trigger_threshold",
            "group_repeat_count_distinct_users_only",
            "group_interject_min_interval_minutes",
            "group_interject_max_daily",
            "group_repeat_follow_probability",
            "group_repeat_interrupt_probability",
            "group_repeat_interrupt_probability_step",
            "group_repeat_interrupt_text",
            "group_repeat_interrupt_image_path",
            "group_scene_recent_limit",
            "enable_group_injection_guard",
            "enable_group_persona_denoise",
            "group_wakeup_direct_words",
            "group_wakeup_context_words",
            "group_wakeup_interest_keywords",
            "group_wakeup_interest_probability",
            "group_wakeup_short_text_wait_seconds",
            "group_wakeup_question_threshold",
            "group_wakeup_cold_group_threshold",
            "group_wakeup_cooldown_seconds",
            "group_wakeup_cold_group_idle_minutes",
            "group_wakeup_generated_keyword_limit",
            "group_wakeup_topic_interest_max_boost",
            "group_wakeup_debounce_pending_penalty",
            "group_wakeup_fatigue_limit",
            "group_wakeup_fatigue_decay_minutes",
            "group_wakeup_log_limit",
            "enable_group_high_intensity_mode",
            "group_high_intensity_wakeup_window_seconds",
            "group_high_intensity_wakeup_threshold",
            "group_high_intensity_cooldown_seconds",
            "group_high_intensity_merge_seconds",
            "group_high_intensity_max_merge_messages",
            "group_high_intensity_merge_scope",
            "enable_forward_message_adaptation",
            "forward_message_mode",
            "forward_message_max_messages",
            "forward_message_max_chars",
            "forward_message_parse_nested",
            "forward_message_image_vision",
            "forward_message_image_limit",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "recall_message_cache_ttl_seconds",
            "recall_message_cache_max_items",
            "recall_message_image_cache_max_mb",
            "enable_forbidden_word_recall",
            "recall_forbidden_words",
            "recall_forbidden_scope",
            "recall_forbidden_word_case_sensitive",
            "screen_diary_context_max_chars",
            "max_group_recent_messages",
            "max_group_slang_terms",
            "group_slang_web_search_terms",
            "group_slang_web_search_results",
            "memory_refresh_interval_minutes",
            "episode_memory_refresh_messages",
            "episode_memory_refresh_minutes",
            "max_companion_memory_items",
            "max_learned_expression_items",
            "expression_learning_mode",
            "enable_expression_manual_review",
            "enable_expression_style_review",
            "max_dialogue_episodes",
            "user_habit_min_count",
            "user_habit_max_items",
            "emotional_gate_hurt_threshold",
            "emotional_gate_refuse_threshold",
            "emotional_gate_recovery_per_hour",
            "emotional_gate_max_hurt_minutes",
            "enable_llm_emotion_judgement",
            "emotion_judgement_mode",
            "enable_skill_growth_simulation",
            "skill_growth_rate",
            "skill_growth_custom_skills",
            "enable_skill_growth_passive_injection",
            "enable_skill_growth_schedule_influence",
            "skill_growth_schedule_influence_strength",
            "enable_bilibili_integration",
            "enable_bilibili_boredom_watch",
            "bilibili_boredom_min_interval_hours",
            "bilibili_share_probability",
            "bilibili_share_min_score",
            "enable_news_integration",
            "enable_news_boredom_read",
            "enable_news_daily_hot_read",
            "enable_ai_daily_watch",
            "ai_daily_sources",
            "ai_daily_prefer_text_version",
            "enable_external_event_self_link",
            "news_min_interval_hours",
            "news_share_probability",
            "external_event_self_link_probability",
            "external_event_self_link_cooldown_hours",
            "external_link_share_cooldown_hours",
            "news_max_items_per_source",
            "news_sources",
            "news_hot_sources",
            "news_hot_max_items",
            "enable_web_exploration",
            "enable_web_exploration_boredom_search",
            "web_exploration_min_interval_hours",
            "web_exploration_share_probability",
            "external_event_self_link_probability",
            "external_event_self_link_cooldown_hours",
            "web_exploration_max_results",
            "web_exploration_interests",
            "WEB_EXPLORATION_API_BASE_URL",
            "WEB_EXPLORATION_API_KEY",
            "WEB_EXPLORATION_API_MODEL",
            "enable_qzone_integration",
            "QZONE_COOKIE",
            "enable_qzone_life_publish",
            "qzone_life_publish_min_interval_hours",
            "qzone_life_publish_probability",
            "qzone_publish_style_prompt",
            "enable_qzone_generated_image_publish",
            "qzone_generated_image_probability",
            "qzone_publish_image_style_prompt",
            "enable_qzone_comment_inbox",
            "qzone_comment_inbox_interval_minutes",
            "qzone_comment_inbox_recent_posts",
            "qzone_comment_inbox_max_replies_per_tick",
            "enable_qzone_emotional_vent_publish",
            "qzone_emotional_vent_threshold",
            "qzone_emotional_vent_cooldown_hours",
            "qzone_emotional_vent_probability",
            "enable_private_reading_integration",
            "enable_private_reading_boredom_read",
            "enable_private_reading_ask_recommendation",
            "private_reading_min_interval_hours",
            "private_reading_max_photo_count",
            "private_reading_share_probability",
            "private_reading_ask_probability",
            "private_reading_preference_min_ratings",
            "private_reading_preference_max_terms",
            "private_reading_default_keywords",
            "private_reading_blocked_tags",
            "enable_unanswered_screen_peek_followup",
            "unanswered_screen_peek_after_minutes",
            "unanswered_screen_peek_cooldown_minutes",
            "enable_creative_writing",
            "creative_inspiration_probability",
            "creative_share_probability",
            "creative_chars_per_session",
            "creative_max_active_projects",
            "creative_hidden_mode",
            "creative_direction_prompt",
            "enable_worldbook_member_recognition",
            "worldbook_auto_import",
            "worldbook_member_match_aliases",
            "worldbook_self_registration",
            "worldbook_self_registration_block_words",
            "worldbook_self_registration_block_reply",
            "worldbook_auto_pending_observations",
            "worldbook_member_inject_limit",
            "worldbook_config_paths",
            "cross_user_memory_owner_only",
            "enable_atrelay_tools",
            "atrelay_require_worldbook_first",
            "atrelay_member_cache_minutes",
            "atrelay_sensitive_confirm",
            "enable_atrelay_llm_rewrite",
            "atrelay_default_relay_style",
            "atrelay_multi_target_limit",
        }
        keys.update(self._schema_setting_keys(public_only=True))
        return keys

    def _normalize_setting_value(self, key: str, value: Any) -> Any:
        if key in self._schema_bool_keys():
            return self._normalize_bool_value(value)
        expression_modes = {
            "expression_private_learning_source_mode": ({"owner", "selected", "all"}, "owner"),
            "expression_group_learning_source_mode": ({"disabled", "selected", "all"}, "disabled"),
            "expression_private_application_mode": ({"all", "selected"}, "all"),
            "expression_group_application_mode": ({"disabled", "all", "selected"}, "all"),
        }
        if key in expression_modes:
            allowed, default = expression_modes[key]
            mode = str(value or default).strip().lower()
            return mode if mode in allowed else default
        expression_id_keys = {
            "expression_private_learning_source_ids",
            "expression_group_learning_source_ids",
            "expression_private_application_user_ids",
            "expression_group_application_ids",
        }
        if key in expression_id_keys:
            ids = self._normalize_id_list(value)
            if key in {
                "expression_private_learning_source_ids",
                "expression_private_application_user_ids",
            }:
                canonicalizer = getattr(self.plugin, "_canonical_private_user_id", None)
                if callable(canonicalizer):
                    normalized_ids: list[str] = []
                    for item in ids:
                        try:
                            normalized_ids.append(self._single_line(canonicalizer(item), 80) or item)
                        except Exception:
                            normalized_ids.append(item)
                    ids = normalized_ids
            return list(dict.fromkeys(item for item in ids if item))[:500]
        if key in {"environment_perception_timezone", "deepseek_peak_timezone"}:
            return _normalize_timezone_name(value)
        if key == "target_user_ids":
            return self._normalize_private_target_id_list(value)
        if key == "plugin_specific_persona_id":
            return str(value or "").strip()[:160]
        if key == "page_font_family":
            text = str(value or "original").strip().lower()
            return text if text in PAGE_FONT_NAMES else "original"
        if key == "page_theme":
            text = str(value or "classic").strip().lower()
            return text if text in PAGE_THEME_NAMES else "classic"
        if key == "provider_config_mode":
            normalizer = getattr(self.plugin, "_normalize_provider_config_mode", None)
            if callable(normalizer):
                return normalizer(value, getattr(self.plugin, "config", None))
            text = str(value or "quick").strip().lower()
            aliases = {
                "fast": "quick",
                "simple": "quick",
                "快速": "quick",
                "快速配置": "quick",
                "precise": "precision",
                "advanced": "precision",
                "精准": "precision",
                "精准配置": "precision",
                "分流": "precision",
            }
            text = aliases.get(text, text)
            return text if text in {"quick", "precision"} else "quick"
        if key == "model_timeout_overrides":
            normalizer = getattr(self.plugin, "_normalize_model_timeout_overrides", None)
            normalized = normalizer(value) if callable(normalizer) else {}
            return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if key == "model_fallback_overrides":
            normalizer = getattr(self.plugin, "_normalize_model_fallback_overrides", None)
            normalized = normalizer(value) if callable(normalizer) else {}
            return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if key == "storage_backend":
            text = str(value or "json").strip().lower()
            return text if text in {"json", "sqlite"} else "json"
        if key == "storage_sqlite_path":
            return str(value or "").strip()[:1000]
        if key == "passive_injection_position":
            normalizer = getattr(self.plugin, "_normalize_passive_injection_position", None)
            if callable(normalizer):
                return normalizer(value)
            text = str(value or "prompt").strip().lower()
            return text if text in {"auto", "prompt", "system_prompt"} else "prompt"
        if key == "rest_reply_active_windows":
            return re.sub(r"\s+", "", str(value or ""))[:160]
        if key == "quote_target_strategy":
            text = str(value or "current").strip().lower()
            aliases = {
                "当前": "current",
                "当前消息": "current",
                "触发消息": "current",
                "引用旧消息": "quoted",
                "旧消息": "quoted",
                "被引用消息": "quoted",
                "自动": "auto",
            }
            text = aliases.get(text, text)
            return text if text in {"current", "quoted", "auto"} else "current"
        if key == "group_high_intensity_merge_scope":
            text = str(value or "group").strip().lower()
            aliases = {
                "sender": "same_user",
                "same_sender": "same_user",
                "user": "same_user",
                "同一用户": "same_user",
                "同一发送者": "same_user",
                "全群": "group",
            }
            text = aliases.get(text, text)
            return text if text in {"group", "same_user"} else "group"
        if key in {"private_user_aliases", "private_user_delivery_aliases"}:
            return str(value or "").strip()[:4000]
        if key == "worldbook_config_paths":
            return str(value or "").strip()[:1000]
        if key in {"news_sources", "ai_daily_sources"}:
            return self._normalize_multiline_source_config(value, limit=4000)
        if key in {"news_hot_sources", "web_exploration_interests", "private_reading_default_keywords", "private_reading_blocked_tags"}:
            return str(value or "").strip()[:1200]
        if key == "WEB_EXPLORATION_API_BASE_URL":
            raw = str(value or "").strip()[:800]
            if not raw or raw.startswith(("http://", "https://")):
                return raw
            if re.match(r"^[a-z][a-z0-9+.-]*://", raw, flags=re.I):
                return raw
            local_pattern = r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[0-1])\.|192\.168\.|\[?::1\]?)"
            scheme = "http://" if re.match(local_pattern, raw, flags=re.I) else "https://"
            return f"{scheme}{raw}"
        if key == "WEB_EXPLORATION_API_KEY":
            return str(value or "").strip()[:800]
        if key == "WEB_EXPLORATION_API_MODEL":
            return str(value or "").strip()[:160]
        if key == "worldbook_self_registration_block_words":
            return str(value or "").strip()[:1200]
        if key == "worldbook_self_registration_block_reply":
            reply = str(value or "").strip()[:200]
            return "这个称呼我不记。" if reply in {"这个称呼我先不记。", "你是小猪"} else reply
        if key == "QZONE_COOKIE":
            return str(value or "").replace("\r", ";").replace("\n", ";").strip()[:8000]
        if key in {"group_wakeup_direct_words", "group_wakeup_context_words", "group_wakeup_interest_keywords", "recall_forbidden_words"}:
            parser = getattr(self.plugin, "_parse_text_list_config", None)
            if callable(parser):
                limit = 300 if key == "recall_forbidden_words" else 120
                try:
                    return parser(value, limit=limit)
                except TypeError:
                    return parser(value)
            if isinstance(value, list):
                limit = 300 if key == "recall_forbidden_words" else 120
                return [str(item).strip() for item in value if str(item or "").strip()][:limit]
            text = str(value or "").strip()[:1200]
            if not text:
                return []
            return [part.strip() for part in re.split(r"[\n,，、;；]+", text) if part.strip()]
        if key == "recall_forbidden_scope":
            scope = str(value or "bot_and_group").strip().lower()
            return scope if scope in {"bot_only", "group_only", "bot_and_group"} else "bot_and_group"
        if key == "private_image_self_recognition_hint":
            return str(value or "").strip()[:1200]
        if key == "worldview_adaptation_mode":
            mode = str(value or "auto").strip()
            return mode if mode in {"auto", "modern", "fantasy", "sci_fi", "custom", "off"} else "auto"
        if key == "rest_reply_mode":
            mode = str(value or "probability").strip().lower()
            aliases = {
                "概率": "probability",
                "仅概率": "probability",
                "仅概率醒来": "probability",
                "模型": "llm",
                "模型判断": "llm",
                "模型判断是否醒来": "llm",
                "model": "llm",
                "llm_judge": "llm",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"probability", "llm"} else "probability"
        if key == "REST_WAKEUP_PROVIDER_ID":
            return str(value or "").strip()[:160]
        if key == "tts_generation_mode":
            mode = str(value or "fast_tag").strip().lower()
            aliases = {
                "hybrid": "fast_tag",
                "direct": "fast_tag",
                "tag": "fast_tag",
                "fast": "fast_tag",
                "快速": "fast_tag",
                "标签": "fast_tag",
                "标签直出": "fast_tag",
                "convert": "postprocess",
                "post": "postprocess",
                "llm": "postprocess",
                "后处理": "postprocess",
                "判断翻译": "postprocess",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"fast_tag", "postprocess"} else "fast_tag"
        if key == "tts_frequency_control_mode":
            mode = str(value or "global").strip().lower()
            aliases = {
                "全局": "global",
                "全局频控": "global",
                "新版": "global",
                "旧版": "legacy",
                "旧版行为": "legacy",
                "legacy_mode": "legacy",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"global", "legacy"} else "global"
        if key == "tts_constraint_mode":
            mode = str(value or "weak").strip().lower()
            aliases = {
                "弱": "weak",
                "弱约束": "weak",
                "软": "weak",
                "软约束": "weak",
                "强": "strong",
                "强约束": "strong",
                "硬": "strong",
                "硬约束": "strong",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"weak", "strong"} else "weak"
        if key == "tts_voice_language":
            lang = str(value or "ja").strip().lower()
            return lang if lang in {"ja", "zh", "en"} else "ja"
        if key == "tts_delivery_mode":
            mode = str(value or "voice_and_text").strip().lower()
            return mode if mode in {"voice_only", "voice_and_text"} else "voice_and_text"
        if key == "tts_foreign_text_mode":
            mode = str(value or "translation").strip().lower()
            return mode if mode in {"original", "translation", "bilingual"} else "translation"
        if key == "tts_conversion_scope":
            mode = str(value or "partial").strip().lower()
            return mode if mode in {"partial", "full"} else "partial"
        if key in {"tts_extra_prompt", "main_user_mention_voice_prompt"}:
            return str(value or "").strip()[:1200]
        if key in {"natural_language_photo_extra_prompt", "photo_generation_fixed_prompt", "photo_generation_scene_presets"}:
            return str(value or "").strip()[:5000]
        if key == "natural_language_photo_generation_mode":
            mode = str(value or "tool_first").strip().lower()
            aliases = {
                "tool": "tool_first",
                "工具": "tool_first",
                "工具优先": "tool_first",
                "规则": "rule_fast",
                "规则快判": "rule_fast",
                "快判": "rule_fast",
                "关闭": "off",
                "关": "off",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"tool_first", "rule_fast", "off"} else "tool_first"
        if key == "tts_conversion_provider_id":
            return str(value or "").strip()[:160]
        if key == "tts_session_min_interval_seconds":
            try:
                return max(0.0, min(3600.0, float(value)))
            except (TypeError, ValueError):
                return 90.0
        if key in {"tts_private_min_interval_seconds", "tts_group_min_interval_seconds"}:
            try:
                return max(-1.0, min(3600.0, float(value)))
            except (TypeError, ValueError):
                return -1.0
        if key == "main_user_mention_voice_keywords":
            return str(value or "").strip()[:1200]
        if key == "forward_message_mode":
            mode = str(value or "inject").strip().lower()
            if mode in {"注入", "injection"}:
                return "inject"
            if mode in {"转述", "summary", "summarize", "narrate", "relay"}:
                return "transcribe"
            return mode if mode in {"inject", "transcribe"} else "inject"
        if key == "photo_generation_backend":
            mode = str(value or "auto").strip().lower()
            return mode if mode in {"auto", "comfyui", "sdgen", "external", "tool_call"} else "auto"
        if key == "external_image_api_endpoints":
            normalizer = getattr(self.plugin, "_normalize_external_image_api_endpoints", None)
            return normalizer(value) if callable(normalizer) else (value if isinstance(value, list) else [])
        if key in {"external_image_api_platform", "backup_external_image_api_platform"}:
            mode = str(value or "auto").strip().lower()
            aliases = {
                "openai兼容": "openai",
                "openai-compatible": "openai",
                "百炼": "bailian",
                "阿里云百炼": "bailian",
                "dashscope": "bailian",
                "modelscope": "modelscope",
                "model_scope": "modelscope",
                "魔搭": "modelscope",
                "魔搭社区": "modelscope",
                "api-inference": "modelscope",
                "doubao": "doubao",
                "豆包": "doubao",
                "火山": "doubao",
                "火山引擎": "doubao",
                "seedream": "doubao",
                "volcengine": "doubao",
                "gemini": "gemini",
                "google": "gemini",
                "谷歌": "gemini",
                "generativelanguage": "gemini",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"auto", "openai", "bailian", "modelscope", "doubao", "gemini"} else "auto"
        if key == "segmented_proactive_split_mode":
            mode = str(value or "regex").strip().lower()
            return mode if mode in {"regex", "words"} else "regex"
        if key == "segmented_proactive_scope":
            mode = str(value or "proactive_only").strip().lower()
            aliases = {
                "plugin": "proactive_only",
                "plugins": "proactive_only",
                "proactive": "proactive_only",
                "插件": "proactive_only",
                "插件主动": "proactive_only",
                "all": "all_llm",
                "llm": "all_llm",
                "全部": "all_llm",
                "全部分段": "all_llm",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"proactive_only", "all_llm"} else "proactive_only"
        if key == "segmented_proactive_chat_scope":
            mode = str(value or "all").strip().lower()
            aliases = {
                "全部": "all",
                "all_chat": "all",
                "both": "all",
                "私聊": "private",
                "仅私聊": "private",
                "private_only": "private",
                "群聊": "group",
                "仅群聊": "group",
                "group_only": "group",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"all", "private", "group"} else "all"
        if key == "segmented_proactive_interval_method":
            mode = str(value or "log").strip().lower()
            return mode if mode in {"log", "random"} else "log"
        if key == "segmented_proactive_content_cleanup_scope":
            mode = str(value or "all").strip().lower()
            return mode if mode in {"all", "trailing"} else "all"
        if key in {"segmented_proactive_split_words", "segmented_proactive_content_cleanup_words"}:
            def _decode_segmented_word(raw: Any) -> str:
                text = str(raw or "")
                stripped = text.strip()
                lowered = stripped.lower()
                if lowered in {"<space>", "{space}", "[space]", "\\s", "\\u0020", "空格"}:
                    return " "
                if lowered in {"<newline>", "{newline}", "[newline]", "\\n", "换行"}:
                    return "\n"
                if lowered in {"<tab>", "{tab}", "[tab]", "\\t", "tab"}:
                    return "\t"
                if lowered in {"<comma>", "{comma}", "[comma]", "comma", "英文逗号"}:
                    return ","
                if lowered in {"<zh_comma>", "{zh_comma}", "[zh_comma]", "zh_comma", "中文逗号", "逗号"}:
                    return "，"
                if text and text.isspace():
                    return text[:1]
                return stripped

            if isinstance(value, list):
                words = [_decode_segmented_word(item) for item in value]
            else:
                raw_words = str(value or "")
                parts = re.split(r"\r?\n", raw_words) if ("\n" in raw_words or "\r" in raw_words) else re.split(r"[,、]+", raw_words)
                words = [_decode_segmented_word(part) for part in parts]
            words = [word for word in words if word != ""]
            return words[:80]
        if key == "segmented_proactive_content_replacements":
            if isinstance(value, list):
                rules = [item for item in value if isinstance(item, dict) or str(item or "").strip()]
            else:
                rules = [line.strip() for line in str(value or "").splitlines() if line.strip()]
            return rules[:80]
        if key in {"segmented_proactive_regex", "segmented_proactive_content_cleanup_rule"}:
            return str(value or "").strip()[:800]
        if key == "atrelay_default_relay_style":
            mode = str(value or "persona").strip()
            return mode if mode in {"persona", "soft", "original"} else "persona"
        if key == "enable_persona_voice_channels":
            return self._normalize_bool_value(value)
        if key in {
            "reply_style_prompt",
            "worldview_adaptation_prompt",
            "persona_conversation_voice_prompt",
            "persona_creative_voice_prompt",
            "persona_planning_voice_prompt",
            "persona_inner_voice_prompt",
            "persona_proactive_voice_prompt",
        }:
            return str(value or "").strip()[:1200]
        if key == "roleplay_knowledge_source_ids":
            normalizer = getattr(self.plugin, "_normalize_roleplay_knowledge_source_ids", None)
            if callable(normalizer):
                return normalizer(value)
            return []
        if key in {"schedule_persona_prompt", "schedule_worldview_prompt", "roleplay_user_profile_prompt"}:
            return str(value or "").strip()[:2000]
        if key == "humanized_state_intensity":
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 50
        if key in {"local_photo_cpu_busy_percent", "local_photo_memory_busy_percent"}:
            try:
                return max(1, min(100, int(value)))
            except (TypeError, ValueError):
                return 85 if key == "local_photo_cpu_busy_percent" else 88
        if key == "local_photo_defer_minutes":
            try:
                return max(1, min(240, int(value)))
            except (TypeError, ValueError):
                return 30
        if key == "comfyui_photo_wait_seconds":
            try:
                return max(5, min(600, int(value)))
            except (TypeError, ValueError):
                return 90
        if key in {"external_image_api_timeout_seconds", "backup_external_image_api_timeout_seconds"}:
            try:
                return max(20, min(600, int(value)))
            except (TypeError, ValueError):
                return 180
        if key == "photo_action_max_daily":
            try:
                return max(0, min(5, int(value)))
            except (TypeError, ValueError):
                return 1
        if key == "natural_language_photo_generation_max_daily":
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 2
        if key in self.PERCENT_PROBABILITY_KEYS:
            try:
                raw = float(value)
                return max(0, min(100, int(round(raw * 100 if 0 <= raw <= 1 else raw))))
            except (TypeError, ValueError):
                if key == "rest_reply_probability":
                    return 18
                if key in {"tts_trigger_probability", "auto_voice_probability"}:
                    return 25
                return 20
        if key in self.INHERIT_PERCENT_PROBABILITY_KEYS:
            try:
                raw = float(value)
                if raw < 0:
                    return -1
                return max(0, min(100, int(round(raw * 100 if 0 <= raw <= 1 else raw))))
            except (TypeError, ValueError):
                return -1
        if key in {"rest_reply_llm_threshold", "group_wakeup_question_threshold", "group_wakeup_cold_group_threshold"}:
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 65
        if key == "rest_reply_awake_grace_minutes":
            try:
                return max(0, min(240, int(value)))
            except (TypeError, ValueError):
                return 30
        if key == "proactive_persona_judge_send_threshold":
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 62
        if key == "proactive_intensity_preset":
            normalizer = getattr(self.plugin, "_normalize_proactive_intensity_preset", None)
            return normalizer(value) if callable(normalizer) else str(value or "off").strip().lower()
        if key in {"proactive_review_strength", "passive_review_strength"}:
            text = str(value or "lenient").strip().lower()
            aliases = {
                "宽松": "lenient",
                "标准": "balanced",
                "严格": "strict",
            }
            text = aliases.get(text, text)
            return text if text in {"lenient", "balanced", "strict"} else "lenient"
        if key in {"passive_review_mode", "proactive_review_mode", "response_review_mode"}:
            default = "full" if key == "proactive_review_mode" else "severe_only"
            text = str(value or default).strip().lower()
            return text if text in {"local_only", "severe_only", "full"} else default
        if key == "quote_skip_short_reply_chars":
            try:
                return max(0, min(120, int(value)))
            except (TypeError, ValueError):
                return 0
        if key == "rest_backlog_max_messages":
            try:
                return max(1, min(12, int(value)))
            except (TypeError, ValueError):
                return 4
        if key == "proactive_reply_context_hours":
            try:
                return max(1, min(72, int(value)))
            except (TypeError, ValueError):
                return 12
        if key == "proactive_persona_judge_cache_minutes":
            try:
                return max(5, min(720, int(value)))
            except (TypeError, ValueError):
                return 180
        if key == "proactive_persona_judge_max_daily":
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 12
        if key == "enable_maslow_schedule_influence":
            return self._normalize_bool_value(value)
        if key == "enable_experimental_motivation_model":
            return self._normalize_bool_value(value)
        if key == "enable_personality_iteration_experiment":
            return self._normalize_bool_value(value)
        if key == "enable_personality_iteration_auto_tune":
            return self._normalize_bool_value(value)
        if key == "maslow_motivation_strength":
            try:
                return max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return 35
        if key == "memory_companion_context_timeout_seconds":
            try:
                return max(0.2, min(6.0, float(value)))
            except (TypeError, ValueError):
                return 1.2
        if key in (
            "enable_memory_companion_emotional_drift",
            "enable_memory_companion_cross_window_emotion",
            "enable_memory_companion_dream_fragment",
            "enable_memory_companion_open_loop_search",
            "enable_memory_companion_feature_context",
        ):
            return self._normalize_bool_value(value)
        if key == "memory_companion_context_top_k":
            try:
                return max(1, min(10, int(value)))
            except (TypeError, ValueError):
                return 5
        if key == "memory_companion_context_max_chars":
            try:
                return max(240, min(1800, int(value)))
            except (TypeError, ValueError):
                return 900
        if key == "max_proactive_plan_lag_minutes":
            try:
                return max(5, min(1440, int(value)))
            except (TypeError, ValueError):
                return 180
        if key == "external_link_share_cooldown_hours":
            try:
                return max(0, min(168, int(value)))
            except (TypeError, ValueError):
                return 72
        if key == "web_exploration_min_interval_hours":
            try:
                return max(1, min(168, int(value)))
            except (TypeError, ValueError):
                return 8
        if key == "web_exploration_max_results":
            try:
                return max(3, min(20, int(value)))
            except (TypeError, ValueError):
                return 6
        if key in {
            "check_interval_seconds",
            "daily_token_limit",
            "daily_token_soft_limit",
            "rest_reply_llm_threshold",
            "idle_minutes",
            "min_interval_minutes",
            "max_daily_messages",
            "segmented_proactive_threshold",
            "segmented_proactive_min_segment_chars",
            "segmented_proactive_max_segments",
            "group_conversation_followup_seconds",
            "group_conversation_followup_max_turns",
            "group_interject_min_interval_minutes",
            "group_interject_max_daily",
            "group_scene_recent_limit",
            "group_wakeup_cooldown_seconds",
            "group_wakeup_cold_group_idle_minutes",
            "group_wakeup_generated_keyword_limit",
            "group_wakeup_topic_interest_max_boost",
            "group_wakeup_debounce_pending_penalty",
            "group_wakeup_fatigue_limit",
            "group_wakeup_fatigue_decay_minutes",
            "group_wakeup_log_limit",
            "group_high_intensity_wakeup_window_seconds",
            "group_high_intensity_wakeup_threshold",
            "group_high_intensity_cooldown_seconds",
            "group_high_intensity_merge_seconds",
            "group_high_intensity_max_merge_messages",
            "photo_action_max_daily",
            "comfyui_photo_wait_seconds",
            "local_photo_cpu_busy_percent",
            "local_photo_memory_busy_percent",
            "local_photo_defer_minutes",
            "external_image_api_timeout_seconds",
            "forward_message_max_messages",
            "forward_message_max_chars",
            "forward_message_image_limit",
            "max_group_recent_messages",
            "max_group_slang_terms",
            "memory_refresh_interval_minutes",
            "episode_memory_refresh_messages",
            "episode_memory_refresh_minutes",
            "max_companion_memory_items",
            "max_learned_expression_items",
            "max_dialogue_episodes",
            "user_habit_min_count",
            "user_habit_max_items",
            "emotional_gate_hurt_threshold",
            "emotional_gate_refuse_threshold",
            "emotional_gate_recovery_per_hour",
            "emotional_gate_max_hurt_minutes",
            "bilibili_boredom_min_interval_hours",
            "bilibili_share_min_score",
            "news_min_interval_hours",
            "news_max_items_per_source",
            "news_hot_max_items",
            "ai_daily_check_interval_minutes",
            "external_event_self_link_cooldown_hours",
            "external_link_share_cooldown_hours",
            "qzone_life_publish_min_interval_hours",
            "qzone_emotional_vent_threshold",
            "qzone_emotional_vent_cooldown_hours",
            "private_reading_min_interval_hours",
            "private_reading_max_photo_count",
            "private_reading_preference_min_ratings",
            "private_reading_preference_max_terms",
            "unanswered_screen_peek_after_minutes",
            "unanswered_screen_peek_cooldown_minutes",
            "creative_chars_per_session",
            "creative_max_active_projects",
            "worldbook_member_inject_limit",
            "atrelay_member_cache_minutes",
            "atrelay_multi_target_limit",
            "private_image_vision_cache_max_items",
            "context_image_caption_max_items",
            "group_slang_web_search_terms",
            "group_slang_web_search_results",
            "auto_voice_max_chars",
            "auto_voice_cooldown_seconds",
        }:
            try:
                if key == "group_high_intensity_max_merge_messages":
                    return max(0, min(50, int(value)))
                parsed = max(0, int(value))
                return parsed
            except (TypeError, ValueError):
                if key == "group_high_intensity_max_merge_messages":
                    return 8
                return 0
        if key == "group_wakeup_interest_probability":
            try:
                raw = float(value)
                return max(0, min(100, int(round(raw * 100 if 0 <= raw <= 1 else raw))))
            except (TypeError, ValueError):
                return 0
        if key == "inbound_message_debounce_seconds":
            try:
                return max(0.0, min(30.0, float(value)))
            except (TypeError, ValueError):
                return 3.0
        if key == "semantic_message_debounce_seconds":
            try:
                return max(0.0, min(15.0, float(value)))
            except (TypeError, ValueError):
                return 8.0
        if key in {"text_message_debounce_seconds", "image_message_debounce_seconds", "forward_message_debounce_seconds"}:
            try:
                return max(0.0, min(15.0, float(value)))
            except (TypeError, ValueError):
                return 0.0 if key != "image_message_debounce_seconds" else 8.0
        if key == "text_message_debounce_max_wait_seconds":
            try:
                return max(0.0, min(30.0, float(value)))
            except (TypeError, ValueError):
                return 12.0
        if key == "message_debounce_max_merge_messages":
            try:
                return max(0, min(30, int(value)))
            except (TypeError, ValueError):
                return 8
        if key in {"smart_message_debounce_model_timeout_seconds", "smart_message_debounce_wait_seconds", "smart_message_debounce_learning_window_seconds"}:
            try:
                upper = 5.0 if key == "smart_message_debounce_model_timeout_seconds" else 30.0
                lower = 0.2 if key == "smart_message_debounce_model_timeout_seconds" else 0.0
                return max(lower, min(upper, float(value)))
            except (TypeError, ValueError):
                if key == "smart_message_debounce_model_timeout_seconds":
                    return 0.8
                return 3.0 if key == "smart_message_debounce_wait_seconds" else 8.0
        if key == "smart_message_debounce_examples_limit":
            try:
                return max(0, min(30, int(value)))
            except (TypeError, ValueError):
                return 8
        if key == "SMART_MESSAGE_DEBOUNCE_PROVIDER_ID":
            return self._single_line(value, 160)
        if key == "SMART_SILENCE_PROVIDER_ID":
            return self._single_line(value, 160)
        if key == "smart_silence_judge_mode":
            mode = str(value or "boundary_only").strip().lower()
            aliases = {
                "边界": "boundary_only",
                "明确边界": "boundary_only",
                "保守": "boundary_only",
                "上下文": "contextual",
                "模型判断": "contextual",
                "更智能": "contextual",
                "智能": "contextual",
            }
            mode = aliases.get(mode, mode)
            return mode if mode in {"boundary_only", "contextual"} else "boundary_only"
        if key == "smart_silence_model_timeout_seconds":
            try:
                return max(0.2, min(5.0, float(value)))
            except (TypeError, ValueError):
                return 1.2
        if key == "private_image_vision_wait_seconds":
            try:
                return max(0.0, min(90.0, float(value)))
            except (TypeError, ValueError):
                return 30.0
        if key == "context_image_caption_timeout_seconds":
            try:
                return max(0.0, min(30.0, float(value)))
            except (TypeError, ValueError):
                return 8.0
        if key == "private_image_gif_max_frames":
            try:
                return max(1, min(8, int(value)))
            except (TypeError, ValueError):
                return 4
        if key == "group_repeat_trigger_threshold":
            try:
                return max(3, min(20, int(value)))
            except (TypeError, ValueError):
                return 4
        if key in {
            "group_repeat_follow_probability",
            "group_repeat_interrupt_probability",
            "group_repeat_interrupt_probability_step",
        }:
            try:
                raw = float(value)
                return max(0, min(100, int(round(raw * 100 if 0 <= raw <= 1 else raw))))
            except (TypeError, ValueError):
                return 0
        if key in self.FRACTIONAL_PERCENT_SETTING_KEYS:
            return self._normalize_fractional_percent_value(value)
        if key == "skill_growth_rate":
            try:
                return max(0.1, min(3.0, float(value)))
            except (TypeError, ValueError):
                return 1.0
        if key in {
            "segmented_proactive_interval_min",
            "segmented_proactive_interval_max",
            "segmented_proactive_log_base",
        }:
            try:
                raw = float(value)
                if key == "segmented_proactive_log_base":
                    return max(1.1, min(10.0, raw))
                return max(0.1, min(30.0, raw))
            except (TypeError, ValueError):
                return 1.8 if key == "segmented_proactive_log_base" else 1.5
        if key in {
            "enable_daily_token_soft_limit",
            "enable_bilibili_integration",
            "enable_bilibili_boredom_watch",
            "enable_news_integration",
            "enable_news_boredom_read",
            "enable_news_daily_hot_read",
            "enable_ai_daily_watch",
            "ai_daily_prefer_text_version",
            "enable_external_event_self_link",
            "enable_web_exploration",
            "enable_web_exploration_boredom_search",
            "enable_qzone_integration",
            "enable_qzone_life_publish",
            "enable_qzone_generated_image_publish",
            "enable_qzone_comment_inbox",
            "enable_qzone_emotional_vent_publish",
            "enable_private_reading_integration",
            "enable_private_reading_boredom_read",
            "enable_private_reading_ask_recommendation",
            "enable_private_reading_preference_influence",
            "enable_unanswered_screen_peek_followup",
            "enable_creative_writing",
            "creative_hidden_mode",
            "enable_environment_perception",
            "enable_holiday_perception",
            "enable_platform_perception",
            "enable_model_perception",
            "enable_worldview_perception",
            "enable_lunar_perception",
            "enable_solar_term_perception",
            "enable_almanac_perception",
            "auto_voice_enabled",
            "auto_voice_full_conversion_enabled",
            "enable_humanized_states",
            "inject_passive_states",
            "enable_health_state",
            "enable_hunger_state",
            "enable_cycle_state",
            "enable_worldbook_member_recognition",
            "enable_group_scene_awareness",
            "enable_group_reality_promise_guard",
            "enable_group_wakeup_enhancement",
            "enable_group_high_intensity_mode",
            "enable_group_injection_guard",
            "enable_group_persona_denoise",
            "enable_group_repeat_follow",
            "group_repeat_count_distinct_users_only",
            "enable_forward_message_adaptation",
            "enable_skill_growth_simulation",
            "enable_skill_growth_passive_injection",
            "enable_skill_growth_schedule_influence",
            "forward_message_parse_nested",
            "forward_message_image_vision",
            "enable_message_debounce",
            "enable_smart_message_debounce",
            "enable_recall_enhancement",
            "enable_recall_cancel_reply",
            "enable_recall_message_cache",
            "enable_recall_transcribe_command",
            "enable_forbidden_word_recall",
            "recall_forbidden_word_case_sensitive",
            "enable_semantic_message_debounce",
            "enable_proactive_quote_trigger_message",
            "enable_quote_group_reply",
            "enable_quote_group_interjection",
            "enable_quote_private_proactive",
            "enable_local_photo_load_guard",
            "enable_private_image_self_recognition",
            "enable_context_image_captioning",
            "enable_private_image_gif_enhancement",
            "enable_private_image_vision_cache",
            "enable_segmented_proactive_reply",
            "segmented_proactive_send_as_forward",
            "enable_segmented_proactive_content_cleanup",
            "enable_segmented_proactive_content_replacement",
            "enable_humanized_states",
            "inject_passive_states",
            "enable_health_state",
            "enable_hunger_state",
            "enable_cycle_state",
            "enable_group_conversation_followup",
            "worldbook_auto_import",
            "worldbook_member_match_aliases",
            "worldbook_self_registration",
            "enable_atrelay_tools",
            "enable_cross_user_memory_bridge",
            "atrelay_require_worldbook_first",
            "cross_user_memory_owner_only",
            "atrelay_sensitive_confirm",
            "enable_atrelay_llm_rewrite",
        }:
            return self._normalize_bool_value(value)
        schema_item = self._schema_item_for_key(key)
        if schema_item:
            return self._normalize_schema_setting_value(value, schema_item)
        return self._single_line(value, 240)

    def _normalize_schema_setting_value(self, value: Any, schema_item: dict[str, Any]) -> Any:
        item_type = str(schema_item.get("type") or "").lower()
        default = schema_item.get("default")
        slider = schema_item.get("slider") if isinstance(schema_item.get("slider"), dict) else {}

        def clamp_number(raw: float) -> float:
            if "min" in slider:
                try:
                    raw = max(float(slider.get("min")), raw)
                except (TypeError, ValueError):
                    pass
            if "max" in slider:
                try:
                    raw = min(float(slider.get("max")), raw)
                except (TypeError, ValueError):
                    pass
            return raw

        if item_type == "bool":
            return self._normalize_bool_value(value)
        if item_type == "int":
            try:
                return int(round(clamp_number(float(value))))
            except (TypeError, ValueError):
                try:
                    return int(default)
                except (TypeError, ValueError):
                    return 0
        if item_type == "float":
            try:
                return clamp_number(float(value))
            except (TypeError, ValueError):
                try:
                    return float(default)
                except (TypeError, ValueError):
                    return 0.0
        if item_type == "list":
            if isinstance(value, list):
                return [self._single_line(item, 160) for item in value if self._single_line(item, 160)]
            text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
            parts = re.split(r"[\n,，、\s]+", text)
            return [self._single_line(item, 160) for item in parts if self._single_line(item, 160)]
        limit = 4000 if item_type == "text" else 1000
        return str(value if value is not None else default or "").strip()[:limit]

    @staticmethod
    def _normalize_fractional_percent_value(value: Any, default: float = 0.0) -> float:
        try:
            raw = float(value)
        except (TypeError, ValueError):
            raw = default
        if raw > 1.0:
            raw /= 100.0
        return max(0.0, min(1.0, raw))

    @staticmethod
    def _normalize_multiline_source_config(value: Any, *, limit: int = 4000) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if text and "\n" not in text:
            markers = list(re.finditer(r"(?:^|\s+)(#?\s*[^|\n]+?)\|(?=(?:https?://|bilibili:|bvid:))", text, flags=re.I))
            if len(markers) > 1:
                recovered: list[str] = []
                for index, match in enumerate(markers):
                    start = match.end()
                    end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
                    name = str(match.group(1) or "").strip()
                    target = text[start:end].strip()
                    if name and target:
                        recovered.append(f"{name}|{target}")
                if recovered:
                    text = "\n".join(recovered)
        lines: list[str] = []
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if line:
                lines.append(line)
        return "\n".join(lines)[:limit].strip()

    def _schema_key_index(self) -> dict[str, Any]:
        cached = self._schema_key_index_cache
        if cached is not None:
            return cached
        index: dict[str, Any] = {
            "all": set(),
            "public": set(),
            "bool": set(),
            "public_bool": set(),
            "provider": set(),
            "public_provider": set(),
            "group": {},
            "item": {},
        }

        def visit(items: dict[str, Any], group_key: str = "") -> None:
            for raw_key, item in items.items():
                if not isinstance(item, dict):
                    continue
                key = str(raw_key)
                item_type = str(item.get("type") or "")
                if item_type == "object" and isinstance(item.get("items"), dict):
                    visit(item["items"], key)
                    continue
                hidden = bool(item.get("invisible"))
                index["group"][key] = group_key
                index["item"][key] = item
                index["all"].add(key)
                if not hidden:
                    index["public"].add(key)
                if item_type == "bool":
                    index["bool"].add(key)
                    if not hidden:
                        index["public_bool"].add(key)
                if self._schema_item_is_provider(key, item):
                    index["provider"].add(key)
                    if not hidden:
                        index["public_provider"].add(key)

        try:
            raw = json.loads(Path(__file__).with_name("_conf_schema.json").read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                visit(raw)
        except Exception as exc:
            logger.debug("[PrivateCompanionPage] 读取配置 schema 索引失败: %s", exc)
        self._schema_key_index_cache = index
        return index

    @staticmethod
    def _schema_item_is_provider(key: str, item: dict[str, Any]) -> bool:
        if item.get("_special") == "select_provider":
            return True
        return key.endswith("PROVIDER_ID") or key.endswith("_provider_id") or key.endswith("provider_id")

    def _schema_setting_keys(self, *, public_only: bool = False) -> set[str]:
        index = self._schema_key_index()
        key_name = "public" if public_only else "all"
        provider_key_name = "public_provider" if public_only else "provider"
        return set(index[key_name]) - set(index[provider_key_name])

    def _schema_provider_keys(self, *, public_only: bool = False) -> set[str]:
        index = self._schema_key_index()
        return set(index["public_provider" if public_only else "provider"])

    def _schema_bool_keys(self) -> set[str]:
        return set(self._schema_key_index()["bool"])

    def _schema_group_for_key(self, key: str) -> str:
        group_map = self._schema_key_index().get("group")
        return str(group_map.get(key, "") if isinstance(group_map, dict) else "")

    def _schema_item_for_key(self, key: str) -> dict[str, Any]:
        item_map = self._schema_key_index().get("item")
        item = item_map.get(key) if isinstance(item_map, dict) else None
        return item if isinstance(item, dict) else {}

    @classmethod
    def _normalize_worldbook_member_id(cls, value: Any) -> str:
        text = cls._single_line(value, 80)
        if not text:
            return ""
        lowered = text.lower()
        if lowered.startswith("bili:") or lowered.startswith("bilibili:"):
            digits = re.sub(r"\D+", "", lowered.split(":", 1)[1])
            return f"bili:{digits}" if digits else ""
        if lowered.startswith("bili_live_"):
            return re.sub(r"[^A-Za-z0-9_:-]+", "_", text)[:80]
        if text.isdigit():
            return text
        return re.sub(r"[^A-Za-z0-9_:-]+", "_", text)[:80]

    @staticmethod
    def _worldbook_member_id_valid(user_id: str) -> bool:
        if user_id.isdigit():
            return len(user_id) >= 5
        lowered = user_id.lower()
        if lowered.startswith("bili:"):
            return bool(re.fullmatch(r"bili:\d{2,}", lowered))
        if lowered.startswith("bili_live_"):
            return bool(re.fullmatch(r"bili_live_[A-Za-z0-9_-]{6,64}", user_id))
        return False

    def _bind_worldbook_external_member_locked(
        self,
        profiles: dict[str, Any],
        source_id: str,
        target_id: str,
        source_profile: dict[str, Any],
    ) -> dict[str, Any]:
        target = profiles.get(target_id)
        if not isinstance(target, dict):
            target = {
                "user_id": target_id,
                "name": self._single_line(source_profile.get("name"), 80) or target_id,
                "gender": self._single_line(source_profile.get("gender"), 40),
                "aliases": [],
                "content": "",
                "identity_note": f"QQ {target_id}，由外部身份绑定创建。",
                "boundary_note": "",
                "important_memories": [],
                "enabled": True,
                "priority": 120,
                "source_entries": [],
                "observed_names": [],
            }
            profiles[target_id] = target
        target["user_id"] = target_id
        target["identity_type"] = "qq"
        source_gender = self._single_line(source_profile.get("gender"), 40)
        if source_gender and not self._single_line(target.get("gender"), 40):
            target["gender"] = source_gender
        live_names = self._worldbook_string_list(source_profile.get("observed_names"), limit=12, item_limit=40)
        live_name = self._single_line(source_profile.get("name"), 40)
        if live_name and live_name != target_id:
            live_names.insert(0, live_name)
        aliases = self._worldbook_string_list(target.get("aliases"), limit=30, item_limit=40)
        for alias in live_names:
            if alias and alias != target_id and alias not in aliases:
                aliases.append(alias)
        target["aliases"] = aliases[:30]

        external_ids = self._worldbook_string_list(target.get("external_ids"), limit=20, item_limit=80)
        if source_id not in external_ids:
            external_ids.insert(0, source_id)
        target["external_ids"] = external_ids[:20]
        target["linked_bili_profile_id"] = source_id
        target["manual_edit_ts"] = time.time()

        for field, limit in (("content", 2000), ("identity_note", 2000), ("boundary_note", 1200)):
            source_text = str(source_profile.get(field) or "").strip()
            target_text = str(target.get(field) or "").strip()
            if source_text and source_text not in target_text:
                glue = "\n" if target_text else ""
                target[field] = (target_text + glue + source_text)[:limit]

        source_memories = self._normalize_important_memories(source_profile.get("important_memories"))
        target_memories = self._normalize_important_memories(target.get("important_memories"))
        seen = {self._single_line(item.get("content"), 160) for item in target_memories if isinstance(item, dict)}
        for memory in source_memories:
            content = self._single_line(memory.get("content"), 160)
            if content and content not in seen:
                target_memories.append(memory)
                seen.add(content)
        target["important_memories"] = target_memories[:30]

        source_entries = self._worldbook_string_list(target.get("source_entries"), limit=30, item_limit=80)
        for entry in self._worldbook_string_list(source_profile.get("source_entries"), limit=12, item_limit=80):
            if entry not in source_entries:
                source_entries.append(entry)
        if "live_stream_companion" not in source_entries:
            source_entries.append("live_stream_companion")
        target["source_entries"] = source_entries[:30]

        source_profile["enabled"] = False
        source_profile["linked_qq_user_id"] = target_id
        source_profile["merged_into_user_id"] = target_id
        source_profile["manual_edit_ts"] = time.time()
        self._merge_live_viewer_activity_for_worldbook_bind(source_id, target_id, live_names)
        return {"source_user_id": source_id, "target_user_id": target_id}

    def _worldbook_string_list(self, value: Any, *, limit: int = 20, item_limit: int = 60) -> list[str]:
        raw_items: list[Any]
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            raw_items = re.split(r"[\n,，;；]+", value)
        else:
            raw_items = []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = self._single_line(item, item_limit)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= limit:
                break
        return result

    def _merge_live_viewer_activity_for_worldbook_bind(self, source_id: str, target_id: str, live_names: list[str]) -> None:
        store = self.plugin.data.get("live_stream_companion")
        if not isinstance(store, dict):
            return
        activity = store.get("viewer_activity")
        if not isinstance(activity, dict):
            return
        target_key = f"user:{target_id}"
        source_keys = [f"user:{source_id}"]
        source_keys.extend(f"live:{name}" for name in live_names if name)
        target = activity.setdefault(target_key, {"viewer_key": target_key, "user_id": target_id, "recent_events": [], "recent_danmaku": [], "event_counts": {}})
        if not isinstance(target, dict):
            target = {"viewer_key": target_key, "user_id": target_id, "recent_events": [], "recent_danmaku": [], "event_counts": {}}
            activity[target_key] = target
        target["viewer_key"] = target_key
        target["user_id"] = target_id
        aliases = target.setdefault("live_usernames", [])
        if not isinstance(aliases, list):
            aliases = []
            target["live_usernames"] = aliases
        for name in live_names:
            if name and name not in aliases:
                aliases.insert(0, name)
        del aliases[8:]
        for key in source_keys:
            item = activity.get(key)
            if not isinstance(item, dict) or item is target:
                continue
            self._merge_activity_item(target, item)
            activity.pop(key, None)

    @staticmethod
    def _merge_activity_item(target: dict[str, Any], source: dict[str, Any]) -> None:
        def as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def as_int(value: Any, default: int = 0) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        target["total_events"] = as_int(target.get("total_events")) + as_int(source.get("total_events"))
        if source.get("display_name") and not target.get("display_name"):
            target["display_name"] = source.get("display_name")
        if source.get("live_username") and not target.get("live_username"):
            target["live_username"] = source.get("live_username")
        target["first_seen"] = min(as_float(target.get("first_seen"), time.time()), as_float(source.get("first_seen"), time.time()))
        target["last_seen"] = max(as_float(target.get("last_seen")), as_float(source.get("last_seen")))
        counts = target.setdefault("event_counts", {})
        if isinstance(counts, dict) and isinstance(source.get("event_counts"), dict):
            for key, value in source["event_counts"].items():
                counts[key] = as_int(counts.get(key)) + as_int(value)
        for field, limit in (("recent_events", 12), ("recent_danmaku", 8)):
            rows = []
            for row in [*(target.get(field) if isinstance(target.get(field), list) else []), *(source.get(field) if isinstance(source.get(field), list) else [])]:
                if isinstance(row, dict):
                    rows.append(row)
            rows.sort(key=lambda row: as_float(row.get("ts")), reverse=True)
            target[field] = rows[:limit]

    def _worldbook_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        profiles = data.get("worldbook_member_profiles") if isinstance(data.get("worldbook_member_profiles"), dict) else {}
        groups = data.get("worldbook_group_profiles") if isinstance(data.get("worldbook_group_profiles"), dict) else {}
        entries = data.get("worldbook_entries") if isinstance(data.get("worldbook_entries"), list) else []
        state = data.get("worldbook_import_state") if isinstance(data.get("worldbook_import_state"), dict) else {}
        member_count = self._int(data.get("worldbook_member_profile_count")) if "worldbook_member_profile_count" in data else 0
        enabled_member_count = self._int(data.get("worldbook_enabled_member_profile_count")) if "worldbook_enabled_member_profile_count" in data else 0
        pending_observation_total = self._int(data.get("worldbook_pending_observation_total")) if "worldbook_pending_observation_total" in data else 0
        group_count = self._int(data.get("worldbook_group_profile_count")) if "worldbook_group_profile_count" in data else 0
        entry_count = self._int(data.get("worldbook_entry_count")) if "worldbook_entry_count" in data else len(entries)
        profile_items = []
        for user_id, item in profiles.items():
            if not isinstance(item, dict):
                continue
            aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
            observed = item.get("observed_names") if isinstance(item.get("observed_names"), list) else []
            external_ids = item.get("external_ids") if isinstance(item.get("external_ids"), list) else []
            memories = self._normalize_important_memories(item.get("important_memories"))
            pending = item.get("pending_observations") if isinstance(item.get("pending_observations"), list) else []
            pending_items = []
            for raw in pending[:8]:
                if not isinstance(raw, dict):
                    continue
                pending_items.append(
                    {
                        "id": self._single_line(raw.get("id"), 40),
                        "title": self._single_line(raw.get("title"), 60) or "群聊观察",
                        "content": self._single_line(raw.get("content"), 260),
                        "evidence": self._single_line(raw.get("evidence"), 160),
                        "group_id": self._single_line(raw.get("group_id"), 40),
                        "weight": self._clamp_int(raw.get("weight"), 35, 0, 100),
                        "count": self._clamp_int(raw.get("count"), 1, 1, 999),
                        "created_at": self.plugin._format_timestamp_elapsed(raw.get("created_at", 0)),
                    }
                )
            profile_items.append(
                {
                    "user_id": self._single_line(user_id, 40),
                    "identity_type": self._single_line(item.get("identity_type") or ("qq" if str(user_id).isdigit() else "external"), 20),
                    "name": self._single_line(item.get("name"), 60),
                    "gender": self._single_line(item.get("gender"), 40),
                    "enabled": bool(item.get("enabled", True)),
                    "priority": item.get("priority", 120),
                    "aliases": [self._single_line(alias, 40) for alias in aliases if self._single_line(alias, 40)],
                    "observed_names": [self._single_line(name, 40) for name in observed if self._single_line(name, 40)],
                    "external_ids": [self._single_line(ext, 80) for ext in external_ids if self._single_line(ext, 80)],
                    "linked_qq_user_id": self._single_line(item.get("linked_qq_user_id") or item.get("merged_into_user_id"), 40),
                    "linked_bili_profile_id": self._single_line(item.get("linked_bili_profile_id"), 80),
                    "auto_registration_pending": bool(item.get("auto_registration_pending", False)),
                    "content": self._single_line(item.get("content"), 260),
                    "identity_note": self._single_line(item.get("identity_note") or item.get("note") or item.get("content"), 500),
                    "boundary_note": self._single_line(item.get("boundary_note"), 500),
                    "important_memories": memories,
                    "pending_observations": pending_items,
                    "pending_observation_count": len(pending_items),
                    "source_entries": item.get("source_entries") if isinstance(item.get("source_entries"), list) else [],
                    "note": self._single_line(item.get("note"), 500),
                }
            )
        profile_items.sort(key=lambda item: (not item.get("enabled", True), item.get("name") or item.get("user_id")))
        if "worldbook_member_profile_count" not in data:
            member_count = len(profile_items)
            enabled_member_count = sum(1 for item in profile_items if item.get("enabled", True))
            pending_observation_total = sum(self._clamp_int(item.get("pending_observation_count"), 0, 0, 999) for item in profile_items)
        group_items = [
            {
                "group_id": self._single_line(group_id, 40),
                "name": self._single_line(item.get("name"), 60),
                "enabled": bool(item.get("enabled", True)),
                "priority": item.get("priority", 110),
                "content": self._single_line(item.get("content"), 220),
            }
            for group_id, item in groups.items()
            if isinstance(item, dict)
        ]
        if "worldbook_group_profile_count" not in data:
            group_count = len(group_items)
        return {
            "enabled": bool(getattr(self.plugin, "enable_worldbook_member_recognition", False)),
            "auto_import": bool(getattr(self.plugin, "worldbook_auto_import", False)),
            "match_aliases": bool(getattr(self.plugin, "worldbook_member_match_aliases", False)),
            "self_registration": bool(getattr(self.plugin, "worldbook_self_registration", False)),
            "self_registration_block_word_count": len(
                getattr(self.plugin, "worldbook_self_registration_block_words", [])
                if isinstance(getattr(self.plugin, "worldbook_self_registration_block_words", []), list)
                else []
            ),
            "auto_pending_observations": bool(getattr(self.plugin, "worldbook_auto_pending_observations", False)),
            "inject_limit": getattr(self.plugin, "worldbook_member_inject_limit", 0),
            "entry_count": entry_count,
            "member_count": member_count,
            "enabled_member_count": enabled_member_count,
            "pending_observation_total": pending_observation_total,
            "group_count": group_count,
            "last_import": self.plugin._format_timestamp_elapsed(state.get("last_import_at", 0)),
            "source_files": state.get("source_files") if isinstance(state.get("source_files"), list) else [],
            "members": profile_items[:120],
            "groups": group_items[:80],
        }

    def _normalize_important_memories(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        memories: list[dict[str, Any]] = []
        for raw in value[:12]:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or "").strip()[:500]
            if not content:
                continue
            privacy = self._single_line(raw.get("privacy"), 20).lower()
            if privacy not in {"public", "private", "internal"}:
                privacy = "internal"
            memories.append(
                {
                    "title": self._single_line(raw.get("title"), 60),
                    "content": content,
                    "weight": self._clamp_int(raw.get("weight"), 50, 0, 100),
                    "privacy": privacy,
                    "source": self._single_line(raw.get("source"), 40),
                    "enabled": bool(raw.get("enabled", True)),
                    "updated_at": float(raw.get("updated_at") or time.time()),
                }
            )
        memories.sort(key=lambda item: (item.get("enabled", True), item.get("weight", 50), item.get("updated_at", 0)), reverse=True)
        return memories[:8]

    def _livingmemory_summary(self) -> dict[str, Any]:
        try:
            available = bool(self.plugin._livingmemory_available())
        except Exception:
            available = False
        diagnostic_getter = getattr(self.plugin, "_memory_recall_diagnostic_status", None)
        try:
            recall_status = diagnostic_getter() if callable(diagnostic_getter) else {}
        except Exception:
            recall_status = {}
        if not isinstance(recall_status, dict):
            recall_status = {}
        if recall_status.get("active") is False:
            available = False
        try:
            plugin_dir = str(self.plugin._livingmemory_plugin_dir())
        except Exception:
            plugin_dir = ""
        plugin_dir = str(recall_status.get("directory") or plugin_dir)
        try:
            status = self.plugin._format_livingmemory_status()
        except Exception:
            status = "记忆插件：状态探测失败，已跳过协同。"
        # Detect "我会牢牢记住你" (RememberYou) bridge availability
        memory_companion_active = False
        memory_companion_display_name = ""
        try:
            bridge = self.plugin._memory_companion_bridge()  # type: ignore[attr-defined]
            if bridge is not None:
                memory_companion_active = True
                memory_companion_display_name = getattr(bridge, "display_name", "") or "我会牢牢记住你"
                if str(memory_companion_display_name).strip().lower() in {"rememberyou", "remember you", "memorycompanion", "memory companion", "astrbot_plugin_memory_companion", "astrbot_plugin_remember_you"}:
                    memory_companion_display_name = "我会牢牢记住你"
        except Exception:
            pass
        configured_enabled = bool(getattr(self.plugin, "enable_livingmemory_integration", False))
        active_plugins: list[dict[str, Any]] = []
        if memory_companion_active:
            active_plugins.append(
                {
                    "type": "memory_companion",
                    "name": memory_companion_display_name or "我会牢牢记住你",
                    "display_name": memory_companion_display_name or "我会牢牢记住你",
                    "status": "桥接可用",
                }
            )
        if available:
            active_plugins.append(
                {
                    "type": "livingmemory",
                    "name": "书架长期记忆检索",
                    "display_name": "书架长期记忆检索",
                    "provider_plugin_id": "astrbot_plugin_bookshelf",
                    "role": "on_demand_recall",
                    "status": "工具式召回可用",
                    "tool_name": getattr(self.plugin, "livingmemory_tool_name", "") or "recall_long_term_memory",
                    "plugin_dir": plugin_dir,
                }
            )
        selected_plugin = active_plugins[0] if active_plugins else None
        coexisting = bool(memory_companion_active and available)
        # Bridge availability and a recall provider are complementary capability
        # signals, not proof of duplicate injection or writes.
        conflict = False
        conflict_warning = ""
        return {
            "enabled": bool(configured_enabled and active_plugins),
            "configured_enabled": configured_enabled,
            "compatible_available": bool(active_plugins),
            "available": available,
            "tool_name": getattr(self.plugin, "livingmemory_tool_name", ""),
            "plugin_dir": plugin_dir,
            "status": status,
            "memory_companion_active": memory_companion_active,
            "memory_companion_display_name": memory_companion_display_name,
            "active_plugins": active_plugins,
            "selected_plugin": selected_plugin,
            "selected_plugin_name": str((selected_plugin or {}).get("display_name") or ""),
            "conflict": conflict,
            "conflict_warning": conflict_warning,
            "coexistence_detected": coexisting,
            "coexistence_note": "记忆陪伴桥接与书架按需检索同时可用；这不是插件故障，也不能据此断言重复写入或重复注入。" if coexisting else "",
            "recall_provider": recall_status,
            "verification_state": "capability_presence_only",
        }

    def _screen_companion_available(self) -> bool:
        getter = getattr(self.plugin, "_get_screen_companion_plugin", None)
        if callable(getter):
            try:
                return getter() is not None
            except Exception:
                return False
        return False

    def _screen_companion_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        available = self._screen_companion_available()
        context = data.get("screen_diary_context") if isinstance(data.get("screen_diary_context"), dict) else {}
        return {
            "enabled": bool(available and getattr(self.plugin, "enable_yesterday_screen_diary_context", False)),
            "available": available,
            "source": context.get("source", ""),
            "source_date": context.get("source_date", ""),
            "context_available": bool(context.get("available")),
            "summary_chars": len(str(context.get("summary") or "")),
        }

    def _bilibili_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("bilibili_integration") if isinstance(data.get("bilibili_integration"), dict) else {}
        try:
            available = bool(getattr(self.plugin, "_bilibili_available", lambda: False)())
        except Exception:
            available = False
        latest = None
        try:
            latest_getter = getattr(self.plugin, "_latest_bilibili_video_candidate", None)
            latest = latest_getter(include_memory_api=False) if callable(latest_getter) else None
        except Exception:
            latest = None
        try:
            watch_log = str(getattr(self.plugin, "_bilibili_watch_log_file", lambda: "")())
        except Exception:
            watch_log = ""
        try:
            memory_checker = getattr(self.plugin, "_bilibili_memory_api_available", None)
            if callable(memory_checker):
                try:
                    memory_api_available = bool(memory_checker(allow_probe=False))
                except TypeError:
                    memory_api_available = bool(memory_checker())
            else:
                memory_api_available = False
        except Exception:
            memory_api_available = False
        return {
            "enabled": bool(available and getattr(self.plugin, "enable_bilibili_integration", False)),
            "boredom_watch_enabled": bool(available and getattr(self.plugin, "enable_bilibili_boredom_watch", False)),
            "available": available,
            "memory_api_available": memory_api_available,
            "watch_log": watch_log,
            "last_boredom_watch_at": self.plugin._format_timestamp_elapsed(state.get("last_boredom_watch_at", 0)),
            "last_status": state.get("last_boredom_watch_status", ""),
            "latest_video": latest if isinstance(latest, dict) else {},
        }

    def _news_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("news_integration") if isinstance(data.get("news_integration"), dict) else {}
        digest = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
        latest_items = state.get("latest_items") if isinstance(state.get("latest_items"), list) else []
        history = [
            item
            for item in self._browsing_history_entries(data)
            if item.get("source") == "news"
        ]
        ai_daily = state.get("ai_daily") if isinstance(state.get("ai_daily"), dict) else {}
        ai_digest = ai_daily.get("last_digest") if isinstance(ai_daily.get("last_digest"), dict) else {}
        ai_digest_items = ai_digest.get("items") if isinstance(ai_digest.get("items"), list) else []
        ai_digest_first_item = ai_digest_items[0] if ai_digest_items and isinstance(ai_digest_items[0], dict) else {}
        try:
            ai_text_chars = max(0, int(ai_daily.get("last_text_chars") or 0))
        except (TypeError, ValueError):
            ai_text_chars = 0
        if not ai_text_chars and ai_digest_first_item:
            ai_text_chars = len(str(ai_digest_first_item.get("article_text") or ""))
        try:
            ai_subtitle_chars = max(0, int(ai_daily.get("last_video_subtitle_chars") or 0))
        except (TypeError, ValueError):
            ai_subtitle_chars = 0
        if not ai_subtitle_chars and ai_digest_first_item:
            ai_subtitle_chars = len(str(ai_digest_first_item.get("video_subtitle_text") or ""))
        try:
            ai_video_context_chars = max(0, int(ai_daily.get("last_video_context_chars") or 0))
        except (TypeError, ValueError):
            ai_video_context_chars = 0
        if not ai_video_context_chars and ai_digest_first_item:
            ai_video_context_chars = len(str(ai_digest_first_item.get("video_context_text") or ""))
        try:
            ai_video_duration = max(0, int(ai_daily.get("last_video_duration") or ai_digest_first_item.get("video_duration") or 0))
        except (TypeError, ValueError):
            ai_video_duration = 0
        ai_video_tags_raw = ai_daily.get("last_video_tags") if isinstance(ai_daily.get("last_video_tags"), list) else ai_digest_first_item.get("video_tags")
        ai_video_tags = [
            self._single_line(tag, 40)
            for tag in ai_video_tags_raw
            if self._single_line(tag, 40)
        ] if isinstance(ai_video_tags_raw, list) else []
        ai_video_comments_raw = ai_daily.get("last_video_hot_comments") if isinstance(ai_daily.get("last_video_hot_comments"), list) else ai_digest_first_item.get("video_hot_comments")
        ai_video_comments = [
            self._single_line(comment, 120)
            for comment in ai_video_comments_raw
            if self._single_line(comment, 120)
        ] if isinstance(ai_video_comments_raw, list) else []
        try:
            source_count = len(getattr(self.plugin, "_news_source_items", lambda: [])())
        except Exception:
            source_count = 0
        return {
            "enabled": bool(getattr(self.plugin, "enable_news_integration", False)),
            "boredom_read_enabled": bool(getattr(self.plugin, "enable_news_boredom_read", False)),
            "daily_hot_enabled": bool(getattr(self.plugin, "enable_news_daily_hot_read", False)),
            "ai_daily_enabled": bool(getattr(self.plugin, "enable_ai_daily_watch", False)),
            "source_count": source_count,
            "history_count": len(history),
            "history": history,
            "last_read_at": self.plugin._format_timestamp_elapsed(state.get("last_read_at", 0)),
            "last_status": self._single_line(state.get("last_status"), 80),
            "ai_daily": {
                "status": self._single_line(ai_daily.get("status"), 80),
                "date": self._single_line(ai_daily.get("date"), 20),
                "last_checked_at": self.plugin._format_timestamp_elapsed(ai_daily.get("last_checked_at", 0)),
                "last_success_date": self._single_line(ai_daily.get("last_success_date"), 20),
                "last_source_name": self._single_line(ai_daily.get("last_source_name"), 40),
                "last_source_author": self._single_line(ai_daily.get("last_source_author"), 60),
                "last_source_mid": self._single_line(ai_daily.get("last_source_mid"), 40),
                "last_source_schedule": self._single_line(ai_daily.get("last_source_schedule"), 10),
                "last_video_title": self._single_line(ai_daily.get("last_video_title"), 120),
                "last_video_link": self._single_line(ai_daily.get("last_video_link"), 400),
                "last_video_owner_name": self._single_line(ai_daily.get("last_video_owner_name") or ai_digest_first_item.get("video_owner_name"), 80),
                "last_video_tname": self._single_line(ai_daily.get("last_video_tname") or ai_digest_first_item.get("video_tname"), 60),
                "last_video_duration": ai_video_duration,
                "last_video_context_chars": ai_video_context_chars,
                "last_video_tags": ai_video_tags[:10],
                "last_video_hot_comments": ai_video_comments[:5],
                "last_text_link": self._single_line(ai_daily.get("last_text_link"), 400),
                "last_text_readable": bool(ai_daily.get("last_text_readable")) if "last_text_readable" in ai_daily else bool(ai_digest_first_item.get("article_readable") and ai_digest_first_item.get("article_text")),
                "last_text_chars": ai_text_chars,
                "last_video_subtitle_readable": bool(ai_daily.get("last_video_subtitle_readable")) if "last_video_subtitle_readable" in ai_daily else bool(ai_digest_first_item.get("video_subtitle_readable") and ai_digest_first_item.get("video_subtitle_text")),
                "last_video_subtitle_chars": ai_subtitle_chars,
                "last_video_subtitle_status": self._single_line(ai_daily.get("last_video_subtitle_status") or ai_digest_first_item.get("video_subtitle_status"), 40),
                "last_read_basis": self._single_line(ai_daily.get("last_read_basis"), 40),
                "sources": [
                    {
                        "key": self._single_line(item.get("key"), 80),
                        "name": self._single_line(item.get("name"), 40),
                        "author_name": self._single_line(item.get("author_name"), 60),
                        "mid": self._single_line(item.get("mid"), 40),
                        "schedule": self._single_line(item.get("schedule"), 10),
                    }
                    for item in (ai_daily.get("sources") if isinstance(ai_daily.get("sources"), list) else [])
                    if isinstance(item, dict)
                ],
                "source_states": {
                    self._single_line(key, 80): {
                        "name": self._single_line(value.get("name"), 40),
                        "author_name": self._single_line(value.get("author_name"), 60),
                        "mid": self._single_line(value.get("mid"), 40),
                        "schedule": self._single_line(value.get("schedule"), 10),
                        "status": self._single_line(value.get("status"), 80),
                        "last_checked_at": self.plugin._format_timestamp_elapsed(value.get("last_checked_at", 0)),
                        "last_success_date": self._single_line(value.get("last_success_date"), 20),
                        "last_video_title": self._single_line(value.get("last_video_title"), 120),
                    }
                    for key, value in (ai_daily.get("source_states") if isinstance(ai_daily.get("source_states"), dict) else {}).items()
                    if isinstance(value, dict)
                },
                "topic": self._single_line(ai_digest.get("topic"), 60),
                "headline": self._single_line(ai_digest.get("headline"), 120),
            },
            "last_digest": {
                "topic": self._single_line(digest.get("topic"), 60),
                "headline": self._single_line(digest.get("headline"), 120),
                "source": self._single_line(digest.get("selected_source"), 40),
                "impression": self._sanitize_news_text(
                    digest.get("impression"),
                    180,
                    fallback="这条新闻的正文解析异常，建议稍后重新阅读。",
                ),
                "link": self._single_line(digest.get("selected_link"), 400),
            },
            "latest_items": [
                {
                    "source": self._single_line(item.get("source"), 40),
                    "title": self._single_line(item.get("title"), 120),
                    "summary": self._sanitize_news_text(
                        item.get("summary"),
                        160,
                        fallback="这条新闻摘要暂时解析异常，建议打开原文查看。",
                    ),
                    "link": self._single_line(item.get("link"), 400),
                }
                for item in latest_items[:8]
                if isinstance(item, dict)
            ],
        }

    def _web_exploration_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("web_exploration") if isinstance(data.get("web_exploration"), dict) else {}
        digest = state.get("last_digest") if isinstance(state.get("last_digest"), dict) else {}
        notes = state.get("notes") if isinstance(state.get("notes"), list) else []
        history = [
            item
            for item in self._browsing_history_entries(data)
            if item.get("source") != "news"
        ]
        custom_available = bool(getattr(self.plugin, "_custom_web_exploration_search_configured", lambda: False)())
        try:
            astrbot_available = bool(getattr(self.plugin, "_astrbot_any_web_search_available", lambda: False)())
        except Exception:
            astrbot_available = False
        available = bool(custom_available or astrbot_available)
        search_backend = "custom" if custom_available else ("astrbot" if astrbot_available else "none")
        return {
            "enabled": bool(getattr(self.plugin, "enable_web_exploration", False)),
            "boredom_search_enabled": bool(getattr(self.plugin, "enable_web_exploration_boredom_search", False)),
            "available": available,
            "search_backend": search_backend,
            "custom_search_enabled": custom_available,
            "astrbot_search_available": astrbot_available,
            "last_explore_at": self.plugin._format_timestamp_elapsed(state.get("last_explore_at", 0)),
            "last_status": self._single_line(state.get("last_status"), 80),
            "last_query": {
                "query": self._single_line((state.get("last_query") or {}).get("query") if isinstance(state.get("last_query"), dict) else "", 80),
                "reason": self._single_line((state.get("last_query") or {}).get("reason") if isinstance(state.get("last_query"), dict) else "", 120),
                "topic": self._single_line((state.get("last_query") or {}).get("topic") if isinstance(state.get("last_query"), dict) else "", 20),
            },
            "last_digest": {
                "topic": self._single_line(digest.get("topic"), 80),
                "note": self._single_line(digest.get("note"), 220),
                "source_title": self._single_line(digest.get("source_title"), 120),
                "source_url": self._single_line(digest.get("source_url"), 400),
            },
            "note_count": len(notes),
            "history_count": len(history),
            "history": history,
            "recent_notes": [
                {
                    "topic": self._single_line(item.get("topic"), 80),
                    "note": self._single_line(item.get("note"), 180),
                    "query": self._single_line(item.get("query"), 80),
                    "created_at": self.plugin._format_timestamp_elapsed(item.get("created_ts", 0)),
                }
                for item in notes[-8:]
                if isinstance(item, dict)
            ],
        }

    def _browsing_history_entries(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        news_state = data.get("news_integration") if isinstance(data.get("news_integration"), dict) else {}
        news_digest = news_state.get("last_digest") if isinstance(news_state.get("last_digest"), dict) else {}
        news_digests = news_state.get("digests") if isinstance(news_state.get("digests"), list) else []
        news_items = [item for item in news_digests if isinstance(item, dict)]
        if news_digest and not any(
            self._single_line(item.get("selected_key"), 32) == self._single_line(news_digest.get("selected_key"), 32)
            and self._float(item.get("created_ts")) == self._float(news_digest.get("created_ts"))
            for item in news_items
        ):
            news_items.append(news_digest)
        for news_digest in news_items:
            headline = self._single_line(news_digest.get("headline") or news_digest.get("topic"), 120)
            impression = self._single_line(news_digest.get("impression"), 1000)
            selected_source = self._single_line(news_digest.get("selected_source"), 40)
            selected_link = self._single_line(news_digest.get("selected_link"), 400)
            created_ts = self._float(news_digest.get("created_ts"))
            entries.append(
                {
                    "_ts": created_ts,
                    "source": "news",
                    "source_label": "新闻阅读",
                    "date": self.plugin._format_timestamp_elapsed(created_ts) or "今日新闻",
                    "generated_at": self.plugin._format_timestamp_elapsed(created_ts),
                    "title": headline or "新闻阅读",
                    "query": "",
                    "intro": impression or "这次新闻阅读没有留下明显印象。",
                    "content": "\n\n".join(
                        part
                        for part in (
                            f"新闻见闻：{headline}" if headline else "",
                            impression,
                            f"来源：{selected_source}" if selected_source else "",
                            f"链接：{selected_link}" if selected_link else "",
                        )
                        if part
                    ) or "这次新闻阅读没有留下正文。",
                    "source_title": selected_source,
                    "source_url": selected_link,
                    "tags": ["新闻阅读"],
                }
            )
        web_state = data.get("web_exploration") if isinstance(data.get("web_exploration"), dict) else {}
        web_notes = web_state.get("notes") if isinstance(web_state.get("notes"), list) else []
        web_items = [note for note in web_notes if isinstance(note, dict)]
        last_digest = web_state.get("last_digest") if isinstance(web_state.get("last_digest"), dict) else {}
        if last_digest:
            last_key = "|".join(
                self._single_line(last_digest.get(key), 120)
                for key in ("query", "topic", "created_ts")
            )
            if not any(
                "|".join(
                    self._single_line(item.get(key), 120)
                    for key in ("query", "topic", "created_ts")
                ) == last_key
                for item in web_items
            ):
                web_items.append(last_digest)
        for item in web_items:
            topic = self._single_line(item.get("topic"), 100)
            query = self._single_line(item.get("query"), 100)
            note = self._single_line(
                item.get("note")
                or item.get("summary")
                or item.get("impression")
                or item.get("content"),
                1000,
            )
            source_title = self._single_line(item.get("source_title"), 120)
            source_url = self._single_line(item.get("source_url"), 400)
            created_ts = self._float(item.get("created_ts"))
            result_lines = []
            raw_results = item.get("results") if isinstance(item.get("results"), list) else []
            for result in raw_results[:4]:
                if not isinstance(result, dict):
                    continue
                title = self._single_line(result.get("title"), 100)
                snippet = self._single_line(result.get("snippet"), 180)
                if title and snippet:
                    result_lines.append(f"{title}：{snippet}")
                elif title:
                    result_lines.append(title)
                elif snippet:
                    result_lines.append(snippet)
            result_excerpt = self._single_line("；".join(result_lines), 1000)
            if not note:
                note = result_excerpt
            entries.append(
                {
                    "_ts": created_ts,
                    "source": self._single_line(item.get("source"), 40) or "web_exploration",
                    "source_label": self._single_line(item.get("source_label"), 40) or "主动搜索",
                    "date": self.plugin._format_timestamp_elapsed(created_ts) or "某次搜索",
                    "generated_at": self.plugin._format_timestamp_elapsed(created_ts),
                    "title": topic or query or "主动搜索",
                    "query": query,
                    "intro": note or "这次搜索没有留下明显印象。",
                    "content": "\n\n".join(
                        part
                        for part in (
                            f"搜索词：{query}" if query else "",
                            f"搜索动机：{self._single_line(item.get('reason'), 160)}" if self._single_line(item.get("reason"), 160) else "",
                            f"笔记：{note}" if note else "",
                            f"结果摘录：{result_excerpt}" if result_excerpt and result_excerpt != note else "",
                            f"主要来源：{source_title}" if source_title else "",
                            f"链接：{source_url}" if source_url else "",
                        )
                        if part
                    ) or "这次主动搜索没有留下正文。",
                    "source_title": source_title,
                    "source_url": source_url,
                    "tags": ["主动搜索"],
                }
            )
        entries.sort(key=lambda item: self._float(item.get("_ts")))
        for item in entries:
            item.pop("_ts", None)
        return entries

    def _qzone_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("qzone_integration") if isinstance(data.get("qzone_integration"), dict) else {}
        available = bool(
            callable(getattr(self.plugin, "_qzone_get_cookies", None))
            and callable(getattr(self.plugin, "_qzone_query_feeds", None))
        )
        enabled = bool(available and getattr(self.plugin, "enable_qzone_integration", False))
        return {
            "enabled": enabled,
            "life_publish_enabled": bool(enabled and getattr(self.plugin, "enable_qzone_life_publish", False)),
            "comment_inbox_enabled": bool(enabled and getattr(self.plugin, "enable_qzone_comment_inbox", False)),
            "emotional_vent_enabled": bool(
                enabled
                and getattr(self.plugin, "enable_emotion_simulation", False)
                and getattr(self.plugin, "enable_qzone_emotional_vent_publish", False)
            ),
            "available": available,
            "last_life_publish_at": self.plugin._format_timestamp_elapsed(state.get("last_life_publish_at", 0)),
            "last_status": state.get("last_life_publish_status", ""),
            "last_text": state.get("last_life_publish_text", ""),
            "generated_image_enabled": bool(enabled and getattr(self.plugin, "enable_qzone_generated_image_publish", False)),
            "generated_image_probability": self._float(getattr(self.plugin, "qzone_generated_image_probability", 0)),
            "last_life_publish_images": self._int(state.get("last_life_publish_images")),
            "last_life_publish_generated_image_status": state.get("last_life_publish_generated_image_status", ""),
            "last_life_publish_generated_image_note": state.get("last_life_publish_generated_image_note", ""),
            "last_life_publish_generated_image_backend": state.get("last_life_publish_generated_image_backend", ""),
            "last_life_publish_generated_image_caption": state.get("last_life_publish_generated_image_caption", ""),
            "last_life_publish_generated_image_reference": state.get("last_life_publish_generated_image_reference", ""),
            "last_life_publish_generated_image_reference_exists": bool(state.get("last_life_publish_generated_image_reference_exists", False)),
            "last_life_publish_generated_image_anchor": state.get("last_life_publish_generated_image_anchor", ""),
            "last_life_publish_generated_image_composition": state.get("last_life_publish_generated_image_composition", ""),
            "last_manual_publish_generated_image_status": state.get("last_manual_publish_generated_image_status", ""),
            "last_manual_publish_generated_image_note": state.get("last_manual_publish_generated_image_note", ""),
            "last_manual_publish_generated_image_backend": state.get("last_manual_publish_generated_image_backend", ""),
            "last_manual_publish_generated_image_caption": state.get("last_manual_publish_generated_image_caption", ""),
            "last_manual_publish_generated_image_reference": state.get("last_manual_publish_generated_image_reference", ""),
            "last_manual_publish_generated_image_reference_exists": bool(state.get("last_manual_publish_generated_image_reference_exists", False)),
            "last_manual_publish_generated_image_anchor": state.get("last_manual_publish_generated_image_anchor", ""),
            "last_manual_publish_generated_image_composition": state.get("last_manual_publish_generated_image_composition", ""),
            "last_emotional_vent_at": self.plugin._format_timestamp_elapsed(state.get("last_emotional_vent_at", 0)),
            "last_emotional_vent_status": state.get("last_emotional_vent_status", ""),
            "last_emotional_vent_text": state.get("last_emotional_vent_text", ""),
            "last_emotional_vent_images": self._int(state.get("last_emotional_vent_images")),
            "last_emotional_vent_generated_image_status": state.get("last_emotional_vent_generated_image_status", ""),
            "last_emotional_vent_generated_image_note": state.get("last_emotional_vent_generated_image_note", ""),
            "last_emotional_vent_generated_image_backend": state.get("last_emotional_vent_generated_image_backend", ""),
            "last_emotional_vent_generated_image_caption": state.get("last_emotional_vent_generated_image_caption", ""),
            "last_emotional_vent_generated_image_reference": state.get("last_emotional_vent_generated_image_reference", ""),
            "last_emotional_vent_generated_image_reference_exists": bool(state.get("last_emotional_vent_generated_image_reference_exists", False)),
            "last_emotional_vent_generated_image_anchor": state.get("last_emotional_vent_generated_image_anchor", ""),
            "last_emotional_vent_generated_image_composition": state.get("last_emotional_vent_generated_image_composition", ""),
            "last_comment_inbox_checked_at": self.plugin._format_timestamp_elapsed(state.get("last_comment_inbox_checked_at", 0)),
            "last_comment_inbox_status": state.get("last_comment_inbox_status", ""),
            "last_comment_inbox_reply_text": state.get("last_comment_inbox_reply_text", ""),
            "auth_block_until": self.plugin._format_timestamp_elapsed(state.get("auth_block_until", 0)),
            "auth_failure_reason": state.get("last_auth_failure_reason", ""),
            "auth_failure_count": self._int(state.get("auth_failure_count")),
            "auth_status": state.get("last_auth_status", ""),
            "cookie_fetch_status": state.get("last_cookie_fetch_status", ""),
            "cookie_fetch_reason": state.get("last_cookie_fetch_reason", ""),
            "cookie_fetch_has_uin": bool(state.get("last_cookie_fetch_has_uin", False)),
            "cookie_fetch_has_skey": bool(state.get("last_cookie_fetch_has_skey", False)),
            "cookie_fetch_has_p_skey": bool(state.get("last_cookie_fetch_has_p_skey", False)),
            "cookie_fetch_uin": state.get("last_cookie_fetch_uin", ""),
            "cookie_fetch_at": self.plugin._format_timestamp_elapsed(state.get("last_cookie_fetch_at", 0)),
        }

    def _jm_cosmos_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        state = data.get("jm_cosmos_integration") if isinstance(data.get("jm_cosmos_integration"), dict) else {}
        try:
            available = bool(getattr(self.plugin, "_jm_cosmos_available", lambda: False)())
        except Exception:
            available = False
        album = state.get("last_album") if isinstance(state.get("last_album"), dict) else {}
        return {
            "enabled": bool(available and getattr(self.plugin, "enable_jm_cosmos_integration", False)),
            "boredom_read_enabled": bool(available and getattr(self.plugin, "enable_jm_cosmos_boredom_read", False)),
            "ask_recommendation_enabled": bool(available and getattr(self.plugin, "enable_private_reading_ask_recommendation", False)),
            "available": available,
            "last_read_at": self.plugin._format_timestamp_elapsed(state.get("last_read_at", 0)),
            "last_status": state.get("last_status", ""),
            "last_keyword": state.get("last_keyword", ""),
            "last_album": {
                "id": self._single_line(album.get("id"), 32),
                "title": self._single_line(album.get("title"), 100),
                "impression": self._single_line(album.get("impression"), 160),
                "rating": self._int(album.get("rating")),
                "user_rating": self._int(album.get("user_rating")),
            },
        }

    def _bookshelf_image_url(
        self,
        album_id: str,
        *,
        data_root: Path,
        page_index: int = 0,
        cover: bool = False,
        path_value: Any = "",
        access_token: str = "",
    ) -> str:
        if not album_id or (page_index < 1 and not cover):
            return ""
        url = f"{PAGE_API_PREFIX}/bookshelf/image?album_id={quote(str(album_id), safe='')}"
        if cover:
            url += "&cover=1"
        elif page_index > 0:
            url += f"&page={page_index}"
        if access_token:
            url += f"&access_token={quote(str(access_token), safe='')}"
        raw_path = self._single_line(path_value, 500)
        if raw_path:
            try:
                path = Path(raw_path).resolve()
                path.relative_to(data_root)
                if path.exists() and path.is_file():
                    stat = path.stat()
                    url += f"&v={int(stat.st_mtime)}-{stat.st_size}"
            except Exception:
                pass
        return url

    def _bookshelf_cover_url(
        self,
        album_id: str,
        item: dict[str, Any],
        page_items: list[dict[str, Any]],
        data_root: Path,
        *,
        access_token: str = "",
    ) -> str:
        cover_path = self._single_line(item.get("cover_path"), 500)
        if cover_path:
            return self._bookshelf_image_url(
                album_id,
                data_root=data_root,
                cover=True,
                path_value=cover_path,
                access_token=access_token,
            )
        first_page = page_items[0] if page_items else {}
        if isinstance(first_page, dict):
            return self._single_line(first_page.get("src"), 500)
        return ""

    async def _bookshelf_summary(self, data: dict[str, Any], *, unlocked: bool, access_token: str = "") -> dict[str, Any]:
        projects = data.get("creative_projects") if isinstance(data.get("creative_projects"), list) else []
        diaries = data.get("bot_diaries") if isinstance(data.get("bot_diaries"), list) else []
        shelf_items = data.get("bookshelf_items") if isinstance(data.get("bookshelf_items"), list) else []
        jm_items = [item for item in shelf_items if isinstance(item, dict) and item.get("type") == "jm_album"]
        jm_state = data.get("jm_cosmos_integration") if isinstance(data.get("jm_cosmos_integration"), dict) else {}
        secret_state = data.get("bookshelf_secret") if isinstance(data.get("bookshelf_secret"), dict) else {}
        reason_sanitizer = getattr(self.plugin, "_sanitize_bookshelf_password_reason", None)
        password_hint = ""
        if callable(reason_sanitizer):
            try:
                password_hint = reason_sanitizer(secret_state.get("reason"))
            except Exception:
                password_hint = ""
        else:
            password_hint = self._single_line(secret_state.get("reason"), 80)
        if not password_hint:
            password_hint = "提示会在通过“陪伴 输出夹层密码”生成后显示。"
        last_album = jm_state.get("last_album") if isinstance(jm_state.get("last_album"), dict) else {}
        if last_album and not any(str(item.get("album_id") or item.get("id") or "") == str(last_album.get("id") or "") for item in jm_items):
            jm_items.append(
                {
                    "type": "jm_album",
                    "title": last_album.get("title"),
                    "album_id": last_album.get("id"),
                    "description": last_album.get("description") or last_album.get("intro") or last_album.get("summary"),
                    "keyword": last_album.get("keyword"),
                    "author": last_album.get("author"),
                    "tags": last_album.get("tags"),
                    "photo_count": last_album.get("photo_count"),
                    "impression": last_album.get("impression"),
                    "reading_impression": last_album.get("reading_impression") or last_album.get("impression"),
                    "vision": last_album.get("vision"),
                    "rating": last_album.get("rating"),
                    "rating_reason": last_album.get("rating_reason"),
                    "user_rating": last_album.get("user_rating"),
                    "user_rating_reason": last_album.get("user_rating_reason"),
                    "user_rated_ts": last_album.get("user_rated_ts"),
                    "preference_tags": last_album.get("preference_tags") if isinstance(last_album.get("preference_tags"), list) else [],
                    "user_liked_tags": last_album.get("user_liked_tags") if isinstance(last_album.get("user_liked_tags"), list) else [],
                    "user_disliked_tags": last_album.get("user_disliked_tags") if isinstance(last_album.get("user_disliked_tags"), list) else [],
                    "user_tags_updated_ts": last_album.get("user_tags_updated_ts"),
                    "page_comments": last_album.get("page_comments") if isinstance(last_album.get("page_comments"), list) else [],
                    "image_count": last_album.get("image_count"),
                    "pages": last_album.get("pages") if isinstance(last_album.get("pages"), list) else [],
                    "sampled_pages": last_album.get("sampled_pages") if isinstance(last_album.get("sampled_pages"), list) else [],
                    "created_ts": last_album.get("created_ts"),
                }
            )
        data_root = Path(str(getattr(self.plugin, "data_dir", ""))).resolve()
        covers_root = data_root / "jm_cosmos_covers"
        if unlocked:
            pages_root = data_root / "bookshelf_pages"
            known_jm_ids = {
                self._single_line(item.get("album_id") or item.get("id"), 80)
                for item in jm_items
                if isinstance(item, dict) and self._single_line(item.get("album_id") or item.get("id"), 80)
            }
            preference_history = []
            profile = jm_state.get("preference_profile") if isinstance(jm_state.get("preference_profile"), dict) else {}
            if isinstance(profile.get("history"), list):
                preference_history = [item for item in profile.get("history", []) if isinstance(item, dict)]
            history_by_album: dict[str, dict[str, Any]] = {}
            for item in preference_history:
                album_id = self._single_line(item.get("album_id") or item.get("id"), 80)
                if album_id:
                    history_by_album[album_id] = {**history_by_album.get(album_id, {}), **item}
            try:
                orphan_dirs = [
                    path
                    for path in pages_root.iterdir()
                    if path.is_dir() and self._single_line(path.name, 80) and self._single_line(path.name, 80) not in known_jm_ids
                ] if pages_root.exists() else []
            except Exception:
                orphan_dirs = []
            for path in orphan_dirs:
                album_id = self._single_line(path.name, 80)
                page_files = sorted(
                    file
                    for file in path.iterdir()
                    if file.is_file() and file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                )
                if not album_id or not page_files:
                    continue
                meta = history_by_album.get(album_id, {})
                created_ts = self._float(meta.get("created_ts")) or max((file.stat().st_mtime for file in page_files), default=0.0)
                cover_path = covers_root / f"{album_id}.jpg"
                jm_items.append(
                    {
                        "type": "jm_album",
                        "album_id": album_id,
                        "title": meta.get("title") or f"私密阅读 {album_id}",
                        "description": meta.get("reason") or "",
                        "tags": meta.get("terms") if isinstance(meta.get("terms"), list) else [],
                        "rating": meta.get("bot_rating") or meta.get("rating"),
                        "user_rating": meta.get("user_rating"),
                        "rating_reason": meta.get("reason") or "",
                        "user_rating_reason": meta.get("reason") or "",
                        "cover_path": str(cover_path) if cover_path.exists() else "",
                        "pages": [
                            {
                                "index": index + 1,
                                "path": str(file),
                                "name": file.name,
                            }
                            for index, file in enumerate(page_files)
                        ],
                        "image_count": len(page_files),
                        "created_ts": created_ts,
                        "source": "bookshelf_orphan_recovered",
                        "locked": True,
                    }
                )
        public_books = []
        browsing_entries = self._browsing_history_entries(data)
        for item in [project for project in projects if isinstance(project, dict)][-12:]:
            chunks = item.get("draft_chunks") if isinstance(item.get("draft_chunks"), list) else []
            full_text = "\n\n".join(
                self._single_line(chunk.get("text"), 2000)
                for chunk in chunks
                if isinstance(chunk, dict) and self._single_line(chunk.get("text"), 2000)
            )
            chunk_entries = [
                {
                    "index": index + 1,
                    "text": self._single_line(chunk.get("text"), 2000),
                    "created": self.plugin._format_timestamp_elapsed(chunk.get("created_ts", 0) or chunk.get("created_at", 0)),
                }
                for index, chunk in enumerate(chunks)
                if isinstance(chunk, dict) and self._single_line(chunk.get("text"), 2000)
            ]
            status = self._single_line(item.get("status"), 24)
            progress = f"{self._int(item.get('current_chars'))}/{self._int(item.get('target_chars')) or '-'} 字"
            public_books.append(
                {
                    "id": self._single_line(item.get("id"), 32) or f"creative-{len(public_books)}",
                    "kind": "creative",
                    "category": self._single_line(item.get("work_type"), 30) or "创作",
                    "work_type": self._single_line(item.get("work_type"), 30) or "短篇小说",
                    "title": self._single_line(item.get("title"), 60) or "未定标题",
                    "intro": self._single_line(item.get("premise"), 240) or "这本书还没整理出简介。",
                    "status": status,
                    "tone": self._single_line(item.get("tone"), 40),
                    "point_of_view": self._single_line(item.get("point_of_view"), 40) or "第三人称有限视角",
                    "progress": progress,
                    "content": full_text or self._single_line(chunks[-1].get("text") if chunks else "", 2000) or "这本书还没有正文。",
                    "chunks": chunk_entries,
                    "outline_count": len(item.get("outline") or []) if isinstance(item.get("outline"), list) else 0,
                    "character_count": len(item.get("characters") or []) if isinstance(item.get("characters"), list) else 0,
                    "review_count": len(item.get("quality_reviews") or []) if isinstance(item.get("quality_reviews"), list) else 0,
                    "manual_edit_count": len(item.get("manual_edits") or []) if isinstance(item.get("manual_edits"), list) else 0,
                    "has_story_bible": bool(item.get("story_bible")) if isinstance(item.get("story_bible"), dict) else False,
                    "last_manual_edit_summary": self._single_line(item.get("last_manual_edit_summary"), 120),
                    "created": self.plugin._format_timestamp_elapsed(item.get("created_at", 0)),
                    "cover_src": self._creative_project_cover_url(item),
                    "cover_status": self._single_line(item.get("cover_generation_status"), 24),
                }
            )
        if browsing_entries:
            latest = browsing_entries[-1]
            public_books.append(
                {
                    "id": "browsing-history-main",
                    "kind": "browsing",
                    "category": "浏览记录",
                    "title": "浏览记录",
                    "intro": f"这里收着 {len(browsing_entries)} 条新闻阅读和主动搜索记录。打开后可以选择记录。",
                    "content": self._single_line(latest.get("content"), 2000) or self._single_line(latest.get("intro"), 1200),
                    "entries": browsing_entries,
                    "created": self._single_line(latest.get("generated_at") or latest.get("date"), 32),
                    "progress": f"{len(browsing_entries)} 条记录",
                    "tags": ["新闻阅读", "主动搜索"],
                }
            )
        locked_count = (1 if diaries else 0) + len(jm_items)
        secret_books: list[dict[str, Any]] = []
        if unlocked:
            diary_entries = []
            for item in [entry for entry in diaries if isinstance(entry, dict)][-60:]:
                body = self.plugin._polish_diary_text(item.get("body"), field="body")
                summary = self.plugin._polish_diary_text(item.get("summary"), field="summary")
                share_seed = self.plugin._polish_diary_text(item.get("share_seed"), field="share")
                content = body or "\n\n".join(part for part in (summary, share_seed) if part)
                diary_entries.append(
                    {
                        "date": self._single_line(item.get("date"), 24) or "某天",
                        "generated_at": self._single_line(item.get("generated_at"), 32),
                        "title": f"{self._single_line(item.get('date'), 24) or '某天'}",
                        "intro": summary or "这一天没有留下摘要。",
                        "content": content or "这一天的日记暂时没有写出正文。",
                        "tags": [self._single_line(tag, 24) for tag in item.get("tags", [])[:8] if self._single_line(tag, 24)]
                        if isinstance(item.get("tags"), list)
                        else [],
                    }
                )
            if diary_entries:
                secret_books.append(
                    {
                        "id": "diary-main",
                        "kind": "diary",
                        "category": "日记",
                        "title": "日记本",
                        "intro": f"这里收着 {len(diary_entries)} 天的日记。打开后可以选择日期。",
                        "content": diary_entries[-1].get("content") or "这本日记暂时没有可读内容。",
                        "entries": diary_entries,
                        "created": diary_entries[-1].get("generated_at", ""),
                    }
            )
            recent_jm_items = sorted(
                jm_items,
                key=lambda item: self._float(item.get("created_ts") or item.get("created_at") or item.get("ts")),
                reverse=True,
            )[:18]
            for item in recent_jm_items:
                album_id = self._single_line(item.get("album_id") or item.get("id"), 32)
                pages = item.get("pages") if isinstance(item.get("pages"), list) else []
                reading_impression = self._single_line(item.get("reading_impression") or item.get("impression"), 1000)
                vision_impression = self._single_line(item.get("vision"), 1000)
                show_vision_impression = bool(
                    vision_impression
                    and (
                        not reading_impression
                        or _text_similarity(vision_impression, reading_impression) < 0.72
                    )
                )
                bot_rating = self._int(item.get("rating"))
                user_rating = self._int(item.get("user_rating"))
                rating_reason = self._single_line(item.get("rating_reason"), 180)
                user_rating_reason = self._single_line(item.get("user_rating_reason"), 180)
                album_description = self._single_line(
                    item.get("description")
                    or item.get("intro")
                    or item.get("summary")
                    or item.get("desc"),
                    600,
                )
                if not album_description:
                    detail_parts = []
                    author_text = self._single_line(item.get("author"), 40)
                    photo_count = self._int(item.get("photo_count")) or self._int(item.get("image_count"))
                    tag_text = "、".join(
                        self._single_line(tag, 24)
                        for tag in (item.get("tags") if isinstance(item.get("tags"), list) else [])[:6]
                        if self._single_line(tag, 24)
                    )
                    if author_text:
                        detail_parts.append(f"作者：{author_text}")
                    if photo_count:
                        detail_parts.append(f"页数：{photo_count}")
                    if tag_text:
                        detail_parts.append(f"标签：{tag_text}")
                    album_description = "；".join(detail_parts) or "这条阅读记录暂时没有整理出明确简介。"
                page_comment_map: dict[int, list[str]] = {}
                raw_comments = self._merge_bookshelf_page_comments(
                    item.get("page_comments") if isinstance(item.get("page_comments"), list) else [],
                    item.get("page_comments_previous") if isinstance(item.get("page_comments_previous"), list) else [],
                    limit=32,
                )
                for comment_item in raw_comments:
                    if not isinstance(comment_item, dict):
                        continue
                    page_no = self._int(comment_item.get("page"))
                    comment_text = self._single_line(comment_item.get("comment"), 100)
                    if page_no > 0 and comment_text:
                        page_comments = page_comment_map.setdefault(page_no, [])
                        if comment_text not in page_comments:
                            page_comments.append(comment_text)
                reading_progress_page = max(0, self._int(item.get("reading_progress_page")))
                reading_progress_total = max(0, self._int(item.get("reading_progress_total"))) or len(pages)
                reading_progress_updated_at = self._float(item.get("reading_progress_updated_at"))
                reading_bookmark = self._single_line(item.get("reading_bookmark"), 120)
                reading_completed_at = self._float(item.get("reading_completed_at"))
                page_items = []
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    index = self._int(page.get("index"))
                    if index <= 0:
                        continue
                    page_src = self._bookshelf_image_url(
                        album_id,
                        data_root=data_root,
                        page_index=index,
                        path_value=page.get("path"),
                        access_token=access_token,
                    )
                    page_items.append(
                        {
                            "index": index,
                            "src": page_src,
                            "comment": "\n".join(page_comment_map.get(index, [])),
                        }
                    )
                cover_src = ""
                if album_id:
                    cover_src = self._bookshelf_cover_url(album_id, item, page_items, data_root, access_token=access_token)
                secret_books.append(
                    {
                        "id": f"jm-{album_id or len(secret_books)}",
                        "kind": "jm_album",
                        "category": "私密阅读",
                        "album_id": album_id,
                        "title": self._single_line(item.get("title"), 100) or "未命名阅读记录",
                        "intro": self._single_line(album_description, 600),
                        "reading_impression": reading_impression or vision_impression,
                        "rating": bot_rating,
                        "rating_reason": rating_reason,
                        "user_rating": user_rating,
                        "user_rating_reason": user_rating_reason,
                        "user_rated": bool(user_rating),
                        "author": self._single_line(item.get("author"), 40),
                        "progress": (
                            "已读完"
                            if reading_completed_at
                            else f"读至 {min(max(1, reading_progress_page), max(1, reading_progress_total))}/{max(1, reading_progress_total)} 页"
                            if reading_progress_page > 0
                            else f"{len(page_items) or self._int(item.get('image_count')) or self._int(item.get('photo_count'))} 页"
                        ),
                        "created": self.plugin._format_timestamp_elapsed(item.get("created_ts", 0)),
                        "content": "\n\n".join(
                            part
                            for part in (
                                f"读后感：{reading_impression}" if reading_impression else "",
                                f"Bot 评分：{bot_rating}/10" if bot_rating else "",
                                f"用户评分：{user_rating}/10" if user_rating else "",
                                f"评分理由：{user_rating_reason or rating_reason}" if (user_rating_reason or rating_reason) else "",
                                f"画面记录：{vision_impression}" if show_vision_impression else "",
                                f"关键词：{self._single_line(item.get('keyword'), 80)}" if self._single_line(item.get("keyword"), 80) else "",
                            )
                            if part
                        ) or "这本只留下了一点很含糊的阅读印象。",
                        "tags": [self._single_line(tag, 24) for tag in item.get("tags", [])[:8] if self._single_line(tag, 24)]
                        if isinstance(item.get("tags"), list)
                        else [],
                        "preference_tags": [
                            self._single_line(tag, 24)
                            for tag in (item.get("preference_tags") if isinstance(item.get("preference_tags"), list) else [])[:8]
                            if self._single_line(tag, 24)
                        ],
                        "user_liked_tags": [
                            self._single_line(tag, 24)
                            for tag in (item.get("user_liked_tags") if isinstance(item.get("user_liked_tags"), list) else [])[:8]
                            if self._single_line(tag, 24)
                        ],
                        "user_disliked_tags": [
                            self._single_line(tag, 24)
                            for tag in (item.get("user_disliked_tags") if isinstance(item.get("user_disliked_tags"), list) else [])[:8]
                            if self._single_line(tag, 24)
                        ],
                        "user_tags_updated": bool(item.get("user_tags_updated_ts")),
                        "cover_src": cover_src,
                        "pages": page_items,
                        "reading_progress_page": reading_progress_page,
                        "reading_progress_total": reading_progress_total,
                        "reading_progress_updated_at": reading_progress_updated_at,
                        "reading_bookmark": reading_bookmark,
                        "reading_completed_at": reading_completed_at,
                        "page_comment_count": sum(len(comments) for comments in page_comment_map.values()),
                        "page_comments": [
                            {"page": page, "comment": comment}
                            for page, comments in sorted(page_comment_map.items())
                            for comment in comments
                        ],
                    }
                )
        return {
            "unlocked": unlocked,
            "access_token": access_token if unlocked and self._bookshelf_access_token_valid(access_token) else "",
            "access_expires_in": int(max(0, self._bookshelf_access_tokens().get(access_token, 0) - time.time()))
            if unlocked and access_token
            else 0,
            "public_count": len(public_books),
            "secret_count": locked_count,
            "diary_count": 1 if diaries else 0,
            "jm_album_count": len(jm_items),
            "reading_now_count": sum(1 for item in jm_items if self._int(item.get("reading_progress_page")) > 0 and not self._float(item.get("reading_completed_at"))),
            "memo_notes": self._memo_notes_payload(data),
            "password_hint": password_hint,
            "public_books": public_books,
            "secret_books": secret_books,
        }

    def _proactive_template_text(self, value: Any, *, target_name: Any = "", limit: int = 220) -> str:
        text = self._single_line(value, limit)
        if not text:
            return ""
        name = self._single_line(target_name, 40) or "对方"
        return self._single_line(text.replace("{name}", name).replace("{{name}}", name), limit)

    def _proactive_reason_label(self, reason: Any, *, target_name: Any = "") -> str:
        key = self._single_line(reason, 40)
        if not key:
            return "未记录原因"
        extra = {
            "bookshelf_reading_share": "跟你提起刚翻到的漫画本子",
            "bookshelf_recommendation_request": "想问你要不要推荐阅读",
            "web_exploration_share": "分享主动搜索后的发现",
            "news_share": "分享刚读到的新闻",
            "environment_change": "注意到外面的环境突然变了",
            "personal_goal_progress": "自己的一个长期目标有了新进展",
            "timer": "聊天中形成的临时约定",
            "troubleshooting_test": "排障测试触发",
        }
        return self._proactive_template_text(extra.get(key) or _REASON_TEXT.get(key) or key, target_name=target_name, limit=80)

    def _proactive_source_meta(self, source: Any) -> dict[str, str]:
        key = self._single_line(source, 40)
        if not key:
            return {"label": "插件主动", "note": ""}
        meta = {
            "random": {
                "label": "轻微想念",
                "note": "没有明确外部触发，更像安静一阵后轻轻冒出来、想靠近你一下。",
            },
            "daily_greeting": {
                "label": "日常招呼",
                "note": "到了早中晚合适的那个点，顺手来冒个头，不是专门执行问候任务。",
            },
            "pending_followup": {
                "label": "补一句",
                "note": "前面那句还留着一个具体点没落地，所以隔一阵再接一句。",
            },
            "state": {
                "label": "身体小需求",
                "note": "不是汇报状态，而是身体上那点小事挂着，顺手拿来找你说一句。",
            },
            "event": {"label": "生活事件", "note": ""},
            "story": {"label": "日常剧情", "note": ""},
            "habit": {"label": "习惯关心", "note": ""},
            "bilibili": {"label": "B站分享", "note": ""},
            "bookshelf_reading": {"label": "私密阅读", "note": ""},
            "creative_writing": {"label": "创作灵感", "note": ""},
            "group_share": {"label": "群聊见闻", "note": ""},
            "web_exploration": {"label": "主动搜索", "note": ""},
            "news": {"label": "新闻阅读", "note": ""},
            "environment_change": {"label": "环境突变", "note": "实时环境出现明显变化后形成的短时主动。"},
            "meal_care": {"label": "饭点关心", "note": "在合适饭点形成的低压力饮食关心。"},
            "group_ignore_complaint": {
                "label": "群内冒泡关心",
                "note": "对方暂未回复私聊、但刚在群内出现后形成的低压力关心。",
            },
            "jm_cosmos": {"label": "私密阅读", "note": ""},
            "personal_goal": {"label": "个人目标", "note": "非创作型长期目标在真实推进、停滞或完成后形成的主动。"},
            "candidate": {"label": "主动候选", "note": ""},
            "followup": {"label": "补一句", "note": "前面的话还差个具体点，所以顺手再接一句。"},
            "external": {"label": "外部主动能力", "note": ""},
            "timer": {"label": "官方定时计划", "note": ""},
            "proactive": {"label": "插件主动", "note": ""},
            "unknown": {"label": "未记录来源", "note": ""},
        }
        return dict(meta.get(key) or {"label": key, "note": ""})

    def _proactive_source_label(self, source: Any) -> str:
        return self._proactive_source_meta(source).get("label") or "插件主动"

    def _proactive_source_note(self, source: Any) -> str:
        return self._single_line(self._proactive_source_meta(source).get("note"), 120)

    def _proactive_reason_detail(
        self,
        *,
        reason: Any,
        source: Any = "",
        topic: Any = "",
        motive: Any = "",
        note: Any = "",
        target_name: Any = "",
    ) -> str:
        label = self._proactive_reason_label(reason, target_name=target_name)
        parts = [label]
        topic_text = self._proactive_template_text(topic, target_name=target_name, limit=80)
        motive_text = self._proactive_template_text(motive, target_name=target_name, limit=140)
        note_text = self._proactive_template_text(note, target_name=target_name, limit=120)
        source_text = self._proactive_source_label(source)
        if topic_text:
            parts.append(f"话题：{topic_text}")
        if motive_text:
            parts.append(f"动机：{motive_text}")
        if note_text:
            parts.append(f"记录：{note_text}")
        if source_text:
            parts.append(f"来源：{source_text}")
        return self._single_line("；".join(parts), 220)

    def _proactive_candidate_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("proactive_candidate_pool") if isinstance(data.get("proactive_candidate_pool"), list) else []
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        now = time.time()
        buckets: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        user_counts: dict[str, dict[str, Any]] = {}
        total_attempts = 0
        pending_total = 0

        def pending_status(status: Any) -> bool:
            normalized = self._single_line(status, 24).lower()
            return normalized in {"accepted", "deferred", "queued", "pending", "unknown", ""}

        def repeat_limit(status: Any) -> int:
            normalized = self._single_line(status, 24).lower()
            if normalized in {"accepted", "deferred", "queued", "pending", "unknown", ""}:
                return 12
            if normalized == "sent":
                return 8
            return 6

        def normalized_repeat(item: dict[str, Any], status: str) -> int:
            count = max(1, self._int(item.get("repeat_count")))
            limit = repeat_limit(status)
            value = max(1, min(limit, count))
            if count != value:
                item["repeat_count"] = value
                item["repeat_count_capped"] = True
            return value

        def candidate_user_meta(user_id: str, user: Any) -> dict[str, str]:
            if not isinstance(user, dict):
                return {"label": user_id or "未知用户", "role": "unknown", "role_label": "未知"}
            role = self.plugin._private_user_role(user, user_id) if hasattr(self.plugin, "_private_user_role") else ""
            role_labeler = getattr(self.plugin, "_private_user_role_label", None)
            role_label = role_labeler(role) if callable(role_labeler) else ("主要用户" if role == "owner" else "次要用户")
            nickname = self._single_line(user.get("nickname"), 40)
            generic_names = {"用户", "主人", "主要用户", "默认用户"}
            if str(user_id).isdigit():
                label = nickname if nickname and nickname not in generic_names else user_id
            else:
                label = f"临时会话 · {str(user_id)[:8]}"
            return {"label": label or user_id or "未知用户", "role": role or "friend", "role_label": role_label}

        for item in raw[-240:]:
            if not isinstance(item, dict):
                continue
            status = self._single_line(item.get("status"), 24) or "unknown"
            repeat_count = normalized_repeat(item, status)
            note = self._single_line(item.get("note"), 160)
            if status == "blocked" and note in {"朋友关系不接收敏感主动", "次要用户关系不接收敏感主动"}:
                continue
            user_id = self._single_line(item.get("user_id"), 32)
            user = users.get(user_id) if isinstance(users, dict) else None
            reason_raw = self._single_line(item.get("reason"), 40)
            action_raw = self._single_line(item.get("action"), 40)
            if (
                isinstance(user, dict)
                and hasattr(self.plugin, "_friend_can_receive_proactive_reason")
                and not self.plugin._friend_can_receive_proactive_reason(user, reason_raw, action_raw)
            ):
                continue
            if status != "sent" and not bool(
                isinstance(user, dict)
                and getattr(self.plugin, "_user_enabled_for_proactive", lambda uid, profile: bool(profile and profile.get("enabled", True)))(
                    user_id,
                    user,
                )
            ):
                continue
            total_attempts += repeat_count
            if pending_status(status):
                pending_total += repeat_count
            user_meta = candidate_user_meta(user_id, user)
            user_bucket = user_counts.setdefault(
                user_id or "unknown",
                {
                    "user_id": user_id,
                    "label": user_meta["label"],
                    "role": user_meta["role"],
                    "role_label": user_meta["role_label"],
                    "total": 0,
                    "pending_total": 0,
                    "counts": {},
                },
            )
            user_bucket["total"] = self._int(user_bucket.get("total")) + repeat_count
            if pending_status(status):
                user_bucket["pending_total"] = self._int(user_bucket.get("pending_total")) + repeat_count
            bucket_counts = user_bucket.get("counts")
            if not isinstance(bucket_counts, dict):
                bucket_counts = {}
                user_bucket["counts"] = bucket_counts
            bucket_counts[status] = self._int(bucket_counts.get(status)) + repeat_count
            source = self._single_line(item.get("source"), 40) or "unknown"
            display_source = "bookshelf_reading" if source == "jm_cosmos" else source
            counts[status] = counts.get(status, 0) + repeat_count
            source_counts[display_source] = source_counts.get(display_source, 0) + repeat_count
            scheduled = self._float(item.get("scheduled_ts"))
            created = self._float(item.get("created_ts"))
            last_seen = self._float(item.get("last_seen_ts")) or created
            reason = reason_raw
            action = action_raw
            if reason == "jm_cosmos_share":
                reason = "bookshelf_reading_share"
            if reason == "jm_cosmos_recommendation_request":
                reason = "bookshelf_recommendation_request"
            if action == "jm_cosmos_read":
                action = "bookshelf_reading"
            signature = self._single_line(item.get("signature"), 120)
            topic = self._single_line(item.get("topic"), 100)
            motive = self._single_line(item.get("motive"), 180)
            semantic_kind = self._single_line(item.get("semantic_kind"), 40)
            semantic_anchor_type = self._single_line(item.get("semantic_anchor_type"), 40)
            semantic_score = self._int(item.get("semantic_score"))
            semantic_pressure = self._int(item.get("semantic_pressure"))
            semantic_risk = self._int(item.get("semantic_risk"))
            semantic_note = self._single_line(item.get("semantic_note"), 180)
            need_layer = self._single_line(item.get("semantic_need_layer") or item.get("need_layer"), 40)
            need_drive = self._single_line(item.get("semantic_need_drive") or item.get("need_drive"), 80)
            need_note = self._single_line(item.get("semantic_need_note") or item.get("need_note"), 120)
            need_score_bias = item.get("semantic_need_score_bias", item.get("need_score_bias"))
            need_pressure_bias = item.get("semantic_need_pressure_bias", item.get("need_pressure_bias"))
            sanitizer = getattr(self.plugin, "_sanitize_friend_proactive_plan_fields", None)
            if isinstance(user, dict) and callable(sanitizer):
                sanitized = sanitizer(
                    user,
                    reason=reason,
                    action=action,
                    topic=topic,
                    motive=motive,
                )
                reason = self._single_line(sanitized.get("reason"), 40) or reason
                action = self._single_line(sanitized.get("action"), 40) or action
                topic = self._single_line(sanitized.get("topic"), 100)
                motive = self._single_line(sanitized.get("motive"), 180)
            merged = None
            for existing in reversed(buckets):
                if existing.get("status") != status:
                    continue
                if existing.get("user_id") != user_id:
                    continue
                old_signature = str(existing.get("_signature") or "")
                if signature and old_signature:
                    similar = bool(getattr(self.plugin, "_topic_signature_similar", lambda a, b: a == b)(signature, old_signature))
                else:
                    similar = (topic or motive) == (existing.get("topic") or existing.get("motive"))
                if not similar:
                    continue
                if max(last_seen, scheduled, created) - self._float(existing.get("_first_ts")) > 36 * 3600:
                    continue
                merged = existing
                break
            if merged is None:
                buckets.append(
                    {
                        "id": self._single_line(item.get("id"), 20),
                        "user_id": user_id,
                        "user_label": user_meta["label"],
                        "user_role": user_meta["role"],
                        "user_role_label": user_meta["role_label"],
                        "source": display_source,
                        "source_label": self._proactive_source_label(display_source),
                        "source_note": self._proactive_source_note(display_source),
                        "reason": reason,
                        "reason_label": self._proactive_reason_label(reason, target_name=user_meta["label"]),
                        "reason_detail": self._proactive_reason_detail(
                            reason=reason,
                            source=display_source,
                            topic=topic,
                            motive=motive,
                            note=note,
                            target_name=user_meta["label"],
                        ),
                        "action": action,
                        "topic": topic,
                        "motive": motive,
                        "score": self._int(item.get("score")),
                        "semantic_kind": semantic_kind,
                        "semantic_anchor_type": semantic_anchor_type,
                        "semantic_score": semantic_score,
                        "semantic_pressure": semantic_pressure,
                        "semantic_risk": semantic_risk,
                        "semantic_note": semantic_note,
                        "need_layer": need_layer,
                        "need_level": need_layer,
                        "need_drive": need_drive,
                        "need_note": need_note,
                        "need_score_bias": need_score_bias,
                        "need_pressure_bias": need_pressure_bias,
                        "status": status,
                        "note": note,
                        "repeat_count": repeat_count,
                        "created_ts": created,
                        "last_seen_ts": last_seen,
                        "scheduled_ts": scheduled,
                        "is_due": bool(scheduled and scheduled <= now),
                        "_signature": signature,
                        "_first_ts": max(created, scheduled, last_seen),
                    }
                )
                continue
            previous_repeat = self._int(merged.get("repeat_count"))
            merged_repeat_limit = repeat_limit(status)
            merged["repeat_count"] = min(merged_repeat_limit, previous_repeat + repeat_count)
            if previous_repeat + repeat_count > merged_repeat_limit:
                merged["repeat_count_capped"] = True
            merged["last_seen_ts"] = max(self._float(merged.get("last_seen_ts")), last_seen, created)
            merged["scheduled_ts"] = max(self._float(merged.get("scheduled_ts")), scheduled)
            merged["score"] = max(self._int(merged.get("score")), self._int(item.get("score")))
            if semantic_score >= self._int(merged.get("semantic_score")):
                merged["semantic_kind"] = semantic_kind
                merged["semantic_anchor_type"] = semantic_anchor_type
                merged["semantic_score"] = semantic_score
                merged["semantic_pressure"] = semantic_pressure
                merged["semantic_risk"] = semantic_risk
                merged["semantic_note"] = semantic_note
                merged["need_layer"] = need_layer
                merged["need_level"] = need_layer
                merged["need_drive"] = need_drive
                merged["need_note"] = need_note
                merged["need_score_bias"] = need_score_bias
                merged["need_pressure_bias"] = need_pressure_bias
            if topic:
                merged["topic"] = topic
            if motive:
                merged["motive"] = motive
            if note and note != merged.get("note"):
                merged["note"] = "多来源合并"
            merged["is_due"] = bool(merged.get("scheduled_ts") and self._float(merged.get("scheduled_ts")) <= now)
        items: list[dict[str, Any]] = []
        for item in buckets:
            created = self._float(item.get("created_ts"))
            last_seen = self._float(item.get("last_seen_ts")) or created
            scheduled = self._float(item.get("scheduled_ts"))
            item.pop("_signature", None)
            item.pop("_first_ts", None)
            item["created"] = self.plugin._format_timestamp_elapsed(created)
            item["last_seen"] = self.plugin._format_timestamp_elapsed(last_seen)
            item["scheduled"] = self.plugin._format_timestamp_elapsed(scheduled)
            items.append(item)
        items.sort(key=lambda item: item.get("last_seen_ts") or item.get("scheduled_ts") or 0, reverse=True)
        return {
            "total": total_attempts,
            "pending_total": pending_total,
            "record_total": len([item for item in raw if isinstance(item, dict)]),
            "visible_total": len(items),
            "counts": counts,
            "source_counts": source_counts,
            "source_labels": {key: self._proactive_source_label(key) for key in source_counts},
            "users": sorted(
                user_counts.values(),
                key=lambda item: (self._int(item.get("total")), self._single_line(item.get("label"), 40)),
                reverse=True,
            ),
            "items": items[:60],
        }

    def _proactive_motivation_runtime_summary(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        def part(raw: Any) -> dict[str, Any]:
            if not isinstance(raw, dict):
                return {}
            result: dict[str, Any] = {
                "score": round(self._float(raw.get("score")), 3),
                "label": self._single_line(raw.get("label"), 60),
                "detail": self._single_line(raw.get("detail"), 180),
            }
            if "level" in raw:
                result["level"] = round(self._float(raw.get("level")), 3)
            return result

        return {
            "score": round(self._float(value.get("score")), 3),
            "label": self._single_line(value.get("label"), 60),
            "detail": self._single_line(value.get("detail"), 220),
            "drive": part(value.get("drive")),
            "temperature": part(value.get("temperature")),
            "incentive": part(value.get("incentive")),
            "arousal": part(value.get("arousal")),
        }

    def _proactive_task_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        now = time.time()
        items: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        audit_items: list[dict[str, Any]] = []
        audit_status_counts: dict[str, int] = {}
        user_states: list[dict[str, Any]] = []

        def readiness_snapshot(user: dict[str, Any]) -> dict[str, Any]:
            getter = getattr(self.plugin, "_proactive_inner_readiness", None)
            if not callable(getter):
                return {}
            try:
                raw = getter(user, now=now)
            except Exception:
                return {}
            if not isinstance(raw, dict):
                return {}
            drive = raw.get("drive") if isinstance(raw.get("drive"), dict) else {}
            temperature = raw.get("temperature") if isinstance(raw.get("temperature"), dict) else {}
            return {
                "score": round(self._float(raw.get("score")), 3),
                "label": self._single_line(raw.get("label"), 80),
                "detail": self._single_line(raw.get("detail"), 220),
                "drive_score": round(self._float(drive.get("score")), 3) if drive else 0,
                "drive_label": self._single_line(drive.get("label"), 40) if drive else "",
                "drive_detail": self._single_line(drive.get("detail"), 140) if drive else "",
                "temperature_score": round(self._float(temperature.get("score")), 3) if temperature else 0,
                "temperature_label": self._single_line(temperature.get("label"), 40) if temperature else "",
                "temperature_detail": self._single_line(temperature.get("detail"), 140) if temperature else "",
                "motivation": self._proactive_motivation_runtime_summary(raw.get("motivation")),
            }

        def planned_semantic_snapshot(user: dict[str, Any]) -> dict[str, Any]:
            semantic_kind = self._single_line(user.get("planned_proactive_semantic_kind"), 40)
            anchor_type = self._single_line(user.get("planned_proactive_anchor_type"), 40)
            semantic_score = self._int(user.get("planned_proactive_semantic_score"))
            semantic_note = self._single_line(user.get("planned_proactive_semantic_note"), 180)
            need_layer = self._single_line(user.get("planned_proactive_need_layer"), 40)
            need_drive = self._single_line(user.get("planned_proactive_need_drive"), 80)
            need_note = self._single_line(user.get("planned_proactive_need_note"), 120)
            need_score_bias = None
            need_pressure_bias = None
            pressure = 0
            risk = 0
            getter = getattr(self.plugin, "_planned_proactive_semantics", None)
            if callable(getter):
                try:
                    semantics = getter(user)
                except Exception:
                    semantics = {}
                if isinstance(semantics, dict):
                    semantic_kind = semantic_kind or self._single_line(semantics.get("kind"), 40)
                    anchor_type = anchor_type or self._single_line(semantics.get("anchor_type"), 40)
                    if semantic_score <= 0:
                        semantic_score = int(max(0.0, min(1.0, self._float(semantics.get("score")))) * 100)
                    pressure = int(max(0.0, min(1.0, self._float(semantics.get("pressure")))) * 100)
                    risk = int(max(0.0, min(1.0, self._float(semantics.get("risk")))) * 100)
                    semantic_note = semantic_note or self._single_line(semantics.get("note"), 180)
                    need_layer = need_layer or self._single_line(semantics.get("need_layer"), 40)
                    need_drive = need_drive or self._single_line(semantics.get("need_drive"), 80)
                    need_note = need_note or self._single_line(semantics.get("need_note"), 120)
                    need_score_bias = semantics.get("need_score_bias")
                    need_pressure_bias = semantics.get("need_pressure_bias")
            return {
                "semantic_kind": semantic_kind,
                "semantic_anchor_type": anchor_type,
                "semantic_score": semantic_score,
                "semantic_pressure": pressure,
                "semantic_risk": risk,
                "semantic_note": semantic_note,
                "need_layer": need_layer,
                "need_level": need_layer,
                "need_drive": need_drive,
                "need_note": need_note,
                "need_score_bias": need_score_bias,
                "need_pressure_bias": need_pressure_bias,
            }

        def planned_window_snapshot(user: dict[str, Any]) -> dict[str, Any]:
            start_ts = self._float(user.get("planned_proactive_window_start_at"))
            best_until_ts = self._float(user.get("planned_proactive_best_until_at"))
            expire_ts = self._float(user.get("planned_proactive_expire_at"))
            phase = ""
            detail = ""
            phase_getter = getattr(self.plugin, "_planned_impulse_window_phase", None)
            if callable(phase_getter):
                try:
                    phase, detail = phase_getter(user, now=now)
                except Exception:
                    phase, detail = "", ""
            impulse_value = 0
            value_getter = getattr(self.plugin, "_planned_impulse_value", None)
            if callable(value_getter):
                try:
                    impulse_value = int(max(0.0, min(1.0, self._float(value_getter(user, now=now)))) * 100)
                except Exception:
                    impulse_value = 0
            return {
                "window_start_ts": start_ts,
                "window_start": self.plugin._format_timestamp_elapsed(start_ts),
                "best_until_ts": best_until_ts,
                "best_until": self.plugin._format_timestamp_elapsed(best_until_ts),
                "expire_ts": expire_ts,
                "expire": self.plugin._format_timestamp_elapsed(expire_ts),
                "window_phase": self._single_line(phase, 24),
                "window_detail": self._single_line(detail, 160),
                "impulse_value": impulse_value,
            }

        def afterglow_snapshot(user: dict[str, Any]) -> dict[str, Any]:
            raw = user.get("proactive_afterglow")
            if not isinstance(raw, dict):
                return {}
            ts = self._float(raw.get("ts"))
            return {
                "ts": ts,
                "time": self.plugin._format_timestamp_elapsed(ts),
                "status": self._single_line(raw.get("status"), 32),
                "label": self._single_line(raw.get("label"), 180),
                "next_tendency": self._single_line(raw.get("next_tendency"), 180),
                "reason": self._single_line(raw.get("reason"), 50),
                "action": self._single_line(raw.get("action"), 50),
                "semantic_kind": self._single_line(raw.get("semantic_kind"), 40),
                "anchor_type": self._single_line(raw.get("anchor_type"), 40),
                "semantic_score": self._int(raw.get("semantic_score")),
            }

        def hesitation_snapshot(user: dict[str, Any]) -> dict[str, Any]:
            raw = user.get("recent_proactive_hesitations")
            latest = raw[-1] if isinstance(raw, list) and raw and isinstance(raw[-1], dict) else {}
            ts = self._float(latest.get("ts") if isinstance(latest, dict) else 0) or self._float(user.get("last_proactive_hesitation_at"))
            note = self._single_line(latest.get("note") if isinstance(latest, dict) else "", 160) or self._single_line(user.get("last_proactive_hesitation_note"), 160)
            if not ts and not note:
                return {}
            return {
                "ts": ts,
                "time": self.plugin._format_timestamp_elapsed(ts),
                "note": note,
                "count": self._int(latest.get("count") if isinstance(latest, dict) else 0),
                "topic": self._single_line(latest.get("topic") if isinstance(latest, dict) else "", 80),
                "motive": self._single_line(latest.get("motive") if isinstance(latest, dict) else "", 140),
            }

        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            readiness = readiness_snapshot(user)
            afterglow = afterglow_snapshot(user)
            hesitation = hesitation_snapshot(user)
            if bool(user.get("enabled", True)):
                user_summary_for_state = self._user_summary(str(user_id), user)
                effective_limit = (
                    self.plugin._effective_user_daily_limit(user)
                    if hasattr(self.plugin, "_effective_user_daily_limit")
                    else getattr(self.plugin, "max_daily_messages", 0)
                )
                next_for_state = self._float(user.get("next_proactive_at"))
                user_states.append(
                    {
                        "user_id": str(user_id),
                        "user_label": user_summary_for_state.get("display_name") or str(user_id),
                        "user_role": user_summary_for_state.get("relationship_role") or "",
                        "user_role_label": user_summary_for_state.get("relationship_role_label") or "",
                        "sent_today": self._int(user.get("sent_today")),
                        "effective_daily_limit": effective_limit,
                        "effective_daily_limit_text": (
                            self.plugin._format_proactive_daily_limit(effective_limit)
                            if hasattr(self.plugin, "_format_proactive_daily_limit")
                            else str(effective_limit)
                        ),
                        "effective_daily_limit_unlimited": (
                            self.plugin._proactive_daily_limit_is_unlimited(effective_limit)
                            if hasattr(self.plugin, "_proactive_daily_limit_is_unlimited")
                            else False
                        ),
                        "next_proactive_ts": next_for_state,
                        "next_proactive": self.plugin._format_timestamp_elapsed(next_for_state),
                        "proactive_sending": bool(user.get("proactive_sending")),
                        "last_skip_ts": self._float(user.get("last_proactive_skip_at")),
                        "last_skip": self.plugin._format_timestamp_elapsed(user.get("last_proactive_skip_at", 0)),
                        "last_skip_reason": self._single_line(user.get("last_proactive_skip_reason"), 160),
                        "last_skip_prefix": self._single_line(user.get("last_proactive_skip_prefix"), 20),
                        "last_sent_ts": self._float(user.get("last_sent")),
                        "last_sent": self.plugin._format_timestamp_elapsed(user.get("last_sent", 0)),
                        "inner_readiness": readiness,
                        "afterglow": afterglow,
                        "hesitation": hesitation,
                    }
                )
            scheduled_ts = self._float(user.get("next_proactive_at"))
            timer_event = user.get("llm_timer_event") if isinstance(user.get("llm_timer_event"), dict) else {}
            if scheduled_ts <= 0 and timer_event:
                scheduled_ts = self._float(timer_event.get("scheduled_ts"))
            if scheduled_ts <= 0:
                continue
            source = self._single_line(user.get("planned_proactive_source"), 40)
            if not source and timer_event:
                source = "timer"
            source = source or "proactive"
            status = "due" if scheduled_ts <= now else "scheduled"
            if scheduled_ts < now - 15 * 60:
                status = "overdue"
            if timer_event and self._single_line(timer_event.get("backend"), 40) == "astrbot_cron" and scheduled_ts <= now:
                status = "handed_off"
            timer_status = self._single_line(timer_event.get("status"), 40)
            if timer_status in {"failed", "cancelled", "cancel_failed", "cancel_skipped"}:
                status = timer_status
            user_summary = self._user_summary(str(user_id), user)
            source_counts[source] = source_counts.get(source, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
            action = (
                self._single_line(user.get("planned_proactive_action"), 40)
                or self._single_line(timer_event.get("action"), 40)
                or "message"
            )
            reason = (
                self._single_line(user.get("planned_proactive_reason"), 40)
                or self._single_line(timer_event.get("reason"), 40)
            )
            topic = (
                self._single_line(user.get("planned_proactive_topic"), 80)
                or self._single_line(timer_event.get("topic"), 80)
            )
            motive = (
                self._single_line(user.get("planned_proactive_motive"), 180)
                or self._single_line(timer_event.get("motive"), 180)
            )
            sanitizer = getattr(self.plugin, "_sanitize_friend_proactive_plan_fields", None)
            if callable(sanitizer):
                sanitized = sanitizer(
                    user,
                    reason=reason,
                    action=action,
                    topic=topic,
                    motive=motive,
                )
                reason = self._single_line(sanitized.get("reason"), 40) or reason
                action = self._single_line(sanitized.get("action"), 40) or action
                topic = self._single_line(sanitized.get("topic"), 80)
                motive = self._single_line(sanitized.get("motive"), 180)
            semantic = planned_semantic_snapshot(user)
            window = planned_window_snapshot(user)
            model_result = user.get("planned_proactive_model_judge_result")
            if not isinstance(model_result, dict):
                model_result = {}
            judged_at = self._float(user.get("planned_proactive_model_judge_at"))
            items.append(
                {
                    "user_id": str(user_id),
                    "user_label": user_summary.get("display_name") or str(user_id),
                    "user_role": user_summary.get("relationship_role") or "",
                    "user_role_label": user_summary.get("relationship_role_label") or "",
                    "source": source,
                    "source_label": self._proactive_source_label(source),
                    "source_note": self._proactive_source_note(source),
                    "status": status,
                    "action": action,
                    "reason": reason,
                    "reason_label": self._proactive_reason_label(reason, target_name=user_summary.get("display_name") or str(user_id)),
                    "reason_detail": self._proactive_reason_detail(
                        reason=reason,
                        source=source,
                        topic=topic,
                        motive=motive,
                        note=user.get("last_proactive_skip_reason"),
                        target_name=user_summary.get("display_name") or str(user_id),
                    ),
                    "topic": topic,
                    "motive": motive,
                    "planned_impulse_id": self._single_line(user.get("planned_proactive_impulse_id"), 40),
                    "planned_candidate_id": self._single_line(user.get("planned_candidate_id"), 40),
                    **semantic,
                    **window,
                    "inner_readiness": readiness,
                    "afterglow": afterglow,
                    "hesitation": hesitation,
                    "model_judge": {
                        "decision": self._single_line(model_result.get("decision"), 24),
                        "score": self._int(model_result.get("score")),
                        "reason": self._single_line(model_result.get("reason"), 140),
                        "cached": bool(model_result.get("cached")),
                        "judged_ts": judged_at,
                        "judged": self.plugin._format_timestamp_elapsed(judged_at),
                    } if model_result or judged_at > 0 else {},
                    "scheduled_ts": scheduled_ts,
                    "scheduled": self.plugin._format_timestamp_elapsed(scheduled_ts),
                    "last_skip": self.plugin._format_timestamp_elapsed(user.get("last_proactive_skip_at", 0)),
                    "last_skip_ts": self._float(user.get("last_proactive_skip_at")),
                    "last_skip_reason": self._single_line(user.get("last_proactive_skip_reason"), 120),
                    "last_skip_prefix": self._single_line(user.get("last_proactive_skip_prefix"), 20),
                    "created_ts": self._float(timer_event.get("created_at")),
                    "created": self.plugin._format_timestamp_elapsed(timer_event.get("created_at", 0)),
                    "origin": self._single_line(timer_event.get("origin"), 40),
                    "backend": self._single_line(timer_event.get("backend"), 40),
                    "job_id": self._single_line(timer_event.get("job_id"), 80),
                    "timer_status": timer_status,
                    "timer_error": self._single_line(timer_event.get("error") or timer_event.get("replace_error"), 180),
                    "activity": self._single_line(timer_event.get("activity"), 60),
                    "estimated_minutes": self._int(timer_event.get("estimated_minutes")),
                    "followup_intensity": self._int(timer_event.get("followup_intensity")),
                    "replaced_job_id": self._single_line(timer_event.get("replaced_job_id"), 80),
                    "cancelled_job_id": self._single_line(timer_event.get("cancelled_job_id"), 80),
                    "raw_time": self._single_line(timer_event.get("raw_time"), 40),
                    "trigger_message_id": self._single_line(timer_event.get("trigger_message_id"), 120),
                    "trigger_umo": self._single_line(timer_event.get("trigger_umo"), 160),
                    "has_timer_event": bool(timer_event),
                    "silence_until_due": bool(timer_event.get("silence_until_due")) if timer_event else False,
                }
            )

        items.sort(key=lambda item: self._float(item.get("scheduled_ts")))
        raw_audit = data.get("proactive_audit_log") if isinstance(data.get("proactive_audit_log"), list) else []
        seen_audit_signatures: dict[str, dict[str, Any]] = {}
        for raw in raw_audit:
            if not isinstance(raw, dict):
                continue
            meta_leak_checker = getattr(self.plugin, "_framework_agent_meta_summary_leak", None)
            if callable(meta_leak_checker) and (
                meta_leak_checker(str(raw.get("text_preview") or ""))
                or meta_leak_checker(str(raw.get("original_text_preview") or ""))
                or meta_leak_checker(str(raw.get("final_text_preview") or ""))
                or meta_leak_checker(str(raw.get("text") or ""))
                or meta_leak_checker(str(raw.get("note") or ""))
            ):
                continue
            user_id = str(raw.get("user_id") or "")
            user = users.get(user_id) if isinstance(users.get(user_id), dict) else {}
            user_summary = self._user_summary(user_id, user) if user_id else {}
            status = self._single_line(raw.get("status"), 32) or "unknown"
            note = self._single_line(raw.get("note"), 180)
            obsolete_checker = getattr(self.plugin, "_proactive_audit_note_is_obsolete_fixed_error", None)
            if callable(obsolete_checker) and obsolete_checker(note):
                status = "obsolete"
                note = "旧版本主动发送变量错误，当前版本已修复"
            if status == "obsolete":
                continue
            audit_reason = self._single_line(raw.get("reason"), 40)
            audit_action = self._single_line(raw.get("action"), 60)
            audit_topic = self._single_line(raw.get("topic"), 100)
            audit_motive = self._single_line(raw.get("motive"), 180)
            sanitizer = getattr(self.plugin, "_sanitize_friend_proactive_plan_fields", None)
            if isinstance(user, dict) and callable(sanitizer):
                sanitized = sanitizer(
                    user,
                    reason=audit_reason,
                    action=audit_action,
                    topic=audit_topic,
                    motive=audit_motive,
                )
                audit_reason = self._single_line(sanitized.get("reason"), 40) or audit_reason
                audit_action = self._single_line(sanitized.get("action"), 60) or audit_action
                audit_topic = self._single_line(sanitized.get("topic"), 100)
                audit_motive = self._single_line(sanitized.get("motive"), 180)
            updated_ts = self._float(raw.get("updated_ts"))
            bucket = int(updated_ts // 300) if updated_ts > 0 else 0
            signature = "|".join(
                self._single_line(value, 120)
                for value in (
                    user_id,
                    status,
                    self._single_line(raw.get("source"), 40),
                    audit_reason,
                    audit_action,
                    audit_topic,
                    audit_motive,
                    note,
                    bucket,
                )
            )
            text_preview = self._display_message_text(raw.get("text_preview"), 180)
            original_text_preview = self._display_message_text(raw.get("original_text_preview"), 180)
            final_text_preview = self._display_message_text(raw.get("final_text_preview"), 180)
            existing = seen_audit_signatures.get(signature)
            if existing is not None:
                previous_updated = self._float(existing.get("updated_ts"))
                existing["updated_ts"] = max(previous_updated, updated_ts)
                existing["updated"] = self.plugin._format_timestamp_elapsed(existing["updated_ts"])
                existing["duplicate_count"] = max(1, self._int(existing.get("duplicate_count"))) + max(1, self._int(raw.get("duplicate_count")))
                if updated_ts >= previous_updated:
                    if text_preview:
                        existing["text_preview"] = text_preview
                    if original_text_preview:
                        existing["original_text_preview"] = original_text_preview
                    if final_text_preview:
                        existing["final_text_preview"] = final_text_preview
                continue
            audit_status_counts[status] = audit_status_counts.get(status, 0) + 1
            item = {
                "id": self._single_line(raw.get("id"), 40),
                "user_id": user_id,
                "user_label": user_summary.get("display_name") or user_id,
                "user_role": user_summary.get("relationship_role") or "",
                "user_role_label": user_summary.get("relationship_role_label") or "",
                "status": status,
                "source": self._single_line(raw.get("source"), 40),
                "source_label": self._proactive_source_label(raw.get("source")),
                "source_note": self._proactive_source_note(raw.get("source")),
                "reason": audit_reason,
                "reason_label": self._proactive_reason_label(audit_reason, target_name=user_summary.get("display_name") or user_id),
                "reason_detail": self._proactive_reason_detail(
                    reason=audit_reason,
                    source=raw.get("source"),
                    topic=audit_topic,
                    motive=audit_motive,
                    note=note,
                    target_name=user_summary.get("display_name") or user_id,
                ),
                "action": audit_action,
                "topic": audit_topic,
                "motive": audit_motive,
                "semantic_kind": self._single_line(raw.get("semantic_kind"), 40),
                "semantic_anchor_type": self._single_line(raw.get("semantic_anchor_type"), 40),
                "semantic_score": self._int(raw.get("semantic_score")),
                "semantic_pressure": self._int(raw.get("semantic_pressure")),
                "semantic_risk": self._int(raw.get("semantic_risk")),
                "semantic_note": self._single_line(raw.get("semantic_note"), 180),
                "need_layer": self._single_line(raw.get("need_layer") or raw.get("semantic_need_layer"), 40),
                "need_level": self._single_line(raw.get("need_layer") or raw.get("semantic_need_layer"), 40),
                "need_drive": self._single_line(raw.get("need_drive") or raw.get("semantic_need_drive"), 80),
                "need_note": self._single_line(raw.get("need_note") or raw.get("semantic_need_note"), 120),
                "need_score_bias": raw.get("need_score_bias", raw.get("semantic_need_score_bias")),
                "need_pressure_bias": raw.get("need_pressure_bias", raw.get("semantic_need_pressure_bias")),
                "note": note,
                "text_preview": text_preview,
                "original_text_preview": original_text_preview,
                "final_text_preview": final_text_preview,
                "scheduled_ts": self._float(raw.get("scheduled_ts")),
                "scheduled": self.plugin._format_timestamp_elapsed(raw.get("scheduled_ts", 0)),
                "created_ts": self._float(raw.get("created_ts")),
                "created": self.plugin._format_timestamp_elapsed(raw.get("created_ts", 0)),
                "updated_ts": updated_ts,
                "updated": self.plugin._format_timestamp_elapsed(raw.get("updated_ts", 0)),
                "candidate_id": self._single_line(raw.get("candidate_id"), 40),
                "has_image": bool(self._single_line(raw.get("image_path"), 260)),
                "extra_count": self._int(raw.get("extra_count")),
                "duplicate_count": max(1, self._int(raw.get("duplicate_count"))),
            }
            seen_audit_signatures[signature] = item
            audit_items.append(item)
        audit_items.sort(key=lambda item: self._float(item.get("updated_ts") or item.get("created_ts")), reverse=True)
        runtime = data.get("proactive_runtime") if isinstance(data.get("proactive_runtime"), dict) else {}
        last_tick_started = self._float(runtime.get("last_tick_started_at")) if runtime else 0
        last_tick_finished = self._float(runtime.get("last_tick_finished_at")) if runtime else 0
        tick_age = now - max(last_tick_started, last_tick_finished) if max(last_tick_started, last_tick_finished) > 0 else -1
        expected_interval = max(30, self._int(getattr(self.plugin, "check_interval_seconds", 60)))
        return {
            "total": len(items),
            "source_counts": source_counts,
            "status_counts": status_counts,
            "items": items[:30],
            "audit_total": len(audit_items),
            "audit_status_counts": audit_status_counts,
            "audit_items": audit_items[:40],
            "user_states": sorted(
                user_states,
                key=lambda item: (
                    0 if item.get("user_role") == "owner" else 1,
                    self._float(item.get("next_proactive_ts")) if self._float(item.get("next_proactive_ts")) > 0 else 9999999999,
                    self._single_line(item.get("user_label"), 40),
                ),
            )[:40],
            "runtime": {
                "last_tick_started_ts": last_tick_started,
                "last_tick_started": self.plugin._format_timestamp_elapsed(last_tick_started),
                "last_tick_finished_ts": last_tick_finished,
                "last_tick_finished": self.plugin._format_timestamp_elapsed(last_tick_finished),
                "tick_age_seconds": round(tick_age, 1) if tick_age >= 0 else -1,
                "expected_interval_seconds": expected_interval,
                "healthy": bool(tick_age >= 0 and tick_age <= max(180, expected_interval * 4)),
                "last_tick_error": self._single_line(runtime.get("last_tick_error"), 180) if runtime else "",
            },
        }

    # ============================================================
    # Creative Project Management Endpoints
    # ============================================================

    def _creative_project_cover_path(self, project: dict[str, Any]) -> Path | None:
        path_text = self._single_line(project.get("cover_path"), 500)
        if not path_text:
            return None
        try:
            path = Path(path_text).resolve()
        except Exception:
            return None
        return path if path.exists() and path.is_file() else None

    def _creative_project_cover_url(self, project: dict[str, Any]) -> str:
        project_id = self._single_line(project.get("id"), 32)
        path = self._creative_project_cover_path(project)
        if not project_id or path is None:
            return ""
        try:
            stat = path.stat()
            version = f"{int(stat.st_mtime)}-{stat.st_size}"
        except OSError:
            version = self._single_line(project.get("cover_generated_at"), 40)
        return f"{PAGE_API_PREFIX}/creative/project/cover?id={quote(project_id, safe='')}&v={quote(version, safe='')}"

    def _creative_project_payload(self, project: dict[str, Any]) -> dict[str, Any]:
        chunks = project.get("draft_chunks") if isinstance(project.get("draft_chunks"), list) else []
        chunk_items = []
        for idx, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            chunk_ts = chunk.get("at", 0) or chunk.get("created_at", 0) or chunk.get("created_ts", 0)
            chunk_items.append(
                {
                    "index": idx,
                    "text": self._single_line(chunk.get("text"), 8000),
                    "chars": self._int(chunk.get("chars")),
                    "at": chunk_ts,
                    "created": self.plugin._format_timestamp_elapsed(chunk_ts),
                    "manually_edited": bool(chunk.get("manually_edited")),
                }
            )
        return {
            "id": self._single_line(project.get("id"), 32),
            "title": self._single_line(project.get("title"), 80),
            "work_type": self._single_line(project.get("work_type"), 40) or "短篇小说",
            "premise": self._single_line(project.get("premise"), 500),
            "tone": self._single_line(project.get("tone"), 80),
            "point_of_view": self._single_line(project.get("point_of_view"), 60),
            "source": self._single_line(project.get("source"), 40),
            "source_text": self._single_line(project.get("source_text"), 500),
            "status": self._single_line(project.get("status"), 24),
            "current_chars": self._int(project.get("current_chars")),
            "target_chars": self._int(project.get("target_chars")),
            "next_hint": self._single_line(project.get("next_hint"), 240),
            "outline": project.get("outline") if isinstance(project.get("outline"), list) else [],
            "characters": project.get("characters") if isinstance(project.get("characters"), list) else [],
            "story_bible": project.get("story_bible") if isinstance(project.get("story_bible"), dict) else {},
            "revision_notes": self._limited_list(project.get("revision_notes"), 20),
            "quality_reviews": self._limited_list(project.get("quality_reviews"), 20),
            "manual_edits": self._limited_list(project.get("manual_edits"), 30),
            "creative_memory_pool": self._limited_list(project.get("creative_memory_pool"), 50),
            "last_manual_edit_at": self.plugin._format_timestamp_elapsed(project.get("last_manual_edit_at", 0)),
            "last_manual_edit_summary": self._single_line(project.get("last_manual_edit_summary"), 160),
            "chunks": chunk_items,
            "chunk_count": len(chunk_items),
            "milestones": project.get("disclosed_milestones") if isinstance(project.get("disclosed_milestones"), list) else [],
            "created_at": self.plugin._format_timestamp_elapsed(project.get("created_at", 0)),
            "last_advanced": self.plugin._format_timestamp_elapsed(project.get("last_advanced_at", 0)),
            "next_advance": self.plugin._format_timestamp_elapsed(project.get("next_advance_at", 0)),
            "cover_src": self._creative_project_cover_url(project),
            "cover_status": self._single_line(project.get("cover_generation_status"), 24),
            "cover_error": self._single_line(project.get("cover_generation_error"), 220),
            "cover_backend": self._single_line(project.get("cover_generation_backend"), 80),
            "cover_style": self._single_line(project.get("cover_generation_style"), 40),
            "cover_attempts": self._int(project.get("cover_generation_attempts")),
            "cover_generated_at": self.plugin._format_timestamp_elapsed(project.get("cover_generated_at", 0)),
        }

    async def get_creative_project_cover(self):
        project_id = self._single_line(request.args.get("id"), 32)
        if not project_id:
            return self._error("缺少 id")
        async with self.plugin._data_lock:
            projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
            project = next(
                (item for item in projects if isinstance(item, dict) and self._single_line(item.get("id"), 32) == project_id),
                None,
            )
            path = self._creative_project_cover_path(project) if isinstance(project, dict) else None
        if path is None:
            return self._error("作品封面不存在")
        response = await send_file(str(path))
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    async def get_creative_project_cover_data(self) -> dict[str, Any]:
        project_id = self._single_line(request.args.get("id"), 32)
        if not project_id:
            return self._error("缺少 id")
        async with self.plugin._data_lock:
            projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
            project = next(
                (item for item in projects if isinstance(item, dict) and self._single_line(item.get("id"), 32) == project_id),
                None,
            )
            path = self._creative_project_cover_path(project) if isinstance(project, dict) else None
        if path is None:
            return self._error("作品封面不存在")
        try:
            mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
            data = await self._read_file_base64(path)
            stat = path.stat()
            return self._ok(
                {
                    "mime": mime,
                    "data_url": f"data:{mime};base64,{data}",
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                }
            )
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 读取创作封面数据失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def get_creative_project(self) -> dict[str, Any]:
        project_id = str(request.args.get("id", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            async with self.plugin._data_lock:
                projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
                project = next((p for p in projects if isinstance(p, dict) and p.get("id") == project_id), None)
                if not project:
                    return self._error("作品不存在")
                snapshot = deepcopy(project)
            return self._ok(self._creative_project_payload(snapshot))
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 获取创作项目详情失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def update_creative_project(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            changed_notes: list[str] = []
            async with self.plugin._data_lock:
                projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
                project = next((p for p in projects if isinstance(p, dict) and p.get("id") == project_id), None)
                if not project:
                    return self._error("作品不存在")
                for key, limit in (
                    ("title", 80),
                    ("work_type", 40),
                    ("premise", 500),
                    ("tone", 80),
                    ("point_of_view", 60),
                    ("next_hint", 240),
                    ("source_text", 500),
                ):
                    if key not in payload:
                        continue
                    value = self._single_line(payload.get(key), limit)
                    if value != self._single_line(project.get(key), limit):
                        project[key] = value
                        changed_notes.append(f"{key}: {value}")
                if "status" in payload:
                    status = self._single_line(payload.get("status"), 24)
                    if status in ("drafting", "finished", "paused") and status != project.get("status"):
                        project["status"] = status
                        changed_notes.append(f"status: {status}")
                if "target_chars" in payload:
                    target_chars = _safe_int(payload.get("target_chars"), 2000, 300, 5200)
                    if target_chars != self._int(project.get("target_chars")):
                        project["target_chars"] = target_chars
                        changed_notes.append(f"target_chars: {target_chars}")
                if changed_notes:
                    story_bible_getter = getattr(self.plugin, "_get_or_create_story_bible", None)
                    if callable(story_bible_getter):
                        story_bible = story_bible_getter(project)
                        if "premise" in payload:
                            story_bible["mainline_direction"] = self._single_line(project.get("premise"), 160)
                        if "next_hint" in payload:
                            story_bible["next_direction"] = self._single_line(project.get("next_hint"), 160)
                    edits = project.setdefault("manual_edits", [])
                    if not isinstance(edits, list):
                        edits = []
                        project["manual_edits"] = edits
                    now = time.time()
                    note = "；".join(changed_notes)
                    edits.append(
                        {
                            "id": secrets.token_hex(6),
                            "type": "project_meta",
                            "title": "更新作品信息",
                            "content": note[:2000],
                            "chunk_index": -1,
                            "created_at": now,
                        }
                    )
                    del edits[:-10]
                    project["last_manual_edit_at"] = now
                    project["last_manual_edit_summary"] = "更新作品信息"
                    pool_getter = getattr(self.plugin, "_get_or_create_memory_pool", None)
                    add_memory = getattr(self.plugin, "_add_memory_entry", None)
                    extract_keywords = getattr(self.plugin, "_extract_creative_keywords", None)
                    if callable(pool_getter) and callable(add_memory):
                        keywords = extract_keywords(note, limit=8) if callable(extract_keywords) else ["作品信息"]
                        add_memory(
                            pool_getter(project),
                            project_id,
                            "revision",
                            f"更新作品信息: {self._single_line(note, 180)}",
                            keywords or ["作品信息"],
                            importance=5,
                        )
                self.plugin._save_data_sync()
            return self._ok({"project_id": project_id, "changed": bool(changed_notes), "message": "作品已更新"})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 更新创作项目失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def update_creative_chunk(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        chunk_index = _safe_int(payload.get("chunk_index"), -1, -1)
        text = str(payload.get("text", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        if chunk_index < 0:
            return self._error("缺少 chunk_index")
        if not text:
            return self._error("缺少 text")
        try:
            apply_edit = getattr(self.plugin, "_apply_creative_manual_edit", None)
            if not callable(apply_edit):
                return self._error("创作编辑能力不可用")
            result = await apply_edit(project_id, "chunk_text", text, f"修改第{chunk_index + 1}段", chunk_index)
            if not result.get("success"):
                return self._error(result.get("error") or "片段更新失败")
            return self._ok({"project_id": project_id, "chunk_index": chunk_index, "message": "片段已更新"})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 更新创作片段失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def update_creative_outline(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        outline_text = str(payload.get("outline", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            apply_edit = getattr(self.plugin, "_apply_creative_manual_edit", None)
            if not callable(apply_edit):
                return self._error("创作编辑能力不可用")
            result = await apply_edit(project_id, "outline", outline_text, "更新大纲", -1)
            if not result.get("success"):
                return self._error(result.get("error") or "大纲更新失败")
            return self._ok({"project_id": project_id, "message": "大纲已更新"})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 更新创作大纲失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def update_creative_characters(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        raw_characters = payload.get("characters")
        if not project_id:
            return self._error("缺少 id")
        if not isinstance(raw_characters, list):
            return self._error("角色必须是数组")
        try:
            characters = [item for item in raw_characters if isinstance(item, dict)]
            apply_edit = getattr(self.plugin, "_apply_creative_manual_edit", None)
            if not callable(apply_edit):
                return self._error("创作编辑能力不可用")
            result = await apply_edit(
                project_id,
                "characters",
                json.dumps(characters, ensure_ascii=False),
                "更新角色表",
                -1,
            )
            if not result.get("success"):
                return self._error(result.get("error") or "角色更新失败")
            return self._ok({"project_id": project_id, "message": "角色已更新"})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 更新创作角色失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def reanalyze_creative_project(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            async with self.plugin._data_lock:
                projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
                project = next((p for p in projects if isinstance(p, dict) and p.get("id") == project_id), None)
                if not project:
                    return self._error("作品不存在")
                snapshot = deepcopy(project)
            chunks = snapshot.get("draft_chunks") if isinstance(snapshot.get("draft_chunks"), list) else []
            latest = next((c for c in reversed(chunks) if isinstance(c, dict) and self._single_line(c.get("text"), 80)), None)
            if not latest:
                return self._error("还没有正文片段，无法分析")
            story_bible = snapshot.get("story_bible") if isinstance(snapshot.get("story_bible"), dict) else {}
            outline = "\n".join(snapshot.get("outline", [])) if isinstance(snapshot.get("outline"), list) else ""
            safe_recent_chunks = [c for c in chunks[-5:] if isinstance(c, dict)]
            reviewer = getattr(self.plugin, "_review_creative_chunk", None)
            if not callable(reviewer):
                return self._error("创作审校能力不可用")
            review = await reviewer(snapshot, story_bible, outline, latest.get("text", ""), safe_recent_chunks)
            if not isinstance(review, dict):
                review = {}
            async with self.plugin._data_lock:
                projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
                project = next((p for p in projects if isinstance(p, dict) and p.get("id") == project_id), None)
                if not project:
                    return self._error("作品不存在")
                review["id"] = secrets.token_hex(6)
                review["chunk_index"] = len(project.get("draft_chunks") or []) - 1
                review["created_at"] = time.time()
                reviews = project.setdefault("quality_reviews", [])
                if not isinstance(reviews, list):
                    reviews = []
                    project["quality_reviews"] = reviews
                reviews.append(review)
                del reviews[:-20]
                self.plugin._save_data_sync()
            return self._ok({"project_id": project_id, "review": review})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 创作项目质量分析失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def rebuild_creative_memory(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            rebuild = getattr(self.plugin, "_rebuild_creative_memory_from_project", None)
            if not callable(rebuild):
                return self._error("创作记忆重建能力不可用")
            result = await rebuild(project_id)
            if not result.get("success"):
                return self._error(result.get("error") or "重建失败")
            return self._ok(result)
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 重建创作记忆失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    async def delete_creative_project(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        project_id = str(payload.get("id", "")).strip()
        if not project_id:
            return self._error("缺少 id")
        try:
            async with self.plugin._data_lock:
                projects = self.plugin.data.get("creative_projects") if isinstance(self.plugin.data.get("creative_projects"), list) else []
                before = len(projects)
                self.plugin.data["creative_projects"] = [
                    p for p in projects if not (isinstance(p, dict) and p.get("id") == project_id)
                ]
                removed = before - len(self.plugin.data["creative_projects"])
                self.plugin._save_data_sync()
            return self._ok({"project_id": project_id, "removed": removed})
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 删除创作项目失败: %s", exc, exc_info=True)
            return self._error(str(exc))

    def _creative_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        projects = data.get("creative_projects") if isinstance(data.get("creative_projects"), list) else []
        items = [item for item in projects if isinstance(item, dict)]
        active = [item for item in items if item.get("status") == "drafting"]
        latest = items[-1] if items else {}
        return {
            "enabled": bool(getattr(self.plugin, "enable_creative_writing", False)),
            "hidden_mode": bool(getattr(self.plugin, "creative_hidden_mode", False)),
            "cover_generation_enabled": bool(getattr(self.plugin, "enable_creative_cover_generation", False)),
            "project_count": len(items),
            "active_projects": len(active),
            "latest_title": self._single_line(latest.get("title"), 60) if isinstance(latest, dict) else "",
            "latest_status": self._single_line(latest.get("status"), 24) if isinstance(latest, dict) else "",
            "latest_progress": {
                "current_chars": self._int(latest.get("current_chars")) if isinstance(latest, dict) else 0,
                "target_chars": self._int(latest.get("target_chars")) if isinstance(latest, dict) else 0,
            },
            "items": [
                {
                    "id": self._single_line(item.get("id"), 20),
                    "title": self._single_line(item.get("title"), 60),
                    "work_type": self._single_line(item.get("work_type"), 30) or "短篇小说",
                    "premise": self._single_line(item.get("premise"), 160),
                    "tone": self._single_line(item.get("tone"), 40),
                    "point_of_view": self._single_line(item.get("point_of_view"), 40) or "第三人称有限视角",
                    "source": self._single_line(item.get("source_text"), 160),
                    "status": self._single_line(item.get("status"), 24),
                    "current_chars": self._int(item.get("current_chars")),
                    "target_chars": self._int(item.get("target_chars")),
                    "chunk_count": len(item.get("draft_chunks") or []) if isinstance(item.get("draft_chunks"), list) else 0,
                    "outline_count": len(item.get("outline") or []) if isinstance(item.get("outline"), list) else 0,
                    "character_count": len(item.get("characters") or []) if isinstance(item.get("characters"), list) else 0,
                    "has_story_bible": bool(item.get("story_bible")) if isinstance(item.get("story_bible"), dict) else False,
                    "review_count": len(item.get("quality_reviews") or []) if isinstance(item.get("quality_reviews"), list) else 0,
                    "manual_edit_count": len(item.get("manual_edits") or []) if isinstance(item.get("manual_edits"), list) else 0,
                    "latest_snippet": self._single_line(
                        (item.get("draft_chunks") or [])[-1].get("text") if isinstance(item.get("draft_chunks"), list) and item.get("draft_chunks") else "",
                        260,
                    ),
                    "milestones": item.get("disclosed_milestones") if isinstance(item.get("disclosed_milestones"), list) else [],
                    "created_at": self.plugin._format_timestamp_elapsed(item.get("created_at", 0)),
                    "last_advanced": self.plugin._format_timestamp_elapsed(item.get("last_advanced_at", 0)),
                    "next_advance": self.plugin._format_timestamp_elapsed(item.get("next_advance_at", 0)),
                    "cover_src": self._creative_project_cover_url(item),
                    "cover_status": self._single_line(item.get("cover_generation_status"), 24),
                    "cover_error": self._single_line(item.get("cover_generation_error"), 180),
                }
                for item in items[-6:]
            ],
        }
