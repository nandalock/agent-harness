"""Service key for the session API controller."""
from agent_platform_plugin_sdk import ServiceKey

from .service import SessionApiService

SESSION_API: ServiceKey[SessionApiService] = ServiceKey("session.api")
