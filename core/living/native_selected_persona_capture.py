"""Isolated observation of the SDK's actual selected Persona ID.

No Host integration, SDK monkey patch, Persona resolution, log read, or grant.
An integration must either bracket the real SDK ensure call with request
begin/finish, or use the genuine public Waiting and Request hook boundaries.
An attached trace alone can never produce a current proof. Existing scope and
MC authorization must still be checked independently by that integration.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import math
from pathlib import Path
import sys
import time
import types
import weakref

from .models import private_scope

SDK_SOURCE_SHA256 = '163b28a2bc42b4968e61ee2d4b9a168921bd5197b8af097453b1397879c9826b'
_SCOPE = frozenset(('platform', 'bot_id', 'user_id', 'character_id', 'session_id', 'private'))


def _find(code, name):
    found = []
    def visit(current):
        if current.co_name == name:
            found.append(current)
        for item in current.co_consts:
            if isinstance(item, types.CodeType): visit(item)
    visit(code)
    if len(found) != 1: raise ValueError('one exact SDK function required')
    return found[0]


def _scope(value):
    if type(value) is not dict or set(value) != _SCOPE or value.get('private') is not True:
        raise ValueError('complete exact genuine private scope required')
    normalized = private_scope(value)
    if normalized != value: raise ValueError('normalized private scope required')
    return normalized


class _SDKSource:
    def __init__(self):
        from astrbot.core import astr_main_agent as module
        self.module = module
        self.path = Path(module.__file__)
        self.function = module._ensure_persona_and_skills
        raw = self._read()
        expected = _find(compile(raw, str(self.path), 'exec', dont_inherit=True), '_ensure_persona_and_skills')
        if (not inspect.iscoroutinefunction(self.function)
                or self.function.__globals__ is not vars(module)
                or self.function.__code__ != expected):
            raise ValueError('loaded SDK ensure differs from reviewed source')
        self.code = self.function.__code__

    def _read(self):
        if (self.path.name != 'astr_main_agent.py' or self.path.is_symlink()
                or not self.path.is_file() or self.path.stat().st_size > 262144):
            raise ValueError('bounded reviewed SDK source required')
        with self.path.open('rb') as stream: raw = stream.read(262145)
        if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != SDK_SOURCE_SHA256:
            raise ValueError('only the reviewed SDK source is supported')
        return raw

    def current(self):
        try:
            return (sys.modules.get(self.module.__name__) is self.module
                and self.module._ensure_persona_and_skills is self.function
                and self.function.__code__ is self.code
                and self.function.__globals__ is vars(self.module)
                and Path(self.module.__file__) == self.path and bool(self._read()))
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class SelectedPersonaEpoch:
    _seal: object = field(repr=False)
    _token: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class SelectedPersonaEventEpoch:
    _seal: object = field(repr=False)
    _token: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class SelectedPersonaProof:
    persona_id: str
    sdk_source_sha256: str
    grants_mc_authority: bool = field(default=False, init=False)
    grants_runtime_authority: bool = field(default=False, init=False)
    grants_write_or_send: bool = field(default=False, init=False)
    capture_mode: str = 'request_epoch'
    _seal: object = field(default=None, repr=False)
    _token: object = field(default=None, repr=False)


class _TraceProxy:
    __slots__ = ('_target', '_owner', '_event', '_entry', '__weakref__')

    def __init__(self, target, owner, event, entry):
        object.__setattr__(self, '_target', target)
        object.__setattr__(self, '_owner', weakref.ref(owner))
        object.__setattr__(self, '_event', weakref.ref(event))
        object.__setattr__(self, '_entry', entry)

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __setattr__(self, name, value):
        if name in self.__slots__: raise AttributeError('capture proxy bindings are immutable')
        setattr(self._target, name, value)

    def __delattr__(self, name):
        if name in self.__slots__: raise AttributeError('capture proxy bindings are immutable')
        delattr(self._target, name)

    def record(self, action, **fields):
        frame = sys._getframe(1)
        owner, candidate = self._owner(), None
        try:
            if owner is not None:
                try: candidate = owner._candidate(self, frame, action, fields)
                except Exception: candidate = None
            try:
                result = self._target.record(action, **fields)
            except BaseException:
                if owner is not None and candidate is not None: owner._drop(candidate[0])
                raise
            if owner is not None and candidate is not None:
                owner._recorded(*candidate)
            return result
        finally:
            # Never retain the caller frame or its ProviderRequest/prompt locals.
            del frame


class NativeSelectedPersonaCapture:
    """Per-event forwarding trace with explicit, weakly-bound request epochs.

    authorize(event, exact_scope) is the caller's existing synchronous genuine
    scope proof. It is not replaced by this module or by the selected ID. An
    integration can call begin_request immediately before the real SDK ensure
    and finish_request in success and failure/cancel branches. Alternatively,
    begin_event belongs in the genuine Waiting hook and finish_event in the
    Request hook after successful build; that Waiting handler must invalidate
    on BaseException before re-raising because the SDK hook dispatcher catches
    it. Errors in arbitrary other plugins' hooks cannot be inferred here.
    Neither a second resolution nor log text is used as identity evidence.
    """
    def __init__(self, context, *, authorize, clock=time.monotonic, max_entries=64, ttl_seconds=120.):
        from astrbot.api.event import AstrMessageEvent
        from astrbot.api.star import Context
        from astrbot.core.provider.entities import ProviderRequest
        from astrbot.core.utils.trace import TraceSpan
        if (type(context) is not Context or not callable(authorize) or not callable(clock)
                or type(max_entries) is not int or not 1 <= max_entries <= 256
                or type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds)
                or not 1 <= ttl_seconds <= 600):
            raise ValueError('exact SDK context and bounded synchronous capture required')
        self.context, self.authorize, self.clock = context, authorize, clock
        self._bindings = (context, authorize, clock)
        self.max_entries, self.ttl_seconds = max_entries, float(ttl_seconds)
        self._event_type, self._request_type, self._trace_type = AstrMessageEvent, ProviderRequest, TraceSpan
        self._source = _SDKSource()
        self._seal, self.active = object(), True
        self._entries, self._states, self._requests = {}, {}, {}
        self._event_epochs = {}
        self._alias_restore_failures = 0

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('finite monotonic clock required')
        return float(value)

    def _allowed(self, event, scope):
        try:
            if (not self.active or not isinstance(event, self._event_type)
                    or any(old is not new for old, new in zip(self._bindings,
                        (self.context, self.authorize, self.clock)))
                    or event.is_private_chat() is not True
                    or any(getattr(event, key, False) is not False for key in
                        ('private_companion_proactive_framework', 'private_companion_internal_generation'))
                    or str(event.get_self_id() or '') != scope['bot_id']
                    or str(event.get_sender_id() or '') != scope['user_id']
                    or scope['bot_id'] == scope['user_id']
                    or event.unified_msg_origin != scope['session_id']): return False
            allowed = self.authorize(event, dict(scope))
            if inspect.isawaitable(allowed):
                if inspect.iscoroutine(allowed): allowed.close()
                return False
            return allowed is True and self.active and self._source.current()
        except Exception:
            return False

    def _drop(self, token):
        state = self._states.pop(token, None)
        if state is not None:
            if self._requests.get(state['request_id']) is token: self._requests.pop(state['request_id'], None)
            if self._event_epochs.get(state['event_id']) is token: self._event_epochs.pop(state['event_id'], None)

    def _entry(self, event):
        entry = self._entries.get(id(event))
        if (entry is None or entry['event']() is not event
                or event.trace is not entry['proxy']() or event.span is not entry['proxy']()
                or self._now() - entry['created'] > self.ttl_seconds): return None
        return entry

    def invalidate(self, event):
        entry = self._entries.get(id(event))
        if entry is None or entry['event']() is not event: return
        self._entries.pop(id(event), None)
        for token, state in list(self._states.items()):
            if state['event']() is event: self._drop(token)
        self._event_epochs.pop(id(event), None)
        proxy = entry['proxy']()
        original = entry['original']()
        if proxy is not None and original is not None:
            for name in ('trace', 'span'):
                try:
                    if getattr(event, name, None) is proxy:
                        setattr(event, name, original)
                        if getattr(event, name, None) is not original:
                            self._alias_restore_failures = min(1000000, self._alias_restore_failures + 1)
                except Exception:
                    # A platform may reject one late alias restore. The
                    # capture is already revoked; continue restoring the other
                    # alias and other events, and never report complete cleanup.
                    self._alias_restore_failures = min(1000000, self._alias_restore_failures + 1)

    def _purge(self, *, release_finished_events=False):
        now = self._now()
        for token, state in list(self._states.items()):
            task = state['task']()
            request_gone = (state['request'] is not None and state['request']() is None)
            if (request_gone or state['event']() is None
                    or task is None or task.done() or task.cancelling()
                    or now-state['created'] > self.ttl_seconds):
                self._drop(token)
        active_attachments = {state['attachment'] for state in self._states.values()}
        for key, entry in list(self._entries.items()):
            event = entry['event']()
            if event is None: self._entries.pop(key, None)
            elif (now-entry['created'] > self.ttl_seconds
                    or release_finished_events and entry['ever_begun']
                    and entry['token'] not in active_attachments):
                self.invalidate(event)

    def attach(self, event, scope):
        try:
            scope = _scope(scope); self._purge(release_finished_events=True)
            existing = self._entry(event)
            if existing is not None:
                if existing['scope'] != scope:
                    self.invalidate(event); return False
                return self._allowed(event, scope)
            if id(event) in self._entries: self.invalidate(event)
            if len(self._entries) >= self.max_entries or not self._allowed(event, scope): return False
            trace = getattr(event, 'trace', None)
            if type(trace) is not self._trace_type or getattr(event, 'span', None) is not trace: return False
            token = object(); proxy = _TraceProxy(trace, self, event, token)
            self._entries[id(event)] = dict(event=weakref.ref(event), original=weakref.ref(trace),
                proxy=weakref.ref(proxy), token=token, scope=scope, created=self._now(), ever_begun=False)
            try:
                event.trace = event.span = proxy
            except BaseException:
                self.invalidate(event)
                raise
            return True
        except Exception:
            return False

    def begin_request(self, req, event, scope):
        try:
            self._purge(); scope = _scope(scope)
            # Reuse always revokes the previous epoch, including an untaken proof.
            previous = self._requests.get(id(req))
            if previous is not None: self._drop(previous)
            entry, task = self._entry(event), asyncio.current_task()
            if (type(req) is not self._request_type or entry is None or entry['scope'] != scope
                    or len(self._states) >= self.max_entries or task is None or task.cancelling()
                    or not self._allowed(event, scope)): return None
            token = object()
            self._states[token] = dict(request=weakref.ref(req), request_id=id(req), event=weakref.ref(event),
                event_id=id(event), mode='request_epoch', selection_seen=False,
                task=weakref.ref(task), scope=scope, attachment=entry['token'], created=self._now(),
                recorded=False, finished=False, taken=False, persona_id=None, proof=None)
            self._requests[id(req)] = token
            entry['ever_begun'] = True
            return SelectedPersonaEpoch(self._seal, token)
        except Exception:
            return None

    def begin_event(self, event, scope):
        """OnWaitingLLMRequest boundary, before the real session lock/build.

        Revoke first, including when a new scope is invalid or authorization
        later raises. No request exists yet; only an actual SDK selection frame
        may weakly bind its first request. The caller still must install this
        in the genuine public waiting hook; this module registers no handler.
        """
        self.invalidate(event)
        try:
            scope = _scope(scope); self._purge()
            task = asyncio.current_task()
            if (task is None or task.cancelling() or len(self._states) >= self.max_entries
                    or not self.attach(event, scope)): return None
            entry = self._entry(event)
            if entry is None or not self._allowed(event, scope): return None
            token = object()
            self._states[token] = dict(request=None, request_id=None, event=weakref.ref(event),
                event_id=id(event), mode='event_epoch', selection_seen=False,
                task=weakref.ref(task), scope=scope, attachment=entry['token'], created=self._now(),
                recorded=False, finished=False, taken=False, persona_id=None, proof=None)
            self._event_epochs[id(event)] = token
            entry['ever_begun'] = True
            return SelectedPersonaEventEpoch(self._seal, token)
        except Exception:
            return None

    def _current_state(self, state, *, allow_unbound=False):
        try:
            req = state['request']() if state['request'] is not None else None
            event, task = state['event'](), state['task']()
            entry = self._entry(event)
            if not (task is not None and task is asyncio.current_task()
                and not task.done() and not task.cancelling() and entry is not None
                and entry['token'] is state['attachment'] and entry['scope'] == state['scope']
                and self._now()-state['created'] <= self.ttl_seconds and self._allowed(event, state['scope'])):
                return False
            if state['mode'] == 'event_epoch':
                if self._states.get(self._event_epochs.get(id(event))) is not state: return False
                if state['request'] is None:
                    return allow_unbound and state['request_id'] is None
            return (req is not None and self._requests.get(id(req)) in self._states
                and self._states[self._requests[id(req)]] is state)
        except Exception:
            return False

    def _candidate(self, proxy, frame, action, fields):
        if (action != 'sel_persona' or set(fields) != {'persona_id', 'persona_toolset'}
                or not self._source.current() or frame.f_code is not self._source.code
                or frame.f_globals is not vars(self._source.module)): return None
        values = frame.f_locals
        try:
            req, event = values.get('req'), values.get('event')
            event_token = self._event_epochs.get(id(event))
            event_state = self._states.get(event_token)
            if (values.get('plugin_context') is not self.context or event is not proxy._event()
                    or type(req) is not self._request_type):
                if event_state is not None: self._drop(event_token)
                return None
            token = self._requests.get(id(req)); state = self._states.get(token)
            if event_state is not None:
                if event_state['request'] is None:
                    if state is not None:
                        self._drop(token); self._drop(event_token); return None
                    if not self._current_state(event_state, allow_unbound=True):
                        self._drop(event_token); return None
                    event_state['request'], event_state['request_id'] = weakref.ref(req), id(req)
                    self._requests[id(req)] = event_token
                elif event_state['request']() is not req:
                    self._drop(event_token); return None
                token, state = event_token, event_state
            entry = self._entry(event)
            if (state is None or state['request']() is not req or not self._current_state(state)
                    or entry is None or entry['proxy']() is not proxy
                    or state['attachment'] is not proxy._entry):
                if event_state is not None: self._drop(event_token)
                return None
            identity = values.get('persona_id')
            if state['mode'] == 'event_epoch':
                if state['selection_seen']:
                    self._drop(token); return None
                state['selection_seen'] = True
            if (type(identity) is not str or not 0 < len(identity) <= 256
                    or any(ord(char) < 32 for char in identity) or fields['persona_id'] != identity):
                if state['mode'] == 'event_epoch': self._drop(token)
                return None
            if state['recorded'] or state['finished']:
                self._drop(token); return None
            return token, identity
        finally:
            del values

    def _recorded(self, token, persona_id):
        state = self._states.get(token)
        if state is not None and self._current_state(state):
            state['recorded'], state['persona_id'] = True, persona_id

    def finish_request(self, epoch, *, succeeded):
        if type(epoch) is not SelectedPersonaEpoch or epoch._seal is not self._seal: return False
        state = self._states.get(epoch._token)
        if state is None or state['mode'] != 'request_epoch': return False
        if succeeded is not True or not state['recorded'] or not self._current_state(state):
            self._drop(epoch._token); return False
        if state['finished']: return False
        state['finished'] = True
        state['proof'] = SelectedPersonaProof(state['persona_id'], SDK_SOURCE_SHA256,
                                              _seal=self._seal, _token=epoch._token)
        return True

    def finish_event(self, req, event, scope):
        """OnLLMRequest boundary, after successful real build and selection.

        No Waiting epoch, different Task/request, missing selection, or failed
        scope validation can publish a proof. A failed build never reaches the
        genuine SDK request hook; callers must not fabricate that hook.
        """
        token = self._event_epochs.get(id(event)); state = self._states.get(token)
        if state is None or state['mode'] != 'event_epoch': return False
        try:
            if (state['event']() is not event or state['request'] is None
                    or state['request']() is not req or state['scope'] != _scope(scope)
                    or not state['recorded'] or not self._current_state(state)):
                self._drop(token); return False
            if state['finished']: return False
            state['finished'] = True
            state['proof'] = SelectedPersonaProof(state['persona_id'], SDK_SOURCE_SHA256,
                capture_mode='event_epoch', _seal=self._seal, _token=token)
            return True
        except Exception:
            self._drop(token); return False
        except BaseException:
            # The SDK public-hook dispatcher catches even cancellation. Revoke
            # before propagating so a later hook cannot finish this old epoch.
            self._drop(token)
            raise

    def take(self, req, event, scope):
        try:
            scope = _scope(scope); token = self._requests.get(id(req)); state = self._states.get(token)
            if (state is None or state['request']() is not req or state['event']() is not event
                    or state['scope'] != scope or not state['finished'] or state['taken']
                    or not self._current_state(state)): return None
            state['taken'] = True
            return state['proof']
        except Exception:
            return None

    def current(self, proof, req, event, scope):
        try:
            if type(proof) is not SelectedPersonaProof or proof._seal is not self._seal: return False
            state = self._states.get(proof._token)
            return (state is not None and state['proof'] is proof and state['taken']
                and state['request']() is req and state['event']() is event
                and state['scope'] == _scope(scope) and self._current_state(state))
        except Exception:
            return False

    def stop(self):
        self.active = False
        for entry in list(self._entries.values()):
            event = entry['event']()
            if event is not None: self.invalidate(event)
        self._entries.clear(); self._states.clear(); self._requests.clear(); self._event_epochs.clear()

    def diagnostics(self):
        self._purge()
        return dict(active=self.active, event_attachments=len(self._entries), request_epochs=len(self._states),
                    event_epochs=len(self._event_epochs), pending_event_epochs=sum(
                        state['mode'] == 'event_epoch' and state['request'] is None for state in self._states.values()),
                    max_entries=self.max_entries, sdk_source_sha256=SDK_SOURCE_SHA256,
                    alias_restore_failures=self._alias_restore_failures,
                    original_alias_restoration_complete=self._alias_restore_failures == 0,
                    grants_mc_authority=False, grants_write_or_send=False, reads_logs=False,
                    requires_real_before_after_request_integration=True, integrated_with_host=False)
