import unittest

from agent_platform_plugin_inventory import PLUGIN_INVENTORY, PluginInventoryPlugin
from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime


class InventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_projects_the_runtime_catalog(self):
        runtime = PluginRuntime(
            {"plugins": [{"id": "inventory", "name": "agent-platform.plugin-inventory"}]},
            catalog=MappingCatalog({
                "agent-platform.plugin-inventory": PluginInventoryPlugin,
            }),
        )
        try:
            await runtime.start()
            rows = runtime.require(PLUGIN_INVENTORY).list()
            self.assertEqual(rows, [{
                "id": "inventory",
                "name": "agent-platform.plugin-inventory",
                "version": "0.1.0",
            }])
        finally:
            await runtime.aclose()
