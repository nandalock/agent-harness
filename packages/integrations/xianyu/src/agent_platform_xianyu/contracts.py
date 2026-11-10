"""Xianyu manager service key."""
from agent_platform_plugin_sdk import ServiceKey

from .manager import XianyuManager

XIANYU: ServiceKey[XianyuManager] = ServiceKey("xianyu")
