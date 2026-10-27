"""Native TLS console over authenticated AstrBot extension routes.

Current plugin/host objects and bounded read-only legacy ownership observations
are inspected. There is no business proxy, sender activation or ownership change. Configuration edits are a
small CAS-protected subset of existing dynamic presentation/capture parameters.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import re
import sqlite3
import threading
import time

from astrbot.api.web import error_response, json_response, request

from .core.living.capability_registry import CapabilityRegistry
from .core.living.capability_catalog import build_capability_catalog
from .core.living.delivery_scheduler import NativeScheduler
from .core.living.delivery_store import DeliveryConflict
from .core.living.journal import LivingJournal
from .core.living.context_config_inheritance import ContextConfigInheritance
from .core.living.journal import JournalConflict
from .core.living.models import private_scope, scope_key
from .core.living.native_history_archive import NativeHistoryArchive
from .core.living.native_memory_adapter import NativeMemoryAdapter
from .core.living.native_memory_transfer import NativeMemoryTransfer
from .core.living.native_agenda import NativeAgenda
from .core.living.native_important_dates import NativeImportantDates
from .core.living.native_music_catalog import NativeMusicCatalog
from .core.living.native_music_library import NativeMusicLibrary
from .core.living.native_memo_notes import NativeMemoNotes
from .core.living.native_personal_goals import NativePersonalGoals
from .core.living.native_scoped_daily_plan import NativeScopedDailyPlans
from .core.living.native_profile_candidates import NativeProfileCandidates
from .core.living.native_expression_learning import NativeExpressionLearning
from .core.living.native_phone_companion import NativePhoneCompanion
from .core.living.native_expression_assets import NativeExpressionAssets
from .core.living.narrative import NarrativeStore
from .core.living.reminders import ReminderService


PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/console'
_FIELDS = ('platform', 'bot_id', 'user_id', 'character_id', 'session_id')
_DEFAULTS = {'living_memory_capture_enabled': False, 'presence_context_enabled': True,
             'presence_context_max_chars': 420, 'presence_repeat_seconds': 300}
_READONLY = {'living_system_enabled': False, 'living_memory_backend': 'legacy',
             'presence_layer_enabled': True, 'living_memory_sessions': []}
_INTEGER_LIMITS = {'presence_context_max_chars': (160, 1200), 'presence_repeat_seconds': (30, 3600)}


class _BadRequest(ValueError):
    pass


class _Conflict(RuntimeError):
    pass


class _Unavailable(RuntimeError):
    pass


def _scope(value):
    if not isinstance(value, dict) or set(value) - set(_FIELDS) - {'private'}:
        raise _BadRequest('需要完整的五项会话身份')
    for key in _FIELDS:
        field = value.get(key)
        if (not isinstance(field, str) or not field.strip() or field != field.strip()
                or len(field) > 256 or any(ord(char) < 32 for char in field)):
            raise _BadRequest('会话身份缺失或无效')
    if value.get('private', True) is not True:
        raise _BadRequest('控制台仅管理完整私聊范围')
    return private_scope(dict(value, private=True))


def _metrics(value):
    return {str(key): item for key, item in (value or {}).items()
            if isinstance(item, (int, float, bool))} if isinstance(value, dict) else {}


class NativeConsoleWebApi:
    def __init__(self, plugin):
        self.plugin = plugin
        lock = getattr(plugin, '_native_console_config_lock', None)
        if lock is None:
            lock = threading.RLock()
            plugin._native_console_config_lock = lock
        self._config_lock = lock

    def register_routes(self):
        register = self.plugin.context.register_web_api
        for path, handler, method in (
                ('overview', self.overview, 'GET'), ('config', self.config, 'GET'),
                ('config/save', self.save_config, 'POST'), ('tasks', self.tasks, 'GET'),
                ('config/inheritance', self.inherited_config, 'GET'),
                ('config/inheritance/save', self.save_inherited_config, 'POST'),
                ('tasks/cancel', self.cancel_task, 'POST')):
            register(PAGE_API_PREFIX + '/' + path, handler, [method],
                     'TLS native authenticated console ' + path)

    def _runtime(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        return getattr(host, 'runtime', None)

    def _value(self, key, default):
        reader = getattr(self.plugin, '_cfg', None)
        value = reader(key, default) if callable(reader) else self.plugin.config.get(key, default)
        return deepcopy(value)

    def _config_snapshot(self):
        values = {key: self._value(key, default) for key, default in _DEFAULTS.items()}
        revision = hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return {'values': values, 'revision': revision,
                'readonly': {key: self._value(key, default) for key, default in _READONLY.items()},
                'writable': callable(getattr(getattr(self.plugin, 'config', None), 'save_config', None))}

    def _save_config(self, body):
        changes = body.get('changes')
        if not isinstance(changes, dict) or not changes or set(changes) - set(_DEFAULTS):
            raise _BadRequest('只能修改控制台列出的动态参数')
        revision = body.get('expected_revision')
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise _BadRequest('需要载入配置时的版本')
        for key, value in changes.items():
            if key in _INTEGER_LIMITS:
                low, high = _INTEGER_LIMITS[key]
                if type(value) is not int or not low <= value <= high:
                    raise _BadRequest(f'{key} 必须是 {low}–{high} 的整数')
            elif type(value) is not bool:
                raise _BadRequest('开关参数必须为布尔值')
        config = getattr(self.plugin, 'config', None)
        saver = getattr(config, 'save_config', None)
        if not callable(saver):
            raise _Unavailable('configuration persistence unavailable')
        with self._config_lock:
            if self._config_snapshot()['revision'] != revision:
                raise _Conflict('configuration changed')
            old = {key: (key in config, deepcopy(config.get(key))) for key in changes}
            try:
                config.update(changes)
                saver()
            except BaseException:
                for key, (existed, value) in old.items():
                    if existed:
                        config[key] = value
                    else:
                        config.pop(key, None)
                raise
            return self._config_snapshot()

    def _inherited_config(self, body, *, write=False):
        level = body.get('level', 'global')
        scope = _scope(body.get('scope')) if level != 'global' else None
        runtime = self._runtime()
        journal = getattr(runtime, 'journal', None)
        if not (isinstance(journal, LivingJournal) and not journal._closed
                and getattr(runtime, 'active', False)):
            journal = None
        with self._config_lock:
            store = ContextConfigInheritance(self.plugin.config, journal)
            return store.save(body, scope, level) if write else store.snapshot(scope, level)

    async def _inherited_handle(self, write=False):
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        try:
            if write:
                body = await request.json(default=None)
                if not isinstance(body, dict) or set(body) - {'level','scope','changes','restore','expected_revision'}:
                    raise _BadRequest('配置请求字段无效')
            else:
                query = getattr(request, 'query', None) or {}
                body = {'level': query.get('level', 'global'),
                        'scope': {key: query.get(key) for key in _FIELDS}}
            result = await asyncio.to_thread(self._inherited_config, body, write=write)
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except JournalConflict:
            return error_response('配置或上级值已变更，请重新读取', status_code=409)
        except (ValueError, TypeError):
            return error_response('配置层级、范围或字段无效', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('配置存储或持久化暂不可用', status_code=503)

    async def inherited_config(self):
        return await self._inherited_handle()

    async def save_inherited_config(self):
        return await self._inherited_handle(write=True)

    def _lanes(self):
        runtime = self._runtime()
        reminders, delivery = getattr(runtime, 'reminders', None), getattr(runtime, 'delivery', None)
        result = []
        if isinstance(reminders, ReminderService):
            result.append(('reminders', '明确提醒', reminders))
        if isinstance(delivery, NativeScheduler):
            result.append(('delivery', '原生投递', delivery))
        return result

    def _tasks(self, scope):
        result = []
        for name, label, service in self._lanes():
            store = service.store
            if not service.active:
                result.append({'id': name, 'label': label, 'active': False,
                               'state': 'inactive', 'counts': {}, 'tasks': []})
                continue
            if not callable(getattr(store, 'task_counts', None)):
                result.append({'id': name, 'label': label, 'active': bool(service.active),
                               'state': 'read_unavailable', 'counts': {}, 'tasks': []})
                continue
            counts = store.task_counts(scope)
            rows = store.list_tasks(scope) if scope is not None and callable(getattr(store, 'list_tasks', None)) else []
            tasks = []
            for row in sorted(rows, key=lambda item: (item.get('due_at', 0), str(item.get('id', ''))))[:50]:
                item = {key: row.get(key) for key in ('id', 'state', 'text', 'due_at', 'expires_at', 'attempts', 'max_attempts')}
                item.update(lane=name, can_cancel=False)
                binding = row.get('reminder_binding')
                if name == 'reminders' and isinstance(binding, dict):
                    # Read only this native service's occurrence binding. Never
                    # expose consent, lease tokens, approvals or platform data.
                    with service.journal._lock:
                        raw = service.journal._db.execute(
                            'SELECT data FROM tls_reminder_occurrences WHERE id=? AND scope=?',
                            (binding.get('occurrence_id'), scope_key(scope))).fetchone()
                    occurrence = json.loads(raw[0]) if raw else None
                    if occurrence is not None:
                        item.update(reminder_id=occurrence['source_id'], revision=occurrence['revision'],
                                    can_cancel=(service.active and service._authorized(scope) and occurrence['status'] == 'active'
                                                and row.get('state') not in {'sending', 'unknown', 'confirmed'}))
                tasks.append(item)
            result.append({'id': name, 'label': label, 'active': bool(service.active), 'state': 'attached',
                           'environment': service.environment, 'counts': counts, 'tasks': tasks})
        return {'lanes': result, 'scope': scope, 'limit': 50,
                'state': 'attached' if result else 'not_attached',
                'note': '仅显示当前 TLS 原生队列；未接入的旧调度任务不在此列表中'}

    def _capabilities(self, overview, scope, *, authenticated=False):
        """Only existing runtime snapshots and registry metadata; no calls."""
        runtime = self._runtime()
        unified = getattr(runtime, 'unified', None)
        registry = getattr(unified, 'capabilities', None)
        snapshot = registry.status_snapshot() if isinstance(registry, CapabilityRegistry) else None
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        scope_available = bool(scope is not None and host is not None
            and callable(getattr(host, 'authorized_scope', None)) and host.authorized_scope(scope) is True)
        legacy_plugins={}
        getter=getattr(getattr(self.plugin,'context',None),'get_all_stars',None)
        if callable(getter):
            stars=getter()
            if isinstance(stars,(list,tuple)) and len(stars)<=512:
                for name in ('astrbot_plugin_memory_companion','astrbot_plugin_proactive_chat',
                             'astrbot_plugin_phone_perception','astrbot_plugin_insight_center',
                             'astrbot_plugin_private_companion'):
                    matching=[star for star in stars if getattr(star,'root_dir_name',None)==name]
                    if len(matching)==1:
                        active=getattr(matching[0],'activated',None)
                        legacy_plugins[name]={'loaded':True,'activated':active if type(active) is bool else None}
        observed_modules=list(overview.get('modules', []))
        from .core.living.native_phone_service.runtime import NativePhoneService
        from .core.living.native_insight_center import NativeInsightCenter
        phone_service=getattr(self.plugin,'_native_phone_service',None)
        insight=getattr(self.plugin,'_native_insight',None)
        phone_active=(isinstance(phone_service,NativePhoneService) and phone_service._active is True
                      and not getattr(self.plugin,'_stopping',False))
        observed_modules.extend([
            {'id':'phone_service','active':phone_active},
            {'id':'phone_flow','active':phone_active and phone_service.dialogue_flow._active is True},
            {'id':'insight','active':isinstance(insight,NativeInsightCenter) and insight.active is True
                and not getattr(self.plugin,'_stopping',False)},
        ])
        transfer=getattr(runtime, 'memory_transfer', None)
        observed_modules.append({'id':'memory_transfer',
            'active':isinstance(transfer, NativeMemoryTransfer) and transfer.active})
        from .core.living.native_core_tools import NativeCoreTools
        core_tools=getattr(self.plugin,'_native_core_tools',None)
        core_status=core_tools.status(scope) if isinstance(core_tools,NativeCoreTools) else {}
        from .core.living.native_mc_takeover_runtime import NativeMCTakeoverRuntime
        mc_runtime=getattr(self.plugin,'_native_mc_takeover',None)
        mc_status=(mc_runtime.status()
            if isinstance(mc_runtime,NativeMCTakeoverRuntime) else {})
        observed_modules.append({'id':'memory_summary',
            'active':mc_status.get('summary',{}).get('active')is True})
        integrations=getattr(self.plugin,'_native_server_integrations',None)
        def actual_status(owner):
            if (owner is None or integrations is None
                    or getattr(integrations,'context',None) is not self.plugin.context
                    or getattr(integrations,'plugin',None) is not self.plugin
                    or getattr(integrations,'_closed',True)):
                return {}
            try:
                value=owner.status()
                return value if isinstance(value,dict) else {}
            except Exception:
                return {'phase':'unknown','last_error':'status_read_unavailable'}
        mc_full_status=actual_status(getattr(integrations,'_mc_full_owner',None))
        pc_full_status=actual_status(getattr(integrations,'pc_full',None))
        independent_status=actual_status(getattr(integrations,'proactive_chat',None))
        independent_owner_status=actual_status(getattr(integrations,'_proactive_full_owner',None))
        if independent_owner_status:
            for key in ('active','phase','configured','original_plugin_active','last_error'):
                if key in independent_owner_status:
                    independent_status[key]=independent_owner_status[key]
        daily=getattr(runtime,'pc_daily_lifecycle',None)
        daily_status={}
        if daily is not None and callable(getattr(daily,'diagnostics',None)):
            try: daily_status=daily.diagnostics(scope)
            except PermissionError:
                daily_status=dict(daily.diagnostics(),scope_read_unavailable=True)
            except Exception:
                daily_status={'phase':'unknown','last_error':'scope_status_unavailable'}
        observed_modules.extend([
            {'id':'pc_daily','active':pc_full_status.get('active')is True},
            {'id':'proactive_chat','active':independent_status.get('active')is True}])
        return build_capability_catalog(modules=observed_modules, registry_snapshot=snapshot,
            flags={key:self._value(key, default) for key,default in {
                'living_memory_capture_enabled':False,'living_phone_companion_enabled':False,'living_exploration_enabled':False,
                'vb_enabled':True,'sp_enabled':True,'mo_enabled':True}.items()},
            presence=overview.get('presence'), proactive=overview.get('native_proactive'),
            random_handoff=overview.get('random_handoff'), scope_available=scope_available,
            authenticated=authenticated, legacy_plugins=legacy_plugins,core_tools=core_status,
            scope_selected=scope is not None,explicit_memory=mc_status.get('explicit',{}),
            relationship_memory=mc_status.get('relationship',{}),profile_memory=mc_status.get('profile',{}),
            summary_algorithm=mc_status.get('summary',{}),mc_full=mc_full_status,
            pc_full=pc_full_status,pc_daily=daily_status,independent_proactive=independent_status)

    def _overview(self, scope):
        runtime = self._runtime()
        presence = getattr(getattr(self.plugin, '_presence', None), 'api', None)
        native = getattr(runtime, 'memory', None)
        memory_active = isinstance(native, NativeMemoryAdapter) and native.active
        unified = getattr(runtime, 'unified', None)
        source_state = presence.diagnostics() if presence is not None else {}
        tasks = self._tasks(scope)
        archive = getattr(runtime, 'history_archive', None)
        archive_active = (isinstance(archive, NativeHistoryArchive) and not archive.closed
                          and archive.backend == 'native_history_archive'
                          and archive.retrieval_enabled is False)
        adoption = getattr(runtime, 'history_adoption', None)
        adoption_active = bool(archive_active and memory_active
            and getattr(adoption, 'backend', None) == 'native_history_adoption'
            and getattr(adoption, 'active', False)
            and getattr(adoption, 'archive', None) is archive
            and getattr(adoption, 'memory', None) is native.store)
        host_services=getattr(runtime,'native_services',None)
        service_diagnostics=host_services.diagnostics() if host_services is not None else {}
        proactive_status=dict(service_diagnostics.get('proactive_companion',{'configured':False}),
            legacy=service_diagnostics.get('legacy_proactive',{'state':'unavailable'}))
        memory = {'active': bool(memory_active), 'backend': getattr(native, 'backend', 'unavailable'),
                  'metrics': _metrics(getattr(native, 'metrics', None)) if memory_active else {},
                  'stats': native.store.stats(scope) if memory_active and scope is not None else None}
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        catalog_coordinator=getattr(host,'coordinator',None)
        catalog_reader=getattr(catalog_coordinator,'_reader',None)
        native_catalog_attached=(isinstance(catalog_reader,NativeMusicCatalog)
            and getattr(catalog_coordinator,'active',False) is True)
        modules = [
            {'id':'music_resolver','label':'音乐曲库解析','active':native_catalog_attached,
             'native_backend':isinstance(catalog_reader,NativeMusicCatalog),
             'reader_state':catalog_reader.state if isinstance(catalog_reader,NativeMusicCatalog) else 'not_attached',
             'detail':'曲目目录用于识别；实时播放来自已授权的感知数据'},
            {'id': 'memory', 'label': '基础记忆', 'active': bool(memory_active),
             'detail': '原生存储、检索与资料维护；画像、摘要及权限状态由对应模块和实际会话授权决定'},
            {'id': 'history', 'label': '历史档案', 'active': bool(archive_active),
             'manual_adoption_active': adoption_active,
             'detail': ('保留原文与原始分类；逐条人工核对后可收录到所选会话的原生记忆，原档案不改'
                        if adoption_active else '保留旧资料原文与原始分类，归属待确认；管理员只读审阅，不参与聊天召回')},
            {'id': 'context', 'label': '统一上下文', 'active': bool(getattr(unified, 'active', False)),
             'detail': '汇合记忆与已启用的身体、空间内容，保持既有人格'},
            {'id': 'agenda', 'label': '日程',
             'active': isinstance(getattr(runtime, 'agenda', None), NativeAgenda)
                and runtime.agenda.active and runtime.agenda.reminders.active,
             'detail': '一次性日程、版本化取消与恢复；周期日程和便签沿用TLS已接管的成熟实现'},
            {'id': 'important_dates', 'label': '重要日期与纪念日',
             'active': bool(getattr(runtime, 'active', False))
                and isinstance(getattr(runtime, 'important_dates', None), NativeImportantDates)
                and runtime.important_dates.active
                and runtime.important_dates.journal is getattr(runtime, 'journal', None)
                and isinstance(runtime.journal, LivingJournal) and not runtime.journal._closed,
             'detail': '原生日期资料与未来日期上下文；PC日期业务已原生接管，自动提醒仍受实际开关和发送授权限制'},
            {'id': 'music_library', 'label': '音乐资料库',
             'active': bool(getattr(runtime, 'active', False))
                and isinstance(getattr(runtime, 'music_library', None), NativeMusicLibrary)
                and runtime.music_library.active
                and runtime.music_library.journal is getattr(runtime, 'journal', None)
                and isinstance(runtime.journal, LivingJournal) and not runtime.journal._closed,
             'detail': '原生音乐资料维护、导入导出与匹配预览；元数据不是实际播放，手机实时来源保持原职责'},
            {'id': 'memo_notes', 'label': '便签与待办',
             'active': bool(getattr(runtime, 'active', False))
                and isinstance(getattr(runtime, 'memo_notes', None), NativeMemoNotes)
                and runtime.memo_notes.active
                and runtime.memo_notes.journal is getattr(runtime, 'journal', None)
                and isinstance(runtime.journal, LivingJournal) and not runtime.journal._closed,
             'detail': '原生便签资料、完成与恢复；定时和周期提醒由TLS接管的成熟业务与统一调度处理'},
            {'id':'scoped_daily_plans','label':'目标专用日计划',
             'active':bool(getattr(runtime,'active',False))
                and isinstance(getattr(runtime,'scoped_daily_plans',None),NativeScopedDailyPlans)
                and runtime.scoped_daily_plans.active is True
                and runtime.scoped_daily_plans.journal is getattr(runtime,'journal',None)
                and runtime.scoped_daily_plans.goals is getattr(runtime,'personal_goals',None)
                and not getattr(host,'_closed',True) and not getattr(self.plugin,'_stopping',False),
             'automatic_progression_active':False,'proactive_share_active':False,
             'detail':'未来明确范围的虚构目标计划；手动完成后通过原目标实例推进，自动时钟与主动分享默认关闭，旧全局日计划保留'},
            {'id':'profile_candidates','label':'画像候选与审核',
             'active':bool(getattr(runtime,'active',False))
                and isinstance(getattr(runtime,'profile_candidates',None),NativeProfileCandidates)
                and runtime.profile_candidates.active is True
                and getattr(runtime.profile_candidates,'store',None) is getattr(getattr(runtime,'memory',None),'store',None)
                and not getattr(host,'_closed',True) and not getattr(self.plugin,'_stopping',False),
             'detail':'同一原生库的画像证据、待审核原因、批准拒绝及单值替代；不是伪装manual的自动画像'},
            {'id': 'personal_goals', 'label': '个人目标资料与手动进度',
             'active': bool(getattr(runtime, 'active', False))
                and isinstance(getattr(runtime, 'personal_goals', None), NativePersonalGoals)
                and runtime.personal_goals.active is True
                and runtime.personal_goals.journal is getattr(runtime, 'journal', None)
                and isinstance(getattr(runtime, 'journal', None), LivingJournal)
                and getattr(host, 'journal', None) is runtime.journal
                and not runtime.journal._closed and not getattr(host, '_closed', True)
                and not getattr(self.plugin, '_stopping', False),
             'automatic_progression_active': False, 'proactive_share_active': False,
             'handoff_state': 'awaiting_legacy_handoff',
             'detail': '原生目标资料、来源、迁移预览和手动进度；活动自动推进与主动分享未接通，旧PC原消费职责保留'},
            {'id': 'narrative', 'label': '剧情与互动偏好',
             'active': bool(getattr(unified, 'active', False))
                and isinstance(getattr(unified, 'narrative', None), NarrativeStore),
             'detail': '明确的虚构场景、线索、状态及互动模式，不改写核心人格'},
            {'id': 'expression', 'label': '表达学习',
             'active': bool(getattr(runtime, 'active', False))
                and isinstance(getattr(runtime, 'expression_learning', None), NativeExpressionLearning),
             'detail': '从明确措辞反馈形成可编辑、可撤回的表达规则'},
            {'id': 'expression_assets', 'label': '表情与素材',
             'active': isinstance(getattr(runtime, 'expression_assets', None), NativeExpressionAssets)
                and runtime.expression_assets.active,
             'detail': '人工图片与标签；QQ 普通私聊回复后独立发送表情，遵守授权、冷却与去重，空库不发图'},
            {'id': 'phone_companion', 'label': 'App 图文互动',
             'active': isinstance(getattr(runtime, 'phone_companion', None), NativePhoneCompanion)
                and runtime.phone_companion.active and bool(self._value('living_phone_companion_enabled', False)),
             'detail': '真实打开 App 后按频率规则选择本地短句和一张新图；不是手机送达回执'},
            {'id': 'proactive', 'label': '主动陪伴',
             'active': bool(proactive_status.get('configured')
                and proactive_status.get('runtime',{}).get('active')),
             'configured': bool(proactive_status.get('configured')),
             'detail': 'TLS按统一频率准备表达并进入原生队列；实际执行取当前owner、会话授权及发送权限'},
            {'id': 'presence', 'label': '环境状态', 'active': bool(source_state.get('active')),
             'detail': '当前已登记的真实来源与可用状态'},
            {'id': 'body', 'label': '身体', 'active': getattr(self.plugin, '_store', None) is not None and bool(self._value('vb_enabled', True)),
             'detail': 'TLS 本地身体状态引擎'},
            {'id': 'space', 'label': '空间', 'active': getattr(self.plugin, '_manor_store', None) is not None and bool(self._value('sp_enabled', True)),
             'detail': 'TLS 本地庄园状态引擎'},
            {'id': 'mood', 'label': '心绪', 'active': bool(getattr(self.plugin, '_space_data_dir', '')) and bool(self._value('mo_enabled', True)),
             'detail': 'TLS 本地心绪规则与状态'},
        ]
        lanes = {lane['id']: lane for lane in tasks['lanes']}
        for name, label in (('reminders', '明确提醒'), ('delivery', '原生投递')):
            lane = lanes.get(name)
            modules.append({'id': name, 'label': label, 'active': bool(lane and lane['active']),
                            'detail': '当前原生服务已挂载' if lane else '当前运行时尚未挂载原生服务'})
        return {'sampled_at': time.time(), 'runtime_active': bool(getattr(runtime, 'active', False)),
                'memory': memory, 'presence': {'active': bool(source_state.get('active')),
                'context_enabled': bool(source_state.get('context_enabled')),
                'sources': source_state.get('registered_sources', []),
                'known_private_sessions': source_state.get('known_private_sessions', 0)},
                'modules': modules, 'tasks': tasks, 'scope': scope,
                'journal_capacity': self._journal_capacity(runtime),
                'native_proactive': proactive_status,
                'boundary': '模块运行状态不等同于旧插件已停用；控制台不切换生产执行权'}

    def _journal_capacity(self, runtime):
        """Counts from the attached journal only; no configuration estimates.

        stats() owns the existing connection lock. Its three COUNT statements
        are not a cross-table/cross-connection atomic snapshot. Audit retention
        is a rolling window, unlike the two admission limits.
        """
        result = {'state': 'unavailable', 'read_only': True,
                  'coverage': 'shared_runtime_journal_total',
                  'thresholds_percent': [70, 85, 95], 'threshold_policy': 'advisory_only',
                  'cross_table_atomic_snapshot': False, 'entries': []}
        journal = getattr(runtime, 'journal', None)
        if not isinstance(journal, LivingJournal) or getattr(runtime, 'active', False) is not True:
            return result
        try:
            names = ('max_records', 'max_observations', 'max_audit')
            limits = tuple(getattr(journal, name) for name in names)
            if any(type(value) is not int or value < 1 for value in limits):
                return result
            counts = journal.stats()
            if (not isinstance(counts, dict) or type(counts.get('schema_version')) is not int
                    or counts['schema_version'] != 1):
                return result
            entries = []
            for (identity, behavior), limit in zip((
                    ('checkpoints', 'reject_new_allow_existing_update'),
                    ('observations', 'reject_new_allow_existing_id'),
                    ('audit', 'rolling_retention')), limits):
                used = counts.get(identity)
                if type(used) is not int or used < 0:
                    return result
                level = ('full' if used >= limit else 'critical' if used * 100 >= limit * 95
                         else 'warning' if used * 100 >= limit * 85
                         else 'watch' if used * 100 >= limit * 70 else 'normal')
                if identity == 'audit' and used >= limit:
                    level = 'rolling'
                entries.append({'id': identity, 'used': used, 'limit': limit,
                                'percent': (used * 10000 // limit) / 100,
                                'level': level, 'on_limit': behavior})
            current_limits = tuple(getattr(journal, name) for name in names)
            if (self._runtime() is not runtime or getattr(runtime, 'journal', None) is not journal
                    or getattr(runtime, 'active', False) is not True or journal._closed
                    or any(type(value) is not int for value in current_limits) or current_limits != limits):
                return result
            return {**result, 'state': 'available', 'sampled_at': time.time(), 'entries': entries}
        except Exception:
            # A capacity diagnostic failure must neither expose an exception's
            # private path/text nor erase the rest of the console overview.
            return result

    async def _handle(self, action):
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        try:
            if action in {'config/save', 'tasks/cancel'}:
                body = await request.json(default=None)
                if not isinstance(body, dict):
                    raise _BadRequest('请求正文必须是 JSON 对象')
                if action == 'config/save':
                    result = await asyncio.to_thread(self._save_config, body)
                else:
                    scope = _scope(body.get('scope'))
                    reminder_id, revision = body.get('id'), body.get('expected_revision')
                    if (not isinstance(reminder_id, str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}', reminder_id)
                            or type(revision) is not int or revision < 1):
                        raise _BadRequest('提醒 ID 或版本无效')
                    service = next((service for name, _, service in self._lanes() if name == 'reminders'), None)
                    if service is None or not service.active:
                        raise _Unavailable('native reminders unavailable')
                    await service.cancel(scope, reminder_id, expected_revision=revision)
                    result = {'cancelled': True, 'id': reminder_id}
            else:
                query = getattr(request, 'query', None)
                values = {key: query.get(key) for key in _FIELDS if query is not None and query.get(key) is not None}
                scope = _scope(values) if values else None
                if action == 'config':
                    def read_config():
                        with self._config_lock:
                            return self._config_snapshot()
                    result = await asyncio.to_thread(read_config)
                else:
                    result = await asyncio.to_thread(self._tasks if action == 'tasks' else self._overview, scope)
                    if action=='overview' and getattr(self._runtime(),'native_services',None) is not None:
                        from .core.living.native_legacy_companion_inspection import inspect_legacy_companion, inspect_random_handoff
                        result['native_proactive']['legacy']=inspect_legacy_companion(getattr(self.plugin,'context',None))
                        result['random_handoff']=(inspect_random_handoff(getattr(self.plugin,'context',None),scope)
                            if scope is not None else {'state':'unknown','reason':'no_explicit_scope',
                                'random_gate_confirmed':False})
                    if action=='overview':
                        result.update(self._capabilities(result, scope, authenticated=True))
                        services=getattr(self._runtime(),'native_services',None)
                        if services is not None:
                            result['queue_authority']=services.queue_authority_status(scope)
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except _BadRequest as exc:
            return error_response(str(exc), status_code=400)
        except (_Conflict, DeliveryConflict):
            return error_response('数据已被修改，请刷新后重试', status_code=409)
        except KeyError:
            return error_response('当前范围中找不到该任务', status_code=404)
        except PermissionError:
            return error_response('当前范围没有原生任务操作权限', status_code=403)
        except (ValueError, TypeError):
            return error_response('控制台参数无效', status_code=400)
        except (RuntimeError, OSError, sqlite3.Error):
            return error_response('原生服务或配置存储暂不可用', status_code=503)
        except Exception:
            return error_response('控制台操作失败，请稍后重试', status_code=500)

    async def overview(self): return await self._handle('overview')
    async def config(self): return await self._handle('config')
    async def save_config(self): return await self._handle('config/save')
    async def tasks(self): return await self._handle('tasks')
    async def cancel_task(self): return await self._handle('tasks/cancel')
