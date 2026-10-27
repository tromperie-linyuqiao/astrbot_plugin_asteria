"""Own Insight and Phone lifecycles inside the existing TLS plugin.

PPB remains the user's external collection bridge. Legacy plugin removal is an
explicit administrator operation; constructing these services never starts a
second phone owner or clears a queue, clock, lease or listening history.
"""
from __future__ import annotations
import asyncio
from collections import OrderedDict, deque
from collections.abc import MutableMapping
from copy import deepcopy
import json
import inspect
from pathlib import Path
import threading
from types import MethodType


class PhoneConfigView(MutableMapping):
    """The original Phone configuration shape, stored in TLS's existing config."""
    def __init__(self, plugin, lock): self.plugin, self.lock = plugin, lock
    @property
    def _data(self):
        value = self.plugin.config.get('living_phone', {})
        if not isinstance(value, dict): raise ValueError('phone configuration must be an object')
        return value
    def __getitem__(self, key): return self._data[key]
    def __setitem__(self, key, value):
        with self.lock:
            values = dict(self._data); values[key] = value
            self.plugin.config['living_phone'] = values
    def __delitem__(self, key):
        with self.lock:
            values = dict(self._data); del values[key]
            self.plugin.config['living_phone'] = values
    def __iter__(self): return iter(self._data)
    def __len__(self): return len(self._data)
    def save_config(self):
        with self.lock: self.plugin.config.save_config()


def _pack(value):
    if value is None or type(value) in (str, bool, int, float): return ['value', value]
    if isinstance(value, deque): return ['deque', value.maxlen, [_pack(x) for x in value]]
    if isinstance(value, OrderedDict): return ['ordered', [[_pack(k), _pack(v)] for k,v in value.items()]]
    if type(value) is dict: return ['dict', [[_pack(k), _pack(v)] for k,v in value.items()]]
    if type(value) in (tuple, list): return ['tuple' if type(value) is tuple else 'list', [_pack(x) for x in value]]
    raise TypeError('phone continuity must contain data only')


def _unpack(value):
    tag = value[0]
    if tag == 'value': return value[1]
    if tag == 'deque': return deque((_unpack(x) for x in value[2]), maxlen=value[1])
    if tag in ('dict', 'ordered'):
        return (dict if tag == 'dict' else OrderedDict)((_unpack(k), _unpack(v)) for k,v in value[1])
    if tag in ('tuple', 'list'):
        return (tuple if tag == 'tuple' else list)(_unpack(x) for x in value[1])
    raise ValueError('unknown phone continuity data')


class NativeServerIntegrations:
    def __init__(self, plugin):
        from astrbot.api.star import StarTools
        self.plugin, self.context = plugin, plugin.context
        self.data_dir = Path(StarTools.get_data_dir('astrbot_plugin_virtual_body'))
        self.phone_data_dir = self.data_dir.parent/'astrbot_plugin_phone_perception'
        self.flow_store_path = self.data_dir.parent/'astrbot_plugin_dialogue_flow'/'preferences.db'
        self._config_lock = threading.RLock()
        self._lock = asyncio.Lock()
        self._prepared_phone = None
        self._prepared_terminate = self._prepared_wrapper = None
        self._closed = False
        self._phone_phase = 'inactive'
        self._generation = 0
        self.insight = self.phone = None
        self.mc = self.pc = None
        self.mc_full = self.pc_full = None
        self._mc_full_owner = None
        self._proactive_full_owner = None
        self.proactive_chat = None
        self._native_ingress_results = {}
        self._business_delivery = None
        self._flow_forwarders = None
        self._shared_connector = None
        self._prior_connector_parameters = None
        self._owned_tools = {}
        self._owned_commands = []
        self._continuity = self.data_dir/'phone-native-continuity.json'
        self._toggle_full_commands('mc',False)
        self._toggle_full_commands('pc',False)

    def _toggle_full_commands(self, kind, active):
        from astrbot.core.star.star_handler import star_handlers_registry
        if kind=='mc':
            selected=lambda name:name=='native_mcomp' or name.startswith('native_cmd_mcomp_')
        else:
            path=Path(__file__).parent/'native_pc_business/EVENT-HOOKS.json'
            names={'integrated_pc_'+row['function'] for row in json.loads(path.read_bytes())['hooks']
                if row['module']=='main.py' and row['decorator'].startswith(('filter.command(', 'filter.command_group('))}
            selected=lambda name:name in names
        module=type(self.plugin).__module__
        for handler in star_handlers_registry:
            if getattr(handler,'handler_module_path',None)==module and selected(getattr(handler,'handler_name','')):
                handler.enabled=bool(active)

    def legacy(self, name):
        matches = [row for row in self.context.get_all_stars()
                   if getattr(row, 'root_dir_name', None) == name]
        if len(matches) != 1: return None
        row = matches[0]
        return getattr(row, 'star_cls', None) if getattr(row, 'activated', False) is True else None

    def _save_flag(self, key, value):
        previous = self.plugin.config.get(key, None)
        with self._config_lock:
            self.plugin.config[key] = value
            try: self.plugin.config.save_config()
            except Exception:
                if previous is None: self.plugin.config.pop(key, None)
                else: self.plugin.config[key] = previous
                raise

    def _native_config_is_default(self,key,value):
        """Recognize only the SDK's untouched schema-default materialization."""
        path=Path(inspect.getfile(type(self.plugin))).resolve().parent/'_conf_schema.json'
        schema=json.loads(path.read_bytes()).get(key,{})
        def defaults(items):
            return {name:defaults(row['items']) if row.get('type')=='object' else deepcopy(row['default'])
                for name,row in items.items() if row.get('type')=='object' or 'default' in row}
        return (type(value) is dict and schema.get('type')=='object'
            and json.dumps(value,sort_keys=True,allow_nan=False)
                ==json.dumps(defaults(schema.get('items',{})),sort_keys=True,allow_nan=False))

    def _phone_authorized(self, umo):
        """Preserve configured Phone ownership; never fabricate a Presence lease.

        This predicate controls Phone pacing/its existing configured background
        care lane only. Memory/LLM hooks retain their own existing live checks.
        """
        if (self._closed or self.phone is None or not self.phone._active or not isinstance(umo, str)
                or self.legacy('astrbot_plugin_phone_perception') is not None):
            return False
        parts = umo.split(':', 2)
        if len(parts) != 3 or parts[1] != 'FriendMessage': return False
        sender = parts[2]
        if parts[0] == 'webchat':
            fields = sender.split('!')
            if len(fields) != 3 or fields[0] != 'webchat': return False
            sender = fields[1]
        resolved = self.plugin._resolve_session(sender)
        return (resolved is not None and sender in self.phone._allowed_users()
                and not getattr(self.plugin, '_stopping', False))

    def _host(self):
        return getattr(getattr(self.plugin, '_presence', None), 'living_host', None)

    async def _pause_phone_companion(self):
        host = self._host()
        if host is None: return
        host.phone_transfer_pending = True
        task = getattr(host, '_phone_task', None)
        if task is not None and not task.done():
            # Do not cancel an operation with a possible external effect.
            await asyncio.shield(task)

    async def _share_phone_client(self):
        from .native_phone_integration_connector import NativePhoneSharedConnector
        host = self._host()
        runtime = getattr(host, 'runtime', None)
        services = getattr(runtime, 'native_services', None)
        companion = getattr(runtime, 'phone_companion', None)
        if companion is None: return
        await self._pause_phone_companion()
        old = companion.connector
        if isinstance(old, NativePhoneSharedConnector) and old.service is self.phone:
            self._shared_connector = old
            host.phone_transfer_pending = False
            return
        connector = NativePhoneSharedConnector(self.phone,
            authorize=services._delivery_allowed, clock=host.clock)
        from .native_phone_connector import NativePhoneConnector
        if type(old) is NativePhoneConnector:
            self._prior_connector_parameters = dict(base_url=old._endpoint.rsplit('/state',1)[0],
                token=old._token, user_devices=deepcopy(old._bindings),
                authorize=services._delivery_allowed, clock=host.clock,
                stale_seconds=old.stale, music_ttl_seconds=old.music_ttl,
                timeout_seconds=old.timeout, cache_ttl_seconds=old.cache_ttl)
        try:
            await old.close()
            companion.connector = connector
            runtime.phone_connector = connector
            self._shared_connector = connector
            host.phone_transfer_pending = False
        except BaseException:
            await connector.close()
            raise

    def _install_flow_forwarders(self):
        from .native_phone_flow.integration import install_legacy_forwarders
        self._flow_forwarders = install_legacy_forwarders(self.context, self.phone)

    def _make_pc(self):
        host = self._host()
        runtime = getattr(host, 'runtime', None)
        services = getattr(runtime, 'native_services', None)
        self.pc = services.configure_pc() if services is not None else None
        self.plugin._native_pc_integration = self.pc
        return self.pc

    def _make_insight(self):
        from .native_insight_center import NativeInsightCenter
        self.insight = NativeInsightCenter(self.plugin, plugin_data_dir=self.data_dir.parent)
        self.plugin._native_insight = self.insight
        return self.insight

    def _make_phone(self):
        from .native_phone_service.runtime import NativePhoneService
        self.phone = NativePhoneService(self.context, PhoneConfigView(self.plugin, self._config_lock),
            data_dir=self.phone_data_dir, flow_store_path=self.flow_store_path,
            authorize_session=self._phone_authorized, config_write_lock=self._config_lock)
        self.plugin._native_phone_service = self.phone
        return self.phone

    def _register_tools(self, kind):
        from .native_integrated_tools import insight_tools, phone_tools, memory_companion_tools
        if kind in self._owned_tools: return
        if kind=='pc_full':
            from .native_pc_tools import factorytools
            tools=factorytools(self.pc_full)
        else:
            tools = (memory_companion_tools if kind == 'mc' else insight_tools if kind == 'insight' else phone_tools)(self)
        self.context.add_llm_tools(*tools)
        self._owned_tools[kind] = tools

    def _remove_tools(self, kind):
        if not self._owned_tools.get(kind): return
        manager = self.context.get_llm_tool_manager()
        for tool in self._owned_tools.pop(kind, []):
            if any(item is tool for item in manager.func_list):
                manager.remove_func(tool.name)

    def _register_phone_commands(self):
        if self._owned_commands: return
        from astrbot.core.star.star_handler import star_handlers_registry
        commands = [('彩蛋测试','command_greeting_test'),('歌单重灌','command_resync_playlist'),
                    ('感知令牌重置','command_rotate_token'),('感知重载','command_reload'),
                    ('感知客户端配置','command_client_config'),('ppb','ppb_command'),
                    ('手机感知','command_phone_perception'),('flow','flow_command')]
        for name, method in commands:
            before = {id(item) for item in star_handlers_registry}
            self.context.register_commands('astrbot_plugin_virtual_body',name,'TLS原生手机与节奏',0,
                                           getattr(self.phone,method))
            for item in star_handlers_registry:
                if id(item) not in before:
                    item.handler_module_path = type(self.plugin).__module__
                    self._owned_commands.append(item)

    def _remove_phone_commands(self):
        from astrbot.core.star.star_handler import star_handlers_registry
        owned = {id(item) for item in self._owned_commands}
        for item in list(star_handlers_registry):
            if id(item) in owned: star_handlers_registry.remove(item)
        self._owned_commands.clear()

    async def start(self):
        if self._closed: return
        insight = self._make_insight()
        insight.active = False
        if (self.plugin._cfg_bool('living_insight_native_enabled', False)
                and self.legacy('astrbot_plugin_insight_center') is None):
            insight.active = True
            result = await insight.register_job(replace_existing=True)
            if result.get('state') != 'registered': insight.active = False
            if insight.active: self._register_tools('insight')
        if isinstance(self.plugin._cfg('living_phone', None), dict):
            phone = self._make_phone()
            if (self.plugin._cfg_bool('living_phone_native_enabled', False)
                    and self.legacy('astrbot_plugin_phone_perception') is None):
                self._restore_continuity(phone)
                if self.legacy('astrbot_plugin_dialogue_flow') is not None:
                    raise RuntimeError('standalone dialogue flow still owns pacing')
                await self._pause_phone_companion()
                try:
                    if not phone.activate(start_tasks=True):
                        raise RuntimeError('Phone source registration unavailable')
                    await self._share_phone_client()
                    self._install_flow_forwarders()
                    self._phone_phase = 'native'
                    self._register_tools('phone')
                    self._register_phone_commands()
                except BaseException:
                    await phone.terminate()
                    if self._flow_forwarders is not None: self._flow_forwarders.restore_exact()
                    self._remove_tools('phone')
                    self._remove_phone_commands()
                    self._phone_phase = 'activation_failed'
                    self._save_flag('living_phone_native_enabled', False)
                    raise
        self._make_pc()
        from .host import LivingHost
        from .native_memory_adapter import NativeMemoryAdapter
        host = self._host()
        memory = getattr(getattr(host,'runtime',None),'memory',None)
        if (type(host) is LivingHost and type(memory) is NativeMemoryAdapter
                and getattr(host.runtime,'unified',None) is not None
                and getattr(host,'selected_persona',None) is not None):
            from .native_mc_takeover_runtime import NativeMCTakeoverRuntime
            if self.plugin._cfg_bool('living_mc_full_native_enabled',False):
                await self._full_mc_owner().start_if_configured()
                if self.mc_full is not None and self.mc_full.active:self._register_tools('mc')
            else:
                self.mc = NativeMCTakeoverRuntime(self.plugin, host)
                await self.mc.start()
        self.plugin._native_mc_takeover = self.mc
        from .native_pc_full_owner import NativePCFullOwner
        self.pc_full = NativePCFullOwner(self)
        from .native_business_delivery import NativeBusinessDelivery
        self._business_delivery = NativeBusinessDelivery(self)
        self.pc_full.send_chain = self._business_delivery.dispatch
        self.pc_full.platform_action = self._business_delivery.platform_action
        await self.pc_full.start_if_configured()
        self._configure_pc_daily()
        if self.pc_full.active:self._register_tools('pc_full')
        self.plugin._native_pc_full = self.pc_full
        self._refresh_native_crosslinks()
        self._toggle_full_commands('mc',self.mc_full is not None and self.mc_full.active)
        self._toggle_full_commands('pc',self.pc_full.active)
        self._make_proactive_chat()
        if self.plugin._cfg_bool('living_proactive_chat_native_enabled',False):
            await self._full_proactive_owner().start_if_configured()
        self._generation += 1

    def _full_mc_owner(self):
        if self._mc_full_owner is None:
            from .native_mc_full_owner import NativeMCFullOwner
            self._mc_full_owner = NativeMCFullOwner(self)
        return self._mc_full_owner

    def _full_proactive_owner(self):
        if self._proactive_full_owner is None:
            from .native_proactive_full_owner import NativeProactiveChatFullOwner
            self._proactive_full_owner=NativeProactiveChatFullOwner(self)
        return self._proactive_full_owner

    async def activate_proactive_full(self):
        await self._full_proactive_owner().activate()
        return self.status()

    async def stop_proactive_full(self):
        await self._full_proactive_owner().stop()
        return self.status()

    async def restore_proactive_full(self):
        await self._full_proactive_owner().restore_legacy()
        return self.status()

    async def activate_mc_full(self):
        await self._full_mc_owner().activate()
        self.plugin._native_mc_takeover = self.mc
        self._register_tools('mc')
        self._toggle_full_commands('mc',True)
        self._refresh_native_crosslinks()
        return self.status()

    async def stop_mc_full(self):
        await self._full_mc_owner().stop()
        self._remove_tools('mc')
        self._toggle_full_commands('mc',False)
        return self.status()

    async def restore_mc_full(self):
        self._toggle_full_commands('mc',False)
        self._remove_tools('mc')
        await self._full_mc_owner().restore_legacy()
        self.plugin._native_mc_takeover = self.mc
        return self.status()

    async def activate_pc_full(self):
        await self.pc_full.activate()
        self._configure_pc_daily()
        self._register_tools('pc_full')
        self._toggle_full_commands('pc',True)
        self._refresh_native_crosslinks()
        return self.status()

    async def stop_pc_full(self):
        daily=getattr(getattr(self._host(),'runtime',None),'pc_daily_lifecycle',None)
        if daily is not None:daily.stop()
        await self.pc_full.stop()
        self._remove_tools('pc_full')
        self._toggle_full_commands('pc',False)
        return self.status()

    async def restore_pc_full(self):
        self._toggle_full_commands('pc',False)
        self._remove_tools('pc_full')
        await self.pc_full.restore_legacy()
        return self.status()

    def _configure_pc_daily(self):
        host=self._host()
        if host is None or self.pc_full is None or not self.pc_full.active:return
        runtime=host.runtime
        previous=getattr(runtime,'pc_daily_lifecycle',None)
        if previous is not None:previous.stop()
        from .native_pc_goal_handoff import NativePCGoalHandoff
        from .native_pc_daily_lifecycle import NativePCDailyLifecycle
        service=self.pc_full.service
        def set_old_goal(enabled):
            if enabled is not False:raise RuntimeError('full_native_owner_cannot_reopen_old_goal_writer')
            service.enable_personal_goals=False
        handoff=NativePCGoalHandoff(service,self.context,
            source_current=lambda current:current is service and self.pc_full.active and service.native_source_current(),
            set_legacy_enabled=set_old_goal,
            native_closed=lambda:getattr(runtime,'pc_daily_lifecycle',None) is None or runtime.pc_daily_lifecycle.native_closed())
        defaults=self.plugin.config.get('living_pc_daily_settings',{})
        if not isinstance(defaults,dict) or set(defaults)!={'auto_generate','auto_progress','share_enabled','routine_enabled'}:
            defaults=dict(auto_generate=True,auto_progress=True,share_enabled=True,routine_enabled=True)
        daily=NativePCDailyLifecycle(runtime.scoped_daily_plans,runtime.personal_goals,
            getattr(runtime,'proactive_companion',None),context=self.context,handoff=handoff,
            authorize=lambda scope,operation:self.pc_full.active and host.authorized_scope(scope)
                and host._native_memory_allowed(scope),
            authorize_material=lambda scope:host.authorized_scope(scope) and host._native_memory_allowed(scope),
            persona_allowed=lambda scope,selected:service._tls_primary_scope==scope
                and isinstance(service._tls_source,dict) and service._tls_source.get('persona_id')==selected,
            clock=host.clock,defaults=defaults)
        daily.daily_source=service
        runtime.pc_daily_lifecycle=daily

    async def observe_native_event(self,event):
        host=self._host()
        if self._closed or host is None:return
        results={}
        if self.pc_full is not None and self.pc_full.active:
            observed=False
            try:
                observed=await self.pc_full.observe_event(event)
                results['pc']=dict(observed=bool(observed),state='observed' if observed else 'not_admitted')
                if observed:
                    scope=host.presence.peek_scope_for_session(str(getattr(event,'unified_msg_origin','')))
                    service=self.pc_full.service
                    binding=getattr(host.runtime.native_services,'persona_binding',None)
                    if binding is not None and isinstance(service._tls_source,dict):
                        binding.bind(scope,service._tls_source['persona_id'])
                    daily=getattr(host.runtime,'pc_daily_lifecycle',None)
                    if daily is not None:
                        identity=str(getattr(getattr(event,'message_obj',None),'message_id','') or '')
                        await daily.observe_scope(scope,identity)
            except Exception as exc:
                results['pc']=dict(observed=bool(observed),state='error',error_type=type(exc).__name__)
        if self.proactive_chat is not None and self.proactive_chat.active:
            try:
                observed=await self.proactive_chat.observe_event(event)
                results['proactive_chat']=dict(observed=bool(observed),state='observed' if observed else 'not_admitted')
            except Exception as exc:
                results['proactive_chat']=dict(observed=False,state='error',error_type=type(exc).__name__)
        self._native_ingress_results=results
        return dict(results)

    def _refresh_native_crosslinks(self):
        if self.mc_full is not None and self.mc_full.service is not None and self.pc_full is not None:
            api = self.pc_full.get_private_companion_api()
            self.mc_full.companion_api = api
            self.mc_full.service.native_companion_api = api

    def _make_proactive_chat(self):
        from .native_proactive_chat_host import NativeProactiveChatHost
        host=self._host()
        values=self.plugin.config.get('living_proactive_chat')
        if not isinstance(values,dict) or not values:
            path=Path(inspect.getfile(type(self.plugin))).resolve().parent.parent.parent/'config/astrbot_plugin_proactive_chat_config.json'
            values=json.loads(path.read_bytes()) if path.is_file() else {}
        self.proactive_chat=NativeProactiveChatHost(self.plugin,host,values,
            self.data_dir.parent/'astrbot_plugin_proactive_chat',
            legacy_closed=self._proactive_chat_legacy_closed,
            authorize=lambda scope:host.authorized_scope(scope) and host.runtime.native_services._delivery_allowed(scope))
        self.plugin._native_proactive_chat=self.proactive_chat
        return self.proactive_chat

    def _proactive_chat_legacy_closed(self):
        rows=[row for row in self.context.get_all_stars() if getattr(row,'root_dir_name',None)=='astrbot_plugin_proactive_chat']
        if len(rows)!=1 or getattr(rows[0],'activated',None) is not False:return False
        record=getattr(self.context,'_tls_native_proactive_chat_retired',None)
        old=getattr(rows[0],'star_cls',None)
        return old is None or (isinstance(record,dict) and record.get('owner') is old and record.get('drained') is True)

    def register_routes(self):
        from ...insight_web_api import NativeInsightWebApi
        from ...server_integration_web_api import NativeServerIntegrationWebApi
        self.plugin._native_insight_api = NativeInsightWebApi(self.plugin)
        self.plugin._native_insight_api.register_routes()
        self.plugin._native_server_api = NativeServerIntegrationWebApi(self.plugin)
        self.plugin._native_server_api.register_routes()
        if self.phone is not None: self.phone.register_routes()
        from ...pc_integration_web_api import NativePCIntegrationWebApi
        self.plugin._native_pc_integration_api = NativePCIntegrationWebApi(self.plugin)
        self.plugin._native_pc_integration_api.register_routes()
        from ...proactive_chat_native_web_api import NativeProactiveChatWebApi
        self.plugin._native_proactive_chat_api=NativeProactiveChatWebApi(self.plugin)
        self.plugin._native_proactive_chat_api.register_routes()
        from ...pc_daily_native_web_api import NativePCDailyWebApi
        self.plugin._native_pc_daily_api=NativePCDailyWebApi(self.plugin)
        self.plugin._native_pc_daily_api.register_routes()

    async def activate_insight(self):
        async with self._lock:
            if self._closed: raise RuntimeError('integrations stopped')
            if self.legacy('astrbot_plugin_insight_center') is not None:
                raise RuntimeError('retire the original Insight hooks before activation')
            service = self.insight or self._make_insight()
            service.active = True
            result = await service.register_job(replace_existing=True)
            if result.get('state') != 'registered':
                service.active = False
                raise RuntimeError('Insight task transfer unavailable')
            self._save_flag('living_insight_native_enabled', True)
            self._register_tools('insight')
            return self.status()

    def _save_continuity(self, streams, events, context):
        from ..state import _atomic_write
        raw = json.dumps({'schema':'tls.phone.continuity.v2',
                          'streams':_pack(streams), 'last_events':_pack(events),
                          'context':_pack(context)},
                         ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > 8*1024*1024: raise ValueError('phone continuity capacity')
        self._continuity.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(str(self._continuity), raw)
        self._continuity.chmod(0o600)

    def _restore_continuity(self, phone):
        if not self._continuity.exists(): return
        if self._continuity.stat().st_size > 8*1024*1024: raise ValueError('phone continuity capacity')
        value = json.loads(self._continuity.read_bytes())
        if value.get('schema') not in {'tls.phone.continuity.v1','tls.phone.continuity.v2'}:
            raise ValueError('phone continuity schema')
        phone.adopt_music_continuity(_unpack(value['streams']), _unpack(value['last_events']))
        if value['schema'] == 'tls.phone.continuity.v2':
            phone.adopt_context_continuity(_unpack(value['context']))

    @staticmethod
    def _phone_context(phone):
        return {name:deepcopy(getattr(phone,name)) for name in
                ('_last_inject_at','_last_inject_line','_same_line_count')}

    def _snapshot_phone(self):
        self._save_continuity(self.phone._music_provider._streams,
            self.phone._music_last_events, self._phone_context(self.phone))

    def _restore_prepared_wrapper(self):
        old = self._prepared_phone
        if (old is not None and self._prepared_terminate is not None
                and getattr(old.terminate, '__func__', None) is self._prepared_wrapper):
            old.terminate = self._prepared_terminate
        self._prepared_phone = self._prepared_terminate = self._prepared_wrapper = None

    async def _prepare_phone(self):
        """Prepare a one-time in-RAM capture at the original terminate boundary.

        The administrator subsequently uses AstrBot's normal deactivate API.
        This operation itself does not stop the original Phone or start ours.
        """
        async with self._lock:
            if self._closed: raise RuntimeError('integrations stopped')
            old = self.legacy('astrbot_plugin_phone_perception')
            if old is None: raise RuntimeError('original Phone instance required')
            if self.phone is not None and self.phone._active: raise RuntimeError('native Phone already active')
            if self.legacy('astrbot_plugin_dialogue_flow') is not None:
                raise RuntimeError('standalone dialogue flow still owns pacing')
            if self._prepared_phone is old: return self.status()
            if self._prepared_phone is not None: raise RuntimeError('different Phone transfer pending')
            host = self._host()
            pending_before_transfer = getattr(host,'phone_transfer_pending',False)
            await self._pause_phone_companion()
            music = getattr(host, 'native_phone_music', None)
            if music is not None:
                music.stop()
                if music.diagnostics().get('restore_pending'): raise RuntimeError('previous music owner restoration pending')
            config = deepcopy(dict(old.config))
            previous = self.plugin.config.get('living_phone', None)
            with self._config_lock:
                self.plugin.config['living_phone'] = config
                try: self.plugin.config.save_config()
                except Exception:
                    if previous is None: self.plugin.config.pop('living_phone', None)
                    else: self.plugin.config['living_phone'] = previous
                    raise
            if self.phone is not None: await self.phone.terminate()
            phone = self._make_phone(); phone.register_routes()
            original = old.terminate
            controller = self
            async def capture_then_terminate(instance):
                # All RAM is copied on this loop before the old terminate's
                # synchronous clear. A failed snapshot leaves the old instance
                # untouched and never pretends that the transfer completed.
                prior_stopping = instance._music_stopping
                entered_original = False
                try:
                    streams = deepcopy(instance._music_provider._streams)
                    events = deepcopy(instance._music_last_events)
                    context = controller._phone_context(instance)
                    phone.adopt_music_continuity(streams, events)
                    phone.adopt_context_continuity(context)
                    controller._save_continuity(streams, events, context)
                    instance._music_stopping = True
                    entered_original = True
                    await original()
                    phone.reload_persisted_state()
                    controller._phone_phase = 'legacy_closed'
                except BaseException:
                    if not entered_original:
                        instance._music_stopping = prior_stopping
                        if host is not None: host.phone_transfer_pending = pending_before_transfer
                    controller._phone_phase = 'transfer_failed'
                    raise
                finally:
                    if getattr(instance.terminate, '__func__', None) is capture_then_terminate:
                        instance.terminate = original
            self._prepared_terminate, self._prepared_wrapper = original, capture_then_terminate
            old.terminate = MethodType(capture_then_terminate, old)
            self._prepared_phone = old
            self._phone_phase = 'prepared_waiting_original_deactivation'
            return self.status()

    async def prepare_phone(self):
        host = self._host()
        prior_pending = getattr(host,'phone_transfer_pending',False)
        try:
            return await self._prepare_phone()
        except BaseException:
            if host is not None: host.phone_transfer_pending = prior_pending
            raise

    async def activate_phone(self):
        async with self._lock:
            if self._closed or self.phone is None: raise RuntimeError('Phone preparation required')
            if self.legacy('astrbot_plugin_phone_perception') is not None:
                raise RuntimeError('original Phone hooks and tasks still active')
            if self.legacy('astrbot_plugin_dialogue_flow') is not None:
                raise RuntimeError('standalone dialogue flow still owns pacing')
            if self._phone_phase != 'legacy_closed': raise RuntimeError('original terminate completion required')
            self.phone.reload_persisted_state()
            try:
                self._save_flag('living_phone_native_enabled', True)
                if not self.phone.activate(start_tasks=True):
                    raise RuntimeError('Phone source registration unavailable')
                await self._share_phone_client()
                self._install_flow_forwarders()
                self._register_tools('phone')
                self._register_phone_commands()
            except BaseException:
                host = self._host()
                if host is not None: host.phone_transfer_pending = True
                await self.phone.terminate()
                if self._flow_forwarders is not None: self._flow_forwarders.restore_exact()
                self._remove_tools('phone')
                self._remove_phone_commands()
                self._save_flag('living_phone_native_enabled', False)
                self._phone_phase = 'activation_failed'
                raise
            self._phone_phase = 'native'
            self._generation += 1
            return self.status()

    async def stop_phone(self):
        async with self._lock:
            await self._pause_phone_companion()
            if self.phone is not None:
                try:
                    if self.phone._active: self._snapshot_phone()
                finally:
                    await self.phone.terminate()
            self._restore_prepared_wrapper()
            if self._flow_forwarders is not None: self._flow_forwarders.restore_exact()
            self._remove_tools('phone')
            self._remove_phone_commands()
            self._save_flag('living_phone_native_enabled', False)
            self._phone_phase = 'native_closed'
            return self.status()

    async def stop_insight(self):
        async with self._lock:
            if self.insight is not None: await self.insight.close()
            self._remove_tools('insight')
            self._save_flag('living_insight_native_enabled', False)
            return self.status()

    def status(self):
        phone_active = self.phone is not None and self.phone._active and not self._closed
        insight_active = self.insight is not None and self.insight.active and not self._closed
        return {'ok':True, 'generation':self._generation,
            'phone':{'native_active':phone_active,
                     'legacy_active':self.legacy('astrbot_plugin_phone_perception') is not None,
                     'phase':self._phone_phase,
                     'runtime':self.phone.diagnostics() if self.phone is not None else None},
            'insight':{'native_active':insight_active,
                       'legacy_active':self.legacy('astrbot_plugin_insight_center') is not None,
                       'runtime':({'active':self.insight.active, 'metrics':dict(self.insight.metrics),
                                   'registration_receipt_present':self.insight._job_id is not None}
                                  if self.insight is not None else None)},
            'mc_full':self._mc_full_owner.status() if self._mc_full_owner is not None else {'active':False,'phase':'not_requested'},
            'pc_full':self.pc_full.status() if self.pc_full is not None else {'active':False,'phase':'not_requested'},
            'proactive_chat':self.proactive_chat.status() if self.proactive_chat is not None else {'active':False},
            'native_ingress':deepcopy(getattr(self,'_native_ingress_results',{})),
            'proactive_full':self._proactive_full_owner.status() if self._proactive_full_owner is not None else {'active':False,'phase':'not_requested'},
            'mc':dict(self.mc.status() if self.mc is not None else {'native_active':False},
                      legacy_active=self.legacy('astrbot_plugin_memory_companion') is not None),
            'pc':dict(self.pc.diagnostics() if self.pc is not None else {'active':False},
                      enabled=self.plugin._cfg_bool('living_pc_integration_enabled',False),
                      legacy_active=self.legacy('astrbot_plugin_private_companion') is not None)}

    async def close(self):
        self._closed = True
        self._generation += 1
        await self._pause_phone_companion()
        self._restore_prepared_wrapper()
        if self.pc is not None: self.pc.stop()
        if self.pc_full is not None: await self.pc_full.close()
        if self._proactive_full_owner is not None:await self._proactive_full_owner.close()
        elif self.proactive_chat is not None: await self.proactive_chat.stop()
        if self._mc_full_owner is not None and self.mc_full is not None:
            await self._mc_full_owner.close()
        elif self.mc is not None: await self.mc.close()
        if self.insight is not None: await self.insight.close()
        self._remove_tools('insight')
        self._remove_tools('phone')
        self._remove_tools('mc')
        self._remove_tools('pc_full')
        self._remove_phone_commands()
        if self.phone is not None:
            try:
                if self.phone._active: self._snapshot_phone()
            finally:
                await self.phone.terminate()
                if self._flow_forwarders is not None: self._flow_forwarders.restore_exact()

    async def activate_pc(self):
        async with self._lock:
            if self._closed or self.pc is None: raise RuntimeError('native reminder services unavailable')
            self._save_flag('living_pc_integration_enabled', True)
            return self.status()

    async def stop_pc(self):
        async with self._lock:
            self._save_flag('living_pc_integration_enabled', False)
            return self.status()

    async def activate_mc(self):
        async with self._lock:
            if self._closed or self.mc is None: raise RuntimeError('native memory context unavailable')
            await self.mc.activate()
            self._save_flag('living_mc_context_native_enabled', True)
            return self.status()

    async def stop_mc(self):
        async with self._lock:
            if self.mc is not None:
                summary=self.mc.status().get('summary',{})
                if summary.get('algorithm_active') or summary.get('recovery_required') or summary.get('controller_retained'):
                    raise RuntimeError('restore_summary_algorithm_before_context')
            if self.mc is not None and self.mc.explicit_installed():
                raise RuntimeError('stop_and_restore_explicit_branch_before_context')
            if self.mc is not None: self.mc.stop()
            self._save_flag('living_mc_context_native_enabled', False)
            return self.status()

    async def inspect_mc_summary(self):
        if self._closed or self.mc is None:raise RuntimeError('native MC source unavailable')
        return {'ok':True,'summary':await self.mc.inspect_summary()}

    async def activate_mc_summary(self):
        async with self._lock:
            if self._closed or self.mc is None:raise RuntimeError('native MC source unavailable')
            await self.mc.activate_summary()
            try:self._save_flag('living_mc_summary_native_enabled',True)
            except BaseException:
                # Do not leave a successful RAM swap hidden behind a failed
                # flag save. The same owned controller performs exact restore.
                await self.mc.restore_summary()
                raise
            return self.status()

    async def restore_mc_summary(self):
        async with self._lock:
            if self.mc is None:raise RuntimeError('native MC source unavailable')
            await self.mc.restore_summary()
            self._save_flag('living_mc_summary_native_enabled',False)
            return self.status()

    async def activate_mc_explicit(self):
        async with self._lock:
            if self._closed or self.mc is None:raise RuntimeError('native MC source unavailable')
            current=self.mc.status().get('explicit',{})
            if current.get('active') is True:return self.status()
            await self.mc.prepare_explicit()
            try:
                self._save_flag('living_mc_explicit_native_enabled',True)
                self.mc.open_explicit()
            except BaseException:
                self.mc.stop_explicit()
                raise
            return self.status()

    async def stop_mc_explicit(self):
        async with self._lock:
            if self.mc is not None:self.mc.stop_explicit()
            self._save_flag('living_mc_explicit_native_enabled',False)
            return self.status()

    async def restore_mc_explicit(self):
        async with self._lock:
            if self.mc is None:raise RuntimeError('native MC source unavailable')
            if self.mc.relationship_requested() or self.mc.profile_requested():raise RuntimeError('stop_other_claim_branches_before_shared_restore')
            self.mc.stop_explicit()
            self._save_flag('living_mc_explicit_native_enabled',False)
            await self.mc.restore_explicit()
            return self.status()

    async def activate_mc_relationship(self):
        async with self._lock:
            if self._closed or self.mc is None:raise RuntimeError('native MC source unavailable')
            if self.mc.status().get('relationship',{}).get('active') is True:return self.status()
            await self.mc.prepare_explicit(relationship=True)
            try:
                self._save_flag('living_mc_relationship_native_enabled',True)
                self.mc.open_relationship()
            except BaseException:
                self.mc.close_claims()
                raise
            return self.status()

    async def stop_mc_relationship(self):
        async with self._lock:
            if self.mc is not None:self.mc.stop_relationship()
            self._save_flag('living_mc_relationship_native_enabled',False)
            return self.status()

    async def restore_mc_relationship(self):
        async with self._lock:
            if self.mc is None:raise RuntimeError('native MC source unavailable')
            if self.mc.explicit_requested() or self.mc.profile_requested():raise RuntimeError('stop_other_claim_branches_before_shared_restore')
            self.mc.stop_relationship()
            self._save_flag('living_mc_relationship_native_enabled',False)
            await self.mc.restore_explicit()
            return self.status()

    async def activate_mc_profile(self):
        async with self._lock:
            if self._closed or self.mc is None:raise RuntimeError('native MC source unavailable')
            if self.mc.status().get('profile',{}).get('active') is True:return self.status()
            await self.mc.prepare_explicit(profile=True)
            try:
                self._save_flag('living_mc_profile_native_enabled',True)
                self.mc.open_profile()
            except BaseException:
                self.mc.close_claims()
                raise
            return self.status()

    async def stop_mc_profile(self):
        async with self._lock:
            if self.mc is not None:self.mc.stop_profile()
            self._save_flag('living_mc_profile_native_enabled',False)
            return self.status()

    async def restore_mc_profile(self):
        async with self._lock:
            if self.mc is None:raise RuntimeError('native MC source unavailable')
            if self.mc.explicit_requested() or self.mc.relationship_requested():
                raise RuntimeError('stop_other_claim_branches_before_shared_restore')
            self.mc.stop_profile()
            self._save_flag('living_mc_profile_native_enabled',False)
            await self.mc.restore_explicit()
            return self.status()

    async def restore_mc(self):
        async with self._lock:
            if self.mc is None: raise RuntimeError('memory context owner unavailable')
            await self.mc.restore_legacy()
            self._save_flag('living_mc_context_native_enabled', False)
            return self.status()

    async def restore_phone_helpers(self):
        async with self._lock:
            if self.phone is not None and self.phone._active:
                raise RuntimeError('native Phone still active')
            if self._flow_forwarders is not None:
                result = self._flow_forwarders.restore_exact(allow_legacy_restore=True)
                if result.get('state') != 'restored': raise RuntimeError('old helper restoration pending')
            if self.legacy('astrbot_plugin_phone_perception') is None:
                raise RuntimeError('restored original Phone owner required')
            host = self._host()
            runtime = getattr(host,'runtime',None)
            companion = getattr(runtime,'phone_companion',None)
            if companion is not None and self._prior_connector_parameters is not None:
                from .native_phone_connector import NativePhoneConnector
                connector = NativePhoneConnector(**self._prior_connector_parameters)
                await self._pause_phone_companion()
                await companion.connector.close()
                companion.connector = connector
                runtime.phone_connector = connector
                self._shared_connector = None
            if host is not None: host.phone_transfer_pending = False
            return self.status()
