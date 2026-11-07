"""Resolve and dispatch external agent requests through runtime-owned services."""
import asyncio

from agent_platform_agents import NEXT_STEP, NEXT_TURN, RunConflict
from agent_platform_llm.http import HttpSessionPool
from agent_platform_plugin_sdk import ServiceClosedError

from .context import RequestContext
from .errors import AgentBusy, AgentNotFound, InvalidGatewayContext, NoActiveRun
from .router import RouterRuntime


class AgentGateway:
    def __init__(self, agents, runtime, runs, database, llm):
        self._agents = agents
        self._runtime = runtime
        self._runs = runs
        self._database = database
        self._llm = llm
        self._http = HttpSessionPool()
        self._desc_cache: dict[str, dict[tuple[str, str], list[float]]] = {}
        self._history_tasks: set[asyncio.Task] = set()
        self._router_tasks: set[asyncio.Task] = set()
        self._closed = False

    async def resolve(self, agent_key: str) -> dict:
        if self._closed:
            raise ServiceClosedError("agent entry is closed")
        if not agent_key:
            raise InvalidGatewayContext("agent_key 不能为空")
        definition = await self._agents.get_definition(agent_key)
        if definition is None:
            raise AgentNotFound(f"Agent 不存在: {agent_key}")
        return definition

    def invalidate_desc_cache(self, agent_key: str) -> None:
        self._desc_cache.pop(agent_key, None)

    def _start_history_task(self, operation) -> None:
        task = asyncio.create_task(operation)
        self._history_tasks.add(task)
        task.add_done_callback(self._history_tasks.discard)

    async def chat(self, rctx: RequestContext, question: str, *, on_event=None,
                   session_event_sink=None, cancel=None, resume_from=None, on_session_ready=None):
        if not isinstance(rctx, RequestContext) or rctx.tenant_id is None:
            raise InvalidGatewayContext("chat() 需要有效的 RequestContext 和 tenant_id")
        definition = await self.resolve(rctx.agent_key)
        if definition.get("agent_type") == "router":
            if resume_from is not None:
                raise InvalidGatewayContext("此智能体未使用可恢复执行循环")
            if self._closed:
                raise ServiceClosedError("agent entry is closed")
            router = RouterRuntime(
                rctx.agent_key, self._agents, self._database, self._llm, self._http,
                self._desc_cache.setdefault(rctx.agent_key, {}), self._start_history_task,
            )
            task = asyncio.current_task()
            self._router_tasks.add(task)
            try:
                return await router.reply(rctx.tenant_id, question, context=rctx.context)
            finally:
                self._router_tasks.discard(task)

        try:
            return await self._runtime.reply(
                rctx.agent_key, definition, rctx.tenant_id, question,
                context=rctx.context, session_id=rctx.session_id, on_event=on_event,
                session_event_sink=session_event_sink, cancel=cancel,
                resume_from=resume_from, on_session_ready=on_session_ready,
            )
        except RunConflict as exc:
            raise AgentBusy(str(exc)) from exc

    def steer(self, rctx: RequestContext, text: str, target: str = NEXT_STEP) -> str:
        session_id = rctx.session_id or ""
        run = self._runs.get(session_id)
        if run is None:
            raise NoActiveRun(f"会话 {session_id or '(空)'} 上没有正在运行的轮次")
        return run.followup(text) if target == NEXT_TURN else run.steer(text)

    async def aclose(self) -> None:
        self._closed = True
        tasks = (self._history_tasks | self._router_tasks) - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._desc_cache.clear()
        await self._http.aclose()
