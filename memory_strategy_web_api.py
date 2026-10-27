"""Normal AstrBot administrator settings for the existing memory consumers."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

from astrbot.api.web import request, json_response, error_response
from .core.living.memory_routing_strategy import DEFAULTS, validate_settings, public_contract

PREFIX = '/astrbot_plugin_virtual_body/page/memory-strategy'


class _Conflict(RuntimeError):
    pass


class NativeMemoryStrategyWebApi:
    def __init__(self, plugin):
        self.plugin = plugin
        lock = getattr(plugin, '_native_console_config_lock', None)
        if lock is None:
            lock = threading.RLock()
            plugin._native_console_config_lock = lock
        self.lock = lock
        # One existing config source, read synchronously from RAM by capture.
        # No file IO, database, model, timer or scope grant is added per message.
        plugin.context._tls_memory_strategy_settings = self._values

    def register_routes(self):
        for suffix, method in (('config', 'GET'), ('config/save', 'POST')):
            self.plugin.context.register_web_api(PREFIX + '/' + suffix,
                self.save if method == 'POST' else self.read, [method],
                'TLS memory routing administrator settings')

    def _values(self):
        with self.lock:
            return validate_settings({key: deepcopy(self.plugin.config.get(key, default))
                                      for key, default in DEFAULTS.items()})

    def _snapshot(self):
        values = self._values()
        path = getattr(self.plugin.config, 'config_path', None)
        persisted, file_hash = False, None
        if isinstance(path, (str, Path)) and str(path):
            data = Path(path).read_bytes()
            if len(data) > 8 * 1024 * 1024:
                raise ValueError('configuration capacity')
            document = json.loads(data.decode('utf-8-sig'))
            if not isinstance(document, dict):
                raise ValueError('configuration object required')
            file_hash = hashlib.sha256(data).hexdigest()
            persisted = (all(self.plugin.config.get(key, default) == document.get(key, default)
                             for key, default in DEFAULTS.items())
                and all(key in self.plugin.config and self.plugin.config[key] == value
                        for key, value in document.items() if key not in DEFAULTS))
        revision = hashlib.sha256(json.dumps([values, file_hash], sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        return {'values': values, 'defaults': dict(DEFAULTS), 'revision': revision,
                'persisted_verified': persisted,
                'writable': persisted and callable(getattr(self.plugin.config, 'save_config', None)),
                'contract': public_contract(), 'scope': 'global_future_capture_and_summary',
                'boundary': '保存只影响后续采集、工作记忆有效期和新摘要窗口；不批量重写历史、手工资料、授权或执行权。'}

    def _save(self, body):
        if (not isinstance(body, dict) or set(body) != {'expected_revision', 'changes'}
                or not isinstance(body['changes'], dict) or not body['changes']
                or set(body['changes']) - set(DEFAULTS)):
            raise ValueError('只接受 expected_revision 和已声明的 changes')
        with self.lock:
            current = self._snapshot()
            if body['expected_revision'] != current['revision']:
                raise _Conflict('memory strategy configuration changed')
            if not current['writable']:
                raise _Conflict('configuration file changed or is not writable')
            validate_settings({**current['values'], **body['changes']})
            config = self.plugin.config
            old = {key: (key in config, deepcopy(config.get(key))) for key in body['changes']}
            try:
                config.update(deepcopy(body['changes']))
                config.save_config()
            except BaseException:
                for key, (existed, value) in old.items():
                    if existed:
                        config[key] = value
                    else:
                        config.pop(key, None)
                raise
            result = self._snapshot()
            if not result['persisted_verified']:
                raise RuntimeError('configuration save is not yet confirmed; read before retry')
            return result

    async def _respond(self, write=False):
        username = getattr(request, 'username', None)
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        try:
            if write:
                body = await request.json(default=None)
                result = await asyncio.to_thread(self._save, body)
            else:
                if dict(getattr(request, 'query', None) or {}):
                    raise ValueError('该配置不接受查询参数')
                result = await asyncio.to_thread(self._snapshot)
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except _Conflict:
            return error_response('配置已变化，请先读取当前值再保存', status_code=409)
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
        except (RuntimeError, OSError):
            return error_response('配置读取或保存未确认，请先回读，不要重复提交', status_code=503)

    async def read(self):
        return await self._respond()

    async def save(self):
        return await self._respond(True)
