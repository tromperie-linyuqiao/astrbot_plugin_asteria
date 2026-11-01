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

def settings(plugin):
    value = getattr(plugin, 'config', {}).get('voice_cloud', {})
    value = value if isinstance(value, dict) else {}
    base = str(value.get('base_url', '')).rstrip('/')
    parsed = urlsplit(base)
    valid = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
    models = [v for v in value.get('models', []) if isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', v)] if isinstance(value.get('models'), list) else []
    model = str(value.get('model', ''))
    key = str(value.get('api_key', '')).strip()
    return dict(enabled=value.get('enabled') is True, base_url=base, api_key=key,
                configured=bool(valid and key and model in models), model=model, models=models,
                label=str(value.get('label', '云端语音'))[:80])

def availability(plugin):
    cfg = settings(plugin)
    return dict(available=cfg['enabled'] and cfg['configured'], label=cfg['label'],
                model=cfg['model'], models=cfg['models'], max_characters=MAX_TEXT,
                asr=False, format='mp3', pitch=False, speed=True, credentials_on_server=True,
                reason='' if cfg['enabled'] and cfg['configured'] else '服务端尚未启用或配置云端语音')

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

    def _reserve(self, identity, data):
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
            else:
                raise VoiceError('这次合成仍在处理或结果不明，未重复调用付费接口。可重新读取声音设置或改用设备音色。', 409)
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

    async def synthesize(self, text, message_id, chosen=None):
        cfg = settings(self.plugin)
        if not cfg['enabled'] or not cfg['configured']:
            raise VoiceError('当前服务器未配置可用的云端语音', 503)
        profile = chosen or self.profile.get()['profile']
        binding = profile['binding']
        if binding['service'] != 'fish_tts': raise VoiceError('请先选择云端音色', 400)
        model = binding.get('model') or cfg['model']
        if model not in cfg['models']: raise VoiceError('这个语音模型未在当前服务器启用', 400)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise VoiceError('云端单次朗读支持 1–1500 字；原消息不会被截断', 400)
        body = dict(text=text, format='mp3', normalize=True, latency='normal',
                    prosody=dict(speed=profile['rate']))
        if binding['voice_id']: body['reference_id'] = binding['voice_id']
        identity = hashlib.sha256(canonical([scope_key(self.scope), cfg['base_url'], model, message_id, body]).encode()).hexdigest()
        data = dict(message_id=str(message_id), model=model, source='fish_tts', mime_type='audio/mpeg',
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(), characters=len(text), created_at=time.time())
        cached, row = await asyncio.to_thread(self._reserve, identity, data)
        if cached: return cached
        try:
            self.profile.current()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=80)) as client:
                async with client.post(cfg['base_url']+'/tts', json=body,
                        headers={'Authorization':'Bearer '+cfg['api_key'], 'model':model}, allow_redirects=False) as response:
                    if response.status != 200:
                        # Provider errors may echo secrets; never forward their body.
                        reason = {401:'语音凭据未通过验证',402:'语音服务额度不足',403:'语音服务拒绝请求',429:'语音服务暂时限流'}.get(response.status,'语音服务暂不可用')
                        raise VoiceError(reason+'（HTTP '+str(response.status)+'），没有自动重试。', 502)
                    chunks=[]; size=0
                    async for chunk in response.content.iter_chunked(65536):
                        size+=len(chunk)
                        if size>MAX_AUDIO: raise VoiceError('语音结果超过可用大小，未保存', 502)
                        chunks.append(chunk)
            raw=b''.join(chunks)
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
                    dict(data, state='failed' if isinstance(exc, VoiceError) else 'unknown', error_type=type(exc).__name__)))
            except Exception: pass
            if isinstance(exc, (VoiceError, asyncio.CancelledError, PermissionError)): raise
            raise VoiceError('云端语音未完成，结果不明；没有自动重试或改用其他模型。') from None
