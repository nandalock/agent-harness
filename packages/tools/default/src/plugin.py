"""The entry-point plugin that publishes tools.v1 and its host catalog."""
from agent_platform_plugin_sdk import (
    Plugin,
    PluginContext,
    PluginSpec,
    SdkModel,
    TOOLS,
)

from .catalog import TOOL_CATALOG
from .service import ToolsDefaultService


class ToolsConfig(SdkModel):
    pass


class ToolsDefaultPlugin:
    spec = PluginSpec(
        name="agent-platform.tools-default",
        version="0.1.0",
        provides=(TOOLS.ref, TOOL_CATALOG.ref),
    )
    config_model = ToolsConfig

    async def setup(self, ctx: PluginContext, config: ToolsConfig) -> None:
        service = ToolsDefaultService()
        ctx.provide(TOOLS, service)
        ctx.provide(TOOL_CATALOG, service)
        ctx.on_dispose(service.aclose, label="tools-default service")


plugin: Plugin[ToolsConfig] = ToolsDefaultPlugin()
