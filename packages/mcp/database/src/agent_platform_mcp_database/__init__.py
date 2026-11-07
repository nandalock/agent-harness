"""Persisted MCP server rows as a plugin-owned manager extension."""
from .plugin import McpDatabaseConfig, McpDatabasePlugin, config_from_row

__all__ = ["McpDatabaseConfig", "McpDatabasePlugin", "config_from_row"]
