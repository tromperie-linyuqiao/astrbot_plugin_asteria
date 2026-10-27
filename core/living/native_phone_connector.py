"""Read the configured PPB /state protocol without importing the phone plugin.

The existing host tick calls ``read``; this module creates no polling task or
model call. Only explicitly bound users/devices are read. A small transport
cache retains upstream clocks, never renews section freshness, and never falls
back to an old value after a failed request. The host owns Presence registration
and must transfer phone source ownership explicitly before using these rows.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import json
import math
import re
import time
from urllib.parse import urlsplit

import aiohttp

from .models import EvidenceKind, Observation, plain, private_scope

DEVICE_DOMAINS = ('device.battery', 'device.screen', 'device.network', 'device.app',
                  'device.audio', 'device.device', 'user_activity')
OBSERVATION_TYPES = DEVICE_DOMAINS + ('music',)
_SECTIONS = ('battery', 'screen', 'network', 'app', 'audio', 'device', 'activity', 'music')
_DEVICE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z')
_PACKAGE = re.compile(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z')
_MAX_EPOCH = 253402300799
_MAX_RESPONSE = 256 * 1024
# Only protocol metadata, excluding notifications, location and legacy audio
# titles. Dedicated media-session observations own current playback claims.
_FIELDS = {
    'battery': {'level':100, 'charging':bool, 'charging_type':16, 'temperature_c':90., 'health':24, 'cycle_count':1000000},
    'screen': {'on':bool, 'locked':bool},
    'network': {'type':16, 'ssid_hash':16, 'roaming':bool, 'metered':bool},
    'app': {'foreground_package':120, 'foreground_label':60, 'foreground_since_epoch':4102444800.,
            'foreground_minutes':1440, 'swipe_events_per_min':600},
    'audio': {'headphones':bool, 'ringer_mode':16},
    'device': {'name':120, 'platform':24, 'os_version':32, 'battery_temp_c':90., 'power_save':bool},
    'activity': {'steps_today':1000000, 'device_idle':bool, 'last_unlock_epoch':4102444800.},
}
_STRINGS = {'charging_type','health','type','ssid_hash','foreground_package','foreground_label',
            'ringer_mode','name','platform','os_version'}


def _number(value, maximum=_MAX_EPOCH):
    return float(value) if type(value) in (int,float) and math.isfinite(value) and 0<=value<=maximum else None


def _bounded(value, name, low, high):
    number = _number(value, high)
    if number is None or number<low: raise ValueError('invalid '+name)
    return number


def _text(value, maximum):
    if not isinstance(value,str): return ''
    # Untrusted app/media text stays a single bounded metadata line.
    return ' '.join(re.sub(r'[\x00-\x1f\x7f<>#`*_~\[\]|]', ' ', value).split())[:maximum]


def _url(value):
    if not isinstance(value,str) or not 1<=len(value)<=500 or re.search(r'[\x00-\x20\x7f]',value):
        raise ValueError('explicit PPB HTTP(S) base URL required')
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('http','https') or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment or parts.port==0
                or '..' in parts.path.split('/')): raise ValueError
    except ValueError: raise ValueError('explicit PPB HTTP(S) base URL required') from None
    return value.rstrip('/')


def _bindings(value):
    if not isinstance(value,dict) or len(value)>128: raise ValueError('explicit bounded user/device mapping required')
    result={}
    for user, devices in value.items():
        if (not isinstance(user,str) or not 1<=len(user)<=256 or user!=user.strip()
                or any(ord(char)<32 for char in user) or not isinstance(devices,(list,tuple))
                or not 1<=len(devices)<=8 or any(not isinstance(device,str) or not _DEVICE.fullmatch(device) for device in devices)):
            raise ValueError('invalid explicit user/device binding')
        result[user]=tuple(dict.fromkeys(devices))
    return result


def _section(section, raw):
    if not isinstance(raw,dict): return None
    result={}
    for key, maximum in _FIELDS[section].items():
        value=raw.get(key)
        if maximum is bool:
            if type(value) is bool: result[key]=value
        elif key in _STRINGS:
            text=value if key=='foreground_package' and isinstance(value,str) else _text(value,maximum)
            if key=='foreground_package' and len(text)>maximum:continue
            if text or key=='foreground_package' and value=='': result[key]=text
        else:
            number=_number(value,maximum)
            if number is not None: result[key]=int(number) if type(maximum) is int else number
    if section=='app' and result.get('foreground_package') and not _PACKAGE.fullmatch(result['foreground_package']):
        result.pop('foreground_package')
    if section=='app' and 'foreground_package' not in result:return None
    return result or None


def _music(raw, device, observed, now):
    if (not isinstance(raw,dict) or type(raw.get('schema_version')) is not int or raw['schema_version']!=1
            or raw.get('source')!='media_session' or type(raw.get('playing')) is not bool): return None
    playback=raw.get('state')
    if not isinstance(playback,str) or playback not in ('playing','paused','stopped'): return None
    if raw['playing'] is not (playback=='playing'): return None
    title=_text(raw.get('title'),120) if playback=='playing' else ''
    if playback=='playing' and not title: return None
    info={key:_text(raw.get(key),120) for key in ('title','artist','album')} if title else {}
    if info: info.update(source='media_session', metadata_source='media_observed')
    user=dict(state=playback, playing=raw['playing'], reliable=True, source='media_session',
              device_id=device, observed_at=observed, age_seconds=max(0.,now-observed),
              package=_text(raw.get('package'),120), track_id=_text(raw.get('track_id'),160),
              listening_seconds=0, reason='observed_'+playback)
    for key in ('duration_ms','progress_ms'):
        value=raw.get(key)
        user[key]=value if type(value) is int and 0<=value<=7*86400000 else None
    if user['duration_ms'] is not None and user['progress_ms'] is not None and user['progress_ms']>user['duration_ms']:
        user['progress_ms']=None
    user['playback_speed']=_number(raw.get('playback_speed'),4)
    return dict(event_type='music_'+playback, song_id='', song_info=info, match_status='unknown', user_state=user)


class NativePhoneConnector:
    """Explicit PPB transport. ``authorize`` validates the complete host scope.

    ``user_devices`` is a mapping of user IDs to reviewed device ID lists; no
    fallback to a global/default device is inferred. The source names preserve
    the shared Presence contract. ``read`` returns at most 64 typed rows and
    rechecks authorization after I/O. ``close`` is async and invalidates reads.
    """
    def __init__(self,base_url,token,user_devices,*,authorize,clock=time.time,
                 stale_seconds=600,music_ttl_seconds=180,timeout_seconds=2,cache_ttl_seconds=2):
        self._endpoint=_url(base_url)+'/state'
        if not isinstance(token,str) or not token.strip() or len(token)>512 or re.search(r'[^\x20-\x7e]',token):
            raise ValueError('explicit valid PPB token required')
        if not callable(authorize) or not callable(clock): raise ValueError('phone authorization/clock required')
        self._token=token;self._bindings=_bindings(user_devices)
        self.authorize,self.clock=authorize,clock
        self.stale=_bounded(stale_seconds,'device freshness',30,86400)
        self.music_ttl=_bounded(music_ttl_seconds,'music freshness',30,600)
        self.timeout=_bounded(timeout_seconds,'PPB timeout',.05,10)
        self.cache_ttl=_bounded(cache_ttl_seconds,'PPB cache TTL',0,30)
        self._closed=False;self._session=None;self._lock=asyncio.Lock();self._cache=OrderedDict()
        self._metrics=dict(requests=0,cache_hits=0,failures=0,reads=0,returned=0)

    def _now(self):
        value=_number(self.clock())
        if value is None: raise ValueError('invalid phone clock')
        return value

    def _allowed(self,scope):
        return not self._closed and self.authorize(scope) is True

    async def _fetch(self,device):
        if self._closed:return None,'closed'
        now=self._now();cached=self._cache.get(device)
        if cached and 0<=now-cached[0]<self.cache_ttl:
            self._cache.move_to_end(device);self._metrics['cache_hits']+=1;return cached[1],cached[2]
        if self._session is None:
            self._session=aiohttp.ClientSession(trust_env=False,timeout=aiohttp.ClientTimeout(total=self.timeout))
        self._metrics['requests']+=1
        try:
            async with self._session.get(self._endpoint,params={'device':device,'stale_seconds':int(self.stale)},
                    headers={'Authorization':'Bearer '+self._token},allow_redirects=False) as response:
                if response.status!=200: raise ValueError('unavailable')
                body=bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    body.extend(chunk)
                    if len(body)>_MAX_RESPONSE: raise ValueError('unavailable')
                view=plain(json.loads(body),_MAX_RESPONSE)
                if not isinstance(view,dict) or view.get('ok') is not True: raise ValueError('unavailable')
            reason='received'
        except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,UnicodeError,RecursionError,RuntimeError):
            # Never retain exception text, HTTP bodies, URLs or headers in logs.
            view=None;reason='bridge_unavailable';self._metrics['failures']+=1
        if self._closed:return None,'closed'
        self._cache[device]=(self._now(),view,reason);self._cache.move_to_end(device)
        while len(self._cache)>32:self._cache.popitem(last=False)
        return view,reason

    def _rows(self,scope,device,view,reason,now):
        valid=(isinstance(view,dict) and view.get('device_id')==device and isinstance(view.get('state'),dict))
        server=_number(view.get('server_time')) if valid else None
        if server is None or server>now+30:
            valid=False;reason='invalid_upstream_identity_or_clock' if view is not None else reason
        state=view['state'] if valid else {};ages=view.get('section_age_seconds') if valid else None
        rows=[]
        for section in _SECTIONS:
            domain='music' if section=='music' else 'user_activity' if section=='activity' else 'device.'+section
            ttl=self.music_ttl if section=='music' else self.stale
            age=_number(ages.get(section)) if isinstance(ages,dict) else None
            observed=server-age if server is not None and age is not None and server>=age else None
            expiry=observed+ttl if observed is not None else None
            raw=state.get(section);payload=None;status='unknown' if valid else 'unavailable';why=reason
            if observed is not None:
                if section=='music':
                    music_stamp=_number(raw.get('observed_at')) if isinstance(raw,dict) else None
                    if music_stamp is None or music_stamp>now+30 or music_stamp>server+30:
                        observed=expiry=None;why='invalid_music_observation_time'
                    else:
                        # Preserve actual media observation time; a newer section
                        # heartbeat cannot extend an older media-session fact.
                        expiry=min(expiry,music_stamp+ttl);observed=music_stamp
                        if expiry<observed:observed=expiry=None
                if observed is not None:
                    status='stale' if now>=expiry else 'fresh'
                    why='section_expired' if status=='stale' else 'section_observed'
                    if status=='fresh':
                        payload=_music(raw,device,observed,now) if section=='music' else _section(section,raw)
                        if payload is None:status='unknown';why='no_reliable_section_metadata'
            elif valid:why='section_timestamp_required'
            provenance=dict(connector='ppb_http',section=section,reason=why,
                            timestamp_basis='upstream_section_clock',upstream_server_time=server)
            semantic=payload
            if section=='music' and payload:
                semantic={key:payload[key] for key in ('event_type','song_info')}
                semantic['user_state']={key:payload['user_state'][key] for key in ('state','playing','source','device_id','package','track_id')}
            rows.append(Observation(source_id='phone.music' if section=='music' else 'phone.device',
                observation_type=domain,scope=scope,observed_at=observed,received_at=now,expires_at=expiry,
                payload=payload,provenance=provenance,permission_scope='phone.read',
                evidence_kind=EvidenceKind.REAL_OBSERVATION,status=status,device_id=device,
                importance='important' if section=='music' and status=='fresh' else 'normal',
                change_key={'value':semantic,'status':status,'device_id':device}))
        return rows

    async def read(self,scope):
        scope=private_scope(scope)
        if not self._allowed(scope):return []
        devices=self._bindings.get(scope['user_id'],())
        if not devices:return []
        async with self._lock:
            if not self._allowed(scope):return []
            self._metrics['reads']+=1
            views=await asyncio.gather(*(self._fetch(device) for device in devices))
            if not self._allowed(scope):return []
            now=self._now()
            rows=[row for device,(view,reason) in zip(devices,views) for row in self._rows(scope,device,view,reason,now)]
            self._metrics['returned']+=len(rows)
            return rows

    def diagnostics(self):
        return dict(active=not self._closed,**self._metrics,cache_entries=len(self._cache),
                    polling_tasks=0,llm_calls=0,writes=0)

    async def close(self):
        self._closed=True;self._cache.clear();self._token=''
        if self._session is not None:await self._session.close()

    aclose=close
