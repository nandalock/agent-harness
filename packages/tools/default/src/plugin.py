"""The entry-point plugin that publishes tools.v1 and its host catalog."""
from agent_platform_plugin_sdk import (
    SdkModel,
    TOOLS,
)

from .catalog import TOOL_CATALOG
from .service import ToolsDefaultService
from minidsh_cordis import Context, Plugin


class ToolsConfig(SdkModel):
    pass


class ToolsDefaultPlugin(Plugin[ToolsConfig]):
    name = "agent-platform.tools-default"
    version = "0.1.0"
    provides = (TOOLS, TOOL_CATALOG)
    config_model = ToolsConfig

    async def setup(self, ctx: Context, config: ToolsConfig) -> None:
        service = ToolsDefaultService()
        ctx.provide(TOOLS, service)
        ctx.provide(TOOL_CATALOG, service)
        ctx.on_dispose(service.aclose, label="tools-default service")


plugin: Plugin[ToolsConfig] = ToolsDefaultPlugin()
