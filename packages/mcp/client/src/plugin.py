"""Plugin entry: one configured MCP server registers its tools into tools.v1."""
import asyncio
import logging

from agent_platform_plugin_sdk import (
    Plugin,
    PluginContext,
    PluginSpec,
    ServiceRequirement,
    TOOLS,
)

from .client import McpConnection
from .config import McpServerConfig
from .manager import MCP_MANAGER, ManagedMcpServer, McpManager
from .registration import register_mcp_tools

logger = logging.getLogger(__name__)


class McpClientPlugin:
    spec = PluginSpec(
        name="agent-platform.mcp-client",
        version="0.1.0",
        requires=(
            ServiceRequirement(service=TOOLS.ref),
            ServiceRequirement(service=MCP_MANAGER.ref, optional=True),
        ),
    )
    config_model = McpServerConfig

    async def setup(self, ctx: PluginContext, config: McpServerConfig) -> None:
        tools = ctx.require(TOOLS)
        manager: McpManager | None = ctx.get(MCP_MANAGER)
        connection = McpConnection(config)
        try:
            await connection.connect()
        except asyncio.CancelledError:
            raise
        except BaseExceptionGroup as exc:
            # The MCP SDK wraps transport failures (including an HTTP error)
            # in an anyio task-group exception group. Re-raise only if OUR task
            # is being cancelled; otherwise treat it as an unavailable server.
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            await connection.aclose()
            logger.warning(
                "MCP server %r 连接失败，跳过其工具: %s",
                config.server_name,
                exc,
            )
            return
        except Exception as exc:  # noqa: BLE001
            # One unavailable server must not take down the whole plugin tree
            # (and with it tools-default and every other tool plugin).
            await connection.aclose()
            logger.warning(
                "MCP server %r 连接失败，跳过其工具: %s",
                config.server_name,
                exc,
            )
            return
        ctx.on_dispose(
            connection.aclose, label=f"mcp-client({config.server_name})"
        )

        registration = register_mcp_tools(tools, config, connection, plugin_id=ctx.instance_id)
        ctx.track(registration.executor_registration)
        for item in registration.tool_registrations.values():
            ctx.track(item)

        if manager is not None:
            server = ManagedMcpServer(
                server_name=config.server_name,
                config=config,
                connection=connection,
                registration=registration,
                owner=ctx.instance_id,
            )
            token = await manager.adopt(server, owner=ctx.instance_id)
            ctx.on_dispose(
                lambda: manager.forget(config.server_name, token),
                label=f"mcp-manager forget({config.server_name})",
            )


plugin: Plugin[McpServerConfig] = McpClientPlugin()
