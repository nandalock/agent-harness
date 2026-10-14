import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.faq import router as faq_router
from backend.api.auth import router as auth_router
from backend.api.xianyu import router as xianyu_router
from backend.api.ws import router as ws_router
from backend.api.agents import router as agents_router
from backend.api.chat import router as chat_router
from backend.api.memory import router as memory_router
from backend.api.mcp import router as mcp_router
from backend.api.tools import router as tools_router
from backend.api.workflow import router as workflow_router
from backend.api.workspace import router as workspace_router
from backend.api.skills import router as skills_router
from backend.gateway.errors import (
    AgentBusy,
    AgentNotFound,
    GatewayError,
    InvalidGatewayContext,
    NoActiveRun,
    SessionNotFound,
)
from backend.agents.runtime.session.checkpoint import CheckpointError
from backend.agents.runtime.session.recovery import RecoveryError
from backend.agents.runtime.loop.registry import RunConflict

app = FastAPI(title="Agent Harness")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(faq_router)
app.include_router(xianyu_router)
app.include_router(ws_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(mcp_router)
app.include_router(tools_router)
app.include_router(workflow_router)
app.include_router(workspace_router)
app.include_router(skills_router)

#: Gateway 领域错误 → HTTP 状态（通道层的唯一映射表；错误本身携带稳定 code，见 gateway/errors.py）
#: 409 的两种情况分开：AgentBusy = 该会话已在跑（改投运行中输入 /chat/steer）；
#: NoActiveRun = 没有在跑的轮次（改用 /chat/stream 发新消息）—— 客户端的动作不同，别合并。
_GATEWAY_STATUS = {
    InvalidGatewayContext: 400,
    AgentNotFound: 404,
    SessionNotFound: 404,
    AgentBusy: 409,
    NoActiveRun: 409,
}


@app.exception_handler(GatewayError)
async def _gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
    """Gateway 只抛领域错误，状态码由这里定 —— 各端点不必各写一份 try/except。"""
    return JSONResponse(
        status_code=_GATEWAY_STATUS.get(type(exc), 500),
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(CheckpointError)
async def _checkpoint_error_handler(request: Request, exc: CheckpointError):
    return JSONResponse(status_code=503, content={"detail": str(exc), "code": exc.code})


@app.exception_handler(RecoveryError)
async def _recovery_error_handler(request: Request, exc: RecoveryError):
    return JSONResponse(status_code=409, content={"detail": str(exc), "code": exc.code})


@app.exception_handler(RunConflict)
async def _session_write_conflict_handler(request: Request, exc: RunConflict):
    return JSONResponse(status_code=409, content={"detail": "会话正在执行，请结束后再修改设置", "code": "session/agent-busy"})


@app.on_event("startup")
async def startup():
    from backend.core.schema import init_db
    from backend.agents import register, _agents
    from backend.agents.runtime import AgentRuntime
    from backend.agents.faqagent.agent import FaqAgent
    from backend.agents.supervisor.agent import SupervisorAgent
    from backend.agents.router import RouterAgent, RouterRuntime
    from backend.agents.human_handoff.agent import HumanHandoffAgent
    from backend.agents.config_service import list_agent_definitions
    from backend.tool_system.registry.registry import init_registry
    from backend.tool_system.runtime.runtime import init_tool_runtime

    from backend.core.seeds import seed_orders
    from backend.agents.runtime.session import PostgresSessionPersistence, set_session_persistence

    init_db()
    seed_orders(tenant_id=1)

    # 项目注册表引导：把**存量**会话按 cwd 归组建成项目（每个租户只跑一次）。
    # 必须在 init_db 之后 —— 两张注册表由它建。失败不阻断启动：会话照常能开，
    # 只是暂时没有分组，下次启动会重试（标记与账目同事务，不会留半截状态）。
    try:
        from backend.api.workspace import bootstrap_workspace_projects
        bootstrap_workspace_projects()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"项目注册表引导失败（会话不受影响）: {e}")

    # 装配 Session Event Log 持久化（PostgreSQL）。默认 NoopPersistence：进程内 Session，
    # 退出即消失；装配后 SessionStore 只做内存热区，Event Log 持久化 + 冷恢复走 Postgres。
    set_session_persistence(PostgresSessionPersistence())

    # 1. 有自定义 logic 的 Agent
    register(FaqAgent())
    register(SupervisorAgent())
    register(RouterAgent())
    register(HumanHandoffAgent())

    # 2. 从 DB 自动发现剩余的纯 AgentRuntime agent
    for row in list_agent_definitions():
        if row["agent_key"] not in _agents:
            agent_type = row.get("agent_type", "agent")
            if agent_type == "router":
                register(RouterRuntime(key=row["agent_key"], definition=row))
            else:
                register(AgentRuntime(key=row["agent_key"], definition=row))

    # asyncio.create_task(auto_connect())  # 闲鱼已禁用

    # 先启动本地 MCP server (9001)，ToolRegistry 需要连接它
    from backend.tool_packages.builtin.server import mcp as mcp_server
    from starlette.middleware.cors import CORSMiddleware as StarletteCORS
    import uvicorn
    mcp_app = mcp_server.streamable_http_app()
    mcp_app.add_middleware(StarletteCORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Mcp-Session-Id"])
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=9001, log_level="info")
    server_task = asyncio.create_task(uvicorn.Server(config).serve())
    await asyncio.sleep(0.5)  # 等 MCP server 就绪

    # 论文域 MCP server (9002) — 领域扩展点，新域继续往下加
    from backend.tool_packages.paper.server import mcp as paper_mcp
    paper_app = paper_mcp.streamable_http_app()
    paper_app.add_middleware(StarletteCORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Mcp-Session-Id"])
    paper_config = uvicorn.Config(paper_app, host="0.0.0.0", port=9002, log_level="info")
    paper_task = asyncio.create_task(uvicorn.Server(paper_config).serve())
    await asyncio.sleep(0.3)  # 等论文 MCP server 就绪

    rt_id = None
    import os
    if os.environ.get("OVERLEAF_RT_ENABLED", "false").lower() == "true":
        from backend.tool_packages.overleaf_rt.integration import ensure_server
        rt_id = ensure_server()

    try:
        await init_registry()
        from backend.skills.tool import skill_descriptor
        from backend.tool_system.registry.registry import get_registry
        get_registry().register_builtin(skill_descriptor())
        if rt_id is not None:
            from backend.tool_packages.overleaf_rt.integration import configure_tools
            configure_tools(get_registry(), rt_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"ToolRegistry 初始化失败（不影响服务启动）: {e}")

    # Tool 执行入口（Registry 解析 → Executor 执行）；AgentLoop / API 都经它调用工具
    try:
        init_tool_runtime()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"ToolRuntime 初始化失败（工具调用不可用）: {e}")

    # 沙箱子系统：校验工作区根 → 功能探测 → 装配 provider。
    # 失败不阻断服务启动——沙箱工具执行时 fail-closed（返回错误而非裸跑）。
    try:
        from backend.tool_system.sandbox.runtime import init_sandbox
        init_sandbox()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"沙箱未装配（沙箱工具将拒绝执行）: {e}")

    # 审批服务：通用的人机确认能力（interaction 层），沙箱升权是它的第一个消费者。
    # **未装配时需要审批的能力恒不可用**（fail-closed 到拒绝，等价 DSH 的
    # approval=never）—— 没有判定方 ≠ 默认批准。
    try:
        from backend.interaction.approval import init_approval_service
        init_approval_service()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"审批服务未装配（需要审批的能力将一律被拒）: {e}")

    # 按能力开关注册内建沙箱工具（bash / python）：停用时不注册 → 模型完全看不到。
    # 开关值归沙箱子系统所有（settings.sandbox.enabled），这里只问结果、不解释原因。
    try:
        from backend.tool_system.sandbox.runtime import apply_enabled, is_enabled
        _sandbox_on = is_enabled()
        apply_enabled(_sandbox_on)
        if not _sandbox_on:
            import logging
            logging.getLogger(__name__).info("沙箱能力已停用（settings.sandbox.enabled=false）")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"沙箱工具注册失败: {e}")

    # 装配：论文域工具内部进度 → registry 进度查询（平台扩展点示例）
    try:
        from backend.tool_packages.paper.server import get_stage
        from backend.tool_system.registry.registry import get_registry
        _registry = get_registry()
        for _tool in ("summarize_paper", "fetch_paper_text"):
            _registry.register_progress_query(_tool, lambda args, _t=_tool: get_stage(args.get("url", "")))
            # 重活工具（PDF 下载/LLM 总结）：显式声明更长超时，避免默认 30s 误杀
            _registry.register_tool_timeout(_tool, 120)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"论文域进度查询注册失败: {e}")


@app.on_event("shutdown")
async def shutdown():
    from backend.tool_system.adapters.stdio_pool import close_stdio_sessions
    await close_stdio_sessions()
    from backend.core.http import close_http_session
    await close_http_session()
