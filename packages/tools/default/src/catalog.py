"""Host-only snapshot of the tools that tools-default directly owns.

The backend needs this to mirror descriptors into its UI/binding index. It is
deliberately separate from `ToolsService.list_for_agent`, which is scope-aware
and may include lazily discovered provider tools.
"""
from typing import Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef, ToolDescriptor


class ToolCatalog(Protocol):
    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        """All directly registered tools, independent of any execution scope."""
        ...

    def has_tool(self, name: str) -> bool: ...


TOOL_CATALOG: ServiceKey[ToolCatalog] = ServiceKey(
    ServiceRef(name="tools.catalog", api_version=1)
)
