"""Bounded observation of the already loaded PC owner, never a business call.

The production getter returns ``_private_companion_plugin.extension_api`` and
that API stores its owner as ``_plugin``. Inspect those exact backreferences and
the SDK registry without importing PC or invoking any of its methods.
"""
from __future__ import annotations

import asyncio
import inspect
import math
from pathlib import Path
import sys
from types import ModuleType

from .models import private_scope

ROOT = 'astrbot_plugin_private_companion'
MAX_STARS = 256
MAX_TASKS = 512
MAX_DEPTH = 32
MAX_LABELS = 64
RANDOM_MARKER = 'tls.native.random.owner.v1'
RANDOM_CONFIG_KEY = 'tls_native_random_sessions'
_MISSING = object()
_FILES = {'main.py', 'proactive.py', 'daily_state.py', 'companion_image.py',
          'companion_delivery.py', 'proactive_photo.py', 'proactive_chat_runtime_bridge.py'}
_KINDS = {
    '_scheduler_loop': 'scheduler', '_tick': 'tick', '_tick_inner': 'tick', '_kick_proactive_loop_once': 'tick',
    '_render_message': 'llm', '_generate_proactive_message_with_llm': 'llm',
    '_generate_proactive_message_via_framework': 'llm', '_generate_proactive_message_direct_fallback': 'llm',
    '_run_framework_agent_text': 'llm', '_llm_call': 'llm', '_review_planned_proactive_with_model': 'llm',
    '_review_proactive_message_send_decision': 'llm', '_prepare_companion_image': 'image',
    '_prepare_companion_image_unlocked': 'image', '_generate_photo_image': 'image',
    '_run_external_photo_generation': 'image', '_send_companion_image_message': 'image',
    '_send_proactive_message_chain': 'send', '_send_chain_components': 'send',
    '_send_companion_chain_atomic': 'send', '_send_chain_components_via_onebot_direct': 'send',
    '_send_media_proactive_chain': 'send', '_wrapped_send': 'send',
}
_SDK_SENSITIVE = {'text_chat', 'text_chat_stream', 'send_message', 'send_by_session',
                  '_run_external_photo_generation', '_generate_photo_image'}


def _attrs(value):
    try: result = vars(value)
    except TypeError: return {}
    return result if isinstance(result, dict) else {}


def _config_root(config):
    if isinstance(config, dict): return config
    values = [_attrs(config).get(key) for key in ('data', 'config')]
    roots = [value for value in values if isinstance(value, dict)]
    if not roots or any(value is not roots[0] for value in roots): return None
    return roots[0]


def _config_value(config, key, group, *, default=_MISSING):
    """Audited schema-group precedence without old getters or arbitrary aliases.

    A hidden flat compatibility default may differ from the authoritative group.
    Other nested occurrences must agree; ambiguous/oversized trees deny.
    """
    root = _config_root(config)
    if root is None: return _MISSING
    known = dict.get(root, group, _MISSING)
    if known is not _MISSING and not isinstance(known, dict): return _MISSING
    selected = dict.get(known, key, _MISSING) if isinstance(known, dict) else _MISSING
    nested = []; seen = set(); stack = [(root, 0)]
    try:
        while stack:
            node, depth = stack.pop()
            if depth > 8 or len(seen) >= 1024 or id(node) in seen: return _MISSING
            seen.add(id(node))
            if node is not root and dict.__contains__(node, key): nested.append(dict.get(node, key))
            stack.extend((value, depth + 1) for value in dict.values(node) if isinstance(value, dict))
        if selected is not _MISSING:
            if any(type(value) is not type(selected) or value != selected for value in nested): return _MISSING
            return selected
        if nested: return _MISSING
        return dict.get(root, key, default)
    except (RuntimeError, TypeError, ValueError): return _MISSING


def _normalized_daily_limit(config):
    value = _config_value(config, 'max_daily_messages', 'proactive_reach_config', default=8)
    if type(value) not in (int, float, str): return None
    if isinstance(value, str) and (len(value) > 32 or not value.strip()): return None
    if isinstance(value, float) and not math.isfinite(value): return None
    try: return max(0, min(12, int(value)))  # Actual main._cfg_int(..., 8, 0, 12).
    except (TypeError, ValueError, OverflowError): return None


def _unknown(reason, *, loaded=None):
    return dict(schema='tls.legacy.companion.inspection.v1', state='unknown', reason=reason, loaded=loaded,
        read_only=True, business_calls=0, imports=0, model_calls=0, sends=0,
        observation_scope='current_python_event_loop_only', task_inspection_available=False,
        handoff=dict(state='unknown', absolute_no_inflight_guarantee=False,
                     sdk_dispatch_acknowledgement_proven=False, ordinary_chat_rp_execution_verified=False))


def native_pc_successor(context):
    """Actual TLS full owner only after the registered old PC is inactive.

    This exposes no identity and never pretends that the native service is an
    active old Star. Original proof branches remain unchanged while PC is live.
    """
    try:
        rows = _registry(context)
        old = [row for row in rows if _attrs(row).get('root_dir_name') == ROOT]
        tls = [row for row in rows if _attrs(row).get('root_dir_name') == 'astrbot_plugin_virtual_body']
        if (len(old) != 1 or _attrs(old[0]).get('activated') is not False
                or len(tls) != 1 or _attrs(tls[0]).get('activated') is not True): return None
        plugin = _attrs(tls[0]).get('star_cls')
        integrations = _attrs(plugin).get('_native_server_integrations')
        owner = getattr(integrations, 'pc_full', None)
        service = getattr(owner, 'service', None)
        if (getattr(plugin, 'context', None) is not context or getattr(integrations, 'context', None) is not context
                or getattr(integrations, 'plugin', None) is not plugin or getattr(integrations, '_closed', True)
                or getattr(owner, 'context', None) is not context or getattr(owner, 'active', False) is not True
                or getattr(service, 'context', None) is not context or getattr(service, 'active', False) is not True
                or not callable(getattr(owner, 'legacy_closed', None)) or owner.legacy_closed() is not True
                or not callable(getattr(service, 'native_source_current', None)) or service.native_source_current() is not True): return None
        return owner, service
    except Exception: return None


def _registry(context):
    getter = getattr(context, 'get_all_stars', None) if context is not None else None
    if callable(getter): rows = getter()
    else:
        module = sys.modules.get('astrbot.core.star.star')
        rows = _attrs(module).get('star_registry')
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_STARS:
        raise ValueError('registry unavailable or capacity')
    return list(rows)


def _same_owner(context, metadata, instance, module_data, api):
    try:
        rows = [row for row in _registry(context) if _attrs(row).get('root_dir_name') == ROOT]
        return (len(rows) == 1 and rows[0] is metadata and _attrs(rows[0]).get('activated') is True
            and _attrs(rows[0]).get('star_cls') is instance
            and module_data.get('_private_companion_plugin') is instance and _attrs(api).get('_plugin') is instance)
    except Exception: return False


def _code_label(code, root):
    if code is None: return None, None
    filename = str(code.co_filename).replace('\\', '/')
    prefix = root.replace('\\', '/').rstrip('/') + '/'
    if filename.startswith(prefix):
        relative = filename[len(prefix):]
        source = 'pc/' + relative if relative in _FILES else 'pc/other.py'
        return source, _KINDS.get(code.co_name, 'other')
    if ('/astrbot/' in filename and code.co_name in _SDK_SENSITIVE):
        return 'sdk/sensitive-await', 'unattributed'
    return None, None


def _task_observation(task, root):
    labels = []; kinds = set(); seen = set(); truncated = False
    try:
        current = task.get_coro()
        for _ in range(MAX_DEPTH):
            if current is None: break
            if id(current) in seen: truncated = True; break
            seen.add(id(current))
            if inspect.iscoroutine(current): code, frame, following = current.cr_code, current.cr_frame, current.cr_await
            elif inspect.isasyncgen(current): code, frame, following = current.ag_code, current.ag_frame, current.ag_await
            elif inspect.isgenerator(current): code, frame, following = current.gi_code, current.gi_frame, current.gi_yieldfrom
            else: break  # Future/thread waits have no inspectable coroutine body.
            source, kind = _code_label(code, root)
            if source:
                labels.append(dict(source=source, kind=kind, line=frame.f_lineno if frame is not None else code.co_firstlineno))
                kinds.add(kind)
            current = following
        else: truncated = current is not None
        for frame in task.get_stack(limit=8):
            source, kind = _code_label(frame.f_code, root)
            if source:
                label = dict(source=source, kind=kind, line=frame.f_lineno)
                if label not in labels: labels.append(label)
                kinds.add(kind)
        return labels, kinds, truncated, False
    except Exception:
        return [], set(), False, True


def inspect_legacy_companion(context=None, *, inspect_tasks=True):
    """Return only fixed labels, booleans and counts; no task names or locals.

    ``quiescent_observed`` is one current-loop observation, not cancellation or
    proof that an SDK dispatch, worker thread or another event loop is absent.
    """
    try: matches = [row for row in _registry(context) if _attrs(row).get('root_dir_name') == ROOT]
    except Exception: return _unknown('registry_unavailable')
    if not matches:
        result = _unknown('not_registered', loaded=False); result['state'] = 'not_loaded'; return result
    if len(matches) != 1: return _unknown('ambiguous_registered_owner')
    metadata = matches[0]; meta = _attrs(metadata)
    if meta.get('activated') is not True:
        result = _unknown('plugin_not_active', loaded=False); result['state'] = 'not_loaded'; return result
    instance = meta.get('star_cls'); module = meta.get('module')
    if not isinstance(module, ModuleType): module = sys.modules.get(meta.get('module_path'))
    data = _attrs(instance); module_data = _attrs(module)
    file = module_data.get('__file__')
    if instance is None or not isinstance(file, str): return _unknown('loaded_owner_unavailable')
    root = str(Path(file).parent)
    if Path(file).name != 'main.py' or Path(root).name != ROOT:
        return _unknown('exact_plugin_module_unavailable')
    api = data.get('extension_api')
    if (module_data.get('_private_companion_plugin') is not instance
            or _attrs(api).get('_plugin') is not instance
            or not inspect.isfunction(module_data.get('get_private_companion_api'))):
        return _unknown('api_owner_backreference_unconfirmed')
    runtime_limit = data.get('max_daily_messages')
    runtime_limit = runtime_limit if type(runtime_limit) is int and 0 <= runtime_limit <= 60 else None
    config = data.get('config')
    config_limit = _normalized_daily_limit(config)
    config_agrees = config_limit is not None and runtime_limit is not None and config_limit == runtime_limit
    disabled = runtime_limit == 0 and config_agrees
    root_data = data.get('data'); root_data = root_data if isinstance(root_data, dict) else {}
    runtime = root_data.get('proactive_runtime'); runtime = runtime if isinstance(runtime, dict) else {}
    visited = runtime.get('generation_disabled') is True and runtime.get('generation_disabled_reason') == 'max_daily_messages=0'
    tick = data.get('_tick_in_flight'); tick = tick if type(tick) is bool else None
    runtime_info = dict(enabled=data.get('enabled') if type(data.get('enabled')) is bool else None,
        max_daily_messages=runtime_limit, live_config_agrees=config_agrees,
        ordinary_generation_disabled=disabled, zero_gate_visited=visited, tick_in_flight=tick)
    if inspect_tasks is False:
        if not _same_owner(context, metadata, instance, module_data, api): return _unknown('owner_changed_during_observation')
        result = _unknown('task_inspection_not_requested', loaded=True)
        result.update(state='observed', runtime=runtime_info, api_owner_backreference_confirmed=True, pc_getter_invoked=False)
        return result
    scheduler = data.get('_task')
    scheduler_info = dict(present=isinstance(scheduler, asyncio.Task), done=None, cancelled=None, current_loop=None)
    if isinstance(scheduler, asyncio.Task):
        scheduler_info.update(done=scheduler.done(), cancelled=scheduler.cancelled())
    bridge = _attrs(data.get('_proactive_chat_runtime_bridge'))
    attempts = bridge.get('_open_attempts')
    attempt_count = len(attempts) if isinstance(attempts, dict) and len(attempts) <= 256 else None
    bridge_unknown = (sum(isinstance(row, dict) and (row.get('delivery_unknown') is True or row.get('phase') == 'delivery_unknown')
        for row in attempts.values()) if attempt_count is not None else None)
    users = root_data.get('users')
    user_count = len(users) if isinstance(users, dict) and len(users) <= 1024 else None
    sending_flags = (sum(isinstance(row, dict) and row.get('proactive_sending') is True for row in users.values())
                     if user_count is not None else None)
    try:
        loop = asyncio.get_running_loop(); tasks = asyncio.all_tasks(loop)
    except RuntimeError:
        result = _unknown('event_loop_not_observable', loaded=True)
        result['runtime'] = runtime_info
        result['scheduler'] = scheduler_info
        return result
    if len(tasks) > MAX_TASKS: return _unknown('task_scan_capacity', loaded=True)
    scheduler_known = False
    if isinstance(scheduler, asyncio.Task):
        scheduler_info['current_loop'] = scheduler.get_loop() is loop
        if scheduler.done(): scheduler_known = True
        elif scheduler_info['current_loop']:
            _labels, scheduler_kinds, truncated, failed = _task_observation(scheduler, root)
            scheduler_known = 'scheduler' in scheduler_kinds and not truncated and not failed
    counts = dict(owned_tasks=0, tick_tasks=0, llm_tasks=0, image_tasks=0, send_tasks=0,
        unattributed_sensitive_tasks=0, uninspectable_tasks=0, truncated_await_chains=0,
        open_bridge_attempts=attempt_count, bridge_unknown_attempts=bridge_unknown, proactive_sending_flags=sending_flags)
    labels = []; own_current = asyncio.current_task(loop)
    for task in tasks:
        if task is own_current: continue
        observed, kinds, truncated, failed = _task_observation(task, root)
        owned = any(row['source'].startswith('pc/') for row in observed)
        counts['uninspectable_tasks'] += failed; counts['truncated_await_chains'] += truncated
        if owned:
            counts['owned_tasks'] += 1
            for kind in ('tick', 'llm', 'image', 'send'): counts[kind + '_tasks'] += kind in kinds
        elif 'unattributed' in kinds: counts['unattributed_sensitive_tasks'] += 1
        for label in observed:
            if label not in labels and len(labels) < MAX_LABELS: labels.append(label)
    if not _same_owner(context, metadata, instance, module_data, api):
        return _unknown('owner_changed_during_observation')
    unknown = (not scheduler_known or data.get('enabled') is not True or tick is None or attempt_count is None or sending_flags is None
        or counts['uninspectable_tasks'] or counts['truncated_await_chains'] or counts['unattributed_sensitive_tasks'])
    busy = tick is True or any(counts[key] for key in ('tick_tasks', 'llm_tasks', 'image_tasks', 'send_tasks'))
    busy = busy or bool(attempt_count) or bool(sending_flags)
    handoff = 'busy' if busy else 'unknown' if unknown else 'not_disabled' if not disabled else 'quiescent_observed'
    return dict(schema='tls.legacy.companion.inspection.v1', state='observed', loaded=True,
        read_only=True, business_calls=0, imports=0, model_calls=0, sends=0,
        observation_scope='current_python_event_loop_only', task_inspection_available=True,
        api_owner_backreference_confirmed=True, pc_getter_invoked=False, runtime=runtime_info,
        scheduler=scheduler_info, counts=counts, task_sources=labels,
        handoff=dict(state=handoff, no_visible_old_work=False if busy else None if unknown else True,
            passive_plugin_still_loaded=True, ordinary_chat_rp_execution_verified=False,
            threadpool_and_other_event_loops_observed=False, sdk_dispatch_acknowledgement_proven=False,
            absolute_no_inflight_guarantee=False))


def runtime_disabled(context=None):
    """Pure synchronous owner/zero-limit observation, safe in journal workers.

    ``None`` means unknown and must deny new native work. This does not claim
    that any old asynchronous work has quiesced.
    """
    if native_pc_successor(context) is not None: return True
    result = inspect_legacy_companion(context, inspect_tasks=False)
    if result.get('loaded') is not True or result.get('state') != 'observed': return None
    runtime = result.get('runtime', {})
    if runtime.get('enabled') is not True or runtime.get('max_daily_messages') is None: return None
    if runtime.get('live_config_agrees') is not True: return None
    return runtime.get('ordinary_generation_disabled') is True


def current_legacy_persona(context=None):
    """Internal RAM-only exact override, never include its value in safe output.

    None means unknown/reloading/drift; empty string means the loaded instance
    and live configuration both have no plugin-specific persona override.
    """
    successor = native_pc_successor(context)
    if successor is not None:
        data = _attrs(successor[1]); value = data.get('plugin_specific_persona_id')
        configured = _config_value(data.get('config'), 'plugin_specific_persona_id', 'basic_config', default='')
        if (type(value) is str and type(configured) is str and value == configured.strip()
                and len(value) <= 256 and not any(ord(c) < 32 for c in value)): return value
        return None
    result = inspect_legacy_companion(context, inspect_tasks=False)
    if result.get('loaded') is not True or result.get('state') != 'observed': return None
    try:
        rows = [row for row in _registry(context) if _attrs(row).get('root_dir_name') == ROOT]
        if len(rows) != 1: return None
        meta = _attrs(rows[0]); instance = meta.get('star_cls'); data = _attrs(instance)
        module = meta.get('module')
        if not isinstance(module, ModuleType): module = sys.modules.get(meta.get('module_path'))
        runtime_value = data.get('plugin_specific_persona_id'); config = data.get('config')
        configured = _config_value(config, 'plugin_specific_persona_id', 'basic_config', default='')
        if (not isinstance(runtime_value, str) or not isinstance(configured, str)
                or runtime_value != configured.strip() or len(runtime_value) > 256
                or any(ord(char) < 32 for char in runtime_value)): return None
        if not _same_owner(context, rows[0], instance, _attrs(module), data.get('extension_api')): return None
        return runtime_value
    except Exception: return None


def _random_runtime(context, scope):
    """Private loaded-owner token/config snapshot; never emit the owner or UMO."""
    try: scope = private_scope(scope)
    except (ValueError, TypeError): return None
    result = inspect_legacy_companion(context, inspect_tasks=False)
    if result.get('loaded') is not True or result.get('state') != 'observed': return None
    try:
        rows = [row for row in _registry(context) if _attrs(row).get('root_dir_name') == ROOT]
        if len(rows) != 1: return None
        meta = _attrs(rows[0]); instance = meta.get('star_cls'); data = _attrs(instance)
        if data.get('enabled') is not True: return None
        module = meta.get('module')
        if not isinstance(module, ModuleType): module = sys.modules.get(meta.get('module_path'))
        root = Path(_attrs(module).get('__file__', '')).parent
        if inspect.getattr_static(instance, '_TLS_NATIVE_RANDOM_MARKER', None) != RANDOM_MARKER: return None
        for name in ('_tls_native_random_owned', '_tls_native_random_attempt_blocked', '_tls_native_random_quarantine'):
            method = inspect.getattr_static(instance, name, None)
            if (not inspect.isfunction(method) or Path(method.__code__.co_filename) != root / 'proactive.py'):
                return None
            if name == '_tls_native_random_owned' and RANDOM_MARKER not in method.__code__.co_consts:
                return None
        config = _config_root(data.get('config'))
        if config is None: return None
        sessions = dict.get(config, RANDOM_CONFIG_KEY)
        if (not isinstance(sessions, list) or len(sessions) > 64
                or any(not isinstance(item, str) or not item or len(item) > 512 or item != item.strip()
                       or any(ord(char) < 32 for char in item) for item in sessions)
                or len(set(sessions)) != len(sessions)):
            return None
        snapshot = tuple(sessions)
        if not _same_owner(context, rows[0], instance, _attrs(module), data.get('extension_api')): return None
        if tuple(dict.get(config, RANDOM_CONFIG_KEY, ())) != snapshot: return None
        return scope['session_id'] in snapshot, instance, snapshot, scope
    except Exception: return None


def runtime_random_disabled(context, scope):
    """Worker-safe RAM-only exact random gate proof, independent of daily cap.

    True proves the loaded marked implementation and exact configured session;
    it does not prove that already started old work has quiesced.
    """
    try: private_scope(scope)
    except (ValueError, TypeError): return None
    if native_pc_successor(context) is not None: return True
    value = _random_runtime(context, scope)
    return value[0] if value is not None else None


def inspect_random_handoff(context, scope, *, inspect_tasks=True):
    """Conservative current-loop observation for only the random handoff.

    Nonrandom work may temporarily make this busy. It is never cancelled here,
    and daily-limit values above zero do not by themselves fail this handoff.
    """
    try: private_scope(scope)
    except (ValueError, TypeError): return _unknown('complete_private_scope_required', loaded=False)
    if native_pc_successor(context) is not None:
        return dict(schema='tls.legacy.random.handoff.v1', read_only=True, loaded=False,
            state='quiescent_observed', reason='original_pc_retired_native_service_has_no_random_scheduler',
            original_plugin_active=False, native_pc_successor=True, random_gate_confirmed=True,
            task_inspection_available=True, business_calls=0, imports=0, model_calls=0, sends=0,
            absolute_no_inflight_guarantee=False, sdk_dispatch_acknowledgement_proven=False,
            global_cadence_shared_atomically=False)
    before = _random_runtime(context, scope)
    observed = inspect_legacy_companion(context, inspect_tasks=inspect_tasks)
    after = _random_runtime(context, scope)
    result = dict(schema='tls.legacy.random.handoff.v1', read_only=True,
        loaded=observed.get('loaded'), task_inspection_available=observed.get('task_inspection_available', False),
        random_gate_confirmed=before is not None and before[0] is True,
        state='unknown', business_calls=0, imports=0, model_calls=0, sends=0,
        absolute_no_inflight_guarantee=False, sdk_dispatch_acknowledgement_proven=False,
        global_cadence_shared_atomically=False)
    if (before is None or after is None or before[1] is not after[1] or before[2] != after[2]
            or before[0] != after[0]):
        result['reason'] = 'random_runtime_unknown_or_changed'; return result
    if not before[0]: result.update(state='not_disabled', reason='session_not_owned'); return result
    data = _attrs(before[1]).get('data')
    users = data.get('users') if isinstance(data, dict) else None
    if not isinstance(users, dict) or len(users) > 1024:
        result['reason'] = 'legacy_user_state_unknown'; return result
    matches = [row for row in users.values() if isinstance(row, dict) and row.get('umo') == before[3]['session_id']]
    if len(matches) != 1:
        result['reason'] = 'exact_session_state_unavailable'; return result
    user = matches[0]; impulses = user.get('proactive_impulses', [])
    if not isinstance(impulses, list) or len(impulses) > 1024:
        result['reason'] = 'random_pending_state_unknown'; return result
    pending = sum(isinstance(row, dict) and row.get('source') == 'random'
        and (row.get('state') not in ('cancelled', 'expired', 'sent', 'blocked', 'dropped')
             or row.get('last_status') in ('unknown', 'delivery_unknown') or row.get('delivery_unknown') is True)
        and row.get('trigger_umo') in (None, '', before[3]['session_id']) for row in impulses)
    quarantine = user.get('_tls_native_random_quarantine', [])
    plans = user.get('_tls_native_random_plan_quarantine', [])
    if (not isinstance(quarantine, list) or len(quarantine) > 4096
            or not isinstance(plans, list) or len(plans) > 4096):
        result['reason'] = 'random_audit_state_unknown'; return result
    held = sum(isinstance(row, dict) and row.get('source') == 'random'
        and (row.get('tls_handoff_hold') is True or row.get('state') == 'unknown'
             or row.get('last_status') in ('unknown', 'delivery_unknown') or row.get('delivery_unknown') is True)
        for row in quarantine)
    for row in plans:
        if not isinstance(row, dict): result['reason'] = 'random_audit_state_unknown'; return result
        retry = row.get('pending_proactive_send_retry')
        status = retry.get('delivery_state', retry.get('last_status', retry.get('state', ''))) if isinstance(retry, dict) else ''
        if (row.get('proactive_sending') is True or bool(row.get('proactive_sending_started_at'))
                or str(row.get('planned_proactive_delivery_state') or '').lower() not in ('', 'fresh', 'deferred')
                or str(status or '').lower() not in ('', 'fresh', 'deferred', 'queued')):
            held += 1
    planned = user.get('planned_proactive_source') == 'random'
    result['counts'] = dict(pending_random_impulses=pending, current_random_plans=int(planned),
        quarantined_unknown_deliveries=held,
        **observed.get('counts', {}))
    state = observed.get('handoff', {}).get('state')
    if pending or held or planned or state == 'busy': result.update(state='busy', reason='visible_legacy_work')
    elif state in ('not_disabled', 'quiescent_observed') and result['task_inspection_available']:
        result.update(state='quiescent_observed', reason='random_gate_and_no_visible_old_work')
    else: result['reason'] = 'task_observation_unknown'
    return result
