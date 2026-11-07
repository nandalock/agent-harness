"""Service key owned by the RPC gateway plugin."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .gateway import RpcGateway

RPC_GATEWAY: ServiceKey[RpcGateway] = ServiceKey(
    ServiceRef(name="rpc.gateway", api_version=1)
)
