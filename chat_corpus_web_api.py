"""Corpus and explicit preference maintenance through the existing Chat owner.

Root integration calls NativeChatCorpusWebApi(existing_chat_api).register_routes().
The normal LLM hook may call inject_chat_corpus_context(plugin, event, req).
No administrative scope or caller-selected persona is accepted from the App.
"""
from __future__ import annotations

import asyncio
import sqlite3

from astrbot.api.web import error_response, request
from astrbot.core import db_helper, sp
from astrbot.core.agent.message import TextPart
from astrbot.dashboard.services.chat_service import ChatServiceError, build_webchat_unified_msg_origin

from .core.living.chat_corpus import ChatCorpusLibrary
from .core.living.chat_expressions import ChatExpressions
from .core.living.chat_sessions import ChatSessionState
from .core.living.journal import JournalConflict


class NativeChatCorpusWebApi:
    def __init__(self, chat_api):
        self.chat = chat_api

    def register_routes(self):
        # Imported at registration time, avoiding a circular import during Chat load.
        from .chat_web_api import PAGE_API_PREFIX
        self.chat.plugin.context.register_web_api(PAGE_API_PREFIX + '/corpus', self.get, ['GET'], 'Asteria owned corpus and explicit preferences')
        self.chat.plugin.context.register_web_api(PAGE_API_PREFIX + '/corpus', self.save, ['POST'], 'Asteria explicit versioned corpus maintenance')

    async def _respond(self, write):
        from .chat_web_api import _RequestError, _session_id
        write_completed = False
        def uncertain():
            return error_response('保存已提交，但当前身份或角色已变化，结果需要核对；请保留输入，不要重复保存', status_code=503)
        try:
            self.chat._bound()  # Authentication precedes input validation and storage reads.
            if write:
                if request.query:
                    raise _RequestError('写入不接受查询参数')
                data = await self.chat._body()
                if set(data) != {'session_id', 'op', 'id', 'expected_revision', 'request_id', 'record'} or data['op'] != 'save':
                    raise _RequestError('请提供完整的语料保存操作')
            else:
                data = dict(request.query or {})
                if set(data) != {'session_id'}:
                    raise _RequestError('只接受当前会话编号')
            sid = _session_id(data['session_id'])
            username, service, expressions, scope = await self.chat._owned_expression(sid)
            persona = await self.chat._configured_persona(service, username, sid)
            if persona.get('status') != 'configured' or persona.get('configured_id') != scope['character_id']:
                raise _RequestError('请先为此会话选择一个有效角色', 409)
            library = ChatCorpusLibrary(expressions.journal, current=expressions.current)
            await self.chat._recheck_owned_session(username, service, sid)
            if write:
                result = await asyncio.to_thread(library.save, scope, sid, identity=data['id'],
                    expected_revision=data['expected_revision'], request_id=data['request_id'], record=data['record'])
                write_completed = True
            else:
                result = await asyncio.to_thread(library.list, scope, sid)
            await self.chat._recheck_owned_session(username, service, sid)
            latest = await self.chat._configured_persona(service, username, sid)
            if latest != persona:
                raise _RequestError('角色已变化，请重新读取；已提交的结果需要核对', 409)
            expressions._check()
            response = self.chat._ok(dict(result, session_id=sid, persona_id=scope['character_id'],
                factual_memory_writes=0, sends=0, provider_calls=0))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except (_RequestError, ChatServiceError) as exc:
            if write_completed: return uncertain()
            return self.chat._error(exc)
        except JournalConflict:
            return error_response('语料版本已变化，请先读取当前版本', status_code=409)
        except KeyError:
            if write_completed: return uncertain()
            return error_response('当前范围内没有这个资料项', status_code=404)
        except PermissionError:
            if write_completed: return uncertain()
            return error_response('当前资料权限已变化，请重新读取', status_code=403)
        except (ValueError, TypeError) as exc:
            if write_completed: return uncertain()
            return error_response(str(exc), status_code=400)
        except (RuntimeError, OSError, sqlite3.Error):
            return error_response('语料服务暂不可用；请保留输入，写入结果未知时不要重复保存', status_code=503)

    async def get(self):
        return await self._respond(False)

    async def save(self):
        return await self._respond(True)


async def inject_chat_corpus_context(plugin, event, req):
    """Bounded, temporary reference from the actual owner and configured persona.

The caller handles optional failure without suppressing the ordinary reply.
This read does not create a Presence lease or write an application/usage receipt.
"""
    if getattr(plugin, '_stopping', False) or event.get_platform_name() != 'webchat':
        return False
    raw = getattr(getattr(event, 'message_obj', None), 'raw_message', None)
    if not isinstance(raw, tuple) or len(raw) != 3:
        return False
    username, sid, payload = raw
    if (type(username) is not str or type(sid) is not str or type(payload) is not dict
            or username != str(event.get_sender_id() or '')):
        return False
    host = getattr(getattr(plugin, '_presence', None), 'living_host', None)
    runtime = getattr(host, 'runtime', None)
    assets = getattr(runtime, 'expression_assets', None)
    journal = getattr(assets, 'journal', None)
    if journal is None:
        return False

    def current():
        return (not getattr(plugin, '_stopping', False)
            and getattr(getattr(plugin, '_presence', None), 'living_host', None) is host
            and not getattr(host, '_closed', True) and getattr(host, 'runtime', None) is runtime
            and getattr(runtime, 'expression_assets', None) is assets
            and getattr(assets, 'active', False) is True and not getattr(journal, '_closed', True)
            and getattr(assets, 'journal', None) is journal)

    async def identity():
        if not current():
            return None
        session = await db_helper.get_platform_session_by_id(sid)
        if (session is None or session.session_id != sid or session.creator != username
                or session.platform_id != 'webchat' or session.is_group != 0):
            return None
        umo = build_webchat_unified_msg_origin(session)
        if str(event.unified_msg_origin) != umo:
            return None
        config = await sp.get_async(scope='umo', scope_id=umo, key='session_service_config', default={})
        persona_id = config.get('persona_id') if type(config) is dict else None
        if (type(persona_id) is not str or not persona_id or persona_id == '[%None]'
                or len(persona_id) > 256 or any(ord(c) < 32 for c in persona_id)):
            return None
        # Deleted personas must not continue exposing their old private library.
        manager = getattr(plugin.context, 'persona_manager', None)
        if manager is None:
            return None
        persona = await manager.get_persona(persona_id)
        if persona is None:
            return None
        return persona_id

    persona_id = await identity()
    if persona_id is None:
        return False
    state = await asyncio.to_thread(ChatSessionState(journal, current=current).get, username, sid)
    if state['archived'] or not current():
        return False
    scope = ChatExpressions.preference_scope(username, persona_id)
    query = getattr(req, 'prompt', '')
    if type(query) is not str:
        return False
    packet = await asyncio.to_thread(ChatCorpusLibrary(journal, current=current).context,
        scope, sid, query, scene=state.get('scene', '')[:1000])
    if not packet['text'] or not current() or await identity() != persona_id:
        return False
    # This identifies candidate material supplied, not proven model use or a fact.
    event.set_extra('asteria_corpus_candidates', dict(persona_id=persona_id, session_id=sid,
        items=[dict(id=row['id'], revision=row['revision'], kind=row['kind']) for row in packet['items']],
        actual_use='not_observed'))
    req.extra_user_content_parts.append(TextPart(text=packet['text']).mark_as_temp())
    return True
