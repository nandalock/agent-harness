"""HTTP application service contract."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef


class HttpAppService(Protocol):
    def __call__(self, scope, receive, send) -> Any: ...


HTTP_APP: ServiceKey[HttpAppService] = ServiceKey(
    ServiceRef(name="http.app", api_version=1)
)
