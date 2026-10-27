"""Authenticated scoped review of TLS native expression feedback.

AstrBot grants administrator access. The native learner separately authorizes
each complete private scope. No old plugin, persona file or LLM is invoked.
UI edits retain immutable rule identity/pattern and require revision plus a
source message ID, preserving the learner's durable CAS/idempotency contract.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.native_expression_learning import ExpressionConflict, NativeExpressionLearning
from .core.living.native_expression_review import _ApplicationJournal
from .core.living.journal import LivingJournal
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text


PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/expression'


class _Unavailable(RuntimeError):
    pass


def _event_id(value):
    value = _text(value,'source_message_id',256)
    if value != value.strip() or any(ord(c)<32 for c in value):
        raise _InvalidRequest('source_message_id 不能包含首尾空白或控制字符')
    return value


class NativeExpressionWebApi:
    def __init__(self,plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list','update','delete'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,
                getattr(self,'expression_'+name),['GET' if name=='list' else 'POST'],
                'TLS native authenticated expression '+name)

    def register_admin_routes(self):
        for name in ('list', 'update', 'delete'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX + '/admin-' + name,
                getattr(self, 'expression_admin_' + name), ['GET' if name == 'list' else 'POST'],
                'TLS authenticated administrator historical expression ' + name)

    def _admin_resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        learner = self._learner()
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(journal, LivingJournal) or journal._closed
                or getattr(runtime, 'journal', None) is not journal or learner.journal is not journal):
            raise _Unavailable('current expression administrator resources unavailable')
        return presence, host, runtime, learner, journal

    def _same_admin_resources(self, resources):
        if any(old is not new for old, new in zip(resources, self._admin_resources())):
            raise _Unavailable('expression administrator resources replaced')

    def _learner(self):
        host = getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        learner = getattr(getattr(host,'runtime',None),'expression_learning',None)
        if not isinstance(learner,NativeExpressionLearning):
            raise _Unavailable('native expression learning not attached')
        return learner

    @staticmethod
    def _operation(name,data):
        if not isinstance(data,dict): raise _InvalidRequest('请求正文必须是 JSON 对象')
        if name=='list':
            if set(data)-set(SCOPE_FIELDS)-{'include_deleted'}:
                raise _InvalidRequest('表达规则查询含未知字段')
            scope = _scope({key:data.get(key) for key in SCOPE_FIELDS})
            deleted = data.get('include_deleted',True)
            if isinstance(deleted,str) and deleted in {'true','false'}: deleted = deleted=='true'
            if type(deleted) is not bool: raise _InvalidRequest('include_deleted 必须为布尔值')
            return scope,(),{'include_deleted':deleted}
        allowed = {'scope','id','expected_revision','source_message_id'} | ({'patch'} if name=='update' else set())
        if set(data)!=allowed: raise _InvalidRequest('需要完整的 scope、ID、版本和操作来源，且不能修改额外字段')
        scope = _scope(data['scope'])
        identity = _text(data['id'],'表达规则 ID',64)
        revision = _integer(data['expected_revision'],'expected_revision',1,2147483647)
        event_id = _event_id(data['source_message_id'])
        args = (identity,revision)
        if name=='update':
            patch = data['patch']
            if not isinstance(patch,dict) or not patch or set(patch)-{'replacement','preference'}:
                raise _InvalidRequest('只能修改替换文本或已有表达偏好，不能修改原词、类型或归属')
            for key,value in patch.items():
                _text(value,key,80)
                if value!=value.strip() or any(ord(c)<32 for c in value):
                    raise _InvalidRequest('表达内容不能包含首尾空白或控制字符')
            args = (identity,dict(patch),revision)
        return scope,args,{'source_message_id':event_id}

    async def _respond(self,name, *, administrative=False):
        try: username = getattr(request,'username',None)
        except RuntimeError: username = None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            learner = self._learner()
            resources = self._admin_resources() if administrative else None
            if name=='list':
                query = getattr(request,'query',None)
                data = dict(query or {})
            else: data = await request.json(default=None)
            scope,args,kwargs = self._operation(name,data)
            if administrative:
                def guard():
                    self._same_admin_resources(resources)
                    return True
                # Same Journal and existing rule CAS/history, with a request-
                # local administrator boundary. Runtime recall remains on the
                # original learner's real inbound-scope authorization.
                # Read methods use the actual shared Journal's lock/connection.
                # The existing transaction-only approval view is reserved for
                # mutations, where it rechecks ownership before COMMIT.
                operation_journal = resources[-1] if name == 'list' else _ApplicationJournal(resources[-1], guard)
                learner = NativeExpressionLearning(operation_journal,
                    authorize=lambda candidate: candidate == scope and guard(), clock=resources[3].clock,
                    max_rules=resources[3].max_rules, max_events=resources[3].max_events)
            def operate():
                if administrative:
                    self._same_admin_resources(resources)
                elif self._learner() is not learner:
                    raise _Unavailable('native expression learner replaced')
                return getattr(learner,name)(scope,*args,**kwargs)
            result = await asyncio.to_thread(operate)
            if administrative:
                self._same_admin_resources(resources)
            response = {'ok':True,'backend':'native','access':'authenticated_administrator',
                        'scope':scope,'changes_persona':False,'changes_character_facts':False,
                        'authority':'historical_administrator' if administrative else 'live_private_scope',
                        'automatic_scope_granted':False,
                        'llm_calls':0,'external_operations':0}
            if name=='list':
                response.update(records=result,generation=hashlib.sha256(json.dumps(result,
                    ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest())
            else: response.update(result)
            return json_response(response,headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc),status_code=400)
        except ExpressionConflict:
            return error_response('表达规则版本或操作来源已改变，请刷新后重试',status_code=409)
        except PermissionError:
            return error_response('该完整会话范围未获原生表达服务授权',status_code=403)
        except KeyError:
            return error_response('当前会话中找不到该表达规则',status_code=404)
        except ValueError:
            return error_response('表达参数无效，请检查类型、偏好、来源和版本',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('原生表达学习未启用或暂不可用',status_code=503)
        except Exception:
            return error_response('表达规则操作失败，请稍后重试',status_code=500)

    async def expression_list(self): return await self._respond('list')
    async def expression_update(self): return await self._respond('update')
    async def expression_delete(self): return await self._respond('delete')
    async def expression_admin_list(self): return await self._respond('list', administrative=True)
    async def expression_admin_update(self): return await self._respond('update', administrative=True)
    async def expression_admin_delete(self): return await self._respond('delete', administrative=True)
