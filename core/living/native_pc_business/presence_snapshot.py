"""存在层快照（L1 线，PC 侧只读消费）。

为 PC 主动消息的 prompt 提供一段 ≤100 字符的只读快照：她此刻在哪个房间
（含该房前 3 件家具）以及身体状态短语，让她主动开口时知道自己身在何处。

数据源（全部只读，绝不写入）：
  plugin_data/astrbot_plugin_virtual_body/state/<character>_<session>.space.json
      —— 空间状态（she.room / he.room / moving）
  plugin_data/astrbot_plugin_virtual_body/state/<character>_<session>.json
      —— 身体状态（arousal / phase）
  manor.json（房名与家具）：
      1) plugin_data/astrbot_plugin_virtual_body/manor/manor.json（用户覆盖层，vb 语义优先）
      2) 从 PC 的 plugin_data 目录推 ../../plugins/astrbot_plugin_virtual_body/data/manor.json
         （运行时服务器上 vb 插件源码目录自带的 builtin），失败则房间用 room id 原文

纪律：
- 纯只读 + 模块级 mtime 缓存（容量 32，dict+清理的简化 LRU）
- 结构宽容：文件不存在 / JSON 坏 / 核心字段缺失 → 一律返回空串，绝不抛异常
- 绝不读取任何 *.names.json（快照不需要命名层）
- 输出总长超 100 字符截断
"""
from __future__ import annotations

import json
import os
import re
import time as _time
from typing import Any

_MAX_CHARS = 100
_CACHE_LIMIT = 32
_SESSION_RE = re.compile(r"[A-Za-z0-9_:\-]+")          # 对齐 vb SP_SESSION_RE
_VB_NAME = "astrbot_plugin_virtual_body"
_SPACE_SUFFIX = ".space.json"

# 模块级 mtime 缓存：path -> (mtime_ns, 解析结果)。容量 32，超限清最旧（插入序）。
_cache: dict[str, tuple[int, Any]] = {}


def _load_json_file(path: str) -> Any:
    """mtime 缓存读 JSON；文件不存在 / 坏 JSON → None（同时清掉该键的缓存）。"""
    try:
        mtime_ns = os.stat(path).st_mtime_ns
    except OSError:
        _cache.pop(path, None)
        return None
    hit = _cache.get(path)
    if hit is not None and hit[0] == mtime_ns:
        _cache.pop(path, None)      # LRU 触碰：删掉重插，移到末尾
        _cache[path] = hit
        return hit[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        _cache.pop(path, None)
        return None
    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)), None)
    _cache[path] = (mtime_ns, data)
    return data


def _find_space_file(state_dir: str, session: str) -> str:
    """在 state/ 下找 <character>_<session>.space.json（character 无下划线，后缀即边界）。"""
    suffix = f"_{session}{_SPACE_SUFFIX}"
    try:
        names = sorted(os.listdir(state_dir))
    except OSError:
        return ""
    for name in names:
        if name.endswith(suffix) and not name.endswith(".tmp"):
            return os.path.join(state_dir, name)
    return ""


def _load_manor(pc_data_dir: str) -> Any:
    """manor.json：用户覆盖层优先，其次 ../../plugins/.../data/manor.json；失败返回 None。"""
    base = os.path.dirname(os.path.normpath(str(pc_data_dir)))   # plugin_data/
    candidates = (
        os.path.join(base, _VB_NAME, "manor", "manor.json"),
        os.path.normpath(
            os.path.join(
                str(pc_data_dir), "..", "..", "plugins", _VB_NAME, "data", "manor.json"
            )
        ),
    )
    for path in candidates:
        data = _load_json_file(path)
        if isinstance(data, dict):
            return data
    return None


def _room_label(manor: Any, room_id: str) -> tuple[str, list[str]]:
    """room id → (房名, 家具名列表)；manor 缺失/找不到房间时房名用 room id 原文。"""
    if isinstance(manor, dict):
        for room in manor.get("rooms") or []:
            if isinstance(room, dict) and str(room.get("id") or "") == room_id:
                label = str(room.get("label") or "").strip()
                props = [
                    str(item).strip()
                    for item in (room.get("props") or [])
                    if str(item or "").strip()
                ]
                return (label or room_id), props
    return room_id, []


def _body_phrase(body: dict[str, Any]) -> str:
    """arousal/phase → 短语：平静 / 渐起 / 余韵 / 不应期。"""
    try:
        arousal = float(body.get("arousal") or 0.0)
    except (TypeError, ValueError):
        arousal = 0.0
    phase = str(body.get("phase") or "").strip()
    if phase == "afterglow":
        return "余韵"
    if phase == "cooldown":
        return "不应期"
    return "渐起" if arousal >= 0.15 else "平静"




def _find_body_file(state_dir: str, session: str) -> dict[str, Any] | None:
    """找最近 mtime 的 <char>_<session>.json（排除 .space/.names）。"""
    import glob as _glob
    pattern = os.path.join(state_dir, f"*_{session}.json")
    best_path, best_mtime = None, -1.0
    for p in _glob.glob(pattern):
        if p.endswith(".space.json") or p.endswith(".names.json"):
            continue
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt > best_mtime:
            best_path, best_mtime = p, mt
    return _load_json_file(best_path) if best_path else None


def _intent_phrase(body: dict[str, Any]) -> str:
    """主动触碰意图短语（TTL 30 分钟内附在快照尾部）。"""
    intent = body.get("proactive_intent")
    if not isinstance(intent, dict):
        return ""
    hint = str(intent.get("hint") or "").strip()
    ts = intent.get("ts")
    try:
        ts_val = float(ts) if ts is not None else 0.0
    except (TypeError, ValueError):
        return ""
    if not hint or ts_val <= 0:
        return ""
    import time as _t
    if _t.time() - ts_val > 1800:
        return ""
    return f"，{hint[:14]}"


def build_snapshot(data_dir: str, session: str, now: float) -> str:
    """生成存在层快照（纯只读）。

    data_dir：PC 自己的 plugin_data 目录（plugin_data/astrbot_plugin_private_companion）。
    session：目标用户 QQ 号。任何缺失/坏数据 → 空串（调用方跳过拼接即可）。
    样例输出：（她此刻在厨房（中岛·炉灶·咖啡机），身体平静）
    """
    try:
        session = str(session or "").strip()
        if not session or not _SESSION_RE.fullmatch(session):
            return ""
        pc_data_dir = str(data_dir or "").strip()
        if not pc_data_dir:
            return ""
        state_dir = os.path.join(
            os.path.dirname(os.path.normpath(pc_data_dir)), _VB_NAME, "state"
        )
        space_path = _find_space_file(state_dir, session)
        space = _load_json_file(space_path) if space_path else None
        if not isinstance(space, dict):
            space = {}
        she = space.get("she") if isinstance(space.get("she"), dict) else {}
        room_id = str(she.get("room") or "").strip()
        # 0.30.1 兜底：无空间数据时仍给出身体短语（主动消息至少知道她的身体状态）
        if not room_id:
            body = _find_body_file(state_dir, session)
            if isinstance(body, dict):
                return f"（她身体{_body_phrase(body)}{_intent_phrase(body)}）"[:_MAX_CHARS]
            return ""
        body_path = space_path[: -len(_SPACE_SUFFIX)] + ".json"
        body = _load_json_file(body_path)
        if not isinstance(body, dict):
            body = {}
        label, props = _room_label(_load_manor(pc_data_dir), room_id)
        head = f"她此刻在{label}"
        if props:
            head += f"（{'·'.join(props[:3])}）"
        snapshot = f"（{head}，身体{_body_phrase(body)}{_intent_phrase(body)}）"
        return snapshot[:_MAX_CHARS]
    except Exception:
        return ""


def append_to_prompt(prompt: str, owner: Any, user: dict[str, Any]) -> str:
    """组装点便捷入口：读快照并按既有提示块风格拼到 prompt 末尾。

    任何失败（含 owner 无 data_dir）原样返回 prompt，绝不影响主链路。
    """
    try:
        data_dir = str(getattr(owner, "data_dir", "") or "")
        info = user if isinstance(user, dict) else {}
        session = str(info.get("user_id") or info.get("id") or "")
        prompt = str(prompt or "")
        snapshot = build_snapshot(data_dir, session, _time.time())
        if snapshot and "存在层快照" not in prompt:
            prompt = (
                f"{prompt.rstrip()}\n\n"
                "【存在层快照】\n"
                f"{snapshot}\n"
                "这是她此刻真实的所在与身体状态，只作开口背景自然融入，不要照读或当作要谈的话题。"
            )
        trigger = _read_mood_triggers(data_dir, _time.time())
        if trigger and "情境线索" not in prompt:
            prompt = (
                f"{prompt.rstrip()}\n"
                f"{trigger}\n"
                "（情境线索由外部编排层给出，是否提起、怎么说由你自己决定。）"
            )
        return prompt
    except Exception:
        return prompt


def _read_mood_triggers(data_dir: str, now: float) -> str:
    """心绪编排触发（0.27.0 并入存在层后：读 vb 的 plugin_data/mood/triggers.json；
    旧 astrbot_plugin_mood_orchestrator 路径回退兼容）。过期过滤 + 前 3 条拼段；任何缺失 → 空串。"""
    import os as _os
    paths = [
        _os.path.normpath(_os.path.join(str(data_dir), "..", "astrbot_plugin_virtual_body", "mood", "triggers.json")),
        _os.path.normpath(_os.path.join(str(data_dir), "..", "astrbot_plugin_mood_orchestrator", "triggers.json")),
    ]
    data = None
    for path in paths:
        data = _load_json_file(path)
        if isinstance(data, dict):
            break
    if not isinstance(data, dict):
        return ""
    items = [t for t in (data.get("triggers") or [])
             if isinstance(t, dict) and isinstance(t.get("expires_at"), (int, float))
             and float(t["expires_at"]) > now]
    if not items:
        return ""
    items.sort(key=lambda t: (int(t.get("priority") or 3), -float(t.get("created_at") or 0)))
    hints = [str(t.get("template_hint") or t.get("reason") or "").strip() for t in items[:3]]
    text = "；".join(h for h in hints if h)
    return f"【情境触发】{text}"[:200] if text else ""
