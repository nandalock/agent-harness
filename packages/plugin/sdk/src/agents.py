"""Generic plugin contributions to an agent run; no capability-specific imports."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from .lifecycle import Registration, ServiceKey
from .models import ServiceRef

PreStep = Callable[[Any, list[Any]], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class AgentRunContext:
    tenant_id: int
    agent_key: str
    config: dict[str, Any]
    tool_schemas: list[dict[str, Any]]


@dataclass(frozen=True)
class AgentRunContribution:
    tool_schemas: list[dict[str, Any]]
    pre_step: PreStep | None = None
    capabilities: frozenset[str] = frozenset()


AgentExtension = Callable[[AgentRunContext], Awaitable[AgentRunContribution]]


class AgentExtensionsService(Protocol):
    def register(self, name: str, extension: AgentExtension) -> Registration: ...


AGENT_EXTENSIONS: ServiceKey[AgentExtensionsService] = ServiceKey(
    ServiceRef(name="agent.extensions", api_version=1)
)
