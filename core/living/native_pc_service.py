"""TLS-owned PC runtime with the mature business/state implementations.

There is no PC Star registration and no second scheduler. The original plugin
must be stopped and drained before construction opens its existing state. TLS
owns the source selection, event/tool registration and its one Host tick.
"""
from __future__ import annotations

import asyncio
import contextvars
from copy import deepcopy
from datetime import datetime
import inspect
import json
import hashlib
import time
from pathlib import Path

from .models import canonical, private_scope
from .native_pc_business.main import PrivateCompanionPlugin as _Business
from .native_pc_business.companion_delivery import CompanionDeliveryUncertainError
from .native_pc_business.helpers import (special_settings_defaults, validate_special_changes,
    special_calendar, special_day_events, special_holiday_catalog)
from .journal import LivingJournal, JournalConflict

_HERE = Path(__file__).resolve().parent / 'native_pc_business'
VIRTUAL_EVENTS = 'tls.native.pc.virtual_life.events.v1'
_DISPATCH_CONTEXT = contextvars.ContextVar('tls_native_pc_dispatch', default=None)
OUTBOUND_TRANSFORM = contextvars.ContextVar('tls_native_pc_outbound_transform', default=None)


async def _value(value):
    return await value if inspect.isawaitable(value) else value


class NativePCService(_Business):
    """Full native PC business host; legacy_closed is a real operator proof.

    authorize(operation, scope) must use the current Host authority, not this
    stored scope. send_chain(scope, umo, chain, metadata) returns a dictionary
    with state='confirmed' only after the existing TLS transport confirmation.
    Native generation retains the migrated budget/provider implementation.
    """

    def __init__(self, context, config, *, legacy_closed, authorize,
                 send_chain=None, platform_action=None, register_ui=False, journal=None, music_library_reader=None):
        if not callable(legacy_closed) or not callable(authorize):
            raise ValueError('actual legacy closure and current TLS authority callbacks required')
        if legacy_closed() is not True:
            raise PermissionError('stop and drain the original PC before opening its live state')
        self._tls_legacy_closed = legacy_closed
        self._tls_authorize = authorize; self._tls_send_chain = send_chain
        self._tls_platform_action = platform_action
        self._tls_primary_scope = None; self._tls_source = None
        self._tls_running = False; self._tls_initialized = False
        self._tls_tick_lock = asyncio.Lock(); self._tls_tasks = set()
        self._tls_last_tick = 0.; self._tls_last_error = None
        self._tls_registered_routes = []; self._tls_register_ui = register_ui
        self._tls_journal = journal
        if music_library_reader is not None and not callable(music_library_reader):
            raise ValueError('current native music read callback required')
        self._tls_music_library_reader = music_library_reader
        if journal is not None and not isinstance(journal, LivingJournal): raise ValueError('existing LivingJournal required')
        # Original storage backend, data directory, locks, indexes and persisted
        # business state are reused. No state is re-created or bulk imported.
        super().__init__(context, config)
        self._tls_apply_ownership()
        self._tls_pin_sources()

    @property
    def active(self): return self._tls_running

    def _special_user(self, user_id, authorize):
        if (not self.active or not self.native_source_current()
                or (authorize is not None and authorize() is not True)):
            raise PermissionError('当前陪伴服务或绑定不可用')
        user = self.data.get('users', {}).get(user_id)
        if not isinstance(user, dict):
            raise ValueError('真实绑定用户的陪伴资料尚未建立')
        return user

    def _special_view(self, user):
        defaults = special_settings_defaults()
        values = {key: deepcopy(user.get(key, default)) for key, default in defaults.items()}
        now = time.time()
        return dict(values=values, revision=user.get('special_settings_revision', 0),
                    updated_at=user.get('special_settings_updated_at'),
                    calendar=special_calendar(user, now), today=special_day_events(user, now),
                    holidays=special_holiday_catalog(),
                    delivery='沿现有主动消息通道和权限发送；课程提醒不补发过期课程')

    async def get_special_settings(self, user_id, *, authorize=None):
        async with self._data_lock:
            return self._special_view(self._special_user(user_id, authorize))

    async def update_special_settings(self, user_id, changes, expected_revision, *, authorize=None):
        changes = validate_special_changes(changes)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('请先读取当前设置')
        async with self._data_lock:
            user = self._special_user(user_id, authorize)
            if user.get('special_settings_revision', 0) != expected_revision:
                raise JournalConflict('设置已变化，请刷新后修改')
            self._special_user(user_id, authorize)
            user.update(deepcopy(changes))
            user['special_settings_revision'] = expected_revision + 1
            user['special_settings_updated_at'] = time.time()
            # Use the existing coalesced writer, never a competing state file.
            self._save_data_sync()
        if not await self._flush_scheduled_data_save():
            raise RuntimeError('持久化尚未完成，请回读核对，勿重复保存')
        return await self.get_special_settings(user_id, authorize=authorize)

    def _tls_pin_sources(self):
        manifest = json.loads((_HERE / 'SOURCE-MANIFEST.json').read_text(encoding='utf-8'))
        self._tls_source_files = {}
        for relative, record in manifest['modules'].items():
            path = _HERE / relative
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('native PC business source does not match its manifest')
            value = path.stat(); self._tls_source_files[path] = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        path = Path(__file__).resolve(); value = path.stat()
        self._tls_source_files[path] = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        self._tls_service_code = {name: (descriptor, descriptor.__code__) for name, descriptor in vars(NativePCService).items()
                                  if inspect.isfunction(descriptor)}

    def native_source_current(self):
        try:
            if self.context is None or self._tls_legacy_closed() is not True: return False
            for path, expected in self._tls_source_files.items():
                value = path.stat()
                if path.is_symlink() or (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns) != expected: return False
            return all(vars(NativePCService).get(name) is function and function.__code__ is code
                       for name, (function, code) in self._tls_service_code.items())
        except Exception: return False

    def _tls_apply_ownership(self):
        # These responsibilities already belong to the existing TLS native
        # services. Their old business data remains available for inspection.
        self.enable_personal_goals = False
        self.enable_personal_goal_auto_progress = False
        self.enable_book_reading = False
        self.enable_private_reading = False
        self.enable_app_greeting = False
        self.enable_environment_change_proactive = False
        self._task = None

    def _compact_store_history_inplace(self, data):
        # A takeover is not a cleanup operation. In particular retain the old
        # candidate/UNKNOWN history instead of applying startup trim heuristics.
        return {}

    def _recover_stale_troubleshooting_proactive_plans(self): return False
    def _prime_enabled_user_schedules(self): return False

    def _tls_allowed(self, operation, scope=None):
        transform = OUTBOUND_TRANSFORM.get()
        if transform is not None and operation in {'model', 'send', 'platform_action'}:
            transform['secondary_operation'] = operation
            return False
        scope = self._tls_primary_scope if scope is None else scope
        try:
            return (self._tls_running and scope is not None and self.native_source_current()
                    and self._tls_authorize(operation, dict(scope)) is True)
        except Exception: return False

    def _register_page_api_if_available(self):
        # The copied constructor invokes this virtual method. Actual normal
        # AstrBot route registration is explicit and occurs under TLS ownership.
        self.page_api = None

    async def initialize(self):
        if self._tls_initialized: return
        if self._tls_legacy_closed() is not True:
            raise PermissionError('original PC runtime is not closed')
        # The migrated initialize keeps storage/schedule recovery, but its SDK
        # handler repair, background-startup tasks, bridge.start and scheduler
        # creation statements were removed by source materialization.
        await super().initialize()
        self._tls_apply_ownership()
        self._tls_initialized = True; self._tls_running = True
        if self._tls_register_ui: self.register_native_routes()

    async def bind_scope(self, scope, event_id, persona_id):
        """Only called by TLS after a genuine inbound, never from an admin API."""
        scope = private_scope(scope)
        if not self._tls_allowed('bind', scope): raise PermissionError('genuine native PC scope is unavailable')
        if type(event_id) is not str or not event_id or len(event_id) > 256:
            raise ValueError('real bounded inbound event ID required')
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(scope['session_id'])
        conversation = await manager.get_conversation(scope['session_id'], cid, create_if_not_exists=False) if cid else None
        if cid and (conversation is None or getattr(conversation, 'user_id', None) != scope['session_id']):
            raise PermissionError('native PC conversation owner changed')
        selected, persona, *_ = await self.context.persona_manager.resolve_selected_persona(
            umo=scope['session_id'], conversation_persona_id=getattr(conversation, 'persona_id', None),
            platform_name=scope['platform'], provider_settings=self.context.get_config(umo=scope['session_id']).get('provider_settings', {}))
        if (selected != persona_id or not isinstance(persona, dict) or persona.get('name') != selected
                or not self._tls_allowed('bind', scope)):
            raise PermissionError('actual selected Persona differs from the inbound binding')
        if self._tls_primary_scope is not None and self._tls_primary_scope != scope:
            raise PermissionError('this PC runtime already owns another explicit full scope')
        self._tls_primary_scope = scope
        self._tls_source = dict(event_id=event_id, persona_id=selected, source='genuine_inbound_sdk_selection')
        # Refresh the existing cache for the exact UMO, rather than using the
        # old unscoped/default-persona fallback for future native model work.
        await self._refresh_default_persona_prompt(umo=scope['session_id'])
        return dict(bound=True, source='genuine_inbound_sdk_selection', grants_lease=False)

    async def project_scoped_plan(self, scope, plan):
        """Give existing diary/outfit consumers a sourced future-plan projection.

        The prior unowned global plan is never overwritten or assigned a guessed
        owner. Only a separate new projection is visible to bound-scope readers.
        """
        scope = private_scope(scope)
        if (scope != self._tls_primary_scope or not self._tls_allowed('plan') or type(plan) is not dict
                or plan.get('scope') != scope or not str(plan.get('id', '')).startswith('plan.')):
            raise PermissionError('a new explicitly bound scoped plan is required')
        from .native_important_dates import date_zone
        zone = date_zone(plan['timezone'])
        projected = dict(date=plan['date'], generated_at=plan['created_at'], source='tls_scoped_virtual_plan',
            native_plan_id=plan['id'], native_revision=plan['revision'], scope=scope,
            persona_id=self._tls_source['persona_id'], evidence_kind='roleplay_event',
            items=[dict(start=datetime.fromtimestamp(item['scheduled_at'], zone).strftime('%H:%M'),
                        end=datetime.fromtimestamp(item['scheduled_at'] + 1800, zone).strftime('%H:%M'),
                        activity=item['title'], note=item['description'], native_item_id=item['id'])
                   for item in plan['items'] if item['status'] != 'cancelled'])
        async with self._data_lock:
            if not self._tls_allowed('plan'): raise PermissionError('native plan projection authority changed')
            self.data['tls_scoped_daily_plan_projection'] = projected
            self._save_data_sync()
        return dict(projected=True, scope=scope, plan_id=plan['id'], legacy_history_preserved=True)

    async def _ensure_daily_plan(self, force=False):
        # New future plans come only from NativePCDailyLifecycle. Do not call the
        # old unscoped global generator or silently label its historical items.
        return self._native_daily_plan_view()

    def _native_daily_plan_view(self, default=None):
        current = self.data.get('tls_scoped_daily_plan_projection')
        if (isinstance(current, dict) and current.get('scope') == self._tls_primary_scope
                and self._tls_primary_scope is not None): return current
        # Historical global material remains a separate unowned record. Native
        # future execution must wait for a genuine scoped projection instead.
        return default

    async def _generate_daily_plan(self):
        raise PermissionError('use the explicitly scoped native daily-plan producer')

    async def _scheduler_loop(self):
        raise RuntimeError('NativePCService has no independent scheduler; TLS Host owns ticks')

    async def _kick_proactive_loop_once(self):
        return await self.host_tick()

    async def _maybe_settle_personal_goals(self, *, force=False): return None
    def _queue_personal_goal_candidate_locked(self, *args, **kwargs): return 0
    async def _maybe_process_memo_notes(self, *, force=False): return None
    async def _maybe_refresh_environment_change(self, *args, **kwargs): return None
    async def _maybe_schedule_app_greeting(self, *args, **kwargs): return None

    async def _tick(self, *args, **kwargs):
        # The original mixed-source scheduler must never re-admit random, App,
        # memo/timer, important-date or weather candidates now owned by TLS.
        # Existing persisted candidates/UNKNOWN records are retained untouched.
        return None

    async def _tick_inner(self, *args, **kwargs): return None

    async def _llm_call(self, *args, **kwargs):
        if not self._tls_allowed('model'): raise PermissionError('native PC model work is not currently permitted')
        task = asyncio.current_task(); entered = task not in self._tls_tasks
        if entered: self._tls_tasks.add(task)
        try:
            result = await super()._llm_call(*args, **kwargs)
            if not self._tls_allowed('model'): raise PermissionError('native PC model authority changed')
            return result
        finally:
            if entered: self._tls_tasks.discard(task)

    async def _generate_photo_image(self, *args, **kwargs):
        # The mature photo adapter may call an image provider directly instead
        # of _llm_call. It shares the same current-scope and pure-transform gate.
        if not self._tls_allowed('model'): raise PermissionError('native PC image generation is not currently permitted')
        task = asyncio.current_task(); entered = task not in self._tls_tasks
        if entered: self._tls_tasks.add(task)
        try:
            result = await super()._generate_photo_image(*args, **kwargs)
            if not self._tls_allowed('model'): raise PermissionError('native PC image authority changed')
            return result
        finally:
            if entered: self._tls_tasks.discard(task)

    def _record_virtual_artifact(self, kind, artifact):
        if not isinstance(self._tls_journal, LivingJournal) or not self._tls_allowed('plan'):
            return
        projection = self._native_daily_plan_view()
        if projection is None or not isinstance(artifact, dict): return
        if kind == 'diary':
            title = str(artifact.get('title') or '角色今日日记')[:100]
            body = str(artifact.get('body') or artifact.get('text') or '').strip()
            if not body: return
            text = title + '：' + body[:700]
        else:
            if artifact.get('error') or not artifact.get('path'): return
            profile = artifact.get('outfit_profile') or {}
            title = '角色今日虚构穿搭'
            text = title + '：' + '；'.join(str(value) for value in profile.values() if isinstance(value, str))[:500]
        scope = dict(self._tls_primary_scope)
        identity = hashlib.sha256(canonical([scope, projection['date'], kind]).encode()).hexdigest()
        if self._tls_journal.fetch(VIRTUAL_EVENTS, identity, scope): return
        data = dict(schema=1, id=identity, scope=scope, kind=kind, title=title, text=text,
            plan_id=projection['native_plan_id'], inbound_event_id=self._tls_source['event_id'],
            persona_id=self._tls_source['persona_id'], source='tls.native.pc.virtual_life',
            evidence_kind='roleplay_event', created_at=__import__('time').time(), shared_task=None)
        self._tls_journal.put(VIRTUAL_EVENTS, identity, scope, data, expected_revision=0,
            authorize=lambda: self._tls_allowed('plan', scope))

    async def _ensure_daily_diary(self, force=False):
        if self._native_daily_plan_view() is None: return None
        result = await super()._ensure_daily_diary(force=force)
        if isinstance(result, dict): self._record_virtual_artifact('diary', result)
        return result

    async def _ensure_daily_outfit_photo(self, diary=None, *, force=False):
        if self._native_daily_plan_view() is None: return None
        old = canonical(self.data.get('daily_outfit_photo') or {})
        result = await super()._ensure_daily_outfit_photo(diary, force=force)
        if isinstance(result, dict) and canonical(result) != old:
            self._record_virtual_artifact('outfit', result)
        return result

    def proactive_candidates(self, scope):
        scope = private_scope(scope)
        if (scope != self._tls_primary_scope or not self._tls_allowed('share', scope)
                or not isinstance(self._tls_journal, LivingJournal)): return []
        now = __import__('time').time(); candidates = []
        for row in self._tls_journal.list(VIRTUAL_EVENTS, scope, limit=128):
            data = row['data']
            if data.get('shared_task') or not 0 <= now - data['created_at'] <= 86400: continue
            candidates.append(dict(source='pc_virtual_life', kind=data['kind'], reason='virtual_life_share',
                candidate_id=data['id'], dedupe_key=data['id'], event_id=data['id'], revision=row['revision'],
                topic='虚构角色经历：' + data['title'], motive='自然分享已保存的虚构角色日常，不声称现实发生。',
                evidence=data['text'][:180], evidence_kind='roleplay_event', eligible=True, score=75,
                occurred_at=data['created_at'], creates_send_permission=False))
        return sorted(candidates, key=lambda row: (-row['score'], row['occurred_at']))[:8]

    def confirm_share(self, scope, candidate, task_id):
        scope = private_scope(scope)
        if not self._tls_allowed('share', scope) or not isinstance(self._tls_journal, LivingJournal):
            raise PermissionError('current scoped native daily share required')
        from .native_pc_business.native_runtime_bindings import integrations_for
        integrations = integrations_for(self)
        host = integrations._host() if integrations is not None else None
        delivery = getattr(getattr(host, 'runtime', None), 'delivery', None)
        actual = delivery.store.get(task_id) if delivery is not None else None
        if not actual or actual.get('scope') != scope or actual.get('state') != 'confirmed':
            raise PermissionError('actual shared-lane delivery confirmation required')
        row = self._tls_journal.fetch(VIRTUAL_EVENTS, candidate['event_id'], scope)
        if row is None: raise KeyError('native daily event missing')
        if row['data'].get('shared_task') == task_id: return row
        if row['revision'] != candidate['revision'] or row['data'].get('shared_task'):
            raise JournalConflict('native daily share source changed')
        data = dict(row['data'], shared_task=task_id, shared_at=__import__('time').time())
        return self._tls_journal.put(VIRTUAL_EVENTS, data['id'], scope, data, expected_revision=row['revision'],
            authorize=lambda: self._tls_allowed('share', scope))

    async def _tls_dispatch(self, umo, chain, *, metadata=None):
        if (not self._tls_allowed('send') or not callable(self._tls_send_chain)
                or self._tls_primary_scope['session_id'] != str(umo)):
            return False
        metadata = dict(metadata or {})
        dispatch = _DISPATCH_CONTEXT.get() or {}
        user = self._companion_delivery_user(str(umo))
        user = user if isinstance(user, dict) else {}
        # Cached planned fields are not evidence that this actual call belongs
        # to that candidate. A new user command must not reuse a stale random
        # or UNKNOWN candidate's occurrence or accidentally dispatch it.
        planned = dispatch.get('origin') == 'selected_planned_candidate'
        if planned:
            pool = self.data.get('proactive_candidate_pool', [])
            if not isinstance(pool, list) or len(pool) > 4096:
                return False
            original_ids = {str(item[key]) for item in pool if isinstance(item, dict)
                            for key in ('id', 'candidate_id', 'impulse_id')
                            if isinstance(item.get(key), (str, int)) and not isinstance(item.get(key), bool)}
            if any(str(user.get(key)) in original_ids for key in ('planned_candidate_id', 'planned_impulse_id')
                   if user.get(key) is not None):
                # The retired pool is preserved as history/unknown work. It is
                # not automatically admitted by the new sourced producer.
                return False
        source = str(user.get('planned_proactive_source') or '') if planned else ''
        reason = str(user.get('planned_proactive_reason') or user.get('planned_reason') or '') if planned else ''
        if (metadata.get('timer_receipt') or source in {'random', 'app', 'app_greeting', 'memo_note', 'timer',
                'personal_goal', 'important_date', 'environment_change'}
                or reason in {'personal_goal_progress', 'important_date', 'environment_change'}):
            return False
        category = (reason or source or dispatch.get('category') or 'user_requested_business_chain')[:80]
        occurrence = None
        for key in (('planned_candidate_id', 'planned_impulse_id') if planned else ()):
            value = user.get(key)
            if type(value) is str and 0 < len(value) <= 256:
                occurrence = [category, key, value]; break
        projection = self._native_daily_plan_view()
        if occurrence is None and projection is not None:
            occurrence = [category, 'scoped_plan', projection['native_plan_id'],
                          projection['date'], dispatch.get('event_id') or self._tls_source['event_id']]
        if occurrence is None:
            occurrence = [category, 'genuine_inbound', dispatch.get('event_id') or self._tls_source['event_id'],
                          self._environment_now().date().isoformat()]
        metadata.update(source='tls.native.pc.business', source_kind=category,
            source_event_id='pc.business.' + hashlib.sha256(canonical([self._tls_primary_scope, occurrence]).encode()).hexdigest(),
            source_evidence='genuine_inbound_sdk_selection', body_is_not_occurrence_identity=True)
        cleaner = getattr(self, '_redact_outbound_chain_secrets', None)
        outgoing = cleaner(list(chain))[0] if callable(cleaner) else list(chain)
        task = asyncio.current_task(); entered = task not in self._tls_tasks
        if entered: self._tls_tasks.add(task)
        try:
            result = await _value(self._tls_send_chain(dict(self._tls_primary_scope), str(umo), outgoing, metadata))
        finally:
            if entered: self._tls_tasks.discard(task)
        if isinstance(result, dict) and result.get('state') in {'unknown', 'quarantined'}:
            raise CompanionDeliveryUncertainError('tls.shared.delivery', RuntimeError('delivery_result_unknown'))
        return isinstance(result, dict) and result.get('state') == 'confirmed'

    async def _send_chain_components(self, umo, chain, *, require_companion_image=False):
        return await self._tls_dispatch(umo, chain, metadata=dict(require_companion_image=require_companion_image))

    async def _send_proactive_message_chain(self, umo, text, image_path='', *, extra_components=None,
            quote_message_id='', disable_segmenting=False, require_companion_image=False):
        from .native_pc_business.main import Image, Plain
        if require_companion_image and (not text or not image_path): return False
        components = []
        if text: components.append(Plain(str(text)))
        if image_path: components.append(Image.fromFileSystem(image_path))
        components.extend(extra_components or [])
        # A single occurrence is always one chain. The shared sender decides
        # supported component types/media counts; never split or fallback.
        return await self._tls_dispatch(umo, components,
            metadata=dict(require_companion_image=require_companion_image, quote_message_id=quote_message_id))

    async def _send_companion_chain_atomic(self, umo, components, *, timer_receipt=None):
        return await self._tls_dispatch(umo, components, metadata=dict(require_companion_image=True, timer_receipt=timer_receipt))

    async def _send_chain_components_via_onebot_direct(self, *args, **kwargs):
        return False, 'TLS 统一发送结果未确认；禁止切换到第二个直接发送出口'

    async def _send_segmented_event_forward_message(self, event, segments, *, source='decorating_result'):
        transform = OUTBOUND_TRANSFORM.get()
        if transform is not None:
            if getattr(self, 'segmented_proactive_send_as_forward', False) is True and len(segments) > 1:
                transform['segmented_forward_requested'] = True
            return False
        return await super()._send_segmented_event_forward_message(event, segments, source=source)

    async def _send_segmented_llm_chain_remainder(self, event, chunks, *, previous_segment='', source='', started_at=None):
        transform = OUTBOUND_TRANSFORM.get()
        if transform is not None:
            transform.setdefault('remaining_chains', []).extend(deepcopy(chunks))
            return None
        return await super()._send_segmented_llm_chain_remainder(event, chunks,
            previous_segment=previous_segment, source=source, started_at=started_at)

    def _schedule_reply_interception_forward(self, category, *, source='', reason='', source_session='',
            inbound='', before='', after='', detail=''):
        transform = OUTBOUND_TRANSFORM.get()
        if transform is not None:
            enabled = {'plugin_block': getattr(self, 'reply_interception_forward_plugin_blocks', False),
                       'rewrite': getattr(self, 'reply_interception_forward_rewrites', False),
                       'proactive_block': getattr(self, 'reply_interception_forward_proactive_blocks', False)}.get(str(category or ''), False)
            target = str(getattr(self, 'reply_interception_forward_target_umo', '') or '').strip()
            if getattr(self, 'enable_reply_interception_forward', False) and enabled and target:
                transform['secondary_operation'] = 'diagnostic_forward'
            return None
        return super()._schedule_reply_interception_forward(category, source=source, reason=reason,
            source_session=source_session, inbound=inbound, before=before, after=after, detail=detail)

    async def _send_single_poke(self, client, *, user_id, group_id):
        if not self._tls_allowed('platform_action') or not callable(self._tls_platform_action):
            raise PermissionError('poke requires the existing explicit platform-action adapter')
        dispatch=_DISPATCH_CONTEXT.get()
        if not isinstance(dispatch,dict) or not dispatch.get('event_id'):
            raise PermissionError('actual sourced interaction required')
        ordinal=dispatch.get('poke_ordinal',0)+1
        if not 1<=ordinal<=3:raise ValueError('original bounded poke count exceeded')
        dispatch['poke_ordinal']=ordinal
        occurrence=hashlib.sha256(canonical([dispatch['event_id'],dispatch.get('category'),ordinal]).encode()).hexdigest()
        result = await _value(self._tls_platform_action(dict(self._tls_primary_scope), 'poke',
            dict(user_id=user_id,group_id=group_id,source_event_id='pc.poke.'+occurrence)))
        if not isinstance(result, dict) or result.get('state') != 'confirmed':
            raise RuntimeError('platform poke was not confirmed')

    async def host_tick(self):
        if not self._tls_allowed('tick'): return dict(state='disabled', reason='no_genuine_bound_source')
        if self._tls_tick_lock.locked(): return dict(state='busy')
        task = asyncio.current_task(); self._tls_tasks.add(task)
        try:
            async with self._tls_tick_lock:
                self._tls_apply_ownership()
                results = {}
                # All bodies are now TLS-owned source. Existing time checks,
                # cooldowns, persisted candidates and generation limits remain.
                for name in ('_ensure_daily_state', '_ensure_detail_enhancement',
                    '_ensure_current_detail_presence_status', '_ensure_daily_diary',
                    '_ensure_daily_outfit_photo', '_maybe_advance_creative_projects',
                    '_maybe_refresh_balance_awareness', '_refresh_passive_injection_cache'):
                    if not self._tls_allowed('tick'): break
                    method = getattr(self, name, None)
                    if not callable(method): continue
                    if name in {'_ensure_detail_enhancement', '_ensure_daily_diary', '_ensure_daily_outfit_photo'} and self._native_daily_plan_view() is None:
                        results[name] = 'waiting_for_explicit_scoped_plan'; continue
                    token = _DISPATCH_CONTEXT.set(dict(origin='native_daily_maintenance', category=name,
                                                       event_id=self._tls_source['event_id']))
                    try:
                        await _value(method())
                        results[name] = 'returned'
                    except asyncio.CancelledError: raise
                    except Exception as error:
                        results[name] = 'failed:' + type(error).__name__
                    finally: _DISPATCH_CONTEXT.reset(token)
                self._tls_last_tick = __import__('time').time()
                return dict(state='current', operations=results, independent_scheduler=False)
        finally: self._tls_tasks.discard(task)

    def hook_specs(self):
        records = json.loads((_HERE / 'EVENT-HOOKS.json').read_text(encoding='utf-8'))['hooks']
        return [dict(row, handler=self.hook(row['function'])) for row in records
                if row['module'] == 'main.py' and row['decorator'].startswith('filter.')
                and callable(getattr(self, row['function'], None))]

    def hook(self, name):
        original = getattr(self, name)
        def dispatch_context(args):
            message = getattr(args[0], 'message_obj', None) if args else None
            event_id = getattr(message, 'message_id', None)
            if not isinstance(event_id, str) or not event_id:
                event_id = self._tls_source['event_id'] if self._tls_source else ''
            return dict(origin='genuine_inbound_hook', category=name, event_id=event_id, service=self)
        async def music_view(args, dispatch):
            if name not in {'pc_music_lookup', 'inject_humanized_state'}:
                return
            reader = self._tls_music_library_reader
            if reader is None:
                dispatch['music_view'] = None
                return
            try:
                view = await asyncio.to_thread(reader, args[0] if args else None)
                dispatch['music_view'] = view if self._tls_music_library_reader is reader else None
            except Exception:
                dispatch['music_view'] = None
        if inspect.isasyncgenfunction(original):
            async def generator(*args, **kwargs):
                if not self._tls_allowed('hook'): return
                task = asyncio.current_task(); entered = task not in self._tls_tasks
                if entered: self._tls_tasks.add(task)
                dispatch = dispatch_context(args)
                token = _DISPATCH_CONTEXT.set(dispatch)
                try:
                    await music_view(args, dispatch)
                    async for result in original(*args, **kwargs): yield result
                finally:
                    _DISPATCH_CONTEXT.reset(token)
                    if entered: self._tls_tasks.discard(task)
            return generator
        if inspect.iscoroutinefunction(original):
            async def coroutine(*args, **kwargs):
                if not self._tls_allowed('hook'): return None
                task = asyncio.current_task(); entered = task not in self._tls_tasks
                if entered: self._tls_tasks.add(task)
                dispatch = dispatch_context(args)
                token = _DISPATCH_CONTEXT.set(dispatch)
                try:
                    await music_view(args, dispatch)
                    return await original(*args, **kwargs)
                finally:
                    _DISPATCH_CONTEXT.reset(token)
                    if entered: self._tls_tasks.discard(task)
            return coroutine
        def function(*args, **kwargs):
            if not self._tls_allowed('hook'): return None
            return original(*args, **kwargs)
        return function

    def _music_db(self):
        dispatch = _DISPATCH_CONTEXT.get()
        view = dispatch.get('music_view') if isinstance(dispatch, dict) and dispatch.get('service') is self else None
        current = view.get('current') if isinstance(view, dict) else None
        def allowed():
            try: return callable(current) and current() is True
            except Exception: return False
        if getattr(self, '_tls_music_library_reader', None) is None or not allowed():
            return dict(songs=[], _tls_music_source=dict(kind='blocked', reason='current_music_scope_or_read_grant_unavailable'))
        if view.get('allow_legacy') is True:
            legacy = deepcopy(super()._music_db())
            legacy['_tls_music_source'] = dict(kind='legacy_json_fallback', ownership='unassigned_legacy_catalog',
                metadata_only=True, creates_playback_evidence=False)
            return legacy if allowed() else dict(songs=[], _tls_music_source=dict(kind='blocked'))
        return deepcopy(view['db'])

    def register_native_routes(self):
        if self.page_api is not None: return
        from .native_pc_business.page_api import PrivateCompanionPageApi
        from astrbot.api.web import error_response
        service = self
        class NativePage(PrivateCompanionPageApi):
            def _apply_config_value(self, key, value, overrides=None):
                super()._apply_config_value(key,value,overrides)
                # A mature-editor setting cannot reopen superseded writers.
                service._tls_apply_ownership()
            async def update_personal_goal(self):
                return error_response('请在 TLS“个人目标与日常”维护原生目标。', status_code=409)
            async def update_memo_note(self):
                # The old JSON memo consumer is retired. Cached mature pages
                # must not claim to schedule reminders in an unconsumed store.
                return error_response('旧便签资料仅供查阅；请在 TLS“便签与待办”维护原生便签和提醒。', status_code=409)
            async def get_image_cache_preview_data(self):
                # Image elements cannot attach the SDK's authorization header.
                # Read the same fixed cache entry through the existing bridge.
                import base64
                import io
                from PIL import Image
                from astrbot.api.web import request, json_response
                if not str(getattr(request,'username','') or '').strip():
                    return error_response('请先登录AstrBot后台。',status_code=401)
                key=self._single_line(request.query.get('key'),120)
                if not key:return error_response('缺少缓存 key。',status_code=400)
                async with service._data_lock:
                    cache=service.data.get('private_image_vision_cache')
                    item=cache.get(key) if isinstance(cache,dict) else None
                    if not isinstance(item,dict):return error_response('缓存条目不存在。',status_code=404)
                    path=self._image_cache_preview_file(key,item)
                    if path is None:return error_response('预览文件不可用，缓存正文仍可查阅。',status_code=404)
                    if not 0<path.stat().st_size<=2*1024*1024:
                        return error_response('预览图片超出2 MiB读取范围。',status_code=413)
                    raw=path.read_bytes()
                    try:
                        with Image.open(io.BytesIO(raw)) as image:
                            kind=image.format
                            if kind not in {'PNG','JPEG','GIF','WEBP'} or image.width*image.height>64000000:
                                return error_response('预览格式或尺寸不可用。',status_code=400)
                    except (OSError,ValueError):return error_response('预览图片格式不可读取。',status_code=400)
                    if not service._tls_running:return error_response('TLS角色服务已停止。',status_code=503)
                    media={'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif','WEBP':'image/webp'}[kind]
                    return json_response(self._ok(dict(data_url='data:'+media+';base64,'+base64.b64encode(raw).decode('ascii'))),
                        headers={'Cache-Control':'no-store'})
        self.page_api = NativePage(self)
        self.page_api.register_routes()
        self.context.register_web_api('/astrbot_plugin_virtual_body/page/pc/image_cache/preview_data',
            self.page_api.get_image_cache_preview_data,['GET'],'TLS authenticated image-cache preview data')
        registry = self.context.registered_web_apis
        for index, entry in enumerate(list(registry)):
            route, handler, methods, description = entry
            if not route.startswith('/astrbot_plugin_virtual_body/page/pc/') or getattr(handler, '__self__', None) is not self.page_api: continue
            async def guarded(*args, _handler=handler, **kwargs):
                if not service._tls_running:
                    return error_response('TLS 角色日常服务已停止。', status_code=503)
                return await _value(_handler(*args, **kwargs))
            replacement = (route, guarded, methods, description)
            registry[index] = replacement; self._tls_registered_routes.append(replacement)

    def diagnostics(self):
        return dict(active=self._tls_running, initialized=self._tls_initialized,
            bound_source=self._tls_primary_scope is not None, source_kind='genuine_inbound_sdk_selection' if self._tls_source else None,
            source_package='tls.native_pc_business', legacy_star_required=False, independent_scheduler=False,
            raw_direct_fallback=False, send_adapter_present=callable(self._tls_send_chain),
            hook_count=len(self.hook_specs()), native_routes=len(self._tls_registered_routes),
            last_tick=self._tls_last_tick, tasks=len(self._tls_tasks), legacy_history_preserved=True,
            goals_owned_by_existing_tls=True, memos_owned_by_existing_tls=True)

    async def terminate(self):
        self._tls_running = False
        self._tls_music_library_reader = None
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            running = set(task for task in self._tls_tasks if task is not asyncio.current_task() and not task.done())
            for task in asyncio.all_tasks():
                if task is asyncio.current_task() or task.done(): continue
                current, seen = task.get_coro(), set()
                for _ in range(96):
                    if current is None or id(current) in seen: break
                    seen.add(id(current)); code = getattr(current, 'cr_code', getattr(current, 'gi_code', None))
                    if code is not None:
                        filename = str(code.co_filename).replace('\\', '/')
                        if filename.startswith(str(_HERE).replace('\\', '/') + '/'):
                            running.add(task); break
                    current = getattr(current, 'cr_await', getattr(current, 'gi_yieldfrom', None))
            if not running: break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0: raise RuntimeError('native PC business operations still draining; retain runtime references')
            await asyncio.wait(running, timeout=min(remaining, .2))
        await super().terminate()
