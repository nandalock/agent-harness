"""Explicit RPC method registration and validated dispatch.

Only methods registered by a controller can be called. There is no service
reflection: a method name maps to one Pydantic request contract and one async
handler owned by the plugin that registered it.
"""
from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import RpcInvalidParams, RpcMethodNotFound
from .models import RpcContext

logger = logging.getLogger(__name__)

_METHOD = re.compile(r"^[a-z][a-zA-Z0-9_]*(?:\.[a-z][a-zA-Z0-9_]*)+$")


@dataclass(frozen=True)
class RpcMethodContract:
    """One public method contract shared by controllers and TS generation."""

    method: str
    params_model: type[BaseModel]
    result_model: type[BaseModel] | None = None


Handler = Callable[[BaseModel, RpcContext], Awaitable[Any]]


class _Registration:
    def __init__(self, gateway: "RpcGateway", method: str, token: object) -> None:
        self._gateway = gateway
        self._method = method
        self._token = token
        self._closed = False

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._gateway._remove(self._method, self._token)


@dataclass(frozen=True)
class _Entry:
    contract: RpcMethodContract
    handler: Handler
    token: object


class RpcGateway:
    """Per-runtime method table; no module-level registry."""

    def __init__(self) -> None:
        self._methods: dict[str, _Entry] = {}

    def register(
        self,
        contract: RpcMethodContract,
        handler: Handler,
    ) -> _Registration:
        if not _METHOD.fullmatch(contract.method):
            raise ValueError(f"invalid RPC method name: {contract.method!r}")
        if contract.method in self._methods:
            raise ValueError(f"RPC method already registered: {contract.method}")
        if not inspect.iscoroutinefunction(handler):
            raise TypeError(f"RPC handler for {contract.method} must be async")
        token = object()
        self._methods[contract.method] = _Entry(contract, handler, token)
        return _Registration(self, contract.method, token)

    def _remove(self, method: str, token: object) -> None:
        entry = self._methods.get(method)
        if entry is not None and entry.token is token:
            del self._methods[method]

    def methods(self) -> tuple[str, ...]:
        return tuple(sorted(self._methods))

    def contracts(self) -> tuple[RpcMethodContract, ...]:
        return tuple(self._methods[name].contract for name in sorted(self._methods))

    async def invoke(self, method: str, params: dict[str, Any], context: RpcContext) -> Any:
        entry = self._methods.get(method)
        if entry is None:
            raise RpcMethodNotFound(method)
        context.check_cancelled()
        try:
            request = entry.contract.params_model.model_validate(params)
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_context=False, include_input=False)
            raise RpcInvalidParams(f"Invalid params for {method}", {"errors": errors}) from None
        result = await entry.handler(request, context)
        context.check_cancelled()
        if entry.contract.result_model is not None:
            validated = entry.contract.result_model.model_validate(result)
            return validated.model_dump(mode="json")
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        return result
