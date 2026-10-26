"""Plugin entry: publish skill tools into tools.v1."""
from agent_platform_plugin_sdk import (
    AGENTS,
    Plugin,
    PluginContext,
    PluginSpec,
    ServiceRequirement,
    TOOLS,
    SdkModel,
)

from .descriptors import skill_descriptor, skill_install_descriptor
from .executors import SkillExecutor, SkillInstallExecutor


class SkillToolsConfig(SdkModel):
    pass


class SkillToolsPlugin:
    spec = PluginSpec(
        name="agent-platform.skill-tools",
        version="0.1.0",
        requires=(
            ServiceRequirement(service=TOOLS.ref),
            ServiceRequirement(service=AGENTS.ref),
        ),
    )
    config_model = SkillToolsConfig

    async def setup(self, ctx: PluginContext, config: SkillToolsConfig) -> None:
        tools = ctx.require(TOOLS)
        agents = ctx.require(AGENTS)

        ctx.track(tools.register_executor("skill", SkillExecutor(agents)))
        ctx.track(
            tools.register_executor("skill_install", SkillInstallExecutor(agents))
        )
        for descriptor in (skill_descriptor(), skill_install_descriptor()):
            ctx.track(tools.register_tool(descriptor.model_copy(update={
                "plugin_id": ctx.instance_id, "plugin_name": ctx.spec.name,
            })))


plugin: Plugin[SkillToolsConfig] = SkillToolsPlugin()
