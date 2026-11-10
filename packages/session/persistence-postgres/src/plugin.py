"""PostgreSQL session-persistence plugin."""
from agent_platform_plugin_sdk import SdkModel

from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .services import DATABASE
from .postgres import PostgresSessionPersistence
from minidsh_cordis import Context, Plugin


class PersistenceConfig(SdkModel):
    pass


class PostgresPersistencePlugin(Plugin[PersistenceConfig]):
    name = "agent-platform.session-persistence-postgres"
    version = "0.1.0"
    provides = (SESSION_PERSISTENCE,)
    requires = (DATABASE, SESSIONS)
    config_model = PersistenceConfig

    async def setup(self, ctx: Context, config: PersistenceConfig) -> None:
        ctx.provide(
            SESSION_PERSISTENCE,
            PostgresSessionPersistence(ctx.require(DATABASE).get_conn),
        )
