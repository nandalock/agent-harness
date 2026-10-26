import tempfile
import unittest
from pathlib import Path

from agent_platform_plugin_sdk import (
    ExecutionScope,
    TOOLS,
    ToolCall,
    ToolContext,
)

from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from support import EchoPlugin, FakeTools, ToolsPlugin


def echo_context() -> ToolContext:
    return ToolContext(
        scope=ExecutionScope(tenant_id=7, agent_key="assistant"),
        visible_tool_names=frozenset({"echo"}),
    )


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_provided_tools_service_is_resolved_and_closed(self):
        runtime = PluginRuntime(
            {
                "version": 1,
                "plugins": [
                    {"id": "echo", "name": "test.echo", "config": {"prefix": "收到："}},
                    {"id": "tools", "name": "test.tools"},
                ],
            },
            catalog=MappingCatalog(
                {"test.echo": EchoPlugin, "test.tools": ToolsPlugin}
            ),
        )
        await runtime.start()
        self.assertEqual(
            [plugin.instance_id for plugin in runtime.plugins], ["tools", "echo"]
        )
        tools = runtime.require(TOOLS)
        result = await tools.execute(
            ToolCall(call_id="1", name="echo", arguments={"text": "hello"}),
            echo_context(),
        )
        self.assertEqual(result.data, {"text": "收到：hello"})
        await runtime.aclose()
        self.assertTrue(tools.closed)

    async def test_host_provided_tools_service_is_borrowed_not_closed(self):
        hosted = FakeTools()
        runtime = PluginRuntime(
            {
                "version": 1,
                "plugins": [
                    {"id": "echo", "name": "test.echo", "config": {"prefix": ">"}},
                ],
            },
            catalog=MappingCatalog({"test.echo": EchoPlugin}),
            host_services={TOOLS: hosted},
        )
        await runtime.start()
        result = await hosted.execute(
            ToolCall(call_id="1", name="echo", arguments={"text": "hi"}),
            echo_context(),
        )
        self.assertEqual(result.data, {"text": ">hi"})
        await runtime.aclose()
        self.assertFalse(hosted.closed)
        self.assertEqual(hosted.tools, {})
        self.assertEqual(hosted.executors, {})

    async def test_yaml_file_drives_the_same_lifecycle(self):
        document = """
version: 1
plugins:
  - id: echo
    name: test.echo
    config:
      prefix: "echo: "
  - id: tools
    name: test.tools
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.yaml"
            path.write_text(document, encoding="utf-8")
            runtime = PluginRuntime.from_yaml(
                path,
                catalog=MappingCatalog(
                    {"test.echo": EchoPlugin, "test.tools": ToolsPlugin}
                ),
            )
            await runtime.start()
            tools = runtime.require(TOOLS)
            result = await tools.execute(
                ToolCall(call_id="1", name="echo", arguments={"text": "hello"}),
                echo_context(),
            )
            self.assertEqual(result.data, {"text": "echo: hello"})
            self.assertEqual(
                [(plugin.instance_id, plugin.version) for plugin in runtime.plugins],
                [("tools", "0.1.0"), ("echo", "0.1.0")],
            )
            await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
