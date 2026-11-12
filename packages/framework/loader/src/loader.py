"""Compose native Cordis plugins from a configuration document."""
import asyncio
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from minidsh_cordis import Context, PinnedServiceError, Plugin, ServiceClosedError, ServiceKey
from minidsh_cordis_plugin_group import is_group_disabled
from minidsh_cordis_plugin_include import ConfigurationError, PluginConfiguration, apply_entry_patches, Include, parse_config
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ValidationError

from .catalog import PLUGIN_CATALOG, PluginCatalog, _PluginInventory, load_module_plugin
from .catalog import LoadedPluginInfo as LoadedPluginInfo
from .errors import DiscoveryError, LifecycleError


class LoaderState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"


class Loader(Plugin[None]):
    """Compose configured plugins and provide their inventory as a Cordis plugin."""

    name = "minidsh.loader"
    version = "0.1.0"
    _instance_id = "minidsh.loader"

    def __init__(
        self, config: PluginConfiguration | Mapping[str, object], *,
        context: Context | None = None,
        catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> None:
        super().__init__()
        if context is not None and host_services is not None:
            raise TypeError("configure host_services on the supplied Context")
        self._context = context
        self._config = apply_entry_patches(config if isinstance(config, PluginConfiguration) else parse_config(config))
        self._catalog = catalog
        self._host_services = dict(host_services or {})
        has_catalog = (
            context.get(PLUGIN_CATALOG) is not None if context is not None
            else PLUGIN_CATALOG in self._host_services
        )
        self.provides = () if has_catalog else (PLUGIN_CATALOG,)
        self._state = LoaderState.NEW
        self._lock = asyncio.Lock()
        self._root: Context | None = None
        self._entries: tuple[tuple[str, Plugin[Any], Any], ...] = ()

    @classmethod
    def from_yaml(
        cls, path: str | Path, *, context: Context | None = None, catalog: PluginCatalog | None = None,
        host_services: Mapping[ServiceKey[Any], Any] | None = None,
    ) -> "Loader":
        return cls(Include(path).read(), context=context, catalog=catalog, host_services=host_services)

    @property
    def state(self) -> LoaderState:
        return self._state

    @property
    def config(self) -> PluginConfiguration:
        return self._config

    @property
    def plugins(self) -> tuple[LoadedPluginInfo, ...]:
        if self._root is None:
            return ()
        entries = {instance: plugin for instance, plugin, _ in self._entries}
        return tuple(
            LoadedPluginInfo(fiber.id, plugin.name, str(Version(plugin.version)), plugin.web_package)
            for fiber in self._root.active_fibers if (plugin := entries.get(fiber.id)) is not None
        )

    def validate(self) -> None:
        """Resolve exports and validate declarations without starting plugins."""
        root = self._context or Context(host_services=self._host_services)
        root.validate(((self._instance_id, self, None), *self._prepare(self._config)))

    def setup(self, ctx: Context, config: None) -> None:
        if PLUGIN_CATALOG in self.provides:
            ctx.provide(PLUGIN_CATALOG, _PluginInventory(lambda: self.plugins))

    def _prepare(self, config: PluginConfiguration) -> tuple[tuple[str, Plugin[Any], Any], ...]:
        entries: list[tuple[str, Plugin[Any], Any]] = []
        for entry in config.plugins:
            if entry.disabled or is_group_disabled(entry.group, config.groups):
                continue
            if entry.id == self._instance_id:
                raise ConfigurationError(f"plugin id {entry.id!r} is reserved for the loader")
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
        return tuple(entries)

    async def start(self) -> None:
        if self._state is LoaderState.CLOSED:
            raise ServiceClosedError("plugin loader is closed")
        if self._state is not LoaderState.NEW:
            raise LifecycleError(f"cannot start plugin loader in state {self._state.value!r}")
        self._state = LoaderState.STARTING
        try:
            entries = self._prepare(self._config)
            root = self._context or Context(host_services=self._host_services, lifecycle_in_caller=True)
            await root.start(((self._instance_id, self, None), *entries))
        except BaseException:
            self._state = LoaderState.NEW
            raise
        self._root, self._entries = root, entries
        self._state = LoaderState.RUNNING

    async def reconfigure(
        self, config: PluginConfiguration, *, pinned: frozenset[ServiceKey[Any]] = frozenset(),
    ) -> tuple[str, ...]:
        async with self._lock:
            root, old = self._root, self._entries
            if self._state is not LoaderState.RUNNING or root is None:
                raise LifecycleError("plugin loader must be running before reconfiguration")
            config = apply_entry_patches(config)
            running = {fiber.id for fiber in root.active_fibers}
            missing = {instance for instance, _, _ in old} - running
            if config == self._config and not missing:
                return ()
            new = self._prepare(config)
            before = {instance: (plugin, value) for instance, plugin, value in old}
            after = {instance for instance, _, _ in new}
            old_targets = {row.id: row.use for row in self._config.plugins}
            new_targets = {row.id: row.use for row in config.plugins}
            changed = missing | (before.keys() ^ after)
            for instance, plugin, value in new:
                if instance not in before:
                    continue
                previous, old_value = before[instance]
                if (old_targets[instance] != new_targets[instance] or type(plugin) is not type(previous)
                    or plugin.name != previous.name or plugin.provides != previous.provides
                    or plugin.requires != previous.requires or plugin.optional != previous.optional or value != old_value):
                    changed.add(instance)
            registered = {fiber.id for fiber in root.fibers}
            try:
                affected = ()
                if changed:
                    affected = await root.reconfigure(
                        changed & registered, (row for row in new if row[0] in changed), pinned=pinned,
                    )
            except PinnedServiceError as error:
                raise LifecycleError(str(error)) from error
            self._config, self._entries = config, new
            return tuple(sorted(changed.union(affected)))

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
                self._root = None
                self._entries = ()
                self._state = LoaderState.CLOSED

    @property
    def ctx(self) -> Context:
        if self._state is not LoaderState.RUNNING or self._root is None:
            raise LifecycleError(f"plugin loader is not running (state {self._state.value!r})")
        return self._root

    def require[T](self, key: ServiceKey[T]) -> T:
        return self.ctx.require(key)
