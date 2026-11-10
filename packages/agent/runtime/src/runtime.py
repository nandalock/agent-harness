"""Plugin-owned request assembly, session lifecycle, hooks and loop driving."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from agent_platform_agents import AGENT_RUNS, Agent, EventSink
from agent_platform_llm import DEFAULT_MAX_LLM_RETRIES, LLM, LlmRequest, LoopHooks, ModelConfig
from agent_platform_plugin_sdk import AGENTS, AgentRunContext
from agent_platform_sandbox.services import AGENT_SANDBOX
from agent_platform_session import SessionEvent
from agent_platform_session.events import TURN_START, TASK_INPUT
from agent_platform_session_recovery import SESSION_RECOVERY
from agent_platform_session_title import SESSION_TITLE
from agent_platform_session.trace import TraceProjection
from agent_platform_system_prompt import RUNTIME_PROMPTS
from .contracts import AgentReply
from .context import saved_task_context, CONTINUE_TASK

logger = logging.getLogger(__name__)


class RuntimeAgent:
    """One reply coordinator; configuration and host resources come from services."""

    def __init__(self, ctx, extensions, key: str, definition: dict):
        self.ctx = ctx
        self.extensions = extensions
        self.key = key
        self.name = definition.get("name", key)
        self.desc = definition.get("description", "")

    async def reply(
        self, tenant_id: int, question: str,
        context: dict | None = None,
        on_event: EventSink | None = None,
        session_id: str | None = None,
        session_event_sink: Callable[[SessionEvent], None] | None = None,
        cancel: asyncio.Event | None = None,
        resume_from: int | None = None,
        on_session_ready: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentReply:
        config = await self.ctx.require(AGENTS).get_config(self.key) or {}
        context = saved_task_context(context)
        enabled = bool(config.get("session_enabled", True))
        async with self.ctx.require(SESSION_RECOVERY).prepare(
            session_id, enabled=enabled,
            agent_key=self.key, resume_from=resume_from,
        ) as (session, checkpoint, recovery):
            if enabled:
                if on_session_ready:
                    await on_session_ready(session.header.id)
                if on_event:
                    await on_event({"type": "session/ready", "session_id": session.header.id})
            if recovery is not None:
                question = CONTINUE_TASK
                if context is None:
                    for event in session.events:
                        if event.seq <= resume_from:
                            continue
                        if event.type == TURN_START:
                            break
                        if event.type == TASK_INPUT:
                            context = event.data.get("context")
                            break
                if on_event:
                    await on_event({
                        "type": "recovery", "session_id": session.header.id,
                        "source_turn_start_seq": resume_from,
                        "message": "已恢复上次进度，我会先确认中断时的操作是否完成，再继续任务。",
                    })
            reply = await self._reply_prepared(
                tenant_id, question, config=config, session=session,
                checkpoint=checkpoint, context=context, on_event=on_event,
                session_event_sink=session_event_sink, cancel=cancel,
                resumed_from=resume_from,
            )
        if on_event:
            await on_event({"type": "done", "answer": reply.answer, "tier": reply.tier,
                            "trace": reply.trace, "session_id": reply.session_id})
        return reply

    async def _reply_prepared(
        self, tenant_id, question, *, config, session, checkpoint,
        context=None, on_event=None, session_event_sink=None, cancel=None, resumed_from=None,
    ) -> AgentReply:
        t0 = time.perf_counter()
        session_enabled = bool(config.get("session_enabled", True))
        # 组装 system prompt（每轮一次）：
        #   ① SystemPrompt.assemble 求值全部贡献（工具 schema + 使用指导、身份、角色、
        #      上游上下文），段在前、动态上下文在尾部 —— 尾部变化不断前部的前缀缓存
        #   ② render 严格插值成最终文本（未知/无值变量在此报错，不发坏提示词给模型）
        #   ③ assembly.tools 即本 agent 可见工具，无需再单独查 Registry
        assembly = await self.ctx.require(RUNTIME_PROMPTS).assemble(
            tenant_id=tenant_id, agent_key=self.key, agent_name=self.name,
            agent_description=self.desc, config=config, question=question,
            session=session, upstream_context=context,
        )
        system_prompt = assembly.text
        contributions = await self.extensions.prepare(AgentRunContext(
            tenant_id=tenant_id, agent_key=self.key, config=config, tool_schemas=assembly.tools,
        ))
        tool_schemas = contributions.tool_schemas

        # 准备运行环境，创建并驱动 AgentLoop（执行循环在 Loop 内部；Session 与
        # 组装好的 system prompt 由 Runtime 注入）。
        # LLM 出口按契约注入（llm/client.py）：Loop 只发 canonical 请求，端点/凭据/HTTP
        # 全在客户端后面 —— 换 provider = 在这里换一个客户端，循环一行不改。
        model_config = self.ctx.require(LLM).resolve(config)
        llm = self._llm_client(model_config, config)
        runs = self.ctx.require(AGENT_RUNS)
        async with runs.open(
            key=self.key,
            llm_params=self._llm_params(config),
            llm=llm,
            model=model_config.model,
            fallback_reply=config.get("fallback_reply", "") or "",
            tool_schemas=tool_schemas,
            tenant_id=tenant_id,
            system_prompt=system_prompt,
            on_event=on_event,
            session=session,
            # provider 声明的默认重试策略（对齐 A：策略归 provider、执行归循环）。
            # 装配方要换策略，传自己的 LoopHooks 进来即可 —— 这里只兜「没人给」的情况。
            hooks=LoopHooks(request_error=llm.retry_policy, pre_step=contributions.pre_step,
                            prepare_request=contributions.prepare_request),
            checkpoint=checkpoint, resumed_from=resumed_from,
            task_context=saved_task_context(context),
            sandbox_policy=lambda: self._sandbox_policy(session),
        ) as loop:

            # 派生消费者装配：TraceProjection（→ AgentReply.trace / done.trace）与
            # session_event_sink（→ UI projection）都是 Session listener，不产生事实。
            # Session.append 同步回调、无 await 间隙 → 按 seq 收到全部事件；
            # Session 被 SessionStore 跨轮复用 → listener 只在 loop.run 期间挂载，
            # finally 统一摘除，保证不跨轮泄漏（事件不会迟到下一轮的投影/快照）。
            projection = TraceProjection()
            session.add_listener(projection.handle)
            attached_sink = session_event_sink is not None
            if attached_sink:
                session.add_listener(session_event_sink)
            try:
                answer = await self._drive(loop, question, cancel)
            finally:
                session.remove_listener(projection.handle)
                if attached_sink:
                    session.remove_listener(session_event_sink)

                if session_enabled:
                    title = self.ctx.get(SESSION_TITLE)
                    if title is not None:
                        title.settle(session)
                    if not checkpoint.failed:
                        await checkpoint.flush("turn_end")

        if session_enabled:
            # 排一次 LLM 标题升级：**不在本函数里 await**（schedule 不返回 awaitable），
            # 所以它绝不会推迟 done 事件或拖长本轮耗时；生成完自己写事件 + flush。
            # 只对首条消息、且标题还没被升级/钉住时排得上（见 schedule 的三条判据）。
            # 硬取消路径走不到这里（异常已经穿过去了）—— 正在被拆掉的这轮不再排新工作；
            # 协作取消（信号）是正常返回，照常排。
            title = self.ctx.get(SESSION_TITLE)
            if title is not None:
                title.schedule(session, config)

        # trace = TraceProjection.snapshot()：派生观测视图（steps/limits/usage/stop_reason
        # 全部来自 Event Log 投影），不是第二套事实存储。AgentLoop 只产生事件，不写 trace。
        trace = projection.snapshot()
        # total_ms：运行时观测指标（含 session 装配/持久化开销），在投影之外维护
        trace["total_ms"] = round((time.perf_counter() - t0) * 1000)
        tier = "llm" if any(s.get("type") == "llm" for s in trace.get("steps", [])) else "fallback"
        # usage 汇总命中率日志（纯观测，从投影结果读取，语义同旧 AgentLoop 轮末日志）
        usage = trace.get("usage")
        if usage is not None:
            ratio = usage.get("cache_hit_ratio")
            if ratio is None:
                logger.info(f"AgentLoop [{self.key}] usage 无 cache 字段（非 DeepSeek 网关?）: {usage}")
            elif ratio < 0.5:
                logger.warning(
                    f"AgentLoop [{self.key}] 上下文缓存命中率偏低: {usage}"
                    f" —— 检查前缀是否变化（system prompt / 工具集改动会从改动点起断缓存）"
                )
            else:
                logger.info(f"AgentLoop [{self.key}] usage: {usage}")
        # session_id 返回给客户端：首轮为新建 Session 的 id，后续轮次客户端原样带回；
        # 临时 Session（session_enabled=False）不返回 id。
        sid = session.header.id if session_enabled else None
        if sid:
            starts = [ev for ev in session.events if ev.type == TURN_START]
            if starts:
                trace["session_id"] = sid
                trace["turn_start_seq"] = starts[-1].seq
        return AgentReply(answer=answer, tier=tier, trace=trace, session_id=sid)

    async def _drive(self, loop: Agent, question: str, cancel: asyncio.Event | None) -> str:
        """事件驱动的三段式：**投递 → 等 driver 收敛 → 取答案**（Loop 没有一次性入口）。

        投递是同步的（不等待），等待是显式的，答案从 Event Log 的投影里取 —— 中间那段时间
        正是运行中输入的窗口（steer / inject 随时可以并进来）。

        ``cancel`` 是外部取消信号（SSE 连接断开即 set）：起一个转发任务把它搬成
        ``loop.cancel`` —— 取消的语义（清队列 + 置本轮 abort 信号）归 Loop，这里只做搬运。
        转发任务在本次运行结束时撤销（它等的信号可能永远不来）。
        """
        bridge = None
        if cancel is not None:
            bridge = asyncio.create_task(self._bridge_cancel(loop, cancel))
        try:
            loop.followup(question)
            await loop.when_idle()
        finally:
            if bridge is not None:
                bridge.cancel()      # 不 await：被取消的一方没有收尾要等
        return loop.answer_text()

    @staticmethod
    async def _bridge_cancel(loop: Agent, cancel: asyncio.Event) -> None:
        """外部信号 → ``loop.cancel``：只停这一轮，不动待投递队列。

        ``keep_inbox=True`` 是刻意的：队列归投递方所有，这里只负责「叫停」，不该顺手
        丢弃别人还没投出去的东西。
        """
        await cancel.wait()
        loop.cancel("外部信号（连接断开）", keep_inbox=True)

    def _sandbox_policy(self, session):
        return self.ctx.require(AGENT_SANDBOX).policy(session)

    def _llm_client(self, model: ModelConfig, config: dict):
        return self.ctx.require(LLM).create_client(
            model, max_llm_retries=self._llm_params(config)["max_llm_retries"],
        )

    def _llm_params(self, config: dict) -> dict:
        """运行参数（LLM 调用 + 防失控限制），全部从 agent 配置读取，默认值=现行为（零破坏）"""
        return {
            "max_steps": int(config.get("max_steps", 5)),
            "max_tool_calls": int(config.get("max_tool_calls", 30)),
            "max_wall_time": float(config.get("max_wall_time", 300)),
            # 同批 Tool 调用的并发上限（ToolScheduler 的滚动池大小）；
            # 1 = 退化为串行，与调度器引入前行为一致
            **({"max_parallel_tools": int(config["max_parallel_tools"])} if "max_parallel_tools" in config else {}),
            "max_tokens": int(config.get("max_tokens", 1024)),
            "max_tokens_plain": int(config.get("max_tokens_plain", 512)),
            "temperature": float(config.get("temperature", 0.3)),
            # 单次 step 的 LLM 调用重试次数上限（429/5xx/超时/非法响应；4xx 不重试）。
            # 重试在 step 内进行，不占 max_steps 轮数，不落 surface 事实。
            "max_llm_retries": int(config.get("max_llm_retries", DEFAULT_MAX_LLM_RETRIES)),
        }

    async def _call_llm_plain(self, messages: list[dict], config: dict) -> tuple[str, bool]:
        """通用非工具 LLM 调用，复用统一客户端。

        走的是同一个客户端：凭据、端点、失败分类、超时都归它管，这里只做「问一句、
        取一段文本」。工具与流式都不参与 —— 一次非流式 canonical 请求。
        """
        model_config = self.ctx.require(LLM).resolve(config)
        llm = self._llm_client(model_config, config)
        if not model_config.configured:
            return "", False
        params = self._llm_params(config)
        try:
            response = await llm.complete(LlmRequest(
                model=model_config.model,
                messages=messages,
                temperature=params["temperature"],
                max_tokens=params["max_tokens_plain"],
                timeout=30.0,        # 简单调用最多等 30s（与改造前的 ClientTimeout 同值）
            ))
            answer = response.message.get("content", "")
            return answer, bool(answer)
        except Exception as e:
            logger.warning(f"AgentRuntime [{self.key}] LLM plain 调用失败: {e}")
            return "", False
