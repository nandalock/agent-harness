"""Sandbox service contracts (providers and per-session policy)."""
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .provider import SandboxProvider


class AgentSandboxPolicy(Protocol):
    def policy(self, session: Any) -> Any: ...


SANDBOX: ServiceKey[SandboxProvider] = ServiceKey(
    ServiceRef(name="sandbox", api_version=1)
)
AGENT_SANDBOX: ServiceKey[AgentSandboxPolicy] = ServiceKey(
    ServiceRef(name="agent.sandbox", api_version=1)
)
