"""时间工具函数模块。"""

from __future__ import annotations

import zoneinfo
from datetime import datetime


def is_quiet_time(quiet_hours_str: str, tz: zoneinfo.ZoneInfo | None, *, now: float | None = None) -> bool:
    """检查免打扰区间并集；now 可传 Host 的 epoch 秒，旧调用仍取当前时间。"""
    try:
        if not isinstance(quiet_hours_str, str) or len(quiet_hours_str) > 143:
            return False
        segments = quiet_hours_str.split(",")
        if len(segments) > 24:
            return False
        windows = []
        for segment in segments:
            start_str, end_str = segment.split("-")
            start_hour, end_hour = int(start_str), int(end_str)
            if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
                return False
            windows.append((start_hour, end_hour))
        # 未提供时区时沿用系统本地时间；不读取另一套时钟。
        current = (datetime.now(tz) if tz else datetime.now()) if now is None else datetime.fromtimestamp(now, tz)
        return any(start <= current.hour < end if start <= end
                   else current.hour >= start or current.hour < end
                   for start, end in windows)
    except (ValueError, TypeError, OverflowError, OSError):
        # 配置非法时按“非免打扰”处理，避免误阻断主动消息
        return False
