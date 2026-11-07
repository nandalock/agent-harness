"""Settings plugin: database-backed settings.v1."""
from agent_platform_plugin_sdk import (
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
    SETTINGS,
)

from .service import PostgresSettingsService


class SettingsConfig(SdkModel):
    pass


class PostgresSettingsPlugin:
    spec = PluginSpec(
        name="agent-platform.settings-postgres",
        version="0.1.0",
        provides=(SETTINGS.ref,),
        requires=(ServiceRequirement(service=DATABASE.ref),),
    )
    config_model = SettingsConfig

    async def setup(self, ctx: PluginContext, config: SettingsConfig) -> None:
        ctx.provide(SETTINGS, PostgresSettingsService(ctx.require(DATABASE)))
