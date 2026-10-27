"""Personal workbench presentation preferences in the existing SDK config.

Layout is independent from business activation and never grants a scope lease.
The same configuration owner/lock used by phone settings persists these values.
"""
from __future__ import annotations

import asyncio
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading

from astrbot.api.web import error_response, json_response, request

PREFIX = '/astrbot_plugin_virtual_body/page/workbench'
KEY = 'living_workbench_layouts'
SCHEMA = 'tls.workbench.layout.v1'
ENTRIES = frozenset('overview modules memory tasks history expression assets phone agenda narrative config body space mood weather materials status maintenance memo_notes music_library brief preferences timeline rules phone_service phone_flow insight personal_goals profile_candidates mc_summary scoped_daily_plan native_ownership pc_daily_native proactive_native memory-native pc-native'.split())


class LayoutConflict(RuntimeError): pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def default_layout():
    groups = [('daily', '日常陪伴', ['phone', 'agenda', 'narrative', 'memory']),
              ('express', '内容与表达', ['assets', 'expression', 'history']),
              ('system', '系统维护', ['modules', 'tasks', 'config'])]
    return {'schema': SCHEMA, 'theme': 'system', 'sections': [
        {'id': identity, 'name': name, 'collapsed': False,
         'items': [{'id': item, 'hidden': False, 'width': 'normal'} for item in items]}
        for identity, name, items in groups]}


def validate_layout(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'theme', 'sections'}
            or value['schema'] != SCHEMA or value['theme'] not in {'system', 'light', 'dark', 'black'}
            or not isinstance(value['sections'], list) or not 1 <= len(value['sections']) <= 12):
        raise ValueError('工作台布局无效')
    ids = set(); total = 0
    for section in value['sections']:
        if (not isinstance(section, dict) or set(section) != {'id', 'name', 'collapsed', 'items'}
                or not isinstance(section['id'], str) or not re.fullmatch('[a-z0-9_-]{1,32}', section['id'])
                or section['id'] in ids or not isinstance(section['name'], str)
                or not section['name'].strip() or len(section['name']) > 24
                or any(ord(c) < 32 for c in section['name']) or type(section['collapsed']) is not bool
                or not isinstance(section['items'], list)):
            raise ValueError('分区名称或设置无效')
        ids.add(section['id']); seen = set()
        for item in section['items']:
            if (not isinstance(item, dict) or set(item) != {'id', 'hidden', 'width'}
                    or not isinstance(item['id'], str) or item['id'] not in ENTRIES or item['id'] in seen
                    or type(item['hidden']) is not bool or item['width'] not in {'normal', 'wide'}):
                raise ValueError('功能入口或宽度设置无效')
            seen.add(item['id']); total += 1
    if total > 64 or len(canonical(value).encode()) > 24576:
        raise ValueError('工作台最多固定64个入口')
    return deepcopy(value)


class NativeWorkbenchWebApi:
    def __init__(self, plugin):
        self.plugin = plugin
        lock = getattr(plugin, '_native_console_config_lock', None)
        if lock is None:
            lock = threading.RLock(); plugin._native_console_config_lock = lock
        self.lock = lock

    def register_routes(self):
        for path, handler, method in [('layout', self.layout, 'GET'), ('layout/save', self.save_layout, 'POST'),
                                      ('catalog', self.catalog, 'GET')]:
            self.plugin.context.register_web_api(PREFIX+'/'+path, handler, [method], 'TLS workbench '+path)

    def _catalog(self):
        """Read literal SDK command declarations whose actual handlers exist.

        This is documentation for the SDK's command parser, not another parser
        or a promise that example natural language is a command.
        """
        source = Path(__file__).with_name('main.py').read_bytes()
        if len(source) > 2 * 1024 * 1024: raise RuntimeError('command source capacity')
        commands = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not callable(getattr(self.plugin, node.name, None)):
                continue
            for decorator in node.decorator_list:
                if (not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute)
                        or not isinstance(decorator.func.value, ast.Name)
                        or decorator.func.value.id != 'filter' or decorator.func.attr != 'command'
                        or not decorator.args):
                    continue
                name = ast.literal_eval(decorator.args[0])
                aliases = next((ast.literal_eval(item.value) for item in decorator.keywords if item.arg == 'alias'), ())
                if not isinstance(name, str) or not isinstance(aliases, (list, tuple, set)):
                    continue
                parameters = [item.arg for item in node.args.args if item.arg not in {'self', 'event'}]
                commands.append({'name': name, 'aliases': sorted(str(item) for item in aliases),
                    'parameters': parameters, 'summary': (ast.get_docstring(node) or '').split('\n')[0][:160],
                    'syntax': '/' + name + (' ' + ' '.join(parameters) if parameters else ''),
                    'source': 'loaded_handler_sdk_declaration'})
        return {'commands': commands, 'command_parser': 'existing_astrbot',
                'natural_language_examples': [
                    {'capability': 'memory', 'text': '我喜欢安静一点的表达', 'guaranteed_command': False},
                    {'capability': 'agenda', 'text': '明天晚上提醒我整理东西', 'guaranteed_command': False}],
                'llm_calls': 0, 'sends': 0, 'writes_business': False}

    def _document(self):
        config = self.plugin.config
        path = getattr(config, 'config_path', None)
        if not isinstance(path, (str, Path)) or not str(path):
            raise RuntimeError('configuration path unavailable')
        path = Path(path)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise RuntimeError('configuration capacity')
        raw = path.read_bytes(); document = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(document, dict): raise RuntimeError('configuration format')
        # The SDK saves the whole config; do not overwrite an out-of-band edit.
        if any(key not in config or config[key] != value for key, value in document.items()):
            raise LayoutConflict('configuration changed outside live owner')
        if config.get(KEY, '{}') != document.get(KEY, '{}'):
            raise RuntimeError('layout persistence reread differs')
        profiles = document.get(KEY, '{}')
        if not isinstance(profiles, str) or len(profiles.encode()) > 512 * 1024:
            raise RuntimeError('layout storage format')
        profiles = json.loads(profiles)
        if not isinstance(profiles, dict) or len(profiles) > 16:
            raise RuntimeError('layout profile capacity')
        return profiles, hashlib.sha256(raw).hexdigest()

    def _snapshot(self, actor):
        profiles, file_digest = self._document()
        layout = validate_layout(profiles.get(actor, default_layout()))
        return {'layout': layout, 'revision': digest([actor, layout, file_digest]),
                'writable': callable(getattr(self.plugin.config, 'save_config', None)),
                'persisted_verified': True, 'business_configuration_changed': False}

    def _save(self, actor, body):
        if (not isinstance(body, dict) or set(body) != {'layout', 'expected_revision'}
                or not isinstance(body['expected_revision'], str)
                or not re.fullmatch('[a-f0-9]{64}', body['expected_revision'])):
            raise ValueError('请先读取布局，再保存修改')
        layout = validate_layout(body['layout'])
        with self.lock:
            current = self._snapshot(actor)
            if current['revision'] != body['expected_revision']:
                raise LayoutConflict('layout changed')
            if not current['writable']: raise RuntimeError('configuration persistence unavailable')
            profiles, _ = self._document()
            if actor not in profiles and len(profiles) >= 16:
                raise ValueError('布局账户数量达到上限')
            profiles[actor] = layout
            config = self.plugin.config; existed = KEY in config; before = config.get(KEY)
            try:
                config[KEY] = canonical(profiles); config.save_config()
                result = self._snapshot(actor)
                if result['layout'] != layout: raise RuntimeError('layout reread differs')
                return result
            except BaseException:
                if existed: config[KEY] = before
                else: config.pop(KEY, None)
                raise

    async def _handle(self, save=False):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('请先登录 AstrBot 管理后台', status_code=401)
        actor = hashlib.sha256(('tls.workbench.admin:'+username).encode()).hexdigest()
        try:
            body = await request.json(default=None) if save else None
            def operation():
                with self.lock:
                    return self._save(actor, body) if save else self._snapshot(actor)
            result = await asyncio.to_thread(operation)
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except LayoutConflict:
            return error_response('设置已在其他页面变更，请刷新后保存', status_code=409)
        except (ValueError, TypeError):
            return error_response('工作台布局参数无效，请检查名称和入口', status_code=400)
        except (RuntimeError, OSError):
            return error_response('布局暂不能保存，请稍后刷新重试', status_code=503)

    async def layout(self): return await self._handle()
    async def save_layout(self): return await self._handle(True)

    async def catalog(self):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('请先登录 AstrBot 管理后台', status_code=401)
        try:
            result = await asyncio.to_thread(self._catalog)
            return json_response({'ok': True, **result}, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError, RuntimeError, SyntaxError):
            return error_response('命令说明暂不可用，原有聊天不受影响', status_code=503)
