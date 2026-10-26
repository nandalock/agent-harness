"""AgentRuntime — 统一 Agent 运行时：配置 + SystemPrompt + LLM 参数 + 执行调度

职责：加载 agent definition / config，组装 system prompt 与工具集，准备 LLM 参数，
创建并驱动 AgentLoop，返回最终结果。Agent 执行循环（LLM → Tool → LLM）在 AgentLoop 中。

每轮的请求装配顺序：
  ① 取 Session（热命中 / 冷恢复 / 新建，见下三段式）
  ② SystemPrompt.assemble —— 一次求值出提示词（段 + 动态上下文）、可见工具与其指导
  ③ render 成 system prompt 文本；assembly.tools 转 OpenAI tools 数组
  ④ 交给 AgentLoop：它把 system 前置为 messages[0]，对话历史由 Session 派生
工具 schema 与工具使用指导由此同源产出（都来自同一次工具求值），不会各自漂移。
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from backend.agents.base import BaseAgent, AgentReply
from backend.agents.config_service import get_agent_definition, get_agent_config
from backend.agents.runtime.llm import (
    DEFAULT_MAX_LLM_RETRIES,
    LlmRequest,
    LoopHooks,
    OpenAiChatClient,
)
from backend.agents.runtime.loop import AgentLoop, get_run_registry
from backend.agents.runtime.loop.events import EventSink
from backend.agents.runtime.session import (
    Session,
    SessionEvent,
    get_session_persistence,
    get_session_title_service,
)
from backend.agents.runtime.session.projections import TraceProjection
from backend.agents.runtime.session.checkpoint import SessionCheckpoint
from backend.agents.runtime.session.recovery import prepare_session, CONTINUE_TASK, saved_task_context
from backend.agents.runtime.session.events import TURN_START, TASK_INPUT
from backend.agents.runtime.system_prompt import (
    AssembleContext,
    assemble,
    render_system_prompt,
)
from agent_platform_tool_system.scheduler import DEFAULT_MAX_PARALLEL_TOOLS

logger = logging.getLogger(__name__)


class AgentRuntime(BaseAgent):
    """通用 Agent 运行时 — 配置来自 agent_definitions + agent_configs 表"""

    def __init__(self, key: str, definition: dict | None = None):
        if definition is None:
            definition = get_agent_definition(key) or {}
        self.key = key
        self.name = definition.get("name", key)
        self.desc = definition.get("description", "")
        self.status = definition.get("status", "active")
        self._definition = definition

    def _cfg(self) -> dict:
        """合并 agent_definitions.config + agent_configs 覆盖"""
        base = self._definition.get("config", {}) if self._definition else {}
        overrides = get_agent_config(self.key) or {}
        return {**base, **overrides}

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
        config = self._cfg()
        context = saved_task_context(context)
        enabled = bool(config.get("session_enabled", True))
        async with prepare_session(
            get_session_persistence(), session_id, enabled=enabled,
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
        self, tenant_id, question, *, config, session, checkpoint: SessionCheckpoint,
        context=None, on_event=None, session_event_sink=None, cancel=None, resumed_from=None,
    ) -> AgentReply:
        t0 = time.perf_counter()
        session_enabled = bool(config.get("session_enabled", True))
        # 组装 system prompt（每轮一次）：
        #   ① SystemPrompt.assemble 求值全部贡献（工具 schema + 使用指导、身份、角色、
        #      上游上下文），段在前、动态上下文在尾部 —— 尾部变化不断前部的前缀缓存
        #   ② render 严格插值成最终文本（未知/无值变量在此报错，不发坏提示词给模型）
        #   ③ assembly.tools 即本 agent 可见工具，无需再单独查 Registry
        assembly = await assemble(AssembleContext(
            tenant_id=tenant_id,
            agent_key=self.key,
            agent_name=self.name,
            agent_description=self.desc,
            config=config,
            question=question,
            session=session,
            upstream_context=context,
        ))
        system_prompt = render_system_prompt(assembly)
        tool_schemas = [t.to_openai() for t in assembly.tools]
        from agent_platform_skills.registry import get_skill_registry
        from agent_platform_skills.runtime import SkillPreStep, scope_for
        from agent_platform_skill_tools import (
            openai_tool,
            skill_descriptor,
            skill_install_descriptor,
        )
        from agent_platform_skills.installer import install_enabled
        # 安装入口不依赖预先绑定工具，才能在空目录中完成第一次安装。
        # 关闭入口时也过滤历史绑定，执行器会再次检查当前配置。
        if install_enabled(config):
            if not any(t["function"]["name"] == "skill_install" for t in tool_schemas):
                tool_schemas.append(openai_tool(skill_install_descriptor()))
        else:
            tool_schemas = [t for t in tool_schemas if t["function"]["name"] != "skill_install"]
        skill_scope = scope_for(tenant_id, self.key, [t["function"]["name"] for t in tool_schemas], config)
        catalog = await asyncio.to_thread(get_skill_registry().list, skill_scope)
        if any(s.model_invocable and not s.unavailable_reason(skill_scope) for s in catalog):
            if "skill" not in skill_scope.tool_names:
                tool_schemas.append(openai_tool(skill_descriptor()))
                skill_scope = scope_for(tenant_id, self.key, [t["function"]["name"] for t in tool_schemas], config)

        # 准备运行环境，创建并驱动 AgentLoop（执行循环在 Loop 内部；Session 与
        # 组装好的 system prompt 由 Runtime 注入）。
        # LLM 出口按契约注入（llm/client.py）：Loop 只发 canonical 请求，端点/凭据/HTTP
        # 全在客户端后面 —— 换 provider = 在这里换一个客户端，循环一行不改。
        llm = self._llm_client(config)
        loop = AgentLoop(
            key=self.key,
            llm_params=self._llm_params(config),
            llm=llm,
            model=config.get("model", "") or "",
            fallback_reply=config.get("fallback_reply", "") or "",
            tool_schemas=tool_schemas,
            tenant_id=tenant_id,
            system_prompt=system_prompt,
            on_event=on_event,
            session=session,
            # provider 声明的默认重试策略（对齐 A：策略归 provider、执行归循环）。
            # 装配方要换策略，传自己的 LoopHooks 进来即可 —— 这里只兜「没人给」的情况。
            hooks=LoopHooks(request_error=llm.retry_policy, pre_step=SkillPreStep(skill_scope)),
            checkpoint=checkpoint, resumed_from=resumed_from,
            task_context=saved_task_context(context),
        )

        # 同 session 单飞 + 活动句柄登记（docs/agent-loop-design.md §4）：本会话已经有一轮在跑
        # → RunConflict（Gateway 翻 AgentBusy、通道层翻 409）。登记之后，外部就能按 session_id
        # 找到这一轮并投递运行中输入 / 叫停它（get_run_registry().get(...)）。
        # 登记得晚一点是刻意的：句柄就是 loop 本身，它到这里才存在；此前没有任何 LLM 动作。
        get_run_registry().register(session.header.id, loop)

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

            try:
                if session_enabled:
                    get_session_title_service().settle(session)
                    if not checkpoint.failed:
                        await checkpoint.flush("turn_end")
            finally:
                get_run_registry().unregister(session.header.id)

        if session_enabled:
            # 排一次 LLM 标题升级：**不在本函数里 await**（schedule 不返回 awaitable），
            # 所以它绝不会推迟 done 事件或拖长本轮耗时；生成完自己写事件 + flush。
            # 只对首条消息、且标题还没被升级/钉住时排得上（见 schedule 的三条判据）。
            # 硬取消路径走不到这里（异常已经穿过去了）—— 正在被拆掉的这轮不再排新工作；
            # 协作取消（信号）是正常返回，照常排。
            get_session_title_service().schedule(session, config)

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
        return AgentReply(answer=answer, tier=tier, trace=trace, session_id=sid)

    async def _drive(self, loop: AgentLoop, question: str, cancel: asyncio.Event | None) -> str:
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
    async def _bridge_cancel(loop: AgentLoop, cancel: asyncio.Event) -> None:
        """外部信号 → ``loop.cancel``：只停这一轮，不动待投递队列。

        ``keep_inbox=True`` 是刻意的：队列归投递方所有，这里只负责「叫停」，不该顺手
        丢弃别人还没投出去的东西。
        """
        await cancel.wait()
        loop.cancel("外部信号（连接断开）", keep_inbox=True)

    def _llm_client(self, config: dict) -> OpenAiChatClient:
        """本 agent 的 LLM 客户端：端点 + 凭据 + provider 声明的默认重试策略。

        **凭据只在这里被搬运，不进循环** —— 循环拿到的是一个 LlmClient，它自己不认识
        api_key / base_url（见 backend/agents/runtime/llm/client.py）。
        """
        return OpenAiChatClient(
            api_key=config.get("api_key", "") or "",
            base_url=config.get("base_url", "") or "",
            max_llm_retries=self._llm_params(config)["max_llm_retries"],
        )

    def _llm_params(self, config: dict) -> dict:
        """运行参数（LLM 调用 + 防失控限制），全部从 agent 配置读取，默认值=现行为（零破坏）"""
        return {
            "max_steps": int(config.get("max_steps", 5)),
            "max_tool_calls": int(config.get("max_tool_calls", 30)),
            "max_wall_time": float(config.get("max_wall_time", 300)),
            # 同批 Tool 调用的并发上限（ToolScheduler 的滚动池大小）；
            # 1 = 退化为串行，与调度器引入前行为一致
            "max_parallel_tools": int(config.get("max_parallel_tools", DEFAULT_MAX_PARALLEL_TOOLS)),
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
        model = (config.get("model", "") or "").strip()
        llm = self._llm_client(config)
        if not llm.configured or not model:
            return "", False
        params = self._llm_params(config)
        try:
            response = await llm.complete(LlmRequest(
                model=model,
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
