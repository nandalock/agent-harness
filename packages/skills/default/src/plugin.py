"""Service-only plugin: the shared skill catalog, independent of its sources."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel
from agent_platform_skills import SKILLS, SkillRegistry


class SkillsConfig(SdkModel):
    pass


class SkillsDefaultPlugin:
    spec = PluginSpec(name="agent-platform.skills-default", version="0.1.0", provides=(SKILLS.ref,))
    config_model = SkillsConfig

    async def setup(self, ctx: PluginContext, config: SkillsConfig) -> None:
        registry = SkillRegistry()
        ctx.provide(SKILLS, registry)
        ctx.on_dispose(registry.aclose, label="skill registry")
