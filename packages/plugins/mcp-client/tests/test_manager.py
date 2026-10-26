"""Dynamic MCP manager: add, call, reconnect, remove."""
import sys
import unittest

from agent_platform_mcp_client import McpManager, McpServerConfig
from agent_platform_plugin_sdk import ExecutionScope, ToolsService
from agent_platform_tools_default import ToolsDefaultService

_ECHO_SERVER = r'''
import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo")

@mcp.tool()
async def echo_marker(marker: str) -> str:
    await asyncio.sleep(0.01)
    return marker

mcp.run()
'''


def _config() -> McpServerConfig:
    return McpServerConfig(
        server_name="echo",
        transport="stdio",
        command=sys.executable,
        args=("-c", _ECHO_SERVER),
        timeout_seconds=20,
    )


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tools: ToolsService = ToolsDefaultService()
        self.manager = McpManager(self.tools)

    async def asyncTearDown(self):
        await self.manager.aclose()
        await self.tools.aclose()

    async def test_add_call_reconnect_remove(self):
        server = await self.manager.add(_config())
        self.assertEqual(sorted(server.registration.tool_registrations), ["echo_marker"])

        scope = ExecutionScope(tenant_id=1, agent_key="agent")
        listed = await self.tools.list_for_agent(scope)
        self.assertEqual([tool.name for tool in listed], ["echo_marker"])
        self.assertEqual(listed[0].plugin_id, "mcp-echo")
        self.assertEqual(listed[0].plugin_name, "agent-platform.mcp-client")

        result = await self.manager.call("echo", "echo_marker", {"marker": "hello"})
        self.assertIsNone(result.error)
        self.assertEqual(result.data["rows"], [{"text": "hello"}])

        # Simulate a lost transport: the next call reconnects once and succeeds.
        await server.connection.aclose()
        result = await self.manager.call("echo", "echo_marker", {"marker": "again"})
        self.assertIsNone(result.error)
        self.assertEqual(result.data["rows"], [{"text": "again"}])

        self.assertTrue(await self.manager.remove("echo"))
        listed = await self.tools.list_for_agent(scope)
        self.assertEqual(list(listed), [])

    async def test_probe_does_not_register_tools(self):
        tools = await self.manager.probe(_config())
        self.assertEqual([tool.name for tool in tools], ["echo_marker"])
        scope = ExecutionScope(tenant_id=1, agent_key="agent")
        self.assertEqual(list(await self.tools.list_for_agent(scope)), [])


if __name__ == "__main__":
    unittest.main()
