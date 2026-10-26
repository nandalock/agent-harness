"""Default in-process implementation of the Agent Platform `tools.v1` contract."""
from .catalog import TOOL_CATALOG, ToolCatalog
from .plugin import ToolsConfig, ToolsDefaultPlugin
from .service import ToolsDefaultService

__version__ = "0.1.0"

__all__ = [
    "TOOL_CATALOG",
    "ToolCatalog",
    "ToolsConfig",
    "ToolsDefaultPlugin",
    "ToolsDefaultService",
]
