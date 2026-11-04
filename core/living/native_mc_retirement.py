"""Explicit retirement of real pre-anchor MC owners retained in this process.

This never adopts an old service for new work. Inspection is read-only. Only
stopped original owners and their exact idle dispatcher timers can be closed.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
from pathlib import Path
import stat
from types import CodeType, CoroutineType, MethodType
import uuid

from .native_mc.host_adapter import NativeMemoryCompanion
from .native_mc.service import MemoryCompanionService

SCHEMA = 'tls.mc.pre-anchor.retirement.v1'
SLOT = '_tls_native_mc_lifecycle'
MAX_OWNERS = 128
DISPATCHERS = (
    ('_maintenance_dispatch_task', '_lifecycle_maintenance_dispatch_loop'),
    ('_portrait_dispatch_task', '_portrait_daily_dispatch_loop'),
    ('_wal_checkpoint_task', '_wal_checkpoint_loop'),
)


def _shape(code):
    """Compare executable method bodies across import generations, not lines."""
    if type(code) is not CodeType:
        return None
    return (code.co_code, code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
        code.co_flags, code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
        tuple(_shape(value) if type(value) is CodeType else value for value in code.co_consts),
        code.co_exceptiontable)


def _method(instance, name):
    bound = getattr(instance, name, None)
    if (type(bound) is not MethodType or bound.__self__ is not instance
            or bound.__func__ is not vars(type(instance)).get(name)):
        raise RuntimeError('pre_anchor_method_changed')
    return bound


class NativeMCRetirement:
    def __init__(self, current, directory):
        self.current, self.context, self.directory = current, current.context, Path(directory).resolve()
        self._checks = None
        self._inventory = None

    def _owners(self):
        record = getattr(self.context, SLOT, None)
        if record is not None:
            if (type(record) is not dict or record.get('schema') != SCHEMA
                    or record.get('context') is not self.context or record.get('directory') != self.directory
                    or record.get('loop') is not asyncio.get_running_loop()):
                raise RuntimeError('native_lifecycle_already_recorded')
            owners = record.get('owners')
            if type(owners) not in (tuple, list) or not 0 < len(owners) <= MAX_OWNERS:
                raise RuntimeError('pre_anchor_original_references_missing')
            return tuple(owners)
        # Follow actual references to this shared context, rather than copying
        # every tracked object in a long-running AstrBot process. Materialised
        # instance dictionaries need one further reverse edge to their owner.
        references = gc.get_referrers(self.context)
        if len(references) > 16384:
            raise RuntimeError('pre_anchor_context_references_exceed_bound')
        owners = []
        current_kind = type(self.current)
        seen = set()
        dictionaries, candidates = [], []
        for reference in references:
            if type(reference) is dict:
                if (reference.get('context') is not self.context
                        or not {'adapter', 'integrations', 'plugin', 'phase'} <= reference.keys()):
                    continue
                dictionaries.append(reference)
            else:
                candidates.append(reference)
        if len(dictionaries) > MAX_OWNERS + 16:
            raise RuntimeError('pre_anchor_owner_dictionaries_exceed_bound')
        # One further GC traversal for all relevant dictionaries, rather than
        # one traversal per old import generation on the server's event loop.
        if dictionaries:
            candidates.extend(gc.get_referrers(*dictionaries))
        if len(candidates) > 16384:
            raise RuntimeError('pre_anchor_owner_references_exceed_bound')
        for item in candidates:
            kind = type(item)
            if (item is self.current or id(item) in seen
                    or kind.__module__ != current_kind.__module__ or kind.__name__ != current_kind.__name__
                    or vars(item).get('context') is not self.context):
                continue
            seen.add(id(item))
            adapter = vars(item).get('adapter')
            if adapter is None or Path(adapter.data_dir).resolve() != self.directory:
                continue
            service = getattr(adapter, 'service', None)
            if service is not None and not service.store._closed:
                owners.append(item)
        self._inventory = dict(open_store_owners=len(owners), limit=MAX_OWNERS)
        if len(owners) > MAX_OWNERS:
            raise RuntimeError('pre_anchor_owner_inventory_exceeds_bound')
        return tuple(owners)

    def _inspect(self):
        rows = [row for row in self.context.get_all_stars()
                if getattr(row, 'root_dir_name', None) == 'astrbot_plugin_virtual_body'
                and getattr(row, 'activated', None) is True]
        if (len(rows) != 1 or getattr(rows[0], 'star_cls', None) is not self.current.plugin
                or getattr(self.current.plugin, '_native_server_integrations', None) is not self.current.integrations
                or getattr(self.current.plugin, '_stopping', None) is not False):
            raise RuntimeError('pre_anchor_current_plugin_unverified')
        owners = self._owners()
        if not owners:
            raise RuntimeError('pre_anchor_original_owner_not_found')
        idle = set()
        for owner in owners:
            adapter, service = owner.adapter, owner.adapter.service
            integrations, plugin = owner.integrations, owner.plugin
            checks = dict(pre_anchor=not hasattr(owner, '_native_record'), owner_lock_idle=not owner._lock.locked(),
                integration_context=integrations.context is self.context,
                integration_plugin=integrations.plugin is plugin,
                original_owner=getattr(integrations, '_mc_full_owner', None) is owner,
                original_adapter=integrations.mc_full is adapter,
                former_plugin=plugin is not self.current.plugin and integrations is not self.current.integrations,
                plugin_stopping=getattr(plugin, '_stopping', None) is True,
                adapter_context=adapter.context is self.context, adapter_lock_idle=not adapter._lifecycle_lock.locked(),
                adapter_directory=Path(adapter.data_dir).resolve() == self.directory,
                service_context=service.context is self.context,
                service_directory=Path(service.data_dir).resolve() == self.directory,
                runtime_inactive=owner.runtime is not None and owner.runtime.status().get('active') is False)
            if not all(checks.values()):
                self._checks = checks
                raise RuntimeError('pre_anchor_owner_not_proven_stopped')
            for actual, expected in ((adapter, NativeMemoryCompanion), (service, MemoryCompanionService)):
                if (type(actual).__module__ != expected.__module__ or type(actual).__name__ != expected.__name__):
                    raise RuntimeError('pre_anchor_native_identity_changed')
            persist = _method(owner, 'persist_config')
            if (type(service.persist_native_config) is not MethodType
                    or service.persist_native_config.__self__ is not owner
                    or service.persist_native_config.__func__ is not persist.__func__):
                raise RuntimeError('pre_anchor_original_controller_missing')
            _method(owner, 'close')
            _method(adapter, 'close')
            stop = _method(adapter, 'begin_stop')
            if _shape(stop.__func__.__code__) != _shape(NativeMemoryCompanion.begin_stop.__code__):
                raise RuntimeError('pre_anchor_admission_stop_unverified')
            save_usage = _method(service, '_save_token_usage')
            if (_shape(save_usage.__func__.__code__) != _shape(MemoryCompanionService._save_token_usage.__code__)
                    or Path(service.token_usage_path).resolve() != self.directory / 'memory_companion_token_usage.json'):
                raise RuntimeError('pre_anchor_usage_writer_unverified')
            _method(adapter, '_work')
            for field, method in DISPATCHERS:
                task = getattr(service, field, None)
                if task is None or task.done():
                    continue
                coro = asyncio.Task.get_coro(task)
                actual = vars(type(service)).get(method)
                expected = vars(MemoryCompanionService).get(method)
                if (type(coro) is CoroutineType and coro.cr_frame is not None
                        and coro.cr_frame.f_locals.get('self') is service
                        and coro.cr_code is getattr(actual, '__code__', None)
                        and _shape(coro.cr_code) == _shape(getattr(expected, '__code__', None))
                        and type(coro.cr_await) is CoroutineType
                        and coro.cr_await.cr_code is asyncio.sleep.__code__):
                    idle.add(task)
        # All original references have been verified. Inventory once, with
        # each owner's tracked work and the current same-store frame checks.
        # No task snapshot is cached between this check and explicit retirement.
        work = NativeMemoryCompanion._work_for_owners(tuple(owner.adapter for owner in owners))
        # A helper, a real operation, or an unrecognised generation stays alive.
        if work - idle:
            raise RuntimeError('pre_anchor_business_or_unknown_work_pending')
        return owners, idle

    def inspect(self):
        try:
            owners, idle = self._inspect()
            return dict(eligible=True, owners=len(owners), idle_dispatchers=len(idle),
                read_only=True, body_or_identity_returned=False)
        except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
            result = dict(eligible=False, reason=str(exc) if type(exc) is RuntimeError else 'pre_anchor_reference_unverified',
                read_only=True, body_or_identity_returned=False)
            if self._checks is not None:
                result['checks'] = dict(self._checks)
            if self._inventory is not None:
                result['inventory'] = dict(self._inventory)
            return result

    def _preserve_usage(self, record, owners):
        if 'usage' in record:
            return record['usage']
        path = self.directory / 'memory_companion_token_usage.json'
        try:
            original = path.read_bytes()
            if len(original) > 8 * 1024 * 1024 or type(json.loads(original)) is not dict:
                raise ValueError('usage source')
            # The original writer uses Path.write_text with native newlines.
            snapshots = [json.dumps(owner.adapter.service._token_usage, ensure_ascii=False, indent=2).replace('\n', os.linesep).encode('utf8')
                         for owner in owners]
            backup = self.directory / ('native_mc_retirement_usage_' + uuid.uuid4().hex + '.json')
            payload = json.dumps(dict(schema='tls.mc.retirement.usage.v1',
                original_utf8=original.decode('utf8'), retained_snapshots=[body.decode('utf8') for body in snapshots]),
                ensure_ascii=False, indent=2).encode('utf8')
            with os.fdopen(os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                stream.write(payload)
            record['usage'] = dict(path=path, original=original, snapshots=snapshots,
                mode=stat.S_IMODE(path.stat().st_mode))
            return record['usage']
        except (OSError, ValueError, TypeError, UnicodeError):
            raise RuntimeError('pre_anchor_usage_archive_unavailable') from None

    def _restore_usage(self, usage, expected):
        path, original = usage['path'], usage['original']
        current = path.read_bytes()
        if current == original:
            return
        if current != expected:
            raise RuntimeError('pre_anchor_usage_changed_during_close')
        temporary = self.directory / ('native_mc_retirement_restore_' + uuid.uuid4().hex + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                stream.write(original)
            temporary.chmod(usage['mode'])
            if path.read_bytes() != expected:
                raise RuntimeError('pre_anchor_usage_changed_during_close')
            temporary.replace(path)
        finally:
            # Only the unique temporary file just created by this operation.
            if temporary.exists():
                temporary.unlink()

    async def retire(self):
        owners, idle = self._inspect()
        record = getattr(self.context, SLOT, None)
        if record is None:
            record = dict(schema=SCHEMA, context=self.context, directory=self.directory,
                loop=asyncio.get_running_loop(), owners=owners)
            setattr(self.context, SLOT, record)
        usage = self._preserve_usage(record, owners)
        # A former plugin can have stopped before its integrations reached MC.
        # Only the explicit operation seals those actual original admissions;
        # the read-only check above already rejected current owners and work.
        for owner in owners:
            _method(owner.adapter, 'begin_stop')()
            if owner.adapter.active or not owner.adapter.service._closing:
                raise RuntimeError('pre_anchor_admission_stop_not_confirmed')
        # No await between proving the work set, closing admissions and
        # cancelling only the exact original idle dispatcher timers.
        for task in idle:
            task.cancel()
        if idle:
            await asyncio.gather(*idle, return_exceptions=True)
        for index, owner in enumerate(owners):
            if usage['path'].read_bytes() != usage['original']:
                raise RuntimeError('pre_anchor_usage_changed_before_close')
            try:
                await _method(owner, 'close')()
            finally:
                # Original close flushes its own old RAM counters. Preserve
                # both snapshots, but keep the current file authoritative for
                # the successor; never sum overlapping historical counters.
                try:
                    self._restore_usage(usage, usage['snapshots'][index])
                except OSError:
                    raise RuntimeError('pre_anchor_usage_restore_unavailable') from None
            if not owner.adapter.closed or not owner.adapter.service.store._closed:
                raise RuntimeError('pre_anchor_store_close_not_confirmed')
        if getattr(self.context, SLOT, None) is not record:
            raise RuntimeError('pre_anchor_retirement_reference_changed')
        delattr(self.context, SLOT)
        return dict(closed_owners=len(owners), cancelled_idle_dispatchers=len(idle))
