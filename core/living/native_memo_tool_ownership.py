"""Memo-tool ownership and occurrence routing in the existing LivingJournal.

This coordinator does not patch PC, register a tool, create a private session,
issue a lease, or prove an old coroutine has drained. The integration supplies
synchronous current-scope/source/lease proofs and exact old/native drain proofs.
A persistent claim is a no-legacy routing fence, never a claim of note success.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import json
import math
import re

from .journal import JournalConflict, LivingJournal
from .models import canonical, private_scope, scope_key

OWNERS = 'tls.native.memo_tool.owners.v1'
CLAIMS = 'tls.native.memo_tool.claims.v1'
FEATURE = 'tls.memo.tool.nonreminder.v1'
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_REQUEST = re.compile(r'memo_[a-f0-9]{64}\Z')
_SCOPE_KEYS = frozenset(('platform', 'bot_id', 'user_id', 'character_id', 'session_id', 'private'))
MAX_GENERATION = 2**53 - 1


def _scope(value):
    if type(value) is not dict or set(value) != _SCOPE_KEYS or value.get('private') is not True:
        raise ValueError('complete exact private memo scope required')
    normalized = private_scope(value)
    if normalized != value or any(type(value[key]) is not str for key in _SCOPE_KEYS - {'private'}):
        raise ValueError('normalized complete private memo scope required')
    return normalized


def _generation(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_GENERATION:
        raise ValueError('exact bounded memo ownership generation required')
    return value


def _hash(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ValueError('lowercase memo binding fingerprint required')
    return value


def _request(value):
    if type(value) is not str or _REQUEST.fullmatch(value) is None:
        raise ValueError('stable native memo occurrence required')
    return value


class NativeMemoToolOwnership:
    """CAS state plus permanent claims, sharing the note transaction's database.

    Callback contracts: authorize_scope(scope), source_current(scope, binding_sha256),
    lease_current(scope), drained(scope, side) return exact bool synchronously.
    binding_sha256 is the exact persisted owner fingerprint, the proposed new
    fingerprint during prepare, or None only for an unclaimed legacy scope.
    side is legacy for activation and native for rollback. Returning True is
    an integration proof; this module cannot derive it from a name or flag.
    """
    def __init__(self, journal, *, authorize_scope, source_current, lease_current, drained):
        if not isinstance(journal, LivingJournal) or any(not callable(callback) for callback in
                (authorize_scope, source_current, lease_current, drained)):
            raise ValueError('shared journal and synchronous live proofs required')
        self.journal = journal
        self.authorize_scope, self.source_current = authorize_scope, source_current
        self.lease_current, self.drained = lease_current, drained
        self._bindings = (journal, authorize_scope, source_current, lease_current, drained)
        self._journal_resources = (journal._db, journal._lock, journal.path)
        self.active = True

    def stop(self):
        # RAM revocation only. Never erase owner/claim records or restore PC.
        self.active = False

    def _resources(self):
        return (self.active and all(a is b for a, b in zip(self._bindings,
            (self.journal, self.authorize_scope, self.source_current, self.lease_current, self.drained)))
            and self.journal._db is self._journal_resources[0]
            and self.journal._lock is self._journal_resources[1]
            and self.journal.path == self._journal_resources[2]
            and self.journal._closed is False)

    @staticmethod
    def _proof(callback, *args):
        value = callback(*args)
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            raise PermissionError('synchronous exact memo proof required')
        return value is True

    def _authorized(self, scope):
        if not self._resources() or not self._proof(self.authorize_scope, dict(scope)) or not self._resources():
            raise PermissionError('memo ownership scope unavailable')

    def _available(self, scope, *, binding_sha256=None, side=None):
        self._authorized(scope)
        if (not self._proof(self.source_current, dict(scope), binding_sha256)
                or not self._proof(self.lease_current, dict(scope))
                or side is not None and not self._proof(self.drained, dict(scope), side)):
            raise PermissionError('memo ownership source lease or drain unavailable')
        self._authorized(scope)

    def _now(self):
        value = self.journal.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 4102444800:
            raise RuntimeError('finite memo ownership clock required')
        return float(value)

    def _read_owner(self, db, scope):
        row = db.execute('SELECT revision,updated,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                         (OWNERS, 'owner', scope_key(scope))).fetchone()
        if row is None:
            return None
        value = json.loads(row['data'])
        expected = {'schema', 'feature', 'scope', 'state', 'generation', 'transition_id', 'binding_sha256', 'ever_native'}
        if (type(value) is not dict or set(value) != expected or type(value['schema']) is not int
                or value['schema'] != 1 or value['feature'] != FEATURE or value['scope'] != scope
                or value['state'] not in {'pending', 'native', 'closed', 'legacy'}
                or type(value['ever_native']) is not bool):
            raise RuntimeError('invalid persistent memo owner')
        _generation(value['generation'], positive=True)
        _hash(value['transition_id']); _hash(value['binding_sha256'])
        if (type(row['revision']) is not int or row['revision'] != value['generation']
                or value['state'] == 'native' and value['ever_native'] is not True):
            raise RuntimeError('invalid memo owner revision')
        return value

    def _claim(self, db, scope, request_id):
        row = db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                         (CLAIMS, request_id, scope_key(scope))).fetchone()
        if row is None:
            return None
        value = json.loads(row['data'])
        expected = {'schema', 'feature', 'scope', 'request_id', 'generation', 'transition_id', 'binding_sha256', 'state'}
        if (type(value) is not dict or set(value) != expected or type(value['schema']) is not int
                or value['schema'] != 1 or value['feature'] != FEATURE or value['scope'] != scope
                or value['request_id'] != request_id or value['state'] != 'claimed'
                or type(row['revision']) is not int or row['revision'] != 1):
            raise RuntimeError('invalid persistent memo occurrence claim')
        _generation(value['generation'], positive=True)
        _hash(value['transition_id']); _hash(value['binding_sha256'])
        return value

    def _write(self, db, namespace, key, scope, data, revision):
        previous = db.execute('SELECT revision FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                              (namespace, key, scope_key(scope))).fetchone()
        if previous is None and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
            raise RuntimeError('checkpoint capacity reached; memo routing history retained')
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
                   (namespace, key, scope_key(scope), revision, self._now(), canonical(data)))

    def _audit(self, db, scope, state, generation, transition_id):
        db.execute('INSERT INTO audit(scope,occurred,event_type,entity_id,status,details) VALUES(?,?,?,?,?,?)',
                   (scope_key(scope), self._now(), 'memo_tool_owner', transition_id, state,
                    canonical(dict(generation=generation, feature=FEATURE))))
        db.execute('DELETE FROM audit WHERE seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT ?)',
                   (self.journal.max_audit,))

    def owner_for_scope(self, scope):
        """Exact callback shape expected by NativeMemoTools; never writes."""
        scope = _scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            self._authorized(scope)
            value = self._read_owner(self.journal._db, scope)
            generation = value['generation'] if value else 0
            state = value['state'] if value else 'legacy'
            if state in {'legacy', 'native'}:
                try:
                    self._available(scope, binding_sha256=value['binding_sha256'] if value else None)
                except PermissionError:
                    state = 'closed'
            else:
                state = 'closed'
            self._authorized(scope)
            return dict(mode=state, generation=generation)

    def inspect(self, scope):
        scope = _scope(scope)
        with self.journal._lock:
            self.journal._ensure_open(); self._authorized(scope)
            value = self._read_owner(self.journal._db, scope)
            self._authorized(scope)
            return deepcopy(value) if value else dict(state='legacy', generation=0)

    def prepare(self, scope, *, expected_generation, transition_id, binding_sha256):
        scope = _scope(scope); _generation(expected_generation)
        _hash(transition_id); _hash(binding_sha256)
        with self.journal._transaction() as db:
            self._available(scope, binding_sha256=binding_sha256)
            old = self._read_owner(db, scope)
            if ((old['generation'] if old else 0) != expected_generation
                    or old and old['state'] not in {'legacy', 'closed'}):
                raise JournalConflict('memo prepare generation or state changed')
            generation = _generation(expected_generation + 1, positive=True)
            value = dict(schema=1, feature=FEATURE, scope=scope, state='pending', generation=generation,
                         transition_id=transition_id, binding_sha256=binding_sha256,
                         ever_native=old['ever_native'] if old else False)
            self._write(db, OWNERS, 'owner', scope, value, generation)
            self._audit(db, scope, 'pending', generation, transition_id)
            self._available(scope, binding_sha256=binding_sha256)
        return deepcopy(value)

    def _transition(self, scope, *, expected_generation, transition_id, target):
        scope = _scope(scope); _generation(expected_generation, positive=True); _hash(transition_id)
        side = 'legacy' if target == 'native' else 'native' if target == 'legacy' else None
        with self.journal._transaction() as db:
            self._authorized(scope)
            old = self._read_owner(db, scope)
            allowed = {'native': {'pending'}, 'closed': {'pending', 'native', 'legacy'}, 'legacy': {'closed'}}[target]
            if (old is None or old['generation'] != expected_generation
                    or old['transition_id'] != transition_id or old['state'] not in allowed):
                raise JournalConflict('memo transition generation identity or state changed')
            if target != 'closed':
                self._available(scope, binding_sha256=old['binding_sha256'], side=side)
            generation = _generation(expected_generation + 1, positive=True)
            value = dict(old, state=target, generation=generation,
                         ever_native=old['ever_native'] or target == 'native')
            self._write(db, OWNERS, 'owner', scope, value, generation)
            self._audit(db, scope, target, generation, transition_id)
            if target != 'closed':
                self._available(scope, binding_sha256=value['binding_sha256'], side=side)
            else:
                self._authorized(scope)
        return deepcopy(value)

    def activate(self, scope, *, expected_generation, transition_id):
        return self._transition(scope, expected_generation=expected_generation,
                                transition_id=transition_id, target='native')

    def close(self, scope, *, expected_generation, transition_id):
        # Closing does not require a working source/lease or a drained operation.
        # It still requires this coordinator's exact live scope authority.
        return self._transition(scope, expected_generation=expected_generation,
                                transition_id=transition_id, target='closed')

    def rollback_legacy(self, scope, *, expected_generation, transition_id):
        # Explicit drained rollback only. All claims and positive generation stay.
        return self._transition(scope, expected_generation=expected_generation,
                                transition_id=transition_id, target='legacy')

    def admit_native(self, scope, request_id, *, expected_generation):
        """Persist a no-fallback claim before calling the native tool.

        A duplicate claim does not authorize execution or report note success.
        The tool must still check the current owner in its note transaction.
        """
        scope = _scope(scope); _request(request_id); _generation(expected_generation, positive=True)
        with self.journal._transaction() as db:
            self._authorized(scope)
            owner = self._read_owner(db, scope)
            if owner is None or owner['state'] != 'native' or owner['generation'] != expected_generation:
                raise JournalConflict('native memo admission authority changed')
            self._available(scope, binding_sha256=owner['binding_sha256'])
            old = self._claim(db, scope, request_id)
            if old is not None:
                self._available(scope, binding_sha256=owner['binding_sha256'])
                return dict(duplicate=True, claim=deepcopy(old), execution_authorized=False)
            value = dict(schema=1, feature=FEATURE, scope=scope, request_id=request_id, generation=expected_generation,
                         transition_id=owner['transition_id'], binding_sha256=owner['binding_sha256'], state='claimed')
            self._write(db, CLAIMS, request_id, scope, value, 1)
            self._available(scope, binding_sha256=owner['binding_sha256'])
        return dict(duplicate=False, claim=deepcopy(value), execution_authorized=False)

    def routing(self, scope, request_id):
        """Read-only route fence, not a legacy admission lease or native permit."""
        scope = _scope(scope); _request(request_id)
        with self.journal._lock:
            self.journal._ensure_open(); self._authorized(scope)
            owner = self.owner_for_scope(scope)
            claim = self._claim(self.journal._db, scope, request_id)
            self._authorized(scope)
            route = 'claimed' if claim is not None else 'legacy' if owner['mode'] == 'legacy' else owner['mode']
            return dict(route=route, owner=owner, claim=deepcopy(claim), execution_authorized=False,
                        legacy_admission_lease=False)
