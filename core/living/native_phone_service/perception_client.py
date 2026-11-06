# -*- coding: utf-8 -*-
"""异步桥接请求；保留原设备、授权、进程内 TTL 和状态回执。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from urllib.parse import urlencode

from ..async_http import HttpStatusError, HttpTransportError, read_json


class PerceptionClient:
    def __init__(self, base_url: str, token: str, timeout: float = 4.0,
                 cache_ttl: float = 20.0, device_id: str = "phone"):
        self.base_url = (base_url or "").rstrip("/")
        self.token = (token or "").strip()
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.device_id = device_id
        self._cache: dict = {}  # key -> (ts, data)；失败结果短 TTL 负缓存
        self._state_diagnostics: dict = {}
        self._generation = 0
        self._state_guard = threading.RLock()
        self._lock = asyncio.Lock()

    def configure(self, base_url: str, token: str, device_id: str | None = None) -> None:
        updated = ((base_url or "").rstrip("/"), (token or "").strip(), device_id or self.device_id)
        with self._state_guard:
            if updated != (self.base_url, self.token, self.device_id):
                self.base_url, self.token, self.device_id = updated
                self.invalidate()

    def invalidate(self) -> None:
        with self._state_guard:
            self._generation += 1
            self._cache.clear()
            self._state_diagnostics.clear()

    def state_snapshot(self, stale_seconds: int = 600, device: str | None = None) -> dict:
        """Borrow existing facts and real request times; this never performs I/O."""
        key = f"state:{device or self.device_id}:{stale_seconds}"
        with self._state_guard:
            cached = self._cache.get(key)
            return {"fetched_at": cached[0] if isinstance(cached, tuple) and len(cached) == 2 else None,
                    "view": cached[1] if isinstance(cached, tuple) and len(cached) == 2 else None,
                    "request": dict(self._state_diagnostics.get(key, {}))}

    def _state_result(self, key, result, attempted, *, code=None):
        previous = self._state_diagnostics.get(key, {})
        now = time.time()
        success = isinstance(result, dict) and result.get("ok") is True
        status = result.get("status") if isinstance(result, dict) else None
        denied = status in (401, 403)
        self._state_diagnostics[key] = {
            "last_attempt_at": attempted, "last_response_at": now,
            "last_success_at": now if success else previous.get("last_success_at"),
            "http_status": status if type(status) is int else 200 if success else None,
            "error_code": None if success else code or "bridge_rejected",
            "error": None if success else str(result.get("error", "桥未确认状态"))[:1024],
            "authorization_denied": False if success else denied or previous.get("authorization_denied", False),
            "authorization_status": status if denied else None if success else previous.get("authorization_status"),
        }
        if len(self._state_diagnostics) > 8:
            oldest = min(self._state_diagnostics, key=lambda item: self._state_diagnostics[item]["last_attempt_at"])
            self._state_diagnostics.pop(oldest, None)
        return result

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and bool(self.token)

    async def _json(self, method: str, path: str, *, payload: dict | None = None, maximum: int = 2 << 20):
        with self._state_guard:
            url, token, timeout = self.base_url + path, self.token, self.timeout
        return await read_json(method, url, timeout=timeout, maximum=maximum,
                               headers={"Authorization": f"Bearer {token}"}, payload=payload)

    async def _fetch_once(self, stale_seconds: int, device: str | None = None) -> dict:
        query = urlencode(dict(device=device or self.device_id, stale_seconds=stale_seconds))
        return await self._json("GET", "/state?" + query, maximum=512 * 1024)

    async def _history_once(self, minutes: int, device: str | None = None) -> dict:
        query = urlencode(dict(device=device or self.device_id, minutes=minutes))
        return await self._json("GET", "/history?" + query)

    async def get_history(self, minutes: int = 360, device: str | None = None) -> dict:
        """返回桥的 /history JSON。失败时返回 {"ok": False, "error": 中文原因}。"""
        if not self.configured:
            return {"ok": False, "error": "插件未配置桥地址或令牌"}
        async with self._lock:
            try:
                return await self._history_once(minutes, device)
            except HttpStatusError as exc:
                detail = {401: "令牌被拒绝", 503: "桥未配置令牌"}.get(exc.status, f"HTTP {exc.status}")
                return {"ok": False, "error": detail, "status": exc.status}
            except (HttpTransportError, TimeoutError, OSError) as exc:
                return {"ok": False, "error": f"连不上桥：{exc}"}
            except (ValueError, json.JSONDecodeError):
                return {"ok": False, "error": "桥返回了无法解析的内容"}
            except Exception as exc:
                return {"ok": False, "error": f"未知错误：{exc}"}

    async def _rotate_once(self) -> dict:
        return await self._json("POST", "/admin/rotate-token", payload={}, maximum=128 * 1024)

    async def _config_call(self, method: str, payload: dict | None = None) -> dict:
        return await self._json(method, "/client-config", payload=payload, maximum=512 * 1024)

    async def _surprises_once(self) -> dict:
        return await self._json("GET", "/surprises", maximum=512 * 1024)

    async def get_surprises(self) -> dict:
        """桥端惊喜内容（greetings/care 覆盖层）。失败返回空 dict（退回内置文案）。"""
        if not self.configured:
            return {}
        try:
            data = await self._surprises_once()
            return data.get("surprises") if isinstance(data, dict) and data.get("ok") else {}
        except Exception:
            return {}

    async def _playlist_bridge_once(self) -> dict:
        return await self._json("GET", "/playlist", maximum=4 << 20)

    async def get_playlist_bridge(self) -> dict | None:
        """桥端歌单主存；成功可为空，失败返回 None（退回本地）。"""
        if not self.configured:
            return None
        try:
            data = await self._playlist_bridge_once()
            pl = data.get("playlist") if isinstance(data, dict) and data.get("ok") else None
            return pl if isinstance(pl, dict) else None
        except Exception:
            return None

    async def _put_playlist_once(self, playlist: dict) -> bool:
        value = await self._json("PUT", "/playlist", payload={"playlist": playlist}, maximum=512 * 1024)
        return isinstance(value, dict) and value.get("ok") is True

    async def put_playlist_bridge(self, playlist: dict) -> bool:
        if not self.configured:
            return False
        try:
            return await self._put_playlist_once(playlist)
        except Exception:
            return False

    async def _devices_once(self) -> dict:
        return await self._json("GET", "/devices", maximum=512 * 1024)

    async def get_devices(self) -> dict:
        if not self.configured:
            return {"ok": False, "error": "未配置"}
        try:
            return await self._devices_once()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def get_client_config(self) -> dict:
        if not self.configured:
            return {"ok": False, "error": "未配置"}
        async with self._lock:
            try:
                return await self._config_call("GET")
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    async def set_client_config(self, patch: dict) -> dict:
        if not self.configured:
            return {"ok": False, "error": "未配置"}
        async with self._lock:
            try:
                return await self._config_call("POST", {"config": patch})
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    async def rotate_token(self) -> dict:
        """让桥轮换令牌（需当前令牌鉴权）。返回 {"ok":bool,...,"token":新令牌}。"""
        if not self.configured:
            return {"ok": False, "error": "插件未配置桥地址或令牌"}
        async with self._lock:
            try:
                with self._state_guard:
                    generation = self._generation
                result = await self._rotate_once()
                with self._state_guard:
                    if generation != self._generation:
                        return {"ok": False, "error": "桥配置已变化，旧轮换结果未应用", "code": "configuration_changed"}
                    token = str(result.get("token") or "").strip()
                    if result.get("ok") and token:
                        self.token = token
                        self.invalidate()
                return result
            except HttpStatusError as exc:
                return {"ok": False, "error": f"HTTP {exc.status}"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    async def get_state(self, stale_seconds: int = 600, device: str | None = None) -> dict:
        """返回桥的 /state JSON（多设备时传 device；默认用构造时的 device_id）。
        失败时返回 {"ok": False, "error": 中文原因}。"""
        if not self.configured:
            return {"ok": False, "error": "插件未配置桥地址或令牌"}
        async with self._lock:
            now = time.time()
            cache_key = f"state:{device or self.device_id}:{stale_seconds}"
            with self._state_guard:
                hit = self._cache.get(cache_key)
                if hit is not None:
                    ts, cached = hit
                    ttl = self.cache_ttl if cached.get("ok") else 30.0
                    if now - ts < ttl:
                        return cached
            try:
                with self._state_guard:
                    generation = self._generation
                data = await self._fetch_once(stale_seconds, device)
                if not isinstance(data, dict):
                    raise ValueError("桥状态必须为对象")
                with self._state_guard:
                    if generation != self._generation:
                        return {"ok": False, "error": "桥配置已改变，旧查询结果已丢弃", "code": "configuration_changed"}
                    data["_key"] = cache_key
                    self._cache[cache_key] = (now, data)
                    if len(self._cache) > 8:
                        for k in sorted(self._cache, key=lambda k: self._cache[k][0])[:-8]:
                            self._cache.pop(k, None)
                    return self._state_result(cache_key, data, now)
            except HttpStatusError as exc:
                detail = {401: "令牌被拒绝", 404: "设备尚无上报", 429: "请求过频",
                          503: "桥未配置令牌"}.get(exc.status, f"HTTP {exc.status}")
                result = {"ok": False, "error": detail, "status": exc.status}
                code = "http_error"
            except (HttpTransportError, TimeoutError, OSError) as exc:
                result = {"ok": False, "error": f"连不上桥：{exc}"}
                code = "transport_error"
            except (ValueError, json.JSONDecodeError):
                result = {"ok": False, "error": "桥返回了无法解析的内容"}
                code = "invalid_response"
            except Exception as exc:  # 兜底：插件绝不能因感知失败拖垮主流程
                result = {"ok": False, "error": f"未知错误：{exc}"}
                code = "unexpected_error"
            with self._state_guard:
                if generation != self._generation:
                    return {"ok": False, "error": "桥配置已改变，旧查询结果已丢弃", "code": "configuration_changed"}
                return self._state_result(cache_key, result, now, code=code)
