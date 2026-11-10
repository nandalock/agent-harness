"""Settings plugin: database-backed settings.v1."""
from agent_platform_plugin_sdk import (
    DATABASE,
    SdkModel,
    SETTINGS,
)

from .service import PostgresSettingsService
from minidsh_cordis import Context, Plugin


class SettingsConfig(SdkModel):
    pass


class PostgresSettingsPlugin(Plugin[SettingsConfig]):
    name = "agent-platform.settings-postgres"
    version = "0.1.0"
    provides = (SETTINGS,)
    requires = (DATABASE,)
    config_model = SettingsConfig

    async def setup(self, ctx: Context, config: SettingsConfig) -> None:
        ctx.provide(SETTINGS, PostgresSettingsService(ctx.require(DATABASE)))
