"""Explicit once/basic reminders on the existing durable delivery machinery.

An explicitly supplied, dedicated queue3 authority separates this deterministic
lane from companion probability, quotas and activity. No production defaults,
cron registrations, model calls, legacy scheduler imports or recipient fallback.
External note completion is a separately acknowledged outbox, never part of a
message retry. All blocking SQLite operations run outside the event loop.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import inspect
import json
import re
from pathlib import Path
import sqlite3
import time

from .delivery_scheduler import NativeScheduler
from .delivery_sender import BeforeDispatchError, NativeSender, SendResult
from .delivery_store import ACTIVE, DeliveryConflict, DeliveryStore, TERMINAL, _identity, _number
from .delivery_types import delivery_policy_hash, make_task, task_input_hash
from .journal import LivingJournal
from .models import canonical, private_scope, scope_key

LANE = 'explicit_once_reminder'


@dataclass(frozen=True)
class ReminderPolicy:
    lease_seconds: float = 30
    timeout_seconds: float = 10
    catchup_seconds: float = 86400
    sampling_minutes: int = 1  # Only shared-driver blocked deferral; no sampling.

    def __post_init__(self):
        for key, low, high in [('lease_seconds', 1, 300), ('timeout_seconds', .01, 120),
                               ('catchup_seconds', 1, 86400)]:
            _number(getattr(self, key), key, low, high)
        if self.lease_seconds <= self.timeout_seconds:
            raise ValueError('lease must exceed timeout')
        if type(self.sampling_minutes) is not int or self.sampling_minutes != 1:
            raise ValueError('reminders do not use companion sampling')

    def as_dict(self):
        return dict(asdict(self), delivery_lane=LANE)


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _sync_allowed(callback, scope):
    value = callback(scope)
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value): value.close()
        return False
    return value is True


class ReminderDeliveryStore(DeliveryStore):
    """One explicit lane; shared leases, recovery, terminal IDs and sender.

    The dedicated DB is a rollback boundary, not a copy of companion data.
    Stage 8 constructors reject queue3; already open old readers quarantine the
    new immutable hash. Downgrading the feature marker is never supported.
    """
    supported_queue_versions = (1, 3)

    def __init__(self, journal, *, origin_node, authorize, clock=time.time, **limits):
        self.origin_node = _identity(origin_node, 'origin node')
        self.authorize = authorize
        super().__init__(journal, clock=clock, **limits)
        with journal._transaction() as db:
            old = db.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()[0]
            if old == 1 and db.execute('SELECT 1 FROM tls_delivery_tasks LIMIT 1').fetchone():
                raise ValueError('existing companion authority cannot become reminder authority')
            row = db.execute("SELECT version FROM tls_delivery_features WHERE name='reminder'").fetchone()
            if row and row[0] != 1: raise ValueError('unsupported reminder schema')
            db.execute("UPDATE tls_delivery_features SET version=3 WHERE name='queue'")
            db.execute("INSERT OR IGNORE INTO tls_delivery_features VALUES('reminder',1)")
            db.execute('CREATE TABLE IF NOT EXISTS tls_reminder_binding(singleton INTEGER PRIMARY KEY CHECK(singleton=1),node TEXT NOT NULL)')
            row = db.execute('SELECT node FROM tls_reminder_binding WHERE singleton=1').fetchone()
            if row and row[0] != self.origin_node: raise PermissionError('reminder node binding mismatch')
            db.execute('INSERT OR IGNORE INTO tls_reminder_binding VALUES(1,?)', (self.origin_node,))
            db.execute('CREATE TABLE IF NOT EXISTS tls_reminder_consent(scope TEXT PRIMARY KEY,id TEXT NOT NULL,generation INTEGER NOT NULL,enabled INTEGER NOT NULL,evidence TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS tls_reminder_occurrences(id TEXT PRIMARY KEY,scope TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS tls_reminder_completions(id TEXT PRIMARY KEY,state TEXT NOT NULL,data TEXT NOT NULL)')

    def _immutable_extension(self, value):
        binding = value.get('reminder_binding')
        if value.get('delivery_lane') != LANE or not isinstance(binding, dict) or set(binding) != {'occurrence_id', 'revision', 'consent_id', 'consent_generation', 'node'}:
            raise ValueError('exact explicit reminder binding required')
        for key in ('occurrence_id', 'consent_id', 'node'): _identity(binding[key], key)
        for key in ('revision', 'consent_generation'):
            if type(binding[key]) is not int or binding[key] < 1: raise ValueError('invalid reminder generation')
        if binding['node'] != self.origin_node: raise PermissionError('foreign reminder node')
        return dict(delivery_lane=LANE, reminder_binding=dict(binding))

    def claim(self, node, lease_seconds=30):
        if node != self.origin_node: raise PermissionError('foreign reminder worker')
        return super().claim(node, lease_seconds)

    def begin(self, task_id, node, token, policy):
        now = self._now()
        with self.journal._transaction() as db:
            task = self._task(db, task_id)
            self._immutable_extension(task)
            self._fence(task, node, token, now)
            if task['state'] != 'claimed': raise DeliveryConflict('only claimed reminders may begin')
            binding = task['reminder_binding']
            row = db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (binding['occurrence_id'],)).fetchone()
            occurrence = json.loads(row[0]) if row else None
            consent = db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (scope_key(task['scope']),)).fetchone()
            owner = self._owner(db, scope_key(task['scope']))
            approval = task['approval']
            valid = (occurrence is not None and occurrence['status'] == 'active'
                     and occurrence['revision'] == binding['revision'] and occurrence['task_id'] == task_id
                     and occurrence['scope'] == task['scope'] and occurrence['node'] == node
                     and consent is not None and consent['enabled'] == 1
                     and consent['id'] == binding['consent_id'] and consent['generation'] == binding['consent_generation']
                     and owner['mode'] == 'tls' and owner['generation'] == task['owner_generation']
                     and isinstance(approval, dict) and approval.get('native') is True
                     and approval.get('allowed') is True and approval.get('delivery_lane') == LANE
                     and approval.get('input_hash') == task['input_hash'] == task_input_hash(task)
                     and approval.get('policy_hash') == delivery_policy_hash(policy)
                     and policy.get('delivery_lane') == LANE
                     and _sync_allowed(self.authorize, task['scope']))
            if not valid:
                task['state'] = 'cancelled'
                self._save(db, task); self._audit(db, task, 'reminder_fence_denied', now)
                return None
            if task['expires_at'] <= now:
                task['state'] = 'expired'
                self._save(db, task); self._audit(db, task, 'reminder_expired', now)
                return None
            if task['due_at'] > now: raise DeliveryConflict('reminder not due')
            if task['attempts'] >= task['max_attempts']:
                task['state'] = 'failed'
                self._save(db, task); self._audit(db, task, 'attempts_exhausted', now)
                return None
            # No companion reservations or probabilistic/frequency gate.
            task.update(state='sending', attempts=task['attempts'] + 1, dispatch_started_at=now)
            self._save(db, task); self._audit(db, task, 'explicit_reminder_dispatch', now)
            return task


class _ReminderDriver(NativeScheduler):
    async def _decision(self, scope, now):
        self.metrics['decisions'] += 1
        return {'last_activity_at': 0}, {'allowed': True, 'retry_at': now}

    async def _scope_unavailable_after_claim(self, task):
        # A cold or temporarily missing genuine lease is not a platform
        # failure. Keep this exact unstarted occurrence until its original
        # expiry; never grant a lease or consume a send attempt here.
        now = self.clock()
        stopped = not self.active or not self.service.active
        code = 'service_stopping' if stopped else 'waiting_for_real_scope'
        available = min(now + (1 if stopped else 15), task['expires_at'])
        if available <= now:
            # The authorization callback may itself cross the expiry. defer
            # requires a future instant and marks >= expires_at as expired.
            # The original immutable expires_at is never extended.
            available = now + 1
        await asyncio.to_thread(self.store.defer, task['id'], self.node, task['token'], available, code=code)
        return SendResult('blocked', code)

    async def submit(self, *args, **kwargs):
        raise PermissionError('use explicitly authorized reminder occurrence API')

    async def receive_event(self, *args, **kwargs):
        return None  # An ordinary chat must never implicitly create a reminder.

    async def step(self):
        result = await super().step()
        if self.service.active: await self.service._run(self.service._reconcile)
        return result


class _ReminderAdapter:
    """Final task-specific fence immediately before the existing SDK adapter."""
    def __init__(self, service, adapter): self.service, self.adapter = service, adapter
    async def healthy(self, session): return await self.adapter.healthy(session)
    def prepare(self, task): return self.adapter.prepare(task)
    async def send(self, task, prepared):
        if not self.service._dispatch_valid(task):
            raise BeforeDispatchError('explicit_reminder_authority_revoked')
        return await self.adapter.send(task, prepared)


class ReminderService:
    environment = 'isolated'

    def __init__(self, path, *, node, authorize, adapter, policy=None, clock=time.time):
        if not callable(authorize): raise ValueError('explicit scope authority required')
        self.node = _identity(node, 'node')
        self.authorize, self.clock, self.policy = authorize, clock, policy or ReminderPolicy()
        self.active = True
        self._operations = set()
        self._completion_tasks = set()
        path = Path(path)
        if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
            raise ValueError('linked reminder authority path rejected')
        if path.exists():
            # Inspect before LivingJournal can add tables or change PRAGMAs.
            # Never turn even an empty companion DB into a reminder authority.
            probe = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                probe.execute('PRAGMA query_only=ON')
                binding = probe.execute('SELECT node FROM tls_reminder_binding WHERE singleton=1').fetchone()
                feature = probe.execute("SELECT version FROM tls_delivery_features WHERE name='queue'").fetchone()
                if binding and binding[0] != node: raise PermissionError('reminder node binding mismatch')
                if not binding or not feature or feature[0] != 3:
                    raise ValueError('existing authority is not owned by this reminder lane')
            except sqlite3.DatabaseError as error:
                raise ValueError('existing authority is not a reminder authority') from error
            finally: probe.close()
        self.journal = LivingJournal(path, clock=clock)
        try:
            self.store = ReminderDeliveryStore(self.journal, origin_node=node, authorize=self._authorized,
                                                clock=clock, max_tasks=4096, max_active=1000)
            self.sender = NativeSender(self.store, _ReminderAdapter(self, adapter), authorize=self._authorized, policy=self.policy)
            self.driver = _ReminderDriver(self.store, self.sender, node=node, read_state=lambda scope: {},
                                           authorize=self._authorized, policy=self.policy, clock=clock)
            self.driver.service = self
            self.store.recover()
            self._reconcile()
        except BaseException:
            self.journal.close()
            raise

    def _authorized(self, scope):
        return self.active and _sync_allowed(self.authorize, private_scope(scope))

    def _dispatch_valid(self, task):
        with self.journal._lock:
            if not self._authorized(task['scope']): return False
            binding = task.get('reminder_binding', {})
            row = self.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (binding.get('occurrence_id'),)).fetchone()
            current = json.loads(row[0]) if row else None
            consent = self.journal._db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (scope_key(task['scope']),)).fetchone()
            owner = self.store._owner(self.journal._db, scope_key(task['scope']))
            stored = self.store._task(self.journal._db, task['id'])
            return bool(current and current['status'] == 'active' and current['revision'] == binding.get('revision')
                        and current['task_id'] == task['id'] and current['scope'] == task['scope']
                        and current['node'] == self.node == binding.get('node')
                        and consent and consent['enabled'] == 1 and consent['id'] == binding.get('consent_id')
                        and consent['generation'] == binding.get('consent_generation')
                        and owner['mode'] == 'tls' and owner['generation'] == task['owner_generation']
                        and stored['state'] == 'sending' and stored['token'] == task['token']
                        and stored['lease_until'] > self.clock() and task['expires_at'] > self.clock())

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self._authorized(scope): raise PermissionError('reminder scope unauthorized')
        return scope

    def _key(self, scope, reminder_id):
        _identity(reminder_id, 'reminder id')
        return _digest([LANE, self.node, private_scope(scope), reminder_id])

    def grant(self, scope, consent_id, *, evidence='operator_fixture'):
        scope = self._scope(scope); _identity(consent_id, 'consent id')
        if evidence not in {'operator_fixture', 'user_explicit'}: raise ValueError('explicit consent evidence required')
        with self.journal._transaction() as db:
            if not self._authorized(scope): raise PermissionError('consent authority changed')
            sk = scope_key(scope)
            row = db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (sk,)).fetchone()
            if row and row['enabled'] and row['id'] == consent_id and row['evidence'] == evidence: return dict(row)
            if row is None and db.execute('SELECT COUNT(*) FROM tls_reminder_consent').fetchone()[0] >= 1000:
                raise RuntimeError('consent capacity reached')
            generation = row['generation'] + 1 if row else 1
            db.execute('INSERT INTO tls_reminder_consent VALUES(?,?,?,?,?) ON CONFLICT(scope) DO UPDATE SET id=excluded.id,generation=excluded.generation,enabled=1,evidence=excluded.evidence',
                       (sk, consent_id, generation, 1, evidence))
            return dict(scope=sk, id=consent_id, generation=generation, enabled=1, evidence=evidence)

    def revoke(self, scope):
        scope = self._scope(scope)
        with self.journal._transaction() as db:
            if not self._authorized(scope): raise PermissionError('consent authority changed')
            db.execute('UPDATE tls_reminder_consent SET enabled=0,generation=generation+1 WHERE scope=?', (scope_key(scope),))

    def set_mode(self, scope, mode, expected_generation):
        with self.journal._lock:
            return self.store.set_owner(self._scope(scope), mode, expected_generation)

    def get(self, scope, reminder_id):
        scope = self._scope(scope)
        with self.journal._lock:
            if not self._authorized(scope): raise PermissionError('read authority changed')
            row = self.journal._db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (self._key(scope, reminder_id),)).fetchone()
            return json.loads(row[0]) if row else None

    def _save_occurrence(self, db, occurrence):
        db.execute('INSERT INTO tls_reminder_occurrences VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,status=excluded.status,data=excluded.data',
                   (occurrence['id'], scope_key(occurrence['scope']), occurrence['revision'], occurrence['status'], canonical(occurrence)))

    async def create_once(self, scope, reminder_id, *, due_at, text, consent_id, expires_at=None, linked_note_id=''):
        return await self._run(self._create_once, scope, reminder_id, due_at=due_at, text=text,
                                       consent_id=consent_id, expires_at=expires_at, linked_note_id=linked_note_id)

    async def _run(self, callback, *args, **kwargs):
        """Own blocking work until completion, even when its awaiter cancels."""
        if not self.active: raise PermissionError('reminder service stopped')
        current = asyncio.current_task()
        self._operations.add(current)
        worker = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
        cancelled = False
        try:
            while not worker.done():
                try: await asyncio.shield(worker)
                except asyncio.CancelledError: cancelled = True
            value = worker.result()
            if cancelled: raise asyncio.CancelledError()
            return value
        finally: self._operations.discard(current)

    def _create_once(self, scope, reminder_id, *, due_at, text, consent_id, expires_at=None, linked_note_id=''):
        scope = self._scope(scope); key = self._key(scope, reminder_id); now = self.clock()
        due_at = _number(due_at, 'due time')
        expires_at = due_at + self.policy.catchup_seconds if expires_at is None else _number(expires_at, 'expiry')
        if not due_at < expires_at <= due_at + self.policy.catchup_seconds or due_at > now + 366 * 86400:
            raise ValueError('invalid reminder lifetime')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 3900: raise ValueError('bounded reminder text required')
        _identity(consent_id, 'consent id')
        if linked_note_id: _identity(linked_note_id, 'linked note id')
        text = text.strip() if text.strip().startswith('【日程】') else '【日程】' + text.strip()
        with self.journal._transaction() as db:
            if not self._authorized(scope): raise PermissionError('reminder authority changed')
            consent = db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (scope_key(scope),)).fetchone()
            if not consent or not consent['enabled'] or consent['id'] != consent_id: raise PermissionError('explicit consent missing')
            row = db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (key,)).fetchone()
            if row:
                old = json.loads(row[0])
                if any(old[field] != value for field, value in [('due_at', due_at), ('expires_at', expires_at), ('text', text), ('consent_id', consent_id), ('linked_note_id', linked_note_id)]):
                    raise DeliveryConflict('reminder identity content conflict; use reschedule')
                occurrence = old
            else:
                if db.execute('SELECT COUNT(*) FROM tls_reminder_occurrences').fetchone()[0] >= 1000:
                    raise RuntimeError('reminder capacity reached')
                occurrence = dict(id=key, source_id=reminder_id, node=self.node, scope=scope, revision=1,
                    status='active' if now < expires_at else 'expired', due_at=due_at, expires_at=expires_at,
                    text=text, consent_id=consent_id, consent_generation=consent['generation'], linked_note_id=linked_note_id,
                    created_at=now, task_id=None)
                self._save_occurrence(db, occurrence)
        return self._materialize(occurrence)

    def _materialize(self, occurrence):
        if occurrence['status'] != 'active': return occurrence
        if not self._authorized(occurrence['scope']): return occurrence
        binding = dict(occurrence_id=occurrence['id'], revision=occurrence['revision'],
                       consent_id=occurrence['consent_id'], consent_generation=occurrence['consent_generation'], node=self.node)
        created = min(occurrence['created_at'], occurrence['due_at'])
        task = make_task(occurrence['scope'], 'reminder:' + occurrence['id'] + ':' + str(occurrence['revision']),
                         text=occurrence['text'], now=created, due_at=occurrence['due_at'], expires_at=occurrence['expires_at'],
                         priority=80, trigger='timer', max_attempts=3)
        task.update(delivery_lane=LANE, reminder_binding=binding)
        task = self.store.create(task)
        with self.journal._transaction() as db:
            row = db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (occurrence['id'],)).fetchone()
            current = json.loads(row[0])
            if current['revision'] != occurrence['revision'] or current['status'] != 'active':
                stale = self.store._task(db, task['id'])
                if stale['state'] not in TERMINAL:
                    stale['state'] = 'cancelled'; self.store._save(db, stale)
                    self.store._audit(db, stale, 'reminder_stale_materialization', self.clock())
                return current
            current['task_id'] = task['id']; self._save_occurrence(db, current)
        if task['state'] == 'candidate':
            approval = dict(native=True, allowed=True, delivery_lane=LANE, input_hash=task_input_hash(task),
                            policy_hash=delivery_policy_hash(self.policy.as_dict()),
                            decision_id=_digest([task['id'], binding, 'explicit_due_approval']), checked_at=task['created_at'])
            try:
                self.store.record_decision(task['id'], approval)
                self.store.approve(task['id'], approval)
            except DeliveryConflict:
                # Another reconciler/authority connection may have advanced
                # this snapshot. Accept only this exact durable decision AND
                # grant, never re-grant ownership or lower its newer state.
                advanced = self.store.get(task['id'])
                if (not isinstance(advanced, dict)
                        or advanced.get('state') not in (ACTIVE | TERMINAL) - {'candidate'}
                        or advanced.get('decision') != approval
                        or advanced.get('approval') != approval
                        or advanced.get('input_hash') != task['input_hash']
                        or task_input_hash(advanced) != task['input_hash']):
                    raise
        if self.store.get(task['id'])['state'] == 'approved': self.store.enqueue(task['id'])
        return self.get(occurrence['scope'], occurrence['source_id'])

    def _reconcile(self):
        with self.journal._lock:
            rows = self.journal._db.execute("SELECT data FROM tls_reminder_occurrences WHERE status='active' ORDER BY id LIMIT 1000").fetchall()
        for row in rows:
            occurrence = json.loads(row[0])
            # A real host has no live private lease during cold boot. Keep
            # pending materialization intact until a genuine scoped event.
            if not self._authorized(occurrence['scope']): continue
            if not occurrence['task_id']:
                if occurrence['expires_at'] <= self.clock():
                    with self.journal._transaction() as db:
                        current = json.loads(db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?',
                                                        (occurrence['id'],)).fetchone()[0])
                        if (current['status'] == 'active' and not current['task_id']
                                and current['revision'] == occurrence['revision']):
                            current['status'] = 'expired'
                            self._save_occurrence(db, current)
                    continue
                self._materialize(occurrence)
                continue
            task = self.store.get(occurrence['task_id'])
            if task is None:
                self._materialize(occurrence)
                continue
            if task['state'] == 'candidate':
                self._materialize(occurrence)
                continue
            if task['state'] not in TERMINAL: continue
            with self.journal._transaction() as db:
                current = json.loads(db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (occurrence['id'],)).fetchone()[0])
                if current['revision'] != occurrence['revision'] or current['status'] != 'active': continue
                current['status'] = 'done' if task['state'] == 'confirmed' else task['state']
                current['closed_at'] = self.clock(); self._save_occurrence(db, current)
                self.store._audit(db, task, 'reminder_closed', self.clock(), {'revision': current['revision']})
                if task['state'] == 'confirmed' and current['linked_note_id']:
                    payload = dict(occurrence_id=current['id'], task_id=task['id'], revision=current['revision'],
                                   note_id=current['linked_note_id'], scope=current['scope'], node=self.node,
                                   consent_id=current['consent_id'], consent_generation=current['consent_generation'],
                                   owner_generation=task['owner_generation'])
                    db.execute("INSERT OR IGNORE INTO tls_reminder_completions VALUES(?,'pending',?)", (task['id'], canonical(payload)))
        # Optional native agenda series share this existing driver/recovery
        # cycle. The agenda owns only its provenanced rows, never other notes.
        reconcile_agenda=getattr(self,'_agenda_reconciler',None)
        if callable(reconcile_agenda):reconcile_agenda()

    async def cancel(self, scope, reminder_id, *, expected_revision):
        return await self._run(self._change, scope, reminder_id, expected_revision=expected_revision, changes=None)

    async def reschedule(self, scope, reminder_id, *, expected_revision, due_at, text=None):
        occurrence = await self._run(self._change, scope, reminder_id, expected_revision=expected_revision,
                                             changes={'due_at': due_at, 'text': text})
        return await self._run(self._materialize, occurrence)

    async def reauthorize(self, scope, reminder_id, *, expected_revision):
        """Explicitly re-propose reviewed pending work after an owner switch.

        Never revives terminal/unknown work, extends its lifetime, or silently
        rebinds an old queued generation. A fresh occurrence revision is audited.
        """
        if self.store.owner(self._scope(scope))['mode'] != 'tls':
            raise PermissionError('TLS reminder lane must own execution first')
        occurrence = await self._run(self._change, scope, reminder_id,
            expected_revision=expected_revision, changes={'reauthorize': True})
        return await self._run(self._materialize, occurrence)

    def _change(self, scope, reminder_id, *, expected_revision, changes, guard=None):
        scope = self._scope(scope)
        if type(expected_revision) is not int or expected_revision < 1: raise ValueError('revision required')
        with self.journal._transaction() as db:
            row = db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (self._key(scope, reminder_id),)).fetchone()
            if not row: raise KeyError('reminder absent')
            current = json.loads(row[0])
            if current['revision'] != expected_revision: raise DeliveryConflict('stale reminder revision')
            if current['status'] == 'cancelled' and changes is None: return current
            if current['status'] != 'active': raise DeliveryConflict('terminal reminder requires a new explicit identity')
            task = self.store._task(db, current['task_id']) if current['task_id'] else None
            if guard is not None: guard(db, current, task)
            if task and task['state'] in {'sending', 'unknown', 'confirmed'}:
                raise DeliveryConflict('dispatch outcome must be reconciled before change')
            if task and task['state'] not in TERMINAL:
                task['state'] = 'cancelled'; self.store._save(db, task)
                self.store._audit(db, task, 'reminder_generation_cancelled', self.clock())
            if changes is None:
                current['status'] = 'cancelled'; self._save_occurrence(db, current); return current
            reauthorize = changes.get('reauthorize') is True
            due = current['due_at'] if reauthorize else _number(changes['due_at'], 'due time')
            if reauthorize:
                if current['expires_at'] <= self.clock(): raise DeliveryConflict('reminder catchup already expired')
            elif not self.clock() <= due <= self.clock() + 366 * 86400: raise ValueError('reschedule must be future bounded')
            text = current['text'] if reauthorize or changes['text'] is None else changes['text']
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 3900: raise ValueError('invalid reminder text')
            if not text.strip().startswith('【日程】'): text = '【日程】' + text.strip()
            consent = db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (scope_key(scope),)).fetchone()
            if not consent or not consent['enabled'] or consent['id'] != current['consent_id']: raise PermissionError('consent revoked')
            current.update(revision=current['revision'] + 1, due_at=due, expires_at=current['expires_at'] if reauthorize else due + self.policy.catchup_seconds,
                           created_at=self.clock(), text=text, task_id=None, consent_generation=consent['generation'])
            self._save_occurrence(db, current)
            if guard is not None: guard(db, current, task)
            return current

    async def step(self):
        if not self.active: return None
        return await self.driver.step()

    def completions(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            if not self._authorized(scope): raise PermissionError('completion read authority changed')
            return [dict(id=row['id'], state=row['state'], **json.loads(row['data']))
                    for row in self.journal._db.execute('SELECT * FROM tls_reminder_completions ORDER BY id LIMIT 1000')
                    if json.loads(row['data'])['scope'] == scope]

    async def complete_linked_note(self, scope, completion_id, port):
        if not self.active: raise PermissionError('reminder service stopped')
        current = asyncio.current_task()
        self._completion_tasks.add(current)
        try: return await self._complete_linked_note(scope, completion_id, port)
        finally: self._completion_tasks.discard(current)

    async def _complete_linked_note(self, scope, completion_id, port):
        """Trusted external idempotent delete-by-id port; unknown is not retried.

        The note port must enforce the supplied scope/node/expected linked
        occurrence. There is no guessed plugin lookup or unscoped delete here.
        """
        scope = self._scope(scope)
        def claim():
            with self.journal._transaction() as db:
                row = db.execute('SELECT * FROM tls_reminder_completions WHERE id=?', (completion_id,)).fetchone()
                if not row: raise KeyError('completion absent')
                data = json.loads(row['data'])
                if data['scope'] != scope: raise PermissionError('foreign completion scope')
                if not self._completion_valid(db, data): raise PermissionError('completion unauthorized')
                if row['state'] != 'pending': return None
                db.execute("UPDATE tls_reminder_completions SET state='unknown' WHERE id=?", (completion_id,))
                return data
        data = await self._run(claim)
        if data is None: return False
        # claim() is an await boundary. Revocation during it cannot authorize
        # an external deletion. Ambiguous claimed outbox stays unknown.
        with self.journal._lock:
            if not self._completion_valid(self.journal._db, data):
                raise PermissionError('completion authority changed')
        result = port(dict(data, idempotency_key=completion_id))
        if inspect.isawaitable(result): result = await asyncio.wait_for(result, self.policy.timeout_seconds)
        if result is True:
            def ack():
                with self.journal._transaction() as db:
                    db.execute("UPDATE tls_reminder_completions SET state='confirmed' WHERE id=? AND state='unknown'", (completion_id,))
            await self._run(ack)
            return True
        return False

    def _completion_valid(self, db, data):
        if data['node'] != self.node or not self._authorized(data['scope']): return False
        row = db.execute('SELECT data FROM tls_reminder_occurrences WHERE id=?', (data['occurrence_id'],)).fetchone()
        current = json.loads(row[0]) if row else None
        consent = db.execute('SELECT * FROM tls_reminder_consent WHERE scope=?', (scope_key(data['scope']),)).fetchone()
        owner = self.store._owner(db, scope_key(data['scope']))
        return bool(current and current['status'] == 'done' and current['revision'] == data['revision']
                    and current['task_id'] == data['task_id'] and current['linked_note_id'] == data['note_id']
                    and consent and consent['enabled'] == 1 and consent['id'] == data['consent_id']
                    and consent['generation'] == data['consent_generation']
                    and owner['mode'] == 'tls' and owner['generation'] == data['owner_generation'])

    def start(self, *, poll_seconds=1):
        return self.driver.start(poll_seconds=poll_seconds)

    def stop(self):
        self.active = False
        self.driver.active = False
        self.sender.active = False

    def abort_initialization(self):
        """Host rejection cleanup, before starting any worker/platform action."""
        if (self.driver._worker is not None or self.driver._steps or self.sender._pending
                or self._operations or self._completion_tasks
                or self.journal._db.execute("SELECT 1 FROM tls_delivery_tasks WHERE state IN ('claimed','sending') LIMIT 1").fetchone()):
            raise RuntimeError('asynchronous close required after execution begins')
        self.stop()
        self.journal.close()

    async def close(self):
        self.stop()
        await self.driver.close()
        current = asyncio.current_task()
        completions = [task for task in self._completion_tasks if task is not current and not task.done()]
        for task in completions: task.cancel()
        if completions: await asyncio.gather(*completions, return_exceptions=True)
        pending = [task for task in self._operations if task is not current and not task.done()]
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        self.journal.close()

    def diagnostics(self):
        return dict(environment=self.environment, active=self.active, delivery_lane=LANE,
                    node=self.node, driver=self.driver.diagnostics(), operations=len(self._operations),
                    completion_tasks=len(self._completion_tasks), production_takeover=False)
