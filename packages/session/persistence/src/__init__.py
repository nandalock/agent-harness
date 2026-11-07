"""Durable session persistence seam (implemented by backend plugins)."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .base import (
    NoopPersistence,
    SessionPersistence,
    flush_session_events,
)

SESSION_PERSISTENCE = ServiceKey[SessionPersistence](
    ServiceRef(name="agent.session-persistence", api_version=1)
)

__all__ = [
    "SESSION_PERSISTENCE",
    "NoopPersistence",
    "SessionPersistence",
    "flush_session_events",
]
