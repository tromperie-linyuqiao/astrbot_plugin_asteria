"""Exact-instance PC goal writer transfer; unrelated PC duties keep running.

The Host supplies the already inspected live owner and the existing config
writer. No legacy data, task or lease is deleted. Cached old bound methods are
covered by the total flag, the original data lock and await-chain drainage;
the already registered admin route is fenced as well as the instance method.
"""
from __future__ import annotations

import asyncio
import inspect
import math
from types import MethodType

SLOT = '_tls_native_pc_goal_owner'
GOAL_METHODS = ('_maybe_settle_personal_goals', '_queue_personal_goal_candidate_locked')
SENSITIVE = ('_tick', '_tick_inner', '_render_message', '_send_proactive_message_chain',
             '_send_chain_components', '_send_companion_chain_atomic',
             '_generate_proactive_message_with_llm', '_generate_proactive_message_via_framework')


class PCGoalHandoffError(RuntimeError):
    pass


async def _value(value):
    return await value if inspect.isawaitable(value) else value


class NativePCGoalHandoff:
    def __init__(self, owner, context, *, source_current, set_legacy_enabled,
                 native_closed, drain_timeout=10):
        if not all(callable(item) for item in (source_current, set_legacy_enabled, native_closed)):
            raise ValueError('current inspected owner, existing config writer and native closure required')
        if type(drain_timeout) not in (int, float) or not math.isfinite(drain_timeout) or not 0 < drain_timeout <= 30:
            raise ValueError('bounded drain timeout required')
        self.owner, self.context = owner, context
        self.source_current, self.set_legacy_enabled, self.native_closed = source_current, set_legacy_enabled, native_closed
        self.timeout = float(drain_timeout)
        self._lock = asyncio.Lock(); self._loop = None
        self._original = {}; self._own = {}; self._routes = []
        self._page = self._data_lock = None; self._old_enabled = None
        self._phase = 'unprepared'; self._owned = False; self._reason = ''
        self._codes = set(); self._blocked = 0; self._last_inventory = None

    def _current(self):
        try:
            value = self.source_current(self.owner)
            if inspect.isawaitable(value):
                if inspect.iscoroutine(value): value.close()
                return False
            return value is True
        except Exception: return False

    def _bind(self):
        loop = asyncio.get_running_loop()
        if self._loop is None: self._loop = loop
        if loop is not self._loop: raise PCGoalHandoffError('same_event_loop_required')
        if not self._current(): raise PCGoalHandoffError('legacy_owner_or_reviewed_source_changed')

    @staticmethod
    def _method(owner, name, *, asynchronous):
        value = getattr(owner, name, None)
        if (not inspect.ismethod(value) or value.__self__ is not owner
                or inspect.iscoroutinefunction(value) is not asynchronous):
            raise PCGoalHandoffError('exact_legacy_method_unavailable:' + name)
        return value

    def _prepare(self):
        self._bind()
        if vars(self.owner).get(SLOT) not in (None, self):
            raise PCGoalHandoffError('another_goal_owner_present')
        self._data_lock = vars(self.owner).get('_data_lock')
        if not isinstance(self._data_lock, asyncio.Lock): raise PCGoalHandoffError('original_data_lock_required')
        enabled = getattr(self.owner, 'enable_personal_goals', None)
        if type(enabled) is not bool: raise PCGoalHandoffError('exact_total_goal_flag_required')
        self._old_enabled = enabled
        page = vars(self.owner).get('page_api')
        if page is None or vars(page).get('plugin') is not self.owner:
            raise PCGoalHandoffError('original_goal_page_instance_required')
        self._page = page
        for name, asynchronous in ((GOAL_METHODS[0], True), (GOAL_METHODS[1], False)):
            value = self._method(self.owner, name, asynchronous=asynchronous)
            self._original[(id(self.owner), name)] = (self.owner, value, vars(self.owner).get(name), name in vars(self.owner))
            self._codes.add(value.__func__.__code__)
        page_handler = self._method(page, 'update_personal_goal', asynchronous=True)
        self._original[(id(page), 'update_personal_goal')] = (page, page_handler, vars(page).get('update_personal_goal'), 'update_personal_goal' in vars(page))
        self._codes.add(page_handler.__func__.__code__)
        for name in SENSITIVE:
            value = getattr(self.owner, name, None)
            if inspect.ismethod(value) and value.__self__ is self.owner: self._codes.add(value.__func__.__code__)
        registry = getattr(self.context, 'registered_web_apis', None)
        if type(registry) is not list or len(registry) > 4096: raise PCGoalHandoffError('sdk_dynamic_route_registry_required')
        matches = [(index, row) for index, row in enumerate(registry)
                   if isinstance(row, tuple) and len(row) == 4 and row[1] == page_handler]
        if not matches or any('POST' not in row[2] for _, row in matches):
            raise PCGoalHandoffError('exact_registered_goal_write_route_required')
        self._registry = registry; self._routes = [(index, row, None) for index, row in matches]

    def _install(self):
        controller = self
        async def blocked_settle(_owner, *args, **kwargs):
            controller._blocked += 1
            return None
        def blocked_queue(_owner, *args, **kwargs):
            controller._blocked += 1
            return 0
        async def blocked_page(_page, *args, **kwargs):
            from astrbot.api.web import error_response
            controller._blocked += 1
            return error_response('个人目标写入已交由 TLS，请使用 TLS 个人目标与日常面板。', status_code=409)
        for owner, name, function in ((self.owner, GOAL_METHODS[0], blocked_settle),
                (self.owner, GOAL_METHODS[1], blocked_queue), (self._page, 'update_personal_goal', blocked_page)):
            bound = MethodType(function, owner)
            setattr(owner, name, bound); self._own[(id(owner), name)] = bound
        handler = self._own[(id(self._page), 'update_personal_goal')]
        replaced = []
        for index, old, _ in self._routes:
            if self._registry[index] is not old: raise PCGoalHandoffError('goal_route_changed_during_install')
            new = (old[0], handler, old[2], old[3])
            self._registry[index] = new; replaced.append((index, old, new))
        self._routes = replaced
        setattr(self.owner, SLOT, self)

    def _slots_current(self):
        return (self._current() and vars(self.owner).get(SLOT) is self
                and vars(self.owner).get('_data_lock') is self._data_lock
                and getattr(self.owner, 'enable_personal_goals', None) is False
                and all(getattr(owner, name, None) is self._own.get(key)
                        for key, (owner, _old, _raw, _had) in self._original.items()
                        for name in [key[1]])
                and getattr(self.context, 'registered_web_apis', None) is self._registry
                and all(index < len(self._registry) and self._registry[index] is new for index, _, new in self._routes))

    def _busy(self):
        current = asyncio.current_task(); busy = []
        tasks = asyncio.all_tasks()
        if len(tasks) > 1024: raise PCGoalHandoffError('task_scan_capacity_exceeded')
        for task in tasks:
            if task is current or task.done(): continue
            value = task.get_coro(); seen = set()
            for _ in range(96):
                if value is None: break
                if id(value) in seen: raise PCGoalHandoffError('ambiguous_task_chain')
                seen.add(id(value))
                if inspect.iscoroutine(value): code, value = value.cr_code, value.cr_await
                elif inspect.isgenerator(value): code, value = value.gi_code, value.gi_yieldfrom
                else: break
                if code in self._codes:
                    busy.append(task); break
            else: raise PCGoalHandoffError('task_chain_capacity_exceeded')
        return busy

    async def _drain(self):
        end = asyncio.get_running_loop().time() + self.timeout
        while True:
            if not self._slots_current(): raise PCGoalHandoffError('goal_fence_or_source_changed')
            # A coroutine that passed the old flag before closure may already be
            # waiting for this exact lock. Do not cancel it or erase its result.
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0: raise PCGoalHandoffError('legacy_goal_drain_timeout')
            await asyncio.wait_for(self._data_lock.acquire(), timeout=remaining)
            self._data_lock.release()
            if not self._busy(): return
            await asyncio.sleep(min(.05, max(.001, end - asyncio.get_running_loop().time())))

    def inventory(self):
        data = vars(self.owner).get('data')
        if type(data) is not dict: raise PCGoalHandoffError('legacy_goal_inventory_unknown')
        goals, pool, users = data.get('personal_goals', []), data.get('proactive_candidate_pool', []), data.get('users', {})
        if type(goals) is not list or type(pool) is not list or type(users) is not dict or max(len(goals), len(pool), len(users)) > 4096:
            raise PCGoalHandoffError('legacy_goal_inventory_shape_unknown')
        if any(type(row) is not dict for row in goals + pool + list(users.values())):
            raise PCGoalHandoffError('legacy_goal_inventory_row_unknown')
        candidates = sum(row.get('source') == 'personal_goal' or row.get('reason') == 'personal_goal_progress'
                         or row.get('context_key') == 'planned_personal_goal_context' for row in pool)
        planned = sum(bool(row.get('planned_personal_goal_context')) or row.get('planned_proactive_source') == 'personal_goal'
                      or row.get('planned_proactive_reason') == 'personal_goal_progress' for row in users.values())
        pending = sum(bool(row.get('pending_share_event')) for row in goals)
        result = dict(legacy_goals=len(goals), personal_goal_candidates=candidates,
                      planned_goal_users=planned, pending_share_events=pending,
                      inflight=len(self._busy()), unknown_dispositions=0,
                      legacy_global_plans_preserved=True, legacy_scope_migration=False)
        self._last_inventory = result
        return result

    async def activate(self):
        async with self._lock:
            self._bind()
            if self._owned and self._slots_current(): return self.status()
            if self._phase not in {'unprepared', 'restored'}: raise PCGoalHandoffError('existing_transition_must_be_reconciled')
            self._prepare(); self._phase = 'closing_legacy'; self._install()
            try:
                await _value(self.set_legacy_enabled(False))
                if getattr(self.owner, 'enable_personal_goals', None) is not False:
                    raise PCGoalHandoffError('legacy_total_goal_flag_not_closed')
                await self._drain()
                async with self._data_lock:
                    inventory = self.inventory()
                    if any(inventory[key] for key in ('personal_goal_candidates', 'planned_goal_users', 'pending_share_events', 'inflight', 'unknown_dispositions')):
                        raise PCGoalHandoffError('legacy_goal_pending_or_unknown_must_be_reconciled')
                    if not self._slots_current(): raise PCGoalHandoffError('legacy_goal_fence_changed')
                    self._owned = True; self._phase = 'native'; self._reason = ''
            except BaseException as error:
                # Retain every original reference and the closed fence. Caller
                # stops native admission, then uses explicit restore, not retry.
                self._owned = False; self._phase = 'closed_pending'; self._reason = type(error).__name__
                raise
            return self.status()

    def owns(self):
        return self._owned and self._phase == 'native' and self._slots_current()

    def stop(self):
        self._owned = False
        if self._phase == 'native': self._phase = 'closed'

    async def restore(self):
        async with self._lock:
            self._bind(); self.stop()
            closed = self.native_closed()
            if inspect.isawaitable(closed):
                if inspect.iscoroutine(closed): closed.close()
                closed = False
            if closed is not True: raise PCGoalHandoffError('native_tasks_and_admission_must_be_closed')
            if not self._slots_current(): raise PCGoalHandoffError('cannot_restore_changed_fence_or_source')
            await self._drain()
            for index, old, own in self._routes:
                if self._registry[index] is not own: raise PCGoalHandoffError('goal_route_restore_conflict')
            for key, (owner, _old, _raw, _had) in self._original.items():
                if getattr(owner, key[1], None) is not self._own[key]: raise PCGoalHandoffError('goal_method_restore_conflict')
            for index, old, _ in self._routes: self._registry[index] = old
            for key, (owner, _old, raw, had) in self._original.items():
                if had: setattr(owner, key[1], raw)
                else: delattr(owner, key[1])
            if vars(self.owner).get(SLOT) is not self: raise PCGoalHandoffError('goal_owner_restore_conflict')
            delattr(self.owner, SLOT)
            self._phase = 'restoring_configuration'
            try:
                await _value(self.set_legacy_enabled(self._old_enabled))
                if getattr(self.owner, 'enable_personal_goals', None) is not self._old_enabled:
                    raise PCGoalHandoffError('legacy_total_flag_restore_unknown')
            except BaseException:
                self._phase = 'restore_unknown'; raise
            self._phase = 'restored'; self._reason = ''
            return self.status()

    def status(self):
        return dict(phase=self._phase, native_owned=self.owns(), installed=vars(self.owner).get(SLOT) is self,
                    legacy_total_goal_enabled=getattr(self.owner, 'enable_personal_goals', None),
                    blocked_old_goal_calls=self._blocked, last_inventory=self._last_inventory,
                    reason=self._reason, whole_pc_replaced=False, shared_memo_owner_helper_unchanged=True)
