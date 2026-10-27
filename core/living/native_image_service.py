"""One fresh image per admitted task, using the existing OpenAI-compatible NAI API.

No legacy PC imports, sender, prompt LLM, reference-image lookup, endpoint failover
or automatic retry. The host owns this service and its async ``close``. Callers
must obtain delivery admission before calling ``generate``; this service checks
the complete private scope again before and after network I/O. Only the same
task may recover its own prepared media. Provider ambiguity stays UNKNOWN across
restarts, so a lost response cannot cause another paid generation.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

import aiohttp
from PIL import Image

from .models import canonical, private_scope, scope_key

_TASK = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')
_NAI = re.compile(r'^(?:novelai/)?nai-diffusion(?:-|$)', re.I)
_MAX_IMAGE = 10 * 1024 * 1024
_MAX_RESPONSE = 16 * 1024 * 1024
_SCENES = {
    'care': 'Quiet supportive company, calm attentive expression, comfortable everyday surroundings.',
    'night': 'Quiet evening company, subdued lighting, relaxed portrait, restful atmosphere.',
    'daily': 'A small ordinary daily moment, composed expression, natural surroundings.',
    'weather_rain': 'Rainy day indoors beside a window, practical rainwear kept on.',
    'weather_snow': 'Snowy day, warm winter layers, calm sheltered surroundings.',
    'weather_cold': 'Cold day, warm layered outfit, comfortable surroundings.',
    'weather_hot': 'Hot day, lightweight opaque everyday clothing, comfortable shade.',
    'weather_wind': 'Windy day, practical outerwear, sheltered surroundings.',
    'weather_clear': 'Clear weather, natural daylight, a quiet everyday setting.',
    'weather_overcast': 'Overcast daylight, soft light, a quiet everyday setting.',
}
_COMPOSITION = ('A single image depicting one continuous scene in a single frame. '
                'One character, one composition.')
_CLOTHED = ('Complete opaque everyday outfit, covered torso and hips, visibly clothed; '
            'keep specified garments and existing outfit, no unrequested outfit removal.')
_NEGATIVE = ('collage, grid layout, split screen, multiple panels, contact sheet, '
             'character sheet, duplicate character')
_BARE_NEGATIVE = 'nude, naked, topless, bottomless, unclothed, missing clothes, unrequested outfit removal'
_BARE = re.compile(r'\b(?:nude|naked|topless|bottomless|unclothed|bare\s+(?:chest|breasts|torso|hips))\b', re.I)


def _digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode('utf-8')).hexdigest()


def _private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt': path.chmod(0o700)


def _image_url(value, *, download=False):
    # Configured endpoint is trusted operator configuration. A returned download
    # URL is untrusted and must not turn into a request to a literal LAN address.
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or re.search(r'[\x00-\x20\x7f]', value) or '\\' in value):
        raise ValueError('invalid image URL')
    try:
        parts = urlsplit(value)
        path = unquote(parts.path, errors='strict')
        if (parts.scheme not in ({'https'} if download else {'http','https'})
                or not parts.hostname or parts.username is not None or parts.password is not None
                or '#' in value or parts.port == 0 or not download and '?' in value
                or any(item in {'.','..'} for item in path.split('/')) or '//' in path
                or '\\' in path or '%' in path or re.search(r'[\x00-\x20\x7f]', path)):
            raise ValueError
        if download:
            if parts.hostname.lower() in ('localhost', 'localhost.localdomain') or parts.hostname.lower().endswith('.localhost'):
                raise ValueError
            try: address = ipaddress.ip_address(parts.hostname)
            except ValueError: address = None
            if address is not None and not address.is_global: raise ValueError
    except (ValueError,UnicodeError):
        raise ValueError('invalid image URL') from None
    return value.rstrip('/') if not download else value


@dataclass(frozen=True)
class ImageProviderConfig:
    """Reviewed existing account; credentials, model and URL never appear in repr."""
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str = field(repr=False)
    size: str = '832x1216'
    timeout_seconds: float = 180.

    def __post_init__(self):
        object.__setattr__(self, 'base_url', _image_url(self.base_url))
        if (not isinstance(self.api_key, str) or not 1 <= len(self.api_key) <= 2048
                or re.search(r'[^\x21-\x7e]', self.api_key)):
            raise ValueError('valid existing image credential required')
        if not isinstance(self.model, str) or len(self.model) > 256 or not _NAI.match(self.model):
            raise ValueError('reviewed NAI image model required')
        match = re.fullmatch(r'(\d{2,4})x(\d{2,4})', self.size) if isinstance(self.size, str) else None
        if not match or not all(64 <= int(item) <= 4096 for item in match.groups()):
            raise ValueError('valid image dimensions required')
        if (type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 180): raise ValueError('valid image timeout required')

    @classmethod
    def from_existing_config(cls, config):
        """Read only the real production protocol's existing keys; no new vendor."""
        if not hasattr(config, 'get'): raise ValueError('existing image configuration required')
        if config.get('photo_generation_backend') != 'external' or config.get('external_image_api_platform') != 'openai':
            raise ValueError('reviewed external OpenAI-compatible image protocol required')
        if config.get('external_image_api_endpoints'):
            raise ValueError('explicit endpoint queue requires separate review')
        if config.get('enable_backup_external_image_api') or config.get('external_image_api_custom_headers'):
            raise ValueError('backup endpoints/custom headers require separate review')
        return cls(config.get('EXTERNAL_IMAGE_API_BASE_URL', ''), config.get('EXTERNAL_IMAGE_API_KEY', ''),
                   config.get('EXTERNAL_IMAGE_API_MODEL', ''), config.get('external_image_api_size', '832x1216'),
                   config.get('external_image_api_timeout_seconds', 180))

    @property
    def endpoint(self):
        base = self.base_url
        if base.endswith('/images/generations'): return base
        if base.endswith('/images/edits'): return base[:-len('/images/edits')] + '/images/generations'
        return base + '/images/generations'


@dataclass(frozen=True)
class ImageHTTPResponse:
    status: int
    body: bytes = field(repr=False)


class ImageTransportFailure(Exception):
    """Fixed code only. ``definite`` means no accepted generation is possible."""
    def __init__(self, *, definite=False):
        self.definite = definite
        super().__init__('image_transport_definite' if definite else 'image_transport_unknown')


class _PublicResolver(aiohttp.abc.AbstractResolver):
    def __init__(self):
        self._resolver = aiohttp.resolver.ThreadedResolver()

    async def resolve(self, host, port=0, family=0):
        records = await self._resolver.resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(row['host']).is_global for row in records):
            raise OSError('public image download address required')
        return records

    async def close(self):
        await self._resolver.close()


class _AioHTTPTransport:
    async def _request(self, method, url, *, timeout, max_bytes, headers=None, payload=None):
        resolver = None; connector = None
        try:
            if method == 'GET':
                resolver = _PublicResolver()
                connector = aiohttp.TCPConnector(resolver=resolver)
            async with aiohttp.ClientSession(trust_env=False, connector=connector,
                                            timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.request(method, url, headers=headers, json=payload,
                                           allow_redirects=False) as response:
                    chunks = []; length = 0
                    async for chunk in response.content.iter_chunked(65536):
                        length += len(chunk)
                        if length > max_bytes: raise ImageTransportFailure()
                        chunks.append(chunk)
                    return ImageHTTPResponse(response.status, b''.join(chunks))
        except aiohttp.ClientConnectorError:
            raise ImageTransportFailure(definite=True) from None
        except (aiohttp.ClientError, TimeoutError):
            raise ImageTransportFailure() from None
        finally:
            # aiohttp marks an explicitly provided resolver as not connector-
            # owned. Close it ourselves on success, failure and cancellation.
            try:
                if connector is not None: await connector.close()
            finally:
                if resolver is not None: await resolver.close()

    async def post(self, url, *, headers, payload, timeout, max_bytes):
        return await self._request('POST', url, headers=headers, payload=payload, timeout=timeout, max_bytes=max_bytes)

    async def download(self, url, *, timeout, max_bytes):
        # No bearer token, cookies, environment proxy or redirects on image URLs.
        return await self._request('GET', url, timeout=timeout, max_bytes=max_bytes)


class NativeImageService:
    """Host-owned shared service; ``generate`` returns safe fixed-shape outcomes.

    ``transport`` is an optional injected async ``post``/``download`` test seam,
    returning ImageHTTPResponse. Its lifecycle remains with its injecting owner.
    ``media_root`` is an absolute Path; successful ``path`` is an absolute string.
    No method sends messages or imports old plugins. Explicit sexual context is
    a trusted host flag, never inferred from a topic or untrusted prompt text.
    """
    def __init__(self, config, *, media_root, state_path, authorize, appearance,
                 clothing_hint='', transport=None, clock=time.time):
        self.config = config if isinstance(config, ImageProviderConfig) else ImageProviderConfig.from_existing_config(config)
        if not callable(authorize) or not callable(clock): raise ValueError('image authorization/clock required')
        if (not isinstance(appearance, str) or not appearance.strip() or len(appearance) > 6000
                or not isinstance(clothing_hint, str) or len(clothing_hint) > 3000):
            raise ValueError('bounded private character appearance required')
        self._appearance = appearance.strip(); self._clothing = clothing_hint.strip()
        self.media_root = Path(media_root).resolve()
        self._state_path = Path(state_path).resolve()
        _private_dir(self.media_root); _private_dir(self._state_path.parent)
        self.authorize = authorize; self._clock = clock
        self._transport = transport or _AioHTTPTransport()
        self._closed = False; self._started = False; self._tasks = set(); self._lock = threading.RLock()
        self._db = sqlite3.connect(self._state_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('''CREATE TABLE IF NOT EXISTS image_tasks (
                task_ref TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                state TEXT NOT NULL, reason TEXT NOT NULL, path TEXT NOT NULL DEFAULT '',
                image_sha256 TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS image_digest ON image_tasks(image_sha256) WHERE image_sha256<>''")
            self._db.execute("UPDATE image_tasks SET state='unknown',reason='interrupted' WHERE state='pending'")
        if os.name != 'nt': self._state_path.chmod(0o600)

    def __repr__(self):
        return '<NativeImageService closed=' + str(self._closed) + '>'

    def _allowed(self, scope):
        if self._closed: return False
        try: return self.authorize(scope) is True
        except Exception: return False

    @staticmethod
    def _result(ref, state, reason, *, path='', image_sha256='', fresh=False, prepared_replay=False):
        return dict(ok=state == 'ready', state=state, reason=reason, path=path,
                    image_sha256=image_sha256, fresh=fresh, prepared_replay=prepared_replay, task_ref=ref)

    def _payload(self, topic, explicit_sexual):
        appearance = self._appearance
        clothing = self._clothing or 'A complete opaque everyday shirt and trousers.'
        if not explicit_sexual:
            appearance = _BARE.sub('', appearance); clothing = _BARE.sub('', clothing)
        prompt = ' '.join((_COMPOSITION, appearance, _SCENES[topic], clothing,
                           '' if explicit_sexual else _CLOTHED))
        return dict(model=self.config.model, prompt=prompt, size=self.config.size, n=1,
                    negative_prompt=_NEGATIVE + ('' if explicit_sexual else ', ' + _BARE_NEGATIVE))

    def _finish(self, ref, state, reason, *, path='', digest=''):
        try:
            with self._lock, self._db:
                changed = self._db.execute('''UPDATE image_tasks SET state=?,reason=?,path=?,image_sha256=?,updated_at=?
                    WHERE task_ref=? AND state='pending' ''', (state, reason, path, digest, self._clock(), ref)).rowcount
            return changed == 1
        except (sqlite3.Error, OSError):
            # The pre-submission pending row remains a durable no-retry barrier.
            return False

    def _prepared(self, row):
        try:
            path = Path(row['path'])
            if (not path.is_absolute() or path.parent != self.media_root or path.is_symlink()
                    or not path.is_file() or path.stat().st_size > _MAX_IMAGE): return None
            if _digest(path.read_bytes()) != row['image_sha256']: return None
            return self._result(row['task_ref'], 'ready', 'prepared', path=str(path),
                                image_sha256=row['image_sha256'], prepared_replay=True)
        except OSError: return None

    async def _image_bytes(self, response):
        if not isinstance(response, ImageHTTPResponse) or type(response.status) is not int or not isinstance(response.body, bytes):
            raise ValueError('invalid_response')
        if len(response.body) > _MAX_RESPONSE: raise ValueError('response_too_large')
        data = json.loads(response.body)
        items = data.get('data') if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError('single_image_required')
        item = items[0]; encoded = item.get('b64_json'); url = item.get('url')
        if bool(encoded) == bool(url): raise ValueError('single_image_source_required')
        if encoded:
            if not isinstance(encoded, str) or len(encoded) > (_MAX_IMAGE + 2) // 3 * 4:
                raise ValueError('image_too_large')
            try: content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error): raise ValueError('invalid_image_base64') from None
        else:
            target = _image_url(url, download=True)
            reply = await self._transport.download(target, timeout=self.config.timeout_seconds, max_bytes=_MAX_IMAGE)
            if (not isinstance(reply, ImageHTTPResponse) or reply.status != 200
                    or not isinstance(reply.body, bytes)): raise ValueError('image_download_failed')
            content = reply.body
        if not 1 <= len(content) <= _MAX_IMAGE: raise ValueError('image_too_large')
        try:
            with Image.open(BytesIO(content)) as picture:
                fmt = picture.format
                if (fmt not in ('PNG', 'JPEG', 'WEBP') or getattr(picture, 'n_frames', 1) != 1
                        or not all(1 <= n <= 4096 for n in picture.size)
                        or picture.width * picture.height > 16777216): raise ValueError
                picture.verify()
        except Exception: raise ValueError('invalid_image') from None
        return content, {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[fmt]

    async def generate(self, scope, task_id, topic, *, explicit_sexual=False):
        ref = ''
        try:
            scope = private_scope(scope)
            if (not isinstance(task_id, str) or not _TASK.fullmatch(task_id)
                    or not isinstance(topic, str) or topic not in _SCENES or type(explicit_sexual) is not bool):
                raise ValueError
            ref = _digest([scope_key(scope), task_id])
        except (ValueError, TypeError, KeyError):
            return self._result(ref, 'definite_failure', 'invalid_input')
        if not self._allowed(scope): return self._result(ref, 'denied', 'scope_not_authorized')
        payload = self._payload(topic, explicit_sexual)
        fingerprint = _digest([self.config.endpoint, payload, explicit_sexual])
        with self._lock:
            row = self._db.execute('SELECT * FROM image_tasks WHERE task_ref=?', (ref,)).fetchone()
            if row:
                if row['request_hash'] != fingerprint: return self._result(ref, 'definite_failure', 'task_payload_conflict')
                if row['state'] == 'ready':
                    result = self._prepared(row)
                    if result: return result
                    with self._db:
                        self._db.execute("UPDATE image_tasks SET state='unknown',reason='prepared_media_unavailable' WHERE task_ref=?", (ref,))
                    return self._result(ref, 'unknown', 'prepared_media_unavailable')
                return self._result(ref, 'unknown' if row['state'] == 'pending' else row['state'], row['reason'])
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                return self._result(ref, 'definite_failure', 'invalid_clock')
            try:
                with self._db:
                    self._db.execute('INSERT INTO image_tasks(task_ref,request_hash,state,reason,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                                     (ref, fingerprint, 'pending', 'submission_pending', now, now))
            except sqlite3.Error:
                return self._result(ref, 'definite_failure', 'state_unavailable')
        self._started = True
        current = asyncio.current_task(); self._tasks.add(current)
        temporary = None; generation_accepted = False
        try:
            response = await self._transport.post(self.config.endpoint,
                headers={'Authorization': 'Bearer ' + self.config.api_key, 'Content-Type': 'application/json'},
                payload=payload, timeout=self.config.timeout_seconds, max_bytes=_MAX_RESPONSE)
            if not isinstance(response, ImageHTTPResponse) or type(response.status) is not int:
                raise ValueError('invalid_response')
            if 400 <= response.status < 500 and response.status != 408:
                self._finish(ref, 'definite_failure', 'provider_rejected')
                return self._result(ref, 'definite_failure', 'provider_rejected')
            if response.status != 200: raise ValueError('provider_outcome_unknown')
            generation_accepted = True
            content, suffix = await self._image_bytes(response)
            if not self._allowed(scope):
                self._finish(ref, 'unknown', 'authorization_changed')
                return self._result(ref, 'unknown', 'authorization_changed')
            digest = _digest(content)
            with self._lock:
                duplicate = self._db.execute('SELECT 1 FROM image_tasks WHERE image_sha256=?', (digest,)).fetchone()
            if duplicate: raise ValueError('duplicate_generated_image')
            path = self.media_root / (ref + suffix)
            if path.exists() or path.is_symlink(): raise ValueError('media_path_exists')
            temporary = self.media_root / ('.' + ref + '.' + uuid.uuid4().hex + '.tmp')
            with temporary.open('xb') as file:
                if os.name != 'nt': os.chmod(temporary, 0o600)
                file.write(content); file.flush(); os.fsync(file.fileno())
            os.replace(temporary, path); temporary = None
            try:
                if not self._finish(ref, 'ready', 'generated', path=str(path), digest=digest):
                    path.unlink(missing_ok=True)
                    return self._result(ref, 'unknown', 'state_changed')
            except Exception:
                path.unlink(missing_ok=True); raise
            return self._result(ref, 'ready', 'generated', path=str(path), image_sha256=digest, fresh=True)
        except asyncio.CancelledError:
            self._finish(ref, 'unknown', 'cancelled')
            raise
        except ImageTransportFailure as error:
            definite = error.definite and not generation_accepted
            state = 'definite_failure' if definite else 'unknown'
            self._finish(ref, state, 'transport_unavailable' if definite else 'transport_outcome_unknown')
            return self._result(ref, state, 'transport_unavailable' if definite else 'transport_outcome_unknown')
        except Exception:
            # Exceptions/provider bodies may contain URLs, keys or prompts. Only
            # fixed codes reach consumers. Pending remains blocked if disk fails.
            self._finish(ref, 'unknown', 'generation_outcome_unknown')
            return self._result(ref, 'unknown', 'generation_outcome_unknown')
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
            self._tasks.discard(current)

    def stats(self):
        if self._closed: return dict(closed=True, counts=dict(getattr(self, '_closed_counts', {})))
        with self._lock:
            rows = self._db.execute('SELECT state,COUNT(*) AS n FROM image_tasks GROUP BY state').fetchall()
        return dict(closed=self._closed, counts={row['state']: row['n'] for row in rows})

    def diagnostics(self):
        """Fixed counters only: no scope, task IDs, paths, URL, model or prompt."""
        return self.stats()

    def _close_db(self):
        with self._lock:
            rows = self._db.execute('SELECT state,COUNT(*) AS n FROM image_tasks GROUP BY state').fetchall()
            self._closed_counts = {row['state']: row['n'] for row in rows}
            self._db.close()

    def abort_initialization(self):
        """Synchronous constructor cleanup only; never interrupt active I/O.

        The host builds related owned services synchronously. If a later
        constructor fails before async work starts, this releases our SQLite
        connection without needing a running event loop. Normal shutdown must
        await close(); an instance that has ever submitted work is ineligible.
        """
        if self._closed: return
        if self._tasks or self._started:
            raise RuntimeError('image service already used; await close required')
        self._closed = True
        self._close_db()

    async def close(self):
        if self._closed: return
        self._closed = True
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self._close_db()
