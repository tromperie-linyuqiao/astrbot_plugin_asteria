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
_SHARE_REASONS = {
    'scope_or_lane_unavailable': '当时范围或统一发送通道不可用',
    'one_proactive_tick_inflight': '当时已有主动消息操作在处理',
    'clock_moved_backwards': '当时检测到时钟回退',
    'handoff_transition': '当时服务仍处于切换等待期',
    'pending_scope_capacity': '当时待处理范围已达容量上限',
    'native_admission_denied': '当时未通过原统一发送通道的接纳检查',
    'proactive_pending_conflict': '当时原待处理记录发生版本冲突',
    'proactive_input_or_state_unavailable': '当时输入或原主动状态不可用',
    'proactive_tick_failed': '当时主动操作失败',
}


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
        self.life_source = None
        self.life_coordinator = None
        self.defaults = self._settings(defaults or _DEFAULTS)
        self.active = True; self._scopes = {}; self._serial = asyncio.Lock()
        self._last = {}; self._last_at = {}; self._active_tasks = set(); self._source_epoch = 0

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

    @staticmethod
    def _generation_intent(scope, persona, day, routines):
        if type(routines) is not bool or type(day) is not str or date.fromisoformat(day).isoformat() != day:
            raise ValueError('exact role-calendar day and routine flag required')
        persona = _text(persona, 256)
        request = 'pc.daily.' + _digest([scope, persona, day, 'routine' if routines else 'goals'])
        return dict(day=day, routines=routines, persona_id=persona, request_id=request,
                    plan_id='plan.' + _digest([scope, request]))

    def _checked_generation_intent(self, scope, value):
        if type(value) is not dict or set(value) != {'day', 'routines', 'persona_id', 'request_id', 'plan_id'}:
            raise ValueError('complete original generation intent required')
        expected = self._generation_intent(scope, value['persona_id'], value['day'], value['routines'])
        if value != expected: raise ValueError('generation intent does not match this exact scope')
        return expected

    def generation_status(self, scope, intent):
        """Read an existing exact mapping, never repair it or grant a live source."""
        scope = self._material(scope)
        intent = self._checked_generation_intent(scope, intent)
        now = datetime.fromtimestamp(self.clock(), self.plans.timezone)
        result = dict(state='not_found', reason_code='generation_not_confirmed',
            reason_label='尚未找到该意图的完整计划证明；不能据此认定原请求未执行或重新提交。',
            can_generate=False, intent=intent, role_date=now.date().isoformat(),
            timezone=self.plans.timezone_name, suggested_day=None)
        link = self.journal.fetch(NAMESPACE, 'plan.' + intent['plan_id'], scope)
        plan = self.plans.get(scope, intent['plan_id'])
        if link is None:
            if plan is not None: result.update(state='inconsistent', reason_code='generation_source_missing')
            return result
        proof = link['data']
        if (proof.get('schema') != 1 or proof.get('fictional') is not True
                or proof.get('legacy_history_migrated') is not False
                or type(proof.get('inbound_event_id')) is not str or not proof['inbound_event_id'].strip()
                or proof.get('scope') != scope or proof.get('plan_id') != intent['plan_id']
                or proof.get('persona_id') != intent['persona_id']
                or proof.get('kind') != ('routine' if intent['routines'] else 'goals')
                or proof.get('source') != 'genuine_private_inbound_sdk_selection'):
            return dict(result, state='inconsistent', reason_code='generation_source_changed')
        if proof.get('phase') != 'ready':
            return dict(result, state='pending', reason_code='generation_preparing',
                reason_label='已有该意图的准备记录，但没有完整完成证明；保留原记录，不自动重发。')
        actor = 'inbound.' + _digest([scope, intent['persona_id']])[:32]
        if (plan is None or plan.get('scope') != scope or plan.get('date') != intent['day']
                or plan.get('provenance', {}).get('request_id') != intent['request_id']
                or plan.get('provenance', {}).get('actor') != actor):
            return dict(result, state='inconsistent', reason_code='generation_plan_changed')
        self._material(scope)
        return dict(result, state='confirmed', reason_code='generation_plan_exists', plan=plan,
            reason_label='该意图对应的计划已存在；这不证明是本次请求新建。')

    def _routine_items(self, target, now):
        items = []
        for hour, title in [(10, '整理日常思绪'), (15, '留一段轻松休息的时间'), (21, '回顾今天的虚构经历')]:
            at = datetime.combine(target, time(hour, 0), self.plans.timezone).timestamp()
            if at > now:
                items.append(dict(title=title, description='目标之外的虚构角色日常；仅在到时或明确完成后记为角色事件。',
                                  scheduled_at=at, goal_ids=[]))
        return items

    def _generation_block(self, scope, target, routines, now):
        tomorrow = (datetime.fromtimestamp(now, self.plans.timezone).date() + timedelta(days=1)).isoformat()
        if routines and not self._routine_items(target, now):
            return dict(reason_code='no_future_routine_slot', suggested_day=tomorrow,
                reason_label='角色所在时区的当天已没有未来日常时段，请选择明天或之后的日期；未创建计划。')
        if not routines:
            goals = [row for row in self.plans.goal_options(scope) if row['status'] == 'active' and not row['archived']]
            if not goals:
                return dict(reason_code='no_active_goals', suggested_day=None,
                    reason_label='当前范围没有可用的进行中目标；请先在个人目标中维护目标，再准备目标计划。')
            start = datetime.combine(target, time(9, 0), self.plans.timezone).timestamp()
            if start <= now: start = (math.floor(now / 1800) + 1) * 1800
            if datetime.fromtimestamp(start, self.plans.timezone).date() != target:
                return dict(reason_code='no_future_goal_slot', suggested_day=tomorrow,
                    reason_label='角色当天已没有未来目标时段，请选择明天或之后的日期；未创建计划。')
        return None

    async def generation_preview(self, scope, *, day=None, routines=False):
        """Bind a new UI intent to the actual persona/date without writing."""
        scope = private_scope(scope)
        source = await self._source(scope, 'generate')
        now = self.clock(); today = datetime.fromtimestamp(now, self.plans.timezone).date()
        target = today if day is None else date.fromisoformat(day)
        if target < today or target > today + timedelta(days=7):
            raise ValueError('select today or one of the next seven role-calendar days')
        intent = self._generation_intent(scope, source['persona_id'], target.isoformat(), routines)
        result = self.generation_status(scope, intent)
        if result['state'] != 'not_found': return result
        blocked = self._generation_block(scope, target, routines, now)
        if blocked: return dict(result, state='blocked', **blocked)
        return dict(result, state='ready', can_generate=True, reason_code='generation_ready',
            reason_label='当前可以准备该意图的计划；仍需点击原生成操作后提交。')

    async def generate(self, scope, *, day=None, routines=False, expected_generation=None):
        scope = private_scope(scope)
        source = await self._source(scope, 'generate')
        now = self.clock(); today = datetime.fromtimestamp(now, self.plans.timezone).date()
        target = today if day is None else date.fromisoformat(day)
        if target < today or target > today + timedelta(days=7):
            raise ValueError('select today or one of the next seven role-calendar days')
        day = target.isoformat()
        intent = self._generation_intent(scope, source['persona_id'], day, routines)
        if expected_generation is not None and self._checked_generation_intent(scope, expected_generation) != intent:
            raise JournalConflict('预检后的角色、日期或计划类型已变化；未执行该次计划准备')
        request, plan_id = intent['request_id'], intent['plan_id']
        link_key = 'plan.' + plan_id
        link = self.journal.fetch(NAMESPACE, link_key, scope)
        if link is not None and link['data'].get('phase') == 'ready':
            existing = self.plans.get(scope, plan_id)
            if existing is None: raise RuntimeError('sourced daily plan is missing; do not recreate history')
            return existing
        actor = 'inbound.' + _digest([scope, source['persona_id']])[:32]
        # Known refusal must happen before creating even a preparing proof.
        # Existing proofs/plans are retained and never rewritten by this check.
        existing = self.plans.get(scope, plan_id)
        if existing is None:
            blocked = self._generation_block(scope, target, routines, now)
            if blocked: raise ValueError(blocked['reason_label'])
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
        if existing is not None:
            if existing['provenance']['actor'] != actor:
                raise JournalConflict('existing daily plan has another creation source')
            proof['phase'] = 'ready'
            self._put(NAMESPACE, link_key, scope, proof, link['revision'], operation='generate')
            return existing
        if routines:
            # These are explicitly fictional proposals, never imported global
            # PC history or claims about real observation, reading, or skills.
            items = self._routine_items(target, now)
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
            if (link['data'].get('kind') == 'routine' and self.life_coordinator
                    and self.life_coordinator.owns_generation(scope)): continue
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
        life = self.life_source
        life_owned = bool(self.life_coordinator and self.life_coordinator.owns_generation(scope))
        if life is not None and life.active:
            rows += life.proactive_candidates(scope, include_ineligible=include_ineligible)
        source = self.daily_source
        if not life_owned and source is not None and getattr(source, 'active', False) is True:
            rows += source.proactive_candidates(scope)
        return sorted(rows, key=lambda row: (-row['score'], row['candidate_id']))[:16]

    async def _share_source_current(self, scope, work):
        try:
            await self._source(scope, 'share')
            if not self.settings(scope)['flags']['share_enabled']: return False
            if work['candidate']['source'] == 'autonomous_life':
                life = self.life_source
                if life is None or not life.active: return False
                policy = life.settings(scope)['settings']
                event = life.get_event(scope, work['candidate']['event_id'])
                return bool(policy['enabled'] and policy['share_enabled'] and event and event['valid']
                    and not event['archived'] and event['version'] == work['candidate']['event_version']
                    and not any(topic.casefold() in (event['fields']['title']+' '+event['fields']['content']).casefold()
                        for topic in policy.get('muted_topics', [])))
            candidate = self._candidate(scope, work['candidate']['candidate_id'])
            return (candidate is not None and candidate['eligible'] is True
                    and candidate['dedupe_key'] == work['candidate']['dedupe_key'])
        except Exception: return False

    def _share_put(self, scope, work, revision):
        return self._put(SHARES, work['key'], scope, work, revision, operation='share')

    async def _life_image_followup(self, scope, work):
        if work['candidate']['source'] != 'autonomous_life' or work.get('phase') != 'claimed':
            return None
        try:
            from .chat_generated_images import service_for
            service = service_for(self.proactive.host.plugin)
            return await service.followup_for_share(scope, work['task_id'],
                work['candidate']['event_id'], work['candidate']['event_version'])
        except (RuntimeError, ValueError, PermissionError, KeyError, AttributeError, OSError):
            return None  # Saved text and its original delivery remain intact.

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
            if candidate['source'] == 'autonomous_life':
                if self.life_source is None: raise PermissionError('life owner unavailable')
                saved = self.life_source.record_share(scope, candidate['event_id'], task_id=work['task_id'],
                    state='confirmed', event_version=candidate['event_version'])
            elif candidate['source'] == 'pc_virtual_life':
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
        await self._life_image_followup(scope, work)
        return dict(state=work['phase'], task_id=work['task_id'], delivery_confirmed=True)

    async def _reconcile_share(self, scope, row):
        work = dict(row['data'])
        if work['phase'] in {'acked'}: return await self._claim_confirmed(scope, row)
        if work['phase'] in _SETTLED or work['phase'] == 'unknown':
            if work['phase'] == 'claimed': await self._life_image_followup(scope, work)
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
        if work['candidate']['source'] == 'autonomous_life' and self.life_source is not None and work['phase'] in {'failed','dropped','unknown'}:
            self.life_source.record_share(scope, work['candidate']['event_id'], task_id=work['task_id'],
                state='unknown' if work['phase']=='unknown' else 'failed',
                event_version=work['candidate']['event_version'], detail=work['phase'])
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
            if row['data']['phase'] == 'claimed':
                # Recover the accepted follow-up by its same durable identity
                # if the process stopped between text claim and job creation.
                await self._life_image_followup(scope, row['data'])
        for candidate in self._candidates(scope):
            key = candidate['dedupe_key']
            previous = self.journal.fetch(SHARES, key, scope)
            event_id = event_id_for(self.clock())
            if previous:
                if previous['data']['phase'] != 'blocked' or previous['data']['engine_event_id'] == event_id: continue
            actual = await self.proactive._fetch(scope)
            if actual and (actual['data']['phase'] in _WAITING or actual['data']['event_id'] == event_id):
                return dict(state='deferred', reason='existing_shared_lane_event_retained')
            topic = (('有来源的虚构生活分享：' if candidate['source'] == 'autonomous_life' else '有来源的个人目标分享：') + candidate['topic'] + '。' + candidate['motive']
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
            # Text takes the existing admission and queue first. A confirmed
            # life share may attach one image later under that same admission;
            # generating a picture never blocks the initial message.
            result = await self.proactive.tick(scope, topic,
                **({'text_only': True} if candidate['source'] == 'autonomous_life' else {}))
            actual = await self.proactive._fetch(scope)
            if candidate['source'] == 'autonomous_life' and actual and actual['data'].get('task_id') == task_id:
                self.life_source.record_share(scope, candidate['event_id'], task_id=task_id,
                    state='queued' if actual['data']['phase'] in _WAITING | {'acked'} else 'unknown',
                    event_version=candidate['event_version'], detail='existing_shared_lane')
            if (actual and actual['data']['event_id'] == event_id
                    and actual['data'].get('signature') == _digest([scope, event_id, topic])):
                return await self._reconcile_share(scope, row)
            work['phase'] = 'blocked' if result.get('state') in {'blocked', 'disabled', 'busy'} else 'unknown'
            reason = result.get('reason')
            if type(reason) is str and reason in _SHARE_REASONS: work['reason_code'] = reason
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
                    life_owned = bool(self.life_coordinator and self.life_coordinator.owns_generation(scope))
                    for routines in ([False, True] if flags['routine_enabled'] and not life_owned else [False]):
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
                self._last_at[scope_key(scope)] = self.clock()
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
        reason = row['data'].get('reason_code') if row else None
        reason = reason if type(reason) is str and reason in _SHARE_REASONS else None
        return dict(result, settings=self.settings(scope), genuine_scope_registered=key in self._scopes,
            last_tick=self._last.get(key), last_tick_at=self._last_at.get(key), share=dict(phase=row['data']['phase'],
                delivery_confirmed=row['data'].get('delivery_confirmed', False),
                created_at=row['data'].get('created_at'), updated_at=row['updated_at'],
                reason_code=reason, reason_label=_SHARE_REASONS.get(reason, '原记录未保存可核对的原因，不能据此推断当前状态。'),
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
