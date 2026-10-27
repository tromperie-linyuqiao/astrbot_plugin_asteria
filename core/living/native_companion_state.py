"""Read-only compatibility input while the old companion keeps other duties.

No old plugin is imported or called. Only exact user/session rows contribute
frequency inputs; this does not transfer its queue, persona, memory or counters.
Unreadable/incomplete data disables new opportunities rather than inventing an
idle user. The host merges this with its own durable activity and reservations.
Old UNKNOWN outcomes remain frequency reservations for the same bounded 24h
window as PC. They are not confirmed sends, and this read never settles them.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json,math,os,stat,time
from pathlib import Path

from .models import private_scope


class NativeCompanionStateReader:
    def __init__(self,path,*,authorize,clock=time.time,tz_offset_minutes=480,max_bytes=32*1024**2):
        self.path=Path(path);self.authorize=authorize;self.clock=clock
        self.zone=timezone(timedelta(minutes=tz_offset_minutes));self.max_bytes=max_bytes
        if not callable(authorize) or not callable(clock):raise ValueError('state reader authority required')

    def read(self,scope,*,source_scope=None):
        scope=private_scope(scope)
        if self.authorize(scope) is not True:raise PermissionError('private state unavailable')
        source=scope if source_scope is None else private_scope(source_scope)
        # The host resolves the confirmed link before supplying this internal
        # read-only source. It remains data ownership, never a source lease or
        # permission to send. Ordinary callers retain the exact identity check.
        if source!=scope and (scope['platform']!='webchat' or scope['bot_id']!='webchat'
                or source['platform']=='webchat' or source['session_id']==scope['session_id']
                or source['character_id']!=scope['character_id']):
            raise ValueError('linked private state source required')
        now=self.clock()
        def number(value,*,future=False):
            if (type(value) not in (int,float) or not math.isfinite(value) or value<0
                    or value>253402300799 or not future and value>now+30):
                raise ValueError('invalid shared state timestamp')
            return value
        try:
            number(now,future=True)
            if any(p.is_symlink() for p in (self.path,*self.path.parents)):raise ValueError('state path alias')
            with self.path.open('rb') as stream:
                before=os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size>self.max_bytes:raise ValueError('state capacity')
                raw=stream.read(self.max_bytes+1);after=os.fstat(stream.fileno())
            if len(raw)>self.max_bytes or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
                raise ValueError('shared state changed during read')
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('shared state layout')
            users=data.get('users')
            if not isinstance(users,dict):raise ValueError('shared state layout')
            row=users.get(source['user_id'])
            if (not isinstance(row,dict) or row.get('umo')!=source['session_id']
                    or row.get('user_id',source['user_id'])!=source['user_id']):
                raise ValueError('exact shared identity missing')
            if row.get('relationship_role') not in {'owner','friend'}:raise ValueError('explicit shared role missing')
            sending=row.get('proactive_sending',False)
            started=number(row.get('proactive_sending_started_at',0))
            if type(sending) is not bool or sending or started:
                # Only the old owner may recover its marker. Its eight-minute
                # cleanup timeout is not proof that an SDK call has stopped.
                raise ValueError('legacy dispatch unresolved')
            activity=max(number(row[key]) for key in ('last_activity_at','last_user_message_at','last_private_activity_at') if key in row)
            sent=max(number(row[key]) for key in ('last_sent','last_proactive_sent_at','companion_last_sent_at','proactive_chat_bridge_last_sent_at') if key in row)
            rest=number(row['user_rest_until'],future=True)
            day=datetime.fromtimestamp(now,self.zone).strftime('%Y-%m-%d')
            counts=[]
            for date_key,count_key in (('sent_day','sent_today'),('companion_sent_day','companion_sent_today')):
                date,count=row[date_key],row[count_key]
                if not isinstance(date,str) or type(count) is not int or not 0<=count<=100000:raise ValueError('shared daily counter')
                if datetime.strptime(date,'%Y-%m-%d').strftime('%Y-%m-%d')!=date or date>day:
                    raise ValueError('shared counter date unavailable')
                counts.append(count if date==day else 0)
            uncertain=row.get('companion_uncertain_deliveries',[])
            if not isinstance(uncertain,list) or len(uncertain)>64:
                raise ValueError('bounded legacy reservations required')
            reserved=0
            for entry in uncertain:
                if not isinstance(entry,dict):raise ValueError('invalid legacy reservation')
                at=number(entry.get('at'))
                if at>now:raise ValueError('future legacy reservation')
                # PC retains 0 <= age <= 86400, inclusive. Stale frequency
                # reservations no longer affect admission; never delete them
                # or reinterpret expiry as a confirmed delivery failure.
                if now-at>86400:continue
                date=entry.get('day')
                if (not isinstance(date,str) or datetime.strptime(date,'%Y-%m-%d').strftime('%Y-%m-%d')!=date
                        or date>day):raise ValueError('legacy reservation day unavailable')
                # Preserve PC's declared local-day and per-row counting. Its
                # two confirmed counters mirror one another, UNKNOWNs do not.
                reserved+=int(date==day)
                sent=max(sent,at)
            if type(row.get('enabled')) is not bool:raise ValueError('shared enable state')
            # manual_enabled is an extra target opt-in, not the inverse of
            # enabled: configured targets normally keep that override False.
            # Preserve an explicit refusal, including malformed refusal values.
            result=dict(enabled=row['enabled'] and row.get('manual_disabled',False) is False,
                is_friend=row['relationship_role']=='friend',last_activity_at=activity,rest_until=rest,
                shared_last_sent_at=sent,shared_sent_today=max(counts)+reserved,
                ignored_streak=max(0,min(100,int(row.get('ignored_streak',0)))),state='current')
        except (OSError,ValueError,TypeError,KeyError,OverflowError):
            return {'enabled':False,'state':'shared_state_unavailable'}
        if self.authorize(scope) is not True:raise PermissionError('private state revoked')
        return result
