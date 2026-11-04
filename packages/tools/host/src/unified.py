"""Host queries/bindings over the single plugin-owned tools.v1 registry.

The application registers all tools through plugins. Native executor hooks are
retained for embedded hosts and tests. Execution conversion/events are shared
with independently loaded agent drivers through ToolsExecutionAdapter.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, cast

from agent_platform_plugin_sdk import (
    ExecutionScope,
    Registration,
    RegistrationConflictError,
    ToolContext as SdkToolContext,
    ToolDescriptor as SdkToolDescriptor,
    ToolError,
    ToolResult,
    ToolsService,
    TOOL_NOT_FOUND,
    TOOL_UNAVAILABLE,
)
from agent_platform_tools_default import ToolCatalog
from pydantic import ValidationError

from agent_platform_tool_system.context import ToolContext as BackendToolContext
from agent_platform_tool_system.descriptor import ToolDescriptor as BackendToolDescriptor
from agent_platform_tool_system.registry import ToolRegistry
from agent_platform_tool_system.runtime import ToolRuntime

logger = logging.getLogger(__name__)

#: tools-default 中代表 backend 原生工具的 executor 名。
NATIVE_EXECUTOR = "backend.native"


def _safe_name(tool_name: str) -> str:
    """与 AgentLoop._safe_name 保持一致：LLM 侧名字会替换 / 和 .。"""
    return tool_name.replace("/", "_").replace(".", "_")


def _native_to_sdk(descriptor: BackendToolDescriptor) -> SdkToolDescriptor:
    schema = descriptor.schema or {}
    input_schema = schema.get("inputSchema")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        input_schema = {"type": "object", "properties": {}}
    return SdkToolDescriptor(
        name=descriptor.name,
        executor=NATIVE_EXECUTOR,
        description=schema.get("description") or descriptor.name,
        input_schema=input_schema,
        execution_mode=cast(
            Literal["parallel", "exclusive"], descriptor.execution_mode
        ),
        timeout_seconds=descriptor.timeout,
        usage_guidance=descriptor.usage_guidance,
    )


def _dict_to_result(raw: Any) -> ToolResult:
    """backend executor 的 dict 结果 → SDK ToolResult。"""
    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            status="error",
            error=ToolError(
                code=str(raw.get("code") or "tool.failed"),
                message=str(raw["error"]),
            ),
        )
    return ToolResult(data=raw)


from .execution import ToolsExecutionAdapter


@dataclass(frozen=True)
class AgentToolDescriptor:
    """提示词/绑定层需要的一个工具视图。"""

    name: str
    description: str
    input_schema: dict
    usage_guidance: str | None
    source: str


class NativeToolExecutor:
    """tools-default 的 executor：把调用转给 backend 原生执行器。"""

    def __init__(self, unified: "UnifiedToolsRuntime") -> None:
        self._unified = unified

    async def execute(
        self,
        descriptor: SdkToolDescriptor,
        arguments: dict,
        context: SdkToolContext,
    ) -> ToolResult:
        native = self._unified.native_descriptor(descriptor.name)
        if native is None:
            return ToolResult(
                status="error",
                error=ToolError(
                    code=TOOL_NOT_FOUND,
                    message=f"原生工具未注册: {descriptor.name}",
                ),
            )
        host_context = context.host_context
        raw = await self._unified.native_runtime.execute_descriptor(
            native, arguments, host_context
        )
        return _dict_to_result(raw)


class UnifiedToolsRuntime(ToolsExecutionAdapter):
    """单轨入口：插件工具与原生工具共用一个 tools-default 注册表。"""

    def __init__(
        self,
        registry: ToolRegistry,
        native_runtime: ToolRuntime,
        tools: ToolsService,
        catalog: ToolCatalog,
    ) -> None:
        self._registry = registry
        self._native_runtime = native_runtime
        self._tools = tools
        self._catalog = catalog
        self._native: dict[str, BackendToolDescriptor] = {}
        self._sdk: dict[str, SdkToolDescriptor] = {}
        self._registrations: dict[str, Registration] = {}
        self._modes: dict[str, str] = {}
        self._sources: dict[str, str] = {}
        self._plugin_owned: set[str] = set()
        self._executor = NativeToolExecutor(self)
        self._executor_registration: Registration | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._pending: set[asyncio.Task] = set()
        self._started = False

    # ── 生命周期 ──

    async def start(self) -> None:
        if self._started:
            return
        self._executor_registration = self._tools.register_executor(
            NATIVE_EXECUTOR, self._executor
        )
        # 插件已经注册的同名工具优先；原生 MCP 工具只在没有插件提供者时兜底。
        self._plugin_owned = {d.name for d in self._catalog.descriptors()}
        for descriptor in self._registry.descriptors():
            if descriptor.type != "plugin":
                self._register_native(descriptor)
        for plugin_descriptor in self._catalog.descriptors():
            self._sdk.setdefault(plugin_descriptor.name, plugin_descriptor)
            self._modes[plugin_descriptor.name] = plugin_descriptor.execution_mode
            self._sources.setdefault(
                plugin_descriptor.name, self._plugin_source(plugin_descriptor)
            )
        self._unsubscribe = self._registry.on_change(self._on_native_change)
        self._started = True
        logger.info(
            "单轨工具运行时已装配：%d 个原生工具，%d 个插件工具",
            len(self._native),
            len(self._sources) - len(self._native),
        )

    async def aclose(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)
        for registration in list(self._registrations.values()):
            try:
                await registration.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("注销原生工具失败: %s", exc)
        self._registrations.clear()
        if self._executor_registration is not None:
            try:
                await self._executor_registration.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("注销原生 executor 失败: %s", exc)
            self._executor_registration = None
        self._native.clear()
        self._sdk.clear()
        self._modes.clear()
        self._sources.clear()
        self._plugin_owned.clear()

    # ── AgentLoop 执行入口（与 ToolRuntime.execute 同签名） ──

    async def execute(self, tool_name: str, args: dict, context: BackendToolContext | None = None) -> dict:
        if not self._started:
            return {"error": "单轨工具运行时已关闭", "code": TOOL_UNAVAILABLE}
        return await super().execute(tool_name, args, context)

    # ── 提示词 / 绑定 / UI 查询 ──

    async def descriptors_for_agent(
        self, tenant_id: int, agent_key: str
    ) -> list[AgentToolDescriptor]:
        """本 agent 绑定且当前可解析的工具（单轨注册表来源）。"""
        if tenant_id <= 0 or not agent_key:
            return []
        try:
            bound = set(self._registry.get_bindings(agent_key))
        except Exception:
            return []
        # 绑定了但尚未索引的远程 MCP 工具：按需走一次 Registry 懒加载，再补进
        # 单轨注册表。这样“绑定即可用”，不要求启动时已经连上所有 server。
        for name in bound:
            if name in self._native or self._catalog.has_tool(name):
                continue
            try:
                descriptor = await self._registry.resolve(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("解析绑定工具 %s 失败: %s", name, exc)
                continue
            if descriptor is not None and descriptor.type != "plugin":
                self._register_native(descriptor)
        scope = ExecutionScope(tenant_id=tenant_id, agent_key=agent_key)
        try:
            descriptors = await self._tools.list_for_agent(scope)
        except Exception as exc:  # noqa: BLE001
            logger.warning("工具服务发现失败: %s", exc)
            return []
        return [
            AgentToolDescriptor(
                name=d.name,
                description=d.description,
                input_schema=dict(d.input_schema),
                usage_guidance=d.usage_guidance,
                source=self._sources.get(d.name) or self._plugin_source(d),
            )
            for d in descriptors
            if d.name in bound
        ]

    def list_tools(self) -> list[dict]:
        """UI 列表：直接注册的原生 + 插件工具（provider 懒加载工具不在此列）。"""
        tools = []
        for descriptor in self._catalog.descriptors():
            source = self._sources.get(descriptor.name) or self._plugin_source(descriptor)
            native = self._native.get(descriptor.name)
            tools.append({
                "name": descriptor.name,
                "description": descriptor.description,
                "inputSchema": dict(descriptor.input_schema),
                "server_id": native.server_id if native is not None else 0,
                "server_name": source,
                "transport": (native.transport or "native") if native is not None else "plugin",
                "plugin_id": descriptor.plugin_id,
                "plugin_name": descriptor.plugin_name,
            })
        tools.sort(key=lambda item: (item["server_name"], item["name"]))
        return tools

    def descriptor(self, name: str) -> SdkToolDescriptor | None:
        return self._sdk.get(name) or next(
            (d for d in self._catalog.descriptors() if d.name == name), None
        )

    async def ensure_tool(self, name: str) -> SdkToolDescriptor | None:
        """按需解析并注册一个原生工具（远程 MCP 懒加载路径）。"""
        descriptor = self.descriptor(name)
        if descriptor is not None:
            return descriptor
        native = await self._registry.resolve(name)
        if native is not None and native.type != "plugin":
            self._register_native(native)
        return self.descriptor(name)

    def native_descriptor(self, name: str) -> BackendToolDescriptor | None:
        return self._native.get(name)

    def is_sandbox_tool(self, name: str) -> bool:
        native = self._native.get(name)
        if native is not None:
            return native.sandbox is not None
        descriptor = self.descriptor(name)
        return descriptor is not None and descriptor.executor == "sandbox"

    def source_label(self, name: str) -> str:
        return self._sources.get(name, "plugin")

    def execution_mode_of(self, name: str) -> str:
        native = self._native.get(name)
        if native is not None:
            return self._registry.execution_mode_of(name)
        mode = self._modes.get(name)
        if mode is not None:
            return mode
        descriptor = self.descriptor(name)
        return descriptor.execution_mode if descriptor is not None else "parallel"

    @property
    def native_runtime(self) -> ToolRuntime:
        return self._native_runtime

    @property
    def tools_service(self) -> ToolsService:
        return self._tools

    # ── 原生工具同步 ──

    def _on_native_change(
        self, name: str, descriptor: BackendToolDescriptor | None
    ) -> None:
        if not self._started:
            return
        if descriptor is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("无法注销原生工具 %s：没有运行中的事件循环", name)
                return
            task = loop.create_task(self._unregister_native(name))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
            return
        if descriptor.type != "plugin":
            self._register_native(descriptor)

    @staticmethod
    def _plugin_source(descriptor: SdkToolDescriptor) -> str:
        if descriptor.executor.startswith(("sandbox", "skill")):
            return "builtin"
        return "plugin"

    def _register_native(self, descriptor: BackendToolDescriptor) -> None:
        name = descriptor.name
        if name in self._registrations:
            return
        if name in self._plugin_owned:
            # A plugin already provides this tool name; never mirror it through
            # backend.native (single-track).
            return
        try:
            sdk = _native_to_sdk(descriptor)
        except ValidationError as exc:
            logger.warning("原生工具 %s 无法映射到 tools.v1: %s", name, exc)
            return
        try:
            registration = self._tools.register_tool(sdk)
        except RegistrationConflictError as exc:
            logger.warning("原生工具 %s 与插件工具重名，跳过原生注册: %s", name, exc)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("原生工具 %s 注册失败，跳过: %s", name, exc)
            return
        self._native[name] = descriptor
        self._sdk[name] = sdk
        self._registrations[name] = registration
        self._modes[name] = descriptor.execution_mode
        self._sources[name] = self._registry.source_label(descriptor)

    async def _unregister_native(self, name: str) -> None:
        registration = self._registrations.pop(name, None)
        if registration is not None:
            await registration.aclose()
        self._native.pop(name, None)
        self._sdk.pop(name, None)
        self._modes.pop(name, None)
        self._sources.pop(name, None)

# 单例状态放在不依赖插件 SDK 的模块里；回退路径可以安全地查询。
from .unified_state import (  # noqa: E402,F401
    close_unified_tools,
    get_unified_tools,
    get_unified_tools_optional,
    set_unified_tools,
)
