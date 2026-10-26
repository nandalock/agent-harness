"""ToolContext — one call's runtime context (Agent Runtime → Tool).

This package only carries values; host adapters/sandbox/approval implementations
interpret them. Keeping the sandbox policy and approval channel opaque is what
lets the core stay independent of a particular host.
"""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    """Read-only context for one tool call (`None` means the host did not supply it)."""

    session_id: str | None = None
    tool_call_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    event_sink: Any | None = None
    #: Host sandbox policy; sandbox tools fail closed when it is absent.
    sandbox_policy: Any | None = None
    #: Host approval channel (`async request(req) -> outcome`); None means no
    #: decision authority, so approval-requiring tools fail closed.
    approval: Any | None = None
    tenant_id: int | None = None
    visible_tool_names: frozenset[str] | None = None
