# -*- coding: utf-8 -*-
"""
ReadingLifeMixin — 读书生活：以书柜真实书籍为精神生活来源

取代创作系统的"独立生活"职责：
- 从书柜插件(astrbot_plugin_bookshelf)的消化产物中读取章节摘要
- 每个读书时段推进若干章，生成一条主动分享（读书感想）
- 进度持久化在用户状态里，读完一本换下一本；全部读完从头重读
- 主动分享走 _offer_proactive_candidate 统一管线，继承
  配额/休息闸门/复核/主题防重等全部保障
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any

from astrbot.api import logger

from .helpers import _now_ts, _safe_float, _safe_int, _single_line

BOOKSHELF_ROOT = "/AstrBot/data/plugin_data/astrbot_plugin_bookshelf"
READING_SHARE_WINDOW = (18, 22)  # 18:00-22:59 才安排读书分享（避开模型高峰+晚间阅读时段）


class ReadingLifeMixin:
    """读书生活：读书节奏 + 读书感想主动分享。"""

    # ---------- 书柜数据读取 ----------

    def _bookshelf_books(self) -> list[dict[str, Any]]:
        """扫描书柜，返回 [{book_id, title, chapter_count, digest_dir}]，按入库顺序。"""
        books: list[dict[str, Any]] = []
        books_root = os.path.join(BOOKSHELF_ROOT, "books")
        digests_root = os.path.join(BOOKSHELF_ROOT, "digests")
        if not os.path.isdir(books_root):
            return books
        try:
            entries = sorted(os.listdir(books_root))
        except Exception:
            return books
        for book_id in entries:
            meta_path = os.path.join(books_root, book_id, "meta.json")
            chapters_path = os.path.join(books_root, book_id, "chapters.json")
            if not os.path.isfile(meta_path) or not os.path.isfile(chapters_path):
                continue
            digest_dir = os.path.join(digests_root, book_id)
            if not os.path.isdir(digest_dir):
                digest_dir = ""  # 未消化的新书：读书生活直接用原文
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            books.append(
                {
                    "book_id": book_id,
                    "title": _single_line(meta.get("title"), 80) or book_id,
                    "chapter_count": _safe_int(meta.get("chapter_count"), 0, 0),
                    "digest_dir": digest_dir,
                }
            )
        return books

    def _reading_chapters_list(self, book_id: str) -> list[dict[str, Any]]:
        """带mtime缓存的chapters.json读取（大书可达15MB，避免反复解析）。"""
        path = os.path.join(BOOKSHELF_ROOT, "books", book_id, "chapters.json")
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            return []
        cache = getattr(self, "_reading_chapters_cache", None)
        if cache and cache[0] == book_id and cache[1] == mtime:
            return cache[2]
        try:
            with open(path, encoding="utf-8") as f:
                chapters = json.load(f)
        except Exception:
            return []
        if not isinstance(chapters, list):
            chapters = []
        self._reading_chapters_cache = (book_id, mtime, chapters)
        return chapters

    def _reading_chapter_titles(self, book_id: str) -> dict[int, str]:
        titles: dict[int, str] = {}
        for item in self._reading_chapters_list(book_id):
            if isinstance(item, dict):
                titles[_safe_int(item.get("index"), -1, -1)] = _single_line(item.get("title"), 40)
        return titles

    def _reading_chapter_content(self, book_id: str, index: int, limit: int = 1000) -> str:
        for item in self._reading_chapters_list(book_id):
            if isinstance(item, dict) and _safe_int(item.get("index"), -1, -1) == index:
                return _single_line(item.get("content"), limit)
        return ""

    def _reading_session_chapters(self, book: dict[str, Any], start_index: int, count: int) -> list[dict[str, Any]]:
        """读取 [start_index, start_index+count) 的章节素材。

        优先用消化摘要；摘要缺失时直接取章节原文片段——喂新书零LLM消耗。
        """
        book_id = str(book.get("book_id") or "")
        titles = self._reading_chapter_titles(book_id)
        result: list[dict[str, Any]] = []
        digest_dir = str(book.get("digest_dir") or "")
        for idx in range(start_index, min(start_index + count, _safe_int(book.get("chapter_count"), 0, 0))):
            digest_path = os.path.join(digest_dir, f"{idx}.json")
            d = None
            try:
                with open(digest_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    d = loaded
            except Exception:
                d = None
            if d is not None:
                summary = _single_line(d.get("summary"), 480)
                if summary:
                    characters_raw = d.get("characters")
                    names: list[str] = []
                    if isinstance(characters_raw, list):
                        for ch in characters_raw[:6]:
                            if isinstance(ch, dict):
                                name = _single_line(ch.get("name"), 24)
                                if name:
                                    names.append(name)
                    result.append(
                        {
                            "index": idx,
                            "title": titles.get(idx, f"第{idx + 1}章"),
                            "summary": summary,
                            "characters": names,
                        }
                    )
                    continue
            # 原文兜底：无摘要/空摘要时直接读章节原文
            raw = self._reading_chapter_content(book_id, idx, limit=1000)
            if raw:
                result.append(
                    {
                        "index": idx,
                        "title": titles.get(idx, f"第{idx + 1}章"),
                        "summary": raw,
                        "characters": [],
                        "raw": True,
                    }
                )
        return result

    # ---------- 用户读书状态 ----------

    def _reading_state(self, user: dict[str, Any]) -> dict[str, Any]:
        state = user.get("reading_life")
        if not isinstance(state, dict):
            state = {}
            user["reading_life"] = state
        return state

    def _reading_pick_book(self, state: dict[str, Any], books: list[dict[str, Any]]) -> dict[str, Any] | None:
        current_id = _single_line(state.get("book_id"), 60)
        finished = state.get("finished_books")
        if not isinstance(finished, list):
            finished = []
            state["finished_books"] = finished
        for book in books:
            if str(book.get("book_id")) == current_id and current_id not in finished:
                return book
        for book in books:
            if str(book.get("book_id")) not in finished:
                state["book_id"] = str(book.get("book_id"))
                state["next_chapter"] = 0
                return book
        # 全部读完：从第一本重新读
        if books:
            finished.clear()
            state["book_id"] = str(books[0].get("book_id"))
            state["next_chapter"] = 0
            return books[0]
        return None

    # ---------- 主动分享调度 ----------

    def _maybe_schedule_reading_share(self) -> bool:
        if not bool(getattr(self, "enable_reading_life", False)):
            return False
        hour = self._environment_now().hour
        if not (READING_SHARE_WINDOW[0] <= hour <= READING_SHARE_WINDOW[1]):
            return False
        books = self._bookshelf_books()
        if not books:
            return False
        users = self.data.get("users")
        if not isinstance(users, dict):
            return False
        now = _now_ts()
        today = time.strftime("%Y-%m-%d")
        changed = False
        max_daily = _safe_int(getattr(self, "reading_share_max_daily", 2), 2, 1, 6)
        min_interval = _safe_int(getattr(self, "reading_share_min_interval_hours", 3), 3, 1, 48) * 3600
        base_probability = _safe_float(getattr(self, "reading_share_probability", 0.7), 0.7, 0.0, 1.0)
        for user_id, user in users.items():
            if not isinstance(user, dict) or not self._is_target_private_user(str(user_id), user) or not user.get("enabled", True) or not user.get("umo"):
                continue
            if not self._friend_can_receive_proactive_reason(user, "reading_share", "message"):
                continue
            state = self._reading_state(user)
            if state.get("shared_day") != today:
                state["shared_day"] = today
                state["shared_today"] = 0
                changed = True  # 跨天重置也要落盘，否则重启可能重复分享
            if _safe_int(state.get("shared_today"), 0, 0) >= max_daily:
                continue
            if now - _safe_float(state.get("last_share_at"), 0) < min_interval:
                continue
            idle_seconds = now - _safe_float(user.get("last_seen"), 0)
            if idle_seconds < max(self.idle_minutes, 75) * 60:
                continue
            book = self._reading_pick_book(state, books)
            if not isinstance(book, dict):
                continue
            chapter_count = _safe_int(book.get("chapter_count"), 0, 0)
            # 上限用chapter_count而非chapter_count-1：next_chapter==chapter_count
            # 是"读完待换书"的哨兵值，钳到-1会让完书检测(start_index>=chapter_count)
            # 永远不成立，最后一章摘要缺失时永远重读同一章
            start_index = _safe_int(state.get("next_chapter"), 0, 0, max(0, chapter_count))
            if start_index >= chapter_count:
                finished = state.get("finished_books")
                if not isinstance(finished, list):
                    finished = []
                    state["finished_books"] = finished
                if str(book.get("book_id")) not in finished:
                    finished.append(str(book.get("book_id")))
                book = self._reading_pick_book(state, books) or {}
                start_index = _safe_int(state.get("next_chapter"), 0, 0)
                chapter_count = _safe_int(book.get("chapter_count"), 0, 0)
                if not book or start_index >= chapter_count:
                    continue
            per_session = _safe_int(getattr(self, "reading_chapters_per_session", 4), 4, 1, 12)
            count = max(1, per_session + random.randint(-1, 1))
            chapters = self._reading_session_chapters(book, start_index, count)
            end_index = min(start_index + count, chapter_count)
            if not chapters:
                # 摘要缺失也推进进度，避免卡死在坏章节
                state["next_chapter"] = end_index
                changed = True
                continue
            if random.random() > base_probability:
                continue
            # 读书分享不受"他要睡觉"判定影响（用户明确：高质量消息可以一直打扰）
            title = _single_line(book.get("title"), 60)
            # 去掉常见文件名后缀，便于口播
            for suffix in (".txt", ".epub", ".md"):
                if title.lower().endswith(suffix):
                    title = title[: -len(suffix)]
                    break
            first_chapter = chapters[0]
            last_chapter = chapters[-1]
            progress = f"第{end_index}/{chapter_count}章"
            if end_index >= chapter_count:
                progress = "读完最后一章"
            book_finished = end_index >= chapter_count
            highlight = _single_line(random.choice(chapters).get("summary"), 200)
            names = sorted({n for ch in chapters for n in ch.get("characters", [])})[:5]
            motive_topic = f"读书：{title} {first_chapter.get('title', '')}起"
            scheduled = now + random.randint(10, 40) * 60
            candidate = {
                "source": "reading_life",
                "reason": "reading_share",
                "action": "message",
                "scheduled_ts": scheduled,
                "topic": _single_line(motive_topic, 80),
                "score": int(max(70, min(88, 74 + len(chapters) * 2))),
                "motive": f"刚读完《{title}》{first_chapter.get('title', '')}到{last_chapter.get('title', '')}，有点感触，想自然地跟他说一句",
                "context_key": "reading_share_context",
                "context": {
                    "created_ts": now,
                    "book_id": str(book.get("book_id")),
                    "title": title,
                    "chapters": [
                        {
                            "title": _single_line(ch.get("title"), 40),
                            "summary": _single_line(ch.get("summary"), 320),
                        }
                        for ch in chapters
                    ],
                    "characters": names,
                    "progress": progress,
                    "finished": book_finished,
                },
            }
            accepted = self._offer_proactive_candidate(str(user_id), user, candidate)
            state["next_chapter"] = end_index
            if accepted:
                state["last_share_at"] = now
                state["shared_today"] = _safe_int(state.get("shared_today"), 0, 0) + 1
            if book_finished:
                finished = state.setdefault("finished_books", [])
                if str(book.get("book_id")) not in finished:
                    finished.append(str(book.get("book_id")))
                state["next_chapter"] = 0
                state["book_id"] = ""
            changed = True
            if accepted:
                # 前情提要：把本次阅读前2章的摘要也放进上下文——
                # 人物锚点的素材来源（"尚翎雪是谁"的答案在前文里）
                prev_chapters = []
                if start_index >= 2:
                    prev_chapters = self._reading_session_chapters(book, start_index - 2, 2)
                ctx = candidate.get("context")
                if isinstance(ctx, dict) and prev_chapters:
                    ctx["prev_recap"] = [
                        {
                            "title": _single_line(ch.get("title"), 40),
                            "summary": _single_line(ch.get("summary"), 240),
                        }
                        for ch in prev_chapters
                    ]
                logger.info(
                    "[PrivateCompanion][reading_life] 已安排读书分享: user=%s book=%s chapters=%d-%d %s prev_recap=%d",
                    _single_line(user.get("user_id"), 40),
                    title,
                    first_chapter.get("index", start_index),
                    max(start_index + count - 1, start_index),
                    progress,
                    len(prev_chapters),
                )
        return changed

    # ---------- 发送时上下文 ----------

    def _format_reading_share_action_context(self, user: dict[str, Any]) -> str:
        reading = user.get("reading_share_context")
        if not isinstance(reading, dict):
            return ""
        if _now_ts() - _safe_float(reading.get("created_ts"), 0) > 8 * 3600:
            return ""
        title = _single_line(reading.get("title"), 60)
        if not title:
            return ""
        chapters = reading.get("chapters") if isinstance(reading.get("chapters"), list) else []
        prev = reading.get("prev_recap") if isinstance(reading.get("prev_recap"), list) else []
        names = [n for n in (reading.get("characters") or []) if isinstance(n, str)][:5]
        parts = [
            "读书分享线索",
            f"书名：{title}",
            f"刚读到的进度：{_single_line(reading.get('progress'), 24)}",
        ]
        if prev:
            recap_lines = [f"- {_single_line(p.get('title'), 40)}：{_single_line(p.get('summary'), 180)}" for p in prev if isinstance(p, dict) and _single_line(p.get("summary"), 180)]
            if recap_lines:
                parts.append("前情提要（给雨桥做人物锚点用的素材，讲新内容前先用一句话把人认回来）：\n" + "\n".join(recap_lines))
        if names:
            parts.append(f"本章主要角色：{'、'.join(names)}")
        for ch in chapters[:4]:
            ch_title = _single_line(ch.get("title"), 40) if isinstance(ch, dict) else ""
            summary = _single_line(ch.get("summary"), 200) if isinstance(ch, dict) else ""
            if summary:
                parts.append(f"- {ch_title}：{summary}")
        if reading.get("finished"):
            parts.append("这本书正好读完了，可以带一点合上书的余味")
        parts.append("以上是她真实读过的章节内容，感想必须基于这些章节，不要虚构书里没有的情节")
        parts.append(
            "听众说明：雨桥读过这些书但记不全细节。分享时：\n"
            "- 先给一句前情或人物锚点（'猫爷，之前把徒弟踹下车那个'），再讲这次读到的东西——他接得住才有得回\n"
            "- 用你的反应带出内容，不用剧情黑话开场（'十一章狰把王诩吞了'这种他没法接）\n"
            "- 他没接上不代表不想听——那是记忆没被勾回来，换个角度再聊，不追问读没读"
        )
        return "\n".join(part for part in parts if part)
