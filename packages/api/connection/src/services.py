"""Service key owned by the RPC connection plugin."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .connection import RpcConnection

CONNECTION: ServiceKey[RpcConnection] = ServiceKey(
    ServiceRef(name="rpc.connection", api_version=1)
)
