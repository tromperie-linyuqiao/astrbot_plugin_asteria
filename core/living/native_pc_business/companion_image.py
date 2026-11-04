"""Bind existing image generation to companion sends; no new provider or LLM."""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .helpers import _today_key
from .photo_clothing import ensure_character_clothing, split_photo_prompt

_VERSION = 2
_THEME_MARKER = re.compile(r"Companion image theme:\s*([a-z_]+)", re.I)
_BARE = re.compile(r"\b(?:nude|naked|topless|bottomless|unclothed)\b|裸体|全裸|不穿衣服", re.I)
_SCENES = {
    "care": "quiet supportive company, a calm attentive expression, comfortable everyday surroundings",
    "night": "quiet evening company, subdued lighting, relaxed clothed portrait, restful atmosphere",
    "daily": "a small ordinary daily moment, composed expression, natural everyday surroundings",
    "weather_rain": "rain visible in the environment, sheltered comfortable portrait, soft rainy light",
    "weather_snow": "snow visible in the environment, warm covering clothes, soft winter light",
    "weather_cold": "cool weather, warm covering clothes, comfortable sheltered portrait",
    "weather_hot": "warm weather, light but complete everyday clothing, gentle summer light",
    "weather_wind": "wind visible in the surroundings, weather-appropriate covering clothes",
    "weather_clear": "clear weather visible in the surroundings, natural light, composed portrait",
    "weather_overcast": "overcast weather visible in the surroundings, soft diffused light",
}
_CAPTIONS = {
    "care": "安静陪伴的日常人物画面", "night": "低光下安静休息的日常人物画面",
    "daily": "德克萨斯日常状态的人物画面", "weather_rain": "雨天环境中的日常人物画面",
    "weather_snow": "雪天环境中的日常人物画面", "weather_cold": "凉冷天气中的日常人物画面",
    "weather_hot": "温暖天气中的日常人物画面", "weather_wind": "风中环境的日常人物画面",
    "weather_clear": "晴朗环境中的日常人物画面", "weather_overcast": "阴天环境中的日常人物画面",
}


def _number(value: Any, default: float = 0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _line(value: Any, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"false", "0", "off", "no", "否"}


def companion_theme(text: str, reason: str = "", *, hour: int = 12,
                    night_mode: str = "quiet_companion") -> str:
    """Classify only; raw chat is never interpolated into an image prompt."""
    value = (str(reason or "") + " " + str(text or "")).lower()
    for theme, pattern in (
        ("weather_snow", r"下雪|雪天|雪景|snow"),
        ("weather_rain", r"下雨|雨天|雨声|雨滴|大雨|小雨|rain"),
        ("weather_cold", r"降温|天气冷|天冷|寒冷|冷天|cold weather"),
        ("weather_hot", r"天气热|天热|炎热|高温|hot weather"),
        ("weather_wind", r"起风|刮风|大风|windy"),
        ("weather_clear", r"晴天|晴朗|阳光|sunny|clear weather"),
        ("weather_overcast", r"阴天|多云|overcast|cloudy"),
    ):
        if re.search(pattern, value):
            return theme
    if night_mode != "off" and (
        hour >= 21 or hour < 6
        or re.search(r"晚安|夜晚|深夜|睡前|休息|night|evening|sleep", value)
    ):
        return "night"
    if re.search(r"照顾|担心|关心|累了|辛苦|难过|陪着|陪你|陪伴|care|check.in|support", value):
        return "care"
    return "daily"


def valid_companion_image(value: Any) -> str:
    """Require a complete decodable local still image, never a URL or header alone."""
    raw = str(value or "").strip()
    if raw.lower().startswith("file://"):
        parsed = urlsplit(raw)
        if parsed.netloc and parsed.netloc not in {"localhost"}:
            return ""
        raw = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
    if not raw or "://" in raw or raw.lower().startswith("base64:"):
        return ""
    try:
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return ""
        if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
            return ""
        from PIL import Image
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 40_000_000:
                return ""
            image.verify()
        with Image.open(path) as image:
            image.load()
        return str(path)
    except Exception:
        return ""


class CompanionImageMixin:
    @staticmethod
    def _companion_image_digest(path: str) -> str:
        try:
            with open(path, 'rb') as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                return digest.hexdigest()
        except OSError:
            return ''

    def _companion_image_was_used(self, user: dict, path: str, *, digest: str = '') -> bool:
        """Content identities are shared by every proactive outlet, not file names."""
        digest = digest or self._companion_image_digest(path)
        if not re.fullmatch(r'[0-9a-f]{64}', digest or ''):
            return True
        users = [user]
        resolver = getattr(self, '_companion_delivery_user', None)
        current = resolver(self._companion_image_scope(user)) if callable(resolver) else None
        if isinstance(current, dict) and current is not user:
            users.append(current)
        for record_user in users:
            records = record_user.get('companion_used_images')
            if any(isinstance(item, dict) and item.get('sha256') == digest
                   for item in (records if isinstance(records, list) else [])):
                return True
            unknown = record_user.get('companion_uncertain_deliveries')
            if any(isinstance(item, dict) and item.get('image_digest') == digest
                   for item in (unknown if isinstance(unknown, list) else [])):
                return True
            last_path = str(record_user.get('companion_image_last_path') or '')
            if last_path:
                last_digest = str(record_user.get('companion_image_last_digest') or '')
                if not last_digest:
                    last_digest = self._companion_image_digest(last_path)
                if last_digest == digest:
                    return True
        raw = self.data.get('recent_photo_generations') if isinstance(getattr(self, 'data', None), dict) else []
        scope = self._companion_image_scope(user)
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or str(item.get('session') or '') != scope:
                continue
            if not (item.get('sent') is True or _number(item.get('companion_sent_count')) > 0
                    or _number(item.get('companion_last_sent_at')) > 0):
                continue
            recorded_digest = str(item.get('companion_image_sha256') or '')
            if not recorded_digest:
                recorded_digest = self._companion_image_digest(str(item.get('path') or ''))
            if recorded_digest == digest:
                return True
        return False

    def _companion_consume_image(self, user: dict, path: str, *, digest: str = '',
                                 status: str = 'sent', now: float | None = None) -> None:
        """Call under the delivery/data locks on confirmed or uncertain dispatch."""
        digest = digest or self._companion_image_digest(path)
        if not re.fullmatch(r'[0-9a-f]{64}', digest or ''):
            return
        now = time.time() if now is None else now
        raw = user.get('companion_used_images')
        records = [item for item in (raw if isinstance(raw, list) else [])
                   if isinstance(item, dict) and re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256') or ''))
                   and item.get('sha256') != digest]
        records.append({'sha256': digest, 'at': now, 'status': 'unknown' if status == 'unknown' else 'sent'})
        user['companion_used_images'] = records[-256:]
        prepared = user.get('companion_prepared_images')
        if isinstance(prepared, dict):
            user['companion_prepared_images'] = {
                key: item for key, item in prepared.items()
                if isinstance(item, dict) and item.get('image_digest') != digest}

    def _companion_prepared_image(self, user: dict, request_key: str, text: str, *, now: float) -> dict | None:
        records = user.get('companion_prepared_images')
        key = hashlib.sha256(str(request_key).encode('utf-8')).hexdigest()
        record = records.get(key) if isinstance(records, dict) else None
        if (not isinstance(record, dict) or record.get('version') != _VERSION
                or record.get('session') != self._companion_image_scope(user)):
            return None
        if record.get('text_digest') != hashlib.sha256(str(text).encode('utf-8')).hexdigest():
            return None
        max_age = min(24.0, max(0.0, _number(getattr(self, 'companion_image_cache_hours', 48), 48))) * 3600
        if (max_age <= 0 or record.get('identity') != self._companion_image_identity()
                or not 0 <= now - _number(record.get('created_at')) <= max_age):
            return None
        path = valid_companion_image(record.get('path'))
        if not path or not record.get('image_digest') or record['image_digest'] != self._companion_image_digest(path):
            return None
        if self._companion_image_was_used(user, path, digest=record['image_digest']):
            return None
        return dict(record, path=path)

    def _companion_image_required(self, user: dict[str, Any] | None = None) -> bool:
        return _bool(getattr(self, "companion_require_image", True))

    def _companion_image_identity(self) -> str:
        # Reuse the configured visual identity and current outfit extraction.
        pieces = []
        for name in ("_daily_outfit_role_appearance_text", "_photo_current_clothing_hint"):
            function = getattr(self, name, None)
            if callable(function):
                pieces.append(_line(function(), 900))
        pieces.extend(_line(getattr(self, name, ""), 1000) for name in (
            "photo_persona_reference_image_path", "private_image_self_recognition_hint",
            "photo_generation_style", "photo_generation_style_custom_prompt",
        ))
        return hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()

    def _companion_image_scope(self, user: dict[str, Any]) -> str:
        return str(user.get("umo") or "").strip()

    def _companion_image_prompt(self, theme: str) -> str:
        identity = "the configured bot character, keep the established face, hairstyle and visual identity"
        appearance = getattr(self, "_daily_outfit_role_appearance_text", None)
        if callable(appearance):
            detail = _line(appearance(), 700)
            if detail:
                identity += "; " + detail
        outfit = getattr(self, "_photo_current_clothing_hint", None)
        clothing_hint = _line(outfit(), 360) if callable(outfit) else ""
        prompt = (
            f"Positive prompt: Companion image theme: {theme}; {identity}; "
            f"{_SCENES[theme]}; quiet, composed, understated companionship, "
            "natural environmental upper-body portrait, no mirror, "
            "follow the current schedule and location rather than inventing a new setting. "
            "Negative prompt: text, watermark, logo, mirror selfie, phone covering face, nsfw."
        )
        return ensure_character_clothing(prompt, "selfie", clothing_hint=clothing_hint)

    def _companion_image_quota_ok(self, user: dict[str, Any]) -> bool:
        resolver = getattr(self, "_effective_user_photo_daily_limit", None)
        if not callable(resolver):
            return False
        limit = int(_number(resolver(user)))
        used = int(_number(user.get("photo_sent_today"))) if user.get("photo_sent_day") == _today_key() else 0
        confirmed = int(_number(user.get("companion_photo_sent_today"))) if user.get("companion_photo_sent_day") == _today_key() else 0
        used = max(used, confirmed)
        raw = user.get('companion_uncertain_deliveries')
        used += sum(isinstance(item, dict) and item.get('day') == _today_key()
                    for item in (raw if isinstance(raw, list) else []))
        return limit > 0 and used < limit

    def _companion_image_cached(self, user: dict[str, Any], theme: str, *, now: float,
                                preferred_path: str = "") -> str:
        data = self.data if isinstance(getattr(self, "data", None), dict) else {}
        raw = data.get("recent_photo_generations")
        if not isinstance(raw, list):
            return ""
        scope = self._companion_image_scope(user)
        signature = self._companion_image_identity()
        max_age = min(168.0, max(0.0, _number(getattr(self, "companion_image_cache_hours", 48), 48))) * 3600
        preferred = valid_companion_image(preferred_path) if preferred_path else ""
        if preferred_path and not preferred:
            return ""
        for item in sorted((x for x in raw[:12] if isinstance(x, dict)),
                           key=lambda x: _number(x.get("ts")), reverse=True):
            age = now - _number(item.get("ts"))
            if not item.get("ok") or not 0 <= age <= max_age or str(item.get("session") or "") != scope:
                continue
            if item.get("companion_version") != _VERSION or item.get("companion_theme") != theme:
                continue
            if item.get("companion_identity") != signature or item.get("companion_subject_owner") != "bot":
                continue
            positive, _negative = split_photo_prompt(str(item.get("prompt") or ""))
            if not re.search(r"Clothing continuity:.*?visibly clothed", positive, re.I) or _BARE.search(positive):
                continue
            marker = _THEME_MARKER.search(positive)
            if not marker or marker.group(1).lower() != theme:
                continue
            path = valid_companion_image(item.get("path"))
            if path and item.get('companion_image_sha256') != self._companion_image_digest(path):
                continue
            if path and self._companion_image_was_used(user, path):
                continue
            if path and (not preferred or path == preferred):
                return path
        return ""

    def _companion_image_tag(self, user: dict[str, Any], path: str, theme: str) -> None:
        raw = self.data.get("recent_photo_generations") if isinstance(getattr(self, "data", None), dict) else None
        if not isinstance(raw, list):
            return
        scope = self._companion_image_scope(user)
        for item in raw[:12]:
            if not isinstance(item, dict) or str(item.get("session") or "") != scope:
                continue
            if valid_companion_image(item.get("path")) != path:
                continue
            # _generate_photo_image records its final guarded prompt. Do not bless
            # arbitrary files or older images that lack the same prompt guards.
            positive, _negative = split_photo_prompt(str(item.get("prompt") or ""))
            if not re.search(r"Clothing continuity:.*?visibly clothed", positive, re.I) or _BARE.search(positive):
                return
            marker = _THEME_MARKER.search(positive)
            if not marker or marker.group(1).lower() != theme:
                return
            item.update(companion_version=_VERSION, companion_theme=theme,
                        companion_identity=self._companion_image_identity(), companion_subject_owner="bot",
                        companion_image_sha256=self._companion_image_digest(path))
            return

    async def _prepare_companion_image(self, user: dict[str, Any], text: str,
                                       reason: str = "", existing_path: str = "", *, request_key: str = "") -> dict[str, Any]:
        if not self._companion_image_required(user):
            return {"ok": True, "path": "", "theme": "", "source": "disabled", "note": "图片强制绑定已关闭"}
        locks = getattr(self, "_companion_image_locks", None)
        if not isinstance(locks, dict):
            locks = self._companion_image_locks = {}
        scope = self._companion_image_scope(user) if isinstance(user, dict) else ""
        if not scope:
            return {"ok": False, "path": "", "theme": "", "source": "deferred", "note": "缺少用户私聊会话"}
        if scope not in locks and len(locks) >= 256:
            for key, lock in list(locks.items()):
                if not lock.locked():
                    locks.pop(key, None)
                    break
            if len(locks) >= 256:
                return {"ok": False, "path": "", "theme": "", "source": "deferred",
                        "note": "当前配图请求较多，稍后重试"}
        lock = locks.setdefault(scope, asyncio.Lock())
        async with lock:
            result = await self._prepare_companion_image_unlocked(user, text, reason, existing_path, request_key=request_key)
            if request_key and result.get('ok') and result.get('path'):
                records = user.get('companion_prepared_images')
                records = records if isinstance(records, dict) else {}
                key = hashlib.sha256(str(request_key).encode('utf-8')).hexdigest()
                old_record = records.get(key)
                created_at = (_number(old_record.get('created_at'), time.time())
                              if result.get('source') == 'existing' and isinstance(old_record, dict) else time.time())
                records[key] = {'version': _VERSION, 'session': scope,
                    'text_digest': hashlib.sha256(str(text).encode('utf-8')).hexdigest(),
                    'path': result['path'], 'theme': result['theme'], 'identity': self._companion_image_identity(),
                    'image_digest': self._companion_image_digest(result['path']), 'created_at': created_at}
                async def remember():
                    user['companion_prepared_images'] = dict(list(records.items())[-8:])
                    resolver = getattr(self, '_companion_delivery_user', None)
                    current = resolver(scope) if callable(resolver) else None
                    if isinstance(current, dict):
                        current['companion_prepared_images'] = dict(user['companion_prepared_images'])
                    self._save_data_sync()
                data_lock = getattr(self, '_data_lock', None)
                if data_lock is not None:
                    async with data_lock:
                        await remember()
                else:
                    await remember()
            return result

    async def _prepare_companion_image_unlocked(self, user: dict[str, Any], text: str,
                                                reason: str, existing_path: str, *, request_key: str = "") -> dict[str, Any]:
        now = time.time()
        try:
            hour = self._environment_now().hour
        except Exception:
            hour = datetime.now().hour
        theme = companion_theme(text, reason, hour=hour,
                                night_mode=str(getattr(self, "companion_night_mode", "quiet_companion")))
        result = {"ok": False, "path": "", "theme": theme, "source": "deferred", "note": "",
                  "subject_owner": "bot", "caption": _CAPTIONS[theme], "retry_at": 0}

        def defer(note: str, *, renew: bool = True) -> dict[str, Any]:
            retry = max(1, min(240, _number(getattr(self, "companion_image_retry_minutes", 15), 15))) * 60
            until = now + retry if renew else _number(user.get("companion_image_retry_at"), now + retry)
            user["companion_image_retry_at"] = until
            user["companion_image_last_note"] = _line(note, 180)
            result.update(note=_line(note, 180), retry_at=until)
            return result

        try:
            unknown_block = getattr(self, '_companion_uncertain_block_reason', None)
            if callable(unknown_block) and unknown_block(user, now=now):
                return defer('上次平台回执不确定，暂缓重复图片请求')
            role = getattr(self, "_private_user_role", None)
            if callable(role) and role(user) == "friend":
                return defer("次要用户关系不复用主要用户人物图片")
            if not self._companion_image_quota_ok(user):
                return defer("今日主动图片发送额度已满或图片发送已关闭")
            staged = self._companion_prepared_image(user, request_key, text, now=now) if request_key else None
            if staged:
                result.update(ok=True, path=staged['path'], theme=staged['theme'], source='existing', note='复用本次约定已批准图片')
                return result
            # A theme match or a caller-supplied old path is not a logical
            # delivery identity. Only the same unsent request may use prepared.
            if _number(user.get("companion_image_retry_at")) > now:
                return defer("图片异常重试间隔尚未结束", renew=False)
            available = getattr(self, "_photo_text_available", None)
            generator = getattr(self, "_generate_photo_image", None)
            if not callable(available) or not available(user) or not callable(generator):
                return defer("图片后端或生成额度当前不可用")
            prompt = self._companion_image_prompt(theme)
            note = ""
            path = ""
            try:
                _backend, generated, note = await generator(
                    workflow_kind="selfie", prompt_text=prompt,
                    session_key=self._companion_image_scope(user),
                    allow_daily_outfit_reference=True,
                )
                path = valid_companion_image(generated)
                if generated and not path:
                    note = "图片输出不是有效完整图片"
            except Exception as exc:
                note = "图片生成异常：" + type(exc).__name__
            reused_output = bool(path and self._companion_image_was_used(user, path))
            failure_counter = getattr(self, "_photo_generation_failure_counts_as_attempt", None)
            counted = bool(path) or (callable(failure_counter) and bool(failure_counter(note)))
            data_lock = getattr(self, "_data_lock", None)
            if data_lock is not None:
                async with data_lock:
                    if counted and callable(getattr(self, "_note_photo_generation_attempt", None)):
                        self._note_photo_generation_attempt(str(user.get("user_id") or ""), image_path=path)
                    if path and not reused_output:
                        self._companion_image_tag(user, path, theme)
                    self._save_data_sync()
            elif counted and callable(getattr(self, "_note_photo_generation_attempt", None)):
                self._note_photo_generation_attempt(str(user.get("user_id") or ""), image_path=path)
                if path and not reused_output:
                    self._companion_image_tag(user, path, theme)
            if reused_output:
                return defer("图片后端返回已发送或送达不确定的旧图，等待新图后再发送")
            if path:
                user.pop("companion_image_retry_at", None)
                result.update(ok=True, path=path, source="generated", note="通过现有生图接口生成主题匹配图片")
                return result
            return defer(note or "图片生成未产出有效成图")
        except Exception as exc:
            return defer("图片绑定异常：" + type(exc).__name__)

    @staticmethod
    def _companion_component_kind(component: Any) -> str:
        data = component if isinstance(component, dict) else None
        kind = str((data.get('type') if data is not None else getattr(component, 'type', '')) or '').lower()
        name = type(component).__name__.lower()
        return name if name in {'plain', 'image', 'node', 'nodes', 'forward'} else kind

    def _companion_component_has_nested_image(self, component: Any, *, depth: int = 0) -> bool:
        if depth > 12:
            return True
        kind = self._companion_component_kind(component)
        if kind in {'image', 'node', 'nodes', 'forward'}:
            return True
        if isinstance(component, dict):
            children = component.values()
        elif isinstance(component, (list, tuple)):
            children = component
        else:
            children = [getattr(component, key, None) for key in ('content', 'message', 'messages', 'nodes', 'chain', 'components')]
        return any(self._companion_component_has_nested_image(child, depth=depth + 1)
                   for child in children if not isinstance(child, (str, bytes, int, float, bool, type(None))))

    def _companion_delivery_fingerprint(self, components: list[Any]) -> tuple[str, str]:
        for component in components:
            if self._companion_component_kind(component) == 'image':
                for key in ('file', 'path', 'url'):
                    path = valid_companion_image(component.get(key) if isinstance(component, dict) else getattr(component, key, ''))
                    if path:
                        return path, self._companion_image_digest(path)
        return '', ''

    def _restore_companion_delivery_chain(self, approved: list[Any], decorated: list[Any], *,
                                          fingerprint: tuple[str, str] | None = None) -> list[Any]:
        if not self._companion_chain_has_image_and_text(approved):
            return []
        if fingerprint is not None and self._companion_delivery_fingerprint(approved) != fingerprint:
            return []
        approved_image = next(c for c in approved if self._companion_component_kind(c) == 'image')
        result = [c for c in decorated or [] if not self._companion_component_has_nested_image(c)]
        if not any(self._companion_component_kind(c) in {'plain', 'text'} and str(c.get('text') if isinstance(c, dict) else getattr(c, 'text', '') or '').strip() for c in result):
            result.extend(c for c in approved if self._companion_component_kind(c) in {'plain', 'text'})
        result.insert(0, approved_image)
        return result

    def _companion_chain_has_image_and_text(self, components: list[Any]) -> bool:
        text = False
        images = []
        for component in components or []:
            data = component if isinstance(component, dict) else None
            kind = self._companion_component_kind(component)
            if kind in {"plain", "text"}:
                value = data.get("text") if data is not None else getattr(component, "text", "")
                text = text or bool(str(value or "").strip())
            if kind == "image":
                values = [data.get(name) if data is not None else getattr(component, name, "")
                          for name in ("file", "path", "url")]
                path = next((valid_companion_image(value) for value in values if value and valid_companion_image(value)), '')
                if not path:
                    return False
                images.append(path)
            elif self._companion_component_has_nested_image(component):
                return False
        return bool(text and len(images) == 1)

    def _companion_record_image_sent(self, user: dict[str, Any], path: str,
                                      *, theme: str = "", **_kwargs: Any) -> None:
        """Metadata only. The existing photo_text action settles the daily count."""
        image = valid_companion_image(path)
        if not image:
            return
        now = time.time()
        digest = self._companion_image_digest(image)
        self._companion_consume_image(user, image, digest=digest, now=now)
        user.update(companion_image_last_path=image, companion_image_last_at=now,
                    companion_image_last_theme=theme, companion_image_last_digest=digest)
        user.pop("companion_image_retry_at", None)
        raw = self.data.get("recent_photo_generations") if isinstance(getattr(self, "data", None), dict) else []
        for item in raw or []:
            if isinstance(item, dict) and item.get("session") == self._companion_image_scope(user) and valid_companion_image(item.get("path")) == image:
                item.update(companion_last_sent_at=now, companion_sent_count=int(_number(item.get("companion_sent_count"))) + 1)
                break
