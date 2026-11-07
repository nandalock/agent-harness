"""Service key owned by the session-title plugin."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef
from .service import SessionTitleService

SESSION_TITLE = ServiceKey[SessionTitleService](
    ServiceRef(name="agent.session-title", api_version=1)
)
