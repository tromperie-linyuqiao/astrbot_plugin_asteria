"""Task-specific choices over AstrBot's existing providers and TLS Journal.

No keys, prompts or completions are copied. Unconfigured tasks retain their
current provider chain; this router neither creates a model nor a scheduler.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import math
import time

from .models import canonical, private_scope

NAMESPACE = 'tls.task.model.routing.v1'
SCOPE = private_scope(dict(platform='tls', bot_id='model-routing', user_id='administrator',
                           character_id='system', session_id='task-model-routing', private=True))
TASKS = {'chat': '普通聊天', 'rp': '复杂角色互动', 'summary': '记忆摘要',
         'memory_filter': '记忆筛选', 'archive_review': '档案审阅',
         'classification': '分类与历史提取', 'insight': '数据洞察'}
ALIASES = {'memory_summary': 'summary', 'memory_decay_summary': 'summary',
           'memory_audit_preview': 'archive_review', 'historical_chat_summary': 'summary',
           'historical_chat_phase_summary': 'summary', 'historical_chat_reconcile': 'archive_review',
           'historical_chat_detail_enrichment': 'classification',
           'historical_chat_daily_enrichment': 'classification'}
DEFAULT = {'preferred_provider_id': '', 'fallback_provider_id': ''}


def task_name(value):
    name = ALIASES.get(value, value)
    if name not in TASKS:
        raise ValueError('请选择已接入的模型任务')
    return name


def _identity(value, *, blank=False):
    if (not isinstance(value, str) or len(value) > 160 or value != value.strip()
            or not blank and not value or any(ord(ch) < 32 for ch in value)):
        raise ValueError('模型提供商编号无效')
    return value


def provider_id(provider):
    try:
        meta = provider.meta()
        value = meta.get('id') if isinstance(meta, dict) else getattr(meta, 'id', '')
        return _identity(value)
    except (AttributeError, TypeError, ValueError):
        config = getattr(provider, 'provider_config', None)
        value = config.get('id', '') if isinstance(config, dict) else ''
        try: return _identity(value)
        except ValueError: return ''


def router_for(context):
    value = getattr(context, '_tls_task_model_router', None)
    return value if isinstance(value, TaskModelRouter) and value.current() is True else None


def _number(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def response_usage(response):
    """Use reported SDK/OpenAI usage only. Missing data is unknown, not zero."""
    usage = getattr(response, 'usage', None)
    if usage is None and isinstance(response, dict): usage = response.get('usage')
    if usage is None:
        raw = getattr(response, 'raw_completion', None)
        usage = raw.get('usage') if isinstance(raw, dict) else getattr(raw, 'usage', None)
    def get(name):
        return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    if usage is None: return None
    # AstrBot 4.26.6 TokenUsage.input already includes cached input tokens.
    prompt = _number(get('input'))
    if prompt is None:
        other, cached = _number(get('input_other')), _number(get('input_cached'))
        if other is not None and cached is not None: prompt = other + cached
    if prompt is None: prompt = _number(get('prompt_tokens'))
    if prompt is None: prompt = _number(get('input_tokens'))
    output = _number(get('output'))
    if output is None: output = _number(get('completion_tokens'))
    if output is None: output = _number(get('output_tokens'))
    total = _number(get('total'))
    if total is None: total = _number(get('total_tokens'))
    if total is None and prompt is not None and output is not None: total = prompt + output
    if prompt is None and output is None and total is None: return None
    return dict(input_tokens=prompt, output_tokens=output, total_tokens=total,
                source='provider_reported', estimated=False)


class TaskModelRouter:
    def __init__(self, context, journal, *, current, clock=time.time):
        if not callable(current) or not callable(clock): raise ValueError('current router owner required')
        self.context, self.journal, self.current, self.clock = context, journal, current, clock
        self.telemetry_dropped = 0

    def _check(self):
        if self.current() is not True: raise RuntimeError('任务模型服务正在更新')

    def _providers(self):
        self._check()
        values = self.context.get_all_providers()
        if not isinstance(values, (list, tuple)) or len(values) > 256:
            raise RuntimeError('当前文本模型列表不可用')
        result = {}
        for value in values:
            identity = provider_id(value)
            if identity and callable(getattr(value, 'text_chat', None)):
                result[identity] = value
        self._check()
        return result

    def providers(self):
        result = []
        for identity, value in self._providers().items():
            try: meta = value.meta()
            except (AttributeError, TypeError, ValueError): meta = None
            def label(key):
                raw = meta.get(key) if isinstance(meta, dict) else getattr(meta, key, '')
                return raw[:160] if isinstance(raw, str) and not any(ord(c) < 32 for c in raw) else ''
            result.append(dict(id=identity, model=label('model'), type=label('type')))
        return sorted(result, key=lambda item: item['id'])

    def settings(self):
        self._check()
        row = self.journal.fetch(NAMESPACE, 'settings', SCOPE)
        routes = row['data'].get('routes', {}) if row else {}
        return dict(routes={name: dict(DEFAULT, **routes.get(name, {})) for name in TASKS},
                    revision=row['revision'] if row else 0)

    def save(self, changes, expected_revision):
        if type(changes) is not dict or not changes or set(changes) - set(TASKS):
            raise ValueError('任务模型设置包含未知任务')
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('请先读取当前模型设置版本')
        available = self._providers()
        normalized = {}
        for task, value in changes.items():
            if type(value) is not dict or set(value) != set(DEFAULT):
                raise ValueError('每项须明确提供首选和备选模型；留空表示继承')
            route = {key: _identity(value[key], blank=True) for key in DEFAULT}
            selected = [identity for identity in route.values() if identity]
            if any(identity not in available for identity in selected):
                raise ValueError('所选模型不在当前AstrBot文本提供商列表中，请刷新')
            if len(selected) != len(set(selected)): raise ValueError('首选和备选模型不能相同')
            normalized[task] = route
        with self.journal._lock:
            snapshot = self.settings()
            routes = dict(snapshot['routes'], **normalized)
            def current():
                if self.current() is not True: return False
                live = self._providers()
                return all(live.get(identity) is available[identity]
                           for value in normalized.values() for identity in value.values() if identity)
            self.journal.put(NAMESPACE, 'settings', SCOPE, dict(routes=routes),
                             expected_revision=expected_revision, authorize=current)
        return self.settings()

    def route_attempts(self, task, existing=(), *, umo=None):
        """Reorder real providers; the caller retains its existing fallback loop."""
        task = task_name(task); settings = self.settings()['routes'][task]
        configured = any(settings.values())
        if not configured and existing:
            self._check()
            return list(existing)  # Preserve the original fallback contract.
        available = self._providers() if configured else {}
        result, seen = [], set()
        def append(provider, identity, source, original=None):
            if provider is None or not callable(getattr(provider, 'text_chat', None)) or id(provider) in seen: return
            seen.add(id(provider))
            result.append(dict(original or {}, provider=provider, provider_id=identity,
                               source=source, route_task=task))
        for key, source in [('preferred_provider_id', 'task_preferred'), ('fallback_provider_id', 'task_fallback')]:
            identity = settings[key]
            if identity: append(available.get(identity), identity, source)
        for item in existing:
            if isinstance(item, dict):
                provider = item.get('provider')
                append(provider, item.get('provider_id') or provider_id(provider), item.get('source', 'inherited'), item)
        if not existing and not result:
            provider = self.context.get_using_provider(umo)
            append(provider, provider_id(provider), 'current_session')
        self._check()
        return result

    def select_provider_id(self, task, *, umo=None, explicit_provider_id=None):
        """SDK chat override only when configured; preserve explicit user choice."""
        if explicit_provider_id: return explicit_provider_id
        task = task_name(task)
        if not any(self.settings()['routes'][task].values()): return None
        values = self.route_attempts(task, umo=umo)
        return values[0]['provider_id'] if values else None

    async def text_chat(self, task, *, inherited=(), umo=None, **kwargs):
        """Optional direct boundary for an existing single worker, never a new job."""
        error = None
        attempts = self.route_attempts(task, inherited, umo=umo)
        for item in attempts:
            self._check(); started = time.monotonic()
            try:
                response = await item['provider'].text_chat(**kwargs)
            except asyncio.CancelledError:
                self.record(task, item['provider_id'], success=False, elapsed_ms=int((time.monotonic()-started)*1000), error_type='CancelledError')
                raise
            except Exception as exc:
                self.record(task, item['provider_id'], success=False, elapsed_ms=int((time.monotonic()-started)*1000), error_type=type(exc).__name__)
                error = exc
                continue
            self.record(task, item['provider_id'], response=response, elapsed_ms=int((time.monotonic()-started)*1000))
            self._check()
            return response
        if error is not None: raise error
        raise RuntimeError('当前任务没有可用的文本模型')

    def record(self, task, provider, *, response=None, success=True, elapsed_ms=0, error_type='', call_id=None):
        """Count actual calls. Never estimate tokens or copy provider error text."""
        try:
            task = task_name(task); self._check()
            identity = _identity(provider or '(unknown)')
            if type(success) is not bool or type(elapsed_ms) is not int or elapsed_ms < 0:
                raise ValueError('actual call outcome required')
            token = None
            if call_id is not None:
                if not isinstance(call_id, str) or not 1 <= len(call_id) <= 256: raise ValueError('call identity invalid')
                token = hashlib.sha256(canonical([task, identity, call_id]).encode()).hexdigest()
            usage = response_usage(response)
            stamp = self.clock()
            if type(stamp) not in (int, float) or not math.isfinite(stamp): raise ValueError('invalid usage clock')
            with self.journal._lock:
                old = self.journal.fetch(NAMESPACE, 'usage', SCOPE)
                data = deepcopy(old['data']) if old else dict(tasks={}, recent=[], call_ids=[])
                if token and token in data['call_ids']: return False
                bucket = data['tasks'].setdefault(task, dict(calls=0, successes=0, failures=0,
                    input_tokens=0, output_tokens=0, total_tokens=0, usage_unknown_calls=0))
                bucket['calls'] += 1; bucket['successes' if success else 'failures'] += 1
                if usage is None or any(usage[key] is None for key in ('input_tokens', 'output_tokens', 'total_tokens')):
                    bucket['usage_unknown_calls'] += 1
                else:
                    for key in ('input_tokens', 'output_tokens', 'total_tokens'):
                        if usage[key] is not None: bucket[key] += usage[key]
                data['recent'] = (data['recent'] + [dict(task=task, provider_id=identity, success=success,
                    at=stamp, elapsed_ms=elapsed_ms, usage=usage, cost=None, cost_state='unknown',
                    error_type=error_type if isinstance(error_type, str) and error_type.isidentifier() else '')])[-64:]
                if token: data['call_ids'] = (data['call_ids'] + [token])[-128:]
                self.journal.put(NAMESPACE, 'usage', SCOPE, data, expected_revision=old['revision'] if old else 0, authorize=self.current)
            return True
        except (ValueError, TypeError, RuntimeError, PermissionError, OSError):
            self.telemetry_dropped += 1
            return False

    def snapshot(self):
        settings = self.settings()
        usage = self.journal.fetch(NAMESPACE, 'usage', SCOPE)
        return dict(**settings, tasks=[dict(id=name, label=label) for name, label in TASKS.items()],
                    providers=self.providers(), usage={key: usage['data'][key] for key in ('tasks', 'recent')} if usage else dict(tasks={}, recent=[]),
                    telemetry_dropped=self.telemetry_dropped, cost_state='unknown',
                    usage_note='仅统计已接入此路由的真实调用；缺少用量不按0估算，未配置价格不估算费用。',
                    credential_fields_returned=False, creates_model=False, creates_scheduler=False)
