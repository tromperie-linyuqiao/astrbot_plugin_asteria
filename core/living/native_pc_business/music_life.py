# -*- coding: utf-8 -*-
"""
MusicLifeMixin — 曲库生活：结构化歌单的零成本本地查询

原生宿主优先读取当前授权范围的 NativeMusicLibrary。旧 JSON 仅作明确
标注的历史资料 fallback，不经 embedding/KB 检索，也不证明喜欢或播放。
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any

from astrbot.api import logger

from .helpers import _single_line

MUSIC_DB_PATH = "/AstrBot/data/plugin_data/astrbot_plugin_private_companion/music_library.json"


class MusicLifeMixin:
    """曲库生活。"""

    def _music_db(self) -> dict[str, Any]:
        cache = getattr(self, "_music_db_cache", None)
        try:
            mtime = os.path.getmtime(MUSIC_DB_PATH)
        except Exception:
            return {}
        if cache and cache[0] == mtime:
            return cache[1]
        try:
            with open(MUSIC_DB_PATH, encoding="utf-8") as f:
                db = json.load(f)
        except Exception as e:
            logger.warning("[PrivateCompanion][music] 曲库读取失败: %s", e)
            return {}
        if not isinstance(db, dict):
            db = {}
        self._music_db_cache = (mtime, db)
        return db

    def _music_capability_hint(self) -> str:
        if not bool(getattr(self, "enable_music_life", True)):
            return ""
        db = self._music_db()
        songs = db.get("songs")
        if not isinstance(songs, list) or not songs:
            return ""
        styles = db.get("styles") or []
        languages = db.get("languages") or []
        origin = db.get('_tls_music_source', {}).get('kind', 'legacy_json_fallback')
        label = "当前授权的原生音乐资料" if origin == 'tls_native_music_library' else "旧 JSON 历史目录（未归属 fallback，不是已迁移资料）"
        return (
            f"【音乐资料】{label}中有{len(songs)}首启用记录，"
            f"{len(styles)}种已标注风格、{len(languages)}种语言。曲库构成不证明用户喜欢或播放，也不证明共同经历。"
            "想找歌/荐歌/聊歌时用 pc_music_lookup 工具查询。"
            "可能的歌名或歌词引用可以提取关键词查询；相似命中并不等于出处已经确定。"
            "\n铁律："
            "\n- 工具返回no_match只表示当前资料没有匹配，不证明外部不存在，也不证明从未听过。"
            "\n- 禁止把搜到的歌强行关联到他哼的歌词上——搜到A不等于他哼的就是A。"
            "\n- 禁止纠正他的歌词——除非你100%确定原词，否则你才可能是记错的那个。"
            "\n- 只有明确保存的用户标记或评语可以作为偏好来源；导入、收藏和曲风统计不能自行推成个人口味。"
        )

    async def _pc_music_lookup_impl(
        self,
        style: str = "",
        language: str = "",
        artist: str = "",
        keyword: str = "",
        random_pick: bool = False,
        limit: int = 5,
    ) -> str:
        db = self._music_db()
        source = db.get('_tls_music_source', {})
        origin = source.get('kind', 'legacy_json_fallback')
        attribution = dict(source=origin, read_source=source.get('read_source'), metadata_only=True,
                           creates_playback_evidence=False)
        if origin == 'blocked':
            return json.dumps(dict(status='blocked', message='当前完整范围或共享读取权限不可用，未读取其他范围或旧目录', **attribution), ensure_ascii=False)
        songs = db.get("songs")
        if not isinstance(songs, list) or not songs:
            return json.dumps(dict(status='empty', message='当前资料没有启用歌曲；不会从旧目录复活已停用或归档记录', **attribution), ensure_ascii=False)
        limit = max(1, min(int(limit or 5), 12))
        style_l = _single_line(style, 24).strip().lower()
        language_l = _single_line(language, 16).strip().lower()
        artist_l = _single_line(artist, 40).strip().lower()
        keyword_l = _single_line(keyword, 40).strip().lower()

        def match(s: dict[str, Any]) -> bool:
            if style_l and style_l not in str(s.get("style") or "").lower():
                return False
            if language_l and language_l not in str(s.get("language") or "").lower():
                return False
            if artist_l and artist_l not in str(s.get("artists") or "").lower():
                return False
            if keyword_l:
                blob = f"{s.get('name','')}{s.get('artists','')}{s.get('album','')}{s.get('lyric','')}{s.get('meaning','')}{' '.join(s.get('tags') or [])}".lower()
                if keyword_l not in blob:
                    return False
            return True

        picked = [s for s in songs if isinstance(s, dict) and match(s)]
        total = len(picked)
        if total == 0:
            styles = db.get("styles") or []
            return json.dumps(
                {"status": "no_match", "total": 0, "hint": f"当前资料没有匹配。已标注风格示例：{'、'.join(str(x) for x in styles[:10])}", **attribution},
                ensure_ascii=False,
            )
        if random_pick:
            picked = random.sample(picked, min(limit, total))
        else:
            picked = picked[:limit]
        lines = []
        for s in picked:
            line = f"- {s.get('name','')} — {s.get('artists','')}（{s.get('style','')}·{s.get('language','')}）"
            if s.get('meaning'):
                line += "；人工含义：" + _single_line(s['meaning'], 140)
            if s.get('user_preference') not in (None, '', 'neutral'):
                line += "；用户明确标记：" + _single_line(s['user_preference'], 20)
            if s.get('user_comment'):
                line += "；用户原评语：" + _single_line(s['user_comment'], 140)
            if s.get('character_comment'):
                line += "；已保存的角色评语：" + _single_line(s['character_comment'], 140)
            # 如果是歌词匹配（keyword不在歌名/歌手/专辑里），标注
            if keyword_l and keyword_l not in f"{s.get('name','')}{s.get('artists','')}{s.get('album','')}".lower():
                lyric_snippet = _single_line(s.get("lyric", ""), 80)
                if keyword_l in lyric_snippet.lower():
                    # 找到含关键词的那一行
                    for l in str(s.get("lyric", "")).split("\n"):
                        if keyword_l in l.lower():
                            line += f" ← 歌词：{l.strip()[:60]}"
                            break
            lines.append(line)
        return json.dumps(
            {"status": "ok", "total": total, "songs": lines, **attribution},
            ensure_ascii=False,
        )
