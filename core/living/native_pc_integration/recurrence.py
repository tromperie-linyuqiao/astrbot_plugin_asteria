"""PC recurrence semantics: advancing a due date is an explicit completion, not an ACK."""
from __future__ import annotations
import calendar
from datetime import datetime, timedelta
import math
from ..native_important_dates import date_zone

REPEATS = frozenset(('daily', 'weekly', 'monthly', 'yearly'))


def advance_due(due_at, repeat, *, now, timezone='Asia/Shanghai', anchor_day=0, anchor_month=0):
    for value in (due_at, now):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 4102444800:
            raise ValueError('bounded absolute recurring time required')
    if repeat not in REPEATS or type(anchor_day) is not int or not 0 <= anchor_day <= 31 or type(anchor_month) is not int or not 0 <= anchor_month <= 12:
        raise ValueError('known recurrence and Gregorian anchors required')
    zone = date_zone(timezone)
    candidate, target = datetime.fromtimestamp(due_at, zone), datetime.fromtimestamp(now, zone)
    # Same 500-step ceiling as the original PC implementation; never silently
    # clear due_at when a very old definition cannot be caught up.
    for _ in range(500):
        if repeat == 'daily': candidate += timedelta(days=1)
        elif repeat == 'weekly': candidate += timedelta(days=7)
        elif repeat == 'monthly':
            year, month = candidate.year + (candidate.month == 12), candidate.month % 12 + 1
            candidate = candidate.replace(year=year, month=month, day=min(anchor_day or candidate.day, calendar.monthrange(year, month)[1]))
        else:
            year, month = candidate.year + 1, anchor_month or candidate.month
            candidate = candidate.replace(year=year, month=month, day=min(anchor_day or candidate.day, calendar.monthrange(year, month)[1]))
        if candidate > target:
            value = candidate.timestamp()
            if value > 4102444800: raise ValueError('recurrence outside supported epoch')
            return value
    raise ValueError('recurrence catch-up exceeds 500 steps; definition retained')
