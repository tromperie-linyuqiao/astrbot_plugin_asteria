"""Local app-entry candidates and durable cooldowns; never sends or calls an LLM.

The phone provider still owns polling and fresh observations. A host supplies
reviewed message pools and the existing single delivery owner. Preparing a
candidate reserves cooldowns; UNKNOWN keeps them, and only a definite failure
releases this candidate's reservation. A crash cannot turn the same report into
a second candidate. This module imports no phone/PC plugin business code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import time

from .journal import JournalConflict
from .models import EvidenceKind, Observation, canonical, plain, private_scope, scope_key

NAMESPACE = 'tls.native.phone_candidates.v1'
_PACKAGE = re.compile(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z')


def _number(value, name, maximum=253402300799):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('invalid ' + name)
    return float(value)


def _package(value):
    if not isinstance(value, str) or len(value) > 160 or not _PACKAGE.fullmatch(value):
        raise ValueError('invalid app package')
    return value


def _lines(value):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 128:
        raise ValueError('bounded message pool required')
    result = []
    for line in value:
        if (not isinstance(line, str) or not line.strip() or len(line) > 600
                or any(ord(char) < 32 and char not in '\t\r\n' for char in line)):
            raise ValueError('invalid app greeting text')
        if line.strip() not in result:
            result.append(line.strip())
    return result


def compile_rules(base, *, custom_lines=(), surprises=None, hour_gates=None):
    """Accept the old package->lines, package|line||line and surprises formats.

    Custom lines extend base pools; a nonempty surprises pool replaces its app
    pool. No placeholders or code are evaluated. Configuration is host-owned.
    """
    if not isinstance(base, dict) or len(base) > 128:
        raise ValueError('bounded app rule mapping required')
    pools = {_package(package): _lines(lines) for package, lines in base.items()}
    if not isinstance(custom_lines, (tuple, list)) or len(custom_lines) > 128:
        raise ValueError('bounded custom greeting lines required')
    for entry in custom_lines:
        if not isinstance(entry, str) or '|' not in entry or len(entry) > 12000:
            raise ValueError('invalid custom greeting rule')
        package, rest = entry.split('|', 1)
        package = _package(package.strip())
        additions = _lines([line.strip() for line in rest.split('||') if line.strip()])
        pools[package] = _lines(pools.get(package, []) + additions)
    surprises = {} if surprises is None else plain(surprises, 65536)
    if not isinstance(surprises, dict) or not isinstance(surprises.get('greetings', {}), dict):
        raise ValueError('invalid surprises library')
    for package, value in surprises.get('greetings', {}).items():
        lines = value.get('lines') if isinstance(value, dict) else value
        if lines == []:
            continue  # Existing empty override does not erase a reviewed pool.
        pools[_package(package)] = _lines(lines)
    hour_gates = {} if hour_gates is None else hour_gates
    if not isinstance(hour_gates, dict) or not set(hour_gates) <= set(pools):
        raise ValueError('hour gates require configured apps')
    result = {}
    for package, lines in pools.items():
        hours = hour_gates.get(package)
        if hours is not None and (not isinstance(hours, (list, tuple)) or len(hours) != 2
                or any(type(hour) is not int or not 0 <= hour <= 23 for hour in hours)
                or hours[0] == hours[1]):
            raise ValueError('invalid app hour window')
        result[package] = {'lines': lines, 'hours': list(hours) if hours is not None else None}
    return plain(result, 65536)


class NativePhoneCandidatePolicy:
    """One small checkpoint per complete private scope, in the TLS journal.

    Synchronous SQLite work belongs off the async event loop. ``authorize`` must
    validate the host's genuine private identity lease; package/device/user IDs
    in a phone payload never choose a destination. The caller must reauthorize
    and honor candidate expiry in its existing delivery owner before sending.
    """
    def __init__(self, journal, rules, *, authorize, clock=time.time,
                 app_cooldown_seconds=7200, shared_cooldown_seconds=600,
                 max_entry_age_seconds=180, candidate_ttl_seconds=45,
                 timezone_offset_minutes=480, source_ids=('phone.device',),per_app_policy=None):
        if not callable(authorize):
            raise ValueError('private scope authorizer required')
        self.journal, self.authorize, self.clock = journal, authorize, clock
        self.app_cooldown = _number(app_cooldown_seconds, 'app cooldown', 86400)
        self.shared_cooldown = _number(shared_cooldown_seconds, 'shared cooldown', 86400)
        self.max_entry_age = _number(max_entry_age_seconds, 'entry age', 600)
        self.ttl = _number(candidate_ttl_seconds, 'candidate TTL', 300)
        if self.ttl == 0:
            raise ValueError('positive candidate TTL required')
        if type(timezone_offset_minutes) is not int or not -720 <= timezone_offset_minutes <= 840:
            raise ValueError('invalid timezone offset')
        self.zone = timezone(timedelta(minutes=timezone_offset_minutes))
        if not isinstance(source_ids, (tuple, list)) or not source_ids or any(not isinstance(s, str) for s in source_ids):
            raise ValueError('explicit phone sources required')
        self.sources = frozenset(source_ids)
        self.active = True
        self.metrics = dict(rule_compiles=0, rule_cache_hits=0, llm_calls=0, sends=0)
        self._rules_hash = None
        self.configure(rules,per_app_policy=per_app_policy)

    def configure(self, rules, *, custom_lines=(), surprises=None, hour_gates=None,per_app_policy=None):
        inputs = plain([rules, list(custom_lines), surprises, hour_gates], 65536)
        policies={}
        if per_app_policy is not None:
            if not isinstance(per_app_policy,dict) or len(per_app_policy)>128:raise ValueError('bounded per-App policy required')
            for package,value in per_app_policy.items():
                package=_package(package)
                if (not isinstance(value,dict) or set(value)!={'cooldown_seconds','priority','rule_id'}
                        or type(value['priority']) is not int or not 0<=value['priority']<=100
                        or not isinstance(value['rule_id'],str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}',value['rule_id'])):
                    raise ValueError('closed per-App policy required')
                policies[package]=dict(value,cooldown_seconds=max(self.app_cooldown,
                    _number(value['cooldown_seconds'],'per-App cooldown',86400)))
            inputs.append(policies)
            inputs=plain(inputs,65536)
        digest = hashlib.sha256(canonical(inputs).encode()).hexdigest()
        if digest == self._rules_hash:
            self.metrics['rule_cache_hits'] += 1
            return False
        compiled = compile_rules(rules, custom_lines=custom_lines, surprises=surprises, hour_gates=hour_gates)
        self.rules,self.per_app_policy,self._rules_hash=compiled,policies,digest
        self.metrics['rule_compiles'] += 1
        return True

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize(scope) is not True:
            raise PermissionError('native phone scope unavailable')
        return scope

    def _load(self, db, scope, now):
        row = db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                         (NAMESPACE, 'state', scope_key(scope))).fetchone()
        value = json.loads(row['data']) if row else dict(schema=1, last_clock=now, devices={}, apps={},
                                                        candidates={}, shared_at=None)
        if value.get('schema') != 1:
            raise ValueError('unsupported native phone checkpoint')
        if now < value['last_clock']:
            raise JournalConflict('phone candidate clock moved backwards')
        return value, row['revision'] if row else 0

    def _save(self, db, scope, state, revision, now):
        self._scope(scope)
        if not revision and db.execute('SELECT count(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
            raise ValueError('journal checkpoint capacity reached')
        state['last_clock'] = now
        db.execute('''INSERT INTO checkpoints VALUES(?,?,?,?,?,?)
            ON CONFLICT(namespace,key,scope) DO UPDATE SET revision=excluded.revision,
            updated=excluded.updated,data=excluded.data''',
            (NAMESPACE, 'state', scope_key(scope), revision+1, now, canonical(plain(state, 131072))))

    def observe(self, observation, *, quiet_until=0, shared_last_sent_at=None):
        return self._evaluate(observation,quiet_until=quiet_until,shared_last_sent_at=shared_last_sent_at,write=True)

    def preview(self,observation,*,quiet_until=0,shared_last_sent_at=None):
        """The same eligibility/rotation decision, without changing a checkpoint."""
        result=self._evaluate(observation,quiet_until=quiet_until,shared_last_sent_at=shared_last_sent_at,write=False)
        candidate=result['candidate']
        return dict(result,allowed=candidate is not None,text=candidate['text'] if candidate else None)

    def _evaluate(self,observation,*,quiet_until,shared_last_sent_at,write):
        if not isinstance(observation, Observation):
            raise ValueError('typed phone Observation required')
        scope = self._scope(observation.scope)
        now = _number(self.clock(), 'clock')
        quiet_until = _number(quiet_until, 'quiet until')
        external_shared = None if shared_last_sent_at is None else _number(shared_last_sent_at, 'shared last sent')
        if (observation.source_id not in self.sources or observation.observation_type != 'device.app'
                or observation.evidence_kind != EvidenceKind.REAL_OBSERVATION
                or not observation.valid_at(now) or observation.observed_at > now):
            return {'state': 'rejected', 'reason': 'not_a_current_observed_app', 'candidate': None}
        payload = observation.payload
        if not observation.device_id or not isinstance(payload, dict):
            return {'state': 'rejected', 'reason': 'device_or_app_missing', 'candidate': None}
        package = payload.get('foreground_package')
        if package not in (None, ''):
            package = _package(package)
        else:
            package = ''  # An explicit cleared foreground permits a later entry.
        signature = hashlib.sha256(canonical([package, observation.observed_at]).encode()).hexdigest()
        with self.journal._transaction() if write else self.journal._lock as access:
            self.journal._ensure_open()
            db=access if write else self.journal._db
            self._scope(scope)
            state, revision = self._load(db, scope, now)
            for candidate in state['candidates'].values():
                if candidate['state'] == 'prepared' and candidate['expires_at'] <= now:
                    # Keep the reservation: absence of a callback is not proof
                    # that the platform was never called. Expired proposals
                    # become reclaimable bookkeeping, never retry permission.
                    candidate.update(state='expired', revision=candidate['revision']+1, finished_at=now)
            previous = state['devices'].get(observation.device_id)
            if previous and observation.observed_at <= previous['observed_at']:
                if observation.observed_at == previous['observed_at'] and signature != previous['signature']:
                    raise JournalConflict('same app observation time has conflicting package')
                self._scope(scope)
                return {'state': 'ignored', 'reason': 'duplicate_or_older_observation', 'candidate': None}
            if not previous and len(state['devices']) >= 32:
                raise ValueError('phone device capacity reached')
            state['devices'][observation.device_id] = dict(package=package,
                observed_at=observation.observed_at, signature=signature)
            reason = None
            if previous and previous['package'] == package:
                reason = 'same_foreground_app'
            elif now - observation.observed_at > self.max_entry_age:
                reason = 'entry_too_old'
            elif package not in self.rules:
                reason = 'unconfigured_app'
            elif quiet_until > now:
                reason = 'explicit_quiet'
            rule = self.rules.get(package)
            if not reason and rule['hours'] is not None:
                start, end = rule['hours']; hour = datetime.fromtimestamp(now, self.zone).hour
                if not (start <= hour < end if start < end else hour >= start or hour < end):
                    reason = 'outside_app_hours'
            app_key = hashlib.sha256(canonical([observation.device_id, package]).encode()).hexdigest()
            app = state['apps'].get(app_key, {'at': None, 'recent': [], 'count': 0})
            shared = max((value for value in (state['shared_at'], external_shared) if value is not None), default=None)
            app_policy=self.per_app_policy.get(package)
            cooldown=app_policy['cooldown_seconds'] if app_policy else self.app_cooldown
            if not reason and app['at'] is not None and now - app['at'] < cooldown:
                reason = 'app_cooldown'
            if not reason and shared is not None and now - shared < self.shared_cooldown:
                reason = 'shared_cooldown'
            if reason:
                if write:self._save(db, scope, state, revision, now)
                self._scope(scope)
                return {'state': 'suppressed', 'reason': reason, 'candidate': None}
            if app_key not in state['apps'] and len(state['apps']) >= 256:
                raise ValueError('app cooldown capacity reached')
            candidates = state['candidates']
            if len(candidates) >= 64:
                terminal = sorted((item for item in candidates.values() if item['state'] != 'prepared'
                    and not (item.get('kind') == 'music' and item['state'] == 'unknown')),
                                  key=lambda item: (item['created_at'], item['id']))
                if not terminal:
                    raise ValueError('unresolved phone candidate capacity reached')
                del candidates[terminal[0]['id']]
            fresh = [text for text in rule['lines'] if text not in app['recent']]
            text = fresh[0] if fresh else rule['lines'][app['count'] % len(rule['lines'])]
            identity = hashlib.sha256(canonical(['tls.phone.app_entry.v1', scope_key(scope),
                observation.device_id, observation.observed_at, package]).encode()).hexdigest()
            candidate = dict(id=identity, scope=scope, session=scope['session_id'], text=text,
                source_id=observation.source_id, observation_type='device.app', evidence_kind='real_observation',
                device_id=observation.device_id, package=package, observed_at=observation.observed_at,
                created_at=now, expires_at=min(now+self.ttl, observation.expires_at),
                state='prepared', revision=1, app_key=app_key, previous_app_at=app['at'],
                previous_shared_at=state['shared_at'], delivery_owner_required=True)
            if app_policy:candidate.update(priority=app_policy['priority'],rule_id=app_policy['rule_id'])
            app['at'] = now; state['apps'][app_key] = app
            state['shared_at'] = now; candidates[identity] = candidate
            if write:self._save(db, scope, state, revision, now)
            self._scope(scope)
            return {'state': 'candidate', 'reason': 'fresh_app_entry', 'candidate': plain(candidate)}

    def observe_music(self, observation, *, quiet_until=0, shared_last_sent_at=None,
                      music_cooldown_seconds=2700, enabled=True):
        """A reliable media-session change, not a poll, resume or taste claim.

        Music keeps its own bounded device high-water marks in this same
        checkpoint. Reservations and finish/UNKNOWN use the original app and
        shared cooldown maps; no second queue, database or timer is created.
        """
        if not isinstance(observation, Observation):
            raise ValueError('typed phone Observation required')
        scope = self._scope(observation.scope)
        now = _number(self.clock(), 'clock')
        quiet_until = _number(quiet_until, 'quiet until')
        cooldown = _number(music_cooldown_seconds, 'music cooldown', 86400)
        external_shared = None if shared_last_sent_at is None else _number(shared_last_sent_at, 'shared last sent')
        if type(enabled) is not bool:
            raise ValueError('music enablement must be a boolean')
        rejected = lambda reason: {'state': 'rejected', 'reason': reason, 'candidate': None}
        if (observation.source_id != 'phone.music' or observation.observation_type != 'music'
                or observation.evidence_kind != EvidenceKind.REAL_OBSERVATION
                or not observation.valid_at(now) or observation.observed_at > now
                or observation.received_at > now):
            return rejected('not_a_current_observed_music')
        if now - observation.observed_at > self.max_entry_age:
            return rejected('music_observation_too_old')
        payload = observation.payload
        user = payload.get('user_state') if isinstance(payload, dict) else None
        event = payload.get('event_type') if isinstance(payload, dict) else None
        if (not observation.device_id or not isinstance(user, dict)
                or user.get('source') != 'media_session' or user.get('reliable') is not True
                or type(user.get('playing')) is not bool
                or event not in {'music_playing', 'music_paused', 'music_stopped'}
                or user['playing'] is not (event == 'music_playing')
                or user.get('device_id', observation.device_id) != observation.device_id
                or user.get('state', event.removeprefix('music_')) != event.removeprefix('music_')):
            return rejected('reliable_music_identity_required')
        info = payload.get('song_info')
        if not isinstance(info, dict): info = {}
        def label(value, maximum):
            if value in (None, ''): return ''
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError('bounded media metadata required')
            return ' '.join(value.split())
        title, artist = label(info.get('title'), 160), label(info.get('artist'), 160)
        if user['playing'] and not title:
            return rejected('music_title_required')
        package = label(user.get('package'), 160)
        if package: package = _package(package)
        track_id = label(user.get('track_id'), 160)
        supplied_track = hashlib.sha256(canonical([observation.device_id, package, track_id,
            title, artist]).encode()).hexdigest() if title else None
        with self.journal._transaction() as db:
            self.journal._ensure_open(); self._scope(scope)
            state, revision = self._load(db, scope, now)
            devices = state.setdefault('music_devices', {})
            if not isinstance(devices, dict) or len(devices) > 32:
                raise ValueError('bounded music device checkpoint required')
            previous = devices.get(observation.device_id)
            # Explicit pause/stop may omit metadata. Retain only this device's
            # known track so a later resume cannot masquerade as a new song.
            track = supplied_track or (previous.get('track_key') if previous else None)
            signature = hashlib.sha256(canonical([track, user['playing']]).encode()).hexdigest()
            if previous and observation.observed_at <= previous['observed_at']:
                if observation.observed_at == previous['observed_at'] and signature != previous['signature']:
                    raise JournalConflict('same music observation time has conflicting identity')
                return {'state': 'ignored', 'reason': 'duplicate_or_older_observation', 'candidate': None}
            if not previous and len(devices) >= 32:
                raise ValueError('music device capacity reached')
            devices[observation.device_id] = dict(observed_at=observation.observed_at,
                signature=signature, track_key=track, playing=user['playing'])
            reason = None
            if not user['playing']: reason = 'music_not_playing'
            elif not previous or not previous.get('track_key'): reason = 'music_baseline'
            elif previous['track_key'] == track: reason = 'same_music_track'
            elif not enabled: reason = 'music_disabled'
            elif quiet_until > now: reason = 'explicit_quiet'
            app_key = hashlib.sha256(canonical(['tls.phone.music.device.v1', observation.device_id]).encode()).hexdigest()
            app = state['apps'].get(app_key, {'at': None, 'recent': [], 'count': 0})
            shared = max((value for value in (state['shared_at'], external_shared) if value is not None), default=None)
            if not reason and app['at'] is not None and now - app['at'] < cooldown:
                reason = 'music_cooldown'
            if not reason and shared is not None and now - shared < self.shared_cooldown:
                reason = 'shared_cooldown'
            if reason:
                self._save(db, scope, state, revision, now)
                return {'state': 'suppressed', 'reason': reason, 'candidate': None}
            if app_key not in state['apps'] and len(state['apps']) >= 256:
                raise ValueError('app cooldown capacity reached')
            candidates = state['candidates']
            for candidate in candidates.values():
                if candidate['state'] == 'prepared' and candidate['expires_at'] <= now:
                    candidate.update(state='expired', revision=candidate['revision']+1, finished_at=now)
            if len(candidates) >= 64:
                terminal = sorted((item for item in candidates.values()
                    if item['state'] in {'acked', 'failed', 'expired'}),
                    key=lambda item: (item['created_at'], item['id']))
                if not terminal: raise ValueError('unresolved phone candidate capacity reached')
                del candidates[terminal[0]['id']]
            credit = '（' + artist + '）' if artist else ''
            lines = [f'你换到《{title}》{credit}了，我陪你听一会儿。',
                f'现在是《{title}》{credit}。这首就一起听吧。',
                f'播放器换成了《{title}》{credit}，想安静听也没关系。']
            offset = app['count'] % len(lines)
            ordered = lines[offset:] + lines[:offset]
            text = next((line for line in ordered if line not in app['recent']), ordered[0])
            identity = hashlib.sha256(canonical(['tls.phone.music.track_change.v1', scope_key(scope),
                observation.device_id, observation.observed_at, track]).encode()).hexdigest()
            candidate = dict(id=identity, kind='music', source_kind='media_session_track_change',
                scope=scope, session=scope['session_id'], text=text, source_id='phone.music',
                observation_type='music', evidence_kind='real_observation', device_id=observation.device_id,
                package=package, track_id=track_id, track_key=track, title=title, artist=artist,
                observed_at=observation.observed_at, created_at=now,
                expires_at=min(now+self.ttl, observation.expires_at), state='prepared', revision=1,
                app_key=app_key, previous_app_at=app['at'], previous_shared_at=state['shared_at'],
                music_cooldown_seconds=cooldown, delivery_owner_required=True)
            app['at'] = now; state['apps'][app_key] = app
            state['shared_at'] = now; candidates[identity] = candidate
            self._save(db, scope, state, revision, now)
            return {'state': 'candidate', 'reason': 'fresh_music_track_change', 'candidate': plain(candidate)}

    def finish(self, scope, candidate_id, outcome, *, expected_revision=None):
        """ACK means existing delivery-owner evidence; UNKNOWN never releases cooldown.

        ``failed`` is only a definitely-not-dispatched outcome, never a timeout
        or connection loss after SDK entry. A late ACK can reconcile UNKNOWN.
        """
        scope = self._scope(scope)
        if outcome not in {'acked', 'unknown', 'failed'}:
            raise ValueError('explicit delivery outcome required')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError('invalid candidate revision')
        now = _number(self.clock(), 'clock')
        with self.journal._transaction() as db:
            state, revision = self._load(db, scope, now)
            candidate = state['candidates'].get(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if expected_revision is not None and candidate['revision'] != expected_revision:
                raise JournalConflict('stale phone candidate revision')
            if candidate['state'] == outcome:
                return plain(candidate)
            if candidate['state'] != 'prepared' and not (candidate['state'] in {'unknown', 'expired'} and outcome == 'acked'):
                raise JournalConflict('terminal phone candidate outcome conflict')
            app = state['apps'][candidate['app_key']]
            if outcome == 'failed':
                if app['at'] == candidate['created_at']:
                    app['at'] = candidate['previous_app_at']
                if state['shared_at'] == candidate['created_at']:
                    state['shared_at'] = candidate['previous_shared_at']
            elif candidate['state'] == 'prepared':
                app['recent'] = (app['recent'] + [candidate['text']])[-3:]
                app['count'] += 1
            candidate.update(state=outcome, revision=candidate['revision']+1, finished_at=now)
            self._save(db, scope, state, revision, now)
            return plain(candidate)

    def diagnostics(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            row = self.journal._db.execute('SELECT data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                                           (NAMESPACE, 'state', scope_key(scope))).fetchone()
            state = json.loads(row['data']) if row else {'devices': {}, 'apps': {}, 'candidates': {}}
        counts = {outcome: sum(row['state'] == outcome for row in state['candidates'].values())
                  for outcome in ('prepared', 'acked', 'unknown', 'failed', 'expired')}
        return dict(active=self.active, configured_apps=len(self.rules), devices=len(state['devices']),
                    cooldown_keys=len(state['apps']), candidate_states=counts, **self.metrics)

    def close(self):
        self.active = False  # The host still owns and closes the shared journal.
