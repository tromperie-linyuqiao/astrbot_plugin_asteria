"""Bounded, per-session debounce before AstrBot's session lock."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class Entry:
    text: str
    future: asyncio.Future
    detached: bool = False
    released: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class Bucket:
    entries: list[Entry]
    started: float
    last: float
    window: float
    max_wait: float
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class MessageBatcher:
    def __init__(self, capacity: int = 128):
        self.buckets: dict[str, Bucket] = {}
        self.capacity = capacity
        self.closed = False

    @property
    def pending(self):
        return len(self.buckets)

    def _flush(self, session: str, bucket: Bucket, individual=False):
        if self.buckets.get(session) is not bucket:
            return
        del self.buckets[session]
        alive = [e for e in bucket.entries if not e.detached]
        merged = "\n".join(e.text for e in bucket.entries)
        winner = alive[-1] if alive else None
        for entry in bucket.entries:
            if not entry.future.done():
                entry.future.set_result(entry.text if individual else merged if entry is winner else None)
        bucket.changed.set()

    async def _timer(self, session: str, bucket: Bucket):
        loop = asyncio.get_running_loop()
        try:
            while self.buckets.get(session) is bucket:
                bucket.changed.clear()
                deadline = min(bucket.last + bucket.window, bucket.started + bucket.max_wait)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._flush(session, bucket)
                    return
                try:
                    await asyncio.wait_for(bucket.changed.wait(), remaining)
                except TimeoutError:
                    self._flush(session, bucket)
                    return
        except asyncio.CancelledError:
            self._flush(session, bucket, individual=True)
            raise

    async def submit(self, session: str, text: str, settings: dict) -> str | None:
        """Only the last event continues with merged text; None means absorbed."""
        if self.closed:
            return text
        if len(text) > settings["merge_max_chars"]:
            if bucket := self.buckets.get(session):
                self._flush(session, bucket)
                # Let earlier event hooks resume before this unbatched message
                # competes for the session lock. Each original is released once.
                await asyncio.gather(*(e.released.wait() for e in bucket.entries if not e.detached))
            return text
        loop = asyncio.get_running_loop()
        bucket = self.buckets.get(session)
        if bucket and sum(len(e.text) + 1 for e in bucket.entries) + len(text) > settings["merge_max_chars"]:
            self._flush(session, bucket)
            bucket = None
        if bucket is None:
            if len(self.buckets) >= self.capacity:
                return text
            bucket = Bucket([], loop.time(), loop.time(), settings["merge_window_seconds"], settings["merge_max_wait_seconds"])
            self.buckets[session] = bucket
            bucket.task = asyncio.create_task(self._timer(session, bucket))
        entry = Entry(text, loop.create_future())
        bucket.entries.append(entry)
        bucket.last = loop.time()
        bucket.changed.set()
        if len(bucket.entries) >= settings["merge_max_messages"]:
            self._flush(session, bucket)
        try:
            return await asyncio.shield(entry.future)
        except asyncio.CancelledError:
            entry.detached = True
            bucket.changed.set()
            raise
        finally:
            entry.released.set()

    def flush(self, session: str):
        if bucket := self.buckets.get(session):
            self._flush(session, bucket)

    async def release(self):
        """Disabling/unloading lets pending originals continue individually."""
        tasks = []
        for session, bucket in list(self.buckets.items()):
            self._flush(session, bucket, individual=True)
            if bucket.task:
                bucket.task.cancel()
                tasks.append(bucket.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        self.closed = True
        await self.release()
