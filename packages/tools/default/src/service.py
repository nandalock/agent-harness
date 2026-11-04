"""A complete in-process implementation of `tools.v1`.

Registration, executor/provider ownership, call-time visibility, deadline
enforcement and shutdown semantics live here. The backend only mirrors these
descriptors for bindings/UI and delegates execution back into this service.
"""
import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from agent_platform_plugin_sdk import (
    ExecutionScope,
    Registration,
    RegistrationConflictError,
    ServiceClosedError,
    ToolCall,
    ToolContext,
    ToolDescriptor,
    ToolError,
    ToolExecutor,
    ToolProvider,
    ToolResult,
    TOOL_DENIED,
    TOOL_NOT_FOUND,
    TOOL_TIMEOUT,
    TOOL_UNAVAILABLE,
)

from .catalog import ToolCatalog

logger = logging.getLogger(__name__)


def _unavailable(message: str) -> ToolResult:
    return ToolResult(
        status="error", error=ToolError(code=TOOL_UNAVAILABLE, message=message)
    )


def _deadline_for(descriptor: ToolDescriptor, caller: float | None) -> float | None:
    if descriptor.timeout_seconds is None:
        return caller
    cap = time.monotonic() + descriptor.timeout_seconds
    return cap if caller is None else min(caller, cap)


@dataclass(frozen=True)
class _ToolEntry:
    descriptor: ToolDescriptor
    token: object


class _Registration:
    def __init__(self, remove: Callable[[], None]) -> None:
        self._remove = remove
        self._closed = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._remove()


class ToolsDefaultService(ToolCatalog):
    """One scope's tool table; safe to share by every consumer in a host."""

    def __init__(self) -> None:
        self._tools: dict[str, _ToolEntry] = {}
        self._executors: dict[str, tuple[object, ToolExecutor]] = {}
        self._providers: dict[str, tuple[object, ToolProvider]] = {}
        self._closed = False

    # ── tools.v1 registration ──

    def register_tool(self, descriptor: ToolDescriptor) -> Registration:
        self._ensure_open()
        if descriptor.name in self._tools:
            raise RegistrationConflictError(
                f"tool already registered: {descriptor.name}"
            )
        token = object()
        self._tools[descriptor.name] = _ToolEntry(descriptor, token)

        def remove() -> None:
            entry = self._tools.get(descriptor.name)
            if entry is not None and entry.token is token:
                del self._tools[descriptor.name]

        return _Registration(remove)

    def register_executor(self, name: str, executor: ToolExecutor) -> Registration:
        self._ensure_open()
        if name in self._executors:
            raise RegistrationConflictError(f"executor already registered: {name}")
        token = object()
        self._executors[name] = (token, executor)

        def remove() -> None:
            entry = self._executors.get(name)
            if entry is not None and entry[0] is token:
                del self._executors[name]

        return _Registration(remove)

    def register_provider(self, provider: ToolProvider) -> Registration:
        self._ensure_open()
        name = provider.name
        if name in self._providers:
            raise RegistrationConflictError(f"provider already registered: {name}")
        token = object()
        self._providers[name] = (token, provider)

        def remove() -> None:
            entry = self._providers.get(name)
            if entry is not None and entry[0] is token:
                del self._providers[name]

        return _Registration(remove)

    # ── tools.v1 reads ──

    async def list_for_agent(self, scope: ExecutionScope) -> tuple[ToolDescriptor, ...]:
        if self._closed:
            return ()
        found: dict[str, ToolDescriptor] = {
            name: entry.descriptor for name, entry in self._tools.items()
        }
        for _, provider in list(self._providers.values()):
            try:
                for descriptor in await provider.discover(scope):
                    found.setdefault(descriptor.name, descriptor)
            except Exception as exc:  # noqa: BLE001
                logger.warning("provider %r discover failed: %s", provider.name, exc)
        return tuple(found.values())

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        if self._closed:
            return _unavailable("tools service is closed")
        if call.name not in context.visible_tool_names:
            return ToolResult(
                status="error",
                error=ToolError(code=TOOL_DENIED, message=f"tool denied: {call.name}"),
            )

        descriptor = self._descriptor(call.name)
        if descriptor is None:
            descriptor = await self._lazy_descriptor(call.name, context.scope)
        if descriptor is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_NOT_FOUND, message=f"tool not found: {call.name}"
                ),
            )

        entry = self._executors.get(descriptor.executor)
        if entry is None:
            return _unavailable(f"executor not registered: {descriptor.executor}")
        executor = entry[1]

        deadline = _deadline_for(descriptor, context.deadline)
        if deadline is not None and deadline <= time.monotonic():
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_TIMEOUT, message=f"tool deadline expired: {call.name}"
                ),
            )
        try:
            if deadline is None:
                return await executor.execute(descriptor, call.arguments, context)
            async with asyncio.timeout_at(deadline):
                return await executor.execute(descriptor, call.arguments, context)
        except TimeoutError:
            return ToolResult(
                status="error",
                error=ToolError(code=TOOL_TIMEOUT, message=f"tool timed out: {call.name}"),
            )
        except Exception as exc:  # noqa: BLE001
            # Ordinary infrastructure failures become error results; cancellation
            # is a BaseException and still propagates.
            return _unavailable(f"tool failed: {call.name}: {exc}")

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tools.clear()
        self._executors.clear()
        self._providers.clear()

    # ── ToolCatalog (host snapshot) ──

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(entry.descriptor for entry in self._tools.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    # ── internals ──

    def _descriptor(self, name: str) -> ToolDescriptor | None:
        entry = self._tools.get(name)
        return entry.descriptor if entry is not None else None

    async def _lazy_descriptor(
        self, name: str, scope: ExecutionScope
    ) -> ToolDescriptor | None:
        for _, provider in list(self._providers.values()):
            try:
                descriptor = await provider.lazy_load(name, scope)
            except Exception as exc:  # noqa: BLE001
                logger.warning("provider %r lazy_load failed: %s", provider.name, exc)
                continue
            if descriptor is not None:
                return descriptor
        return None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ServiceClosedError("tools service is closed")
