"""Pure current-day reasons for the existing PC non-random/shared sender lane."""
from datetime import datetime, time, timedelta
import hashlib

from .models import canonical
from .native_pc_business.helpers import special_calendar, special_day_events


def occasion_reason(scope, user, now):
    """Read one user's existing settings; never create users, tasks or leases."""
    settings = {k: user.get(k, {}) for k in ('birthday_profile', 'holiday_messages', 'course_timetable')}
    fingerprint = hashlib.sha256(canonical(settings).encode()).hexdigest()
    calendar = special_calendar(user, now)
    for course in calendar['items']:
        lead = settings['course_timetable'].get('remind_minutes', 10) * 60
        if course['start_at'] - lead <= now < course['start_at']:
            topic = ('课前提醒：' + course['name'] + '即将开始，地点：' + (course['location'] or '未填写')
                + '。自然简短地提醒，只依据已保存课表，不猜测用户已出发或已经到场。')
            identity = 'course:' + course['id']
            return _reason(scope, identity, topic, fingerprint, course['start_at'] - lead, course['start_at'], 100)
    events = special_day_events(user, now)
    if not events:
        return None
    # A birthday and another holiday on the same date remain one expression.
    birthday = [e for e in events if e['kind'] == 'birthday']
    chosen = birthday or events
    day = chosen[0]['date']
    from .native_important_dates import date_zone
    zone = date_zone('Asia/Shanghai')
    start = max(datetime.combine(datetime.fromisoformat(day).date(), time.fromisoformat(e['context']['start_time']), zone).timestamp() for e in chosen)
    end = min(datetime.combine(datetime.fromisoformat(day).date(), time.fromisoformat(e['context']['end_time']), zone).timestamp() for e in chosen)
    if not start <= now < end:
        return None
    names = '、'.join(e['name'] for e in chosen)
    topic = ('今天是用户的生日，给出自然贴近角色的祝福，不推算年龄。' if birthday else
        '今天是' + names + '，给出自然贴近角色的节日问候，不猜测用户放假、出游或庆祝安排。')
    return _reason(scope, ('birthday:' if birthday else 'holiday:') + day, topic, fingerprint, start, end, 95 if birthday else 90)


def _reason(scope, identity, topic, fingerprint, start, end, score):
    key = hashlib.sha256(canonical(['special_calendar', scope, identity]).encode()).hexdigest()
    return dict(key=key, source='special_calendar', topic=topic, score=score,
        evidence=dict(identity=identity, settings_fingerprint=fingerprint, start_at=start, expires_at=end))
