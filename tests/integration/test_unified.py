"""单轨工具运行时自检（不依赖 DB / 网络 / Docker）。

验证：插件工具与原生工具共用 tools-default 注册表；AgentLoop 入口只调用
UnifiedToolsRuntime.execute；原生上下文通过 host_context 透传；生命周期事件
只产生一次；动态注册/注销同步进单轨注册表。

Usage:
    python -m tests.integration.test_unified
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
# Unit tests must not connect to a real database or spawn MCP servers.
os.environ.setdefault("PLUGIN_MCP_AUTO", "false")
os.environ.setdefault("MANAGED_MCP_ENABLED", "false")

try:
    from agent_platform_plugin_runtime import MappingCatalog, PluginLoader
    from agent_platform_plugin_sdk import (
        DATABASE,
        SdkModel,
        TOOLS,
        ToolDescriptor as SdkToolDescriptor,
        ToolError,
        ToolResult,
    )
    from agent_platform_tools_default import ToolsDefaultPlugin, ToolsDefaultService
    from agent_platform_mcp_client import McpManagerPlugin
    from agent_platform_mcp_database import McpDatabasePlugin
    from agent_platform_plugin_inventory import PluginInventoryPlugin
    from agent_platform_skill_tools import SkillToolsPlugin
    from agent_platform_skills_default import SkillsDefaultPlugin
    from agent_platform_skills_filesystem import SkillsFilesystemPlugin
    from agent_platform_plugin_sdk import AGENT_EXTENSIONS
    from agent_platform_agent_runtime import AgentExtensionRegistry
    from agent_platform_llm_deepseek import DeepSeekProviderPlugin
    from agent_platform_agents import AgentsPlugin
    from agent_platform_agent_loop import AgentLoopPlugin
    from agent_platform_agent_runtime import AgentRuntimePlugin
    from agent_platform_agent_entry import AgentEntryPlugin
    from agent_platform_chat import ChatPlugin
    from agent_platform_memory import MemoryPlugin
    from agent_platform_user_approval import UserApprovalPlugin
    from agent_platform_session import SessionPlugin
    from agent_platform_session_persistence_postgres import PostgresPersistencePlugin
    from agent_platform_session_title import SessionTitlePlugin
    from agent_platform_session_recovery import SessionRecoveryPlugin
    from agent_platform_session_projection import SessionProjectionPlugin
    from agent_platform_database_postgres import PostgresDatabasePlugin
    from agent_platform_settings_postgres import PostgresSettingsPlugin
    from agent_platform_agent_config import AgentConfigPlugin
    from agent_platform_llm import LLMPlugin
    from agent_platform_tool_host import ToolHostPlugin
    from agent_platform_system_prompt import SystemPromptPlugin
    from agent_platform_sandbox_policy import SandboxPolicyPlugin
    from agent_platform_http_api import HttpApiPlugin
    from agent_platform_rpc_gateway import RpcGatewayPlugin
    from agent_platform_rpc_connection import RpcConnectionPlugin
    from agent_platform_api_workspace import WorkspaceControllerPlugin
    from agent_platform_api_agents import AgentApiPlugin
    from agent_platform_api_sessions import SessionApiPlugin
    from agent_platform_managed_mcp import BuiltinPlugin, PaperPlugin, OverleafPlugin, OverleafRtPlugin
    from agent_platform_workflow import WorkflowPlugin
    from agent_platform_faq import FaqPlugin
    from agent_platform_xianyu import XianyuPlugin
    from agent_platform_sandbox_tools import SandboxToolsPlugin
    from agent_platform_sandbox.plugin import LocalSandboxPlugin

    PLUGIN_STACK_AVAILABLE = True
except ImportError:  # pragma: no cover
    PLUGIN_STACK_AVAILABLE = False

from agent_platform_tool_system.context import ToolContext as BackendToolContext
from agent_platform_tool_system.events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED
from agent_platform_tool_system.descriptor import ToolDescriptor as BackendToolDescriptor
from agent_platform_tool_system.registry import ToolRegistry
from agent_platform_tool_system.runtime import ToolRuntime
from agent_platform_tool_host import (
    UnifiedToolsRuntime,
    close_unified_tools,
    set_unified_tools,
)
from minidsh_cordis import Plugin


def _skip() -> bool:
    if not PLUGIN_STACK_AVAILABLE:
        print("    (skip: plugin SDK/runtime/tools-default not installed)", end="")
        return True
    return False


def _sdk_descriptor(
    name: str = "echo",
    *,
    executor: str = "echo",
    execution_mode: str = "parallel",
    timeout: float | None = None,
):
    return SdkToolDescriptor(
        name=name,
        executor=executor,
        description="Echo a text argument",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        execution_mode=execution_mode,
        timeout_seconds=timeout,
    )


def _native_descriptor(
    name: str = "native_echo",
    *,
    type_: str = "fake_native",
    execution_mode: str = "parallel",
):
    return BackendToolDescriptor(
        name=name,
        type=type_,
        transport="",
        server_id=0,
        schema={
            "name": name,
            "description": "Native echo",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        },
        execution_mode=execution_mode,
    )


def _context(visible=("echo", "native_echo"), *, sink=None):
    return BackendToolContext(
        session_id="session-1",
        tool_call_id="call-1",
        agent_id="agent",
        tenant_id=1,
        visible_tool_names=None if visible is None else frozenset(visible),
        event_sink=sink,
    )


class _EchoExecutor:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.calls = 0
        self.contexts = []

    async def execute(self, descriptor, arguments, context):
        self.calls += 1
        self.contexts.append(context)
        if arguments.get("fail"):
            return ToolResult(
                status="error",
                error=ToolError(code="echo.failed", message="echo failed"),
            )
        return ToolResult(data={"text": self.prefix + str(arguments.get("text", ""))})


class _NativeExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts = []

    async def execute(self, descriptor, args, context=None):
        self.calls += 1
        self.contexts.append(context)
        if args.get("fail"):
            return {"error": "native failed", "code": "native.failed"}
        return {
            "native": args.get("text", ""),
            "tenant": context.tenant_id if context is not None else None,
        }


class _Sink:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class _LazyProvider:
    name = "lazy"

    async def discover(self):
        return []

    async def lazy_load(self, name):
        return _native_descriptor(name) if name == "lazy_native" else None


class _NoopDatabasePlugin:
    """Database provider that never touches a real server during composition tests."""

    spec = PostgresDatabasePlugin
    config_model = PostgresDatabasePlugin.config_model

    async def setup(self, ctx, config):
        class _Db:
            def get_conn(self):
                raise RuntimeError("database access is not expected in this test")

        ctx.provide(DATABASE, _Db())


class _Recorder:
    def record_call(self, *args, **kwargs):
        pass

    def record_result(self, *args, **kwargs):
        pass


async def _setup(*, plugin_mode: str = "parallel", providers=None):
    registry = ToolRegistry(providers=providers) if providers is not None else ToolRegistry()
    native_runtime = ToolRuntime(registry=registry)
    native_executor = _NativeExecutor()
    native_runtime.register_executor("fake_native", native_executor)
    registry.register_builtin(_native_descriptor())

    tools = ToolsDefaultService()
    plugin_executor = _EchoExecutor("p:")
    tools.register_executor("echo", plugin_executor)
    tools.register_tool(_sdk_descriptor("echo", execution_mode=plugin_mode))

    unified = UnifiedToolsRuntime(registry, native_runtime, tools, tools)
    await unified.start()
    return registry, native_runtime, tools, plugin_executor, native_executor, unified


async def _teardown(unified, tools):
    await unified.aclose()
    await tools.aclose()


# ── 单轨注册与执行 ──


def test_plugin_and_native_tools_share_one_registry():
    if _skip():
        return

    async def case():
        registry, _runtime, tools, plugin_exec, native_exec, unified = await _setup()
        assert tools.has_tool("echo")
        assert tools.has_tool("native_echo")

        context = _context()
        assert await unified.execute("echo", {"text": "x"}, context) == {"text": "p:x"}
        assert await unified.execute("native_echo", {"text": "n"}, context) == {
            "native": "n", "tenant": 1
        }
        assert plugin_exec.contexts[0].host_context is context
        assert native_exec.contexts[0] is context
        await _teardown(unified, tools)

    asyncio.run(case())


def test_visibility_and_untrusted_context_are_denied():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, plugin_exec, _native, unified = await _setup()
        denied = await unified.execute("echo", {"text": "x"}, _context(visible=()))
        assert denied["code"] == "tool.denied", denied
        assert plugin_exec.calls == 0

        bad = BackendToolContext(
            tenant_id=None,
            agent_id="agent",
            visible_tool_names=frozenset({"echo"}),
        )
        denied = await unified.execute("echo", {"text": "x"}, bad)
        assert denied["code"] == "tool.denied"
        await _teardown(unified, tools)

    asyncio.run(case())


class _TypedExecutor:
    def __init__(self, type_: str) -> None:
        self.type = type_
        self.calls = 0

    async def execute(self, descriptor, args, context=None):
        self.calls += 1
        return {"type": self.type, "name": descriptor.name}


def test_mcp_sandbox_skill_dispatch_through_backend_native():
    if _skip():
        return

    async def case():
        registry = ToolRegistry(providers=[])
        native_runtime = ToolRuntime(registry=registry, executors={})
        executors = {}
        for type_ in ("mcp", "sandbox", "skill"):
            executor = _TypedExecutor(type_)
            executors[type_] = executor
            native_runtime.register_executor(type_, executor)
        for type_ in ("mcp", "sandbox", "skill"):
            registry.register_builtin(
                _native_descriptor(f"{type_}_tool", type_=type_)
            )

        tools = ToolsDefaultService()
        unified = UnifiedToolsRuntime(registry, native_runtime, tools, tools)
        await unified.start()
        for type_ in ("mcp", "sandbox", "skill"):
            name = f"{type_}_tool"
            assert tools.has_tool(name)
            result = await unified.execute(
                name, {"text": "x"}, _context(visible=(name,))
            )
            assert result == {"type": type_, "name": name}, result
            assert executors[type_].calls == 1
        await _teardown(unified, tools)

    asyncio.run(case())


def test_plugin_owned_mcp_tool_shadows_the_native_registration():
    if _skip():
        return

    async def case():
        registry = ToolRegistry(providers=[])
        native_runtime = ToolRuntime(
            registry=registry, executors={"mcp": _TypedExecutor("mcp")}
        )
        registry.register_builtin(_native_descriptor("search", type_="mcp"))
        tools = ToolsDefaultService()
        tools.register_executor("echo", _EchoExecutor("plugin:"))
        tools.register_tool(_sdk_descriptor("search", executor="echo"))
        unified = UnifiedToolsRuntime(registry, native_runtime, tools, tools)
        await unified.start()
        assert unified.native_descriptor("search") is None
        result = await unified.execute(
            "search", {"text": "x"}, _context(visible=("search",))
        )
        assert result == {"text": "plugin:x"}, result
        await _teardown(unified, tools)

    asyncio.run(case())


def test_safe_name_is_restored_for_visibility():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        tools.register_executor("dotted", _EchoExecutor())
        tools.register_tool(_sdk_descriptor("tool.with.dot", executor="dotted"))
        result = await unified.execute(
            "tool.with.dot",
            {"text": "x"},
            _context(visible=("tool_with_dot",)),
        )
        assert result == {"text": "x"}, result
        await _teardown(unified, tools)

    asyncio.run(case())


def test_lifecycle_events_are_emitted_once():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        sink = _Sink()
        await unified.execute("echo", {"text": "x"}, _context(sink=sink))
        assert [event.type for event in sink.events] == [TOOL_STARTED, TOOL_COMPLETED]

        sink.events.clear()
        await unified.execute("echo", {"fail": True}, _context(sink=sink))
        assert [event.type for event in sink.events] == [TOOL_STARTED, TOOL_FAILED]
        await _teardown(unified, tools)

    asyncio.run(case())


def test_native_error_result_is_mapped():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        result = await unified.execute("native_echo", {"fail": True}, _context())
        assert result["error"] == "native failed"
        assert result["code"] == "native.failed"
        await _teardown(unified, tools)

    asyncio.run(case())


# ── 动态同步与查询 ──


def test_dynamic_native_registration_is_synchronized():
    if _skip():
        return

    async def case():
        registry, _runtime, tools, _plugin, _native, unified = await _setup()
        registry.register_builtin(_native_descriptor("late"))
        await asyncio.sleep(0)
        assert tools.has_tool("late")
        assert await unified.execute("late", {"text": "x"}, _context(visible=("late",))) == {
            "native": "x", "tenant": 1
        }

        registry.unregister_builtin(["late"])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not tools.has_tool("late")
        await _teardown(unified, tools)

    asyncio.run(case())


def test_bound_native_tool_is_lazily_resolved_and_registered():
    if _skip():
        return

    async def case():
        registry, _runtime, tools, _plugin, _native, unified = await _setup(
            providers=[_LazyProvider()]
        )
        original = ToolRegistry.get_bindings
        ToolRegistry.get_bindings = staticmethod(lambda key: ["lazy_native"])
        try:
            descriptors = await unified.descriptors_for_agent(1, "agent")
        finally:
            ToolRegistry.get_bindings = original
        assert [d.name for d in descriptors] == ["lazy_native"]
        assert tools.has_tool("lazy_native")
        await _teardown(unified, tools)

    asyncio.run(case())


def test_descriptors_for_agent_filters_bindings_and_reports_source():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        original = ToolRegistry.get_bindings
        ToolRegistry.get_bindings = staticmethod(lambda key: ["echo", "native_echo"])
        try:
            descriptors = await unified.descriptors_for_agent(1, "agent")
        finally:
            ToolRegistry.get_bindings = original
        sources = {d.name: d.source for d in descriptors}
        assert sources == {"echo": "plugin", "native_echo": "builtin"}, sources
        await _teardown(unified, tools)

    asyncio.run(case())


def test_execution_mode_comes_from_the_single_registry():
    if _skip():
        return

    async def case():
        registry, native_runtime, tools, _plugin, _native, unified = await _setup(
            plugin_mode="exclusive"
        )
        registry.register_builtin(_native_descriptor("native_exclusive", execution_mode="exclusive"))
        await asyncio.sleep(0)
        assert unified.execution_mode_of("echo") == "exclusive"
        assert unified.execution_mode_of("native_exclusive") == "exclusive"
        assert unified.execution_mode_of("unknown") == "parallel"
        await _teardown(unified, tools)

    asyncio.run(case())


def test_close_removes_native_tools_but_leaves_plugin_registry_open():
    if _skip():
        return

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        await unified.aclose()
        assert not tools.has_tool("native_echo")
        assert tools.has_tool("echo")
        assert (await unified.execute("echo", {"text": "x"}, _context()))["code"] == "tool.unavailable"
        await tools.aclose()

    asyncio.run(case())


def test_scheduler_prefers_unified_runtime_and_mode():
    if _skip():
        return

    from agent_platform_tool_host.scheduler import (
        _registry_mode_resolver,
        ToolScheduler,
    )

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup(
            plugin_mode="exclusive"
        )
        set_unified_tools(unified)
        try:
            assert _registry_mode_resolver("echo") == "exclusive"
            scheduler = ToolScheduler(
                recorder=_Recorder(),
                context_factory=lambda call_id: _context(),
            )
            assert scheduler._runtime_or_default() is unified
        finally:
            await close_unified_tools()
        await tools.aclose()

    asyncio.run(case())


def test_system_prompt_provider_reads_the_unified_registry():
    if _skip():
        return

    from agent_platform_system_prompt import AssembleContext
    from agent_platform_system_prompt.platform_sections import unified_tool_provider

    async def case():
        _registry, _runtime, tools, _plugin, _native, unified = await _setup()
        original = ToolRegistry.get_bindings
        ToolRegistry.get_bindings = staticmethod(lambda key: ["echo", "native_echo"])
        try:
            result = await unified_tool_provider(unified)(
                AssembleContext(tenant_id=1, agent_key="agent")
            )
        finally:
            ToolRegistry.get_bindings = original
            await _teardown(unified, tools)
        assert [schema.name for schema in result.schemas] == ["echo", "native_echo"]
        native = next(s for s in result.schemas if s.name == "native_echo")
        assert native.function["description"] == "Native echo"

    asyncio.run(case())


def test_default_plugins_expose_skill_and_sandbox_tools():
    if _skip():
        return

    from agent_platform_plugin_sdk import (
        AGENTS,
        APPROVAL,
        ExecutionScope,
        SETTINGS,
    )
    from agent_platform_plugin_runtime import PluginConfiguration
    from agent_platform_sandbox_tools import get_sandbox_control

    class Settings:
        def __init__(self):
            self.values = {}

        async def get(self, namespace):
            return dict(self.values.get(namespace, {}))

        async def set(self, namespace, value):
            self.values[namespace] = value

    class Agents:
        async def get_config(self, agent_key):
            return {}

    class Approval:
        available = False

        async def request(self, req):
            return "unavailable"

    async def case():
        config = PluginConfiguration(
            plugins=[
                {"id": "tools", "name": "agent-platform.tools-default", "config": {}},
                {"id": "skill-tools", "name": "agent-platform.skill-tools", "config": {}},
                {"id": "skills", "name": "agent-platform.skills-default"},
                {"id": "filesystem", "name": "agent-platform.skills-filesystem"},
                {"id": "sandbox", "name": "agent-platform.sandbox-tools", "config": {}},
                {"id": "sandbox-provider", "name": "agent-platform.sandbox-local"},
            ]
        )
        runtime = PluginLoader(
            config,
            catalog=MappingCatalog(
                {
                    "agent-platform.tools-default": ToolsDefaultPlugin,
                    "agent-platform.skill-tools": SkillToolsPlugin,
                    "agent-platform.skills-default": SkillsDefaultPlugin,
                    "agent-platform.skills-filesystem": SkillsFilesystemPlugin,
                    "agent-platform.llm-deepseek": DeepSeekProviderPlugin,
                    "agent-platform.agents": AgentsPlugin,
                    "agent-platform.agent-loop": AgentLoopPlugin,
                    "agent-platform.agent-runtime": AgentRuntimePlugin,
                    "agent-platform.sandbox-tools": SandboxToolsPlugin,
                    "agent-platform.sandbox-local": LocalSandboxPlugin,
                    'agent-platform.builtin-mcp': BuiltinPlugin,
                    'agent-platform.paper-mcp': PaperPlugin,
                    'agent-platform.overleaf-mcp': OverleafPlugin,
                    'agent-platform.overleaf-rt-mcp': OverleafRtPlugin,
                    'agent-platform.workflow': WorkflowPlugin,
                    'agent-platform.faq': FaqPlugin,
                    'agent-platform.xianyu': XianyuPlugin,
                    'agent-platform.plugin-inventory': PluginInventoryPlugin,
                }
            ),
            host_services={
                AGENTS: Agents(),
                AGENT_EXTENSIONS: AgentExtensionRegistry(),
                SETTINGS: Settings(),
                APPROVAL: Approval(),
            },
        )
        await runtime.start()
        try:
            tools = runtime.require(TOOLS)
            scope = ExecutionScope(tenant_id=1, agent_key="a")
            names = {d.name for d in await tools.list_for_agent(scope)}
            assert names == ({"bash", "python", "skill", "skill_install", "powershell"} if os.name == "nt" else {"bash", "python", "skill", "skill_install"}), names

            control = get_sandbox_control()
            assert control is not None
            await control.set_enabled(False)
            names = {d.name for d in await tools.list_for_agent(scope)}
            assert names == {"skill", "skill_install"}, names
            await control.set_enabled(True)
            names = {d.name for d in await tools.list_for_agent(scope)}
            assert names == ({"bash", "python", "skill", "skill_install", "powershell"} if os.name == "nt" else {"bash", "python", "skill", "skill_install"}), names
        finally:
            await runtime.aclose()

    asyncio.run(case())


# ── 后端宿主接线 ──


def _consumer_plugin(calls: list):
    class ConsumerConfig(SdkModel):
        pass

    class Consumer(Plugin[ConsumerConfig]):
        name = "test.consumer"
        version = "0.1.0"
        requires = (TOOLS,)
        config_model = ConsumerConfig

        async def setup(self, ctx, config):
            tools = ctx.require(TOOLS)
            executor = _EchoExecutor("h:")
            calls.append(executor)
            ctx.track(tools.register_executor("echo", executor))
            ctx.track(tools.register_tool(_sdk_descriptor("echo")))

    return Consumer


def test_plugin_host_always_assembles_tools_default_and_unified_runtime():
    if _skip():
        return

    import agent_platform_app_boot as plugin_host
    async def case():
        await plugin_host.close_plugin_host()
        old_config = os.environ.get("PLUGIN_CONFIG")
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "plugins.yaml"
                # 故意不写 tools-default：宿主应自动补上，保证单轨。
                path.write_text(
                    "version: 1\n"
                    "plugins:\n"
                    "  - id: consumer\n"
                    "    name: test.consumer\n",
                    encoding="utf-8",
                )
                os.environ["PLUGIN_CONFIG"] = str(path)
                calls = []
                host = await plugin_host.init_plugin_host(
                    catalog=MappingCatalog(
                        {
                            "agent-platform.tools-default": ToolsDefaultPlugin,
                            "agent-platform.database-postgres": _NoopDatabasePlugin,
                            "agent-platform.settings-postgres": PostgresSettingsPlugin,
                            "agent-platform.agent-config": AgentConfigPlugin,
                            "agent-platform.llm": LLMPlugin,
                            "agent-platform.tool-host": ToolHostPlugin,
                            "agent-platform.system-prompt": SystemPromptPlugin,
                            "agent-platform.sandbox-policy": SandboxPolicyPlugin,
                            "agent-platform.rpc-gateway": RpcGatewayPlugin,
                            "agent-platform.rpc-connection": RpcConnectionPlugin,
                            "agent-platform.api-workspace": WorkspaceControllerPlugin,
                            "agent-platform.api-agents": AgentApiPlugin,
                            "agent-platform.api-sessions": SessionApiPlugin,
                            "agent-platform.http-api": HttpApiPlugin,
                            "agent-platform.mcp-manager": McpManagerPlugin,
                            "agent-platform.mcp-database": McpDatabasePlugin,
                            "agent-platform.session": SessionPlugin,
                            "agent-platform.session-persistence-postgres": PostgresPersistencePlugin,
                            "agent-platform.session-title": SessionTitlePlugin,
                            "agent-platform.session-recovery": SessionRecoveryPlugin,
                            "agent-platform.session-projection": SessionProjectionPlugin,
                            "agent-platform.skill-tools": SkillToolsPlugin,
                            "agent-platform.skills-default": SkillsDefaultPlugin,
                            "agent-platform.skills-filesystem": SkillsFilesystemPlugin,
                            "agent-platform.llm-deepseek": DeepSeekProviderPlugin,
                            "agent-platform.agents": AgentsPlugin,
                            "agent-platform.agent-loop": AgentLoopPlugin,
                            "agent-platform.agent-runtime": AgentRuntimePlugin,
                            "agent-platform.agent-entry": AgentEntryPlugin,
                            "agent-platform.chat": ChatPlugin,
                            "agent-platform.memory": MemoryPlugin,
                            "agent-platform.user-approval": UserApprovalPlugin,
                            "agent-platform.sandbox-tools": SandboxToolsPlugin,
                            "agent-platform.sandbox-local": LocalSandboxPlugin,
                            'agent-platform.builtin-mcp': BuiltinPlugin,
                            'agent-platform.paper-mcp': PaperPlugin,
                            'agent-platform.overleaf-mcp': OverleafPlugin,
                            'agent-platform.overleaf-rt-mcp': OverleafRtPlugin,
                            'agent-platform.workflow': WorkflowPlugin,
                    'agent-platform.faq': FaqPlugin,
                    'agent-platform.xianyu': XianyuPlugin,
                    'agent-platform.plugin-inventory': PluginInventoryPlugin,
                            "test.consumer": _consumer_plugin(calls),
                        }
                    )
                )
                assert host is not None
                unified = host.unified
                assert unified is not None
                result = await unified.execute("echo", {"text": "x"}, _context())
                assert result == {"text": "h:x"}

                await plugin_host.close_plugin_host()
                assert plugin_host.get_plugin_host() is None
        finally:
            await plugin_host.close_plugin_host()
            if old_config is None:
                os.environ.pop("PLUGIN_CONFIG", None)
            else:
                os.environ["PLUGIN_CONFIG"] = old_config

    asyncio.run(case())


def test_plugin_host_starts_without_plugin_config():
    if _skip():
        return

    import agent_platform_app_boot as plugin_host
    async def case():
        await plugin_host.close_plugin_host()
        old_config = os.environ.pop("PLUGIN_CONFIG", None)
        try:
            host = await plugin_host.init_plugin_host(
                catalog=MappingCatalog(
                    {
                        "agent-platform.tools-default": ToolsDefaultPlugin,
                        "agent-platform.database-postgres": _NoopDatabasePlugin,
                        "agent-platform.settings-postgres": PostgresSettingsPlugin,
                        "agent-platform.agent-config": AgentConfigPlugin,
                        "agent-platform.llm": LLMPlugin,
                        "agent-platform.tool-host": ToolHostPlugin,
                        "agent-platform.system-prompt": SystemPromptPlugin,
                        "agent-platform.sandbox-policy": SandboxPolicyPlugin,
                        "agent-platform.rpc-gateway": RpcGatewayPlugin,
                        "agent-platform.rpc-connection": RpcConnectionPlugin,
                        "agent-platform.api-workspace": WorkspaceControllerPlugin,
                        "agent-platform.api-agents": AgentApiPlugin,
                        "agent-platform.api-sessions": SessionApiPlugin,
                        "agent-platform.http-api": HttpApiPlugin,
                        "agent-platform.mcp-manager": McpManagerPlugin,
                        "agent-platform.mcp-database": McpDatabasePlugin,
                        "agent-platform.session": SessionPlugin,
                        "agent-platform.session-persistence-postgres": PostgresPersistencePlugin,
                        "agent-platform.session-title": SessionTitlePlugin,
                        "agent-platform.session-recovery": SessionRecoveryPlugin,
                        "agent-platform.session-projection": SessionProjectionPlugin,
                        "agent-platform.skill-tools": SkillToolsPlugin,
                        "agent-platform.skills-default": SkillsDefaultPlugin,
                        "agent-platform.skills-filesystem": SkillsFilesystemPlugin,
                        "agent-platform.llm-deepseek": DeepSeekProviderPlugin,
                        "agent-platform.agents": AgentsPlugin,
                        "agent-platform.agent-loop": AgentLoopPlugin,
                        "agent-platform.agent-runtime": AgentRuntimePlugin,
                        "agent-platform.agent-entry": AgentEntryPlugin,
                        "agent-platform.chat": ChatPlugin,
                        "agent-platform.memory": MemoryPlugin,
                        "agent-platform.user-approval": UserApprovalPlugin,
                        "agent-platform.sandbox-tools": SandboxToolsPlugin,
                        "agent-platform.sandbox-local": LocalSandboxPlugin,
                        'agent-platform.builtin-mcp': BuiltinPlugin,
                        'agent-platform.paper-mcp': PaperPlugin,
                        'agent-platform.overleaf-mcp': OverleafPlugin,
                        'agent-platform.overleaf-rt-mcp': OverleafRtPlugin,
                        'agent-platform.workflow': WorkflowPlugin,
                    'agent-platform.faq': FaqPlugin,
                    'agent-platform.xianyu': XianyuPlugin,
                    'agent-platform.plugin-inventory': PluginInventoryPlugin,
                    }
                )
            )
            assert host is not None
            assert host.unified is not None

            # The HTTP plugin reads the host-bound catalog; the endpoint is the
            # single source the frontend uses to filter its bundles.
            from fastapi.testclient import TestClient
            from agent_platform_http_api import HTTP_APP

            response = TestClient(host.runtime.require(HTTP_APP)).get("/api/plugins")
            assert response.status_code == 200
            names = {item["name"] for item in response.json()["plugins"]}
            assert {"agent-platform.workflow", "agent-platform.http-api"} <= names

            await plugin_host.close_plugin_host()
            assert plugin_host.get_plugin_host() is None
        finally:
            await plugin_host.close_plugin_host()
            if old_config is not None:
                os.environ["PLUGIN_CONFIG"] = old_config

    asyncio.run(case())


# ── 运行器 ──


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        print(f"  {name} ...", end="", flush=True)
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"\r  FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"\r  OK   {name}")
    print()
    if failed:
        print(f"{failed}/{len(tests)} failed")
        return 1
    print(f"all passed ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
