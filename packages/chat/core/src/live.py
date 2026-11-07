"""Live agent runs decoupled from the HTTP stream that started them.

The SSE response is only a *viewer*: it subscribes to a run and may disappear
when the user navigates away.  The run itself lives in a task owned by this
registry, keeps consuming Session events, and persists its final assistant
message.  Returning to the conversation re-attaches with a projection snapshot
plus subsequent live events (see ``GET /api/agents/{key}/chat/live``).

Only the active run is kept here.  Once it finishes, the persisted conversation
message is the source of truth for history; the live entry is removed so a later
attach cannot replay a turn that is already in the message log.
"""
from __future__ import annotations

import asyncio
import copy
import time
from typing import Any, Callable

from agent_platform_plugin_sdk import ServiceClosedError


class LiveRunConflict(RuntimeError):
    """该 session 已有一个后台运行中的轮次。"""

    def __init__(self, session_id: str):
        super().__init__(f"会话 {session_id} 上已有一轮正在运行")
        self.session_id = session_id


class LiveRun:
    """A running turn plus the subscribers currently watching it."""

    def __init__(
        self,
        *,
        session_id: str,
        tenant_id: int,
        agent_key: str,
        conversation_id: int,
        agent_name: str,
        question: str,
    ) -> None:
        self.key = session_id
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.agent_key = agent_key
        self.conversation_id = conversation_id
        self.agent_name = agent_name
        self.question = question
        self.started_at = time.time()
        self.done = False
        self.cancel_event = asyncio.Event()
        self.task: asyncio.Task | None = None
        #: UI 审批事件，按 approval_id 保存：断线重连时随快照一起补发。
        self._pending_approvals: dict[str, dict] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._snapshot_fn: Callable[[], dict] | None = None

    def set_snapshot(self, snapshot: Callable[[], dict]) -> None:
        self._snapshot_fn = snapshot

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        """Fan one UI event out to every attached stream (non-blocking)."""
        kind = event.get("type")
        if kind == "approval.request":
            data = event.get("data") or {}
            approval_id = data.get("approval_id")
            if approval_id:
                self._pending_approvals[approval_id] = event
        elif kind == "sandbox.escalation":
            data = event.get("data") or {}
            approval_id = data.get("approval_id")
            if approval_id:
                self._pending_approvals.pop(approval_id, None)
            elif data.get("granted"):
                # 批准事件不带 approval_id（只有拒绝/取消才带）；同一轮最多一个
                # 沙箱升权请求在等，放行后清掉快照里的陈旧卡片。
                self._pending_approvals.clear()
        elif kind in ("done", "error"):
            self._pending_approvals.clear()
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        # done 已经落给当前订阅者；此后 attach 一律 204（历史消息已由 _persist 落库）。
        # 这样「done 已发、finish 还没跑」的窗口不会让新 attach 接上一条没有 done 的流。
        if kind in ("done", "error"):
            self.done = True

    def snapshot(self) -> dict:
        """A frozen projection snapshot; events published after this call are not included."""
        base = self._snapshot_fn() if self._snapshot_fn is not None else {}
        nodes = copy.deepcopy(base.get("nodes") or [])
        usage = copy.deepcopy(base.get("usage") or [])
        return {
            "type": "live/snapshot",
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "nodes": nodes,
            "usage": usage,
            "pending_approvals": copy.deepcopy(list(self._pending_approvals.values())),
        }

    def cancel(self) -> None:
        self.cancel_event.set()

    def finish(self) -> None:
        self.done = True
        self._pending_approvals.clear()
        for queue in list(self._subscribers):
            queue.put_nowait(None)
        self._subscribers.clear()


class LiveRunRegistry:
    """session_id → 正在后台跑的那一轮（只保留 active）。"""

    def __init__(self) -> None:
        self._runs: dict[str, LiveRun] = {}
        self._closed = False

    def get(self, session_id: str) -> LiveRun | None:
        run = self._runs.get(session_id)
        if run is not None:
            return run
        return next((run for run in self._runs.values() if run.session_id == session_id), None)

    def start(self, **kwargs: Any) -> LiveRun:
        session_id = kwargs["session_id"]
        if self._closed:
            raise ServiceClosedError("chat service is closed")
        if self.get(session_id) is not None:
            raise LiveRunConflict(session_id)
        run = LiveRun(**kwargs)
        self._runs[session_id] = run
        return run

    def finish(self, run: LiveRun) -> None:
        # 只摘自己：极端情况下同一 session 可能已经开了下一轮。
        if self._runs.get(run.key) is run:
            del self._runs[run.key]
        run.finish()

    def active(self) -> list[str]:
        return list(self._runs)


    def bind_session(self, run: LiveRun, session_id: str) -> None:
        existing = self.get(session_id)
        if existing is not None and existing is not run:
            raise LiveRunConflict(session_id)
        run.session_id = session_id

    async def aclose(self) -> None:
        self._closed = True
        runs = tuple(self._runs.values())
        tasks = [run.task for run in runs if run.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for run in runs:
            self.finish(run)
