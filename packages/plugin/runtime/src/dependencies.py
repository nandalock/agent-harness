"""Plan setup order from declared service requirements and providers.

Only enabled plugins participate. A host service satisfies a requirement but
does not create an ordering edge, because the host is ready before any setup.
Optional requirements still create an edge when an enabled provider exists, so
`ctx.get()` observes the provider's service whenever the graph permits it.
"""
from dataclasses import dataclass
from heapq import heapify, heappop, heappush
from typing import Any

from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .errors import (
    DependencyCycleError,
    MissingServiceError,
    ServiceConflictError,
)
from .loader import LoadedPlugin


@dataclass(frozen=True)
class ResolutionPlan:
    """The setup order and the plugin that owns each provided service."""

    plugins: tuple[LoadedPlugin, ...]
    providers: dict[ServiceRef, str]


def resolve(
    plugins: tuple[LoadedPlugin, ...],
    host_services: dict[ServiceKey[Any], Any] | None = None,
) -> ResolutionPlan:
    index = {plugin.entry.id: position for position, plugin in enumerate(plugins)}
    host_refs = {key.ref for key in (host_services or {})}
    providers: dict[ServiceRef, str] = {}

    for plugin in plugins:
        for ref in plugin.spec.provides:
            if ref in host_refs:
                raise ServiceConflictError(
                    f"plugin {plugin.entry.id!r} provides {ref}, "
                    "which the host already provides"
                )
            owner = providers.get(ref)
            if owner is not None:
                raise ServiceConflictError(
                    f"plugins {owner!r} and {plugin.entry.id!r} both provide {ref}"
                )
            providers[ref] = plugin.entry.id

    adjacency: dict[str, set[str]] = {plugin.entry.id: set() for plugin in plugins}
    indegree = {plugin.entry.id: 0 for plugin in plugins}
    missing: list[str] = []

    for plugin in plugins:
        for requirement in plugin.spec.requires:
            ref = requirement.service
            if ref in host_refs:
                continue
            owner = providers.get(ref)
            if owner is None:
                if not requirement.optional:
                    missing.append(
                        f"{plugin.entry.id!r} ({plugin.spec.name}) requires {ref}"
                    )
                continue
            if owner == plugin.entry.id:
                raise DependencyCycleError(
                    f"plugin {plugin.entry.id!r} requires its own provided service {ref}"
                )
            if plugin.entry.id not in adjacency[owner]:
                adjacency[owner].add(plugin.entry.id)
                indegree[plugin.entry.id] += 1

    if missing:
        raise MissingServiceError(
            "missing required services: " + "; ".join(missing)
        )

    ready: list[tuple[int, str]] = [
        (index[plugin.entry.id], plugin.entry.id)
        for plugin in plugins
        if indegree[plugin.entry.id] == 0
    ]
    heapify(ready)
    by_id = {plugin.entry.id: plugin for plugin in plugins}
    order: list[LoadedPlugin] = []
    while ready:
        _, current = heappop(ready)
        order.append(by_id[current])
        for dependent in sorted(adjacency[current], key=index.__getitem__):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heappush(ready, (index[dependent], dependent))

    if len(order) != len(plugins):
        cycle = _find_cycle(
            adjacency,
            [plugin.entry.id for plugin in plugins if indegree[plugin.entry.id] > 0],
        )
        raise DependencyCycleError("dependency cycle: " + " -> ".join(cycle))

    return ResolutionPlan(plugins=tuple(order), providers=providers)


def _find_cycle(adjacency: dict[str, set[str]], candidates: list[str]) -> list[str]:
    visited: set[str] = set()
    active: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in active:
            return path[path.index(node):] + [node]
        if node in visited:
            return None
        visited.add(node)
        active.add(node)
        path.append(node)
        for neighbor in sorted(adjacency[node]):
            cycle = visit(neighbor)
            if cycle is not None:
                return cycle
        path.pop()
        active.remove(node)
        return None

    for candidate in candidates:
        cycle = visit(candidate)
        if cycle is not None:
            return cycle
    return candidates[:1] + candidates[:1]
