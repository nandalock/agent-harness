"""Machine-readable failures at the plugin host boundary."""
from .models import SDK_API_VERSION, PluginSpec, ServiceRef


class PluginSdkError(RuntimeError):
    code = "plugin.error"


class PluginCompatibilityError(PluginSdkError):
    code = "plugin.incompatible_sdk"


class ServiceUnavailableError(PluginSdkError):
    code = "plugin.service_unavailable"

    def __init__(self, service: ServiceRef):
        self.service = service
        super().__init__(f"Required service is unavailable: {service}")


class RegistrationConflictError(PluginSdkError):
    code = "plugin.registration_conflict"


class ServiceClosedError(PluginSdkError):
    code = "plugin.service_closed"


def ensure_sdk_compatible(spec: PluginSpec) -> None:
    """Reject incompatible plugins before setup or service publication.

    API 1 matches exactly; package release versions do not select compatibility.
    This check validates metadata, not method signatures or behavior.
    """
    if spec.sdk_api_version != SDK_API_VERSION:
        raise PluginCompatibilityError(
            f"{spec.name} requires SDK API {spec.sdk_api_version}; host provides {SDK_API_VERSION}"
        )
