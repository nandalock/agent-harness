"""Resolve plugin-owned automatic bindings without persisting them as manual grants."""
from agent_platform_plugin_sdk import AgentRunContext, ExecutionScope


async def prepare_bindings(tenant_id, agent_key, config, manual_tools, tools):
    from backend.agents.runtime.extensions import get_agent_extensions
    available = await tools.list_for_agent(ExecutionScope(tenant_id=tenant_id, agent_key=agent_key))
    bound = set(manual_tools)
    schemas = [{"type": "function", "function": {
        "name": tool.name, "description": tool.description, "parameters": tool.input_schema,
    }} for tool in available if tool.name in bound]
    return await get_agent_extensions().prepare(AgentRunContext(
        tenant_id=tenant_id, agent_key=agent_key, config=config, tool_schemas=schemas,
    ))
