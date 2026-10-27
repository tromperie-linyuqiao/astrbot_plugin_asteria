"""Bounded, serializable native delivery contracts (no platform imports)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re

from .models import canonical, private_scope


def number(value, name, minimum=0, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("invalid " + name)
    return value


def task_input_hash(task):
    values = [task['id'], private_scope(task['scope']),
        task['session'], task['text'], task['images'], task['created_at'],
        task['due_at'], task['expires_at'], task['priority'], task['trigger'],
        task['max_attempts']]
    # Existing companion inputs retain their exact v1 hash. Dedicated queue3
    # reminder authorities bind their explicit lane and occurrence generation;
    # a previously open Stage 8 reader sees a hash mismatch and quarantines it.
    if 'delivery_lane' in task:
        values.extend([task['delivery_lane'], task.get('reminder_binding')])
    if 'audio' in task:
        values.extend(['tls.delivery.audio.v1', task['audio'], task['audio_text']])
    return hashlib.sha256(canonical(values).encode()).hexdigest()


def audio_extension(value):
    """Optional immutable speech metadata; absence retains the exact v1 row."""
    if 'audio' not in value:
        if 'audio_text' in value:
            raise ValueError('audio display metadata requires an owned audio file')
        return {}
    path, include_text = value['audio'], value.get('audio_text', True)
    if not isinstance(path, str) or not 1 <= len(path) <= 2048 or type(include_text) is not bool:
        raise ValueError('one owned audio reference and explicit text policy required')
    return dict(audio=path, audio_text=include_text)


def delivery_policy_hash(value):
    return hashlib.sha256(canonical({key:item for key,item in value.items()
        if key != 'last_activity_at'}).encode()).hexdigest()


def normalize_quiet_hours(value):
    """Optional shared-queue windows; the empty value retains its original policy."""
    if type(value) is not str or len(value)>287:raise ValueError('bounded quiet hours required')
    if not value.strip():return ''
    windows=[part.strip() for part in value.split(',')]
    if len(windows)>24 or any(re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]-(?:[01][0-9]|2[0-3]):[0-5][0-9]',part) is None for part in windows):
        raise ValueError('quiet hours must contain HH:MM-HH:MM windows')
    return ','.join(windows)


def delivery_quiet_window(value,now):
    """One shared half-open clock calculation for admission and final dispatch."""
    enabled=value.get('quiet_enabled',True)
    if type(enabled) is not bool:raise ValueError('invalid quiet setting')
    offset=value.get('tz_offset_minutes',480)
    if type(offset) is not int or not -840<=offset<=840:raise ValueError('invalid timezone offset')
    local=datetime.fromtimestamp(number(now,'now'),timezone(timedelta(minutes=offset)))
    def minutes(text):
        if type(text) is not str or re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',text) is None:
            raise ValueError('invalid quiet time')
        return int(text[:2])*60+int(text[3:])
    start,end=minutes(value.get('quiet_start','02:00')),minutes(value.get('quiet_end','08:00'))
    configured=normalize_quiet_hours(value.get('quiet_hours',''))
    minute=local.hour*60+local.minute
    if not configured:
        # Keep the old single-window calculation, including equal endpoints.
        quiet=enabled and (start==end or (start<=minute<end if start<end else minute>=start or minute<end))
        until=now
        if quiet:
            until=local.replace(hour=end//60,minute=end%60,second=0,microsecond=0).timestamp()
            if until<=now:until+=86400
        return dict(quiet_until=until,quiet_all_day=enabled and start==end)
    intervals=[]
    for part in configured.split(','):
        left,right=(minutes(text) for text in part.split('-'))
        if left==right:intervals=[(0,1440)];break
        intervals.extend([(left,right)] if left<right else [(0,right),(left,1440)])
    merged=[]
    for left,right in sorted(intervals):
        if left==right:continue
        if merged and left<=merged[-1][1]:merged[-1]=(merged[-1][0],max(right,merged[-1][1]))
        else:merged.append((left,right))
    all_day=enabled and merged==[(0,1440)]
    until=now
    if enabled:
        midnight=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        for left,right in merged:
            if left<=minute<right:
                until=midnight+right*60
                if right==1440 and merged[0][0]==0 and not all_day:until+=merged[0][1]*60
                break
    return dict(quiet_until=until,quiet_all_day=all_day)


@dataclass(frozen=True)
class DeliveryPolicy:
    daily_limit: int = 8
    min_interval_seconds: float = 2700
    recent_chat_seconds: float = 1200
    quiet_start: str = '02:00'
    quiet_end: str = '08:00'
    quiet_enabled: bool = True
    tz_offset_minutes: int = 480
    night_mode: str = 'quiet_companion'
    sampling_minutes: int = 10
    require_image: bool = True
    lease_seconds: float = 30
    timeout_seconds: float = 10
    quiet_hours: str = ''

    def __post_init__(self):
        for name, low, high in [('daily_limit',0,100), ('min_interval_seconds',0,86400),
                ('recent_chat_seconds',0,86400), ('tz_offset_minutes',-720,840),
                ('sampling_minutes',1,1440), ('lease_seconds',1,300),
                ('timeout_seconds',0.01,120)]:
            number(getattr(self,name), name, low, high)
        for name in ('daily_limit','tz_offset_minutes','sampling_minutes'):
            if type(getattr(self,name)) is not int: raise ValueError('integer '+name+' required')
        for name in ('quiet_start','quiet_end'):
            if not isinstance(getattr(self,name),str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',getattr(self,name)):
                raise ValueError('invalid '+name)
        if type(self.require_image) is not bool or type(self.quiet_enabled) is not bool or self.night_mode not in {'quiet_companion','off'}:
            raise ValueError('invalid delivery policy')
        if self.lease_seconds <= self.timeout_seconds:
            raise ValueError('lease must exceed platform timeout')
        object.__setattr__(self,'quiet_hours',normalize_quiet_hours(self.quiet_hours))

    def local_time(self, now):
        return datetime.fromtimestamp(number(now,'now'), timezone(timedelta(minutes=self.tz_offset_minutes)))

    def day(self, now): return self.local_time(now).date().isoformat()

    def as_dict(self):
        value=asdict(self)
        if not self.quiet_hours:value.pop('quiet_hours')
        return value


def make_task(scope, event_id, *, text, images=(), now, due_at=None,
              expires_at=None, priority=50, trigger='event', max_attempts=3,
              audio=None, audio_text=True):
    scope = private_scope(scope)
    if not isinstance(event_id,str) or not 1 <= len(event_id) <= 256:
        raise ValueError('bounded event identity required')
    if not isinstance(text,str) or not 1 <= len(text.strip()) <= 4000:
        raise ValueError('bounded nonempty text required')
    if not isinstance(images,(tuple,list)) or len(images)>1 or any(not isinstance(p,str) or not p or len(p)>2048 for p in images):
        raise ValueError('at most one image is supported')
    if type(priority) is not int or not 0 <= priority <= 100 or trigger not in {'event','timer'}:
        raise ValueError('invalid scheduling metadata')
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise ValueError('invalid retry bound')
    now=number(now,'created_at'); due=number(now if due_at is None else due_at,'due_at')
    expires=number(now+3600 if expires_at is None else expires_at,'expires_at')
    if due < now or not now < expires or due >= expires: raise ValueError('invalid task lifetime')
    identity=hashlib.sha256(canonical(['tls.delivery.v1',scope,event_id]).encode()).hexdigest()
    result = dict(id=identity,scope=scope,session=scope['session_id'],text=text.strip(),images=list(images),
        created_at=now,due_at=due,expires_at=expires,priority=priority,trigger=trigger,max_attempts=max_attempts)
    if audio is not None:
        result.update(audio_extension(dict(audio=audio, audio_text=audio_text)))
    return result
