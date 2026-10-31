"""MCP server tools as an Agent Platform plugin."""
from .client import McpConnection, McpToolInfo
from .config import McpServerConfig
from .manager import (
    MCP_MANAGER,
    ManagedMcpServer,
    McpManager,
    McpManagerConfig,
    McpManagerPlugin,
)
from .names import public_tool_name
from .plugin import McpClientPlugin
from .registration import McpRegistration, McpToolExecutor, register_mcp_tools

__version__ = "0.1.0"

__all__ = [
    "MCP_MANAGER",
    "ManagedMcpServer",
    "McpClientPlugin",
    "McpConnection",
    "McpManager",
    "McpManagerConfig",
    "McpManagerPlugin",
    "McpRegistration",
    "McpServerConfig",
    "McpToolExecutor",
    "McpToolInfo",
    "public_tool_name",
    "register_mcp_tools",
]
