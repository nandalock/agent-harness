"""YAML loader for minidsh Cordis plugins."""
from minidsh_cordis import (
    DependencyCycleError, DependencyError, MissingServiceError, ServiceConflictError, UndeclaredServiceError,
)

from minidsh_cordis_plugin_include import ConfigurationError, PluginRuntimeError

from .catalog import PLUGIN_CATALOG, ActivePluginCatalog, LoadedPluginInfo, MappingCatalog, PluginCatalog, load_module_plugin
from .errors import DiscoveryError, LifecycleError
from .loader import LoaderState, Loader

__version__ = "0.1.0"

__all__ = [
    "ConfigurationError", "DependencyCycleError", "DependencyError", "DiscoveryError", "LifecycleError",
    "PLUGIN_CATALOG", "ActivePluginCatalog", "LoadedPluginInfo", "LoaderState", "MappingCatalog",
    "MissingServiceError", "PluginCatalog", "Loader", "PluginRuntimeError",
    "ServiceConflictError", "UndeclaredServiceError", "load_module_plugin",
]
