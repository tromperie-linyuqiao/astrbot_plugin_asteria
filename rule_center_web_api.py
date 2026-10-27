"""Authenticated operation-local administration of reviewed wording rules."""
import asyncio
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_expression_learning import NativeExpressionLearning
from .core.living.native_expression_review import NativeExpressionReview, _ApplicationJournal
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/rule-center'


class NativeRuleCenterWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('state', 'propose', 'review', 'disable'):
            self.plugin.context.register_web_api(PREFIX + '/' + name, getattr(self, name),
                ['GET' if name == 'state' else 'POST'], 'TLS authenticated wording-rule review ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        review = getattr(runtime, 'expression_review', None)
        learner = getattr(runtime, 'expression_learning', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or type(review) is not NativeExpressionReview or not review.active
                or type(learner) is not NativeExpressionLearning
                or not isinstance(journal, LivingJournal) or journal._closed
                or runtime.journal is not journal or learner.journal is not journal
                or review.journal is not journal or review.learner is not learner):
            raise RuntimeError('rule review service unavailable')
        return presence, host, runtime, review, learner, journal

    def _same(self, resources):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise RuntimeError('rule review owner changed')

    async def _respond(self, name):
        try:
            actor = getattr(request, 'username', None)
        except RuntimeError:
            actor = None
        if type(actor) is not str or not actor.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        local = None
        try:
            resources = self._resources()
            if name == 'state':
                data = dict(getattr(request, 'query', None) or {})
                if set(data) - set(SCOPE_FIELDS):
                    raise _InvalidRequest('规则查询只接受五项完整范围')
                scope = _scope(data)
            else:
                if getattr(request, 'query', None):
                    raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii()
                        or not length.isdigit() or len(length) > 6 or int(length) > 8192):
                    raise _InvalidRequest('规则请求过大')
                data = await request.json(default=None)
                if type(data) is not dict:
                    raise _InvalidRequest('规则请求必须是 JSON 对象')
                allowed = {'scope', 'feedback', 'source_message_id'} if name == 'propose' else (
                    {'scope', 'id', 'expected_revision', 'request_id', 'decision', 'note'} if name == 'review'
                    else {'scope', 'id', 'expected_revision', 'source_message_id'})
                if set(data) != allowed:
                    raise _InvalidRequest('请提交完整的规则操作，不能附带人格、授权或行为字段')
                scope = _scope(data['scope'])
                if name != 'propose' and (type(data['expected_revision']) is not int or not 1 <= data['expected_revision'] < 2**53):
                    raise _InvalidRequest('请提交明确的整数修订版本')
                if name == 'review' and data['decision'] not in {'approve_apply', 'reject'}:
                    raise _InvalidRequest('请选择批准并生效或拒绝')
                if name == 'propose':
                    _text(data['feedback'], '纠正内容', 500)
                    _text(data['source_message_id'], '来源消息', 256)
            def guard(candidate):
                self._same(resources)
                return candidate == scope
            original, journal = resources[-2:]
            learner = NativeExpressionLearning(journal, authorize=guard, clock=original.clock,
                max_rules=original.max_rules, max_events=original.max_events)
            local = NativeExpressionReview(journal, learner, authorize=guard,
                review_authorize=lambda candidate, reviewer: reviewer == actor and guard(candidate),
                max_candidates=resources[3].max_candidates)
            def operate():
                self._same(resources)
                if name == 'state':
                    result = dict(candidates=local.list(scope), rules=learner.list(scope, include_deleted=True))
                elif name == 'propose':
                    result = dict(candidate=local.propose(scope, data['feedback'], source_message_id=data['source_message_id']))
                elif name == 'review':
                    candidate = local.get(scope, data['id'])
                    if (data['decision'] == 'approve_apply' and candidate is not None
                            and candidate['state'] == 'approved'
                            and candidate['approval']['request_id'] != data['request_id']):
                        result = local.apply(scope, data['id'], expected_revision=data['expected_revision'], reviewer_id=actor)
                    else:
                        method = local.approve_and_apply if data['decision'] == 'approve_apply' else local.reject
                        result = method(scope, data['id'], expected_revision=data['expected_revision'],
                                        reviewer_id=actor, request_id=data['request_id'], note=data['note'])
                    if data['decision'] == 'reject':
                        result = dict(candidate=result, state='rejected')
                else:
                    guarded = NativeExpressionLearning(_ApplicationJournal(journal, lambda: guard(scope)),
                        authorize=guard, clock=original.clock, max_rules=original.max_rules, max_events=original.max_events)
                    result = guarded.delete(scope, data['id'], data['expected_revision'],
                                            source_message_id=data['source_message_id'])
                self._same(resources)
                local._scope(scope, actor)
                return result
            self._same(resources)
            result = await asyncio.to_thread(operate)
            self._same(resources)
            local._scope(scope, actor)
            return json_response(dict(result, ok=True, scope=scope, changes_persona=False,
                creates_send_permission=False, access='authenticated_administrator',
                automatic_scope_granted=False, legacy_direct_feedback_retained=True,
                behavior_rules='existing_app_rules', behavior_view='phone'), headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except JournalConflict:
            return error_response('规则或审核版本已变化，请刷新；重试请保留原操作编号', status_code=409)
        except PermissionError:
            return error_response('规则资料或审核权限已撤回', status_code=403)
        except KeyError:
            return error_response('当前完整范围中找不到这条规则或候选', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('规则参数无效，请检查明确纠正、范围和版本', status_code=400)
        except (RuntimeError, OSError, sqlite3.Error):
            return error_response('规则服务暂不可用；请保留草稿及操作编号并刷新确认', status_code=503)
        except Exception:
            return error_response('规则操作失败，请保留草稿并稍后回读', status_code=500)
        finally:
            if local is not None:
                local.stop()

    async def state(self): return await self._respond('state')
    async def propose(self): return await self._respond('propose')
    async def review(self): return await self._respond('review')
    async def disable(self): return await self._respond('disable')
