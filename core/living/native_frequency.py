"""TLS-owned deterministic companion cadence decisions.

The public functions preserve the existing companion policy contract. Hosts
provide effective limits and observed counters; this module owns neither their
storage nor random sampling, quiet windows, media preparation or delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

__all__ = ["sampling_bucket", "hard_limit_reason", "build_frequency_profile"]

DAILY_DISABLED = "每日主动上限为 0，主动生成已停止"
DAILY_EXHAUSTED = "已达陪伴每日上限"
INTERVAL_PENDING = "陪伴发送间隔不足"
RECENT_ACTIVITY = "刚聊完，陪伴主动先留出安静时间"
FRIEND_CADENCE = "朋友沿用原有主动节奏"
ACTIVITY_UNKNOWN = "尚无真实私聊活动记录"
NIGHT_DISABLED = "夜间特殊陪伴已关闭"


def _nonnegative(value: Any, fallback: float) -> float:
    """Apply the established finite-number fallback and nonnegative floor."""
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        converted = fallback
    return max(0.0, converted if math.isfinite(converted) else fallback)


def _count(value: Any) -> int:
    return int(_nonnegative(value, 0.0))


@dataclass(frozen=True, slots=True)
class _Timing:
    now: float
    activity: float
    sent: float
    interval_minutes: float
    recent_minutes: float
    sample_minutes: int

    @classmethod
    def normalize(cls, now: Any, activity: Any, sent: Any, interval: Any,
                  recent: Any, sample: Any) -> _Timing:
        return cls(
            _nonnegative(now, 0.0), _nonnegative(activity, 0.0),
            _nonnegative(sent, 0.0), _nonnegative(interval, 45.0),
            _nonnegative(recent, 20.0), max(1, int(_nonnegative(sample, 10.0))),
        )

    @property
    def silence_minutes(self) -> float | None:
        return max(0.0, self.now - self.activity) / 60 if self.activity > 0 else None

    @property
    def retry_at(self) -> float:
        return max(
            self.now,
            self.sent + self.interval_minutes * 60 if self.sent > 0 else 0,
            self.activity + self.recent_minutes * 60 if self.activity > 0 else 0,
        )


@dataclass(frozen=True, slots=True)
class _Stage:
    name: str
    probability: float
    delay_hours: tuple[float, float]


_STAGES = (
    _Stage("recently_active", 0.08, (0.5, 0.9)),
    _Stage("light_companion", 0.22, (0.25, 0.65)),
    _Stage("long_silence", 0.42, (0.15, 0.45)),
    _Stage("extended_silence", 0.62, (0.1, 0.35)),
)


def _stage_for(silence: float, recent: float) -> _Stage:
    # These thresholds deliberately retain their evaluation order when a host
    # supplies a recent-activity window longer than either later stage.
    for threshold, stage in zip((max(45.0, recent), 120.0, 360.0), _STAGES):
        if silence < threshold:
            return stage
    return _STAGES[-1]


def sampling_bucket(now: float, minutes: int = 10) -> int:
    width_seconds = max(1.0, _nonnegative(minutes, 10.0)) * 60.0
    return int(_nonnegative(now, 0.0) // width_seconds)


def hard_limit_reason(
    *, now: float, last_sent: float, sent_today: int, daily_limit: int,
    min_interval_minutes: float, recent_activity_at: float,
    recent_chat_minutes: float,
) -> str:
    """Return the first hard limit; an empty string permits further checks."""
    checked_at = _nonnegative(now, 0.0)
    limit = _count(daily_limit)
    if limit <= 0:
        return DAILY_DISABLED
    if _count(sent_today) >= limit:
        return DAILY_EXHAUSTED
    sent_at = _nonnegative(last_sent, 0.0)
    interval_seconds = _nonnegative(min_interval_minutes, 45.0) * 60.0
    if sent_at > 0 and checked_at - sent_at < interval_seconds:
        return INTERVAL_PENDING
    active_at = _nonnegative(recent_activity_at, 0.0)
    recent_seconds = _nonnegative(recent_chat_minutes, 20.0) * 60.0
    if active_at > 0 and checked_at - active_at < recent_seconds:
        return RECENT_ACTIVITY
    return ""


def _compatibility_profile(timing: _Timing, reason: str, night: bool) -> dict[str, Any]:
    """Keep the external dictionary contract separate from normalized inputs."""
    return {
        "allowed": False, "probability": 0.0, "delay_hours": (0.5, 1.0),
        "stage": "blocked", "block_reason": reason,
        "silent_minutes": timing.silence_minutes, "is_night": night,
        "sampling_bucket": sampling_bucket(timing.now, timing.sample_minutes),
        "sampling_minutes": timing.sample_minutes, "retry_at": timing.retry_at,
    }


def build_frequency_profile(
    *, now: float, last_activity_at: float, last_sent: float, sent_today: int,
    daily_limit: int, min_interval_minutes: float = 45,
    recent_chat_minutes: float = 20, sampling_minutes: int = 10,
    ignored_streak: int = 0, is_friend: bool = False,
    night_mode: str = "quiet_companion", local_hour: int = 12,
) -> dict[str, Any]:
    """Describe an opportunity; never sample, queue, persist or send it."""
    timing = _Timing.normalize(now, last_activity_at, last_sent, min_interval_minutes,
                               recent_chat_minutes, sampling_minutes)
    reason = hard_limit_reason(
        now=timing.now, last_sent=timing.sent, sent_today=sent_today,
        daily_limit=daily_limit, min_interval_minutes=timing.interval_minutes,
        recent_activity_at=timing.activity, recent_chat_minutes=timing.recent_minutes,
    )
    hour = int(_nonnegative(local_hour, 12.0))
    night = 0 <= hour < 2 or hour >= 23
    profile = _compatibility_profile(timing, reason, night)
    if reason:
        return profile
    if is_friend:
        profile["block_reason"] = FRIEND_CADENCE
        return profile
    silence = timing.silence_minutes
    if silence is None:
        profile["block_reason"] = ACTIVITY_UNKNOWN
        return profile
    if night and str(night_mode).lower() in {"off", "disabled", "none"}:
        profile["block_reason"] = NIGHT_DISABLED
        return profile

    stage = _stage_for(silence, timing.recent_minutes)
    name, probability, delay = stage.name, stage.probability, stage.delay_hours
    ignored = _count(ignored_streak)
    if ignored >= 1:
        # Multiplication order is part of the compatibility contract: ignored,
        # then remaining daily allowance, then night; round only at the end.
        probability *= 0.5 if ignored == 1 else 0.18
        floors = (0.75, 1.5) if ignored == 1 else (1.5, 4.0)
        delay = (max(delay[0], floors[0]), max(delay[1], floors[1]))
        name = "unanswered_backoff"
    remaining = max(0, _count(daily_limit) - _count(sent_today))
    if remaining <= 2:
        probability *= 0.65
    if night:
        probability *= 0.7
        delay = (max(delay[0], 0.35), max(delay[1], 0.75))
    profile.update(
        allowed=True, probability=round(min(0.75, probability), 6),
        delay_hours=delay, stage=name, block_reason="",
    )
    return profile
