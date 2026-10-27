# -*- coding: utf-8 -*-
"""Private Companion Page API - 主动候选管理与 token 统计 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import time
from copy import deepcopy

from astrbot.api import logger
from quart import request


class PrivateCompanionPageApiProactiveMixin:
    async def update_proactive_only_unlock(self) -> dict[str, Any]:
        try:
            payload = await request.get_json(silent=True) or {}
            key = self._single_line(payload.get("key"), 80)
            action = self._single_line(payload.get("action"), 20) or "unlock"
            sync_related = bool(payload.get("sync_related"))
            normalizer = getattr(self.plugin, "_normalize_proactive_only_unlock_key", None)
            normalized = normalizer(key) if callable(normalizer) else key
            if not normalized:
                return self._error("缺少要临时放行的功能")
            applier = getattr(self.plugin, "_apply_proactive_only_temp_unlock", None)
            if not callable(applier):
                return self._error("当前插件缺少主动专用模式临时放行接口")
            clear = action in {"clear", "remove", "cancel", "关闭", "取消"}
            message = applier(normalized, sync_related=sync_related, clear=clear)
            return self._ok(
                {
                    "message": message,
                    "proactive_only": self._proactive_only_mode_snapshot(),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新主动专用临时放行失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def delete_proactive_candidate(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        candidate_id = self._single_line(payload.get("candidate_id") or payload.get("id"), 40)
        if not candidate_id:
            return self._error("缺少 candidate_id")
        try:
            async with self.plugin._data_lock:
                raw = self.plugin.data.get("proactive_candidate_pool")
                if not isinstance(raw, list):
                    raw = []
                    self.plugin.data["proactive_candidate_pool"] = raw
                removed_item = None
                kept = []
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    if self._single_line(item.get("id"), 40) == candidate_id and removed_item is None:
                        removed_item = dict(item)
                        continue
                    kept.append(item)
                if removed_item is None:
                    return self._error("没有找到对应主动候选")
                self.plugin.data["proactive_candidate_pool"] = kept
                user_id = self._single_line(removed_item.get("user_id"), 40)
                users = self.plugin.data.get("users") if isinstance(self.plugin.data.get("users"), dict) else {}
                cleared_current_plan = False
                if user_id and isinstance(users.get(user_id), dict):
                    user = users[user_id]
                    if self._single_line(user.get("planned_candidate_id"), 40) == candidate_id:
                        clearer = getattr(self.plugin, "_clear_pending_proactive_plan", None)
                        scheduler = getattr(self.plugin, "_schedule_next_proactive", None)
                        if callable(clearer):
                            clearer(user)
                            cleared_current_plan = True
                        if callable(scheduler):
                            scheduler(user, now=time.time())
                    shrinker = getattr(self.plugin, "_shrink_user_proactive_candidates", None)
                    if callable(shrinker):
                        shrinker(user_id, note="page_delete")
                self.plugin._save_data_sync()
                data = self._overview_data_snapshot_locked(self.plugin.data)
            message = "已删除主动候选"
            if cleared_current_plan:
                message += "，并重新安排了下一次主动检查"
            return self._ok(
                {
                    "message": message,
                    "removed": True,
                    "cleared_current_plan": cleared_current_plan,
                    "proactive_candidates": self._proactive_candidate_summary(data),
                    "proactive_tasks": self._proactive_task_summary(data),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 删除主动候选失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def prune_proactive_candidates(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        user_id = self._single_line(payload.get("user_id"), 40)
        if not user_id:
            return self._error("缺少 user_id")
        keep = self._int(payload.get("keep"), 160, 1, 400)
        try:
            async with self.plugin._data_lock:
                shrinker = getattr(self.plugin, "_shrink_user_proactive_candidates", None)
                if not callable(shrinker):
                    return self._error("当前插件缺少主动候选收缩能力")
                removed = int(shrinker(user_id, pending_cap=keep, note="page_prune") or 0)
                self.plugin._save_data_sync()
                data = self._overview_data_snapshot_locked(self.plugin.data)
            return self._ok(
                {
                    "message": f"已为用户压缩 {removed} 条未发送候选",
                    "removed": removed,
                    "kept_limit": keep,
                    "proactive_candidates": self._proactive_candidate_summary(data),
                    "proactive_tasks": self._proactive_task_summary(data),
                }
            )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 压缩主动候选失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def get_token_stats(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                usage = deepcopy(self.plugin.data.get("token_usage", {}))
                balance_state = deepcopy(self.plugin.data.get("balance_awareness", {}))
            return self._ok(self._token_stats_payload(usage, balance_state))
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 获取 Token 统计失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def reset_token_stats(self) -> dict[str, Any]:
        try:
            async with self.plugin._data_lock:
                self.plugin.data["token_usage"] = {}
                balance_state = deepcopy(self.plugin.data.get("balance_awareness", {}))
                self.plugin._save_data_sync()
            return self._ok(self._token_stats_payload({}, balance_state))
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 重置 Token 统计失败: {exc}", exc_info=True)
            return self._error(str(exc))
