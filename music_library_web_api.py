"""Authenticated scoped music metadata maintenance, never playback authority."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.native_music_library import BASE_FIELDS, FIELDS, MAX_SONGS, NativeMusicLibrary
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/music-library'
MAX_BODY_BYTES = 80 * 1024
READS = frozenset(('list', 'detail', 'export', 'match'))


class _Unavailable(RuntimeError):
    pass


class NativeMusicLibraryWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'export', 'match', 'create', 'update', 'archive', 'restore', 'preview_import', 'confirm_import'):
            path = {'preview_import': 'import/preview', 'confirm_import': 'import/confirm'}.get(name, name)
            self.plugin.context.register_web_api(PREFIX + '/' + path, getattr(self, name),
                ['GET' if name in READS else 'POST'], 'TLS authenticated administrator music metadata ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = getattr(runtime, 'music_library', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(service, NativeMusicLibrary) or service.active is not True
                or not isinstance(journal, LivingJournal) or service.journal is not journal
                or getattr(runtime, 'journal', None) is not journal or getattr(journal, '_closed', True)):
            raise _Unavailable('native music metadata unavailable')
        return presence, host, runtime, service, journal

    def _same_resources(self, resources):
        if any(old is not new for old, new in zip(resources, self._resources())):
            raise _Unavailable('native music metadata runtime changed')

    def _admin_service(self, resources, scope):
        expected = dict(scope)
        def authorize(candidate):
            self._same_resources(resources)
            return candidate == expected
        # Operation-local permission does not alter the runtime source reader,
        # grant an inbound identity, register a collector or permit delivery.
        return NativeMusicLibrary(resources[-1], authorize=authorize, clock=resources[-2].clock)

    @staticmethod
    def _operation(name, data):
        if type(data) is not dict:
            raise _InvalidRequest('请求必须为 JSON 对象或合法查询')
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BODY_BYTES:
            raise _InvalidRequest('音乐资料请求过大，请拆分迁移批次')
        if name in READS:
            extra = {'q', 'artist', 'genre', 'language', 'include_archived', 'limit', 'offset'} if name == 'list' else {'id'} if name == 'detail' else {'title', 'artist'} if name == 'match' else set()
            if set(data) - set(SCOPE_FIELDS) - extra:
                raise _InvalidRequest('音乐资料查询包含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name == 'detail':
                return scope, (_text(data.get('id'), '音乐资料 ID', 100),), {}
            if name == 'export':
                return scope, (), {}
            if name == 'match':
                return scope, (_text(data.get('title'), '歌名', 120),
                    _text(data.get('artist', ''), '歌手', 120, blank=True)), {}
            archived = data.get('include_archived', False)
            if type(archived) is str and archived in {'true', 'false'}:
                archived = archived == 'true'
            if type(archived) is not bool:
                raise _InvalidRequest('include_archived 必须为布尔值')
            options = dict(include_archived=archived,
                limit=_integer(data.get('limit', 20), 'limit', 1, 100),
                offset=_integer(data.get('offset', 0), 'offset', 0, MAX_SONGS))
            for query_key, field in (('q', 'query'), ('artist', 'artist'), ('genre', 'genre'), ('language', 'language')):
                options[field] = _text(data.get(query_key, ''), query_key, 200, blank=True)
            return scope, (), options
        scope = _scope(data.get('scope'))
        if name in {'preview_import', 'confirm_import'}:
            allowed = {'scope', 'payload'} if name == 'preview_import' else {'scope', 'payload', 'preview_sha256', 'request_id', 'owner_confirmed'}
            if set(data) != allowed:
                raise _InvalidRequest('导入只接受完整范围、来源制品和本次明确预览确认')
            return scope, (data['payload'],), {key: data[key] for key in data if key not in {'scope', 'payload'}}
        allowed = {'scope', 'request_id', 'fields'} if name == 'create' else {'scope', 'id', 'expected_revision'} | ({'fields'} if name == 'update' else set())
        if set(data) != allowed:
            raise _InvalidRequest('音乐资料操作需要完整参数，不能提交播放或发送权限')
        if name in {'create', 'update'} and (type(data['fields']) is not dict
                or not BASE_FIELDS <= set(data['fields']) or set(data['fields']) - FIELDS):
            raise _InvalidRequest('请提交完整基础音乐资料；来源、标签与双方评语为可选字段')
        if name == 'create':
            return scope, (_text(data['request_id'], 'request_id', 128),), dict(data['fields'])
        revision = data['expected_revision']
        if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
            raise _InvalidRequest('expected_revision 必须是明确整数')
        return scope, (_text(data['id'], '音乐资料 ID', 100),), dict(expected_revision=revision,
            **(data['fields'] if name == 'update' else {}))

    async def _respond(self, name):
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        service = None
        try:
            resources = self._resources()
            if name in READS:
                data = dict(getattr(request, 'query', None) or {})
            else:
                if getattr(request, 'query', None):
                    raise _InvalidRequest('写操作不接受查询参数')
                length = getattr(request, 'headers', {}).get('Content-Length')
                if length is not None and (type(length) is not str or not length.isascii()
                        or not length.isdigit() or len(length) > 10 or int(length) > MAX_BODY_BYTES):
                    raise _InvalidRequest('音乐资料请求过大')
                data = await request.json(default=None)
            scope, args, kwargs = self._operation(name, data)
            self._same_resources(resources)
            service = self._admin_service(resources, scope)
            def operate():
                self._same_resources(resources)
                method = 'search' if name == 'list' else 'get' if name == 'detail' else name
                result = getattr(service, method)(scope, *args, **kwargs)
                if name == 'detail' and result is None:
                    raise KeyError('music metadata absent')
                if name in {'create', 'update', 'archive', 'restore'}:
                    saved = service.get(scope, result['id'])
                    if saved != result:
                        raise RuntimeError('music metadata write readback changed')
                    result = saved
                if name == 'confirm_import':
                    records = [service.get(scope, identity) for identity in result['created_ids'] + result['existing_ids']]
                    if any(row is None for row in records):
                        raise RuntimeError('music import readback absent')
                    result = dict(result, records=records)
                self._same_resources(resources)
                service._scope(scope)
                return result
            result = await asyncio.to_thread(operate)
            self._same_resources(resources)
            service._scope(scope)
            body = dict(ok=True, backend='tls_native_music_library', scope=scope,
                access='authenticated_administrator', authority='historical_administrator_materials',
                metadata_only=True, creates_playback_evidence=False, creates_send_permission=False,
                legacy_consumer_retained=True, phone_source_bound=False)
            if name == 'list':
                body.update(result)
            elif name == 'confirm_import':
                body['import'] = {key: value for key, value in result.items() if key != 'records'}
                body['records'] = result['records']
            else:
                body[{'export': 'export', 'preview_import': 'preview', 'match': 'match'}.get(name, 'record')] = result
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except JournalConflict:
            return error_response('音乐资料版本、来源或预览已改变，请回读后重新核对', status_code=409)
        except PermissionError:
            return error_response('需要当前后台认证及明确的音乐资料归属确认', status_code=403)
        except KeyError:
            return error_response('当前完整范围中找不到该音乐资料', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('音乐资料或迁移制品无效，请检查字段、限额和版本', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('音乐资料暂不可用或正在重载；请保留原请求并回读确认', status_code=503)
        except Exception:
            return error_response('音乐资料操作失败，请保留草稿并稍后核对', status_code=500)
        finally:
            if service is not None:
                service.stop()

    async def list(self): return await self._respond('list')
    async def detail(self): return await self._respond('detail')
    async def export(self): return await self._respond('export')
    async def match(self): return await self._respond('match')
    async def create(self): return await self._respond('create')
    async def update(self): return await self._respond('update')
    async def archive(self): return await self._respond('archive')
    async def restore(self): return await self._respond('restore')
    async def preview_import(self): return await self._respond('preview_import')
    async def confirm_import(self): return await self._respond('confirm_import')
