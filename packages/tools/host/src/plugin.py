"""Plugin that owns the single-track tools runtime for one Loader."""
from agent_platform_plugin_sdk import (
    SdkModel,
    TOOLS,
    TOOL_BINDINGS,
)
from agent_platform_tools_default import TOOL_CATALOG
from agent_platform_tool_system.registry import ToolRegistry
from agent_platform_tool_system.runtime import ToolRuntime

from .services import UNIFIED_TOOLS
from .unified import UnifiedToolsRuntime
from minidsh_cordis import Context, Plugin


class ToolHostConfig(SdkModel):
    pass


class ToolHostPlugin(Plugin[ToolHostConfig]):
    name = "agent-platform.tool-host"
    version = "0.1.0"
    provides = (UNIFIED_TOOLS,)
    requires = (TOOLS, TOOL_CATALOG)
    optional = (TOOL_BINDINGS,)
    config_model = ToolHostConfig

    async def setup(self, ctx: Context, config: ToolHostConfig) -> None:
        bindings = ctx.get(TOOL_BINDINGS)
        registry = ToolRegistry(
            providers=[],
            bindings=bindings.get_bindings if bindings is not None else None,
        )
        unified = UnifiedToolsRuntime(
            registry,
            ToolRuntime(registry=registry, executors={}),
            ctx.require(TOOLS),
            ctx.require(TOOL_CATALOG),
        )
        await unified.start()
        ctx.provide(UNIFIED_TOOLS, unified)
        ctx.on_quiesce(unified.aclose, label="stop unified tools")
