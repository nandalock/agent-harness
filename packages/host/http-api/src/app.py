"""FastAPI surface owned by the HTTP/API plugin.

The runtime is started by the host proxy (``backend.main``); this module only
assembles the web application and its routes. Route handlers resolve services
from the active PluginRuntime instead of importing runtime implementations.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .routes.agents import router as agents_router
from .routes.auth import router as auth_router
from .routes.chat import router as chat_router
from .routes.faq import router as faq_router
from .routes.mcp import router as mcp_router
from .routes.memory import router as memory_router
from .routes.skills import router as skills_router
from .routes.tools import router as tools_router
from .routes.workflow import router as workflow_router
from .routes.workspace import router as workspace_router
from .routes.ws import router as ws_router
from .routes.xianyu import router as xianyu_router
from agent_platform_agent_entry import (
    AgentBusy,
    AgentNotFound,
    GatewayError,
    InvalidGatewayContext,
    NoActiveRun,
    SessionNotFound,
)
from agent_platform_chat.service import ConversationConflict, ConversationNotFound
from agent_platform_plugin_sdk import ServiceClosedError
from agent_platform_session_recovery import CheckpointError, RecoveryError
from agent_platform_agents import RunConflict

logger = logging.getLogger(__name__)

#: Gateway 领域错误 → HTTP 状态（通道层的唯一映射表；错误本身携带稳定 code）
_GATEWAY_STATUS = {
    InvalidGatewayContext: 400,
    AgentNotFound: 404,
    SessionNotFound: 404,
    AgentBusy: 409,
    NoActiveRun: 409,
    ConversationConflict: 409,
    ConversationNotFound: 404,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Project registry bootstrap needs the schema created by the database
    # plugin; failures never block conversation startup.
    try:
        from .routes.workspace import bootstrap_workspace_projects

        bootstrap_workspace_projects()
    except Exception as exc:  # noqa: BLE001
        logger.warning("项目注册表引导失败（会话不受影响）: %s", exc)
    yield


def create_app(
    connection=None, *, entry=None, chat=None, approval=None, agent_config=None, memory=None,
) -> FastAPI:
    app = FastAPI(title="minidsh", lifespan=lifespan)
    app.state.agent_entry = entry
    app.state.chat = chat
    app.state.approval = approval
    app.state.agent_config = agent_config
    app.state.memory = memory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:4000").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        auth_router, faq_router, xianyu_router, ws_router, agents_router,
        chat_router, mcp_router, tools_router, workflow_router,
        workspace_router, skills_router,
    ):
        app.include_router(router)
    if memory is not None:
        app.include_router(memory_router)

    if connection is not None:
        @app.post("/api/rpc")
        async def rpc_endpoint(request: Request):
            raw = await request.body()
            tenant_id = request.headers.get("X-Tenant-ID", "1")
            try:
                tenant = int(tenant_id)
            except ValueError:
                tenant = 1
            result = await connection.dispatch_json(
                raw, tenant_id=tenant,
                session_id=request.headers.get("X-Session-ID"),
            )
            if result is None:
                return Response(status_code=204)
            return JSONResponse(result)

    @app.get("/health")
    async def health():
        from backend.plugin_host import get_plugin_host

        ready = get_plugin_host() is not None
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "unavailable", "plugins": ready},
        )

    @app.exception_handler(GatewayError)
    async def _gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=_GATEWAY_STATUS.get(type(exc), 500),
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(ServiceClosedError)
    async def _service_closed_handler(request: Request, exc: ServiceClosedError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(CheckpointError)
    async def _checkpoint_error_handler(request: Request, exc: CheckpointError):
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": exc.code})

    @app.exception_handler(RecoveryError)
    async def _recovery_error_handler(request: Request, exc: RecoveryError):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": exc.code})

    @app.exception_handler(RunConflict)
    async def _session_write_conflict_handler(request: Request, exc: RunConflict):
        return JSONResponse(
            status_code=409,
            content={"detail": "会话正在执行，请结束后再修改设置", "code": "session/agent-busy"},
        )

    return app
