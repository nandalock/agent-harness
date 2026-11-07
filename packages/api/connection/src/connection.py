"""Carrier-neutral JSON-RPC 2.0 connection over an RpcGateway."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent_platform_rpc_gateway import (
    RpcCancelled,
    RpcContext,
    RpcError,
    RpcInternalError,
    RpcInvalidRequest,
    RpcParseError,
)

logger = logging.getLogger(__name__)


class RpcConnection:
    """Decode one JSON-RPC request, dispatch it, and build the response."""

    def __init__(self, gateway) -> None:
        self._gateway = gateway

    async def dispatch_json(
        self,
        raw: str | bytes,
        *,
        tenant_id: int,
        session_id: str | None = None,
        cancel: asyncio.Event | None = None,
    ):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return _error(None, RpcParseError())
        return await self.dispatch(
            payload, tenant_id=tenant_id, session_id=session_id, cancel=cancel,
        )

    async def dispatch(
        self,
        payload: Any,
        *,
        tenant_id: int,
        session_id: str | None = None,
        cancel: asyncio.Event | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(payload, list):
            if not payload:
                return _error(None, RpcInvalidRequest("Empty batch"))
            responses = []
            for item in payload:
                response = await self._one(
                    item, tenant_id=tenant_id, session_id=session_id, cancel=cancel
                )
                if response is not None:
                    responses.append(response)
            return responses or None
        return await self._one(
            payload, tenant_id=tenant_id, session_id=session_id, cancel=cancel
        )

    async def _one(
        self, payload: Any, *, tenant_id: int, session_id: str | None,
        cancel: asyncio.Event | None,
    ) -> dict[str, Any] | None:
        request_id: str | int | None = None
        notification = True
        try:
            if not isinstance(payload, dict):
                raise RpcInvalidRequest("Request must be an object")
            request_id = payload.get("id")
            notification = "id" not in payload
            if payload.get("jsonrpc") != "2.0":
                raise RpcInvalidRequest("jsonrpc must be exactly '2.0'")
            if not notification and not (
                request_id is None
                or isinstance(request_id, str)
                or (isinstance(request_id, int) and not isinstance(request_id, bool))
            ):
                raise RpcInvalidRequest("id must be a string, number, or null")
            method = payload.get("method")
            if not isinstance(method, str) or not method:
                raise RpcInvalidRequest("method must be a non-empty string")
            params = payload.get("params", {})
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise RpcInvalidRequest("params must be an object")
            context = RpcContext(
                tenant_id=tenant_id,
                request_id=request_id,
                session_id=session_id,
                cancel=cancel,
            )
            result = await self._gateway.invoke(method, params, context)
            if notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except asyncio.CancelledError:
            error: RpcError = RpcCancelled()
        except RpcError as exc:
            error = exc
        except Exception:  # noqa: BLE001 — never leak internal exception text
            logger.exception("RPC dispatch failed")
            error = RpcInternalError()
        if notification:
            return None
        return _error(request_id, error)


def _error(request_id: str | int | None, exc: RpcError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": exc.to_jsonrpc()}
