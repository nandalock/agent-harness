"""Session store plugin: makes the live-session registry a plugin service."""
import logging

from agent_platform_plugin_sdk import SdkModel

from .services import SESSIONS
from .store import SessionStore
from minidsh_cordis import Context, Plugin

logger = logging.getLogger(__name__)


class SessionConfig(SdkModel):
    pass


class SessionPlugin(Plugin[SessionConfig]):
    name = "agent-platform.session"
    version = "0.1.0"
    provides = (SESSIONS,)
    config_model = SessionConfig

    async def setup(self, ctx: Context, config: SessionConfig) -> None:
        ctx.provide(SESSIONS, SessionStore())
        logger.info("Session store plugin ready")
