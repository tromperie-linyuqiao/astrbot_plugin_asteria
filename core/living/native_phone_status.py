"""One bounded status projection over the native Phone owner's existing cache.

No collector, database, lease, delivery or authorization is created here. An
explicit read reuses PerceptionClient.get_state and its original lock/cache.
"""
from __future__ import annotations

import math
import re
import time

from .models import private_scope


SOURCE_FIELDS = {
    'battery': ('level', 'charging', 'charging_type', 'temperature_c', 'health', 'cycle_count'),
    'screen': ('on', 'locked'), 'network': ('type', 'roaming', 'metered'),
    'audio': ('media_active', 'headphones', 'ringer_mode'),
    'device': ('name', 'platform', 'os_version', 'battery_temp_c', 'power_save'),
    'activity': ('steps_today', 'device_idle', 'last_unlock_epoch'),
    'app': ('foreground_package', 'foreground_label', 'foreground_since_epoch', 'foreground_minutes', 'swipe_events_per_min'),
    'music': ('schema_version', 'source', 'state', 'playing', 'observed_at', 'title', 'artist', 'album',
              'package', 'track_id', 'duration_ms', 'progress_ms', 'playback_speed'),
    'location': (),
}


def number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def display(value):
    if type(value) is bool or type(value) in (int, float) and math.isfinite(value):
        return value
    if isinstance(value, str):
        value = re.sub(r'https?://\S+', '[地址已隐藏]', value[:1024], flags=re.I)
        value = re.sub(r'(?i)(?:bearer\s+|token\s*[:=]\s*)[A-Za-z0-9._~+/=-]+', '[凭据已隐藏]', value)
        return ' '.join(re.sub(r'[\x00-\x1f\x7f<>]', ' ', value).split())[:256]
    return None


def error(code, message, status=None):
    return {'code': code, 'message': display(message), 'http_status': status if type(status) is int else None}


def source_row(status='unknown', *, reason=None, device=None):
    return {'status': status, 'value': None, 'device_id': device, 'last_received_at': None,
            'observed_at': None, 'expires_at': None, 'received_basis': None,
            'stale': status == 'stale', 'unauthorized': status == 'unauthorized',
            'unavailable': status == 'unavailable', 'error': reason}


def empty_status(now, status='unavailable', reason=None, *, configured=None):
    return {'schema': 1, 'generated_at': now, 'device_id': None, 'devices': [],
            'access': {'authorized': False, 'reason': reason['code'] if reason else status},
            'transport': {'configured': configured, 'state': 'unconfigured' if configured is False else 'unknown',
                          'last_attempt_at': None, 'last_success_at': None, 'error': reason},
            'sources': {key: source_row(status, reason=reason) for key in SOURCE_FIELDS}}


def project_source(section, cached, *, now, ttl, device, request):
    row = source_row(device=device)
    view = cached.get('view')
    facts = view.get('state') if isinstance(view, dict) and view.get('ok') is True else None
    raw = facts.get(section) if isinstance(facts, dict) else None
    http = request.get('http_status')
    if http in (401, 403) or request.get('authorization_denied') is True:
        message = request.get('error') if http in (401, 403) else '此前访问被感知桥拒绝，尚无后续成功访问确认授权恢复'
        return source_row('unauthorized', reason=error('bridge_unauthorized', message or '感知桥拒绝当前访问',
                                                     http if http in (401, 403) else request.get('authorization_status')), device=device)
    if isinstance(view, dict) and view.get('ok') is True and view.get('device_id') != device:
        return source_row('unavailable', reason=error('device_response_mismatch', '感知桥返回的设备身份与所选设备不符，未展示数据'), device=device)
    if section == 'location':
        # The retained PPB contract has no location field or location grant.
        # Receiving an unexpected coordinate is not permission to disclose it.
        return source_row('unauthorized' if raw is not None else 'unavailable',
            reason=error('location_permission_unverified' if raw is not None else 'source_not_provided',
                         '尚无可核验的位置读取授权' if raw is not None else '现有感知来源未提供位置'), device=device)
    if not isinstance(raw, dict):
        reason = error(request.get('error_code') or 'source_not_received', request.get('error') or '尚未收到此来源的状态', http)
        return source_row('unavailable' if request.get('error_code') else 'unknown', reason=reason, device=device)
    row['value'] = {key: display(raw[key]) for key in SOURCE_FIELDS[section] if key in raw and display(raw[key]) is not None} or None
    received = number(request.get('last_success_at'))
    if received is not None:
        row.update(last_received_at=received, received_basis='tls_bridge_response')
    server = number(view.get('server_time'))
    generated = server if server is not None else number(cached.get('fetched_at'))
    ages = view.get('section_age_seconds')
    age = number(ages.get(section) if isinstance(ages, dict) and ages else view.get('age_seconds'))
    observed = generated - age if generated is not None and age is not None else None
    actual = number(raw.get('observed_at'))
    if section == 'music':
        observed = min(observed, actual) if observed is not None and actual is not None and 0 < actual <= now + 30 else None
    if observed is not None and (observed <= 0 or observed > now + 30 or server is not None and server > now + 30):
        observed = None
    row.update(observed_at=observed, expires_at=observed + ttl if observed is not None else None)
    if observed is None:
        row.update(error=error('observation_time_unavailable', '来源缺少可核验的观察时间，不能判断当前新鲜度'))
    else:
        row['status'] = 'stale' if now > observed + ttl else 'fresh'
        row['stale'] = row['status'] == 'stale'
    if section == 'music' and (type(raw.get('schema_version')) is not int or raw.get('schema_version') != 1 or raw.get('source') != 'media_session'
            or raw.get('state') not in {'playing', 'paused', 'stopped', 'buffering', 'unknown'} or type(raw.get('playing')) is not bool
            or raw.get('playing') != (raw.get('state') == 'playing')):
        row.update(status='unavailable', unavailable=True, error=error('reliable_music_unavailable', '没有可靠的媒体会话播放事实'))
    elif row['value'] is None:
        row.update(status='unknown', error=error('source_empty', '此来源没有可显示的事实字段'))
    if request.get('error_code'):
        row.update(status='unavailable', unavailable=True,
                   error=error(request['error_code'], request.get('error') or '最近访问感知桥失败', http))
    return row


class NativePhoneStatus:
    def __init__(self, plugin, *, clock=time.time):
        self.plugin, self.clock = plugin, clock

    def _resolve(self, scope, device_id=None):
        from .native_phone_service.runtime import NativePhoneService
        scope = private_scope(scope)
        service = getattr(self.plugin, '_native_phone_service', None)
        if (not isinstance(service, NativePhoneService) or not service._active or service._music_stopping
                or getattr(self.plugin, '_stopping', False) or service.context is not getattr(self.plugin, 'context', None)):
            return None, [], None, 'phone_service_unavailable', None
        service._sync_client()
        if not service._enabled():
            return service, [], None, 'perception_disabled', None
        adapter = service._presence_adapter
        if not adapter._eligible(scope):
            return service, [], None, 'scope_not_authorized', None
        source = adapter._source_scope(scope)
        devices = service._music_devices_for_user(source['user_id']) if source else []
        devices = [value for value in devices[:16] if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value)]
        if not devices:
            return service, [], None, 'device_binding_required', None
        if device_id is not None and device_id not in devices:
            return service, [], None, 'device_not_owned', None
        selected = device_id or (devices[0] if len(devices) == 1 else None)
        signature = (id(service), id(service.client), source, tuple(devices), service.client.base_url, service.client.token)
        signature += (service._music_enabled(), service.config.get('show_app', False), service._stale_seconds(), service._music_ttl())
        return service, devices, selected, None, signature

    def _report_receipt(self, source, device):
        """Read only an existing bound installation's matching Journal receipt."""
        try:
            from .chat_identity import identity_service
            from .chat_expressions import ChatExpressions
            links = identity_service(self.plugin)
            link = links.for_qq(source)
            if not link:
                return None
            scope = ChatExpressions.message_scope(link['username'], link['session_id'])
            latest = None
            for row in links.journal.list('tls.chat.perception', scope, limit=65):
                if not row['key'].startswith('status:'):
                    continue
                state = row['data']
                config = links.journal.fetch('tls.chat.perception', 'config:' + row['key'][7:], scope)
                if (not config or config['data'].get('enabled') is not True or config['data'].get('link_id') != link['link_id']
                        or config['data'].get('device_id') != device or state.get('device_id') != device
                        or state.get('config_revision') != config['revision'] or state.get('link_id') != link['link_id']):
                    continue
                if latest is None or (number(state.get('started_at')) or 0) > (number(latest.get('started_at')) or 0):
                    latest = state
            if latest is None or not links.current() or links.get(link['username'], link['session_id']) != link:
                return None
            state = latest.get('state')
            return {'state': state if state in {'accepted', 'rejected', 'unknown'} else 'unknown',
                    'accepted': state == 'accepted', 'started_at': number(latest.get('started_at')),
                    'completed_at': number(latest.get('completed_at')),
                    'http_status': latest.get('bridge_status') if type(latest.get('bridge_status')) is int else None,
                    'provenance': 'existing_journal_report_receipt'}
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, PermissionError):
            return None

    def read(self, scope, *, device_id=None, include_reports=True):
        now = number(self.clock())
        if now is None:
            raise ValueError('valid phone status clock required')
        try:
            service, devices, selected, reason, signature = self._resolve(scope, device_id)
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, PermissionError):
            service, devices, selected, reason = None, [], None, 'scope_unavailable'
        configured = bool(service.client.configured) if service else None
        if reason:
            state = 'disabled' if reason == 'perception_disabled' else 'unauthorized' if reason in {'scope_not_authorized', 'device_not_owned'} else 'unavailable'
            return empty_status(now, state,
                                error(reason, {'scope_not_authorized': '此会话尚无读取手机感知的有效授权',
                                              'device_not_owned': '不能读取未分配给当前身份的设备',
                                              'perception_disabled': '手机感知当前未启用，未读取数据',
                                              'device_binding_required': '当前身份尚无明确分配的设备',
                                              'scope_unavailable': '完整会话身份暂不可核验'}.get(reason, '当前会话或手机来源暂不可用')),
                                configured=configured)
        result = empty_status(now, configured=configured)
        result.update(device_id=selected, devices=[{'id': value, 'label': value} for value in devices])
        result['access'] = {'authorized': True, 'reason': 'ready' if selected else 'device_selection_required'}
        if not selected:
            result['sources'] = {key: source_row(reason=error('device_selection_required', '请选择已分配的具体设备')) for key in SOURCE_FIELDS}
            result['summaries'] = [self.read(scope, device_id=device, include_reports=include_reports) for device in devices]
            try:
                current = self._resolve(scope, None)
            except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, PermissionError):
                current = None
            if current is None or current[3] or current[4] != signature:
                return empty_status(now, 'unauthorized', error('authorization_changed', '读取期间授权或来源配置已改变'))
            return result
        snapshot = getattr(service.client, 'state_snapshot', None)
        cached = snapshot(service._stale_seconds(), selected) if callable(snapshot) else {}
        request = dict(cached.get('request', {}))
        if isinstance(request.get('error'), str):
            for secret, replacement in ((service.client.token, '[凭据已隐藏]'), (service.client.base_url, '[地址已隐藏]')):
                if secret:
                    request['error'] = request['error'].replace(secret, replacement)
        transport = result['transport']
        transport.update(last_attempt_at=number(request.get('last_attempt_at')), last_success_at=number(request.get('last_success_at')), error=None)
        if not configured:
            transport.update(state='unconfigured', error=error('bridge_not_configured', '感知桥地址或访问凭据尚未配置'))
        elif request.get('http_status') in (401, 403):
            transport.update(state='unauthorized', error=error('bridge_unauthorized', request.get('error'), request.get('http_status')))
        elif request.get('error_code'):
            transport.update(state='unavailable', error=error(request['error_code'], request.get('error'), request.get('http_status')))
        elif number(request.get('last_success_at')) is not None:
            transport['state'] = 'reachable'
        for section in SOURCE_FIELDS:
            if not configured:
                result['sources'][section] = source_row('unavailable', reason=transport['error'], device=selected)
            elif section == 'app' and service.config.get('show_app', False) is not True:
                result['sources'][section] = source_row('disabled', reason=error('app_display_disabled', '前台应用感知展示尚未启用'), device=selected)
            elif section == 'music' and not service._presence_adapter._eligible(scope, music=True):
                result['sources'][section] = source_row('disabled', reason=error('music_source_disabled', '音乐感知来源尚未启用'), device=selected)
            else:
                ttl = service._music_ttl() if section == 'music' else service._stale_seconds()
                result['sources'][section] = project_source(section, cached, now=now, ttl=ttl, device=selected, request=request)
            value = result['sources'][section].get('value')
            if isinstance(value, dict) and service.client.token:
                for key, item in value.items():
                    if isinstance(item, str):
                        value[key] = item.replace(service.client.token, '[凭据已隐藏]')
        result['report'] = self._report_receipt(signature[2], selected) if include_reports else None
        try:
            current = self._resolve(scope, selected)
            if current[3] or current[4] != signature:
                return empty_status(now, 'unauthorized', error('authorization_changed', '读取期间授权或来源配置已改变'))
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, PermissionError):
            return empty_status(now, 'unauthorized', error('authorization_changed', '读取期间授权或来源配置已改变'))
        return result

    async def refresh(self, scope, *, device_id=None):
        service, _, selected, reason, signature = self._resolve(scope, device_id)
        if reason or selected is None or not service.client.configured:
            return self.read(scope, device_id=device_id)
        await service.client.get_state(service._stale_seconds(), device=selected)
        current = self._resolve(scope, selected)
        if current[3] or current[4] != signature:
            return self.read(scope, device_id=device_id)
        return self.read(scope, device_id=selected)
