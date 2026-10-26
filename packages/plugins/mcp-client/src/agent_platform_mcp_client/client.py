"""MCP session wrapper: connect, discover tools, call one MCP tool."""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from agent_platform_plugin_sdk import (
    JsonObject,
    JsonValue,
    ToolError,
    ToolResult,
    TOOL_UNAVAILABLE,
)
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .config import McpServerConfig

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: JsonObject


class McpConnection:
    """One live MCP session owned by one plugin instance."""

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._transport: Any = None
        self._session: ClientSession | None = None
        self._tools: tuple[McpToolInfo, ...] = ()

    @staticmethod
    def _outer_cancellation() -> bool:
        task = asyncio.current_task()
        return task is not None and task.cancelling() > 0

    @staticmethod
    def _transport_cancelled(exc: asyncio.CancelledError) -> bool:
        """The MCP HTTP transport cancels its own anyio scope on handshake errors."""
        return "Cancelled via cancel scope" in str(exc)

    async def connect(self) -> None:
        try:
            if self._config.transport == "http":
                assert self._config.url is not None
                self._transport = streamablehttp_client(
                    self._config.url,
                    timeout=_CONNECT_TIMEOUT,
                    sse_read_timeout=self._config.timeout_seconds,
                )
            else:
                assert self._config.command is not None
                params = StdioServerParameters(
                    command=self._config.command,
                    args=list(self._config.args),
                    env=dict(self._config.env) or None,
                )
                self._transport = stdio_client(params)

            entered = await self._transport.__aenter__()
            read, write = entered[0], entered[1]
            self._session = await ClientSession(read, write).__aenter__()
            await self._session.initialize()
            listed = await self._session.list_tools()
            self._tools = tuple(
                McpToolInfo(
                    name=tool.name,
                    description=tool.description or tool.name,
                    input_schema=cast(JsonObject, tool.inputSchema)
                    if isinstance(tool.inputSchema, dict)
                    else {},
                )
                for tool in listed.tools
            )
        except asyncio.CancelledError as exc:
            # The MCP streamable-http transport cancels its own anyio task group
            # when the HTTP handshake fails. That is a connection failure, not
            # cancellation of this plugin task.
            if self._transport_cancelled(exc) or not self._outer_cancellation():
                raise ConnectionError(
                    f"MCP 连接被传输层取消: {self._config.server_name}"
                ) from None
            raise
        logger.info(
            "MCP 已连接 (%s, %s)，%d 个工具",
            self._config.transport,
            self._config.server_name,
            len(self._tools),
        )

    async def aclose(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except asyncio.CancelledError as exc:
                if not self._transport_cancelled(exc) and self._outer_cancellation():
                    raise
                logger.warning("MCP session 关闭被传输层取消")
            except BaseExceptionGroup as exc:
                logger.warning("MCP session 关闭失败: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP session 关闭失败: %s", exc)
            self._session = None
        if self._transport is not None:
            try:
                await self._transport.__aexit__(None, None, None)
            except asyncio.CancelledError as exc:
                if not self._transport_cancelled(exc) and self._outer_cancellation():
                    raise
                logger.warning("MCP transport 关闭被传输层取消")
            except BaseExceptionGroup as exc:
                logger.warning("MCP transport 关闭失败: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP transport 关闭失败: %s", exc)
            self._transport = None

    @property
    def tools(self) -> tuple[McpToolInfo, ...]:
        return self._tools

    async def call(self, raw_name: str, arguments: JsonObject) -> ToolResult:
        if self._session is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_UNAVAILABLE, message="MCP 会话未连接"
                ),
            )
        result = await asyncio.wait_for(
            self._session.call_tool(raw_name, arguments),
            timeout=self._config.timeout_seconds,
        )
        content: list[JsonObject] = []
        rows: list[JsonValue] = []
        for block in result.content:
            if hasattr(block, "model_dump"):
                item = cast(
                    JsonObject, block.model_dump(mode="json", exclude_none=True)
                )
            elif isinstance(block, dict):
                item = cast(JsonObject, block)
            else:
                item = {"type": "text", "text": str(block)}
            content.append(item)
            if item.get("type") == "text":
                text = str(item.get("text", ""))
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    rows.append({"text": text})
                else:
                    if isinstance(parsed, list):
                        rows.extend(cast(list[JsonValue], parsed))
                    else:
                        rows.append(cast(JsonValue, parsed))

        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)
        data: JsonObject = {
            "content": cast(list[JsonValue], content),
            "rows": rows,
            "count": len(rows),
        }
        if structured is not None:
            data["structuredContent"] = cast(JsonValue, structured)

        if getattr(result, "isError", False):
            message = next(
                (str(item.get("text")) for item in content if item.get("type") == "text"),
                f"MCP 工具返回错误: {raw_name}",
            )
            return ToolResult(
                status="error",
                error=ToolError(code="mcp.tool_error", message=message),
                data=data,
            )
        return ToolResult(data=data)
