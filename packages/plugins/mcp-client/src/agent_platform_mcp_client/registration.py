"""Register one MCP connection's tools on tools.v1.

Both the static ``mcp-client`` plugin and the dynamic ``mcp-manager`` use this
helper, so naming, schema normalization, conflict containment and ownership are
implemented once.
"""
from dataclasses import dataclass, field
import logging
from typing import Any

from agent_platform_plugin_sdk import (
    JsonObject,
    Registration,
    RegistrationConflictError,
    TOOL_NOT_FOUND,
    ToolsService,
    ToolDescriptor,
    ToolError,
    ToolExecutor,
    ToolResult,
)

from .client import McpConnection
from .config import McpServerConfig
from .names import public_tool_name

logger = logging.getLogger(__name__)


class McpToolExecutor:
    """Shared executor for one server; maps public names back to raw MCP names."""

    def __init__(self, connection: McpConnection) -> None:
        self._connection = connection
        self._raw_names: dict[str, str] = {}

    def bind(self, public_name: str, raw_name: str) -> None:
        self._raw_names[public_name] = raw_name

    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: JsonObject,
        context: Any,
    ) -> ToolResult:
        raw_name = self._raw_names.get(descriptor.name)
        if raw_name is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_NOT_FOUND,
                    message=f"MCP 工具未注册: {descriptor.name}",
                ),
            )
        return await self._connection.call(raw_name, arguments)


@dataclass
class McpRegistration:
    """Owned registrations for one server generation."""

    executor_name: str
    executor: McpToolExecutor
    executor_registration: Registration
    tool_registrations: dict[str, Registration] = field(default_factory=dict)
    public_to_raw: dict[str, str] = field(default_factory=dict)

    async def aclose(self) -> None:
        for registration in self.tool_registrations.values():
            await registration.aclose()
        self.tool_registrations.clear()
        await self.executor_registration.aclose()


def register_mcp_tools(
    tools: ToolsService,
    config: McpServerConfig,
    connection: McpConnection,
    *,
    executor_name: str | None = None,
    plugin_id: str | None = None,
) -> McpRegistration:
    """Register the connection's current tools; duplicate names are contained."""
    executor = McpToolExecutor(connection)
    name = executor_name or f"mcp.{config.server_name}"
    executor_registration = tools.register_executor(name, executor)
    registration = McpRegistration(
        executor_name=name,
        executor=executor,
        executor_registration=executor_registration,
    )
    for tool in connection.tools:
        public = public_tool_name(config.tool_prefix, tool.name)
        schema: JsonObject = tool.input_schema
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        try:
            registered = tools.register_tool(
                ToolDescriptor(
                    name=public,
                    executor=name,
                    description=tool.description,
                    input_schema=schema,
                    timeout_seconds=config.timeout_seconds,
                    execution_mode=config.execution_mode,
                    plugin_id=plugin_id or f"mcp-{config.server_name}",
                    plugin_name="agent-platform.mcp-client",
                )
            )
        except RegistrationConflictError as exc:
            logger.warning(
                "MCP tool %r from %r conflicts with an existing tool, skipping: %s",
                public,
                config.server_name,
                exc,
            )
            continue
        executor.bind(public, tool.name)
        registration.tool_registrations[public] = registered
        registration.public_to_raw[public] = tool.name
    return registration
