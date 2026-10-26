"""Run the example against a plugin-owned tools.v1 registry.

`tools-default` owns registration and execution; `example.echo` only requires
`tools.v1` and registers its tool. The backend follows the same shape: it
consumes the plugin service instead of providing one.
"""
import asyncio
from pathlib import Path

from agent_platform_plugin_runtime import PluginRuntime
from agent_platform_plugin_sdk import (
    ExecutionScope,
    TOOLS,
    ToolCall,
    ToolContext,
)


async def main() -> None:
    runtime = PluginRuntime.from_yaml(Path(__file__).with_name("plugins.yaml"))
    try:
        await runtime.start()
        print("started:", [(plugin.instance_id, plugin.name, plugin.version)
                           for plugin in runtime.plugins])
        tools = runtime.require(TOOLS)
        result = await tools.execute(
            ToolCall(call_id="demo-1", name="echo", arguments={"text": "hello"}),
            ToolContext(
                scope=ExecutionScope(tenant_id=1, agent_key="example"),
                visible_tool_names=frozenset({"echo"}),
            ),
        )
        print("result:", result.data)
    finally:
        await runtime.aclose()


if __name__ == "__main__":
    asyncio.run(main())
