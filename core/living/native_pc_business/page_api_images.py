# -*- coding: utf-8 -*-
"""Private Companion Page API - 图片缓存 CRUD 与设置写/迁移 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote

from astrbot.api import logger
from quart import request, send_file

from .helpers import _safe_int

# PAGE_API_PREFIX / PrivateCompanionPageApi
# 由 page_api.py 在类定义完成后回填注入(见该文件末尾), 方法体保持逐字搬运。


class PrivateCompanionPageApiImagesMixin:
    def _cache_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        image_cache = data.get("private_image_vision_cache") if isinstance(data.get("private_image_vision_cache"), dict) else {}
        image_cache_count = self._int(data.get("private_image_vision_cache_count")) if "private_image_vision_cache_count" in data else len(image_cache)
        metrics = data.get("cache_metrics") if isinstance(data.get("cache_metrics"), dict) else {}

        def metric_row(name: str) -> dict[str, Any]:
            item = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
            hits = 0
            misses = 0
            try:
                hits = max(0, int(item.get("hits") or 0))
            except (TypeError, ValueError):
                hits = 0
            try:
                misses = max(0, int(item.get("misses") or 0))
            except (TypeError, ValueError):
                misses = 0
            total = hits + misses
            return {
                "hits": hits,
                "misses": misses,
                "total": total,
                "hit_rate": round(hits / total, 4) if total else 0,
                "last_hit_at": self.plugin._format_timestamp_elapsed(item.get("last_hit_ts", 0)),
                "last_miss_at": self.plugin._format_timestamp_elapsed(item.get("last_miss_ts", 0)),
            }

        atrelay_cache = getattr(self.plugin, "_atrelay_member_cache", {})
        atrelay_count = len(atrelay_cache) if isinstance(atrelay_cache, dict) else 0
        weather = data.get("daily_weather") if isinstance(data.get("daily_weather"), dict) else {}
        weather_age = self.plugin._format_timestamp_elapsed(weather.get("fetched_ts", 0)) if weather else ""
        provider_runtime: dict[str, Any] = {}
        runtime_getter = getattr(self.plugin, "_private_image_visual_provider_runtime_summary", None)
        if callable(runtime_getter):
            try:
                provider_runtime = runtime_getter()
            except Exception as exc:
                provider_runtime = {"error": self._single_line(exc, 160)}
        return {
            "private_image_vision": {
                "enabled": bool(getattr(self.plugin, "enable_private_image_vision_cache", False)),
                "items": image_cache_count,
                "max_items": int(getattr(self.plugin, "private_image_vision_cache_max_items", 0) or 0),
                "private": metric_row("image_vision:private_image"),
                "forward": metric_row("image_vision:forward_image"),
                "provider_runtime": provider_runtime,
            },
            "atrelay_member_cache": {
                "items": atrelay_count,
                "ttl_minutes": int(getattr(self.plugin, "atrelay_member_cache_minutes", 0) or 0),
            },
            "weather": {
                "cached": bool(weather),
                "age": weather_age,
                "source": self._single_line(weather.get("source"), 40),
                "summary": self._single_line(weather.get("prompt"), 120),
            },
        }

    async def list_image_cache(self) -> dict[str, Any]:
        try:
            scope_filter = self._single_line(request.args.get("scope"), 40)
            keyword = self._single_line(request.args.get("q"), 120).lower()
            limit = self._query_int("limit", 80, 1, 300)
            offset = self._query_int("offset", 0, 0, 100000)
            async with self.plugin._data_lock:
                data = deepcopy(self.plugin.data)
            cache = data.get("private_image_vision_cache") if isinstance(data.get("private_image_vision_cache"), dict) else {}
            rows: list[dict[str, Any]] = []
            scopes: set[str] = set()
            for key, raw in cache.items():
                if not isinstance(raw, dict):
                    continue
                item = self._image_cache_item_summary(str(key), raw)
                scope = item.get("scope") or "private_image"
                scopes.add(str(scope))
                if scope_filter and scope_filter != "all" and scope != scope_filter:
                    continue
                if keyword:
                    haystack = " ".join(
                        str(item.get(name) or "")
                        for name in (
                            "key",
                            "text",
                            "provider_id",
                            "scope",
                            "image_keys_text",
                            "image_aliases_text",
                            "image_type",
                            "ownership",
                            "intent",
                        )
                    ).lower()
                    if keyword not in haystack:
                        continue
                rows.append(item)
            rows.sort(
                key=lambda item: (
                    self._float(item.get("last_hit_ts"))
                    or self._float(item.get("created_ts")),
                    self._float(item.get("created_ts")),
                ),
                reverse=True,
            )
            total = len(rows)
            return self._ok(
                {
                    "items": rows[offset : offset + limit],
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "scopes": sorted(scopes),
                    "enabled": bool(getattr(self.plugin, "enable_private_image_vision_cache", False)),
                    "max_items": int(getattr(self.plugin, "private_image_vision_cache_max_items", 0) or 0),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取图片缓存失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_image_cache_item(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        key = self._single_line(payload.get("key"), 120)
        action = self._single_line(payload.get("action"), 20).lower() or "regenerate"
        if not key:
            return self._error("缺少缓存 key")
        text = str(payload.get("text") or "").strip()
        if not text:
            return self._error("视觉摘要不能为空")
        try:
            async with self.plugin._data_lock:
                cache = self.plugin.data.get("private_image_vision_cache")
                if not isinstance(cache, dict) or not isinstance(cache.get(key), dict):
                    return self._error("缓存条目不存在")
                item = cache[key]
                scope = self._single_line(item.get("scope"), 40) or "private_image"
                item["text"] = self._single_line(text, 900 if scope == "forward_image" else 600)
                if "provider_id" in payload:
                    item["provider_id"] = self._single_line(payload.get("provider_id"), 160)
                if "scope" in payload:
                    next_scope = self._single_line(payload.get("scope"), 40)
                    if next_scope:
                        item["scope"] = next_scope
                item["edited_ts"] = time.time()
                self.plugin._save_data_sync()
                updated = deepcopy(item)
            return self._ok(self._image_cache_item_summary(key, updated))
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新图片缓存失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _image_cache_preview_file(self, key: str, raw: dict[str, Any] | None = None) -> Path | None:
        clean_key = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(key or ""))[:80]
        if not clean_key:
            return None
        base = (Path(getattr(self.plugin, "data_dir", "")) / "private_image_cache_previews").resolve()
        candidates: list[Path] = []
        preview_path = self._single_line((raw or {}).get("preview_path"), 260) if isinstance(raw, dict) else ""
        if preview_path:
            try:
                candidates.append(Path(preview_path).resolve())
            except Exception:
                pass
        candidates.extend(base / f"{clean_key}{suffix}" for suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"))
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.is_relative_to(base):
                    return candidate
            except Exception:
                continue
        return None

    def _restore_image_cache_preview_metadata(self, key: str, raw: dict[str, Any]) -> bool:
        preview = self._image_cache_preview_file(key, raw)
        if preview is None:
            return False
        changed = False
        if self._single_line(raw.get("preview_path"), 260) != str(preview):
            raw["preview_path"] = str(preview)
            changed = True
        try:
            preview_size = preview.stat().st_size
        except Exception:
            preview_size = 0
        if _safe_int(raw.get("preview_size"), 0, 0) != preview_size:
            raw["preview_size"] = preview_size
            changed = True
        return changed

    async def get_image_cache_preview(self) -> Any:
        key = self._single_line(request.args.get("key"), 120)
        if not key:
            return self._error("缺少缓存 key")
        try:
            async with self.plugin._data_lock:
                cache = self.plugin.data.get("private_image_vision_cache")
                item = cache.get(key) if isinstance(cache, dict) else None
                if not isinstance(item, dict):
                    return self._error("缓存条目不存在")
                path = self._image_cache_preview_file(key, item)
                if path is None:
                    return self._error("缓存预览文件不存在")
                if self._restore_image_cache_preview_metadata(key, item):
                    self.plugin._save_data_sync()
            response = await send_file(str(path))
            response.headers["Cache-Control"] = "no-store, max-age=0"
            return response
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取图片缓存预览失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def delete_image_cache_item(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        key = self._single_line(payload.get("key"), 120)
        if not key:
            return self._error("缺少缓存 key")
        try:
            preview_path = ""
            async with self.plugin._data_lock:
                cache = self.plugin.data.get("private_image_vision_cache")
                if not isinstance(cache, dict) or key not in cache:
                    return self._error("缓存条目不存在")
                removed = cache.pop(key, None)
                if isinstance(removed, dict):
                    preview_path = self._single_line(removed.get("preview_path"), 260)
                self.plugin._save_data_sync()
                remaining = len(cache)
            self._remove_image_cache_preview_file(preview_path)
            return self._ok({"key": key, "remaining": remaining})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 删除图片缓存失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _remove_image_cache_preview_file(self, preview_path: str) -> None:
        if not preview_path:
            return
        try:
            path = Path(preview_path).resolve()
            base = (Path(getattr(self.plugin, "data_dir", "")) / "private_image_cache_previews").resolve()
            if path.is_file() and path.is_relative_to(base):
                path.unlink(missing_ok=True)
        except Exception:
            pass

    def _image_cache_item_summary(self, key: str, raw: dict[str, Any]) -> dict[str, Any]:
        text = str(raw.get("text") or "").strip()
        image_keys = [str(value).strip() for value in raw.get("image_keys", []) if str(value or "").strip()]
        image_aliases = [str(value).strip() for value in raw.get("image_aliases", []) if str(value or "").strip()]
        scope = self._single_line(raw.get("scope"), 40) or "private_image"
        created_ts = self._float(raw.get("created_ts"))
        last_hit_ts = self._float(raw.get("last_hit_ts"))
        edited_ts = self._float(raw.get("edited_ts"))
        preview_file = self._image_cache_preview_file(key, raw)
        preview_exists = preview_file is not None
        return {
            "key": self._single_line(key, 120),
            "text": self._single_line(text, 900 if scope == "forward_image" else 600),
            "provider_id": self._single_line(raw.get("provider_id"), 160),
            "scope": scope,
            "prompt_sig": self._single_line(raw.get("prompt_sig"), 32),
            "image_keys": image_keys[:8],
            "image_aliases": image_aliases[:12],
            "image_keys_text": " ".join(image_keys[:8]),
            "image_aliases_text": " ".join(image_aliases[:12]),
            "image_count": _safe_int(raw.get("image_count"), len(image_keys), 0),
            "preview_url": f"{PAGE_API_PREFIX}/image_cache/preview?key={quote(key, safe='')}" if preview_exists else "",
            "preview_size": _safe_int(raw.get("preview_size"), 0, 0),
            "preview_width": _safe_int(raw.get("preview_width"), 0, 0),
            "preview_height": _safe_int(raw.get("preview_height"), 0, 0),
            "hits": _safe_int(raw.get("hits"), 0, 0),
            "created_ts": created_ts,
            "last_hit_ts": last_hit_ts,
            "edited_ts": edited_ts,
            "created": self.plugin._format_timestamp_elapsed(created_ts),
            "last_hit": self.plugin._format_timestamp_elapsed(last_hit_ts),
            "edited": self.plugin._format_timestamp_elapsed(edited_ts),
            "image_type": self._extract_labeled_text(text, "图片类型", 40),
            "visible": self._extract_labeled_text(text, "可见内容", 180),
            "intent": self._extract_labeled_text(text, "图像表达意图", 180),
            "ownership": self._extract_labeled_text(text, "图像归属判断", 80),
        }

    @staticmethod
    def _extract_labeled_text(text: str, label: str, limit: int) -> str:
        source = str(text or "")
        pattern = rf"{re.escape(label)}\s*[：:]\s*(.+?)(?=(?:\s+[^\s：:]{{2,20}}\s*[：:])|$)"
        match = re.search(pattern, source)
        if not match:
            return ""
        return PrivateCompanionPageApi._single_line(match.group(1), limit)

    def _auto_import_worldbook_if_needed_locked(self) -> None:
        if not bool(getattr(self.plugin, "worldbook_auto_import", False)):
            return
        if not bool(getattr(self.plugin, "enable_worldbook_member_recognition", False)):
            return
        data = getattr(self.plugin, "data", {})
        if not isinstance(data, dict):
            return
        has_imported = bool(data.get("worldbook_entries")) or bool(data.get("worldbook_member_profiles")) or bool(data.get("worldbook_group_profiles"))
        if has_imported:
            return
        importer = getattr(self.plugin, "_import_worldbook_entries_from_sources", None)
        if not callable(importer):
            return
        if importer():
            self.plugin._save_data_sync()


    async def update_settings(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        try:
            changed: dict[str, Any] = {}
            if "group_access_mode" in payload:
                mode = str(payload.get("group_access_mode") or "").strip().lower()
                if mode not in {"whitelist", "blacklist"}:
                    return self._error("group_access_mode 只能是 whitelist 或 blacklist")
                changed["group_access_mode"] = mode
            if "group_whitelist_ids" in payload:
                changed["group_whitelist_ids"] = self._normalize_id_list(payload.get("group_whitelist_ids"))
            if "group_blacklist_ids" in payload:
                changed["group_blacklist_ids"] = self._normalize_id_list(payload.get("group_blacklist_ids"))
            for key, value in (payload.get("features") or {}).items():
                if key in self._allowed_feature_keys():
                    changed[key] = self._normalize_bool_value(value)
                elif key in self._schema_bool_keys() and key in self._allowed_setting_keys():
                    changed[key] = self._normalize_bool_value(value)
            provider_payload: dict[str, Any] = {}
            for key, value in (payload.get("providers") or {}).items():
                if key in self._allowed_provider_keys():
                    provider_payload[key] = self._single_line(value, 160)
            for key, value in (payload.get("settings") or {}).items():
                if key in self._allowed_setting_keys():
                    changed[key] = self._normalize_setting_value(key, value)
            if provider_payload:
                if bool(payload.get("overwrite_provider_modes")):
                    mode_value = changed.get("provider_config_mode") or self._config_get("provider_config_mode") or getattr(self.plugin, "provider_config_mode", "quick")
                    provider_payload = self._expand_provider_overwrite_bundle(str(mode_value), provider_payload)
                changed.update(provider_payload)
            storage_changed = bool({"storage_backend", "storage_sqlite_path"} & set(changed))
            apply_overrides = dict(changed)
            if storage_changed:
                apply_overrides["__defer_storage_rebuild"] = True
                flush_save = getattr(self.plugin, "_flush_scheduled_data_save", None)
                if callable(flush_save):
                    await flush_save()
            for key, value in changed.items():
                self._apply_config_value(key, value, apply_overrides)
            expression_scope_keys = {
                "expression_private_learning_source_mode",
                "expression_private_learning_source_ids",
                "expression_group_learning_source_mode",
                "expression_group_learning_source_ids",
                "expression_private_application_mode",
                "expression_private_application_user_ids",
                "expression_group_application_mode",
                "expression_group_application_ids",
            }
            if expression_scope_keys & set(changed):
                async with self.plugin._data_lock:
                    expression_refresher = getattr(self.plugin, "_refresh_expression_voice_profile", None)
                    if callable(expression_refresher):
                        expression_refresher()
                    self.plugin._save_data_sync()
            if storage_changed:
                rebuild = getattr(self.plugin, "_rebuild_store_manager", None)
                if callable(rebuild):
                    rebuild(reload_data=True)
            await self._record_personality_auto_tune_manual_values(changed)
            personality_restore: dict[str, Any] = {}
            if (
                ("enable_personality_iteration_experiment" in changed and not bool(changed.get("enable_personality_iteration_experiment")))
                or ("enable_personality_iteration_auto_tune" in changed and not bool(changed.get("enable_personality_iteration_auto_tune")))
            ):
                personality_restore = await self._restore_personality_iteration_auto_tune(
                    "角色贴合校准或自主调节已关闭"
                )
                restored_values = personality_restore.get("restored") if isinstance(personality_restore, dict) else {}
                if isinstance(restored_values, dict):
                    changed.update(restored_values)
            if any(key in self._allowed_provider_keys() for key in changed) or "provider_config_mode" in changed:
                apply_quick = getattr(self.plugin, "_apply_quick_provider_defaults", None)
                if callable(apply_quick):
                    apply_quick()
            clearer = getattr(self.plugin, "_clear_proactive_only_temp_unlocks_if_mode_off", None)
            if callable(clearer):
                clearer()
            config_saved = True
            if changed:
                config_saved = await self._save_config_if_possible()
            overview = await self.get_overview()
            if overview.get("success"):
                overview["data"]["changed"] = changed
                overview["data"]["config_saved"] = config_saved
                if personality_restore:
                    overview["data"]["personality_auto_tune_restore"] = personality_restore
                data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
                features = data.get("features") if isinstance(data.get("features"), dict) else {}
                settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
                for key, value in changed.items():
                    if key in self._allowed_feature_keys():
                        features[key] = self._normalize_bool_value(value)
                    if key in self._allowed_setting_keys():
                        settings[key] = value
            return overview
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新设置失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def swap_image_api_settings(self) -> dict[str, Any]:
        try:
            payload = await request.get_json(silent=True) or {}
            force = self._normalize_bool_value(payload.get("force"))
            normalizer = getattr(self.plugin, "_normalize_external_image_api_endpoints", None)
            raw_endpoints = self._config_get_raw("external_image_api_endpoints", [])
            endpoints = normalizer(raw_endpoints) if callable(normalizer) else (raw_endpoints if isinstance(raw_endpoints, list) else [])
            if endpoints:
                if len(endpoints) < 2:
                    return self._error("在线生图 API 队列少于 2 条，无法交换优先级。")
                second = endpoints[1] if isinstance(endpoints[1], dict) else {}
                second_missing = [
                    label
                    for key, label in (
                        ("base_url", "第二条 API 地址"),
                        ("api_key", "第二条 API Key"),
                        ("model", "第二条图片模型"),
                    )
                    if not str(second.get(key) or "").strip()
                ]
                if (not second.get("enabled", True) or second_missing) and not force:
                    reason = "第二条 API 已关闭" if not second.get("enabled", True) else "、".join(second_missing)
                    return self._error(f"第二条在线图片 API 不可用，不能切换：{reason}")
                changed = list(endpoints)
                changed[0], changed[1] = changed[1], changed[0]
                self._apply_config_value("external_image_api_endpoints", changed)
                config_saved = await self._save_config_if_possible()
                overview = await self.get_overview()
                if overview.get("success"):
                    data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
                    data["changed"] = {"external_image_api_endpoints": changed}
                    data["config_saved"] = config_saved
                    data["message"] = "已交换在线图片 API 队列前两项。"
                    overview["data"] = data
                return overview
            pairs = (
                ("external_image_api_platform", "backup_external_image_api_platform"),
                ("EXTERNAL_IMAGE_API_BASE_URL", "BACKUP_EXTERNAL_IMAGE_API_BASE_URL"),
                ("EXTERNAL_IMAGE_API_KEY", "BACKUP_EXTERNAL_IMAGE_API_KEY"),
                ("EXTERNAL_IMAGE_API_MODEL", "BACKUP_EXTERNAL_IMAGE_API_MODEL"),
                ("external_image_api_size", "backup_external_image_api_size"),
                ("external_image_api_timeout_seconds", "backup_external_image_api_timeout_seconds"),
                ("external_image_api_custom_headers", "backup_external_image_api_custom_headers"),
            )

            current: dict[str, Any] = {}
            for primary_key, backup_key in pairs:
                current[primary_key] = self._normalize_setting_value(primary_key, self._config_get(primary_key))
                current[backup_key] = self._normalize_setting_value(backup_key, self._config_get(backup_key))

            backup_required = (
                "BACKUP_EXTERNAL_IMAGE_API_BASE_URL",
                "BACKUP_EXTERNAL_IMAGE_API_KEY",
                "BACKUP_EXTERNAL_IMAGE_API_MODEL",
            )
            missing_backup = [key for key in backup_required if not str(current.get(key) or "").strip()]
            if missing_backup and not force:
                labels = {
                    "BACKUP_EXTERNAL_IMAGE_API_BASE_URL": "备选在线 API 地址",
                    "BACKUP_EXTERNAL_IMAGE_API_KEY": "备选在线 API Key",
                    "BACKUP_EXTERNAL_IMAGE_API_MODEL": "备选在线图片模型",
                }
                return self._error("备选在线图片 API 未配置完整，不能切换：" + "、".join(labels.get(key, key) for key in missing_backup))

            changed: dict[str, Any] = {}
            for primary_key, backup_key in pairs:
                changed[primary_key] = current.get(backup_key)
                changed[backup_key] = current.get(primary_key)

            old_primary_complete = bool(
                str(current.get("EXTERNAL_IMAGE_API_BASE_URL") or "").strip()
                and str(current.get("EXTERNAL_IMAGE_API_KEY") or "").strip()
                and str(current.get("EXTERNAL_IMAGE_API_MODEL") or "").strip()
            )
            changed["enable_backup_external_image_api"] = old_primary_complete

            for key, value in changed.items():
                self._apply_config_value(key, value, changed)
            self._sync_photo_generation_runtime_config()
            config_saved = await self._save_config_if_possible()
            overview = await self.get_overview()
            if overview.get("success"):
                data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
                data["changed"] = changed
                data["config_saved"] = config_saved
                data["message"] = "已交换主在线图片 API 与备选在线图片 API。"
                overview["data"] = data
            return overview
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 切换在线生图 API 失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def export_migration_config(self) -> dict[str, Any]:
        try:
            package = await self._build_migration_package(self._migration_export_options_from_request())
            return self._ok(package)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 导出配置备份失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def list_migration_backups(self) -> dict[str, Any]:
        try:
            return self._ok({"items": self._list_migration_backup_items(limit=8)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 读取配置备份列表失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def restore_migration_backup(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        try:
            backup_id = self._single_line(payload.get("id") or payload.get("name"), 160)
            path = self._resolve_migration_backup_path(backup_id)
            package = json.loads(path.read_text(encoding="utf-8-sig"))
            package = self._extract_migration_package(package)
            normalized = self._normalize_migration_package(package)
            overview = await self._apply_migration_normalized(normalized, mode="replace", conflict="use_backup")
            data = overview.get("data") if isinstance(overview.get("data"), dict) else {}
            data["message"] = "已从自动备份恢复。"
            data["restored_from"] = path.name
            overview["data"] = data
            return overview
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 恢复配置备份失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def preview_migration_config_import(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        try:
            package = self._extract_migration_package(
                payload,
                allow_checksum_mismatch=self._normalize_bool_value(payload.get("allow_checksum_mismatch")),
            )
            normalized = self._normalize_migration_package(package)
            summary = await self._migration_import_summary(normalized)
            summary["message"] = "已读取备份，确认后才会写入。"
            return self._ok(summary)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 预览配置导入失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def apply_migration_config_import(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        try:
            package = self._extract_migration_package(
                payload,
                allow_checksum_mismatch=self._normalize_bool_value(payload.get("allow_checksum_mismatch")),
            )
            mode = str(payload.get("mode") or "merge").strip().lower()
            if mode not in {"merge", "replace"}:
                mode = "merge"
            conflict = str(payload.get("conflict") or "use_backup").strip().lower()
            if conflict not in {"use_backup", "keep_current", "fill_empty"}:
                conflict = "use_backup"
            normalized = self._normalize_migration_package(package)
            if normalized.get("legacy_snapshot") and mode == "replace":
                mode = "merge"
            return await self._apply_migration_normalized(normalized, mode=mode, conflict=conflict)
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 应用配置导入失败: {exc}", exc_info=True)
            return self._error(str(exc))
