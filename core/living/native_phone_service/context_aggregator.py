"""Small provider boundary; the first registered context is music.

No persona replacement, history writes, delivery API or proactive scheduler.
The host owns SDK TextPart.mark_as_temp() creation and request-local replacement.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .music_context import MUSIC_CONTEXT_END, MUSIC_CONTEXT_MARKER, render_music_context


class ContextAggregator:
    def __init__(self):
        self._providers = {}

    def register(self, name: str, provider: Any) -> None:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
            raise ValueError("invalid provider name")
        if name not in self._providers and len(self._providers) >= 16:
            raise ValueError("provider limit reached")
        if not callable(provider) and not callable(getattr(provider, "observe", None)):
            raise TypeError("provider must be callable or implement observe")
        self._providers[name] = provider

    def collect(self, inputs: dict[str, Any], **kwargs) -> dict[str, dict]:
        if not isinstance(inputs, dict):
            return {}
        events = {}
        for name, provider in self._providers.items():
            if name not in inputs:
                continue
            try:
                observe = getattr(provider, "observe", None)
                result = observe(inputs[name], **kwargs) if callable(observe) else provider(inputs[name], **kwargs)
                if isinstance(result, dict):
                    events[name] = deepcopy(result)
            except Exception as exc:
                # Type-only diagnostic: no source payload, IDs, title or path.
                events[name] = {"event_type": name + "_unknown", "song_id": "", "song_info": {},
                                "match_status": "unknown", "user_state": {"playing": False, "reliable": False},
                                "provider_error_type": type(exc).__name__}
        return events

    def render(self, events: dict[str, dict], *, max_chars: int = 500) -> str:
        return render_music_context(events.get("music"), max_chars=max_chars) if isinstance(events, dict) else ""


def wrap_music_fragment(text: str) -> str:
    return f"{MUSIC_CONTEXT_MARKER}\n{text}\n{MUSIC_CONTEXT_END}" if text else ""


def replace_system_fragment(req: Any, name: str, text: str) -> bool:
    """Fallback when temporary TextParts are unavailable, replacing only ours.

    This touches the current request only. SDK integration should prefer a
    marked temporary part and remove the same owned marker before appending.
    """
    if name != "music" or not hasattr(req, "system_prompt"):
        return False
    current = str(getattr(req, "system_prompt", "") or "")
    pattern = re.escape(MUSIC_CONTEXT_MARKER) + r".*?" + re.escape(MUSIC_CONTEXT_END)
    current = re.sub(pattern, "", current, flags=re.DOTALL).rstrip()
    fragment = wrap_music_fragment(text)
    req.system_prompt = current + ("\n\n" if current and fragment else "") + fragment
    return True
