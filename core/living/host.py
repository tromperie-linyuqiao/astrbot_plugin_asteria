"""Opt-in observation journal adapter over the existing Presence projection.

No collectors, simulation state or scheduling live here. The synchronous
observer only schedules bounded work; journal/governance I/O runs off-loop.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import time
from typing import Any

from .journal import LivingJournal
from .models import EvidenceKind, Observation, private_scope


_EVIDENCE = {"observed": EvidenceKind.REAL_OBSERVATION,
             "reported": EvidenceKind.USER_REPORTED,
             "inferred": EvidenceKind.MODEL_INFERENCE,
             "simulated": EvidenceKind.ROLEPLAY_EVENT,
             "derived": EvidenceKind.MODEL_INFERENCE}
_PRIVATE_FIELDS = frozenset({"summary", "prompt", "system_prompt", "persona", "profile",
                            "profiles", "raw", "raw_text", "raw_message", "message",
                            "message_str", "lyrics", "instructions", "constraint_text"})


def _journal_value(value: Any) -> Any:
    """Exclude rendered prompts and raw conversation/profile fields."""
    if isinstance(value, dict):
        return {key: _journal_value(item) for key, item in value.items()
                if key.casefold() not in _PRIVATE_FIELDS}
    if isinstance(value, list):
        return [_journal_value(item) for item in value]
    return copy.deepcopy(value)


def observation_from_presence(scope: dict, record: dict) -> Observation:
    """Keep source clocks/evidence; never timestamp a historical fact as new."""
    meta = record.get("meta") or {}
    source, domain = record["source"], record["domain"]
    original = meta.get("evidence_kind", "observed")
    evidence = _EVIDENCE[original]
    provenance = {"adapter": "presence_v1", "source_id": source,
                  "domain": domain, "presence_evidence_kind": original,
                  "source_revision": meta.get("source_revision")}
    if domain == "time" and source == "presence.environment" and original in {"observed", "derived"}:
        evidence = EvidenceKind.REAL_OBSERVATION
        provenance["method"] = "server_clock"
    elif domain.startswith("virtual."):
        evidence = EvidenceKind.ROLEPLAY_EVENT
        provenance["method"] = "existing_virtual_engine"
    return Observation(source_id=source, observation_type=domain, scope=scope,
        observed_at=meta.get("observed_at"), received_at=meta["received_at"],
        expires_at=meta.get("expires_at"), payload=_journal_value(record.get("value")),
        provenance=provenance, permission_scope="observe.persist", evidence_kind=evidence,
        status=record.get("status", "unknown"), device_id=meta.get("device_id"),
        change_key=_journal_value(meta.get("change_key")), importance=meta.get("importance", "normal"))


class LivingHost:
    """One optional audit lane; the Presence cache remains the only live view."""

    def __init__(self, plugin, context, presence, *, clock=time.time,
                 journal_factory=LivingJournal, governance_factory=None, runtime_factory=None,
                 frequency_factory=None, presence_policy_factory=None, max_pending=8):
        self.plugin, self.context, self.presence = plugin, context, presence
        self.clock = clock
        self._journal_factory = journal_factory
        self._governance_factory = governance_factory
        self._runtime_factory = runtime_factory
        self._frequency_factory = frequency_factory
        self._presence_policy_factory = presence_policy_factory
        self.max_pending = min(max(int(max_pending), 1), 8)
        self.journal = self.governance = self.runtime = None
        self._closed = False
        self._start_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._cleanup_task = None
        self.coordinator = self.ability = None
        self._trusted_scope = None  # Inbound identity only; deliberately not restored from disk.
        self._exploration_task = None
        self._phone_task = None
        self._proactive_task = None
        self._pc_task = None
        self._native_business_steps = {}
        self.native_phone_music = None
        self.selected_persona = None
        self._selected_persona_error = None
        self._observer = self._accepted
        self.metrics = {"scheduled": 0, "completed": 0, "denied": 0,
                        "invalid": 0, "overflow": 0, "no_event_loop": 0, "errors": 0}

    def _enabled(self) -> bool:
        return (not self._closed and not getattr(self.plugin, "_stopping", False)
                and self.plugin._cfg_bool("living_system_enabled", False)
                and self.presence.active)

    def _source_allowed(self, source: str) -> bool:
        try:
            values = self.plugin._cfg("living_allowed_sources", [])
            return isinstance(values, list) and source in values and all(isinstance(v, str) for v in values)
        except Exception:
            return False

    def authorized_scope(self, scope: dict) -> bool:
        """Fresh binding plus the genuine private-session identity lease."""
        try:
            active_read = getattr(self.presence, 'authorization_active', None)
            presence_enabled = active_read() if callable(active_read) else self.presence.active
            if (self._closed or getattr(self.plugin, '_stopping', False)
                    or not self.plugin._cfg_bool('living_system_enabled', False)
                    or not presence_enabled):
                return False
            if (self.coordinator is not None and
                    str(self.plugin._cfg("living_catalog_path", "")).strip() != self.coordinator.configured_path):
                return False
            normalized = private_scope(scope)
            resolved = self.plugin._resolve_session(normalized["user_id"])
            # The real Presence implementation offers a non-mutating lookup
            # for database-worker authorization. Keep old isolated seams usable.
            lookup = getattr(self.presence, 'peek_scope_for_session', self.presence.scope_for_session)
            return bool(resolved is not None and resolved[0] == normalized["character_id"]
                        and lookup(normalized["session_id"]) == normalized)
        except Exception:
            return False

    def _build_runtime(self, journal):
        governance_factory = self._governance_factory
        runtime_factory = self._runtime_factory
        if governance_factory is None:
            from .governance import Governance
            governance_factory = Governance
        if runtime_factory is None:
            from .runtime import LivingRuntime
            runtime_factory = LivingRuntime
        frequency = None
        if self.plugin._cfg_bool("living_frequency_migration_enabled", False):
            from .frequency_router import FrequencyPolicyRouter
            frequency_args = dict(resolve_scope=self._frequency_scope,
                authorized_scope=lambda scope: self.plugin._cfg_bool(
                    "living_frequency_migration_enabled", False) and self.authorized_scope(scope))
            if self._frequency_factory is None:
                frequency = FrequencyPolicyRouter(journal, **frequency_args, environment="host")
            else:
                frequency = self._frequency_factory(journal, **frequency_args)
        presence_policy = None
        try:
            if self._presence_policy_factory is not None:
                presence_policy = self._presence_policy_factory(journal,
                    authorized_scope=self.authorized_scope)
                if getattr(presence_policy, 'environment', None) != 'isolated':
                    raise PermissionError('Presence policy factory requires an isolated environment')
            governance = governance_factory(journal, clock=self.clock)
            runtime = runtime_factory(self.presence, journal, governance, clock=self.clock,
                                      scope_validator=self.authorized_scope)
            if hasattr(runtime, 'memory'):
                backend = self.plugin._cfg('living_memory_backend', 'legacy')
                if backend == 'native':
                    from .native_memory import NativeMemoryStore
                    from .native_memory_adapter import NativeMemoryAdapter
                    store = NativeMemoryStore(journal.path.parent / 'native_memory.sqlite3', clock=self.clock)
                    runtime.memory = NativeMemoryAdapter(store, authorize=self._native_memory_allowed, clock=self.clock)
                    from .native_profile_candidates import NativeProfileCandidates
                    runtime.profile_candidates=NativeProfileCandidates(store,clock=self.clock)
                    runtime.memory.profile_candidates=runtime.profile_candidates
                    self.plugin._native_profile_candidates=runtime.profile_candidates
                elif backend == 'legacy':
                    pass  # Preserve legacy construction order after the owned factories.
                else:
                    raise ValueError('invalid living_memory_backend')
            if getattr(getattr(runtime, 'memory', None), 'backend', None) == 'native':
                from .native_shared_timeline import NativeSharedTimeline
                runtime.shared_timeline = NativeSharedTimeline(runtime.memory.store,
                    authorize=self._native_memory_allowed, clock=self.clock)
            from .native_expression_learning import NativeExpressionLearning
            runtime.expression_learning = NativeExpressionLearning(journal,
                authorize=self.authorized_scope, clock=self.clock)
            from .native_expression_review import NativeExpressionReview
            runtime.expression_review = NativeExpressionReview(journal, runtime.expression_learning,
                authorize=self.authorized_scope, review_authorize=lambda scope, reviewer: False, clock=self.clock)
            from .native_music_library import NativeMusicLibrary
            runtime.music_library = NativeMusicLibrary(journal,
                authorize=self._native_memory_allowed, clock=self.clock)
            from .native_memo_notes import NativeMemoNotes
            runtime.memo_notes = NativeMemoNotes(journal,
                authorize=self._native_memory_allowed, clock=self.clock)
            from .native_expression_assets import NativeExpressionAssets
            from .native_expression_reply import NativeExpressionReplyPolicy, NativeExpressionReplyAdapter
            runtime.expression_assets = NativeExpressionAssets(journal,
                authorize=self._native_memory_allowed, clock=self.clock)
            expression_policy = NativeExpressionReplyPolicy(journal, runtime.expression_assets,
                authorize=self._native_memory_allowed, clock=self.clock,
                cooldown_seconds=600, daily_limit=8, tz_offset_minutes=480,
                settings=lambda: {
                    'living_expression_reply_enabled': self.plugin._cfg('living_expression_reply_enabled', True),
                    'living_expression_reply_daily_limit': self.plugin._cfg('living_expression_reply_daily_limit', 8),
                    'living_expression_reply_cooldown_minutes': self.plugin._cfg('living_expression_reply_cooldown_minutes', 10)})
            runtime.expression_reply = NativeExpressionReplyAdapter(expression_policy,
                scope_for=self.presence.scope_for_event, authorize=self._native_memory_allowed)
            runtime.memory_context_recovery = getattr(self.context, '_tls_memory_context_recovery', None)
            unified_factory = getattr(self.context, '_tls_unified_factory', None)
            if unified_factory is not None:
                unified = unified_factory(journal=journal, runtime=runtime,
                    presence=self.presence, authorize=self.authorized_scope,
                    governance=governance, clock=self.clock)
                if getattr(unified, 'environment', None) != 'isolated':
                    stop = getattr(unified, 'stop', None)
                    if callable(stop):
                        stop()
                    raise PermissionError('unified factory requires isolated environment')
                runtime.unified = unified
                runtime.memory_policy = getattr(unified, 'memory_policy', None)
            elif getattr(getattr(runtime, 'memory', None), 'backend', None) == 'native':
                from .unified_system import UnifiedSystem
                from .feature_context import NativeFeatureContextPolicy
                from .private_memory_context import NativePrivateMemoryContextPolicy
                runtime.unified = UnifiedSystem(journal=journal, runtime=runtime,
                    presence=self.presence, authorize=self.authorized_scope,
                    governance=governance, clock=self.clock, environment='native_memory',
                    feature_policy=NativeFeatureContextPolicy(),
                    private_memory_policy=NativePrivateMemoryContextPolicy())
            # Trusted test bootstrap only; there is no configuration/UI switch
            # that can enable a second production sender in this stage.
            delivery_factory=getattr(self.context,'_tls_delivery_factory',None)
            if delivery_factory is not None:
                delivery=delivery_factory(journal=journal,runtime=runtime,
                                          authorize=self.authorized_scope)
                if getattr(delivery,'environment',None) != 'isolated':
                    raise PermissionError('delivery factory requires isolated environment')
                runtime.delivery=delivery
            # Deliberate isolated bootstrap only. Merely upgrading a plugin or
            # changing its config cannot start another production reminder owner.
            reminder_factory=getattr(self.context, '_tls_reminder_factory', None)
            if reminder_factory is not None:
                reminders=reminder_factory(journal=journal, runtime=runtime,
                    authorize=self.authorized_scope)
                if (getattr(reminders, 'environment', None) != 'isolated'
                        or not all(callable(getattr(reminders, name, None))
                            for name in ('stop', 'close', 'diagnostics', 'abort_initialization'))):
                    abort=getattr(reminders, 'abort_initialization', None)
                    if callable(abort):
                        abort()
                    raise PermissionError('reminder factory requires isolated lifecycle contract')
                runtime.reminders=reminders
            if hasattr(runtime, 'memory') and self.plugin._cfg('living_memory_backend', 'legacy') == 'legacy':
                from .bridges import MemoryBridgeAdapter
                runtime.memory = MemoryBridgeAdapter(journal, clock=self.clock)
            from .native_history_archive import NativeHistoryArchive
            runtime.history_archive = NativeHistoryArchive(journal.path.parent / 'history_archive.sqlite3', clock=self.clock)
            if getattr(getattr(runtime, 'memory', None), 'backend', None) == 'native':
                from .native_history_adoption import NativeHistoryAdoption
                runtime.history_adoption = NativeHistoryAdoption(runtime.history_archive,
                    runtime.memory.store, authorize=self._native_memory_allowed, clock=self.clock)
                from .native_memory_transfer import NativeMemoryTransfer
                runtime.memory_transfer = NativeMemoryTransfer(runtime.memory.store,
                    authorize=self._native_memory_allowed, clock=self.clock)
            from .native_host_services import attach_native_services
            attach_native_services(self, runtime, journal.path.parent.parent)
            from .native_important_dates import NativeImportantDates
            runtime.important_dates = NativeImportantDates(journal,
                authorize=lambda scope: runtime.active and self.authorized_scope(scope), clock=self.clock)
            from calendar import timegm
            from ..decay import tz_local_time
            from .native_personal_goals import NativePersonalGoals
            # Snapshot the same configured/local offset used by the existing
            # role clock as an explicit minute-precision date-zone name.
            goal_now = self.clock()
            goal_offset = timegm(tz_local_time(goal_now)) - timegm(time.gmtime(goal_now))
            if goal_offset % 60:
                raise ValueError('personal goals require a minute-precision role timezone')
            goal_minutes = abs(goal_offset) // 60
            goal_timezone = 'UTC%s%02d:%02d' % (
                '+' if goal_offset >= 0 else '-', goal_minutes // 60, goal_minutes % 60)
            runtime.personal_goals = NativePersonalGoals(journal,
                authorize=lambda scope: runtime.active and self._native_memory_allowed(scope),
                clock=self.clock, timezone=goal_timezone)
            from .native_scoped_daily_plan import NativeScopedDailyPlans
            runtime.scoped_daily_plans = NativeScopedDailyPlans(journal,
                goals=runtime.personal_goals,
                authorize=lambda scope: runtime.active and self._native_memory_allowed(scope),
                authorize_activity=lambda scope: runtime.active and self._native_memory_allowed(scope),
                clock=self.clock, automatic_enabled=False)
            if getattr(runtime, 'reminders', None) is not None:
                from .reminders import ReminderService
                if isinstance(runtime.reminders, ReminderService):
                    from .native_agenda import NativeAgenda
                    runtime.agenda = NativeAgenda(runtime.reminders,
                        authorize=self.authorized_scope, clock=self.clock)
                elif not (reminder_factory is not None
                        and getattr(runtime.reminders,'environment',None)=='isolated'):
                    raise PermissionError('native agenda requires real reminder authority')
                # An explicitly injected isolated lifecycle fixture is not a
                # reminder authority and must never acquire an agenda writer.
            services=getattr(runtime,'native_services',None)
            if services is not None:services.configure_pc()
            if getattr(getattr(runtime, 'memory', None), 'backend', None) == 'native':
                sources = tuple((name, getattr(runtime, name)) for name in ('agenda', 'important_dates', 'memo_notes', 'personal_goals')
                                if getattr(runtime, name, None) is not None)
                def material_generation(scope):
                    try:
                        if (self.runtime is not runtime or not runtime.active
                                or runtime.journal is not journal or journal._closed
                                or runtime.important_dates.journal is not journal
                                or runtime.personal_goals.journal is not journal):
                            return None
                        tokens = []
                        for name, service in sources:
                            if getattr(runtime, name, None) is not service:
                                return None
                            token = service.context_generation(scope)
                            if token is None:
                                return None
                            tokens.append(token)
                        return ('native_date_material', tuple(tokens))
                    except Exception:
                        return None
                def material_reader(scope, *, limit=32):
                    if type(limit) is not int or not 1 <= limit <= 64:
                        raise ValueError('bounded date material limit required')
                    before = material_generation(scope)
                    if before is None:
                        raise PermissionError('native date material unavailable')
                    limits = {'memo_notes': 32, 'personal_goals': 16}
                    groups = [service.context_material(scope, limit=min(limit, limits.get(name, limit)))
                              for name, service in sources]
                    if material_generation(scope) != before:
                        raise PermissionError('native date material changed')
                    # Keep the pre-existing agenda represented even when the
                    # date library is full; final selection stays in Unified.
                    return [rows[index] for index in range(limit) for rows in groups if index < len(rows)][:limit]
                runtime.memory.bind_context_material(material_reader, material_generation)
        except BaseException as construction_error:
            errors=[construction_error]
            def cleanup(operation):
                try: operation()
                except BaseException as exc: errors.append(exc)
            for name in ('pc_integration', 'shared_timeline', 'expression_review', 'music_library', 'memo_notes', 'scoped_daily_plans', 'personal_goals', 'important_dates', 'agenda', 'memory_transfer', 'history_adoption', 'expression_reply', 'expression_assets'):
                service = getattr(locals().get('runtime'), name, None)
                if service is not None: cleanup(service.stop)
            services=getattr(locals().get('runtime'),'native_services',None)
            if services is not None:cleanup(services.abort_initialization)
            reminders=getattr(locals().get('runtime'), 'reminders', None)
            if reminders is not None:
                cleanup(reminders.abort_initialization)
            # Factories run synchronously before any workers are started. A
            # later factory failure must also fence the earlier sender.
            delivery=getattr(locals().get('runtime'), 'delivery', None)
            if delivery is not None:
                delivery.active=False
                delivery.sender.active=False
            unified = getattr(locals().get('runtime'), 'unified', None)
            if unified is not None:
                cleanup(unified.stop)
                memory_policy = getattr(unified, 'memory_policy', None)
                if memory_policy is not None:
                    cleanup(memory_policy.close)
            if presence_policy is not None:
                cleanup(presence_policy.close)
            if frequency is not None:
                cleanup(frequency.close)
            memory = getattr(locals().get('runtime'), 'memory', None)
            if getattr(memory, 'backend', None) == 'native':
                cleanup(memory.stop)
                cleanup(memory.store.close)
            history = getattr(locals().get('runtime'), 'history_archive', None)
            if history is not None:
                cleanup(history.close)
            if len(errors)>1:
                raise BaseExceptionGroup('TLS runtime construction and cleanup failed', errors)
            raise
        if frequency is not None:
            runtime.frequency_policy = frequency
        if presence_policy is not None:
            runtime.presence_policy = presence_policy
        return governance, runtime

    def _native_memory_allowed(self, scope):
        sessions = self.plugin._cfg('living_memory_sessions', [])
        return (self.plugin._cfg('living_memory_backend', 'legacy') == 'native'
                and isinstance(sessions, list) and all(isinstance(s, str) for s in sessions)
                and (not sessions or scope['session_id'] in sessions)
                and self.authorized_scope(scope))

    def _frequency_scope(self, user):
        session = user.get("umo") if isinstance(user, dict) else None
        return self.presence.scope_for_session(session) if isinstance(session, str) else None

    async def start(self, data_dir: str) -> bool:
        async with self._start_lock:
            return await self._start(data_dir)

    async def _start(self, data_dir: str) -> bool:
        from .native_phone_music_runtime import restore_phone_music_recovery
        if not restore_phone_music_recovery(self.context):
            return False
        if self.runtime is not None:
            return self._enabled()
        if not self._closed and self.presence.active:
            from .frequency_mode import restore_frequency_tombstone
            await restore_frequency_tombstone(self.context, data_dir)
            from .presence_mode import restore_presence_tombstone
            await restore_presence_tombstone(self.presence, data_dir)
            from .memory_context_mode import restore_memory_context_tombstone
            await restore_memory_context_tombstone(self.context, data_dir)
        if not self._enabled():
            return False
        creation = asyncio.create_task(asyncio.to_thread(self._journal_factory,
                    Path(data_dir) / "living" / "living.sqlite3", clock=self.clock))
        try:
            journal = await asyncio.shield(creation)
        except asyncio.CancelledError:
            # The thread cannot be cancelled. Consume and close its eventual
            # connection rather than leaking it after an interrupted start.
            creation.add_done_callback(self._discard_created_journal)
            raise
        construction = asyncio.create_task(asyncio.to_thread(self._build_runtime, journal))
        try:
            governance, runtime = await asyncio.shield(construction)
        except asyncio.CancelledError:
            self._closed = True
            self._cleanup_task = asyncio.create_task(self._discard_built_runtime(construction, journal))
            self._cleanup_task.add_done_callback(self._consume_cleanup)
            raise
        except BaseException:
            await asyncio.to_thread(journal.close)
            raise
        if not self._enabled():
            frequency = getattr(runtime, "frequency_policy", None)
            if frequency is not None:
                await asyncio.to_thread(frequency.close)
            presence_policy = getattr(runtime, 'presence_policy', None)
            if presence_policy is not None:
                await asyncio.to_thread(presence_policy.close)
            await runtime.close()
            await asyncio.to_thread(journal.close)
            return False
        presence_policy = getattr(runtime, 'presence_policy', None)
        if presence_policy is not None:
            try:
                self.presence.set_read_policy_router(presence_policy)
            except BaseException:
                await asyncio.to_thread(presence_policy.close)
                frequency = getattr(runtime, 'frequency_policy', None)
                if frequency is not None:
                    await asyncio.to_thread(frequency.close)
                await runtime.close()
                await asyncio.to_thread(journal.close)
                raise
        self.journal, self.governance, self.runtime = journal, governance, runtime
        from .task_model_router import TaskModelRouter
        model_router=TaskModelRouter(self.context,journal,clock=self.clock,
            current=lambda:not self._closed and self.runtime is runtime and runtime.active and not journal._closed)
        runtime.task_model_router=model_router
        self.plugin._task_model_router=model_router
        self.context._tls_task_model_router=model_router
        self.presence.set_accepted_observer(self._observer)
        setattr(self.context, "living_system", runtime)
        services = getattr(runtime, 'native_services', None)
        if services is not None:
            await services.retire_stopping_queue_workers()
            services.start()
        if not self.plugin._cfg_bool('living_phone_native_enabled', False):
            from .native_phone_music_runtime import NativePhoneMusicRuntime
            self.native_phone_music = NativePhoneMusicRuntime(self)
            runtime.native_phone_music = self.native_phone_music
            self.native_phone_music.tick()
        self._configure_ability()
        try:
            from .native_selected_persona_host import NativeSelectedPersonaHost
            self.selected_persona = NativeSelectedPersonaHost(self)
        except Exception as exc:
            self._selected_persona_error = type(exc).__name__
        return True

    @staticmethod
    async def _discard_built_runtime(construction, journal):
        """A cancelled start still owns its late worker result and OS lock."""
        try:
            _, runtime = await construction
            try:
                frequency = getattr(runtime, "frequency_policy", None)
                if frequency is not None:
                    await asyncio.to_thread(frequency.close)
                presence_policy = getattr(runtime, 'presence_policy', None)
                if presence_policy is not None:
                    await asyncio.to_thread(presence_policy.close)
            finally:
                await runtime.close()
        finally:
            await asyncio.to_thread(journal.close)

    def remember_scope(self, scope):
        """Remember only an identity already leased by genuine inbound handling."""
        if self.authorized_scope(scope):
            self._trusted_scope = private_scope(scope)
            controller = getattr(self.plugin, '_native_memo_tool_router', None)
            if controller is not None:
                try: controller.observe(scope)
                except Exception: pass

    async def learn_expression_event(self, event, scope):
        """Only explicit user feedback; no model extraction or prompt rewriting."""
        from .native_expression_learning import parse_feedback
        learner=getattr(self.runtime,'expression_learning',None)
        if learner is None or not self.authorized_scope(scope):
            return {'state':'unavailable'}
        if getattr(event,'private_companion_proactive_framework',False):
            return {'state':'unrecognized'}
        text=str(getattr(event,'message_str','') or '')
        quoted=bool(getattr(event,'tls_quoted_message',False))
        roleplay=bool(getattr(event,'tls_roleplay_message',False))
        if parse_feedback(text,quoted=quoted,roleplay=roleplay) is None:
            return {'state':'unrecognized'}
        identity=str(getattr(getattr(event,'message_obj',None),'message_id','') or '')
        if not identity or identity=='0':
            return {'state':'missing_message_identity'}
        return await asyncio.to_thread(learner.learn,scope,text,
            source_message_id=identity,quoted=quoted,roleplay=roleplay)

    def _exploration_enabled(self):
        return (self._enabled() and self._source_allowed("music.catalog") and
                self.plugin._cfg_bool("living_exploration_enabled", False))

    def _share_enabled(self):
        return self._enabled() and self.plugin._cfg_bool("living_share_enabled", False)

    def _companion_scope(self, context):
        user = context.get("user") if isinstance(context, dict) else None
        umo = user.get("umo") if isinstance(user, dict) else None
        scope = self.presence.scope_for_session(umo) if isinstance(umo, str) else None
        if scope is None or not self.authorized_scope(scope):
            return None
        return scope

    def _configure_ability(self):
        if not self._share_enabled():
            if self.ability is not None:
                self.ability.close()
                self.ability = None
            return
        if self.ability is None:
            from .bridges import CompanionAbilityAdapter
            self.ability = CompanionAbilityAdapter(self.journal, self._companion_scope,
                self._material_for, clock=self.clock, authorize_delivery=self._authorize_delivery)
        if self.ability._api is None:
            self.ability.register()  # Native administrator enablement remains default False.

    async def _authorize_delivery(self, scope, source_id):
        """Final native dispatch gate; no grant is inferred from prepared text."""
        def live():
            path = self.plugin._cfg("living_catalog_path", "")
            return (source_id == "music.catalog" and self.runtime is not None and self.runtime.active
                    and self.governance is not None and self._share_enabled() and self._exploration_enabled()
                    and self._source_allowed(source_id) and self.authorized_scope(scope)
                    and isinstance(path, str) and bool(path.strip())
                    and self.coordinator is not None and self.coordinator.active
                    and self.coordinator.configured_path == path.strip())
        try:
            if not live():
                return False
            capabilities = ("catalog.read", "observe.persist", "share.propose", "share.send")
            # Recheck the complete grant set after prior permission awaits;
            # the adapter also validates source correlation/expiry at dispatch.
            for _ in range(2):
                for capability in capabilities:
                    if not live():
                        return False
                    allowed = await asyncio.to_thread(self.governance.allows, capability, scope, source_id)
                    if not allowed or not live():
                        return False
            return live()
        except Exception:
            return False

    async def _material_for(self, scope, context=None):
        if not self._share_enabled() or not self.authorized_scope(scope):
            return {"ok": False, "status": "disabled"}
        result = await self.runtime.material_for(scope, context)
        if not self._share_enabled() or not self.authorized_scope(scope):
            return {"ok": False, "status": "disabled"}
        return result

    async def living_tick(self):
        """Schedule at most one scope step inside the host's existing task cap."""
        if self.native_phone_music is not None:
            self.native_phone_music.tick()
        self._configure_ability()
        integrations=getattr(self.plugin,'_native_server_integrations',None)
        if integrations is not None and not integrations._closed and self.runtime is not None:
            for kind in ('pc_business','pc_daily','independent_proactive'):
                previous=self._native_business_steps.get(kind)
                if previous is not None and not previous.done():continue
                if len(self._tasks)>=self.max_pending:break
                if kind in {'pc_business','pc_daily'}:
                    if self._trusted_scope is None or not self.authorized_scope(self._trusted_scope):continue
                    owner=getattr(integrations,'pc_full',None)
                    if owner is None or not owner.active:continue
                else:
                    independent=getattr(integrations,'proactive_chat',None)
                    if independent is None or not independent.active:continue
                task=asyncio.create_task(self._native_business_step(kind,integrations))
                self._native_business_steps[kind]=task
                self._tasks.add(task);task.add_done_callback(self._finished)
        phone=getattr(self.runtime,'phone_companion',None)
        if (phone is not None and self.plugin._cfg_bool('living_phone_companion_enabled',False)
                and not getattr(self, 'phone_transfer_pending', False)
                and self._trusted_scope is not None
                and self.authorized_scope(self._trusted_scope) and len(self._tasks)<self.max_pending
                and (self._phone_task is None or self._phone_task.done())):
            task=asyncio.create_task(self.runtime.native_services.phone_tick(dict(self._trusted_scope)))
            self._phone_task=task;self._tasks.add(task);task.add_done_callback(self._finished)
        pc=getattr(self.runtime,'pc_integration',None)
        if (pc is not None and pc.active and self.plugin._cfg_bool('living_pc_integration_enabled',False)
                and self._trusted_scope is not None
                and self.authorized_scope(self._trusted_scope) and len(self._tasks)<self.max_pending
                and (self._pc_task is None or self._pc_task.done())):
            task=asyncio.create_task(self.runtime.native_services.pc_tick(dict(self._trusted_scope)))
            self._pc_task=task;self._tasks.add(task);task.add_done_callback(self._finished)
        proactive=getattr(self.runtime,'proactive_companion',None)
        if (proactive is not None and self.plugin._cfg_bool('living_proactive_companion_enabled',False)
                and self._trusted_scope is not None
                and self.authorized_scope(self._trusted_scope) and len(self._tasks)<self.max_pending
                and (self._proactive_task is None or self._proactive_task.done())):
            task=asyncio.create_task(self.runtime.native_services.proactive_tick(dict(self._trusted_scope)))
            self._proactive_task=task;self._tasks.add(task);task.add_done_callback(self._finished)
        if not self._exploration_enabled() or self.runtime is None or self._trusted_scope is None:
            return
        path = self.plugin._cfg("living_catalog_path", "")
        if self.coordinator is not None and str(path).strip() != self.coordinator.configured_path:
            self.coordinator.stop()
            if self._exploration_task is not None:
                self._exploration_task.cancel()
            # A filesystem worker cannot be killed. Retain its owner and slot
            # until it finishes; repeated path edits must not accumulate reads.
            if self.coordinator.diagnostics()["pending_source_read"]:
                return
            if self._exploration_task is not None and not self._exploration_task.done():
                return
            await self.coordinator.close()
            self.coordinator = None
        if self._exploration_task is not None and not self._exploration_task.done():
            return
        if len(self._tasks) >= self.max_pending or not self.authorized_scope(self._trusted_scope):
            return
        if not isinstance(path, str) or not path.strip():
            return
        if self.coordinator is None:
            from .coordinator import CatalogCoordinator
            self.coordinator = CatalogCoordinator(self.runtime,
                catalog_path=lambda: self.plugin._cfg("living_catalog_path", ""),
                enabled=self._exploration_enabled, share_enabled=self._share_enabled,
                scope_validator=self.authorized_scope, clock=self.clock)
        task = asyncio.create_task(self.coordinator.tick(dict(self._trusted_scope)))
        self._exploration_task = task
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        self.metrics["scheduled"] += 1

    async def _native_business_step(self,kind,integrations):
        if self._closed or integrations._closed:return
        if kind=='pc_business':
            return await integrations.pc_full.tick()
        if kind=='independent_proactive':
            return await integrations.proactive_chat.tick()
        daily=getattr(self.runtime,'pc_daily_lifecycle',None)
        if daily is None or self._trusted_scope is None:return
        scope=dict(self._trusted_scope)
        result=await daily.tick(scope)
        owner=integrations.pc_full
        if owner is not None and owner.active and self.authorized_scope(scope):
            from datetime import datetime
            from .native_important_dates import date_zone
            records=daily.plans.list(scope,limit=20)['records']
            for plan in records:
                if plan['date']==datetime.fromtimestamp(self.clock(),date_zone(plan['timezone'])).date().isoformat():
                    await owner.service.project_scoped_plan(scope,plan)
                    break
        return result

    @staticmethod
    def _discard_created_journal(task):
        if task.cancelled():
            return
        try:
            journal = task.result()
        except Exception:
            return
        cleanup = asyncio.create_task(asyncio.to_thread(journal.close))
        cleanup.add_done_callback(LivingHost._consume_cleanup)

    def _accepted(self, scope: dict, record: dict) -> None:
        source = record.get("source")
        if self.coordinator is not None and source == self.coordinator.source_id:
            return  # Coordinator ingestion already journaled its owned projection.
        if not self.authorized_scope(scope) or not self._source_allowed(source):
            self.metrics["denied"] += 1
            return
        if len(self._tasks) >= self.max_pending:
            self.metrics["overflow"] += 1
            return
        try:
            observation = observation_from_presence(scope, record)
        except (ValueError, TypeError, KeyError, OverflowError):
            self.metrics["invalid"] += 1
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.metrics["no_event_loop"] += 1
            return
        task = loop.create_task(self._persist(observation))
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        self.metrics["scheduled"] += 1

    async def _persist(self, observation: Observation) -> None:
        source, scope = observation.source_id, observation.scope
        allowed = await asyncio.to_thread(self.governance.allows, "observe.persist", scope,
                                          source_id=source)
        if not allowed or not self.authorized_scope(scope) or not self._source_allowed(source):
            self.metrics["denied"] += 1
            return
        await self.runtime.ingest(observation, publish=False)
        self.metrics["completed"] += 1

    def _finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                self.metrics["errors"] += 1

    def stop(self) -> None:
        """Synchronously reject late work before awaiting shutdown."""
        self._closed = True
        if self.selected_persona is not None:
            try:
                self.selected_persona.stop()
            except Exception as exc:
                self._selected_persona_error = type(exc).__name__
        if self.native_phone_music is not None:
            self.native_phone_music.stop()
        for name in ('pc_integration', 'proactive_companion', 'proactive_generation', 'proactive_persona_binding',
                     'shared_timeline', 'expression_review', 'music_library', 'memo_notes', 'scoped_daily_plans', 'personal_goals', 'important_dates', 'memory_transfer', 'history_adoption', 'expression_reply', 'expression_assets'):
            service = getattr(self.runtime, name, None)
            if service is not None: service.stop()
        phone=getattr(self.runtime,'phone_companion',None)
        if phone is not None:phone.stop()
        agenda=getattr(self.runtime,'agenda',None)
        if agenda is not None:agenda.stop()
        memory = getattr(self.runtime, 'memory', None)
        if getattr(memory, 'backend', None) == 'native':
            memory.stop()
        unified = getattr(self.runtime, 'unified', None)
        if unified is not None:
            unified.stop()
            memory_policy = getattr(unified, 'memory_policy', None)
            if memory_policy is not None:
                from .memory_context_mode import retain_memory_context_tombstone
                retain_memory_context_tombstone(self.context, memory_policy)
                if getattr(self.context, 'living_system', None) is self.runtime:
                    self.runtime.memory_context_recovery = getattr(self.context, '_tls_memory_context_recovery', None)
        delivery=getattr(self.runtime,'delivery',None)
        if delivery is not None:
            delivery.active=False
            delivery.sender.active=False
        reminders=getattr(self.runtime, 'reminders', None)
        if reminders is not None:
            reminders.stop()
        frequency = getattr(self.runtime, "frequency_policy", None)
        if frequency is not None:
            frequency.stop()
            from .frequency_mode import retain_frequency_tombstone
            retain_frequency_tombstone(self.context, frequency)
        presence_policy = getattr(self.runtime, 'presence_policy', None)
        if presence_policy is not None:
            presence_policy.stop()
            self.presence.clear_read_policy_router(presence_policy)
        self._trusted_scope = None
        if self.coordinator is not None:
            self.coordinator.stop()
        if self.ability is not None:
            self.ability.close()
        self.presence.clear_accepted_observer(self._observer)
        if getattr(self.context, "living_system", None) is self.runtime and self.runtime is not None:
            delattr(self.context, "living_system")
        for task in list(self._tasks):
            task.cancel()

    async def _release(self):
        try:
            takeover=getattr(self.plugin,'_native_mc_takeover',None)
            if takeover is not None and getattr(takeover,'host',None)is self:
                # Presence may close independently of plugin.terminate(). The
                # summary owner must restore/drain before native stores close.
                # Its retained recovery reference survives a refused restore.
                await takeover.close()
            if self.native_phone_music is not None:
                self.native_phone_music.stop()
            frequency = getattr(self.runtime, "frequency_policy", None)
            if frequency is not None:
                await asyncio.to_thread(frequency.close)
                from .frequency_mode import retain_frequency_tombstone
                retain_frequency_tombstone(self.context, frequency)
            presence_policy = getattr(self.runtime, 'presence_policy', None)
            if presence_policy is not None:
                await asyncio.to_thread(presence_policy.close)
            if self.coordinator is not None:
                await self.coordinator.close()
            if self.runtime is not None:
                await self.runtime.close()
                memory_policy = getattr(self.runtime, 'memory_policy', None)
                if memory_policy is not None:
                    from .memory_context_mode import retain_memory_context_tombstone
                    retain_memory_context_tombstone(self.context, memory_policy)
                    if getattr(self.context, 'living_system', None) is self.runtime:
                        self.runtime.memory_context_recovery = getattr(self.context, '_tls_memory_context_recovery', None)
        finally:
            if self.journal is not None:
                await asyncio.to_thread(self.journal.close)

    async def close(self, *, timeout=1.0) -> None:
        self.stop()
        maximum = min(max(float(timeout), 0.01), 1.0)
        started = asyncio.get_running_loop().time()
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=maximum / 2)
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._release())
            self._cleanup_task.add_done_callback(self._consume_cleanup)
        while True:
            pending = (self.native_phone_music is not None
                       and self.native_phone_music.diagnostics()['restore_pending'])
            remaining = maximum - (asyncio.get_running_loop().time() - started)
            if remaining <= 0 or (self._cleanup_task.done() and not pending):
                break
            delay = min(0.01, remaining) if pending else remaining
            if self._cleanup_task.done():
                await asyncio.sleep(delay)
            else:
                await asyncio.wait({self._cleanup_task}, timeout=delay)
            if pending:
                self.native_phone_music.stop()

    @staticmethod
    def _consume_cleanup(task):
        if not task.cancelled():
            try:
                task.exception()
            except Exception:
                pass

    def diagnostics(self) -> dict:
        return {"active": self.runtime is not None and self._enabled(),
                "pending": len(self._tasks), "max_pending": self.max_pending,
                "trusted_scope_ready": self._trusted_scope is not None,
                "restart_barrier": "genuine_inbound_required",
                "selected_persona": self.selected_persona.diagnostics()
                    if self.selected_persona is not None else {"active": False,
                        "state": "unavailable", "error_type": self._selected_persona_error,
                        "grants_mc_authority": False, "grants_write_or_send": False},
                "native_phone_music": self.native_phone_music.diagnostics()
                    if self.native_phone_music is not None else {"state": "disabled", "projection_current": False},
                "catalog": self.coordinator.diagnostics() if self.coordinator is not None else {"active": False},
                "unified": getattr(self.runtime, 'unified', None).diagnostics()
                    if getattr(self.runtime, 'unified', None) is not None else {"active": False},
                "metrics": dict(self.metrics)}
