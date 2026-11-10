"""Service-only plugin: the shared skill catalog, independent of its sources."""
from agent_platform_plugin_sdk import SdkModel
from agent_platform_skills import SKILLS, SkillRegistry
from minidsh_cordis import Context, Plugin


class SkillsConfig(SdkModel):
    pass


class SkillsDefaultPlugin(Plugin[SkillsConfig]):
    name = "agent-platform.skills-default"
    version = "0.1.0"
    provides = (SKILLS,)
    config_model = SkillsConfig

    async def setup(self, ctx: Context, config: SkillsConfig) -> None:
        registry = SkillRegistry()
        ctx.provide(SKILLS, registry)
        ctx.on_dispose(registry.aclose, label="skill registry")
