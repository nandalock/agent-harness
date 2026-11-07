"""Plugin entry: expose the runtime catalog as plugin.inventory.v1."""
from agent_platform_plugin_sdk import (
    PLUGIN_CATALOG,
    PluginCatalog,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

from .client import ClientModule, discover_clients
from .contracts import PLUGIN_INVENTORY


class InventoryConfig(SdkModel):
    pass


class _Inventory:
    def __init__(self, catalog: PluginCatalog) -> None:
        self._catalog = catalog

    def list(self) -> list[dict]:
        return self._catalog.list()

    def clients(self) -> tuple[ClientModule, ...]:
        modules = discover_clients(self._catalog.web_packages())
        return tuple(entry for entry, _ in modules.values())

    def script(self, client_id: str, revision: str) -> bytes | None:
        module = discover_clients(self._catalog.web_packages()).get(client_id)
        if module is None or module[0].rev != revision:
            return None
        try:
            return module[1].read_bytes()
        except FileNotFoundError:
            return None


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
