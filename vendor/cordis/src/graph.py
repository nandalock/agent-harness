"""Resolve and compare compositions without running plugin setup."""

from collections.abc import Iterable
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from heapq import heappop, heappush
from typing import Any

from .errors import DependencyCycleError, MissingServiceError, ServiceConflictError
from .fiber import Plugin
from .services import ServiceKey

type Entry = tuple[str, Plugin[Any], Any]


@dataclass(frozen=True)
class Composition:
    entries: tuple[Entry, ...]
    dependencies: dict[str, frozenset[str]]

    def affected(self, previous: "Composition", changed: set[str]) -> set[str]:
        """Include added/removed instances and consumers of changed providers."""
        affected = changed | (self.dependencies.keys() ^ previous.dependencies.keys())
        for instance, dependencies in self.dependencies.items():
            if dependencies != previous.dependencies.get(instance):
                affected.add(instance)
        while True:
            expanded = affected | {
                instance
                for plan in (previous, self)
                for instance, dependencies in plan.dependencies.items()
                if dependencies & affected
            }
            if expanded == affected:
                return affected
            affected = expanded


def plan(entries: Iterable[Entry], services: Iterable[ServiceKey[Any]] = (), *,
         allow_pending: bool = False) -> Composition:
    available = set(services)
    providers: dict[ServiceKey[Any], str] = {}
    by_id: dict[str, Entry] = {}
    for instance, plugin, config in entries:
        if not instance.strip() or instance in by_id:
            raise ValueError(f"invalid or duplicate plugin id {instance!r}")
        if len(set(plugin.dependencies)) != len(plugin.dependencies):
            raise ValueError(f"plugin {instance!r} declared a dependency more than once")
        for key in plugin.provides:
            if key in providers or key in available:
                raise ServiceConflictError(f"{key} is already reserved by {providers.get(key, '<host>')!r}")
            providers[key] = instance
        by_id[instance] = instance, plugin, config

    missing = [
        f"{instance!r} requires {key}"
        for instance, plugin, _ in by_id.values()
        for key in plugin.requires
        if key not in providers and key not in available
    ]
    if missing and not allow_pending:
        raise MissingServiceError("missing required services: " + ", ".join(missing))
    graph = {
        instance: frozenset(providers[key] for key in plugin.dependencies if key in providers)
        for instance, plugin, _ in by_id.values()
    }
    sorter = TopologicalSorter(graph)
    try:
        sorter.prepare()
    except CycleError as exc:
        raise DependencyCycleError("dependency cycle: " + " -> ".join(exc.args[1])) from exc
    rank = {instance: index for index, instance in enumerate(by_id)}
    ready: list[tuple[int, str]] = []
    order: list[Entry] = []
    while sorter.is_active():
        for instance in sorter.get_ready():
            heappush(ready, (rank[instance], instance))
        _, instance = heappop(ready)
        order.append(by_id[instance])
        sorter.done(instance)
    return Composition(tuple(order), graph)
