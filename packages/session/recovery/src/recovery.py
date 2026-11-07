"""Session recovery status and exclusive preparation for new or resumed runs."""
import asyncio
import json
from contextlib import asynccontextmanager

from .checkpoint import CheckpointError, SessionCheckpoint, drain_io
from agent_platform_session.events import TURN_START, TURN_END, TOOL_RESULT
from agent_platform_session.repair import interrupted_turn_closers
from agent_platform_session import Session


class RecoveryError(ValueError):
    code = "session/recovery-conflict"


def recovery_status(events, *, busy=False, last_durable_seq: int | None = None) -> dict:
    """Read-only status; an open turn is interrupted only without a live owner.

    ``events`` may be only the tail from the last ``turn/start`` (see
    ``SessionPersistence.load_recovery``); ``last_durable_seq`` then carries the
    true high-water mark because the tail may not start at seq 1.
    """
    start = None
    end = None
    for event in events:
        if event.type == TURN_START:
            start, end = event, None
        elif event.type == TURN_END:
            end = event
    status = "running" if busy else (
        "interrupted" if start is not None and end is None else
        end.data.get("stop_reason", "idle") if end else "idle"
    )
    pending = interrupted_turn_closers(events) if not busy else []
    unknown = []
    for event in [*events, *pending]:
        if event.type != TOOL_RESULT or (start and event.seq <= start.seq):
            continue
        try:
            result = json.loads(event.data.get("content", "{}"))
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict) and result.get("code") == "TOOL_OUTCOME_UNKNOWN":
            unknown.append(event.data)
    return {
        "status": status,
        "last_durable_seq": (
            last_durable_seq if last_durable_seq is not None
            else (events[-1].seq if events else 0)
        ),
        "source_turn_start_seq": start.seq if start else None,
        "can_resume": not busy and status in ("interrupted", "cancelled", "persistence_error"),
        "unknown_tool_calls": unknown,
    }


@asynccontextmanager
async def prepare_session(
    *,
    store,
    persistence,
    title=None,
    session_id,
    enabled,
    agent_key,
    resume_from=None,
):
    """Hold write ownership before loading, repairing, or publishing a session.

    All collaborators are explicit: the runtime-scoped SessionStore, the
    persistence provider selected by the composition, and an optional title
    service. There is no module-level fallback.
    """
    if not enabled:
        if resume_from is not None:
            raise RecoveryError("临时会话不支持恢复任务")
        session = Session()
        from agent_platform_session_persistence import NoopPersistence
        yield session, SessionCheckpoint(session, NoopPersistence()), None
        return
    seed = store.get(session_id) if session_id else None
    session_id = session_id or Session().header.id
    lease = persistence.write_owner(session_id)
    entered = asyncio.create_task(asyncio.to_thread(lease.__enter__))
    acquired = False
    try:
        try:
            await asyncio.shield(entered)
            acquired = True
        except asyncio.CancelledError:
            await drain_io(entered)
            acquired = True
            raise
        except Exception as exc:
            from agent_platform_agents import RunConflict
            if isinstance(exc, RunConflict):
                raise
            raise CheckpointError(session_id, "ownership") from exc
        if persistence.durable:
            if title is not None:
                title.supersede(session_id, "会话重新取得执行所有权")
            try:
                loaded = await asyncio.to_thread(persistence.load, session_id)
            except Exception as exc:
                raise CheckpointError(session_id, "load") from exc
            persistence.reset_pending(session_id)
            session = Session.from_events(*loaded) if loaded else seed
        else:
            session = seed
        if session is None:
            if resume_from is not None:
                raise RecoveryError("会话不存在，无法恢复任务")
            session = Session()
            session.header.id = session_id
        checkpoint = SessionCheckpoint(session, persistence)
        if persistence.durable and loaded:
            checkpoint.durable_seq = loaded[1][-1].seq if loaded[1] else 0
        status = recovery_status(session.events)
        if resume_from is not None:
            if not persistence.durable:
                raise RecoveryError("该会话没有持久化后端，无法恢复任务")
            if any(e.type == TURN_START and e.data.get("resumed_from") == resume_from for e in session.events):
                raise RecoveryError("这个任务已经继续过，请刷新查看最新进度")
            if not status["can_resume"] or status["source_turn_start_seq"] != resume_from:
                raise RecoveryError("任务状态已变化，请刷新后再继续")
            source = next(e for e in session.events if e.seq == resume_from)
            if source.data.get("agent") != agent_key:
                raise RecoveryError("该任务不属于当前智能体")
        try:
            await asyncio.to_thread(persistence.create, session_id, session.header)
        except Exception as exc:
            raise CheckpointError(session_id, "create") from exc
        closers = interrupted_turn_closers(session.events)
        if closers:
            session.append_recovered(closers)
            await checkpoint.flush("recovery")
        store.put(session)
        yield session, checkpoint, status if resume_from is not None else None
    finally:
        if acquired:
            closing = asyncio.create_task(asyncio.to_thread(lease.__exit__, None, None, None))
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await drain_io(closing)
                raise
            except Exception as exc:
                raise CheckpointError(session_id, "ownership_release") from exc
