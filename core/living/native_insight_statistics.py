"""TLS-owned dialogue statistics ported from the audited Insight algorithms.
No legacy plugin imports, database access, scheduler or model call.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

_SAMPLE_CONV = 20

_MAX_OUTPUT = 500

LOCAL_TZ = timezone(timedelta(hours=8))

_STOP_CHARS = "的了吗呢吧啊呀哦嘛我你他她它是在有和人一都也个这那就很到说会着与但而被让把没还"

_STOP_RE = re.compile("[" + _STOP_CHARS + "]")

_ZH_RE = re.compile(r"[\u4e00-\u9fff]+")

_EN_RE = re.compile(r"[A-Za-z]{2,}")

_DATE_IN_NAME_RE = re.compile(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})")

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
)

def _parse_ts(v) -> "datetime | None":
    """防御性解析时间戳: 支持 'YYYY-MM-DD HH:MM:SS' / isoformat / 数字秒(毫秒)。"""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(v if v < 1e11 else v / 1000, LOCAL_TZ).replace(tzinfo=None)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(v).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        pass
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def _conv_local_time(value):
    """Framework conversation strings without an offset are stored as UTC."""
    dt = _parse_ts(value)
    if dt is None or isinstance(value, (int, float)):
        return dt
    try:
        raw = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if raw.tzinfo is not None:
            return dt
    except ValueError:
        pass
    return dt + timedelta(hours=8)

def _msg_text(content) -> str:
    """提取消息文本: content 可能是 str, 也可能是消息链 list[{text}|{data:{text}}|str]。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for seg in content:
            if isinstance(seg, str):
                parts.append(seg)
            elif isinstance(seg, dict):
                t = seg.get("text")
                if isinstance(t, str):
                    parts.append(t)
                else:
                    data = seg.get("data")
                    if isinstance(data, dict) and isinstance(data.get("text"), str):
                        parts.append(data["text"])
        return "".join(parts)
    return ""

def _load_content(raw):
    """会话 content 字段: 可能是 JSON 字符串, 也可能已被上层反序列化为 list。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []

def _extract_topics(texts) -> Counter:
    """高频话题词: 中文按停用字切分(2-4字段整词, >4字滑窗), 英文单词(>=2字母)。"""
    cnt: Counter = Counter()
    for t in texts:
        if not t:
            continue
        for seg in _ZH_RE.findall(t):
            for sub in _STOP_RE.split(seg):
                n = len(sub)
                if 2 <= n <= 4:
                    cnt[sub] += 1
                elif n > 4:
                    for i in range(n - 1):
                        cnt[sub[i : i + 2]] += 1
        for w in _EN_RE.findall(t):
            cnt[w.lower()] += 1
    return cnt

def _clip(text, limit=30) -> str:
    s = str(text).strip().replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"

def _bounded(text: str) -> str:
    """输出软限制: 超长时在行边界截断。"""
    if len(text) <= _MAX_OUTPUT + 100:
        return text
    cut = text[:_MAX_OUTPUT]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > 0 else cut).rstrip() + "\n…"

def _analyze_conv_rows(rows, days: int) -> str:
    """纯CPU统计(在 to_thread 中执行)。"""
    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    cutoff = now - timedelta(days=days)
    sample_n = 0

    user_n = bot_n = 0
    hour_hist = [0] * 24
    user_texts = []

    for row in rows:
        conv_time = _conv_local_time(row.get("updated_at"))
        row_in_window = False
        for msg in _load_content(row.get("content")):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            text = _msg_text(msg.get("content"))
            ts = None
            for key in ("timestamp", "time", "created_at"):
                ts = _parse_ts(msg.get(key))
                if ts is not None:
                    break
            if ts is None:
                ts = conv_time  # 无消息级时间戳, 用会话 updated_at 近似
            if ts is None or not cutoff <= ts <= now:
                continue
            row_in_window = True
            if role == "user":
                user_n += 1
                if len(text) < 2000:
                    user_texts.append(text)
            elif role == "assistant":
                bot_n += 1
            if ts is not None:
                hour_hist[ts.hour] += 1
        sample_n += int(row_in_window)

    # 活跃时段: 2小时桶 top3
    buckets = Counter()
    for h, c in enumerate(hour_hist):
        if c > 0:
            buckets[h // 2 * 2] += c
    top_buckets = buckets.most_common(3)

    lines = ["💬 最近对话模式分析", ""]
    lines.append(f"消息量: 用户{user_n}条 / 机器人{bot_n}条 ({sample_n}个会话样本, 最近{days}天)")
    if top_buckets:
        segs = [
            f"{h}-{h + 2}点" + ("(高峰)" if i == 0 else "")
            for i, (h, _) in enumerate(top_buckets)
        ]
        lines.append("活跃时段: " + ", ".join(segs))
    else:
        lines.append("活跃时段: 无时间数据")
    words = _extract_topics(user_texts).most_common(8)
    if words:
        lines.append("高频话题词: " + ", ".join(f"{w}({c})" for w, c in words))
    else:
        lines.append("高频话题词: 无用户消息样本")
    if user_n == 0 and bot_n == 0:
        return "💬 最近对话模式分析\n\n最近没有可分析的对话数据。"
    return "\n".join(lines)

__all__ = ["chat_pattern_impl", "memory_insight_impl"]
