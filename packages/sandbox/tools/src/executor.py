"""Bridge from the tools.v1 executor contract to ``SandboxExecutor``."""
from typing import Any

from agent_platform_plugin_sdk import (
    JsonObject,
    TOOL_NOT_FOUND,
    TOOL_UNAVAILABLE,
    ToolContext,
    ToolDescriptor,
    ToolError,
    ToolResult,
)
from agent_platform_tool_system.descriptor import ToolDescriptor as NativeToolDescriptor

from agent_platform_sandbox.executor import SandboxExecutor


class SandboxToolExecutor:
    """One executor shared by bash/python; native descriptors carry the config.

    ``context.host_context`` is the documented opaque bridge for host sandbox
    policy/event sink. This plugin is a native-capability adapter; model
    arguments never contribute to it.
    """

    def __init__(
        self,
        descriptors: dict[str, NativeToolDescriptor],
        executor: SandboxExecutor,
    ) -> None:
        self._descriptors = descriptors
        self._executor = executor

    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: JsonObject,
        context: ToolContext,
    ) -> ToolResult:
        native = self._descriptors.get(descriptor.name)
        if native is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_NOT_FOUND,
                    message=f"沙箱工具未注册: {descriptor.name}",
                ),
            )
        host_context: Any = context.host_context
        if host_context is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_UNAVAILABLE,
                    message=f"沙箱策略缺失，拒绝执行 {descriptor.name}（沙箱未装配？）",
                ),
            )
        raw = await self._executor.execute(native, dict(arguments), host_context)
        if isinstance(raw, dict) and raw.get("error"):
            return ToolResult(
                status="error",
                error=ToolError(
                    code=str(raw.get("code") or "tool.failed"),
                    message=str(raw["error"]),
                ),
            )
        return ToolResult(data=raw)
