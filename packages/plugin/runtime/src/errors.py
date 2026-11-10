"""Host failures for reading and applying a plugin configuration."""


class PluginRuntimeError(RuntimeError):
    """Base class for errors at the loader boundary."""

    code = "plugin_runtime.error"


class ConfigurationError(PluginRuntimeError):
    code = "plugin_runtime.config"

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


class DiscoveryError(PluginRuntimeError):
    """An explicit plugin export could not be loaded."""

    code = "plugin_runtime.discovery"


class LifecycleError(PluginRuntimeError):
    """The loader cannot make the requested transition."""

    code = "plugin_runtime.lifecycle"
