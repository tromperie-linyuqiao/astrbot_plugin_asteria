"""Thin AstrBot host adapter for the optional shared Presence contract."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import re
import sqlite3
import time
from typing import Any

from .presence import PresenceLayer
from .presence_context import PresenceContextPolicy, drop_request_context
from . import mood_signals, decay
from .living.context_config_inheritance import any_context_enabled, effective_context_values


def _text(value: Any, maximum: int = 100) -> str:
    return ' '.join(re.sub(r'[\x00-\x1f\x7f<>]', ' ', str(value or '')).split())[:maximum]


class PresenceIntegration:
    def __init__(self, plugin: Any, context: Any):
        self.plugin, self.context = plugin, context
        self.policy = PresenceContextPolicy()
        self.api = None
        self.living_host = None
        self._closing_living = None
        self._living_error = None
        self._living_recovery_retry_dir = None
        self.start()

    def _enabled(self) -> bool:
        enabled = not getattr(self.plugin, '_stopping', False) and self.plugin._cfg_bool('presence_layer_enabled', True)
        if not enabled:
            self.policy.clear()
        return enabled

    def _context_enabled(self) -> bool:
        enabled = self._enabled() and any_context_enabled(self.plugin)
        if not enabled:
            self.policy.clear()
        return enabled

    def _role(self, user: str) -> str | None:
        resolved = self.plugin._resolve_session(user)
        return resolved[0] if resolved is not None else None

    def start(self) -> None:
        if self.api is not None:
            return
        self.api = PresenceLayer(role_resolver=self._role, enabled=self._enabled,
                                 context_enabled=self._context_enabled, context_renderer=self._project_context)
        self.api.register('presence.environment', owner=self, domains=('time', 'weather'),
                          collector=self._collect_environment, renderer=self._render_environment, enabled=self._enabled)
        self.api.register('presence.reading',owner=self,domains=('reading',),collector=self._collect_reading,
                          renderer=self._render_environment,
                          enabled=lambda:self._enabled() and self.plugin._cfg_bool('mo_enabled',True)
                              and self.plugin._cfg_bool('mo_reading_enabled',True))
        self.api.register('presence.body',owner=self,domains=('virtual.body',),renderer=self._render_virtual,
                          enabled=lambda:self._enabled() and self.plugin._cfg_bool('vb_enabled',True))
        self.api.register('presence.space',owner=self,domains=('virtual.space',),renderer=self._render_virtual,
                          enabled=lambda:self._enabled() and self.plugin._space_enabled())
        setattr(self.context, 'presence_layer', self.api)

    def close(self) -> None:
        self._living_recovery_retry_dir = None
        if self.living_host is not None:
            self.living_host.stop()
            self._closing_living = self.living_host
            self.living_host = None
        if self.api is not None:
            self.api.close()
            if getattr(self.context, 'presence_layer', None) is self.api:
                delattr(self.context, 'presence_layer')
        self.api = None
        self.policy.clear()

    async def aclose(self) -> None:
        self.close()
        host = self._closing_living
        if host is not None:
            await host.close()
            controller = getattr(host, 'native_phone_music', None)
            pending = controller is not None and controller.diagnostics()['restore_pending']
            if self._closing_living is host and not pending:
                self._closing_living = None

    async def configure_living(self, data_dir: str) -> bool:
        """Bind optional storage after profiles/bindings exist; retain this API."""
        if self.api is None or not self.api.active:
            self._living_recovery_retry_dir = None
            return False
        if self.living_host is not None:
            self._living_recovery_retry_dir = None
            return True
        from .living.host import LivingHost
        host = None
        try:
            from .living.native_phone_music_runtime import restore_phone_music_recovery
            if not restore_phone_music_recovery(self.context):
                self._living_error = 'NativePhoneMusicRestorePending'
                self._living_recovery_retry_dir = (str(data_dir)
                    if self.plugin._cfg_bool('living_system_enabled', False) else None)
                return False
            # Only a pending RAM restoration schedules this narrow retry.
            # An ordinary construction/configuration failure does not recur.
            self._living_recovery_retry_dir = None
            if self._living_error == 'NativePhoneMusicRestorePending':
                self._living_error = None
            # Stopping optional TLS must not silently release an existing
            # Native/shadow lease after a new Presence API is constructed.
            from .living.presence_mode import restore_presence_tombstone
            if not self.plugin._cfg_bool('living_system_enabled', False):
                from .living.frequency_mode import restore_frequency_tombstone
                await restore_frequency_tombstone(self.context, data_dir)
                await restore_presence_tombstone(self.api, data_dir)
                return False
            # A trusted local bootstrap may supply this dependency; no config
            # setting or LLM-facing tool changes the default host environment.
            frequency_factory = getattr(self.context, '_tls_frequency_factory', None)
            options = {'frequency_factory': frequency_factory} if callable(frequency_factory) else {}
            presence_factory = getattr(self.context, '_tls_presence_policy_factory', None)
            if callable(presence_factory):
                options['presence_policy_factory'] = presence_factory
            host = LivingHost(self.plugin, self.context, self.api, **options)
            if await host.start(data_dir):
                self.living_host = host
                self._living_error = None
                return True
        except asyncio.CancelledError:
            if host is not None:
                await host.close()
            raise
        except (OSError, sqlite3.Error, ValueError, ImportError, RuntimeError) as exc:
            self._living_error = type(exc).__name__
            if host is not None:
                await host.close()
            return False
        except BaseException:
            if host is not None:
                await host.close()
            raise
        if host is not None:
            await host.close()
        return False

    def scope(self, event: Any) -> dict | None:
        if self.api is None or not self.api.active:
            return None
        if getattr(event, 'private_companion_proactive_framework', False):
            scope = self.api.scope_for_session(str(getattr(event, 'unified_msg_origin', '') or ''))
            if scope is None:
                return None
        else:
            scope = self.api.scope_for_event(event)
        if not scope.get('private') or not scope.get('character_id') or not scope.get('user_id'):
            return None
        if not getattr(event, 'private_companion_proactive_framework', False):
            self.api.remember_scope(scope)
            remember = getattr(self.living_host, 'remember_scope', None)
            if callable(remember):
                remember(scope)
        return scope

    async def living_tick(self) -> None:
        retry_dir = getattr(self, '_living_recovery_retry_dir', None)
        if (self.api is None or not self.api.active
                or not self.plugin._cfg_bool('living_system_enabled', False)):
            self._living_recovery_retry_dir = None
            retry_dir = None
        from .living.native_phone_music_runtime import restore_phone_music_recovery
        if not restore_phone_music_recovery(self.context):
            return
        if retry_dir is not None:
            self._living_recovery_retry_dir = None
            await self.configure_living(retry_dir)
        if self.living_host is not None:
            await self.living_host.living_tick()

    def remember_event(self, event: Any) -> None:
        try:
            if not getattr(event, 'private_companion_proactive_framework', False):
                self.scope(event)
        except Exception:
            return

    def _scoped_context_enabled(self, scope) -> bool:
        return self._enabled() and effective_context_values(self.plugin, scope)['presence_context_enabled']

    def _context_max_chars(self, scope=None) -> int:
        return effective_context_values(self.plugin, scope)['presence_context_max_chars']

    def _repeat_seconds(self, scope=None) -> int:
        return effective_context_values(self.plugin, scope)['presence_repeat_seconds']

    def unified(self):
        """Optional isolated composition; no second plugin or production switch."""
        runtime = getattr(self.living_host, 'runtime', None)
        value = getattr(runtime, 'unified', None)
        return value if value is not None and value.active else None

    def begin_context(self, event, req):
        unified = self.unified()
        if unified is not None:
            scope = self.scope(event)
            if scope is not None:
                unified.begin_request(req, scope)

    def stage_context(self, event, req, block, domain):
        unified = self.unified()
        if unified is None:
            return False
        scope = self.scope(event)
        if scope is not None:
            unified.stage(req, scope, block, domain)
        # A denied optional source cannot bypass unified ownership by taking
        # the old outlet. No production path supplies the isolated factory.
        return True

    def _prepare_context(self, scope: dict, *, query: str = '', max_chars: int = 420,
                         now: float, channel: str = 'ordinary',
                         previous: list[str] | None = None) -> tuple[str, list, dict]:
        memory_scope = dict(scope, _presence_channel=str(channel)[:64])
        if (self.api is None or not self.api.context_enabled or not self._scoped_context_enabled(scope) or not scope.get('private')
                or self._role(str(scope.get('user_id') or '')) != scope.get('character_id')):
            return '', [], memory_scope
        maximum = min(max_chars, self._context_max_chars(scope))
        if maximum < 160:
            return '', [], memory_scope
        # Dedupe state is specific to a generation outlet, while the facts and
        # identity remain a single shared snapshot. The API ignores this
        # private policy key when reading provider records.
        block, selected = self.policy.build(self.api,memory_scope,self.api.snapshot(scope,now=now),
            query=query, max_chars=maximum, repeat_seconds=self._repeat_seconds(scope), now=now,
            retry_domains=self.policy.retry_domains(memory_scope, previous or []))
        return block, selected, memory_scope

    def _project_context(self, scope: dict, *, query: str = '', max_chars: int = 420,
                         now: float, channel: str = 'ordinary') -> str:
        block, selected, memory_scope = self._prepare_context(
            scope, query=query, max_chars=max_chars, now=now, channel=channel)
        if block:
            self.policy.committed(memory_scope, selected, now=now, chars=len(block), projection=block)
        return block

    async def _collect_environment(self, scope: dict, now: float) -> list[dict]:
        if not scope.get('private') or self._role(str(scope.get('user_id') or '')) != scope.get('character_id'):
            return []
        offset = self.plugin._tz()
        tz = timezone(timedelta(hours=offset)) if offset is not None else datetime.now().astimezone().tzinfo
        local = datetime.fromtimestamp(now, tz)
        clock = local.strftime('%Y-%m-%d %H:%M') + ' 星期' + '一二三四五六日'[local.weekday()]
        rows = [{'domain':'time', 'value':{'local':clock, 'utc_offset_hours':offset},
                 'observed_at':now, 'ttl_seconds':90, 'evidence_kind':'observed'}]
        data_dir = str(getattr(self.plugin, '_space_data_dir', '') or '')
        weather = await asyncio.to_thread(mood_signals.read_weather, data_dir, now=now) if data_dir else None
        weather = weather if isinstance(weather, dict) else {}
        fresh = weather.get('available') is True
        observed = weather.get('observed_at')
        if observed is None:
            observed = mood_signals._weather_observed_at(weather.get('updated_at'))
        rows.append({'domain':'weather', 'value':{'city':_text(weather.get('city'),60),
                                                'condition':_text(weather.get('condition'),120) if fresh else None,
                                                'is_rain':weather.get('is_rain') if fresh else None,
                                                'location_scope':'last_weather_query'},
                     'status':'fresh' if fresh else 'stale' if weather.get('stale') else 'unknown',
                     'observed_at':observed, 'ttl_seconds':21600, 'evidence_kind':'observed'})
        return rows

    async def _collect_reading(self, scope: dict, now: float) -> list[dict]:
        if (not self.plugin._cfg_bool('mo_reading_enabled',True)
                or not scope.get('private')
                or self._role(str(scope.get('user_id') or '')) != scope.get('character_id')):
            return []
        rows=[]
        # Reuse the existing tick sample instead of re-scanning all book
        # chapter files on each ordinary chat request.
        reading = (getattr(self.plugin, '_last_signals', {}) or {}).get('reading')
        reading_at = decay.parse_ts((getattr(self.plugin, '_tick_health', {}) or {}).get('last_at'))
        if isinstance(reading, dict) and reading.get('available') is True:
            rows.append({'domain':'reading', 'value':reading, 'observed_at':reading_at,
                         'ttl_seconds':90, 'evidence_kind':'inferred'})
        else:
            rows.append({'domain':'reading', 'value':None, 'observed_at':None,
                         'status':'unknown', 'ttl_seconds':90, 'evidence_kind':'inferred'})
        return rows

    @staticmethod
    def _render_environment(domain: str, record: dict, scope: dict, query: str, maximum: int, now: float) -> str:
        value = record.get('value') or {}
        if record.get('status') != 'fresh' or not isinstance(value, dict):
            return ''
        if domain == 'time':
            text = '当前服务器时间：' + _text(value.get('local'),50) + '；不据时间猜测用户活动。'
        elif domain == 'weather':
            city, condition = _text(value.get('city'),40), _text(value.get('condition'),100)
            if not condition:
                return ''
            text = ('最近有效天气查询' + ('（'+city+'）' if city else '') + '：' + condition +
                    '；查询地点不自动代表用户当前位置。')
        elif domain == 'reading':
            name = _text(value.get('book_title'),60)
            text = ('书柜资料消化进度：'+name if name else '有可用的书柜资料消化进度') + '；不猜测用户正在阅读。'
        else:
            return ''
        return text if len(text) <= maximum else ''

    @staticmethod
    def _render_virtual(domain: str, record: dict, scope: dict, query: str, maximum: int, now: float) -> str:
        value = record.get('value') or {}
        text = value.get('summary') if isinstance(value, dict) and record.get('status') == 'fresh' else ''
        return text if isinstance(text,str) and len(text) <= maximum else ''

    def publish_virtual(self, event: Any, domain: str, value: dict, *, now: float) -> None:
        try:
            scope = self.scope(event)
            if scope is not None:
                self.api.update('presence.body' if domain=='virtual.body' else 'presence.space', scope, domain, value, observed_at=now,
                                ttl_seconds=180, evidence_kind='simulated')
        except Exception:
            # A failed optional projection must not suppress the existing
            # body/space injection or change its persistence path.
            return

    async def inject(self, event: Any, req: Any, text_part: Any) -> None:
        from .living.context_engine import ContextAssembler
        owned = getattr(req, '_tls_context_state', None)
        ContextAssembler._clear_owned(req)
        previous = drop_request_context(req)
        scope = self.scope(event)
        if scope is None or self.api is None or text_part is None:
            return
        unified = self.unified()
        environment_enabled = self.api.context_enabled and self._scoped_context_enabled(scope)
        if not environment_enabled and unified is None:
            return
        if not isinstance(getattr(req, 'extra_user_content_parts', None), list):
            return
        if isinstance(owned, dict):
            from .living.models import scope_key
            if owned.get('scope') == scope_key(scope):
                for key in ('previous_environment', 'environment_projection'):
                    text = owned.get(key)
                    if isinstance(text, str) and len(text) <= 1200:
                        previous.append(text)
        request_state = getattr(req, '_tls_context_state', None)
        if unified is not None and (not isinstance(request_state, dict)
                or request_state.get('owner') is not unified.assembler):
            request_state = unified.begin_request(req, scope)
        started = self.api
        # The environment switch only controls provider collection/rendering.
        # Native memory and already-staged body/space still use this one outlet.
        if environment_enabled:
            await started.refresh(scope, timeout_seconds=2)
        now = time.time()
        # Authorization/binding can change while a device request is pending.
        if self.api is not started or not started.active or self.scope(event) != scope:
            return
        environment_enabled = started.context_enabled and self._scoped_context_enabled(scope)
        if not environment_enabled and unified is None:
            return
        if unified is not None and (self.unified() is not unified
                or getattr(req, '_tls_context_state', None) is not request_state):
            return
        # Another invocation can share the collection while using this same
        # request. Re-read its current list after the await, so only one owned
        # fragment survives and we never append to a detached, obsolete list.
        previous.extend(drop_request_context(req))
        parts = getattr(req, 'extra_user_content_parts', None)
        if not isinstance(parts, list):
            return
        synthetic = getattr(event,'private_companion_proactive_framework',False)
        block, selected, memory_scope = '', [], None
        if environment_enabled:
            block, selected, memory_scope = self._prepare_context(scope,
                query='' if synthetic else str(getattr(event,'message_str','') or ''),
                max_chars=self._context_max_chars(scope), now=now,
                channel='pc_framework' if synthetic else 'ordinary', previous=previous)
        unified = self.unified()
        if unified is not None:
            material = await unified.inject(req, scope,
                query='' if synthetic else str(getattr(event, 'message_str', '') or ''),
                environment_block=block, text_part=text_part)
            if block and 'presence.context' in material['selected']:
                self.policy.committed(memory_scope, selected, now=now, chars=len(block), projection=block)
            return
        if block:
            parts.append(text_part(text=block).mark_as_temp())
            self.policy.committed(memory_scope, selected, now=now, chars=len(block), projection=block)

    async def query(self, event: Any, aspect: str = '') -> str:
        scope = self.scope(event)
        if scope is None or self.api is None:
            return '当前会话没有可用的环境感知权限。'
        started = self.api
        await started.refresh(scope, timeout_seconds=2)
        now = time.time()
        if self.api is not started or not started.active or self.scope(event) != scope:
            return '当前环境信息暂不可用。'
        block, _ = self.policy.build(started,scope,started.snapshot(scope,now=now),
                                     query=str(aspect or ''), aspect=str(aspect or '')[:128],
                                     max_chars=800,now=now,force=True)
        self.policy.metrics['queries'] += 1
        if not block:
            return '没有这个方面的有效环境观测；未知不代表未播放、离线或晴天。'
        # Tool results are evidence, not an extra persona prompt.
        from .presence_context import CONTEXT_START, CONTEXT_END
        return block.replace(CONTEXT_START,'').replace(CONTEXT_END,'').strip()

    def diagnostics(self) -> dict:
        result = self.api.diagnostics() if self.api is not None else {'active':False,'context_enabled':False,'registered_sources':[]}
        result['context'] = dict(self.policy.metrics)
        result['context']['max_chars'] = self._context_max_chars()
        result['context']['repeat_seconds'] = self._repeat_seconds()
        host = self.living_host if self.living_host is not None else self._closing_living
        result['living'] = host.diagnostics() if host is not None else {'active': False}
        from .living.native_phone_music_runtime import phone_music_recovery_diagnostics
        recovery = phone_music_recovery_diagnostics(self.context)
        if recovery is not None:
            result['living']['native_phone_music'] = recovery
        if self._living_error is not None:
            result['living']['error_type'] = self._living_error
        return result
