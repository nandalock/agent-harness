"""Service keys owned by the session recovery plugin."""
from typing import Protocol

from agent_platform_plugin_sdk import ServiceKey


class SessionRecovery(Protocol):
    def prepare(self, session_id, **options): ...
    def status(self, events, *, busy=False, last_durable_seq=None) -> dict: ...


SESSION_RECOVERY = ServiceKey[SessionRecovery]("agent.session-recovery")
