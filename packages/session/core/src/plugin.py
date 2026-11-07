"""Session store plugin: makes the live-session registry a plugin service."""
import logging

from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel

from .services import SESSIONS
from .store import SessionStore

logger = logging.getLogger(__name__)


class SessionConfig(SdkModel):
    pass


class SessionPlugin:
    spec = PluginSpec(
        name="agent-platform.session",
        version="0.1.0",
        provides=(SESSIONS.ref,),
    )
    config_model = SessionConfig

    async def setup(self, ctx: PluginContext, config: SessionConfig) -> None:
        ctx.provide(SESSIONS, SessionStore())
        logger.info("Session store plugin ready")
