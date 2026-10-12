"""Awaited durability barriers; storage failures stop dependent execution."""
import asyncio
import copy

from backend.agents.runtime.session.persistence.base import SessionPersistence


async def drain_io(task):
    """Wait for protected storage cleanup even if the caller is cancelled again."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise


class CheckpointError(RuntimeError):
    code = "session/checkpoint-failed"

    def __init__(self, session_id: str, reason: str):
        self.session_id = session_id
        self.reason = reason
        super().__init__("进度保存失败，任务已停止。请稍后重试继续。")


class SessionCheckpoint:
    """One session's awaited, serialized database writes, outside the event loop."""

    def __init__(self, session, persistence: SessionPersistence):
        self.session = session
        self.persistence = persistence
        self.enabled = persistence.durable
        self._lock = asyncio.Lock()
        self.durable_seq = 0
        self.failed = False

    async def flush(self, reason: str) -> None:
        if not self.enabled:
            return
        async with self._lock:
            if self.failed:
                raise CheckpointError(self.session.header.id, reason)
            events = copy.deepcopy([e for e in self.session.events if e.seq > self.durable_seq])

            def write():
                self.persistence.append_events(self.session.header.id, events)
                self.persistence.flush(self.session.header.id)

            # A cancelled await must not leave a writer racing lease release.
            task = asyncio.create_task(asyncio.to_thread(write))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                try:
                    await drain_io(task)
                except Exception:
                    self.failed = True
                raise
            except Exception as exc:
                self.failed = True
                raise CheckpointError(self.session.header.id, reason) from exc
            self.durable_seq = events[-1].seq if events else self.durable_seq

    async def before_tool(self, call) -> None:
        await self.flush("before_tool")
