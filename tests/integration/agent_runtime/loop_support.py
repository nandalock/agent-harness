"""Explicit plugin contexts for driver unit tests that do not boot the host."""
from agent_platform_agent_loop import AgentLoopPlugin, LoopContext
from agent_platform_plugin_runtime.context import RuntimePluginContext
from agent_platform_plugin_runtime.registry import ServiceRegistry
from agent_platform_plugin_sdk import APPROVAL, TOOLS
from agent_platform_tools_default import TOOL_CATALOG, ToolsDefaultService


class UnavailableApproval:
    available = False

    async def request(self, req):
        return "unavailable"


def plugin_context(tools=None):
    tools = tools if tools is not None else ToolsDefaultService()
    return RuntimePluginContext("test-loop", AgentLoopPlugin.spec, ServiceRegistry({
        TOOLS: tools, TOOL_CATALOG: tools, APPROVAL: UnavailableApproval(),
    }))


def loop_context(llm, *, tools=None):
    return LoopContext(plugin_ctx=plugin_context(tools), llm=llm)
