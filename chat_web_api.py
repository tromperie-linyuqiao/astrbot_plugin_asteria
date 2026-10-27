"""Authenticated Texas Chat entry points over AstrBot's existing ChatService.

The service owns conversations, generation, SSE and persistence. This small
bridge adds the missing owner check before a new main-session generation.
QQ settings require an existing, explicitly confirmed identity link. This
bridge does not grant delivery authority or create a second LLM path.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

from copy import deepcopy
from types import SimpleNamespace

from astrbot.core import sp

from astrbot.api.web import error_response, json_response, request, stream_response, file_response
from astrbot.dashboard.services.chat_service import ChatServiceError, build_webchat_unified_msg_origin, sanitize_upload_filename
from astrbot.core.utils.media_utils import detect_image_mime_type_async, MEDIA_MIME_EXTENSIONS
from astrbot.dashboard.services.persona_service import PersonaServiceError
from astrbot.dashboard.services.session_management_service import SessionManagementServiceError

from .core.living.chat_expressions import ChatExpressions, ChatExpressionError, ChatUserProfile, avatar_source, avatar_crop, avatar_preview
from .core.living.chat_sessions import ChatSessionState, touch_catalog, apply_chat_touch, chat_body_snapshot
from .core.living.chat_identity import QQ_PLATFORMS, identity_service, linked_memory
from .core.living.chat_notifications import drain_inbox
from .core.living.chat_workspace import ChatWorkspace, actual_app_scope, calendar_view
from .core.living.journal import JournalConflict
from .core.living.delivery_store import DeliveryConflict
from .core.living.native_expression_assets import NativeExpressionAssets
from .core.living.native_memory import NativeMemoryStore, NativeMemoryConflict
from .core.living.native_memory_adapter import NativeMemoryAdapter
from .core.living.models import private_scope


PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/chat'
MAX_MESSAGE_CHARS = 16000
MAX_BODY_BYTES = 65536
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 4
_MEDIA_TYPES = frozenset({'image', 'file', 'record', 'video'})
_SEND_FIELDS = frozenset({'session_id', 'message', 'enable_streaming',
                          'selected_provider', 'selected_model', 'files', 'parts', 'client_message_id'})


class _RequestError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def _session_id(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 256 or any(ord(char) < 32 for char in value)):
        raise _RequestError('会话编号无效')
    return value


class NativeChatWebApi:
    def __init__(self, plugin):
        self.plugin = plugin
        self._connect_lock = asyncio.Lock()
        self._inbox_lock = asyncio.Lock()

    def register_routes(self):
        for name, handler, method in (
                ('sessions', self.sessions, 'GET'), ('personas', self.personas, 'GET'),
                ('new', self.new, 'POST'), ('connect', self.connect, 'POST'),
                ('bookmarks', self.bookmarks_get, 'GET'), ('bookmarks', self.bookmarks_save, 'POST'),
                ('history', self.history, 'GET'), ('send', self.send, 'POST'),
                ('rename', self.rename, 'POST'),
                ('remove', self.remove, 'POST'),
                ('session-state', self.session_state_get, 'GET'),
                ('session-state', self.session_state_save, 'POST'),
                ('search', self.search, 'GET'), ('context', self.chat_context, 'GET'),
                ('proactive-state', self.proactive_state, 'GET'),
                ('memory-detail', self.memory_detail, 'GET'), ('memory-correct', self.memory_correct, 'POST'),
                ('regenerate', self.regenerate, 'POST'),
                ('expression-settings', self.expression_settings_get, 'GET'),
                ('expression-settings', self.expression_settings_save, 'POST'),
                ('expressions', self.expressions, 'GET'),
                ('expression-preview', self.expression_preview, 'GET'),
                ('expression-preference', self.expression_preference, 'POST'),
                ('expression-metadata', self.expression_metadata, 'POST'),
                ('actions', self.actions_get, 'GET'), ('actions', self.actions_save, 'POST'),
                ('body-state', self.body_state, 'GET'),
                ('identity', self.identity_get, 'GET'),
                ('identity/challenge', self.identity_challenge, 'POST'),
                ('identity/revoke', self.identity_revoke, 'POST'),
                ('occasions', self.occasions_get, 'GET'), ('occasions', self.occasions_save, 'POST'),
                ('workspace', self.workspace_get, 'GET'), ('workspace', self.workspace_save, 'POST'),
                ('calendar', self.calendar_get, 'GET'), ('calendar', self.calendar_save, 'POST'),
                ('perception/config', self.perception_get, 'GET'), ('perception/config', self.perception_save, 'POST'),
                ('perception/report', self.perception_report, 'POST'),
                ('user-avatar', self.user_avatar_get, 'GET'), ('user-avatar', self.user_avatar_save, 'POST'),
                ('upload', self.upload, 'POST'), ('file', self.file, 'GET')):
            self.plugin.context.register_web_api(
                PAGE_API_PREFIX + '/' + name, handler, [method],
                'TLS authenticated Texas Chat ' + name)

    def _bound(self):
        if getattr(self.plugin, '_stopping', False):
            raise _RequestError('聊天服务正在更新，请稍后重试', 503)
        username = request.username
        if not isinstance(username, str) or not username.strip():
            raise _RequestError('请先登录 AstrBot 后台', 401)
        try:
            service = request._request.app.state.services.chat
        except AttributeError as exc:
            raise _RequestError('AstrBot 聊天服务暂不可用', 503) from exc
        if service is None:
            raise _RequestError('AstrBot 聊天服务暂不可用', 503)
        return username, service

    @staticmethod
    def _error(exc):
        if isinstance(exc, _RequestError):
            return error_response(str(exc), status_code=exc.status_code)
        if str(exc) == 'Permission denied':
            return error_response('无权访问这个会话', status_code=403)
        if str(exc).startswith('Session ') and str(exc).endswith(' not found'):
            return error_response('会话不存在', status_code=404)
        return error_response('聊天请求无效', status_code=400)

    @staticmethod
    def _ok(data):
        return json_response({'status': 'ok', 'message': None, 'data': data})

    async def _body(self, limit=MAX_BODY_BYTES):
        raw = await request.body()
        if len(raw) > limit:
            raise _RequestError('消息过长')
        body = await request.json()
        if not isinstance(body, dict):
            raise _RequestError('需要 JSON 对象')
        return body

    async def sessions(self):
        try:
            username, service = self._bound()
            sessions = await service.get_sessions(username, 'webchat')
            try:
                expressions = self._expressions(service)
                state_store = ChatSessionState(expressions.journal, current=expressions.current)
                def decorate():
                    return [dict(row, tls_state=state_store.get(username, row['session_id'])) for row in sessions]
                sessions = await asyncio.to_thread(decorate)
            except (RuntimeError, OSError, ValueError):
                sessions = [dict(row, tls_state={'state': 'unavailable'}) for row in sessions]
            return self._ok(sessions)
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    def _persona_service(self):
        try:
            return request._request.app.state.services.personas
        except AttributeError as exc:
            raise _RequestError('角色列表暂不可用', 503) from exc

    async def personas(self):
        try:
            self._bound()
            values = await self._persona_service().list_personas(None, False)
            # PersonaService's full records contain private prompts. Project
            # only real IDs; AstrBot has no distinct persona display-name field.
            return self._ok([{'persona_id': item['persona_id'],
                              'display_name': item['persona_id']}
                             for item in values if isinstance(item.get('persona_id'), str)])
        except (_RequestError, PersonaServiceError) as exc:
            return self._error(exc)

    async def connect(self):
        """Adopt one durable owned APP conversation, creating only if absent."""
        try:
            body = await self._body()
            if set(body) - {'persona_id', 'preferred_session_id'}:
                raise _RequestError('长期连接参数无效')
            username, service = self._bound()
            expressions = self._expressions(service)
            scope = expressions.message_scope(username, 'long-term-connection')
            persona_id = body.get('persona_id')
            preferred = body.get('preferred_session_id')
            if persona_id is not None:
                _session_id(persona_id)
                detail = await self._persona_service().get_persona_detail({'persona_id': persona_id})
                if not isinstance(detail, dict) or detail.get('persona_id') != persona_id:
                    raise _RequestError('请选择现有的真实角色')
            if preferred is not None:
                _session_id(preferred)
            async with self._connect_lock:
                prior = await asyncio.to_thread(expressions.journal.fetch, 'tls.chat.connection', 'primary', scope)
                if prior:
                    session_id = prior['data']['session_id']
                    try:
                        _, _, _, session = await self._owned_chat(session_id)
                    except ChatServiceError as exc:
                        raise _RequestError('原长期聊天记录已不存在，请在后台恢复原会话，不会自动新建覆盖。', 409) from exc
                else:
                    sessions = await service.get_sessions(username, 'webchat')
                    candidates = ([preferred] if preferred else []) + [row['session_id'] for row in sessions if row.get('is_group') == 0]
                    session_id = None
                    seen = set()
                    for candidate in candidates:
                        if candidate in seen:
                            continue
                        seen.add(candidate)
                        try:
                            _, _, _, session = await self._owned_chat(candidate)
                        except ChatServiceError:
                            if candidate == preferred:
                                raise
                            continue
                        configured = await self._configured_persona(service, username, candidate)
                        if persona_id is not None and configured.get('configured_id') != persona_id:
                            continue
                        session_id = candidate
                        break
                    if session_id is None:
                        if persona_id is None:
                            raise _RequestError('首次连接请先在连接设置中选择德克萨斯的实际角色。', 409)
                        self._bound()
                        created = await service.new_session(username, 'webchat')
                        session_id = _session_id(created.get('session_id'))
                        _, _, _, session = await self._owned_chat(session_id)
                        umo = build_webchat_unified_msg_origin(session)
                        values = await sp.get_async(scope='umo', scope_id=umo, key='session_service_config', default={})
                        if not isinstance(values, dict):
                            raise _RequestError('会话配置不可用', 503)
                        values = dict(values, persona_id=persona_id)
                        rules = request._request.app.state.services.sessions
                        await rules.update_session_rule({'umo': umo, 'rule_key': 'session_service_config', 'rule_value': values})
                    configured = await self._configured_persona(service, username, session_id)
                    self._bound()
                    await asyncio.to_thread(expressions.journal.put, 'tls.chat.connection', 'primary', scope,
                        {'session_id': session_id, 'persona_id': configured.get('configured_id'), 'source': 'owned_webchat_connection'},
                        expected_revision=0, authorize=expressions.current)
                state_store = ChatSessionState(expressions.journal, current=expressions.current)
                state = await asyncio.to_thread(state_store.get, username, session_id)
                if state['archived']:
                    await asyncio.to_thread(state_store.save, username, session_id, {'archived': False},
                        expected_revision=state['revision'])
                snapshot = await service.get_session(username, session_id)
                configured = await self._configured_persona(service, username, session_id)
                return self._ok({'session_id': session_id, 'platform_id': 'webchat', 'creator': username,
                    'display_name': session.display_name, 'created_at': str(session.created_at),
                    'persona_id': configured.get('configured_id'), 'persona': configured,
                    'primary': True, 'history_count': len(snapshot.get('history', [])),
                    'tls_state': await asyncio.to_thread(ChatSessionState(expressions.journal,
                        current=expressions.current).get, username, session_id)})
        except (_RequestError, ChatServiceError, PersonaServiceError, SessionManagementServiceError,
                RuntimeError, OSError, ValueError, KeyError) as exc:
            return self._expression_error(exc)

    async def bookmarks_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, service, _, _ = await self._owned_chat(session_id)
            expressions = self._expressions(service)
            scope = expressions.message_scope(username, session_id)
            single = request.query.get('message_id')
            if single is not None:
                if not str(single).isdigit():
                    raise _RequestError('收藏消息编号无效')
                marker = await asyncio.to_thread(expressions.journal.fetch, 'tls.chat.bookmarks', str(single), scope)
                if marker is None or marker['data'].get('enabled') is not True:
                    raise _RequestError('这条消息尚未收藏', 404)
                record = await service.db.get_platform_message_history_by_id(int(single))
                if record is None:
                    raise _RequestError('原消息已经删除，收藏标记仍保留', 404)
                if record.platform_id != 'webchat' or record.user_id != session_id:
                    raise _RequestError('收藏来源不属于当前会话', 403)
                return self._ok({'message_id': str(single), 'text': self._record_text(record.content),
                    'role': 'user' if record.content.get('type') == 'user' else 'assistant',
                    'media_in_original_history': any(isinstance(part, dict) and part.get('type') in _MEDIA_TYPES
                        for part in record.content.get('message', []))})
            rows = await asyncio.to_thread(expressions.journal.list, 'tls.chat.bookmarks', scope, limit=1000)
            result = []
            for row in rows:
                if row['data'].get('enabled') is not True:
                    continue
                identity = row['key']
                record = await service.db.get_platform_message_history_by_id(int(identity))
                found = record is not None and record.platform_id == 'webchat' and record.user_id == session_id
                result.append({'message_id': identity, 'enabled': True, 'revision': row['revision'],
                    'excerpt': self._record_text(record.content)[:1200] if found else '原消息已删除，收藏标记保留。',
                    'role': 'user' if found and record.content.get('type') == 'user' else 'assistant',
                    'available': found, 'saved_at': row['updated_at']})
                if len(result) >= 200:
                    break
            return self._ok({'session_id': session_id, 'items': result, 'limited': len(result) == 200})
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def bookmarks_save(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'message_id', 'enabled', 'expected_revision'}:
                raise _RequestError('收藏参数无效')
            session_id = _session_id(body.get('session_id'))
            username, service, _, _ = await self._owned_chat(session_id)
            identity = body.get('message_id')
            if type(identity) not in (str, int) or not str(identity).isdigit() or type(body.get('enabled')) is not bool:
                raise _RequestError('收藏需要真实消息编号和开关')
            identity = str(identity)
            expressions = self._expressions(service)
            scope = expressions.message_scope(username, session_id)
            old = await asyncio.to_thread(expressions.journal.fetch, 'tls.chat.bookmarks', identity, scope)
            record = await service.db.get_platform_message_history_by_id(int(identity))
            if record is None:
                if body['enabled'] or old is None:
                    raise _RequestError('原消息不存在', 404)
            elif record.platform_id != 'webchat' or record.user_id != session_id:
                raise _RequestError('不能收藏其他会话的消息', 403)
            result = await asyncio.to_thread(expressions.journal.put, 'tls.chat.bookmarks', identity, scope,
                {'enabled': body['enabled'], 'message_id': identity},
                expected_revision=body.get('expected_revision', old['revision'] if old else 0), authorize=expressions.current)
            return self._ok({'message_id': identity, 'enabled': body['enabled'], 'revision': result['revision']})
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def new(self):
        try:
            username, service = self._bound()
            body = await self._body()
            if set(body) - {'persona_id'}:
                raise _RequestError('新会话只接受已有角色编号')
            persona_id = body.get('persona_id')
            session_rules = None
            if persona_id is not None:
                _session_id(persona_id)
                detail = await self._persona_service().get_persona_detail({'persona_id': persona_id})
                if not isinstance(detail, dict) or detail.get('persona_id') != persona_id:
                    raise _RequestError('选中的角色不存在')
                try:
                    session_rules = request._request.app.state.services.sessions
                except AttributeError as exc:
                    raise _RequestError('会话设置暂不可用', 503) from exc
                if session_rules is None:
                    raise _RequestError('会话设置暂不可用', 503)
            self._bound()
            created = await service.new_session(username, 'webchat')
            if persona_id is not None:
                # This is the just-created owned webchat session, not a caller-
                # supplied origin or a QQ session alias. Use AstrBot's builder.
                session_id = _session_id(created.get('session_id'))
                if created.get('platform_id') != 'webchat':
                    raise _RequestError('新会话平台不匹配', 503)
                umo = build_webchat_unified_msg_origin(SimpleNamespace(
                    platform_id='webchat', is_group=False, creator=username,
                    session_id=session_id))
                original = await sp.get_async(scope='umo', scope_id=umo,
                                              key='session_service_config', default={})
                if not isinstance(original, dict):
                    raise _RequestError('新会话配置格式无效', 503)
                values = deepcopy(original)
                values['persona_id'] = persona_id
                self._bound()
                await session_rules.update_session_rule({'umo': umo,
                    'rule_key': 'session_service_config', 'rule_value': values})
            return self._ok(dict(created, persona_id=persona_id))
        except (_RequestError, ChatServiceError, PersonaServiceError,
                SessionManagementServiceError) as exc:
            return self._error(exc)

    async def history(self):
        try:
            username, service = self._bound()
            session_id = _session_id(request.query.get('session_id'))
            snapshot = await service.get_session(username, session_id)
            inbox_state = 'not_linked'
            try:
                links = identity_service(self.plugin)
                link = await asyncio.to_thread(links.get, username, session_id)
                if link and link.get('notifications') is True:
                    await self._owned_chat(session_id)
                    if await drain_inbox(self.plugin, service, username, session_id, lock=self._inbox_lock):
                        snapshot = await service.get_session(username, session_id)
                    inbox_state = 'enabled'
            except (RuntimeError, ValueError, OSError, PermissionError, JournalConflict):
                inbox_state = 'unavailable'
            persona = await self._configured_persona(service, username, session_id)
            # Existing history remains available if the optional expression
            # service is stopped; normal text/media is still the SDK source.
            try:
                expressions = self._expressions(service)
                pref = expressions.preference_scope(username, persona.get('configured_id'))
                scope = expressions.message_scope(username, session_id)
                snapshot = await asyncio.to_thread(self._typed_history, expressions, scope, pref, snapshot)
            except (RuntimeError, OSError, ValueError, KeyError):
                snapshot = dict(snapshot, expression_state='unavailable')
            try:
                state_store = ChatSessionState(self._expressions(service).journal,
                    current=lambda: not getattr(self.plugin, '_stopping', False))
                state = await asyncio.to_thread(state_store.get, username, session_id)
            except (RuntimeError, OSError, ValueError):
                state = {'state': 'unavailable'}
            return self._ok(dict(snapshot, persona=persona, tls_state=state, proactive_inbox=inbox_state))
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    def _expressions(self, service):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        assets = getattr(runtime, 'expression_assets', None)
        journal = getattr(assets, 'journal', None)
        if (not isinstance(assets, NativeExpressionAssets) or assets.active is not True
                or journal is None or getattr(journal, '_closed', True)):
            raise RuntimeError('共享表情库尚未启动')
        def current():
            return (not getattr(self.plugin, '_stopping', False)
                and getattr(getattr(getattr(self.plugin, '_presence', None), 'living_host', None), 'runtime', None) is runtime
                and getattr(runtime, 'expression_assets', None) is assets and assets.active is True
                and getattr(journal, '_closed', True) is False)
        return ChatExpressions(journal, assets, current=current, attachments_dir=service.attachments_dir,
                               touch_catalog=lambda: touch_catalog(self.plugin))

    async def _owned_expression(self, session_id):
        username, service = self._bound()
        await service.get_session(username, session_id)
        session = await service.db.get_platform_session_by_id(session_id)
        if (session is None or session.creator != username or session.session_id != session_id
                or session.platform_id != 'webchat' or session.is_group != 0):
            raise _RequestError('这个入口只接受自己的私有 APP 会话', 403)
        persona = await self._configured_persona(service, username, session_id)
        expressions = self._expressions(service)
        return username, service, expressions, expressions.preference_scope(username, persona.get('configured_id'))

    @staticmethod
    def _expression_error(exc):
        if isinstance(exc, (_RequestError, ChatServiceError)):
            return NativeChatWebApi._error(exc)
        if isinstance(exc, (JournalConflict, DeliveryConflict)):
            return error_response('设置已更新，请读取最新值再保存', status_code=409)
        if isinstance(exc, KeyError):
            return error_response('表情或动作不存在，请刷新', status_code=404)
        if isinstance(exc, (ChatExpressionError, ValueError)):
            return error_response(str(exc), status_code=400)
        return error_response('表达服务暂不可用，请稍后重试', status_code=503)

    async def expressions(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            _, _, expressions, scope = await self._owned_expression(session_id)
            result = await asyncio.to_thread(expressions.list, scope,
                query=request.query.get('query', ''), filter_name=request.query.get('filter', 'all'))
            return self._ok(result)
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def expression_preview(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            _, _, expressions, _ = await self._owned_expression(session_id)
            return self._ok(await asyncio.to_thread(expressions.preview, request.query.get('asset_id')))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def expression_preference(self):
        try:
            body = await self._body()
            if set(body) != {'session_id', 'asset_id', 'actor', 'changes'}:
                raise _RequestError('偏好需要会话、表情、使用者和修改内容')
            _, _, expressions, scope = await self._owned_expression(_session_id(body['session_id']))
            return self._ok(await asyncio.to_thread(expressions.preference,
                scope, body['asset_id'], body['actor'], body['changes']))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def expression_metadata(self):
        try:
            body = await self._body()
            if set(body) != {'session_id', 'asset_id', 'changes'}:
                raise _RequestError('素材语义需要会话、表情和修改内容')
            _, _, expressions, _ = await self._owned_expression(_session_id(body['session_id']))
            return self._ok(await asyncio.to_thread(expressions.metadata, body['asset_id'], body['changes']))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def actions_get(self):
        try:
            _, _, expressions, scope = await self._owned_expression(_session_id(request.query.get('session_id')))
            return self._ok(await asyncio.to_thread(expressions.actions, scope))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def actions_save(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'op', 'record', 'request_id'} or not {'session_id', 'op', 'record'} <= set(body):
                raise _RequestError('动作保存需要会话、操作及完整动作资料')
            _, _, expressions, scope = await self._owned_expression(_session_id(body['session_id']))
            return self._ok(await asyncio.to_thread(expressions.save_action,
                scope, body['op'], body['record'], body.get('request_id')))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def body_state(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, _, _, _ = await self._owned_chat(session_id)
            return self._ok(chat_body_snapshot(self.plugin, username, session_id))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def _avatar_view(self, service, username, profile):
        result = {key: profile[key] for key in ('crop', 'revision', 'updated_at')}
        result.update(data_url=None, source_data_url=None)
        saved = profile.get('avatar')
        if not saved:
            return result
        attachment_id = self._attachment_id(saved['attachment_id'])
        owner = self._owner(service, attachment_id)
        if not owner or owner['username'] != username or owner['session_id'] != saved['session_id']:
            raise _RequestError('头像来源不属于当前账户', 403)
        attachment = await service.db.get_attachment_by_id(attachment_id)
        if not attachment or attachment.type != 'image':
            raise _RequestError('头像原图已不可用', 404)
        path = self._file_path(service, attachment)
        raw = await asyncio.to_thread(path.read_bytes)
        if hashlib.sha256(raw).hexdigest() != owner['sha256']:
            raise _RequestError('头像原图校验失败', 409)
        result['data_url'] = await asyncio.to_thread(avatar_preview, raw, profile['crop'])
        result['source_data_url'] = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode()
        return result

    async def user_avatar_get(self):
        try:
            username, service = self._bound()
            expressions = self._expressions(service)
            profile = ChatUserProfile(expressions.journal, current=expressions.current).get(username)
            return self._ok(await self._avatar_view(service, username, profile))
        except (_RequestError, ChatServiceError, ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def user_avatar_save(self):
        try:
            body = await self._body(1024 * 1024)
            if set(body) - {'session_id', 'source_data_url', 'crop', 'reset', 'expected_revision'}:
                raise _RequestError('头像保存字段无效')
            session_id = _session_id(body.get('session_id'))
            username, service, _, _ = await self._owned_chat(session_id)
            expressions = self._expressions(service)
            store = ChatUserProfile(expressions.journal, current=expressions.current)
            old = store.get(username)
            revision = body.get('expected_revision')
            if type(revision) is not int or revision != old['revision']:
                raise _RequestError('头像已变化，请先重新读取', 409)
            reset = body.get('reset', False)
            if type(reset) is not bool:
                raise _RequestError('恢复默认需要开关值')
            crop = avatar_crop(body.get('crop', old['crop']))
            selected = None if reset else old.get('avatar')
            if not reset and body.get('source_data_url') is not None:
                raw = await asyncio.to_thread(avatar_source, body['source_data_url'])
                filename = uuid.uuid4().hex + '.jpg'
                root = Path(service.attachments_dir).resolve()
                descriptor = os.open(root / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
                class SelectedAvatar:
                    content_type = 'image/jpeg'
                    async def save(self, destination):
                        await asyncio.to_thread(Path(destination).write_bytes, raw)
                upload = SelectedAvatar();upload.filename = filename
                self._bound()
                saved = await service.save_uploaded_file(upload)
                attachment_id = self._attachment_id(saved.get('attachment_id'))
                attachment = await service.db.get_attachment_by_id(attachment_id)
                path = self._file_path(service, attachment)
                if path.stat().st_size != len(raw) or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
                    raise _RequestError('头像上传未完整保存', 503)
                owner = {'schema': 1, 'username': username, 'session_id': session_id,
                    'attachment_id': attachment_id, 'filename': path.name, 'display_name': '我的头像.jpg',
                    'type': attachment.type, 'mime_type': attachment.mime_type, 'size': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest()}
                with self._owner_path(service, attachment_id, create=True).open('x', encoding='utf-8') as output:
                    json.dump(owner, output, ensure_ascii=False);output.flush();os.fsync(output.fileno())
                selected = {'attachment_id': attachment_id, 'session_id': session_id}
            self._bound()
            profile = store.save(username, selected, crop, revision)
            return self._ok(await self._avatar_view(service, username, profile))
        except (_RequestError, ChatServiceError, ChatExpressionError, JournalConflict, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def _owned_chat(self, session_id):
        username, service = self._bound()
        snapshot = await service.get_session(username, session_id)
        session = await service.db.get_platform_session_by_id(session_id)
        if (session is None or session.creator != username or session.session_id != session_id
                or session.platform_id != 'webchat' or session.is_group != 0):
            raise _RequestError('这个入口只接受自己的私有 APP 会话', 403)
        return username, service, snapshot, session

    def _app_memory_resources(self, username, session):
        """An owned SDK session is not itself a live private-memory grant."""
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        memory = getattr(runtime, 'memory', None)
        scope = actual_app_scope(self.plugin, username, session)
        if scope is None:
            raise _RequestError('请在当前APP会话正常聊天后再管理记忆；QQ共享记忆保持只读', 403)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(memory, NativeMemoryAdapter) or not memory.allowed(scope)
                or not isinstance(memory.store, NativeMemoryStore) or memory.store._closed):
            raise _RequestError('当前APP原生记忆服务暂不可用', 503)
        return host, runtime, memory, memory.store, scope

    def _same_app_memory_resources(self, username, session, resources):
        current = self._app_memory_resources(username, session)
        if any(a is not b for a, b in zip(current[:4], resources[:4])) or current[4] != resources[4]:
            raise _RequestError('记忆来源已变化，请重新读取，不要重复提交', 409)

    @staticmethod
    def _chat_memory_record(record):
        value = {key: record.get(key) for key in ('id', 'content', 'revision', 'source_id',
            'evidence_kind', 'memory_type', 'created_at', 'updated_at')}
        return dict(value, source='app_native_memory', editable=True)

    def _chat_context_memory_items(self, memory, scope, items):
        result = []
        native = isinstance(memory, NativeMemoryAdapter) and isinstance(memory.store, NativeMemoryStore)
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('content'), str):
                continue
            value = {key: item.get(key) for key in ('id', 'content', 'source_id', 'evidence_kind')}
            record = None
            if native and memory.allowed(scope) and isinstance(item.get('id'), str):
                try: record = memory.store.get(scope, item['id'])
                except ValueError: pass
            editable = (record is not None and record['content'] == item['content']
                and record['source_id'] == item.get('source_id') and memory.allowed(scope))
            value.update(revision=record['revision'] if editable else None, editable=editable,
                source='app_native_memory' if editable else 'existing_tls_material',
                readonly_reason=None if editable else 'not_an_owned_app_native_record')
            result.append(value)
        return result

    @staticmethod
    def _chat_memory_error(exc):
        if isinstance(exc, NativeMemoryConflict):
            return error_response('记忆已被修改，请读取最新内容并比较后再保存', status_code=409)
        if isinstance(exc, KeyError):
            return error_response('当前APP会话没有这条可编辑原生记忆；QQ共享资料只读', status_code=404)
        if isinstance(exc, (_RequestError, ChatServiceError)):
            return NativeChatWebApi._error(exc)
        if isinstance(exc, PermissionError):
            return error_response('当前APP记忆授权已变化，请重新读取', status_code=403)
        if isinstance(exc, (ValueError, TypeError)):
            return error_response('记忆内容或版本无效', status_code=400)
        return error_response('记忆操作结果请回读同一记录核对，不要重复提交', status_code=503)

    async def memory_detail(self):
        try:
            query = dict(getattr(request, 'query', None) or {})
            if set(query) != {'session_id', 'id'}:
                raise _RequestError('记忆读取只接受当前会话与记录编号')
            session_id, identity = _session_id(query['session_id']), _session_id(query['id'])
            username, _, _, session = await self._owned_chat(session_id)
            resources = self._app_memory_resources(username, session)
            def read():
                store, scope = resources[3:]
                with store._lock:
                    self._same_app_memory_resources(username, session, resources)
                    record = store.get(scope, identity)
                    if record is None: raise KeyError(identity)
                    history = store.history(scope, identity)
                    self._same_app_memory_resources(username, session, resources)
                    return dict(record=self._chat_memory_record(record),
                        history=[dict(revision=row['revision'], operation=row['operation'],
                            changed_at=row['changed_at'], record=self._chat_memory_record(row['record']))
                            for row in history[-20:]],
                        history_total=len(history), history_limited=len(history) > 20)
            snapshot = await asyncio.to_thread(read)
            self._same_app_memory_resources(username, session, resources)
            return self._ok(dict(session_id=session_id, **snapshot, editable=True,
                shared_qq_read_only=True, state='current'))
        except (ChatServiceError, _RequestError, NativeMemoryConflict, PermissionError, KeyError,
                RuntimeError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return self._chat_memory_error(exc)

    async def memory_correct(self):
        try:
            body = await self._body()
            if set(body) != {'session_id', 'id', 'content', 'expected_revision'}:
                raise _RequestError('纠错仅接受当前APP会话、记录、内容与原版本')
            session_id, identity = _session_id(body['session_id']), _session_id(body['id'])
            content, revision = body['content'], body['expected_revision']
            if (not isinstance(content, str) or not content.strip() or len(content) > 6000
                    or any(ord(c) < 32 and c not in '\t\r\n' for c in content)
                    or type(revision) is not int or revision < 1):
                raise _RequestError('请输入1至6000字的记忆内容和有效原版本')
            username, _, _, session = await self._owned_chat(session_id)
            resources = self._app_memory_resources(username, session)
            def correct():
                store, scope = resources[3:]
                # Reuse the Store's reentrant transaction, history and lexical
                # index. Revocation before commit rolls back this correction.
                with store.transaction():
                    self._same_app_memory_resources(username, session, resources)
                    if store.get(scope, identity) is None: raise KeyError(identity)
                    record = store.correct(scope, identity, content, revision)
                    self._same_app_memory_resources(username, session, resources)
                    return self._chat_memory_record(record)
            record = await asyncio.to_thread(correct)
            self._same_app_memory_resources(username, session, resources)
            return self._ok(dict(session_id=session_id, record=record, editable=True,
                shared_qq_read_only=True, state='corrected'))
        except (ChatServiceError, _RequestError, NativeMemoryConflict, PermissionError, KeyError,
                RuntimeError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
            return self._chat_memory_error(exc)

    async def proactive_state(self):
        """Current own-APP diagnostics; never schedule or force a send."""
        try:
            query = dict(getattr(request, 'query', None) or {})
            if set(query) != {'session_id'}:
                raise _RequestError('主动状态只接受当前会话')
            session_id = _session_id(query['session_id'])
            username, _, _, session = await self._owned_chat(session_id)
            host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
            clock = getattr(host, 'clock', None)
            from time import time
            value = dict(session_id=session_id, available=False, active=False, enabled=False,
                state='unavailable', reason='native_proactive_unavailable', source_kind=None,
                destination=None, real_scope_available=False, pc_scope_matches=False, scheduled=False,
                next_evaluation_at=None, quiet_hours=None, timezone=None,
                checked_at=clock() if callable(clock) else time(), admission=None, latest_admission=None,
                read_only=True, reservation=False, background_push=False,
                historical_attempt_reason_proven=False)
            scope = actual_app_scope(self.plugin, username, session)
            if scope is None:
                value.update(state='waiting_for_real_scope', reason='waiting_for_real_app_message')
                return self._ok(value)
            value['real_scope_available'] = True
            links = identity_service(self.plugin)
            link = links.get(username, session_id)
            destination = ChatWorkspace(links).settings(username, session_id)['values']['proactive_destination']
            value['destination'] = destination
            if not link or link.get('app_scope') != scope or not link.get('app_persona'):
                value.update(state='blocked', reason='confirmed_app_binding_required')
                return self._ok(value)
            if destination not in {'chat_all', 'chat_text'}:
                value.update(state='blocked', reason='chat_destination_not_selected')
                return self._ok(value)
            from .core.living.native_proactive_chat_host import NativeProactiveChatHost
            service = getattr(self.plugin, '_native_proactive_chat', None)
            if (not isinstance(service, NativeProactiveChatHost) or service.host is not host
                    or service.runtime is not getattr(host, 'runtime', None) or service._closed):
                return self._ok(value)
            row = next((item for item in service.status()['sessions'] if item['session_id'] == scope['session_id']), None)
            if row is None:
                value.update(active=service.active, state='waiting_for_real_scope',
                    reason='waiting_for_authorized_app_source')
                return self._ok(value)
            config = service._get_session_config(scope['session_id']) or {}
            diagnostic_id = 'chat-state-' + hashlib.sha256(json.dumps(scope, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest()[:48]
            admission = await service.preview_admission(scope['session_id'], diagnostic_id)
            # The await does not keep an old binding, selected route or Host alive.
            if (getattr(self.plugin, '_native_proactive_chat', None) is not service
                    or actual_app_scope(self.plugin, username, session) != scope
                    or links.get(username, session_id) != link
                    or ChatWorkspace(links).settings(username, session_id)['values']['proactive_destination'] != destination):
                raise _RequestError('主动消息来源已变化，请重新读取', 409)
            fields = ('allowed', 'state', 'reason', 'checked_at', 'source', 'read_only',
                'model_stage_entered', 'queue_submission_attempted', 'queue_submission_returned', 'confirmed')
            current = {key: admission.get(key) for key in fields}
            current.update(read_only=True, reservation=False)
            previous = row.get('last_admission')
            previous = {key: previous.get(key) for key in fields} if isinstance(previous, dict) else None
            job = service.scheduler.get_job(scope['session_id'])
            next_time = getattr(job, 'next_run_time', None)
            blocking = row.get('blocking_reason') or (None if service.active else 'native_proactive_inactive')
            value.update(available=True, active=service.active, enabled=row['enabled'],
                state='blocked' if blocking else 'ready' if admission.get('allowed') is True else admission.get('state', 'blocked'),
                reason=blocking or admission.get('reason'), source_kind=row['source_kind'],
                pc_scope_matches=row['pc_scope_matches'], scheduled=job is not None,
                next_evaluation_at=next_time.timestamp() if next_time is not None else None,
                quiet_hours=config.get('schedule_settings', {}).get('quiet_hours', '1-7'),
                timezone=str(service.timezone), admission=current, latest_admission=previous)
            return self._ok(value)
        except (_RequestError, ChatServiceError, ChatExpressionError, PermissionError,
                RuntimeError, OSError, ValueError, TypeError, KeyError) as exc:
            return self._expression_error(exc)

    async def identity_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, _, _, _ = await self._owned_chat(session_id)
            return self._ok(await asyncio.to_thread(identity_service(self.plugin).status, username, session_id))
        except (_RequestError, ChatServiceError, ChatExpressionError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    def _check_occasions_target(self, username, session_id, links, link, scope, owner, service):
        fresh = links.get(username, session_id)
        if (not isinstance(fresh, dict) or fresh.get('active') is not True
                or fresh.get('link_id') != link.get('link_id') or fresh.get('qq_scope') != scope):
            raise _RequestError('QQ绑定已变更，请重新读取节日与生日设置', 409)
        source_current = getattr(service, 'native_source_current', None)
        if (getattr(self.plugin, '_native_pc_full', None) is not owner
                or getattr(owner, 'active', False) is not True
                or getattr(owner, 'service', None) is not service
                or getattr(service, 'active', False) is not True
                or not callable(source_current) or source_current() is not True):
            raise _RequestError('原生陪伴服务尚未就绪，请稍后重试', 409)
        data = getattr(service, 'data', None)
        users = data.get('users') if isinstance(data, dict) else None
        if not isinstance(users, dict) or not isinstance(users.get(scope['user_id']), dict):
            raise _RequestError('绑定的QQ尚无陪伴资料，请先在QQ正常私聊后重试', 409)
        return True

    async def _occasions_target(self, session_id):
        username, _, _, _ = await self._owned_chat(session_id)
        links = identity_service(self.plugin)
        link = links.get(username, session_id)
        if not isinstance(link, dict) or link.get('active') is not True:
            raise _RequestError('请先在真实QQ私聊确认绑定，再设置节日与生日', 409)
        if (link.get('username') != username or link.get('session_id') != session_id
                or not isinstance(link.get('link_id'), str) or not link['link_id']):
            raise _RequestError('QQ绑定资料无效，请重新确认绑定', 409)
        try:
            scope = private_scope(link.get('qq_scope'))
        except (TypeError, ValueError, KeyError) as exc:
            raise _RequestError('QQ绑定资料无效，请重新确认绑定', 409) from exc
        if scope != link.get('qq_scope') or scope['platform'] not in QQ_PLATFORMS:
            raise _RequestError('这个入口需要真实QQ私聊绑定', 409)
        owner = getattr(self.plugin, '_native_pc_full', None)
        service = getattr(owner, 'service', None)
        self._check_occasions_target(username, session_id, links, link, scope, owner, service)
        return username, links, link, scope, owner, service

    async def occasions_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, links, link, scope, owner, service = await self._occasions_target(session_id)
            authorize = lambda: self._check_occasions_target(
                username, session_id, links, link, scope, owner, service)
            result = await service.get_special_settings(scope['user_id'], authorize=authorize)
            self._check_occasions_target(username, session_id, links, link, scope, owner, service)
            return self._ok(result)
        except (_RequestError, ChatServiceError, ChatExpressionError, JournalConflict,
                KeyError, PermissionError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def occasions_save(self):
        try:
            body = await self._body()
            if set(body) != {'session_id', 'changes', 'expected_revision'}:
                raise _RequestError('节日与生日设置字段无效')
            if type(body['changes']) is not dict or not body['changes']:
                raise _RequestError('请选择要修改的节日与生日设置')
            if type(body['expected_revision']) is not int or body['expected_revision'] < 0:
                raise _RequestError('请先读取当前节日与生日设置')
            session_id = _session_id(body['session_id'])
            username, links, link, scope, owner, service = await self._occasions_target(session_id)
            authorize = lambda: self._check_occasions_target(
                username, session_id, links, link, scope, owner, service)
            result = await service.update_special_settings(
                scope['user_id'], body['changes'], body['expected_revision'], authorize=authorize)
            self._check_occasions_target(username, session_id, links, link, scope, owner, service)
            return self._ok(result)
        except (_RequestError, ChatServiceError, ChatExpressionError, JournalConflict,
                KeyError, PermissionError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def workspace_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, _, _, _ = await self._owned_chat(session_id)
            links = identity_service(self.plugin)
            workspace_settings = ChatWorkspace(links).settings(username, session_id)
            return self._ok(dict(settings=workspace_settings,
                identity=links.status(username, session_id),
                destinations={'qq':'QQ保持发送', 'chat_text':'纯文本主动消息改发Chat；图片与语音保留QQ',
                    'chat_all':'文字、图片与语音均发Chat'},
                supported_settings=list(workspace_settings['values']),
                phone_calendar_permission=False, background_push=False))
        except (_RequestError, ChatServiceError, ValueError, RuntimeError, OSError) as exc:
            return self._expression_error(exc)

    async def workspace_save(self):
        try:
            body = await self._body()
            if set(body) != {'session_id','changes','expected_revision'}: raise _RequestError('设置字段无效')
            session_id = _session_id(body['session_id'])
            username, _, _, _ = await self._owned_chat(session_id)
            result = await asyncio.to_thread(ChatWorkspace(identity_service(self.plugin)).save,
                username, session_id, body['changes'], body['expected_revision'])
            return self._ok(result)
        except (_RequestError, ChatServiceError, JournalConflict, ValueError, RuntimeError, OSError) as exc:
            return self._expression_error(exc)

    async def calendar_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, _, _, session = await self._owned_chat(session_id)
            links = identity_service(self.plugin)
            return self._ok(await calendar_view(self.plugin, links, username, session_id,
                actual_app_scope(self.plugin, username, session)))
        except (_RequestError, ChatServiceError, PermissionError, ValueError, RuntimeError, OSError) as exc:
            return self._expression_error(exc)

    async def calendar_save(self):
        try:
            body = await self._body()
            if set(body) - {'session_id','action','request_id','id','expected_revision','due_at','text','repeat','timezone'}:
                raise _RequestError('日程字段无效')
            session_id = _session_id(body.get('session_id'))
            username, _, _, session = await self._owned_chat(session_id)
            scope = actual_app_scope(self.plugin, username, session)
            if scope is None: raise _RequestError('请先在APP正常聊一句，登记当前会话后再添加日程', 409)
            agenda = self.plugin._presence.living_host.runtime.agenda
            action = body.get('action')
            recurring = {key:body[key] for key in ('repeat','timezone') if key in body}
            if action == 'create':
                result = await agenda.create(scope, body.get('request_id'), due_at=body.get('due_at'), text=body.get('text'), **recurring)
            elif action == 'update':
                result = await agenda.update(scope, body.get('id'), expected_revision=body.get('expected_revision'),
                    due_at=body.get('due_at'), text=body.get('text'), **recurring)
            elif action == 'cancel':
                result = await agenda.cancel(scope, body.get('id'), expected_revision=body.get('expected_revision'))
            elif action == 'restore':
                result = await agenda.restore(scope, body.get('id'), expected_revision=body.get('expected_revision'),
                    due_at=body.get('due_at'), text=body.get('text'), **recurring)
            else: raise _RequestError('请选择新增、编辑、取消或恢复日程')
            return self._ok(result)
        except (_RequestError, ChatServiceError, PermissionError, JournalConflict, ValueError, RuntimeError, KeyError, OSError) as exc:
            return self._expression_error(exc)

    async def perception_get(self):
        try:
            from .core.living.chat_perception import ChatPhonePerception
            query=dict(request.query or {})
            if set(query)!={'session_id','installation_id'}:raise _RequestError('请提供当前会话和本机标识')
            session_id=_session_id(query['session_id'])
            username,_,_,_=await self._owned_chat(session_id)
            service=ChatPhonePerception(self.plugin)
            return self._ok(await service.read_snapshot_current(username,session_id,query['installation_id']))
        except (_RequestError,ChatServiceError,ChatExpressionError,PermissionError,ValueError,RuntimeError,OSError)as exc:
            return self._expression_error(exc)

    async def perception_save(self):
        try:
            from .core.living.chat_perception import ChatPhonePerception
            body=await self._body();session_id=_session_id(body.get('session_id'))
            username,_,_,_=await self._owned_chat(session_id)
            service=ChatPhonePerception(self.plugin)
            return self._ok(await asyncio.to_thread(service.save,username,session_id,{k:v for k,v in body.items()if k!='session_id'}))
        except (_RequestError,ChatServiceError,ChatExpressionError,PermissionError,JournalConflict,ValueError,RuntimeError,OSError)as exc:
            return self._expression_error(exc)

    async def perception_report(self):
        try:
            from .core.living.chat_perception import ChatPhonePerception
            body=await self._body();session_id=_session_id(body.get('session_id'))
            username,_,_,_=await self._owned_chat(session_id)
            service=ChatPhonePerception(self.plugin)
            return self._ok(await service.report(username,session_id,{k:v for k,v in body.items()if k!='session_id'}))
        except (_RequestError,ChatServiceError,ChatExpressionError,PermissionError,JournalConflict,ValueError,RuntimeError,OSError)as exc:
            return self._expression_error(exc)

    async def identity_challenge(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'consent', 'notifications'} or not {'session_id', 'consent'} <= set(body):
                raise _RequestError('绑定参数无效')
            session_id = _session_id(body['session_id'])
            username, _, _, _ = await self._owned_chat(session_id)
            return self._ok(await asyncio.to_thread(identity_service(self.plugin).issue,
                username, session_id, consent=body['consent'], notifications=body.get('notifications', False)))
        except (_RequestError, ChatServiceError, ChatExpressionError, JournalConflict, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def identity_revoke(self):
        try:
            body = await self._body()
            if set(body) != {'session_id'}: raise _RequestError('解除绑定参数无效')
            session_id = _session_id(body['session_id'])
            username, _, _, _ = await self._owned_chat(session_id)
            return self._ok(await asyncio.to_thread(identity_service(self.plugin).revoke, username, session_id))
        except (_RequestError, ChatServiceError, ChatExpressionError, JournalConflict, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def session_state_get(self):
        try:
            identity = request.query.get('session_id')
            if not identity:
                return await self.sessions()
            session_id = _session_id(identity)
            username, service, _, _ = await self._owned_chat(session_id)
            expressions = self._expressions(service)
            store = ChatSessionState(expressions.journal, current=expressions.current)
            return self._ok(await asyncio.to_thread(store.get, username, session_id))
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def session_state_save(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'archived', 'mode', 'scene', 'reply_format', 'expected_revision'}:
                raise _RequestError('会话设置含不支持的字段')
            session_id = _session_id(body.get('session_id'))
            username, service, _, _ = await self._owned_chat(session_id)
            expressions = self._expressions(service)
            store = ChatSessionState(expressions.journal, current=expressions.current)
            changes = {key: body[key] for key in ('archived', 'mode', 'scene', 'reply_format') if key in body}
            if not changes:
                raise _RequestError('没有需要保存的会话设置')
            state = await asyncio.to_thread(store.save, username, session_id, changes,
                expected_revision=body.get('expected_revision'))
            return self._ok(state)
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def expression_settings_get(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            _, _, expressions, scope = await self._owned_expression(session_id)
            return self._ok(await asyncio.to_thread(expressions.settings_get, scope, session_id))
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def expression_settings_save(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'level', 'changes', 'patch', 'reset', 'expected_revision'}:
                raise _RequestError('表达设置含不支持的字段')
            session_id = _session_id(body.get('session_id'))
            _, _, expressions, scope = await self._owned_expression(session_id)
            level = body.get('level', 'session')
            if level == 'persona':
                level = 'role'
            return self._ok(await asyncio.to_thread(expressions.settings_save, scope, session_id,
                level=level, changes=body.get('changes', body.get('patch')),
                reset=body.get('reset', False), expected_revision=body.get('expected_revision')))
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    @staticmethod
    def _record_text(content):
        if not isinstance(content, dict):
            return ''
        parts = content.get('message', [])
        if isinstance(parts, str):
            return parts
        if not isinstance(parts, list):
            return ''
        return '\n'.join(part.get('text', '') for part in parts
            if isinstance(part, dict) and part.get('type') == 'plain'
            and part.get('chain_type') not in {'reasoning', 'tool_call', 'tool_call_result'}
            and isinstance(part.get('text'), str))

    async def search(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            _, _, snapshot, _ = await self._owned_chat(session_id)
            query = request.query.get('q', '')
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise _RequestError('请输入 1 到 200 字的搜索内容')
            query = query.strip()
            records = snapshot.get('history', [])
            values = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                text = self._record_text(record.get('content'))
                found = text.casefold().find(query.casefold())
                if found < 0:
                    continue
                values.append({'id': record.get('id'), 'message_id': record.get('id'),
                    'role': 'user' if (record.get('content') or {}).get('type') == 'user' else 'assistant',
                    'excerpt': text[max(0, found - 70):found + len(query) + 130],
                    'created_at': record.get('created_at')})
                if len(values) == 200:
                    break
            return self._ok({'session_id': session_id, 'query': query, 'items': values,
                'scanned': len(records), 'limit': 1000,
                'limited': len(records) >= 1000 or len(values) >= 200,
                'source': 'owned_astrbot_recent_history', 'hidden_reasoning_searched': False})
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    async def chat_context(self):
        try:
            session_id = _session_id(request.query.get('session_id'))
            username, service, _, session = await self._owned_chat(session_id)
            persona = await self._configured_persona(service, username, session_id)
            expressions = self._expressions(service)
            state = await asyncio.to_thread(ChatSessionState(expressions.journal,
                current=expressions.current).get, username, session_id)
            presence = getattr(self.plugin, '_presence', None)
            api = getattr(presence, 'api', None)
            runtime = getattr(getattr(presence, 'living_host', None), 'runtime', None)
            umo = build_webchat_unified_msg_origin(session)
            peek = getattr(api, 'peek_scope_for_session', None)
            scope = peek(umo) if callable(peek) else None
            memories, narrative = [], None
            memory_state = 'waiting_for_real_message'
            if (isinstance(scope, dict) and scope.get('platform') == 'webchat'
                    and scope.get('bot_id') == 'webchat' and scope.get('user_id') == username
                    and scope.get('session_id') == umo and scope.get('private') is True):
                memory = getattr(runtime, 'memory', None)
                if memory is not None and memory.allowed(scope):
                    material = await memory.context_material(scope=scope, limit=12)
                    memory_state = material.get('state', 'available' if material.get('ok') else 'unavailable')
                    if material.get('ok'):
                        memories = await asyncio.to_thread(self._chat_context_memory_items,
                            memory, scope, material.get('items', []))
                store = getattr(getattr(runtime, 'unified', None), 'narrative', None)
                if store is not None:
                    try:
                        record = await asyncio.to_thread(store.read_scene, scope)
                        if record:
                            narrative = record['data']['payload']
                    except (PermissionError, RuntimeError, ValueError):
                        pass
            links = identity_service(self.plugin)
            link = await asyncio.to_thread(links.get, username, session_id)
            shared = await linked_memory(self.plugin, links, link, direction='app') if link else dict(state='not_linked', sections=[])
            return self._ok({'session_id': session_id, 'persona': persona, 'tls_state': state,
                'mode': state['mode'], 'scene': state['scene'], 'narrative': narrative,
                'memories': memories, 'memory_state': memory_state,
                'memory_sharing': 'explicit_confirmed_pair' if link else 'existing_tls_authorized_owner_persona_policy',
                'qq_identity_linked': bool(link), 'shared_memory_state': shared['state'],
                'shared_memories': [dict(row, editable=False, readonly_reason='shared_qq_memory_read_only')
                    for row in shared['sections']]})
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError, PermissionError) as exc:
            return self._expression_error(exc)

    async def _resolved_references(self, service, username, session_id, parts):
        result = {}
        for part in parts or []:
            if not isinstance(part, dict) or part.get('type') != 'reference':
                continue
            identity = part.get('message_id')
            if type(identity) not in (str, int) or not str(identity).isdigit():
                raise _RequestError('引用消息编号无效')
            record = await service.db.get_platform_message_history_by_id(int(identity))
            if (record is None or record.platform_id != 'webchat' or record.user_id != session_id):
                raise _RequestError('只能引用当前会话的真实消息', 403)
            if not isinstance(record.content, dict):
                raise _RequestError('这条历史消息没有可引用的内容')
            text = self._record_text(record.content)
            if not text:
                text = '这条消息包含附件，引用不自动重新发送原附件。'
            result[str(identity)] = {'message_id': str(identity), 'text': text[:1200],
                'role': 'user' if record.content.get('type') == 'user' else 'assistant',
                'source': 'user_reference'}
        return result

    async def regenerate(self):
        try:
            body = await self._body()
            if set(body) - {'session_id', 'message_id', 'client_message_id', 'enable_streaming'}:
                raise _RequestError('重新回答参数无效')
            session_id = _session_id(body.get('session_id'))
            username, service, _, _ = await self._owned_chat(session_id)
            identity = body.get('message_id')
            if type(identity) not in (str, int) or not str(identity).isdigit():
                raise _RequestError('需要原助手消息编号')
            client_id = body.get('client_message_id')
            if (not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}', client_id)):
                raise _RequestError('重新回答需要稳定的请求编号')
            target = await service.db.get_platform_message_history_by_id(int(identity))
            if (target is None or target.platform_id != 'webchat' or target.user_id != session_id
                    or not isinstance(target.content, dict) or target.content.get('type') != 'bot'):
                raise _RequestError('只能对当前会话的真实助手回复重新作答', 403)
            prompt = '请重新回答我对这条回复提出的问题，换一种自然表达；保留原回复，不要把重新作答当作新的现实经历。'
            return await self._send_body({'session_id': session_id,
                'message': prompt, 'parts': [{'type': 'reference', 'message_id': str(identity)},
                    {'type': 'text', 'text': prompt}],
                'client_message_id': client_id,
                'enable_streaming': body.get('enable_streaming', True)})
        except (_RequestError, ChatServiceError, RuntimeError, OSError, ValueError, KeyError) as exc:
            return self._expression_error(exc)

    async def remove(self):
        try:
            username, service = self._bound()
            body = await self._body()
            if set(body) != {'session_id'}:
                raise _RequestError('删除会话只接受会话编号')
            session_id = _session_id(body['session_id'])
            await service.get_session(username, session_id)
            session = await service.db.get_platform_session_by_id(session_id)
            if (session is None or session.creator != username or session.session_id != session_id
                    or session.platform_id != 'webchat' or session.is_group != 0):
                raise _RequestError('无权删除这个会话', 403)
            # The fixed long-term connection must not be left pointing at a
            # deleted SDK session. Other owned historical sessions stay editable.
            async with self._connect_lock:
                try:
                    expressions = self._expressions(service)
                    primary = await asyncio.to_thread(expressions.journal.fetch, 'tls.chat.connection', 'primary',
                        expressions.message_scope(username, 'long-term-connection'))
                except (RuntimeError, OSError, ValueError):
                    raise _RequestError('暂时无法核对长期会话，请稍后再删除历史记录。', 503) from None
                if primary and primary['data'].get('session_id') == session_id:
                    raise _RequestError('当前长期聊天会话需要保留；你仍可导出记录或删除其他历史会话。', 409)
                self._bound()
                await service.delete_webchat_session(username, session_id)
            # Typed sidecars are retained as recovery/audit material; no shared
            # expression file or another session's assets are deleted here.
            return self._ok({'session_id': session_id, 'deleted': True})
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    @staticmethod
    def _typed_history(expressions, scope, preference_scope, snapshot):
        snapshot = deepcopy(snapshot)
        for record in snapshot.get('history', []):
            if not isinstance(record, dict) or not isinstance(record.get('content'), dict):
                continue
            content = record['content']
            role = 'user' if content.get('type') == 'user' else 'assistant'
            submission = expressions.checkpoint_submission(scope, record.get('llm_checkpoint_id'))
            if submission is not None:
                record['client_message_id'] = submission['client_message_id']
            existing = expressions.saved_parts(scope, role, record.get('id'))
            if existing is None:
                # Do not retroactively invent expression sends for old history.
                if submission is None:
                    continue
                if role == 'user':
                    media = [part for part in content.get('message', []) if isinstance(part, dict) and part.get('type') in _MEDIA_TYPES]
                    existing = expressions.bind_user(scope, preference_scope, submission, record['id'], media)
                else:
                    state = ChatSessionState(expressions.journal, current=expressions.current).get(scope['user_id'], scope['session_id'])
                    existing = expressions.assistant_parts(scope, preference_scope, record['id'], content,
                        context=submission.get('expression_context') or {'mode': state['mode'], 'scene': state['scene'],
                            'input_text': '\n'.join(part.get('text', part.get('description', '')) for part in submission.get('parts', []))})
            record['tls_parts'] = existing
            record['content']['tls_parts'] = existing
        snapshot['expression_state'] = 'available'
        return snapshot

    async def rename(self):
        """Rename an owned private webchat using the official chat service.

        The expected title is an optimistic precheck, not an atomic database CAS.
        The existing service performs its own owner check and update afterwards.
        """
        try:
            username, service = self._bound()
            body = await self._body()
            if set(body) != {'session_id', 'display_name', 'expected_display_name'}:
                raise _RequestError('改名需要会话编号、新标题及原始标题')
            session_id = _session_id(body['session_id'])
            name = body['display_name']
            expected = body['expected_display_name']
            if (not isinstance(name, str)
                    or any(unicodedata.category(char) == 'Cc' for char in name)):
                raise _RequestError('标题不能包含控制字符')
            name = name.strip()
            if not name or len(name) > 120:
                raise _RequestError('标题需为1至120字')
            if expected is not None and not isinstance(expected, str):
                raise _RequestError('原始标题必须为文字或null')
            await service.get_session(username, session_id)
            session = await service.db.get_platform_session_by_id(session_id)
            if session is None:
                raise _RequestError('会话不存在', 404)
            if (session.session_id != session_id or session.creator != username
                    or session.platform_id != 'webchat' or session.is_group != 0):
                raise _RequestError('无权修改这个会话', 403)
            if session.display_name != expected:
                raise _RequestError('会话标题已变化，请先同步再修改', 409)
            self._bound()  # Hot unload closes writes before the official service call.
            return self._ok(await service.update_session_display_name(username, session_id, name))
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    async def _configured_persona(self, service, username, session_id):
        """Optional saved configuration metadata, never an LLM selection proof.

        The caller must first complete ChatService.get_session's owner check.
        Re-read the official platform session before deriving its existing UMO.
        No QQ alias, default-role guess or additional authorization is created.
        """
        unavailable = {'configured_id': None, 'display_name': None, 'status': 'unavailable'}
        try:
            session = await service.db.get_platform_session_by_id(session_id)
            if (session is None or session.session_id != session_id
                    or session.platform_id != 'webchat' or session.creator != username
                    or session.is_group != 0):
                return unavailable
            umo = build_webchat_unified_msg_origin(session)
            values = await sp.get_async(scope='umo', scope_id=umo,
                                        key='session_service_config', default={})
            if not isinstance(values, dict):
                return unavailable
            configured_id = values.get('persona_id')
            if configured_id is None or configured_id in ('', '[%None]'):
                return dict(unavailable, status='unconfigured')
            if (not isinstance(configured_id, str) or len(configured_id) > 256
                    or any(ord(char) < 32 for char in configured_id)):
                return unavailable
            personas = await self._persona_service().list_personas(None, False)
            if not isinstance(personas, list):
                return unavailable
            for item in personas:
                if isinstance(item, dict) and item.get('persona_id') == configured_id:
                    # IDs/names come only from the existing persona service.
                    # Never expose a raw invalid configuration value or prompt.
                    return {'configured_id': item['persona_id'],
                            'display_name': item['persona_id'], 'status': 'configured'}
            return dict(unavailable, status='missing')
        except Exception:
            # History remains usable when optional metadata cannot be read.
            # Cancellation/BaseException still propagates to the original API.
            return unavailable

    async def send(self):
        try:
            return await self._send_body(await self._body())
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)

    async def _send_body(self, body):
        try:
            username, service = self._bound()
            if set(body) - _SEND_FIELDS:
                raise _RequestError('消息含不支持的参数')
            session_id = _session_id(body.get('session_id'))
            message = body.get('message', '')
            files = body.get('files', [])
            if (not isinstance(message, str) or len(message) > MAX_MESSAGE_CHARS
                    or not isinstance(files, list) or len(files) > MAX_ATTACHMENTS
                    or (not message.strip() and not files and not body.get('parts'))):
                raise _RequestError('请输入有效消息，每条最多 16000 字和 4 个附件')
            for item in files:
                if (not isinstance(item, dict) or set(item) != {'attachment_id'}
                        or not isinstance(item['attachment_id'], str)):
                    raise _RequestError('附件只接受上传返回的编号')
            streaming = body.get('enable_streaming', True)
            if type(streaming) is not bool:
                raise _RequestError('流式回复开关必须为布尔值')
            payload = {'session_id': session_id, 'message': message,
                       'enable_streaming': streaming}
            for key in ('selected_provider', 'selected_model'):
                value = body.get(key)
                if value is None:
                    continue
                if (not isinstance(value, str) or not value.strip() or len(value) > 256
                        or any(ord(char) < 32 for char in value)):
                    raise _RequestError('模型选项无效')
                payload[key] = value
            # ChatService.build_chat_stream does not check the session owner.
            # Reuse its existing owner-aware reader before any generation/write.
            snapshot = await service.get_session(username, session_id)
            session = await service.db.get_platform_session_by_id(session_id)
            if (session is None or session.session_id != session_id or session.creator != username
                    or session.platform_id != 'webchat' or session.is_group != 0):
                raise _RequestError('这个发送入口只接受自己的私有 APP 会话', 403)
            expressions = preference_scope = submission = native_receipt = None
            expression_context = {'input_text': message, 'mode': 'chat', 'conversation_text':
                '\n'.join(self._record_text(record.get('content')) for record in snapshot.get('history', [])[-6:])[-3000:]}
            try:
                expressions = self._expressions(service)
            except RuntimeError:
                if 'parts' in body:
                    raise _RequestError('组合表达服务尚未启动，请稍后重试', 503)
            if expressions is not None:
                persona = await self._configured_persona(service, username, session_id)
                preference_scope = expressions.preference_scope(username, persona.get('configured_id'))
                state_store = ChatSessionState(expressions.journal, current=expressions.current)
                session_state = await asyncio.to_thread(state_store.get, username, session_id)
                if session_state['archived']:
                    raise _RequestError('这个会话已归档，恢复后再继续聊天', 409)
                from .core.living.structured_reply import enabled as structured_enabled
                if structured_enabled(session_state):
                    # A full envelope must be validated before it is displayed;
                    # ordinary text keeps the SDK's real streaming path.
                    payload['enable_streaming']=False
                router=getattr(self.plugin,'_task_model_router',None)
                if router is not None and not payload.get('selected_provider'):
                    routed=router.select_provider_id('rp'if session_state['mode']=='roleplay'else'chat')
                    if routed:payload['selected_provider']=routed
                expression_context.update(persona_id=persona.get('configured_id'),
                    mode=session_state['mode'], scene=session_state['scene'],
                    roleplay=session_state['mode'] == 'roleplay')
                references = await self._resolved_references(service, username, session_id, body.get('parts'))
                attached = {}
                for part in body.get('parts') or []:
                    if isinstance(part, dict) and part.get('type') in {'attachment', 'image', 'file', 'record', 'video'}:
                        attachment_id = part.get('attachment_id')
                        attachment, owner = await self._allowed_attachment(service, username,
                            session_id, attachment_id, snapshot)
                        attached[attachment_id] = {'type': attachment.type, 'attachment_id': attachment_id,
                            'filename': owner['display_name'] if owner else Path(attachment.path).name}
                if len(attached) + len(files) > MAX_ATTACHMENTS:
                    raise _RequestError('每条组合消息最多 4 个附件')
                typed_parts, projected = await asyncio.to_thread(expressions.user_parts,
                    preference_scope, body.get('parts'), message, references=references, attachments=attached)
                if not typed_parts and not files:
                    raise _RequestError('请添加文字、动作、表情或附件')
                payload['message'] = projected
            if expressions is not None:
                # The original ChatService accepts typed plain/media in order.
                # Keep user actions and quotes explicit in its text projection.
                ordered = []
                for part in typed_parts:
                    kind = part.get('type')
                    if kind in _MEDIA_TYPES:
                        ordered.append({key: value for key, value in part.items()
                            if key in {'type', 'attachment_id', 'filename'}})
                    else:
                        text = part.get('text', '')
                        if kind == 'action':
                            text = '【用户角色互动输入（非现实感知）：' + part['label'] + '】' + part['description']
                            # All explicit actions use one parser below. Quoting
                            # keeps the legacy free-text observer from replaying
                            # either a custom action or a native verb/part pair.
                            text = '【用户主动选择的角色互动，触觉由TLS统一处理】' + json.dumps(part['label'] + '：' + part['description'], ensure_ascii=False)
                        elif kind == 'sticker':
                            asset = expressions.asset(part['asset_id'])
                            text = '【用户用聊天表情表达情绪，不是上传照片：' + asset['name'] + '】' + asset['meaning']
                        elif kind == 'reference':
                            text = '【引用当前会话' + ('你的回复' if part.get('role') == 'assistant' else '我的消息') + '】\n' + part.get('text', '')
                        if text:
                            ordered.append({'type': 'plain', 'text': text})
                payload['message'] = ordered
            if files:
                projected = payload['message']
                parts = list(projected) if isinstance(projected, list) else ([{'type': 'plain', 'text': projected}] if projected.strip() else [])
                seen = {part.get('attachment_id') for part in parts if isinstance(part, dict) and part.get('attachment_id')}
                for item in files:
                    attachment_id = item['attachment_id']
                    if attachment_id in seen:
                        raise _RequestError('同一附件不能重复添加')
                    seen.add(attachment_id)
                    attachment, owner = await self._allowed_attachment(
                        service, username, session_id, attachment_id, snapshot)
                    display_name = owner['display_name'] if owner else Path(attachment.path).name
                    parts.append({'type': attachment.type, 'attachment_id': attachment_id,
                                  'filename': display_name})
                payload['message'] = parts
            if expressions is not None:
                client_id = body.get('client_message_id') or ('tc-' + uuid.uuid4().hex)
                digest = hashlib.sha256(json.dumps(body, ensure_ascii=False,
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                message_scope = expressions.message_scope(username, session_id)
                submission = await asyncio.to_thread(expressions.begin, message_scope,
                    client_id, typed_parts, request_digest=digest)
                if submission['duplicate']:
                    return json_response({'status': 'error', 'message': '这个消息编号已提交，请先同步历史，不会重复发送。',
                        'data': {'client_message_id': client_id, 'state': submission['status'],
                                 'checkpoint_id': submission['checkpoint_id']}}, status_code=409)
                await asyncio.to_thread(expressions.mark_submission, message_scope, submission,
                    expression_context=expression_context)
                payload['_llm_checkpoint_id'] = submission['checkpoint_id']
                self._bound()
                native_receipt = apply_chat_touch(self.plugin, username, session_id, typed_parts)
                if native_receipt is not None:
                    await asyncio.to_thread(expressions.mark_submission, message_scope, submission,
                        native_touch=native_receipt)
            self._bound()  # A hot unload while checking ownership closes new work.
            stream = await service.build_chat_stream(username, payload)
            if expressions is not None:
                stream = self._expression_stream(stream, service, username, session_id,
                    expressions, message_scope, preference_scope, submission, expression_context, native_receipt)
            return stream_response(stream, content_type='text/event-stream', headers={
                'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)
        except (ChatExpressionError, KeyError, RuntimeError, OSError, ValueError) as exc:
            return self._expression_error(exc)

    async def _expression_stream(self, stream, service, username, session_id,
                                 expressions, message_scope, preference_scope, submission, expression_context=None, action_receipt=None):
        """Observe SDK save receipts; add presentation parts after real storage.

        The SDK keeps owning generation and persistence even if the subscriber
        disconnects. A later history read can recover typed parts through its
        exact server-owned checkpoint; an unknown send is never resubmitted.
        """
        final_state = 'stream_finished'
        yield 'data: '+json.dumps({'type':'tls_generation_state','data':{'phase':'queued','source':'sdk_run_accepted'}})+'\n\n'
        if action_receipt is not None:
            yield 'data: ' + json.dumps({'type': 'tls_action_result', 'data': action_receipt}, ensure_ascii=False) + '\n\n'
        async for chunk in stream:
            text = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk
            emitted=chunk
            if isinstance(text,str) and text.startswith('data: '):
                try:
                    frame=json.loads(text[6:].strip())
                    if frame.get('type')in {'plain','complete'}and isinstance(frame.get('data'),str)and frame['data']:
                        from .core.living.structured_reply import display
                        frame['data']=display(frame['data'])
                        emitted='data: '+json.dumps(frame,ensure_ascii=False)+'\n\n'
                        reasoning=frame.get('chain_type')=='reasoning'
                        phase='generating' if reasoning else 'streaming'
                        source='model_reasoning_received' if reasoning else 'model_output_received'
                        yield 'data: '+json.dumps({'type':'tls_generation_state','data':{'phase':phase,'source':source}})+'\n\n'
                    elif frame.get('type')=='error':
                        yield 'data: '+json.dumps({'type':'tls_generation_state','data':{'phase':'failed','source':'sdk_error'}})+'\n\n'
                except (ValueError,TypeError):pass
            yield emitted
            if not isinstance(text, str):
                continue
            for line in text.splitlines():
                if not line.startswith('data: '):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                kind = event.get('type')
                if kind == 'error':
                    final_state = 'generation_error'
                if kind not in {'user_message_saved', 'message_saved'}:
                    continue
                saved_id = (event.get('data') or {}).get('id')
                if saved_id is None:
                    continue
                try:
                    record = await service.db.get_platform_message_history_by_id(int(saved_id))
                    if (record is None or record.platform_id != 'webchat' or record.user_id != session_id
                            or record.llm_checkpoint_id != submission['checkpoint_id']):
                        continue
                    content = record.content
                    if kind == 'user_message_saved':
                        if not isinstance(content, dict) or content.get('type') != 'user':
                            continue
                        media = [part for part in content.get('message', []) if isinstance(part, dict) and part.get('type') in _MEDIA_TYPES]
                        parts = await asyncio.to_thread(expressions.bind_user, message_scope,
                            preference_scope, submission, saved_id, media)
                        role = 'user'
                    else:
                        if not isinstance(content, dict) or content.get('type') != 'bot':
                            continue
                        parts = await asyncio.to_thread(expressions.assistant_parts, message_scope,
                            preference_scope, saved_id, content, context=expression_context)
                        await asyncio.to_thread(expressions.mark_submission, message_scope, submission,
                            last_assistant_record_id=str(saved_id))
                        role = 'assistant'
                    payload = {'type': 'tls_parts', 'data': {'role': role, 'message_id': saved_id,
                        'client_message_id': submission['client_message_id'], 'parts': parts}}
                    yield 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
                except (OSError, RuntimeError, ValueError, KeyError, TypeError):
                    # Preserve a successful SDK reply if optional presentation
                    # could not be recorded; do not call the LLM/send again.
                    yield 'data: ' + json.dumps({'type': 'tls_parts_unavailable',
                        'data': {'message_id': saved_id, 'reason': 'expression_storage_unavailable'}}) + '\n\n'
        try:
            await asyncio.to_thread(expressions.mark_submission, message_scope, submission, status=final_state)
        except (OSError, RuntimeError, ValueError):
            pass  # Saved SDK messages remain authoritative; never resend.
        yield 'data: '+json.dumps({'type':'tls_generation_state','data':{'phase':'failed'if final_state=='generation_error'else'completed','source':'sdk_stream_finished'}})+'\n\n'

    @staticmethod
    def _attachment_id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise _RequestError('附件编号无效')
        return value

    @staticmethod
    def _history_parts(snapshot):
        for record in snapshot.get('history', []):
            content = record.get('content') if isinstance(record, dict) else None
            for part in content.get('message', []) if isinstance(content, dict) else []:
                if isinstance(part, dict) and part.get('type') in _MEDIA_TYPES:
                    yield part

    @staticmethod
    def _owner_path(service, attachment_id, *, create=False):
        root = Path(service.attachments_dir).resolve()
        directory = root / '.tls-chat-upload-owners'
        if create:
            directory.mkdir(mode=0o700, exist_ok=True)
        if directory.resolve().parent != root:
            raise _RequestError('附件登记目录无效', 503)
        return directory / (attachment_id + '.json')

    @classmethod
    def _owner(cls, service, attachment_id):
        path = cls._owner_path(service, attachment_id)
        if not path.exists():
            return None
        try:
            if path.is_symlink() or path.stat().st_size > 8192:
                raise ValueError('invalid owner record')
            value = json.loads(path.read_bytes())
            fields = {'schema', 'username', 'session_id', 'attachment_id', 'filename',
                      'display_name', 'type', 'mime_type', 'size', 'sha256'}
            if (not isinstance(value, dict) or set(value) != fields
                    or value['schema'] != 1 or value['attachment_id'] != attachment_id
                    or any(not isinstance(value[k], str) for k in fields - {'schema', 'size'})
                    or type(value['size']) is not int or not 0 < value['size'] <= MAX_FILE_BYTES
                    or not re.fullmatch('[0-9a-f]{64}', value['sha256'])):
                raise ValueError('invalid owner record')
            return value
        except (OSError, ValueError, TypeError) as exc:
            raise _RequestError('附件归属记录不可用', 403) from exc

    @staticmethod
    def _file_path(service, attachment):
        path = Path(attachment.path)
        resolved = path.resolve()
        roots = [Path(service.attachments_dir).resolve(), Path(service.webchat_img_dir).resolve()]
        if (path.is_symlink() or not any(resolved.is_relative_to(root) for root in roots)
                or not resolved.is_file() or not 0 < resolved.stat().st_size <= MAX_FILE_BYTES):
            raise _RequestError('附件文件不可用', 403)
        return resolved

    async def _allowed_attachment(self, service, username, session_id, attachment_id, snapshot):
        attachment_id = self._attachment_id(attachment_id)
        owner = self._owner(service, attachment_id)
        in_history = any(part.get('attachment_id') == attachment_id
                         for part in self._history_parts(snapshot))
        if owner is not None:
            if owner['username'] != username or owner['session_id'] != session_id:
                raise _RequestError('附件不属于这个会话', 403)
        elif not in_history:
            raise _RequestError('附件没有这个会话的归属证明', 403)
        attachment = await service.db.get_attachment_by_id(attachment_id)
        if attachment is None or attachment.type not in _MEDIA_TYPES:
            raise _RequestError('附件不存在', 404)
        path = self._file_path(service, attachment)
        if owner is not None and (owner['filename'] != path.name
                or owner['type'] != attachment.type or owner['mime_type'] != attachment.mime_type
                or owner['size'] != path.stat().st_size
                or owner['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest()):
            raise _RequestError('附件与上传记录不一致', 403)
        return attachment, owner

    async def upload(self):
        files = None
        try:
            username, service = self._bound()
            form = await request.form()
            if set(form.keys()) != {'session_id'} or len(form.getlist('session_id')) != 1:
                raise _RequestError('上传需要一个会话编号')
            session_id = _session_id(form.get('session_id'))
            await service.get_session(username, session_id)
            files = await request.files()
            if set(files.keys()) != {'file'} or len(files.getlist('file')) != 1:
                raise _RequestError('每次上传一个文件')
            uploaded = files.get('file')
            data = await uploaded.read(MAX_FILE_BYTES + 1)
            if not data or len(data) > MAX_FILE_BYTES:
                raise _RequestError('附件不能为空且不能超过 8 MiB')
            display_name = sanitize_upload_filename(uploaded.filename)
            if len(display_name) > 256:
                raise _RequestError('文件名过长')
            detected = await detect_image_mime_type_async(data, default_mime_type=None)
            guessed = mimetypes.guess_type(display_name)[0] or 'application/octet-stream'
            if detected:
                mime = detected
                suffix = MEDIA_MIME_EXTENSIONS.get(detected, '')
            else:
                if guessed.startswith('image/') or (uploaded.content_type or '').startswith('image/'):
                    raise _RequestError('图片内容与文件类型不匹配')
                # An explicitly selected system recording may have no suffix.
                # Preserve a standard declared audio MIME so ChatService uses
                # its existing Record/ASR path instead of generic file text.
                declared = (uploaded.content_type or '').split(';', 1)[0].lower()
                audio = {'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/aac', 'audio/amr',
                         'audio/wav', 'audio/x-wav', 'audio/webm', 'audio/3gpp', 'audio/x-m4a'}
                mime = declared if declared in audio else guessed
                suffix = Path(display_name).suffix
                if not re.fullmatch(r'\.[A-Za-z0-9]{1,12}', suffix):
                    suffix = ''
            # Reserve a fresh name exclusively. The existing saver writes only
            # this new reservation, never a prior user's same-name upload.
            root = Path(service.attachments_dir).resolve()
            for _ in range(4):
                filename = uuid.uuid4().hex + suffix
                try:
                    descriptor = os.open(root / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    os.close(descriptor)
                    break
                except FileExistsError:
                    continue
            else:
                raise _RequestError('无法分配新的附件文件名', 503)
            uploaded.filename = filename
            uploaded.content_type = mime
            await uploaded.seek(0)
            self._bound()
            saved = await service.save_uploaded_file(uploaded)
            attachment_id = self._attachment_id(saved.get('attachment_id'))
            attachment = await service.db.get_attachment_by_id(attachment_id)
            if attachment is None:
                raise _RequestError('上传结果未保存', 503)
            path = self._file_path(service, attachment)
            if (path.name != filename or path.stat().st_size != len(data)
                    or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest()):
                raise _RequestError('上传结果校验失败', 503)
            owner = {'schema': 1, 'username': username, 'session_id': session_id,
                     'attachment_id': attachment_id, 'filename': path.name,
                     'display_name': display_name, 'type': attachment.type,
                     'mime_type': attachment.mime_type, 'size': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()}
            owner_path = self._owner_path(service, attachment_id, create=True)
            with owner_path.open('x', encoding='utf-8') as output:
                json.dump(owner, output, ensure_ascii=False, separators=(',', ':'))
                output.flush()
                os.fsync(output.fileno())
            return self._ok({key: owner[key] for key in ('attachment_id', 'filename',
                'display_name', 'type', 'mime_type', 'size', 'session_id')})
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)
        finally:
            if files is not None:
                for key in files.keys():
                    for upload in files.getlist(key):
                        await upload.close()

    async def file(self):
        try:
            username, service = self._bound()
            session_id = _session_id(request.query.get('session_id'))
            filename = request.query.get('filename')
            if (not isinstance(filename, str) or not filename or len(filename) > 256
                    or '/' in filename or '\\' in filename or filename in {'.', '..'}
                    or any(ord(char) < 32 for char in filename)):
                raise _RequestError('文件名无效')
            snapshot = await service.get_session(username, session_id)
            for part in self._history_parts(snapshot):
                if filename not in {part.get('filename'), part.get('stored_filename')}:
                    continue
                attachment, owner = await self._allowed_attachment(service, username,
                    session_id, part.get('attachment_id'), snapshot)
                path = self._file_path(service, attachment)
                # A matching display name alone is insufficient: the history's
                # concrete stored name must also agree with the attachment row.
                stored = part.get('stored_filename') or part.get('filename')
                if stored != path.name:
                    raise _RequestError('历史附件引用不一致', 403)
                resolved, _ = await service.resolve_attachment_file(attachment.attachment_id)
                if Path(resolved).resolve() != path:
                    raise _RequestError('附件路径发生变化', 403)
                mime = attachment.mime_type or 'application/octet-stream'
                if attachment.type == 'image':
                    mime = await detect_image_mime_type_async(path, default_mime_type=None)
                    if not mime:
                        raise _RequestError('历史图片不可用', 403)
                display = owner['display_name'] if owner else part.get('filename') or path.name
                self._bound()
                return file_response(path, filename=None if attachment.type == 'image' else display,
                    content_type=mime, headers={'X-Content-Type-Options': 'nosniff',
                                               'Cache-Control': 'private, no-store'})
            raise _RequestError('文件尚未出现在这个会话的历史中', 403)
        except (_RequestError, ChatServiceError) as exc:
            return self._error(exc)
