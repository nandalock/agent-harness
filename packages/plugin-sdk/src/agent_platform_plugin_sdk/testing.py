"""Reusable tools.v1 behavior checks for each independently packaged provider.

This is a baseline contract suite, not a substitute for provider-specific tests.
The factory must create a fresh service and allow contract.echo/contract.wait in
its binding repository for the supplied scope. It must not pre-register tools.
"""
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from typing import AsyncIterator

from .errors import RegistrationConflictError, ServiceClosedError
from .models import ExecutionScope, JsonObject
from .tools import (
    TOOL_DENIED, TOOL_NOT_FOUND, TOOL_TIMEOUT, TOOL_UNAVAILABLE,
    ToolCall, ToolContext, ToolDescriptor, ToolResult, ToolsService,
)

ToolsServiceFactory = Callable[[ExecutionScope], Awaitable[ToolsService]]


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _Executor:
    def __init__(self, *, wait: bool = False):
        self.wait = wait
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.calls = 0

    async def execute(self, descriptor: ToolDescriptor, arguments: JsonObject, context: ToolContext) -> ToolResult:
        self.calls += 1
        self.started.set()
        try:
            if self.wait:
                await asyncio.Event().wait()
            return ToolResult(data={"arguments": arguments, "tenant_id": context.scope.tenant_id})
        finally:
            self.cleaned.set()


def _descriptor(name: str = "contract.echo") -> ToolDescriptor:
    return ToolDescriptor(name=name, executor="contract", description="SDK contract fixture")


async def verify_tools_service(factory: ToolsServiceFactory, scope: ExecutionScope | None = None) -> tuple[str, ...]:
    """Raise AssertionError on incompatible behavior and always close each fixture.

    Uses the current task's normal asyncio cancellation and monotonic deadline.
    No network, external processes, backend imports or durable data are needed.
    """
    scope = scope or ExecutionScope(tenant_id=1, agent_key="sdk-contract")
    context = ToolContext(scope=scope, visible_tool_names=frozenset({"contract.echo", "contract.wait", "contract.missing"}))
    call = ToolCall(call_id="contract-1", name="contract.echo", arguments={"tenant_id": 999})
    passed: list[str] = []

    @asynccontextmanager
    async def fresh() -> AsyncIterator[ToolsService]:
        service = await factory(scope)
        try:
            yield service
        finally:
            await service.aclose()

    async with fresh() as service:
        executor = _Executor()
        service.register_executor("contract", executor)
        service.register_tool(_descriptor())
        result = await service.execute(call, context)
        _check(result.status == "success", "registered tool did not execute")
        _check(result.data == {"arguments": {"tenant_id": 999}, "tenant_id": scope.tenant_id}, "trusted context was lost or rewritten from arguments")
        _check(executor.calls == 1, "service retried a tool unexpectedly")
        passed.append("execution_context")

        expired = await service.execute(call, context.model_copy(update={"deadline": monotonic() - 0.001}))
        _check(expired.error is not None and expired.error.code == TOOL_TIMEOUT, "expired call must return tool.timeout")
        _check(executor.calls == 1, "already expired call reached executor")

        denied = await service.execute(call, context.model_copy(update={"visible_tool_names": frozenset()}))
        _check(denied.error is not None and denied.error.code == TOOL_DENIED, "empty visibility must deny dispatch")
        _check(executor.calls == 1, "denied tool reached executor")
        missing = await service.execute(call.model_copy(update={"name": "contract.missing"}), context)
        _check(missing.error is not None and missing.error.code == TOOL_NOT_FOUND, "authorized unknown tool must return tool.not_found")
        passed.append("visibility_and_lookup")

    async with fresh() as service:
        service.register_executor("contract", _Executor())
        original = service.register_tool(_descriptor())
        try:
            service.register_tool(_descriptor())
        except RegistrationConflictError:
            pass
        else:
            raise AssertionError("duplicate tool registration silently replaced its owner")
        try:
            service.register_executor("contract", _Executor())
        except RegistrationConflictError:
            pass
        else:
            raise AssertionError("duplicate executor registration silently replaced its owner")
        await original.aclose()
        names = {descriptor.name for descriptor in await service.list_for_agent(scope)}
        _check("contract.echo" not in names, "closed handle left a tool in discovery")
        service.register_tool(_descriptor())
        await original.aclose()
        result = await service.execute(call, context)
        _check(result.status == "success", "stale registration removed a replacement")
        passed.append("registration_ownership")

    async with fresh() as service:
        executor = _Executor(wait=True)
        service.register_executor("contract", executor)
        service.register_tool(_descriptor())
        task = asyncio.create_task(service.execute(call, context))
        try:
            await asyncio.wait_for(executor.started.wait(), 1)
            task.cancel()
            try:
                await asyncio.wait_for(task, 1)
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("CancelledError was swallowed")
            _check(executor.cleaned.is_set(), "executor cleanup outlived cancellation")
            _check(executor.calls == 1, "cancelled call was retried")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        passed.append("cancellation")

    for source in ("deadline", "tool_timeout"):
        async with fresh() as service:
            executor = _Executor(wait=True)
            service.register_executor("contract", executor)
            timeout_seconds = 0.03 if source == "tool_timeout" else 1.0
            service.register_tool(_descriptor().model_copy(update={"timeout_seconds": timeout_seconds}))
            deadline = context.model_copy(update={"deadline": monotonic() + (1 if source == "tool_timeout" else 0.03)})
            result = await asyncio.wait_for(service.execute(call, deadline), 2)
            _check(result.error is not None and result.error.code == TOOL_TIMEOUT, "deadline did not produce tool.timeout")
            _check(executor.cleaned.is_set(), "deadline returned before executor cleanup")
            _check(executor.calls == 1, "timed-out call was retried")
            passed.append(source)

    async with fresh() as service:
        executor = _Executor()
        service.register_executor("contract", executor)
        service.register_tool(_descriptor())
        await service.aclose()
        await service.aclose()
        result = await service.execute(call, context)
        _check(result.error is not None and result.error.code == TOOL_UNAVAILABLE, "closed service accepted new execution")
        _check(executor.calls == 0, "closed service reached executor")
        try:
            service.register_tool(_descriptor())
        except ServiceClosedError:
            pass
        else:
            raise AssertionError("closed service accepted registration")
        passed.append("shutdown")

    return tuple(passed)
