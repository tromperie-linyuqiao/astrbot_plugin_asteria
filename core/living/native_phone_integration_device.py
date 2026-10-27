"""TLS-native device fact presentation/query over the existing PPB source.

No collector, transport, old Phone instance, model, store or sender is used.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

from .models import private_scope
from ..presence import PresenceLayer
from .native_phone_service.formatter import sanitize_phone_text, format_perception, _human_gap

_DOMAINS = ('device.battery', 'device.screen', 'device.network', 'device.audio',
            'user_activity', 'device.device', 'device.app', 'device.status')
_FIELDS = {
    'device.battery': {'level':(0,100),'charging':bool,'charging_type':str,'temperature_c':(0,90)},
    'device.screen': {'on':bool,'locked':bool},
    'device.network': {'type':str,'metered':bool},
    'device.audio': {'headphones':bool,'ringer_mode':str},
    'user_activity': {'steps_today':(0,1000000),'device_idle':bool,'last_unlock_epoch':(0,253402300799)},
    'device.device': {},
    'device.app': {'foreground_package':str,'foreground_label':str,'foreground_minutes':(0,1440),
                   'swipe_events_per_min':(0,600)},
    'device.status': {'reporting_recently':bool},
}
_ASPECTS = {
    'battery': ('device.battery',), '电量':('device.battery',), '充电':('device.battery',),
    'screen': ('device.screen',), '屏幕':('device.screen',),
    'network':('device.network',), '网络':('device.network',),
    'audio':('device.audio',), '耳机':('device.audio',),
    'app':('device.app',), '应用':('device.app',), '软件':('device.app',),
    'activity':('user_activity',), '活动':('user_activity',), '步数':('user_activity',),
    'status':('device.status',), '状态':_DOMAINS, '手机':_DOMAINS, '':_DOMAINS,
}


def _finite(value):
    return float(value) if type(value) in (int,float) and math.isfinite(value) else None


def _epoch(value):
    number = _finite(value)
    if number is not None:
        return number
    if isinstance(value,str) and len(value)<=40:
        try:
            parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (ValueError,OverflowError,OSError):
            return None
    return None


def _clean_value(domain, value):
    if not isinstance(value,dict):
        return {}
    clean = {}
    for key, expected in _FIELDS[domain].items():
        raw = value.get(key)
        if expected is bool:
            if type(raw) is bool:
                clean[key] = raw
        elif expected is str:
            text = sanitize_phone_text(raw,120)
            if text:
                clean[key] = text
        else:
            number = _finite(raw)
            if number is not None and expected[0]<=number<=expected[1]:
                clean[key] = number
    return clean


def format_device_record(domain, record, *, now, show_app=False, max_chars=360):
    """Format one current, source-qualified observation without collecting."""
    now = _finite(now)
    if (domain not in _DOMAINS or now is None or type(show_app) is not bool
            or type(max_chars) is not int or not 0<=max_chars<=4096
            or not isinstance(record,dict) or record.get('source')!='phone.device'
            or record.get('status')!='fresh'):
        return ''
    meta = record.get('meta')
    if not isinstance(meta,dict):
        return ''
    observed,expires = _epoch(meta.get('observed_at')),_epoch(meta.get('expires_at'))
    if (observed is None or expires is None or observed<0 or observed>now+30
            or expires<=observed or now>=expires):
        return ''
    value = _clean_value(domain,record.get('value'))
    if domain=='device.status':
        line = ('手机近期有状态上报；实时连接是否在线无法确认。'
                if value.get('reporting_recently') is True else '')
    else:
        section = 'activity' if domain=='user_activity' else domain.split('.',1)[1]
        # The only time-relative field is computed against the supplied frame
        # clock, never by renewing the original observation timestamp.
        if section=='activity':
            unlock = value.pop('last_unlock_epoch',None)
            line = format_perception({section:value},show_app=show_app,max_len=4096)
            if unlock is not None and 0<=now-unlock<36*3600:
                suffix = '上次解锁'+_human_gap(now-unlock)+'前'
                line = (line+'，' if line else '手机：')+suffix
        else:
            line = format_perception({section:value},show_app=show_app,max_len=4096)
        if section=='screen' and value.get('on') is False and line:
            line += '；灭屏不能证明忙碌或睡眠。'
    return line if len(line)<=max_chars else ''


class NativePhoneIntegration:
    """Read-only phone facts/query business independent of a legacy instance.

    The host may install render as phone.device's renderer while retaining the
    exact existing collector. query reads its snapshot only, never refresh().
    No source registration, source takeover, old configuration or DB is done.
    """
    def __init__(self,presence,*,authorize,show_app=False,clock=time.time):
        if not isinstance(presence,PresenceLayer) or not callable(authorize) or not callable(clock):
            raise ValueError('existing Presence and explicit scope authorization required')
        if type(show_app) is not bool and not callable(show_app):
            raise ValueError('explicit app-label policy required')
        self.presence,self.authorize,self.show_app,self.clock = presence,authorize,show_app,clock
        self.active = True

    def _allowed(self,scope):
        return self.active and self.presence.active and self.authorize(private_scope(scope)) is True

    def _show_app(self):
        value = self.show_app() if callable(self.show_app) else self.show_app
        return value is True

    def render(self,domain,record,scope,query,max_chars,now):
        scope = private_scope(scope)
        if not self._allowed(scope):
            return ''
        line = format_device_record(domain,record,now=now,show_app=self._show_app(),max_chars=max_chars)
        return line if self._allowed(scope) else ''

    def query(self,scope,aspect='',*,max_chars=800):
        scope = private_scope(scope)
        if type(max_chars) is not int or not 80<=max_chars<=1200:
            raise ValueError('bounded phone query budget required')
        if not isinstance(aspect,str) or len(aspect)>64:
            raise ValueError('bounded phone aspect required')
        domains = _ASPECTS.get(aspect.strip().lower())
        if domains is None:
            raise ValueError('unsupported phone aspect')
        if not self._allowed(scope):
            raise PermissionError('phone scope unavailable')
        now = _finite(self.clock())
        if now is None or now<0:
            raise ValueError('valid phone clock required')
        snapshot = self.presence.snapshot(scope,now=now)
        states = snapshot.get('states',{})
        if snapshot.get('scope')!=scope or not isinstance(states,dict) or not self._allowed(scope):
            raise PermissionError('phone scope changed')
        lines, selected = [], []
        show_app = self._show_app()
        for domain in domains:
            line = format_device_record(domain,states.get(domain),now=now,show_app=show_app,max_chars=max_chars)
            if line and sum(map(len,lines))+len(lines)+len(line)<=max_chars:
                lines.append(line)
                selected.append(domain)
        if not self._allowed(scope):
            raise PermissionError('phone scope changed')
        return {'available':bool(lines),'text':'\n'.join(lines) if lines else '当前手机感知没有这个方面的有效观测。',
                'domains':selected,'collector_refreshes':0,'model_calls':0,'sends':0}

    def diagnostics(self):
        return {'active':self.active and self.presence.active,'polling_tasks':0,
                'collector_refreshes':0,'model_calls':0,'sends':0,'writes':0,
                'owns_collection':False,'owns_music_accumulation':False}

    def close(self):
        self.active = False
