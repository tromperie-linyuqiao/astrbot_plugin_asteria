"""A scoped, temporary reference to user-maintained music metadata.

This combines an existing Phone observation with the existing exact library
matcher. It never changes the observation, its song ID, or playback history.
build/current are synchronous database readers: their caller must use its
existing worker. Capture and re-read Presence snapshots on the owning loop;
the module does not collect, create workers, stage fragments, or grant scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import math
import re

from .context_engine import ContextFragment
from .memory_context import _SECRET
from .models import canonical, plain, private_scope, scope_key
from .native_music_catalog import display_text
from .native_music_library import NativeMusicLibrary

_MUSIC = re.compile(r'音乐|歌曲|听歌|歌名|歌手|专辑|这首|曲目|歌词|music|song|artist|album|lyrics', re.I)
_LYRICS = re.compile(r'(?:给我|发我|展示|看看|看下|想看|告诉我|解释|查下?|找下?).{0,12}歌词|歌词(?:是什么|内容|全文|含义|怎么唱)|(?:what|show|give|tell|explain).{0,32}lyrics', re.I)
_NO_LYRICS = re.compile(r'(?:不要|不用|不必|无需|别|不想|不需要).{0,12}歌词|歌词.{0,4}(?:不要|不用|别|无需|不必)|(?:do not|don.t|no|without).{0,20}lyrics', re.I)
_DEVICE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z')


def _hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _text(value, maximum, *, empty=False):
    if (type(value) is not str or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError('bounded observed music text required')
    value = display_text(value)
    if not empty and not value:
        raise ValueError('explicit observed music text required')
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('finite positive timestamp required')
    return float(value)


def _stamp(value):
    # Actual PresenceLayer.read publishes timezone-aware ISO strings.
    if type(value) is not str or not 1 <= len(value) <= 64:
        raise ValueError('actual Presence ISO timestamp required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone-aware Presence timestamp required')
    return _number(parsed.timestamp())


def _observation(scope, snapshot, now):
    snapshot = plain(snapshot, 32768)
    if (type(snapshot) is not dict or type(snapshot.get('schema_version')) is not int
            or snapshot['schema_version'] != 1 or private_scope(snapshot.get('scope')) != scope
            or type(snapshot.get('revision')) is not int or snapshot['revision'] < 0
            or type(snapshot.get('states')) is not dict or set(snapshot['states']) != {'music'}):
        raise ValueError('one actual scoped Presence music snapshot required')
    record = snapshot['states']['music']
    if (type(record) is not dict or record.get('source') != 'phone.music'
            or record.get('status') != 'fresh' or type(record.get('meta')) is not dict
            or type(record.get('value')) is not dict):
        raise ValueError('fresh Phone music source required')
    meta, event = record['meta'], record['value']
    user, info = event.get('user_state'), event.get('song_info')
    if (type(user) is not dict or type(info) is not dict or event.get('event_type') != 'music_playing'
            or user.get('source') != 'media_session' or user.get('state') != 'playing'
            or user.get('playing') is not True or user.get('reliable') is not True
            or meta.get('evidence_kind') != 'observed' or 'source_revision' not in meta):
        raise ValueError('actual reliable playing media-session observation required')
    revision = meta['source_revision']
    # Phone's real collector currently supplies explicit None here. The
    # snapshot revision is always retained as well; an absent key is unknown.
    if (revision is not None and type(revision) not in (str, int, float)
            or type(revision) is str and len(revision) > 128
            or type(revision) is float and not math.isfinite(revision)):
        raise ValueError('bounded actual source version required')
    observed, expiry = _stamp(meta.get('observed_at')), _stamp(meta.get('expires_at'))
    if not observed <= now + 30 or not observed < expiry <= observed + 604800 or not now < expiry:
        raise ValueError('unexpired actual observation required')
    if abs(_number(user.get('observed_at')) - observed) > .001:
        raise ValueError('music observation clocks disagree')
    device = _text(meta.get('device_id'), 64)
    if not _DEVICE.fullmatch(device) or user.get('device_id') != device:
        raise ValueError('same explicit observed device required')
    title, artist = _text(info.get('title'), 120), _text(info.get('artist'), 120, empty=True)
    identity = dict(scope=scope, source='phone.music', status='fresh', source_revision=revision,
        snapshot_revision=snapshot['revision'], observed_at=observed, expires_at=expiry,
        device_id=device, event_type=event['event_type'], title=title, artist=artist,
        original_song_id=_text(event.get('song_id'), 128, empty=True),
        track_id=_text(user.get('track_id'), 160, empty=True),
        session_id=_text(user.get('session_id'), 160, empty=True),
        package=_text(user.get('package'), 120, empty=True),
        media_source=user['source'], state=user['state'], playing=True, reliable=True)
    return dict(title=title, artist=artist, expires_at=expiry, music_token=_hash(identity))


@dataclass(frozen=True)
class MusicReferenceContribution:
    fragment: ContextFragment
    music_token: str
    library_generation: tuple
    record_id: str
    scope_token: str
    lyrics_included: bool
    _seal: object = field(repr=False, compare=False)
    _fragment_token: str = field(repr=False)


class NativeMusicReference:
    """No cache: one exact metadata match, followed by a final read proof.

build accepts the detached result of PresenceLayer.read(scope, 'music'). A
None result means no eligible reference. current must receive a newly captured
snapshot, not the original saved input; it is a final callback for the caller,
not a worker or automatic publication mechanism. Database reads require the
caller's existing worker, including current's library generation check.
"""
    def __init__(self, library, *, clock=None):
        if type(library) is not NativeMusicLibrary:
            raise ValueError('actual existing native music library required')
        self.library = library
        self.clock = library.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('explicit clock required')
        self._bindings = (library, library.journal, library.authorize, library.clock)
        self._seal, self.active = object(), True

    def _resources(self):
        library = self.library
        return (self.active and library.active and not library.journal._closed
            and all(old is new for old, new in zip(self._bindings,
                (library, library.journal, library.authorize, library.clock))))

    def _now(self):
        return _number(self.clock())

    def snapshot_token(self, scope, snapshot):
        """Pure final loop check after a worker await; no database access."""
        try:
            if not self._resources():
                return None
            return _observation(private_scope(scope), snapshot, self._now())['music_token']
        except Exception:
            return None

    @staticmethod
    def _fragment_token(fragment):
        return _hash(dict(id=fragment.fragment_id, text=fragment.text, source=fragment.source,
            kind=fragment.evidence_kind, priority=fragment.priority, expires_at=fragment.expires_at))

    def build(self, scope, snapshot, *, query='', max_chars=900):
        """Read metadata synchronously off-loop; never mutate any source object."""
        if (type(query) is not str or len(query) > 2000 or not _MUSIC.search(query)
                or type(max_chars) is not int or not 240 <= max_chars <= 1200):
            return None
        try:
            scope = private_scope(scope)
            now = self._now()
            observed = _observation(scope, snapshot, now)
            if not self._resources():
                return None
            generation = self.library.generation(scope)
            if generation is None:
                return None
            match = self.library.match(scope, observed['title'], observed['artist'])
            if (not self._resources() or generation != self.library.generation(scope)
                    or match.get('status') != 'matched' or match.get('candidate_count') != 1):
                return None
            info = match.get('song_info')
            if (type(info) is not dict or info.get('metadata_only') is not True
                    or info.get('source') != 'tls_native_music_library'
                    or match.get('song_id') != info.get('song_id')):
                return None
            identity = match['song_id']
            row = self.library.get(scope, identity)
            if row is None or row['archived'] or row['fields']['enabled'] is not True:
                return None
            values = row['fields']
            if any(_SECRET.search(values[name]) for name in ('title','artist','album','genre','language','mood','lyrics','note')):
                return None
            lines = ['用户维护的曲目参考资料；不是设备观测，不证明用户喜好、实际听过或角色经历。']
            def append(label, value, maximum=None):
                if not value:
                    return False
                excerpt = maximum is not None and len(value) > maximum
                line = label + ('（节选）' if excerpt else '') + '：' + (value[:maximum] if excerpt else value)
                if len('\n'.join([*lines,line])) <= max_chars:
                    lines.append(line)
                    return True
                return False
            for key, label in (('title','资料歌名'),('artist','资料艺人'),('album','资料专辑'),
                    ('genre','资料风格'),('language','资料语言'),('mood','人工情绪标签（非用户当前心情）')):
                append(label, values[key])
            lyrics = bool(not _NO_LYRICS.search(query)
                and (query.strip().casefold() in {'歌词','lyrics'} or _LYRICS.search(query)))
            included = lyrics and append('歌词原文（用户提供，未自动获取）', values['lyrics'], 240)
            append('资料备注', values['note'], 160)
            text = '\n'.join(lines)
            fragment = ContextFragment('music.reference.' + _hash([scope,identity])[:32], text,
                'setting', 'tls.music.library.reference', priority=68,
                expires_at=min(observed['expires_at'], now + 60))
            value = MusicReferenceContribution(fragment, observed['music_token'], generation, identity,
                scope_key(scope), bool(included), self._seal, self._fragment_token(fragment))
            return value if self.current(value, scope, snapshot) else None
        except Exception:
            # Optional reference failure never changes the valid Phone fact or
            # starts a fallback read from a different library/user/old plugin.
            return None

    def current(self, contribution, scope, snapshot):
        """Final synchronous worker proof; caller supplies a fresh loop snapshot."""
        try:
            if (type(contribution) is not MusicReferenceContribution or contribution._seal is not self._seal
                    or not self._resources() or contribution._fragment_token != self._fragment_token(contribution.fragment)):
                return False
            scope, now = private_scope(scope), self._now()
            observed = _observation(scope, snapshot, now)
            return (scope_key(scope) == contribution.scope_token
                and observed['music_token'] == contribution.music_token
                and now < contribution.fragment.expires_at
                and self.library.generation(scope) == contribution.library_generation
                and self._resources())
        except Exception:
            return False

    def stop(self):
        self.active = False
