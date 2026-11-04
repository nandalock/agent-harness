"""MCP connection manager: dynamic add/remove/probe/reconnect.

Configuration remains plugin-owned: each statically configured server is one
``mcp-client`` instance. The manager is the host-facing control plane for
servers created at runtime (DB CRUD/import) and for connectivity probes. It
does not read a database; the host supplies a validated config.
"""
import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from agent_platform_plugin_sdk import (
    JsonObject,
    Plugin,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceKey,
    ServiceRef,
    ServiceRequirement,
    TOOLS,
    TOOL_UNAVAILABLE,
    ToolsService,
    ToolError,
    ToolResult,
)

from .client import McpConnection, McpToolInfo
from .config import McpServerConfig
from .registration import McpRegistration, register_mcp_tools

logger = logging.getLogger(__name__)

MCP_MANAGER: ServiceKey["McpManager"] = ServiceKey(
    ServiceRef(name="mcp.manager", api_version=1)
)


def _error(message: str) -> ToolResult:
    return ToolResult(
        status="error", error=ToolError(code=TOOL_UNAVAILABLE, message=message)
    )


@dataclass
class ManagedMcpServer:
    server_name: str
    config: McpServerConfig
    connection: McpConnection
    registration: McpRegistration
    token: object = field(default_factory=object)
    owner: str | None = None

    async def aclose(self) -> None:
        await self.registration.aclose()
        await self.connection.aclose()


class McpManager:
    """One runtime scope's live MCP connections."""

    def __init__(self, tools: ToolsService) -> None:
        self._tools = tools
        self._servers: dict[str, ManagedMcpServer] = {}
        self._closed = False
        self._lock = asyncio.Lock()

    # ── lifecycle ──

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        servers, self._servers = self._servers, {}
        for server in servers.values():
            try:
                await server.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("关闭 MCP server %s 失败: %s", server.server_name, exc)

    async def adopt(self, server: ManagedMcpServer, *, owner: str | None = None) -> object:
        """Adopt a statically configured plugin connection; returns an ownership token."""
        async with self._lock:
            server.owner = owner
            previous = self._servers.get(server.server_name)
            if previous is not None:
                await previous.aclose()
            self._servers[server.server_name] = server
            return server.token

    async def forget(self, server_name: str, token: object) -> None:
        """Drop an adopted entry without closing it (the plugin context owns it)."""
        async with self._lock:
            current = self._servers.get(server_name)
            if current is not None and current.token is token:
                del self._servers[server_name]

    # ── control plane ──

    def get(self, server_name: str) -> ManagedMcpServer | None:
        return self._servers.get(server_name)

    def list_managed(self) -> list[dict[str, Any]]:
        return [
            {
                "server_name": server.server_name,
                "transport": server.config.transport,
                "owner": server.owner,
                "tools": sorted(server.registration.tool_registrations),
            }
            for server in self._servers.values()
        ]

    async def probe(self, config: McpServerConfig) -> tuple[McpToolInfo, ...]:
        """Connect temporarily and return the current tool list (stdio probe included)."""
        connection = McpConnection(config)
        try:
            await connection.connect()
            return connection.tools
        finally:
            await connection.aclose()

    async def add(
        self, config: McpServerConfig, *, owner: str | None = None
    ) -> ManagedMcpServer:
        """Connect one server and publish its tools; replaces an existing generation."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("MCP manager is closed")
            previous = self._servers.pop(config.server_name, None)
            if previous is not None:
                await previous.aclose()
            connection = McpConnection(config)
            try:
                await connection.connect()
                registration = register_mcp_tools(self._tools, config, connection, plugin_id=owner)
            except BaseException:
                await connection.aclose()
                raise
            server = ManagedMcpServer(
                server_name=config.server_name,
                config=config,
                connection=connection,
                registration=registration,
                owner=owner,
            )
            self._servers[config.server_name] = server
            return server

    async def ensure(
        self, config: McpServerConfig, *, owner: str | None = None
    ) -> ManagedMcpServer:
        server = self.get(config.server_name)
        if server is not None:
            return server
        return await self.add(config, owner=owner)

    async def remove(self, server_name: str, token: object | None = None) -> bool:
        async with self._lock:
            server = self._servers.get(server_name)
            if server is None:
                return False
            if token is not None and server.token is not token:
                return False
            del self._servers[server_name]
            await server.aclose()
            return True

    async def reconnect(
        self, server_name: str, config: McpServerConfig | None = None
    ) -> ManagedMcpServer:
        existing = self.get(server_name)
        effective = config or (existing.config if existing is not None else None)
        if effective is None:
            raise KeyError(f"MCP server is not managed: {server_name}")
        await self.remove(server_name)
        return await self.add(effective, owner=existing.owner if existing else None)

    async def call(
        self,
        server_name: str,
        raw_name: str,
        arguments: JsonObject,
        *,
        config: McpServerConfig | None = None,
    ) -> ToolResult:
        """Call one raw MCP tool, reconnecting once when the transport is gone."""
        server = self.get(server_name)
        try:
            if server is None:
                if config is None:
                    return _error(f"MCP server 未连接: {server_name}")
                server = await self.add(config)
            effective = config or server.config
            result = await server.connection.call(raw_name, arguments)
            if (
                result.error is not None
                and result.error.code == TOOL_UNAVAILABLE
            ):
                server = await self.reconnect(server_name, effective)
                return await server.connection.call(raw_name, arguments)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            retry_config: McpServerConfig | None = (
                config or (server.config if server is not None else None)
            )
            if retry_config is None:
                return _error(f"MCP 调用失败: {exc}")
            logger.warning("MCP server %s 调用失败，重连后重试: %s", server_name, exc)
            server = await self.reconnect(server_name, retry_config)
            try:
                return await server.connection.call(raw_name, arguments)
            except asyncio.CancelledError:
                raise
            except Exception as retry_exc:  # noqa: BLE001
                return _error(f"MCP 重连后仍失败: {retry_exc}")


class McpManagerConfig(SdkModel):
    pass


class McpManagerPlugin:
    """Publish the dynamic MCP control plane on ``mcp.manager.v1``."""

    spec = PluginSpec(
        name="agent-platform.mcp-manager",
        version="0.1.0",
        requires=(ServiceRequirement(service=TOOLS.ref),),
        provides=(MCP_MANAGER.ref,),
    )
    config_model = McpManagerConfig

    async def setup(self, ctx: PluginContext, config: McpManagerConfig) -> None:
        manager = McpManager(ctx.require(TOOLS))
        ctx.provide(MCP_MANAGER, manager)
        ctx.on_dispose(manager.aclose, label="mcp-manager")


plugin: Plugin[McpManagerConfig] = McpManagerPlugin()
