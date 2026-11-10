"""Plugin service keys owned by the session core."""
from agent_platform_plugin_sdk import ServiceKey
from .store import SessionStore

SESSIONS = ServiceKey[SessionStore]("agent.sessions")
