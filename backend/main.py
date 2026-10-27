import asyncio
import os

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

app = FastAPI(title="minidsh")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:4000").split(","),
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


@app.get("/health")
async def health():
    from backend.plugin_host import get_plugin_host
    ready = get_plugin_host() is not None
    return JSONResponse(status_code=200 if ready else 503,
                        content={"status": "ready" if ready else "unavailable", "plugins": ready})

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
    from backend.agents import load_configured_agents

    from backend.agents.runtime.session import PostgresSessionPersistence, set_session_persistence

    init_db()

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

    # Agents are user definitions, loaded by the same factory as API creation.
    load_configured_agents()

    # asyncio.create_task(auto_connect())  # 闲鱼已禁用

    # 先启动本地 MCP server (9001)，ToolRegistry 需要连接它
    from agent_platform_builtin_mcp.server import mcp as mcp_server
    from starlette.middleware.cors import CORSMiddleware as StarletteCORS
    from backend.embedded_mcp import start_server
    app.state.mcp_servers = []
    mcp_app = mcp_server.streamable_http_app()
    mcp_app.add_middleware(StarletteCORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Mcp-Session-Id"])
    app.state.mcp_servers.append(await start_server(mcp_app, int(os.environ.get("BUILTIN_MCP_PORT", "9001"))))

    # 论文域 MCP server (9002) — 领域扩展点，新域继续往下加
    from agent_platform_paper_mcp.server import mcp as paper_mcp
    paper_app = paper_mcp.streamable_http_app()
    paper_app.add_middleware(StarletteCORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["Mcp-Session-Id"])
    try:
        app.state.mcp_servers.append(await start_server(paper_app, int(os.environ.get("PAPER_MCP_PORT", "9002"))))
    except BaseException:
        from backend.embedded_mcp import close_servers
        await close_servers(app.state.mcp_servers)
        raise

    # Overleaf 使用独立 SDK 2 环境；这里只确保 DB 里有可被 mcp-client 读取的行。
    try:
        from agent_platform_overleaf_mcp.integration import ensure_server
        if os.environ.get("OVERLEAF_ENABLED", "true").lower() == "true":
            ensure_server()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Overleaf MCP 注册失败: {e}")

    if os.environ.get("OVERLEAF_RT_ENABLED", "false").lower() == "true":
        from agent_platform_overleaf_rt_mcp.integration import ensure_server
        ensure_server()

    # 审批服务：通用的人机确认能力（interaction 层），沙箱升权是它的第一个消费者。
    # **未装配时需要审批的能力恒不可用**（fail-closed 到拒绝，等价 DSH 的
    # approval=never）—— 没有判定方 ≠ 默认批准。
    try:
        from backend.interaction.approval import init_approval_service
        init_approval_service()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"审批服务未装配（需要审批的能力将一律被拒）: {e}")

    # 单轨工具运行时：装配 tools-default + 默认工具插件；PLUGIN_CONFIG 只追加额外插件。
    # 依赖缺失或装配失败不阻断服务启动，但工具调用不可用。
    try:
        from backend.plugin_host import init_plugin_host
        await init_plugin_host()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"插件工具运行时装配失败，工具调用不可用: {e}")



@app.on_event("shutdown")
async def shutdown():
    try:
        from backend.plugin_host import close_plugin_host
        await close_plugin_host()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"单轨工具运行时关闭失败: {e}")
    from backend.core.http import close_http_session
    await close_http_session()
    from backend.embedded_mcp import close_servers
    await close_servers(getattr(app.state, "mcp_servers", []))
