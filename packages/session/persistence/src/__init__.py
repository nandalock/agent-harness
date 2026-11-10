"""Durable session persistence seam (implemented by backend plugins)."""
from agent_platform_plugin_sdk import ServiceKey

from .base import (
    NoopPersistence,
    SessionPersistence,
    flush_session_events,
)

SESSION_PERSISTENCE = ServiceKey[SessionPersistence]("agent.session-persistence")

__all__ = [
    "SESSION_PERSISTENCE",
    "NoopPersistence",
    "SessionPersistence",
    "flush_session_events",
]
