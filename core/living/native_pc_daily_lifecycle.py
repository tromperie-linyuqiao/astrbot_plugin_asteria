"""Sourced virtual routines and goal sharing over the existing TLS services.

No timer, sender, model provider or delivery queue is created. The real inbound
Host registers a scope; its existing tick calls this service. A durable source
snapshot is provenance, never a replacement for the Host's current permission.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import hashlib
import inspect
import json
import math

from .journal import JournalConflict
from .models import canonical, private_scope, scope_key
from .native_pc_goal_handoff import NativePCGoalHandoff
from .native_personal_goals import NativePersonalGoals
from .native_scoped_daily_plan import NativeScopedDailyPlans, MAX_PLANS
from .native_proactive_companion import NativeProactiveCompanion, event_id_for
from .delivery_types import make_task

NAMESPACE = 'tls.native.pc.daily_lifecycle.v1'
SHARES = 'tls.native.pc.goal_share.v1'
STATE = 'tls.native.pc.daily_settings.v1'
_WAITING = {'attempting', 'generating', 'imaging', 'submitting', 'queued'}
_SETTLED = {'acked', 'failed', 'dropped', 'duplicate', 'delivered_unclaimed', 'claimed', 'claim_unknown'}
_DEFAULTS = dict(auto_generate=False, auto_progress=False, share_enabled=False, routine_enabled=False)


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _text(value, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('bounded exact source identifier required')
    return value.strip()


async def _value(value):
    return await value if inspect.isawaitable(value) else value


class NativePCDailyLifecycle:
    def __init__(self, plans, goals, proactive, *, context, handoff, authorize,
                 authorize_material, persona_allowed, clock=None, defaults=None, daily_source=None):
        if (not isinstance(plans, NativeScopedDailyPlans) or not isinstance(goals, NativePersonalGoals)
                or plans.goals is not goals or plans.journal is not goals.journal
                or proactive is not None and not isinstance(proactive, NativeProactiveCompanion)
                or not isinstance(handoff, NativePCGoalHandoff)
                or not all(callable(value) for value in (authorize, authorize_material, persona_allowed))):
            raise ValueError('existing scoped plans, goals, shared lane and exact legacy handoff required')
        if proactive is not None and proactive.runtime.journal is not plans.journal:
            raise ValueError('one living journal required')
        self.plans, self.goals, self.proactive = plans, goals, proactive
        self.context, self.handoff, self.authorize = context, handoff, authorize
        self.authorize_material, self.persona_allowed = authorize_material, persona_allowed
        self.journal = plans.journal; self.clock = clock or plans.clock
        self.daily_source = daily_source
        self.defaults = self._settings(defaults or _DEFAULTS)
        self.active = True; self._scopes = {}; self._serial = asyncio.Lock()
        self._last = {}; self._active_tasks = set(); self._source_epoch = 0

    @staticmethod
    def _settings(value):
        if type(value) is not dict or set(value) != set(_DEFAULTS) or any(type(v) is not bool for v in value.values()):
            raise ValueError('four exact native daily flags required')
        return dict(value)

    def _allowed(self, scope, operation):
        try:
            return self.active and self.authorize(dict(scope), operation) is True and (operation == 'bind' or self._goal_owned())
        except Exception: return False

    def _goal_owned(self):
        if self.handoff.owns(): return True
        from .native_legacy_companion_inspection import native_pc_successor
        # Full retirement supersedes the old exact-instance partial fence. The
        # real native service hard-disables its inherited old goal writer.
        return native_pc_successor(self.context) is not None

    def _material(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize_material(dict(scope)) is not True:
            raise PermissionError('scoped native daily material unavailable')
        return scope

    def _put(self, namespace, key, scope, data, revision, operation='advance'):
        return self.journal.put(namespace, key, scope, data, expected_revision=revision,
            authorize=lambda: self._allowed(scope, operation))

    async def _selected(self, scope):
        """Actual SDK selection without creating a conversation or calling a model."""
        if not self._allowed(scope, 'bind'): raise PermissionError('real inbound scope is no longer authorized')
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(scope['session_id'])
        conversation = None
        if cid is not None:
            conversation = await manager.get_conversation(scope['session_id'], cid, create_if_not_exists=False)
            if (conversation is None or getattr(conversation, 'cid', None) != cid
                    or getattr(conversation, 'user_id', None) != scope['session_id']):
                raise PermissionError('SDK conversation ownership unavailable')
        config = self.context.get_config(umo=scope['session_id'])
        settings = config.get('provider_settings', {})
        selected, persona, *_ = await self.context.persona_manager.resolve_selected_persona(
            umo=scope['session_id'], conversation_persona_id=getattr(conversation, 'persona_id', None),
            platform_name=scope['platform'], provider_settings=settings)
        if (not self._allowed(scope, 'bind') or not isinstance(persona, dict)
                or persona.get('name') != selected or self.persona_allowed(dict(scope), selected) is not True):
            raise PermissionError('actual SDK persona is not bound to this scope')
        return _text(selected, 256)

    async def observe_scope(self, scope, event_id):
        """Internal genuine-private-inbound hook; deliberately has no HTTP route."""
        scope = private_scope(scope); event_id = _text(event_id, 256)
        selected = await self._selected(scope)
        key = scope_key(scope)
        if key not in self._scopes and len(self._scopes) >= 32:
            raise RuntimeError('native daily live-scope capacity reached')
        source = dict(schema=1, scope=scope, event_id=event_id, persona_id=selected,
                      source='genuine_private_inbound_sdk_selection', observed_at=self.clock())
        old = self.journal.fetch(NAMESPACE, 'source', scope)
        self._put(NAMESPACE, 'source', scope, source, old['revision'] if old else 0, operation='bind')
        self._source_epoch += 1
        self._scopes[key] = source
        return dict(registered=True, source='genuine_private_inbound_sdk_selection', grants_lease=False)

    async def resume_scope(self, scope, event_id):
        """Resume an existing source only after the RAM identity handoff."""
        scope = private_scope(scope)
        selected = await self._selected(scope)
        row = self.journal.fetch(NAMESPACE, 'source', scope)
        source = row['data'] if row else None
        if (not isinstance(source, dict) or source.get('scope') != scope
                or source.get('event_id') != event_id or source.get('persona_id') != selected
                or source.get('source') != 'genuine_private_inbound_sdk_selection'):
            return False
        self._scopes[scope_key(scope)] = dict(source)
        self._source_epoch += 1
        return True  # Preserve original observed_at and journal revision.

    async def _source(self, scope, operation):
        if not self._allowed(scope, operation): raise PermissionError('native daily execution is not currently owned')
        source = self._scopes.get(scope_key(scope))
        if source is None or source['scope'] != scope:
            raise PermissionError('a genuine private inbound is required after load')
        selected = await self._selected(scope)
        if (source is not self._scopes.get(scope_key(scope)) or selected != source['persona_id']
                or not self._allowed(scope, operation)):
            raise PermissionError('daily source or selected persona changed')
        return source

    def settings(self, scope):
        scope = self._material(scope)
        row = self.journal.fetch(STATE, 'settings', scope)
        value = self._settings(row['data']['flags']) if row else dict(self.defaults)
        return dict(flags=value, revision=row['revision'] if row else 0, scope=scope)

    def configure(self, scope, *, expected_revision, flags, actor):
        scope = self._material(scope); flags = self._settings(flags); actor = _text(actor, 120)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('exact nonnegative settings revision required')
        self.journal.put(STATE, 'settings', scope, dict(schema=1, flags=flags, actor=actor, updated_at=self.clock()),
            expected_revision=expected_revision,
            authorize=lambda: self.active and self.authorize_material(dict(scope)) is True)
        return self.settings(scope)

    async def generate(self, scope, *, day=None, routines=False):
        scope = private_scope(scope)
        source = await self._source(scope, 'generate')
        now = self.clock(); today = datetime.fromtimestamp(now, self.plans.timezone).date()
        target = today if day is None else date.fromisoformat(day)
        if target < today or target > today + timedelta(days=7):
            raise ValueError('select today or one of the next seven role-calendar days')
        day = target.isoformat()
        identity = _digest([scope, source['persona_id'], day, 'routine' if routines else 'goals'])
        request = 'pc.daily.' + identity
        plan_id = 'plan.' + _digest([scope, request])
        link_key = 'plan.' + plan_id
        link = self.journal.fetch(NAMESPACE, link_key, scope)
        if link is not None and link['data'].get('phase') == 'ready':
            existing = self.plans.get(scope, plan_id)
            if existing is None: raise RuntimeError('sourced daily plan is missing; do not recreate history')
            return existing
        actor = 'inbound.' + _digest([scope, source['persona_id']])[:32]
        # Provenance is durable before the plan, so a crash cannot leave an
        # apparently ownerless plan that a later inbound silently adopts.
        if link is None:
            proof = dict(schema=1, plan_id=plan_id, scope=scope, persona_id=source['persona_id'],
                inbound_event_id=source['event_id'], source='genuine_private_inbound_sdk_selection',
                created_at=self.clock(), fictional=True, kind='routine' if routines else 'goals',
                phase='preparing', legacy_history_migrated=False)
            link = self._put(NAMESPACE, link_key, scope, proof, 0, operation='generate')
        else:
            proof = dict(link['data'])
            if proof['persona_id'] != source['persona_id'] or proof['plan_id'] != plan_id:
                raise JournalConflict('daily creation source changed')
        existing = self.plans.get(scope, plan_id)
        if existing is not None:
            if existing['provenance']['actor'] != actor:
                raise JournalConflict('existing daily plan has another creation source')
            proof['phase'] = 'ready'
            self._put(NAMESPACE, link_key, scope, proof, link['revision'], operation='generate')
            return existing
        if routines:
            # These are explicitly fictional proposals, never imported global
            # PC history or claims about real observation, reading, or skills.
            slots = [(10, '整理日常思绪'), (15, '留一段轻松休息的时间'), (21, '回顾今天的虚构经历')]
            items = []
            for hour, title in slots:
                at = datetime.combine(target, time(hour, 0), self.plans.timezone).timestamp()
                if at <= now: continue
                items.append(dict(title=title, description='目标之外的虚构角色日常；仅在到时或明确完成后记为角色事件。', scheduled_at=at))
            if not items:
                raise ValueError('today has no future routine slot; choose tomorrow')
            plan = self.plans.create(scope, request, title='明确归属的虚构日常', day=day, items=items, actor=actor)
        else:
            plan = self.plans.generate(scope, request, day=day, limit=6, actor=actor)
        await self._source(scope, 'generate')
        proof['phase'] = 'ready'
        self._put(NAMESPACE, link_key, scope, proof, link['revision'], operation='generate')
        return plan

    async def _advance(self, scope, source):
        advanced = 0; now = self.clock()
        rows = self.plans.list(scope, limit=MAX_PLANS)['records']
        for plan in rows:
            link = self.journal.fetch(NAMESPACE, 'plan.' + plan['id'], scope)
            if (not link or link['data'].get('phase') != 'ready' or link['data'].get('persona_id') != source['persona_id']
                    or plan['status'] != 'active' or plan['archived']): continue
            for item in list(plan['items']):
                if item['status'] != 'pending' or item['scheduled_at'] > now: continue
                await self._source(scope, 'advance')
                plan = self.plans.complete_item(scope, plan['id'], item['id'], expected_revision=plan['revision'],
                    request_id='pc.clock.' + _digest([plan['id'], item['id']]),
                    actor='sourced_virtual_clock', occurred_at=item['scheduled_at'])
                advanced += 1
            if any(item['status'] == 'completed' and item['progress_state'] != 'applied' for item in plan['items']):
                await self._source(scope, 'advance')
                self.plans.apply_completed(scope, plan['id'])
        return advanced

    def _candidate(self, scope, identity):
        for candidate in self._candidates(scope, include_ineligible=True):
            if candidate['candidate_id'] == identity: return candidate
        return None

    def _candidates(self, scope, *, include_ineligible=False):
        rows = self.goals.proactive_candidates(scope, limit=8, include_ineligible=include_ineligible)
        source = self.daily_source
        if source is not None and getattr(source, 'active', False) is True:
            rows += source.proactive_candidates(scope)
        return sorted(rows, key=lambda row: (-row['score'], row['candidate_id']))[:16]

    async def _share_source_current(self, scope, work):
        try:
            await self._source(scope, 'share')
            if not self.settings(scope)['flags']['share_enabled']: return False
            candidate = self._candidate(scope, work['candidate']['candidate_id'])
            return (candidate is not None and candidate['eligible'] is True
                    and candidate['dedupe_key'] == work['candidate']['dedupe_key'])
        except Exception: return False

    def _share_put(self, scope, work, revision):
        return self._put(SHARES, work['key'], scope, work, revision, operation='share')

    async def _claim_confirmed(self, scope, row):
        work = dict(row['data'])
        if work.get('claim_attempted'):
            return dict(state=work['phase'], reason='confirmed_delivery_retained_without_claim_retry')
        if not await self._share_source_current(scope, work):
            work['phase'] = 'delivered_unclaimed'
            self._share_put(scope, work, row['revision'])
            return dict(state='delivered_unclaimed', reason='goal_changed_after_actual_delivery')
        candidate = work['candidate']
        # Commit intent before claim. A crash can leave an unclaimed delivered
        # reason; it cannot re-send or execute claim twice without reconciliation.
        work.update(phase='claim_unknown', delivery_confirmed=True, claim_attempted=True, claim_at=self.clock())
        row = self._share_put(scope, work, row['revision'])
        try:
            if candidate['source'] == 'pc_virtual_life':
                if self.daily_source is None: raise PermissionError('native daily event owner unavailable')
                saved = self.daily_source.confirm_share(scope, candidate, work['task_id'])
            else:
                saved = self.goals.claim_share(scope, candidate['goal_id'], expected_revision=candidate['revision'],
                    kind=candidate['kind'], candidate_id=candidate['candidate_id'], now=work['claim_at'])
        except JournalConflict:
            work.update(phase='delivered_unclaimed', claim_reason='goal_revision_changed')
        except Exception:
            # No automatic retry after an ambiguous database result.
            work.update(phase='claim_unknown', claim_reason='claim_result_unknown')
        else:
            work.update(phase='claimed', claimed_goal_revision=saved['revision'])
        self._share_put(scope, work, row['revision'])
        return dict(state=work['phase'], task_id=work['task_id'], delivery_confirmed=True)

    async def _reconcile_share(self, scope, row):
        work = dict(row['data'])
        if work['phase'] in {'acked'}: return await self._claim_confirmed(scope, row)
        if work['phase'] in _SETTLED or work['phase'] == 'unknown':
            return dict(state=work['phase'], task_id=work.get('task_id'), automatic_retry=False)
        actual = await self.proactive._fetch(scope)
        if (actual is None or actual['data']['event_id'] != work['engine_event_id']
                or actual['data'].get('signature') != _digest([scope, work['engine_event_id'], work['topic']])):
            work['phase'] = 'unknown'; self._share_put(scope, work, row['revision'])
            return dict(state='unknown', reason='shared_lane_mapping_unresolved', automatic_retry=False)
        await self.proactive._reconcile(scope, actual)
        actual = await self.proactive._fetch(scope)
        work.update(phase=actual['data']['phase'], task_id=actual['data']['task_id'])
        row = self._share_put(scope, work, row['revision'])
        if work['phase'] == 'acked': return await self._claim_confirmed(scope, row)
        return dict(state=work['phase'], task_id=work['task_id'])

    async def _share(self, scope):
        if self.proactive is None: return dict(state='disabled', reason='existing_shared_lane_unavailable')
        await self._source(scope, 'share')
        pointer = self.journal.fetch(NAMESPACE, 'active_share', scope)
        if pointer:
            row = self.journal.fetch(SHARES, pointer['data']['key'], scope)
            if row is None: return dict(state='unknown', reason='durable_share_mapping_missing')
            if row['data']['phase'] in _WAITING | {'unknown', 'acked'}:
                return await self._reconcile_share(scope, row)
        for candidate in self._candidates(scope):
            key = candidate['dedupe_key']
            previous = self.journal.fetch(SHARES, key, scope)
            event_id = event_id_for(self.clock())
            if previous:
                if previous['data']['phase'] != 'blocked' or previous['data']['engine_event_id'] == event_id: continue
            actual = await self.proactive._fetch(scope)
            if actual and (actual['data']['phase'] in _WAITING or actual['data']['event_id'] == event_id):
                return dict(state='deferred', reason='existing_shared_lane_event_retained')
            topic = ('有来源的个人目标分享：' + candidate['topic'] + '。' + candidate['motive']
                     + '。依据：' + candidate['evidence'])[:300]
            topic = ' '.join(topic.split())
            task_id = make_task(scope, event_id, text='identity', now=self.clock())['id']
            work = dict(schema=1, key=key, scope=scope, candidate=candidate, engine_event_id=event_id,
                task_id=task_id, topic=topic, phase='attempting', created_at=self.clock(),
                delivery_confirmed=False, claim_attempted=False)
            row = self._share_put(scope, work, previous['revision'] if previous else 0)
            self._put(NAMESPACE, 'active_share', scope, dict(key=key), pointer['revision'] if pointer else 0, operation='share')
            # One existing lane owns generation, model/image budget, quiet hours,
            # shared cadence, queueing, permission and platform confirmation.
            result = await self.proactive.tick(scope, topic)
            actual = await self.proactive._fetch(scope)
            if (actual and actual['data']['event_id'] == event_id
                    and actual['data'].get('signature') == _digest([scope, event_id, topic])):
                return await self._reconcile_share(scope, row)
            work['phase'] = 'blocked' if result.get('state') in {'blocked', 'disabled', 'busy'} else 'unknown'
            self._share_put(scope, work, row['revision'])
            return dict(state=work['phase'], reason=result.get('reason'), task_id=task_id)
        return dict(state='idle', reason='no_new_eligible_goal_share')

    async def tick(self, scope):
        scope = private_scope(scope)
        task = asyncio.current_task(); self._active_tasks.add(task)
        try:
            async with self._serial:
                source = await self._source(scope, 'advance')
                flags = self.settings(scope)['flags']; result = dict(state='current', generated=0, completed_items=0)
                if flags['auto_generate']:
                    for routines in ([False, True] if flags['routine_enabled'] else [False]):
                        try:
                            before = len(self.plans.list(scope, limit=MAX_PLANS)['records'])
                            await self.generate(scope, routines=routines)
                            after = len(self.plans.list(scope, limit=MAX_PLANS)['records'])
                            result['generated'] += max(0, after - before)
                        except ValueError as error:
                            result['planning_note'] = str(error)
                if flags['auto_progress']: result['completed_items'] = await self._advance(scope, source)
                result['share'] = await self._share(scope) if flags['share_enabled'] else dict(state='disabled')
                self._last[scope_key(scope)] = result
                return result
        except PermissionError:
            return dict(state='disabled', reason='scope_persona_or_goal_handoff_not_current')
        finally: self._active_tasks.discard(task)

    def owns_task(self, scope, task):
        try:
            scope = private_scope(scope)
            if task.get('scope') != scope: return False
            pointer = self.journal.fetch(NAMESPACE, 'active_share', scope)
            row = self.journal.fetch(SHARES, pointer['data']['key'], scope) if pointer else None
            if not row: return False
            if row['data']['task_id'] == task.get('id'): return True
            # A bucket transition still routes the matching topic here to deny a
            # mismatched task, rather than bypassing the source-specific gate.
            actual = self.journal.fetch('tls.native.proactive_companion.v1', 'pending', scope)
            return bool(actual and actual['data']['task_id'] == task.get('id')
                and actual['data'].get('signature') == _digest([scope, actual['data']['event_id'], row['data']['topic']]))
        except Exception: return False

    async def delivery_allowed(self, scope, task):
        try:
            scope = private_scope(scope)
            pointer = self.journal.fetch(NAMESPACE, 'active_share', scope)
            row = self.journal.fetch(SHARES, pointer['data']['key'], scope) if pointer else None
            return bool(row and row['data']['task_id'] == task.get('id')
                and row['data']['phase'] in _WAITING and await self._share_source_current(scope, row['data']))
        except Exception: return False

    def context_material(self, scope, limit=4):
        scope = self._material(scope); lines = []
        for plan in self.plans.list(scope, limit=MAX_PLANS)['records']:
            if plan['archived'] or plan['status'] != 'active': continue
            link = self.journal.fetch(NAMESPACE, 'plan.' + plan['id'], scope)
            if not link or link['data'].get('phase') != 'ready': continue
            for item in plan['items']:
                if item['status'] not in {'pending', 'completed'}: continue
                label = '虚构活动已到时完成' if item['status'] == 'completed' else '未来虚构计划，尚未完成'
                lines.append('－%s：%s（%s）' % (plan['date'], item['title'], label))
                if len(lines) >= limit: break
            if len(lines) >= limit: break
        return '\n'.join(['【明确归属的角色日常；均非现实观察】'] + lines) if lines else ''

    def diagnostics(self, scope=None):
        result = dict(active=self.active, live_scopes=len(self._scopes), old_goal_writer=self.handoff.status(),
            effective_native_goal_owned=self._goal_owned(),
            uses_existing_goal_store=True, uses_existing_proactive_lane=True, independent_scheduler=False,
            claim_only_after_actual_delivery=True, legacy_unowned_history_preserved=True, whole_pc_replaced=False)
        if scope is None: return result
        scope = self._material(scope); key = scope_key(scope)
        pointer = self.journal.fetch(NAMESPACE, 'active_share', scope)
        row = self.journal.fetch(SHARES, pointer['data']['key'], scope) if pointer else None
        return dict(result, settings=self.settings(scope), genuine_scope_registered=key in self._scopes,
            last_tick=self._last.get(key), share=dict(phase=row['data']['phase'],
                delivery_confirmed=row['data'].get('delivery_confirmed', False),
                automatic_retry=False) if row else None)

    def stop(self):
        self.active = False; self._source_epoch += 1; self._scopes.clear()
        self.handoff.stop()

    async def close(self):
        self.stop()
        pending = [task for task in self._active_tasks if task is not asyncio.current_task() and not task.done()]
        if pending: await asyncio.wait(pending, timeout=10)

    def native_closed(self):
        """A queued or unknown goal task prevents blindly restoring old writers."""
        if self.active or any(not task.done() for task in self._active_tasks): return False
        # The legacy flag is global, so closure covers every persisted native
        # scope, including scopes whose RAM inbound registration was discarded.
        with self.journal._lock:
            rows = self.journal._db.execute('SELECT data FROM checkpoints WHERE namespace=? LIMIT 4097', (SHARES,)).fetchall()
        if len(rows) > 4096: return False
        for row in rows:
            work = json.loads(row['data'])
            if work['phase'] == 'claim_unknown': return False
            if work['phase'] not in _WAITING | {'unknown', 'acked'}: continue
            if self.proactive is None: return False
            try: task = self.proactive.runtime.delivery.store.get(work.get('task_id'))
            except Exception: return False
            if not task or task.get('state') not in {'confirmed', 'failed', 'cancelled', 'expired'}: return False
        return True
