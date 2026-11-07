"""Conversation turns and live projections shared by all HTTP viewers."""
import asyncio
import logging
from dataclasses import dataclass

from agent_platform_agent_entry import (
    GatewayError, InvalidGatewayContext, NoActiveRun, RequestContext,
)
from agent_platform_agent_runtime import AgentReply
from agent_platform_agent_runtime.context import CONTINUE_TASK
from agent_platform_agents import NEXT_STEP, NEXT_TURN
from agent_platform_session_projection import TrajectoryProjection

from .live import LiveRun, LiveRunConflict, LiveRunRegistry
from .models import ConversationCreate, MessageCreate
from .store import ChatStore

logger = logging.getLogger(__name__)


class ConversationNotFound(GatewayError):
    code = "chat/conversation-not-found"


class ConversationConflict(GatewayError):
    code = "chat/conversation-conflict"


@dataclass(frozen=True)
class LiveView:
    events: asyncio.Queue
    run: LiveRun
    snapshot: dict | None = None

    def detach(self) -> None:
        self.run.unsubscribe(self.events)


async def _commit(write, *args, **kwargs):
    """Finish a dispatched write before shutting down the database provider."""
    task = asyncio.create_task(asyncio.to_thread(write, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled() and task.exception() is not None:
            logger.error("Chat persistence failed during shutdown", exc_info=task.exception())
        raise


class ChatService:
    def __init__(self, entry, store: ChatStore):
        self._entry = entry
        self.store = store
        self._live = LiveRunRegistry()

    def _conversation(self, tenant_id, agent_key, conversation_id):
        conversation = self.store.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            raise ConversationNotFound("会话不存在")
        if conversation.channel != f"agent:{agent_key}":
            raise ConversationConflict("该会话不属于当前智能体")
        return conversation

    async def _start(self, tenant_id, agent_key, question, *, conversation_id=None,
                     session_id=None, visitor_id=None, resume_from=None):
        definition = await self._entry.resolve(agent_key)
        if conversation_id:
            conversation = self._conversation(tenant_id, agent_key, conversation_id)
        else:
            conversation = self.store.create_conversation(tenant_id, ConversationCreate(
                channel=f"agent:{agent_key}", agent_key=agent_key,
                channel_conversation_id=visitor_id or None,
                customer_name="测试用户" if visitor_id else "匿名用户",
            ))
        mapped = conversation.session_id
        if session_id and session_id != mapped:
            raise ConversationConflict("会话与执行记录不一致，请刷新后重试")

        context = RequestContext(
            tenant_id=tenant_id, agent_key=agent_key, session_id=mapped,
            conversation_id=conversation.id, visitor_id=visitor_id,
        )
        try:
            run = self._live.start(
                session_id=mapped or f"conversation:{conversation.id}", tenant_id=tenant_id,
                agent_key=agent_key, conversation_id=conversation.id,
                agent_name=definition.get("name", agent_key), question=question,
            )
        except LiveRunConflict as exc:
            raise ConversationConflict(str(exc)) from exc
        try:
            if resume_from is None:
                self.store.create_message(tenant_id, conversation.id, MessageCreate(
                    role="customer", content=question,
                ))
        except BaseException:
            self._live.finish(run)
            raise
        return run, context

    async def reply(self, tenant_id, agent_key, question, **options) -> dict:
        run, context = await self._start(tenant_id, agent_key, question, **options)
        task = asyncio.create_task(self._execute(run, context, options.get("resume_from"), streaming=False))
        run.task = task
        reply = await task
        return {
            "answer": reply.answer, "sources": reply.sources, "tier": reply.tier,
            "trace": reply.trace, "conversation_id": run.conversation_id, "session_id": reply.session_id,
        }

    async def start_stream(self, tenant_id, agent_key, question, **options) -> LiveView:
        run, context = await self._start(tenant_id, agent_key, question, **options)
        view = LiveView(run.subscribe(), run)
        run.task = asyncio.create_task(self._execute(run, context, options.get("resume_from"), streaming=True))
        return view

    def _find(self, tenant_id, agent_key, session_id, conversation_id=None):
        run = self._live.get(session_id)
        if (run is not None and not run.done and run.tenant_id == tenant_id and run.agent_key == agent_key
                and (conversation_id is None or run.conversation_id == conversation_id)):
            return run
        return None

    def attach(self, tenant_id, agent_key, session_id, conversation_id=None) -> LiveView | None:
        run = self._find(tenant_id, agent_key, session_id, conversation_id)
        if run is None:
            return None
        snapshot = run.snapshot()
        return LiveView(run.subscribe(), run, snapshot)

    def cancel(self, tenant_id, agent_key, session_id) -> bool:
        run = self._find(tenant_id, agent_key, session_id)
        if run is None:
            return False
        run.cancel()
        return True

    async def steer(self, tenant_id, agent_key, session_id, question, target, conversation_id=None) -> str:
        await self._entry.resolve(agent_key)
        if target not in (NEXT_STEP, NEXT_TURN):
            raise InvalidGatewayContext(f"未知的投递目标: {target!r}")
        if conversation_id is not None:
            conversation = self._conversation(tenant_id, agent_key, conversation_id)
            if conversation.session_id != session_id:
                raise ConversationConflict("会话与执行记录不一致，请刷新后重试")
        if self._find(tenant_id, agent_key, session_id, conversation_id) is None:
            raise NoActiveRun(f"会话 {session_id} 上没有正在运行的轮次")

        msg_id = self._entry.steer(RequestContext(
            tenant_id=tenant_id, agent_key=agent_key, session_id=session_id, conversation_id=conversation_id,
        ), question, target)
        if conversation_id is not None:
            self.store.create_message(tenant_id, conversation_id, MessageCreate(role="customer", content=question))
        return msg_id

    async def _execute(self, run, context, resume_from, *, streaming) -> AgentReply | None:
        projector = TrajectoryProjection()
        thinking_parts: list[str] = []

        def publish(event: dict) -> None:
            kind = event.get("type")
            if kind == "thinking" or (kind == "traj/delta" and event.get("field") == "thinking"):
                thinking_parts.append(event.get("delta", ""))
            if kind in ("done", "session/ready"):
                event = {**event, "conversation_id": run.conversation_id}
            run.publish(event)

        async def on_event(event):
            # Emit the authoritative completion only after saving the reply.
            if event.get("type") != "done":
                publish(event)

        def on_session_event(event):
            for ui_event in projector.handle(event):
                publish(ui_event)

        async def on_session_ready(session_id):
            self._live.bind_session(run, session_id)
            await _commit(
                self.store.bind_session, run.tenant_id, run.conversation_id, session_id,
                resumed=resume_from is not None,
            )

        run.set_snapshot(projector.finish)
        try:
            reply = await self._entry.chat(
                context, run.question, on_event=on_event, session_event_sink=on_session_event,
                cancel=run.cancel_event, resume_from=resume_from, on_session_ready=on_session_ready,
            )
            metadata = {"tier": reply.tier, "sources": reply.sources, "trace": reply.trace}
            if streaming:
                metadata["thinking"] = "".join(thinking_parts)[:6000] or None
            await _commit(self.store.save_reply, run.tenant_id, run.conversation_id, reply.session_id, MessageCreate(
                role="agent", sender_name=run.agent_name, content=reply.answer, metadata=metadata,
            ))
            publish({
                "type": "done", "answer": reply.answer, "tier": reply.tier,
                "trace": reply.trace, "session_id": reply.session_id,
            })
            return reply
        except Exception as exc:
            code = getattr(exc, "code", "agent/error")
            if code == "agent/error":
                logger.exception("Agent turn failed")
            message = str(exc) if code != "agent/error" else "任务执行失败，请稍后重试"
            publish({"type": "error", "code": code, "message": message})
            if not streaming:
                raise
            return None
        finally:
            self._live.finish(run)

    async def aclose(self) -> None:
        await self._live.aclose()
