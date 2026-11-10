"""Service key owned by the RPC connection plugin."""
from agent_platform_plugin_sdk import ServiceKey

from .connection import RpcConnection

CONNECTION: ServiceKey[RpcConnection] = ServiceKey("rpc.connection")
