"""Service key for the single-track tools host."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef


class UnifiedToolsService(Protocol):
    async def descriptors_for_agent(self, tenant_id: int, agent_key: str) -> list[Any]: ...
    def is_sandbox_tool(self, name: str) -> bool: ...
    async def aclose(self) -> None: ...


UNIFIED_TOOLS: ServiceKey[UnifiedToolsService] = ServiceKey(
    ServiceRef(name="unified-tools", api_version=1)
)
