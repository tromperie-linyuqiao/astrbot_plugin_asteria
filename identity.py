"""Canonical Asteria identity with explicit, non-copying upgrade compatibility."""
from pathlib import Path

PLUGIN_NAME = 'astrbot_plugin_asteria'
DISPLAY_NAME = '星栖 Asteria'
LEGACY_PLUGIN_NAME = 'astrbot_plugin_virtual_body'
REPOSITORY = 'https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria'
_OWNED_COMPONENT_DIRS = frozenset({'companion', 'memory_companion', 'phone', 'dialogue_flow',
                                  'proactive_chat', 'insight_center', 'intimacy_cards'})


def canonical_data_directory():
    """Resolve the storage root through AstrBot, independent of the installation path."""
    from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
    parent = Path(get_astrbot_plugin_data_path()).resolve()
    target = parent / PLUGIN_NAME
    if target.resolve() != target:
        raise RuntimeError('Asteria 的数据目录不能重定向到其他目录')
    return target


def component_data_directory(component, legacy_name, *, retain_existing, markers):
    """New component stores belong to Asteria; keep previously owned files in place."""
    own = canonical_data_directory()
    if component not in _OWNED_COMPONENT_DIRS:
        raise ValueError('unknown Asteria component')
    path, previous = own / component, own.parent / legacy_name
    if path.resolve() != path:
        raise RuntimeError('组件数据目录不能重定向')
    if not retain_existing or path.is_dir() and any(path.iterdir()):
        return path
    if previous.resolve() != previous:
        raise RuntimeError('旧组件数据目录不能重定向')
    if any((previous / name).is_file() and not (previous / name).is_symlink() for name in markers):
        return previous
    return path


def ensure_single_instance(context):
    """Refuse a second active registration before constructing any writers."""
    reader = getattr(context, 'get_all_stars', None)
    if reader is None:
        return
    for metadata in reader():
        if getattr(metadata, 'name', None) not in (PLUGIN_NAME, LEGACY_PLUGIN_NAME):
            continue
        owner = getattr(metadata, 'star_cls', None)
        if owner is not None and not getattr(owner, '_stopping', False):
            raise RuntimeError('星栖 Asteria 已有运行实例；请在原安装位置更新，不能并行启用新旧标识')


def data_directory(star_tools):
    """Prefer existing data in place; refuse two populated owners, never merge."""
    canonical = Path(star_tools.get_data_dir(PLUGIN_NAME))
    return existing_data_directory(canonical.parent)


def existing_data_directory(parent):
    """Read-only selection, shared by companion projections and the host."""
    canonical = Path(parent) / PLUGIN_NAME
    legacy = Path(parent) / LEGACY_PLUGIN_NAME
    populated = lambda p: p.is_dir() and any(p.iterdir())
    if populated(legacy):
        # The canonical namespace may already contain component subdirectories
        # without hosting a second primary state owner.
        if canonical.is_dir() and any(child.name not in _OWNED_COMPONENT_DIRS or not child.is_dir()
                                      or child.is_symlink() for child in canonical.iterdir()):
            raise RuntimeError('Asteria 与旧标识的数据目录均有资料，请明确选择，不能自动合并')
        return legacy
    return canonical


def register_canonical_aliases(plugin):
    """Alias this instance's existing handlers; same authentication and effects."""
    context = plugin.context
    owned = [plugin]
    exact_handlers = []
    integrations = getattr(plugin, '_native_server_integrations', None)
    if integrations is not None and getattr(integrations, 'plugin', None) is plugin:
        phone = getattr(integrations, 'phone', None)
        pc = getattr(getattr(integrations, 'pc_full', None), 'service', None)
        owned.extend(x for x in (phone, getattr(phone, 'dialogue_flow', None),
                                pc, getattr(integrations, 'mc_full', None)) if x is not None)
        exact_handlers.extend(row[1] for row in getattr(pc, '_tls_registered_routes', ()))
    saved = getattr(plugin, '_asteria_route_aliases', [])
    prefix = '/' + LEGACY_PLUGIN_NAME + '/'
    aliases = 0
    for route, handler, methods, description in list(getattr(context, 'registered_web_apis', ())):
        original = getattr(handler, '__wrapped__', handler)
        owner = getattr(original, '__self__', None)
        if owner is None:
            owner = getattr(original, '__asteria_owner__', None)
        route_plugin = getattr(owner, 'plugin', None)
        if route_plugin is None:
            route_plugin = getattr(getattr(owner, 'chat', None), 'plugin', None)
        if not (any(route_plugin is value or owner is value for value in owned)
                or any(handler is value for value in exact_handlers)):
            continue
        canonical_prefix = '/' + PLUGIN_NAME + '/'
        if route.startswith(prefix):
            target = canonical_prefix + route[len(prefix):]
        elif route.startswith(canonical_prefix):
            target = prefix + route[len(canonical_prefix):]
        else:
            continue
        context.register_web_api(target, handler, methods, description)
        saved.extend(row for row in context.registered_web_apis
                     if row[0] == target and row[1] is handler and not any(row is old for old in saved))
        aliases += 1
    plugin._asteria_route_aliases = saved
    return aliases


def remove_canonical_aliases(plugin):
    registry = getattr(plugin.context, 'registered_web_apis', None)
    saved = getattr(plugin, '_asteria_route_aliases', ())
    if isinstance(registry, list):
        registry[:] = [row for row in registry if not any(row is old for old in saved)]
    plugin._asteria_route_aliases = []


def _retained_type(value, name, module, relative, method):
    """Recognize an exact class exported by its own retained import generation."""
    from types import FunctionType, MethodType
    cls = type(value)
    function = vars(cls).get(method)
    bound = getattr(value, method, None)
    return (cls.__module__ == module and type(function) is FunctionType
        and type(bound) is MethodType and bound.__self__ is value and bound.__func__ is function
        and function.__globals__.get(name) is cls
        and function.__globals__.get('__name__') == module
        and Path(function.__code__.co_filename).resolve() == Path(__file__).parent.joinpath(relative).resolve())


def _phone_quiescent(phone, *, closed=False):
    import asyncio
    from types import FunctionType
    flow = phone.dialogue_flow
    # close() releases queued inputs; never use it to flush an uncertain batch.
    if flow.batcher.pending or flow.batcher.buckets:
        return False
    if any(not task.done() for task in flow._notices.values()):
        return False
    # A direct send can be awaiting the platform without a batch/notice entry.
    # Inspect only exact functions and receivers from these two retained types;
    # an uncertain submission remains with its original task and ledger.
    tasks = asyncio.all_tasks()
    if len(tasks) > 4096: return False
    codes = {value.__code__ for cls in (type(phone), type(flow)) for value in vars(cls).values()
             if type(value) is FunctionType}
    loops = {vars(type(phone))[name].__code__ for name in ('_care_loop', '_greeting_loop')}
    for task in tasks:
        if task.done(): continue
        current, seen = task.get_coro(), set()
        for _ in range(128):
            if current is None or id(current) in seen: break
            seen.add(id(current))
            frame = getattr(current, 'cr_frame', getattr(current, 'gi_frame', None))
            code = getattr(current, 'cr_code', getattr(current, 'gi_code', None))
            next_await = getattr(current, 'cr_await', getattr(current, 'gi_yieldfrom', None))
            if frame is not None and code in codes and (frame.f_locals.get('self') is phone or frame.f_locals.get('self') is flow):
                sleeping = (code in loops and (task is phone._care_task or task is phone._greet_task)
                    and (next_await is None or getattr(next_await, 'cr_code', None) is asyncio.sleep.__code__))
                if not sleeping: return False
            current = next_await
        else:
            return False
    if closed:
        return (phone._active is False and flow._active is False and flow.store._closed is True
            and all(task is None or task.done() for task in (phone._care_task, phone._greet_task)))
    return True


async def close_failed_initialization(plugin):
    """Same close order as terminate; a failed drain retains its exact owner."""
    controller = getattr(plugin, '_native_server_integrations', None)
    presence = getattr(plugin, '_presence', None)
    prior = getattr(plugin.context, '_asteria_failed_initialization', None)
    if controller is not None and (prior is None or prior is plugin):
        plugin.context._asteria_failed_initialization = plugin
    remove_canonical_aliases(plugin)
    runtime = getattr(getattr(presence, 'living_host', None), 'runtime', None)
    reminders = getattr(runtime, 'reminders', None)
    if reminders is not None: reminders.stop()
    delivery = getattr(runtime, 'delivery', None)
    if delivery is not None:
        delivery.active = False
        delivery.sender.active = False
    try:
        phone = getattr(controller, 'phone', None)
        if phone is not None and not _phone_quiescent(phone):
            raise RuntimeError('failed phone inputs still pending; retain original lifecycle')
        if controller is not None: await controller.close()
    except BaseException:
        if presence is not None: presence.close()
        await plugin._cancel_runtime_tasks()
        raise
    if presence is not None: await presence.aclose()
    await plugin._cancel_runtime_tasks()
    plugin._native_server_integrations = None
    if getattr(plugin.context, '_asteria_failed_initialization', None) is plugin:
        delattr(plugin.context, '_asteria_failed_initialization')


async def recover_failed_initialization(plugin):
    """Close only a same-Context failed object, before constructing a successor.

    Retained Phone fences, MC lifecycle anchors and exact PC route closures are
    references, not a new state store. Unknown/active owners always block.
    """
    import asyncio
    import os
    from types import MethodType, FunctionType
    from .main import AsteriaPlugin
    from .core.living.native_phone_flow import integration as flow_api
    context = plugin.context
    if type(plugin) is not AsteriaPlugin:
        raise RuntimeError('failed lifecycle successor class changed')
    prefix = type(plugin).__module__.rsplit('.', 1)[0]
    candidates = []
    def add(old):
        if old is plugin: return
        if old is None: raise RuntimeError('failed lifecycle owner missing')
        if not any(old is previous for previous in candidates): candidates.append(old)
    retained = getattr(context, '_asteria_failed_initialization', None)
    if retained is not None: add(retained)
    state = getattr(context, flow_api._STATE_KEY, None)
    if state is not None:
        required = {'version','context','service','slots','wrapper','token','enabled','sender',
                    'pc_aliases','not_present','errors','ready'}
        if (type(state) is not dict or set(state) != required or state['version'] != flow_api._STATE_VERSION
            or state['context'] is not context or type(state['slots']) is not list or not 1 <= len(state['slots']) <= 256
            or type(state['wrapper']) is not FunctionType
            or getattr(state['wrapper'], '_tls_phone_flow_token', None) is not state['token']
            or dict(zip(state['wrapper'].__code__.co_freevars,
                        (cell.cell_contents for cell in state['wrapper'].__closure__ or ()))).get('state') is not state
            or any(not flow_api._legacy_function(original) or vars(module).get(name) is not state['wrapper']
                   for module, name, original in state['slots'])):
            raise RuntimeError('failed phone forwarder identity changed')
        phone = state['service']
        if not _retained_type(phone, 'NativePhoneService', prefix+'.core.living.native_phone_service.runtime',
                'core/living/native_phone_service/runtime.py', 'terminate') or phone.context is not context:
            raise RuntimeError('failed phone type/context changed')
        if phone is not getattr(plugin, '_native_phone_service', None) and not _phone_quiescent(phone, closed=True):
            add(getattr(phone.config, 'plugin', None))
    mc = getattr(context, '_tls_native_mc_lifecycle', None)
    if mc is not None:
        owner = mc.get('owner') if type(mc) is dict else None
        callback = mc.get('close') if type(mc) is dict else None
        if (type(mc) is not dict or mc.get('schema') != 'tls.mc.native.lifecycle.v1'
            or mc.get('context') is not context or mc.get('pid') != os.getpid()
            or mc.get('loop') is not asyncio.get_running_loop()
            or not _retained_type(owner, 'NativeMCFullOwner', prefix+'.core.living.native_mc_full_owner',
                'core/living/native_mc_full_owner.py', 'close')
            or owner._native_record is not mc or owner.context is not context
            or type(callback) is not MethodType or callback.__self__ is not owner
            or callback.__func__ is not vars(type(owner))['close']
            or mc.get('adapter') is not owner.adapter or mc.get('service') is not owner.adapter.service
            or owner.integrations._mc_full_owner is not owner):
            raise RuntimeError('failed memory lifecycle identity changed')
        add(owner.plugin)
    # A PC-only partial load has no Phone/MC anchor. Read its own already-bound
    # route closures, never arbitrary modules, queues or garbage-collector data.
    routes = getattr(context, 'registered_web_apis', [])
    if type(routes) is not list or len(routes) > 8192:
        raise RuntimeError('failed lifecycle route inventory unavailable')
    for row in routes:
        handler = row[1]
        if (type(handler) is not FunctionType or handler.__module__ != prefix+'.core.living.native_pc_service'
            or handler.__qualname__ != 'NativePCService.register_native_routes.<locals>.guarded'):
            continue
        closure = dict(zip(handler.__code__.co_freevars, (cell.cell_contents for cell in handler.__closure__ or ())))
        service = closure.get('service')
        if not _retained_type(service, 'NativePCService', handler.__module__, 'core/living/native_pc_service.py', 'terminate'):
            raise RuntimeError('failed companion route class changed')
        callback = service._tls_legacy_closed
        owner = getattr(callback, '__self__', None)
        if (type(callback) is not MethodType or not _retained_type(owner, 'NativePCFullOwner',
                prefix+'.core.living.native_pc_full_owner', 'core/living/native_pc_full_owner.py', 'close')
            or callback.__func__ is not vars(type(owner))['legacy_closed']
            or owner.service is not service or service.context is not context
            or service.config.owner is not owner or owner.integrations.pc_full is not owner
            or not any(row is saved for saved in service._tls_registered_routes)):
            raise RuntimeError('failed companion route owner changed')
        add(owner.plugin)
    if not candidates: return 0
    if len(candidates) != 1:
        raise RuntimeError('multiple failed lifecycle owners; do not guess')
    old = candidates[0]
    def validate():
        cls = type(old)
        if (not (_retained_type(old, 'AsteriaPlugin', type(plugin).__module__, 'main.py', 'initialize')
                 or _retained_type(old, 'VirtualBodyPlugin', type(plugin).__module__, 'main.py', 'initialize'))
            or old.context is not context or old._stopping is not True or old._initialized is not False):
            raise RuntimeError('predecessor is not an exact failed Asteria instance')
        rows = context.get_all_stars()
        if any(getattr(row, 'name', None) in (PLUGIN_NAME, LEGACY_PLUGIN_NAME)
               and getattr(row, 'activated', False) is True
               and getattr(row, 'star_cls', None) is not None
               and getattr(row, 'star_cls', None) is not plugin for row in rows):
            raise RuntimeError('another registered Asteria owner remains active')
        controller = getattr(old, '_native_server_integrations', None)
        if (not _retained_type(controller, 'NativeServerIntegrations', prefix+'.core.living.native_server_integrations',
                'core/living/native_server_integrations.py', 'close')
            or controller.plugin is not old or controller.context is not context):
            raise RuntimeError('failed controller identity changed')
        phone = controller.phone
        if phone is not None:
            callback = phone._authorize_session
            flow = phone.dialogue_flow
            flow_authorize = flow._authorize_session
            if (not _retained_type(phone, 'NativePhoneService', prefix+'.core.living.native_phone_service.runtime',
                    'core/living/native_phone_service/runtime.py', 'terminate')
                or not _retained_type(phone.config, 'PhoneConfigView', prefix+'.core.living.native_server_integrations',
                    'core/living/native_server_integrations.py', 'save_config')
                or not _retained_type(flow, 'NativePhoneFlow', prefix+'.core.living.native_phone_flow.runtime',
                    'core/living/native_phone_flow/runtime.py', 'terminate')
                or flow.context is not context or type(flow_authorize) is not MethodType
                or flow_authorize.__self__ is not phone or flow_authorize.__func__ is not vars(type(phone))['_session_allowed']
                or phone.context is not context or phone.config.plugin is not old
                or old._native_phone_service is not phone or type(callback) is not MethodType
                or callback.__self__ is not controller or callback.__func__ is not vars(type(controller))['_phone_authorized']
                or not _phone_quiescent(phone)):
                raise RuntimeError('failed phone owner changed or queued inputs/inflight work remain')
            if state is not None and state['service'] is phone and (
                    controller._flow_forwarders is None or controller._flow_forwarders._state is not state):
                raise RuntimeError('failed phone fence/controller differs')
        return controller
    controller = validate()
    if (type(old._lifecycle_lock) is not asyncio.Lock or type(controller._lock) is not asyncio.Lock
        or old._lifecycle_lock.locked() or controller._lock.locked()):
        raise RuntimeError('failed lifecycle close already in progress')
    async with old._lifecycle_lock:
        controller = validate()
        await controller.close()
        phone = controller.phone
        pc = controller.pc_full
        memory = controller._mc_full_owner
        proactive = controller.proactive_chat
        if (not controller._closed or phone is not None and not _phone_quiescent(phone, closed=True)
            or pc is not None and (pc.active or pc.service is not None)
            or memory is not None and (memory._native_record is not None
                or memory.adapter is not None and not memory.adapter.closed)
            or proactive is not None and (not proactive._closed or any(not task.done() for task in proactive._running))):
            raise RuntimeError('failed lifecycle drain not confirmed')
        if state is not None and state['service'] is phone and (
                getattr(context, flow_api._STATE_KEY, None) is not state or state['enabled'] is not False
                or any(vars(module).get(name) is not state['wrapper'] for module, name, _ in state['slots'])):
            raise RuntimeError('failed phone fence changed while draining')
        presence = getattr(old, '_presence', None)
        if presence is not None: await presence.aclose()
        await old._cancel_runtime_tasks()
        old._native_server_integrations = None
        if getattr(context, '_asteria_failed_initialization', None) is old:
            delattr(context, '_asteria_failed_initialization')
    return 1
