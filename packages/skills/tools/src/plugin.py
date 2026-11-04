"""Plugin entry: publish skill tools into tools.v1."""
from agent_platform_plugin_sdk import (
    AGENTS,
    AGENT_EXTENSIONS,
    Plugin,
    PluginContext,
    PluginSpec,
    ServiceRequirement,
    TOOLS,
    SdkModel,
)

from .descriptors import skill_descriptor, skill_install_descriptor
from .executors import SkillExecutor, SkillInstallExecutor
from agent_platform_skills import SKILLS
from .extension import SkillAgentExtension


class SkillToolsConfig(SdkModel):
    pass


class SkillToolsPlugin:
    spec = PluginSpec(
        name="agent-platform.skill-tools",
        version="0.1.0",
        requires=(
            ServiceRequirement(service=TOOLS.ref),
            ServiceRequirement(service=AGENTS.ref),
            ServiceRequirement(service=SKILLS.ref),
            ServiceRequirement(service=AGENT_EXTENSIONS.ref),
        ),
    )
    config_model = SkillToolsConfig

    async def setup(self, ctx: PluginContext, config: SkillToolsConfig) -> None:
        tools = ctx.require(TOOLS)
        agents = ctx.require(AGENTS)
        skills = ctx.require(SKILLS)

        ctx.track(tools.register_executor("skill", SkillExecutor(agents, skills)))
        ctx.track(
            tools.register_executor("skill_install", SkillInstallExecutor(agents))
        )
        for descriptor in (skill_descriptor(), skill_install_descriptor()):
            ctx.track(tools.register_tool(descriptor.model_copy(update={
                "plugin_id": ctx.instance_id, "plugin_name": ctx.spec.name,
            })))
        ctx.track(ctx.require(AGENT_EXTENSIONS).register(
            ctx.instance_id, SkillAgentExtension(skills, tools),
        ))


plugin: Plugin[SkillToolsConfig] = SkillToolsPlugin()
