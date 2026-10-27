"""Strict bridge client shared by the page, commands and optional LLM hook."""

from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit

import httpx

GET_ROUTES = {
    "health",
    "devices",
    "state",
    "history",
    "overview",
    "client-config",
    "surprises",
    "playlist",
    "rules",
    "effects",
}
WRITE_ROUTES = {
    "client-config": "POST",
    "surprises": "PUT",
    "playlist": "PUT",
    "rules": "PUT",
    "surprises/suggest": "POST",
}


class BridgeError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def normalize_url(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 500
        or re.search(r"[\x00-\x20\x7f]", value)
    ):
        raise ValueError("桥端地址不能为空或含空格")
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("桥端地址应为 http(s)://主机:端口，可含反向代理路径")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("桥端端口无效") from exc
    return value.rstrip("/")


def validate_settings(patch: dict, current: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("设置必须是对象")
    keys = {
        "bridge_url",
        "bridge_token",
        "default_device",
        "timeout_seconds",
        "inject_context",
        "allowed_sessions",
        "stale_seconds",
    }
    if set(patch) - keys:
        raise ValueError("设置包含未知字段")
    result = dict(current)
    for key, value in patch.items():
        if key == "bridge_url":
            result[key] = (
                normalize_url(value.strip())
                if isinstance(value, str)
                else normalize_url(value)
            )
        elif key == "bridge_token":
            if (
                not isinstance(value, str)
                or len(value) > 512
                or re.search(r"[^\x20-\x7e]", value)
            ):
                raise ValueError("令牌格式无效")
            if value.strip():
                result[key] = value.strip()  # blank preserves the existing secret
        elif key == "default_device":
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,64}", value
            ):
                raise ValueError("设备 ID 需为 1–64 位英文、数字或 -_.")
            result[key] = value
        elif key in ("timeout_seconds", "stale_seconds"):
            lo, hi = (1, 30) if key == "timeout_seconds" else (30, 86400)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{key} 必须为 {lo}–{hi} 的整数")
            result[key] = value
        elif key == "inject_context":
            if type(value) is not bool:
                raise ValueError("inject_context 必须为布尔值")
            result[key] = value
        elif key == "allowed_sessions":
            if (
                not isinstance(value, list)
                or len(value) > 100
                or any(
                    not isinstance(v, str) or not v.strip() or len(v) > 300
                    for v in value
                )
            ):
                raise ValueError("会话白名单应为最多 100 条的非空字符串数组")
            result[key] = list(dict.fromkeys(v.strip() for v in value))
    return result


class BridgeClient:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.http = httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method: str, route: str, *, params=None, body=None) -> dict:
        if method == "GET":
            allowed = route in GET_ROUTES
        else:
            allowed = WRITE_ROUTES.get(route) == method
        if not allowed:
            raise BridgeError("不支持的操作", 400)
        try:
            base = normalize_url(self.config.get("bridge_base_url", self.config.get("bridge_url", "http://127.0.0.1:6187")))
        except ValueError as exc:
            raise BridgeError(str(exc), 400) from exc
        token = self.config.get("bridge_token", "")
        if not isinstance(token, str) or not token:
            raise BridgeError("请先填写手机使用的 PPB_TOKEN", 400)
        if len(token) > 512 or re.search(r"[^\x20-\x7e]", token):
            raise BridgeError("桥端令牌格式无效", 400)
        timeout = self.config.get("timeout_seconds", 8)
        if type(timeout) is not int or not 1 <= timeout <= 30:
            raise BridgeError("连接超时必须为 1–30 的整数", 400)
        try:
            response = await self.http.request(
                method,
                base + "/" + route,
                params=params,
                json=body,
                headers={"Authorization": "Bearer " + token},
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise BridgeError("桥端连接超时，请检查地址和容器网络", 504) from exc
        except httpx.HTTPError as exc:
            raise BridgeError("无法连接桥端，请检查地址、端口和服务是否运行") from exc
        if response.status_code == 401:
            raise BridgeError("桥端令牌不匹配，请填写手机当前使用的令牌", 401)
        if response.status_code == 404:
            raise BridgeError("接口或设备不存在；完整面板需要升级桥端至 v0.8.0", 404)
        if 300 <= response.status_code < 400:
            raise BridgeError("桥端返回了跳转，请直接填写最终服务地址")
        try:
            if len(response.content) > 4 * 1024 * 1024:
                raise ValueError
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError) as exc:
            raise BridgeError(
                "桥端响应格式异常，地址可能指向了 AstrBot 或其他服务"
            ) from exc
        if response.is_error or data.get("ok") is not True:
            message = data.get("error")
            safe = (
                message[:300]
                if isinstance(message, str)
                else f"桥端请求失败（HTTP {response.status_code}）"
            )
            raise BridgeError(safe, response.status_code if response.is_error else 502)
        return data


def fresh_section_ages(view: dict, stale_seconds: int) -> dict:
    """Unknown ages are unavailable; old bridges may supply a whole-frame age."""
    if not isinstance(view, dict) or not isinstance(view.get("state"), dict):
        return {}
    ages = view.get("section_age_seconds")
    has_section_ages = isinstance(ages, dict) and bool(ages)
    frame_age = view.get("age_seconds")
    result = {}
    for key, value in view["state"].items():
        age = ages.get(key) if has_section_ages else frame_age
        if (isinstance(value, dict) and type(age) in (int, float)
                and 0 <= age <= stale_seconds and math.isfinite(age)):
            result[key] = float(age)
    return result


def fresh_facts(view: dict, stale_seconds: int) -> dict:
    ages = fresh_section_ages(view, stale_seconds)
    if not ages:
        return {}
    return {
        k: v
        for k, v in view.get("state", {}).items()
        if k in ages
    }


def describe_state(view: dict, stale_seconds: int) -> str:
    facts = fresh_facts(view, stale_seconds)
    if not facts:
        return "手机状态已过期，目前无法判断手机的实时情况。"
    parts = []
    battery = facts.get("battery", {})
    if "level" in battery:
        charging = "，充电中" if battery.get("charging") is True else ""
        parts.append(f"电量 {battery['level']}%{charging}")
    temp = battery.get("temperature_c", facts.get("device", {}).get("battery_temp_c"))
    if temp is not None:
        parts.append(f"手机温度 {temp}℃")
    screen = facts.get("screen", {})
    if "on" in screen:
        parts.append("屏幕亮着" if screen["on"] else "屏幕熄灭")
    if "locked" in screen:
        parts.append("已锁屏" if screen["locked"] else "未锁屏")
    net = facts.get("network", {})
    if net.get("type"):
        parts.append("网络 " + str(net["type"]))
    app = facts.get("app", {})
    if app.get("foreground_label") or app.get("foreground_package"):
        parts.append(
            "最近上报的前台应用："
            + str(app.get("foreground_label") or app["foreground_package"])
        )
    audio = facts.get("audio", {})
    if audio.get("media_active") is True and audio.get("media_title"):
        parts.append("正在播放：" + str(audio["media_title"]))
    if "steps_today" in facts.get("activity", {}):
        parts.append(f"今日已上报步数 {facts['activity']['steps_today']}")
    return "；".join(parts) if parts else "部分手机数据是新鲜的，暂无可描述字段。"
