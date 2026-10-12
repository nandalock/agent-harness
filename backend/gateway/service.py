"""AgentGateway — 外部 Agent 驱动者的统一进程内入口（DSH Request boundary）

调用链：
    HTTP (api/agents.py)  ─┐
    Workflow (engine/…)  ──┼──→  AgentGateway.chat()  →  AgentRuntime.reply()
    渠道 (integrations/…) ─┘

职责链：身份校验 → target 解析（注册表）→ 会话映射 → 上下文装配 →
       运行状态检查（预留）→ 调用 AgentRuntime → 返回结果 / 转发事件。

Gateway 本身不执行 Agent：禁止 LLM / Tool / MCP / AgentLoop 构造 / Prompt 构造 /
LangGraph 执行 —— 执行全部在已有的 AgentRuntime 内。Gateway 无状态：
agent 每次都从注册表现查，不缓存业务对象（DSH: resolve from registries, not cached）。

错误只抛 gateway/errors 定义的领域错误，通道层负责翻译。
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend.agents.base import BaseAgent, AgentReply
from backend.agents.runtime.loop import RunConflict, get_run_registry
from backend.agents.runtime.loop.events import EventSink
from backend.agents.runtime.loop.inbox import NEXT_STEP, NEXT_TURN
from backend.agents.runtime.session import SessionEvent
from backend.gateway.context import RequestContext
from backend.gateway.errors import AgentBusy, AgentNotFound, InvalidGatewayContext, NoActiveRun

logger = logging.getLogger(__name__)


class AgentGateway:
    """统一入口。所有方法只接收 RequestContext / 领域错误，不感知 HTTP/SSE/WS。"""

    def resolve(self, agent_key: str) -> BaseAgent:
        """target 解析：agent_key → 注册表中的 Agent 实例。

        KeyError 一律翻译为 AgentNotFound（Gateway 错误），不泄漏注册表异常。
        """
        if not agent_key:
            raise InvalidGatewayContext("agent_key 不能为空")
        from backend.agents import get_agent  # 延迟 import：gateway → agents 单向依赖
        try:
            return get_agent(agent_key)
        except KeyError:
            raise AgentNotFound(f"Agent 不存在: {agent_key}") from None

    async def chat(
        self,
        rctx: RequestContext,
        question: str,
        on_event: EventSink | None = None,
        session_event_sink: Callable[[SessionEvent], None] | None = None,
        cancel: asyncio.Event | None = None,
        resume_from: int | None = None,
        on_session_ready: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentReply:
        """运行入口：身份校验 → 解析目标 → 调 AgentRuntime.reply()。

        参数形状与各 Agent.reply 的既有约定保持一致：
        context / session_id 所有已注册 Agent 都接受；
        on_event / session_event_sink / cancel 仅 AgentRuntime 系支持 —— 有才传入，
        行为与既有调用完全等价。Gateway 只做透传，不解释事件语义、也不持有取消信号
        （信号的持有方是驱动方：HTTP 通道在客户端断开时 set）。
        """
        if not isinstance(rctx, RequestContext):
            raise InvalidGatewayContext("chat() 必须接收 RequestContext")
        if rctx.tenant_id is None:
            raise InvalidGatewayContext("RequestContext.tenant_id 缺失")

        agent = self.resolve(rctx.agent_key)
        from backend.agents.runtime.agent_runtime import AgentRuntime
        supports_recovery = getattr(agent.reply, "__func__", None) is AgentRuntime.reply
        if resume_from is not None and not supports_recovery:
            raise InvalidGatewayContext("此智能体未使用可恢复执行循环")
        extra = {}
        if supports_recovery:
            if resume_from is not None:
                extra["resume_from"] = resume_from
            if on_session_ready is not None:
                extra["on_session_ready"] = on_session_ready

        try:
            if on_event is None and session_event_sink is None and cancel is None:
                return await agent.reply(
                    rctx.tenant_id, question,
                    context=rctx.context, session_id=rctx.session_id, **extra,
                )
            return await agent.reply(
                rctx.tenant_id, question,
                context=rctx.context, session_id=rctx.session_id,
                on_event=on_event,
                session_event_sink=session_event_sink,
                cancel=cancel,
                **extra,
            )
        except RunConflict as e:
            # 同 session 单飞（run ownership）：第二个请求不该排队等，而是改投运行中输入。
            # 领域词汇在 Gateway 层归一 —— Runtime 抛的是 loop 层的运行时错误，通道层只认
            # gateway/errors 的 code。
            raise AgentBusy(str(e)) from e

    def steer(self, rctx: RequestContext, text: str, target: str = NEXT_STEP) -> str:
        """把一条输入投给该会话正在跑的那一轮，返回受理 id（msg_id）。

        ``target`` 决定它落在哪条队列（语义见 loop/inbox.py）：
          next-step（默认）—— 当前轮的下一步就并入上下文（「方向偏了，往这边走」）
          next-turn        —— 本轮结束后作为新的一轮开始（「等我做完这个，再看这个」）

        没有正在跑的轮次 → NoActiveRun（通道层翻 409）：「下一轮」的语义由 /chat/stream 承担，
        这一层不发明「无人接单也照样受理」的行为。Gateway 仍不执行 Agent 也不构造 Loop ——
        它只是把「找到那一轮、投一条进去」这两次同步调用接起来。
        """
        session_id = rctx.session_id or ""
        run = get_run_registry().get(session_id)
        if run is None:
            raise NoActiveRun(f"会话 {session_id or '(空)'} 上没有正在运行的轮次")
        return run.followup(text) if target == NEXT_TURN else run.steer(text)
