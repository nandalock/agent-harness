"""Validate configured plugin instances without running their setup."""
import inspect
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from agent_platform_plugin_sdk import (
    Plugin,
    PluginCompatibilityError,
    PluginConfiguration,
    PluginEntry,
    PluginSpec,
    ensure_sdk_compatible,
)

from .catalog import PluginCatalog
from .errors import ConfigurationError, DiscoveryError


@dataclass(frozen=True)
class LoadedPlugin:
    """One enabled configuration entry and the implementation it resolved to."""

    entry: PluginEntry
    spec: PluginSpec
    plugin: Plugin[Any]
    config: BaseModel


def load_plugins(
    config: PluginConfiguration, catalog: PluginCatalog
) -> tuple[LoadedPlugin, ...]:
    """Resolve every enabled entry and validate it before any setup runs.

    Disabled entries are intentionally not discovered: their implementation may
    be absent, and they may not satisfy another plugin's declared dependency.
    """
    loaded: list[LoadedPlugin] = []
    for entry in config.plugins:
        if entry.disabled:
            continue
        plugin = catalog.load(entry.name)
        if isinstance(plugin, type):
            raise DiscoveryError(
                f"plugin entry {entry.name!r} resolved to a class; "
                "the catalog must return an instance"
            )
        spec = _validate_spec(plugin, entry)
        config_model = _config_model(plugin, entry)
        setup = getattr(plugin, "setup", None)
        if not callable(setup) or not inspect.iscoroutinefunction(setup):
            raise DiscoveryError(
                f"plugin {entry.id!r} ({entry.name}) must define an async setup()"
            )
        try:
            plugin_config = config_model.model_validate(entry.config)
        except ValidationError as exc:
            raise ConfigurationError(
                f"plugin {entry.id!r} ({entry.name}) rejected its config: {exc}"
            ) from exc
        loaded.append(
            LoadedPlugin(
                entry=entry,
                spec=spec,
                plugin=cast(Plugin[Any], plugin),
                config=plugin_config,
            )
        )
    return tuple(loaded)


def _validate_spec(plugin: object, entry: PluginEntry) -> PluginSpec:
    spec = getattr(plugin, "spec", None)
    if not isinstance(spec, PluginSpec):
        raise DiscoveryError(
            f"plugin {entry.id!r} ({entry.name}) must expose a PluginSpec as spec"
        )
    if spec.name != entry.name:
        raise DiscoveryError(
            f"plugin instance {entry.id!r} resolved {entry.name!r} but its spec "
            f"names {spec.name!r}"
        )
    try:
        ensure_sdk_compatible(spec)
    except PluginCompatibilityError as exc:
        exc.add_note(f"plugin instance {entry.id!r} ({entry.name})")
        raise
    return spec


def _config_model(plugin: object, entry: PluginEntry) -> type[BaseModel]:
    model = getattr(plugin, "config_model", None)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise DiscoveryError(
            f"plugin {entry.id!r} ({entry.name}) must expose a Pydantic "
            "config_model"
        )
    return model
