"""Session recovery status and exclusive preparation for new or resumed runs."""
import asyncio
import json
from contextlib import asynccontextmanager

from backend.agents.runtime.session.checkpoint import CheckpointError, SessionCheckpoint, drain_io
from backend.agents.runtime.session.events import TURN_START, TURN_END, TOOL_RESULT
from backend.agents.runtime.session.repair import interrupted_turn_closers
from backend.agents.runtime.session.session import Session
from backend.agents.runtime.session.store import get_session_store

CONTINUE_TASK = (
    "请继续上次未完成的任务，依据已有结果决定下一步。"
    "结果未知的工具先核实实际状态，不要重复已经确认完成的操作。"
)


def saved_task_context(context):
    """Keep JSON task inputs while excluding credential fields from durable logs."""
    if context is None:
        return None
    sensitive = {"api_key", "authorization", "password", "secret", "credentials", "access_token", "refresh_token"}

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if key.lower() not in sensitive}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(json.loads(json.dumps(context, ensure_ascii=False, allow_nan=False)))


class RecoveryError(ValueError):
    code = "session/recovery-conflict"


def recovery_status(events, *, busy=False) -> dict:
    """Read-only status; an open turn is interrupted only without a live owner."""
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
        "last_durable_seq": events[-1].seq if events else 0,
        "source_turn_start_seq": start.seq if start else None,
        "can_resume": not busy and status in ("interrupted", "cancelled", "persistence_error"),
        "unknown_tool_calls": unknown,
    }


@asynccontextmanager
async def prepare_session(persistence, session_id, *, enabled, agent_key, resume_from=None):
    """Hold write ownership before loading, repairing, or publishing a session."""
    if not enabled:
        if resume_from is not None:
            raise RecoveryError("临时会话不支持恢复任务")
        session = Session()
        from backend.agents.runtime.session.persistence.base import NoopPersistence
        yield session, SessionCheckpoint(session, NoopPersistence()), None
        return
    store = get_session_store()
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
            from backend.agents.runtime.loop.registry import RunConflict
            if isinstance(exc, RunConflict):
                raise
            raise CheckpointError(session_id, "ownership") from exc
        if persistence.durable:
            from backend.agents.runtime.session.title.service import get_session_title_service
            get_session_title_service().supersede(session_id, "会话重新取得执行所有权")
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
