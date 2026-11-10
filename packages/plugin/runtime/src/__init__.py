"""YAML loader for minidsh Cordis plugins."""
from minidsh_cordis import (
    DependencyCycleError, DependencyError, MissingServiceError, ServiceConflictError, UndeclaredServiceError,
)

from .catalog import MappingCatalog, PluginCatalog, load_module_plugin
from .config import load_yaml_config, parse_config, parse_yaml
from .errors import ConfigurationError, DiscoveryError, LifecycleError, PluginRuntimeError
from .layers import apply_patches, load_layers, merge_layers
from .loader import LoadedPluginInfo, LoaderState, PluginLoader
from .models import PluginConfiguration, PluginEntry, PluginGroup, PluginPatch

__version__ = "0.1.0"

__all__ = [
    "ConfigurationError", "DependencyCycleError", "DependencyError", "DiscoveryError", "LifecycleError",
    "LoadedPluginInfo", "LoaderState", "MappingCatalog", "MissingServiceError", "PluginCatalog", "PluginLoader",
    "PluginConfiguration", "PluginEntry", "PluginGroup", "PluginPatch", "PluginRuntimeError",
    "ServiceConflictError", "UndeclaredServiceError", "apply_patches", "load_layers",
    "load_module_plugin", "load_yaml_config", "merge_layers", "parse_config", "parse_yaml",
]
