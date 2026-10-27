# -*- coding: utf-8 -*-
"""Private Companion Page API - 排障中心 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from astrbot.api import logger
from quart import request


class PrivateCompanionPageApiTroubleMixin:
    def _troubleshooting_warning_type(self, scope: str, *parts: Any) -> str:
        source = "\x1f".join(
            self._single_line(part, 180).strip().lower()
            for part in (scope, *parts)
            if self._single_line(part, 180).strip()
        )
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
        return f"warning:{digest}"

    def _troubleshooting_semantic_warning_type(self, code: Any) -> str:
        normalized = re.sub(r"[^a-z0-9_.:-]+", "_", self._single_line(code, 120).lower()).strip("_.:-")
        return self._troubleshooting_warning_type("semantic", normalized or "unknown")

    def _troubleshooting_proactive_warning_code(self, kind: str, item: dict[str, Any], note: str) -> str:
        text = " ".join(
            self._single_line(value, 180).lower()
            for value in (item.get("reason"), item.get("source"), item.get("action"), note)
            if value
        )
        categories = (
            ("timeout", ("超时", "timeout", "timed out")),
            ("provider", ("provider", "模型", "不可用", "api", "鉴权", "401", "403")),
            ("send", ("发送失败", "投递失败", "send", "发送异常")),
            ("storage", ("保存失败", "写入失败", "database", "sqlite", "locked", "存储")),
            ("media", ("生图", "图片", "photo", "image", "参考图", "下载")),
            ("voice", ("tts", "语音", "音频")),
            ("tool", ("工具", "tool", "调用失败")),
        )
        category = next((name for name, tokens in categories if any(token in text for token in tokens)), "other")
        action = re.sub(r"[^a-z0-9_]+", "_", self._single_line(item.get("action"), 40).lower()).strip("_") or "message"
        return f"proactive.{kind}.{category}.{action}"

    def _troubleshooting_chain_warning_code(self, test_type: str, text: Any) -> str:
        warning = self._single_line(text, 360).lower()
        categories = (
            ("timeout_budget", ("测试外层最多等待", "测试层截断")),
            ("fallback_delay", ("备选在线图片 api", "回退链路")),
            ("sdgen_timeout", ("sdgen",)),
            ("auto_backend", ("当前为自动后端",)),
            ("reference_missing", ("没有解析到可用本地参考图",)),
            ("reference_scope", ("参考图", "文生图")),
            ("serial_queue", ("全局串行锁", "先排队")),
            ("gateway_buffer", ("cloudflare", "网关", "缓冲")),
            ("test_scope", ("只检查生成文件", "不覆盖后续")),
        )
        category = next((name for name, tokens in categories if any(token in warning for token in tokens)), "other")
        normalized_test = re.sub(r"[^a-z0-9_]+", "_", self._single_line(test_type, 60).lower()).strip("_") or "chain"
        return f"chain.{normalized_test}.{category}"

    def _troubleshooting_chain_tests_with_warning_items(
        self,
        results: dict[str, Any],
        suppressed_keys: set[str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        decorated = deepcopy(results) if isinstance(results, dict) else {}
        all_items: list[dict[str, Any]] = []
        for test_type, raw_result in decorated.items():
            if not isinstance(raw_result, dict):
                continue
            warning_items: list[dict[str, Any]] = []
            for warning in raw_result.get("warnings", []) if isinstance(raw_result.get("warnings"), list) else []:
                text = self._single_line(warning, 360)
                if not text:
                    continue
                code = self._troubleshooting_chain_warning_code(str(test_type), text)
                warning_items.append(
                    {
                        "level": "warn",
                        "title": self._single_line(text, 90),
                        "text": text,
                        "source": "链路测试",
                        "warning_code": code,
                        "warning_type": self._troubleshooting_semantic_warning_type(code),
                    }
                )
            all_items.extend(warning_items)
            visible_items = self._filter_suppressed_troubleshooting_warnings(warning_items, suppressed_keys)
            raw_result["warning_items"] = visible_items
            raw_result["warnings"] = [item["text"] for item in visible_items]
        return decorated, all_items

    def _troubleshooting_legacy_warning_code(self, title: Any) -> str:
        normalized = self._single_line(title, 90)
        aliases = {
            "TTS 配置已开但 provider 不可用": "tts.provider_unavailable",
            "TTS 强化已开但会话 TTS 未启用": "tts.provider_unavailable",
            "TTS 强化开启但合成 provider 不可用": "tts.provider_unavailable",
            "暂无启用的私聊对象": "proactive.no_enabled_users",
            "主动消息没有私聊对象": "proactive.no_enabled_users",
            "私聊主动已关闭": "proactive.daily_limit_zero",
            "私聊主动总额度为 0": "proactive.daily_limit_zero",
            "Token 软限额正在暂缓后台任务": "token.soft_limit_active",
            "每日 Token 软限额已接管": "token.soft_limit_active",
            "SQLite 并发状态需要关注": "sqlite.wal",
            "主动循环心跳不新鲜": "proactive.loop_stale",
            "私聊图片识别调度状态读取失败": "vision.runtime_unreadable",
            "私聊图片识别暂无可用模型": "vision.no_available_provider",
            "有识图模型被临时降权": "vision.provider_cooldown",
            "配置诊断仍有待处理项": "diagnostic.pending",
        }
        return aliases.get(normalized, "")

    def _troubleshooting_warning_records(self, data: dict[str, Any] | None) -> list[dict[str, Any]]:
        raw = data.get("troubleshooting_suppressed_warning_types") if isinstance(data, dict) else []
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_raw: set[str] = set()
        for item in raw if isinstance(raw, list) else []:
            record = item if isinstance(item, dict) else {"key": item}
            raw_key = self._single_line(record.get("key"), 64)
            if raw_key and raw_key in seen_raw:
                continue
            if raw_key:
                seen_raw.add(raw_key)
            code = re.sub(r"[^a-z0-9_.:-]+", "_", self._single_line(record.get("code"), 120).lower()).strip("_.:-")
            if not code:
                code = self._troubleshooting_legacy_warning_code(record.get("title"))
            key = self._troubleshooting_semantic_warning_type(code) if code else raw_key
            if not re.fullmatch(r"warning:[0-9a-f]{20}", key) or key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "key": key,
                    "title": self._single_line(record.get("title"), 90) or "未命名警告类型",
                    "source": self._single_line(record.get("source"), 40) or "排障检查",
                    "suppressed_at": self._float(record.get("suppressed_at")),
                    "code": code,
                }
            )
        return records[:120]

    def _troubleshooting_diagnostics_with_types(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decorated: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            code = self._single_line(item.get("warning_code"), 120)
            item["warning_type"] = self._single_line(item.get("warning_type"), 64) or (
                self._troubleshooting_semantic_warning_type(code)
                if code
                else self._troubleshooting_warning_type("diagnostic", item.get("title"))
            )
            decorated.append(item)
        return decorated

    def _filter_suppressed_troubleshooting_warnings(
        self,
        items: list[dict[str, Any]],
        suppressed_keys: set[str],
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in items
            if not (
                self._single_line(item.get("level"), 12) == "warn"
                and self._single_line(item.get("warning_type"), 64) in suppressed_keys
            )
        ]

    def _troubleshooting_suppression_payload(
        self,
        records: list[dict[str, Any]],
        *item_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        active_counts: dict[str, int] = {}
        for items in item_groups:
            for item in items:
                if not isinstance(item, dict) or self._single_line(item.get("level"), 12) != "warn":
                    continue
                key = self._single_line(item.get("warning_type"), 64)
                if key:
                    active_counts[key] = active_counts.get(key, 0) + 1
        return [{**record, "current_count": active_counts.get(record["key"], 0)} for record in records]

    async def update_troubleshooting_warning_suppression(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        action = self._single_line(payload.get("action"), 24).lower()
        if action not in {"suppress", "restore", "restore_all"}:
            return self._error("action 只能是 suppress、restore 或 restore_all")
        key = self._single_line(payload.get("key"), 64)
        code = re.sub(r"[^a-z0-9_.:-]+", "_", self._single_line(payload.get("code"), 120).lower()).strip("_.:-")
        if action == "suppress" and code:
            key = self._troubleshooting_semantic_warning_type(code)
        if action != "restore_all" and not re.fullmatch(r"warning:[0-9a-f]{20}", key):
            return self._error("无效的警告类型")
        try:
            async with self.plugin._data_lock:
                records = self._troubleshooting_warning_records(self.plugin.data)
                previous = list(records)
                if action == "suppress":
                    record = {
                        "key": key,
                        "title": self._single_line(payload.get("title"), 90) or "未命名警告类型",
                        "source": self._single_line(payload.get("source"), 40) or "排障检查",
                        "suppressed_at": time.time(),
                        "code": code,
                    }
                    records = [item for item in records if item.get("key") != key]
                    records.append(record)
                    records = records[-120:]
                elif action == "restore":
                    records = [item for item in records if item.get("key") != key]
                else:
                    records = []
                changed = records != previous
                self.plugin.data["troubleshooting_suppressed_warning_types"] = records
                if changed:
                    self.plugin._save_data_sync()
            return self._ok(
                {
                    "items": records,
                    "count": len(records),
                    "changed": changed,
                    "message": "已屏蔽此类警告" if action == "suppress" else ("已恢复全部警告类型" if action == "restore_all" else "已恢复此类警告"),
                }
            )
        except Exception as exc:
            logger.error("[PrivateCompanionPage] 更新排障警告屏蔽失败: %s", self._single_line(exc, 160), exc_info=True)
            return self._error(str(exc))

    async def get_diagnostics(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                raw_users = self.plugin.data.get("users") if isinstance(self.plugin.data.get("users"), dict) else {}
                raw_groups = self.plugin.data.get("groups") if isinstance(self.plugin.data.get("groups"), dict) else {}
                users = {str(key): dict(value) for key, value in raw_users.items() if isinstance(value, dict)}
                groups = {str(key): dict(value) for key, value in raw_groups.items() if isinstance(value, dict)}
                suppression_records = self._troubleshooting_warning_records(self.plugin.data)
            tune_result = await self._maybe_apply_personality_iteration_auto_tune(users, groups)
            items = self._build_diagnostics(users, groups)
            tune_item = self._personality_auto_tune_diagnostic_item(tune_result)
            if tune_item:
                items.append(tune_item)
            items = self._troubleshooting_diagnostics_with_types(items)
            visible_items = self._filter_suppressed_troubleshooting_warnings(
                items,
                {record["key"] for record in suppression_records},
            )
            return self._ok(
                {
                    "items": visible_items,
                    "suppressed_warning_types": self._troubleshooting_suppression_payload(suppression_records, items),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取诊断失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def get_troubleshooting(self) -> dict[str, Any]:
        try:
            await self._recover_stale_troubleshooting_proactive_test()
            async with self.plugin._data_lock:
                data = deepcopy(self.plugin.data)
            users = data.get("users") if isinstance(data.get("users"), dict) else {}
            groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
            tune_result = await self._maybe_apply_personality_iteration_auto_tune(users, groups)
            suppression_records = self._troubleshooting_warning_records(data)
            suppressed_keys = {record["key"] for record in suppression_records}
            all_diagnostics = self._build_diagnostics(users, groups)
            tune_item = self._personality_auto_tune_diagnostic_item(tune_result)
            if tune_item:
                all_diagnostics.append(tune_item)
            all_diagnostics = self._troubleshooting_diagnostics_with_types(all_diagnostics)
            diagnostics = self._filter_suppressed_troubleshooting_warnings(all_diagnostics, suppressed_keys)
            proactive_tasks = self._proactive_task_summary(data)
            proactive_candidates = self._proactive_candidate_summary(data)
            token_stats = self._token_stats_payload(data.get("token_usage", {}))
            cache = self._cache_summary(data)
            tts = self._tts_runtime_summary(users)
            sqlite_status = await self._sqlite_wal_status_summary()
            all_sqlite_items: list[dict[str, Any]] = []
            for raw_item in sqlite_status.get("items", []) if isinstance(sqlite_status.get("items"), list) else []:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                if self._single_line(item.get("level"), 12) == "warn":
                    item["warning_code"] = "sqlite.wal"
                    item["warning_type"] = self._troubleshooting_semantic_warning_type("sqlite.wal")
                all_sqlite_items.append(item)
            sqlite_status = {**sqlite_status, "items": all_sqlite_items}
            passive_no_reply = self._passive_no_reply_summary(data)
            screen_companion = self._screen_companion_summary(data)
            qzone = self._qzone_summary(data)
            all_recent_events = self._troubleshooting_recent_events(
                diagnostics=diagnostics,
                proactive_tasks=proactive_tasks,
                proactive_candidates=proactive_candidates,
                token_stats=token_stats,
                passive_no_reply=passive_no_reply,
            )
            all_checks = self._troubleshooting_checks(
                data=data,
                users=users,
                groups=groups,
                diagnostics=diagnostics,
                proactive_tasks=proactive_tasks,
                proactive_candidates=proactive_candidates,
                token_stats=token_stats,
                cache=cache,
                tts=tts,
                sqlite_status=sqlite_status,
            )
            recent_events = self._filter_suppressed_troubleshooting_warnings(all_recent_events, suppressed_keys)
            checks = self._filter_suppressed_troubleshooting_warnings(all_checks, suppressed_keys)
            visible_sqlite_items = self._filter_suppressed_troubleshooting_warnings(all_sqlite_items, suppressed_keys)
            visible_sqlite_status = {**sqlite_status, "items": visible_sqlite_items}
            chain_tests, all_chain_warning_items = self._troubleshooting_chain_tests_with_warning_items(
                self._troubleshooting_test_results(data),
                suppressed_keys,
            )
            suppression_payload = self._troubleshooting_suppression_payload(
                suppression_records,
                all_diagnostics,
                all_recent_events,
                all_checks,
                all_sqlite_items,
                all_chain_warning_items,
            )
            active_suppressed_count = sum(self._int(item.get("current_count")) for item in suppression_payload)
            projection = self._troubleshooting_state_projection(diagnostics, checks, recent_events)
            counts = projection["current_counts"]
            headline_level = "error" if counts["error"] else ("warn" if counts["warn"] else "ok")
            headline = "发现需要处理的异常" if headline_level == "error" else (
                "有可关注项"
                if headline_level == "warn"
                else ("未发现未屏蔽异常" if active_suppressed_count else "运行状态正常")
            )
            return self._ok(
                {
                    "schema_version": 2,
                    "available": True,
                    "source_checked_at": time.time(),
                    "details_available": True,
                    "summary": {
                        "level": headline_level,
                        "headline": headline,
                        "counts": counts,
                        "current_counts": counts,
                        "history_counts": projection["history_counts"],
                        "suppressed_count": active_suppressed_count,
                        "suppressed_types": len(suppression_payload),
                        "generated_at": self.plugin._format_timestamp_elapsed(time.time()),
                    },
                    "recent_events": recent_events[:80],
                    "current_events": projection["current_events"],
                    "historical_events": projection["historical_events"],
                    "current_counts": counts,
                    "history_counts": projection["history_counts"],
                    "checks": checks,
                    "diagnostics": diagnostics,
                    "sqlite": visible_sqlite_status,
                    "chain_tests": chain_tests,
                    "recent_photo_generations": self._recent_photo_generation_summary(data),
                    "passive_no_reply": passive_no_reply,
                    "prompt_injections": self._prompt_injection_summary(data),
                    "screen_companion": screen_companion,
                    "qzone": qzone,
                    "proactive_intensity": self._proactive_intensity_summary(),
                    "proactive_runtime": proactive_tasks.get("runtime", {}),
                    "token_budget": token_stats.get("budget", {}),
                    "cache": cache,
                    "tts": tts,
                    "suppressed_warning_types": suppression_payload,
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取排障信息失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def _recover_stale_troubleshooting_proactive_test(self, *, max_age_seconds: int = 120) -> int:
        recovered = 0
        now = time.time()
        async with self.plugin._data_lock:
            users = self.plugin.data.get("users")
            if not isinstance(users, dict):
                return 0
            for user_id, user in list(users.items()):
                if not isinstance(user, dict):
                    continue
                if str(user.get("planned_proactive_source") or "") != "troubleshooting":
                    continue
                if not isinstance(user.get("troubleshooting_proactive_restore"), dict):
                    continue
                started = self._float(user.get("troubleshooting_proactive_started_at"))
                if started <= 0 or now - started <= max_age_seconds:
                    continue
                self.plugin._append_troubleshooting_proactive_step(
                    user,
                    "等待结果",
                    "error",
                    f"超过 {max_age_seconds} 秒仍未完成，已停止等待并恢复原主动计划",
                )
                self.plugin._record_troubleshooting_proactive_result(
                    str(user_id),
                    user,
                    ok=False,
                    detail="主动消息测试等待超时，已恢复原主动计划",
                    error=f"超过 {max_age_seconds} 秒仍未完成；请确认主动循环是否启动、目标用户是否有私聊会话、发送端是否可用",
                    action=str(user.get("planned_proactive_action") or "message"),
                    reason=str(user.get("planned_proactive_reason") or "check_in"),
                )
                user["proactive_sending"] = False
                user["proactive_sending_started_at"] = 0
                self.plugin._restore_troubleshooting_proactive_plan(user)
                recovered += 1
            if recovered:
                self.plugin._save_data_sync()
        return recovered

    async def run_troubleshooting_test(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        test_type = self._single_line(payload.get("type"), 40)
        start = time.time()
        try:
            if test_type == "proactive_message":
                await self._recover_stale_troubleshooting_proactive_test(max_age_seconds=120)
            if test_type in {"image_generation", "image_generation_text2img", "image_generation_selfie"}:
                image_payload = dict(payload)
                if test_type == "image_generation_text2img":
                    image_payload["workflow_kind"] = "text2img"
                elif test_type == "image_generation_selfie":
                    image_payload["workflow_kind"] = "selfie"
                result = await self._run_image_generation_chain_test(image_payload)
            elif test_type == "tts_generation":
                result = await self._run_tts_generation_chain_test(payload)
            elif test_type == "screen_peek":
                result = await self._run_screen_peek_chain_test(payload)
            elif test_type == "qzone_integration":
                result = await self._run_qzone_chain_test(payload)
            elif test_type == "proactive_message":
                result = await self._run_proactive_message_chain_test(payload)
            elif test_type in {"skill_similarity", "model_diagnostics"}:
                result = await self._run_model_diagnostics_check(payload)
            else:
                return self._error("未知排障测试类型")
        except Exception as exc:
            logger.warning("[PrivateCompanionPage] 排障链路测试失败: %s", self._single_line(exc, 160), exc_info=True)
            result = {
                "type": test_type,
                "ok": False,
                "title": self._troubleshooting_test_title(test_type),
                "error": str(exc),
            }
        result["type"] = test_type
        result["elapsed_ms"] = self._int(result.get("elapsed_ms")) or int((time.time() - start) * 1000)
        result["ran_at"] = time.time()
        result["ran_at_text"] = self.plugin._format_timestamp_elapsed(result["ran_at"])
        await self._remember_troubleshooting_test_result(test_type, result)
        return self._ok(result)

    async def _run_image_generation_chain_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._sync_photo_generation_runtime_config()
        generator = getattr(self.plugin, "_generate_photo_image", None)
        if not callable(generator):
            return {
                "ok": False,
                "title": "图片生成链路测试",
                "error": "插件缺少图片生成入口 _generate_photo_image",
            }
        reference_enabled = bool(getattr(self.plugin, "enable_photo_reference_image", False))
        reference_getter = getattr(self.plugin, "_photo_persona_reference_image_path", None)
        reference_image_path = ""
        if reference_enabled and callable(reference_getter):
            try:
                reference_image_path = self._single_line(reference_getter(), 260)
            except Exception:
                reference_image_path = ""
        configured_reference = self._single_line(getattr(self.plugin, "photo_persona_reference_image_path", ""), 1000).strip().strip('"').strip("'")
        has_reference_source = bool(reference_enabled and (reference_image_path or re.match(r"^https?://", configured_reference, flags=re.I)))
        workflow_kind = self._single_line(payload.get("workflow_kind"), 20)
        if not workflow_kind:
            workflow_kind = "selfie" if has_reference_source else "text2img"
        if workflow_kind in {"selfie", "portrait", "自拍", "人像"}:
            async_reference_getter = getattr(self.plugin, "_photo_persona_reference_image_for_kind_async", None)
            if callable(async_reference_getter):
                try:
                    reference_image_path = self._single_line(
                        await async_reference_getter(workflow_kind, allow_daily_outfit=True),
                        260,
                    )
                except Exception as exc:
                    logger.info(
                        "[PrivateCompanionPage] 自拍排障参考图解析失败: %s",
                        self._single_line(exc, 160),
                    )
        prompt_text = self._single_line(payload.get("prompt"), 600)
        if not prompt_text and workflow_kind in {"selfie", "portrait", "自拍", "人像"}:
            if reference_image_path:
                prompt_text = (
                    "排障测试自拍图，保持参考图中的人物身份和外观一致，手机随手自拍构图，"
                    "自然室内光，画面干净清晰，真实摄影风格，不包含文字水印"
                )
            else:
                prompt_text = (
                    "排障测试自拍图，一名角色面向镜头，手机随手自拍构图，"
                    "自然室内光，画面干净清晰，真实摄影风格，不包含文字水印"
                )
        if not prompt_text:
            role_appearance = self._troubleshooting_role_appearance_prompt()
            if role_appearance:
                prompt_text = (
                    f"画面主体是这个角色：{role_appearance}。"
                    "角色面向镜头，手举一个简洁的小牌子，牌子上只有一个绿色对钩符号，"
                    "室内日常背景，画面干净清晰，构图自然，真实摄影或精致插画质感；"
                    "不要出现其他文字、水印、额外人物或变形手。"
                )
            else:
                prompt_text = (
                    "排障测试图，一枚小小的绿色对勾贴纸放在白色桌面上，旁边有柔和台灯光，"
                    "画面干净清晰，真实摄影风格，不包含人物、不包含文字水印"
                )
        started = time.time()
        diagnostics = self._image_generation_timeout_diagnostics(
            workflow_kind=workflow_kind,
            has_reference_source=has_reference_source,
            reference_image_path=reference_image_path,
        )
        logger.info(
            "[PrivateCompanionPage] 图片生成排障测试开始: workflow_kind=%s prompt_chars=%s reference=%s timeout=%ss estimated=%ss prompt=%s",
            self._single_line(workflow_kind, 40),
            len(str(prompt_text or "")),
            has_reference_source,
            diagnostics.get("test_timeout_seconds"),
            diagnostics.get("estimated_timeout_seconds"),
            self._single_line(prompt_text, 180),
        )
        timeout = self._int(diagnostics.get("test_timeout_seconds"), 240, 45, 900)
        try:
            backend_name, image_path, note = await asyncio.wait_for(
                generator(
                    workflow_kind=workflow_kind,
                    prompt_text=prompt_text,
                    session_key="private_companion_troubleshooting",
                    reference_image_path=reference_image_path,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - started) * 1000)
            warnings = list(diagnostics.get("warnings") or [])
            timeout_targets = "在线 API、备用 API、参考图接口或本地工作流队列" if reference_image_path else "在线 API、备用 API 或本地工作流队列"
            warnings.insert(0, f"测试等待 {timeout}s 后仍未返回；实际链路可能卡在{timeout_targets}。")
            return {
                "ok": False,
                "title": "图片生成链路测试",
                "backend": "",
                "path": "",
                "file_size": 0,
                "detail": f"测试超时（{timeout}s）",
                "prompt": self._single_line(prompt_text, 220),
                "workflow_kind": self._single_line(workflow_kind, 20),
                "reference_image": self._single_line(reference_image_path, 260),
                "used_reference": False,
                "image_model": self._single_line(getattr(self.plugin, "external_image_api_model", ""), 80),
                "elapsed_ms": elapsed_ms,
                "error": f"测试超时（{timeout}s）",
                **diagnostics,
                "warnings": warnings[:8],
            }
        elapsed_ms = int((time.time() - started) * 1000)
        exists = False
        file_size = 0
        if image_path:
            try:
                image_file = Path(str(image_path))
                exists = image_file.exists()
                file_size = image_file.stat().st_size if exists else 0
            except Exception:
                exists = False
        logger.info(
            "[PrivateCompanionPage] 图片生成排障测试结束: ok=%s backend=%s elapsed=%sms path=%s exists=%s size=%s note=%s",
            bool(image_path and exists),
            self._single_line(backend_name, 80),
            elapsed_ms,
            self._single_line(image_path, 180),
            exists,
            file_size,
            self._single_line(note, 180),
        )
        return {
            "ok": bool(image_path and exists),
            "title": "图片生成链路测试",
            "backend": self._single_line(backend_name, 80),
            "path": self._single_line(image_path, 260),
            "file_size": file_size,
            "detail": self._single_line(note, 220) or ("已生成图片" if image_path else "未返回图片路径"),
            "prompt": self._single_line(prompt_text, 220),
            "workflow_kind": self._single_line(workflow_kind, 20),
            "reference_image": self._single_line(reference_image_path, 260),
            "used_reference": bool(
                reference_image_path
                and workflow_kind in {"selfie", "portrait", "自拍", "人像"}
                and "已使用" in str(note or "")
            ),
            "image_model": self._single_line(getattr(self.plugin, "external_image_api_model", ""), 80),
            "elapsed_ms": elapsed_ms,
            "error": "" if image_path and exists else (self._single_line(note, 220) or "图片生成未返回有效文件"),
            **diagnostics,
        }

    def _image_generation_timeout_diagnostics(
        self,
        *,
        workflow_kind: str,
        has_reference_source: bool,
        reference_image_path: str,
    ) -> dict[str, Any]:
        preferred = self._single_line(getattr(self.plugin, "photo_generation_backend", "auto"), 30).lower() or "auto"
        external_timeout = self._int(getattr(self.plugin, "external_image_api_timeout_seconds", 180), 180, 20, 600)
        backup_timeout = self._int(getattr(self.plugin, "backup_external_image_api_timeout_seconds", 180), 180, 20, 600)
        comfyui_wait = self._int(getattr(self.plugin, "comfyui_photo_wait_seconds", 90), 90, 5, 600)
        endpoint_queue: list[dict[str, Any]] = []
        queue_getter = getattr(self.plugin, "_external_image_api_endpoint_queue", None)
        if callable(queue_getter):
            try:
                endpoint_queue = [
                    endpoint
                    for endpoint in queue_getter(include_incomplete=True)
                    if isinstance(endpoint, dict) and endpoint.get("enabled", True)
                ]
            except Exception:
                endpoint_queue = []
        primary_external_configured = bool(
            getattr(self.plugin, "external_image_api_base_url", "")
            and getattr(self.plugin, "external_image_api_key", "")
            and getattr(self.plugin, "external_image_api_model", "")
        )
        backup_available = bool(getattr(self.plugin, "_backup_external_photo_available", lambda: False)())
        external_available = bool(getattr(self.plugin, "_external_photo_available", lambda: False)())
        comfyui_available = bool(getattr(self.plugin, "_comfyui_photo_available", lambda: False)())
        sdgen_available = bool(getattr(self.plugin, "_sdgen_photo_available", lambda: False)())
        tool_call_timeout = self._image_generation_tool_call_timeout_seconds()

        segments: list[tuple[str, int]] = []
        warnings: list[str] = []
        if preferred in {"auto", "external"} and external_available:
            if endpoint_queue:
                for index, endpoint in enumerate(endpoint_queue[:12]):
                    timeout_seconds = self._int(endpoint.get("timeout_seconds"), external_timeout, 20, 600)
                    name = self._single_line(endpoint.get("name") or endpoint.get("model") or f"在线图片 API #{index + 1}", 40)
                    segments.append((name, timeout_seconds * 2))
                if len(endpoint_queue) > 1:
                    warnings.append(
                        f"已配置 {len(endpoint_queue)} 条在线生图 API 队列：会按优先级逐条失败后再试下一条，完整失败链路会比单接口测试更慢。"
                    )
            else:
                segments.append(("主在线图片 API", external_timeout * 2))
                if backup_available:
                    segments.append(("备选在线图片 API", backup_timeout * 2))
                    warnings.append("已启用备选在线图片 API：主接口失败或超时后会再跑一轮备选接口，实际耗时可能明显长于单次测试观感。")
        if preferred in {"auto", "comfyui"} and comfyui_available:
            segments.append(("ComfyUI", comfyui_wait))
        if preferred in {"auto", "sdgen"} and sdgen_available:
            segments.append(("SDGen", 180))
            warnings.append("SDGen 调用由 SDGen 插件自身控制，本插件只能估算耗时，无法完全保证外层超时。")

        estimated = sum(seconds for _, seconds in segments) + 30
        if not segments:
            estimated = max(45, external_timeout + 30, comfyui_wait + 30)
        test_timeout = min(900, max(45, estimated + 30))
        if estimated + 30 > test_timeout:
            warnings.append(f"估算完整回退链路约 {estimated}s，排障测试外层最多等待 {test_timeout}s；极端慢链路仍可能被测试层截断。")
        if preferred == "auto" and len(segments) > 1:
            warnings.append("当前为自动后端：真实出图可能按在线 API、ComfyUI、SDGen 依次回退，测试通过只代表本次命中的那条链路可用。")
        if has_reference_source and workflow_kind not in {"selfie", "portrait", "自拍", "人像"}:
            warnings.append("已配置参考图，但本次测的是文生图；自拍、表情包、改图或 QQ 空间人物配图仍需单独测试参考图链路。")
        if workflow_kind in {"selfie", "portrait", "自拍", "人像"} and not reference_image_path and has_reference_source:
            warnings.append("检测到参考图配置，但本次没有解析到可用本地参考图；真实自拍可能会因下载/路径问题失败。")
        if external_available:
            warnings.append("在线图片 API 使用全局串行锁；多个生图请求同时发生时，后来的请求会先排队，单独点击测试无法覆盖排队等待。")
        if tool_call_timeout and estimated > tool_call_timeout:
            warnings.append(
                f"自然语言/主链工具调用可能受 AstrBot tool_call_timeout={tool_call_timeout}s 限制；"
                f"当前完整链路估算约 {estimated}s，测试能等到不代表 pc_generate_photo 工具一定不会超时。"
            )
        warnings.append("排障生图只检查生成文件，不覆盖后续发图、QQ 空间发布、记忆回写和主链工具调用耗时。")

        return {
            "timeout_seconds": test_timeout,
            "test_timeout_seconds": test_timeout,
            "estimated_timeout_seconds": estimated,
            "timeout_budget": " + ".join(f"{name}{seconds}s" for name, seconds in segments) or "未命中可用后端",
            "backend_preference": preferred,
            "external_timeout_seconds": external_timeout,
            "backup_external_timeout_seconds": backup_timeout,
            "comfyui_wait_seconds": comfyui_wait,
            "backup_external": backup_available,
            "external_queue_lock": external_available,
            "tool_call_timeout_seconds": tool_call_timeout,
            "warnings": warnings[:8],
        }

    def _image_generation_tool_call_timeout_seconds(self) -> int:
        context = getattr(self.plugin, "context", None)
        getter = getattr(context, "get_config", None)
        if not callable(getter):
            return 120
        try:
            cfg = getter()
        except Exception:
            return 120
        provider_settings = cfg.get("provider_settings", {}) if isinstance(cfg, dict) else {}
        if not isinstance(provider_settings, dict):
            return 120
        return self._int(provider_settings.get("tool_call_timeout"), 120, 1, 3600)

    def _troubleshooting_role_appearance_prompt(self) -> str:
        persona = str(getattr(self.plugin, "schedule_persona_prompt", "") or self._config_get("schedule_persona_prompt") or "")
        recognition = str(
            getattr(self.plugin, "private_image_self_recognition_hint", "")
            or self._config_get("private_image_self_recognition_hint")
            or ""
        )
        if not persona and not recognition:
            return ""
        label_prefix = {
            "姓名": "角色名",
            "种族": "种族",
            "性别": "性别",
            "识别点": "主要识别点",
            "外貌": "外貌",
            "主要识别点": "主要识别点",
            "发型发色": "发型发色",
            "发色": "发色",
            "发型": "发型",
            "瞳色": "瞳色",
            "眼睛": "眼睛",
            "服饰风格": "服饰风格",
            "服装": "服装",
            "衣着": "衣着",
        }
        visual_labels = {
            "识别点",
            "外貌",
            "主要识别点",
            "发型发色",
            "发色",
            "发型",
            "瞳色",
            "眼睛",
            "服饰风格",
            "服装",
            "衣着",
        }
        parts: list[str] = []
        has_visual = bool(recognition)
        for line in str(persona or "").replace("\r", "\n").split("\n"):
            text = line.strip()
            if not text or ("：" not in text and ":" not in text):
                continue
            label, value = text.split("：", 1) if "：" in text else text.split(":", 1)
            label = label.strip()
            value = self._single_line(value, 140)
            if label in label_prefix and value:
                if label in visual_labels:
                    has_visual = True
                parts.append(f"{label_prefix[label]}：{value}")
        if recognition:
            parts.append(f"补充识别线索{self._single_line(recognition, 180)}")
        if not has_visual:
            return ""
        seen: set[str] = set()
        unique = []
        for item in parts:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return self._single_line("，".join(unique), 420)

    async def _run_screen_peek_chain_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        getter = getattr(self.plugin, "_get_screen_companion_plugin", None)
        screen_plugin = getter() if callable(getter) else None
        if screen_plugin is None or not callable(getattr(screen_plugin, "_invoke_screen_skill", None)):
            return {
                "ok": False,
                "title": "窥屏链路测试",
                "error": "未检测到可用的 screen_companion 插件或识屏入口",
            }
        async with self.plugin._data_lock:
            users = deepcopy(self.plugin.data.get("users") if isinstance(self.plugin.data.get("users"), dict) else {})
        umo = self._single_line(payload.get("umo"), 180) or self._preferred_tts_test_umo(users)
        event = None
        if umo and callable(getattr(screen_plugin, "_create_virtual_event", None)):
            try:
                event = screen_plugin._create_virtual_event(umo)
            except Exception as exc:
                logger.info(
                    "[PrivateCompanionPage] 窥屏排障虚拟事件创建失败,将无事件调用: umo=%s error=%s",
                    self._single_line(umo, 120),
                    self._single_line(exc, 120),
                )
        prompt = self._single_line(payload.get("prompt"), 500) or (
            "这是一次插件排障中心发起的授权识屏链路测试。请只判断当前屏幕观察能力是否可用，"
            "用一句很短的内部摘要描述大概画面类型；不要输出账号、完整聊天内容、隐私细节或长文本。"
        )
        started = time.time()
        try:
            raw_result = await asyncio.wait_for(
                screen_plugin._invoke_screen_skill(
                    event,
                    request_prompt=prompt,
                    history_user_text="Private Companion 排障中心正在测试 screen_companion 识屏链路。",
                    task_id="private_companion_troubleshooting_screen_peek",
                ),
                timeout=max(15, self._int(payload.get("timeout_seconds"), 60, 5, 180)),
            )
        except Exception as exc:
            elapsed_ms = int((time.time() - started) * 1000)
            error = self._single_line(exc, 220)
            logger.warning("[PrivateCompanionPage] 窥屏排障测试失败: %s", error, exc_info=True)
            return {
                "ok": False,
                "title": "窥屏链路测试",
                "umo": umo,
                "elapsed_ms": elapsed_ms,
                "error": error or repr(exc),
            }
        elapsed_ms = int((time.time() - started) * 1000)
        context = "screen_peek：\n" + (self._single_line(raw_result, 500) if raw_result else "没有得到屏幕观察结果")
        unusable_checker = getattr(self.plugin, "_is_unusable_screen_peek_context", None)
        unusable = bool(unusable_checker(context)) if callable(unusable_checker) else not bool(raw_result)
        preview = self._single_line(raw_result, 220)
        logger.info(
            "[PrivateCompanionPage] 窥屏排障测试结束: ok=%s elapsed=%sms umo=%s preview=%s",
            not unusable,
            elapsed_ms,
            self._single_line(umo, 120),
            preview,
        )
        return {
            "ok": not unusable,
            "title": "窥屏链路测试",
            "umo": umo,
            "provider": "screen_companion",
            "detail": "已成功获得屏幕观察摘要" if not unusable else "识屏返回为空或不可用结果",
            "text_preview": preview,
            "context_chars": len(str(raw_result or "")),
            "elapsed_ms": elapsed_ms,
            "error": "" if not unusable else (preview or "没有得到屏幕观察结果"),
        }

    async def _run_qzone_chain_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, str]] = []

        def add_step(name: str, status: str, detail: str) -> None:
            steps.append(
                {
                    "name": self._single_line(name, 40),
                    "status": self._single_line(status, 16),
                    "detail": self._single_line(detail, 180),
                }
            )

        started = time.time()
        service_available = bool(
            callable(getattr(self.plugin, "_test_qzone_integration", None))
            and callable(getattr(self.plugin, "_qzone_get_cookies", None))
        )
        enabled = bool(getattr(self.plugin, "enable_qzone_integration", False))
        comment_enabled = bool(getattr(self.plugin, "enable_qzone_comment_inbox", False))
        add_step("内置服务", "ok" if service_available else "error", "可用" if service_available else "QQ 空间模块入口不可用")
        add_step("整合开关", "ok" if enabled else "warn", "已开启" if enabled else "已关闭")
        if not service_available or not enabled:
            return {
                "ok": False,
                "title": "QQ 空间链路测试",
                "provider": "qzone",
                "detail": "QQ 空间整合未启用或模块入口不可用",
                "text_preview": "开启 QQ 空间整合后再测试 Cookie、读取和发布工具链路。",
                "steps": steps,
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": "QQ 空间整合未启用或模块入口不可用",
            }

        target_id = self._single_line(payload.get("target_id"), 40)
        read_text = ""
        read_ok = False
        read_detail = ""
        reader = getattr(self.plugin, "_test_qzone_integration", None)
        if callable(reader):
            try:
                read_text = await asyncio.wait_for(
                    reader(None, target_id=target_id),
                    timeout=max(15, self._int(payload.get("timeout_seconds"), 45, 10, 180)),
                )
                read_ok = ("读取链路正常" in read_text) or ("读取链路可调用" in read_text)
                read_detail = (
                    (self._qzone_test_line_with_prefix(read_text, "查询结果：失败") if not read_ok else "")
                    or self._qzone_test_last_result_line(read_text)
                    or self._single_line(read_text, 180)
                )
                add_step("Cookie/读取", "ok" if read_ok else "error", read_detail or "读取测试未返回明确结果")
            except Exception as exc:
                read_detail = self._single_line(exc, 180)
                add_step("Cookie/读取", "error", read_detail or "读取测试异常")
        else:
            add_step("Cookie/读取", "error", "缺少 _test_qzone_integration 测试入口")

        publish_ok = False
        publish_detail = ""
        publisher = getattr(self.plugin, "_pc_qzone_publish_feed_impl", None)
        if callable(publisher):
            try:
                raw = await asyncio.wait_for(publisher(None, ""), timeout=15)
                parsed = json.loads(raw) if isinstance(raw, str) else {}
                status = self._single_line(parsed.get("status"), 40) if isinstance(parsed, dict) else ""
                message = self._single_line(parsed.get("message"), 160) if isinstance(parsed, dict) else self._single_line(raw, 160)
                publish_ok = status == "need_text"
                publish_detail = "空参数返回 need_text，发布工具入口正常" if publish_ok else (message or f"返回 {status or '未知状态'}")
                add_step("发布模拟", "ok" if publish_ok else "warn", publish_detail)
            except Exception as exc:
                publish_detail = self._single_line(exc, 180)
                add_step("发布模拟", "error", publish_detail or "发布工具空参数测试异常")
        else:
            add_step("发布模拟", "warn", "缺少发布工具入口，无法测试空参数模拟")

        async with self.plugin._data_lock:
            qzone_state = deepcopy(
                self.plugin.data.get("qzone_integration")
                if isinstance(self.plugin.data.get("qzone_integration"), dict)
                else {}
            )
        list_len = lambda key: len(qzone_state.get(key)) if isinstance(qzone_state.get(key), list) else 0
        seen_count = list_len("comment_inbox_seen_ids") + list_len("comment_inbox_seen_keys")
        replied_count = list_len("comment_inbox_replied_ids") + list_len("comment_inbox_replied_keys")
        inbox_status = self._single_line(qzone_state.get("last_comment_inbox_status"), 120)
        inbox_detail = (
            f"{'已开启' if comment_enabled else '未开启'}；已见 {seen_count}，已回复 {replied_count}"
            + (f"；最近 {inbox_status}" if inbox_status else "")
        )
        add_step("评论收件箱", "ok" if comment_enabled else "info", inbox_detail)

        ok = bool(read_ok and publish_ok)
        preview_parts = [
            read_detail,
            publish_detail,
            inbox_detail,
        ]
        if read_text:
            preview_parts.append(self._single_line(read_text, 500))
        return {
            "ok": ok,
            "title": "QQ 空间链路测试",
            "provider": "qzone",
            "detail": "QQ 空间读取和发布模拟正常" if ok else "QQ 空间链路存在需要处理的项",
            "text_preview": self._single_line("；".join(part for part in preview_parts if part), 500),
            "steps": steps,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": "" if ok else (read_detail or publish_detail or "QQ 空间链路测试未通过"),
        }

    @staticmethod
    def _qzone_test_last_result_line(text: str) -> str:
        for line in reversed(str(text or "").replace("\r", "\n").split("\n")):
            clean = line.strip().lstrip("-").strip()
            if clean.startswith("结果："):
                return clean
        return ""

    @staticmethod
    def _qzone_test_line_with_prefix(text: str, prefix: str) -> str:
        for line in str(text or "").replace("\r", "\n").split("\n"):
            clean = line.strip().lstrip("-").strip()
            if clean.startswith(prefix):
                return clean
        return ""

    async def _run_tts_generation_chain_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = getattr(self.plugin, "context", None)
        if context is None:
            return {
                "ok": False,
                "title": "TTS 生成链路测试",
                "error": "AstrBot context 不可用",
            }
        async with self.plugin._data_lock:
            users = deepcopy(self.plugin.data.get("users") if isinstance(self.plugin.data.get("users"), dict) else {})
        umo = self._single_line(payload.get("umo"), 180) or self._preferred_tts_test_umo(users)
        config: dict[str, Any] = {}
        getter = getattr(context, "get_config", None)
        if callable(getter):
            try:
                config = getter(umo) if umo else getter()
                if not isinstance(config, dict):
                    config = {}
            except Exception:
                config = {}
        provider_getter = getattr(context, "get_using_tts_provider", None)
        tts_provider = None
        if callable(provider_getter):
            try:
                tts_provider = provider_getter(umo) if umo else provider_getter()
            except Exception:
                tts_provider = None
        if tts_provider is None:
            return {
                "ok": False,
                "title": "TTS 生成链路测试",
                "umo": umo,
                "error": "当前会话没有可用 TTS provider",
            }
        provider_settings = dict((config or {}).get("provider_tts_settings", {}) or {})
        spoken = self._single_line(payload.get("text"), 240) or "这是一条排障测试语音，用来确认 TTS 生成链路可以跑通。"
        record_builder = getattr(self.plugin, "_tts_record_component", None)
        started = time.time()
        if callable(record_builder):
            component = await record_builder(
                spoken,
                tts_provider,
                provider_settings,
                config,
                source_text=spoken,
            )
            refs_getter = getattr(self.plugin, "_tts_record_refs", None)
            refs = refs_getter(component) if callable(refs_getter) and component is not None else []
        else:
            audio_path = await tts_provider.get_audio(spoken)
            component = None
            refs = [str(audio_path)] if audio_path else []
        elapsed_ms = int((time.time() - started) * 1000)
        audio_ref = self._single_line(refs[0] if refs else "", 260)
        exists = False
        file_size = 0
        if audio_ref and not re.match(r"^https?://", audio_ref, flags=re.IGNORECASE):
            try:
                audio_file = Path(audio_ref)
                exists = audio_file.exists()
                file_size = audio_file.stat().st_size if exists else 0
            except Exception:
                exists = False
        else:
            exists = bool(audio_ref)
        provider_id = self._provider_id(tts_provider)
        provider_label = self._provider_name(tts_provider, provider_id) if provider_id else getattr(tts_provider, "__class__", type(tts_provider)).__name__
        return {
            "ok": bool(audio_ref and exists),
            "title": "TTS 生成链路测试",
            "umo": umo,
            "provider": self._single_line(provider_label, 100),
            "path": audio_ref,
            "file_size": file_size,
            "detail": "已生成语音组件" if component is not None else "已调用 TTS provider 生成音频",
            "text": spoken,
            "elapsed_ms": elapsed_ms,
            "error": "" if audio_ref and exists else "TTS provider 未返回有效音频文件",
        }

    async def _run_proactive_message_chain_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, str]] = []

        def add_step(name: str, status: str, detail: str = "") -> None:
            steps.append(
                {
                    "name": self._single_line(name, 40),
                    "status": self._single_line(status, 16) or "info",
                    "detail": self._single_line(detail, 180),
                }
            )

        context = getattr(self.plugin, "context", None)
        if context is None:
            add_step("上下文", "error", "AstrBot context 不可用")
            return {
                "ok": False,
                "title": "主动消息链路测试",
                "steps": steps,
                "error": "AstrBot context 不可用",
            }

        target_user_id = self._single_line(payload.get("user_id"), 80)
        async with self.plugin._data_lock:
            users = deepcopy(self.plugin.data.get("users") if isinstance(self.plugin.data.get("users"), dict) else {})
        target_user_id, target_user = self._preferred_proactive_test_user(users, target_user_id)
        if not target_user_id or not target_user:
            add_step("目标会话", "error", "没有找到已启用且带私聊会话的私聊对象")
            return {
                "ok": False,
                "title": "主动消息链路测试",
                "steps": steps,
                "error": "没有找到可用于测试的私聊对象",
            }
        umo = self._single_line(target_user.get("umo"), 180)
        if not umo:
            add_step("目标会话", "error", "目标用户缺少 umo")
            return {
                "ok": False,
                "title": "主动消息链路测试",
                "user_id": target_user_id,
                "steps": steps,
                "error": "目标用户缺少私聊会话",
            }
        add_step("目标会话", "ok", f"用户 {target_user.get('nickname') or target_user_id} / {umo}")

        now = time.time()
        delay_seconds = self._int(payload.get("delay_seconds"), 60, 5, 300)
        scheduled_ts = now + delay_seconds
        test_id = secrets.token_hex(6)
        plan_keys = (
            "next_proactive_at",
            "planned_proactive_reason",
            "planned_proactive_action",
            "planned_proactive_source",
            "planned_proactive_motive",
            "planned_proactive_topic",
            "planned_proactive_impulse_id",
            "planned_proactive_window_start_at",
            "planned_proactive_best_until_at",
            "planned_proactive_expire_at",
            "planned_proactive_origin_at",
            "planned_proactive_origin_key",
            "planned_proactive_freshness",
            "planned_proactive_delivery_state",
            "planned_proactive_semantic_kind",
            "planned_proactive_anchor_type",
            "planned_proactive_semantic_score",
            "planned_proactive_semantic_note",
            "planned_proactive_model_judge_signature",
            "planned_proactive_model_judge_result",
            "planned_proactive_model_judge_at",
            "planned_event_chain",
            "planned_opener_mode",
            "planned_followup_kind",
            "planned_proactive_quota_exempt",
            "planned_candidate_id",
            "planned_proactive_trigger_message_id",
            "planned_proactive_trigger_umo",
            "planned_proactive_trigger_ts",
            "planned_proactive_trigger_inbound_count",
            "planned_proactive_trigger_created_at",
            "llm_timer_event",
            "sent_today",
            "proactive_sent_count",
            "ignored_streak",
            "awaiting_reply_since",
            "last_sent",
            "last_companion_message",
            "last_proactive_reason",
            "last_proactive_action",
            "last_proactive_behavior_summary",
            "last_proactive_motive",
            "recent_proactive_topics",
            "proactive_daypart_counts",
            "proactive_afterglow",
            "recent_proactive_afterglows",
            "recent_proactive_hesitations",
            "last_proactive_hesitation_at",
            "last_proactive_hesitation_note",
            "state_continuity",
            "pending_followup_event",
            "suspended_proactive",
            "poke_daily_limit",
            "photo_daily_limit",
            "screen_peek_daily_limit",
        )

        async with self.plugin._data_lock:
            current = self.plugin._get_user(target_user_id)
            if not isinstance(current, dict) or not current.get("enabled", True):
                add_step("临时任务", "error", "目标私聊对象未启用")
                return {
                    "ok": False,
                    "title": "主动消息链路测试",
                    "user_id": target_user_id,
                    "umo": umo,
                    "steps": steps,
                    "error": "目标私聊对象未启用",
                }
            if current.get("proactive_sending"):
                add_step("临时任务", "error", "该用户已有主动发送正在进行")
                return {
                    "ok": False,
                    "title": "主动消息链路测试",
                    "user_id": target_user_id,
                    "umo": umo,
                    "steps": steps,
                    "error": "该用户已有主动发送正在进行",
                }
            if (
                str(current.get("planned_proactive_source") or "") == "troubleshooting"
                and isinstance(current.get("troubleshooting_proactive_restore"), dict)
            ):
                existing_steps = current.get("troubleshooting_proactive_steps") if isinstance(current.get("troubleshooting_proactive_steps"), list) else []
                return {
                    "ok": True,
                    "pending": True,
                    "title": "主动消息链路测试",
                    "user_id": target_user_id,
                    "umo": umo,
                    "steps": existing_steps,
                    "detail": "已有一个排障临时主动任务在等待执行，请稍后刷新查看结果",
                    "action": "message",
                    "reason": self._single_line(current.get("planned_proactive_reason"), 40) or "check_in",
                    "error": "",
                }
            restore = {
                "values": {key: deepcopy(current[key]) for key in plan_keys if key in current},
                "missing": [key for key in plan_keys if key not in current],
            }
            current["troubleshooting_proactive_restore"] = restore
            current["troubleshooting_proactive_test_id"] = test_id
            current["troubleshooting_proactive_started_at"] = now
            current["troubleshooting_proactive_steps"] = [
                {"name": "目标会话", "status": "ok", "detail": f"用户 {current.get('nickname') or target_user_id} / {umo}"},
                {"name": "临时任务", "status": "ok", "detail": f"已预约 {delay_seconds} 秒后由主动循环执行"},
            ]
            current["user_id"] = str(current.get("user_id") or target_user_id)
            current["umo"] = umo
            self.plugin._reset_planned_proactive_delivery_state(current)
            current["next_proactive_at"] = scheduled_ts
            current["planned_proactive_reason"] = "check_in"
            current["planned_proactive_action"] = "message"
            current["planned_proactive_source"] = "troubleshooting"
            current["planned_proactive_motive"] = "对方希望你主动来找一下,轻轻开口确认主动消息链路能正常工作。"
            current["planned_proactive_topic"] = "主动来找对方一下"
            current["planned_proactive_impulse_id"] = ""
            current["planned_proactive_window_start_at"] = scheduled_ts
            active_span, grace_span = self.plugin._proactive_impulse_default_window_seconds("check_in")
            current["planned_proactive_best_until_at"] = scheduled_ts + active_span
            current["planned_proactive_expire_at"] = scheduled_ts + active_span + grace_span
            semantics = self.plugin._planned_proactive_semantics(current)
            current["planned_proactive_semantic_kind"] = self._single_line(semantics.get("kind"), 40)
            current["planned_proactive_anchor_type"] = self._single_line(semantics.get("anchor_type"), 40)
            current["planned_proactive_semantic_score"] = int(max(0.0, min(1.0, self._float(semantics.get("score")))) * 100)
            current["planned_proactive_semantic_note"] = self._single_line(semantics.get("note"), 180)
            current["planned_event_chain"] = []
            current["planned_opener_mode"] = ""
            current["planned_followup_kind"] = ""
            current["planned_proactive_quota_exempt"] = True
            current["planned_candidate_id"] = f"troubleshooting_{test_id}"
            current["llm_timer_event"] = {}
            current["poke_daily_limit"] = 0
            current["photo_daily_limit"] = 0
            current["screen_peek_daily_limit"] = 0
            result = {
                "ok": True,
                "pending": True,
                "title": "主动消息链路测试",
                "user_id": target_user_id,
                "umo": umo,
                "steps": list(current["troubleshooting_proactive_steps"]),
                "detail": f"已预约 {delay_seconds} 秒后的排障临时主动任务；到点后由主动循环走完整生成、复核、发送和归档流程",
                "action": "message",
                "reason": "check_in",
                "error": "",
            }
            raw = self.plugin.data.setdefault("troubleshooting_test_results", {})
            if not isinstance(raw, dict):
                raw = {}
                self.plugin.data["troubleshooting_test_results"] = raw
            raw["proactive_message"] = self._sanitize_troubleshooting_test_result(result)
            self.plugin._save_data_sync()
        add_step("临时任务", "ok", f"已预约 {delay_seconds} 秒后由主动循环执行")
        return result

    def _preferred_tts_test_umo(self, users: dict[str, Any]) -> str:
        fallback = ""
        for user_id, item in users.items():
            if not isinstance(item, dict) or not item.get("enabled", True) or not item.get("umo"):
                continue
            umo = self._single_line(item.get("umo"), 180)
            if not fallback:
                fallback = umo
            if self.plugin._private_user_role(item, str(item.get("user_id") or user_id)) == "owner":
                return umo
        return fallback

    def _preferred_proactive_test_user(
        self,
        users: dict[str, Any],
        preferred_user_id: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        if preferred_user_id:
            item = users.get(preferred_user_id)
            if isinstance(item, dict) and item.get("enabled", True) and item.get("umo"):
                item = deepcopy(item)
                item["user_id"] = str(item.get("user_id") or preferred_user_id)
                return preferred_user_id, item
        fallback: tuple[str, dict[str, Any] | None] = ("", None)
        for user_id, item in users.items():
            if not isinstance(item, dict) or not item.get("enabled", True) or not item.get("umo"):
                continue
            candidate = deepcopy(item)
            candidate["user_id"] = str(candidate.get("user_id") or user_id)
            if not fallback[0]:
                fallback = (str(user_id), candidate)
            if self.plugin._private_user_role(candidate, str(candidate.get("user_id") or user_id)) == "owner":
                return str(user_id), candidate
        return fallback

    async def _run_skill_similarity_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run_model_diagnostics_check(payload)

    async def _run_model_diagnostics_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        use_model = self._normalize_bool_value(payload.get("use_model", True))
        async with self.plugin._data_lock:
            data = deepcopy(self.plugin.data)
        skill_items = self._skill_similarity_local_candidates(data)
        slang_items = self._model_diagnostics_slang_candidates(data)
        pending_items = self._model_diagnostics_pending_observation_candidates(data)
        memory_items = self._model_diagnostics_companion_memory_candidates(data)
        expression_items = self._model_diagnostics_expression_candidates(data)
        total_local = len(skill_items) + len(slang_items) + len(pending_items) + len(memory_items) + len(expression_items)
        sections: list[dict[str, Any]] = [
            {
                "key": "skills",
                "title": "技能相似项",
                "local_count": len(skill_items),
                "model_count": 0,
                "suggestions": [
                    f"技能｜{item.get('a')} ↔ {item.get('b')}：{item.get('reason')}"
                    for item in skill_items[:4]
                ],
            },
            {
                "key": "slang",
                "title": "群黑话杂音",
                "local_count": len(slang_items),
                "model_count": 0,
                "suggestions": [
                    f"黑话｜{item.get('group_name') or item.get('group_id')}｜{item.get('term')}：{item.get('reason')}"
                    for item in slang_items[:4]
                ],
            },
            {
                "key": "worldbook",
                "title": "关系网待确认观察",
                "local_count": len(pending_items),
                "model_count": 0,
                "suggestions": [
                    f"关系网｜{item.get('name') or item.get('user_id')}：{item.get('reason')}｜{item.get('evidence')}"
                    for item in pending_items[:4]
                ],
            },
            {
                "key": "memory",
                "title": "长期画像噪音",
                "local_count": len(memory_items),
                "model_count": 0,
                "suggestions": [
                    f"长期画像｜{item.get('name') or item.get('user_id')}｜{item.get('field')}：{item.get('reason')}｜{item.get('text')}"
                    for item in memory_items[:4]
                ],
            },
            {
                "key": "expression",
                "title": "表达学习污染",
                "local_count": len(expression_items),
                "model_count": 0,
                "suggestions": [
                    f"表达学习｜{item.get('name') or item.get('user_id')}：{item.get('reason')}｜{item.get('text')}"
                    for item in expression_items[:4]
                ],
            },
        ]
        steps: list[dict[str, str]] = [
            {
                "name": "本地规则",
                "status": "ok" if total_local else "info",
                "detail": (
                    (
                        f"发现 {total_local} 条候选：技能 {len(skill_items)}、黑话 {len(slang_items)}、"
                        f"关系网 {len(pending_items)}、长期画像 {len(memory_items)}、表达学习 {len(expression_items)}"
                    )
                    if total_local
                    else "未发现明显技能冲突、黑话杂音、无效关系观察或私聊学习污染"
                ),
            }
        ]
        model_items: list[str] = []
        provider_id = ""
        if use_model and total_local:
            caller = getattr(self.plugin, "_llm_call", None)
            if callable(caller):
                provider_selector = getattr(self.plugin, "_task_provider", None)
                if callable(provider_selector):
                    provider_id = provider_selector(
                        getattr(self.plugin, "troubleshooting_provider_id", ""),
                        getattr(self.plugin, "response_review_provider_id", ""),
                        getattr(self.plugin, "mai_style_provider_id", ""),
                        getattr(self.plugin, "llm_provider_id", ""),
                    )
                else:
                    provider_id = str(
                        getattr(self.plugin, "troubleshooting_provider_id", "")
                        or getattr(self.plugin, "response_review_provider_id", "")
                        or getattr(self.plugin, "mai_style_provider_id", "")
                        or getattr(self.plugin, "llm_provider_id", "")
                        or ""
                    )
                prompt = self._model_diagnostics_review_prompt(
                    data,
                    skill_items,
                    slang_items,
                    pending_items,
                    memory_items,
                    expression_items,
                )
                try:
                    raw = await caller(
                        prompt,
                        max_tokens=700,
                        provider_id=provider_id,
                        task="troubleshooting_model_diagnostics",
                    )
                    model_items = self._parse_skill_similarity_model_result(raw)
                    self._attach_model_diagnostics_section_suggestions(sections, model_items)
                    steps.append(
                        {
                            "name": "模型复核",
                            "status": "ok" if model_items else "info",
                            "detail": f"模型给出 {len(model_items)} 条建议" if model_items else "模型未给出额外排障建议",
                        }
                    )
                except Exception as exc:
                    steps.append({"name": "模型复核", "status": "warn", "detail": f"调用失败: {self._single_line(exc, 120)}"})
            else:
                steps.append({"name": "模型复核", "status": "warn", "detail": "插件缺少 _llm_call，无法调用模型"})
        elif not use_model:
            steps.append({"name": "模型复核", "status": "info", "detail": "本次按请求仅执行本地规则检查"})
        elif not total_local:
            steps.append({"name": "模型复核", "status": "info", "detail": "没有本地候选，未调用模型"})

        local_preview = []
        for section in sections:
            local_preview.extend(section.get("suggestions") if isinstance(section.get("suggestions"), list) else [])
        all_suggestions = [*local_preview]
        for item in model_items:
            if item not in all_suggestions:
                all_suggestions.append(item)
        detail = (
            f"本地发现 {total_local} 条候选，模型给出 {len(model_items)} 条建议"
            if all_suggestions
            else "模型相关数据目前没有明显杂音"
        )
        return {
            "ok": True,
            "title": "模型数据排障",
            "provider": self._single_line(provider_id, 100),
            "detail": self._single_line(detail, 220),
            "text_preview": self._single_line(" | ".join(all_suggestions[:5]), 220),
            "suggestions": [self._single_line(item, 220) for item in all_suggestions[:12]],
            "sections": sections,
            "local_count": total_local,
            "model_count": len(model_items),
            "suggestion_count": len(all_suggestions),
            "extra_count": max(0, len(all_suggestions) - 5),
            "steps": steps,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": "",
        }

    def _skill_similarity_local_candidates(self, data: dict[str, Any]) -> list[dict[str, str]]:
        state = data.get("skill_growth") if isinstance(data.get("skill_growth"), dict) else {}
        skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
        generic_terms = {
            "学习",
            "上课",
            "下课",
            "作业",
            "复习",
            "预习",
            "考试",
            "测验",
            "练习",
            "刷题",
            "做题",
            "题目",
            "课堂",
            "课程",
            "笔记",
            "讲题",
            "错题",
            "背诵",
            "背书",
            "阅读",
            "听课",
            "训练",
        }
        items: list[dict[str, Any]] = []
        for raw in skills.values():
            if not isinstance(raw, dict):
                continue
            name = self._single_line(raw.get("name"), 32)
            if not name:
                continue
            keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
            aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
            keyword_terms: set[str] = set()
            for raw_term in keywords:
                term = self._single_line(raw_term, 24)
                if term and term not in generic_terms:
                    keyword_terms.add(term)
            identity_terms: set[str] = set()
            for raw_term in [name, *aliases]:
                term = self._single_line(raw_term, 24)
                if term:
                    identity_terms.add(term)
            items.append(
                {
                    "name": name,
                    "category": self._single_line(raw.get("category"), 24),
                    "hidden": bool(raw.get("hidden")),
                    "frozen": bool(raw.get("frozen")),
                    "keyword_terms": keyword_terms,
                    "identity_terms": identity_terms,
                }
            )
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for idx, left in enumerate(items):
            for right in items[idx + 1:]:
                reason = ""
                if left["name"] == right["name"]:
                    reason = "名称完全重复"
                elif left["name"] in right["identity_terms"] or right["name"] in left["identity_terms"]:
                    reason = "名称与对方合并别名冲突"
                elif len(left["name"]) >= 2 and len(right["name"]) >= 2 and (left["name"] in right["name"] or right["name"] in left["name"]):
                    reason = "名称相互包含"
                else:
                    overlap = left["keyword_terms"] & right["keyword_terms"]
                    if left["category"] and left["category"] == right["category"] and len(overlap) >= 3:
                        reason = f"同分类专有关键词重叠: {'、'.join(sorted(overlap)[:4])}"
                if not reason:
                    continue
                key = tuple(sorted([left["name"], right["name"]]) + [reason])
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({"a": left["name"], "b": right["name"], "reason": reason})
        return candidates[:12]

    def _model_diagnostics_slang_candidates(self, data: dict[str, Any]) -> list[dict[str, str]]:
        groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
        common_terms = {
            "什么",
            "这个",
            "那个",
            "就是",
            "可以",
            "没有",
            "真的",
            "一下",
            "今天",
            "明天",
            "昨天",
            "然后",
            "现在",
            "等等",
            "不是",
            "因为",
            "所以",
            "但是",
            "感觉",
            "可能",
            "应该",
            "好像",
            "知道",
            "看看",
            "消息",
            "图片",
        }
        reaction_terms = {"哈哈", "哈哈哈", "笑死", "草", "好的", "收到", "嗯嗯", "啊啊", "救命", "失败", "报错"}
        media_markers = ("[图片]", "[视频]", "[语音]", "[表情]", "[文件]", "[CQ:", "http://", "https://")
        candidates: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for group_id, group in groups.items():
            if not isinstance(group, dict):
                continue
            group_name = self._single_line(group.get("name") or group.get("group_name") or group_id, 40)
            terms = group.get("slang_terms") if isinstance(group.get("slang_terms"), list) else []
            meanings = group.get("slang_meanings") if isinstance(group.get("slang_meanings"), dict) else {}
            indexed: list[dict[str, Any]] = []
            for raw in terms:
                if isinstance(raw, dict):
                    indexed.append(raw)
                else:
                    indexed.append({"term": raw})
            for raw in indexed[:160]:
                term = self._single_line(raw.get("term") if isinstance(raw, dict) else raw, 50)
                if not term:
                    continue
                if isinstance(raw, dict) and self._single_line(raw.get("source"), 20) == "manual":
                    continue
                compact = re.sub(r"\s+", "", term)
                reason = ""
                if any(marker.lower() in term.lower() for marker in media_markers):
                    reason = "像媒体占位或链接，不像黑话"
                elif re.fullmatch(r"\d{5,}", compact):
                    reason = "像纯数字 ID，不像黑话"
                elif compact in common_terms:
                    reason = "像普通高频词，不像群内黑话"
                elif compact in reaction_terms:
                    reason = "像一次性语气/反应词，容易污染黑话"
                elif len(compact) <= 1 and not re.fullmatch(r"[a-zA-Z]+", compact):
                    reason = "过短，缺少可解释语义"
                elif len(compact) >= 18 and re.search(r"[。！？!?，,]", term):
                    reason = "像整句聊天内容，不像词条"
                else:
                    raw_meaning = meanings.get(term) if isinstance(meanings.get(term), dict) else {}
                    meaning = self._single_line(raw_meaning.get("meaning"), 80) if isinstance(raw_meaning, dict) else ""
                    confidence = self._float(raw_meaning.get("confidence")) if isinstance(raw_meaning, dict) else 0.0
                    count = self._int(raw.get("count")) if isinstance(raw, dict) else 0
                    if meaning and confidence < 0.35 and count <= 2:
                        reason = "低频且释义置信度很低"
                    elif meaning and any(marker in meaning for marker in ("无法判断", "语境不明", "不确定")) and count <= 2:
                        reason = "释义长期不确定，建议复核"
                if not reason:
                    continue
                key = (str(group_id), term)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "group_id": self._single_line(group_id, 40),
                        "group_name": group_name,
                        "term": term,
                        "reason": reason,
                        "count": str(self._int(raw.get("count")) if isinstance(raw, dict) else 0),
                    }
                )
                if len(candidates) >= 24:
                    return candidates
        return candidates

    def _model_diagnostics_pending_observation_candidates(self, data: dict[str, Any]) -> list[dict[str, str]]:
        profiles = data.get("worldbook_member_profiles") if isinstance(data.get("worldbook_member_profiles"), dict) else {}
        generic_reactions = {"哈哈", "哈哈哈", "笑死", "草", "好的", "收到", "嗯嗯", "啊啊啊", "救命", "离谱", "不是吧"}
        log_markers = ("Traceback", "[ERROR]", "[WARN]", "Exception", "File \"", "```", "ERROR", "WARN")
        candidates: list[dict[str, str]] = []
        seen_global: set[str] = set()
        for user_id, profile in profiles.items():
            if not isinstance(profile, dict):
                continue
            name = self._single_line(profile.get("name") or user_id, 40)
            pending = profile.get("pending_observations") if isinstance(profile.get("pending_observations"), list) else []
            seen_local: set[str] = set()
            for raw in pending[:12]:
                if not isinstance(raw, dict):
                    continue
                evidence = self._single_line(raw.get("evidence") or raw.get("content") or raw.get("title"), 140)
                content = self._single_line(raw.get("content") or evidence, 180)
                compact = re.sub(r"[\s，。！？!?~～…、,.]+", "", evidence)
                norm = compact.lower()
                reason = ""
                if not compact or len(compact) <= 2:
                    reason = "内容过短，难以沉淀成人物观察"
                elif compact in generic_reactions:
                    reason = "像临时语气反应，不像稳定人物信息"
                elif any(marker in evidence or marker in content for marker in log_markers):
                    reason = "像日志/代码片段，不适合写入关系网"
                elif norm in seen_local:
                    reason = "同一成员下重复观察"
                elif norm in seen_global:
                    reason = "跨成员重复泛化观察，可能没有辨识度"
                elif re.fullmatch(r"[\dA-Za-z_-]{8,}", compact):
                    reason = "像 ID 或文件名，不像人物观察"
                elif any(marker in evidence for marker in ("今天", "刚刚", "现在", "一会儿", "等下")) and self._int(raw.get("count")) <= 1:
                    reason = "像临时状态，缺少长期价值"
                seen_local.add(norm)
                seen_global.add(norm)
                if not reason:
                    continue
                candidates.append(
                    {
                        "user_id": self._single_line(user_id, 40),
                        "name": name,
                        "title": self._single_line(raw.get("title"), 50),
                        "evidence": evidence,
                        "reason": reason,
                    }
                )
                if len(candidates) >= 24:
                    return candidates
        return candidates

    def _model_diagnostics_companion_memory_candidates(self, data: dict[str, Any]) -> list[dict[str, str]]:
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        temporary_tokens = ("今天", "刚刚", "刚才", "现在", "今晚", "明天", "这次", "暂时", "一会儿", "等会儿", "刚睡醒", "刚下课")
        joke_tokens = ("开玩笑", "不是认真的", "随口", "口嗨", "逗你的", "反话", "阴阳怪气")
        log_markers = ("Traceback", "Error code:", "Exception", "[INFO]", "[WARN]", "[ERRO]", "[Core]", "```", "git ", "python ", "node ")
        internal_markers = ("提示词", "系统提示", "内部控制标签", "插件配置", "schema", "token", "cache hit", "PCTTS", "<pc_tts")
        profile_fields = {
            "strong_memories": "强记忆",
            "weak_preferences": "弱偏好",
            "user_traits": "用户画像",
            "interests": "兴趣/偏好",
            "boundaries": "边界/雷点",
            "relationship_notes": "关系线索",
            "speaking_style": "说话习惯",
        }

        def reason_for(text: str) -> str:
            if any(marker.lower() in text.lower() for marker in log_markers):
                return "像日志/代码/报错内容，不适合长期画像"
            if any(marker.lower() in text.lower() for marker in internal_markers):
                return "像系统或插件内部文本，不适合长期画像"
            if any(token in text for token in joke_tokens):
                return "带有玩笑/反讽不确定性，建议人工确认"
            if any(token in text for token in temporary_tokens) and not any(token in text for token in ("以后", "长期", "一直", "固定", "默认", "记住", "记得")):
                return "像临时状态，不像长期画像"
            if re.fullmatch(r"[\dA-Za-z_-]{8,}", re.sub(r"\s+", "", text)):
                return "像 ID 或文件名，不像用户画像"
            return ""

        candidates: list[dict[str, str]] = []
        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            name = self._single_line(user.get("nickname") or user.get("name") or user_id, 40)
            memory = user.get("companion_memory") if isinstance(user.get("companion_memory"), dict) else {}
            raw_items = memory.get("items") if isinstance(memory.get("items"), list) else []
            for raw in raw_items[:24]:
                if not isinstance(raw, dict):
                    continue
                text = self._single_line(raw.get("text"), 160)
                reason = reason_for(text)
                if not reason:
                    continue
                candidates.append(
                    {
                        "user_id": self._single_line(user_id, 40),
                        "name": name,
                        "field": self._single_line(raw.get("kind") or "原始记录", 30),
                        "text": text,
                        "reason": reason,
                    }
                )
                if len(candidates) >= 24:
                    return candidates
            profile = memory.get("profile") if isinstance(memory.get("profile"), dict) else {}
            for key, label in profile_fields.items():
                value = profile.get(key)
                values = value if isinstance(value, list) else ([value] if value else [])
                for raw_text in values[:8]:
                    text = self._single_line(raw_text, 160)
                    reason = reason_for(text)
                    if not reason:
                        continue
                    candidates.append(
                        {
                            "user_id": self._single_line(user_id, 40),
                            "name": name,
                            "field": label,
                            "text": text,
                            "reason": reason,
                        }
                    )
                    if len(candidates) >= 24:
                        return candidates
        return candidates

    def _model_diagnostics_expression_candidates(self, data: dict[str, Any]) -> list[dict[str, str]]:
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        log_markers = ("Traceback", "Error code:", "Exception", "[INFO]", "[WARN]", "[ERRO]", "[Core]", "```", "commit ", "diff ")
        model_markers = ("<pc_tts", "</pc_tts>", "[[PCTTS:", "send_message_to_user", "assistant", "system prompt", "提示词")
        political_markers = (
            "习近平",
            "共产党",
            "中共",
            "六四",
            "天安门",
            "法轮功",
            "台独",
            "港独",
            "藏独",
            "疆独",
            "民主运动",
            "政治敏感",
        )

        def reason_for(text: str) -> str:
            lowered = text.lower()
            if any(marker.lower() in lowered for marker in log_markers):
                return "像日志/代码/报错内容，不该作为表达习惯"
            if any(marker.lower() in lowered for marker in model_markers):
                return "像模型输出格式或内部标签，不该作为表达习惯"
            if any(marker in text for marker in political_markers):
                return "含政治敏感内容，不适合进入表达学习"
            if text.count("…") + text.count("～") + text.count("~") >= 5:
                return "标点留白过多，容易污染表达节奏"
            if text.count("？") + text.count("?") + text.count("！") + text.count("!") >= 6:
                return "疑问/感叹标点过多，容易污染表达节奏"
            return ""

        candidates: list[dict[str, str]] = []
        for user_id, user in users.items():
            if not isinstance(user, dict):
                continue
            name = self._single_line(user.get("nickname") or user.get("name") or user_id, 40)
            profile = user.get("expression_profile") if isinstance(user.get("expression_profile"), dict) else {}
            samples = profile.get("samples") if isinstance(profile.get("samples"), list) else []
            for raw in samples[:36]:
                if not isinstance(raw, dict):
                    continue
                text = self._single_line(raw.get("phrase") or raw.get("ending"), 120)
                marks = raw.get("punctuation") if isinstance(raw.get("punctuation"), dict) else {}
                pause_total = sum(self._int(marks.get(mark)) for mark in ("…", "～", "~"))
                strong_total = sum(self._int(marks.get(mark)) for mark in ("？", "?", "！", "!"))
                direct_reason = ""
                if pause_total >= 5:
                    direct_reason = "标点留白过多，容易污染表达节奏"
                elif strong_total >= 6:
                    direct_reason = "疑问/感叹标点过多，容易污染表达节奏"
                if not text:
                    text = " ".join(f"{mark}×{self._int(count)}" for mark, count in marks.items() if self._int(count) > 0)
                reason = direct_reason or reason_for(text)
                if not reason:
                    continue
                candidates.append(
                    {
                        "user_id": self._single_line(user_id, 40),
                        "name": name,
                        "text": text,
                        "reason": reason,
                    }
                )
                if len(candidates) >= 24:
                    return candidates
            for raw_text in [*(profile.get("recent_phrases") if isinstance(profile.get("recent_phrases"), list) else []), *(profile.get("endings") if isinstance(profile.get("endings"), list) else [])][:36]:
                text = self._single_line(raw_text, 120)
                reason = reason_for(text)
                if not reason:
                    continue
                candidates.append(
                    {
                        "user_id": self._single_line(user_id, 40),
                        "name": name,
                        "text": text,
                        "reason": reason,
                    }
                )
                if len(candidates) >= 24:
                    return candidates
        return candidates

    def _model_diagnostics_review_prompt(
        self,
        data: dict[str, Any],
        skill_candidates: list[dict[str, str]],
        slang_candidates: list[dict[str, str]],
        pending_candidates: list[dict[str, str]],
        memory_candidates: list[dict[str, str]],
        expression_candidates: list[dict[str, str]],
    ) -> str:
        skill_lines = [f"- {item.get('a')} / {item.get('b')}：{item.get('reason')}" for item in skill_candidates[:12]]
        slang_lines = [
            f"- {item.get('group_name') or item.get('group_id')}｜{item.get('term')}｜{item.get('reason')}｜次数:{item.get('count') or 0}"
            for item in slang_candidates[:18]
        ]
        pending_lines = [
            f"- {item.get('name') or item.get('user_id')}｜{item.get('reason')}｜{item.get('evidence')}"
            for item in pending_candidates[:18]
        ]
        memory_lines = [
            f"- {item.get('name') or item.get('user_id')}｜{item.get('field')}｜{item.get('reason')}｜{item.get('text')}"
            for item in memory_candidates[:18]
        ]
        expression_lines = [
            f"- {item.get('name') or item.get('user_id')}｜{item.get('reason')}｜{item.get('text')}"
            for item in expression_candidates[:18]
        ]
        return (
            "你是陪伴插件的数据排障助手。请复核下面这些由本地规则挑出的候选项，只指出明显会影响模型理解的杂音。\n"
            "范围包括：技能相似项、群黑话杂音、关系网待确认观察、长期画像噪音、表达学习污染。不要修改数据，不要发散，不要把正常口癖或真实群梗误报。\n"
            "表达学习污染只关注日志、复制模型格式、政治敏感内容和过度标点等，不要扩展到普通语气判断。\n"
            "输出 1-10 条短建议，每条不超过 45 字，必须用分类前缀：技能｜、黑话｜、关系网｜、长期画像｜、表达学习｜。\n"
            "如果某一类没有明显问题，不要为了凑数输出。若全部无明显问题，输出“未发现明显模型数据杂音”。\n\n"
            "技能候选：\n" + ("\n".join(skill_lines) if skill_lines else "- 无") + "\n\n"
            "群黑话候选：\n" + ("\n".join(slang_lines) if slang_lines else "- 无") + "\n\n"
            "关系网待确认观察候选：\n" + ("\n".join(pending_lines) if pending_lines else "- 无") + "\n\n"
            "长期画像候选：\n" + ("\n".join(memory_lines) if memory_lines else "- 无") + "\n\n"
            "表达学习候选：\n" + ("\n".join(expression_lines) if expression_lines else "- 无")
        )

    def _attach_model_diagnostics_section_suggestions(self, sections: list[dict[str, Any]], suggestions: list[str]) -> None:
        section_by_key = {str(section.get("key")): section for section in sections if isinstance(section, dict)}
        prefix_map = {
            "技能": "skills",
            "黑话": "slang",
            "关系网": "worldbook",
            "长期画像": "memory",
            "表达学习": "expression",
        }
        for suggestion in suggestions:
            prefix = self._single_line(str(suggestion).split("｜", 1)[0], 20)
            key = prefix_map.get(prefix)
            section = section_by_key.get(key or "")
            if not section:
                continue
            items = section.setdefault("suggestions", [])
            if isinstance(items, list):
                items.append(self._single_line(suggestion, 180))
            section["model_count"] = self._int(section.get("model_count")) + 1

    def _skill_similarity_review_prompt(self, data: dict[str, Any], candidates: list[dict[str, str]]) -> str:
        summary = self._skill_growth_summary(data)
        skills = summary.get("items") if isinstance(summary.get("items"), list) else []
        skill_lines = []
        for item in skills[:80]:
            aliases = "、".join(item.get("aliases") or [])
            keywords = "、".join((item.get("keywords") or [])[:8])
            flags = " ".join(flag for flag in ("隐藏" if item.get("hidden") else "", "冻结" if item.get("frozen") else "") if flag)
            skill_lines.append(
                f"- {item.get('name')}｜{item.get('category')}｜{item.get('level_title')}｜别名:{aliases or '-'}｜关键词:{keywords or '-'}｜{flags or '正常'}"
            )
        candidate_lines = [f"- {item.get('a')} / {item.get('b')}：{item.get('reason')}" for item in candidates[:12]]
        return (
            "你是插件排障助手。请检查技能成长列表中是否存在疑似重复技能、别名冲突、过泛关键词或应该隐藏/冻结的项。\n"
            "只根据给出的列表判断，不要发散。不要修改数据，只给建议。\n"
            "不要把“上课、作业、复习、考试、练习、笔记、题目”等通用学习流程词当作技能相似证据。\n"
            "只有名称/别名明显指向同一能力，或多个专有关键词高度重叠时，才建议合并。\n"
            "请输出 1-6 条短建议，每条不超过 45 字；如果没有问题，只输出“未发现需要合并的技能”。\n\n"
            "本地候选：\n" + "\n".join(candidate_lines) + "\n\n"
            "技能列表：\n" + "\n".join(skill_lines)
        )

    def _parse_skill_similarity_model_result(self, raw: Any) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        lines = []
        for line in re.split(r"[\r\n]+", text):
            item = re.sub(r"^\s*[-*•\d.、)）]+\s*", "", line).strip()
            item = self._single_line(item, 90)
            if re.search(r"^(未发现|没有发现|暂无|无明显|无额外)", item):
                continue
            if item and item not in lines:
                lines.append(item)
        return lines[:10]

    async def _remember_troubleshooting_test_result(self, test_type: str, result: dict[str, Any]) -> None:
        if not test_type:
            return
        try:
            async with self.plugin._data_lock:
                raw = self.plugin.data.setdefault("troubleshooting_test_results", {})
                if not isinstance(raw, dict):
                    raw = {}
                    self.plugin.data["troubleshooting_test_results"] = raw
                raw[test_type] = self._sanitize_troubleshooting_test_result(result)
                self.plugin._save_data_sync()
        except Exception as exc:
            logger.warning("[PrivateCompanionPage] 保存排障测试结果失败: %s", self._single_line(exc, 120))

    def _troubleshooting_test_results(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("troubleshooting_test_results")
        if not isinstance(raw, dict):
            return {}
        results: dict[str, Any] = {}
        users = data.get("users") if isinstance(data.get("users"), dict) else {}
        active_proactive_test = any(
            isinstance(user, dict)
            and str(user.get("planned_proactive_source") or "") == "troubleshooting"
            and isinstance(user.get("troubleshooting_proactive_restore"), dict)
            for user in users.values()
        )
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            item = self._sanitize_troubleshooting_test_result(value)
            if key == "proactive_message" and item.get("pending") and not active_proactive_test:
                item.update(
                    {
                        "ok": False,
                        "pending": False,
                        "error": item.get("error") or "主动消息测试任务状态已丢失，请重新测试",
                        "detail": item.get("detail") or "没有找到正在等待执行的临时主动任务",
                        "ran_at": time.time(),
                        "ran_at_text": self.plugin._format_timestamp_elapsed(time.time()),
                    }
                )
            results[key] = item
        return results

    def _recent_photo_generation_summary(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        raw = data.get("recent_photo_generations")
        if not isinstance(raw, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            ts = self._float(item.get("ts"))
            prompt = str(item.get("prompt") or "")
            items.append(
                {
                    "ts": ts,
                    "time": self.plugin._format_timestamp_elapsed(ts),
                    "trace": self._single_line(item.get("trace"), 40),
                    "session": self._single_line(item.get("session"), 100),
                    "kind": self._single_line(item.get("kind"), 30),
                    "backend": self._single_line(item.get("backend"), 80),
                    "ok": bool(item.get("ok")),
                    "prompt": prompt[:500],
                    "prompt_preview": self._single_line(prompt, 180),
                    "path": self._single_line(item.get("path"), 260),
                    "note": self._single_line(item.get("note"), 220),
                    "reference": bool(item.get("reference")),
                    "reference_path": self._single_line(item.get("reference_path"), 260),
                    "image_size": self._single_line(item.get("image_size"), 40),
                    "elapsed_ms": self._int(item.get("elapsed_ms")),
                    "trigger": self._single_line(item.get("trigger"), 40),
                    "intent_kind": self._single_line(item.get("intent_kind"), 30),
                    "sent": bool(item.get("sent")),
                    "caption": self._single_line(item.get("caption"), 120),
                    "scene_preset": self._single_line(item.get("scene_preset"), 80),
                    "tool_name": self._single_line(item.get("tool_name"), 60),
                    "presets": [
                        self._single_line(name, 40)
                        for name in (item.get("presets") if isinstance(item.get("presets"), list) else [])
                        if self._single_line(name, 40)
                    ][:6],
                }
            )
        return items

    def _prompt_injection_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("recent_prompt_injections")
        if not isinstance(raw, dict):
            raw = {}
        raw_events = data.get("recent_prompt_injection_events")
        if not isinstance(raw_events, list):
            raw_events = []

        def preview_is_internal_prompt(value: Any) -> bool:
            cleaned = self._single_line(value, 260)
            if not cleaned:
                return False
            internal_markers = (
                "【语音消息规则】",
                "<pc_tts>",
                "</pc_tts>",
                "语音消息规则",
                "提示词片段",
                "请求级环境感知注入",
                "被动回复注入",
                "当前语音正文目标语种",
                "自然聊天时用中文文字推进对话",
                "不要写“中文含义”",
            )
            if any(marker in cleaned for marker in internal_markers):
                return True
            return cleaned.startswith("【") and "规则" in cleaned[:40]

        def safe_message_preview(value: Any, limit: int = 120) -> str:
            preview = self._single_line(value, limit)
            if preview_is_internal_prompt(preview):
                return ""
            return preview

        def normalize_item(item: Any) -> dict[str, Any] | None:
            if not isinstance(item, dict):
                return None
            ts = self._float(item.get("ts"))
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            raw_modules = item.get("modules") if isinstance(item.get("modules"), list) else []
            if not raw_modules:
                normalizer = getattr(self.plugin, "_normalize_prompt_injection_modules", None)
                if callable(normalizer):
                    try:
                        raw_modules = normalizer(str(item.get("content") or ""), None)
                    except Exception:
                        raw_modules = []
            modules: list[dict[str, Any]] = []
            for index, module in enumerate(raw_modules[:28]):
                if not isinstance(module, dict):
                    continue
                content = str(module.get("content") or "")[:6500]
                if not content.strip():
                    continue
                module_metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
                modules.append(
                    {
                        "key": self._single_line(module.get("key"), 100) or f"module.{index + 1}",
                        "source": self._single_line(module.get("source"), 80),
                        "priority": self._int(module.get("priority")),
                        "title": self._single_line(module.get("title"), 80) or "提示词片段",
                        "description": self._single_line(module.get("description"), 260),
                        "chars": self._int(module.get("chars")),
                        "truncated": bool(module.get("truncated")),
                        "preview": self._single_line(module.get("preview"), 220),
                        "content": content,
                        "metadata": {
                            self._single_line(key, 40): self._single_line(value, 120)
                            for key, value in module_metadata.items()
                            if self._single_line(key, 40) and self._single_line(value, 120)
                        },
                    }
                )
            return {
                "ts": ts,
                "time": self.plugin._format_timestamp_elapsed(ts),
                "kind": self._single_line(item.get("kind"), 20),
                "session": self._single_line(item.get("session"), 160),
                "title": self._single_line(item.get("title"), 80),
                "mode": self._single_line(item.get("mode"), 40),
                "chars": self._int(item.get("chars")),
                "truncated": bool(item.get("truncated")),
                "preview": self._single_line(item.get("preview"), 260),
                "trace_seq": self._int(item.get("trace_seq")),
                "content": str(item.get("content") or "")[:13000],
                "modules": modules,
                "metadata": {
                    self._single_line(key, 40): self._single_line(value, 240)
                    for key, value in metadata.items()
                    if self._single_line(key, 40) and self._single_line(value, 240)
                },
            }

        def normalize_message(item: Any) -> dict[str, Any] | None:
            if not isinstance(item, dict):
                return None
            raw_items = item.get("items") if isinstance(item.get("items"), list) else []
            normalized_items = [entry for entry in (normalize_item(raw_item) for raw_item in raw_items[:32]) if entry]
            normalized_items.sort(
                key=lambda entry: (
                    self._float(entry.get("ts")),
                    self._int(entry.get("trace_seq")),
                )
            )
            if not normalized_items:
                return None
            first_ts = self._float(item.get("first_ts")) or min(self._float(entry.get("ts")) for entry in normalized_items)
            last_ts = self._float(item.get("last_ts")) or max(self._float(entry.get("ts")) for entry in normalized_items)
            kinds: list[str] = []
            for entry in normalized_items:
                kind = self._single_line(entry.get("kind"), 20)
                if kind and kind not in kinds:
                    kinds.append(kind)
            message_preview = safe_message_preview(item.get("message_preview"), 120)
            if not message_preview:
                message_preview = next(
                    (
                        safe_message_preview(entry.get("metadata", {}).get("触发消息"), 120)
                        for entry in normalized_items
                        if isinstance(entry, dict)
                        and safe_message_preview(entry.get("metadata", {}).get("触发消息"), 120)
                    ),
                    "",
                )
            return {
                "trace_id": self._single_line(item.get("trace_id"), 80),
                "session": self._single_line(item.get("session"), 160) or self._single_line(normalized_items[-1].get("session"), 160),
                "sender_label": self._single_line(item.get("sender_label"), 80),
                "message_preview": message_preview,
                "first_ts": first_ts,
                "first_time": self.plugin._format_timestamp_elapsed(first_ts),
                "last_ts": last_ts,
                "time": self.plugin._format_timestamp_elapsed(last_ts),
                "item_count": len(normalized_items),
                "module_count": sum(len(entry.get("modules") or []) for entry in normalized_items),
                "kinds": kinds,
                "items": normalized_items,
            }

        result: dict[str, Any] = {}
        for kind in ("tts", "proactive", "passive", "request"):
            items = raw.get(kind) if isinstance(raw.get(kind), list) else []
            limit = 8 if kind == "tts" else 5
            normalized = [entry for entry in (normalize_item(item) for item in items[:limit]) if entry]
            result[kind] = normalized
        messages = [entry for entry in (normalize_message(item) for item in raw_events[:10]) if entry]
        if not messages:
            legacy_messages: list[dict[str, Any]] = []
            for kind in ("request", "passive", "proactive", "tts"):
                for index, item in enumerate(result.get(kind, [])):
                    if not isinstance(item, dict):
                        continue
                    ts = self._float(item.get("ts"))
                    legacy_messages.append(
                        {
                            "trace_id": self._single_line(item.get("trace_id"), 80) or f"legacy-{kind}-{index}",
                            "session": self._single_line(item.get("session"), 160),
                            "sender_label": self._single_line(item.get("metadata", {}).get("发送者"), 80),
                            "message_preview": safe_message_preview(item.get("metadata", {}).get("触发消息"), 120),
                            "first_ts": ts,
                            "first_time": self.plugin._format_timestamp_elapsed(ts),
                            "last_ts": ts,
                            "time": self.plugin._format_timestamp_elapsed(ts),
                            "item_count": 1,
                            "module_count": len(item.get("modules") or []),
                            "kinds": [kind],
                            "items": [item],
                        }
                    )
            legacy_messages.sort(key=lambda entry: self._float(entry.get("last_ts")), reverse=True)
            messages = legacy_messages[:10]
        else:
            messages.sort(key=lambda entry: self._float(entry.get("last_ts")), reverse=True)
        result["messages"] = messages[:10]
        result["message_total"] = len(result["messages"])
        result["total"] = (
            len(result.get("tts", []))
            + len(result.get("proactive", []))
            + len(result.get("passive", []))
            + len(result.get("request", []))
        )
        return result

    def _sanitize_troubleshooting_test_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": self._single_line(result.get("type"), 40),
            "ok": bool(result.get("ok")),
            "pending": bool(result.get("pending")),
            "title": self._single_line(result.get("title"), 60),
            "backend": self._single_line(result.get("backend"), 80),
            "image_model": self._single_line(result.get("image_model"), 80),
            "workflow_kind": self._single_line(result.get("workflow_kind"), 20),
            "reference_image": self._single_line(result.get("reference_image"), 260),
            "used_reference": bool(result.get("used_reference")),
            "provider": self._single_line(result.get("provider"), 100),
            "umo": self._single_line(result.get("umo"), 180),
            "path": self._single_line(result.get("path"), 260),
            "file_size": self._int(result.get("file_size")),
            "detail": self._single_line(result.get("detail"), 220),
            "error": self._single_line(result.get("error"), 220),
            "prompt": self._single_line(result.get("prompt"), 500),
            "timeout_seconds": self._int(result.get("timeout_seconds")),
            "test_timeout_seconds": self._int(result.get("test_timeout_seconds")),
            "estimated_timeout_seconds": self._int(result.get("estimated_timeout_seconds")),
            "timeout_budget": self._single_line(result.get("timeout_budget"), 220),
            "backend_preference": self._single_line(result.get("backend_preference"), 30),
            "external_timeout_seconds": self._int(result.get("external_timeout_seconds")),
            "backup_external_timeout_seconds": self._int(result.get("backup_external_timeout_seconds")),
            "comfyui_wait_seconds": self._int(result.get("comfyui_wait_seconds")),
            "backup_external": bool(result.get("backup_external")),
            "external_queue_lock": bool(result.get("external_queue_lock")),
            "tool_call_timeout_seconds": self._int(result.get("tool_call_timeout_seconds")),
            "warnings": [
                self._single_line(item, 220)
                for item in (result.get("warnings") if isinstance(result.get("warnings"), list) else [])[:8]
                if self._single_line(item, 220)
            ],
            "text_preview": self._single_line(result.get("text_preview"), 220),
            "original_text_preview": self._single_line(result.get("original_text_preview"), 220),
            "final_text_preview": self._single_line(result.get("final_text_preview"), 220),
            "context_chars": self._int(result.get("context_chars")),
            "action": self._single_line(result.get("action"), 60),
            "reason": self._single_line(result.get("reason"), 40),
            "extra_count": self._int(result.get("extra_count")),
            "local_count": self._int(result.get("local_count")),
            "model_count": self._int(result.get("model_count")),
            "suggestion_count": self._int(result.get("suggestion_count")),
            "suggestions": [
                self._single_line(item, 220)
                for item in (result.get("suggestions") if isinstance(result.get("suggestions"), list) else [])[:12]
                if self._single_line(item, 220)
            ],
            "sections": [
                {
                    "key": self._single_line(section.get("key"), 40),
                    "title": self._single_line(section.get("title"), 60),
                    "local_count": self._int(section.get("local_count")),
                    "model_count": self._int(section.get("model_count")),
                    "suggestions": [
                        self._single_line(item, 220)
                        for item in (section.get("suggestions") if isinstance(section.get("suggestions"), list) else [])[:8]
                        if self._single_line(item, 220)
                    ],
                }
                for section in (result.get("sections") if isinstance(result.get("sections"), list) else [])[:6]
                if isinstance(section, dict)
            ],
            "steps": [
                {
                    "name": self._single_line(step.get("name"), 40),
                    "status": self._single_line(step.get("status"), 16),
                    "detail": self._single_line(step.get("detail"), 180),
                }
                for step in (result.get("steps") if isinstance(result.get("steps"), list) else [])[:12]
                if isinstance(step, dict)
            ],
            "elapsed_ms": self._int(result.get("elapsed_ms")),
            "ran_at": self._float(result.get("ran_at")),
            "ran_at_text": self._single_line(result.get("ran_at_text"), 40),
        }

    @staticmethod
    def _troubleshooting_test_title(test_type: str) -> str:
        return {
            "image_generation": "图片生成链路测试",
            "image_generation_text2img": "文生图链路测试",
            "image_generation_selfie": "自拍参考图链路测试",
            "tts_generation": "TTS 生成链路测试",
            "screen_peek": "窥屏链路测试",
            "qzone_integration": "QQ 空间链路测试",
            "proactive_message": "主动消息链路测试",
            "model_diagnostics": "模型数据排障",
            "skill_similarity": "技能相似项检查",
        }.get(test_type, "排障链路测试")

    @staticmethod
    def _token_task_label(task: Any) -> str:
        normalized = str(task or "").strip()
        if not normalized:
            return "未分类模型调用"
        labels = {
            "daily_plan": "日程生成",
            "detail": "日程细化",
            "dream": "梦境内容",
            "diary": "日记整理",
            "diary_rewrite": "日记修订",
            "diary_derivatives": "日记线索提取",
            "memory_profile": "长期画像",
            "dialogue_episode": "私聊片段",
            "response_review": "回复/主动复核",
            "emotion_judgement": "情绪判断",
            "relationship": "关系分析",
            "group_interject": "群聊插话",
            "group_episode": "群聊片段",
            "group_slang": "黑话释义",
            "group_question_wakeup_reply_review": "群聊答疑复核",
            "group_followup_judge": "群聊续接判断",
            "worldbook_registration": "关系网自登记",
            "web_exploration_query": "探索选题",
            "web_exploration_digest": "探索笔记",
            "external_event_self_link": "外界信息关联",
            "news_digest": "新闻整理",
            "creative_project": "创作立项",
            "creative_outline": "创作大纲",
            "creative_writing": "文本创作",
            "creative_review": "创作审校",
            "creative_extract": "创作抽取",
            "photo_prompt": "生图提示",
            "screen_narration": "识屏转述",
            "forward_message": "合并转发转述",
            "forward_message_image_vision": "转发图片识别",
            "private_reading_vision": "夹层视觉",
            "private_image_vision": "私聊图片识别",
            "private_image_only_framework": "单图回复主链",
            "private_image_only_fallback": "单图兜底回复",
            "voice": "语音文本",
            "proactive_framework": "主动主回复",
            "proactive_persona_judge": "主动人格判定",
            "voice_framework": "框架语音",
            "voice_repair": "语音格式修复",
            "tts_conversion": "TTS 快速转换",
            "tts_spoken_conversion": "TTS 口语转换",
            "tts_postprocess": "TTS 后处理",
            "tts_visible_translation": "TTS 可见译文",
            "smart_message_debounce": "智能收口防抖",
            "smart_silence": "智能沉默判断",
            "group_air_reply_guard": "群聊插话把关",
            "group_nsfw_image_review": "群图安全审核",
            "rest_wakeup_judge": "休息醒来判断",
            "yesterday_summary": "昨日摘要",
            "full_test_detail": "完整测试细化",
            "provider_test": "模型测试",
            "qzone_comment": "空间评论",
            "qzone_comment_inbox_decision": "空间评论判断",
            "qzone_publish": "空间说说",
            "qzone_publish_test": "空间发布测试",
            "qzone_publish_sanitize": "空间文案清理",
            "qzone_publish_image_test_draft": "空间配图测试草稿",
            "qzone_emotional_vent": "空间情绪表达",
            "companion_manual_diagnosis": "陪伴答疑",
            "proactive_send_review": "主动发送复核",
            "atrelay_rewrite": "代答转写",
            "bookshelf_password": "书柜密码生成",
            "bookshelf_password_reason": "书柜密码缘由",
            "astrbot_private_reply": "非插件私聊主回复",
            "astrbot_group_reply": "非插件群聊主回复",
            "astrbot_reply": "非插件主回复",
            "other": "未分类模型调用",
        }
        if normalized in labels:
            return labels[normalized]
        if normalized.startswith("qzone_") and normalized.endswith("_photo_prompt"):
            return "空间配图提示"
        if normalized.startswith("qzone_"):
            return "QQ 空间任务"
        if normalized.startswith("astrbot_"):
            return "AstrBot 主回复"
        if normalized.startswith("private_image_"):
            return "私聊图片处理"
        if normalized.startswith("web_exploration_"):
            return "主动搜索"
        return normalized

    def _troubleshooting_recent_events(
        self,
        *,
        diagnostics: list[dict[str, Any]],
        proactive_tasks: dict[str, Any],
        proactive_candidates: dict[str, Any],
        token_stats: dict[str, Any],
        passive_no_reply: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        def add(
            level: str,
            source: str,
            title: str,
            detail: str = "",
            *,
            ts: float = 0,
            action: str = "",
            jump: str = "",
            warning_type: str = "",
            warning_code: str = "",
            event_kind: str = "event",
            event_status: str = "historical",
        ) -> None:
            resolved_type = warning_type or (
                self._troubleshooting_semantic_warning_type(warning_code)
                if warning_code
                else self._troubleshooting_warning_type("event", source, title)
            )
            events.append(
                {
                    "level": level,
                    "source": source,
                    "title": self._single_line(title, 90),
                    "detail": self._single_line(detail, 220),
                    "action": self._single_line(action, 160),
                    "jump": self._single_line(jump, 40),
                    "ts": self._float(ts),
                    "time": self.plugin._format_timestamp_elapsed(ts) if ts else "",
                    "warning_type": resolved_type,
                    "warning_code": warning_code,
                    "event_kind": event_kind,
                    "event_status": event_status,
                    "counts_as_current": event_status in {"current", "unresolved"},
                }
            )

        for item in diagnostics:
            level = self._single_line(item.get("level"), 12)
            if level not in {"error", "warn"}:
                continue
            add(
                level,
                "配置诊断",
                item.get("title", ""),
                item.get("text", ""),
                action=item.get("action", ""),
                jump="troubleshooting",
                warning_type=self._single_line(item.get("warning_type"), 64),
                warning_code=self._single_line(item.get("warning_code"), 120),
                event_kind="diagnostic",
                event_status="current",
            )

        for item in proactive_tasks.get("audit_items", [])[:40]:
            status = self._single_line(item.get("status"), 24)
            if status not in {"failed", "dropped", "deferred"}:
                continue
            note = self._single_line(item.get("note"), 180)
            if status in {"dropped", "deferred"} and not self._proactive_audit_note_needs_troubleshooting(note):
                continue
            level = "error" if status == "failed" else "warn"
            title = item.get("topic") or item.get("reason") or item.get("note") or "主动执行异常"
            detail = "；".join(
                part
                for part in [
                    f"用户 {item.get('user_label') or item.get('user_id') or '-'}",
                    f"动作 {item.get('action') or 'message'}",
                    note,
                    item.get("text_preview") or "",
                ]
                if part
            )
            add(
                level,
                "主动审计",
                title,
                detail,
                ts=self._float(item.get("updated_ts") or item.get("created_ts")),
                jump="proactive",
                warning_code=self._troubleshooting_proactive_warning_code("audit", item, note),
                event_kind="proactive_audit",
            )

        for item in proactive_candidates.get("items", [])[:40]:
            if self._single_line(item.get("status"), 24) != "blocked":
                continue
            note = self._single_line(item.get("note"), 180)
            if self._proactive_candidate_block_is_normal(note):
                continue
            title = item.get("topic") or item.get("reason") or "主动候选被拦截"
            detail = "；".join(
                part
                for part in [
                    f"用户 {item.get('user_label') or item.get('user_id') or '-'}",
                    f"动作 {item.get('action') or 'message'}",
                    note,
                ]
                if part
            )
            add(
                "warn",
                "主动候选",
                title,
                detail,
                ts=self._float(item.get("last_seen_ts") or item.get("created_ts")),
                jump="proactive",
                warning_code=self._troubleshooting_proactive_warning_code("candidate", item, note),
                event_kind="candidate",
            )

        for item in self._active_token_failures(token_stats.get("recent", []), limit=50):
            title = f"{self._token_task_label(item.get('task'))}失败"
            detail = "；".join(
                part
                for part in [
                    f"Provider {item.get('provider') or '-'}",
                    item.get("error") or "无错误详情",
                ]
                if part
            )
            add(
                "error",
                "模型调用",
                title,
                detail,
                ts=self._float(item.get("ts")),
                jump="tokens",
                warning_code=f"model_call.{re.sub(r'[^a-z0-9_]+', '_', self._single_line(item.get('task'), 40).lower()).strip('_') or 'unknown'}",
                event_kind="model_call",
                event_status="unresolved",
            )

        passive_items = passive_no_reply.get("items", []) if isinstance(passive_no_reply, dict) else []
        for item in passive_items[:40]:
            if not isinstance(item, dict):
                continue
            count = self._int(item.get("count"))
            source = self._single_line(item.get("source"), 40) or "被动未回复"
            reason = self._single_line(item.get("reason"), 100) or "未说明原因"
            inbound = self._single_line(item.get("last_inbound"), 100)
            detail = "；".join(
                part
                for part in [
                    f"已合并 {count} 次" if count > 1 else "最近 1 次",
                    f"会话 {self._single_line(item.get('last_session'), 80)}" if item.get("last_session") else "",
                    f"消息 {inbound}" if inbound else "",
                    self._single_line(item.get("last_detail"), 120),
                ]
                if part
            )
            add(
                self._single_line(item.get("level"), 12) or "info",
                source,
                reason,
                detail,
                ts=self._float(item.get("last_ts")),
                action="同类原因已合并计数，刷新后可查看最近样本",
                jump="troubleshooting",
                warning_code=f"passive_no_reply.{re.sub(r'[^a-z0-9_]+', '_', self._single_line(item.get('key'), 40).lower()).strip('_') or hashlib.sha256(reason.encode('utf-8')).hexdigest()[:12]}",
                event_kind="passive_no_reply",
            )

        events.sort(key=lambda item: self._float(item.get("ts")), reverse=True)
        return events

    def _troubleshooting_state_projection(
        self, diagnostics: list[dict[str, Any]], checks: list[dict[str, Any]],
        recent_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Separate current evidence from past events; never alter stored history."""
        ranks = {"ok": 0, "info": 1, "warn": 2, "error": 3}
        current: dict[str, dict[str, Any]] = {}
        history: list[dict[str, Any]] = []

        def add_current(raw: dict[str, Any], source: str) -> None:
            item = dict(raw)
            item.setdefault("event_kind", "diagnostic" if source == "diagnostics" else "check")
            item.setdefault("event_status", "current")
            item["counts_as_current"] = True
            if item.get("warning_code") == "diagnostic.pending":
                item["aggregate"] = True
                item["counts_as_issue"] = False
                item["level"] = "info"
            code = str(item.get("warning_code") or item.get("warning_type") or "")
            key = code or "title:" + hashlib.sha256(str(item.get("title") or "").encode("utf-8")).hexdigest()[:20]
            old = current.get(key)
            if old is None:
                item["source_arrays"] = [source]
                current[key] = item
                return
            sources = list(old.get("source_arrays", []))
            if source not in sources:
                sources.append(source)
            if ranks.get(item.get("level"), 1) > ranks.get(old.get("level"), 1):
                current[key] = item
            current[key]["source_arrays"] = sources

        for name, rows in (("diagnostics", diagnostics), ("checks", checks)):
            for item in rows:
                if isinstance(item, dict):
                    add_current(item, name)
        for raw in recent_events:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            is_current = item.get("counts_as_current") is True or item.get("event_status") in {"current", "unresolved"}
            if is_current:
                add_current(item, "recent_events")
            else:
                item.setdefault("event_kind", "event")
                item.setdefault("event_status", "historical")
                item["counts_as_current"] = False
                history.append(item)
        values = list(current.values())
        counts = {level: sum(1 for item in values if item.get("level") == level
                            and item.get("counts_as_issue") is not False and not item.get("aggregate"))
                  for level in ranks}
        history_counts = {level: sum(1 for item in history if item.get("level") == level) for level in ranks}
        return {"current_events": values, "historical_events": history,
                "current_counts": counts, "history_counts": history_counts}

    def _passive_no_reply_item_is_obsolete_fixed_error(self, item: dict[str, Any]) -> bool:
        checker = getattr(self.plugin, "_proactive_audit_note_is_obsolete_fixed_error", None)
        texts = [
            item.get("reason"),
            item.get("last_detail"),
            item.get("last_action"),
            item.get("last_reply_preview"),
        ]
        samples = item.get("samples") if isinstance(item.get("samples"), list) else []
        for sample in samples[:5]:
            if not isinstance(sample, dict):
                continue
            texts.extend([sample.get("detail"), sample.get("reply_preview")])
        joined = "\n".join(str(value or "") for value in texts)
        if callable(checker) and checker(joined):
            return True
        return "NameError" in joined and any(
            token in joined
            for token in (
                "name 'topic' is not defined",
                "name 'name' is not defined",
            )
        )

    def _passive_no_reply_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("passive_no_reply_records")
        if not isinstance(raw, dict):
            return {"total": 0, "items": []}
        items: list[dict[str, Any]] = []
        now = time.time()
        max_age_seconds = 2 * 60 * 60
        hidden_stale = 0
        hidden_obsolete = 0
        for item in raw.get("items", []):
            if not isinstance(item, dict):
                continue
            last_ts = self._float(item.get("last_ts"))
            if self._passive_no_reply_item_is_obsolete_fixed_error(item):
                hidden_obsolete += 1
                continue
            if last_ts > 0 and now - last_ts > max_age_seconds:
                hidden_stale += 1
                continue
            samples = []
            for sample in item.get("samples", []) if isinstance(item.get("samples"), list) else []:
                if not isinstance(sample, dict):
                    continue
                ts = self._float(sample.get("ts"))
                samples.append(
                    {
                        "time": self.plugin._format_timestamp_elapsed(ts) if ts else self._single_line(sample.get("time"), 40),
                        "session": self._single_line(sample.get("session"), 120),
                        "sender_id": self._single_line(sample.get("sender_id"), 80),
                        "inbound": self._single_line(sample.get("inbound"), 120),
                        "detail": self._single_line(sample.get("detail"), 160),
                        "reply_preview": self._single_line(sample.get("reply_preview"), 140),
                        "ts": ts,
                    }
                )
            items.append(
                {
                    "key": self._single_line(item.get("key"), 32),
                    "level": self._single_line(item.get("level"), 12) or "info",
                    "source": self._single_line(item.get("source"), 40) or "被动未回复",
                    "reason": self._single_line(item.get("reason"), 120) or "未说明原因",
                    "count": self._int(item.get("count")),
                    "first_ts": self._float(item.get("first_ts")),
                    "last_ts": last_ts,
                    "last_time": self.plugin._format_timestamp_elapsed(last_ts) if last_ts else "",
                    "last_session": self._single_line(item.get("last_session"), 120),
                    "last_sender_id": self._single_line(item.get("last_sender_id"), 80),
                    "last_inbound": self._single_line(item.get("last_inbound"), 120),
                    "last_detail": self._single_line(item.get("last_detail"), 160),
                    "last_action": self._single_line(item.get("last_action"), 120),
                    "last_reply_preview": self._single_line(item.get("last_reply_preview"), 140),
                    "samples": samples[:5],
                }
            )
        items.sort(key=lambda item: self._float(item.get("last_ts")), reverse=True)
        total = self._int(raw.get("total")) or sum(self._int(item.get("count")) for item in items)
        return {
            "total": total,
            "last_ts": self._float(raw.get("last_ts")),
            "items": items[:80],
            "hidden_stale": hidden_stale,
            "hidden_obsolete": hidden_obsolete,
            "max_age_seconds": max_age_seconds,
        }

    def _active_token_failures(
        self,
        recent: Any,
        *,
        max_age_seconds: float = 30 * 60,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        if not isinstance(recent, list):
            return []
        now = time.time()
        recovered: set[tuple[str, str]] = set()
        failures: list[dict[str, Any]] = []
        for item in recent[:limit]:
            if not isinstance(item, dict):
                continue
            task = self._single_line(item.get("task"), 40) or "LLM 调用"
            provider = self._single_line(item.get("provider"), 80) or "-"
            key = (task, provider)
            if bool(item.get("success", True)):
                recovered.add(key)
                continue
            ts = self._float(item.get("ts"))
            if ts > 0 and now - ts > max_age_seconds:
                continue
            if key in recovered:
                continue
            failures.append(item)
        return failures

    def _proactive_candidate_block_is_normal(self, note: str) -> bool:
        text = self._single_line(note, 180)
        if not text:
            return True
        exact_normal = {
            "已有更早主动候选",
            "近期主题过于相似",
            "已有用户预约/定时主动",
            "用户明确休息中",
            "当前时段主动已足够,已避开扎堆",
            "朋友主动已按日内节奏延后",
            "已有更早主动候选",
            "用户在该问候窗口内已经活跃过",
            "潜在念头窗口已过期",
            "多来源合并",
            "群聊分享候选已过期",
        }
        if text in exact_normal:
            return True
        normal_tokens = (
            "已有更早",
            "近期主题",
            "过于相似",
            "用户明确休息",
            "休息中",
            "免打扰",
            "已避开扎堆",
            "按日内节奏延后",
            "额度",
            "冷却",
            "间隔",
            "频率",
            "调度过滤",
            "窗口已过期",
            "已经活跃过",
            "多来源合并",
            "候选已过期",
        )
        return any(token in text for token in normal_tokens)

    def _proactive_audit_note_needs_troubleshooting(self, note: str) -> bool:
        text = self._single_line(note, 180)
        if not text:
            return False
        normal_tokens = (
            "主动行为失败或不适合发送",
            "不适合发送",
            "用户明确休息",
            "休息中",
            "免打扰",
            "已有更早",
            "调度过滤",
            "已避开扎堆",
            "按日内节奏延后",
            "冷却",
            "间隔",
            "频率",
            "额度",
            "低分",
            "未达到阈值",
            "窗口已过期",
            "已经活跃过",
            "多来源合并",
            "候选已过期",
        )
        if any(token in text for token in normal_tokens):
            return False
        error_tokens = (
            "异常",
            "报错",
            "Traceback",
            "Error",
            "Exception",
            "provider",
            "模型",
            "超时",
            "不可用",
            "发送失败",
            "生成失败",
            "调用失败",
            "保存失败",
            "处理失败",
            "database is locked",
        )
        return any(token in text for token in error_tokens)

    def _troubleshooting_checks(
        self,
        *,
        data: dict[str, Any],
        users: dict[str, Any],
        groups: dict[str, Any],
        diagnostics: list[dict[str, Any]],
        proactive_tasks: dict[str, Any],
        proactive_candidates: dict[str, Any],
        token_stats: dict[str, Any],
        cache: dict[str, Any],
        tts: dict[str, Any],
        sqlite_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        def add(level: str, title: str, text: str, action: str = "", jump: str = "", warning_code: str = "") -> None:
            item = {
                "level": level,
                "title": self._single_line(title, 90),
                "text": self._single_line(text, 240),
                "action": self._single_line(action, 180),
                "jump": self._single_line(jump, 40),
                "warning_code": warning_code,
                "warning_type": self._troubleshooting_semantic_warning_type(warning_code)
                if warning_code
                else self._troubleshooting_warning_type("check", title),
            }
            checks.append(item)

        llm_blocks = []
        raw_llm_blocks = data.get("group_llm_reply_blocks")
        if isinstance(raw_llm_blocks, dict):
            for group_id, item in raw_llm_blocks.items():
                if not isinstance(item, dict) or not bool(item.get("enabled")):
                    continue
                gid = self._single_line(item.get("group_id") or group_id, 80)
                if not gid:
                    continue
                group = groups.get(gid) if isinstance(groups, dict) else None
                name = self._single_line((group or {}).get("name") if isinstance(group, dict) else "", 40)
                llm_blocks.append({"group_id": gid, "name": name, "updated_at": item.get("updated_at")})
        if llm_blocks:
            first = llm_blocks[0]
            label = f"{first.get('name')}({first.get('group_id')})" if first.get("name") else str(first.get("group_id") or "-")
            add(
                "warn",
                "存在群级 LLM 回复熔断",
                f"{len(llm_blocks)} 个群已关闭所有 LLM 回复，首个：{label}。这是手动开关状态，不会被最近记录清理。",
                "在对应群发送：陪伴群 开启LLM",
                "troubleshooting",
                "group.llm_breaker",
            )

        enabled_users = [item for item in users.values() if isinstance(item, dict) and item.get("enabled", True)]
        runtime = proactive_tasks.get("runtime", {})
        daily_limit = self._int(getattr(self.plugin, "max_daily_messages", 0))
        budget = token_stats.get("budget", {})
        if not enabled_users:
            add("warn", "主动消息没有私聊对象", "当前没有启用的私聊对象，主动消息不会有目标。", "到私聊页新增或启用对象", "private", "proactive.no_enabled_users")
        elif daily_limit <= 0:
            add("warn", "私聊主动总额度为 0", "每日主动上限为 0 时，主动念头、候选、主动行为生成与发送均已停止。", "到模块配置调高每日主动上限", "modules", "proactive.daily_limit_zero")
        elif not runtime.get("healthy"):
            add("warn", "主动循环心跳不新鲜", runtime.get("last_tick_error") or "最近没有检测到主动循环心跳。", "查看主动页的循环状态", "proactive", "proactive.loop_stale")
        else:
            add("ok", "主动循环可运行", f"启用对象 {len(enabled_users)} 个，最近心跳 {runtime.get('last_tick_started') or '-'}。", "", "proactive")

        if budget.get("exceeded"):
            add("error", "今日 Token 硬限额已耗尽", f"今日已用 {budget.get('used')}，硬限额 {budget.get('limit')}。", "调高每日 Token 限额或等待明日重置", "tokens")
        elif budget.get("soft_active"):
            add("warn", "Token 软限额正在暂缓后台任务", f"今日已用 {budget.get('used')}，软限额 {budget.get('soft_limit')}；主动生图、新闻、创作等低优先级任务会延后。", "到 Token 页或模块配置检查限额", "tokens", "token.soft_limit_active")
        else:
            add("ok", "Token 预算未阻塞", f"今日已用 {budget.get('used', 0)}；软限额剩余 {budget.get('soft_remaining') if budget.get('soft_remaining') is not None else '不限'}。", "", "tokens")

        photo_enabled = bool(getattr(self.plugin, "enable_photo_text_action", False))
        photo_available = bool(getattr(self.plugin, "_photo_text_available", lambda *args, **kwargs: False)())
        photo_blocked = [
            item for item in proactive_candidates.get("items", [])
            if "photo_text" in str(item.get("action") or "") and str(item.get("status") or "") == "blocked"
        ]
        photo_blocked_abnormal = [
            item for item in photo_blocked
            if not self._proactive_candidate_block_is_normal(self._single_line(item.get("note"), 180))
        ]
        if not photo_enabled:
            add("warn", "主动带图功能未开启", "enable_photo_text_action 关闭时不会生成主动图片。", "到功能开关打开主动拍照/生图", "config", "image.proactive_disabled")
        elif not photo_available:
            add("warn", "主动带图后端或额度不可用", "生图后端不可用、每日生图额度用完，或当前对象不允许 photo_text。", "检查生图后端、每日生图上限和用户关系角色", "modules", "image.proactive_backend_unavailable")
        elif photo_blocked_abnormal:
            add("warn", "近期带图候选被拦截", self._single_line(photo_blocked_abnormal[0].get("note"), 160) or "最近 photo_text 候选没有进入发送。", "到主动页筛选 photo_text", "proactive", "image.proactive_candidate_blocked")
        else:
            add("ok", "主动带图链路可尝试", "开关和可用性检查通过；是否出现取决于主动动机、天气/日程和候选权重。", "", "proactive")

        if bool(tts.get("enhancement_enabled")):
            if bool(tts.get("provider_available")):
                add("ok", "TTS provider 可用", f"模式 {tts.get('mode')}，语种 {tts.get('language')}，provider {tts.get('provider_label') or '-'}。", "", "modules")
            else:
                add("warn", "TTS 强化开启但合成 provider 不可用", "插件能处理 TTS 标签，但真实语音合成需要 AstrBot 当前会话启用 TTS provider。", "到 AstrBot 会话 TTS 配置启用 provider", "modules", "tts.provider_unavailable")
        else:
            add("info", "TTS 强化未开启", "模型不应被要求生成 TTS 标签；如仍出现标签，发送前会清理。", "", "modules")

        sqlite_bad = [item for item in sqlite_status.get("items", []) if item.get("level") in {"warn", "error"}]
        if sqlite_bad:
            add("warn", "SQLite 并发状态需要关注", sqlite_bad[0].get("text") or "有数据库未处于 WAL 或检查失败。", "重启插件后查看是否仍有 database is locked", "troubleshooting", "sqlite.wal")
        else:
            add("ok", "SQLite WAL 检查通过", f"已检查 {len(sqlite_status.get('items', []))} 个数据库文件。", "", "troubleshooting")

        token_errors = self._active_token_failures(token_stats.get("recent", []))
        if token_errors:
            first = token_errors[0]
            add("error", "最近存在模型调用失败", first.get("error") or f"{first.get('task') or '任务'} 调用失败。", "到 Token 页查看失败任务和 provider", "tokens")
        else:
            add("ok", "近期模型调用无待处理失败", "近 30 分钟内没有未恢复的模型调用失败；历史失败可在 Token 页查看。", "", "tokens")

        image_cache = cache.get("private_image_vision", {})
        if image_cache.get("enabled"):
            add("ok", "图片视觉缓存已开启", f"当前缓存 {image_cache.get('items', 0)}/{image_cache.get('max_items') or '不限'} 条。", "", "image-cache")
        else:
            add("info", "图片视觉缓存未开启", "重复表情包会重复调用视觉模型，但不影响首次识图。", "到模块配置开启重复图片缓存", "modules")
        provider_runtime = image_cache.get("provider_runtime") if isinstance(image_cache.get("provider_runtime"), dict) else {}
        provider_candidates = provider_runtime.get("candidates") if isinstance(provider_runtime.get("candidates"), list) else []
        usable_vision = [
            item for item in provider_candidates
            if isinstance(item, dict) and item.get("available") and item.get("supports_image") and not item.get("cooldown")
        ]
        provider_cooldowns = provider_runtime.get("cooldowns") if isinstance(provider_runtime.get("cooldowns"), list) else []
        last_success = provider_runtime.get("last_success") if isinstance(provider_runtime.get("last_success"), dict) else {}
        if provider_runtime.get("error"):
            add("warn", "私聊图片识别调度状态读取失败", provider_runtime.get("error") or "无法读取当前视觉模型状态。", "刷新排障页或查看日志", "troubleshooting", "vision.runtime_unreadable")
        elif not usable_vision:
            add(
                "warn",
                "私聊图片识别暂无可用模型",
                f"候选 {len(provider_candidates)} 个，但没有同时满足可用、支持图片且不在冷却的模型。",
                "检查快速配置/精准配置里的插件识图模型，或等待临时降权结束",
                "config",
                "vision.no_available_provider",
            )
        elif last_success.get("provider_id"):
            add(
                "ok",
                "私聊图片识别会尊重配置并记住视觉恢复候选",
                f"AstrBot 图片转文字配置仍保留首位；最近成功视觉模型：{last_success.get('provider_id')}（{last_success.get('source') or '来源未知'}，{last_success.get('time') or '刚刚'}）；当前可用 {len(usable_vision)} 个。",
                "",
                "troubleshooting",
            )
        else:
            first_provider = usable_vision[0].get("provider_id") if usable_vision and isinstance(usable_vision[0], dict) else "-"
            add("info", "私聊图片识别候选模型可用", f"当前可用 {len(usable_vision)} 个，首选 {first_provider}；成功一次后会记录为视觉恢复候选。", "", "troubleshooting")
        if provider_cooldowns:
            first_cooldown = provider_cooldowns[0] if isinstance(provider_cooldowns[0], dict) else {}
            add(
                "warn",
                "有识图模型被临时降权",
                f"{first_cooldown.get('provider_id') or '-'}：{first_cooldown.get('error') or '最近调用失败'}；到期 {first_cooldown.get('until') or '-'}。",
                "如果反复出现，换掉插件识图模型或调高单次超时",
                "config",
                "vision.provider_cooldown",
            )

        diag_warns = [item for item in diagnostics if item.get("level") in {"warn", "error"}]
        if diag_warns:
            add("info", "配置诊断仍有待处理项", f"{len(diag_warns)} 项需要关注：{diag_warns[0].get('title') or '-'}。", diag_warns[0].get("action") or "查看下方当前诊断", "troubleshooting", "diagnostic.pending")
            checks[-1].update({"aggregate": True, "counts_as_issue": False})
        else:
            add("ok", "配置诊断无待处理警告", "现有未屏蔽诊断项没有 warn/error。", "", "dashboard")
        return checks

    async def _sqlite_wal_status_summary(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        paths_getter = getattr(self.plugin, "_sqlite_wal_candidate_paths", None)
        paths = paths_getter() if callable(paths_getter) else []

        def inspect(path: Path) -> dict[str, Any]:
            try:
                conn = sqlite3.connect(str(path), timeout=2.0)
                try:
                    mode_row = conn.execute("PRAGMA journal_mode").fetchone()
                    timeout_row = conn.execute("PRAGMA busy_timeout").fetchone()
                    mode = str(mode_row[0] if mode_row else "").lower()
                    timeout_ms = self._int(timeout_row[0] if timeout_row else 0)
                finally:
                    conn.close()
                level = "ok" if mode == "wal" and timeout_ms >= 1000 else "warn"
                text = f"journal_mode={mode or '-'}，busy_timeout={timeout_ms}ms"
                return {"path": str(path), "name": path.name, "level": level, "text": text, "journal_mode": mode, "busy_timeout_ms": timeout_ms}
            except Exception as exc:
                return {"path": str(path), "name": path.name, "level": "error", "text": self._single_line(exc, 180)}

        for path in paths[:12]:
            items.append(await self._to_thread_sqlite_inspect(inspect, path))
        return {
            "items": items,
            "ok": sum(1 for item in items if item.get("level") == "ok"),
            "warn": sum(1 for item in items if item.get("level") == "warn"),
            "error": sum(1 for item in items if item.get("level") == "error"),
        }

    async def _to_thread_sqlite_inspect(self, func: Any, path: Path) -> dict[str, Any]:
        try:
            import asyncio

            return await asyncio.to_thread(func, path)
        except Exception:
            return func(path)
