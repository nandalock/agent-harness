"""Session controller plugin: session RPC methods."""
from agent_platform_plugin_sdk import (
    DATABASE,
    SdkModel,
)
from agent_platform_rpc_gateway import RPC_GATEWAY, RpcMethodContract
from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE
from agent_platform_session_recovery import SESSION_RECOVERY

from .models import (
    SessionIdParams,
    SessionRecoveryResult,
    SessionSandboxModeResult,
    SessionSetSandboxModeParams,
    SessionSetSandboxModeResult,
    SessionTrajectoryResult,
)
from .service import SessionApiService
from .services import SESSION_API
from minidsh_cordis import Context, Plugin

METHODS = (
    RpcMethodContract("session.recovery", SessionIdParams, SessionRecoveryResult),
    RpcMethodContract("session.trajectory", SessionIdParams, SessionTrajectoryResult),
    RpcMethodContract("session.sandboxMode.get", SessionIdParams, SessionSandboxModeResult),
    RpcMethodContract("session.sandboxMode.set", SessionSetSandboxModeParams, SessionSetSandboxModeResult),
)


class SessionApiConfig(SdkModel):
    pass


class SessionApiPlugin(Plugin[SessionApiConfig]):
    name = "agent-platform.api-sessions"
    version = "0.1.0"
    provides = (SESSION_API,)
    requires = (RPC_GATEWAY, DATABASE, SESSIONS, SESSION_PERSISTENCE, SESSION_RECOVERY)
    config_model = SessionApiConfig

    async def setup(self, ctx: Context, config: SessionApiConfig) -> None:
        service = SessionApiService(
            ctx.require(DATABASE),
            ctx.require(SESSIONS),
            ctx.require(SESSION_PERSISTENCE),
            ctx.require(SESSION_RECOVERY),
        )
        ctx.provide(SESSION_API, service)
        gateway = ctx.require(RPC_GATEWAY)
        contracts = {contract.method: contract for contract in METHODS}

        async def recovery(params, context):
            return SessionRecoveryResult(**await service.recovery(context.tenant_id, params.session_id))

        async def trajectory(params, context):
            return SessionTrajectoryResult(**await service.trajectory(context.tenant_id, params.session_id))

        async def sandbox_get(params, context):
            return SessionSandboxModeResult(**await service.sandbox_mode(context.tenant_id, params.session_id))

        async def sandbox_set(params, context):
            return SessionSetSandboxModeResult(**await service.set_sandbox_mode(
                context.tenant_id, params.session_id, params.mode,
            ))

        for method, handler in {
            "session.recovery": recovery,
            "session.trajectory": trajectory,
            "session.sandboxMode.get": sandbox_get,
            "session.sandboxMode.set": sandbox_set,
        }.items():
            ctx.track(gateway.register(contracts[method], handler))


plugin = SessionApiPlugin()
