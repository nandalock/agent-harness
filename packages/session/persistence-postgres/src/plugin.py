"""PostgreSQL session-persistence plugin."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel, ServiceRequirement

from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .services import DATABASE
from .postgres import PostgresSessionPersistence


class PersistenceConfig(SdkModel):
    pass


class PostgresPersistencePlugin:
    spec = PluginSpec(
        name="agent-platform.session-persistence-postgres",
        version="0.1.0",
        provides=(SESSION_PERSISTENCE.ref,),
        requires=(
            ServiceRequirement(service=DATABASE.ref),
            ServiceRequirement(service=SESSIONS.ref),
        ),
    )
    config_model = PersistenceConfig

    async def setup(self, ctx: PluginContext, config: PersistenceConfig) -> None:
        ctx.provide(
            SESSION_PERSISTENCE,
            PostgresSessionPersistence(ctx.require(DATABASE).get_conn),
        )
