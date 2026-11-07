"""Database plugin: owns the pooled connection factory and schema bootstrap."""
import asyncio
import os

from pydantic import Field

from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel

from .database import DEFAULT_DATABASE_URL, PostgresDatabase
from .schema import init_db
from .services import DATABASE


class DatabaseConfig(SdkModel):
    dsn: str | None = None
    initialize_schema: bool = Field(default=False, alias="initializeSchema")


class PostgresDatabasePlugin:
    spec = PluginSpec(
        name="agent-platform.database-postgres",
        version="0.1.0",
        provides=(DATABASE.ref,),
    )
    config_model = DatabaseConfig

    async def setup(self, ctx: PluginContext, config: DatabaseConfig) -> None:
        database = PostgresDatabase(
            config.dsn or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        )
        if config.initialize_schema:
            await asyncio.to_thread(init_db, database)
        ctx.provide(DATABASE, database)
        ctx.on_dispose(database.aclose, label="postgres pool")
