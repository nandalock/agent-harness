"""Locate plugin classes: installed entry points or a static mapping for embedding."""
from collections.abc import Callable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol

from agent_platform_plugin_sdk import PLUGIN_ENTRY_POINT_GROUP

from .errors import DiscoveryError


class PluginCatalog(Protocol):
    """Resolve an implementation name to a no-argument-constructed plugin instance."""

    def load(self, name: str) -> object: ...


class EntryPointCatalog:
    """Load plugin classes from the `agent_platform.plugins` entry point group.

    Entry point names must be unique across installed distributions. A duplicate
    name is a host configuration error, never a silent last-one-wins choice.
    """

    def __init__(self, group: str = PLUGIN_ENTRY_POINT_GROUP) -> None:
        self._group = group
        self._entries: dict[str, EntryPoint] | None = None

    def _index(self) -> dict[str, EntryPoint]:
        if self._entries is None:
            found: dict[str, EntryPoint] = {}
            for entry in entry_points(group=self._group):
                if entry.name in found:
                    raise DiscoveryError(
                        f"duplicate entry point {entry.name!r} in group {self._group!r}"
                    )
                found[entry.name] = entry
            self._entries = found
        return self._entries

    def load(self, name: str) -> object:
        entry = self._index().get(name)
        if entry is None:
            raise DiscoveryError(
                f"no entry point named {name!r} in group {self._group!r}"
            )
        try:
            factory = entry.load()
        except Exception as exc:
            raise DiscoveryError(f"cannot import plugin {name!r}: {exc}") from exc
        if not callable(factory):
            raise DiscoveryError(
                f"entry point {name!r} did not resolve to a callable plugin class"
            )
        try:
            return factory()
        except Exception as exc:
            raise DiscoveryError(f"cannot instantiate plugin {name!r}: {exc}") from exc


class MappingCatalog:
    """A deterministic catalog for tests and hosts that embed plugin classes directly.

    Each value is a zero-argument factory returning a fresh plugin instance, so the
    same implementation can serve several configuration entries without sharing state.
    """

    def __init__(self, plugins: Mapping[str, Callable[[], object]]) -> None:
        self._plugins = dict(plugins)

    def load(self, name: str) -> object:
        factory = self._plugins.get(name)
        if factory is None:
            raise DiscoveryError(f"no plugin registered under {name!r}")
        try:
            return factory()
        except Exception as exc:
            raise DiscoveryError(f"cannot instantiate plugin {name!r}: {exc}") from exc
