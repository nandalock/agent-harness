"""Agent configuration plugin: database-backed AGENTS and TOOL_BINDINGS."""
from agent_platform_plugin_sdk import (
    AGENTS,
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
    TOOL_BINDINGS,
)

from .service import AgentConfigService, ToolBindingsService


class AgentConfigPluginConfig(SdkModel):
    pass


class AgentConfigPlugin:
    spec = PluginSpec(
        name="agent-platform.agent-config",
        version="0.1.0",
        provides=(AGENTS.ref, TOOL_BINDINGS.ref),
        requires=(ServiceRequirement(service=DATABASE.ref),),
    )
    config_model = AgentConfigPluginConfig

    async def setup(self, ctx: PluginContext, config: AgentConfigPluginConfig) -> None:
        database = ctx.require(DATABASE)
        ctx.provide(AGENTS, AgentConfigService(database))
        ctx.provide(TOOL_BINDINGS, ToolBindingsService(database))
