"""YAML-driven plugin host for the Agent Platform plugin SDK.

The runtime reads a declarative document, resolves installed entry points,
validates every enabled instance, rejects an unsatisfiable service graph, and
owns setup/teardown. It does not implement `tools.v1`: a host service or a
separate plugin package provides that capability.
"""
from .catalog import EntryPointCatalog, MappingCatalog, PluginCatalog
from .config import load_yaml_config, parse_config, parse_yaml
from .errors import (
    ConfigurationError,
    DependencyCycleError,
    DependencyError,
    DiscoveryError,
    LifecycleError,
    MissingServiceError,
    PluginRuntimeError,
    ServiceConflictError,
    UndeclaredServiceError,
)
from .runtime import LoadedPluginInfo, PluginRuntime, RuntimeState

__version__ = "0.1.0"

__all__ = [
    "ConfigurationError",
    "DependencyCycleError",
    "DependencyError",
    "DiscoveryError",
    "EntryPointCatalog",
    "LifecycleError",
    "LoadedPluginInfo",
    "MappingCatalog",
    "MissingServiceError",
    "PluginCatalog",
    "PluginRuntime",
    "PluginRuntimeError",
    "RuntimeState",
    "ServiceConflictError",
    "UndeclaredServiceError",
    "load_yaml_config",
    "parse_config",
    "parse_yaml",
]
