"""Session RPC contracts."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionIdParams(_Model):
    session_id: str


class SessionRecoveryResult(_Model):
    session_id: str
    status: str
    last_durable_seq: int = 0
    source_turn_start_seq: int | None = None
    can_resume: bool = False
    unknown_tool_calls: list[dict[str, Any]] = []


class SessionTrajectoryResult(_Model):
    session_id: str
    trajectory: dict[str, Any]


class SessionSandboxModeResult(_Model):
    session_id: str
    override: str | None = None
    default: str | None = None
    effective: str


class SessionSetSandboxModeParams(_Model):
    session_id: str
    mode: str


class SessionSetSandboxModeResult(_Model):
    session_id: str
    override: str
