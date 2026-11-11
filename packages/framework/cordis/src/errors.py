"""Failures shared by the kernel and its hosts."""

from typing import Any

from .services import ServiceKey


class DependencyError(ValueError):
    """The declared service graph cannot be satisfied."""

    code = "plugin_runtime.dependency"


class MissingServiceError(DependencyError, LookupError):
    """A required service has no provider."""

    code = "plugin_runtime.missing_service"


class ServiceConflictError(DependencyError):
    """Two providers claim the same service."""

    code = "plugin_runtime.service_conflict"


class DependencyCycleError(DependencyError):
    """The service dependencies form a cycle."""

    code = "plugin_runtime.dependency_cycle"


class UndeclaredServiceError(LookupError, ValueError):
    """A plugin accessed a service outside its declared contract."""

    code = "plugin_runtime.undeclared_service"


class ServiceUnavailableError(LookupError, RuntimeError):
    code = "plugin.service_unavailable"

    def __init__(self, service: ServiceKey[Any]):
        self.service = service
        super().__init__(f"service {service} is unavailable")


class PinnedServiceError(RuntimeError):
    """A live host binding would be invalidated by a replacement."""


class ServiceClosedError(RuntimeError):
    """A service or context has already closed."""

    code = "plugin.service_closed"


class RegistrationConflictError(ValueError, RuntimeError):
    """A registration would overwrite an existing one."""

    code = "plugin.registration_conflict"
