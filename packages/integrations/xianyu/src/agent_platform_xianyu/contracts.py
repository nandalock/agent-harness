"""Xianyu manager service key."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .manager import XianyuManager

XIANYU: ServiceKey[XianyuManager] = ServiceKey(
    ServiceRef(name="xianyu", api_version=1)
)
