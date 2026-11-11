"""Failures when loading and starting plugins."""

from minidsh_cordis_plugin_include import PluginRuntimeError


class DiscoveryError(PluginRuntimeError):
    """An explicit plugin export could not be loaded."""

    code = "plugin_runtime.discovery"


class LifecycleError(PluginRuntimeError):
    """The loader cannot make the requested transition."""

    code = "plugin_runtime.lifecycle"
