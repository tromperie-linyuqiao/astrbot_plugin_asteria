"""Authenticated manual image assets; no arbitrary paths, models or sends."""
from __future__ import annotations

import asyncio
import base64
import binascii
import re
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.native_expression_assets import (
    ExpressionAssetConflict, ExpressionAssetError, NativeExpressionAssets,
)
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/assets'
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_BASE64_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
BOUNDARY = ('这里只保管用户人工提供的图片及人工说明、标签，不自动理解画面、不调用模型、不发送消息。'
            '停用和软删除不会物理抹除原图，软删除可按版本恢复；恢复后仍保留原启用状态。')
_ID = re.compile(r'[a-f0-9]{64}\Z')
_ROW_FIELDS = ('schema', 'scope', 'id', 'sha256', 'media_type', 'format', 'width', 'height',
               'frames', 'total_pixels', 'byte_size', 'caption', 'tags', 'enabled', 'deleted',
               'revision', 'created_at', 'updated_at', 'deleted_at', 'source')


def _boolean(value, name):
    if type(value) is not bool:
        raise _InvalidRequest(name + ' 必须为布尔值')
    return value


def _deleted(value):
    if isinstance(value, str) and value in {'true', 'false'}:
        value = value == 'true'
    return _boolean(value, 'include_deleted')


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise _InvalidRequest('图片 ID 必须是有效的原生图片标识')
    return value


def _annotations(values):
    if 'caption' in values:
        caption = _text(values['caption'], '人工说明', 300, blank=True)
        if any(ord(c) < 32 and c not in '\n\r\t' or ord(c) == 127 for c in caption):
            raise _InvalidRequest('人工说明不能含控制字符')
    if 'tags' in values:
        tags = values['tags']
        if not isinstance(tags, list) or len(tags) > 16:
            raise _InvalidRequest('人工标签最多 16 个')
        for tag in tags:
            _text(tag, '人工标签', 32)
            if tag != tag.strip() or any(ord(c) < 32 or ord(c) == 127 for c in tag):
                raise _InvalidRequest('每个标签须为 1–32 字，不能有首尾空白或控制字符')
    if 'enabled' in values:
        _boolean(values['enabled'], 'enabled')
    return values


class NativeAssetsWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for name in ('list', 'detail', 'preview', 'upload', 'update', 'delete', 'restore'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX + '/' + name,
                getattr(self, 'assets_' + name), ['GET' if name in {'list', 'detail', 'preview'} else 'POST'],
                'TLS authenticated manual expression assets ' + name)

    def register_admin_routes(self):
        # Management of historical assets uses ordinary AstrBot administrator
        # authentication. The live-scope routes and runtime sender ACL stay intact.
        for name in ('list', 'detail', 'preview', 'upload', 'update', 'delete', 'restore'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX + '/admin-' + name,
                getattr(self, 'assets_admin_' + name),
                ['GET' if name in {'list', 'detail', 'preview'} else 'POST'],
                'TLS authenticated administrator expression assets ' + name)

    def _resources(self):
        presence = getattr(self.plugin, '_presence', None)
        host = getattr(presence, 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        service = self._assets()
        journal = service.journal
        if getattr(journal, '_closed', False):
            raise ExpressionAssetError('native expression assets journal closed')
        return presence, host, runtime, service, journal

    def _same_resources(self, resources):
        current = self._resources()
        if any(old is not new for old, new in zip(resources, current)):
            raise ExpressionAssetError('native expression assets runtime replaced')
        return current

    def _admin_service(self, resources, scope):
        expected = dict(scope)
        def authorize(candidate):
            self._same_resources(resources)
            return candidate == expected
        original = resources[3]
        return NativeExpressionAssets(resources[4], assets_root=original._root,
                                      authorize=authorize, clock=original.clock)

    def _assets(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        service = getattr(getattr(host, 'runtime', None), 'expression_assets', None)
        if not isinstance(service, NativeExpressionAssets) or service.active is not True:
            raise ExpressionAssetError('native expression assets unavailable')
        return service

    def _check(self, service, scope):
        if self._assets() is not service:
            raise ExpressionAssetError('native expression assets replaced')
        if service.authorize(dict(scope)) is not True:
            raise PermissionError('native expression assets scope denied')

    @staticmethod
    def _parse(name, data):
        if not isinstance(data, dict):
            raise _InvalidRequest('需要 JSON 对象')
        if name in {'list', 'detail', 'preview'}:
            extra = {'limit', 'offset', 'include_deleted'} if name == 'list' else (
                {'id', 'include_deleted'} if name == 'detail' else {'id', 'expected_revision'})
            if set(data) - set(SCOPE_FIELDS) - extra:
                raise _InvalidRequest('图片查询含未知字段')
            scope = _scope({key: data.get(key) for key in SCOPE_FIELDS})
            if name == 'list':
                return scope, dict(limit=_integer(data.get('limit', 25), 'limit', 1, 100),
                    offset=_integer(data.get('offset', 0), 'offset', 0, 256),
                    include_deleted=_deleted(data.get('include_deleted', False)))
            result = dict(id=_identity(data.get('id')))
            if name == 'detail': result['include_deleted'] = _deleted(data.get('include_deleted', False))
            else: result['expected_revision'] = _integer(data.get('expected_revision'), 'expected_revision', 1, 2147483647)
            return scope, result
        fields = ({'scope', 'request_id', 'content_base64', 'caption', 'tags', 'enabled'} if name == 'upload'
                  else {'scope', 'id', 'expected_revision'} | ({'patch'} if name == 'update' else set()))
        if set(data) != fields:
            raise _InvalidRequest('请提交全部指定字段；不接受路径、URL、来源或其他配置')
        scope = _scope(data['scope'])
        if name == 'upload':
            encoded = data['content_base64']
            if (not isinstance(encoded, str) or not 1 <= len(encoded) <= MAX_BASE64_CHARS
                    or not encoded.isascii()):
                raise _InvalidRequest('图片须为不超过 3 MiB 原图的标准 base64 文本')
            return scope, dict(request_id=_text(data['request_id'], 'request_id', 256),
                content_base64=encoded, **_annotations({key: data[key] for key in ('caption', 'tags', 'enabled')}))
        result = dict(id=_identity(data['id']), expected_revision=_integer(data['expected_revision'], 'expected_revision', 1, 2147483647))
        if name == 'update':
            patch = data['patch']
            if not isinstance(patch, dict) or not patch or set(patch) - {'caption', 'tags', 'enabled'}:
                raise _InvalidRequest('只能修改人工说明、标签和启用状态')
            result['patch'] = _annotations(dict(patch))
        return scope, result

    @staticmethod
    def _row(row):
        if row is None: raise KeyError('asset absent')
        return {key: row[key] for key in _ROW_FIELDS}

    async def _respond(self, name, *, administrative=False):
        try: username = getattr(request, 'username', None)
        except RuntimeError: username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        local_service = None
        try:
            data = (dict(getattr(request, 'query', None) or {}) if name in {'list', 'detail', 'preview'}
                    else await request.json(default=None))
            scope, values = self._parse(name, data)
            resources = self._resources()
            def check():
                if administrative:
                    self._same_resources(resources)
                    if local_service is not None and local_service.active is not True:
                        raise PermissionError('administrator asset operation ended')
                else:
                    self._check(resources[3], scope)
            check()
            if administrative:
                local_service = self._admin_service(resources, scope)
            service = local_service if administrative else resources[3]

            def operate():
                # The service's dynamic authorize callback is required to be
                # thread safe; its transaction checks must never be bypassed.
                check()
                if name == 'list':
                    return dict(records=[self._row(row) for row in service.list(scope, **values)])
                if name == 'detail':
                    return dict(record=self._row(service.get(scope, values['id'], include_deleted=values['include_deleted'])))
                if name == 'preview':
                    row = self._row(service.get(scope, values['id']))
                    raw = service.read_bytes(scope, values['id'], expected_revision=values['expected_revision'])
                    if row['revision'] != values['expected_revision']:
                        raise ExpressionAssetConflict('preview version changed')
                    return dict(record=row, content_base64=base64.b64encode(raw).decode('ascii'))
                if name == 'upload':
                    encoded = values['content_base64']
                    try: raw = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        raise _InvalidRequest('图片 base64 编码无效') from None
                    if not 1 <= len(raw) <= MAX_IMAGE_BYTES or base64.b64encode(raw).decode('ascii') != encoded:
                        raise _InvalidRequest('图片须为不超过 3 MiB 的标准 base64 原图')
                    row = service.import_bytes(scope, raw, **{key: value for key, value in values.items() if key != 'content_base64'})
                elif name == 'update':
                    row = service.update(scope, values['id'], values['patch'], expected_revision=values['expected_revision'])
                else:
                    row = getattr(service, name)(scope, values['id'], expected_revision=values['expected_revision'])
                return dict(record=self._row(row))

            result = await asyncio.to_thread(operate)
            check()
            return json_response(dict(ok=True, backend='native_expression_assets', scope=scope,
                access='authenticated_administrator', boundary=BOUNDARY, manual_only=True,
                authority='historical_administrator' if administrative else 'live_private_scope',
                llm_calls=0, sends=0, limits=dict(max_image_bytes=MAX_IMAGE_BYTES, caption_chars=300,
                    max_tags=16, tag_chars=32, formats=['PNG', 'JPEG', 'GIF', 'WebP']), **result),
                headers={'Cache-Control': 'no-store'})
        except _InvalidRequest as error: return error_response(str(error), status_code=400)
        except ExpressionAssetConflict: return error_response('图片版本或上传请求已改变，请刷新后重试', status_code=409)
        except PermissionError: return error_response('需要有效管理员登录与明确选定的完整私聊范围' if administrative
            else '该完整私聊范围尚未获得原生图片库授权，请先在目标私聊发话', status_code=403)
        except KeyError: return error_response('当前范围中找不到该图片，或图片已软删除', status_code=404)
        except ValueError: return error_response('请检查图片格式、大小、人工说明、标签和版本', status_code=400)
        except (ExpressionAssetError, RuntimeError, sqlite3.Error, OSError):
            return error_response('原生图片库暂不可用或正在重载', status_code=503)
        except Exception: return error_response('图片库操作失败，请稍后重试', status_code=500)
        finally:
            if local_service is not None: local_service.close()

    async def assets_list(self): return await self._respond('list')
    async def assets_detail(self): return await self._respond('detail')
    async def assets_preview(self): return await self._respond('preview')
    async def assets_upload(self): return await self._respond('upload')
    async def assets_update(self): return await self._respond('update')
    async def assets_delete(self): return await self._respond('delete')
    async def assets_restore(self): return await self._respond('restore')

    async def assets_admin_list(self): return await self._respond('list', administrative=True)

    async def assets_admin_detail(self): return await self._respond('detail', administrative=True)

    async def assets_admin_preview(self): return await self._respond('preview', administrative=True)

    async def assets_admin_upload(self): return await self._respond('upload', administrative=True)

    async def assets_admin_update(self): return await self._respond('update', administrative=True)

    async def assets_admin_delete(self): return await self._respond('delete', administrative=True)

    async def assets_admin_restore(self): return await self._respond('restore', administrative=True)
