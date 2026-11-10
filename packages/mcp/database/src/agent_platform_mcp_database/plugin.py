"""Load generic MCP server rows into the manager after the database starts."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from agent_platform_mcp_client import MCP_MANAGER, McpServerConfig
from agent_platform_managed_mcp import owns_database_row
from agent_platform_plugin_sdk import (
    DATABASE,
    SdkModel,
)
from minidsh_cordis import Context, Plugin

logger = logging.getLogger(__name__)


class McpDatabaseConfig(SdkModel):
    enabled: bool = True


def _load_rows(database: Any) -> list[dict[str, Any]]:
    with database.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, transport, url, command, args, env "
                "FROM mcp_servers ORDER BY id"
            )
            return [dict(row) for row in cur.fetchall()]


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def config_from_row(row: dict[str, Any]) -> McpServerConfig | None:
    """Translate one persisted row into the same shape used by YAML entries."""
    transport = row.get("transport") or "http"
    config: dict[str, Any] = {
        "server_name": f"mcp{row['id']}",
        "transport": transport,
        "timeout_seconds": 300,
        "tool_prefix": "",
    }
    if transport == "http":
        if not row.get("url"):
            return None
        config["url"] = row["url"]
    else:
        if not row.get("command"):
            return None
        config["command"] = row["command"]
        args = _json_value(row.get("args"), [])
        config["args"] = list(args) if isinstance(args, list) else []
        env = _json_value(row.get("env"), {})
        config["env"] = (
            {str(key): str(value) for key, value in env.items()}
            if isinstance(env, dict)
            else {}
        )
    try:
        return McpServerConfig(**config)
    except ValidationError as exc:
        logger.warning("MCP server row %s is invalid, skipping: %s", row.get("id"), exc)
        return None


class McpDatabasePlugin(Plugin[McpDatabaseConfig]):
    name = "agent-platform.mcp-database"
    version = "0.1.0"
    requires = (MCP_MANAGER, DATABASE)
    config_model = McpDatabaseConfig

    async def setup(self, ctx: Context, config: McpDatabaseConfig) -> None:
        if not config.enabled:
            return
        if os.environ.get("PLUGIN_MCP_AUTO", "true").lower() in ("0", "false", "no"):
            return
        manager = ctx.require(MCP_MANAGER)
        database = ctx.require(DATABASE)
        try:
            rows = await asyncio.to_thread(_load_rows, database)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 MCP server 配置失败，跳过 DB 自动装配: %s", exc)
            return

        for row in rows:
            if owns_database_row(row):
                continue
            server_config = config_from_row(row)
            if server_config is None:
                continue
            try:
                server = await manager.add(server_config, owner=ctx.instance_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MCP server %r 自动装配失败，跳过其工具: %s",
                    server_config.server_name,
                    exc,
                )
                continue

            server_name = server_config.server_name
            token = server.token

            async def disconnect(name: str = server_name, current=token) -> None:
                await manager.remove(name, current)

            ctx.on_dispose(disconnect, label=f"mcp-database({server_name})")


plugin = McpDatabasePlugin()
