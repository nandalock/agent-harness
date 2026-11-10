"""Plugin inventory contract."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey

from .client import ClientModule


class PluginInventory(Protocol):
    """Point-in-time projection of started plugin instances."""

    def list(self) -> list[dict[str, Any]]: ...

    def clients(self) -> tuple[ClientModule, ...]: ...

    def script(self, client_id: str, revision: str) -> bytes | None: ...


PLUGIN_INVENTORY: ServiceKey[PluginInventory] = ServiceKey("plugin.inventory")
