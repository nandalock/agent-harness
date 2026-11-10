"""Service contracts shared by capability plugins and host adapters."""

from dataclasses import dataclass, field
from typing import Any, ContextManager, Literal, Protocol
import uuid

from minidsh_cordis import ServiceKey

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
    """Approval decision authority.

    ``available`` reports whether a decision authority exists. When it is
    false, callers must fail closed rather than assume approval.
    """

    @property
    def available(self) -> bool: ...

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome: ...


def new_approval_id() -> str:
    """Short, paired-with-one-request identifier."""
    return uuid.uuid4().hex[:12]


APPROVAL: ServiceKey[ApprovalService] = ServiceKey("approval")


# ── settings.v1 ──

class SettingsService(Protocol):
    """Namespace-scoped JSON settings owned by a capability plugin."""

    async def get(self, namespace: str) -> dict[str, Any]: ...

    async def set(self, namespace: str, value: dict[str, Any]) -> None: ...


SETTINGS: ServiceKey[SettingsService] = ServiceKey("settings")


# ── agents.v1 ──

class AgentConfigService(Protocol):
    """Read and update agent definitions/configs for one runtime."""

    async def get_config(self, agent_key: str) -> dict[str, Any] | None: ...

    async def get_definition(self, agent_key: str) -> dict[str, Any] | None: ...

    async def list_definitions(self) -> list[dict[str, Any]]: ...

    async def save_config(self, agent_key: str, config: dict[str, Any]) -> dict[str, Any]: ...

    async def list_l1_keywords(self, router_key: str) -> list[dict[str, Any]]: ...

    async def create_l1_keyword(self, router_key: str, keywords: list[str], target: str) -> dict[str, Any]: ...

    async def update_l1_keyword(self, rule_id: int, router_key: str, keywords: list[str], target: str) -> dict[str, Any] | None: ...

    async def delete_l1_keyword(self, rule_id: int, router_key: str) -> bool: ...


AGENTS: ServiceKey[AgentConfigService] = ServiceKey("agents")


# ── tool-bindings.v1 ──

class ToolBindingsService(Protocol):
    """Read the explicitly bound tool names for one agent key."""

    def get_bindings(self, agent_key: str) -> list[str]: ...


TOOL_BINDINGS: ServiceKey[ToolBindingsService] = ServiceKey("tool-bindings")


# ── database.v1 ──

class Database(Protocol):
    """Host-provided pooled connection factory (context manager)."""

    def get_conn(self) -> ContextManager[Any]: ...


DATABASE: ServiceKey[Database] = ServiceKey("database")


# ── plugin-catalog.v1 ──

class PluginCatalog(Protocol):
    """Host-supplied view of the plugin instances that actually started.

    Disabled or failed instances are absent; clients use this as the single
    enablement source when composing their own UI or capabilities.
    """

    def list(self) -> list[dict[str, Any]]: ...

    def web_packages(self) -> tuple[str, ...]: ...


PLUGIN_CATALOG: ServiceKey[PluginCatalog] = ServiceKey("plugin-catalog")
