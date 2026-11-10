"""Generic plugin contributions to an agent run; no capability-specific imports."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from minidsh_cordis import Closeable as Registration, ServiceKey

PreStep = Callable[[Any, list[Any]], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class RequestPreparation:
    """Changes to apply before deriving the final model request."""

    system_context: str = ""
    events: tuple[tuple[str, dict[str, Any]], ...] = ()


PrepareRequest = Callable[[Any, Any, Any], Awaitable[RequestPreparation]]


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
    # Tool name -> owning feature labels. Hosts expose these separately from
    # manual grants; only tool_schemas determine actual model-visible tools.
    automatic_tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    prepare_request: PrepareRequest | None = None


AgentExtension = Callable[[AgentRunContext], Awaitable[AgentRunContribution]]


class AgentExtensionsService(Protocol):
    def register(self, name: str, extension: AgentExtension) -> Registration: ...
    async def prepare(self, context: AgentRunContext) -> AgentRunContribution: ...


AGENT_EXTENSIONS: ServiceKey[AgentExtensionsService] = ServiceKey("agent.extensions")
