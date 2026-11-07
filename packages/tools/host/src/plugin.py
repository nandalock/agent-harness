"""Plugin that owns the single-track tools runtime for one PluginRuntime."""
from agent_platform_plugin_sdk import (
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
    TOOLS,
    TOOL_BINDINGS,
)
from agent_platform_tools_default import TOOL_CATALOG
from agent_platform_tool_system.registry import ToolRegistry
from agent_platform_tool_system.runtime import ToolRuntime

from .services import UNIFIED_TOOLS
from .unified import UnifiedToolsRuntime


class ToolHostConfig(SdkModel):
    pass


class ToolHostPlugin:
    spec = PluginSpec(
        name="agent-platform.tool-host",
        version="0.1.0",
        provides=(UNIFIED_TOOLS.ref,),
        requires=(
            ServiceRequirement(service=TOOLS.ref),
            ServiceRequirement(service=TOOL_CATALOG.ref),
            ServiceRequirement(service=TOOL_BINDINGS.ref, optional=True),
        ),
    )
    config_model = ToolHostConfig

    async def setup(self, ctx: PluginContext, config: ToolHostConfig) -> None:
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
