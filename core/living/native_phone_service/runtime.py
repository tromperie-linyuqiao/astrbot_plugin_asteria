# -*- coding: utf-8 -*-
"""astrbot_plugin_phone_perception — 手机感知桥插件。

从 Phone Perception Bridge（FastAPI）拉取用户手机实时状态，
以紧凑中文行注入主用户私聊的 LLM 请求，并提供主动查询工具。

安全与隐私：
- 默认 enable_phone_perception=false；不配置不注入。
- 仅白名单用户（allowed_user_ids）的私聊生效。
- v1 不采集位置与通知内容（桥侧白名单已硬性拦截）。
- 任何桥接失败都静默降级，绝不拖垮对话主流程。
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context

from .formatter import (
    detect_mood,
    mood_context,
    CARE_LINES,
    entered_now,
    proactive_gate,
    DEFAULT_APP_GREETINGS,
    _care_line,
    apply_note,
    build_injection_hint,
    injection_reasons,
    offline_decision,
    care_decisions,
    daily_digest,
    format_error,
    format_perception,
    format_stale_notice,
    greeting_allowed,
    history_summary,
    merge_greeting_rules,
    pick_greeting,
    sedentary_decision,
    sleep_summary,
)
from ..native_phone_flow.runtime import NativePhoneFlow
from ..native_phone_flow.config import ConfigSection
from .perception_client import PerceptionClient
from .context_aggregator import ContextAggregator, wrap_music_fragment
from .music_context import MusicContextProvider, choose_music_views, build_music_event, MUSIC_CONTEXT_MARKER, MUSIC_CONTEXT_END
from .music_index import MusicIndex
from .presence_adapter import PhonePresenceAdapter
try:
    from astrbot.core.agent.message import TextPart
except ImportError:
    TextPart = None
from .ppb_client import BridgeClient, BridgeError, fresh_section_ages, validate_settings
from .web_compat import body_json, error_response, json_response, query_args

PLUGIN_NAME = "astrbot_plugin_virtual_body"
PHONE_API_PREFIX = "/astrbot_plugin_virtual_body/phone-integration"

INJECTION_BLOCK_TITLE = "## 她的手机此刻（背景情报，别照着念）"
INJECTION_HINT = "（以上是用户手机的桥接实时数据，可信。可以在对话里自然地化用，但不要机械播报或罗列字段，也不要因此打断正在说的正事。）"


class NativePhoneService:
    # Retain the old implementation and diary data, but RP no longer gets automatic daily summaries.
    AUTO_DAILY_SUMMARY = False

    def __init__(self, context: Context, config: AstrBotConfig, *, data_dir, flow_store_path, authorize_session,
                 config_write_lock=None):
        if not callable(authorize_session):
            raise ValueError("explicit existing-session authorization required")
        self.context = context
        self._active = False
        self._authorize_session = authorize_session
        self._data_dir = Path(data_dir)
        self.config = config
        # WebUI data client (merged from ppb)
        self._web_client = BridgeClient(config)
        self._web_save_lock = asyncio.Lock()
        self._config_write_lock = config_write_lock if config_write_lock is not None else threading.RLock()
        self.dialogue_flow = NativePhoneFlow(context,
            ConfigSection(config, key="dialogue_flow", write_lock=self._config_write_lock),
            self._web_save_lock, store_path=flow_store_path,
            authorize_session=self._session_allowed, register_routes=False,
            manual_quiet_key="phone_respect_manual_quiet")

        self.client = PerceptionClient(
            base_url=str(config.get("bridge_base_url", "") or ""),
            token=str(config.get("bridge_token", "") or ""),
            timeout=float(config.get("timeout_seconds", 4) or 4),
            cache_ttl=8.0,
            device_id=str(config.get("device_id", "phone") or "phone"),
        )
        self._last_inject_at: dict[str, float] = {}
        self._last_activity_at: dict[str, float] = {}
        self._notify_origins: dict[str, str] = {}
        self._playlist_cache = None
        self._playlist_mtime = 0.0
        self._playlist_bridge_cache = None
        self._playlist_bridge_at = 0.0
        self._playlist_lock = asyncio.Lock()
        self._surprises_cache = None
        self._surprises_at = 0.0
        self._last_proactive_at: dict[str, float] = {}
        self._photo_counts: dict[str, dict] = {}
        self._mood_history: dict[str, list[tuple]] = {}
        self._night_counts: dict[str, int] = {}
        self._steps_seen: dict[str, tuple] = {}
        self._last_inject_line: dict[str, str] = {}
        self._same_line_count: dict[str, int] = {}
        self._recent_topics: dict[str, list[tuple]] = {}
        self._care_texts: dict[str, dict] = {}
        self._broken_origins: dict[str, float] = {}  # origin -> timestamp（>7天清理）
        self._bridge_fail_until = 0.0
        self._bridge_down = False
        self._bridge_down_logged_at = 0.0
        # 先建齐所有字典，再加载落盘状态（顺序错误曾让持久化每次启动即失效）
        self._care_last: dict[str, dict] = {}
        self._greet_last_pkg: dict[str, str] = {}
        self._greet_last_at: dict[str, float] = {}
        self._greet_recent: dict[str, list[str]] = {}
        self._state_save_at = 0.0
        _data_dir = self._data_dir
        # 句柄只在拿不到数据目录时才为 None；文件缺失是正常首启，不废持久化
        self._state_file = (_data_dir / "state.json") if _data_dir else None
        self._music_index = MusicIndex((_data_dir / "music" / "music_index.json") if _data_dir else None)
        self._music_provider = MusicContextProvider(self._music_index, ttl_seconds=180)
        self._context_aggregator = ContextAggregator()
        self._context_aggregator.register("music", self._music_provider)
        self._music_stopping = False
        self._music_scope = None
        self._music_selected_by_user = {}
        self._music_last_events = {}
        self._music_metrics = {"injections": 0, "timeouts": 0, "errors": 0, "last_event_type": "music_unknown"}
        self._presence_adapter = PhonePresenceAdapter(self)
        self._origin_file = (_data_dir / "origins.json") if _data_dir else None
        self.reload_persisted_state()
        self._care_task = None
        self._greet_task = None

    def reload_persisted_state(self):
        """Inactive-only final read after the old owner has saved its state.

        Read/validate both documents before changing RAM. Missing files are a
        genuine first-start condition; malformed existing data blocks adoption.
        No cold-start reset, file deletion or state rewrite is performed here.
        """
        if self._active:
            raise RuntimeError('persisted state reload must precede activation')
        documents = []
        for path in (self._state_file,self._origin_file):
            if path is None or not path.exists():
                documents.append(None)
                continue
            if path.stat().st_size>8*1024*1024:
                raise ValueError('phone state capacity exceeded')
            document = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(document,dict):
                raise ValueError('phone state must be an object')
            documents.append(document)
        state_document,origin_document = documents
        if state_document is not None:
            for name in ('_care_last','_last_proactive_at','_last_activity_at','_greet_last_at',
                         '_greet_last_pkg','_night_counts','_photo_counts','_care_texts',
                         '_steps_seen','_greet_recent'):
                getattr(self,name).clear()
        if state_document is not None:
            saved = state_document
            if isinstance(saved, dict):
                def _map(name, target):
                    try:
                        target.update(saved.get(name) or {})
                    except Exception:
                        logger.warning(f"[{PLUGIN_NAME}] state.json 的 {name} 段损坏，已跳过")

                _map("care_last", self._care_last)
                for name, target in (("last_proactive_at", self._last_proactive_at), ("last_activity_at", self._last_activity_at)):
                    values = saved.get(name, {})
                    if isinstance(values, dict):
                        for key, value in values.items():
                            if type(value) not in (int, float):
                                continue
                            try:
                                stamp = float(value)
                            except (ValueError, OverflowError):
                                continue
                            if math.isfinite(stamp) and 0 <= stamp <= time.time():
                                target[str(key)] = stamp
                _map("greet_last_at", self._greet_last_at)
                _map("greet_last_pkg", self._greet_last_pkg)
                _map("night_counts", self._night_counts)
                for k, v in (saved.get("photo_counts") or {}).items():
                    try:
                        self._photo_counts[k] = {"date": str(v.get("date")), "count": int(v.get("count", 0))}
                    except Exception:
                        pass
                for k, v in (saved.get("care_texts") or {}).items():
                    try:
                        self._care_texts[k] = {str(k2): str(v2) for k2, v2 in v.items()}
                    except Exception:
                        pass
                for k, v in (saved.get("steps_seen") or {}).items():
                    try:
                        self._steps_seen[k] = (v[0], v[1])
                    except Exception:
                        pass
                for k, v in (saved.get("greet_recent") or {}).items():
                    try:
                        self._greet_recent[k] = [str(x) for x in v][:3]
                    except Exception:
                        pass
        if origin_document is not None:
            self._notify_origins = {str(k):str(v) for k,v in origin_document.items()}
        return {"state_present":state_document is not None,"origins_present":origin_document is not None,
                "care_users":len(self._care_last),"origins":len(self._notify_origins)}

    def _session_allowed(self, umo):
        try:
            return self._active and self._authorize_session(umo) is True
        except Exception:
            return False

    def activate(self, *, start_tasks=True):
        """Host calls only after retiring old hooks/tasks/providers.

        The deployment gate proves the old owner is drained. Construction never
        starts a second collector and never adopts old live plugin methods.
        """
        if type(start_tasks) is not bool:
            raise ValueError("explicit background-start flag required")
        if self._music_stopping:
            return False
        if self._active:
            return True
        self._active = True
        if not self._presence_adapter.ensure_registered():
            self._active = False
            return False
        if start_tasks:
            loop = asyncio.get_running_loop()
            self._care_task = loop.create_task(self._care_loop())
            self._greet_task = loop.create_task(self._greeting_loop())
        return True

    def adopt_music_continuity(self, streams, last_events=None):
        if self._active:
            raise RuntimeError("continuity transfer must precede activation")
        from ..models import plain
        events = {} if last_events is None else plain(last_events,524288)
        if (not isinstance(events,dict) or len(events)>128
                or any(not isinstance(key,str) or not key or len(key)>256
                       or not isinstance(value,dict) for key,value in events.items())):
            raise ValueError("bounded user music-event mapping required")
        result = self._music_provider.adopt_continuity(streams)
        self._music_last_events = events
        return dict(result,last_events=len(events))

    def adopt_context_continuity(self, values):
        """Adopt only old Phone's three typed repeated-context RAM maps.

        The controller copies these data fields before awaiting old shutdown.
        This does not call an old object, create a scope, touch a file or grant
        delivery authority. Validate every field before changing any live map.
        Other state/care/origins are still read from their final persisted files.
        """
        if self._active:
            raise RuntimeError("context continuity transfer must precede activation")
        names = ("_last_inject_at", "_last_inject_line", "_same_line_count")
        if type(values) is not dict or set(values) != set(names):
            raise ValueError("exact repeated-context maps required")
        copied = {};total_bytes = 0
        for name in names:
            mapping = values[name]
            if type(mapping) is not dict or len(mapping) > 4096:
                raise ValueError("bounded repeated-context map required")
            clean = {}
            for key, value in mapping.items():
                if type(key) is not str or not key or len(key) > 256:
                    raise ValueError("bounded sender identifier required")
                total_bytes += len(key.encode("utf-8")) + 32
                if name == "_last_inject_at":
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError("finite nonnegative injection timestamp required")
                elif name == "_last_inject_line":
                    if type(value) is not str or len(value) > 1048576:
                        raise ValueError("bounded injection signature required")
                    total_bytes += len(value.encode("utf-8"))
                elif type(value) is not int or not 0 <= value <= 9223372036854775807:
                    raise ValueError("nonnegative repeat count required")
                if total_bytes > 8388608:
                    raise ValueError("context continuity exceeds byte budget")
                clean[key] = value
            copied[name] = clean
        # Inputs contain only immutable primitives; each mapping is a fresh copy.
        self._last_inject_at = copied["_last_inject_at"]
        self._last_inject_line = copied["_last_inject_line"]
        self._same_line_count = copied["_same_line_count"]
        return {"maps": 3, "entries": sum(len(value) for value in copied.values())}

    def diagnostics(self):
        adapter = self._presence_adapter
        return {'active':self._active,'owns_native_phone_business':True,
                'collection_protocol':'existing_ppb',
                'care_task_active':self._care_task is not None and not self._care_task.done(),
                'greeting_task_active':self._greet_task is not None and not self._greet_task.done(),
                'music_streams':len(self._music_provider._streams),
                'music_last_events':len(self._music_last_events),
                'presence_registered':adapter.api is not None and not adapter.closed
                    and adapter.api is getattr(self.context,'presence_layer',None),
                'flow':self.dialogue_flow._runtime()}

    def register_routes(self):
        self._register_web_routes(self.context)
        self.dialogue_flow.register_routes()

    async def command_greeting_test(self, event: AstrMessageEvent):
        """当场验证主动消息发送链路：会单独给你私聊发一条彩蛋文案。"""
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        sender = self._sender_id(event)
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if not origin:
            yield event.plain_result("没有会话上下文，无法测试。")
            return
        rules = merge_greeting_rules(
            DEFAULT_APP_GREETINGS, list(self.config.get("app_greeting_custom", []) or [])
        )
        pool = rules.get("tv.danmaku.bili") or [m for msgs in rules.values() for m in msgs]
        text = pick_greeting(pool)
        ok = await self._send_private(origin, text)
        if ok:
            self._notify_origins.setdefault(sender, origin)
            if self._notify_origins.get(sender) != origin:
                self._notify_origins[sender] = origin
                self._save_origins()
            yield event.plain_result(f"已发送测试彩蛋（{text}）。没收到的话告诉我。")
        else:
            yield event.plain_result("发送失败，看服务器日志排查。")

    # ---- 歌单备注与重灌 ----

    async def playlist_annotate(self, event: AstrMessageEvent, song: str, note: str) -> str:
        """给歌单里的一首歌写下你们之间的备注（她可以自己维护共同记忆）。

        当聊天中某首歌被提起、且值得留下记忆点时调用；用户主动说"把这首歌记下来"时必须调用。

        Args:
            song(string): 歌名。
            note(string): 一句话备注，例如你们的回忆点或这首歌对你的意义。
        """
        if not self._authorized(event):
            return "仅白名单用户可以在私聊中使用手机感知。"
        if not getattr(self, "_origin_file", None):
            return "数据目录不可用，写不了。"
        try:
            self._sync_client()
            async with self._playlist_lock:
                current = await self.client.get_playlist_bridge()
                if current is None:
                    return "桥端歌单读取失败，未改动歌单，请检查连接后重试。"
                updated = apply_note(current, song, note)
                if not await self.client.put_playlist_bridge(updated):
                    return "桥端歌单保存失败，备注未写入，请检查连接后重试。"
                self._remember_playlist(updated)
            return f"已记下：《{song.strip()[:40]}》——{note.strip()[:60]}"
        except Exception as exc:
            return f"写入失败：{exc}"

    async def command_resync_playlist(self, event: AstrMessageEvent):
        """从知识库音乐库重新抽取歌单到 playlist.json（手写备注保留）。"""
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        try:
            count = await self._resync_playlist_from_kb()
            yield event.plain_result(f"歌单重灌完成：共 {count} 首（手写备注已保留）。")
        except Exception as exc:
            yield event.plain_result(f"重灌失败：{exc}")

    async def _resync_playlist_from_kb(self) -> int:
        import re as _re
        import sqlite3 as _sq

        kb = _sq.connect("/AstrBot/data/knowledge_base/kb.db")
        docs = kb.execute(
            "SELECT doc_id, doc_name FROM kb_documents WHERE doc_name LIKE '歌曲_%'"
        ).fetchall()
        kb.close()
        doc_cat = {}
        for doc_id, name in docs:
            m = _re.match(r"歌曲_(.+?)_第", name)
            doc_cat[doc_id] = m.group(1) if m else "其他"
        playlist: dict = {}
        row_re = _re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|")
        for kb_dir in Path("/AstrBot/data/knowledge_base").iterdir():
            doc_db = kb_dir / "doc.db"
            if not doc_db.exists():
                continue
            d = _sq.connect(str(doc_db))
            try:
                rows = d.execute("SELECT text, metadata FROM documents").fetchall()
            except Exception:
                d.close()
                continue
            d.close()
            for text, meta in rows:
                try:
                    kd = json.loads(meta or "{}").get("kb_doc_id")
                except Exception:
                    continue
                if kd not in doc_cat:
                    continue
                note = "方舟曲" if "明日方舟" in doc_cat[kd] else ""
                for line in (text or "").splitlines():
                    mm = row_re.match(line.strip())
                    if mm:
                        song = mm.group(1).strip()
                        if song and song != "歌曲名" and len(song) < 60:
                            playlist.setdefault(song, note)
        path = self._origin_file.parent / "playlist.json"
        import shutil as _sh

        if path.exists():
            _sh.copy2(path, path.with_suffix(".json.bak"))  # 重灌前备份，手写备注永不丢
        self._sync_client()
        async with self._playlist_lock:
            old = await self.client.get_playlist_bridge()
            if old is None:
                raise RuntimeError("桥端歌单读取失败，未覆盖现有歌单，请检查连接后重试")
            merged = dict(playlist)
            for k, v in old.items():
                if v and v != "方舟曲":
                    merged[k] = v  # 手写备注优先（方舟曲备注允许被分类刷新）
            if not await self.client.put_playlist_bridge(merged):
                raise RuntimeError("桥端歌单保存失败，未覆盖现有歌单，请检查连接后重试")
            self._remember_playlist(merged)
        return len(merged)

    # ---- 感知令牌轮换 ----

    async def command_rotate_token(self, event: AstrMessageEvent):
        """轮换感知桥令牌：桥和插件都换新，随后需要把新令牌填到手机 App。"""
        if not self._is_private(event):
            yield event.plain_result("请在私聊中使用此命令（涉及令牌安全）。")
            return
        sender = self._sender_id(event)
        if not sender or sender not in self._allowed_users():
            yield event.plain_result("只有白名单用户可以重置令牌。")
            return
        self._sync_client()
        if not self.client.configured:
            yield event.plain_result("桥未配置。")
            return
        result = await self.client.rotate_token()
        if not result.get("ok"):
            yield event.plain_result(f"轮换失败：{result.get('error', '未知')}")
            return
        new_token = str(result.get("token", "")).strip()
        if not new_token:
            yield event.plain_result("桥没有返回新令牌。")
            return
        try:
            self.config["bridge_token"] = new_token
            self._save_config()
        except Exception as exc:
            yield event.plain_result(f"桥已换令牌但插件配置写入失败：{exc}（请手动在 WebUI 填写新令牌）")
            return
        self.client.invalidate()
        yield event.plain_result(
            "令牌已轮换（桥+插件均已更新）。请把新令牌复制到每台手机的感知App里重新保存：\n" + new_token
        )

    async def command_reload(self, event: AstrMessageEvent):
        """免重启热重载：重新读歌单/客户端配置，清空状态缓存。"""
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        self._playlist_mtime = 0.0
        self._playlist_bridge_at = 0.0
        self.client.invalidate()
        self._sync_client()
        playlist = await self._playlist_async()
        rules = merge_greeting_rules(
            DEFAULT_APP_GREETINGS, list(self.config.get("app_greeting_custom", []) or [])
        )
        yield event.plain_result(
            f"已重载：歌单 {len(playlist) if isinstance(playlist, dict) else (len(playlist) if playlist else 0)} 首、"
            f"彩蛋覆盖 {sum(len(v) for v in rules.values())} 条、设备 {self._devices()}。配置改动即时生效。"
        )

    async def command_client_config(self, event: AstrMessageEvent, *args):
        """查看/修改客户端远程配置（手机App自动应用，免装新包）。用法：感知客户端配置 [键 值]"""
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        self._sync_client()
        data = await self.client.get_client_config()
        if not isinstance(data, dict) or not data.get("ok"):
            yield event.plain_result(format_error(str((data or {}).get("error", "未知原因"))))
            return
        cfg = data.get("config") or {}
        argv = [str(a) for a in args if str(a).strip()]
        if len(argv) >= 2:
            key, value = argv[0], argv[1]
            if key not in cfg:
                yield event.plain_result(f"没有这个配置项：{key}")
                return
            parsed = value
            if type(cfg[key]) is bool:
                if value.lower() not in {"true", "false", "1", "0", "on", "off"}:
                    yield event.plain_result("值应为 true 或 false")
                    return
                parsed = value.lower() in {"true", "1", "on"}
            elif isinstance(cfg[key], int):
                try:
                    parsed = int(value)
                except ValueError:
                    yield event.plain_result("值必须是整数")
                    return
            elif isinstance(cfg[key], list):
                parsed = [x.strip() for x in value.replace("，", ",").split(",") if x.strip()]
            result = await self.client.set_client_config({key: parsed})
            if result.get("ok"):
                yield event.plain_result(f"已更新 {key} = {result['config'][key]}（手机下次上报时自动应用）")
            else:
                yield event.plain_result(f"更新失败：{result.get('error')}")
            return
        lines = [f"{k} = {v}" for k, v in cfg.items()]
        yield event.plain_result("客户端远程配置（改法：感知客户端配置 键 值）：\n" + "\n".join(lines))

    # ==== WebUI routes & /ppb command (merged from ppb) ====

    def _register_web_routes(self, context) -> None:
        # Register AstrBot plugin page API routes
        routes = [
            ("connection", self._web_connection_get, ["GET"]),
            ("read/music", self._web_music_get, ["GET"]),
            ("flow/phone-policy", self._web_phone_policy_get, ["GET"]),
            ("flow/phone-policy", self._web_phone_policy_save, ["POST"]),
            ("connection/save", self._web_connection_save, ["POST"]),
            ("connection/test", self._web_connection_test, ["POST"]),
        ]
        for resource in (
            "health", "devices", "state", "history", "overview",
            "client-config", "surprises", "playlist", "rules", "effects",
        ):
            routes.append(("read/" + resource, self._web_read(resource), ["GET"]))
        for resource in ("client-config", "surprises", "playlist", "rules"):
            routes.append(("save/" + resource, self._web_save(resource), ["POST"]))
        for path, handler, methods in routes:
            try:
                context.register_web_api(
                    f"{PHONE_API_PREFIX}/{path}", handler, methods,
                    "手机感知桥管理面板"
                )
            except Exception as exc:
                logger.warning(f"[{PLUGIN_NAME}] Web路由注册失败（页面可能不可用）: {exc!r}")

    def _connection_data(self):
        return {
            "bridge_url": self.config.get("bridge_base_url", ""),
            "default_device": self.config.get("device_id", "phone"),
            "timeout_seconds": self.config.get("timeout_seconds", 4),
            "token_configured": bool(self.config.get("bridge_token")),
            "configured_devices": self._devices(),
            "perception_enabled": self._enabled(),
            "allowed_user_count": len(self._allowed_users()),
            "show_app": bool(self.config.get("show_app", False)),
            "stale_seconds": self._stale_seconds(),
            "auto_daily_summary_enabled": False,
            "music": self._music_diagnostics(),
            "phone_respect_manual_quiet": bool(self.config.get("phone_respect_manual_quiet", False)),
        }

    def _web_connection_get(self):
        return json_response({"ok": True, "connection": self._connection_data()})

    async def _web_connection_save(self):
        try:
            patch = await body_json()
            async with self._web_save_lock:
                if not isinstance(patch, dict):
                    raise ValueError("设置必须是对象")
                # 兼容旧后台字段，页面字段映射到现役插件配置；令牌空值保留。
                aliases = {"bridge_base_url": "bridge_url", "device_id": "default_device"}
                patch = {aliases.get(k, k): v for k, v in patch.items()}
                allowed = {"bridge_url", "bridge_token", "default_device", "timeout_seconds"}
                if set(patch) - allowed:
                    raise ValueError("请在插件配置中修改感知白名单与新鲜度")
                current = {**self._connection_data(), "bridge_token": self.config.get("bridge_token", "")}
                settings = validate_settings(patch, current)
                mapping = {"bridge_url": "bridge_base_url", "default_device": "device_id",
                           "bridge_token": "bridge_token", "timeout_seconds": "timeout_seconds"}
                previous = {key: self.config.get(key) for key in mapping.values()}
                old_devices = self.config.get("device_ids")
                # A single-device default follows this form. Explicit multi-device
                # lists remain under the plugin configuration's control.
                sync_devices = ("default_device" in patch and len(self._devices()) == 1)
                for key, target in mapping.items():
                    self.config[target] = settings[key]
                if sync_devices and old_devices:
                    self.config["device_ids"] = [settings["default_device"]]
                try:
                    self._save_config()
                except Exception as exc:
                    for key, value in previous.items():
                        self.config[key] = value
                    if sync_devices and old_devices:
                        self.config["device_ids"] = old_devices
                    logger.warning(f"[{PLUGIN_NAME}] WebUI配置保存失败: {exc!r}")
                    return error_response("配置写入失败，请重试", status_code=500)
                self._sync_client()
                self._playlist_bridge_cache = None
                self._playlist_bridge_at = 0.0
            return json_response({"ok": True, "connection": self._connection_data()})
        except Exception as exc:
            return error_response(str(exc), status_code=400)

    async def _web_connection_test(self):
        try:
            health = await self._web_client.request("GET", "health")
            devices = await self._web_client.request("GET", "devices")
            return json_response({"ok": True, "health": health, "devices": devices.get("devices", [])})
        except BridgeError as exc:
            return error_response(str(exc), status_code=exc.status)

    def _web_read(self, resource):
        async def handler():
            try:
                params = {}
                args = query_args()
                if resource in ("state", "history", "overview", "effects"):
                    params["device"] = args.get("device") or self.config.get("device_id", "phone")
                for key in ("minutes", "limit", "stale_seconds"):
                    if args.get(key) is not None and resource in ("state", "history", "overview"):
                        params[key] = args.get(key)
                if resource == "playlist":
                    async with self._playlist_lock:
                        data = await self._web_client.request("GET", resource, params=params)
                        if isinstance(data.get("playlist"), dict):
                            self._remember_playlist(data["playlist"])
                else:
                    data = await self._web_client.request("GET", resource, params=params)
                return json_response(data)
            except BridgeError as exc:
                return error_response(str(exc), status_code=exc.status)
        return handler

    def _web_save(self, resource):
        async def handler():
            try:
                methods = {"client-config": "POST", "surprises": "PUT", "playlist": "PUT", "rules": "PUT"}
                if resource not in methods:
                    return error_response("不支持的保存操作", status_code=400)
                payload = await body_json()
                if not isinstance(payload, dict):
                    return error_response("保存内容必须为对象", status_code=400)
                if resource == "playlist":
                    async with self._playlist_lock:
                        data = await self._web_client.request(methods[resource], resource, body=payload)
                        self._remember_playlist(data.get("playlist", payload.get("playlist", {})))
                else:
                    data = await self._web_client.request(methods[resource], resource, body=payload)
                return json_response(data)
            except BridgeError as exc:
                return error_response(str(exc), status_code=exc.status)
        return handler

    async def ppb_command(self, event: AstrMessageEvent, action: str = "状态"):
        # /ppb [状态|关怀|设备] admin-only private chat
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        self._sync_client()
        try:
            if action == "设备":
                rows = (await self.client.get_devices()).get("devices", [])
                text = "已上报设备：" + ("、".join(d.get("device_id", "?") for d in rows) or "暂无")
            elif action == "关怀":
                view = await self._freshest_view()
                if view is None:
                    text = "目前没有新鲜数据。"
                else:
                    text = "当前状态：" + format_perception(view[0], age_seconds=view[1], fresh=True, show_app=True)
            else:
                view = await self._freshest_view()
                if view is None:
                    text = "手机还没有上报过数据。"
                else:
                    text = format_perception(view[0], age_seconds=view[1], fresh=True, show_app=True,
                                             playlist=await self._playlist_async())
            yield event.plain_result(text)
        except Exception as exc:
            yield event.plain_result(f"PPB: {str(exc)[:80]}")

    async def terminate(self):
        was_active = self._active
        self._active = False
        self._music_stopping = True
        self._presence_adapter.close()
        self._music_provider.clear()
        self._music_last_events.clear()
        await self.dialogue_flow.terminate()
        try:
            await self._web_client.close()
        except Exception:
            pass
        tasks = [t for t in (self._care_task, self._greet_task) if t is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                pass
        if was_active:
            self._save_state(force=True)
        self.client.invalidate()
        logger.info(f"[{PLUGIN_NAME}] 已终止，状态已落盘")

    def _save_state(self, force: bool = False) -> None:
        """节流保存运行状态（30s 一次），重启不丢冷却/计数。原子写入。"""
        if not getattr(self, "_state_file", None):
            return
        now = time.time()
        if not force and now - self._state_save_at < 30:
            return
        try:
            data = {
                "care_last": self._care_last,
                "last_proactive_at": self._last_proactive_at,
                "last_activity_at": self._last_activity_at,
                "greet_last_at": self._greet_last_at,
                "greet_last_pkg": self._greet_last_pkg,
                "greet_recent": {k: v[-3:] for k, v in self._greet_recent.items()},
                "night_counts": self._night_counts,
                "care_texts": self._care_texts,
                "steps_seen": self._steps_seen,
                "photo_counts": self._photo_counts,
            }
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            import os as _os

            _os.replace(tmp, self._state_file)
            self._state_save_at = now
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] state.json save failed: {exc!r}")

    def _save_origins(self) -> None:
        if not getattr(self, "_origin_file", None):
            return
        try:
            self._origin_file.parent.mkdir(parents=True, exist_ok=True)
            self._origin_file.write_text(
                json.dumps(self._notify_origins, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] origins保存失败: {exc!r}")

    def _targets(self) -> dict[str, str]:
        """主动消息目标：持久化的会话优先；没有记录时按白名单拼私聊地址兜底（坏地址停用）。"""
        targets = {}
        for sender in self._allowed_users():
            stored = self._notify_origins.get(sender)
            now_ts = time.time()
            self._broken_origins = {k: v for k, v in self._broken_origins.items() if now_ts - v < 7 * 86400}
            if stored and stored not in self._broken_origins:
                targets[sender] = stored
                continue
            fallback = f"default:FriendMessage:{sender}"
            if fallback not in self._broken_origins:
                targets[sender] = fallback
        return targets

    # ---- 主动关怀（后台低频检查，默认关闭） ----

    async def _care_loop(self) -> None:
        while True:
            await asyncio.sleep(600)
            try:
                await self._care_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[{PLUGIN_NAME}] care tick 异常: {exc}")

    # ---- 开 App 彩蛋（前台切到关注 App 时主动搭话，话术轮换防复读） ----

    async def _greeting_loop(self) -> None:
        logger.info(f"[{PLUGIN_NAME}] 彩蛋巡检已启动（15s周期）")
        while True:
            await asyncio.sleep(15)
            try:
                await self._greeting_tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[{PLUGIN_NAME}] greeting tick 异常: {exc}")

    async def _greeting_tick(self) -> None:
        if not self._enabled() or not bool(self.config.get("app_greeting_enabled", False)):
            return
        if not self.config.get("show_app", False):
            return  # 没开前台感知就没有 app 段
        self._sync_client()
        if not self.client.configured:
            return
        rules = merge_greeting_rules(
            DEFAULT_APP_GREETINGS, list(self.config.get("app_greeting_custom", []) or [])
        )
        surprises = await self._surprises()
        for pkg, meta in (surprises.get("greetings") or {}).items():
            lines = meta.get("lines") if isinstance(meta, dict) else meta
            if isinstance(lines, list) and lines:
                rules.setdefault(str(pkg), [])
                rules[str(pkg)] = [str(x) for x in lines if str(x).strip()] or rules[str(pkg)]
        cooldown = max(10, int(self.config.get("app_greeting_cooldown_minutes", 120) or 120)) * 60
        now = time.time()
        self._save_state()  # 巡检尾部节流落盘（含 _greet_last_pkg 变化）
        for sender, origin in self._targets().items():
            for dev in self._devices():
                data = await self.client.get_state(self._stale_seconds(), device=dev)
                view = self._fresh_view(data)
                if view is None:
                    continue
                app = view[0].get("app") or {}
                app_age = (data.get("section_age_seconds") or {}).get("app")
                pkg = str(app.get("foreground_package") or "")
                lkey = f"{sender}:{dev}"
                if not pkg or pkg not in rules:
                    self._greet_last_pkg[lkey] = pkg
                    continue
                if not greeting_allowed(pkg, datetime.now().hour):
                    self._greet_last_pkg[lkey] = pkg
                    continue
                first_seen = self._greet_last_pkg.get(lkey) is None
                entered = pkg != self._greet_last_pkg.get(lkey)
                self._greet_last_pkg[lkey] = pkg
                if not entered:
                    continue  # 一直停在这个 App 只在进入时搭话
                if first_seen and not entered_now(app_age):
                    continue  # 重启/首见：陈旧段不算刚打开，防幽灵彩蛋重发
                key = f"{sender}:{dev}:{pkg}"
                if now - self._greet_last_at.get(key, -1e9) < cooldown:
                    continue
                recent = self._greet_recent.setdefault(key, [])
                text = pick_greeting(rules[pkg], recent)
                if not text:
                    continue
                if await self._send_private(origin, text, sender=sender):
                    recent.append(text)
                    del recent[:-3]  # 只记最近3条用于防重复
                    self._greet_last_at[key] = now
                    self._save_state()
                    logger.info(f"[{PLUGIN_NAME}] 开App彩蛋已发送: {dev}:{pkg} -> {sender}")

    async def _care_tick(self) -> None:
        if not self._enabled() or not bool(self.config.get("care_enabled", False)):
            return
        self._sync_client()
        if not self.client.configured:
            return
        threshold = int(self.config.get("care_battery_threshold", 20) or 20)
        cooldown = max(30, int(self.config.get("care_cooldown_minutes", 120) or 120)) * 60
        addict_enabled = bool(self.config.get("care_addict_enabled", False))
        addict_minutes = max(5, int(self.config.get("care_addict_minutes", 30) or 30))
        addict_swipe = max(1, int(self.config.get("care_swipe_per_min", 12) or 12))
        addict_pkgs = self._addict_packages()
        digest_hour = int(self.config.get("care_daily_hour", 22) or 22)
        sedentary_on = bool(self.config.get("care_sedentary_enabled", False))
        sedentary_min = max(30, int(self.config.get("care_sedentary_minutes", 120) or 120))
        today = datetime.now().strftime("%Y-%m-%d")
        hour_now = datetime.now().hour
        # 失联感知：全部设备的最新上报年龄（白天超2小时她会主动来问）
        care_overrides = ((await self._surprises()).get("care") or {})
        devices_data = await self.client.get_devices()
        newest_age = None
        if isinstance(devices_data, dict) and devices_data.get("ok"):
            ages = [
                time.time() - float(d.get("updated_at", 0))
                for d in devices_data.get("devices", [])
                if isinstance(d, dict) and d.get("updated_at")
            ]
            if ages:
                newest_age = min(ages)
        for sender, origin in self._targets().items():
            now = time.time()
            sent_keys: set[str] = set()
            for dev in self._devices():
                data = await self.client.get_state(self._stale_seconds(), device=dev)
                view = self._fresh_view(data)
                if view is None:
                    continue
                fresh_state, _ = view
                notes = care_decisions(
                    fresh_state,
                    hour=hour_now,
                    battery_threshold=threshold,
                    last_notified=self._care_last.get(sender, {}),
                    now=now,
                    cooldown_s=cooldown,
                    addict_packages=addict_pkgs if addict_enabled else (),
                    addict_minutes=addict_minutes,
                    swipe_per_min=addict_swipe,
                    last_texts=self._care_texts.get(sender, {}),
                    newest_age_s=None,
                    care_lines=care_overrides or None,
                )
                # 久坐：白天+亮屏+步数长时间没动
                if sedentary_on:
                    skey = f"{sender}:{dev}"
                    activity = fresh_state.get("activity") or {}
                    screen = fresh_state.get("screen") or {}
                    steps = activity.get("steps_today")
                    last = self._steps_seen.get(skey)
                    if sedentary_decision(
                        hour=hour_now,
                        screen_on=screen.get("on") is True,
                        steps=steps,
                        last_steps=last[0] if last else None,
                        last_move_ts=last[1] if last else now,
                        now=now,
                        threshold_minutes=sedentary_min,
                    ) and now - self._care_last.get(sender, {}).get("sedentary", -1e9) >= cooldown:
                        notes.append((
                            "sedentary",
                            _care_line("sedentary", {}, self._care_texts.get(sender, {}).get("sedentary"), override=care_overrides or None),
                        ))
                    if isinstance(steps, (int, float)) and (not last or last[0] != steps):
                        self._steps_seen[skey] = (steps, now)  # 步数变了=动过，重置计时
                for key, text in notes[:1]:
                    if key in sent_keys:
                        continue  # 双机同类提醒只发一次（以第一台命中的文案为准）
                    if await self._send_private(origin, text, sender=sender):
                        sent_keys.add(key)
                        self._care_last.setdefault(sender, {})[key] = now
                        self._care_texts.setdefault(sender, {})[key] = text
                        self._save_state()
                        logger.info(f"[{PLUGIN_NAME}] 主动关怀已发送({key},{dev}) 给 {sender}")

            # 全部状态过期时也能提示失联。保持原有昼间/6小时冷却与发送闸门。
            offline_notes = offline_decision(
                hour=hour_now, newest_age_s=newest_age,
                last_notified=self._care_last.get(sender, {}), now=now,
                last_texts=self._care_texts.get(sender, {}), care_lines=care_overrides or None,
            )
            for key, text in offline_notes:
                if await self._send_private(origin, text, sender=sender):
                    self._care_last.setdefault(sender, {})[key] = now
                    self._care_texts.setdefault(sender, {})[key] = text
                    self._save_state()

            # 晚安日报：每天指定小时推一次今日汇总
            if (
                self.AUTO_DAILY_SUMMARY and bool(self.config.get("care_daily_enabled", False))
                and hour_now >= digest_hour
                and self._care_last.get(sender, {}).get("digest_date") != today
            ):
                samples = await self._primary_history(26 * 60)
                if samples:
                    tail = "晚安。" if digest_hour >= 21 else "今天也辛苦了。"
                    text = "今日手机小结：" + daily_digest(
                        samples, sleep=sleep_summary(samples)
                    ) + tail
                    if await self._send_private(origin, text, sender=sender, bypass_gate=True):
                        self._care_last.setdefault(sender, {})["digest_date"] = today
                        self._save_state()
                        steps_vals = []
                        on_frames = total_frames = 0
                        for s in samples:
                            secs = s.get("sections", {}) if isinstance(s, dict) else {}
                            act = secs.get("activity") if isinstance(secs.get("activity"), dict) else {}
                            if isinstance(act.get("steps_today"), (int, float)):
                                steps_vals.append(int(act["steps_today"]))
                            scr = secs.get("screen") if isinstance(secs.get("screen"), dict) else None
                            if scr and isinstance(scr.get("on"), bool):
                                total_frames += 1
                                if scr["on"]:
                                    on_frames += 1
                        metrics = {
                            "steps": max(steps_vals) if steps_vals else None,
                            "screen_on_ratio": round(on_frames / total_frames, 2) if total_frames else None,
                        }
                        self._append_diary(today, text, metrics)
                        logger.info(f"[{PLUGIN_NAME}] 晚安日报已发送给 {sender}")

    def _diary_path(self):
        if not getattr(self, "_origin_file", None):
            return None
        return self._origin_file.parent / "diary.jsonl"

    def _append_diary(self, date: str, text: str, metrics: dict | None = None) -> None:
        """日报落档（diary.jsonl，一天一行，含每日指标数值供后续 z-score 基线用）。"""
        try:
            path = self._diary_path()
            if path is None:
                return
            lines = []
            if path.exists():
                lines = [
                    l for l in path.read_text(encoding="utf-8").splitlines()
                    if l.strip() and f'"date": "{date}"' not in l and f'"date":"{date}"' not in l
                ]
            entry = {"date": date, "text": text}
            if metrics:
                entry.update(metrics)
            lines.append(json.dumps(entry, ensure_ascii=False))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] diary写入失败: {exc!r}")

    async def phone_perception_diary(self, event: AstrMessageEvent, days_ago: int = 0) -> str:
        """回查历史保留的小结；当前自动每日小结关闭。

        用户问"我前天/上周某天在干嘛、那天睡了多久、走了多少步"时调用；当天或最近几天用 phone_perception_insight 更合适。

        Args:
            days_ago(int): 几天前，0=今天，1=昨天，最大30。
        """
        if not self._authorized(event):
            return "仅白名单用户可以在私聊中使用手机感知。"
        from datetime import timedelta

        day = (datetime.now() - timedelta(days=max(0, min(days_ago, 30)))).strftime("%Y-%m-%d")
        path = self._diary_path()
        if path is None or not path.exists():
            return f"还没有日记（{day}）。"
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("date") == day:
                return f"{day}的记录：{str(entry.get('text', ''))[:300]}"
        recent = []
        for line in path.read_text(encoding="utf-8").splitlines()[-7:]:
            try:
                recent.append(json.loads(line).get("date"))
            except Exception:
                pass
        hint = f"现有记录日期：{'、'.join(filter(None, recent))}。" if recent else "日记还没有积累。"
        return f"没有 {day} 的记录。{hint}"

    def _addict_packages(self) -> set[str]:
        raw = self.config.get("care_addict_packages", []) or []
        if isinstance(raw, str):
            raw = [x for x in raw.replace("，", ",").split(",") if x.strip()]
        return {str(x).strip() for x in raw if str(x).strip()}

    async def _auto_quiet_reason(self, sender: str) -> str | None:
        """自动安静判定：基于感知数据判断用户此刻是否不该被打扰。"""
        try:
            best = await self._freshest_view()
            if best is None:
                return None  # 没数据时不限制
            state, age, dev = best
            if age > 600:
                return None  # 数据过期不限制
            screen = state.get("screen") or {}
            battery = state.get("battery") or {}
            hour = datetime.now().hour

            # 灭屏 + 没在充电（可能在睡觉/没看手机）
            if screen.get("on") is False and battery.get("charging") is not True:
                # 深夜灭屏：肯定在睡觉，别吵
                if 0 <= hour < 7:
                    return "深夜灭屏未充电（睡眠）"
                # 白天灭屏 + 超过30分钟没互动：可能在忙
                last_msg_gap = time.time() - self._last_activity_at.get(sender, 0)
                if last_msg_gap > 1800:
                    return f"白天灭屏+{int(last_msg_gap/60)}分钟未互动"

            # 正在专注用某个 App（前台 >20 分钟）：不打断
            app = state.get("app") or {}
            fg_min = app.get("foreground_minutes")
            if isinstance(fg_min, (int, float)) and fg_min > 20:
                label = app.get("foreground_label") or app.get("foreground_package") or "?"
                if str(app.get("foreground_package", "")) not in ("com.tencent.mobileqq", "com.android.systemui"):
                    return f"专注使用{label}已{int(fg_min)}分钟"

            return None
        except Exception:
            return None

    async def _send_private(self, origin: str, text: str, *, sender: str = "", bypass_gate: bool = False) -> bool:
        if not self._session_allowed(origin):
            return False
        if self.config.get("phone_respect_manual_quiet", False):
            reason = await self.dialogue_flow.quiet_reason(origin)
            if reason:
                logger.info(f"[{PLUGIN_NAME}] 手机提醒遵守会话手动安静，本次跳过")
                return False
        now = time.time()
        if not bypass_gate and sender:
            # 全局节流：10分钟内已有主动消息则本条静默让路（防连发轰炸）
            if not proactive_gate(self._last_proactive_at.get(sender), now):
                logger.info(f"[{PLUGIN_NAME}] 主动消息节流让路（10分钟内已发过）")
                return False
            # 自动安静：灭屏/深夜/专注时静默让路（不需要用户手动设 busy）
            quiet = await self._auto_quiet_reason(sender)
            if quiet:
                logger.info(f"[{PLUGIN_NAME}] 自动安静：{quiet}，主动消息静默跳过")
                return False
        if not self._session_allowed(origin):
            return False
        try:
            chain = MessageChain().message(text)
            delivered = await self.context.send_message(origin, chain)
            if delivered is False:
                logger.warning(f"[{PLUGIN_NAME}] 主动消息未提交，目标平台不可用")
                return False
            self._broken_origins.pop(origin, None)
            if sender:
                self._last_proactive_at[sender] = time.time()
            topics = self._recent_topics.setdefault(sender, [])
            topics.append((text, time.time()))
            del topics[:-10]
            self._save_state(force=True)
            return True
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] 主动消息发送失败 origin={origin}: {exc!r}")
            import time as _t

            self._broken_origins[origin] = _t.time()  # 停用坏地址
            return False

    # ---- 历史洞察工具 ----

    async def phone_perception_insight(self, event: AstrMessageEvent, hours: int = 6) -> str:
        """回顾用户手机最近几小时的变化趋势（电量走势、步数增量、亮屏占比、听过的歌、长时间灭屏记录）。

        仅当用户主动问"我今天/最近几个小时手机状态怎么样""我昨晚睡得怎么样"之类回溯性问题时调用，
        查询当前状态请用 phone_perception_query。

        Args:
            hours(int): 回看的小时数，1 到 26。
        """
        if not self._authorized(event):
            return "仅白名单用户可以在私聊中使用手机感知。"
        if not self._enabled():
            return "手机感知功能未开启。"
        self._sync_client()
        minutes = int(max(1, min(hours or 6, 26)) * 60)
        samples = await self._primary_history(minutes)
        if not samples:
            return format_error("最近没有上报样本")
        parts = [history_summary(samples)]
        sleep = sleep_summary(samples)
        if sleep:
            parts.append(sleep)
        return "手机：" + " · ".join(parts)

    async def _primary_history(self, minutes: int) -> list[dict]:
        """延用最新上报设备优先；历史始终来自同一台设备，按时间倒序。"""
        best = await self._freshest_view()
        devices = self._devices()
        if best is not None:
            devices = [best[2]] + [dev for dev in devices if dev != best[2]]
        candidates = []
        for dev in devices:
            data = await self.client.get_history(minutes, device=dev)
            if not isinstance(data, dict) or not data.get("ok"):
                continue
            samples = [sample for sample in (data.get("samples") or []) if isinstance(sample, dict)]
            samples.sort(key=lambda sample: float(sample.get("received_at", 0) or 0), reverse=True)
            if samples:
                if best is not None and dev == best[2]:
                    return samples
                candidates.append(samples)
        return max(candidates, key=lambda samples: float(samples[0].get("received_at", 0) or 0)) if candidates else []

    # ---- 配置 ----

    def _enabled(self) -> bool:
        return self._active and bool(self.config.get("enable_phone_perception", False))

    def _save_config(self) -> None:
        """AstrBot 使用 save_config；兼容旧宿主的 save，不吞掉写入失败。"""
        save = getattr(self.config, "save_config", None)
        if not callable(save):
            save = getattr(self.config, "save", None)
        if not callable(save):
            raise RuntimeError("宿主配置对象不支持持久化")
        with self._config_write_lock:
            save()

    def _allowed_users(self) -> set[str]:
        raw = self.config.get("allowed_user_ids", []) or []
        if isinstance(raw, str):
            raw = [x for x in raw.replace("，", ",").split(",") if x.strip()]
        return {str(x).strip() for x in raw if str(x).strip()}

    def _stale_seconds(self) -> int:
        minutes = self.config.get("stale_minutes", 10)
        try:
            return max(30, int(minutes) * 60)
        except (TypeError, ValueError):
            return 600

    def _sync_client(self) -> None:
        self.client.configure(
            base_url=str(self.config.get("bridge_base_url", "") or ""),
            token=str(self.config.get("bridge_token", "") or ""),
            device_id=str(self.config.get("device_id", "phone") or "phone"),
        )
        self.client.timeout = float(self.config.get("timeout_seconds", 4) or 4)
        self.client.cache_ttl = 2.0 if self._music_enabled() else 8.0

    async def _secondary_note(self, primary_dev: str) -> str | None:
        """多设备时给非主力机的电量简报（最多一台，信息量压到最小）。"""
        devices = self._devices()
        if len(devices) < 2:
            return None
        for dev in devices:
            if dev == primary_dev:
                continue
            data = await self.client.get_state(self._stale_seconds(), device=dev)
            view = self._fresh_view(data)
            if view is None:
                continue
            battery = view[0].get("battery") or {}
            level = battery.get("level")
            if not isinstance(level, (int, float)):
                continue
            charging = "，充电中" if battery.get("charging") is True else ""
            return f"另一台{dev}：电量{int(level)}%{charging}"
        return None

    async def _stale_line(self) -> str:
        """inject_when_stale 开启时：取最近一帧原始状态，明确标注不新鲜。"""
        for dev in self._devices():
            data = await self.client.get_state(24 * 3600, device=dev)
            if isinstance(data, dict) and data.get("ok") and data.get("state"):
                return format_perception(
                    self._without_legacy_music(data["state"]),
                    age_seconds=data.get("age_seconds"),
                    fresh=False,
                    show_app=bool(self.config.get("show_app", False)),
                    playlist=self._playlist(),
                )
        return ""

    def _photo_nudge_hint(self, sender: str) -> str | None:
        """随身相机（常态能力）：低频提醒她"你有相机，自己决定什么时候用"。不倒数、不催促。"""
        if not bool(self.config.get("photo_nudge_enabled", True)):
            return None
        refresh = max(10, int(self.config.get("photo_refresh_messages", 20) or 20))
        today = datetime.now().strftime("%Y-%m-%d")
        pc = self._photo_counts.setdefault(sender, {"date": today, "count": 0})
        if pc.get("date") != today:
            pc.update({"date": today, "count": 0})
        pc["count"] += 1
        self._save_state()
        if pc["count"] % refresh != 0:
            return None  # 不是刷新轮次，静默
        hour = datetime.now().hour
        night = 0 <= hour < 5 or hour >= 22
        parts = [
            "你有一部随身相机（工具 pc_generate_photo），可以随时给自己拍一张发给用户。",
            "内容是你此刻的自拍——穿衣、场景、神态都贴合当下，生活化、亲密。",
            "不需要用户开口，也不需要解释为什么发。像随手分享一样自然。",
            "什么时候用：她夸你/撒娇/情绪浓时，用一张自拍回应；",
            "你主动发消息（彩蛋/关怀/晚安）时，偶尔附一张；",
        ]
        if night:
            parts.append("深夜氛围好的时候也可以来一张。")
        parts.append(
            "总之它就在你手边，你自己判断——有感觉就拍，没感觉就当没这条。"
            "要么真的发出来，要么不提——不要说'我要去拍'却没动作。"
        )
        return "## 随身相机（常态能力提醒）\n" + "".join(parts)

    def _playlist_local(self):
        return self._playlist()

    def _playlist(self):
        """读插件数据目录的 playlist.json（歌单备注库），mtime 缓存。"""
        if self._playlist_bridge_cache is not None:
            return self._playlist_bridge_cache
        if not getattr(self, "_origin_file", None):
            return None
        path = self._origin_file.parent / "playlist.json"
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] playlist.json 状态读取失败: {exc!r}")
            return self._playlist_cache  # 读不到 mtime 时退回上次缓存，绝不当作"没有歌单"
        if self._playlist_cache is not None and self._playlist_mtime == mtime:
            return self._playlist_cache
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            self._playlist_cache, self._playlist_mtime = data, mtime
            return data
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning(f"[{PLUGIN_NAME}] playlist.json 解析失败（保留旧缓存）: {exc!r}")
            return self._playlist_cache

    def _remember_playlist(self, playlist: dict) -> None:
        """桥端成功后更新插件缓存与本地兜底副本，空歌单也是有效结果。"""
        if not isinstance(playlist, dict):
            return
        self._playlist_bridge_cache = dict(playlist)
        self._playlist_bridge_at = time.time()
        self._playlist_cache = dict(playlist)
        self._playlist_mtime = 0.0
        if getattr(self, "_origin_file", None):
            try:
                import os

                path = self._origin_file.parent / "playlist.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(playlist, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, path)
            except OSError as exc:
                logger.warning(f"[{PLUGIN_NAME}] 桥端歌单已保存，但本地副本写入失败: {exc!r}")

    async def _playlist_async(self):
        """桥为主存（30秒缓存），不可达时使用上次成功结果或本地副本。"""
        async with self._playlist_lock:
            if time.time() - self._playlist_bridge_at < 30:
                return self._playlist()
            playlist = await self.client.get_playlist_bridge()
            self._playlist_bridge_at = time.time()
            if playlist is not None:
                self._remember_playlist(playlist)
            return self._playlist()

    async def _surprises(self) -> dict:
        """桥端惊喜内容，5 分钟缓存；失败/为空退回内置。"""
        now = time.time()
        if self._surprises_cache is not None and now - self._surprises_at < 300:
            return self._surprises_cache
        data = await self.client.get_surprises()
        self._surprises_cache, self._surprises_at = (data if isinstance(data, dict) else {}), now
        return self._surprises_cache

    def _devices(self) -> list[str]:
        """多设备支持：device_ids 优先，退回单 device_id。"""
        raw = self.config.get("device_ids", []) or []
        if isinstance(raw, str):
            raw = [x for x in raw.replace("，", ",").split(",") if x.strip()]
        devices = [str(x).strip() for x in raw if str(x).strip()]
        if not devices:
            single = str(self.config.get("device_id", "phone") or "phone").strip()
            devices = [single or "phone"]
        return devices

    async def _freshest_view(self, stale_s: int | None = None, bridge_health: bool = False) -> tuple[dict, float, str] | None:
        """拉全部设备状态，返回最新的 (state, age, device)；全部过期/无数据返回 None。"""
        stale = self._stale_seconds() if stale_s is None else stale_s
        best: tuple[dict, float, str] | None = None
        best_latest_age = float("inf")
        reached_any = False
        for dev in self._devices():
            data = await self.client.get_state(stale, device=dev)
            if isinstance(data, dict) and data.get("ok"):
                reached_any = True
            view = self._fresh_view(data, stale)
            if view is None:
                continue
            fresh_state, age = view
            latest_age = data.get("age_seconds")
            if (type(latest_age) not in (int, float) or not 0 <= latest_age <= 253402300799
                    or not math.isfinite(latest_age)):
                latest_age = min(fresh_section_ages(data, stale).values())
            if best is None or latest_age < best_latest_age:
                best = (fresh_state, age, dev)
                best_latest_age = latest_age
        if bridge_health:
            self._bridge_down = not reached_any
        return best

    def _fresh_view(self, data: dict, stale_s: int | None = None) -> tuple[dict, float] | None:
        """返回可用段与其中最老段龄，避免把整行说成刚刚更新。

        旧桥无段龄时使用有效的全局段龄；无法确认年龄的字段不作事实。
        """
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        state = data.get("state") or {}
        stale_s = self._stale_seconds() if stale_s is None else stale_s
        fresh_keys = fresh_section_ages(data, stale_s)
        if not fresh_keys:
            return None
        return self._without_legacy_music({k: state[k] for k in fresh_keys}), max(fresh_keys.values())

    # ---- 事件辅助 ----

    def _sender_id(self, event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_id() or "")
        except Exception:
            return ""

    def _is_private(self, event: AstrMessageEvent) -> bool:
        try:
            getter = getattr(event, "get_group_id", None)
            if callable(getter):
                return not str(getter() or "").strip()
        except Exception:
            pass
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        return ":GroupMessage" not in origin and "group" not in origin.lower()

    def _authorized(self, event: AstrMessageEvent) -> bool:
        sender = self._sender_id(event)
        return (self._is_private(event) and bool(sender) and sender in self._allowed_users()
                and self._session_allowed(str(getattr(event, "unified_msg_origin", "") or "")))

    # ---- 独立音乐上下文：不接关怀或发送队列 ----

    def _music_enabled(self) -> bool:
        return self._enabled() and self.config.get("enable_music_context", False) is True

    def _music_ttl(self) -> int:
        value = self.config.get("music_stale_seconds", 180)
        return value if type(value) is int and 30 <= value <= 600 else 180

    def _music_devices_for_user(self, sender: str) -> list[str]:
        if sender not in self._allowed_users():
            return []
        raw = self.config.get("music_user_devices", "")
        if raw:
            try:
                mapping = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(mapping, dict):
                    return []
                devices = mapping.get(sender, [])
                if not isinstance(devices, list):
                    return []
            except (ValueError, TypeError):
                return []
        elif len(self._allowed_users()) == 1:
            devices = self._devices()
        else:
            return []
        if len(devices) > 8 or any(not isinstance(device, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", device) for device in devices):
            return []
        return list(dict.fromkeys(devices))

    def _music_diagnostics(self) -> dict:
        index = self._music_index.get()
        stats = index.get("stats", {}) if isinstance(index, dict) else {}
        stats = stats if isinstance(stats, dict) else {}
        rows = stats.get("indexed_rows", 0)
        rows = rows if type(rows) is int and rows >= 0 else 0
        owner=getattr(self.config,'plugin',None)
        host=getattr(getattr(owner,'_presence',None),'living_host',None)
        companion=getattr(getattr(host,'runtime',None),'phone_companion',None)
        notifications=bool(owner is not None and getattr(owner,'_native_phone_service',None)is self
            and self._active and not getattr(owner,'_stopping',False)
            and companion is not None and companion.active
            and owner._cfg_bool('living_phone_music_notifications_enabled',False)is True)
        return {"enabled": self._music_enabled(), "protocol_version": 1,
                "ttl_seconds": self._music_ttl(), "index_rows": rows,
                "index_error_type": self._music_index.error_type,
                "temporary_context_available": TextPart is not None,
                "active_music_notifications": notifications,
                "music_notification_owner": "tls_native_phone_companion" if notifications else None,
                **self._music_metrics}

    @staticmethod
    def _drop_music_fragment(req) -> None:
        parts = getattr(req, "extra_user_content_parts", None)
        if isinstance(parts, list):
            req.extra_user_content_parts = [part for part in parts if MUSIC_CONTEXT_MARKER not in str(getattr(part, "text", ""))]
        system = str(getattr(req, "system_prompt", "") or "")
        if MUSIC_CONTEXT_MARKER in system:
            pattern = re.escape(MUSIC_CONTEXT_MARKER) + r".*?" + re.escape(MUSIC_CONTEXT_END)
            req.system_prompt = re.sub(pattern, "", system, flags=re.S)

    def _without_legacy_music(self, state: dict) -> dict:
        if not self._music_enabled() or not isinstance(state, dict):
            return state
        result = {key: value for key, value in state.items() if key != "music"}
        audio = result.get("audio")
        if isinstance(audio, dict):
            result["audio"] = {key: value for key, value in audio.items() if key not in {"media_active", "media_title", "media_artist"}}
        return result

    async def _collect_music_event(self, sender: str) -> dict:
        now = time.time()
        devices = self._music_devices_for_user(sender)
        unknown = build_music_event({}, now=now, ttl_seconds=self._music_ttl())
        if not devices:
            unknown["user_state"]["reason"] = "device_binding_required"
            return unknown
        self._sync_client()
        self.client.cache_ttl = 2.0
        scope = (self.client.base_url, self.client.token, str(self.config.get("music_user_devices", "")),
                 tuple(sorted(self._allowed_users())), tuple(self._devices()))
        if scope != self._music_scope:
            self._music_provider.clear()
            self._music_selected_by_user.clear()
            self._music_last_events.clear()
            self._music_scope = scope
        if not self.client.configured or time.time() < getattr(self, "_bridge_fail_until", 0.0):
            return unknown
        self._music_provider.ttl_seconds = self._music_ttl()
        try:
            # Same stale flag/cache key as ordinary phone perception: one fetch
            # serves both hooks. Music freshness is enforced locally per section.
            rows = await asyncio.wait_for(asyncio.gather(*(self.client.get_state(self._stale_seconds(), device=device) for device in devices)), timeout=1.5)
        except asyncio.TimeoutError:
            self._music_metrics["timeouts"] += 1
            self._bridge_fail_until = time.time() + 30
            unknown["user_state"]["reason"] = "bridge_timeout"
            return unknown
        except Exception as exc:
            self._music_metrics["errors"] += 1
            self._bridge_fail_until = time.time() + 30
            unknown["provider_error_type"] = type(exc).__name__
            return unknown
        self._sync_client()
        current_scope = (self.client.base_url, self.client.token, str(self.config.get("music_user_devices", "")),
                         tuple(sorted(self._allowed_users())), tuple(self._devices()))
        if self._music_stopping or not self._music_enabled() or scope != current_scope:
            return unknown
        if not any(isinstance(row, dict) and row.get("ok") is True for row in rows):
            self._bridge_fail_until = time.time() + 30
        preferred = self.config.get("music_preferred_device", "")
        priority = [preferred] if isinstance(preferred, str) and preferred in devices else None
        selected = choose_music_views(dict(zip(devices, rows)), device_priority=priority, now=time.time(), ttl_seconds=self._music_ttl())
        device = selected.get("device_id") or self._music_selected_by_user.get(sender) or devices[0]
        if selected.get("status") == "selected":
            self._music_selected_by_user[sender] = device
        observation = selected.get("view") or {}
        if selected.get("status") == "unavailable":
            # Keep the explicit stale event without retaining a stale title.
            for candidate_device, row in sorted(zip(devices, rows), key=lambda item: item[0] != device):
                if build_music_event(row, now=time.time(), ttl_seconds=self._music_ttl())["event_type"] == "music_stale":
                    observation, device = row, candidate_device
                    break
        events = self._context_aggregator.collect({"music": observation}, user_id=sender, device_id=device, now=time.time())
        event = events.get("music", unknown)
        if selected.get("status") != "selected":
            event["user_state"]["reason"] = selected.get("reason", "unavailable")
        self._music_last_events[sender] = event
        self._music_metrics["last_event_type"] = event.get("event_type", "music_unknown")
        return event

    async def inject_music_context(self, event: AstrMessageEvent, req: ProviderRequest, *args, **kwargs) -> None:
        self._drop_music_fragment(req)
        if self._music_stopping or not self._music_enabled() or not self._authorized(event):
            return
        if self._presence_adapter.delegated(event):
            return
        sender = self._sender_id(event)
        music = await self._collect_music_event(sender)
        if self._music_stopping or not self._music_enabled() or not self._authorized(event):
            return
        maximum = self.config.get("music_context_max_chars", 360)
        maximum = maximum if type(maximum) is int and 160 <= maximum <= 800 else 360
        text = self._context_aggregator.render({"music": music}, max_chars=maximum)
        if text and TextPart is not None and isinstance(getattr(req, "extra_user_content_parts", None), list):
            req.extra_user_content_parts.append(TextPart(text=wrap_music_fragment(text)).mark_as_temp())
            self._music_metrics["injections"] += 1

    async def register_shared_presence(self):
        """全插件加载后登记共享接口，避免插件加载顺序造成冷启动缺来源。"""
        self._presence_adapter.ensure_registered()

    async def _web_music_get(self):
        self._presence_adapter.ensure_registered()
        users = self._allowed_users()
        sender = str(query_args().get("user") or "")
        if not sender and len(users) == 1:
            sender = next(iter(users))
        if sender not in users:
            return error_response("请选择已有授权并绑定设备的用户", status_code=400)
        if not self._music_enabled():
            return json_response({"ok": True, "enabled": False, "diagnostics": self._music_diagnostics()})
        event = await self._collect_music_event(sender)
        return json_response({"ok": True, "enabled": True, "event": event, "diagnostics": self._music_diagnostics()})

    # ---- LLM 注入 ----

    def _phone_auxiliary_parts(self, sender: str, user_text: str) -> tuple[str, str, str]:
        """Existing chat aids stay outside the shared environment facts."""
        mood = detect_mood(user_text)
        if mood:
            hist = self._mood_history.setdefault(sender, [])
            hist.insert(0, (mood, time.time()))
            del hist[10:]
        mood_line = mood_context(self._mood_history.get(sender, []), time.time())
        photo_extra = self._photo_nudge_hint(sender)
        topic_window = max(5, int(self.config.get("topic_window_minutes", 30) or 30)) * 60
        topics = [txt for txt, ts in self._recent_topics.get(sender, []) if time.time() - ts < topic_window][-2:]
        topic_line = ("## 你最近主动说过（别重复发同样的话）\n" + "\n".join(f"- {text}" for text in topics)) if topics else ""
        return photo_extra, mood_line, topic_line

    async def inject_phone_perception(
        self, event: AstrMessageEvent, req: ProviderRequest, *args, **kwargs
    ) -> None:
        if not self._enabled():
            return
        if not self._is_private(event):
            return
        sender = self._sender_id(event)
        if not sender or sender not in self._allowed_users():
            return
        # 记录该用户最近一次私聊会话，供主动关怀发送使用
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if origin and self._notify_origins.get(sender) != origin:
            self._notify_origins[sender] = origin
            self._broken_origins.pop(origin, None)
            self._save_origins()

        self._sync_client()
        cooldown = float(self.config.get("inject_cooldown_seconds", 0) or 0)
        now = time.time()
        if cooldown > 0 and now - self._last_inject_at.get(sender, 0) < cooldown:
            return
        if self._presence_adapter.delegated(event):
            # Presence owns device facts. Keep photo hints, mood tracking and
            # recent topics intact without a second bridge fetch/data block.
            photo, mood_line, topic_line = self._phone_auxiliary_parts(sender, str(getattr(event, "message_str", "") or ""))
            parts = [part for part in (photo, f"## 用户情绪\n{mood_line}" if mood_line else "", topic_line) if part]
            if parts:
                current = str(getattr(req, "system_prompt", "") or "")
                req.system_prompt = f"{current}\n\n" + "\n".join(parts)
                self._last_inject_at[sender] = time.time()
            return
        if not self.client.configured:
            return

        now0 = time.time()
        if now0 < getattr(self, "_bridge_fail_until", 0.0):
            return  # 桥近期不可达：熔断期内不再尝试，绝不拖慢对话
        try:
            best = await self._freshest_view(bridge_health=True)
        except Exception as exc:  # 双保险：任何异常都不影响主流程
            logger.warning(f"[{PLUGIN_NAME}] 拉取状态异常，跳过注入: {exc!r}")
            self._bridge_fail_until = now0 + 30
            return

        # 情绪追踪：从用户消息中检测（无 LLM 调用，纯关键词）
        user_text = str(getattr(event, "message_str", "") or "")
        # 深夜画笔按消息计数，与数据新鲜度无关。
        photo_extra, mood_line, topic_line = self._phone_auxiliary_parts(sender, user_text)
        if best is None:
            if photo_extra:
                current0 = str(getattr(req, "system_prompt", "") or "")
                req.system_prompt = f"{current0}\n\n{photo_extra}".strip()
            if self._bridge_down:
                self._bridge_fail_until = now0 + 30
                if now0 - getattr(self, "_bridge_down_logged_at", 0.0) > 60:
                    self._bridge_down_logged_at = now0
                    logger.info(f"[{PLUGIN_NAME}] 桥不可达，30秒内跳过感知注入")
            elif bool(self.config.get("inject_when_stale", False)) and not self._bridge_down:
                # 开了"过期也注入"：以最近一帧+明确标注的方式给（桥可达才给）
                stale_line = await self._stale_line()
                if stale_line:
                    current0 = str(getattr(req, "system_prompt", "") or "")
                    extra0 = photo_extra or ""
                    req.system_prompt = f"{current0}\n\n{INJECTION_BLOCK_TITLE}\n{stale_line}{extra0}".strip()
                return
            else:
                logger.info(f"[{PLUGIN_NAME}] 全部设备的数据段已过期，跳过数据注入")
            return
        fresh_state, fresh_age, best_dev = best

        hint = build_injection_hint(fresh_state, repeated=False)
        worth_saying = bool(injection_reasons(fresh_state))

        line = ""
        if worth_saying:
            line = format_perception(
                fresh_state,
                age_seconds=fresh_age,
                fresh=True,
                show_app=bool(self.config.get("show_app", False)),
                playlist=await self._playlist_async(),
            )
            extra = await self._secondary_note(best_dev)
            if extra:
                line = f"{line} · {extra}"

        # Display ages advance while facts stay the same. Only factual changes
        # (including another device's battery note) reset repetition suppression.
        signature = json.dumps([best_dev, fresh_state, extra if worth_saying else None],
                               ensure_ascii=False, sort_keys=True) if line else ""
        repeated = signature == self._last_inject_line.get(sender, "") and bool(line)
        self._same_line_count[sender] = self._same_line_count.get(sender, 0) + 1 if repeated else 0
        self._last_inject_line[sender] = signature

        # 组装注入块：只在有内容时才写（正常状态零注入）
        parts: list[str] = []
        if line and self._same_line_count.get(sender, 0) < 2:
            parts.append(f"{INJECTION_BLOCK_TITLE}\n{line}\n{hint}")
        if photo_extra:
            parts.append(photo_extra)
        if mood_line:
            parts.append(f"## 用户情绪\n{mood_line}")

        # 主动话头：只带最近30分钟内的（过期不再提醒，减轻上下文）
        if topic_line:
            parts.append(topic_line)

        if parts:
            block = "\n".join(parts)
            current = str(getattr(req, "system_prompt", "") or "")
            req.system_prompt = f"{current}\n\n{block}".strip()
            self._last_inject_at[sender] = now

    # ---- LLM 工具：bot 主动查询 ----

    async def phone_perception_query(self, event: AstrMessageEvent, aspect: str = "") -> str:
        """查询用户手机的当前实时状态（电量、充电、灭屏、网络、步数、闲置等）。

        仅当用户主动问起手机相关情况，或需要判断用户是否在忙、是否方便时调用。
        数据可能过期，回答时不要夸大精确性。

        Args:
            aspect(string): 想了解的方面，例如“电量”“在不在忙”“音乐”，可留空表示全部。
        """
        if not self._authorized(event):
            return "仅白名单用户可以在私聊中使用手机感知。"
        if not self._enabled():
            return "手机感知功能未开启。"
        self._sync_client()
        if not self.client.configured:
            return "手机感知桥还没配置地址或令牌。"
        if self._music_enabled() and any(word in str(aspect or "").lower() for word in ("音乐", "歌曲", "在听", "music", "song")):
            music = await self._collect_music_event(self._sender_id(event))
            if music.get("event_type") == "music_paused":
                return "当前音乐已暂停。"
            if music.get("event_type") == "music_stopped":
                return "当前音乐已停止。"
            if music.get("event_type") != "music_playing":
                return "现在无法可靠确认正在播放的歌曲，不应沿用旧歌名。"
            info = music.get("song_info", {})
            line = "当前播放器显示：" + str(info.get("title") or "未知曲目")
            if info.get("artist"):
                line += " · " + str(info["artist"])
            if music.get("match_status") != "matched":
                line += "。曲库详细资料尚未确认。"
            return line
        devices = self._devices()
        lines: list[str] = []
        for dev in devices:
            try:
                data = await self.client.get_state(self._stale_seconds(), device=dev)
            except Exception as exc:
                return format_error(str(exc))
            if not isinstance(data, dict) or not data.get("ok"):
                if isinstance(data, dict) and data.get("status") == 404:
                    lines.append(f"{dev}：还没有上报过数据。")
                    continue
                lines.append(f"{dev}：" + format_error(str((data or {}).get("error", "未知原因"))))
                continue
            view = self._fresh_view(data)
            if view is None:
                lines.append(f"{dev}：" + format_stale_notice(data.get("age_seconds")))
                continue
            fresh_state, fresh_age = view
            line = format_perception(
                fresh_state,
                age_seconds=fresh_age,
                fresh=True,
                show_app=bool(self.config.get("show_app", False)),
                playlist=await self._playlist_async(),
            )
            lines.append((f"{dev}：{line}") if line else f"{dev}：" + format_stale_notice(None))
        if len(lines) == 1 and "还没有上报过数据" in lines[0]:
            return "手机还没有上报过数据（先在手机 App 里点「立即试报一帧」）。"
        return "\n".join(lines)

    # ---- 手动验证命令 ----

    async def command_phone_perception(self, event: AstrMessageEvent):
        """手动检查感知桥连通性与当前状态。"""
        if not self._authorized(event):
            yield event.plain_result("仅白名单用户可以在私聊中使用手机感知。")
            return
        if not self._enabled():
            yield event.plain_result("手机感知功能未开启（WebUI 插件配置 enable_phone_perception）。")
            return
        self._sync_client()
        if not self.client.configured:
            yield event.plain_result("感知桥未配置：请在插件配置里填 bridge_base_url 与 bridge_token。")
            return
        data = await self.client.get_state(self._stale_seconds())
        if not isinstance(data, dict) or not data.get("ok"):
            if isinstance(data, dict) and data.get("status") == 404:
                yield event.plain_result("手机感知：手机还没有上报过数据。先在手机 App 填好地址和令牌，点「立即试报一帧」。")
                return
            yield event.plain_result(format_error(str((data or {}).get("error", "未知原因"))))
            return
        view = self._fresh_view(data)
        if view is None:
            yield event.plain_result(format_stale_notice(data.get("age_seconds")))
            return
        fresh_state, fresh_age = view
        line = format_perception(
            fresh_state,
            age_seconds=fresh_age,
            fresh=True,
            show_app=True,
            playlist=await self._playlist_async(),
        )
        yield event.plain_result(line or format_stale_notice(data.get("age_seconds")))

    def _record_phone_activity(self, event):
        if self._authorized(event):
            get_extra = getattr(event, "get_extra", None)
            if callable(get_extra) and get_extra("phone_activity_recorded"):
                return
            self._last_activity_at[self._sender_id(event)] = time.time()
            set_extra = getattr(event, "set_extra", None)
            if callable(set_extra):
                set_extra("phone_activity_recorded", True)

    async def flow_wait_for_message(self, event: AstrMessageEvent):
        self._record_phone_activity(event)
        await self.dialogue_flow.wait_for_message(event)

    async def flow_style_request(self, event: AstrMessageEvent, req: ProviderRequest):
        self._record_phone_activity(event)
        await self.dialogue_flow.style_request(event, req)

    async def flow_finish_notice(self, event: AstrMessageEvent, response):
        await self.dialogue_flow.finish_notice(event, response)

    async def flow_command(self, event: AstrMessageEvent, action: str = ""):
        self._record_phone_activity(event)
        async for result in self.dialogue_flow.flow_command(event, action):
            yield result

    async def send_proactive(self, umo, event_key, chain):
        return await self.dialogue_flow.send_proactive(umo, event_key, chain)

    def _web_phone_policy_get(self):
        return json_response({"ok": True, "policy": {"respect_manual_quiet": bool(self.config.get("phone_respect_manual_quiet", False))}})

    async def _web_phone_policy_save(self):
        try:
            body = await body_json()
            if not isinstance(body, dict) or set(body) != {"respect_manual_quiet"} or type(body["respect_manual_quiet"]) is not bool:
                return error_response("请提供 respect_manual_quiet 布尔值", status_code=400)
            async with self._web_save_lock:
                old = self.config.get("phone_respect_manual_quiet", False)
                self.config["phone_respect_manual_quiet"] = body["respect_manual_quiet"]
                try:
                    self._save_config()
                except Exception:
                    self.config["phone_respect_manual_quiet"] = old
                    return error_response("保存失败，原提醒规则已保留", status_code=503)
            return self._web_phone_policy_get()
        except (ValueError, TypeError):
            return error_response("请提供 JSON 对象", status_code=400)
