"""Scoped remote workers for one durable, origin-bound reminder authority.

SQLite remains on the authority machine. Workers hold no alternate task DB and
cannot grant consent, create tasks, choose policy, or change ownership. Existing
ReminderDeliveryStore owns task transitions; this module adds credential-bound
execution ownership, renewable pre-send claims and a durable one-use dispatch
permit. A permit/receipt lost in transit is UNKNOWN, never permission to resend.
This is single-authority coordination, not replicated authority HA or a claim of
exactly-once platform delivery. The existing bounded TLS/loopback RPC transports
can carry dispatch(); SSH tests use the explicit client transport seam.

A granted permit cannot retract an external action: response transit or a worker
pause may delay the actual SDK call until after lease expiry or later revocation.
The authority never requeues SENDING, so this can cause a late/uncertain single
attempt, not authorization for another executor to send the same task. Workers
must remain trusted; credentials grant dispatch within their explicit scopes.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import inspect
import json
import math
import secrets
from time import monotonic

from .delivery_authority import AuthorityClient, MAX_REQUEST, MAX_RESPONSE
from .delivery_scheduler import NativeScheduler
from .delivery_sender import BeforeDispatchError, NativeSender
from .delivery_store import DeliveryConflict, _identity, _number
from .delivery_types import delivery_policy_hash
from .models import canonical, private_scope, scope_key
from .reminders import ReminderService


def _token(value):
    if (not isinstance(value, str) or not 32 <= len(value) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise ValueError('strong printable worker credential required')
    return value


@dataclass(frozen=True)
class WorkerGrant:
    worker_id: str
    token: str
    scopes: tuple

    def __post_init__(self):
        _identity(self.worker_id, 'executor identity')
        _token(self.token)
        if not isinstance(self.scopes, (list, tuple)) or not 1 <= len(self.scopes) <= 100:
            raise ValueError('bounded exact worker scopes required')
        normalized = tuple(private_scope(s) for s in self.scopes)
        if len({scope_key(s) for s in normalized}) != len(normalized):
            raise ValueError('duplicate worker scope')
        object.__setattr__(self, 'scopes', normalized)


class PersistentReminderAuthority:
    """Trusted local owner plus restricted, authenticated remote worker API.

    ``initialize=True`` is explicit first creation. Restarts must omit it and
    provide the same authority identity, origin, policy and worker grants. This
    prevents an empty/recreated DB from masquerading as recovered task state.
    Credential rotation/revocation is deliberately not an unaudited worker API.
    """
    operations = frozenset({'get', 'claim', 'begin', 'finish', 'defer', 'health', 'renew', 'permit'})

    def __init__(self, service, *, workers, authority_id, lease_seconds=None, initialize=False):
        if not isinstance(service, ReminderService) or not service.active:
            raise ValueError('live dedicated reminder service required')
        if (service.driver._worker is not None or service.driver._steps or service.sender._pending):
            raise DeliveryConflict('stop local reminder execution before assigning remote authority')
        # Attempted handoff is fail-closed even if configuration/storage checks
        # below reject initialization. The caller must close that service;
        # constructor failure must not leave a usable local sender fallback.
        service.driver.active = False
        service.sender.active = False
        self.service, self.store = service, service.store
        self.authority_id = _identity(authority_id, 'authority identity')
        self.lease_seconds = _number(service.policy.lease_seconds if lease_seconds is None else lease_seconds,
                                     'lease duration', 1, 300)
        if self.lease_seconds != service.policy.lease_seconds:
            raise ValueError('authority lease must match explicitly approved policy')
        if not isinstance(workers, (list, tuple)) or not 1 <= len(workers) <= 32:
            raise ValueError('bounded worker configuration required')
        if any(not isinstance(w, WorkerGrant) for w in workers):
            raise ValueError('explicit worker grants required')
        if len({w.worker_id for w in workers}) != len(workers) or len({w.token for w in workers}) != len(workers):
            raise ValueError('worker credentials and identities must be unique')
        self.workers = {w.worker_id: w for w in workers}
        self._scope_keys = {w.worker_id: frozenset(scope_key(s) for s in w.scopes) for w in workers}
        # Store only the configuration fingerprint, never reusable raw tokens.
        fingerprint = hashlib.sha256(canonical(sorted(
            [w.worker_id, hashlib.sha256(w.token.encode()).hexdigest(), sorted(scope_key(s) for s in w.scopes)]
            for w in workers)).encode()).hexdigest()
        self._binding = canonical(dict(authority_id=self.authority_id, origin=service.node,
            policy=delivery_policy_hash(service.policy.as_dict()), workers=fingerprint,
            lease_seconds=self.lease_seconds, schema=1))
        journal = self.store.journal
        with journal._transaction() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tls_coordination_binding'").fetchone()
            if not exists and initialize is not True:
                raise ValueError('persistent coordination binding missing; explicit new initialization required')
            if exists:
                row = db.execute('SELECT binding FROM tls_coordination_binding WHERE singleton=1').fetchone()
                if not row or row[0] != self._binding:
                    raise PermissionError('persistent authority configuration mismatch')
            else:
                db.execute('CREATE TABLE tls_coordination_binding(singleton INTEGER PRIMARY KEY CHECK(singleton=1),binding TEXT NOT NULL,last_clock REAL NOT NULL)')
                db.execute('INSERT INTO tls_coordination_binding VALUES(1,?,?)', (self._binding, self.store._now()))
                db.execute('CREATE TABLE tls_coordination_executors(task TEXT PRIMARY KEY,epoch INTEGER NOT NULL,worker TEXT NOT NULL,permit INTEGER NOT NULL CHECK(permit IN (0,1)))')
            self._guard_clock(db)

    def _guard_clock(self, db):
        """Authority wallclock only; backward steps fail closed, including restart."""
        now = self.store._now()
        previous = db.execute('SELECT last_clock,binding FROM tls_coordination_binding WHERE singleton=1').fetchone()
        if previous is None or previous['binding'] != self._binding:
            raise PermissionError('authority binding unavailable')
        if now < previous['last_clock']:
            raise DeliveryConflict('authority clock moved backwards')
        db.execute('UPDATE tls_coordination_binding SET last_clock=? WHERE singleton=1', (now,))
        return now

    def _worker(self, authorization):
        if not isinstance(authorization, str):
            return None
        try:
            supplied = authorization.encode('ascii')
        except UnicodeEncodeError:
            return None
        match = None
        for grant in self.workers.values():
            if secrets.compare_digest(supplied, ('Bearer ' + grant.token).encode()):
                match = grant
        return match

    def _scope_allowed(self, grant, task):
        return isinstance(task, dict) and scope_key(private_scope(task.get('scope'))) in self._scope_keys[grant.worker_id]

    def _task(self, db, grant, task_id):
        _identity(task_id, 'task identity')
        task = self.store._task(db, task_id)
        if not self._scope_allowed(grant, task):
            raise PermissionError('task outside executor scope')
        self.store._immutable_extension(task)
        return task

    def _execution(self, db, grant, task_id, node, token, now):
        if node != grant.worker_id:
            raise PermissionError('credential cannot impersonate another executor')
        task = self._task(db, grant, task_id)
        row = db.execute('SELECT * FROM tls_coordination_executors WHERE task=?', (task_id,)).fetchone()
        if not row or row['worker'] != grant.worker_id or row['epoch'] != task['epoch']:
            raise DeliveryConflict('executor ownership is stale')
        self.store._fence(task, self.service.node, token, now)
        return task, row

    def _get(self, grant, task_id):
        with self.store.journal._transaction() as db:
            self._guard_clock(db)
            row = db.execute('SELECT data FROM tls_delivery_tasks WHERE id=?', (_identity(task_id, 'task identity'),)).fetchone()
            if not row:
                return None
            task = self._task(db, grant, task_id)
            executor = db.execute('SELECT worker,epoch FROM tls_coordination_executors WHERE task=?', (task_id,)).fetchone()
            task = dict(task)
            # A competing worker can observe state but never steal a live token.
            if not executor or executor['worker'] != grant.worker_id or executor['epoch'] != task['epoch']:
                task['token'] = None
            return task

    def _claim(self, grant, node, lease_seconds=30):
        if node != grant.worker_id:
            raise PermissionError('credential cannot impersonate another executor')
        if _number(lease_seconds, 'worker lease duration', 1, 300) != self.lease_seconds:
            raise ValueError('worker cannot change authority lease')
        result = None
        with self.store.journal._transaction() as db:
            now = self._guard_clock(db)
            self.store._recover(db, now, claim_only=True)
            keys = tuple(self._scope_keys[grant.worker_id])
            placeholders = ','.join('?' for _ in keys)
            rows = db.execute("SELECT data FROM tls_delivery_tasks WHERE state IN ('queued','retry_wait') AND due<=? AND expires>? AND scope IN (" + placeholders + ') ORDER BY priority DESC,due,id', (now, now, *keys))
            for row in rows:
                task = json.loads(row[0])
                owner = self.store._owner(db, scope_key(task['scope']))
                if owner['mode'] != 'tls' or owner['generation'] != task['owner_generation']:
                    continue
                task.update(state='claimed', owner_node=self.service.node, token=secrets.token_hex(24),
                            lease_until=min(now + self.lease_seconds, task['expires_at']), epoch=task['epoch'] + 1)
                self.store._save(db, task)
                db.execute('INSERT INTO tls_coordination_executors VALUES(?,?,?,0) ON CONFLICT(task) DO UPDATE SET epoch=excluded.epoch,worker=excluded.worker,permit=0',
                           (task['id'], task['epoch'], grant.worker_id))
                self.store._audit(db, task, 'remote_claimed', now, {'epoch': task['epoch'], 'executor': grant.worker_id})
                result = task
                break
        # Recovery can close a lease without finish() (crash/lost response).
        # Project those terminal rows into occurrences/outboxes after commit,
        # never leave the UI's business state active until another restart.
        self.service._reconcile()
        return result

    def _renew(self, grant, task_id, node, token):
        with self.store.journal._transaction() as db:
            now = self._guard_clock(db)
            task, _ = self._execution(db, grant, task_id, node, token, now)
            if task['state'] != 'claimed':
                raise DeliveryConflict('only unstarted claims can renew')
            task['lease_until'] = min(now + self.lease_seconds, task['expires_at'])
            self.store._save(db, task)
            self.store._audit(db, task, 'remote_renewed', now, {'epoch': task['epoch'], 'executor': grant.worker_id})
            return task

    def _permit(self, grant, task_id, node, token):
        with self.store.journal._transaction() as db:
            now = self._guard_clock(db)
            task, execution = self._execution(db, grant, task_id, node, token, now)
            if task['state'] != 'sending' or execution['permit']:
                raise DeliveryConflict('dispatch permit absent or already issued')
            if not self.service._dispatch_valid(task):
                raise PermissionError('reminder authority changed before platform dispatch')
            db.execute('UPDATE tls_coordination_executors SET permit=1 WHERE task=?', (task_id,))
            self.store._audit(db, task, 'remote_dispatch_permit', now, {'epoch': task['epoch'], 'executor': grant.worker_id})
            return dict(allowed=True, authority_id=self.authority_id, task_id=task_id,
                        epoch=task['epoch'], executor=grant.worker_id, lease_until=task['lease_until'],
                        authority_time=now, remaining_lease_seconds=task['lease_until'] - now)

    def _begin(self, grant, task_id, node, token, policy):
        # Validate executor before the existing origin-bound Store transaction.
        with self.store.journal._lock:
            with self.store.journal._transaction() as db:
                now = self._guard_clock(db)
                self._execution(db, grant, task_id, node, token, now)
            if delivery_policy_hash(policy) != delivery_policy_hash(self.service.policy.as_dict()):
                raise PermissionError('worker cannot change approved reminder policy')
            result = self.store.begin(task_id, self.service.node, token, policy)
            self.service._reconcile()
            return result

    def _finish(self, grant, task_id, node, token, outcome, code=''):
        with self.store.journal._lock:
            with self.store.journal._transaction() as db:
                now = self._guard_clock(db)
                task, execution = self._execution(db, grant, task_id, node, token, now)
                if outcome == 'confirmed' and (task['state'] != 'sending' or not execution['permit']):
                    raise DeliveryConflict('confirmation requires issued dispatch permit')
                # Once a permit leaves the authority, any uncertain return is
                # unsafe to classify retryable. Only pre-platform explicit
                # local failure/false route or unknown can close that attempt.
                if execution['permit'] and outcome == 'retryable':
                    raise DeliveryConflict('issued dispatch cannot be retried automatically')
            result = self.store.finish(task_id, self.service.node, token, outcome, code)
            self.service._reconcile()
            return result

    def _defer(self, grant, task_id, node, token, available_at, code='frequency_gate'):
        _number(available_at, 'client deferral')  # Never use a worker wallclock.
        with self.store.journal._lock:
            with self.store.journal._transaction() as db:
                now = self._guard_clock(db)
                self._execution(db, grant, task_id, node, token, now)
            result = self.store.defer(task_id, self.service.node, token, now + 1, code)
            self.service._reconcile()
            return result

    def _health(self, grant):
        with self.store.journal._transaction() as db:
            now = self._guard_clock(db)
            self.store._recover(db, now)
            counts = {}
            for key in self._scope_keys[grant.worker_id]:
                for state, count in db.execute('SELECT state,COUNT(*) FROM tls_delivery_tasks WHERE scope=? GROUP BY state', (key,)):
                    counts[state] = counts.get(state, 0) + count
            result = dict(ok=True, feature='tls.reminder.durable-coordination.v1', authority_id=self.authority_id,
                          executor=grant.worker_id, authority_time=now, lease_seconds=self.lease_seconds,
                          counts=counts, persistent=True, replicated=False)
        self.service._reconcile()
        return result

    def dispatch(self, authorization, body):
        grant = self._worker(authorization)
        if grant is None:
            return 401, dict(ok=False, error='unauthorized')
        if not isinstance(body, bytes) or len(body) > MAX_REQUEST:
            return 413, dict(ok=False, error='request_too_large')
        try:
            request = json.loads(body)
            if not isinstance(request, dict) or set(request) - {'operation', 'args', 'kwargs'}:
                raise ValueError('invalid request')
            operation = request.get('operation')
            if operation not in self.operations:
                return 403, dict(ok=False, error='operation_forbidden')
            args, kwargs = request.get('args', []), request.get('kwargs', {})
            if not isinstance(args, list) or len(args) > 6 or not isinstance(kwargs, dict) or len(kwargs) > 6:
                raise ValueError('invalid arguments')
            target = getattr(self, '_' + operation)
            inspect.signature(target).bind(grant, *args, **kwargs)
            result = target(grant, *args, **kwargs)
            response = dict(ok=True, result=result)
            if len(json.dumps(response, allow_nan=False).encode()) > MAX_RESPONSE:
                return 500, dict(ok=False, error='response_too_large')
            return 200, response
        except DeliveryConflict:
            return 409, dict(ok=False, error='delivery_conflict')
        except PermissionError:
            return 403, dict(ok=False, error='forbidden')
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return 400, dict(ok=False, error='invalid_request')
        except Exception:
            return 503, dict(ok=False, error='authority_unavailable')


class RemoteReminderClient(AuthorityClient):
    def __init__(self, url, token, *, worker_id, timeout=3, tls_context=None, transport=None):
        self.worker_id = _identity(worker_id, 'executor identity')
        super().__init__(url, token, timeout=timeout, tls_context=tls_context, transport=transport)

    def renew(self, task_id, node, token):
        return self._call('renew', task_id, node, token)

    def permit(self, task_id, node, token):
        return self._call('permit', task_id, node, token)


class _RemoteReminderAdapter:
    def __init__(self, client, adapter, *, lease_seconds, final_authorize=None):
        if final_authorize is not None and not callable(final_authorize):
            raise ValueError('explicit final authorization callback required')
        self.client, self.adapter = client, adapter
        self.lease_seconds = lease_seconds
        self.final_authorize = final_authorize

    async def healthy(self, session):
        return await self.adapter.healthy(session)

    def prepare(self, task):
        return self.adapter.prepare(task)

    async def send(self, task, prepared):
        # RPC failure is not proof the permit was uncommitted. NativeSender
        # conservatively records UNKNOWN; no fallback or implicit retry.
        requested_at = monotonic()
        permit = await asyncio.to_thread(self.client.permit, task['id'], self.client.worker_id, task['token'])
        if (not isinstance(permit, dict) or permit.get('allowed') is not True
                or permit.get('task_id') != task['id'] or type(permit.get('epoch')) is not int
                or permit.get('epoch') != task['epoch']
                or not isinstance(permit.get('authority_id'), str)
                or not 1 <= len(permit['authority_id']) <= 256
                or permit.get('executor') != self.client.worker_id):
            raise BeforeDispatchError('remote_permit_denied')
        # Bound the response age without trusting the worker's wallclock. The
        # full RPC round trip is subtracted: it overestimates the permit's age
        # when the request was delayed, which is deliberately conservative.
        # Missing metadata from an older authority is not an execution grant.
        stamp, until, remaining = (permit.get(key) for key in
                                  ('authority_time', 'lease_until', 'remaining_lease_seconds'))
        values = (stamp, until, remaining)
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in values)
                or remaining <= 0 or remaining > self.lease_seconds
                or until <= stamp or remaining > until - stamp):
            raise BeforeDispatchError('remote_permit_stale')
        # Local revocation/shutdown may arrive while the permit RPC is in
        # flight. Recheck known local execution rights immediately before the
        # platform boundary. An awaited check consumes the same permit budget.
        if self.final_authorize is not None:
            allowed = self.final_authorize(task['scope'])
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                raise BeforeDispatchError('remote_local_authorization_revoked')
        elapsed = monotonic() - requested_at
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed) or elapsed < 0
                or min(remaining, until - stamp) - elapsed <= 0):
            raise BeforeDispatchError('remote_permit_stale')
        # A final async authorizer can suppress CancelledError. Sender timeout
        # or cancellation has already ended that attempt as UNKNOWN: it must
        # not start its first SDK operation afterwards. Check the dispatch
        # task's cancellation request, not cancelled() (which is false while
        # a coroutine is still running). Older runtimes without this public
        # state fail closed rather than guessing from private Task fields.
        try:
            cancelling = getattr(asyncio.current_task(), 'cancelling', None)
            cancellation_count = cancelling() if callable(cancelling) else None
        except Exception:
            raise BeforeDispatchError('remote_cancellation_state_unavailable') from None
        if type(cancellation_count) is not int or cancellation_count != 0:
            raise BeforeDispatchError('remote_dispatch_cancelled')
        # A pause after this final check, or inside a platform SDK, cannot be
        # fenced by a local clock. SENDING therefore remains non-replayable.
        return await self.adapter.send(task, prepared)


class RemoteReminderWorker(NativeScheduler):
    """Existing scheduler/sender with explicit deterministic reminder policy.

    No local authority DB or candidate/consent API. start()/step()/close() are
    the existing lifecycle. renew() is explicit pre-send renewal; SENDING is
    never extended. An SDK operation cannot be retracted after its permit.
    """
    def __init__(self, client, adapter, *, authorize, policy, clock=None):
        if not isinstance(client, RemoteReminderClient) or not callable(authorize):
            raise ValueError('authenticated client and explicit local scope check required')
        if not callable(getattr(asyncio.Task, 'cancelling', None)):
            # Reject an unsupported runtime before any claim is attempted;
            # the per-dispatch dynamic check remains fail-closed as well.
            raise ValueError('remote worker requires public Task cancellation state')
        if clock is None:
            import time
            clock = time.time
        async def final_authorize(scope):
            if not self.active or not self.sender.active:
                return False
            allowed = authorize(scope)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            return bool(allowed) and self.active and self.sender.active

        sender = NativeSender(client, _RemoteReminderAdapter(client, adapter,
                              lease_seconds=policy.lease_seconds, final_authorize=final_authorize),
                              authorize=authorize, policy=policy)
        super().__init__(client, sender, node=client.worker_id, read_state=lambda scope: {},
                         authorize=authorize, policy=policy, clock=clock)

    async def _decision(self, scope, now):
        self.metrics['decisions'] += 1
        return {'last_activity_at': 0}, {'allowed': True, 'retry_at': now}

    async def submit(self, *args, **kwargs):
        raise PermissionError('remote workers cannot create or approve reminder tasks')

    async def receive_event(self, *args, **kwargs):
        return None
