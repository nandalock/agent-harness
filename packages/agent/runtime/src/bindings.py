"""Resolve plugin-owned automatic bindings without persisting manual grants."""
from __future__ import annotations

from typing import Any

from agent_platform_plugin_sdk import (
    AgentExtensionsService,
    AgentRunContext,
    ExecutionScope,
)


async def prepare_bindings(
    tenant_id: int,
    agent_key: str,
    config: dict[str, Any],
    manual_tools: list[str],
    tools: Any,
    extensions: AgentExtensionsService,
):
    """Visible descriptors for manual bindings, then feature contributions."""
    available = await tools.list_for_agent(
        ExecutionScope(tenant_id=tenant_id, agent_key=agent_key)
    )
    bound = set(manual_tools)
    schemas = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in available
        if tool.name in bound
    ]
    return await extensions.prepare(
        AgentRunContext(
            tenant_id=tenant_id,
            agent_key=agent_key,
            config=config,
            tool_schemas=schemas,
        )
    )
