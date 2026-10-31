"""ToolRuntime — native tool executor dispatcher.

The host supplies the executor mapping (MCP, sandbox, skill, ...). This class
only resolves a descriptor, dispatches by ``descriptor.type``, and emits the
tool lifecycle events; it has no MCP/HTTP/sandbox knowledge.
"""
import logging
import time
from typing import Protocol

from .context import ToolContext
from .descriptor import ToolDescriptor
from .events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED, ToolEvent
from .registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    async def execute(
        self,
        descriptor: ToolDescriptor,
        args: dict,
        context: ToolContext | None = None,
    ) -> dict: ...


class ToolRuntime:
    """Dispatch native tool calls to the host's executors and emit events."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        executors: dict[str, ToolExecutor] | None = None,
    ) -> None:
        self._registry = registry or get_registry()
        self._executors: dict[str, ToolExecutor] = (
            dict(executors) if executors is not None else {}
        )

    def register_executor(self, type_: str, executor: ToolExecutor) -> None:
        """Register one executor kind; duplicate types are rejected."""
        if type_ in self._executors:
            raise ValueError(f"执行器已注册: {type_}")
        self._executors[type_] = executor

    def unregister_executor(
        self, type_: str, executor: ToolExecutor | None = None
    ) -> None:
        """Remove an executor; with ``executor`` only when it is the same object."""
        current = self._executors.get(type_)
        if current is not None and (executor is None or current is executor):
            del self._executors[type_]

    async def execute_descriptor(
        self,
        descriptor: ToolDescriptor,
        args: dict,
        context: ToolContext | None = None,
    ) -> dict:
        """Execute a descriptor without producing lifecycle events."""
        executor = self._executors.get(descriptor.type)
        if executor is None:
            raise RuntimeError(
                f"没有匹配的执行器: type={descriptor.type} (tool={descriptor.name})"
            )
        return await executor.execute(descriptor, args, context)

    async def execute(
        self,
        tool_name: str,
        args: dict,
        context: ToolContext | None = None,
    ) -> dict:
        """Resolve and execute a tool; emits started → completed/failed."""
        descriptor = await self._registry.resolve(tool_name)
        if descriptor is None:
            raise KeyError(f"工具未注册: {tool_name}")

        start = time.perf_counter()
        await self._emit(context, TOOL_STARTED, tool_name, {})
        try:
            result = await self.execute_descriptor(descriptor, args, context)
        except Exception as exc:
            await self._emit(
                context,
                TOOL_FAILED,
                tool_name,
                {
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - start) * 1000),
                },
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000)
        error = result.get("error") if isinstance(result, dict) else None
        if error:
            await self._emit(
                context,
                TOOL_FAILED,
                tool_name,
                {"error": error, "duration_ms": duration_ms},
            )
        else:
            await self._emit(
                context,
                TOOL_COMPLETED,
                tool_name,
                {
                    "count": result.get("count")
                    if isinstance(result, dict)
                    else None,
                    "duration_ms": duration_ms,
                },
            )
        return result

    @staticmethod
    async def _emit(
        context: ToolContext | None,
        event_type: str,
        tool_name: str,
        data: dict,
    ) -> None:
        if context is None:
            return
        sink = context.event_sink
        if sink is None:
            return
        try:
            await sink.emit(
                ToolEvent(
                    type=event_type,
                    tool_name=tool_name,
                    session_id=context.session_id,
                    trace_id=context.trace_id,
                    data=data,
                )
            )
        except Exception as exc:
            logger.warning(
                "ToolEvent 发送失败（不影响执行）: %s %s: %s",
                event_type,
                tool_name,
                exc,
            )
