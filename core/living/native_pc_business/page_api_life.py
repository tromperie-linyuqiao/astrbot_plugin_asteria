# -*- coding: utf-8 -*-
"""Private Companion Page API - 生活数据/日常状态/token payload/LivingMemory 直查 mixin(自 page_api.py 拆分)。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from astrbot.api import logger
from quart import request

from .helpers import _text_looks_garbled, _today_key

# PrivateCompanionPageApi
# 由 page_api.py 在类定义完成后回填注入(见该文件末尾), 方法体保持逐字搬运。


class PrivateCompanionPageApiLifeMixin:
    async def update_skill_growth(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        skill_id = self._single_line(payload.get("id"), 40)
        name = self._single_line(payload.get("name"), 32)
        if not skill_id and not name:
            return self._error("缺少技能名称")
        def _parse_bool(value: Any, default: bool = False) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in {"1", "true", "yes", "on", "启用", "开启"}

        def _parse_terms(value: Any, *, limit: int = 16) -> list[str]:
            if isinstance(value, list):
                raw_items = value
            else:
                raw_items = re.split(r"[,，、\n]+", str(value or ""))
            items: list[str] = []
            for raw in raw_items:
                item = self._single_line(raw, 24)
                if item and item not in items:
                    items.append(item)
            return items[:limit]

        try:
            async with self.plugin._data_lock:
                state = self.plugin.data.setdefault("skill_growth", {})
                if not isinstance(state, dict):
                    state = {}
                    self.plugin.data["skill_growth"] = state
                skills = state.setdefault("skills", {})
                if not isinstance(skills, dict):
                    skills = {}
                    state["skills"] = skills

                if payload.get("delete"):
                    changed = bool(skill_id and skills.pop(skill_id, None) is not None)
                    state["updated_ts"] = time.time()
                    self.plugin._save_data_sync()
                    return self._ok({"changed": changed, "message": "已删除技能", "skill_growth": self._skill_growth_summary(self.plugin.data)})

                if not name:
                    return self._error("缺少技能名称")
                if not skill_id:
                    for existing_id, existing_skill in skills.items():
                        if not isinstance(existing_skill, dict):
                            continue
                        existing_name = self._single_line(existing_skill.get("name"), 32)
                        existing_aliases = existing_skill.get("aliases") if isinstance(existing_skill.get("aliases"), list) else []
                        alias_set = {self._single_line(item, 24) for item in existing_aliases}
                        if name == existing_name:
                            skill_id = self._single_line(existing_id, 40)
                            break
                        if name in alias_set:
                            return self._error(f"“{name}”已经是“{existing_name or '未命名技能'}”的合并别名，请直接编辑该技能")
                if not skill_id:
                    skill_id = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
                existing = skills.get(skill_id) if isinstance(skills.get(skill_id), dict) else {}
                level = max(1, min(6, self._int(payload.get("level")) or self._int(existing.get("level")) or 1))
                exp = self._float(payload.get("exp"))
                if exp <= 0 and isinstance(existing, dict):
                    exp = self._float(existing.get("exp"))
                if exp <= 0:
                    exp = {1: 0, 2: 100, 3: 260, 4: 520, 5: 900, 6: 1400}.get(level, 0)
                if hasattr(self.plugin, "_skill_level_from_exp"):
                    level = self.plugin._skill_level_from_exp(exp)
                keywords = _parse_terms(payload.get("keywords")) or [name]
                aliases = _parse_terms(payload.get("aliases"), limit=12)
                hidden = _parse_bool(payload.get("hidden"), bool(existing.get("hidden")) if isinstance(existing, dict) else False)
                frozen = _parse_bool(payload.get("frozen"), bool(existing.get("frozen")) if isinstance(existing, dict) else False)
                skill = dict(existing) if isinstance(existing, dict) else {}
                skill.update(
                    {
                        "id": skill_id,
                        "name": name,
                        "category": self._single_line(payload.get("category"), 20) or self._single_line(skill.get("category"), 20) or "能力",
                        "keywords": keywords,
                        "aliases": [item for item in aliases if item != name],
                        "hidden": hidden,
                        "frozen": frozen,
                        "exp": round(max(0.0, exp), 2),
                        "level": level,
                        "level_title": self.plugin._skill_level_title(level) if hasattr(self.plugin, "_skill_level_title") else self._single_line(skill.get("level_title"), 24),
                        "created_ts": self._float(skill.get("created_ts")) or time.time(),
                        "last_trained_ts": self._float(skill.get("last_trained_ts")),
                        "training_count": self._int(skill.get("training_count")),
                        "recent_logs": skill.get("recent_logs") if isinstance(skill.get("recent_logs"), list) else [],
                    }
                )
                skills[skill_id] = skill
                state["updated_ts"] = time.time()
                self.plugin._save_data_sync()
                return self._ok({"message": "已保存技能", "skill_growth": self._skill_growth_summary(self.plugin.data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新技能失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_personal_goal(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        goal_id = self._single_line(payload.get("id"), 40)
        title = self._single_line(payload.get("title"), 60)
        if not goal_id and not title:
            return self._error("缺少目标名称")

        def parse_terms(value: Any) -> list[str]:
            raw = value if isinstance(value, list) else re.split(r"[,，、\n]+", str(value or ""))
            terms: list[str] = []
            for item in raw:
                term = self._single_line(item, 32)
                if term and term not in terms:
                    terms.append(term)
            return terms[:16]

        try:
            async with self.plugin._data_lock:
                goals = self.plugin.data.setdefault("personal_goals", [])
                if not isinstance(goals, list):
                    goals = []
                    self.plugin.data["personal_goals"] = goals
                index = next(
                    (idx for idx, item in enumerate(goals) if isinstance(item, dict) and self._single_line(item.get("id"), 40) == goal_id),
                    -1,
                )
                if payload.get("delete"):
                    if index >= 0:
                        goals.pop(index)
                    self.plugin._save_data_sync()
                    return self._ok({"changed": index >= 0, "message": "已删除个人目标", "personal_goals": self._personal_goal_summary(self.plugin.data)})
                if not title:
                    return self._error("缺少目标名称")
                category = self._single_line(payload.get("category"), 24) or "生活"
                if any(token in category for token in ("创作", "写作", "绘画创作", "作品")):
                    return self._error("创作型目标请继续使用创作项目，这里只管理非创作型个人目标")
                existing = goals[index] if index >= 0 and isinstance(goals[index], dict) else {}
                if index < 0 and any(self._single_line(item.get("title"), 60) == title for item in goals if isinstance(item, dict)):
                    return self._error("已经存在同名个人目标")
                status = self.plugin._personal_goal_status(payload.get("status") or existing.get("status"))
                old_progress = max(0, min(100, self._int(existing.get("progress"))))
                progress = max(0, min(100, self._int(payload.get("progress")) if payload.get("progress") is not None else self._int(existing.get("progress"))))
                if status == "completed":
                    progress = 100
                elif progress >= 100:
                    status = "completed"
                now = time.time()
                keywords = parse_terms(payload.get("keywords")) if "keywords" in payload else parse_terms(existing.get("keywords"))
                if index < 0 and not keywords:
                    keywords = [title]
                goal = dict(existing)
                goal.update(
                    {
                        "id": goal_id or uuid.uuid4().hex[:12],
                        "title": title,
                        "category": category,
                        "status": status,
                        "progress": progress,
                        "next_step": self._single_line(payload.get("next_step") if "next_step" in payload else existing.get("next_step"), 100),
                        "note": self._single_line(payload.get("note") if "note" in payload else existing.get("note"), 160),
                        "keywords": keywords,
                        "auto_step": max(1, min(50, self._int(payload.get("auto_step")) or self._int(existing.get("auto_step")) or 10)),
                        "created_at": self._float(existing.get("created_at")) or now,
                        "updated_at": now,
                        "last_progress_at": self._float(existing.get("last_progress_at")) or now,
                        "recent_logs": existing.get("recent_logs") if isinstance(existing.get("recent_logs"), list) else [],
                    }
                )
                if progress > old_progress:
                    goal["last_progress_at"] = now
                    goal["stalled_notified_at"] = 0
                    logs = goal.setdefault("recent_logs", [])
                    if not isinstance(logs, list):
                        logs = []
                        goal["recent_logs"] = logs
                    logs.append({"ts": now, "kind": "manual_progress", "progress": progress, "evidence": "在陪伴面板中手动更新"})
                    del logs[:-12]
                    if progress >= 100:
                        goal["pending_share_event"] = {"kind": "completed", "evidence": "在陪伴面板中手动更新为已完成"}
                    elif progress // 25 > old_progress // 25:
                        goal["pending_share_event"] = {"kind": "progress", "milestone": (progress // 25) * 25, "evidence": "在陪伴面板中手动更新进度"}
                elif progress < old_progress:
                    goal.pop("pending_share_event", None)
                if status in {"paused", "abandoned"}:
                    goal.pop("pending_share_event", None)
                if status == "completed" and not self._float(goal.get("completed_at")):
                    goal["completed_at"] = now
                elif status != "completed":
                    goal["completed_at"] = 0
                if index >= 0:
                    goals[index] = goal
                else:
                    goals.append(goal)
                self.plugin._save_data_sync()
                return self._ok({"message": "已保存个人目标", "personal_goals": self._personal_goal_summary(self.plugin.data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新个人目标失败: {exc}", exc_info=True)
            return self._error(str(exc))

    @staticmethod
    def _food_menu_parse_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "on", "启用", "开启", "是", "常吃"}

    def _food_menu_parse_terms(self, value: Any, *, limit: int = 12, item_limit: int = 24) -> list[str]:
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = re.split(r"[,，、\n/|#]+", str(value or ""))
        items: list[str] = []
        for raw in raw_items:
            item = self._single_line(raw, item_limit)
            if item and item not in items:
                items.append(item)
        return items[:limit]

    def _food_menu_normalize_times(self, value: Any) -> list[str]:
        mapping = {
            "早餐": "breakfast",
            "早饭": "breakfast",
            "早上": "breakfast",
            "breakfast": "breakfast",
            "午餐": "lunch",
            "午饭": "lunch",
            "中午": "lunch",
            "lunch": "lunch",
            "晚餐": "dinner",
            "晚饭": "dinner",
            "晚上": "dinner",
            "dinner": "dinner",
            "夜宵": "late_night",
            "宵夜": "late_night",
            "深夜": "late_night",
            "late_night": "late_night",
            "latenight": "late_night",
            "加餐": "snack",
            "零食": "snack",
            "下午茶": "snack",
            "snack": "snack",
        }
        normalized: list[str] = []
        for raw in self._food_menu_parse_terms(value, limit=5, item_limit=16):
            key = mapping.get(str(raw).strip().lower()) or mapping.get(str(raw).strip())
            if key and key not in normalized:
                normalized.append(key)
        return normalized

    def _food_menu_infer_fields(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        text = " ".join(
            str(payload.get(key) or "")
            for key in ("type", "category", "tags", "times", "note")
        )
        text = f"{name} {text}"
        item_type = self._single_line(payload.get("type"), 20)
        if not item_type:
            if any(token in text for token in ("奶茶", "咖啡", "甜品", "蛋糕", "水果", "零食", "饮料", "酸奶")):
                item_type = "drink_snack"
            elif any(token in text for token in ("外卖", "美团", "饿了么", "配送", "到家")):
                item_type = "takeout"
            elif any(token in text for token in ("店", "馆", "楼下", "附近", "食堂", "餐厅", "小吃街")):
                item_type = "restaurant"
            elif any(token in text for token in ("泡面", "速食", "面包", "麦片", "饼干", "应急")):
                item_type = "emergency"
            else:
                item_type = "dish"
        allowed_types = {"dish", "restaurant", "takeout", "drink_snack", "emergency"}
        if item_type not in allowed_types:
            item_type = "dish"

        category = self._single_line(payload.get("category"), 24)
        if not category:
            category_rules = [
                ("面食", ("面", "粉", "馄饨", "饺子", "抄手", "米线", "米粉", "螺蛳粉")),
                ("米饭", ("饭", "盖浇", "便当", "煲仔", "黄焖鸡", "咖喱")),
                ("快餐", ("汉堡", "炸鸡", "披萨", "麦当劳", "肯德基", "华莱士", "塔斯汀")),
                ("甜口", ("奶茶", "甜品", "蛋糕", "水果", "酸奶")),
                ("热锅", ("火锅", "麻辣烫", "冒菜", "砂锅", "关东煮")),
                ("应急", ("泡面", "速食", "面包", "麦片", "饼干")),
            ]
            category = next((label for label, tokens in category_rules if any(token in text for token in tokens)), "")

        tags = self._food_menu_parse_terms(payload.get("tags"), limit=10, item_limit=16)
        inferred_tags: list[str] = []
        tag_rules = [
            ("热乎", ("面", "粉", "粥", "汤", "馄饨", "米线", "火锅", "麻辣烫", "砂锅", "关东煮")),
            ("快", ("泡面", "速食", "便当", "外卖", "汉堡", "炸鸡", "麦当劳", "肯德基", "华莱士", "塔斯汀")),
            ("清淡", ("粥", "汤", "沙拉", "蒸", "清淡")),
            ("辣", ("辣", "麻辣", "川", "火锅", "冒菜", "麻辣烫", "螺蛳粉")),
            ("甜", ("奶茶", "甜品", "蛋糕", "水果", "酸奶")),
            ("顶饱", ("饭", "面", "粉", "汉堡", "便当", "盖浇", "黄焖鸡")),
            ("便宜", ("食堂", "快餐", "兰州", "沙县", "华莱士")),
        ]
        for tag, tokens in tag_rules:
            if any(token in text for token in tokens) and tag not in tags and tag not in inferred_tags:
                inferred_tags.append(tag)
        tags = (tags + inferred_tags)[:10]

        times = self._food_menu_normalize_times(payload.get("times"))
        if not times:
            if any(token in text for token in ("早餐", "早饭", "早上", "包子", "豆浆", "油条", "麦片", "面包")):
                times.append("breakfast")
            if any(token in text for token in ("奶茶", "咖啡", "甜品", "水果", "零食", "酸奶")):
                times.append("snack")
            if any(token in text for token in ("夜宵", "宵夜", "烧烤", "炸鸡", "泡面", "螺蛳粉")):
                times.append("late_night")
        return {"type": item_type, "category": category, "tags": tags, "times": times}

    def _food_menu_payload_from_line(self, line: str) -> dict[str, Any]:
        text = self._single_line(line, 220)
        parts = [self._single_line(part, 80) for part in re.split(r"[|｜\t]+", text) if self._single_line(part, 80)]
        name = self._single_line(parts[0] if parts else text, 40)
        payload: dict[str, Any] = {"name": name}
        if len(parts) >= 2:
            payload["category"] = parts[1]
        if len(parts) >= 3:
            payload["tags"] = parts[2]
        if len(parts) >= 4:
            payload["times"] = parts[3]
        return payload

    async def update_food_menu(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        item_id = self._single_line(payload.get("id"), 48)
        name = self._single_line(payload.get("name"), 40)

        try:
            async with self.plugin._data_lock:
                state = self.plugin.data.setdefault("food_menu", {})
                if not isinstance(state, dict):
                    state = {}
                    self.plugin.data["food_menu"] = state
                items = state.setdefault("items", [])
                if not isinstance(items, list):
                    items = []
                    state["items"] = items

                if payload.get("delete"):
                    before = len(items)
                    state["items"] = [item for item in items if not (isinstance(item, dict) and self._single_line(item.get("id"), 48) == item_id)]
                    state["updated_ts"] = time.time()
                    self.plugin._save_data_sync()
                    return self._ok({
                        "changed": len(state["items"]) != before,
                        "message": "已移出候选",
                        "food_menu": self._food_menu_summary(self.plugin.data),
                    })

                if not name:
                    return self._error("缺少名称")
                if not item_id:
                    for existing in items:
                        if not isinstance(existing, dict):
                            continue
                        existing_name = self._single_line(existing.get("name"), 40)
                        aliases = self._food_menu_parse_terms(existing.get("aliases"), limit=12, item_limit=24)
                        if name == existing_name or name in aliases:
                            item_id = self._single_line(existing.get("id"), 48)
                            break
                if not item_id:
                    item_id = f"food_{hashlib.sha1((name + str(time.time())).encode('utf-8')).hexdigest()[:12]}"

                existing_index = -1
                existing_item: dict[str, Any] = {}
                for index, item in enumerate(items):
                    if isinstance(item, dict) and self._single_line(item.get("id"), 48) == item_id:
                        existing_index = index
                        existing_item = dict(item)
                        break

                inferred = self._food_menu_infer_fields(name, payload)
                if "type" in payload:
                    item_type = self._single_line(payload.get("type"), 20) or inferred.get("type") or "dish"
                else:
                    item_type = self._single_line(existing_item.get("type"), 20) or inferred.get("type") or "dish"
                allowed_types = {"dish", "restaurant", "takeout", "drink_snack", "emergency"}
                if item_type not in allowed_types:
                    item_type = "dish"
                if "category" in payload:
                    category = self._single_line(payload.get("category"), 24)
                    if not category and existing_index < 0:
                        category = self._single_line(inferred.get("category"), 24)
                else:
                    category = self._single_line(existing_item.get("category"), 24) or self._single_line(inferred.get("category"), 24)
                if "tags" in payload:
                    tags = self._food_menu_parse_terms(payload.get("tags"), limit=10, item_limit=16)
                else:
                    tags = self._food_menu_parse_terms(existing_item.get("tags"), limit=10, item_limit=16)
                if not tags and existing_index < 0:
                    tags = list(inferred.get("tags") or [])
                if "times" in payload:
                    times = self._food_menu_normalize_times(payload.get("times"))
                else:
                    times = self._food_menu_normalize_times(existing_item.get("times"))
                if not times and existing_index < 0:
                    times = list(inferred.get("times") or [])
                item = dict(existing_item)
                item.update(
                    {
                        "id": item_id,
                        "name": name,
                        "type": item_type,
                        "category": category,
                        "tags": tags[:10],
                        "times": times[:5],
                        "avoid": self._food_menu_parse_terms(payload.get("avoid"), limit=8, item_limit=24),
                        "aliases": [value for value in self._food_menu_parse_terms(payload.get("aliases"), limit=10, item_limit=24) if value != name],
                        "note": self._single_line(payload.get("note"), 100),
                        "favorite": self._food_menu_parse_bool(payload.get("favorite"), bool(existing_item.get("favorite"))),
                        "hidden": self._food_menu_parse_bool(payload.get("hidden"), bool(existing_item.get("hidden"))),
                        "use_count": self._int(payload.get("use_count")) if "use_count" in payload else self._int(existing_item.get("use_count")),
                        "created_ts": self._float(existing_item.get("created_ts")) or time.time(),
                        "updated_ts": time.time(),
                        "last_used_at": self._float(existing_item.get("last_used_at")),
                        "last_recommended_at": self._float(existing_item.get("last_recommended_at")),
                    }
                )
                if existing_index >= 0:
                    items[existing_index] = item
                else:
                    items.append(item)
                state["updated_ts"] = time.time()
                self.plugin._save_data_sync()
                return self._ok({"message": "已保存候选", "food_menu": self._food_menu_summary(self.plugin.data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新吃什么候选失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def bulk_update_food_menu(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        raw_text = str(payload.get("text") or payload.get("items") or "").strip()
        favorite = self._food_menu_parse_bool(payload.get("favorite"), False)
        hidden = self._food_menu_parse_bool(payload.get("hidden"), False)
        if not raw_text:
            return self._error("先粘贴几样候选")
        lines = [
            self._single_line(part, 220)
            for part in re.split(r"[\r\n;；]+", raw_text)
            if self._single_line(part, 220)
        ]
        if not lines:
            return self._error("没有读到候选")
        added = 0
        updated = 0
        skipped = 0
        try:
            async with self.plugin._data_lock:
                state = self.plugin.data.setdefault("food_menu", {})
                if not isinstance(state, dict):
                    state = {}
                    self.plugin.data["food_menu"] = state
                items = state.setdefault("items", [])
                if not isinstance(items, list):
                    items = []
                    state["items"] = items
                for line in lines[:80]:
                    item_payload = self._food_menu_payload_from_line(line)
                    name = self._single_line(item_payload.get("name"), 40)
                    if not name:
                        skipped += 1
                        continue
                    existing_index = -1
                    existing_item: dict[str, Any] = {}
                    for index, item in enumerate(items):
                        if not isinstance(item, dict):
                            continue
                        existing_name = self._single_line(item.get("name"), 40)
                        aliases = self._food_menu_parse_terms(item.get("aliases"), limit=12, item_limit=24)
                        if name == existing_name or name in aliases:
                            existing_index = index
                            existing_item = dict(item)
                            break
                    inferred = self._food_menu_infer_fields(name, item_payload)
                    item_id = self._single_line(existing_item.get("id"), 48)
                    if not item_id:
                        item_id = f"food_{hashlib.sha1((name + str(time.time())).encode('utf-8')).hexdigest()[:12]}"
                    now = time.time()
                    existing_tags = self._food_menu_parse_terms(existing_item.get("tags"), limit=10, item_limit=16)
                    inferred_tags = [tag for tag in (inferred.get("tags") or []) if tag not in existing_tags]
                    existing_times = self._food_menu_normalize_times(existing_item.get("times"))
                    inferred_times = [time_key for time_key in (inferred.get("times") or []) if time_key not in existing_times]
                    item = dict(existing_item)
                    item.update(
                        {
                            "id": item_id,
                            "name": name,
                            "type": self._single_line(existing_item.get("type"), 20) or inferred.get("type") or "dish",
                            "category": self._single_line(item_payload.get("category"), 24)
                            or self._single_line(existing_item.get("category"), 24)
                            or self._single_line(inferred.get("category"), 24),
                            "tags": (existing_tags + inferred_tags)[:10],
                            "times": (existing_times + inferred_times)[:5],
                            "note": self._single_line(existing_item.get("note"), 100),
                            "favorite": bool(existing_item.get("favorite")) or favorite,
                            "hidden": bool(existing_item.get("hidden")) or hidden,
                            "use_count": self._int(existing_item.get("use_count")),
                            "created_ts": self._float(existing_item.get("created_ts")) or now,
                            "updated_ts": now,
                            "last_used_at": self._float(existing_item.get("last_used_at")),
                            "last_recommended_at": self._float(existing_item.get("last_recommended_at")),
                        }
                    )
                    if existing_index >= 0:
                        items[existing_index] = item
                        updated += 1
                    else:
                        items.append(item)
                        added += 1
                state["updated_ts"] = time.time()
                self.plugin._save_data_sync()
                return self._ok(
                    {
                        "message": f"已加入 {added} 个，更新 {updated} 个" + (f"，跳过 {skipped} 个" if skipped else ""),
                        "added": added,
                        "updated": updated,
                        "skipped": skipped,
                        "food_menu": self._food_menu_summary(self.plugin.data),
                    }
                )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 批量更新吃什么候选失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def bulk_delete_food_menu(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        raw_ids = payload.get("ids") if isinstance(payload.get("ids"), list) else []
        item_ids: list[str] = []
        for raw_id in raw_ids[:160]:
            item_id = self._single_line(raw_id, 48)
            if item_id and item_id not in item_ids:
                item_ids.append(item_id)
        if not item_ids:
            return self._error("请先选择要删除的候选")
        selected = set(item_ids)
        try:
            async with self.plugin._data_lock:
                state = self.plugin.data.setdefault("food_menu", {})
                if not isinstance(state, dict):
                    state = {}
                    self.plugin.data["food_menu"] = state
                items = state.get("items") if isinstance(state.get("items"), list) else []
                existing_ids = {
                    self._single_line(item.get("id"), 48)
                    for item in items
                    if isinstance(item, dict) and self._single_line(item.get("id"), 48)
                }
                remaining = [
                    item
                    for item in items
                    if not (isinstance(item, dict) and self._single_line(item.get("id"), 48) in selected)
                ]
                deleted_ids = [item_id for item_id in item_ids if item_id in existing_ids]
                missing_ids = [item_id for item_id in item_ids if item_id not in existing_ids]
                if deleted_ids:
                    state["items"] = remaining
                    state["updated_ts"] = time.time()
                    self.plugin._save_data_sync()
                return self._ok(
                    {
                        "message": f"已删除 {len(deleted_ids)} 个候选",
                        "deleted": len(deleted_ids),
                        "deleted_ids": deleted_ids,
                        "missing_ids": missing_ids,
                        "food_menu": self._food_menu_summary(self.plugin.data),
                    }
                )
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 批量删除吃什么候选失败: {exc}", exc_info=True)
            return self._error(str(exc))

    async def update_external_ability(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True) or {}
        normalizer = getattr(self.plugin, "_normalize_external_ability_name", None)
        name = self._single_line(payload.get("name"), 80)
        name = normalizer(name) if callable(normalizer) else name
        if not name:
            return self._error("缺少外部能力名称")
        try:
            async with self.plugin._data_lock:
                store_getter = getattr(self.plugin, "_external_ability_store", None)
                store = store_getter() if callable(store_getter) else self.plugin.data.setdefault("external_proactive_abilities", {})
                if not isinstance(store, dict):
                    store = {}
                    self.plugin.data["external_proactive_abilities"] = store
                item = store.get(name) if isinstance(store.get(name), dict) else {"name": name}
                if "enabled" in payload:
                    item["enabled"] = bool(payload.get("enabled"))
                if "share_probability" in payload:
                    item["share_probability"] = max(0.0, min(1.0, self._float(payload.get("share_probability"))))
                if "min_interval_hours" in payload:
                    item["min_interval_hours"] = max(0.0, self._float(payload.get("min_interval_hours")))
                if "config" in payload:
                    config = payload.get("config")
                    if isinstance(config, str):
                        import json
                        config = json.loads(config or "{}")
                    if not isinstance(config, dict):
                        return self._error("自定义配置必须是 JSON 对象")
                    item["config"] = config
                item["updated_ts"] = time.time()
                store[name] = item
                self.plugin._save_data_sync()
                data = deepcopy(self.plugin.data)
            return self._ok({"message": "已保存外部主动能力", "external_abilities": self._external_ability_summary(data)})
        except Exception as exc:
            logger.error(f"[PrivateCompanionPage] 更新外部主动能力失败: {exc}", exc_info=True)
            return self._error(str(exc))

    def _daily_state_summary(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict):
            return {}
        keys = ["date", "sleep", "dream", "health", "hunger", "body_cycle", "location", "weather", "mood_bias", "energy", "note"]
        summary = {key: state.get(key, "") for key in keys}
        runtime = state.get("sleep_runtime") if isinstance(state.get("sleep_runtime"), dict) else {}
        if runtime:
            summary["sleep_phase"] = self._single_line(runtime.get("label") or runtime.get("phase"), 40)
            summary["sleep_runtime"] = {
                "phase": self._single_line(runtime.get("phase"), 40),
                "label": self._single_line(runtime.get("label") or runtime.get("phase"), 40),
                "last_event": self._single_line(runtime.get("last_event"), 120),
                "source": self._single_line(runtime.get("source"), 40),
                "woken_count": self._int(runtime.get("woken_count")),
                "updated_at": self.plugin._format_timestamp_elapsed(runtime.get("updated_at", 0)),
            }
            delay_until = self._float(runtime.get("sleep_delay_until_ts"), 0)
            if delay_until > time.time():
                summary["sleep_delay_override"] = {
                    "active": True,
                    "until": self._single_line(runtime.get("sleep_delay_until_text"), 40)
                    or self.plugin._environment_fromtimestamp(delay_until).strftime("%m-%d %H:%M"),
                    "reason": self._single_line(runtime.get("sleep_delay_reason"), 120),
                    "user_text": self._single_line(runtime.get("sleep_delay_user_text"), 120),
                    "explicit_time": bool(runtime.get("sleep_delay_explicit_time")),
                }
        return summary

    def _life_observation_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        dream = data.get("daily_dream") if isinstance(data.get("daily_dream"), dict) else {}
        diaries = data.get("bot_diaries") if isinstance(data.get("bot_diaries"), list) else []
        fragments = data.get("dream_fragments") if isinstance(data.get("dream_fragments"), list) else []
        plan = data.get("daily_plan") if isinstance(data.get("daily_plan"), dict) else {}
        story = data.get("daily_story_plan") if isinstance(data.get("daily_story_plan"), dict) else {}
        current_item = {}
        current_lifecycle = ""
        try:
            picked = self.plugin._get_current_plan_item(plan)
            current_item = picked if isinstance(picked, dict) else {}
            items = plan.get("items") if isinstance(plan.get("items"), list) else []
            current_index = next((index for index, item in enumerate(items) if item is picked), -1)
            if current_item:
                current_lifecycle = self.plugin._plan_item_runtime_status(plan, current_item, current_index)
        except Exception:
            current_item = {}

        return {
            "dream": {
                "date": self._single_line(dream.get("date"), 24),
                "label": self._single_line(dream.get("label"), 120),
                "dream_type": self._single_line(dream.get("dream_type"), 40),
                "content": self._single_line(dream.get("content"), 1000),
                "afterglow": self._single_line(dream.get("afterglow"), 220),
                "mood": self._single_line(dream.get("mood"), 30),
                "energy_delta": self._int(dream.get("energy_delta")),
                "duration_hours": self._int(dream.get("duration_hours")),
                "generated_at": self._single_line(dream.get("generated_at"), 24),
                "factors": [self._single_line(item, 40) for item in dream.get("factors", [])[:8] if self._single_line(item, 40)]
                if isinstance(dream.get("factors"), list)
                else [],
            },
            "diaries": [
                {
                    "date": self._single_line(item.get("date"), 24),
                    "summary": self.plugin._polish_diary_text(item.get("summary"), field="summary"),
                    "body": self.plugin._polish_diary_text(item.get("body"), field="body"),
                    "share_seed": self.plugin._polish_diary_text(item.get("share_seed"), field="share"),
                    "tags": [self._single_line(tag, 20) for tag in item.get("tags", [])[:6] if self._single_line(tag, 20)]
                    if isinstance(item.get("tags"), list)
                    else [],
                    "generated_at": self._single_line(item.get("generated_at"), 24),
                }
                for item in diaries[-4:]
                if isinstance(item, dict)
            ],
            "dream_fragments": self._limited_dream_fragments(fragments),
            "current_plan": {
                "time": self._single_line(current_item.get("time"), 12),
                "end": self._single_line(current_item.get("end"), 12),
                "lifecycle": current_lifecycle,
                "activity": self._single_line(current_item.get("activity"), 600),
                "mood": self._single_line(current_item.get("mood"), 40),
                "message_seed": self._single_line(current_item.get("message_seed"), 500),
            },
            "story": {
                "date": self._single_line(story.get("date"), 24),
                "today_events": self._limited_story_items(story.get("today_events"), 4),
                "proactive_events": self._limited_story_items(story.get("proactive_events"), 4),
            },
        }

    def _daily_timeline_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        plan = data.get("daily_plan") if isinstance(data.get("daily_plan"), dict) else {}
        enhanced = data.get("detail_enhanced_segments") if isinstance(data.get("detail_enhanced_segments"), dict) else {}
        story = data.get("daily_story_plan") if isinstance(data.get("daily_story_plan"), dict) else {}
        adjustments = data.get("schedule_adjustments") if isinstance(data.get("schedule_adjustments"), list) else []
        presence = data.get("qq_presence_state") if isinstance(data.get("qq_presence_state"), dict) else {}

        segments: list[dict[str, Any]] = []
        seen_segment_keys: set[str] = set()
        plan_items = plan.get("items") if isinstance(plan.get("items"), list) else []
        normalized_starts = self.plugin._normalized_plan_item_starts(plan_items)
        for key, snapshot in enhanced.items():
            if not isinstance(snapshot, dict):
                continue
            segment = self._segment_from_key(str(key), plan, snapshot)
            seen_segment_keys.add(str(key))
            segment_item = segment.get("item") if isinstance(segment.get("item"), dict) else {}
            lifecycle = self.plugin._plan_item_runtime_status(
                plan,
                segment_item,
                self._int(segment.get("index"), -1, -1),
            ) if segment_item else "planned"
            segments.append(
                {
                    "key": str(key),
                    "window": segment.get("window", str(key)),
                    "start": segment.get("start", 99999),
                    "end": segment.get("end", 99999),
                    "lifecycle": lifecycle,
                    "activity": self._single_line(segment_item.get("activity"), 180),
                    "basis": self.plugin._normalize_schedule_basis(segment_item.get("basis"), default=["coarse_plan"]),
                    "confidence": self._float(segment_item.get("confidence"), 0.72, 0.0, 1.0),
                    "status": snapshot.get("status", ""),
                    "started_at": snapshot.get("started_at", ""),
                    "summary": snapshot.get("summary", ""),
                    "summary_basis": self.plugin._normalize_schedule_basis(snapshot.get("summary_basis"), default=["coarse_plan"]),
                    "summary_confidence": self._float(snapshot.get("summary_confidence"), 0.75, 0.0, 1.0),
                    "quality": snapshot.get("quality") if isinstance(snapshot.get("quality"), dict) else {},
                    "regeneration_error": self._single_line(snapshot.get("regeneration_error"), 180),
                    "error": snapshot.get("error", ""),
                    "retry_after": snapshot.get("retry_after", ""),
                    "state_variables": self._limited_state_variables(snapshot.get("state_variables")),
                    "presence_status": snapshot.get("presence_status") if isinstance(snapshot.get("presence_status"), dict) else {},
                    "interaction_updates": self._limited_interaction_updates(snapshot.get("interaction_updates")),
                    "today_events": self._timeline_story_items(snapshot.get("today_events"), 5, str(plan.get("date") or "")),
                    "proactive_events": self._timeline_story_items(snapshot.get("proactive_events"), 4, str(plan.get("date") or "")),
                }
            )
        for index, item in enumerate(plan_items):
            if not isinstance(item, dict):
                continue
            start_text = self._single_line(item.get("time"), 8)
            start = normalized_starts[index] if index < len(normalized_starts) else None
            if start is None:
                continue
            key = f"{plan.get('date')}:{index}:{start_text}"
            if key in seen_segment_keys:
                continue
            next_start = None
            for next_item in plan_items[index + 1 :]:
                if isinstance(next_item, dict):
                    next_start = self.plugin._parse_hhmm_to_minutes(next_item.get("time"))
                    if next_start is not None:
                        break
            end = self.plugin._plan_item_end_minutes(start, item, next_start=next_start)
            segments.append(
                {
                    "key": key,
                    "window": f"{self.plugin._minutes_to_hhmm(start)}-{self.plugin._minutes_to_hhmm(end)}",
                    "start": start,
                    "end": end,
                    "lifecycle": self.plugin._plan_item_runtime_status(plan, item, index),
                    "activity": self._single_line(item.get("activity"), 180),
                    "basis": self.plugin._normalize_schedule_basis(item.get("basis"), default=["coarse_plan"]),
                    "confidence": self._float(item.get("confidence"), 0.72, 0.0, 1.0),
                    "status": "",
                    "summary": self._single_line(item.get("activity"), 180),
                    "summary_basis": self.plugin._normalize_schedule_basis(item.get("basis"), default=["coarse_plan"]),
                    "summary_confidence": self._float(item.get("confidence"), 0.72, 0.0, 1.0),
                    "quality": {},
                    "state_variables": [],
                    "presence_status": {},
                    "interaction_updates": [],
                    "today_events": [],
                    "proactive_events": [],
                }
            )
        segments.sort(key=lambda item: item.get("start", 99999))

        return {
            "plan_date": plan.get("date", ""),
            "story_date": story.get("date", ""),
            "detail_day": data.get("detail_enhanced_day", ""),
            "segment_count": len(segments),
            "plan_quality": plan.get("quality") if isinstance(plan.get("quality"), dict) else {},
            "segments": segments,
            "story_today_events": self._limited_story_items(story.get("today_events"), 48),
            "story_proactive_events": self._limited_story_items(story.get("proactive_events"), 32),
            "adjustments": self._limited_adjustments(adjustments),
            "qq_presence_state": presence,
        }

    def _segment_from_key(self, key: str, plan: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        keyed = re.fullmatch(r"(\d{4}-\d{2}-\d{2}):(\d+):(\d{1,2}:\d{2})", key)
        if keyed:
            index = int(keyed.group(2))
            key_start_text = keyed.group(3)
            start = self.plugin._parse_hhmm_to_minutes(key_start_text)
            items = []
            if isinstance(plan, dict):
                if isinstance(plan.get("items"), list):
                    items = plan.get("items") or []
                elif isinstance(plan.get("schedule"), list):
                    items = plan.get("schedule") or []
            end = None
            current_item = items[index] if isinstance(items, list) and index < len(items) and isinstance(items[index], dict) else None
            if isinstance(current_item, dict) and self._single_line(current_item.get("time"), 8) == key_start_text:
                starts = self.plugin._normalized_plan_item_starts(items)
                if index < len(starts) and starts[index] is not None:
                    start = starts[index]
            else:
                current_item = None
            if isinstance(current_item, dict):
                end = self.plugin._parse_hhmm_to_minutes(current_item.get("end"))
                if start is not None and end is not None and end <= start:
                    end += 24 * 60
            if isinstance(items, list):
                for next_item in items[index + 1:]:
                    if end is not None:
                        break
                    if isinstance(next_item, dict):
                        end = self.plugin._parse_hhmm_to_minutes(next_item.get("time"))
                        if end is not None:
                            break
            if start is not None:
                if end is None:
                    end = self.plugin._plan_item_end_minutes(start, current_item)
                return {
                    "window": f"{self.plugin._minutes_to_hhmm(start)}-{self.plugin._minutes_to_hhmm(end)}",
                    "start": start,
                    "end": end,
                    "index": index,
                    "item": current_item or {},
                }

        inferred = self._segment_from_story_windows(snapshot)
        if inferred:
            return inferred

        match = re.search(r"(?:^|[:|_])(\d{1,4})[-_](\d{1,4})(?:$|[:|_])", key)
        if not match:
            return {"window": key, "start": 99999}
        start = int(match.group(1))
        end = int(match.group(2))
        if not (0 <= start < 24 * 60 and 0 < end <= 28 * 60):
            return {"window": key, "start": 99999}
        return {"window": f"{self.plugin._minutes_to_hhmm(start)}-{self.plugin._minutes_to_hhmm(end)}", "start": start}

    def _memory_plugin_token_usage_raw(self) -> dict[str, Any]:
        getter = getattr(self.plugin, "_memory_companion_token_usage_summary", None)
        if not callable(getter):
            return {"available": False, "display_name": "我会牢牢记住你", "reason": "陪伴插件当前未接入记忆插件桥"}
        try:
            usage = getter()
        except Exception as exc:
            return {"available": False, "display_name": "我会牢牢记住你", "reason": self._single_line(exc, 160)}
        if not isinstance(usage, dict):
            return {"available": False, "display_name": "我会牢牢记住你", "reason": "记忆插件返回的 Token 统计格式无效"}
        usage.setdefault("available", True)
        usage.setdefault("display_name", "我会牢牢记住你")
        usage.setdefault("counted_in_private_companion_budget", False)
        return usage

    def _balance_status_payload(self, state: Any = None) -> dict[str, Any]:
        raw = state if isinstance(state, dict) else {}

        def optional_number(value: Any) -> float | None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if math.isfinite(number) else None

        amount = optional_number(raw.get("amount"))
        total = optional_number(raw.get("total"))
        remaining_percent = optional_number(raw.get("remaining_percent"))
        tier = self._single_line(raw.get("tier"), 20) or "unknown"
        if tier not in {"normal", "low", "critical", "unknown"}:
            tier = "unknown"
        enabled = bool(getattr(self.plugin, "enable_balance_awareness", False))
        manual_configured = bool(str(getattr(self.plugin, "balance_api_url", "") or "").strip())
        auto_available_getter = getattr(self.plugin, "_balance_auto_discovery_available", None)
        try:
            auto_discovery_available = bool(auto_available_getter()) if callable(auto_available_getter) else False
        except Exception:
            auto_discovery_available = False
        configured = manual_configured or auto_discovery_available
        query_mode = self._single_line(raw.get("query_mode"), 20)
        if query_mode not in {"manual", "auto"}:
            query_mode = "manual" if manual_configured else "auto"
        return {
            "enabled": enabled,
            "configured": configured,
            "manual_configured": manual_configured,
            "auto_discovery_available": auto_discovery_available,
            "query_mode": query_mode,
            "source_label": self._single_line(raw.get("auto_source_id"), 80),
            "available": bool(enabled and configured and amount is not None and self._float(raw.get("last_success_at")) > 0),
            "amount": amount,
            "total": total,
            "remaining_percent": remaining_percent,
            "currency_label": self._single_line(
                raw.get("currency_label") or getattr(self.plugin, "balance_currency_label", "元"),
                20,
            ) or "元",
            "tier": tier,
            "last_check_at": self._float(raw.get("last_check_at")),
            "last_success_at": self._float(raw.get("last_success_at")),
            "next_check_at": self._float(raw.get("next_check_at")),
            "last_prompted_at": self._float(raw.get("last_prompted_at")),
            "consecutive_failures": self._int(raw.get("consecutive_failures")),
            "last_error": self._single_line(raw.get("last_error"), 180),
        }

    def _token_stats_payload(self, usage: Any, balance_state: Any = None) -> dict[str, Any]:
        if not isinstance(usage, dict):
            usage = {}
        external_usage = usage.get("external") if isinstance(usage.get("external"), dict) else {}
        memory_plugin_usage = self._memory_plugin_token_usage_raw()
        totals = self._token_bucket(usage.get("totals"))
        by_provider = self._token_ranked_map(usage.get("by_provider"))
        by_task = self._token_ranked_map(usage.get("by_task"))
        by_day = self._token_series_map(usage.get("by_day"), limit=30)
        by_day_provider_raw = usage.get("by_day_provider") if isinstance(usage.get("by_day_provider"), dict) else {}
        by_day_task_raw = usage.get("by_day_task") if isinstance(usage.get("by_day_task"), dict) else {}
        by_day_detail = []
        for item in by_day:
            day_key = item.get("key", "")
            providers = self._token_ranked_map(by_day_provider_raw.get(day_key))[:5]
            tasks = self._token_ranked_map(by_day_task_raw.get(day_key))[:6]
            by_day_detail.append({**item, "providers": providers, "tasks": tasks})
        by_hour = self._token_series_map(usage.get("by_hour"), limit=48)
        today_key = _today_key()
        today_bucket = usage.get("by_day", {}).get(today_key, {}) if isinstance(usage.get("by_day"), dict) else {}
        today_total_tokens = self._int(today_bucket.get("total_tokens")) if isinstance(today_bucket, dict) else 0
        exempt_by_day = usage.get("budget_exempt_by_day") if isinstance(usage.get("budget_exempt_by_day"), dict) else {}
        today_exempt_bucket = exempt_by_day.get(today_key, {}) if isinstance(exempt_by_day, dict) else {}
        today_exempt_tokens = self._int(today_exempt_bucket.get("total_tokens")) if isinstance(today_exempt_bucket, dict) else 0
        if today_exempt_tokens <= 0:
            today_tasks = by_day_task_raw.get(today_key, {}) if isinstance(by_day_task_raw, dict) else {}
            if isinstance(today_tasks, dict):
                is_exempt_task = getattr(self.plugin, "_is_llm_budget_exempt_task", None)
                today_exempt_tokens = sum(
                    self._int(bucket.get("total_tokens"))
                    for task, bucket in today_tasks.items()
                    if (
                        (
                            callable(is_exempt_task)
                            and is_exempt_task(task)
                        )
                        or (
                            not callable(is_exempt_task)
                            and str(task) in {"proactive_framework", "voice_framework"}
                        )
                    )
                    and isinstance(bucket, dict)
                )
        today_tokens = max(0, today_total_tokens - today_exempt_tokens)
        daily_limit = self._int(getattr(self.plugin, "daily_token_limit", 0))
        soft_limit = self._int(getattr(self.plugin, "daily_token_soft_limit", 0))
        soft_enabled = bool(getattr(self.plugin, "enable_daily_token_soft_limit", True))
        budget_skips = usage.get("budget_skips", {})
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
        recent_raw = usage.get("recent")
        recent = []
        if isinstance(recent_raw, list):
            for item in recent_raw[-80:][::-1]:
                if not isinstance(item, dict):
                    continue
                recent.append(
                    {
                        "time": self._single_line(item.get("time"), 24),
                        "ts": self._float(item.get("ts")),
                        "provider": self._single_line(item.get("provider"), 80),
                        "task": self._single_line(item.get("task"), 40),
                        "success": bool(item.get("success", True)),
                        "prompt_tokens": self._int(item.get("prompt_tokens")),
                        "completion_tokens": self._int(item.get("completion_tokens")),
                        "total_tokens": self._int(item.get("total_tokens")),
                        "cached_tokens": self._int(item.get("cached_tokens")),
                        "cache_read_tokens": self._int(item.get("cache_read_tokens")),
                        "cache_write_tokens": self._int(item.get("cache_write_tokens")),
                        "estimated": bool(item.get("estimated", False)),
                        "elapsed_ms": self._int(item.get("elapsed_ms")),
                        "prompt_chars": self._int(item.get("prompt_chars")),
                        "completion_chars": self._int(item.get("completion_chars")),
                        "error": self._single_line(item.get("error"), 160),
                        "budget_exempt": bool(item.get("budget_exempt", False)),
                    }
                )
        return {
            "updated_at": self._single_line(usage.get("updated_at"), 24),
            "totals": totals,
            "by_provider": by_provider,
            "by_task": by_task,
            "by_day": by_day,
            "by_day_detail": by_day_detail,
            "by_hour": by_hour,
            "budget": budget,
            "balance": self._balance_status_payload(balance_state),
            "recent": recent,
            "external": self._token_external_payload(external_usage),
            "memory_plugin": self._token_memory_plugin_payload(memory_plugin_usage),
        }

    def _token_external_payload(self, usage: Any) -> dict[str, Any]:
        if not isinstance(usage, dict):
            usage = {}
        by_day = self._token_series_map(usage.get("by_day"), limit=30)
        by_day_provider_raw = usage.get("by_day_provider") if isinstance(usage.get("by_day_provider"), dict) else {}
        by_day_task_raw = usage.get("by_day_task") if isinstance(usage.get("by_day_task"), dict) else {}
        by_day_session_raw = usage.get("by_day_session") if isinstance(usage.get("by_day_session"), dict) else {}
        by_day_detail = []
        for item in by_day:
            day_key = item.get("key", "")
            by_day_detail.append(
                {
                    **item,
                    "providers": self._token_ranked_map(by_day_provider_raw.get(day_key))[:5],
                    "tasks": self._token_ranked_map(by_day_task_raw.get(day_key))[:6],
                    "sessions": self._token_ranked_map(by_day_session_raw.get(day_key))[:8],
                }
            )
        recent = []
        recent_raw = usage.get("recent")
        if isinstance(recent_raw, list):
            for item in recent_raw[-80:][::-1]:
                if not isinstance(item, dict):
                    continue
                recent.append(
                    {
                        "time": self._single_line(item.get("time"), 24),
                        "ts": self._float(item.get("ts")),
                        "provider": self._single_line(item.get("provider"), 80),
                        "task": self._single_line(item.get("task"), 40),
                        "session": self._single_line(item.get("session"), 160),
                        "sender": self._single_line(item.get("sender"), 80),
                        "message_type": self._single_line(item.get("message_type"), 20),
                        "success": bool(item.get("success", True)),
                        "prompt_tokens": self._int(item.get("prompt_tokens")),
                        "completion_tokens": self._int(item.get("completion_tokens")),
                        "total_tokens": self._int(item.get("total_tokens")),
                        "cached_tokens": self._int(item.get("cached_tokens")),
                        "cache_read_tokens": self._int(item.get("cache_read_tokens")),
                        "cache_write_tokens": self._int(item.get("cache_write_tokens")),
                        "estimated": bool(item.get("estimated", False)),
                        "elapsed_ms": self._int(item.get("elapsed_ms")),
                        "prompt_chars": self._int(item.get("prompt_chars")),
                        "completion_chars": self._int(item.get("completion_chars")),
                        "error": self._single_line(item.get("error"), 160),
                        "external": True,
                    }
                )
        return {
            "updated_at": self._single_line(usage.get("updated_at"), 24),
            "totals": self._token_bucket(usage.get("totals")),
            "by_provider": self._token_ranked_map(usage.get("by_provider")),
            "by_task": self._token_ranked_map(usage.get("by_task")),
            "by_session": self._token_ranked_map(usage.get("by_session")),
            "by_day": by_day,
            "by_day_detail": by_day_detail,
            "by_hour": self._token_series_map(usage.get("by_hour"), limit=48),
            "recent": recent,
        }

    def _token_memory_plugin_payload(self, usage: Any) -> dict[str, Any]:
        if not isinstance(usage, dict):
            usage = {"available": False}
        available = bool(usage.get("available", True))
        by_day = self._token_series_map(usage.get("by_day"), limit=30)
        by_day_provider_raw = usage.get("by_day_provider") if isinstance(usage.get("by_day_provider"), dict) else {}
        by_day_task_raw = usage.get("by_day_task") if isinstance(usage.get("by_day_task"), dict) else {}
        by_day_detail = []
        for item in by_day:
            day_key = item.get("key", "")
            by_day_detail.append(
                {
                    **item,
                    "providers": self._token_ranked_map(by_day_provider_raw.get(day_key))[:5],
                    "tasks": self._token_ranked_map(by_day_task_raw.get(day_key))[:8],
                }
            )
        recent = []
        recent_raw = usage.get("recent")
        if isinstance(recent_raw, list):
            for item in recent_raw[-80:][::-1]:
                if not isinstance(item, dict):
                    continue
                recent.append(
                    {
                        "time": self._single_line(item.get("time"), 24),
                        "ts": self._float(item.get("ts")),
                        "provider": self._single_line(item.get("provider"), 80),
                        "task": self._single_line(item.get("task"), 60),
                        "success": bool(item.get("success", True)),
                        "prompt_tokens": self._int(item.get("prompt_tokens")),
                        "completion_tokens": self._int(item.get("completion_tokens")),
                        "total_tokens": self._int(item.get("total_tokens")),
                        "cached_tokens": self._int(item.get("cached_tokens")),
                        "cache_read_tokens": self._int(item.get("cache_read_tokens")),
                        "cache_write_tokens": self._int(item.get("cache_write_tokens")),
                        "estimated": bool(item.get("estimated", False)),
                        "elapsed_ms": self._int(item.get("elapsed_ms")),
                        "prompt_chars": self._int(item.get("prompt_chars")),
                        "completion_chars": self._int(item.get("completion_chars")),
                        "error": self._single_line(item.get("error"), 160),
                    }
                )
        return {
            "available": available,
            "display_name": self._single_line(usage.get("display_name") or "我会牢牢记住你", 80),
            "plugin_name": self._single_line(usage.get("plugin_name") or "astrbot_plugin_memory_companion", 80),
            "reason": self._single_line(usage.get("reason"), 160),
            "note": self._single_line(
                usage.get("note") or "仅展示记忆插件自身模型消耗，不计入陪伴插件每日 Token 限额。",
                220,
            ),
            "counted_in_private_companion_budget": bool(usage.get("counted_in_private_companion_budget", False)),
            "updated_at": self._single_line(usage.get("updated_at"), 24),
            "totals": self._token_bucket(usage.get("totals")),
            "by_provider": self._token_ranked_map(usage.get("by_provider")),
            "by_task": self._token_ranked_map(usage.get("by_task")),
            "by_day": by_day,
            "by_day_detail": by_day_detail,
            "by_hour": self._token_series_map(usage.get("by_hour"), limit=48),
            "recent": recent,
        }

    @classmethod
    def _token_bucket(cls, value: Any) -> dict[str, Any]:
        bucket = value if isinstance(value, dict) else {}
        calls = cls._int(bucket.get("calls"))
        elapsed = cls._int(bucket.get("elapsed_ms"))
        total_tokens = cls._int(bucket.get("total_tokens"))
        estimated_tokens = cls._int(bucket.get("estimated_tokens"))
        cached_tokens = cls._int(bucket.get("cached_tokens"))
        cache_read_tokens = cls._int(bucket.get("cache_read_tokens"))
        cache_write_tokens = cls._int(bucket.get("cache_write_tokens"))
        return {
            "calls": calls,
            "success": cls._int(bucket.get("success")),
            "errors": cls._int(bucket.get("errors")),
            "prompt_tokens": cls._int(bucket.get("prompt_tokens")),
            "completion_tokens": cls._int(bucket.get("completion_tokens")),
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cached_ratio": round(cached_tokens / total_tokens, 4) if total_tokens > 0 else 0,
            "estimated_tokens": estimated_tokens,
            "estimated_ratio": round(estimated_tokens / total_tokens, 4) if total_tokens > 0 else 0,
            "avg_tokens": round(total_tokens / calls, 1) if calls > 0 else 0,
            "avg_latency_ms": round(elapsed / calls, 1) if calls > 0 else 0,
            "last_ts": cls._float(bucket.get("last_ts")),
        }

    @classmethod
    def _token_ranked_map(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, dict):
            return []
        rows = []
        for key, bucket in value.items():
            item = cls._token_bucket(bucket)
            item["key"] = cls._single_line(key, 120)
            rows.append(item)
        rows.sort(key=lambda item: item.get("total_tokens", 0), reverse=True)
        return rows

    @classmethod
    def _token_series_map(cls, value: Any, *, limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, dict):
            return []
        rows = []
        for key, bucket in value.items():
            item = cls._token_bucket(bucket)
            item["key"] = cls._single_line(key, 32)
            rows.append(item)
        rows.sort(key=lambda item: item.get("key", ""))
        return rows[-limit:]

    @staticmethod
    def _int(value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    @staticmethod
    def _float(value: Any, default: float = 0.0, minimum: float | None = None, maximum: float | None = None) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def _segment_from_story_windows(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        minutes: list[int] = []
        for key in ("today_events", "proactive_events"):
            items = snapshot.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                start, end = self.plugin._parse_window_minutes(str(item.get("window") or ""))
                if start is not None:
                    minutes.append(start)
                if end is not None:
                    minutes.append(end)
        if not minutes:
            return None
        start = min(minutes)
        end = max(minutes)
        return {"window": f"{self.plugin._minutes_to_hhmm(start)}-{self.plugin._minutes_to_hhmm(end)}", "start": start}

    @staticmethod
    def _limited_state_variables(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        for item in value[:8]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": PrivateCompanionPageApi._single_line(item.get("name") or item.get("key"), 40),
                    "value": PrivateCompanionPageApi._single_line(item.get("value"), 80),
                    "note": PrivateCompanionPageApi._single_line(item.get("note"), 100),
                }
            )
        return items

    @staticmethod
    def _limited_interaction_updates(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value[-8:]:
            if not isinstance(item, dict):
                continue
            updates = item.get("state_updates")
            items.append(
                {
                    "at": PrivateCompanionPageApi._single_line(item.get("at"), 12),
                    "source": PrivateCompanionPageApi._single_line(item.get("source"), 24),
                    "reaction": PrivateCompanionPageApi._single_line(item.get("reaction"), 140),
                    "state_updates": [
                        PrivateCompanionPageApi._single_line(update, 80)
                        for update in updates[:6]
                        if PrivateCompanionPageApi._single_line(update, 80)
                    ]
                    if isinstance(updates, list)
                    else [],
                }
            )
        return items

    def _timeline_story_items(self, value: Any, limit: int, plan_date: str) -> list[dict[str, Any]]:
        items = self._limited_story_items(value, limit)
        for item in items:
            start, end = self.plugin._parse_window_minutes(str(item.get("window") or ""))
            if start is None or end is None:
                item["lifecycle"] = "planned"
                continue
            item["lifecycle"] = self.plugin._schedule_window_runtime_status(
                start,
                end,
                plan_date=plan_date,
                explicit_status=item.get("lifecycle_status"),
            )
        return items

    @staticmethod
    def _limited_story_items(value: Any, limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, str]] = []
        indexed_items = [
            (PrivateCompanionPageApi._story_item_start_minutes(item), index, item)
            for index, item in enumerate(value)
            if isinstance(item, dict)
        ]
        indexed_items.sort(key=lambda row: (row[0], row[1]))
        for _, _, item in indexed_items[:limit]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "window": PrivateCompanionPageApi._single_line(item.get("window") or item.get("time"), 24),
                    "text": PrivateCompanionPageApi._single_line(
                        item.get("event")
                        or item.get("topic")
                        or item.get("summary")
                        or item.get("text")
                        or item.get("content"),
                        160,
                    ),
                    "mood": PrivateCompanionPageApi._single_line(item.get("mood"), 24),
                    "action": PrivateCompanionPageApi._single_line(item.get("action"), 24),
                    "reason": PrivateCompanionPageApi._single_line(item.get("reason"), 32),
                    "lifecycle_status": PrivateCompanionPageApi._single_line(item.get("lifecycle_status"), 20),
                    "basis": [
                        PrivateCompanionPageApi._single_line(value, 24)
                        for value in (item.get("basis") or [])[:3]
                        if PrivateCompanionPageApi._single_line(value, 24)
                    ] if isinstance(item.get("basis"), list) else [],
                    "confidence": min(1.0, PrivateCompanionPageApi._float(item.get("confidence"), 0.72)),
                }
            )
        return items

    @staticmethod
    def _story_item_start_minutes(item: Any) -> int:
        if not isinstance(item, dict):
            return 99999
        text = PrivateCompanionPageApi._single_line(item.get("window") or item.get("time"), 32)
        match = re.search(r"(\d{1,2}):(\d{2})", text)
        if not match:
            return 99999
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return 99999
        return hour * 60 + minute

    @staticmethod
    def _limited_adjustments(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value[-10:]:
            if not isinstance(item, dict):
                continue
            updates = item.get("state_updates")
            items.append(
                {
                    "date": PrivateCompanionPageApi._single_line(item.get("date"), 12),
                    "source": PrivateCompanionPageApi._single_line(item.get("source"), 24),
                    "scope": PrivateCompanionPageApi._single_line(item.get("scope"), 40),
                    "scope_key": PrivateCompanionPageApi._single_line(item.get("scope_key"), 24),
                    "note": PrivateCompanionPageApi._single_line(item.get("note"), 140),
                    "reaction": PrivateCompanionPageApi._single_line(item.get("immediate_reaction"), 140),
                    "state_updates": [
                        PrivateCompanionPageApi._single_line(update, 80)
                        for update in updates[:6]
                        if PrivateCompanionPageApi._single_line(update, 80)
                    ]
                    if isinstance(updates, list)
                    else [],
                }
            )
        return items

    @staticmethod
    def _limited_dream_fragments(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for raw in value[-18:]:
            if isinstance(raw, dict):
                text = PrivateCompanionPageApi._single_line(
                    raw.get("text") or raw.get("keyword") or raw.get("label"),
                    42,
                )
                if not text:
                    continue
                items.append(
                    {
                        "text": text,
                        "weight": PrivateCompanionPageApi._float(raw.get("effective_weight") or raw.get("weight")),
                        "source": PrivateCompanionPageApi._single_line(raw.get("source"), 24),
                        "created_at": PrivateCompanionPageApi._single_line(raw.get("created_at") or raw.get("created_ts"), 24),
                    }
                )
            else:
                text = PrivateCompanionPageApi._single_line(raw, 42)
                if text:
                    items.append({"text": text, "weight": 1.0, "source": "", "created_at": ""})
        items.sort(key=lambda item: float(item.get("weight") or 0), reverse=True)
        return items[:14]

    @staticmethod
    def _limited_list(value: Any, limit: int) -> list[Any]:
        return list(value[:limit]) if isinstance(value, list) else []

    @staticmethod
    def _memory_item_count(memory: Any) -> int:
        if not isinstance(memory, dict):
            return 0
        count = 0
        for value in memory.values():
            if isinstance(value, list):
                count += len(value)
            elif value:
                count += 1
        return count

    def _livingmemory_db_path(self) -> Path | None:
        candidates: list[Path] = []
        data_dir = Path(str(getattr(self.plugin, "data_dir", "") or "")).resolve()
        if data_dir:
            candidates.append(data_dir.parent / "astrbot_plugin_livingmemory" / "livingmemory.db")
            candidates.append(data_dir.parent / "astrbot_plugin_livingmemory" / "livingmemory_graph_documents.db")
        candidates.append(Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_livingmemory" / "livingmemory.db")
        for path in candidates:
            try:
                if path.exists() and path.is_file():
                    return path
            except OSError:
                continue
        return None

    def _worldbook_member_livingmemory_tokens(self, user_id: str, profile: dict[str, Any]) -> dict[str, list[str]]:
        primary_raw: list[Any] = [
            user_id,
            profile.get("linked_qq_user_id"),
            profile.get("merged_into_user_id"),
            profile.get("linked_bili_profile_id"),
        ]
        external_ids = profile.get("external_ids")
        if isinstance(external_ids, list):
            primary_raw.extend(external_ids)
        support_raw: list[Any] = []
        for key in ("name", "aliases", "observed_names"):
            value = profile.get(key)
            if isinstance(value, list):
                support_raw.extend(value)

        def normalize(raw_items: list[Any], seen: set[str]) -> list[str]:
            tokens: list[str] = []
            for raw in raw_items:
                text = self._single_line(raw, 80)
                if not text or text in seen:
                    continue
                if text.isdigit():
                    if len(text) < 5:
                        continue
                elif len(text) < 2:
                    continue
                seen.add(text)
                tokens.append(text)
            return tokens

        def stable_support(raw_items: list[Any]) -> list[Any]:
            stable: list[Any] = []
            for raw in raw_items:
                text = self._single_line(raw, 40)
                if not text or len(text) > 16:
                    continue
                if any(mark in text for mark in ("，", ",", "。", "！", "？", " ", "：", ":", "|", "\n")):
                    continue
                stable.append(text)
            return stable

        seen_tokens: set[str] = set()
        primary_tokens = normalize(primary_raw, seen_tokens)
        support_tokens = normalize(stable_support(support_raw), seen_tokens)
        tokens = [*primary_tokens, *support_tokens]
        return {
            "tokens": tokens[:18],
            "primary_tokens": primary_tokens[:8],
            "support_tokens": support_tokens[:12],
        }

    @staticmethod
    def _sqlite_like_pattern(token: str) -> str:
        escaped = str(token).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    @staticmethod
    def _json_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if not isinstance(value, str) or not value.strip():
            return []
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _livingmemory_match_info(self, content: str, metadata_text: str, token_bundle: dict[str, list[str]]) -> dict[str, Any]:
        haystack = f"{content}\n{metadata_text}".lower()
        score = 0.0
        primary_tokens = token_bundle.get("primary_tokens", [])
        support_tokens = token_bundle.get("support_tokens", [])
        matched_primary: list[str] = []
        matched_support: list[str] = []
        for token in primary_tokens:
            text = token.lower()
            if not text or text not in haystack:
                continue
            count = max(1, haystack.count(text))
            if token.isdigit():
                score += 9.0 + min(count, 4)
            else:
                score += min(8.0, 3.5 + len(token) * 0.65) + min(count - 1, 3) * 0.7
            matched_primary.append(token)
        for token in support_tokens:
            text = token.lower()
            if not text or text not in haystack:
                continue
            count = max(1, haystack.count(text))
            score += min(3.0, 0.8 + len(token) * 0.25) + min(count - 1, 2) * 0.25
            matched_support.append(token)
        accepted = bool(matched_primary) or (not primary_tokens and len(matched_support) >= 2)
        return {
            "accepted": accepted,
            "score": round(score, 3),
            "matched_tokens": [*matched_primary, *matched_support][:8],
            "primary_hits": len(matched_primary),
            "support_hits": len(matched_support),
        }

    def _livingmemory_item_from_document(self, row: sqlite3.Row, token_bundle: dict[str, list[str]]) -> dict[str, Any] | None:
        metadata = self._json_dict(row["metadata"])
        content = str(row["text"] or "").strip()
        match = self._livingmemory_match_info(content, str(row["metadata"] or ""), token_bundle)
        if not match.get("accepted"):
            return None
        create_time = self._coerce_float(metadata.get("create_time"))
        last_access = self._coerce_float(metadata.get("last_access_time"))
        topics = metadata.get("topics") if isinstance(metadata.get("topics"), list) else []
        key_facts = metadata.get("key_facts") if isinstance(metadata.get("key_facts"), list) else []
        return {
            "source": "documents",
            "source_label": "长期记忆文档",
            "id": row["doc_id"] or row["id"],
            "score": match.get("score"),
            "matched_tokens": match.get("matched_tokens", []),
            "primary_hits": match.get("primary_hits", 0),
            "support_hits": match.get("support_hits", 0),
            "session_id": self._single_line(metadata.get("session_id"), 80),
            "persona_id": self._single_line(metadata.get("persona_id"), 80),
            "importance": metadata.get("importance"),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "create_time": create_time,
            "last_access_time": last_access,
            "topics": [self._single_line(item, 40) for item in topics[:8] if self._single_line(item, 40)],
            "key_facts": [self._single_line(item, 120) for item in key_facts[:8] if self._single_line(item, 120)],
            "preview": self._single_line(metadata.get("canonical_summary") or content, 260),
            "content": content[:1800],
        }

    def _livingmemory_item_from_atom(self, row: sqlite3.Row, token_bundle: dict[str, list[str]]) -> dict[str, Any] | None:
        content = str(row["content"] or "").strip()
        entities = self._json_list(row["entities"])
        metadata = self._json_dict(row["metadata"])
        metadata_text = " ".join([str(row["entities"] or ""), str(row["metadata"] or "")])
        match = self._livingmemory_match_info(content, metadata_text, token_bundle)
        if not match.get("accepted"):
            return None
        return {
            "source": "atoms",
            "source_label": "原子记忆",
            "id": row["id"],
            "parent_memory_id": row["parent_memory_id"],
            "score": match.get("score"),
            "matched_tokens": match.get("matched_tokens", []),
            "primary_hits": match.get("primary_hits", 0),
            "support_hits": match.get("support_hits", 0),
            "session_id": self._single_line(row["session_id"], 80),
            "persona_id": self._single_line(row["persona_id"], 80),
            "importance": row["importance"],
            "confidence": row["confidence"],
            "created_at": str(row["created_at"] or ""),
            "create_time": self._coerce_float(row["created_at"]),
            "last_access_time": self._coerce_float(row["last_accessed_at"]),
            "topics": [self._single_line(item, 40) for item in entities[:8] if self._single_line(item, 40)],
            "key_facts": [self._single_line(item, 120) for item in metadata.get("key_facts", [])[:6]] if isinstance(metadata.get("key_facts"), list) else [],
            "preview": self._single_line(content, 260),
            "content": content[:1200],
        }

    def _livingmemory_item_from_graph_entry(self, row: sqlite3.Row, token_bundle: dict[str, list[str]]) -> dict[str, Any] | None:
        metadata = self._json_dict(row["metadata"])
        content = str(row["content"] or "").strip()
        match = self._livingmemory_match_info(content, str(row["metadata"] or ""), token_bundle)
        if not match.get("accepted"):
            return None
        return {
            "source": "graph",
            "source_label": "关系图谱",
            "id": row["entry_key"] or row["id"],
            "parent_memory_id": row["source_memory_id"],
            "score": match.get("score"),
            "matched_tokens": match.get("matched_tokens", []),
            "primary_hits": match.get("primary_hits", 0),
            "support_hits": match.get("support_hits", 0),
            "session_id": self._single_line(row["session_id"] or metadata.get("session_id"), 80),
            "persona_id": self._single_line(row["persona_id"] or metadata.get("persona_id"), 80),
            "importance": metadata.get("importance"),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "create_time": self._coerce_float(metadata.get("create_time")),
            "last_access_time": self._coerce_float(metadata.get("last_access_time")),
            "topics": [],
            "key_facts": [],
            "preview": self._single_line(content, 260),
            "content": content[:1600],
        }

    def _query_livingmemory_for_tokens(self, db_path: Path, token_bundle: dict[str, list[str]], limit: int) -> list[dict[str, Any]]:
        tokens = token_bundle.get("primary_tokens") or token_bundle.get("tokens", [])
        if not tokens:
            return []
        db_uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=1500")
            like_tokens = [self._sqlite_like_pattern(token) for token in tokens]
            table_limit = max(80, limit * 8)
            items: list[dict[str, Any]] = []

            def where_for(columns: list[str]) -> tuple[str, list[str]]:
                parts: list[str] = []
                params: list[str] = []
                for pattern in like_tokens:
                    sub = []
                    for column in columns:
                        sub.append(f"{column} LIKE ? ESCAPE '\\'")
                        params.append(pattern)
                    parts.append("(" + " OR ".join(sub) + ")")
                return " OR ".join(parts), params

            if self._sqlite_table_exists(conn, "documents"):
                where, params = where_for(["text", "metadata"])
                for row in conn.execute(
                    f"SELECT id, doc_id, text, metadata, created_at, updated_at FROM documents WHERE {where} ORDER BY id DESC LIMIT ?",
                    [*params, table_limit],
                ).fetchall():
                    item = self._livingmemory_item_from_document(row, token_bundle)
                    if item:
                        items.append(item)

            if self._sqlite_table_exists(conn, "memory_atoms"):
                where, params = where_for(["content", "entities", "metadata"])
                for row in conn.execute(
                    f"""SELECT id, parent_memory_id, atom_type, content, entities, importance, confidence,
                              created_at, last_accessed_at, session_id, persona_id, metadata
                         FROM memory_atoms
                        WHERE (status IS NULL OR status != 'expired') AND ({where})
                        ORDER BY id DESC LIMIT ?""",
                    [*params, table_limit],
                ).fetchall():
                    item = self._livingmemory_item_from_atom(row, token_bundle)
                    if item:
                        items.append(item)

            if self._sqlite_table_exists(conn, "graph_entries"):
                where, params = where_for(["content", "metadata", "session_id"])
                for row in conn.execute(
                    f"""SELECT id, entry_key, source_memory_id, session_id, persona_id, entry_type,
                              relation_type, content, metadata, created_at, updated_at
                         FROM graph_entries
                        WHERE {where}
                        ORDER BY id DESC LIMIT ?""",
                    [*params, table_limit],
                ).fetchall():
                    item = self._livingmemory_item_from_graph_entry(row, token_bundle)
                    if item:
                        items.append(item)

            seen: set[tuple[str, str]] = set()
            unique: list[dict[str, Any]] = []
            for item in sorted(items, key=lambda entry: (entry.get("score") or 0, entry.get("last_access_time") or entry.get("create_time") or 0), reverse=True):
                key = (str(item.get("source") or ""), str(item.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                unique.append(item)
                if len(unique) >= limit:
                    break
            return unique
        finally:
            conn.close()

    @staticmethod
    def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)).fetchone()
        return row is not None

    @staticmethod
    def _query_int(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = request.args.get(name, default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _clamp_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _normalize_id_list(value: Any) -> list[str]:
        if isinstance(value, str):
            raw_items = value.replace("，", ",").replace("\n", ",").split(",")
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = PrivateCompanionPageApi._single_line(item, 128)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @classmethod
    def _dedupe_text_list(cls, value: Any, limit: int = 12) -> list[str]:
        items = value if isinstance(value, list) else []
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = cls._single_line(item, 180)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= limit:
                break
        return result

    def _normalize_private_target_id_list(self, value: Any) -> list[str]:
        normalizer = getattr(self.plugin, "_normalize_private_identity_id", None)
        result: list[str] = []
        seen: set[str] = set()
        for item in self._normalize_id_list(value):
            text = normalizer(item) if callable(normalizer) else self._single_line(item, 128)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _single_line(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").strip().split())
        return text[:limit]

    @classmethod
    def _sanitize_news_text(cls, value: Any, limit: int, *, fallback: str = "") -> str:
        text = cls._single_line(value, limit)
        if text and _text_looks_garbled(text):
            return fallback
        return text

    @staticmethod
    def _multi_line(value: Any, limit: int) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:limit].strip()

    @staticmethod
    def _multi_line_head_tail(value: Any, limit: int) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text) <= limit:
            return text.strip()
        marker = "\n\n（中间内容过长，已保留开头和结尾；请优先依据稳定重复信息归纳。）\n\n"
        if limit <= len(marker) + 200:
            return text[:limit].strip()
        head_len = max(200, int((limit - len(marker)) * 0.65))
        tail_len = max(200, limit - len(marker) - head_len)
        return (text[:head_len].strip() + marker + text[-tail_len:].strip())[:limit].strip()
