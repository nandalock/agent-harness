"""Session projection plugin."""
from agent_platform_plugin_sdk import SdkModel

from .services import SESSION_PROJECTION, SessionProjectionService
from minidsh_cordis import Context, Plugin


class ProjectionConfig(SdkModel):
    pass


class SessionProjectionPlugin(Plugin[ProjectionConfig]):
    name = "agent-platform.session-projection"
    version = "0.1.0"
    provides = (SESSION_PROJECTION,)
    config_model = ProjectionConfig

    async def setup(self, ctx: Context, config: ProjectionConfig) -> None:
        ctx.provide(SESSION_PROJECTION, SessionProjectionService())
