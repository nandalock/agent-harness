"""Validated configuration for one MCP server instance."""
import re
from typing import Annotated, Literal, Self

from agent_platform_plugin_sdk import SdkModel
from pydantic import Field, StrictFloat, field_validator, model_validator

_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_TOOL_PREFIX = re.compile(r"^[A-Za-z0-9_-]*$")


class McpServerConfig(SdkModel):
    """One MCP server: HTTP/streamable-http or stdio, never both transports."""

    server_name: Annotated[str, Field(min_length=1, max_length=32)]
    transport: Literal["http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Annotated[StrictFloat, Field(gt=0)] = 300.0
    execution_mode: Literal["parallel", "exclusive"] = "parallel"
    #: Prepended to every raw MCP tool name. Empty preserves existing bindings.
    tool_prefix: str = ""

    @field_validator("server_name")
    @classmethod
    def valid_server_name(cls, value: str) -> str:
        if not _SERVER_NAME.fullmatch(value):
            raise ValueError("server_name must match [A-Za-z0-9_-]{1,32}")
        return value

    @field_validator("tool_prefix")
    @classmethod
    def valid_tool_prefix(cls, value: str) -> str:
        if not _TOOL_PREFIX.fullmatch(value):
            raise ValueError("tool_prefix must match [A-Za-z0-9_-]*")
        return value

    @model_validator(mode="after")
    def transport_fields(self) -> Self:
        if self.transport == "http":
            if not (self.url or "").strip():
                raise ValueError("http transport requires url")
        else:
            if not (self.command or "").strip():
                raise ValueError("stdio transport requires command")
        return self
