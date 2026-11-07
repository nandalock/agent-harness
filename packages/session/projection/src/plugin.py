"""Session projection plugin."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel

from .services import SESSION_PROJECTION, SessionProjectionService


class ProjectionConfig(SdkModel):
    pass


class SessionProjectionPlugin:
    spec = PluginSpec(
        name="agent-platform.session-projection",
        version="0.1.0",
        provides=(SESSION_PROJECTION.ref,),
    )
    config_model = ProjectionConfig

    async def setup(self, ctx: PluginContext, config: ProjectionConfig) -> None:
        ctx.provide(SESSION_PROJECTION, SessionProjectionService())
