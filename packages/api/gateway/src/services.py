"""Service key owned by the RPC gateway plugin."""
from agent_platform_plugin_sdk import ServiceKey

from .gateway import RpcGateway

RPC_GATEWAY: ServiceKey[RpcGateway] = ServiceKey("rpc.gateway")
