"""Resolve explicit module exports or classes supplied by an embedding host."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from minidsh_cordis import Plugin, ServiceKey

from .errors import DiscoveryError


class ActivePluginCatalog(Protocol):
    """View of active plugin instances and their browser packages."""

    def list(self) -> list[dict[str, Any]]: ...

    def web_packages(self) -> tuple[str, ...]: ...


PLUGIN_CATALOG: ServiceKey[ActivePluginCatalog] = ServiceKey("plugin-catalog")


@dataclass(frozen=True)
class LoadedPluginInfo:
    instance_id: str
    name: str
    version: str
    web_package: str | None


class _PluginInventory:
    def __init__(self, active_plugins: Callable[[], tuple[LoadedPluginInfo, ...]]) -> None:
        self._active_plugins = active_plugins

    def list(self) -> list[dict[str, Any]]:
        return [
            {"id": plugin.instance_id, "name": plugin.name, "version": plugin.version}
            for plugin in self._active_plugins()
        ]

    def web_packages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            plugin.web_package for plugin in self._active_plugins() if plugin.web_package is not None
        ))


class PluginCatalog(Protocol):
    def load(self, name: str) -> object: ...


class MappingCatalog:
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


def load_module_plugin(target: str) -> Plugin[Any]:
    try:
        module, export = target.split(":", 1)
        exported = getattr(import_module(module), export)
        plugin = exported if isinstance(exported, Plugin) else exported()
        if not isinstance(plugin, Plugin):
            raise TypeError("expected a Cordis Plugin, plugin class or factory")
        return plugin
    except Exception as exc:
        raise DiscoveryError(f"cannot load plugin export {target!r}: {exc}") from exc
