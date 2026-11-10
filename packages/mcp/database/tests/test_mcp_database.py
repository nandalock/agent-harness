import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent_platform_mcp_client import MCP_MANAGER
from agent_platform_mcp_database import McpDatabasePlugin, config_from_row
from agent_platform_plugin_runtime import MappingCatalog, PluginLoader
from agent_platform_plugin_sdk import DATABASE


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append(sql)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakeCursor(self.rows)


class FakeDatabase:
    def __init__(self, rows):
        self.rows = rows

    def get_conn(self):
        class Context:
            def __enter__(self_inner):
                return FakeConnection(self.rows)

            def __exit__(self_inner, *exc):
                return False

        return Context()


class FakeManager:
    def __init__(self):
        self.added = []
        self.removed = []

    async def add(self, config, *, owner=None):
        server = SimpleNamespace(token=object(), config=config, owner=owner)
        self.added.append((config, owner))
        return server

    async def remove(self, name, token):
        self.removed.append((name, token))
        return True


def test_config_from_row_builds_http_and_stdio_entries():
    http = config_from_row({
        "id": 1, "name": "local", "transport": "http",
        "url": "http://localhost:9001/mcp", "command": None, "args": None, "env": None,
    })
    assert http.server_name == "mcp1"
    assert http.url == "http://localhost:9001/mcp"

    stdio = config_from_row({
        "id": 2, "name": "stdio", "transport": "stdio", "url": None,
        "command": "npx", "args": '["-y", "server"]', "env": '{"A": "B"}',
    })
    assert stdio.command == "npx"
    assert tuple(stdio.args) == ("-y", "server")
    assert stdio.env == {"A": "B"}

    assert config_from_row({"id": 3, "transport": "http", "url": None}) is None


class McpDatabasePluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_rows_are_added_and_managed_rows_are_skipped(self):
        manager = FakeManager()
        database = FakeDatabase([
            {"id": 1, "name": "generic", "transport": "http", "url": "http://localhost:9999/mcp",
             "command": None, "args": None, "env": None},
            {"id": 2, "name": "overleaf", "transport": "stdio", "url": None,
             "command": "/python", "args": None, "env": None},
        ])
        runtime = PluginLoader(
            {"plugins": [{"id": "mcp-db", "name": "agent-platform.mcp-database"}]},
            catalog=MappingCatalog({"agent-platform.mcp-database": McpDatabasePlugin}),
            host_services={MCP_MANAGER: manager, DATABASE: database},
        )
        try:
            with patch.dict(os.environ, {"PLUGIN_MCP_AUTO": "true"}):
                await runtime.start()
            self.assertEqual(len(manager.added), 1)
            config, owner = manager.added[0]
            self.assertEqual(config.server_name, "mcp1")
            self.assertEqual(owner, "mcp-db")
        finally:
            await runtime.aclose()
        self.assertEqual([name for name, _ in manager.removed], ["mcp1"])
