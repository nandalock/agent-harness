"""Owned registry of workflow node kinds."""
from __future__ import annotations

from agent_platform_plugin_sdk import (
    Registration,
    RegistrationConflictError,
    ServiceClosedError,
)

from .contracts import NodeContext, NodeDefinition, NodeFactory
from .errors import WorkflowValidationError


class _Registration:
    def __init__(self, registry: "WorkflowNodeRegistry", kind: str, factory: NodeFactory) -> None:
        self._registry = registry
        self._kind = kind
        self._factory = factory

    async def aclose(self) -> None:
        if self._registry._factories.get(self._kind) is self._factory:
            del self._registry._factories[self._kind]


class WorkflowNodeRegistry:
    """One registry per plugin runtime; built-ins and extensions share it."""

    def __init__(self) -> None:
        self._factories: dict[str, NodeFactory] = {}
        self._closed = False

    def register(self, kind: str, factory: NodeFactory) -> Registration:
        if self._closed:
            raise ServiceClosedError("workflow node registry is closed")
        name = (kind or "").strip()
        if not name:
            raise ValueError("workflow node kind is required")
        if name in self._factories:
            raise RegistrationConflictError(f"workflow node kind already registered: {name}")
        self._factories[name] = factory
        return _Registration(self, name, factory)

    async def build(self, kind: str, context: NodeContext) -> NodeDefinition:
        if self._closed:
            raise ServiceClosedError("workflow node registry is closed")
        factory = self._factories.get(kind)
        if factory is None:
            known = ", ".join(sorted(self._factories)) or "none"
            raise WorkflowValidationError(
                f"unknown workflow node kind: {kind} (registered: {known})"
            )
        return await factory(context)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    async def aclose(self) -> None:
        self._closed = True
        self._factories.clear()
