"""RPC gateway plugin."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel

from .gateway import RpcGateway
from .services import RPC_GATEWAY


class GatewayConfig(SdkModel):
    pass


class RpcGatewayPlugin:
    spec = PluginSpec(
        name="agent-platform.rpc-gateway",
        version="0.1.0",
        provides=(RPC_GATEWAY.ref,),
    )
    config_model = GatewayConfig

    async def setup(self, ctx: PluginContext, config: GatewayConfig) -> None:
        ctx.provide(RPC_GATEWAY, RpcGateway())


plugin = RpcGatewayPlugin()
