"""A session-only selection over the original TaskModelRouter and SDK providers.

No credentials, alternate provider clients, generation loop or model retry is
created. The SDK retains its own runtime fallback. The HTTP caller must first
obtain its real owned private PlatformSession, and use the SDK's origin builder.
"""
from __future__ import annotations

import math

from .chat_expressions import ChatExpressions
from .chat_sessions import ChatSessionState, MODEL_ROUTE_DEFAULTS
from .task_model_router import TaskModelRouter, provider_id

RESPONSE_NAMESPACE = 'tls.chat.model.responses.v1'
RESPONSE_KEY = 'last_response'


def _text(value, *, limit=160, blank=False):
    if (not isinstance(value, str) or len(value) > limit or value != value.strip()
            or not blank and not value or any(ord(char) < 32 for char in value)):
        raise ValueError('模型响应标识无效')
    return value


class ChatModelRoute:
    def __init__(self, states, router, *, username, session_id, umo):
        if not isinstance(states, ChatSessionState) or not isinstance(router, TaskModelRouter):
            raise RuntimeError('当前会话模型路由尚未接通')
        self.states, self.router = states, router
        self.username, self.session_id, self.umo = username, session_id, umo

    def _check(self):
        if self.states.current() is not True or self.router.current() is not True:
            raise RuntimeError('模型路由正在更新，请重新读取')

    def _resolve(self, explicit_provider_id=None, explicit_model=None):
        """Resolve one owned configuration snapshot; never generate or retry."""
        self._check()
        state = self.states.get(self.username, self.session_id)
        task = 'rp' if state['mode'] == 'roleplay' else 'chat'
        providers = self.router.providers()
        by_id = {row['id']: row for row in providers}
        task_route = self.router.settings()['routes'][task]
        primary, fallback = (state[key] for key in MODEL_ROUTE_DEFAULTS)
        selected, source, reason = '', 'unavailable', 'no_available_provider'
        for identity, origin in [(primary, 'session_override'), (fallback, 'session_fallback'),
                (task_route['preferred_provider_id'], 'task_preferred'),
                (task_route['fallback_provider_id'], 'task_fallback')]:
            if identity and identity in by_id:
                selected, source = identity, origin
                reason = 'session_provider_unavailable' if primary and primary not in by_id else ''
                break
        if not selected:
            try:
                inherited = self.router.context.get_using_provider(umo=self.umo)
                identity = provider_id(inherited)
            except (ValueError, RuntimeError, AttributeError):
                identity = ''
            if identity in by_id:
                selected, source = identity, 'sdk_session_default'
                reason = 'session_provider_unavailable' if primary else ''
        if explicit_provider_id is not None:
            identity = _text(explicit_provider_id)
            if identity not in by_id:
                raise ValueError('所选模型不在当前AstrBot文本模型列表中，请刷新')
            selected, source, reason = identity, 'explicit_request', ''
        model = by_id.get(selected, {}).get('model') or None
        if explicit_model is not None:
            model = _text(explicit_model, limit=512)
            if not selected:
                raise ValueError('请先选择可用的模型提供商')
        fallback_ids, fallback_source = self._network_fallbacks(state, task_route, by_id, selected)
        self._check()
        return dict(state=state, task=task, providers=providers, task_route=task_route,
            effective=dict(provider_id=selected or None, model=model, source=source,
                available=bool(selected), fallback=source in {'session_fallback', 'task_fallback'}
                    or bool(primary and selected != primary and source != 'explicit_request'),
                reason=reason or None), fallback_provider_ids=fallback_ids,
            fallback_source=fallback_source)

    def _network_fallbacks(self, state, task_route, available, selected):
        # A configured chain owns its boundary even when every member has been
        # removed. Only a blank choice inherits; never silently append globals.
        if state['model_fallback_provider_id']:
            candidates, source = [state['model_fallback_provider_id']], 'session'
        elif task_route['fallback_provider_id']:
            candidates, source = [task_route['fallback_provider_id']], 'task'
        else:
            source = 'astrbot'
            try:
                config = self.router.context.get_config(umo=self.umo)
                settings = config.get('provider_settings', {}) if isinstance(config, dict) else {}
                candidates = settings.get('fallback_chat_models', []) if isinstance(settings, dict) else []
            except (AttributeError, TypeError, ValueError, RuntimeError, KeyError):
                candidates = []
        if not isinstance(candidates, list):
            candidates = []
        result, seen = [], {selected}
        for identity in candidates:
            if not isinstance(identity, str) or identity not in available or identity in seen:
                continue
            seen.add(identity)
            result.append(identity)
        return result, source

    def request_plan(self, explicit_provider_id=None, explicit_model=None):
        """IDs for one accepted request, consumed by the existing SDK runner.

        The explicit model belongs only to the primary provider. Fallback IDs
        deliberately carry no model override and keep their own SDK settings.
        """
        value = self._resolve(explicit_provider_id, explicit_model)
        state, effective = value['state'], value['effective']
        return dict(session_id=self.session_id, revision=state['revision'], mode=state['mode'],
            task=value['task'], provider_id=effective['provider_id'], model=effective['model'],
            source=effective['source'], available=effective['available'],
            fallback_provider_ids=list(value['fallback_provider_ids']),
            fallback_source=value['fallback_source'])

    def _response(self, provider, model, requested_provider_id, observed_at, checkpoint_id, *, check_clock):
        identity = _text(provider if isinstance(provider, str) else provider_id(provider))
        model = _text(model, limit=512)
        requested = None if requested_provider_id is None else _text(requested_provider_id, blank=True) or None
        checkpoint = _text(checkpoint_id, limit=256)
        if (type(observed_at) not in (int, float) or not math.isfinite(observed_at)
                or not 0 < observed_at <= 253402300799):
            raise ValueError('模型响应观察时间无效')
        if check_clock:
            now = self.states.journal.clock()
            if type(now) not in (int, float) or not math.isfinite(now) or observed_at > now + 30:
                raise ValueError('模型响应观察时间晚于当前时间')
        return dict(schema=1, provider_id=identity, model=model, requested_provider_id=requested,
            observed_at=observed_at, checkpoint_id=checkpoint,
            outcome='response_received', source='sdk_response')

    def _last_response(self):
        row = self.states.journal.fetch(RESPONSE_NAMESPACE, RESPONSE_KEY,
            ChatExpressions.message_scope(self.username, self.session_id))
        data = row['data'] if row else None
        if (not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] != 1
                or data.get('outcome') != 'response_received' or data.get('source') != 'sdk_response'):
            return None
        try:
            return self._response(data.get('provider_id'), data.get('model'),
                data.get('requested_provider_id'), data.get('observed_at'), data.get('checkpoint_id'),
                check_clock=False)
        except (ValueError, TypeError):
            return None

    def record_response(self, provider, model, requested_provider_id, observed_at, checkpoint_id):
        """Record trusted SDK response metadata, separately from user settings.

        The caller proves the original accepted event and current DB owner.
        These identifiers are response evidence, not a delivery/save receipt,
        and are never inferred from today's registered provider model list.
        """
        self._check()
        data = self._response(provider, model, requested_provider_id, observed_at, checkpoint_id,
            check_clock=True)
        scope = ChatExpressions.message_scope(self.username, self.session_id)
        journal = self.states.journal
        with journal._lock:
            self._check()
            old = journal.fetch(RESPONSE_NAMESPACE, RESPONSE_KEY, scope)
            previous = self._last_response()
            if previous and (previous['observed_at'] > observed_at or previous == data):
                return False
            def authorize():
                self._check()
                return True
            journal.put(RESPONSE_NAMESPACE, RESPONSE_KEY, scope, data,
                expected_revision=old['revision'] if old else 0, authorize=authorize)
        self._check()
        return True

    def view(self):
        value = self._resolve()
        state, effective = value['state'], value['effective']
        last_call = self._last_response()
        self._check()
        return dict(session_id=self.session_id, revision=state['revision'], mode=state['mode'], task=value['task'],
            override={key: state[key] for key in MODEL_ROUTE_DEFAULTS}, providers=value['providers'],
            task_route=value['task_route'], effective=effective,
            runtime=dict(state='sdk_managed', observed_outcome=last_call is not None, last_call=last_call,
                network_fallback_provider_ids=list(value['fallback_provider_ids']),
                network_fallback_source=value['fallback_source'],
                note='下次请求是当前配置解析；最近返回仅记录SDK实际响应，不代表历史保存或客户端送达。'),
            credentials_returned=False, global_settings_changed=False)

    def save(self, changes, expected_revision):
        self._check()
        if type(changes) is not dict or set(changes) != set(MODEL_ROUTE_DEFAULTS):
            raise ValueError('请明确选择会话首选和备选模型；留空表示继承')
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('请先读取当前会话模型设置')
        available = self.router._providers()
        for value in changes.values():
            if (not isinstance(value, str) or len(value) > 160 or value != value.strip()
                    or any(ord(c) < 32 for c in value) or value and value not in available):
                raise ValueError('所选模型不在当前AstrBot文本模型列表中，请刷新')
        if changes['model_fallback_provider_id'] and not changes['model_provider_id']:
            raise ValueError('继承模型时不能单独覆盖备选模型')
        def current():
            self._check()
            live = self.router._providers()
            return all(live.get(value) is available[value] for value in changes.values() if value)
        # The existing Journal transaction still provides revision/CAS. The
        # writer repeats current provider identity checks at its commit edge.
        states = ChatSessionState(self.states.journal, current=current)
        states.save(self.username, self.session_id, changes, expected_revision=expected_revision)
        return self.view()

    def selected_provider_id(self):
        """Resolve once for the existing payload; no retry and no model call."""
        value = self.request_plan()
        return value['provider_id'] if value['available'] else None
