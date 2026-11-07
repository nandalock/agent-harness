"""Plugin service keys owned by the session core."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef
from .store import SessionStore

SESSIONS = ServiceKey[SessionStore](ServiceRef(name="agent.sessions", api_version=1))
