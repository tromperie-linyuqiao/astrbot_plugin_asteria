"""Bounded task-chain shape observation; never a handoff or sending permit.

No task names, coroutine reprs, frames' locals, object identities or paths are
returned. Exact built-in coroutine/iterator types are read without calling an
unknown awaitable's attributes or methods. The old gate remains unchanged.
"""
from __future__ import annotations

import asyncio
import inspect
from types import AsyncGeneratorType, CodeType, CoroutineType, FrameType, GeneratorType, MethodDescriptorType
from weakref import WeakSet

MAX_TASKS = 512
MAX_DEPTH = 32
REASONS = ('none_terminal', 'future_terminal', 'opaque_awaitable', 'cycle',
           'depth_limit', 'get_coro_error', 'attribute_error', 'unsupported_task')
OPAQUE_TYPES = ('coroutine_wrapper', 'async_generator_asend', 'async_generator_athrow', 'other_unknown')
FAMILIES = ('sdk_lifecycle', 'sdk_platform', 'sdk_event_bus', 'sdk_dashboard',
            'stdlib_asyncio', 'hypercorn', 'anyio', 'legacy_mc', 'tls', 'other_plugin', 'other_unknown')


def _opaque_types():
    async def coroutine():
        return None
    async def generator():
        yield None
    coro = coroutine(); wrapper = coro.__await__()
    gen = generator(); send = gen.__anext__(); throw = gen.athrow(GeneratorExit)
    result = ((type(wrapper), 'coroutine_wrapper'), (type(send), 'async_generator_asend'),
              (type(throw), 'async_generator_athrow'))
    wrapper.close(); coro.close(); send.close(); throw.close()
    return result


_OPAQUE = _opaque_types()


def _task_snapshot(loop):
    """Use bounded registries and C descriptors, never subclass overrides.

    CPython 3.11 calls the weak registry _all_tasks; 3.12 calls it
    _scheduled_tasks and adds _eager_tasks. Unknown registry shapes fail closed.
    This does not change or substitute the handoff gate's own all_tasks call.
    """
    if any(type(method) is not MethodDescriptorType for method in
           (asyncio.Task.get_loop, asyncio.Task.done, asyncio.Task.get_coro)):
        raise ValueError('unsupported_task_runtime')
    namespace = vars(asyncio.tasks)
    scheduled = namespace.get('_scheduled_tasks', namespace.get('_all_tasks'))
    eager = namespace.get('_eager_tasks', frozenset())
    if type(scheduled) is not WeakSet or type(eager) not in (set, frozenset):
        raise ValueError('unsupported_task_registry')
    seen = set(); tasks = []
    iterators = (WeakSet.__iter__(scheduled), set.__iter__(eager) if type(eager) is set else frozenset.__iter__(eager))
    for iterator in iterators:
        for task in iterator:
            if id(task) in seen: continue
            seen.add(id(task))
            if len(seen) > MAX_TASKS: raise OverflowError('task_capacity')
            # The built-in descriptor rejects non-Task values without resolving
            # user attributes, and bypasses Task-subclass method overrides.
            if asyncio.Task.get_loop(task) is loop and not asyncio.Task.done(task):
                tasks.append(task)
    return tasks


def _family(code):
    if type(code) is not CodeType or len(code.co_filename) > 4096:
        return 'other_unknown'
    # These are metadata categories, not source authentication or authority.
    name = code.co_filename.replace('\\', '/')
    if name.endswith('/astrbot/core/core_lifecycle.py'): return 'sdk_lifecycle'
    if '/astrbot/core/platform/' in name: return 'sdk_platform'
    if name.endswith('/astrbot/core/event_bus.py'): return 'sdk_event_bus'
    if '/astrbot/dashboard/' in name: return 'sdk_dashboard'
    if '/asyncio/' in name: return 'stdlib_asyncio'
    if '/hypercorn/' in name: return 'hypercorn'
    if '/anyio/' in name: return 'anyio'
    if '/astrbot_plugin_memory_companion/' in name: return 'legacy_mc'
    if '/astrbot_plugin_virtual_body/' in name: return 'tls'
    if '/plugins/' in name: return 'other_plugin'
    return 'other_unknown'


def _chain(root, future_type):
    current = root; seen = set(); root_family = 'other_unknown'; last_family = 'other_unknown'
    for depth in range(MAX_DEPTH):
        if current is None:
            return dict(reason='none_terminal', depth=depth, root_family=root_family, last_family=last_family, opaque_type=None)
        if id(current) in seen:
            return dict(reason='cycle', depth=depth, root_family=root_family, last_family=last_family, opaque_type=None)
        seen.add(id(current))
        kind = type(current)
        try:
            if kind is CoroutineType: code, following = current.cr_code, current.cr_await
            elif kind is GeneratorType: code, following = current.gi_code, current.gi_yieldfrom
            elif kind is AsyncGeneratorType: code, following = current.ag_code, current.ag_await
            elif kind is future_type:
                return dict(reason='future_terminal', depth=depth, root_family=root_family, last_family=last_family, opaque_type=None)
            else:
                return dict(reason='opaque_awaitable', depth=depth, root_family=root_family,
                    last_family=last_family, opaque_type=next((label for known, label in _OPAQUE if kind is known), 'other_unknown'))
        except Exception:
            return dict(reason='attribute_error', depth=depth, root_family=root_family, last_family=last_family, opaque_type=None)
        last_family = _family(code)
        if depth == 0: root_family = last_family
        current = following
    return dict(reason='depth_limit' if current is not None else 'none_terminal', depth=MAX_DEPTH,
                root_family=root_family, last_family=last_family, opaque_type=None)


def observe_task_diagnostics():
    """Call synchronously in the actual application's event-loop thread.

    A separate SSH Python interpreter cannot observe the application's Tasks.
    The 32-level diagnostic limit is stricter than the unchanged gate's 64;
    matching unknown counts is meaningful only if no diagnostic depth limit or
    unsupported task is reported. No task is awaited, resumed or cancelled.
    """
    result = dict(schema='tls.native.core.task_diagnostics.v1', state='unknown', code='event_loop_unavailable',
        diagnostic_only=True, authorization_granted=False, gate_changed=False, business_calls=0,
        models=0, sends=0, observation_scope='current_python_event_loop_only',
        absolute_no_inflight_guarantee=False, source_identity_proven=False,
        max_tasks=MAX_TASKS, max_depth=MAX_DEPTH, unchanged_gate_max_depth=64,
        observed_tasks=None, inspectable_tasks=None, uninspectable_tasks=None,
        reason_counts={k: 0 for k in REASONS}, opaque_terminal_type_counts={k: 0 for k in OPAQUE_TYPES},
        unknown_groups=[], current_stack_depth=None, current_stack_truncated=None,
        task_names_returned=False, locals_or_repr_returned=False, paths_or_object_ids_returned=False)
    try:
        loop = asyncio.get_running_loop()
        try: tasks = _task_snapshot(loop)
        except OverflowError:
            result['code'] = 'task_capacity'; return result
        # Construct only a plain Future iterator, never an application Task.
        future = asyncio.Future(loop=loop); iterator = future.__await__(); future_type = type(iterator)
        counts = result['reason_counts']; groups = {}; unknown = 0
        for task in tasks:
            try:
                root = asyncio.Task.get_coro(task)
                observed = _chain(root, future_type)
            except Exception:
                observed = dict(reason='get_coro_error', root_family='other_unknown', last_family='other_unknown', opaque_type=None)
            reason = observed['reason']; counts[reason] += 1
            if reason not in {'none_terminal', 'future_terminal'}:
                unknown += 1
                opaque = observed['opaque_type']
                if opaque is not None: result['opaque_terminal_type_counts'][opaque] += 1
                key = (reason, observed['root_family'], observed['last_family'], opaque)
                groups[key] = groups.get(key, 0) + 1
        # Inspect code pointers only; no f_locals and no arbitrary frame methods.
        frame = inspect.currentframe(); depth = 0
        try:
            while type(frame) is FrameType and depth < MAX_DEPTH:
                depth += 1; frame = frame.f_back
            result.update(current_stack_depth=depth, current_stack_truncated=frame is not None)
        finally:
            del frame
        result.update(state='available', code='bounded_shape_observation', observed_tasks=len(tasks),
            inspectable_tasks=len(tasks) - unknown, uninspectable_tasks=unknown,
            unknown_groups=[dict(reason=k[0], root_family=k[1], last_family=k[2], opaque_type=k[3], count=v)
                for k, v in sorted(groups.items(), key=lambda item: tuple(x or '' for x in item[0]))])
        return result
    except Exception:
        # Never expose exception strings, task names, filenames or coroutine repr.
        result['code'] = 'task_observation_failed'; return result
