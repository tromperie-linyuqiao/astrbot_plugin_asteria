"""Explicit scoped panel overrides over the existing expression learner only."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import LivingJournal
from .core.living.models import canonical, scope_key
from .core.living.native_expression_learning import NativeExpressionLearning, ExpressionConflict, _definition
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/interaction-preferences'
OPTIONS = {'length': ('short', 'normal', 'detailed'), 'lists': ('less', 'normal'),
           'questions': ('less', 'normal'), 'tone': ('natural_direct',)}
META = 'tls_interaction_panel_override'
RESTORED = 'tls_interaction_panel_restored_source'
SOURCE = 'webui.interaction-preferences.action.'
MAX_BODY_BYTES = 16 * 1024


class _Unavailable(RuntimeError): pass


def _owned(row):
    meta = row.get(META) if row else None
    return (type(meta) is dict and type(meta.get('schema')) is int and meta['schema'] == 1 and meta.get('owner') == 'interaction_preferences'
            and meta.get('set_source') == row.get('source_message_id'))


def _effective_source(row):
    restored = row.get(RESTORED)
    if type(restored) is dict and restored.get('operation_source') == row.get('source_message_id'):
        return restored.get('effective_source', row['source_message_id'])
    return row['source_message_id']


class NativeInteractionPreferencesWebApi:
    def __init__(self, plugin): self.plugin = plugin

    def register_routes(self):
        self.plugin.context.register_web_api(PREFIX + '/expression', self.expression_state, ['GET'], 'TLS scoped explicit interaction expression preferences')
        self.plugin.context.register_web_api(PREFIX + '/expression/save', self.expression_save, ['POST'], 'TLS scoped panel overrides of existing expression rules')

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        learner = getattr(runtime, 'expression_learning', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True or not isinstance(learner, NativeExpressionLearning)
                or not isinstance(journal, LivingJournal)
                or learner.journal is not journal or getattr(runtime, 'journal', None) is not journal
                or getattr(journal, '_closed', True)):
            raise _Unavailable('expression preferences unavailable')
        return presence, host, runtime, learner, journal

    def _check(self, resources, scope):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise _Unavailable('expression runtime changed')
        # Normal authenticated administration maintains existing durable
        # expression definitions, as the historical material/date APIs do.
        # _local supplies an operation-only exact scope; the automatic reader's
        # authorize callback and genuine inbound lease remain unchanged.

    def _local(self, resources, scope, enabled):
        def authorize(candidate):
            if not enabled[0] or candidate != scope: return False
            self._check(resources, candidate)
            return True
        original = resources[-2]
        return NativeExpressionLearning(resources[-1], authorize=authorize, clock=original.clock,
            max_rules=original.max_rules, max_events=original.max_events)

    @staticmethod
    def _state(learner, scope):
        rows = learner.list(scope, include_deleted=True)
        output = {}
        for feature in OPTIONS:
            found = [row for row in rows if row['kind'] == 'preference' and row['pattern'] == feature]
            if len(found) > 1: raise _Unavailable('ambiguous preference feature')
            row = found[0] if found else None
            if row: _definition({key: row[key] for key in ('kind', 'pattern', 'replacement', 'preference')})
            owned = bool(row and _owned(row))
            source = _effective_source(row) if row else ''
            label = ('本面板明确覆盖' if owned else '规则审核后应用' if source.startswith('expression.review.apply.')
                     else '已有明确反馈或表达规则' if row and row['active'] else '未覆盖，沿用既有默认')
            output[feature] = dict(value=row['preference'] if row and row['active'] else 'default',
                selection=row['preference'] if owned and row['active'] else 'default', revision=row['revision'] if row else 0,
                active=bool(row and row['active']), rule_id=row['id'] if row else None, override_owned=owned,
                source_label=label, effective_source=source, latest_operation=row['source_message_id'] if row else '')
        return dict(preferences=output, options={key: list(value) for key, value in OPTIONS.items()},
            scope_defaults_only=True, changes_global_defaults=False, changes_persona=False, creates_send_permission=False)

    @staticmethod
    def _save(learner, scope, body):
        feature, value, expected = body['feature'], body['value'], body['expected_revision']
        event = SOURCE + hashlib.sha256(canonical([scope, body['request_id']]).encode()).hexdigest()
        fingerprint = hashlib.sha256(canonical(['panel_override', feature, value, expected]).encode()).hexdigest()
        with learner.journal._transaction() as db:
            learner._scope(scope)
            data, checkpoint_revision = learner._load(db, scope)
            replay = learner._receipt(data, event, fingerprint, scope)
            if replay:
                learner._scope(scope)
                return
            identity = 'expr_' + hashlib.sha256(canonical([scope_key(scope), 'preference', feature]).encode()).hexdigest()[:24]
            row = data['rules'].get(identity)
            if (row['revision'] if row else 0) != expected:
                raise ExpressionConflict('panel preference revision conflict')
            now = learner._now()
            if value == 'default':
                if not row or not _owned(row):
                    raise ExpressionConflict('only the current panel override may be reset')
                baseline = row[META].get('baseline')
                if baseline is None:
                    definition = _definition({key: row[key] for key in ('kind', 'pattern', 'replacement', 'preference')})
                    updated = learner._change(row, definition, False, event, now)
                else:
                    if (type(baseline) is not dict or type(baseline.get('active')) is not bool
                            or type(baseline.get('source')) is not str):
                        raise _Unavailable('panel baseline invalid')
                    definition = _definition(baseline['definition'])
                    if definition['kind'] != 'preference' or definition['pattern'] != feature:
                        raise _Unavailable('panel baseline feature mismatch')
                    updated = learner._change(row, definition, baseline['active'], event, now)
                    updated[RESTORED] = dict(operation_source=event, effective_source=baseline['source'])
                updated.pop(META, None)
                state = 'panel_override_reset'
            else:
                definition = _definition(dict(kind='preference', pattern=feature, replacement='', preference=value))
                if row:
                    baseline = deepcopy(row[META]['baseline']) if _owned(row) else dict(
                        definition={key: row[key] for key in ('kind', 'pattern', 'replacement', 'preference')},
                        active=row['active'], source=_effective_source(row))
                    updated = learner._change(row, definition, True, event, now)
                else:
                    if len(data['rules']) >= learner.max_rules: raise ValueError('expression rule capacity reached')
                    baseline = None
                    updated = dict(definition, id=identity, revision=1, active=True, source_message_id=event,
                        created_source_message_id=event, created_at=now, updated_at=now, history=[])
                updated[META] = dict(schema=1, owner='interaction_preferences', set_source=event, baseline=baseline)
                updated.pop(RESTORED, None)
                state = 'panel_override_set'
            data['rules'][identity] = updated
            learner._remember(data, event, fingerprint, state, identity)
            learner._save(db, scope, data, checkpoint_revision)
            learner._scope(scope)

    async def _respond(self, save):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        enabled = [True]
        try:
            resources = self._resources()
            if save:
                if getattr(request, 'query', None): raise _InvalidRequest('保存不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii() or not length.isdigit()
                        or len(length) > 10 or int(length) > MAX_BODY_BYTES): raise _InvalidRequest('偏好请求过大')
                body = await request.json(default=None)
                if type(body) is not dict or set(body) != {'scope', 'feature', 'value', 'expected_revision', 'request_id'}:
                    raise _InvalidRequest('请只提交完整范围、偏好、版本和本次请求标识')
                if len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BODY_BYTES:
                    raise _InvalidRequest('偏好请求过大')
                scope = _scope(body['scope'])
                if (type(body['feature']) is not str or body['feature'] not in OPTIONS
                        or type(body['value']) is not str or body['value'] not in (*OPTIONS[body['feature']], 'default')):
                    raise _InvalidRequest('只能选择当前已支持的表达偏好')
                if type(body['expected_revision']) is not int or not 0 <= body['expected_revision'] <= 2147483647:
                    raise _InvalidRequest('请提供读取时的明确整数版本')
                request_id = _text(body['request_id'], 'request_id', 128)
                if request_id != request_id.strip() or any(ord(c) < 32 for c in request_id): raise _InvalidRequest('请求标识无效')
            else:
                body = dict(getattr(request, 'query', None) or {})
                if set(body) - set(SCOPE_FIELDS): raise _InvalidRequest('查询只接受五项完整范围')
                scope = _scope(body)
            self._check(resources, scope)
            local = self._local(resources, scope, enabled)
            def operate():
                local._scope(scope)
                if save: self._save(local, scope, body)
                result = self._state(local, scope)
                local._scope(scope)
                return result
            result = await asyncio.to_thread(operate)
            self._check(resources, scope)
            return json_response(dict(ok=True, backend='native_expression_preferences', scope=scope,
                access='authenticated_administrator', authority='historical_administrator_materials',
                runtime_authority_granted=False, creates_private_session=False,
                **result), headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc: return error_response(str(exc), status_code=400)
        except ExpressionConflict: return error_response('偏好或来源已有变化；只允许撤回本面板当前覆盖，请读取当前来源后再决定', status_code=409)
        except PermissionError: return error_response('当前完整范围的本次偏好维护未获准，请核对范围并重新读取', status_code=403)
        except (ValueError, TypeError, KeyError, RecursionError): return error_response('偏好参数或记录无效，未确认本次修改', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError): return error_response('偏好服务正在重载或存储未确认，请保留原请求并回读', status_code=503)
        except Exception: return error_response('偏好操作未确认，请保留草稿并稍后核对', status_code=500)
        finally: enabled[0] = False

    async def expression_state(self): return await self._respond(False)
    async def expression_save(self): return await self._respond(True)
