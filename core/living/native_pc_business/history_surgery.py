# -*- coding: utf-8 -*-
"""
HistorySurgeryMixin — 历史外科手术系统

三层防御：
1. save-time think拦截（预防）
2. 定期健康检查（检测，挂_tick）
3. 选择性重写违规轮（手术，不清全史）
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from astrbot.api import logger

from .helpers import _now_ts, _safe_int, _single_line

DB_PATH = "/AstrBot/data/data_v4.db"

# ---------- 违规模式库（可扩展） ----------
VIOLATION_PATTERNS = {
    "novel_frame": {
        "regex": r"手机震|他醒了|屏幕亮了|消息弹出|终端响了",
        "desc": "小说叙事框架（描写收到消息而非回应）",
    },
    "voice_tag": {
        "regex": r"声低|鼻音很重|声哑|声含混|声低软",
        "desc": "声音标签注释",
    },
    "camera_pure": {
        "check": "zero_dialogue_long",
        "desc": "纯旁白零话语（他发了文字，你只回动作不回话）",
    },
    "echo_open": {
        "check": "echo_previous",
        "desc": "开场复读他刚说的话",
    },
    "third_person_self": {
        "regex": r"^她没|她不躲|她笑了|她起身|她低头|她没躲",
        "desc": "第三人称自述（用'她'描述自己而不是第一人称）",
    },
    "re_narrate": {
        "check": "repeats_user_action",
        "desc": "重述他的动作（他消息里已写的括号动作被她重新描写）",
    },
}


def _turn_text(t: dict) -> str:
    """提取一轮的文本（兼容str和分片list两种content格式）。"""
    cc = t.get("content")
    if isinstance(cc, str):
        return cc
    if isinstance(cc, list):
        return " ".join(p.get("text", "") for p in cc if isinstance(p, dict) and p.get("type") == "text")
    return ""


class HistorySurgeryMixin:
    """历史外科手术：检测+选择性重写。"""

    def _surgery_scan_turns(self, turns: list[dict]) -> dict[int, list[str]]:
        """扫描违规轮，返回 {turn_index: [violation_keys]}。"""
        violations: dict[int, list[str]] = {}
        prev_user_text = ""
        for i, t in enumerate(turns):
            if not isinstance(t, dict):
                continue
            cc = t.get("content")
            text = ""
            if isinstance(cc, str):
                text = cc
            elif isinstance(cc, list):
                for p in cc:
                    if isinstance(p, dict) and p.get("type") == "text":
                        text += p.get("text", "")

            if t.get("role") == "assistant":
                found = []
                for key, pat in VIOLATION_PATTERNS.items():
                    if "regex" in pat:
                        if re.search(pat["regex"], text):
                            found.append(key)
                    elif pat.get("check") == "zero_dialogue_long":
                        if "「" not in text and len(text.strip()) > 25 and prev_user_text:
                            found.append(key)
                    elif pat.get("check") == "echo_previous":
                        if prev_user_text and len(prev_user_text) > 5:
                            compact_prev = re.sub(r"\s+", "", prev_user_text[:20])
                            compact_reply = re.sub(r"\s+", "", text[:40])
                            if compact_prev[:10] and compact_prev[:10] in compact_reply:
                                found.append(key)
                    elif pat.get("check") == "repeats_user_action":
                        # 检测她是否重述了他消息里已写的动作
                        if prev_user_text and re.search(r"（.+?）", prev_user_text):
                            user_actions = re.findall(r"（(.+?)）", prev_user_text)
                            reply_start = text.strip()[:60]
                            for action in user_actions:
                                action_words = [w for w in re.split(r"[，。,。]", action) if len(w) >= 2]
                                if any(w in reply_start for w in action_words if len(w) >= 2):
                                    found.append(key)
                                    break
                if found:
                    violations[i] = list(dict.fromkeys(found))  # deduplicate
            elif t.get("role") == "user":
                prev_user_text = text
        return violations

    def _surgery_strip_think(self, turns: list[dict]) -> int:
        """剥离所有轮的think部分，返回剥离数。"""
        stripped = 0
        for t in turns:
            if not isinstance(t, dict):
                continue
            cc = t.get("content")
            if isinstance(cc, list):
                keep = [p for p in cc if not (isinstance(p, dict) and p.get("type") == "think")]
                if len(keep) != len(cc):
                    t["content"] = keep
                    stripped += 1
        return stripped

    async def _surgery_rewrite_violations(
        self,
        turns: list[dict],
        violations: dict[int, list[str]],
    ) -> tuple[dict[int, str], dict[int, str]]:
        """用LLM重写违规的assistant轮，保留内容含义修正表达。

        返回 (rewrites, originals)：
        - rewrites: {快照索引: 新文本}
        - originals: {快照索引: 完整原文}（写回时按原文匹配最新快照，索引可能已失效）
        """
        if not violations:
            return {}, {}
        # 构建重写请求
        items = []
        originals: dict[int, str] = {}
        for idx, keys in sorted(violations.items()):
            t = turns[idx]
            text = _turn_text(t)
            originals[idx] = text
            issues = "、".join(VIOLATION_PATTERNS.get(k, {}).get("desc", k) for k in keys)
            items.append({"index": idx, "issues": issues, "original": _single_line(text, 500)})

        prompt = f"""修正以下{len(items)}条历史回复的风格问题。保持内容含义不变，只修正表达方式。

修正规则：
- 你在和他对话，不是在写小说——直接回应，不描写"收到消息"
- 给他话语回应，纯旁白（只有动作没有话）是错误的
- 不用声音标签（声低/鼻音等）
- 开场不复述他刚说的话

{json.dumps(items, ensure_ascii=False, indent=1)}

只输出JSON：{{"rewrites": [{{"index": 0, "new_text": "修正后的完整回复"}}]}}
"""
        try:
            payload = await self._llm_call_json_with_retry(
                prompt,
                max_tokens=2000,
                provider_id=self._task_provider(getattr(self, "narration_provider_id", ""), getattr(self, "llm_provider_id", "")),
                task="history_surgery",
            )
        except Exception as e:
            logger.warning("[PrivateCompanion][surgery] 重写调用失败: %s", e)
            return {}, {}
        if not isinstance(payload, dict):
            return {}, {}

        rewrites: dict[int, str] = {}
        valid_indices = set(violations.keys())
        for r in payload.get("rewrites", []):
            if not isinstance(r, dict):
                continue
            # 严格校验：只接受扫描时确认违规的索引，LLM自报的越界/干净索引一律丢弃
            # （旧版把越界索引钳制到合法范围，可能改写无辜的轮）
            try:
                idx = int(r.get("index"))
            except (TypeError, ValueError):
                continue
            new_text = _single_line(r.get("new_text"), 800)
            if idx not in valid_indices or not new_text:
                continue
            rewrites[idx] = new_text
        return rewrites, originals

    async def _run_history_surgery(self, session_umo: str = "default:FriendMessage:2117919529") -> dict:
        """执行一次完整的历史外科手术。

        竞态防护：LLM重写耗时数秒，期间会话可能新增轮次。旧版直接把陈旧快照
        整体写回会吞掉新对话。现在：规划在快照上完成；写回前重读最新内容，
        think剥离幂等重放、重写按原文匹配应用，最后用条件UPDATE（内容未变才写）
        兜底。竞态发生时放弃本次手术，下个检查窗口重试。
        """
        try:
            conn = sqlite3.connect(DB_PATH, timeout=15)
            conn.execute("PRAGMA busy_timeout=10000")
            c = conn.cursor()
            row = c.execute(
                "SELECT conversation_id, content FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
                (session_umo,),
            ).fetchone()
            conn.close()
            if not row:
                return {"status": "no_conversation"}
            cid, content = row
            try:
                turns = json.loads(content)
            except Exception:
                return {"status": "parse_error"}
            if not isinstance(turns, list) or not turns:
                return {"status": "empty"}

            # Step 1: 扫描违规（在快照上规划，不写库）
            violations = self._surgery_scan_turns(turns)
            rewrites: dict[int, str] = {}
            originals: dict[int, str] = {}

            # Step 2: LLM重写（竞态窗口从这里开始，耗时数秒）
            if violations:
                rewrites, originals = await self._surgery_rewrite_violations(turns, violations)
                if not rewrites and not self._surgery_has_think(turns):
                    return {"status": "ok", "total_turns": len(turns), "think_stripped": 0,
                            "violations_found": len(violations), "rewritten": 0}

            # Step 3: 重读最新内容，把修改应用到新快照
            conn = sqlite3.connect(DB_PATH, timeout=15)
            conn.execute("PRAGMA busy_timeout=10000")
            c = conn.cursor()
            fresh_row = c.execute(
                "SELECT content FROM conversations WHERE conversation_id=?",
                (cid,),
            ).fetchone()
            if not fresh_row or not fresh_row[0]:
                conn.close()
                return {"status": "changed_skipped"}
            fresh_raw = fresh_row[0]
            try:
                fresh_turns = json.loads(fresh_raw)
            except Exception:
                conn.close()
                return {"status": "parse_error"}
            if not isinstance(fresh_turns, list) or not fresh_turns:
                conn.close()
                return {"status": "empty"}

            think_stripped = self._surgery_strip_think(fresh_turns)

            rewritten = 0
            used_positions: set[int] = set()
            for snap_idx, new_text in rewrites.items():
                original = originals.get(snap_idx, "")
                if not original:
                    continue
                for fi, ft in enumerate(fresh_turns):
                    if fi in used_positions or not isinstance(ft, dict) or ft.get("role") != "assistant":
                        continue
                    if _turn_text(ft) == original:
                        ft["content"] = new_text
                        used_positions.add(fi)
                        rewritten += 1
                        break

            # Step 4: 条件写回——内容在重读后没再变才落库
            if think_stripped or rewritten:
                c.execute(
                    "UPDATE conversations SET content=? WHERE conversation_id=? AND content=?",
                    (json.dumps(fresh_turns, ensure_ascii=False), cid, fresh_raw),
                )
                committed = c.rowcount > 0
                conn.commit()
                conn.close()
                if not committed:
                    return {"status": "racing_skipped", "violations_found": len(violations)}
            else:
                conn.close()

            result = {
                "status": "ok",
                "total_turns": len(fresh_turns),
                "think_stripped": think_stripped,
                "violations_found": len(violations),
                "rewritten": rewritten,
            }
            logger.info("[PrivateCompanion][surgery] %s", result)
            return result
        except Exception as e:
            logger.warning("[PrivateCompanion][surgery] 手术异常: %s", e)
            return {"status": "error", "message": str(e)[:120]}

    def _surgery_has_think(self, turns: list[dict]) -> bool:
        """快速判断是否存在待剥离的think部分。"""
        for t in turns:
            if not isinstance(t, dict):
                continue
            cc = t.get("content")
            if isinstance(cc, list) and any(isinstance(p, dict) and p.get("type") == "think" for p in cc):
                return True
        return False

    def _history_health_score(self, turns: list[dict]) -> float:
        """健康分：0=完全干净，1=全部污染。"""
        if not turns:
            return 0.0
        violations = self._surgery_scan_turns(turns)
        return len(violations) / len(turns)

    async def _maybe_run_history_hygiene(self, user: dict[str, Any]) -> None:
        """每6小时健康检查，污染>15%自动手术。"""
        state = user.get("history_hygiene")
        if not isinstance(state, dict):
            state = {}
            user["history_hygiene"] = state
        # 6小时窗口而非每天
        check_window = time.strftime("%Y-%m-%d_%H")
        last_check = _safe_int(state.get("last_check_window_num"), 0)
        try:
            current_num = int(time.time()) // (6 * 3600)  # 6小时一个窗口
        except Exception:
            current_num = 0
        if last_check == current_num:
            return
        state["last_check_window_num"] = current_num
        state["last_check_day"] = time.strftime("%Y-%m-%d")  # 兼容旧字段
        self._life_hooks_dirty = True  # 窗口标记需落盘，否则重启后重复检查甚至重复手术
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA busy_timeout=5000")
            c = conn.cursor()
            row = c.execute(
                "SELECT content FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
                (_single_line(user.get("umo"), 80) or "default:FriendMessage:2117919529",),
            ).fetchone()
            conn.close()
            if not row:
                return
            turns = json.loads(row[0]) if row[0] else []
            if not isinstance(turns, list) or len(turns) < 4:
                return
            score = self._history_health_score(turns)
            state["last_score"] = round(score, 2)
            state["last_check_ts"] = _now_ts()
            if score > 0.15:  # 从20%降到15%
                logger.info("[PrivateCompanion][surgery] 污染率%.0f%%超阈值，触发手术", score * 100)
                result = await self._run_history_surgery(
                    _single_line(user.get("umo"), 80) or "default:FriendMessage:2117919529"
                )
                state["last_surgery_result"] = result
        except Exception as e:
            logger.warning("[PrivateCompanion][surgery] 健康检查异常: %s", e)
