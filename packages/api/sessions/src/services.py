"""Service key for the session API controller."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .service import SessionApiService

SESSION_API: ServiceKey[SessionApiService] = ServiceKey(
    ServiceRef(name="session.api", api_version=1)
)
