"""Read-only plugin inventory plugin."""
from .contracts import PLUGIN_INVENTORY, PluginInventory
from .plugin import InventoryConfig, PluginInventoryPlugin

__all__ = ["PLUGIN_INVENTORY", "InventoryConfig", "PluginInventory", "PluginInventoryPlugin"]
