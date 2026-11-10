"""Sandbox service contracts (providers and per-session policy)."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey

from .provider import SandboxProvider


class AgentSandboxPolicy(Protocol):
    def policy(self, session: Any) -> Any: ...


SANDBOX: ServiceKey[SandboxProvider] = ServiceKey("sandbox")
AGENT_SANDBOX: ServiceKey[AgentSandboxPolicy] = ServiceKey("agent.sandbox")
