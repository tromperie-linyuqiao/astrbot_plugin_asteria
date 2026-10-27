"""Pure PPB music-event projection, with TLS's existing exact catalog resolver.

This replaces observation parsing and metadata lookup only. Collection, device
selection, listening continuity, rendering and delivery have separate owners.
No legacy import, I/O, worker, model call or send is performed here (a supplied
NativeMusicCatalog retains its existing bounded read-only file behavior).
"""
from __future__ import annotations

import math
import re
import time

from .native_music_catalog import NativeMusicCatalog, display_text, match_music

_STATES = frozenset(('playing', 'paused', 'stopped', 'buffering', 'unknown'))
_MAX_EPOCH = 253402300799


def _number(value, lo=0, hi=_MAX_EPOCH):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi else None


def _text(value, limit=100):
    return ' '.join(re.sub(r'[\x00-\x1f\x7f<>]', ' ', display_text(value)).split())[:limit]


def unknown_music(*, reason='unavailable', device_id='', stale=False):
    return dict(event_type='music_stale' if stale else 'music_unknown', song_id='', song_info={},
        match_status='unknown', user_state=dict(state='stale' if stale else 'unknown', playing=False,
        source='unavailable', reliable=False, device_id=device_id, observed_at=None, age_seconds=None,
        duration_ms=None, progress_ms=None, listening_seconds=0, reason=reason))


def _age(view, section, observed, now):
    ages = view.get('section_age_seconds')
    age = _number(ages.get(section) if isinstance(ages, dict) and ages else view.get('age_seconds'))
    server = _number(view.get('server_time'))
    if age is None or server is not None and server > now + 30:
        return None
    age += max(0., now - server) if server is not None else 0.
    if observed is not None:
        observed = _number(observed, lo=1)
        if observed is None or observed > now + 30:
            return None
        age = max(age, max(0., now - observed))
    return age


def _info(match, music):
    if match['status'] == 'matched':
        row = match['song_info']
        info = {key: _text(row.get(key), 120 if key in ('title', 'artist', 'album') else 60)
                for key in ('title', 'artist', 'album', 'language', 'genre', 'mood', 'source')}
        info['metadata_source'] = 'local_index'
        info['missing'] = [key for key in ('title', 'artist', 'album', 'language', 'genre', 'mood')
                           if not info.get(key) or info[key] == 'unknown']
        return info
    return dict(title=_text(music.get('title')), artist=_text(music.get('artist')),
        album=_text(music.get('album')), language='unknown', genre='unknown', mood='unknown',
        source='media_session', metadata_source='media_observed', missing=['language', 'genre', 'mood'])


def build_music_event(view, index=None, *, now=None, ttl_seconds=180):
    """Project one actual observation; an index entry never proves playback.

    The established PPB event shape, stale boundary (> TTL), explicit legacy
    pause and session/progress fields are preserved for the retained collector
    and listening accumulator. An arbitrary duck-typed reader is not executed.
    """
    now = _number(time.time() if now is None else now)
    ttl = _number(ttl_seconds, lo=1, hi=86400)
    if now is None or ttl is None:
        return unknown_music(reason='invalid_clock_or_ttl')
    if not isinstance(view, dict) or view.get('ok') is not True or not isinstance(view.get('state'), dict):
        return unknown_music()
    device = _text(view.get('device_id'), 64)
    music = view['state'].get('music')
    if not isinstance(music, dict):
        audio = view['state'].get('audio')
        if not isinstance(audio, dict):
            return unknown_music(reason='no_music_observation', device_id=device)
        age = _age(view, 'audio', None, now)
        if age is None:
            return unknown_music(reason='unknown_audio_age', device_id=device)
        if age > ttl:
            return unknown_music(reason='audio_expired', device_id=device, stale=True)
        event = unknown_music(reason='legacy_candidate' if audio.get('media_active') is True else 'legacy_unknown', device_id=device)
        event['user_state'].update(source='legacy_notification', age_seconds=age, observed_at=max(1., now - age))
        if audio.get('media_active') is False:
            event['event_type'] = 'music_paused'
            event['user_state'].update(state='paused', reason='legacy_explicit_pause')
        return event
    if type(music.get('schema_version')) is not int or music['schema_version'] != 1:
        return unknown_music(reason='invalid_schema', device_id=device)
    source, playback = music.get('source'), music.get('state')
    if (not isinstance(source, str) or source not in ('media_session', 'legacy_notification', 'unavailable')
            or not isinstance(playback, str) or playback not in _STATES or type(music.get('playing')) is not bool):
        return unknown_music(reason='invalid_music_state', device_id=device)
    observed = _number(music.get('observed_at'), lo=1)
    if observed is None:
        return unknown_music(reason='invalid_observation_time', device_id=device)
    age = _age(view, 'music', observed, now)
    if age is None:
        return unknown_music(reason='invalid_music_age', device_id=device)
    if age > ttl:
        return unknown_music(reason='music_expired', device_id=device, stale=True)
    event = unknown_music(reason='no_reliable_current_track', device_id=device)
    user = event['user_state']
    user.update(state=playback, source=source, observed_at=observed, age_seconds=round(age, 3),
        package=_text(music.get('package')), track_id=_text(music.get('track_id'), 160),
        session_id=_text(music.get('session_id'), 160))
    if playback in ('paused', 'stopped') and music['playing'] is False:
        event['event_type'] = 'music_' + playback
        user.update(reliable=source == 'media_session', reason='explicit_' + playback)
        return event
    if source != 'media_session' or playback != 'playing' or music['playing'] is not True:
        return event
    title, artist = _text(music.get('title')), _text(music.get('artist'))
    if not title:
        user.update(reason='missing_title')
        return event
    match = index.match(title, artist) if type(index) is NativeMusicCatalog else match_music(index, title, artist)
    event.update(event_type='music_playing', song_id=match['song_id'], song_info=_info(match, music), match_status=match['status'])
    duration, progress = music.get('duration_ms'), music.get('progress_ms')
    duration = duration if type(duration) is int and 0 < duration <= 7 * 86400000 else None
    progress = progress if type(progress) is int and 0 <= progress <= 7 * 86400000 else None
    if duration is not None and progress is not None and progress > duration:
        progress = None
    user.update(playing=True, reliable=True, duration_ms=duration, progress_ms=progress,
        playback_speed=_number(music.get('playback_speed'), hi=4), reason='observed_playing')
    return event
