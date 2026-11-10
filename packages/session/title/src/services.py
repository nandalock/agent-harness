"""Service key owned by the session-title plugin."""
from agent_platform_plugin_sdk import ServiceKey
from .service import SessionTitleService

SESSION_TITLE = ServiceKey[SessionTitleService]("agent.session-title")
