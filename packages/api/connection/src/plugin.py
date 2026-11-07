"""RPC connection plugin: requires the gateway, provides the carrier adapter."""
from agent_platform_plugin_sdk import (
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from agent_platform_rpc_gateway import RPC_GATEWAY

from .connection import RpcConnection
from .services import CONNECTION


class ConnectionConfig(SdkModel):
    pass


class RpcConnectionPlugin:
    spec = PluginSpec(
        name="agent-platform.rpc-connection",
        version="0.1.0",
        provides=(CONNECTION.ref,),
        requires=(ServiceRequirement(service=RPC_GATEWAY.ref),),
    )
    config_model = ConnectionConfig

    async def setup(self, ctx: PluginContext, config: ConnectionConfig) -> None:
        ctx.provide(CONNECTION, RpcConnection(ctx.require(RPC_GATEWAY)))


plugin = RpcConnectionPlugin()
