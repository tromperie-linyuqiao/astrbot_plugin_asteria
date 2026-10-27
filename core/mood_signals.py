"""信号适配器：四个只读源，mtime 无关直读（每分钟一轮，量级极小）。
纪律：结构宽容（任何缺失/坏 JSON → 未激活兜底形态而非 None，0.29.1），绝不写入兄弟插件目录。纯函数无 astrbot 依赖。
0.30.0 新增第五源 read_verbal：PC companions.json 的对话情绪（mtime 缓存——该文件较大且调用频）。"""
from __future__ import annotations

import json
import math
import os
import re
import time as _time
from typing import Any

from .. import CONFIG


def _read_json(path: str) -> Any | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _plugin_data_dir(data_dir: str) -> str:
    """存在层合并 0.27.0：心绪与身体/空间同插件——data_dir 即 vb 的 plugin_data 根。"""
    return str(data_dir)


def _peer_dir(data_dir: str, peer: str) -> str:
    """跨插件兄弟目录（洞察/书柜仍是独立插件，只读）。"""
    return os.path.normpath(os.path.join(_plugin_data_dir(data_dir), "..", peer))


def _collect_text(obj: Any, depth: int = 0) -> str:
    """递归收集 WEATHER_TEXT_KEYS 命中字段的文本（雨词识别用）。"""
    if depth > 4 or not isinstance(obj, dict):
        return ""
    parts = []
    for k, v in obj.items():
        if isinstance(v, str) and k in CONFIG.MO_WEATHER_TEXT_KEYS:
            parts.append(v)
        elif isinstance(v, dict):
            parts.append(_collect_text(v, depth + 1))
        elif isinstance(v, list):
            # 终审修复：list 分支此前不可达（被 dict|list 合并分支吞掉）——嵌套数组里的雨词全漏
            parts.append(" ".join(_collect_text(x, depth + 1) if isinstance(x, dict)
                                  else (x if isinstance(x, str) else "")
                                  for x in v))
    return " ".join(parts)


def read_weather(data_dir: str, now: float | None = None) -> dict[str, Any] | None:
    """天气：plugin_data/astrbot_plugin_weather_ez 下最新 *.json（排除 .names.json / .tmp）。
    0.29.1 兜底：无快照（用户还没问过天气）不返回 None——返回 available=False 的未激活形态，
    规则面板能区分"信号未激活"与"信号不存在"；is_rain=None 让 eq/ne 均不误命中。
    0.32.0 TTL：快照超过 MO_WEATHER_TTL_SECONDS（6h）未更新 → 过期不当真——available=False、
    is_rain=None、stale=True（雨是几小时前的旧闻，规则不再据此触发）。"""
    inner = os.path.join(_plugin_data_dir(data_dir), "weather")
    folder = inner if os.path.isdir(inner) else os.path.join(
        os.path.normpath(os.path.join(_plugin_data_dir(data_dir), "..")), CONFIG.MO_LEGACY_WEATHER_DIR)
    unavailable = {"available": False, "city": "", "condition": "",
                   "is_rain": None, "updated_at": "", "stale": False}
    try:
        names = [n for n in os.listdir(folder)
                 if n.endswith(".json") and not n.endswith(".names.json") and not n.endswith(".tmp")]
    except OSError:
        return unavailable
    best: tuple[float, str] | None = None
    for n in names:
        try:
            mtime = os.stat(os.path.join(folder, n)).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, n)
    if best is None:
        return unavailable
    # 自带工具的权威观测固定写 weather_last.json；辅助城市表/其他 JSON 不应抢占天气。
    canonical = os.path.join(folder, CONFIG.WEATHER_SNAPSHOT_FILE)
    if os.path.isfile(canonical):
        try:
            best = (os.stat(canonical).st_mtime, CONFIG.WEATHER_SNAPSHOT_FILE)
        except OSError:
            return unavailable
    data = _read_json(os.path.join(folder, best[1]))
    if not isinstance(data, dict):
        return unavailable
    now = _time.time() if now is None else float(now)
    observed_at = _weather_observed_at(data.get("updated_at"))
    future = observed_at is not None and observed_at - now > 300
    # mtime 与可解析的观测时间取较早值，复制/恢复旧文件无法续期旧天气。
    observed_at = min(best[0], observed_at) if observed_at is not None else best[0]
    age = now - observed_at
    stale = future or age >= CONFIG.MO_WEATHER_TTL_SECONDS or age < -300
    if stale:
        # 过期：available=False 封死 eq/ne/changed（规则引擎 0.29.1 机制），is_rain 不再当真
        return {"available": False, "city": str(data.get("city") or ""),
                "condition": "", "is_rain": None,
                "observed_at": observed_at,
                "updated_at": data.get("updated_at") or "", "stale": True}
    current = [data.get(k) for k in ("weather", "condition") if isinstance(data.get(k), str)]
    text = " ".join(current).lower() if current else _collect_text(data).lower()
    if not text.strip():
        return unavailable
    return {
        "available": True,
        "city": str(data.get("city") or ""),
        "condition": text[:120],
        "is_rain": any(w in text for w in CONFIG.MO_RAIN_WORDS),
        "updated_at": data.get("updated_at") or "",
        "observed_at": observed_at,
        "stale": False,
    }


def _weather_observed_at(value: Any) -> float | None:
    """自带快照的 naive ISO 按生成它的容器本地时区解释；显式 offset 保留。"""
    if not value or isinstance(value, bool):
        return None
    try:
        import datetime as dt
        stamp = (float(value) if isinstance(value, (int, float))
                 else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
        return stamp if math.isfinite(stamp) else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _body_hint_boost(data_dir: str, now: float | None = None) -> float:
    """身体→情绪（0.30.0）：mood/body_mood_hint.json 的 recent warm hint 加成——
    overload 进余韵时 main 写入 {ts, hint:"warm"}，TTL 内线性衰减（刚结束时 +0.15，2h 归零）。
    坏文件/过期/未来时间戳一律 0.0。"""
    from .decay import parse_ts   # 局部导入避免加载序耦合（decay 不依赖本模块，无环）
    data = _read_json(os.path.join(_plugin_data_dir(data_dir), CONFIG.MO_DATA_SUBDIR,
                                   CONFIG.MO_BODY_HINT_FILE))
    if not isinstance(data, dict) or str(data.get("hint") or "") != "warm":
        return 0.0
    ts = parse_ts(data.get("ts"))
    if ts is None or not math.isfinite(ts):
        return 0.0
    now = _time.time() if now is None else float(now)
    age = now - ts
    if age < 0.0 or age >= CONFIG.MO_BODY_HINT_TTL:
        return 0.0
    return CONFIG.MO_BODY_HINT_BOOST * (1.0 - age / CONFIG.MO_BODY_HINT_TTL)


def read_mood(data_dir: str, now: float | None = None,
              max_age_seconds: float = 2 * 86400) -> dict[str, Any] | None:
    """用户情绪：insight_center 的 mood_calibration.json，取最近日期条目（score -1~1）。
    0.30.0 融合身体→情绪通道：read_mood 结果叠加 body_mood_hint 的 warm 加成（2h 线性衰减）——
    无标定数据但 hint 新鲜时也给出小正值（身体余温本身就是情绪信号）。
    0.29.1 兜底：insight_center 未装/未标定（源文件不存在）不返回 None——返回
    available=False 未激活形态（score=None），面板显示"未激活"；lte/gte 对 None 不命中。"""
    # normpath：Linux 内核解析 "x/../y" 要求 x 真实存在（Windows 由 CRT 归一化无此要求）；
    # 测试传入虚构基目录时同样可用（与 _peer_dir 同款处理）
    path = os.path.normpath(os.path.join(
        _plugin_data_dir(data_dir), "..", CONFIG.MO_SRC_MOOD_FILE))
    data = _read_json(path)
    best_day, best, observed_at = "", None, None
    if isinstance(data, dict):
        entries = data.get("calibrations") or data.get("days") or data
        if isinstance(entries, dict):
            items = entries.items()
        elif isinstance(entries, list):
            items = [(str(e.get("day") or e.get("date") or ""), e) for e in entries if isinstance(e, dict)]
        else:
            items = []
        for day, e in items:
            if isinstance(e, dict) and str(day) >= best_day:
                if not any(key in e for key in ("final", "score", "mood")):
                    continue
                try:
                    raw = e.get("final", e.get("score", e.get("mood", 0.0)))
                    score = float(raw)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(score):
                    continue
                best_day, best = str(day), score
                observed_at = _weather_observed_at(e.get("updated_at") or e.get("ts"))
                day_start = _weather_observed_at(str(day) + "T00:00:00+08:00")
                if day_start is not None:
                    observed_at = min(observed_at, day_start) if observed_at is not None else day_start
    now = _time.time() if now is None else float(now)
    future = observed_at is not None and observed_at - now > 300
    try:
        file_time = os.stat(path).st_mtime
    except OSError:
        file_time = now
    observed_at = min(file_time, observed_at) if observed_at is not None else file_time
    age = now - observed_at
    stale = best is not None and (future or age >= max_age_seconds or age < -300)
    if stale:
        best = None   # 日级标定最多跨次日可用；后续后台写盘不能把旧日低落继续当作现在。
    boost = _body_hint_boost(data_dir, now)
    if best is None and boost <= 0.0:
        return {"available": False, "score": None, "confidence": 0.0, "day": best_day,
                "stale": stale}
    base = best if best is not None else 0.0
    return {"available": True, "score": max(-1.0, min(1.0, base + boost)),
            "confidence": 1.0 if best is not None else 0.3, "day": best_day,
            "stale": stale, "source": "calibration" if best is not None else "body_hint"}


def read_reading(data_dir: str) -> dict[str, Any] | None:
    """书柜：最新 mtime 的书的消化进度（digest 计数 / 总章数）。她的"读到哪"由 PC 模型自己补。
    0.29.1 兜底：书柜插件未装/无书 → available=False 未激活形态（chapter_index=None）——
    消化进度出现时（None→N）与 last_state 的 None 基线构成可比"changed"。"""
    unavailable = {"available": False, "book_id": "", "book_title": "",
                   "chapter_index": None, "chapter_count": 0}
    _bs_root = _peer_dir(data_dir, CONFIG.MO_SRC_BOOKSHELF_DIR)
    root = os.path.join(_bs_root, "books")
    _dg_root = os.path.join(_bs_root, "digests")
    try:
        book_ids = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return unavailable
    best: tuple[float, str, dict] | None = None
    for bid in book_ids:
        meta = _read_json(os.path.join(root, bid, "meta.json"))
        if not isinstance(meta, dict):
            continue
        try:
            mtime = os.stat(os.path.join(root, bid, "meta.json")).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, bid, meta)
    if best is None:
        return unavailable
    _, bid, meta = best
    try:
        total = int(meta.get("chapter_count") or 0)
    except (TypeError, ValueError):
        total = 0
    dg = os.path.join(_dg_root, bid)
    done = 0
    try:
        indices = set()
        for name in os.listdir(dg):
            if not re.fullmatch(r"\d+\.json", name):
                continue
            index = int(name[:-5])
            if total > 0 and index >= total:
                continue
            if isinstance(_read_json(os.path.join(dg, name)), dict):
                indices.add(index)
        done = len(indices)
    except OSError:
        done = 0
    if total > 0 and done >= total:
        # 完本保护（0.32.0）：章节全消化后 digest 不再增长，changed 永不可触发——
        # book_title 换"[已完本]"并 available=False，防误导模型说她还在读这本书
        return {"available": False, "book_id": bid, "book_title": "[已完本]",
                "chapter_index": None, "chapter_count": total}
    return {
        "available": True,
        "book_id": bid,
        "book_title": str(meta.get("title") or bid),
        "chapter_index": done,
        "chapter_count": total,
    }


def _latest_body_stem(folder: str, all_names: list[str]) -> str | None:
    """state 目录里最新 mtime 的身体状态文件 stem（<character>_<session>.json，排除
    .space.json / bindings.json / .names.json / .tmp）——presence 兜底的真值来源。"""
    best: tuple[float, str] | None = None
    for n in all_names:
        if not n.endswith(".json") or n.endswith(".tmp"):
            continue
        if n.endswith(".space.json") or n == "bindings.json" or n.endswith(".names.json"):
            continue
        try:
            mtime = os.stat(os.path.join(folder, n)).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, n)
    return None if best is None else best[1][: -len(".json")]


def _has_profile_override(data_dir: str) -> bool:
    """plugin_data/profiles/ 下有 profile 覆盖文件（排除 .names.json/.bak/.tmp）——插件被编辑使用过的迹象。"""
    try:
        names = os.listdir(os.path.join(_plugin_data_dir(data_dir), "profiles"))
    except OSError:
        return False
    return any(n.endswith(".json") and not n.endswith(".names.json") and not n.endswith(".tmp")
               for n in names)


def read_presence(data_dir: str, manor: dict | None = None,
                  session_key: str | None = None) -> dict[str, Any] | None:
    """存在层：最新 .space.json（她房/移动）+ 同 key 身体文件（phase/arousal）。
    0.29.1 兜底（线上根因修复）：白名单会话未触发过空间事件时 .space.json 不存在，
    原实现返回 None → presence_room_changed/longing_invite/mood_warm 等规则全部短路。
    现按三层迹象兜底（插件在服役即给中性默认）：身体状态文件（phase/arousal 取真值）>
    profile 覆盖层 > 已加载庄园 manor；she_room=None 是"changed"的可比基线——
    她首次落位（space 文件生成）即从 None 变为具体房间，规则可触发。
    三层迹象全无（插件未使用）仍返回 None（信号不存在）。"""
    folder = os.path.join(_plugin_data_dir(data_dir), CONFIG.SP_STATE_DIR_NAME)
    try:
        all_names = [n for n in os.listdir(folder) if n.endswith(".json") and not n.endswith(".tmp")]
    except OSError:
        all_names = []
    scoped = session_key is not None
    if scoped:
        session_key = str(session_key)
        if not re.fullmatch(CONFIG.SP_SESSION_RE, session_key):
            return None
        all_names = [n for n in all_names
                     if n in (session_key + ".json", session_key + ".space.json")]
    best: tuple[float, str] | None = None
    for n in all_names:
        if not n.endswith(".space.json"):
            continue
        try:
            mtime = os.stat(os.path.join(folder, n)).st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, n)
    sp: dict[str, Any] = {}
    stem: str | None = None
    from_space = False
    if best is not None:
        sp = _read_json(os.path.join(folder, best[1]))
        sp = sp if isinstance(sp, dict) else {}   # 坏 space 文件也走兜底（不再 null）
        stem = best[1][: -len(".space.json")]
        from_space = isinstance(sp.get("she"), dict)
    else:
        stem = _latest_body_stem(folder, all_names)
        if stem is None and not _has_profile_override(data_dir) and not manor:
            return None
    she = sp.get("she") if isinstance(sp.get("she"), dict) else {}
    he = sp.get("he") if isinstance(sp.get("he"), dict) else {}
    she_room = str(she.get("room") or "")
    if manor and she_room not in _presence_rooms(manor):
        she_room = ""
    out: dict[str, Any] = {
        "available": True,
        # 无 space 文件时 she_room=None（未知）：作为 changed 基线可比较；有 space 文件保持 str 语义
        "she_room": (she_room or None),
        "she_moving": bool(she.get("moving")),
        "he_moving": bool(he.get("moving")),
        "body_phase": "",
        "arousal": 0.0,
    }
    if stem is not None:
        body = _read_json(os.path.join(folder, stem + ".json"))
        if isinstance(body, dict):
            out["body_phase"] = str(body.get("phase") or "")
            try:
                value = float(body.get("arousal") or 0.0)
                out["arousal"] = round(max(0.0, min(1.0, value)), 2) if math.isfinite(value) else 0.0
            except (TypeError, ValueError):
                pass
    # 环境底色（0.27.2）：房间 mood_bias → env_valence/env_arousal/mood_word + 同室判定
    from . import space as _space
    if manor:
        v, a = _space.room_mood_bias(manor, out["she_room"])
        out["env_valence"] = v
        out["env_arousal"] = a
        out["mood_word"] = _space.mood_word(v, a)
        declared_he_room = str(he.get("room") or "")
        he_room = declared_he_room
        if he_room not in _presence_rooms(manor):
            he_room = ""
        he_inferred = False
        if not declared_he_room and out["she_room"] and not out["she_moving"] and not out["he_moving"]:
            # 他位置兜底（0.32.0）：he.room 未知而她已落位 → 推断他在她身边——
            # same_room 从恒 False 变为可达 True；confidence=0.5（低于显式陈述），
            # he_inferred=True 标注推断来源（渲染层措辞与正常同室一致，不暴露推断细节）
            he_room = str(out["she_room"])
            he_inferred = True
        out["he_room"] = he_room
        out["he_inferred"] = he_inferred
        if he_inferred:
            out["he_confidence"] = CONFIG.MO_HE_INFER_CONFIDENCE
        try:
            confidence = float(he.get("confidence", 1.0))
            he_known = math.isfinite(confidence) and confidence >= 0.5
        except (TypeError, ValueError):
            he_known = False
        out["same_room"] = bool(he_room) and he_room == (out["she_room"] or "") \
            and not out["she_moving"] and not out["he_moving"] and (he_inferred or he_known)
    return out


def _presence_rooms(manor: dict[str, Any]) -> set[str]:
    from .space import known_rooms
    return known_rooms(manor)


# read_verbal 的 PC 文件缓存：path → (mtime_ns, 解析出的用户情绪摘要 dict)。mtime 不变免读盘。
_VERBAL_CACHE: dict[str, tuple[int, dict[str, tuple[str, float | None]]]] = {}


def _verbal_users_summary(data: Any) -> dict[str, tuple[str, float | None]]:
    """从 PC companions.json 抽 {QQ: emotion}——users.<QQ>.intent_profile.emotion 优先，
    容错回退 users.<QQ>.emotion；非 dict/无 users 回空（结构宽容，绝不抛）。"""
    out: dict[str, tuple[str, float | None]] = {}
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, dict):
        return out
    for uid, u in users.items():
        if not isinstance(u, dict):
            continue
        ip = u.get("intent_profile") if isinstance(u.get("intent_profile"), dict) else {}
        emotion = ip.get("emotion") if ip.get("emotion") is not None else u.get("emotion")
        if emotion is None:
            continue
        text = str(emotion).strip()
        if text:
            out[str(uid)] = (text[:32], _weather_observed_at(u.get("last_user_message_at")))
    return out


def read_verbal(data_dir: str, whitelist: list[str] | tuple[str, ...] | None = None,
                emotions: Any = None, now: float | None = None,
                ttl: float | None = None) -> dict[str, Any]:
    """语言调情信号（0.30.0）：读 PC companions.json 的用户对话情绪标签（只读，mtime 缓存）。
    whitelist 给定时只认白名单用户（vb 会话的 profile 白名单），全部缺失则回退全体用户的
    首个可用情绪（排序确定性）；emotions 覆盖亲密情绪集（None 回 CONFIG.VERBAL_INTIMATE_EMOTIONS）。
    返回 {available, emotion, is_intimate}——PC 未装/无情绪字段/白名单无命中 → available=False（不误触）。"""
    path = os.path.normpath(os.path.join(
        _plugin_data_dir(data_dir), "..", "astrbot_plugin_private_companion", "companions.json"))
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _VERBAL_CACHE.pop(path, None)
        return {"available": False, "emotion": "", "is_intimate": False}
    cached = _VERBAL_CACHE.get(path)
    if cached is None or cached[0] != mtime:
        summary = _verbal_users_summary(_read_json(path))
        if len(_VERBAL_CACHE) >= 4:
            _VERBAL_CACHE.pop(next(iter(_VERBAL_CACHE)), None)
        _VERBAL_CACHE[path] = (mtime, summary)
    else:
        summary = cached[1]
    selected: tuple[str, float | None] | None = None
    if whitelist:
        # 白名单口径：只认白名单用户的情绪，全缺失 → available=False（非白名单不误触）
        for uid in whitelist:
            if str(uid) in summary:
                selected = summary[str(uid)]
                break
    elif summary:
        selected = summary[sorted(summary)[0]]   # 未传白名单：首个可用用户（排序确定性）
    if selected is None:
        return {"available": False, "emotion": "", "is_intimate": False}
    emotion, observed_at = selected
    now = _time.time() if now is None else float(now)
    ttl = CONFIG.VERBAL_AROUSAL_TAU if ttl is None else float(ttl)
    future = observed_at is not None and observed_at - now > 300
    source_time = mtime / 1_000_000_000
    observed_at = min(source_time, observed_at) if observed_at is not None else source_time
    age = now - observed_at
    if future or age >= ttl or age < -300:
        # 保留旧增益/衰减规则；离线旧标签不再每分钟重新给身体添火。
        return {"available": False, "emotion": "", "is_intimate": False,
                "stale": True, "age_seconds": max(0, round(age))}
    pool = emotions if emotions is not None else CONFIG.VERBAL_INTIMATE_EMOTIONS
    words = {str(w).strip().lower() for w in (pool or ()) if str(w).strip()}
    return {"available": True, "emotion": emotion,
            "is_intimate": emotion.strip().lower() in words}


def read_all(data_dir: str, manor: dict | None = None,
             session_key: str | None = None, now: float | None = None, *,
             reading_enabled: bool = True) -> dict[str, dict[str, Any] | None]:
    return {"weather": read_weather(data_dir, now), "mood": read_mood(data_dir, now),
            "reading": read_reading(data_dir) if reading_enabled is True else
                {"available": False, "disabled": True, "book_id": "", "book_title": "",
                 "chapter_index": None, "chapter_count": 0},
            "presence": read_presence(data_dir, manor, session_key)}
