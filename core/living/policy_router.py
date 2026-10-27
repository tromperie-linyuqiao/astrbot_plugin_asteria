"""Scoped, feature-specific ownership for bounded synchronous pure policies.

One engine owns receipts, CAS, cached generations, OS locks, comparison stats
and revocation fences. Feature wrappers supply only binding/operations/denials;
no scheduler, sender, source cache or provider state belongs here.
"""
from __future__ import annotations

import asyncio
import copy
import os
import re
import threading
from pathlib import Path

from .journal import JournalConflict
from .models import private_scope, scope_key

NAMESPACE = 'tls.ownership'
MODES = frozenset({'legacy', 'shadow', 'tls'})


class CoordinatorBusy(RuntimeError):
    pass


class _ProcessLock:
    """OS lock survives neither a normal close nor a crashed coordinator."""
    def __init__(self, path):
        self.file = open(path, 'a+b')
        try:
            self.file.seek(0, 2)
            if not self.file.tell():
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise CoordinatorBusy('policy coordinator already owns this feature journal') from None

    def close(self):
        if self.file.closed:
            return
        self.file.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def _validation(value):
    if not isinstance(value, dict) or set(value) != {
            'independent_passed', 'differential_passed', 'suite_sha256'}:
        raise ValueError('a bounded validation receipt is required')
    if any(type(value[key]) is not int or not 0 < value[key] <= 10000000
           for key in ('independent_passed', 'differential_passed')):
        raise ValueError('validation counts must be positive integers')
    if not isinstance(value['suite_sha256'], str) or not re.fullmatch(
            '[a-f0-9]{64}', value['suite_sha256']):
        raise ValueError('validation receipt digest required')
    return dict(value)


class ScopedPolicyRouter:
    def __init__(self, journal, *, feature, operations, denied, authorized_scope,
                 legacy_owner, native_owner, lock_suffix, environment='host', max_scopes=256,
                 _retired_snapshot=False):
        if not isinstance(feature, str) or not re.fullmatch('[a-zA-Z0-9_.:-]{1,128}', feature):
            raise ValueError('invalid pure-policy feature')
        if not isinstance(operations, dict) or not operations or any(
                not isinstance(k, str) or not callable(v) for k, v in operations.items()):
            raise ValueError('registered pure operations required')
        if not callable(denied) or not callable(authorized_scope):
            raise TypeError('synchronous policy authority and denial callbacks required')
        if not re.fullmatch(r'\.[a-z0-9.-]+\.lock', lock_suffix):
            raise ValueError('feature-specific lock suffix required')
        self.feature, self.operations, self._deny = feature, operations, denied
        self.legacy_owner, self.native_owner = legacy_owner, native_owner
        if environment not in {'host', 'isolated'}:
            raise ValueError('unknown coordinator environment')
        self.journal = journal
        self.authorized_scope, self.environment = authorized_scope, environment
        self.max_scopes = min(max(int(max_scopes), 1), 256)
        self._lock = threading.Condition(threading.RLock())
        if type(_retired_snapshot) is not bool:
            raise TypeError('retired ownership snapshot must be explicit')
        self._retired_snapshot = _retired_snapshot
        self._closed = _retired_snapshot
        self._changing = set()
        self._records, self._stats = {}, {}
        # A stopped recovery guard retains ownership metadata only. It cannot
        # decide/transition or compete for a live coordinator's OS lock.
        self._process = None if _retired_snapshot else _ProcessLock(Path(journal.path).with_suffix(lock_suffix))
        try:
            for row in journal.ownership_records():
                if row['key'] != self.feature:
                    continue  # Other future features have their own controllers.
                data = row['data']
                scope = private_scope(data['scope'])
                key = scope_key(scope)
                if (type(data.get('schema_version')) is not int or data.get('schema_version') != 1
                        or type(data.get('generation')) is not int or data.get('feature') != self.feature
                        or row['scope_hash'] != key or data.get('generation') != row['revision']
                        or data.get('mode') not in MODES):
                    raise ValueError('invalid persisted policy ownership')
                if data['mode'] == 'tls':
                    _validation(data.get('validation'))
                    if environment != 'isolated':
                        raise PermissionError('native production cutover has not been accepted')
                if len(self._records) >= self.max_scopes:
                    raise RuntimeError('policy ownership capacity reached')
                self._records[key] = copy.deepcopy(data)
                self._stats[key] = self._empty_stats()
        except BaseException:
            if self._process is not None:
                self._process.close()
            raise

    @staticmethod
    def _empty_stats():
        return {'compared': 0, 'mismatched': 0, 'native_errors': 0,
                'legacy_decisions': 0, 'native_decisions': 0, 'denied': 0}

    def unavailable(self, operation):
        if operation not in self.operations:
            raise ValueError('unknown pure-policy operation')
        return self._deny(operation)

    def _authorized(self, scope, guard=None):
        try:
            return not self._closed and bool(self.authorized_scope(scope)) and (guard is None or bool(guard()))
        except Exception:
            return False

    def snapshot(self, scope):
        scope = private_scope(scope)
        key = scope_key(scope)
        with self._lock:
            record = self._records.get(key)
            return {'feature': self.feature, 'mode': record['mode'] if record else 'legacy',
                    'generation': record['generation'] if record else 0,
                    'owner': self.native_owner if record and record['mode'] == 'tls' else self.legacy_owner,
                    'transitioning': key in self._changing,
                    'statistics': dict(self._stats.get(key, self._empty_stats()))}

    def has_native_session(self, session):
        with self._lock:
            return any(record['mode'] == 'tls' and record['scope']['session_id'] == session
                       for record in self._records.values())

    def has_nonlegacy_bindings(self):
        with self._lock:
            return any(record['mode'] != 'legacy' for record in self._records.values())

    def has_nonlegacy_session(self, session):
        with self._lock:
            return any(record['mode'] != 'legacy' and record['scope']['session_id'] == session
                       for record in self._records.values())

    def native_sessions(self):
        with self._lock:
            return tuple({record['scope']['session_id'] for record in self._records.values()
                          if record['mode'] == 'tls'})

    def _can_resume(self, previous, session=None, *, all_nonlegacy=False):
        if Path(self.journal.path).resolve() != Path(previous.journal.path).resolve():
            return False
        with previous._lock:
            previous_feature = getattr(previous, 'feature', None)
            if previous_feature is None:
                # The original frequency router predates the generic .feature
                # attribute. Its validated durable records still identify the
                # feature; no class-name guess or empty-state release is allowed.
                if not previous._records or any(not isinstance(value, dict)
                        or value.get('feature') != self.feature for value in previous._records.values()):
                    return False
            elif previous_feature != self.feature:
                return False
            prior = {key: copy.deepcopy(value) for key, value in previous._records.items()
                     if (value['mode'] != 'legacy' if all_nonlegacy else value['mode'] == 'tls')
                     and (session is None or value['scope']['session_id'] == session)}
        with self._lock:
            if self._closed and not self._retired_snapshot:
                return False
            return all((new := self._records.get(key)) is not None
                       and new['generation'] >= old['generation']
                       and (new['generation'] != old['generation'] or new['mode'] == old['mode'])
                       for key, old in prior.items())

    def can_resume_controller(self, previous):
        return self._can_resume(previous, all_nonlegacy=True)

    async def transition(self, scope, mode, *, expected_generation, validation=None):
        """CAS handoff of pure decisions only; no legacy state is modified.

        Receipts are maintainer-supplied evidence, not a replacement for review.
        Cancellation waits for the bounded transaction so authority is knowable.
        """
        task = asyncio.create_task(asyncio.to_thread(self._transition, scope, mode,
            expected_generation, validation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    def _transition(self, scope, mode, expected, validation):
        scope = private_scope(scope)
        if mode not in MODES or type(expected) is not int or expected < 0:
            raise ValueError('invalid ownership transition')
        key = scope_key(scope)
        with self._lock:
            if self._closed:
                raise RuntimeError('policy coordinator closed')
            if key in self._changing:
                raise JournalConflict('policy transition in progress')
            previous = self._records.get(key)
            generation = previous['generation'] if previous else 0
            if expected != generation:
                raise JournalConflict('policy generation changed')
            if previous is None and len(self._records) >= self.max_scopes:
                raise RuntimeError('policy ownership capacity reached')
            if mode != 'legacy' and not self._authorized(scope):
                raise PermissionError('fresh private scope binding required')
            if mode == 'tls':
                if self.environment != 'isolated':
                    raise PermissionError('native production cutover has not been accepted')
                validation = _validation(validation)
                stats = self._stats.get(key, self._empty_stats())
                if (not previous or previous['mode'] != 'shadow' or not stats['compared']
                        or stats['mismatched'] or stats['native_errors']):
                    raise ValueError('clean current-process shadow comparison required')
            elif validation is not None:
                validation = _validation(validation)
            data = {'schema_version': 1, 'feature': self.feature, 'scope': scope,
                    'mode': mode, 'generation': generation + 1,
                    'validation': validation}
            self._changing.add(key)
        try:
            def authorized():
                return not self._closed and (mode == 'legacy' or self._authorized(scope))
            self.journal.put(NAMESPACE, self.feature, scope, data,
                             expected_revision=generation, authorize=authorized)
            with self._lock:
                self._records[key] = data
                self._stats[key] = self._empty_stats()
        finally:
            with self._lock:
                self._changing.discard(key)
                self._lock.notify_all()
        return self.snapshot(scope)

    def evaluate(self, operation, values, legacy, *, scope=None, scope_resolver=None,
                 session=None, identity_validator=None, guard=None, incomplete_legacy=False):
        """Synchronously select a pure implementation without journal/source IO.

        Resolvers and guards are trusted synchronous metadata-only callbacks.
        Existing nonlegacy session bindings never silently fall back on lease loss.
        """
        if operation not in self.operations or not isinstance(values, dict):
            raise ValueError('unknown pure-policy operation')
        with self._lock:
            if self._closed:
                return self._deny(operation)
            try:
                resolved = scope_resolver() if scope_resolver is not None else scope
                key = scope_key(private_scope(resolved)) if resolved is not None else None
            except Exception:
                if not incomplete_legacy:
                    return self._deny(operation)
                key, resolved = None, None
            record = self._records.get(key)
            session_records = [item for item in self._records.values()
                               if item['scope']['session_id'] == session and item['mode'] != 'legacy']
            if record is None and session_records:
                return self._deny(operation)
            if key in self._changing:
                return self._deny(operation)
            mode = record['mode'] if record else 'legacy'
            stats = self._stats.setdefault(key, self._empty_stats()) if record else None
            if mode == 'legacy':
                if stats is not None:
                    stats['legacy_decisions'] += 1
                return legacy(**values)
            def authorized():
                try:
                    identity = identity_validator is None or bool(identity_validator(resolved))
                except Exception:
                    identity = False
                return identity and self._authorized(resolved, guard)
            if not authorized():
                stats['denied'] += 1
                return self._deny(operation)
            if mode == 'shadow':
                authoritative = legacy(**copy.deepcopy(values))
                try:
                    candidate = self.operations[operation](**copy.deepcopy(values))
                    stats['compared'] += 1
                    stats['mismatched'] += int(candidate != authoritative)
                except Exception:
                    stats['native_errors'] += 1
                stats['legacy_decisions'] += 1
                if not authorized():
                    stats['denied'] += 1
                    return self._deny(operation)
                return authoritative
            try:
                result = self.operations[operation](**copy.deepcopy(values))
            except Exception:
                stats['native_errors'] += 1
                return self._deny(operation)
            stats['native_decisions'] += 1
            if not authorized():
                stats['denied'] += 1
                return self._deny(operation)
            return result

    def stop(self):
        with self._lock:
            self._closed = True

    def close(self):
        self.stop()
        with self._lock:
            self._lock.wait_for(lambda: not self._changing)
            if self._process is not None:
                self._process.close()
