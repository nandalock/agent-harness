"""tools.v1 executors for skill loading and installation."""
import asyncio
from typing import Any, cast
import zipfile

import aiohttp

from agent_platform_plugin_sdk import (
    AgentConfigService,
    JsonObject,
    JsonValue,
    ToolContext,
    ToolDescriptor,
    ToolError,
    ToolResult,
)
from agent_platform_skills.installer import (
    install_enabled,
    install_skill,
    list_available,
)
from agent_platform_skills.registry import SkillError
from agent_platform_skills.runtime import load_model_skill, scope_for


def _error(message: str) -> ToolResult:
    return ToolResult(
        status="error", error=ToolError(code="tool.failed", message=message)
    )


class _SkillExecutorBase:
    def __init__(self, agents: AgentConfigService) -> None:
        self._agents = agents

    async def _config(self, context: ToolContext) -> dict[str, Any]:
        return await self._agents.get_config(context.scope.agent_key) or {}


class SkillExecutor(_SkillExecutorBase):
    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: JsonObject,
        context: ToolContext,
    ) -> ToolResult:
        config = await self._config(context)
        scope = scope_for(  # type: ignore[no-untyped-call]
            context.scope.tenant_id,
            context.scope.agent_key,
            context.visible_tool_names,
            config,
        )
        name = arguments.get("name")
        if not isinstance(name, str):
            return _error("技能名称必须为字符串")
        resource = arguments.get("resource")
        if resource is not None and not isinstance(resource, str):
            return _error("技能资源路径必须为字符串")
        try:
            row = await asyncio.to_thread(
                load_model_skill, name, scope, resource=resource
            )
        except SkillError as exc:
            return _error(str(exc))
        return ToolResult(
            data={"tool": descriptor.name, "rows": [row], "count": 1}
        )


class SkillInstallExecutor(_SkillExecutorBase):
    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: JsonObject,
        context: ToolContext,
    ) -> ToolResult:
        if (
            context.scope.tenant_id is None
            or not context.scope.agent_key
            or "skill_install" not in context.visible_tool_names
        ):
            return _error("技能安装缺少已验证的智能体、租户或工具上下文")
        config = await self._config(context)
        if not install_enabled(config):
            return _error("当前智能体已停用聊天安装技能")
        if set(arguments) - {"action", "source", "ref", "tenant_id"}:
            return _error("技能安装参数无效")
        try:
            scope = scope_for(  # type: ignore[no-untyped-call]
                context.scope.tenant_id,
                context.scope.agent_key,
                context.visible_tool_names,
                config,
            )
            action = arguments.get("action")
            source = arguments.get("source")
            ref = arguments.get("ref")
            if ref is not None and not isinstance(ref, str):
                return _error("ref 必须为字符串")
            if action == "list":
                rows = await list_available(scope)
            elif action == "install":
                if not isinstance(source, str):
                    return _error("source 必须为字符串")
                rows = [await install_skill(source, scope, ref)]
            else:
                return _error("action 必须为 list 或 install")
        except TimeoutError:
            return _error("技能下载超时，请稍后重试；请先检查是否已安装")
        except (
            aiohttp.ClientError,
            OSError,
            ValueError,
            zipfile.BadZipFile,
            RuntimeError,
        ) as exc:
            return _error(str(exc))
        return ToolResult(
            data=cast(
                JsonValue,
                {"tool": descriptor.name, "rows": rows, "count": len(rows)},
            )
        )
