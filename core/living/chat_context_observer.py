"""Bounded receipts of actual Chat request additions, never model reasoning.

The original SDK checkpoint joins these receipts to saved assistant messages.
No retrieval, provider call, conversation rewrite or additional timer lives here.
"""
from __future__ import annotations

from copy import deepcopy
import re
import time

from .chat_expressions import ChatExpressions
from .native_mc.sensitive_data import redact_sensitive_text

NAMESPACE = 'asteria.chat.context.receipts.v1'
LIMITS = dict(max_records=32, excerpt_chars=800, total_chars=8000, hidden_reasoning=False)
_SLOTS = {
    '_asteria_chat_session_parts': ('会话偏好与身体互动', 'chat.session'),
    '_asteria_chat_daily_parts': ('角色日常', 'chat.daily'),
    '_asteria_chat_corpus_parts': ('参考语料', 'chat.corpus'),
    '_asteria_linked_memory_parts': ('已授权的关联记忆', 'chat.linked_memory'),
    '_asteria_chat_worldline_parts': ('明确追问的生活资料与聊天关联', 'chat.worldline'),
}
_EXTRA = '_asteria_observed_request'
_TOKEN = object()


def safe(value, limit=800):
    text = redact_sensitive_text(str(value or ''))
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    return text[:limit]


def capture(plugin, event, request):
    """Read actual owned parts at the final request hook; do not rerun retrieval."""
    if event.get_platform_name() != 'webchat' or getattr(plugin, '_stopping', False):
        return
    parts = getattr(request, 'extra_user_content_parts', ())
    sections = []
    remaining = LIMITS['total_chars']

    def add(name, source, text, items=()):
        nonlocal remaining
        if not isinstance(text, str) or not text or remaining <= 0 or len(sections) >= 24:
            return
        excerpt = safe(text, min(LIMITS['excerpt_chars'], remaining))
        remaining -= len(excerpt)
        sections.append(dict(name=safe(name, 100), source=safe(source, 160), chars=len(text),
            excerpt=excerpt, truncated=len(excerpt) < len(text), items=list(items)[:16]))

    for slot, (name, source) in _SLOTS.items():
        owned = getattr(request, slot, ())
        texts = [part.text for part in owned if any(part is live for live in parts)
                 and isinstance(getattr(part, 'text', None), str)]
        items=getattr(request,'_asteria_chat_worldline_items',[]) if slot=='_asteria_chat_worldline_parts' else []
        add(name, source, '\n'.join(texts), items)

    state = getattr(request, '_tls_context_state', {})
    if isinstance(state, dict):
        texts = [part.text for part in state.get('emitted', ()) if any(part is live for live in parts)
                 and isinstance(getattr(part, 'text', None), str)]
        add('记忆、生活与当前状态', 'tls.context', '\n'.join(texts), state.get('selection_receipt', []))

    # Reuse the companion's existing real injection receipt. Match the exact
    # event trace AND session; never pick the most recent entry by time.
    owner = plugin._full_pc_service() if callable(getattr(plugin, '_full_pc_service', None)) else None
    trace = getattr(event, 'private_companion_prompt_trace_id', None)
    entries = getattr(owner, 'data', {}).get('recent_prompt_injection_events', []) if owner else []
    if trace:
        for entry in entries:
            if (entry.get('trace_id') != trace or entry.get('session') != str(event.unified_msg_origin)):
                continue
            for item in entry.get('items', []):
                if item.get('kind') != 'passive':
                    continue
                for module in item.get('modules', []):
                    add(module.get('title', '陪伴资料'), module.get('source') or module.get('key'),
                        module.get('content', ''))
            break

    event.set_extra(_EXTRA, (_TOKEN, dict(captured_at=time.time(), sections=sections,
        limits=dict(LIMITS), note='记录实际加入请求的来源摘要，不代表模型逐条采用；不包含隐藏思维链。')))


def captured(event):
    value = event.get_extra(_EXTRA)
    if not isinstance(value, tuple) or len(value) != 2 or value[0] is not _TOKEN:
        return None
    return deepcopy(value[1])


class ContextReceipts:
    def __init__(self, journal, *, current):
        self.journal, self.current = journal, current

    def record(self, username, session_id, checkpoint, receipt, provider_id, model):
        if not isinstance(checkpoint, str) or not 1 <= len(checkpoint) <= 160 or not isinstance(receipt, dict):
            return
        scope = ChatExpressions.message_scope(username, session_id)
        with self.journal._lock:
            if self.current() is not True:
                raise PermissionError('context receipt owner changed')
            old = self.journal.fetch(NAMESPACE, 'recent', scope)
            records = list(old['data'].get('records', [])) if old else []
            entry = deepcopy(receipt)
            entry.update(checkpoint=checkpoint,
                model=dict(state='response_received', provider_id=safe(provider_id, 160), model=safe(model, 160)))
            records = [row for row in records if row.get('checkpoint') != checkpoint]
            records.append(entry)
            self.journal.put(NAMESPACE, 'recent', scope, dict(records=records[-LIMITS['max_records']:]),
                expected_revision=old['revision'] if old else 0, authorize=self.current)

    def read(self, username, session_id, checkpoint, message_id):
        if self.current() is not True:
            raise PermissionError('context receipt owner changed')
        record = self.journal.fetch(NAMESPACE, 'recent', ChatExpressions.message_scope(username, session_id))
        rows = record['data'].get('records', []) if record else []
        found = next((row for row in reversed(rows) if checkpoint and row.get('checkpoint') == checkpoint), None)
        if self.current() is not True:
            raise PermissionError('context receipt owner changed')
        if found:
            value = deepcopy(found)
            value.pop('checkpoint', None)
            return dict(value, state='recorded', message_id=str(message_id))
        return dict(state='not_recorded', message_id=str(message_id), captured_at=None, sections=[],
            model=dict(state='not_recorded'), limits=dict(LIMITS),
            note='这条回复没有保留上下文记录（可能早于此功能或已超出最近32次范围）；当前资料不能代替当时记录。')

