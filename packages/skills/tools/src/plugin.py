"""Plugin entry: publish skill tools into tools.v1."""
from agent_platform_plugin_sdk import (
    AGENTS,
    AGENT_EXTENSIONS,
    TOOLS,
    SdkModel,
)

from .descriptors import skill_descriptor, skill_install_descriptor
from .executors import SkillExecutor, SkillInstallExecutor
from agent_platform_skills import SKILLS
from .extension import SkillAgentExtension
from minidsh_cordis import Context, Plugin


class SkillToolsConfig(SdkModel):
    pass


class SkillToolsPlugin(Plugin[SkillToolsConfig]):
    name = "agent-platform.skill-tools"
    version = "0.1.0"
    requires = (TOOLS, AGENTS, SKILLS, AGENT_EXTENSIONS)
    config_model = SkillToolsConfig

    async def setup(self, ctx: Context, config: SkillToolsConfig) -> None:
        tools = ctx.require(TOOLS)
        agents = ctx.require(AGENTS)
        skills = ctx.require(SKILLS)

        ctx.track(tools.register_executor("skill", SkillExecutor(agents, skills)))
        ctx.track(
            tools.register_executor("skill_install", SkillInstallExecutor(agents))
        )
        for descriptor in (skill_descriptor(), skill_install_descriptor()):
            ctx.track(tools.register_tool(descriptor.model_copy(update={
                "plugin_id": ctx.instance_id, "plugin_name": ctx.plugin_name,
            })))
        ctx.track(ctx.require(AGENT_EXTENSIONS).register(
            ctx.instance_id, SkillAgentExtension(skills, tools),
        ))


plugin: Plugin[SkillToolsConfig] = SkillToolsPlugin()
