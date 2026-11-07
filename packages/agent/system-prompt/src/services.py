"""Service contract for prompt assembly."""
from dataclasses import dataclass
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef


@dataclass(frozen=True)
class PreparedPrompt:
    text: str
    tools: list[dict]


class RuntimePrompts(Protocol):
    async def assemble(self, **options: Any) -> PreparedPrompt: ...
    async def preview(self, **options: Any) -> Any: ...


RUNTIME_PROMPTS: ServiceKey[RuntimePrompts] = ServiceKey(
    ServiceRef(name="agent.prompts", api_version=1)
)
