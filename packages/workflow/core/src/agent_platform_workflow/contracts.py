"""Public contracts for the workflow service and its node extension point."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from agent_platform_plugin_sdk import (
    AgentConfigService,
    Registration,
    ServiceKey,
)

from .state import WorkflowState


class CacheHandle(Protocol):
    """One node's cache view. Implementations may be no-ops."""

    @property
    def policy(self) -> Any: ...

    async def lookup(self, question: str) -> tuple[bool, str | None, str, float | None]: ...

    async def store(self, question: str, answer: str, **kwargs: Any) -> Any: ...


#: node_id, raw cache config, resolved agent cache policy -> handle or None.
CacheFactory = Callable[[str, dict[str, Any], dict[str, Any] | None], CacheHandle | None]


@dataclass(frozen=True)
class NodeContext:
    """Everything a node factory may use while building one node handler."""

    node_id: str
    config: dict[str, Any]
    agent_entry: Any
    agents: AgentConfigService
    cache_factory: CacheFactory | None = None


NodeHandler = Callable[[WorkflowState], Awaitable[dict[str, Any]]]
FindNode = Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class RoutePlan:
    """Conditional edges for one node type."""

    router: Callable[[WorkflowState], str]
    path_map: dict[str, str]


RoutePlanner = Callable[[NodeContext, tuple[str, ...], FindNode], RoutePlan | None]


@dataclass(frozen=True)
class NodeDefinition:
    """A built node: one handler and an optional edge router."""

    handler: NodeHandler
    route: RoutePlanner | None = None


NodeFactory = Callable[[NodeContext], Awaitable[NodeDefinition]]


class WorkflowNodeRegistry(Protocol):
    """Plugins register additional node kinds here."""

    def register(self, kind: str, factory: NodeFactory) -> Registration: ...

    async def build(self, kind: str, context: NodeContext) -> NodeDefinition: ...

    def kinds(self) -> tuple[str, ...]: ...


class WorkflowService(Protocol):
    """CRUD plus execution for tenant-owned workflow rows."""

    async def list(self, tenant_id: int) -> list[dict[str, Any]]: ...

    async def create(
        self,
        tenant_id: int,
        name: str,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    async def get(self, workflow_id: int) -> dict[str, Any]: ...

    async def save(
        self,
        workflow_id: int,
        *,
        name: str | None = None,
        status: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> None: ...

    async def delete(self, workflow_id: int) -> None: ...

    def run(
        self, workflow_id: int, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]: ...


WORKFLOW: ServiceKey[WorkflowService] = ServiceKey("workflow")

WORKFLOW_NODES: ServiceKey[WorkflowNodeRegistry] = ServiceKey("workflow.nodes")
