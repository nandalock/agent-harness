"""Agent configuration plugin: database-backed AGENTS and TOOL_BINDINGS."""
from agent_platform_plugin_sdk import (
    AGENTS,
    DATABASE,
    SdkModel,
    TOOL_BINDINGS,
)

from .service import AgentConfigService, ToolBindingsService
from minidsh_cordis import Context, Plugin


class AgentConfigPluginConfig(SdkModel):
    pass


class AgentConfigPlugin(Plugin[AgentConfigPluginConfig]):
    name = "agent-platform.agent-config"
    version = "0.1.0"
    provides = (AGENTS, TOOL_BINDINGS)
    requires = (DATABASE,)
    config_model = AgentConfigPluginConfig

    async def setup(self, ctx: Context, config: AgentConfigPluginConfig) -> None:
        database = ctx.require(DATABASE)
        ctx.provide(AGENTS, AgentConfigService(database))
        ctx.provide(TOOL_BINDINGS, ToolBindingsService(database))
