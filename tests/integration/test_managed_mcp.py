import socket
import unittest
from unittest.mock import patch

from agent_platform_plugin_runtime import PluginRuntime, MappingCatalog
from agent_platform_plugin_sdk import PluginSpec, SdkModel, ServiceRequirement, TOOLS, ExecutionScope, ToolCall, ToolContext
from agent_platform_tools_default import ToolsDefaultPlugin
from agent_platform_mcp_client import McpManagerPlugin, MCP_MANAGER
from agent_platform_managed_mcp import BuiltinPlugin, PaperPlugin, OverleafPlugin


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def runtime_for(plugin, port, failing=False):
    class Fail:
        spec = PluginSpec(name="test.fail", version="0.1.0", requires=(ServiceRequirement(service=MCP_MANAGER.ref),))
        config_model = SdkModel

        async def setup(self, ctx, config):
            raise RuntimeError("rollback-test")

    entries = [
        {"id": "tools", "name": "agent-platform.tools-default"},
        {"id": "manager", "name": "agent-platform.mcp-manager"},
        {"id": "service", "name": plugin.spec.name, "config": {"port": port}},
    ]
    if failing:
        entries.append({"id": "failure", "name": "test.fail"})
    return PluginRuntime({"plugins": entries}, catalog=MappingCatalog({
        "agent-platform.tools-default": ToolsDefaultPlugin, "agent-platform.mcp-manager": McpManagerPlugin,
        plugin.spec.name: plugin, "test.fail": Fail,
    }))


class ManagedMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_tools_and_port_are_owned_and_reusable(self):
        port = free_port()
        for _ in range(2):
            runtime = runtime_for(PaperPlugin, port)
            with patch.dict("os.environ", {"MANAGED_MCP_ENABLED": "true"}), patch("agent_platform_managed_mcp.server_id", return_value=2):
                try:
                    await runtime.start()
                    tools = runtime.require(TOOLS)
                    scope = ExecutionScope(tenant_id=1, agent_key="test")
                    self.assertEqual(len(await tools.list_for_agent(scope)), 4)
                    result = await tools.execute(ToolCall(call_id="test", name="list_papers"),
                                                 ToolContext(scope=scope, visible_tool_names=frozenset({"list_papers"})))
                    self.assertEqual(result.status, "success", result)
                    await runtime.require(MCP_MANAGER).reconnect("mcp2")
                finally:
                    await runtime.aclose()
            with socket.socket() as sock:
                self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)

    async def test_later_failure_rolls_back_http_listener(self):
        port = free_port()
        runtime = runtime_for(BuiltinPlugin, port, failing=True)
        with patch.dict("os.environ", {"MANAGED_MCP_ENABLED": "true"}), patch("agent_platform_managed_mcp.server_id", return_value=1):
            with self.assertRaisesRegex(RuntimeError, "rollback-test"):
                await runtime.start()
            await runtime.aclose()
        with socket.socket() as sock:
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)

    async def test_disabled_optional_integration_does_not_touch_database(self):
        runtime = runtime_for(OverleafPlugin, free_port())
        with patch.dict("os.environ", {"OVERLEAF_ENABLED": "false", "MANAGED_MCP_ENABLED": "true"}), patch("agent_platform_managed_mcp.server_id") as lookup:
            try:
                await runtime.start()
                lookup.assert_not_called()
                self.assertEqual(await runtime.require(TOOLS).list_for_agent(ExecutionScope(tenant_id=1, agent_key="test")), ())
            finally:
                await runtime.aclose()

    async def test_bind_failure_is_a_runtime_error_not_process_exit(self):
        from agent_platform_managed_mcp.http import start_server
        from fastapi import FastAPI
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with self.assertRaises(RuntimeError):
                await start_server(FastAPI(), occupied.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
