"""Optional shared Presence API boundary for direct persona generation.

Only genuine, leased private identities are eligible. Missing support leaves
the original generation call unchanged; no plugin imports or history writes.
"""
from __future__ import annotations

import inspect
from typing import Any


def supports_temporary_parts(provider: Any) -> bool:
    """Require explicit provider support; **kwargs alone is not proof."""
    try:
        method = getattr(provider, "text_chat", None)
        if not callable(method):
            return False
        parameter = inspect.signature(method).parameters.get("extra_user_content_parts")
        return parameter is not None and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
        }
    except Exception:
        return False


def _api(owner: Any) -> Any:
    try:
        resolver = getattr(owner, "_proactive_framework_context", None)
        context = resolver() if callable(resolver) else None
        if context is None:
            context = getattr(owner, "context", None)
        api = getattr(context, "presence_layer", None)
        if (getattr(api, "api_version", None) != 1 or not api.active or not api.context_enabled
                or not callable(getattr(api, "scope_for_session", None))
                or not callable(getattr(api, "render_context", None))):
            return None
        return api
    except Exception:
        return None


def shared_presence_available(owner: Any, session_id: str) -> bool:
    api = _api(owner)
    if api is None or not callable(getattr(api, "context_renderer", None)):
        return False
    try:
        scope = api.scope_for_session(str(session_id or ""))
        return isinstance(scope, dict) and scope.get("private") is True
    except Exception:
        return False


async def temporary_context_parts(owner: Any, *, session_id: str, query: str = "",
                                  channel: str = "pc_proactive", max_chars: int = 420) -> list:
    """Refresh and project request-only context, without changing the prompt."""
    api = _api(owner)
    if api is None:
        return []
    try:
        # Check the native temporary channel before consuming policy dedupe.
        from astrbot.core.agent.message import TextPart
        if not callable(getattr(TextPart, "mark_as_temp", None)):
            return []
        scope = api.scope_for_session(str(session_id or ""))
        if not isinstance(scope, dict) or scope.get("private") is not True:
            return []
        await api.refresh(scope, timeout_seconds=2)
        if api.scope_for_session(str(session_id or "")) != scope or not api.context_enabled:
            return []
        text = api.render_context(scope, query=str(query or "")[:2048], max_chars=max_chars, channel=channel)
        if not isinstance(text, str) or not text:
            return []
        return [TextPart(text=text).mark_as_temp()]
    except Exception:
        return []
