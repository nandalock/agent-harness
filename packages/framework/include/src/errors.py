"""Failures when reading or applying a plugin configuration."""


class PluginRuntimeError(RuntimeError):
    code = "plugin_runtime.error"


class ConfigurationError(PluginRuntimeError):
    code = "plugin_runtime.config"

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)
