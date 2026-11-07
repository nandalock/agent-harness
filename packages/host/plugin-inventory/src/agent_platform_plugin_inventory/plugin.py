"""Plugin entry: expose the runtime catalog as plugin.inventory.v1."""
from typing import Any

from agent_platform_plugin_sdk import (
    PLUGIN_CATALOG,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

from .contracts import PLUGIN_INVENTORY


class InventoryConfig(SdkModel):
    pass


class _Inventory:
    def __init__(self, catalog: Any) -> None:
        self._catalog = catalog

    def list(self) -> list[dict[str, Any]]:
        return self._catalog.list()


class PluginInventoryPlugin:
    spec = PluginSpec(
        name="agent-platform.plugin-inventory",
        version="0.1.0",
        provides=(PLUGIN_INVENTORY.ref,),
        requires=(ServiceRequirement(service=PLUGIN_CATALOG.ref),),
    )
    config_model = InventoryConfig

    async def setup(self, ctx: PluginContext, config: InventoryConfig) -> None:
        ctx.provide(PLUGIN_INVENTORY, _Inventory(ctx.require(PLUGIN_CATALOG)))


plugin = PluginInventoryPlugin()
