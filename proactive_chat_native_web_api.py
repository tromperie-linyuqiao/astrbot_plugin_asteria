"""Independent proactive administration through normal AstrBot authentication."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import re

from astrbot.api.web import error_response, json_response, request

from .core.living.native_proactive_chat_host import NativeProactiveChatHost


PREFIX = '/astrbot_plugin_virtual_body/page/proactive-chat-native'


class _RevisionConflict(RuntimeError):
    pass


class NativeProactiveChatWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for path, method, handler in (
                ('status', 'GET', self.status), ('inspect', 'GET', self.inspect),
                ('session', 'GET', self.session), ('activate', 'POST', self.activate),
                ('stop', 'POST', self.stop), ('trigger', 'POST', self.trigger),
                ('admission', 'GET', self.admission),
                ('session', 'POST', self.update_session)):
            self.plugin.context.register_web_api(PREFIX + '/' + path, handler, [method],
                'TLS native independent proactive ' + path)

    def _service(self):
        username = getattr(request, 'username', None)
        if not isinstance(username, str) or not username.strip():
            raise PermissionError('normal AstrBot administrator login required')
        if getattr(self.plugin, '_stopping', False):
            raise RuntimeError('native proactive owner is stopping')
        service = getattr(self.plugin, '_native_proactive_chat', None)
        if service is None:
            host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
            service = getattr(host, 'native_proactive_chat', None)
        if not isinstance(service, NativeProactiveChatHost) or service._closed:
            raise RuntimeError('native independent proactive service unavailable')
        return service

    @staticmethod
    def _response(value):
        return json_response(value, headers={'Cache-Control': 'no-store'})

    async def _perform(self, callback):
        try:
            service = self._service()
        except PermissionError:
            return error_response('请登录AstrBot管理后台', status_code=401)
        except RuntimeError:
            return error_response('原生主动消息服务暂不可用', status_code=503)
        try:
            return self._response(await callback(service))
        except _RevisionConflict:
            return error_response('会话覆盖已有变化，请重新读取并比较草稿后再保存', status_code=409)
        except PermissionError:
            return error_response('请登录AstrBot后台，实际发送还需要当前真实私聊授权', status_code=403)
        except (ValueError, TypeError, KeyError):
            return error_response('参数或会话配置不兼容，请检查当前状态', status_code=400)
        except (RuntimeError, FileNotFoundError):
            return error_response('旧执行者未排空、配置不兼容或原状态文件不可用，请读取检查结果', status_code=409)
        except Exception:
            return error_response('操作结果待核对，请读取状态，不要重复提交', status_code=503)

    async def status(self):
        async def operation(service):
            return service.status()
        return await self._perform(operation)

    async def inspect(self):
        async def operation(service):
            return await service.prepare()
        return await self._perform(operation)

    async def _empty_operation(self, method):
        async def operation(service):
            body = await request.json(default=None)
            if body not in ({}, None):
                raise ValueError('ownership operation takes no caller-supplied authority')
            owner=getattr(self.plugin,'_native_server_integrations',None)
            if owner is None:raise RuntimeError('current native ownership controller required')
            return await getattr(owner,'activate_proactive_full' if method=='activate' else 'stop_proactive_full')()
        return await self._perform(operation)

    async def activate(self):
        return await self._empty_operation('activate')

    async def stop(self):
        return await self._empty_operation('stop')

    async def session(self):
        async def operation(service):
            query = dict(getattr(request, 'query', None) or {})
            if set(query) != {'session_id'}:
                raise ValueError('session query required')
            session = self._session_id(service, query['session_id'])
            return await self._session_snapshot(service, session)
        return await self._perform(operation)

    @staticmethod
    def _session_id(service, session):
        if (not isinstance(session, str) or not 1 <= len(session) <= 512
                or session != session.strip() or any(ord(char) < 32 for char in session)):
            raise ValueError('session required')
        normalized = service._normalize_session_id(session)
        if not service._get_base_session_config(normalized):
            raise ValueError('session not present in original configured scope')
        return normalized

    async def _session_snapshot(self, service, session):
        manager = service.session_override_manager
        if manager is None:
            raise RuntimeError('session override manager unavailable')
        policy=getattr(service,'policy_session',lambda value:value)(session)
        base = service._get_base_session_config(session)
        config = service._get_session_config(session)
        override = manager.get_override(policy)
        # The preserved manager logs save failures instead of propagating them.
        # A RAM-only value must never be presented as a persisted user setting.
        def read_persisted():
            path = manager.overrides_file
            if not path.exists():
                return {}
            if path.stat().st_size > 8 * 1024 * 1024:
                raise RuntimeError('session override storage capacity')
            document = json.loads(path.read_text(encoding='utf-8-sig'))
            if type(document) is not dict or type(document.get(policy, {})) is not dict:
                raise RuntimeError('session override storage format')
            return document.get(policy, {})
        persisted = await asyncio.to_thread(read_persisted)
        if self._service() is not service or service.session_override_manager is not manager:
            raise RuntimeError('native proactive service replaced')
        if (getattr(service,'policy_session',lambda value:value)(session)!=policy
                or manager.get_override(policy) != override or service._get_base_session_config(session) != base):
            raise _RevisionConflict('session configuration changed while reading persistence')
        encoded = json.dumps(dict(base=base, override=override), ensure_ascii=False,
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        return dict(ok=True, session_id=session, policy_session_id=policy, config=deepcopy(config), base=deepcopy(base),
            override=deepcopy(override), revision=hashlib.sha256(encoded).hexdigest(),
            persisted_verified=persisted == override, global_config_mutated=False,
            current_job_rescheduled=False, administration_grants_send_permission=False)

    @staticmethod
    def _changes(value):
        if type(value) is not dict or set(value) - {'enable', 'session_name', 'proactive_prompt', 'schedule_settings'}:
            raise ValueError('only displayed session settings are editable')
        if 'enable' in value and type(value['enable']) is not bool:
            raise ValueError('explicit session enabled flag required')
        for key, limit in (('session_name', 80), ('proactive_prompt', 16000)):
            if key in value and (type(value[key]) is not str or len(value[key]) > limit
                    or any(ord(char) < 32 and char not in '\n\r\t' for char in value[key])):
                raise ValueError('bounded session wording required')
        schedule = value.get('schedule_settings', {})
        if type(schedule) is not dict or set(schedule) - {'min_interval_minutes', 'max_interval_minutes', 'max_unanswered_times', 'quiet_hours'}:
            raise ValueError('only displayed schedule values are editable')
        for key, number in schedule.items():
            if key == 'quiet_hours':
                if (type(number) is not str
                        or len(number) > 143
                        or re.fullmatch(r'(?:[01]?[0-9]|2[0-3])-(?:[01]?[0-9]|2[0-3])'
                            r'(?:,(?:[01]?[0-9]|2[0-3])-(?:[01]?[0-9]|2[0-3])){0,23}', number) is None):
                    raise ValueError('quiet hours require 1 to 24 comma-separated hour-hour windows from 0 to 23')
                continue
            low, high = (0, 100) if key == 'max_unanswered_times' else (1, 525600)
            if type(number) is not int or not low <= number <= high:
                raise ValueError('integer session schedule value required')
        return deepcopy(value)

    async def update_session(self):
        async def operation(service):
            body = await request.json(default=None)
            if (type(body) is not dict or set(body) - {'session_id', 'changes', 'reset', 'expected_revision'}
                    or 'session_id' not in body or ('changes' in body) == ('reset' in body)):
                raise ValueError('session configuration fields required')
            session = self._session_id(service, body['session_id'])
            if body.get('reset', True) is not True:
                raise ValueError('explicit restore inheritance required')
            revision = body.get('expected_revision')
            if revision is not None and (type(revision) is not str or re.fullmatch('[a-f0-9]{64}', revision) is None):
                raise ValueError('current session revision required')
            changes = self._changes(body['changes']) if 'changes' in body else None
            lock = getattr(service, '_native_admin_override_lock', None)
            if lock is None:
                lock = asyncio.Lock()
                service._native_admin_override_lock = lock
            async with lock:
                current = await self._session_snapshot(service, session)
                if not current['persisted_verified']:
                    raise RuntimeError('session override RAM and storage differ; inspect original result')
                if revision is not None and revision != current['revision']:
                    raise _RevisionConflict('session override changed')
                manager = service.session_override_manager
                merged = manager.deep_merge(current['override'], changes) if changes is not None else {}
                effective = manager.deep_merge(current['base'], merged)
                schedule = effective.get('schedule_settings', {})
                if schedule.get('min_interval_minutes', 30) > schedule.get('max_interval_minutes', 900):
                    raise ValueError('maximum interval must not be smaller than minimum interval')
                if merged == current['override']:
                    return current
                # This is administration of an already configured UMO, not a
                # manual delivery. Runtime update_override additionally asks
                # for a current inbound lease; a normal administrator does not
                # create that lease while editing historical configuration.
                # The original manager still owns sanitization and persistence.
                if self._service() is not service:
                    raise RuntimeError('native proactive service replaced')
                policy=getattr(service,'policy_session',lambda value:value)(session)
                await manager.set_override(policy, merged)
                saved = await self._session_snapshot(service, session)
                if not saved['persisted_verified'] or saved['override'] != merged:
                    raise OSError('session override save not confirmed')
                return saved
        return await self._perform(operation)

    async def trigger(self):
        async def operation(service):
            body = await request.json(default=None)
            if not isinstance(body, dict) or set(body) != {'session_id', 'request_id'}:
                raise ValueError('stable manual request fields required')
            if not isinstance(body['request_id'], str) or re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', body['request_id']) is None:
                raise ValueError('stable request id required')
            return await service.trigger(body['session_id'], body['request_id'])
        return await self._perform(operation)

    async def admission(self):
        async def operation(service):
            query = dict(getattr(request, 'query', None) or {})
            if set(query) != {'session_id', 'request_id'}:
                raise ValueError('exact current admission query required')
            session = self._session_id(service, query['session_id'])
            identity = query['request_id']
            if not isinstance(identity, str) or re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', identity) is None:
                raise ValueError('stable request id required')
            result = await service.preview_admission(session, identity)
            if self._service() is not service:
                raise RuntimeError('native proactive service replaced during read')
            return dict(ok=True, admission=result, read_only=True, reservation=False,
                model_calls=0, sends=0, config_writes=0,
                historical_attempt_reason_proven=False)
        return await self._perform(operation)
