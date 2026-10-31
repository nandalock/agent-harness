"""Machine-readable failures raised by the runtime boundary.

The SDK defines failures that belong to the contract (`PluginCompatibilityError`,
`RegistrationConflictError`, `ServiceClosedError`, `ServiceUnavailableError`).
This module adds failures that only a host can diagnose: configuration,
discovery, dependency planning and lifecycle state.
"""


class PluginRuntimeError(RuntimeError):
    """Base class for host-side plugin runtime failures."""

    code = "plugin_runtime.error"


class ConfigurationError(PluginRuntimeError):
    """The YAML or JSON document cannot be read or validated."""

    code = "plugin_runtime.config"

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


class DiscoveryError(PluginRuntimeError):
    """An entry point is missing, cannot be imported, or is not a plugin."""

    code = "plugin_runtime.discovery"


class DependencyError(PluginRuntimeError):
    """The declared service graph cannot be satisfied."""

    code = "plugin_runtime.dependency"


class MissingServiceError(DependencyError):
    """A required service has no enabled plugin or host provider."""

    code = "plugin_runtime.missing_service"


class ServiceConflictError(DependencyError):
    """Two providers, or a host and a plugin, claim the same service reference."""

    code = "plugin_runtime.service_conflict"


class DependencyCycleError(DependencyError):
    """Setup ordering cannot be satisfied because providers depend on each other."""

    code = "plugin_runtime.dependency_cycle"


class LifecycleError(PluginRuntimeError):
    """The runtime or a plugin context is used in a state that forbids the operation."""

    code = "plugin_runtime.lifecycle"


class UndeclaredServiceError(LifecycleError):
    """A plugin resolved or published a service it did not declare in its spec."""

    code = "plugin_runtime.undeclared_service"
