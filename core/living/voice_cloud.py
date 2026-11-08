"""Explicit Fish-compatible TTS. Existing Journal owns receipts; audio is a cache.

No chat generation, automatic playback, cloning upload, ASR, or retry loop.
"""
from pathlib import Path
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import urlsplit
import aiohttp
from .models import canonical, scope_key
from .journal import JournalConflict

NS = 'tls.voice.audio.v1'
MAX_AUDIO = 4 * 1024 * 1024
MAX_TEXT = 1500

class VoiceError(ValueError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status

def settings(plugin, service='fish_tts'):
    value = getattr(plugin, 'config', {}).get('voice_cloud', {})
    value = value if isinstance(value, dict) else {}
    if service == 'cosyvoice':
        value = value.get('cosyvoice', {})
        value = value if isinstance(value, dict) else {}
    elif service != 'fish_tts':
        value = {}
    base = str(value.get('base_url', '')).rstrip('/')
    parsed = urlsplit(base)
    valid = parsed.scheme == ('wss' if service == 'cosyvoice' else 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
    models = [v for v in value.get('models', []) if isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', v)] if isinstance(value.get('models'), list) else []
    if service == 'cosyvoice':
        models = ['cosyvoice-v3-flash']
    model = str(value.get('model', 'cosyvoice-v3-flash' if service == 'cosyvoice' else ''))
    key = str(value.get('api_key', '')).strip()
    return dict(enabled=value.get('enabled') is True, base_url=base, api_key=key,
                configured=bool(valid and key and model in models), model=model, models=models,
                label=str(value.get('label', 'CosyVoice v3 Flash' if service == 'cosyvoice' else 'Fish Audio'))[:80],
                service=service, default_voice_id=str(value.get('voice_id', ''))[:200])

def availability(plugin, service='fish_tts'):
    cfg = settings(plugin, service)
    return dict(available=cfg['enabled'] and cfg['configured'], configured=cfg['configured'], reachability='not_probed', label=cfg['label'],
                model=cfg['model'], models=cfg['models'], max_characters=MAX_TEXT,
                asr=False, format='mp3', pitch=False, speed=True, credentials_on_server=True,
                service=service, default_voice_id=cfg['default_voice_id'], requires_voice_id=service=='cosyvoice',
                reason='' if cfg['enabled'] and cfg['configured'] else '服务端尚未启用或配置这类语音（需要独立语音 Key）')


def services(plugin):
    return [availability(plugin, name) for name in ('fish_tts', 'cosyvoice')]


def presets(plugin):
    return [dict(service=service, model=model, label=label,
                 configured=model in settings(plugin, service)['models'] and availability(plugin, service)['available'])
            for service, model, label in [('fish_tts','drama-3','Fish Audio Drama 3'),
                ('cosyvoice','cosyvoice-v3-flash','CosyVoice v3 Flash')]]


async def cosy_audio(client, cfg, body, current):
    """Official DashScope task protocol. Collect one MP3; no URL fetch or retry."""
    task_id = uuid.uuid4().hex
    envelope = lambda action, payload: dict(header=dict(action=action, task_id=task_id, streaming='duplex'), payload=payload)
    async with client.ws_connect(cfg['base_url'], headers={'Authorization':'Bearer '+cfg['api_key']},
                                 max_msg_size=MAX_AUDIO, autoping=True) as ws:
        await ws.send_json(envelope('run-task', dict(task_group='audio', task='tts',
            function='SpeechSynthesizer', model=cfg['model'], parameters=body['parameters'], input={})))
        started=False; chunks=[]; size=0
        async for message in ws:
            current()
            if message.type == aiohttp.WSMsgType.BINARY:
                if not started: raise RuntimeError('voice protocol outcome unconfirmed')
                size += len(message.data)
                if size > MAX_AUDIO: raise RuntimeError('voice accepted output limit reached')
                chunks.append(message.data)
            elif message.type == aiohttp.WSMsgType.TEXT:
                frame=json.loads(message.data); header=frame.get('header', {})
                if header.get('task_id') != task_id: raise RuntimeError('voice protocol outcome unconfirmed')
                event=header.get('event')
                if event == 'task-started':
                    if started: raise RuntimeError('voice protocol outcome unconfirmed')
                    started=True
                    await ws.send_json(envelope('continue-task', dict(input=dict(text=body['text']))))
                    await ws.send_json(envelope('finish-task', dict(input={})))
                elif event == 'task-failed':
                    raise VoiceError('CosyVoice 合成失败，没有自动重试。', 502)
                elif event == 'task-finished':
                    if not started: raise RuntimeError('voice protocol outcome unconfirmed')
                    return b''.join(chunks)
            elif message.type in {aiohttp.WSMsgType.ERROR,aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED}:
                break
        raise RuntimeError('voice task disconnected before completion')

def mp3(data):
    return data.startswith(b'ID3') or (len(data) > 2 and data[0] == 255 and data[1] & 224 == 224)

class CloudVoice:
    def __init__(self, plugin, profile):
        self.plugin, self.profile = plugin, profile
        self.journal, self.scope = profile.journal, profile.scope
        self.root = self.journal.path.parent / 'voice_audio'

    def _path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise VoiceError('语音缓存编号无效', 400)
        # Identity is an opaque digest including the authorized full scope.
        return self.root / (identity + '.mp3')

    def read(self, identity):
        self.profile.current()
        row = self.journal.fetch(NS, identity, self.scope)
        path = self._path(identity)
        if row is None or row['data'].get('state') != 'ready':
            raise VoiceError('当前会话没有这段已生成的语音', 404)
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_AUDIO:
            raise VoiceError('语音副本已过期，请重新朗读原消息', 404)
        self.profile.current()
        return path, row['data']

    def recent(self):
        self.profile.current()
        items = []
        for row in self.journal.list(NS, self.scope, limit=8):
            data = row['data']
            state = data.get('state', 'unknown')
            cached = False
            if state == 'ready':
                try:
                    self.read(row['key'])
                    cached = True
                except VoiceError:
                    pass
            items.append(dict(audio_id=row['key'], state=state, cached=cached,
                revision=row['revision'], updated_at=row['updated_at'],
                model=data.get('model', ''), preview=data.get('message_id') == 'preview',
                message_id=data.get('message_id', ''), size=data.get('size', 0),
                error=data.get('error_message', '') if state == 'failed' else '',
                retryable=state == 'failed'))
        self.profile.current()
        return items

    def _reserve(self, identity, data, retry_failed=False):
        self.profile.current()
        old = self.journal.fetch(NS, identity, self.scope)
        if old:
            if old['data'].get('state') == 'ready':
                try:
                    path, cached = self.read(identity)
                    path.touch()
                    return dict(cached, audio_id=identity, cached=True), None
                except VoiceError:
                    pass  # Known completed synthesis, but its expendable cache was evicted.
            elif old['data'].get('state') == 'failed':
                if not retry_failed:
                    raise VoiceError('上次合成已失败，未重复调用。'+(old['data'].get('error_message') or '')+' 如需再次调用，请点击明确重试。', 409)
            else:
                raise VoiceError('这次合成仍在处理或结果不明。请刷新语音记录；不会重复调用付费接口。', 409)
        row = self.journal.put(NS, identity, self.scope, dict(data, state='generating'),
            expected_revision=old['revision'] if old else 0, authorize=self.profile.current)
        return None, row

    def _finish(self, identity, row, data):
        return self.journal.put(NS, identity, self.scope, data,
            expected_revision=row['revision'], authorize=self.profile.current)

    def _store(self, identity, raw):
        self.root.mkdir(parents=True, exist_ok=True)
        paths = sorted((p for p in self.root.glob('*.mp3') if re.fullmatch(r'[a-f0-9]{64}\.mp3', p.name) and not p.is_symlink()), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in paths); count = len(paths)
        for p in paths:
            if total + len(raw) <= 128 * 1024 * 1024 and count < 256: break
            size=p.stat().st_size; p.unlink(); total-=size; count-=1
        self.profile.current()
        path=self._path(identity)
        with path.open('wb') as stream:
            os.chmod(path, 0o600); stream.write(raw)
        return path

    async def synthesize(self, text, message_id, chosen=None, *, retry_failed=False):
        profile = chosen or self.profile.get()['profile']
        binding = profile['binding']
        service = binding['service']
        cfg = settings(self.plugin, service)
        if not cfg['enabled'] or not cfg['configured']:
            raise VoiceError('当前服务器未配置可用的云端语音', 503)
        if service not in {'fish_tts','cosyvoice'}: raise VoiceError('请先选择云端音色', 400)
        model = binding.get('model') or cfg['model']
        if model not in cfg['models']: raise VoiceError('这个语音模型未在当前服务器启用', 400)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise VoiceError('云端单次朗读支持 1–1500 字；原消息不会被截断', 400)
        body = dict(text=text, format='mp3', normalize=True, latency='normal',
                    prosody=dict(speed=profile['rate']))
        if binding['voice_id']: body['reference_id'] = binding['voice_id']
        if service == 'cosyvoice':
            voice = binding['voice_id'] or cfg['default_voice_id']
            if not voice: raise VoiceError('请先填写 CosyVoice v3 Flash 的真实音色 ID', 400)
            body = dict(text=text, parameters=dict(text_type='PlainText', voice=voice,
                format='mp3', sample_rate=24000, volume=50, rate=profile['rate'], pitch=1.0))
        identity = hashlib.sha256(canonical([scope_key(self.scope), cfg['base_url'], model, message_id, body]).encode()).hexdigest()
        data = dict(message_id=str(message_id), model=model, source=service, mime_type='audio/mpeg',
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(), characters=len(text), created_at=time.time())
        cached, row = await asyncio.to_thread(self._reserve, identity, data, retry_failed)
        if cached: return cached
        try:
            self.profile.current()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=80)) as client:
                if service == 'cosyvoice':
                    raw = await asyncio.wait_for(cosy_audio(client, dict(cfg,model=model), body, self.profile.current), timeout=80)
                else:
                    raw = await self._fish_audio(client, cfg, model, body)
            if not raw or not mp3(raw): raise VoiceError('语音服务没有返回有效 MP3', 502)
            self.profile.current()
            await asyncio.to_thread(self._store, identity, raw)
            data.update(state='ready', size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), finished_at=time.time())
            await asyncio.to_thread(self._finish, identity, row, data)
            return dict(data, audio_id=identity, cached=False)
        except (Exception, asyncio.CancelledError) as exc:
            # Preserve an indeterminate request as such across restarts; no blind POST retry.
            try:
                await asyncio.shield(asyncio.to_thread(self._finish, identity, row,
                    dict(data, state='failed' if isinstance(exc, VoiceError) else 'unknown', error_type=type(exc).__name__, error_message=str(exc) if isinstance(exc, VoiceError) else '')))
            except Exception: pass
            if isinstance(exc, (VoiceError, asyncio.CancelledError, PermissionError)): raise
            raise VoiceError('云端语音未完成，结果不明；没有自动重试或改用其他模型。') from None

    async def _fish_audio(self, client, cfg, model, body):
        async with client.post(cfg['base_url']+'/tts', json=body,
                headers={'Authorization':'Bearer '+cfg['api_key'], 'model':model}, allow_redirects=False) as response:
            if response.status != 200:
                # Provider bodies can contain credentials; do not expose them.
                reason = {401:'语音凭据未通过验证',402:'语音服务额度不足',403:'语音服务拒绝请求',429:'语音服务暂时限流'}.get(response.status,'语音服务暂不可用')
                raise VoiceError(reason+'（HTTP '+str(response.status)+'），没有自动重试。', 502)
            chunks=[]; size=0
            async for chunk in response.content.iter_chunked(65536):
                size+=len(chunk)
                if size>MAX_AUDIO: raise VoiceError('语音结果超过可用大小，未保存', 502)
                chunks.append(chunk)
        return b''.join(chunks)
