"""Pure timing policy for existing companion scheduling; no I/O or model calls.

Probabilities apply once per sampling interval to an empty candidate queue.
They are opportunities to queue a thought, never permission to bypass the
plugin's existing privacy, rest, persona or delivery checks.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        result = default
    if not math.isfinite(result):
        result = default
    return max(minimum, result)


def sampling_bucket(now: float, minutes: int = 10) -> int:
    width = max(1.0, _number(minutes, 10.0)) * 60.0
    return int(_number(now, 0.0) // width)


def hard_limit_reason(
    *, now: float, last_sent: float, sent_today: int, daily_limit: int,
    min_interval_minutes: float, recent_activity_at: float,
    recent_chat_minutes: float,
) -> str:
    """Shared send limits, including stricter user settings supplied by caller."""
    check_now = _number(now, 0.0)
    daily = int(_number(daily_limit, 0.0))
    if daily <= 0:
        return "每日主动上限为 0，主动生成已停止"
    if int(_number(sent_today, 0.0)) >= daily:
        return "已达陪伴每日上限"
    sent_at = _number(last_sent, 0.0)
    interval = _number(min_interval_minutes, 45.0) * 60.0
    if sent_at > 0 and check_now - sent_at < interval:
        return "陪伴发送间隔不足"
    activity_at = _number(recent_activity_at, 0.0)
    idle = _number(recent_chat_minutes, 20.0) * 60.0
    if activity_at > 0 and check_now - activity_at < idle:
        return "刚聊完，陪伴主动先留出安静时间"
    return ""


def build_frequency_profile(
    *, now: float, last_activity_at: float, last_sent: float, sent_today: int,
    daily_limit: int, min_interval_minutes: float = 45,
    recent_chat_minutes: float = 20, sampling_minutes: int = 10,
    ignored_streak: int = 0, is_friend: bool = False,
    night_mode: str = "quiet_companion", local_hour: int = 12,
) -> dict[str, Any]:
    check_now = _number(now, 0.0)
    activity_at = _number(last_activity_at, 0.0)
    sent_at = _number(last_sent, 0.0)
    interval = _number(min_interval_minutes, 45.0)
    quiet = _number(recent_chat_minutes, 20.0)
    sample = max(1, int(_number(sampling_minutes, 10.0)))
    reason = hard_limit_reason(
        now=check_now, last_sent=sent_at, sent_today=sent_today,
        daily_limit=daily_limit, min_interval_minutes=interval,
        recent_activity_at=activity_at, recent_chat_minutes=quiet,
    )
    silent_minutes = max(0.0, check_now - activity_at) / 60 if activity_at > 0 else None
    is_night = 0 <= int(_number(local_hour, 12.0)) < 2 or int(_number(local_hour, 12.0)) >= 23
    result: dict[str, Any] = {
        "allowed": False, "probability": 0.0, "delay_hours": (0.5, 1.0),
        "stage": "blocked", "block_reason": reason,
        "silent_minutes": silent_minutes, "is_night": is_night,
        "sampling_bucket": sampling_bucket(check_now, sample),
        "sampling_minutes": sample,
        "retry_at": max(check_now, sent_at + interval * 60 if sent_at > 0 else 0,
                        activity_at + quiet * 60 if activity_at > 0 else 0),
    }
    if reason:
        return result
    if is_friend:
        result["block_reason"] = "朋友沿用原有主动节奏"
        return result
    if silent_minutes is None:
        result["block_reason"] = "尚无真实私聊活动记录"
        return result
    if is_night and str(night_mode).lower() in {"off", "disabled", "none"}:
        result["block_reason"] = "夜间特殊陪伴已关闭"
        return result
    if silent_minutes < max(45.0, quiet):
        stage, probability, delay = "recently_active", 0.08, (0.5, 0.9)
    elif silent_minutes < 120:
        stage, probability, delay = "light_companion", 0.22, (0.25, 0.65)
    elif silent_minutes < 360:
        stage, probability, delay = "long_silence", 0.42, (0.15, 0.45)
    else:
        stage, probability, delay = "extended_silence", 0.62, (0.1, 0.35)
    ignored = int(_number(ignored_streak, 0.0))
    if ignored >= 1:
        probability *= 0.5 if ignored == 1 else 0.18
        delay = (max(delay[0], 0.75 if ignored == 1 else 1.5),
                 max(delay[1], 1.5 if ignored == 1 else 4.0))
        stage = "unanswered_backoff"
    remaining = max(0, int(_number(daily_limit, 0.0)) - int(_number(sent_today, 0.0)))
    if remaining <= 2:
        probability *= 0.65
    if is_night:
        probability *= 0.7
        delay = (max(delay[0], 0.35), max(delay[1], 0.75))
    result.update(allowed=True, probability=round(min(0.75, probability), 6),
                  delay_hours=delay, stage=stage, block_reason="")
    return result
