"""Stateless bridge to tools.v1, usable without a backend or global runtime."""
import logging
import time
from agent_platform_plugin_sdk import (
    ExecutionScope, ToolCall, ToolContext as SdkToolContext, ToolResult, ToolsService, TOOL_DENIED,
)
from agent_platform_tool_system.context import ToolContext as BackendToolContext
from agent_platform_tool_system.events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED, ToolEvent

logger = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    return name.replace("/", "_").replace(".", "_")


def _result_to_dict(result: ToolResult) -> dict:
    """SDK ToolResult → AgentLoop / Session 认识的后端 dict。"""
    if result.status == "error":
        error = result.error
        assert error is not None
        payload: dict = {"error": error.message, "code": error.code}
        if error.details:
            payload["details"] = error.details
        if result.data is not None:
            payload["data"] = result.data
        return payload
    if isinstance(result.data, dict):
        return result.data
    return {"data": result.data}


class ToolsExecutionAdapter:
    def __init__(self, tools: ToolsService):
        self._tools = tools

    async def execute(
        self,
        tool_name: str,
        args: dict,
        context: BackendToolContext | None = None,
    ) -> dict:
        if context is None:
            # 内部/调试调用没有可信身份：只允许调用方显式点名的工具，且
            # 原生工具拿不到 sandbox/approval 上下文（与旧路径一致，fail-closed）。
            scope = ExecutionScope(tenant_id=1, agent_key="<api>")
            visible = frozenset({tool_name})
        else:
            if (
                context.tenant_id is None
                or context.tenant_id <= 0
                or not context.agent_id
                or context.visible_tool_names is None
            ):
                return {"error": "工具调用缺少已验证的智能体、租户或工具上下文",
                        "code": TOOL_DENIED}
            scope = ExecutionScope(
                tenant_id=context.tenant_id,
                agent_key=context.agent_id,
                session_id=context.session_id,
            )
            visible_set = set(context.visible_tool_names)
            if _safe_name(tool_name) in visible_set:
                visible_set.add(tool_name)
            visible = frozenset(visible_set)

        sdk_context = SdkToolContext(
            scope=scope,
            visible_tool_names=visible,
            host_context=context,
        )
        call = ToolCall(
            call_id=(context.tool_call_id if context is not None else None)
            or tool_name,
            name=tool_name,
            arguments=args,
        )
        start = time.perf_counter()
        await self._emit(context, TOOL_STARTED, tool_name, {})
        try:
            result = await self._tools.execute(call, sdk_context)
        except Exception as exc:  # noqa: BLE001
            await self._emit(
                context,
                TOOL_FAILED,
                tool_name,
                {"error": str(exc), "duration_ms": round((time.perf_counter() - start) * 1000)},
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000)
        if result.error is not None:
            await self._emit(
                context,
                TOOL_FAILED,
                tool_name,
                {"error": result.error.message, "duration_ms": duration_ms},
            )
        else:
            await self._emit(
                context,
                TOOL_COMPLETED,
                tool_name,
                {"duration_ms": duration_ms},
            )
        return _result_to_dict(result)

    @staticmethod
    async def _emit(
        context: BackendToolContext | None,
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
            await sink.emit(ToolEvent(
                type=event_type,
                tool_name=tool_name,
                session_id=context.session_id,
                trace_id=context.trace_id,
                data=data,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ToolEvent 发送失败（%s %s）: %s", event_type, tool_name, exc)
