"""Plugin inventory contract."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef


class PluginInventory(Protocol):
    """Point-in-time projection of started plugin instances."""

    def list(self) -> list[dict[str, Any]]: ...


PLUGIN_INVENTORY: ServiceKey[PluginInventory] = ServiceKey(
    ServiceRef(name="plugin.inventory", api_version=1)
)
