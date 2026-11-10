"""RPC gateway plugin."""
from agent_platform_plugin_sdk import SdkModel

from .gateway import RpcGateway
from .services import RPC_GATEWAY
from minidsh_cordis import Context, Plugin


class GatewayConfig(SdkModel):
    pass


class RpcGatewayPlugin(Plugin[GatewayConfig]):
    name = "agent-platform.rpc-gateway"
    version = "0.1.0"
    provides = (RPC_GATEWAY,)
    config_model = GatewayConfig

    async def setup(self, ctx: Context, config: GatewayConfig) -> None:
        ctx.provide(RPC_GATEWAY, RpcGateway())


plugin = RpcGatewayPlugin()
