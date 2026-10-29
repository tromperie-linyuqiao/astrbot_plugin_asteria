"""A session-only selection over the original TaskModelRouter and SDK providers.

No credentials, alternate provider clients, generation loop or model retry is
created. The SDK retains its own runtime fallback. The HTTP caller must first
obtain its real owned private PlatformSession, and use the SDK's origin builder.
"""
from __future__ import annotations

from .chat_sessions import ChatSessionState, MODEL_ROUTE_DEFAULTS
from .task_model_router import TaskModelRouter, provider_id


class ChatModelRoute:
    def __init__(self, states, router, *, username, session_id, umo):
        if not isinstance(states, ChatSessionState) or not isinstance(router, TaskModelRouter):
            raise RuntimeError('当前会话模型路由尚未接通')
        self.states, self.router = states, router
        self.username, self.session_id, self.umo = username, session_id, umo

    def _check(self):
        if self.states.current() is not True or self.router.current() is not True:
            raise RuntimeError('模型路由正在更新，请重新读取')

    def view(self):
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
        self._check()
        return dict(session_id=self.session_id, revision=state['revision'], mode=state['mode'], task=task,
            override={key: state[key] for key in MODEL_ROUTE_DEFAULTS}, providers=providers,
            task_route=task_route,
            effective=dict(provider_id=selected or None, model=by_id.get(selected, {}).get('model') or None,
                source=source, available=bool(selected), fallback=source in {'session_fallback', 'task_fallback'}
                    or bool(primary and selected != primary), reason=reason or None),
            runtime=dict(state='sdk_managed', observed_outcome=False,
                note='以上是当前配置实际解析的下一次请求模型；生成开始后仍可能由AstrBot原有回退或图片能力策略切换，当前接口不提供逐次实际模型回报。'),
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
        value = self.view()
        return value['effective']['provider_id'] if value['effective']['available'] else None
