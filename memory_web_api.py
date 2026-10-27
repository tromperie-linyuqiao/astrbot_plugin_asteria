"""Authenticated administration of the independent native memory store.

AstrBot owns authentication and the plugin-extension permission boundary. These
handlers only use its injected ``request.username``; no credential in a body,
query or custom header can grant access. An administrator can manage a complete
historical private scope. This is deliberately separate from the live chat
identity lease used to authorize automatic recall and writes.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
from typing import Any

from astrbot.api.web import error_response, json_response, request

from .core.living.native_memory import MemoryConflict
from .core.living.models import canonical


PAGE_API_PREFIX = "/astrbot_plugin_virtual_body/page/memory"
SCOPE_FIELDS = ("platform", "bot_id", "user_id", "character_id", "session_id")
_READS = {"scopes", "stats", "list", "search", "detail", "request"}
_KINDS = {"real_observation", "user_reported", "model_inference", "roleplay_event", "action_result"}


class _InvalidRequest(ValueError):
    pass


class _Unavailable(RuntimeError):
    pass


def _text(value: Any, label: str, maximum: int, *, blank: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise _InvalidRequest(f"{label} 必须是长度不超过 {maximum} 的文本")
    if not blank and not value.strip():
        raise _InvalidRequest(f"{label} 不能为空")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _InvalidRequest(f"{label} 必须是 {minimum}–{maximum} 的整数")
    return value


def _scope(data: Any) -> dict:
    if not isinstance(data, dict):
        raise _InvalidRequest("必须明确指定五项完整 scope")
    if set(data) - set(SCOPE_FIELDS) - {"private"}:
        raise _InvalidRequest("scope 含未知字段")
    if data.get("private", True) is not True:
        raise _InvalidRequest("本页仅管理私聊 scope")
    result = {}
    for key in SCOPE_FIELDS:
        value = _text(data.get(key), f"scope.{key}", 256)
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise _InvalidRequest(f"scope.{key} 不能包含首尾空白或控制字符")
        result[key] = value
    return {**result, "private": True}


def _request_identity(scope: dict, value: Any) -> tuple[str, str, str]:
    request_id = _text(value, "request_id", 128)
    if request_id != request_id.strip() or any(ord(char) < 32 for char in request_id):
        raise _InvalidRequest("request_id 不能含首尾空白或控制字符")
    digest = hashlib.sha256(canonical(["tls.webui.memory.request.v1", scope, request_id]).encode("utf8")).hexdigest()
    return request_id, "mem_webui_" + digest, "webui.memory." + digest


class NativeMemoryWebApi:
    """Scope catalog for admins; every record operation requires full scope."""

    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        for name in ("scopes", "stats", "list", "search", "detail", "request", "add", "correct", "delete", "restore"):
            register(PAGE_API_PREFIX + "/" + name, getattr(self, "memory_" + name),
                     ["GET" if name in _READS else "POST"],
                     "Native memory authenticated administrator " + name)

    def _adapter(self):
        presence = getattr(self.plugin, "_presence", None)
        host = getattr(presence, "living_host", None)
        runtime = getattr(host, "runtime", None)
        adapter = getattr(runtime, "memory", None)
        if (getattr(adapter, "backend", None) != "native"
                or getattr(adapter, "active", False) is not True
                or getattr(adapter, "store", None) is None):
            raise _Unavailable("native memory disabled or unavailable")
        return adapter

    @staticmethod
    def _operation(name: str, data: dict):
        if name == "restore" and (set(data) != {"scope", "id", "expected_revision"}
                                  or type(data.get("expected_revision")) is not int):
            raise _InvalidRequest("恢复仅接受完整 scope、id 与整数 expected_revision")
        if name == "scopes":
            limit = _integer(data.get("limit", 100), "limit", 1, 100)
            return None, "scopes", (), {"limit": limit}, "scopes"
        scope = _scope({key: data.get(key) for key in SCOPE_FIELDS}
                       if name in _READS else data.get("scope"))
        if name == "stats":
            return scope, "stats", (), {}, "stats"
        if name == "list":
            limit = _integer(data.get("limit", 50), "limit", 1, 100)
            offset = _integer(data.get("offset", 0), "offset", 0, 1000000)
            deleted = data.get("include_deleted", False)
            if name in _READS and isinstance(deleted, str) and deleted in {"true", "false"}:
                deleted = deleted == "true"
            if not isinstance(deleted, bool):
                raise _InvalidRequest("include_deleted 必须为布尔值")
            return scope, "list", (), {"limit": limit, "offset": offset,
                                        "include_deleted": deleted}, "records"
        if name == "search":
            query = _text(data.get("q"), "检索内容", 512)
            limit = _integer(data.get("limit", 8), "limit", 1, 50)
            return scope, "search", (query,), {"limit": limit}, "records"
        if name in {"request", "detail"}:
            identity = (_request_identity(scope, data.get("request_id"))[1] if name == "request"
                        else _text(data.get("id"), "记忆 ID", 256))
            # Administrator-only readback includes a subsequently archived
            # original request. It does not restore or repeat that operation.
            return scope, "get", (identity,), {"include_deleted": True}, "record"
        content = None
        if name in {"add", "correct"}:
            content = _text(data.get("content"), "记忆内容", 6000)
        if name == "add":
            kind = data.get("evidence_kind", "user_reported")
            if not isinstance(kind, str) or kind not in _KINDS:
                raise _InvalidRequest("evidence_kind 无效")
            memory_type = _text(data.get("memory_type", "fact"), "memory_type", 64)
            # The source is server-owned: manual entries cannot impersonate an
            # automatic collector or a migrated legacy record.
            options = {"source_id": "webui.admin",
                "evidence_kind": kind, "memory_type": memory_type,
                "metadata": {"admin_action": "manual_add"}}
            if "request_id" in data:
                request_id, identity, event_id = _request_identity(scope, data["request_id"])
                options.update(record_id=identity, event_id=event_id)
                options["metadata"]["request_id"] = request_id
            return scope, "write", (content,), options, "record"
        record_id = _text(data.get("id"), "记忆 ID", 256)
        revision = _integer(data.get("expected_revision"), "expected_revision", 1, 2147483647)
        if name == "correct":
            return scope, "correct", (record_id, content), {"expected_revision": revision}, "record"
        if name == "restore":
            return scope, "restore", (record_id,), {"expected_revision": revision}, "record"
        return scope, "delete", (record_id,), {"expected_revision": revision}, "record"

    def _restore_resources(self):
        presence = getattr(self.plugin, "_presence", None)
        host = getattr(presence, "living_host", None)
        runtime = getattr(host, "runtime", None)
        adapter = self._adapter()
        return presence, host, runtime, adapter, adapter.store

    async def _respond(self, name: str):
        try:
            username = getattr(request, "username", None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response("需要通过 AstrBot 管理后台认证", status_code=401)
        try:
            adapter = self._adapter()
            restore_resources = self._restore_resources() if name == "restore" else None
            if name in _READS:
                query = getattr(request, "query", None)
                keys = (*SCOPE_FIELDS, "q", "limit", "offset", "include_deleted", "id", "request_id")
                data = {key: query.get(key) for key in keys
                        if query is not None and query.get(key) is not None}
            else:
                data = await request.json(default=None)
                if not isinstance(data, dict):
                    raise _InvalidRequest("请求正文必须是 JSON 对象")
            scope, method, args, kwargs, result_key = self._operation(name, data)
            # Presence identity/authority callbacks belong to the event loop.
            # Database work below must never enumerate its mutable session LRU.
            presence_api = None
            live_scopes = []
            if name == "scopes":
                presence_api = getattr(getattr(self.plugin, "_presence", None), "api", None)
                known = getattr(presence_api, "known_private_scopes", None)
                allowed = getattr(adapter, "allowed", None)
                if callable(known) and callable(allowed):
                    # Session lookup touches the existing LRU. Validate oldest
                    # first so catalog reads do not reverse recent-inbound order.
                    for candidate in reversed(known(limit=100)):
                        try:
                            candidate = _scope(candidate)
                            if allowed(candidate) is True:
                                live_scopes.append(candidate)
                        except (ValueError, RuntimeError):
                            continue
                    live_scopes.reverse()

            def operate():
                # Recheck before worker I/O in case a configuration reload has
                # replaced or disabled the adapter while awaiting a body.
                if self._adapter() is not adapter:
                    raise _Unavailable("native memory changed")
                if name == "restore":
                    def check_restore():
                        if any(old is not new for old, new in zip(restore_resources, self._restore_resources())):
                            raise _Unavailable("native memory restore runtime changed")
                    # Historical scope management retains its existing admin
                    # boundary. A concurrent reload cannot restore through an
                    # old host/adapter or commit after an identity replacement.
                    with restore_resources[-1].transaction():
                        check_restore()
                        value = restore_resources[-1].restore(scope, *args, **kwargs)
                        check_restore()
                        return value
                if name == "scopes":
                    return adapter.store.scopes(**kwargs)
                return getattr(adapter.store, method)(scope, *args, **kwargs)

            result = await asyncio.to_thread(operate)
            if name in {"request", "detail"} and result is None:
                raise KeyError("native memory absent")
            if name == "restore" and any(old is not new for old, new in zip(restore_resources, self._restore_resources())):
                raise _Unavailable("native memory restore runtime changed")
            if name == "scopes":
                if self._adapter() is not adapter:
                    raise _Unavailable("native memory changed")
                # Recheck live authority after the await. Historical database
                # scopes remain an administrator catalog even without a live
                # chat lease; do not silently apply the chat ACL to them.
                same_presence = (getattr(getattr(self.plugin, "_presence", None), "api", None)
                                 is presence_api)
                merged, seen = [], set()
                for candidate in reversed(live_scopes):
                    try:
                        if (not same_presence
                                or presence_api.scope_for_session(candidate["session_id"]) != candidate
                                or adapter.allowed(candidate) is not True):
                            continue
                    except (ValueError, RuntimeError):
                        continue
                    identity = tuple(candidate[key] for key in SCOPE_FIELDS)
                    if identity not in seen:
                        merged.append(candidate)
                        seen.add(identity)
                merged.reverse()
                for candidate in result:
                    identity = tuple(candidate[key] for key in SCOPE_FIELDS)
                    if identity not in seen:
                        merged.append(candidate)
                        seen.add(identity)
                result = merged[:kwargs["limit"]]
            return json_response({"ok": True, "backend": "native", "scope": scope,
                "access": "authenticated_administrator", result_key: result,
                "retrieval": {"mode": "local_keyword", "default_limit": 8,
                              "note": "仅当前完整 scope；关键词检索，不保证语义召回"}},
                headers={"Cache-Control": "no-store"})
        except _InvalidRequest as exc:
            return error_response(str(exc), status_code=400)
        except MemoryConflict:
            return error_response("记录已被其他操作修改，请刷新后重试", status_code=409)
        except KeyError:
            return error_response("当前数据范围中找不到该记忆", status_code=404)
        except ValueError:
            return error_response("记忆参数无效，请检查内容、类型和版本", status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response("原生记忆未启用或暂不可用，请检查存在层与记忆配置", status_code=503)
        except Exception:
            # Database paths, configuration values and record contents must not
            # be exposed in diagnostics returned to the browser.
            return error_response("原生记忆操作失败，请稍后重试", status_code=500)

    async def memory_stats(self):
        return await self._respond("stats")

    async def memory_scopes(self):
        return await self._respond("scopes")

    async def memory_list(self):
        return await self._respond("list")

    async def memory_search(self):
        return await self._respond("search")

    async def memory_add(self):
        return await self._respond("add")

    async def memory_detail(self):
        return await self._respond("detail")

    async def memory_request(self):
        return await self._respond("request")

    async def memory_correct(self):
        return await self._respond("correct")

    async def memory_delete(self):
        return await self._respond("delete")

    async def memory_restore(self):
        return await self._respond("restore")
