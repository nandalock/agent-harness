"""JSON-RPC 2.0 envelope and invocation context."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


class RpcEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: str
    id: str | int | None = None
    method: str
    params: dict[str, Any] = {}


@dataclass(frozen=True)
class RpcContext:
    """Caller context assembled by the transport adapter."""

    tenant_id: int
    request_id: str | int | None = None
    session_id: str | None = None
    cancel: asyncio.Event | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise asyncio.CancelledError()
