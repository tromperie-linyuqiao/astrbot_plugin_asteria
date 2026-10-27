"""Explicit ownership of the independent proactive plugin's existing tasks.

Construction is inert.  The former executor is fenced and naturally drained
before normal SDK shutdown; the native Host retains its original state files,
task identities and dates.  No model/send is cancelled or retried here.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from functools import partial
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
from queue import SimpleQueue
import sys
import threading
from types import MethodType

from .native_mc.task_drain import source_codes, task_chain, task_codes


LEGACY = 'astrbot_plugin_proactive_chat'
FLAG = 'living_proactive_chat_native_enabled'
CONFIG = 'living_proactive_chat'
RETIRED_SLOT = '_tls_native_proactive_chat_retired'
_ENTRY_METHODS = ('on_friend_message', 'on_group_message', 'on_after_message_sent',
    'check_and_chat', '_handle_auto_trigger_callback', '_handle_group_silence_callback')


class NativeProactiveChatFullOwner:
    def __init__(self, integrations):
        self.integrations, self.plugin, self.context = integrations, integrations.plugin, integrations.context
        self.adapter = None
        self.phase, self.generation, self.last_error = 'inactive', 0, None
        self.last_error_sha256 = None
        self._lock = asyncio.Lock()
        self._legacy = None
        self._source_paths, self._source_identities, self._source_codes = set(), {}, ()
        self._hook_slots, self._method_slots, self._page_slots = [], {}, []
        self._scheduler_state = None
        self._timer_snapshot, self._job_snapshot = [], []
        self._idle_cancelled = []
        self._sdk_hook_inventory = None
        self._old_off_attempted = self._old_off_confirmed = False
        self._drain = dict(tasks=None, threads=None, queued=None, unknown=None, scheduler_instances=None)

    @property
    def active(self):
        return bool(self.adapter is not None and self.adapter.active is True and self.legacy_closed())

    def _row(self):
        rows = [row for row in self.context.get_all_stars()
                if getattr(row, 'root_dir_name', None) == LEGACY]
        if len(rows) != 1:
            raise RuntimeError('original proactive registry is not unique')
        return rows[0]

    def _save(self, values):
        with self.integrations._config_lock:
            before = {key: (key in self.plugin.config, deepcopy(self.plugin.config.get(key))) for key in values}
            try:
                for key, value in values.items():
                    self.plugin.config[key] = deepcopy(value)
                self.plugin.config.save_config()
            except BaseException:
                for key, (present, value) in before.items():
                    if present:
                        self.plugin.config[key] = value
                    else:
                        self.plugin.config.pop(key, None)
                raise

    def _pin_sources(self, owner):
        if getattr(owner, 'context', None) is not self.context:
            raise RuntimeError('original proactive context identity changed')
        module = sys.modules.get(type(owner).__module__)
        if module is None or not getattr(module, '__file__', None):
            raise RuntimeError('original proactive source module missing')
        root = Path(module.__file__).resolve().parent
        if root.name != LEGACY:
            raise RuntimeError('unexpected original proactive source root')
        paths, identities, codes = set(), {}, []
        for relative, digest in _SOURCE_HASHES.items():
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('original proactive source missing or linked')
            data, st = path.read_bytes(), path.stat()
            if len(data) > 2 * 1024**2 or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('original proactive fixed source fingerprint changed')
            paths.add(str(path))
            identities[str(path)] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            codes.extend(source_codes(data, str(path)))
        for name in _ENTRY_METHODS:
            method = getattr(owner, name, None)
            if (not inspect.ismethod(method) or method.__self__ is not owner
                    or str(Path(method.__func__.__code__.co_filename).resolve()) not in paths):
                raise RuntimeError('original proactive runtime entry identity changed')
        self._legacy = owner
        self._source_paths, self._source_identities, self._source_codes = paths, identities, tuple(codes)

    def _source_current(self):
        try:
            return bool(self._source_identities) and all(
                not Path(filename).is_symlink() and
                (lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == identity)(Path(filename).stat())
                for filename, identity in self._source_identities.items())
        except OSError:
            return False

    @staticmethod
    def _closed_callback(callback):
        if inspect.isasyncgenfunction(callback):
            async def generator(*args, **kwargs):
                if False:
                    yield None
            return generator
        if inspect.iscoroutinefunction(callback):
            async def coroutine(*args, **kwargs):
                return None
            return coroutine
        def function(*args, **kwargs):
            return None
        return function

    def _capture_timers(self):
        owner, loop = self._legacy, asyncio.get_running_loop()
        rows = []
        for kind, name in (('auto', 'auto_trigger_timers'), ('group', 'group_timers')):
            values = getattr(owner, name, None)
            if not isinstance(values, dict) or len(values) > 4096:
                raise RuntimeError('original proactive timer inventory unknown')
            for session, handle in values.items():
                if (not isinstance(session, str) or not isinstance(handle, asyncio.TimerHandle)
                        or handle._loop is not loop or handle.cancelled()):
                    raise RuntimeError('original proactive timer identity unknown')
                due = handle.when()
                if not isinstance(due, (int, float)) or not math.isfinite(due):
                    raise RuntimeError('original proactive timer deadline unknown')
                rows.append(dict(kind=kind, session=session, handle=handle, due=due,
                    callback=handle._callback, args=handle._args, context=handle._context,
                    epoch_due=self._wall_time() + due - loop.time()))
        return rows

    @staticmethod
    def _wall_time():
        import time
        return time.time()

    def _capture_jobs(self):
        scheduler = getattr(self._legacy, 'scheduler', None)
        jobs = scheduler.get_jobs() if scheduler is not None else []
        if not isinstance(jobs, list) or len(jobs) > 4096:
            raise RuntimeError('original proactive date inventory unknown')
        rows = []
        for job in jobs:
            callback, args, due = job.func, job.args, job.next_run_time
            gate = self._method_slots.get('check_and_chat', (None, None, None))[2]
            if (not inspect.ismethod(callback) or callback.__self__ is not self._legacy
                    or (callback.__func__.__name__ != 'check_and_chat' and callback is not gate) or len(args) != 1
                    or not isinstance(args[0], str) or str(job.id) != args[0]
                    or not isinstance(due, datetime) or not math.isfinite(due.timestamp())
                    or type(job.trigger).__name__ != 'DateTrigger' or job.kwargs):
                raise RuntimeError('original proactive job requires explicit task reconciliation')
            rows.append(dict(id=job.id, session=args[0], due=due.timestamp()))
        return rows

    async def _freeze_admission(self):
        if self._legacy is None or not self._source_current():
            raise RuntimeError('current original proactive source is required')
        owner, scheduler = self._legacy, getattr(self._legacy, 'scheduler', None)
        if scheduler is None or getattr(scheduler, 'state', None) not in (1, 2):
            raise RuntimeError('original proactive scheduler state unknown')
        self._scheduler_state = scheduler.state
        self._timer_snapshot = self._capture_timers()
        if any(row['kind'] == 'group' for row in self._timer_snapshot):
            raise RuntimeError('existing group proactive timers require a compatible group delivery lane')
        self._capture_jobs()  # validate before changing admission
        from astrbot.core.star.star_handler import EventType, star_handlers_registry
        from astrbot.core.star.filter.event_message_type import EventMessageType, EventMessageTypeFilter
        registry = getattr(star_handlers_registry, '_handlers', None)
        if not isinstance(registry, list) or len(registry) > 4096:
            raise RuntimeError('normal SDK proactive hook inventory unavailable')
        module = type(owner).__module__
        selected = [item for item in registry if getattr(item, 'handler_module_path', None) == module]
        required = {'on_friend_message', 'on_group_message', 'on_after_message_sent'}
        # SDK 4.26.6 binds callbacks with functools.partial(function, star).
        # Its metadata retains handler_name; the bound partial has no __name__.
        names = [getattr(item, 'handler_name', None) for item in selected]
        self._sdk_hook_inventory = dict(module=module, count=len(selected),
            required_present=sorted(required.intersection(name for name in names if isinstance(name, str))),
            callbacks=[dict(name=getattr(item, 'handler_name', None), enabled=getattr(item, 'enabled', None),
                shape='partial' if type(item.handler) is partial else 'bound_method' if inspect.ismethod(item.handler) else 'other')
                for item in selected])
        if set(names) != required or any(names.count(name) != 1 for name in required):
            raise RuntimeError('original proactive SDK hooks are incomplete')
        for metadata in selected:
            name, callback = metadata.handler_name, metadata.handler
            expected = getattr(owner, name)
            if (not inspect.ismethod(expected) or expected.__self__ is not owner
                    or metadata.handler_full_name != module + '_' + name
                    or type(getattr(metadata, 'enabled', None)) is not bool):
                raise RuntimeError('original proactive SDK hook metadata identity changed')
            bound = (type(callback) is partial and callback.func is expected.__func__
                and len(callback.args) == 1 and callback.args[0] is owner and not callback.keywords)
            direct = (inspect.ismethod(callback) and callback.__self__ is owner
                and callback.__func__ is expected.__func__)
            if not (bound or direct):
                raise RuntimeError('original proactive SDK callback binding changed')
            if name == 'on_after_message_sent':
                if metadata.event_type is not EventType.OnAfterMessageSentEvent:
                    raise RuntimeError('original proactive sent hook event type changed')
            else:
                target = (EventMessageType.PRIVATE_MESSAGE if name == 'on_friend_message'
                    else EventMessageType.GROUP_MESSAGE)
                filters = getattr(metadata, 'event_filters', None)
                if (metadata.event_type is not EventType.AdapterMessageEvent or not isinstance(filters, list)
                        or len(filters) > 32 or not any(type(value) is EventMessageTypeFilter
                            and value.event_message_type is target for value in filters)):
                    raise RuntimeError('original proactive message hook event filter changed')
        for metadata in selected:
            original = metadata.handler
            wrapped = self._closed_callback(original)
            metadata.handler = wrapped
            self._hook_slots.append((metadata, original, wrapped))
        for name in _ENTRY_METHODS:
            original = getattr(owner, name)
            replacement = MethodType(self._closed_callback(original), owner)
            self._method_slots[name] = (name in vars(owner), original, replacement)
            setattr(owner, name, replacement)
        scheduler.pause()  # APS jobs, their IDs and original dates stay intact
        web = getattr(owner, 'web_admin_server', None)
        app = getattr(web, 'app', None)
        routes = getattr(app, 'routes', []) if app is not None else []
        if not isinstance(routes, list) or len(routes) > 4096:
            raise RuntimeError('original proactive web route inventory unknown')
        for route in routes:
            methods = getattr(route, 'methods', None)
            websocket = type(route).__name__ == 'APIWebSocketRoute'
            if not websocket and not (methods and any(str(method).upper() not in ('GET', 'HEAD', 'OPTIONS') for method in methods)):
                continue
            dependant = getattr(route, 'dependant', None)
            if dependant is None or not callable(getattr(dependant, 'call', None)):
                raise RuntimeError('original proactive write route call unavailable')
            original, endpoint = dependant.call, route.endpoint
            if websocket:
                async def closed_websocket(websocket):
                    await websocket.close(code=1012)
                replacement = closed_websocket
            else:
                async def closed_http(*args, **kwargs):
                    from starlette.responses import JSONResponse
                    return JSONResponse(dict(ok=False, error='旧主动消息正在交接，请使用 TLS 原生入口。'), status_code=409)
                replacement = closed_http
            dependant.call = replacement
            route.endpoint = replacement
            self._page_slots.append((route, dependant, original, endpoint, replacement))
        connections = getattr(web, '_ws_connections', []) if web is not None else []
        if not isinstance(connections, list) or len(connections) > 4096:
            raise RuntimeError('original proactive websocket inventory unknown')
        for connection in tuple(connections):
            await connection.close(code=1012)

    def _cancel_idle_helpers(self):
        owner = self._legacy
        helpers = [(owner, '_heartbeat_task'),
            (getattr(owner, 'notification_center', None), '_poll_task'),
            (getattr(owner, 'web_admin_server', None), '_token_cleanup_task')]
        for holder, name in helpers:
            task = getattr(holder, name, None) if holder is not None else None
            if task is None or task.done() or any(old is task for _, _, old in self._idle_cancelled):
                continue
            codes, unknown = task_codes(task)
            if not unknown and asyncio.sleep.__code__ in codes:
                task.cancel()  # only an identified idle maintenance sleep, never business IO
                self._idle_cancelled.append((holder, name, task))

    def _scan(self):
        current, tasks, unknown = asyncio.current_task(), set(), 0
        inventory = asyncio.all_tasks()
        if len(inventory) > 4096:
            raise RuntimeError('proactive coroutine inventory exceeds bound')
        web = getattr(self._legacy, 'web_admin_server', None)
        infrastructure = getattr(web, 'server_task', None)
        for task in inventory:
            if task is current or task.done() or task is infrastructure:
                continue
            found, opaque = task_chain(task, self._source_codes)
            unknown += int(opaque)
            if found:
                tasks.add(task)
        frames, threaded = sys._current_frames(), 0
        if len(frames) > 512:
            raise RuntimeError('proactive thread inventory exceeds bound')
        try:
            for ident, frame in frames.items():
                if ident == threading.get_ident():
                    continue
                found = False
                for _ in range(96):
                    if frame is None:
                        break
                    found = found or str(Path(frame.f_code.co_filename).resolve()) in self._source_paths
                    frame = frame.f_back
                else:
                    unknown += int(frame is not None)
                threaded += int(found)
        finally:
            del frames
            try:
                del frame
            except UnboundLocalError:
                pass
        queued = 0
        executor = getattr(asyncio.get_running_loop(), '_default_executor', None)
        if executor is not None:
            if type(executor) is not ThreadPoolExecutor or type(executor._work_queue) is not SimpleQueue:
                raise RuntimeError('proactive executor inventory unknown')
            queued = executor._work_queue.qsize()
        instances = 0
        scheduler = getattr(self._legacy, 'scheduler', None)
        for executor in getattr(scheduler, '_executors', {}).values():
            values = getattr(executor, '_instances', None)
            if not isinstance(values, dict) or len(values) > 4096:
                raise RuntimeError('original APS submitted-job inventory unknown')
            if any(type(value) is not int or value < 0 for value in values.values()):
                raise RuntimeError('original APS submitted-job count unknown')
            instances += sum(values.values())
        if type(queued) is not int or queued < 0:
            raise RuntimeError('proactive queued work count unknown')
        self._drain = dict(tasks=len(tasks), threads=threaded, queued=queued, unknown=unknown,
            scheduler_instances=instances)
        return tasks

    async def _wait_drained(self, *, timeout=30, cancel_idle=True):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if not self._source_current():
                raise RuntimeError('original proactive source changed during transition')
            if cancel_idle:
                self._cancel_idle_helpers()
            tasks = self._scan()
            if not any(self._drain.values()):
                return
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                raise RuntimeError('original proactive model/send/executor has not drained')
            if tasks:
                await asyncio.wait(tasks, timeout=min(.1, left))
            else:
                await asyncio.sleep(min(.05, left))

    def _capture_final_state(self):
        owner = self._legacy
        if not isinstance(getattr(owner, 'session_data', None), dict):
            raise RuntimeError('original proactive state inventory unknown')
        if getattr(owner, 'manual_trigger_sessions', None):
            raise RuntimeError('original proactive manual-send outcome remains in flight')
        # A normally finishing model is allowed to write its actual next date.
        self._job_snapshot = self._capture_jobs()
        self._state_snapshot = deepcopy(owner.session_data)
        live = self._capture_timers()
        original = {(row['kind'], row['session']): row for row in self._timer_snapshot}
        for row in live:
            original[(row['kind'], row['session'])] = row
        self._timer_snapshot = list(original.values())

    def _record_retirement(self):
        row, owner = self._row(), self._legacy
        if row.activated is not False or getattr(owner.scheduler, 'running', None) is not False:
            raise RuntimeError('normal original proactive shutdown is not confirmed')
        self._scan()
        if any(self._drain.values()):
            raise RuntimeError('original proactive work remains after normal shutdown')
        path = Path(owner.session_data_file)
        if path.is_symlink() or path.stat().st_size > 8 * 1024**2:
            raise RuntimeError('original proactive state file identity unknown')
        actual = json.loads(path.read_bytes())
        if actual != self._state_snapshot:
            raise RuntimeError('normal original shutdown did not preserve the final task state')
        setattr(self.context, RETIRED_SLOT, dict(schema='tls.proactive.retired.r60.v1',
            pid=os.getpid(), context=self.context, owner=owner, drained=True,
            source_paths=tuple(self._source_paths), source_identities=dict(self._source_identities),
            source_codes=self._source_codes, jobs=deepcopy(self._job_snapshot),
            timers=tuple(self._timer_snapshot), configuration=deepcopy(dict(owner.config))))
        self._old_off_confirmed = True

    def legacy_closed(self):
        try:
            row = self._row()
            if row.activated is not False:
                return False
            old = getattr(row, 'star_cls', None)
            if old is None:
                return True  # a cold SDK registry has no former RAM executor
            record = getattr(self.context, RETIRED_SLOT, None)
            return (isinstance(record, dict) and record.get('context') is self.context
                and record.get('pid') == os.getpid() and record.get('owner') is old
                and record.get('drained') is True and getattr(old.scheduler, 'running', None) is False)
        except Exception:
            return False

    async def _prepare_native(self):
        if not self.legacy_closed() or getattr(self.integrations, '_closed', False):
            raise RuntimeError('confirmed retired proactive executor and a live TLS Host required')
        current = getattr(self.integrations, 'proactive_chat', None)
        if current is not None and getattr(current, 'active', False):
            if self.adapter is current:
                return current
            raise RuntimeError('another native proactive instance is active')
        if current is not None and any(not task.done() for task in getattr(current, '_running', ())):
            raise RuntimeError('the preceding native proactive instance is still draining')
        adapter = self.integrations._make_proactive_chat()
        if adapter is None or adapter.context is not self.context:
            raise RuntimeError('actual native proactive Host unavailable')
        self.adapter = adapter
        await adapter.prepare()
        blockers = adapter.migration_blockers()
        if blockers:
            raise RuntimeError('enabled proactive configuration requires an unavailable unified feature')
        return adapter

    async def _transfer_dates(self):
        adapter = self.adapter
        record = getattr(self.context, RETIRED_SLOT, None)
        if not isinstance(record, dict) or record.get('drained') is not True:
            return
        first_transfer = record.get('transferred') is not True
        if not first_transfer:
            # The former legacy dates are a one-time handoff. Later TLS
            # reloads may only restore the immediately preceding native RAM
            # snapshot, never overwrite later dates with the retired plugin.
            snapshot = record.get('native_snapshot')
            previous = record.get('native_adapter')
            if (not isinstance(snapshot, dict) or previous is None
                    or previous is adapter or getattr(previous, '_closed', False) is not True
                    or any(not task.done() for task in getattr(previous, '_running', ()))):
                return
            jobs, timers = snapshot.get('jobs', ()), snapshot.get('timers', ())
            record['native_snapshot'] = None
        else:
            jobs, timers = record.get('jobs', ()), record.get('timers', ())
        if len(jobs) + len(timers) > 8192:
            raise RuntimeError('retired proactive task inventory exceeds bound')
        state_changed = False
        for value in jobs:
            session, due = value['session'], value['due']
            # The old auto-trigger branch stored only its interval metadata
            # in JSON. Materialize its already-existing APS date, preserving
            # every other field, so a process restart retains that same task.
            if first_transfer:
                info = adapter.session_data.get(session)
                if not isinstance(info, dict):
                    raise RuntimeError('observed proactive date has no original session state')
                if info.get('next_trigger_time') != due:
                    info['next_trigger_time'] = due
                    state_changed = True
            if due + 60 < adapter.clock():
                if session not in adapter._overdue:
                    adapter._overdue.append(session)
                continue
            adapter.scheduler.add_job(adapter.check_and_chat, 'date',
                run_date=datetime.fromtimestamp(due, adapter.timezone), args=[session],
                id=value['id'], replace_existing=True)
        # Native activate creates default auto dates; replace them with each
        # observed old TimerHandle's exact deadline, without sampling a delay.
        for value in timers:
            if value['kind'] != 'auto':
                raise RuntimeError('retired group timer cannot enter the private delivery lane')
            session = value['session']
            cfg = adapter._get_session_config(session)
            settings = cfg.get('auto_trigger_settings', {}) if cfg else {}
            minutes = settings.get('auto_trigger_after_minutes', 5)
            if not settings.get('enable_auto_trigger', False):
                continue
            identity = 'auto:' + session
            job = adapter.scheduler.add_job(adapter._handle_auto_trigger_callback, 'date',
                run_date=datetime.fromtimestamp(value['epoch_due'], adapter.timezone),
                args=[session, minutes], id=identity, replace_existing=True)
            adapter.auto_trigger_timers[session] = job
        if state_changed:
            await adapter._save_data_internal()
        record.update(transferred=True, native_adapter=adapter)

    async def _unfreeze_existing(self):
        if self._old_off_attempted or not self._source_current() or self._row().activated is not True:
            raise RuntimeError('original proactive shutdown outcome requires explicit reconciliation')
        for holder, original, wrapped in self._hook_slots:
            if holder.handler is not wrapped:
                raise RuntimeError('original proactive hook fence was replaced')
        for name, (had_slot, original, wrapped) in self._method_slots.items():
            if vars(self._legacy).get(name) is not wrapped:
                raise RuntimeError('original proactive entry fence was replaced')
        for route, dependant, original, endpoint, wrapped in self._page_slots:
            if dependant.call is not wrapped or route.endpoint is not wrapped:
                raise RuntimeError('original proactive write fence was replaced')
        for holder, original, wrapped in self._hook_slots:
            holder.handler = original
        for name, (had_slot, original, wrapped) in self._method_slots.items():
            if had_slot:
                setattr(self._legacy, name, original)
            else:
                delattr(self._legacy, name)
        for route, dependant, original, endpoint, wrapped in self._page_slots:
            dependant.call, route.endpoint = original, endpoint
        check_gate = self._method_slots.get('check_and_chat', (None, None, None))[2]
        check_original = self._method_slots.get('check_and_chat', (None, None, None))[1]
        if check_gate is not None:
            for job in self._legacy.scheduler.get_jobs():
                if job.func is check_gate:
                    job.modify(func=check_original)
        self._hook_slots.clear(); self._method_slots.clear(); self._page_slots.clear()
        loop = asyncio.get_running_loop()
        for value in self._timer_snapshot:
            mapping = getattr(self._legacy, 'auto_trigger_timers' if value['kind'] == 'auto' else 'group_timers')
            old = value['handle']
            if not old.cancelled() and old._scheduled:
                continue
            if mapping.get(value['session']) is old:
                mapping[value['session']] = loop.call_at(value['due'], value['callback'],
                    *value['args'], context=value['context'])
        if self._scheduler_state == 1:
            self._legacy.scheduler.resume()
        # The only cancelled helpers were idle maintenance sleeps. Restarting
        # notification/token helpers does not create or randomize a chat task.
        for holder, name, task in self._idle_cancelled:
            if not task.done():
                await asyncio.wait({task}, timeout=1)
            if name == '_heartbeat_task' and task.done():
                holder._heartbeat_task = asyncio.create_task(holder._heartbeat_loop())
            elif name == '_poll_task' and task.done():
                holder._poll_task = None
                await holder.start()
            # Token cleanup is housekeeping only; leave it closed rather than
            # reopening a standalone server or invalidating authentication.
        self._idle_cancelled.clear()

    async def activate(self):
        async with self._lock:
            if self.active:
                return self.status()
            if self._old_off_attempted and not self._old_off_confirmed:
                raise RuntimeError('original proactive shutdown outcome unknown; use status only')
            try:
                row = self._row()
                if getattr(row, 'activated', None) is True:
                    owner = getattr(row, 'star_cls', None)
                    if owner is None:
                        raise RuntimeError('actual original proactive instance missing')
                    self._pin_sources(owner)
                    value = json.loads(json.dumps(dict(owner.config), ensure_ascii=False, allow_nan=False))
                    existing = self.plugin.config.get(CONFIG)
                    if (isinstance(existing, dict) and existing and existing != value
                            and not self.integrations._native_config_is_default(CONFIG,existing)):
                        raise RuntimeError('native and original proactive configuration differ; reconcile before switching')
                    self._save({CONFIG: value})
                    probe = self.integrations._make_proactive_chat()
                    if probe is None or probe.context is not self.context or probe.migration_blockers():
                        raise RuntimeError('enabled original proactive features are not supported by the current unified lane')
                    delivery = getattr(getattr(probe, 'runtime', None), 'delivery', None)
                    if delivery is None or getattr(delivery, 'active', False) is not True:
                        raise RuntimeError('existing unified proactive delivery lane is inactive')
                    self.phase = 'closing_legacy_admission'
                    await self._freeze_admission()
                    self.phase = 'draining_legacy'
                    await self._wait_drained()
                    self._capture_final_state()
                    self._old_off_attempted = True
                    await self.context._star_manager.turn_off_plugin(LEGACY)
                    await self._wait_drained(cancel_idle=False)
                    self._record_retirement()
                elif not self.legacy_closed():
                    raise RuntimeError('original proactive RAM executor retirement is unconfirmed')
                adapter = await self._prepare_native()
                await adapter.activate()
                await self._transfer_dates()
                self._save({FLAG: True})
                self.phase, self.last_error, self.last_error_sha256 = 'native', None, None
                self.generation += 1
                return self.status()
            except BaseException as exc:
                self.last_error = type(exc).__name__
                self.last_error_sha256 = hashlib.sha256(str(exc).encode('utf-8')).hexdigest()
                self.phase = 'blocked' if self._old_off_attempted else 'transition_failed'
                if not self._old_off_attempted and (self._hook_slots or self._method_slots or self._page_slots):
                    try:
                        await self._unfreeze_existing()
                        self.phase = 'legacy_restored'
                    except BaseException:
                        self.phase = 'legacy_restore_unknown'
                if self.adapter is not None and self.adapter.active:
                    await self.adapter.stop()
                raise

    async def start_if_configured(self):
        if self.plugin.config.get(FLAG) is not True:
            return self.status()
        async with self._lock:
            if self.active:
                return self.status()
            if not self.legacy_closed():
                self.phase = 'blocked_legacy_owner'
                raise RuntimeError('persisted native proactive owner cannot overlap an original executor')
            adapter = await self._prepare_native()
            await adapter.activate()
            await self._transfer_dates()
            self.phase, self.last_error, self.last_error_sha256 = 'native', None, None
            self.generation += 1
            return self.status()

    async def _stop_locked(self, persist):
        if persist:
            self._save({FLAG: False})
        if self.adapter is not None:
            snapshot = self._native_date_snapshot()
            result = await self.adapter.stop()
            if result.get('pending_operations') != 0:
                self.phase = 'draining_native'
                raise RuntimeError('native proactive generation/send still draining; keep original closed')
            await self.adapter.close()
            record = getattr(self.context, RETIRED_SLOT, None)
            if (isinstance(record, dict) and record.get('context') is self.context
                    and record.get('native_adapter') is self.adapter):
                record['native_snapshot'] = snapshot
        self.phase = 'native_stopped'
        return self.status()

    def _native_date_snapshot(self):
        jobs, timers = [], []
        adapter = self.adapter
        for job in adapter.scheduler.get_jobs():
            if not job.args:
                raise RuntimeError('native proactive date identity unknown')
            session, due = job.args[0], job.next_run_time.timestamp()
            if job.id == session:
                jobs.append(dict(id=job.id, session=session, due=due))
            elif job.id == 'auto:' + session:
                timers.append(dict(kind='auto', session=session, epoch_due=due))
            else:
                raise RuntimeError('native proactive date kind unknown')
        return dict(jobs=jobs, timers=timers)

    async def stop(self):
        async with self._lock:
            return await self._stop_locked(True)

    async def close(self):
        # TLS hot reload retains persisted ownership and never turns the old
        # executor on.  Actual pending operation references remain reachable.
        async with self._lock:
            return await self._stop_locked(False)

    async def restore_legacy(self):
        async with self._lock:
            await self._stop_locked(True)
            if self.adapter is not None and (self.adapter._unknown or self.adapter._frames):
                raise RuntimeError('native proactive unknown outcomes require per-task reconciliation before legacy restart')
            row = self._row()
            if row.activated is True:
                await self._unfreeze_existing()
            elif self.legacy_closed():
                if self.adapter is not None and self.adapter._overdue:
                    raise RuntimeError('legacy startup would clear overdue dates; reconcile them before restoring')
                await self.context._star_manager.turn_on_plugin(LEGACY)
                if self._row().activated is not True:
                    self.phase = 'legacy_restore_unknown'
                    raise RuntimeError('normal original proactive startup outcome unknown')
                setattr(self.context, RETIRED_SLOT, None)
                self._hook_slots.clear(); self._method_slots.clear(); self._page_slots.clear()
                self._timer_snapshot.clear(); self._job_snapshot.clear(); self._idle_cancelled.clear()
                self._old_off_attempted = self._old_off_confirmed = False
            else:
                raise RuntimeError('original proactive shutdown outcome unknown; do not create a second executor')
            self.phase, self.last_error, self.last_error_sha256 = 'legacy_restored', None, None
            return self.status()

    def status(self):
        try:
            row = self._row()
            old_active = getattr(row, 'activated', None)
        except Exception:
            old_active = None
        return dict(ok=True, protocol='tls.native_proactive.full_owner.r60.v1',
            phase=self.phase, active=self.active, configured=self.plugin.config.get(FLAG) is True,
            generation=self.generation, original_plugin_active=old_active,
            old_off_attempted=self._old_off_attempted, old_off_confirmed=self._old_off_confirmed,
            legacy_closed=self.legacy_closed(), source_current=self._source_current(),
            drain=dict(self._drain), task_dates_preserved=True,
            sdk_hooks=self._sdk_hook_inventory,
            native=self.adapter.status() if self.adapter is not None else None,
            last_error=self.last_error, last_error_sha256=self.last_error_sha256, testing_performed=False)


_SOURCE_HASHES = {
    '__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'main.py': 'e1399b60656e3d0f0373c5f2b15979772cd77f0822cd69f73ff0bf61049c1001',
    'core/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'core/chat_flow.py': '14f948f7b908587081644224b2e8105e61089976508c1d6d97e9dae153d88973',
    'core/data_storage.py': '8b6ae9708d47dae3c5c4b8676df86dee5a126d0eb99d6d462305c91655c1fe64',
    'core/llm_adapter.py': '3b4e1d7760946f199ec6530f6ed7a4c6463f187a3270a5979a8051d603b9b6b0',
    'core/message_events.py': '3664d8b9fdda3b4959d6fa010215a6547948e773ceb9acc3b1e723906f641c30',
    'core/message_sender.py': '1c8f614cf0dc33c560ad559d05a6638aa07fe4fa16da4122394a4a2de27fdd4e',
    'core/notification_center.py': '94036f4666f9c8f309b84d9937d2386064a3a7fed41e97d2cd281f6f4803d735',
    'core/plugin_lifecycle.py': '1cbcf4da46fbe8642e237307671e87a10ee9cf077c0f38576e153e786b695415',
    'core/session_config.py': '9de96f86a8ff4012f20a063201496f8b49527844f796ac50a2db29a414c5d2e2',
    'core/session_override_manager.py': '64812baa76a87084eb2cbe31de85e49bc45a7de8a92358b482d0370abb6d662f',
    'core/session_parser.py': '924b609fccc9c9364ee55b752e590af9700c45052c694857a588e4ae1e8131c0',
    'core/task_scheduler.py': 'a09cb9575d6bd10db73ca67965d5fa5887d2aad4e50dc550e8b93becedd8d4af',
    'core/telemetry_manager.py': 'aa518e0802752b79fd267375b016108160a3157df0a0e0eace152b0df8ea7d73',
    'core/web_admin_server.py': 'e0735df85d5f04af88da04234831e03efdc09eda87102b007185ea7d442ebe34',
    'utils/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'utils/time_utils.py': '66b6eb691f548db16461210675f12d4ee8fc219cc44feb8254e7fc39dacb6920',
    'utils/version.py': 'bb4df5fc3b06d1cb5c04c4d84ece95c8a5192783a38d9d79ed4d0514f91d36b3',
}

# Keep the concise controller spelling available to existing integration code.
NativeProactiveFullOwner = NativeProactiveChatFullOwner
