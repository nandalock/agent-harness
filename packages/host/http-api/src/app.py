"""FastAPI surface owned by the HTTP/API plugin.

The runtime is started by the ASGI carrier (``agent_platform_server``); this
module only assembles the web application and its routes. Route handlers
resolve services from the active PluginLoader instead of importing runtime
implementations.
"""
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
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
from .routes.ws import register_broadcast, router as ws_router
from .routes.xianyu import router as xianyu_router
from .db import reset_current_database, set_current_database
from .services import reset_services, set_services
from agent_platform_agent_entry import (
    AgentBusy,
    AgentNotFound,
    GatewayError,
    InvalidGatewayContext,
    NoActiveRun,
    SessionNotFound,
)
from agent_platform_chat.service import ConversationConflict, ConversationNotFound
from agent_platform_plugin_sdk import ServiceClosedError, ServiceUnavailableError
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
    database = getattr(app.state, "database", None)
    token = set_current_database(database) if database is not None else None
    service_token = set_services(getattr(app.state, "services", {}) or {})
    try:
        # Project registry bootstrap needs the schema created by the database
        # plugin; failures never block conversation startup.
        try:
            from .routes.workspace import bootstrap_workspace_projects

            bootstrap_workspace_projects()
        except Exception as exc:  # noqa: BLE001
            logger.warning("项目注册表引导失败（会话不受影响）: %s", exc)
        yield
    finally:
        reset_services(service_token)
        if token is not None:
            reset_current_database(token)


def create_app(
    connection=None, *, entry=None, chat=None, approval=None, agent_config=None, memory=None,
    workflow=None, plugin_catalog=None, database=None, services=None, faq=None, xianyu=None,
) -> FastAPI:
    app = FastAPI(title="minidsh", lifespan=lifespan)
    app.state.agent_entry = entry
    app.state.chat = chat
    app.state.approval = approval
    app.state.agent_config = agent_config
    app.state.memory = memory
    app.state.workflow = workflow
    app.state.database = database
    app.state.services = services or {}
    app.state.faq = faq
    app.state.xianyu = xianyu
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:4000").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _bind_database(request: Request, call_next):
        token = set_current_database(database) if database is not None else None
        service_token = set_services(services or {})
        try:
            return await call_next(request)
        finally:
            reset_services(service_token)
            if token is not None:
                reset_current_database(token)
    routers = [
        auth_router, agents_router,
        chat_router, mcp_router, tools_router,
        workspace_router, skills_router,
    ]
    if faq is not None:
        routers.append(faq_router)
    if workflow is not None:
        routers.append(workflow_router)
    if xianyu is not None:
        register_broadcast(xianyu)
        routers.extend((xianyu_router, ws_router))
    for router in routers:
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

    @app.get("/api/plugins")
    async def plugins():
        """Advertise browser entries from the same packages as started plugins."""
        if plugin_catalog is None:
            return JSONResponse(status_code=503, content={"detail": "plugin catalog unavailable"})
        return {
            "plugins": plugin_catalog.list(),
            "clients": [
                {
                    **entry.model_dump(mode="json"),
                    "url": f"/api/plugins/client/{quote(entry.id, safe='/')}?rev={entry.rev}",
                }
                for entry in plugin_catalog.clients()
            ],
        }

    @app.get("/api/plugins/client/{client_id:path}")
    def client_script(client_id: str, rev: str):
        script = plugin_catalog.script(client_id, rev) if plugin_catalog is not None else None
        if script is None:
            raise HTTPException(status_code=404, detail="Browser plugin bundle not found")
        return Response(script, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    async def health():
        ready = plugin_catalog is not None
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

    @app.exception_handler(ServiceUnavailableError)
    async def _service_unavailable_handler(request: Request, exc: ServiceUnavailableError):
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
