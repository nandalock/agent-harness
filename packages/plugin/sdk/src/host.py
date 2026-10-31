"""Host services shared by native-capability plugins.

These contracts invert the old dependency direction: a sandbox or skill plugin
declares the capability it needs (approval, settings, agent configuration) and
the host supplies an implementation at runtime. The plugin never imports the
backend.

Only the vocabulary a plugin actually consumes lives here. Implementations
(DB-backed settings, the in-process approval channel, agent loading) belong to
the host.
"""
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
import uuid

from .lifecycle import ServiceKey
from .models import ServiceRef

# ── approval.v1 ──

ApprovalOutcome = Literal["allowed-once", "rejected", "cancelled", "unavailable"]

#: The only value that grants permission. Everything else fails closed.
ALLOWED: ApprovalOutcome = "allowed-once"


@dataclass(frozen=True)
class ApprovalRequest:
    """One request for a human decision; domain details go in ``metadata``."""

    approval_id: str
    reason: str
    tool_name: str = ""
    tool_call_id: str | None = None
    agent: object | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signal: object | None = None

    def to_dict(self) -> dict[str, Any]:
        """API/UI view; ``agent`` is stringified because it is an opaque object."""
        return {
            "approval_id": self.approval_id,
            "reason": self.reason,
            "tool": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "agent": None if self.agent is None else str(self.agent),
            "metadata": self.metadata,
        }


class ApprovalChannel(Protocol):
    async def request(self, req: ApprovalRequest) -> ApprovalOutcome: ...


class ApprovalService(Protocol):
    """Host-supplied approval decision authority.

    ``available`` reports whether a decision authority exists. When it is
    false, callers must fail closed rather than assume approval.
    """

    @property
    def available(self) -> bool: ...

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome: ...


def new_approval_id() -> str:
    """Short, paired-with-one-request identifier."""
    return uuid.uuid4().hex[:12]


APPROVAL: ServiceKey[ApprovalService] = ServiceKey(
    ServiceRef(name="approval", api_version=1)
)


# ── settings.v1 ──

class SettingsService(Protocol):
    """Namespace-scoped JSON settings owned by a capability plugin."""

    async def get(self, namespace: str) -> dict[str, Any]: ...

    async def set(self, namespace: str, value: dict[str, Any]) -> None: ...


SETTINGS: ServiceKey[SettingsService] = ServiceKey(
    ServiceRef(name="settings", api_version=1)
)


# ── agents.v1 ──

class AgentConfigService(Protocol):
    """Read the effective configuration for one agent key."""

    async def get_config(self, agent_key: str) -> dict[str, Any] | None: ...


AGENTS: ServiceKey[AgentConfigService] = ServiceKey(
    ServiceRef(name="agents", api_version=1)
)
