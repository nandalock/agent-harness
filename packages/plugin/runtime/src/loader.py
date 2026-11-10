"""Compose native Cordis plugins from a minidsh configuration."""
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from minidsh_cordis import Composition, Context, FiberState, Plugin, ServiceClosedError, ServiceKey, plan
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ValidationError

from agent_platform_plugin_sdk import PLUGIN_CATALOG
from .models import PluginConfiguration

from .catalog import PluginCatalog, load_module_plugin
from .config import parse_config
from .errors import ConfigurationError, DiscoveryError, LifecycleError
from .layers import apply_patches, load_layers


class LoaderState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"


@dataclass(frozen=True)
class LoadedPluginInfo:
    instance_id: str
    name: str
    version: str
    web_package: str | None


class _PluginInventory:
    def __init__(self, loader: "PluginLoader") -> None:
        self._loader = loader

    def list(self) -> list[dict[str, Any]]:
        return [
            {"id": plugin.instance_id, "name": plugin.name, "version": plugin.version}
            for plugin in self._loader.plugins
        ]

    def web_packages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            plugin.web_package for plugin in self._loader.plugins if plugin.web_package is not None
        ))


class PluginLoader:
    """Validate YAML and delegate plugin execution to a single Cordis root."""

    def __init__(
        self, config: PluginConfiguration | Mapping[str, object], *,
        catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> None:
        self._config = apply_patches(config if isinstance(config, PluginConfiguration) else parse_config(config))
        self._catalog = catalog
        self._host_services = dict(host_services or {})
        self._host_services.setdefault(PLUGIN_CATALOG, _PluginInventory(self))
        self._state = LoaderState.NEW
        self._lock = asyncio.Lock()
        self._root: Context | None = None
        self._plan: Composition | None = None

    @classmethod
    def from_yaml(
        cls, path: str | Path, *, catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> "PluginLoader":
        return cls(load_layers(path), catalog=catalog, host_services=host_services)

    @property
    def state(self) -> LoaderState:
        return self._state

    @property
    def config(self) -> PluginConfiguration:
        return self._config

    @property
    def plugins(self) -> tuple[LoadedPluginInfo, ...]:
        if self._root is None or self._plan is None:
            return ()
        active = {fiber.id for fiber in self._root.fibers if fiber.state is FiberState.ACTIVE}
        return tuple(
            LoadedPluginInfo(instance, plugin.name, str(Version(plugin.version)), plugin.web_package)
            for instance, plugin, _ in self._plan.entries if instance in active
        )

    def validate(self) -> None:
        """Resolve exports, validate config and check the graph without starting plugins."""
        self._prepare(self._config)

    def _prepare(self, config: PluginConfiguration) -> Composition:
        entries: list[tuple[str, Plugin[Any], Any]] = []
        for entry in config.plugins:
            group = config.groups.get(entry.group) if entry.group is not None else None
            if entry.disabled or (group is not None and group.disabled):
                continue
            plugin: object
            if entry.use is not None:
                plugin = load_module_plugin(entry.use)
            elif self._catalog is not None:
                plugin = self._catalog.load(entry.name)
            else:
                raise DiscoveryError(f"plugin {entry.id!r} requires use: module:export")
            if not isinstance(plugin, Plugin):
                raise DiscoveryError(f"plugin {entry.id!r} must be a Cordis Plugin")
            if plugin.name != entry.name:
                raise DiscoveryError(f"plugin {entry.id!r} names {entry.name!r}, but the export declares {plugin.name!r}")
            try:
                Version(plugin.version)
            except InvalidVersion as exc:
                raise DiscoveryError(f"plugin {entry.id!r} has invalid version {plugin.version!r}") from exc
            model = plugin.config_model
            if not isinstance(model, type) or not issubclass(model, BaseModel):
                raise DiscoveryError(f"plugin {entry.id!r} must expose a Pydantic config_model")
            try:
                validated = model.model_validate(entry.config)
            except ValidationError as exc:
                raise ConfigurationError(f"plugin {entry.id!r} ({entry.name}) rejected its config: {exc}") from exc
            entries.append((entry.id, plugin, validated))
        return plan(entries, self._host_services)

    async def start(self) -> None:
        if self._state is LoaderState.CLOSED:
            raise ServiceClosedError("plugin loader is closed")
        if self._state is not LoaderState.NEW:
            raise LifecycleError(f"cannot start plugin loader in state {self._state.value!r}")
        self._state = LoaderState.STARTING
        try:
            composition = self._prepare(self._config)
            root = Context(host_services=self._host_services, lifecycle_in_caller=True)
            await root.start(composition.entries)
        except BaseException:
            self._state = LoaderState.NEW
            raise
        self._root, self._plan = root, composition
        self._state = LoaderState.RUNNING

    async def reconfigure(
        self, config: PluginConfiguration, *, pinned: frozenset[ServiceKey[Any]] = frozenset(),
    ) -> tuple[str, ...]:
        async with self._lock:
            root, old = self._root, self._plan
            if self._state is not LoaderState.RUNNING or root is None or old is None:
                raise LifecycleError("plugin loader must be running before reconfiguration")
            config = apply_patches(config)
            running = {fiber.id for fiber in root.fibers if fiber.state is FiberState.ACTIVE}
            missing = {instance for instance, _, _ in old.entries} - running
            if config == self._config and not missing:
                return ()
            new = self._prepare(config)
            before = {instance: (plugin, value) for instance, plugin, value in old.entries}
            old_targets = {row.id: row.use for row in self._config.plugins}
            new_targets = {row.id: row.use for row in config.plugins}
            changed = missing | {
                instance for instance, plugin, value in new.entries if instance in before
                and (old_targets[instance] != new_targets[instance]
                     or type(plugin) is not type(before[instance][0]) or value != before[instance][1])
            }
            affected = new.affected(old, changed)
            if any(pinned.intersection(plugin.provides) for graph in (old, new)
                   for instance, plugin, _ in graph.entries if instance in affected):
                raise LifecycleError("plugin configuration changes a service bound to the host; restart required")
            if affected:
                await root.replace(affected & running, (row for row in new.entries if row[0] in affected))
            self._config, self._plan = config, new
            return tuple(sorted(affected))

    async def aclose(self) -> None:
        async with self._lock:
            if self._state is LoaderState.CLOSED:
                return
            if self._state is LoaderState.STARTING:
                raise LifecycleError("cannot close a plugin loader while it is starting")
            self._state = LoaderState.STOPPING
            try:
                if self._root is not None:
                    await self._root.aclose()
            finally:
                self._root = self._plan = None
                self._state = LoaderState.CLOSED

    @property
    def ctx(self) -> Context:
        if self._state is not LoaderState.RUNNING or self._root is None:
            raise LifecycleError(f"plugin loader is not running (state {self._state.value!r})")
        return self._root

    def require[T](self, key: ServiceKey[T]) -> T:
        return self.ctx.require(key)
