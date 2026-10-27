"""One classifier batch, original raw tail, existing TLS typed-memory writers.

This is the direct service equivalent of the earlier two-slot capture fence.
It does not classify again, change historical ownership, create a database or
fall back to the companion store when an already-owned write loses authority.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import asdict
import inspect

from ..models import canonical, private_scope
from ..native_explicit_memory import NativeExplicitMemory
from ..native_profile_capture import NativeProfileCapture
from .models import MemoryRecord


def _sync(callback, *args):
    result = callback(*args)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise RuntimeError('synchronous native capture authority required')
    return result


def _identity(ctx):
    return tuple(getattr(ctx, name, None) for name in (
        'scope', 'platform', 'bot_id', 'user_id', 'session_id', 'persona_id',
        'message_id', 'message_text'))


class NativeMCCaptureRouter:
    def __init__(self, native_explicit, *, profile_capture=None, owned_selector,
                 scope_for, native_write_allowed, relationship_owned=True,
                 profile_owned=True):
        if (type(native_explicit) is not NativeExplicitMemory
                or type(relationship_owned) is not bool or type(profile_owned) is not bool
                or not all(callable(item) and not inspect.iscoroutinefunction(item)
                           for item in (owned_selector, scope_for, native_write_allowed))
                or profile_capture is not None and (type(profile_capture) is not NativeProfileCapture
                    or profile_capture.adapter is not native_explicit.adapter)
                or profile_owned and profile_capture is None):
            raise ValueError('shared native business and synchronous capture callbacks required')
        self.native, self.profile_capture = native_explicit, profile_capture
        self.owned_selector, self.scope_for = owned_selector, scope_for
        self.native_write_allowed = native_write_allowed
        self.relationship_owned, self.profile_owned = relationship_owned, profile_owned
        self.closed = True
        self.generation = 0
        self._current = ContextVar('tls_native_mc_owned_capture', default=None)
        self._batches, self._native_tasks = {}, set()
        self._counts = dict(captures=0, selected=0, explicit_selected=0,
            relationship_selected=0, profile_selected=0, native_written=0,
            relationship_written=0, profile_observed=0, denied=0, unknown=0)
        self.native.branch_gate = self.branch_gate
        if self.profile_capture is not None:
            self.profile_capture.branch_gate = self.profile_branch_gate

    def open(self):
        self.closed = False
        self.generation += 1

    def close(self):
        self.closed = True
        self.generation += 1

    def partition(self, ctx, event, req, records):
        if type(records) is not list or any(type(row) is not MemoryRecord for row in records):
            raise RuntimeError('actual native classifier typed batch required')
        ownership = _sync(self.owned_selector, ctx, event, req)
        if ownership is False:
            return records, None
        if ownership is not True:
            raise RuntimeError('native capture ownership unknown')
        profiles = [row for row in records if row.memory_type in
            {'user_profile', 'user_preference', 'user_habit'}
            and type(row.metadata) is dict and row.metadata.get('profile_dimension')]
        selected = []
        if profiles and self.profile_owned:
            if len(profiles) > 16:
                raise RuntimeError('actual bounded native profile batch required')
            selected.append(('profile', profiles))
        else:
            explicit = [row for row in records if row.memory_type == 'explicit_memory']
            relationships = [row for row in records if row.memory_type == 'relationship_claim']
            if len(explicit) > 1 or len(relationships) > 1:
                raise RuntimeError('single actual explicit or relationship branch required')
            if explicit:
                selected.append(('explicit', explicit))
            if relationships and self.relationship_owned:
                selected.append(('relationship', relationships))
        if not selected:
            return records, None
        for _, rows in selected:
            if any(row.metadata.get('extractor') != 'rule_v2' or row.scope != 'private'
                   or row.session_id != ctx.session_id or row.platform != ctx.platform
                   or row.message_id != ctx.message_id for row in rows):
                raise RuntimeError('current actual classifier provenance required')
        try:
            scope = private_scope(_sync(self.scope_for, ctx, event, req))
        except (ValueError, TypeError, KeyError):
            scope = None
        state = dict(ctx=ctx, event=event, req=req, identity=_identity(ctx), scope=scope,
            generation=self.generation, selected=selected, active=True,
            task=asyncio.current_task(), kind=None, records=None, snapshots=None)
        state['digest'] = canonical([[kind, [asdict(row) for row in rows]] for kind, rows in selected])
        self._batches[id(state)] = state
        self._counts['captures'] += 1
        for kind, rows in selected:
            self._counts['selected'] += len(rows)
            self._counts[kind + '_selected'] += len(rows)
        excluded = {id(row) for _, rows in selected for row in rows}
        return [row for row in records if id(row) not in excluded], state

    def _allowed(self, state, event, scope, records=None):
        if (state is None or not state['active'] or self.closed
                or state['generation'] != self.generation or state['event'] is not event
                or state['scope'] != scope or state['identity'] != _identity(state['ctx'])
                or not state['records']):
            return False
        if state['digest'] != canonical([[kind, [asdict(row) for row in rows]]
                                         for kind, rows in state['selected']]):
            return False
        if records is not None and canonical(records) != canonical(state['snapshots']):
            return False
        return (_sync(self.owned_selector, state['ctx'], event, state['req']) is True
                and _sync(self.native_write_allowed, state['ctx'], event, state['req'],
                          dict(scope), state['records'][0]) is True)

    def branch_gate(self, event, scope):
        return self._allowed(self._current.get(), event, scope)

    def profile_branch_gate(self, event, scope, records):
        state = self._current.get()
        return state is not None and state['kind'] == 'profile' and self._allowed(state, event, scope, records)

    async def commit(self, state):
        if state is None:
            return
        token = self._current.set(state)
        try:
            for kind, rows in state['selected']:
                state['kind'], state['records'] = kind, rows
                state['snapshots'] = [asdict(row) for row in rows]
                if state['scope'] is None or not self._allowed(state, state['event'], state['scope']):
                    self._counts['denied'] += 1
                    continue
                if kind == 'profile':
                    work = self.profile_capture.capture_event(state['event'], state['scope'], state['snapshots'])
                elif kind == 'relationship':
                    work = self.native.capture_relationship_event(state['event'], state['scope'])
                else:
                    work = self.native.capture_event(state['event'], state['scope'])
                task = asyncio.create_task(work, name='tls_native_mc:typed_capture')
                self._native_tasks.add(task)
                task.add_done_callback(self._done)
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._counts['unknown'] += 1
                else:
                    if type(result) is dict and result.get('ok') is True:
                        self._counts['native_written'] += 1
                        if kind == 'relationship':
                            self._counts['relationship_written'] += 1
                        if kind == 'profile':
                            self._counts['profile_observed'] += len(rows)
                    else:
                        self._counts['denied'] += 1
        finally:
            self._current.reset(token)

    def _done(self, task):
        self._native_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def release(self, state):
        if state is not None:
            state['active'] = False
            self._batches.pop(id(state), None)

    async def wait_drained(self, timeout=None):
        tasks = {row['task'] for row in self._batches.values()
                 if row['task'] is not None and row['task'] is not asyncio.current_task()}
        tasks.update(self._native_tasks)
        tasks = {task for task in tasks if not task.done()}
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                raise RuntimeError('native memory capture still in flight')
        return self.status()

    def status(self):
        return dict(active=not self.closed, closed=self.closed, generation=self.generation,
            pending=len(self._batches), native_pending=sum(not task.done() for task in self._native_tasks),
            relationship_owned=self.relationship_owned, profile_owned=self.profile_owned,
            counts=dict(self._counts), legacy_fallback_for_owned=False)
