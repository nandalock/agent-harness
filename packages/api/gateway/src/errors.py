"""Stable RPC failures: protocol, business and cancellation stay distinct."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RpcError(Exception):
    """Business failure callers may act on.

    ``code`` is a stable application code such as ``workspace/not-found``.
    ``message`` must be safe to show to the caller; never put credentials or
    raw exception text here.
    """

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    jsonrpc_code: int = -32000

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_jsonrpc(self) -> dict[str, Any]:
        return {
            "code": self.jsonrpc_code,
            "message": self.message,
            "data": {"code": self.code, "details": self.details},
        }


class RpcParseError(RpcError):
    def __init__(self, message: str = "Parse error") -> None:
        super().__init__("rpc/parse-error", message, jsonrpc_code=-32700)


class RpcInvalidRequest(RpcError):
    def __init__(self, message: str = "Invalid Request") -> None:
        super().__init__("rpc/invalid-request", message, jsonrpc_code=-32600)


class RpcMethodNotFound(RpcError):
    def __init__(self, method: str) -> None:
        super().__init__(
            "rpc/method-not-found",
            f"Method not found: {method}",
            {"method": method},
            jsonrpc_code=-32601,
        )


class RpcInvalidParams(RpcError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "rpc/invalid-params", message, details or {}, jsonrpc_code=-32602
        )


class RpcInternalError(RpcError):
    def __init__(self) -> None:
        super().__init__("rpc/internal", "Internal error", jsonrpc_code=-32603)


class RpcCancelled(RpcError):
    def __init__(self) -> None:
        super().__init__("rpc/cancelled", "Request cancelled", jsonrpc_code=-32800)
