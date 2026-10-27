"""Native home for the independent proactive plugin's existing business flow.

Construction is inert. Original session/configuration/LLM modules are reused;
the existing Host tick drives their date jobs and the existing delivery lane
is the only sender. No standalone server, telemetry loop, pseudo input event,
second persistent queue, or platform sender is started here.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from functools import partial
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import time
from types import MappingProxyType, MethodType, SimpleNamespace
from zoneinfo import ZoneInfo

from ..state import _atomic_json
from .models import canonical, private_scope
from .delivery_types import make_task
from .native_proactive_chat.core.chat_flow import ProactiveCoreMixin
from .native_proactive_chat.core.data_storage import StorageMixin
from .native_proactive_chat.core.llm_adapter import LlmMixin
from .native_proactive_chat.core.message_events import EventsMixin
from .native_proactive_chat.core.message_sender import SenderMixin
from .native_proactive_chat.core.session_config import ConfigMixin
from .native_proactive_chat.core.session_override_manager import SessionOverrideManager
from .native_proactive_chat.core.session_parser import SessionMixin
from .native_proactive_chat.core.task_scheduler import SchedulerMixin


NAMESPACE = 'tls.proactive.chat.v1'
SOURCE_ID = 'tls.proactive.chat'
LINKED_SOURCE = 'tls.proactive.linked_app_source.v1'
_ACTIVE_DELIVERY = {'candidate', 'approved', 'queued', 'claimed', 'sending', 'retry_wait', 'paused'}
PC_OUTBOUND_METHODS = frozenset({
    'bridge_proactive_chat_outbound', 'finalize_proactive_chat_outbound_bridge',
    'stop_passive_input_status_before_private_send', 'suppress_recent_duplicate_outbound_text',
    'suppress_group_llm_reply_block_before_send', 'strip_outbound_control_blocks_before_send',
    'strip_plaintext_tool_calls_before_send', 'cancel_reply_if_trigger_recalled_before_send',
    'suppress_forbidden_outbound_before_send', 'suppress_framework_error_leak_before_send',
    'suppress_group_question_wakeup_collision_reply', 'suppress_smart_silence_reply_before_send',
    'record_empty_passive_result_before_send', 'apply_tts_enhancement_before_send_hook',
    'strip_group_internal_identity_anchors', 'suppress_group_silent_control_reply',
    'strip_unexpected_private_passive_reply', 'apply_segmented_llm_reply_scope',
    'remember_group_bot_reply_context_before_send', 'final_tts_markup_guard_before_send',
    'attach_group_reply_quote', 'redact_outbound_secrets_before_send',
})


def clean_text_pipeline(text):
    """The exact TLS outbound text transforms, without constructing an event."""
    from ..inject import sanitize_outbound_text, sanitize_outbound_mixed
    from ..presence_context import strip_context as strip_environment_context
    from .context_engine import strip_context as strip_living_context
    from ..render import sanitize_outbound_text as sanitize_rendered_text
    if not text or ('<' not in text and '＜' not in text and '身体状态' not in text and '空间' not in text):
        return text
    cleaned = sanitize_outbound_text(str(text))
    cleaned = strip_environment_context(cleaned)
    cleaned = strip_living_context(cleaned)
    cleaned = sanitize_outbound_mixed(cleaned)
    return sanitize_rendered_text(cleaned)


def _content_sha(text, images, audio=None, audio_text=True):
    values = [text.strip(), images]
    if audio is not None:
        values.extend(['tls.delivery.audio.v1', audio, audio_text])
    return hashlib.sha256(canonical(values).encode()).hexdigest()


def _copy_owned_speech(source, media_root):
    """Materialize only the current trusted TTS provider's local output."""
    if not isinstance(source, str) or not source or '://' in source:
        raise ValueError('TTS output must be a local file')
    original = Path(source)
    if original.is_symlink():
        raise ValueError('TTS output must not be linked')
    original = original.resolve()
    before = original.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 20 * 1024**2:
        raise ValueError('bounded TTS audio file required')
    raw = original.read_bytes()
    after = original.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != before.st_size:
        raise ValueError('TTS output changed during owned materialization')
    suffix = original.suffix.lower()
    if suffix not in {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.amr', '.silk', '.pcm'}:
        raise ValueError('TTS output format is unsupported by the current unified adapter')
    root = Path(media_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('existing private delivery media root required')
    root = root.resolve()
    target = root / ('proactive-tts-' + hashlib.sha256(raw).hexdigest() + suffix)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != raw:
            raise ValueError('owned audio content identity conflict')
    else:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return str(target)


class _DeliveryStopped(BaseException):
    """Do not let old catch/compensation paths resend an uncertain operation."""
    def __init__(self, state, reason):
        self.state, self.reason = state, reason
        super().__init__(reason)


class _DateJobs:
    """RAM index of the existing legacy dates; LivingHost supplies the clock."""
    def __init__(self, owner):
        self.owner, self.jobs, self.running = owner, {}, False

    def add_job(self, func, trigger, *, run_date, args, id, replace_existing=False, **unused):
        if trigger != 'date' or not callable(func):
            raise ValueError('only existing one-shot date jobs are supported')
        if id in self.jobs and not replace_existing:
            raise ValueError('date job already exists')
        job = SimpleNamespace(id=str(id), func=func, args=list(args),
            next_run_time=run_date, trigger='date', cancel=lambda: self.jobs.pop(str(id), None))
        self.jobs[str(id)] = job
        return job

    def get_job(self, identity):
        return self.jobs.get(identity)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, identity):
        self.jobs.pop(identity, None)

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False
        self.jobs.clear()


class NativeProactiveChatHost(SessionMixin, StorageMixin, ConfigMixin,
        SchedulerMixin, LlmMixin, SenderMixin, EventsMixin, ProactiveCoreMixin):
    protocol = 'tls.native.proactive_chat.v1'

    def __init__(self, plugin, host, config, data_dir, *, legacy_closed,
            authorize=None, scope_for_umo=None, decorator_inventory=None,
            image_for_text=None, clock=time.time):
        if not callable(legacy_closed):
            raise ValueError('the original executor shutdown proof is required')
        self.plugin, self.host, self.context = plugin, host, plugin.context
        self.config, self.data_dir = config, Path(data_dir)
        self.session_data_file = self.data_dir / 'session_data.json'
        self.legacy_closed, self.clock = legacy_closed, clock
        self.authorize = authorize or host.authorized_scope
        self.scope_for_umo = scope_for_umo or host.presence.peek_scope_for_session
        self.decorator_inventory, self.image_for_text = decorator_inventory, image_for_text
        self.data_lock = asyncio.Lock()
        self.scheduler = _DateJobs(self)
        self.session_data, self.session_temp_state, self.last_message_times = {}, {}, {}
        self.group_timers, self.auto_trigger_timers = {}, {}
        self.manual_trigger_sessions, self.first_message_logged = set(), set()
        self.last_bot_message_time = 0
        self.plugin_start_time, self._cleanup_counter = clock(), 0
        self.session_override_manager = None
        self.telemetry = self.notification_center = self.web_admin_server = None
        self.timezone = None
        self.active = self._closed = False
        self._phase, self._last_error = 'closed', None
        self._running, self._frames, self._unknown, self._overdue = set(), {}, {}, []
        self._waiting_scopes = {}
        self._last_admission = {}
        self._counts = dict(started=0, model_requests=0, submitted=0, confirmed=0, unknown=0,
            tts_requests=0, tts_audio_prepared=0, tts_text_fallbacks=0)
        self._tts_last_reason = None
        self._outbound_hooks = dict(envelopes=0, executed=0, suppressed=0,
            secondary_operations_blocked=0, inbound_registration_calls=0,
            segmented_paragraphs_collected=0)

    @property
    def runtime(self):
        return self.host.runtime

    @property
    def journal(self):
        return self.host.journal

    def _physical(self):
        return (not self._closed and getattr(self.plugin, '_stopping', False) is not True
            and getattr(self.host, '_closed', True) is False
            and getattr(self.runtime, 'active', False) is True
            and getattr(self.journal, '_closed', True) is False
            and self.legacy_closed() is True)

    def _scope(self, session):
        value = self.scope_for_umo(session)
        scope = private_scope(value)
        if scope['session_id'] != session or self.authorize(scope) is not True:
            raise PermissionError('a real current private scope is required')
        return scope

    def _source_record(self, session):
        value = self.session_data.get(session, {}).get('tls_linked_source')
        return value if (isinstance(value, dict) and value.get('schema') == LINKED_SOURCE
            and isinstance(value.get('policy_session'), str) and isinstance(value.get('scope'), dict)
            and value['scope'].get('session_id') == session) else None

    def policy_session(self, session):
        """One original policy/override key; this alias grants no live scope."""
        source = self._source_record(session)
        return source['policy_session'] if source is not None else session

    def _get_base_session_config(self, session):
        return ConfigMixin._get_base_session_config(self, self.policy_session(session))

    def _get_session_config(self, session):
        policy = self.policy_session(session)
        if policy == session:
            return ConfigMixin._get_session_config(self, session)
        base = ConfigMixin._get_base_session_config(self, policy)
        if not base or self.session_override_manager is None:
            return base
        # A linked source shares the original policy key even when that QQ
        # platform is offline. Normalizing it into another platform would
        # silently lose the existing user's override. This grants no lease.
        effective = self.session_override_manager.get_effective(policy, base)
        effective['_session_type'] = base.get('_session_type')
        effective['_from_session_list'] = base.get('_from_session_list', False)
        effective['_has_override'] = bool(self.session_override_manager.get_override(policy))
        return effective

    def _normalize_session_id(self, session):
        # The inherited QQ resolver intentionally excludes webchat platforms.
        # Preserve the real SDK's private APP UMO; authorization is still done
        # independently by _scope and the current binding/Persona checks.
        parsed = self._parse_session_id(session)
        if (parsed and parsed[0] == 'webchat' and parsed[1] == 'FriendMessage'
                and parsed[2].startswith('webchat!')):
            return session
        return SessionMixin._normalize_session_id(self, session)

    @staticmethod
    def _app_identity(scope):
        if scope.get('platform') != 'webchat' or scope.get('bot_id') != 'webchat':
            raise PermissionError('linked_source_requires_real_app_scope')
        parts = scope['session_id'].split(':', 2)
        prefix = 'webchat!' + scope['user_id'] + '!'
        if len(parts) != 3 or parts[:2] != ['webchat', 'FriendMessage'] or not parts[2].startswith(prefix):
            raise PermissionError('linked_app_origin_invalid')
        return scope['user_id'], parts[2][len(prefix):]

    def _current_app_source(self):
        """Read only the single actual PC source; never bootstrap a QQ lease."""
        from .chat_identity import identity_service
        from .chat_workspace import ChatWorkspace
        service = self._pc_outbound_service()
        if service is None or not service.native_source_current():
            raise PermissionError('native_pc_source_unavailable')
        scope = private_scope(service._tls_primary_scope)
        username, sid = self._app_identity(scope)
        if self._scope(scope['session_id']) != scope:
            raise PermissionError('app_real_scope_unavailable')
        actual = service._tls_source
        if (not isinstance(actual, dict) or actual.get('source') != 'genuine_inbound_sdk_selection'
                or not isinstance(actual.get('event_id'), str) or not actual['event_id'] or actual['event_id'] == '0'
                or not isinstance(actual.get('persona_id'), str) or not actual['persona_id']):
            raise PermissionError('app_real_persona_unavailable')
        links = identity_service(self.plugin)
        row = links.get(username, sid)
        if not row:
            raise PermissionError('app_binding_unconfirmed')
        if row.get('app_scope') != scope or row.get('app_persona') != actual['persona_id']:
            raise PermissionError('app_persona_observation_not_current')
        mode = ChatWorkspace(links).settings(username, sid)['values']['proactive_destination']
        if mode not in {'chat_text', 'chat_all'}:
            raise PermissionError('app_proactive_destination_not_selected')
        qq_scope = private_scope(row['qq_scope'])
        cfg = ConfigMixin._get_session_config(self, qq_scope['session_id'])
        if not cfg or cfg.get('enable') is not True:
            raise PermissionError('linked_original_policy_disabled')
        # QQ supplies the explicitly configured timing/wording only. No QQ
        # Persona, history, scope lease or owner is inferred from the binding.
        return dict(schema=LINKED_SOURCE, link_id=row['link_id'], username=username,
            app_session_id=sid, scope=scope, qq_scope=qq_scope,
            policy_session=qq_scope['session_id'], persona_id=actual['persona_id'],
            event_id=actual['event_id'], destination=mode)

    def _paired_pending_reason(self, source):
        session = source['policy_session']
        if session in self._frames: return 'paired_source_in_flight'
        if session in self._unknown: return 'paired_source_unknown'
        counts = self.runtime.delivery.store.task_counts(source['qq_scope'])
        if any(counts.get(name, 0) for name in ('unknown', 'quarantined')):
            return 'paired_delivery_unknown'
        if any(counts.get(name, 0) for name in ('claimed', 'sending')):
            return 'paired_delivery_in_flight'
        old = self.session_data.get(session, {})
        if old.get('next_trigger_time') is not None:
            key = 'occurrence:' + self._occurrence(session, old)
            receipt = self.journal.fetch(NAMESPACE, key, source['qq_scope'])
            if receipt and receipt['data'].get('phase') in {'running', 'unknown'}:
                return 'paired_occurrence_unknown'
        return None

    def _linked_source_reason(self, scope, expected=None):
        session = scope['session_id']; source = self._source_record(session)
        if source is not None:
            try:
                fresh = self._current_app_source()
                if fresh != source or (expected is not None and expected != fresh):
                    return 'linked_app_source_changed'
                return self._paired_pending_reason(fresh)
            except (PermissionError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                return 'linked_app_authority_or_persona_unavailable'
        # A selected APP source fences its paired original dates without
        # deleting the original jobs, overdue state or UNKNOWN receipts.
        if scope.get('platform') != 'webchat':
            selected = [info.get('tls_linked_source') for info in self.session_data.values()
                if isinstance(info, dict) and isinstance(info.get('tls_linked_source'), dict)
                and info['tls_linked_source'].get('schema') == LINKED_SOURCE
                and info['tls_linked_source'].get('policy_session') == session]
            if not selected: return None
            try:
                from .chat_identity import identity_service
                from .chat_workspace import ChatWorkspace
                links = identity_service(self.plugin); row = links.for_qq(scope)
                if row and ChatWorkspace(links).settings(row['username'], row['session_id'])['values']['proactive_destination'] in {'chat_text', 'chat_all'}:
                    app = row.get('app_scope')
                    current = self._source_record(app['session_id']) if isinstance(app, dict) else None
                    if current and current.get('link_id') == row['link_id']:
                        return 'linked_app_source_selected'
            except (RuntimeError, ValueError, KeyError, AttributeError):
                return 'linked_source_status_unavailable'
        return None

    async def _resume_linked_app_source(self):
        """Continue an actual RAM handoff once; a tick never rerolls a due time."""
        lock = getattr(self, '_linked_source_lock', None)
        if lock is None:
            lock = self._linked_source_lock = asyncio.Lock()
        async with lock:
            return await self._resume_linked_app_source_locked()

    async def _resume_linked_app_source_locked(self):
        try:
            source = self._current_app_source()
        except (PermissionError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self._linked_source_discovery_reason = str(exc) if isinstance(exc, PermissionError) else type(exc).__name__
            return False
        self._linked_source_discovery_reason = None
        session = source['scope']['session_id']; info = self.session_data.get(session, {})
        old = self._source_record(session)
        if old == source and info.get('next_trigger_time') is not None:
            return True
        if session in self._frames or session in self._unknown:
            self._waiting_scopes[session] = 'app_occurrence_in_flight_or_unknown'; return False
        if old is not None and info.get('next_trigger_time') is not None:
            receipt = self.journal.fetch(NAMESPACE, 'occurrence:' + self._occurrence(session, info), source['scope'])
            if receipt and receipt['data'].get('phase') in {'running', 'unknown'}:
                self._waiting_scopes[session] = 'app_occurrence_unknown'; return False
        if old is None and info.get('next_trigger_time') is not None:
            self._waiting_scopes[session] = 'existing_app_occurrence_requires_review'; return False
        if old is not None and old.get('event_id') == source['event_id']:
            self._waiting_scopes[session] = 'linked_source_change_waiting_for_real_activity'; return False
        reason = self._paired_pending_reason(source)
        if reason:
            self._waiting_scopes[session] = reason; return False
        async with self.data_lock:
            if self._current_app_source() != source:
                return False
            self.session_data.setdefault(session, {})['tls_linked_source'] = source
            # This is the same real APP event ID already accepted by PC. Old
            # QQ counters/dates remain byte-for-byte in their original entry.
            self.session_data[session]['self_id'] = source['scope']['bot_id']
            self.session_data[session]['last_message_time'] = self.clock()
        self.last_message_times[session] = self.clock()
        await self._schedule_next_chat_and_save(session, reset_counter=True)
        self._waiting_scopes.pop(session, None)
        return True

    def _enabled_sessions(self):
        result = set(self.session_data)
        for key in ('friend_settings', 'group_settings'):
            block = self.config.get(key, {})
            if isinstance(block, dict):
                for item in block.get('session_list', []):
                    if isinstance(item, str) and self._parse_session_id(item):
                        result.add(self._normalize_session_id(item))
        return sorted(result)

    def _decorator_records(self):
        if self.decorator_inventory is not None:
            handlers = self.decorator_inventory()
        else:
            from astrbot.core.star.star_handler import EventType, star_handlers_registry
            handlers = star_handlers_registry.get_handlers_by_event_type(EventType.OnDecoratingResultEvent)
        if not isinstance(handlers, (list, tuple)) or len(handlers) > 256:
            raise RuntimeError('current activated outbound registry unavailable')
        return handlers

    def _pc_outbound_service(self):
        integrations = getattr(self.plugin, '_native_server_integrations', None)
        owner = getattr(integrations, 'pc_full', None)
        return getattr(owner, 'service', None) if getattr(owner, 'active', False) is True else None

    def _outbound_scope_ready(self, scope):
        service = self._pc_outbound_service()
        return (service is None or service._tls_primary_scope == scope
            and service.native_source_current() and service._tls_allowed('hook', scope))

    def _decorators(self):
        try:
            handlers = self._decorator_records()
            rows = []
            cls = type(self.plugin)
            native_module = cls.__module__
            is_tls = cls.__name__ == 'VirtualBodyPlugin' and native_module.endswith('astrbot_plugin_virtual_body.main')
            for handler in handlers:
                callback = getattr(handler, 'handler', None)
                name = getattr(handler, 'handler_name', '')
                module = getattr(handler, 'handler_module_path', '')
                expected = getattr(cls, name, None) if isinstance(name, str) else None
                if isinstance(callback, partial):
                    exact = callback.func is expected and callback.args == (self.plugin,) and not callback.keywords
                else:
                    exact = (getattr(callback, '__self__', None) is self.plugin
                        and getattr(callback, '__func__', None) is expected)
                supported = (is_tls and module == native_module and exact
                    and name in {'sanitize_presence_tags_outbound', 'decorate_native_expression'})
                original_pc = name.removeprefix('integrated_pc_') if isinstance(name, str) else ''
                pc_wrapper = (is_tls and module == native_module and exact
                    and name.startswith('integrated_pc_') and original_pc in PC_OUTBOUND_METHODS)
                supported = supported or pc_wrapper
                behavior = 'unsupported_active_handler'
                if pc_wrapper:
                    behavior = 'actual_native_pc_outbound_handler'
                elif supported and name == 'sanitize_presence_tags_outbound':
                    behavior = 'exact_native_pure_text_pipeline'
                elif supported:
                    # Original proactive SenderMixin creates the generic base
                    # AstrMessageEvent, while this decorator requires an actual
                    # AiocqhttpMessageEvent. It cannot append a sticker in the
                    # old proactive synthetic-event path. Do not fake one now.
                    behavior = ('native_owned_image_callback' if self.image_for_text is not None
                        else 'registered_expression_not_applied_without_real_qq_event')
                rows.append(dict(name=name, module=module, full_name=getattr(handler, 'handler_full_name', ''),
                    supported=supported, behavior=behavior))
            return rows
        except Exception:
            return None

    async def _transform_outbound(self, frame, text):
        """An SDK output envelope, never an incoming event or authority grant."""
        from astrbot.api.event import AstrMessageEvent
        from astrbot.api.message_components import Plain
        from astrbot.core.message.message_event_result import MessageEventResult
        from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
        from astrbot.core.platform.message_type import MessageType
        from .native_pc_service import OUTBOUND_TRANSFORM
        scope = frame['scope']
        rows = self._decorators()
        if rows is None or any(not row['supported'] for row in rows):
            raise _DeliveryStopped('blocked', 'outbound_handler_inventory_changed')
        service = self._pc_outbound_service()
        if service is not None:
            if (not service.native_source_current() or service._tls_primary_scope != scope
                    or not service._tls_allowed('hook', scope)):
                raise _DeliveryStopped('blocked', 'native_pc_outbound_scope_not_current')
        parsed = self._parse_session_id(frame['session_id'])
        if not parsed:
            raise _DeliveryStopped('blocked', 'outbound_session_invalid')
        platform_id, _, _ = parsed
        platforms = self.context.platform_manager.get_insts()
        matching = [platform for platform in platforms
            if platform_id in {platform.meta().id, platform.meta().name}]
        if len(matching) != 1:
            raise _DeliveryStopped('blocked', 'outbound_actual_platform_unavailable')
        obj = AstrBotMessage()
        target = parsed[2] if scope['platform'] == 'webchat' else scope['user_id']
        obj.type, obj.session_id, obj.self_id = MessageType.FRIEND_MESSAGE, target, scope['bot_id']
        obj.sender, obj.message, obj.message_str = MessageMember(user_id=scope['user_id']), [], ''
        obj.raw_message, obj.message_id = None, ''
        envelope = AstrMessageEvent(message_str='', message_obj=obj,
            platform_meta=matching[0].meta(), session_id=target)
        if envelope.unified_msg_origin != scope['session_id']:
            raise _DeliveryStopped('blocked', 'outbound_sdk_session_drift')
        result = MessageEventResult()
        result.chain = [Plain(text)]
        envelope.set_result(result)
        envelope.private_companion_proactive_framework = True
        envelope._private_companion_external_proactive_source = SOURCE_ID
        # This is ownership of speech processing, not a claim that speech was
        # already produced. The real provider is called only later below.
        envelope._private_companion_skip_tts_enhancement = 'tls_independent_proactive_owns_tts'
        envelope.tls_outbound_scope = MappingProxyType(dict(scope))
        envelope.tls_outbound_source = MappingProxyType(dict(source_id=SOURCE_ID,
            occurrence=frame['occurrence'], event_id=frame['event_id']))
        async def no_platform_send(_event, *args, **kwargs):
            raise _DeliveryStopped('blocked', 'decorator_attempted_a_second_platform_send')
        envelope.send = MethodType(no_platform_send, envelope)
        guard = dict(source_id=SOURCE_ID, occurrence=frame['occurrence'])
        token = OUTBOUND_TRANSFORM.set(guard)
        self._outbound_hooks['envelopes'] += 1
        try:
            handlers = self._decorator_records()
            if len(handlers) != len(rows):
                raise _DeliveryStopped('blocked', 'outbound_handler_inventory_changed')
            for handler, row in zip(handlers, rows):
                if (getattr(handler, 'handler_name', '') != row['name']
                        or getattr(handler, 'handler_full_name', '') != row['full_name']
                        or not self._allowed(scope) or self._pc_outbound_service() is not service):
                    raise _DeliveryStopped('blocked', 'outbound_authority_or_handler_changed')
                if row['name'] == 'decorate_native_expression':
                    # Actual code requires AiocqhttpMessageEvent. The original
                    # generic proactive output envelope never met that rule;
                    # image_for_text remains the separate owned-image option.
                    continue
                try:
                    await handler.handler(envelope)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise _DeliveryStopped('blocked', 'native_outbound_handler_failed:' + row['name'])
                self._outbound_hooks['executed'] += 1
                if row['name'] == 'integrated_pc_apply_segmented_llm_reply_scope':
                    # The real mature handler starts one remainder coroutine.
                    # NativePCService's outbound-only override gathers its
                    # chunks synchronously instead of opening another sender.
                    await asyncio.sleep(0)
                    if guard.get('segmented_forward_requested'):
                        raise _DeliveryStopped('blocked', 'typed_forward_card_not_supported_by_current_lane')
                    remaining = guard.pop('remaining_chains', [])
                    if remaining:
                        chunks = [list(envelope.get_result().chain or [])] + remaining
                        if any(not isinstance(comp, Plain) for chunk in chunks for comp in chunk):
                            raise _DeliveryStopped('blocked', 'segmented_hook_added_unowned_media')
                        combined = '\n'.join(''.join(str(comp.text or '') for comp in chunk) for chunk in chunks)
                        envelope.get_result().chain = [Plain(combined)]
                        self._outbound_hooks['segmented_paragraphs_collected'] += len(chunks)
                if guard.get('secondary_operation'):
                    self._outbound_hooks['secondary_operations_blocked'] += 1
                    raise _DeliveryStopped('blocked', 'outbound_handler_attempted_' + guard['secondary_operation'])
                if (not self._allowed(scope) or self._pc_outbound_service() is not service
                        or service is not None and not service.native_source_current()):
                    raise _DeliveryStopped('blocked', 'authority_closed_during_outbound_transform')
                if envelope.is_stopped() or not getattr(envelope.get_result(), 'chain', None):
                    self._outbound_hooks['suppressed'] += 1
                    raise _DeliveryStopped('blocked', 'native_outbound_policy_suppressed')
            final = list(envelope.get_result().chain or [])
            if any(not isinstance(component, Plain) for component in final):
                raise _DeliveryStopped('blocked', 'outbound_handler_added_unowned_components')
            transformed = ''.join(str(component.text or '') for component in final)
            if service is not None:
                # PC's speech generator was deliberately skipped; reuse its
                # established pure markup fallback before this owner performs
                # its one configured speech-provider call.
                transformed = service._strip_any_tts_markup(transformed)
            if not transformed.strip():
                raise _DeliveryStopped('blocked', 'empty_after_outbound_transform')
            return transformed
        finally:
            OUTBOUND_TRANSFORM.reset(token)

    def migration_blockers(self):
        issues = []
        for session in self._enabled_sessions():
            cfg = self._get_session_config(session)
            if not cfg or not cfg.get('enable', False):
                continue
            if cfg.get('tts_settings', {}).get('enable_tts', True) is not False and not self._audio_supported():
                issues.append(dict(session_id=session, reason='enabled_tts_not_supported_by_unified_lane'))
            if cfg.get('segmented_reply_settings', {}).get('enable', False) is True:
                issues.append(dict(session_id=session, reason='enabled_segmentation_not_supported_by_single_task_lane'))
            parsed = self._parse_session_id(session)
            if not parsed or not self._is_friend_type(parsed[1]):
                issues.append(dict(session_id=session, reason='group_scope_not_authorized_by_private_lane'))
        decorators = self._decorators()
        unsupported = [row for row in decorators or [] if not row['supported']]
        if decorators is None or unsupported:
            issues.append(dict(reason='decorating_handler_inventory_unknown' if decorators is None
                else 'enabled_decorating_handlers_not_supported_by_unified_lane',
                count=None if decorators is None else len(unsupported), handlers=unsupported))
        return issues

    def _audio_supported(self):
        delivery = getattr(self.runtime, 'delivery', None)
        adapter = getattr(getattr(delivery, 'sender', None), 'adapter', None)
        return getattr(adapter, 'supports_audio', False) is True and isinstance(getattr(adapter, 'media_root', None), Path)

    async def prepare(self):
        """Read the exact old files, without scheduling, sending or rewriting."""
        if self.active or self._running:
            return self.status()
        raw = await asyncio.to_thread(self.session_data_file.read_bytes)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('legacy proactive state exceeds supported read bound')
        loaded = json.loads(raw)
        if not isinstance(loaded, dict) or any(not isinstance(key, str) or not isinstance(value, dict)
                for key, value in loaded.items()):
            raise ValueError('legacy proactive state must be preserved for manual repair')
        override_path = self.data_dir / SessionOverrideManager.OVERRIDES_FILE
        if override_path.exists():
            overrides = json.loads(await asyncio.to_thread(override_path.read_bytes))
            if not isinstance(overrides, dict):
                raise ValueError('legacy session overrides invalid')
        self.session_data = loaded
        self.session_override_manager = SessionOverrideManager(self.data_dir)
        self._prepared_sha = hashlib.sha256(raw).hexdigest()
        self._phase = 'prepared'
        return self.status()

    async def activate(self):
        if self.active:
            return self.status()
        if not self._physical() or self._running:
            raise RuntimeError('old executor must be stopped and drained before activation')
        await self.prepare()
        blockers = self.migration_blockers()
        if blockers:
            self._phase = 'blocked_configuration'
            raise RuntimeError('enabled legacy features cannot yet use the unified lane')
        delivery = getattr(self.runtime, 'delivery', None)
        if delivery is None or getattr(delivery, 'active', False) is not True:
            raise RuntimeError('existing unified delivery lane unavailable')
        try:
            zone = self.context.get_config().get('timezone')
            self.timezone = ZoneInfo(zone) if zone else None
        except (ValueError, TypeError, KeyError):
            self.timezone = None
        self.scheduler = _DateJobs(self)
        self.plugin_start_time = self.clock()
        self.active, self._phase = True, 'native'
        self.scheduler.start()
        # Preserve original identity and due timestamp. In particular do not
        # call legacy _init_jobs_from_data, which clears overdue old state.
        self._overdue = []
        for session, info in self.session_data.items():
            due = info.get('next_trigger_time')
            cfg = self._get_session_config(session)
            if not cfg or not cfg.get('enable', False) or not isinstance(due, (int, float)):
                continue
            if due + 60 < self.clock():
                self._overdue.append(session)
                continue
            self.scheduler.add_job(self.check_and_chat, 'date', run_date=datetime.fromtimestamp(due, self.timezone),
                args=[session], id=session, replace_existing=True)
        await self._setup_auto_triggers_for_enabled_sessions()
        return self.status()

    def _allowed(self, scope):
        try:
            frame = self._frames.get(scope['session_id'])
            return (self.active and self._physical() and self.authorize(private_scope(scope)) is True
                and self._scope(scope['session_id']) == scope and not self.migration_blockers()
                and self._linked_source_reason(scope, frame.get('linked_source') if frame else None) is None
                and getattr(getattr(self.runtime, 'delivery', None), 'active', False) is True)
        except Exception:
            return False

    def _track_task(self, task):
        if task is not None:
            self._running.add(task)
            task.add_done_callback(self._running.discard)
        return task

    async def tick(self):
        if not self.active or not self._physical() or not self.scheduler.running:
            return
        await self._resume_linked_app_source()
        now = self.clock()
        for job in list(self.scheduler.get_jobs()):
            if job.next_run_time.timestamp() > now or len(self._running) >= 8:
                continue
            try:
                session = job.args[0]
                scope = self._scope(session)
                if not self._allowed(scope) or not self._outbound_scope_ready(scope):
                    self._waiting_scopes[session] = self._linked_source_reason(scope) or (
                        'native_pc_scope_not_current' if not self._outbound_scope_ready(scope) else 'waiting_for_real_scope')
                    continue
            except (PermissionError, ValueError, TypeError, IndexError):
                if job.args:
                    self._waiting_scopes[job.args[0]] = 'waiting_for_real_scope'
                continue
            self._waiting_scopes.pop(session, None)
            self.scheduler.remove_job(job.id)
            self._track_task(asyncio.create_task(self._run_date_job(job)))

    async def _run_date_job(self, job):
        try:
            result = await job.func(*job.args)
            if isinstance(result, dict) and result.get('state') == 'waiting_for_real_scope':
                self._retain_date_job(job)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._last_error = type(exc).__name__

    def _retain_date_job(self, job):
        if job.args:
            self._waiting_scopes[job.args[0]] = 'waiting_for_real_scope'
        # A genuine new input may already have installed its own new date.
        # Keep that legitimate policy result rather than overwriting it.
        if self.active and self.scheduler.get_job(job.id) is None:
            self.scheduler.add_job(job.func, 'date', run_date=job.next_run_time,
                args=job.args, id=job.id)

    async def _save_data_internal(self):
        # Keep original filename, exact fields and unrelated entries. Reuse the
        # existing TLS atomic-file primitive instead of truncating live JSON.
        await asyncio.to_thread(_atomic_json, str(self.session_data_file), deepcopy(self.session_data))

    async def _put(self, key, scope, data):
        previous = await asyncio.to_thread(self.journal.fetch, NAMESPACE, key, scope)
        return await asyncio.to_thread(self.journal.put, NAMESPACE, key, scope, data,
            expected_revision=previous['revision'] if previous else 0)

    def _occurrence(self, session, info, request_id=None):
        value = ['manual', request_id] if request_id is not None else ['schedule',
            info.get('next_trigger_time'), info.get('last_scheduled_at')]
        return hashlib.sha256(canonical([SOURCE_ID, session, value]).encode()).hexdigest()

    def _admission_result(self, session, request_id, **values):
        result = dict(session_id=session, request_id=request_id, checked_at=self.clock(),
            reservation=False, model_stage_entered=False, queue_submission_attempted=False,
            queue_submission_returned=False, confirmed=False)
        result.update(values)
        return result

    def _remember_admission(self, session, result):
        records = getattr(self, '_last_admission', None)
        if records is None:
            records = self._last_admission = {}
        if session not in records and len(records) >= 128:
            records.pop(next(iter(records)))
        records[session] = deepcopy(result)
        return result

    async def _admission_check(self, session, request_id, owned_frame=None):
        if request_id is not None and (not isinstance(request_id, str)
                or re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', request_id) is None):
            raise ValueError('stable request id required')
        frame = self._frames.get(session)
        if frame is not None and frame is not owned_frame:
            return self._admission_result(session, request_id, allowed=False,
                state='in_progress', reason='session_occurrence_in_progress'), None, None
        try:
            scope = self._scope(session)
        except (PermissionError, ValueError, TypeError):
            return self._admission_result(session, request_id, allowed=False,
                state='waiting_for_real_scope', reason='actual_scope_lookup_failed'), None, None
        if not self._allowed(scope) or not self._outbound_scope_ready(scope):
            reason = self._linked_source_reason(scope) or ('native_pc_scope_not_current'
                if not self._outbound_scope_ready(scope) else 'current_authority_unavailable')
            return self._admission_result(session, request_id, allowed=False,
                state='waiting_for_real_scope', reason=reason), scope, None
        occurrence = self._occurrence(session, self.session_data.get(session, {}), request_id)
        key = 'occurrence:' + occurrence
        previous = await asyncio.to_thread(self.journal.fetch, NAMESPACE, key, scope)
        if previous is not None:
            return self._admission_result(session, request_id, allowed=False,
                state='existing_occurrence', reason='occurrence_replay_suppressed', occurrence=occurrence,
                recorded_phase=previous['data'].get('phase', 'unknown')), scope, key
        preview = await self.runtime.delivery.preflight(scope, SOURCE_ID + ':' + occurrence + ':0')
        if not self._allowed(scope) or not self._outbound_scope_ready(scope):
            return self._admission_result(session, request_id, allowed=False,
                state='waiting_for_real_scope', reason='authority_changed_after_preflight', occurrence=occurrence), scope, key
        return self._admission_result(session, request_id, allowed=preview.get('allowed') is True,
            state='ready' if preview.get('allowed') is True else 'preflight_denied',
            reason=str(preview.get('reason') or 'preflight_reason_unavailable'), occurrence=occurrence,
            preflight=deepcopy(preview)), scope, key

    async def preview_admission(self, session_id, request_id):
        """Current read-only gate, not the reason for a past request or a permit."""
        session = self._normalize_session_id(session_id)
        try:
            self._scope(session)  # Dashboard authority does not supply a runtime lease.
        except (ValueError, TypeError):
            raise PermissionError('a real current private scope is required') from None
        result, _, _ = await self._admission_check(session, request_id)
        result.update(read_only=True, source='current_preflight_read', historical_attempt_reason_proven=False)
        return self._remember_admission(session, result)

    async def check_and_chat(self, session_id, *, request_id=None):
        session = self._normalize_session_id(session_id)
        if session in self._frames:
            return self._remember_admission(session, self._admission_result(session, request_id,
                allowed=False, state='in_progress', reason='session_occurrence_in_progress', source='trigger_attempt'))
        # A RAM slot and task ownership precede every await, including preflight.
        frame = dict(session_id=session, phase='admitting')
        current_task = asyncio.current_task()
        self._frames[session] = frame
        self._running.add(current_task)
        try:
            return await self._check_and_chat_owned(session, request_id, frame)
        except BaseException as exc:
            self._remember_admission(session, self._admission_result(session, request_id,
                allowed=frame.get('phase') != 'admitting', state='unknown' if frame.get('model_stage_entered')
                or frame.get('queue_submission_attempted') else 'admission_interrupted',
                reason='admission_' + type(exc).__name__, source='trigger_attempt', read_only=False,
                model_stage_entered=frame.get('model_stage_entered', False),
                queue_submission_attempted=frame.get('queue_submission_attempted', False),
                queue_submission_returned=frame.get('queue_submission_returned', False),
                task_ids=list(frame.get('task_ids', []))))
            raise
        finally:
            if self._frames.get(session) is frame:
                self._frames.pop(session, None)
            self._running.discard(current_task)

    async def _check_and_chat_owned(self, session, request_id, frame):
        result, scope, key = await self._admission_check(session, request_id, frame)
        result.update(read_only=False, source='trigger_attempt')
        if result['state'] == 'existing_occurrence':
            self._unknown[session] = result['recorded_phase']
            return self._remember_admission(session, result)
        if result['allowed'] is not True:
            self._remember_admission(session, result)
            if result['state'] != 'preflight_denied':
                return result
            preview = result['preflight']
            # Admission does not rewrite the original persisted due date or
            # choose another random legacy interval.
            retry = max(self.clock() + 60, preview.get('profile', {}).get('retry_at', 0))
            self.scheduler.add_job(self.check_and_chat, 'date', run_date=datetime.fromtimestamp(retry, self.timezone),
                args=[session], id=session, replace_existing=True)
            return result
        occurrence = result['occurrence']
        frame.update(scope=scope, occurrence=occurrence,
            event_id=SOURCE_ID + ':' + occurrence, phase='running', part=0, task_ids=[])
        if self._source_record(session) is not None:
            frame['linked_source'] = deepcopy(self._source_record(session))
        self._counts['started'] += 1
        await self._put(key, scope, frame)
        try:
            await ProactiveCoreMixin.check_and_chat(self, session)
            frame['phase'] = 'completed'
        except _DeliveryStopped as exc:
            frame.update(phase=exc.state, reason=exc.reason)
            if exc.state == 'unknown':
                self._unknown[session] = exc.reason
                self._counts['unknown'] += 1
        except asyncio.CancelledError:
            frame.update(phase='unknown', reason='operation_cancelled_after_admission')
            self._unknown[session] = frame['reason']
            raise
        except BaseException:
            frame.update(phase='unknown', reason='operation_outcome_unknown')
            self._unknown[session] = frame['reason']
            raise
        finally:
            await asyncio.shield(self._put(key, scope, frame))
        result.update(state='confirmed' if frame.get('delivery_state') == 'confirmed'
            else frame['phase'] if frame['phase'] in {'unknown', 'blocked'} else 'no_delivery_confirmation',
            reason=frame.get('reason') or ('sdk_confirmed' if frame.get('delivery_state') == 'confirmed'
                else 'core_returned_without_delivery_confirmation'),
            model_stage_entered=frame.get('model_stage_entered', False),
            queue_submission_attempted=frame.get('queue_submission_attempted', False),
            queue_submission_returned=frame.get('queue_submission_returned', False),
            confirmed=frame.get('delivery_state') == 'confirmed', task_ids=list(frame['task_ids']))
        return self._remember_admission(session, result)

    async def _prepare_llm_request(self, session_id):
        frame = self._frames.get(session_id)
        if frame is None or not self._allowed(frame['scope']):
            raise _DeliveryStopped('blocked', 'scope_closed_before_context')
        if frame.get('linked_source') is not None:
            current = await self._app_selection(frame['linked_source'])
            if current is None:
                raise _DeliveryStopped('blocked', 'app_session_or_persona_changed')
            database, persona = current
            source = frame['linked_source']; settings = self._get_context_settings(session_id)
            count = min(max(int(settings.get('platform_history_count', 20)), 1), 200)
            records = await database.get_platform_message_history(platform_id='webchat',
                user_id=source['app_session_id'], page_size=count)
            history = []
            for record in reversed(list(records or [])):
                if (getattr(record, 'platform_id', None) != 'webchat'
                        or getattr(record, 'user_id', None) != source['app_session_id']):
                    raise _DeliveryStopped('blocked', 'app_history_owner_changed')
                content = getattr(record, 'content', None)
                if not isinstance(content, dict): continue
                text = self._extract_platform_message_text(content)
                if text:
                    history.append(dict(role='assistant' if content.get('type') == 'bot' else 'user', content=text[:20000]))
            if not self._allowed(frame['scope']):
                raise _DeliveryStopped('blocked', 'app_context_authority_changed')
            return dict(conv_id=None, history=history, system_prompt=persona['prompt'], session_id=session_id)
        return await LlmMixin._prepare_llm_request(self, session_id)

    async def _app_selection(self, source):
        """A fresh owner/config/SDK check; saved persona labels cannot grant it."""
        from astrbot.core import db_helper, sp
        from astrbot.dashboard.services.chat_service import build_webchat_unified_msg_origin
        try:
            if self._linked_source_reason(source['scope'], source) is not None: return None
            session = await db_helper.get_platform_session_by_id(source['app_session_id'])
            if (session is None or session.creator != source['username'] or session.is_group != 0
                    or session.platform_id != 'webchat' or session.session_id != source['app_session_id']
                    or build_webchat_unified_msg_origin(session) != source['scope']['session_id']):
                return None
            settings = await sp.get_async(scope='umo', scope_id=source['scope']['session_id'],
                key='session_service_config', default={})
            if not isinstance(settings, dict) or settings.get('persona_id') == '[%None]': return None
            selected, persona, *_ = await self.context.persona_manager.resolve_selected_persona(
                umo=source['scope']['session_id'], conversation_persona_id=settings.get('persona_id') or None,
                platform_name='webchat', provider_settings=self.context.get_config(
                    umo=source['scope']['session_id']).get('provider_settings', {}))
            if (selected != source['persona_id'] or not isinstance(persona, dict) or persona.get('name') != selected
                    or not isinstance(persona.get('prompt'), str) or not persona['prompt'].strip()
                    or len(persona['prompt']) > 32000 or self._linked_source_reason(source['scope'], source) is not None):
                return None
            return db_helper, persona
        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            return None

    async def _generate_llm_response(self, session_id, *args, **kwargs):
        frame = self._frames.get(session_id)
        if frame is None or not self._allowed(frame['scope']):
            raise _DeliveryStopped('blocked', 'scope_closed_before_model')
        if frame.get('linked_source') is not None and await self._app_selection(frame['linked_source']) is None:
            raise _DeliveryStopped('blocked', 'app_persona_changed_before_model')
        self._counts['model_requests'] += 1
        frame['model_stage_entered'] = True
        result = await LlmMixin._generate_llm_response(self, session_id, *args, **kwargs)
        if not self._allowed(frame['scope']):
            raise _DeliveryStopped('blocked', 'scope_closed_after_model')
        return result

    async def _send_proactive_message(self, session_id, text):
        frame = self._frames.get(session_id)
        if frame is None or not self._allowed(frame['scope']):
            raise _DeliveryStopped('blocked', 'send_authority_closed')
        text = await self._transform_outbound(frame, text)
        if not isinstance(text, str) or not text.strip():
            raise _DeliveryStopped('blocked', 'empty_after_native_outbound_cleaning')
        # Segmentation/TTS decorators cannot bypass the shared daily quota or
        # create uncorrelated part sends. One old occurrence is one queue task.
        images = []
        text_only = (frame.get('linked_source') or {}).get('destination') == 'chat_text'
        if self.image_for_text is not None and not text_only:
            result = self.image_for_text(frame['scope'], text)
            result = await result if inspect.isawaitable(result) else result
            if result:
                if not isinstance(result, str):
                    raise _DeliveryStopped('blocked', 'owned_image_reference_invalid')
                images = [result]
        audio, audio_text = None, True
        cfg = self._get_session_config(session_id)
        tts = cfg.get('tts_settings', {}) if cfg else {}
        if tts.get('enable_tts', True) and not text_only:
            if not self._audio_supported():
                raise _DeliveryStopped('blocked', 'unified_audio_adapter_unavailable')
            try:
                provider = self.context.get_using_tts_provider(umo=session_id)
                if provider is not None:
                    if not self._allowed(frame['scope']):
                        raise _DeliveryStopped('blocked', 'scope_closed_before_tts')
                    self._counts['tts_requests'] += 1
                    output = await provider.get_audio(text)
                    if not self._allowed(frame['scope']):
                        raise _DeliveryStopped('blocked', 'scope_closed_after_tts')
                    if output:
                        adapter = self.runtime.delivery.sender.adapter
                        audio = await asyncio.to_thread(_copy_owned_speech, output, adapter.media_root)
                        audio_text = tts.get('always_send_text', True)
                        if type(audio_text) is not bool:
                            raise ValueError('explicit TTS text preference required')
                        self._counts['tts_audio_prepared'] += 1
                        self._tts_last_reason = 'owned_audio_prepared'
                if audio is None:
                    self._counts['tts_text_fallbacks'] += 1
                    self._tts_last_reason = 'tts_provider_or_audio_unavailable_text_fallback'
            except Exception as exc:
                # Original SenderMixin already falls back to text when TTS
                # provider preparation fails. No message has been submitted.
                self._counts['tts_text_fallbacks'] += 1
                self._tts_last_reason = 'tts_preparation_failed:' + type(exc).__name__
                audio, audio_text = None, True
        try:
            await self._submit_confirmed(frame, text, images, audio=audio, audio_text=audio_text)
        except _DeliveryStopped:
            raise
        except BaseException:
            # Even a failure to persist the receipt after a successful queue
            # call must not enter the old exception/reschedule compensation.
            raise _DeliveryStopped('unknown', 'delivery_or_receipt_outcome_unknown')

    async def _send_chain_with_hooks(self, session_id, components):
        raise _DeliveryStopped('blocked', 'legacy_platform_and_pseudo_event_senders_disabled')

    async def _submit_confirmed(self, frame, text, images, *, audio=None, audio_text=True):
        scope, event = frame['scope'], frame['event_id'] + ':0'
        identity = make_task(scope, event, text=text, images=images, now=self.clock(), audio=audio, audio_text=audio_text)['id']
        source = dict(source_id=SOURCE_ID, task_id=identity, scope=scope, event_id=event,
            occurrence=frame['occurrence'], session_id=frame['session_id'], phase='prepared',
            content_sha256=_content_sha(text, images, audio, audio_text))
        if frame.get('linked_source') is not None:
            source['linked_source'] = deepcopy(frame['linked_source'])
        if audio is not None:
            source.update(audio=audio, audio_text=audio_text)
        if not self._allowed(scope):
            raise _DeliveryStopped('blocked', 'send_authority_closed')
        if frame.get('linked_source') is not None and await self._app_selection(frame['linked_source']) is None:
            raise _DeliveryStopped('blocked', 'app_persona_changed_before_submission')
        await self._put('task:' + identity, scope, source)
        frame['task_ids'].append(identity)
        source['phase'] = 'submitting'
        await self._put('task:' + identity, scope, source)
        try:
            frame['queue_submission_attempted'] = True
            task = await self.runtime.delivery.submit(scope, event, text=text, images=images,
                priority=50, trigger='timer', max_attempts=1, audio=audio, audio_text=audio_text)
        except BaseException:
            source['phase'] = 'unknown'
            await asyncio.shield(self._put('task:' + identity, scope, source))
            raise _DeliveryStopped('unknown', 'queue_submission_ack_unknown')
        self._counts['submitted'] += 1
        frame['queue_submission_returned'] = True
        source['phase'] = task.get('state', 'unknown')
        frame['delivery_state'] = source['phase']
        await self._put('task:' + identity, scope, source)
        # The shared worker owns claims/retries/final permission/platform ACK.
        # No local resend occurs when it is queued, paused, late or unknown.
        deadline = time.monotonic() + 90
        while task.get('state') in _ACTIVE_DELIVERY and time.monotonic() < deadline:
            if not self.active:
                raise _DeliveryStopped('unknown', 'owner_stopped_with_queued_task')
            await asyncio.sleep(.5)
            task = await asyncio.to_thread(self.runtime.delivery.store.get, identity)
            if task is None:
                raise _DeliveryStopped('unknown', 'queued_task_missing')
        source['phase'] = task.get('state', 'unknown')
        frame['delivery_state'] = source['phase']
        await self._put('task:' + identity, scope, source)
        if task.get('state') != 'confirmed':
            raise _DeliveryStopped('unknown' if task.get('state') in _ACTIVE_DELIVERY | {'unknown'}
                else 'blocked', 'unified_delivery_' + str(task.get('state', 'unknown')))
        self._counts['confirmed'] += 1

    async def owns_task(self, scope, task):
        try:
            row = await asyncio.to_thread(self.journal.fetch, NAMESPACE, 'task:' + task['id'], private_scope(scope))
            value = row['data'] if row else None
            return (isinstance(value, dict) and value.get('source_id') == SOURCE_ID
                and value.get('scope') == scope and value.get('task_id') == task['id']
                and value.get('content_sha256') == _content_sha(task['text'], task['images'],
                    task.get('audio'), task.get('audio_text', True)))
        except Exception:
            return False

    async def delivery_allowed(self, scope, task):
        if not self._allowed(scope) or not await self.owns_task(scope, task): return False
        row = await asyncio.to_thread(self.journal.fetch, NAMESPACE, 'task:' + task['id'], private_scope(scope))
        expected = row['data'].get('linked_source') if row else None
        if self._source_record(scope['session_id']) is not None:
            return (expected is not None and self._linked_source_reason(scope, expected) is None
                and await self._app_selection(expected) is not None)
        return expected is None

    async def _finalize_and_reschedule(self, session_id, conv_id, user_prompt, assistant_response, unanswered_count):
        if self._source_record(session_id) is None:
            return await ProactiveCoreMixin._finalize_and_reschedule(self, session_id, conv_id,
                user_prompt, assistant_response, unanswered_count)
        # The existing ChatDeliveryAdapter already stored the exact assistant
        # message. Do not create a parallel legacy conversation for this APP.
        frame = self._frames.get(session_id)
        if frame is None or not self._allowed(frame['scope']): return
        async with self.data_lock:
            self.session_data.setdefault(session_id, {})['unanswered_count'] = unanswered_count + 1
        await self._schedule_next_chat_and_save(session_id)

    async def observe_event(self, event):
        if not self.active or not event.get_messages():
            return False
        session = self._normalize_session_id(event.unified_msg_origin)
        scope = self._scope(session)
        if scope.get('platform') == scope.get('bot_id') == 'webchat':
            # PC's SDK-verified source is authoritative; this call never turns
            # an administrator request or a saved binding into an inbound event.
            message_id = str(getattr(getattr(event, 'message_obj', None), 'message_id', '') or '')
            service = self._pc_outbound_service()
            actual = getattr(service, '_tls_source', None)
            if (getattr(event, 'private_companion_proactive_framework', False) or not message_id or message_id == '0'
                    or str(event.get_sender_id()) != scope['user_id'] or str(event.get_self_id()) != scope['bot_id']):
                self._waiting_scopes[session] = 'app_real_ingress_required'; return False
            if service is not None and service._tls_primary_scope == scope and isinstance(actual, dict) and actual.get('event_id') == message_id:
                # On the first APP ingress, the linked-memory LLM hook has not
                # run yet. Record only the exact Persona PC just revalidated.
                from .chat_identity import identity_service
                username, sid = self._app_identity(scope); links = identity_service(self.plugin)
                linked = links.get(username, sid)
                if linked: links.observe(linked, scope, actual['persona_id'])
            if await self._resume_linked_app_source():
                return self._source_record(session) is not None
        if not self._allowed(scope):
            return False
        parsed = self._parse_session_id(session)
        if not self._is_friend_type(parsed[1]):
            return False
        await EventsMixin.on_friend_message(self, event)
        self._waiting_scopes.pop(session, None)
        return True

    async def _setup_auto_trigger(self, session_id, silent=False):
        session = self._normalize_session_id(session_id)
        cfg = self._get_session_config(session)
        settings = cfg.get('auto_trigger_settings', {}) if cfg else {}
        minutes = settings.get('auto_trigger_after_minutes', 5)
        if not settings.get('enable_auto_trigger', False) or not isinstance(minutes, (int, float)) or minutes <= 0:
            return
        await self._cancel_auto_trigger(session)
        job = self.scheduler.add_job(self._handle_auto_trigger_callback, 'date',
            run_date=datetime.fromtimestamp(self.clock() + minutes * 60, self.timezone),
            args=[session, minutes], id='auto:' + session, replace_existing=True)
        self.auto_trigger_timers[session] = job

    async def _reset_group_silence_timer(self, session_id):
        # Shared delivery's current scope contract is private-only. Keep group
        # settings and source modules intact; activation reports the limitation.
        raise PermissionError('group proactive delivery requires an explicit group lane')

    async def trigger(self, session_id, request_id):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError('stable request id required')
        session = self._normalize_session_id(session_id)
        if not self._allowed(self._scope(session)):
            raise PermissionError('current real session authorization required')
        attempt = await self.check_and_chat(session, request_id=request_id)
        return dict(self.status(), attempt=attempt)

    async def update_override(self, session_id, changes):
        if not self.active or self.session_override_manager is None:
            raise RuntimeError('native proactive owner is closed')
        session = self._normalize_session_id(session_id)
        self._scope(session)
        if not isinstance(changes, dict):
            raise ValueError('session configuration patch must be an object')
        if (isinstance(changes.get('tts_settings'), dict)
                and changes['tts_settings'].get('enable_tts') is True and not self._audio_supported()
                or isinstance(changes.get('segmented_reply_settings'), dict)
                and changes['segmented_reply_settings'].get('enable') is True):
            raise ValueError('enabled TTS/segmentation requires a compatible unified lane')
        await self.session_override_manager.set_override(self.policy_session(session), changes)
        # The changed setting takes effect immediately through the original
        # effective-config resolver. Unsupported new settings close admission.
        return dict(session_id=session, config=self._get_session_config(session),
            migration_blockers=self.migration_blockers())

    async def stop(self, *, drain_timeout=30):
        self.active = False
        self.scheduler.shutdown(wait=False)
        self.group_timers.clear()
        self.auto_trigger_timers.clear()
        pending = {task for task in self._running if not task.done() and task is not asyncio.current_task()}
        if pending:
            _, pending = await asyncio.wait(pending, timeout=drain_timeout)
        self._phase = 'draining' if pending else 'closed'
        return self.status()

    async def close(self):
        result = await self.stop()
        if result['pending_operations']:
            raise RuntimeError('proactive operations still draining; keep original owner closed')
        self._closed = True

    def status(self):
        rows = []
        for session, info in sorted(self.session_data.items()):
            cfg = self._get_session_config(session)
            source = self._source_record(session)
            reason = self._waiting_scopes.get(session)
            real_scope = pc_matches = False
            try:
                scope = self._scope(session); real_scope = True
                pc_matches = self._outbound_scope_ready(scope)
                reason = self._linked_source_reason(scope) or (None if pc_matches else 'native_pc_scope_not_current')
            except (PermissionError, ValueError, TypeError, KeyError, AttributeError):
                reason = 'waiting_for_real_scope'
            if session in self._unknown: reason = 'occurrence_outcome_unknown'
            elif session in self._overdue: reason = reason or 'original_occurrence_overdue_requires_review'
            elif not cfg or cfg.get('enable') is not True: reason = 'session_policy_disabled'
            elif not reason:
                from .native_proactive_chat.utils.time_utils import is_quiet_time
                try:
                    if is_quiet_time(cfg.get('schedule_settings', {}).get('quiet_hours', '1-7'), self.timezone):
                        reason = 'quiet_hours'
                except (TypeError, ValueError): reason = 'quiet_hours_configuration_unavailable'
            rows.append(dict(session_id=session, enabled=bool(cfg and cfg.get('enable', False)),
                task_id=session, next_trigger_time=info.get('next_trigger_time'),
                last_scheduled_at=info.get('last_scheduled_at'), unanswered_count=info.get('unanswered_count', 0),
                scheduled=self.scheduler.get_job(session) is not None,
                execution_state=self._waiting_scopes.get(session, 'scheduled' if self.scheduler.get_job(session) else 'idle'),
                manual_review=session in self._unknown or session in self._overdue,
                outcome=self._unknown.get(session), blocking_reason=reason,
                source_kind='confirmed_linked_real_app' if source else 'original_configured_session',
                policy_session_id=self.policy_session(session), real_scope_available=real_scope,
                pc_scope_matches=pc_matches, destination=source.get('destination') if source else 'configured_delivery',
                old_occurrence_adopted=False))
            rows[-1]['last_admission'] = deepcopy(getattr(self, '_last_admission', {}).get(session))
        return dict(ok=True, protocol=self.protocol, active=self.active, phase=self._phase,
            prepared=hasattr(self, '_prepared_sha'),
            pending_operations=sum(not task.done() for task in self._running), sessions=rows,
            migration_blockers=self.migration_blockers(), counts=dict(self._counts),
            decorating_handlers=self._decorators(),
            expression_image_callback_available=self.image_for_text is not None,
            expression_decorator_event_executed=False,
            linked_app_discovery_reason=getattr(self,'_linked_source_discovery_reason',None),
            last_error=self._last_error, legacy_task_ids_preserved=True,
            original_state_file='session_data.json', original_overrides_file=SessionOverrideManager.OVERRIDES_FILE,
            sender='existing_tls_delivery_lane', telemetry=False, standalone_server=False,
            tts_supported=self._audio_supported(), tts_last_reason=self._tts_last_reason,
            arbitrary_decorators_supported=False,
            outbound_transform=dict(self._outbound_hooks),
            segmented_platform_sends=False, platform_receipt_required='confirmed')
