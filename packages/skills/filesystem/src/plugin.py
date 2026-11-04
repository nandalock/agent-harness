"""Register configured local directories as one scoped skill provider."""
from pathlib import Path
from pydantic import Field
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel, ServiceRequirement
from agent_platform_skills import SKILLS, SkillError, SkillSource
from .provider import FilesystemSkillProvider
from .sources import default_sources


class SourceConfig(SdkModel):
    name: str
    path: str
    kind: str = "skill"
    tenant_ids: tuple[int, ...]
    agent_keys: tuple[str, ...] | None = None


class FilesystemConfig(SdkModel):
    builtin: bool = True
    include_installed: bool = True
    sources: tuple[SourceConfig, ...] = Field(default_factory=tuple)


class SkillsFilesystemPlugin:
    spec = PluginSpec(
        name="agent-platform.skills-filesystem", version="0.1.0",
        requires=(ServiceRequirement(service=SKILLS.ref),),
    )
    config_model = FilesystemConfig

    async def setup(self, ctx: PluginContext, config: FilesystemConfig) -> None:
        sources = default_sources(include_builtin=config.builtin)
        for source in config.sources:
            path = Path(source.path)
            if not path.is_absolute() or not source.tenant_ids:
                raise SkillError("自定义技能目录必须是绝对路径，并声明 tenant_ids")
            if source.name in ("platform", "installed"):
                raise SkillError("installed 和 platform 是平台保留的技能来源名称")
            sources.append(SkillSource(source.name, path, source.kind, source.tenant_ids, source.agent_keys))
        provider = FilesystemSkillProvider(sources, include_installed=config.include_installed, name=ctx.instance_id)
        ctx.track(ctx.require(SKILLS).register_provider(provider))
