"""Finite asynchronous HTTP for configured Asteria integrations."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import httpx


class HttpStatusError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f'HTTP {status}')
        self.status = status


class HttpTransportError(OSError):
    pass


async def read_http(method, url, *, timeout, maximum, headers=None, data=None):
    target = urlsplit(url)
    if (target.scheme not in {'http', 'https'} or not target.hostname
            or target.username is not None or target.password is not None):
        raise ValueError('HTTP 地址无效')
    request_headers = {'Accept-Encoding': 'identity', **(headers or {})}
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                         transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False)) as client:
                async with client.stream(method, url, headers=request_headers, content=data) as response:
                    if not 200 <= response.status_code < 300:
                        raise HttpStatusError(response.status_code)
                    # A response nobody consumes does not need buffering.
                    if not maximum:
                        return b'', response.headers
                    if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                        raise ValueError('不支持压缩的桥接响应')
                    size = response.headers.get('Content-Length', '')
                    if size.isdigit() and int(size) > maximum:
                        raise ValueError('HTTP 响应超过大小限制')
                    body = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                        if len(body) + len(chunk) > maximum:
                            raise ValueError('HTTP 响应超过大小限制')
                        body.extend(chunk)
                    return bytes(body), response.headers
    except httpx.TimeoutException as exc:
        raise TimeoutError('HTTP 请求超时') from exc
    except httpx.HTTPError as exc:
        raise HttpTransportError('HTTP 连接失败') from exc


async def read_json(method, url, *, timeout, maximum, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if data is not None:
        headers = {**(headers or {}), 'Content-Type': 'application/json; charset=utf-8'}
    body, _ = await read_http(method, url, timeout=timeout, maximum=maximum, headers=headers, data=data)
    return json.loads(body)

