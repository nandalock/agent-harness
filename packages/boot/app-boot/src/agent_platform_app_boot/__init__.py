"""Shared boot glue: composition discovery and the process plugin runtime."""
from .config import compose_plugins, load_config, resolve_config_path
from .host import PluginHost, close_plugin_host, create_runtime, get_plugin_host, init_plugin_host

__all__ = [
    "PluginHost",
    "close_plugin_host",
    "compose_plugins",
    "create_runtime",
    "get_plugin_host",
    "init_plugin_host",
    "load_config",
    "resolve_config_path",
]
