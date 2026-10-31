import unittest
from unittest.mock import patch

from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import (
    ExecutionScope,
    TOOLS,
    ToolCall,
    ToolContext,
    ToolResult,
)
from agent_platform_tools_default import ToolsDefaultPlugin

from agent_platform_mcp_client import McpClientPlugin, McpToolInfo


class FakeConnection:
    instances = []

    def __init__(self, config):
        self.config = config
        self.calls = []
        self.closed = False
        self.tools = (
            McpToolInfo(
                name="echo_tool",
                description="Echo via MCP",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            ),
        )
        FakeConnection.instances.append(self)

    async def connect(self):
        pass

    async def aclose(self):
        self.closed = True

    async def call(self, raw_name, arguments):
        self.calls.append((raw_name, arguments))
        return ToolResult(data={"raw": raw_name, "arguments": arguments})


class FailingConnection(FakeConnection):
    async def connect(self):
        raise RuntimeError("server unavailable")


class DuplicateToolConnection(FakeConnection):
    def __init__(self, config):
        super().__init__(config)
        self.tools = (self.tools[0], self.tools[0])


class McpPluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeConnection.instances = []

    async def test_mcp_tools_register_and_execute_through_tools_default(self):
        config = {
            "version": 1,
            "plugins": [
                {"id": "tools", "name": "agent-platform.tools-default"},
                {
                    "id": "mcp",
                    "name": "agent-platform.mcp-client",
                    "config": {
                        "server_name": "demo",
                        "transport": "http",
                        "url": "http://example.invalid/mcp",
                    },
                },
            ],
        }
        with patch("agent_platform_mcp_client.plugin.McpConnection", FakeConnection):
            runtime = PluginRuntime(
                config,
                catalog=MappingCatalog(
                    {
                        "agent-platform.tools-default": ToolsDefaultPlugin,
                        "agent-platform.mcp-client": McpClientPlugin,
                    }
                ),
            )
            await runtime.start()
            tools = runtime.require(TOOLS)
            result = await tools.execute(
                ToolCall(
                    call_id="1",
                    name="echo_tool",
                    arguments={"text": "hi"},
                ),
                ToolContext(
                    scope=ExecutionScope(tenant_id=1, agent_key="agent"),
                    visible_tool_names=frozenset({"echo_tool"}),
                ),
            )
            self.assertEqual(
                result.data, {"raw": "echo_tool", "arguments": {"text": "hi"}}
            )
            connection = FakeConnection.instances[0]
            self.assertEqual(connection.calls, [("echo_tool", {"text": "hi"})])

            await runtime.aclose()
            self.assertTrue(connection.closed)

    async def test_unavailable_server_does_not_break_tools_default(self):
        config = {
            "version": 1,
            "plugins": [
                {"id": "tools", "name": "agent-platform.tools-default"},
                {
                    "id": "mcp",
                    "name": "agent-platform.mcp-client",
                    "config": {
                        "server_name": "demo",
                        "transport": "http",
                        "url": "http://example.invalid/mcp",
                    },
                },
            ],
        }
        with patch(
            "agent_platform_mcp_client.plugin.McpConnection", FailingConnection
        ):
            runtime = PluginRuntime(
                config,
                catalog=MappingCatalog(
                    {
                        "agent-platform.tools-default": ToolsDefaultPlugin,
                        "agent-platform.mcp-client": McpClientPlugin,
                    }
                ),
            )
            await runtime.start()
            self.assertEqual(
                [plugin.name for plugin in runtime.plugins],
                ["agent-platform.tools-default", "agent-platform.mcp-client"],
            )
            await runtime.aclose()

    async def test_duplicate_tool_names_are_contained(self):
        config = {
            "version": 1,
            "plugins": [
                {"id": "tools", "name": "agent-platform.tools-default"},
                {
                    "id": "mcp",
                    "name": "agent-platform.mcp-client",
                    "config": {
                        "server_name": "demo",
                        "transport": "http",
                        "url": "http://example.invalid/mcp",
                    },
                },
            ],
        }
        with patch(
            "agent_platform_mcp_client.plugin.McpConnection",
            DuplicateToolConnection,
        ):
            runtime = PluginRuntime(
                config,
                catalog=MappingCatalog(
                    {
                        "agent-platform.tools-default": ToolsDefaultPlugin,
                        "agent-platform.mcp-client": McpClientPlugin,
                    }
                ),
            )
            await runtime.start()
            tools = runtime.require(TOOLS)
            self.assertEqual(
                [d.name for d in await tools.list_for_agent(
                    ExecutionScope(tenant_id=1, agent_key="agent")
                )],
                ["echo_tool"],
            )
            await runtime.aclose()

    async def test_prefix_is_applied_to_public_names(self):
        config = {
            "version": 1,
            "plugins": [
                {"id": "tools", "name": "agent-platform.tools-default"},
                {
                    "id": "mcp",
                    "name": "agent-platform.mcp-client",
                    "config": {
                        "server_name": "demo",
                        "transport": "http",
                        "url": "http://example.invalid/mcp",
                        "tool_prefix": "mcp__demo__",
                    },
                },
            ],
        }
        with patch("agent_platform_mcp_client.plugin.McpConnection", FakeConnection):
            runtime = PluginRuntime(
                config,
                catalog=MappingCatalog(
                    {
                        "agent-platform.tools-default": ToolsDefaultPlugin,
                        "agent-platform.mcp-client": McpClientPlugin,
                    }
                ),
            )
            await runtime.start()
            tools = runtime.require(TOOLS)
            await tools.execute(
                ToolCall(
                    call_id="1",
                    name="mcp__demo__echo_tool",
                    arguments={"text": "hi"},
                ),
                ToolContext(
                    scope=ExecutionScope(tenant_id=1, agent_key="agent"),
                    visible_tool_names=frozenset({"mcp__demo__echo_tool"}),
                ),
            )
            self.assertEqual(
                FakeConnection.instances[0].calls,
                [("echo_tool", {"text": "hi"})],
            )
            await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
