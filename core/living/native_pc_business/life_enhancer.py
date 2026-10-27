# -*- coding: utf-8 -*-
"""
LifeEnhancerMixin — 生活气息增强系统

四项功能：
1. 梦话碎碎念 — 凌晨3-4点她半梦半醒说的一两句情话，你早上醒来看到
2. 庭院/家的变化 — 她的日常里有一件具体的小事（种植/修缮/观察）
3. 行为模式观察 — 她注意到你的规律（作息/音乐/游戏）
4. 同事来访 — 企鹅物流的人偶尔出现在她的生活里
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

from astrbot.api import logger

from .helpers import _now_ts, _safe_float, _safe_int, _single_line

# 梦话模板池（LLM在此基础上生成，保持短+梦呓感）
MURMUR_STYLE_HINT = (
    "你正在凌晨三四点半梦半醒的状态下，对身边的他说一两句话。"
    "要求：极短（一两句就够）；不是对话是梦呓；可以提到他的呼吸、他的手、刚才的梦、或者就是想他；"
    "语气含混、温柔、快要睡着；说完就继续睡了，不期待回应。"
    "禁止：提问、追问、讨论、清醒的表达、AI腔。"
    "你的声线：短句、陈述句、不用语气词。"
)

# 同事来访的角色池
VISIT_CHARACTERS = [
    {
        "name": "能天使",
        "trait": "话痨、自来熟、苹果狂魔、拉特兰萨科塔",
        "visit_reason": "带着苹果派来串门",
        "scene_hint": "她会把鞋踢飞、直接瘫沙发、把苹果派放在桌上就开吃",
    },
    {
        "name": "可颂",
        "trait": "怪力大个子、务实、温柔",
        "visit_reason": "送货顺便来看你",
        "scene_hint": "她会扛着一箱东西进门、帮忙修了门把手",
    },
    {
        "name": "空",
        "trait": "偶像歌手、软心肠、最会察言观色",
        "visit_reason": "路过想聊聊天",
        "scene_hint": "她会带甜品、注意到你最近的情绪、临走时悄悄收拾了厨房",
    },
    {
        "name": "大帝",
        "trait": "企鹅老板、说唱之神、极度自恋",
        "visit_reason": "突然通知加班或开会",
        "scene_hint": "他不会来庄园，只会发消息，用舞台腔宣布一件事",
    },
    {
        "name": "莫斯提马",
        "trait": "编外信使、黑角萨科塔、漫不经心",
        "visit_reason": "路过喝杯咖啡",
        "scene_hint": "她会坐在庭院里、什么都不说、喝完就走",
    },
]


class LifeEnhancerMixin:
    """生活气息增强。"""

    # ---------- 1. 梦话碎碎念 ----------

    def _murmur_state(self, user: dict[str, Any]) -> dict[str, Any]:
        state = user.get("sleep_murmur")
        if not isinstance(state, dict):
            state = {}
            user["sleep_murmur"] = state
        return state

    def _murmur_should_fire(self, user: dict[str, Any]) -> bool:
        """凌晨3:00-3:45之间，每晚最多1次，且当天你们有过互动（不凭空说话）。"""
        state = self._murmur_state(user)
        today = time.strftime("%Y-%m-%d")
        # 用"夜"而非"日期"：9月7日凌晨3点算9月6日的夜
        now = self._environment_now()
        if now.hour != 3:
            return False
        night_key = time.strftime("%Y-%m-%d", time.localtime(_now_ts() - 3600))  # 前一天的日期=今夜
        if state.get("night") == night_key:
            return False
        # 他今天有活动（不是完全消失的日子）
        if _now_ts() - _safe_int(user.get("last_seen"), 0) > 8 * 3600:
            return False
        # 概率 80%（偶尔不说，更自然）
        if random.random() > 0.8:
            state["night"] = night_key  # 不说也标记，避免同一夜重试
            return False
        return True

    async def _generate_sleep_murmur(self, user: dict[str, Any]) -> str:
        """生成一句梦话。"""
        # 取最近的对话上下文做素材
        last_user = _single_line(user.get("last_user_message"), 80)
        last_bot = _single_line(user.get("last_companion_message"), 80)
        prompt = f"""{MURMUR_STYLE_HINT}

【最近他说过的话】{last_user or "（他今天没怎么说话）"}
【你最近说过的话】{last_bot or "（无）"}

只输出她会说的那一两句梦呓本身。不要旁白标记、不要引号、不要解释。"""
        try:
            result = await self._llm_call(
                prompt,
                max_tokens=100,
                provider_id=self._task_provider(
                    getattr(self, "narration_provider_id", ""),
                    getattr(self, "llm_provider_id", ""),
                ),
                task="sleep_murmur",
            )
            return _single_line(result, 120) if result else ""
        except Exception as e:
            logger.warning("[PrivateCompanion][murmur] 梦话生成失败: %s", e)
            return ""

    # ---------- 2. 今日一件事 ----------

    def _daily_event_hint(self) -> str:
        """给状态注入的素材：每天固定一件具体的小事（当天内稳定，不随每条消息变化）。"""
        today = time.strftime("%Y-%m-%d")
        cache = getattr(self, "_daily_event_hint_cache", None)
        if isinstance(cache, dict) and cache.get("day") == today and cache.get("text"):
            return str(cache["text"])
        season = self._current_season()
        weather_note = self._weather_note()
        pool = [
            f"今天{season}，{weather_note}",
            "今天在庭院里做了一件小事（具体写：修剪/发现/种植/观察到的变化）",
            "今天在家做了一件具体的事（修了什么/换了什么/整理了什么/试了什么新东西）",
            "今天在读的书里看到了一个让她有感触的细节",
            "今天尝试做了一道新菜或者用新方法做了熟悉的菜",
        ]
        picked = random.choice(pool)
        self._daily_event_hint_cache = {"day": today, "text": picked}
        return picked

    def _current_season(self) -> str:
        month = self._environment_now().month
        seasons = {12: "冬季", 1: "冬季", 2: "冬季",
                   3: "初春", 4: "春季", 5: "暮春",
                   6: "初夏", 7: "盛夏", 8: "夏末",
                   9: "初秋", 10: "深秋", 11: "秋末"}
        return seasons.get(month, "四季")

    def _weather_note(self) -> str:
        try:
            state = self.data.get("daily_state", {})
            weather = str(state.get("weather", "")).strip()
            if weather and weather != "暂无天气信息":
                return f"天气{weather}。"
        except Exception:
            pass
        return ""

    # ---------- 3. 行为模式观察 ----------

    def _behavior_observation_hint(self, user: dict[str, Any]) -> str:
        """从用户行为数据中提取一条她的观察。只用真实存在的字段，不编造。"""
        observations = []
        # 作息观察（last_seen是真实字段）
        last_seen_ts = _safe_int(user.get("last_seen"), 0)
        if last_seen_ts > 0:
            hour = time.localtime(last_seen_ts).tm_hour
            if 0 <= hour <= 5:
                observations.append(f"他最近{hour}点还在活动")
            elif 6 <= hour <= 8:
                observations.append(f"他今天{hour}点就起了，比平时早")
        if not observations:
            return ""
        return f"你注意到：{random.choice(observations)}。可以在合适的时候自然提起，不刻意。"

    # ---------- 4. 同事来访 ----------

    def _maybe_schedule_social_visit(self, user: dict[str, Any]) -> bool:
        """每周1-2次，随机触发一个同事来访。"""
        state = user.get("social_visit")
        if not isinstance(state, dict):
            state = {}
            user["social_visit"] = state
        week = time.strftime("%Y-W%W")
        if state.get("week") != week:
            # 新的一周：计数清零，否则count跨周累积导致第二周起最多只能来访1次
            state["week"] = week
            state["count"] = 0
            self._life_hooks_dirty = True  # 需要落盘（见_tick_inner钩子后的保存）
        if _safe_int(state.get("count"), 0) >= 2:
            return False
        # 概率：每次tick有0.3%概率（一天约100个tick，即约30%/天→每周约2次）
        if random.random() > 0.003:
            return False
        # 随机选角色
        char = random.choice(VISIT_CHARACTERS)
        state["week"] = week
        state["count"] = _safe_int(state.get("count"), 0) + 1
        state["last_visit"] = {"character": char["name"], "ts": _now_ts()}
        self._life_hooks_dirty = True

        # 构建候选
        title = f"{char['name']}来串门"
        motive = f"今天{char['name']}{char['visit_reason']}，这件事让你想到他"
        context = {
            "created_ts": _now_ts(),
            "character": char["name"],
            "trait": char["trait"],
            "reason": char["visit_reason"],
            "scene": char["scene_hint"],
            "hint": (
                f"用你的方式提起这次来访（一两句）。{char['name']}的性格：{char['trait']}。"
                f"场景：{char['scene_hint']}。"
                "在你的认知里这是真实发生的事，自然聊起，不是汇报。"
                "可以带一点你对这个人的评价（好的坏的都行）。"
            ),
        }
        candidate = {
            "source": "life_enhancer",
            "reason": "social_visit",
            "action": "message",
            "scheduled_ts": _now_ts() + random.randint(5, 30) * 60,
            "topic": title,
            "score": 75,
            "motive": motive,
            "context_key": "social_visit_context",
            "context": context,
        }
        accepted = self._offer_proactive_candidate(
            str(user.get("user_id") or "2117919529"), user, candidate
        )
        if accepted:
            logger.info(
                "[PrivateCompanion][visit] 已安排同事来访: %s", char["name"]
            )
        return accepted

    def _format_social_visit_context(self, user: dict[str, Any]) -> str:
        """发送时渲染来访场景。"""
        ctx = user.get("social_visit_context")
        if not isinstance(ctx, dict):
            return ""
        if _now_ts() - _safe_float(ctx.get("created_ts"), 0) > 4 * 3600:
            return ""
        name = _single_line(ctx.get("character"), 20)
        scene = _single_line(ctx.get("scene"), 100)
        trait = _single_line(ctx.get("trait"), 60)
        if not name:
            return ""
        return (
            f"【来访线索】\n"
            f"来访的人：{name}（{trait}）\n"
            f"场景：{scene}\n"
            f"用你的方式聊起这次来访。这是你生活中真实发生的事。"
        )

    # ---------- 主入口：由 _tick 调用 ----------

    async def _run_life_enhancer(self, user: dict[str, Any]) -> None:
        """在tick中运行的生活增强任务。"""
        try:
            # 梦话碎碎念
            if self._murmur_should_fire(user):
                night_key = time.strftime(
                    "%Y-%m-%d", time.localtime(_now_ts() - 3600)
                )
                # 先标记今夜已尝试：无论生成成败都不重试，避免LLM失败时每tick烧额度
                self._murmur_state(user)["night"] = night_key
                self._life_hooks_dirty = True  # 需要落盘（见_tick_inner钩子后的保存）
                murmur = await self._generate_sleep_murmur(user)
                if murmur:
                    self._murmur_state(user)["last_murmur"] = murmur
                    self._murmur_state(user)["last_ts"] = _now_ts()
                    logger.info(
                        "[PrivateCompanion][murmur] 梦话已生成: %s",
                        _single_line(murmur, 60),
                    )
                    # source=life_enhancer：走正常主动管线（timer已被官方cron取代，
                    # 会触发legacy清理逻辑导致计划被清空，梦话永远发不出）
                    candidate = {
                        "source": "life_enhancer",
                        "reason": "sleep_murmur",
                        "action": "message",
                        "scheduled_ts": _now_ts(),
                        "topic": "梦话",
                        "score": 95,
                        "motive": f"半夜醒来看到他睡着的脸，迷迷糊糊说了一句：{murmur}",
                        "context_key": "sleep_murmur_context",
                        "context": {"created_ts": _now_ts(), "murmur": murmur},
                    }
                    self._offer_proactive_candidate(
                        str(user.get("user_id") or "2117919529"),
                        user,
                        candidate,
                    )
        except Exception as e:
            logger.warning("[PrivateCompanion][murmur] 梦话任务异常: %s", e)

        try:
            # 同事来访（白天才触发）
            hour = self._environment_now().hour
            if 10 <= hour <= 21:
                self._maybe_schedule_social_visit(user)
        except Exception as e:
            logger.warning("[PrivateCompanion][visit] 来访任务异常: %s", e)

    def _format_sleep_murmur_context(self, user: dict[str, Any]) -> str:
        """发送时渲染梦话上下文。"""
        ctx = user.get("sleep_murmur_context")
        if not isinstance(ctx, dict):
            return ""
        if _now_ts() - _safe_float(ctx.get("created_ts"), 0) > 600:
            return ""
        murmur = _single_line(ctx.get("murmur"), 120)
        if not murmur:
            return ""
        return f"【梦呓线索】\n她半梦半醒时想说的话：{murmur}\n就这一两句，说完就睡了。不加旁白、不加解释。"
