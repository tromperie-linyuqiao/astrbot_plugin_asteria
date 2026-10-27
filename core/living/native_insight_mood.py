"""TLS native insight mood scoring and calibration (ported business)

三类信号 → 加权合成 → 按日聚合 → LLM校准:
- 文本信号 _text_signal: 情绪词典 + 语气词 + 标点强度, 覆盖率阻尼(单条命中不刷满)
- 行为信号 _behavior_signal: 消息长度/深夜占比/消息量 vs 前7天基线
- 生活信号 _life_signal: dynamic_life_state 当日时间线关键词(无数据返回None, 触发权重重分配)

设计依据: 词典法是冷启动底线(零成本全覆盖), LLM校准是增量精修(低置信度的日优先)。
本模块独立于插件骨架(main.py/adapters.py), 由 main.py 注入依赖调用:
- mood_timeline_impl(query_db_fn, db_path, days): 情绪时间线报告(≤400字)
- llm_calibrate_daily(date_str, sample_msgs, text_score, provider_fn): 单日LLM校准
- run_daily_calibration(query_db_fn, provider_fn, plugin_data_dir, lookback): 定时校准钩子
  (每日校准成本: ~lookback天×5条×30token)
"""

import asyncio
import inspect
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    from astrbot.api import logger
except Exception:  # 独立编译/测试时无astrbot环境
    import logging

    logger = logging.getLogger("insight_center")

# 本地时区(+08:00), 与 gather/analysis 保持一致
LOCAL_TZ = timezone(timedelta(hours=8))

_MAX_OUTPUT = 400           # 报告软上限(字)
_SAMPLE_CONV = 60           # 采样会话数(窗口=days+7天, 需要比analysis多拿)
_MAX_ROWS = 14              # 时间线最多渲染天数
_CAL_DIR = "insight_center"  # 校准文件所在子目录(plugin_data/下)
CALIBRATION_FILE = "mood_calibration.json"

# ---------------------------------------------------------------------------
# 情绪词典(模块级常量)
# ---------------------------------------------------------------------------

# 正面词(每个+1)
POSITIVE_WORDS = ["哈哈", "嘻嘻", "开心", "高兴", "快乐", "太好了", "绝了", "牛", "厉害", "笑死",
                  "好玩", "有趣", "喜欢", "满意", "顺利", "搞定", "成了", "舒服", "爽", "赞",
                  "爱了", "泪目", "感动", "幸福", "期待", "棒", "好耶", "nice", "great", "love"]
# 负面词(每个-1)
NEGATIVE_WORDS = ["烦", "累", "疲惫", "焦虑", "崩了", "唉", "难过", "伤心", "生气", "气死",
                  "失望", "无语", "难受", "压抑", "郁闷", "emo", "想哭", "绝望", "糟糕", "倒霉",
                  "头疼", "心累", "烦死", "恶心", "讨厌", "抱歉", "对不起", "sad", "bad", "awful"]
# 语气词修正(每个额外±0.5)
POSITIVE_TONE = ["嘿嘿", "哇", "耶", "嘿", "噢耶"]
NEGATIVE_TONE = ["emm", "额", "唉声", "唉气", "呵呵"]

# 生活时间线规则: (关键词组, 分值, 特征标签)
_LIFE_RULES = (
    (("熬夜", "凌晨", "很晚", "通宵"), -0.4, "熬夜"),
    (("晚起", "睡到下午"), -0.2, "晚起"),
    (("外出", "出门", "聚会", "旅行", "散步"), 0.3, "外出活动"),
    (("运动", "健身", "跑步"), 0.3, "运动"),
)

# 三类信号权重(缺失信号按比例重分配, 如无生活信号→文本0.625/行为0.375)
_SIGNAL_WEIGHTS = {"text": 0.5, "behav": 0.3, "life": 0.2}

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
)


# ---------------------------------------------------------------------------
# 通用辅助(与gather/analysis同款, 保持模块独立)
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _clamp(v: float, lo: float, hi: float) -> float:
    """clamp到[lo, hi]。"""
    return max(lo, min(hi, v))


def _plugin_data_dir() -> str:
    """plugin_data基准路径: 优先官方API, 回退容器内默认路径。"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
        return get_astrbot_plugin_data_path()
    except Exception:
        return "/AstrBot/data/plugin_data"


def _parse_ts(v) -> "datetime | None":
    """防御性解析时间戳: 支持 'YYYY-MM-DD HH:MM:SS' / isoformat / 数字秒(毫秒)。"""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(v if v < 1e11 else v / 1000)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("Z", "")
    s = s.split(".")[0].split("+")[0].strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _msg_text(content) -> str:
    """提取消息文本: content可能是str, 也可能是消息链 list[{text}|{data:{text}}|str]。"""
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


def _load_content(raw) -> list:
    """会话content字段: JSON字符串或已被上层反序列化的list。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _load_json(path):
    try:
        if os.path.islink(path) or os.path.getsize(path) > 2 * 1024 * 1024:
            return None
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None



def _bounded(text: str) -> str:
    """输出软限制: 超长时在行边界截断。"""
    if len(text) <= _MAX_OUTPUT + 80:
        return text
    cut = text[:_MAX_OUTPUT]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > 0 else cut).rstrip() + "\n…"


# ---------------------------------------------------------------------------
# DB读取(行形状自适应 + 本地sqlite回退, 同gather.py模式)
# ---------------------------------------------------------------------------

def _row_dict(row, keys) -> dict:
    """行形状自适应: dict / sqlite3.Row / tuple。"""
    if isinstance(row, dict):
        return row
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if isinstance(row, (tuple, list)):
        return dict(zip(keys, row))
    return {}


async def _query_rows(query_db_fn, db_path: str, sql: str, params: tuple) -> list:
    if not callable(query_db_fn):
        raise RuntimeError('explicit_readonly_source_required')
    result = query_db_fn(sql, params)
    return await result if inspect.isawaitable(result) else result



def _text_signal(messages: list) -> tuple:
    """文本情绪信号 → (分数[-1,+1], 消息样本数)。

    自洽归一化:
    - 无任何情绪线索 → 0.0
    - 主分 = 正负词方向 × 强度阻尼(词典覆盖×命中密度, 单条稀疏命中不刷满)
    - 语气词/标点修正随消息量摊薄后叠加; 纯语气词单独成弱信号(×0.4)
    - 最终clamp到[-1,1]
    """
    if not messages:
        return 0.0, 0
    n = len(messages)
    pos = neg = 0            # 情绪词命中数
    tone = 0.0               # 语气/标点修正(累计)
    word_msgs = 0            # 命中情绪词典(非语气词)的消息数
    for msg in messages:
        m_pos = sum(1 for w in POSITIVE_WORDS if w in msg)
        m_neg = sum(1 for w in NEGATIVE_WORDS if w in msg)
        m_tone = sum(0.5 for w in POSITIVE_TONE if w in msg) - sum(0.5 for w in NEGATIVE_TONE if w in msg)
        # 标点强度: 强叹号只放大该条词表方向; 省略号轻微消极
        if "！！！" in msg or "!!!" in msg:
            m_tone += 0.3 if m_pos > m_neg else (-0.3 if m_neg > m_pos else 0.0)
        if "……" in msg or "..." in msg:
            m_tone -= 0.1
        pos += m_pos
        neg += m_neg
        tone += m_tone
        if m_pos or m_neg:
            word_msgs += 1
    tone_avg = tone / n
    if pos + neg == 0:
        # 纯语气词也算信号(弱): "emm"×N → 轻微负分
        score = _clamp(tone_avg, -1.0, 1.0) * 0.4 if tone else 0.0
        return _clamp(score, -1.0, 1.0), n
    raw = (pos - neg) / (pos + neg)                    # 方向[-1,1]
    word_cov = word_msgs / n                           # 词典覆盖率(方向可信度)
    density = min(1.0, (pos + neg) / n)                # 命中密度(强度)
    base = raw * min(1.0, 0.3 + 0.5 * word_cov + 0.2 * density)  # 阻尼: 稀疏命中不刷满
    score = 0.85 * base + 0.3 * _clamp(tone_avg, -0.5, 0.5)
    return _clamp(score, -1.0, 1.0), n


# ---------------------------------------------------------------------------
# 信号2: 行为信号
# ---------------------------------------------------------------------------

def _behavior_signal(day_msgs: list, baseline_len: float, baseline_freq: float) -> tuple:
    """行为模式信号 → (分数[-1,1], 特征标签列表)。

    - 日均消息长度 vs 基线: 骤降≥40% → -0.3~-0.5(低能量); 骤增≥80% → +0.1(倾诉欲)
    - 23点后(含凌晨0-4点)消息占比 ≥30% → -0.2(作息紊乱)
    - 日消息量 vs 基线: 骤降≥50% → -0.2
    基线 = 分析窗口前7天均值; 无基线时对应检查跳过。
    """
    if not day_msgs:
        return 0.0, []
    score = 0.0
    reasons = []
    n = len(day_msgs)
    avg_len = sum(len(t) for t, _ in day_msgs) / n
    if baseline_len > 0:
        ratio = avg_len / baseline_len
        if ratio <= 0.6:
            score -= min(0.5, 0.3 + (0.6 - ratio) * 0.5)  # -0.3 ~ -0.5
            reasons.append("消息变短")
        elif ratio >= 1.8:
            score += 0.1
            reasons.append("倾诉欲增强")
    timed = [ts for _, ts in day_msgs if ts is not None]
    if timed:
        late = sum(1 for ts in timed if ts.hour >= 23 or ts.hour <= 4)
        if late / len(timed) >= 0.3:
            score -= 0.2
            reasons.append("深夜活跃")
    if baseline_freq > 0 and n / baseline_freq <= 0.5:
        score -= 0.2
        reasons.append("消息量骤降")
    return _clamp(score, -1.0, 1.0), reasons


# ---------------------------------------------------------------------------
# 信号3: 生活信号
# ---------------------------------------------------------------------------

def _load_life_texts(max_days: int = 14) -> dict:
    """dynamic_life_state时间线 → {date_str: 文本dump}。

    发现模式同gather.py: 最近max_days修改过的JSON(下探1层子目录),
    文件名日期优先, 回退mtime日期, 同日多文件合并。
    """
    def _sync() -> dict:
        ls_dir = os.path.join(_plugin_data_dir(), "astrbot_plugin_dynamic_life_state")
        if not os.path.isdir(ls_dir):
            return {}
        cutoff_ts = (_now() - timedelta(days=max_days)).timestamp()
        files = []
        for root, dirs, names in os.walk(ls_dir):
            if root.count(os.sep) - ls_dir.count(os.sep) > 1:
                dirs[:] = []
                continue
            for fn in names:
                if not fn.endswith(".json"):
                    continue
                p = os.path.join(root, fn)
                try:
                    if os.path.getmtime(p) >= cutoff_ts:
                        files.append(p)
                except OSError:
                    continue
        texts = {}
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for p in files[:10]:
            data = _load_json(p)
            if data is None:
                continue
            m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", os.path.basename(p))
            if m:
                day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            else:
                try:
                    day = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
                except OSError:
                    continue
            dump = json.dumps(data, ensure_ascii=False)
            texts[day] = (texts[day] + " " + dump) if day in texts else dump
        return texts

    return _sync()


def _life_scan(text: str) -> tuple:
    """生活文本 → (信号分或None, 特征标签列表); 空文本返回(None, [])。"""
    if not text:
        return None, []
    score = 0.0
    labels = []
    for kws, delta, label in _LIFE_RULES:
        if any(k in text for k in kws):
            score += delta
            labels.append(label)
    return _clamp(score, -1.0, 1.0), labels


def _life_signal(day_date: str, life_texts=None):
    """生活信号: 当日生活时间线关键词 → 分数[-1,1]。

    无该日数据返回None(区别于0分, 用于权重重分配)。
    """
    texts = life_texts if life_texts is not None else _load_life_texts()
    score, _labels = _life_scan(texts.get(day_date, ""))
    return score


# ---------------------------------------------------------------------------
# 加权合成
# ---------------------------------------------------------------------------

def _compose_day(text_s, behav_s, life_s, n_msgs: int = 0) -> tuple:
    """加权合成 → (日分数[-1,1], 置信度0-1)。

    权重: 文本0.5/行为0.3/生活0.2; 信号为None时权重按比例重分配
    (如无生活信号 → 文本0.625/行为0.375)。
    置信度: 全覆盖+样本充足=0.8; 只有1类信号×0.4; 文本样本<5条×0.5。
    """
    sigs = {"text": text_s, "behav": behav_s, "life": life_s}
    avail = {k: v for k, v in sigs.items() if v is not None}
    if not avail:
        return 0.0, 0.0
    wsum = sum(_SIGNAL_WEIGHTS[k] for k in avail)
    score = sum(_SIGNAL_WEIGHTS[k] / wsum * avail[k] for k in avail)
    conf = {1: 0.5, 2: 0.65, 3: 0.8}[len(avail)]
    if len(avail) == 1:
        conf *= 0.4
    if "text" in avail and n_msgs < 5:
        conf *= 0.5
    return _clamp(score, -1.0, 1.0), _clamp(conf, 0.0, 1.0)


def _conf_label(conf: float) -> str:
    """置信度数值 → 高/中/低标签。"""
    return "高" if conf >= 0.7 else ("中" if conf >= 0.4 else "低")


# ---------------------------------------------------------------------------
# 按日分组与逐日评估
# ---------------------------------------------------------------------------

def _conv_local_time(updated_at_raw):
    """会话updated_at: UTC字符串→本地(+8h); epoch→本地; 失败返回None。"""
    if isinstance(updated_at_raw, (int, float)) and not isinstance(updated_at_raw, bool):
        return _parse_ts(updated_at_raw)
    dt = _parse_ts(updated_at_raw)
    return dt + timedelta(hours=8) if dt is not None else None


def _group_by_day(rows: list) -> dict:
    """rows → {date_str: [(text, ts), ...]}, 只保留user消息。

    时间戳: 消息级timestamp/time/created_at优先, 无则用会话updated_at近似。
    """
    by_day = {}
    for row in rows:
        r = _row_dict(row, ("content", "updated_at"))
        conv_time = _conv_local_time(r.get("updated_at"))
        for msg in _load_content(r.get("content")):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            text = _msg_text(msg.get("content"))
            if not text:
                continue
            ts = None
            for key in ("timestamp", "time", "created_at"):
                ts = _parse_ts(msg.get(key))
                if ts is not None:
                    break
            if ts is None:
                ts = conv_time
            if ts is None:
                continue
            by_day.setdefault(ts.strftime("%Y-%m-%d"), []).append((text, ts))
    return by_day


def _eval_days(by_day: dict, life_texts: dict, cal: dict, days: int) -> list:
    """窗口内逐日评估(纯CPU, 在to_thread中执行)。

    → [ {date, score, conf, n, behav_reasons, life_labels} ... ](旧→新, 只含有消息的日)
    行为基线 = 窗口前7天(非窗口内)的消息长度/消息量均值。
    LLM校准分(cal中已有final)直接替代词典分, 置信度标高(0.9)。
    """
    today = _now().date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]  # 旧→新
    pre_start = window[0] - timedelta(days=7)
    pre = [t for d, msgs in by_day.items()
           if pre_start <= datetime.strptime(d, "%Y-%m-%d").date() < window[0]
           for t, _ in msgs]
    baseline_len = (sum(len(t) for t in pre) / len(pre)) if pre else 0.0
    baseline_freq = len(pre) / 7.0 if pre else 0.0

    results = []
    for d in window:
        ds = d.strftime("%Y-%m-%d")
        msgs = by_day.get(ds, [])
        if not msgs:
            continue
        texts = [t for t, _ in msgs]
        text_s, n = _text_signal(texts)
        behav_s, behav_reasons = _behavior_signal(msgs, baseline_len, baseline_freq)
        life_s, life_labels = _life_scan(life_texts.get(ds, ""))
        score, conf = _compose_day(text_s, behav_s, life_s, n)
        c = cal.get(ds)
        if isinstance(c, dict) and isinstance(c.get("final"), (int, float)):
            score = float(c["final"])  # LLM校准分替代词典分
            conf = 0.9                 # 置信度标"高"
        results.append({
            "date": ds, "score": score, "conf": conf, "n": n,
            "behav_reasons": behav_reasons, "life_labels": life_labels,
        })
    return results


def _pick_samples(texts: list, limit: int = 5) -> list:
    """代表性消息: 情绪词命中数优先, 再按长度, 最多limit条(控制校准token成本)。"""
    def _weight(t: str) -> tuple:
        hits = sum(1 for w in POSITIVE_WORDS + NEGATIVE_WORDS if w in t)
        return (hits, len(t))

    return sorted(texts, key=_weight, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------

def _bar(score: float) -> str:
    """5格条形图: 分数-1~+1线性映射0~5格(0.5格/0.4分, 四舍五入)。"""
    filled = int(_clamp((score + 1.0) / 0.4 + 0.5, 0, 5))
    return "▓" * filled + "░" * (5 - filled)


def _render_timeline(results: list, days: int) -> str:
    """逐日行 + 突变/回升标记 + 趋势 + 低谷关联 + 免责脚注。"""
    shown = results[-_MAX_ROWS:]
    lines = [f"🎭 最近{days}天情绪时间线", ""]
    prev = None
    for r in shown:
        head = f'{r["date"][5:]} {_bar(r["score"])} {r["score"]:+.2f}'
        tag = ""
        if prev is not None:
            if prev["score"] < -0.3 and r["score"] >= prev["score"] + 0.3:
                tag = "回升"
            elif abs(r["score"] - prev["score"]) > 0.6:
                tag = "↓突变" if r["score"] < prev["score"] else "↑突变"
        if tag == "↓突变" and r["behav_reasons"]:
            lines.append(f'{head} {tag} ({"+".join(r["behav_reasons"][:2])})')
        elif tag:
            lines.append(f"{head} {tag}")
        else:
            lines.append(f'{head} (样本{r["n"]}条,置信{_conf_label(r["conf"])})')
        prev = r

    scores = [r["score"] for r in shown]
    avg = sum(scores) / len(scores)
    spread = max(scores) - min(scores)
    if avg > 0.15:
        trend = "整体偏正面"
    elif avg < -0.15:
        trend = "整体偏低迷"
    elif spread >= 0.6:
        trend = "波动明显"
    else:
        trend = "整体平稳"
    valleys = [r for r in shown if r["score"] < -0.3]
    if valleys:
        trend += f", {valleys[0]['date'][5:]}有明显低谷"
    lines.append(f"趋势: {trend}")

    if valleys:
        assoc = Counter()
        for r in valleys:
            assoc.update(set(r["life_labels"] + r["behav_reasons"]))
        top = ", ".join(f"{lab}({c}/{len(valleys)})" for lab, c in assoc.most_common(4))
        lines.append(f"低谷关联: {top}")

    overall = _conf_label(sum(r["conf"] for r in shown) / len(shown))
    lines.append(f"⚠ 基于词典+行为推断,置信度{overall},仅供参考")
    return _bounded("\n".join(lines))


# ---------------------------------------------------------------------------
# 核心入口1: 情绪时间线
# ---------------------------------------------------------------------------

async def mood_timeline_impl(query_db_fn=None, db_path: str = "/AstrBot/data/data_v4.db", days: int = 7) -> str:
    """情绪时间线: 三类信号加权 → 按日聚合 → 突变/低谷检测 → LLM校准分替换。"""
    try:
        days = max(1, min(int(days), 30))
        fetch_days = days + 7  # 多拿7天做行为基线
        cutoff = (
            (_now() - timedelta(days=fetch_days)).astimezone(timezone.utc).replace(tzinfo=None)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        sql = "SELECT content, updated_at FROM conversations WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT ?"
        rows = await _query_rows(query_db_fn, db_path, sql, (cutoff, _SAMPLE_CONV))
        if not rows:
            return "🎭 情绪时间线\n\n暂无对话数据(数据库不可用或 conversations 表为空)。"

        by_day, life_texts, cal = await asyncio.gather(
            asyncio.to_thread(_group_by_day, rows),
            asyncio.to_thread(_load_life_texts, fetch_days),
            asyncio.to_thread(_load_calibration, _plugin_data_dir()),
        )
        results = await asyncio.to_thread(_eval_days, by_day, life_texts, cal, days)
        if not results:
            return "🎭 情绪时间线\n\n最近无用户消息, 无法分析。"
        return await asyncio.to_thread(_render_timeline, results, days)
    except Exception as e:
        logger.warning(f"[mood] 时间线生成异常: {e}")
        return f"🎭 情绪时间线\n\n生成失败: {e}"


# ---------------------------------------------------------------------------
# LLM校准
# ---------------------------------------------------------------------------

async def llm_calibrate_daily(date_str: str, sample_msgs: list, text_score: float, provider_fn=None) -> dict:
    """LLM校准单日情绪分。

    sample_msgs: 该日代表性消息(最多5条); provider_fn: async fn(prompt)->str(默认None时跳过)。
    返回: {"date", "llm_score", "dict_score", "final", "calibrated_at"};
    偏差>0.5时 final=llm_score(采纳LLM), 否则 final=词典分(LLM只确认); 失败返回{}。
    """
    if not provider_fn or not sample_msgs:
        return {}
    prompt = (
        "分析以下用户消息的整体情绪基调,只输出一个-1到+1之间的小数(-1最消极,+1最积极,0中性)。\n"
        "不要输出其他任何内容。\n\n"
        f"消息(日期{date_str}):\n"
        + "\n".join(f"- {str(m)[:80]}" for m in list(sample_msgs)[:5])
    )
    try:
        resp = await provider_fn(prompt)
    except Exception as e:
        logger.debug(f"[mood] LLM校准调用失败({date_str}): {e}")
        return {}
    m = re.search(r"-?\d+(?:\.\d+)?", str(resp).strip())
    if not m:
        return {}
    try:
        llm_score = _clamp(float(m.group()), -1.0, 1.0)
    except ValueError:
        return {}
    dict_score = float(text_score or 0.0)
    final = llm_score if abs(llm_score - dict_score) > 0.5 else dict_score
    return {
        "date": date_str,
        "llm_score": llm_score,
        "dict_score": dict_score,
        "final": final,
        "calibrated_at": _now().timestamp(),
    }


# ---------------------------------------------------------------------------
# 校准结果持久化(plugin_data/insight_center/mood_calibration.json)
# ---------------------------------------------------------------------------

def _cal_path(plugin_data_dir) -> str:
    return os.path.join(plugin_data_dir or _plugin_data_dir(), _CAL_DIR, CALIBRATION_FILE)


def _load_calibration(plugin_data_dir) -> dict:
    """读校准缓存: {date_str: {llm_score, dict_score, final}}, 失败返回{}。"""
    data = _load_json(_cal_path(plugin_data_dir))
    return data if isinstance(data, dict) else {}


def _save_calibration(plugin_data_dir, data: dict) -> None:
    from ..state import _atomic_json
    path = _cal_path(plugin_data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_json(path, data)


# ---------------------------------------------------------------------------
# 核心入口2: 定时校准钩子(供main.py的定时任务调用)
# ---------------------------------------------------------------------------

async def run_daily_calibration(query_db_fn, provider_fn, plugin_data_dir=None, lookback: int = 3, guard=None) -> str:
    """校准最近lookback天中词典置信度<0.7的日子(已校准过的日跳过)。

    流程: 读最近lookback+7天消息 → 分日算词典分+置信度 → 选低置信度日
    → llm_calibrate_daily(每日最多5条样本) → 原子写盘。返回摘要文本。
    """
    try:
        if guard is not None: guard()
        if not provider_fn:
            return "[mood校准] 未注入LLM provider, 跳过"
        lookback = max(1, min(int(lookback), 7))
        base = plugin_data_dir or _plugin_data_dir()
        fetch_days = lookback + 7  # 基线窗口与时间线保持一致
        cutoff = (
            (_now() - timedelta(days=fetch_days)).astimezone(timezone.utc).replace(tzinfo=None)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        sql = "SELECT content, updated_at FROM conversations WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT 30"
        rows = await _query_rows(query_db_fn, "/AstrBot/data/data_v4.db", sql, (cutoff,))
        if not rows:
            return "[mood校准] 近期无对话数据, 跳过"

        by_day, life_texts, cal = await asyncio.gather(
            asyncio.to_thread(_group_by_day, rows),
            asyncio.to_thread(_load_life_texts, fetch_days),
            asyncio.to_thread(_load_calibration, base),
        )
        # _eval_days(lookback)窗口即最近lookback天; 只校准置信度<0.7且未校准过的日
        results = await asyncio.to_thread(_eval_days, by_day, life_texts, cal, lookback)
        targets = [r for r in results if r["conf"] < 0.7 and r["date"] not in cal]
        if not targets:
            return f"[mood校准] 最近{lookback}天词典置信度均≥0.7或已校准, 无需校准"

        done = []
        for r in targets:
            texts = [t for t, _ in by_day.get(r["date"], [])]
            samples = _pick_samples(texts, 5)
            if guard is not None: guard()
            res = await llm_calibrate_daily(r["date"], samples, r["score"], provider_fn)
            if not res:
                continue
            cal[r["date"]] = {
                "llm_score": res["llm_score"],
                "dict_score": res["dict_score"],
                "final": res["final"],
            }
            adopted = "采纳LLM" if abs(res["llm_score"] - res["dict_score"]) > 0.5 else "维持词典"
            done.append(f'{r["date"][5:]} {res["dict_score"]:+.2f}→{res["llm_score"]:+.2f}({adopted})')
        if not done:
            return "[mood校准] LLM未返回有效结果"
        if guard is not None: guard()
        await asyncio.to_thread(_save_calibration, base, cal)
        return f"[mood校准] 完成{len(done)}天: " + "; ".join(done)
    except Exception as e:
        logger.warning(f"[mood] 校准任务异常: {e}")
        return f"[mood校准] 失败: {e}"


__all__ = ["mood_timeline_impl", "llm_calibrate_daily", "run_daily_calibration"]
