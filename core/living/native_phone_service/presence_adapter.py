"""Optional API v1 adapter; the phone plugin never imports another plugin.

Existing music adaptation and formatting remain the source of truth. Every
phone section keeps its own observation time, owner and freshness window.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import time
from typing import Any

from .formatter import injection_reasons
from ..native_phone_integration_device import format_device_record
from .ppb_client import fresh_section_ages

_SECTIONS = ("battery", "screen", "network", "app", "audio", "device", "activity")
DEVICE_DOMAINS = tuple("user_activity" if key == "activity" else "device." + key for key in _SECTIONS) + ("device.status",)


def _field(value: Any, name: str, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _sender(scope) -> str:
    return str(_field(scope, "user_id", "") or "")


def _number(value) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


class PhonePresenceAdapter:
    SOURCES = ("phone.music", "phone.device")

    def __init__(self, plugin):
        self.plugin = plugin
        self.owner = object()
        self.api = None
        self.closed = False
        self._signature = None

    def _config_signature(self):
        p = self.plugin
        return (p._enabled(), p._music_enabled(), str(p.config.get("music_user_devices", "")),
                tuple(sorted(p._allowed_users())), tuple(p._devices()),
                str(p.config.get("bridge_base_url", "")), str(p.config.get("bridge_token", "")))

    def close(self) -> None:
        self.closed = True
        self._unregister()

    def _unregister(self) -> None:
        if self.api is not None:
            for source in self.SOURCES:
                try:
                    self.api.unregister(source, owner=self.owner)
                except Exception:
                    pass
        self.api = None

    def ensure_registered(self) -> bool:
        p = self.plugin
        candidate = getattr(p.context, "presence_layer", None)
        signature = self._config_signature()
        if signature != self._signature:
            # Binding/config changes invalidate both provider and shared facts.
            self._unregister()
            p._music_provider.clear()
            p._music_selected_by_user.clear()
            p._music_last_events.clear()
            self._signature = signature
        if self.closed or p._music_stopping or not p._enabled():
            self._unregister()
            return False
        if candidate is not self.api:
            self._unregister()
        if candidate is None or not getattr(candidate, "active", False) or not getattr(candidate, "context_enabled", False):
            return False
        if self.api is candidate:
            return True
        if not all(callable(getattr(candidate, method, None)) for method in ("register", "unregister", "scope_for_event")):
            return False
        try:
            music_ok = candidate.register("phone.music", owner=self.owner, domains=("music",),
                               collector=self.collect_music, renderer=self.render_music,
                               enabled=lambda: not self.closed and not p._music_stopping and p._music_enabled(),
                               priority=90)
            device_ok = candidate.register("phone.device", owner=self.owner, domains=DEVICE_DOMAINS,
                               collector=self.collect_device, renderer=self.render_device,
                               enabled=lambda: not self.closed and not p._music_stopping and p._enabled(),
                               priority=60)
            if music_ok is False or device_ok is False:
                raise RuntimeError("presence registration rejected")
        except Exception:
            for source in self.SOURCES:
                try:
                    candidate.unregister(source, owner=self.owner)
                except Exception:
                    pass
            return False
        self.api = candidate
        return True

    def delegated(self, event) -> bool:
        if not self.ensure_registered() or not self.plugin._authorized(event):
            return False
        try:
            scope = self.api.scope_for_event(event)
            return (bool(_field(scope, "private", False)) and _sender(scope) == self.plugin._sender_id(event)
                    and bool(_field(scope, "character_id")))
        except Exception:
            return False

    def _eligible(self, scope, *, music=False) -> bool:
        p = self.plugin
        source = self._source_scope(scope)
        return (not self.closed and not p._music_stopping and bool(_field(scope, "private", False))
                and source is not None and _sender(source) in p._allowed_users()
                and p._session_allowed(_field(source, "session_id", ""))
                and (p._music_enabled() if music else p._enabled()))

    def _source_scope(self, scope):
        """Resolve device ownership without changing the actual caller scope."""
        if _field(scope, 'platform') != 'webchat':
            return scope
        p = self.plugin
        host = getattr(p.config, 'plugin', None)
        if (host is None or getattr(host, '_native_phone_service', None) is not p
                or getattr(host, 'context', None) is not p.context):
            return None
        try:
            from ..chat_workspace import linked_source_scope
            return linked_source_scope(host, scope, permission='perception')
        except (RuntimeError, ValueError, TypeError, PermissionError):
            return None

    @staticmethod
    def _mark_shared(records, scope, source):
        if source == scope:
            return records
        for record in records:
            record['provenance'] = {'phone_source': 'confirmed_link', 'source_scope_shared': True}
            change = record.get('change_key')
            record['change_key'] = dict(change if isinstance(change, dict) else {},
                                        source_scope_shared=True, phone_source='confirmed_link')
        return records

    async def collect_music(self, scope, now: float):
        if not self._eligible(scope, music=True):
            return []
        source = self._source_scope(scope)
        if source is None:
            return []
        signature = self._config_signature()
        event = await self.plugin._collect_music_event(_sender(source))
        if (not self._eligible(scope, music=True) or source != self._source_scope(scope)
                or signature != self._config_signature()):
            return []
        event = deepcopy(event)
        user = event.get("user_state", {})
        kind = event.get("event_type", "music_unknown")
        if kind in {"music_unknown", "music_stale"}:
            user["playing"] = None
        status = "stale" if kind == "music_stale" else "unknown" if kind == "music_unknown" else "fresh"
        observed = _number(user.get("observed_at"))
        info = event.get("song_info", {})
        change_key = {"event_type": kind, "song_id": event.get("song_id"),
                      "title": info.get("title"), "artist": info.get("artist"),
                      "playing": user.get("playing"), "reliable": user.get("reliable"),
                      "source": user.get("source"), "package": user.get("package"),
                      "device_id": user.get("device_id"), "status": status}
        return self._mark_shared([{"domain": "music", "value": event, "observed_at": observed,
                 "received_at": time.time(), "ttl_seconds": self.plugin._music_ttl(),
                 "status": status, "evidence_kind": "observed",
                 "device_id": user.get("device_id") or None, "importance": "important",
                 "change_key": change_key}], scope, source)

    def render_music(self, domain, record, scope, query, max_chars, now) -> str:
        if not self._eligible(scope, music=True):
            return ""
        value = deepcopy(_field(record, "value", {}))
        status = _field(record, "status", "unknown")
        if status not in {"known", "fresh"}:
            # A cached record that expired must never keep its old title alive.
            value = {"event_type": "music_stale" if status == "stale" else "music_unknown", "user_state": {"playing": None}}
        cap = self.plugin.config.get("music_context_max_chars", 360)
        cap = cap if type(cap) is int and 160 <= cap <= 800 else 360
        return self.plugin._context_aggregator.render({"music": value}, max_chars=min(cap, max_chars))

    async def collect_device(self, scope, now: float):
        p = self.plugin
        if not self._eligible(scope):
            return []
        source = self._source_scope(scope)
        if source is None:
            return []
        # Reuse the explicit music ownership mapping; ambiguous multi-user
        # configurations have no implicit device access in the shared layer.
        devices = p._music_devices_for_user(_sender(source))
        if not devices:
            return self._mark_shared(self._empty_device_records("unknown", "device_binding_required", now), scope, source)
        signature = self._config_signature()
        p._sync_client()
        if not p.client.configured or time.time() < getattr(p, "_bridge_fail_until", 0.0):
            return self._empty_device_records("unavailable", "bridge_unavailable", now)
        try:
            rows = await asyncio.wait_for(asyncio.gather(*(p.client.get_state(p._stale_seconds(), device=device) for device in devices)), timeout=1.5)
        except Exception:
            return self._empty_device_records("unavailable", "bridge_unavailable", now)
        if (not self._eligible(scope) or source != self._source_scope(scope)
                or signature != self._config_signature()):
            return []
        received = time.time()
        records = {}
        for device, row in zip(devices, rows):
            if not isinstance(row, dict) or row.get("ok") is not True:
                continue
            # Bridge ages describe response generation, not this cached read.
            server = _number(row.get("server_time"))
            if server is not None and server > received + 30:
                continue
            # Older bridge replies have no generation clock. Their client cache
            # timestamp still prevents repeated reads from renewing the frame.
            cached = getattr(p.client, "_cache", {}).get(row.get("_key"))
            fetched = _number(cached[0]) if isinstance(cached, tuple) and len(cached) == 2 else None
            generated = server if server is not None else fetched
            elapsed = max(0.0, received - generated) if generated is not None else 0.0
            adjusted = deepcopy(row)
            ages = row.get("section_age_seconds")
            if isinstance(ages, dict) and ages:
                adjusted["section_age_seconds"] = {key: age + elapsed for key, age in ages.items() if _number(age) is not None}
            elif _number(row.get("age_seconds")) is not None:
                adjusted["age_seconds"] = row["age_seconds"] + elapsed
            fresh = fresh_section_ages(adjusted, p._stale_seconds())
            state = deepcopy(p._without_legacy_music(row.get("state", {})))
            # Music belongs to its dedicated source even with that feature off.
            if isinstance(state.get("audio"), dict):
                state["audio"] = {key: value for key, value in state["audio"].items() if key not in {"media_active", "media_title", "media_artist"}}
            for section in _SECTIONS:
                if section not in fresh or not isinstance(state.get(section), dict):
                    continue
                domain = "user_activity" if section == "activity" else "device." + section
                observed = received - fresh[section]
                previous = records.get(domain)
                if previous is not None and previous["observed_at"] >= observed:
                    continue
                value = deepcopy(state[section])
                important = bool(injection_reasons({section: value}))
                records[domain] = {"domain": domain, "value": value, "observed_at": observed,
                                   "received_at": received, "ttl_seconds": p._stale_seconds(),
                                   "status": "fresh", "evidence_kind": "observed", "device_id": device,
                                   "importance": "important" if important else "normal",
                                   "change_key": {"device_id": device, "value": value}}
        if records:
            latest = max(records.values(), key=lambda record: record["observed_at"])
            records["device.status"] = {"domain": "device.status",
                                        "value": {"online": None, "last_seen": latest["observed_at"], "reporting_recently": True},
                                        "observed_at": latest["observed_at"], "received_at": received,
                                        "ttl_seconds": p._stale_seconds(), "status": "fresh",
                                        "evidence_kind": "inferred", "device_id": latest["device_id"],
                                        "importance": "normal", "change_key": {"reporting_recently": True, "device_id": latest["device_id"]}}
        missing = {record["domain"]: record for record in self._empty_device_records("unknown", "no_fresh_section", received)}
        return self._mark_shared([records.get(domain, missing[domain]) for domain in DEVICE_DOMAINS], scope, source)

    @staticmethod
    def _empty_device_records(status, reason, now):
        return [{"domain": domain, "value": None, "observed_at": None, "received_at": now,
                 "ttl_seconds": 1, "status": status, "evidence_kind": "observed", "device_id": None,
                 "importance": "normal", "change_key": {"status": status, "reason": reason}}
                for domain in DEVICE_DOMAINS]

    def render_device(self, domain, record, scope, query, max_chars, now) -> str:
        if not self._eligible(scope):
            return ''
        return format_device_record(domain,record,now=now,
            show_app=bool(self.plugin.config.get('show_app',False)),max_chars=max_chars)
