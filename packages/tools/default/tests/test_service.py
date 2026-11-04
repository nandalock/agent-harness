import asyncio
import time
import unittest

from agent_platform_plugin_sdk import (
    ExecutionScope,
    PluginSpec,
    RegistrationConflictError,
    SdkModel,
    ServiceRequirement,
    TOOLS,
    ToolCall,
    ToolContext,
    ToolDescriptor,
    ToolError,
    ToolResult,
    TOOL_DENIED,
    TOOL_TIMEOUT,
    TOOL_UNAVAILABLE,
)
from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_tools_default import (
    TOOL_CATALOG,
    ToolsDefaultPlugin,
    ToolsDefaultService,
)


def scope() -> ExecutionScope:
    return ExecutionScope(tenant_id=1, agent_key="agent", session_id="s")


def context(visible=("echo",), *, deadline: float | None = None) -> ToolContext:
    return ToolContext(
        scope=scope(),
        visible_tool_names=frozenset(visible),
        deadline=deadline,
    )


def descriptor(name: str = "echo", *, executor: str = "echo", timeout: float | None = None):
    return ToolDescriptor(
        name=name,
        executor=executor,
        description="Echo a text argument",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        timeout_seconds=timeout,
    )


class EchoExecutor:
    def __init__(self, prefix: str = "", delay: float = 0.0) -> None:
        self.prefix = prefix
        self.delay = delay
        self.calls = 0

    async def execute(self, descriptor, arguments, context):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if arguments.get("fail"):
            return ToolResult(
                status="error",
                error=ToolError(code="echo.failed", message="echo failed"),
            )
        return ToolResult(data={"text": self.prefix + str(arguments.get("text", ""))})


class DiscoveryProvider:
    name = "fixture"

    async def discover(self, scope):
        return [descriptor("discovered")]

    async def lazy_load(self, name, scope):
        return descriptor("lazy") if name == "lazy" else None


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_lists_only_directly_registered_tools(self):
        service = ToolsDefaultService()
        service.register_executor("echo", EchoExecutor())
        service.register_tool(descriptor("echo"))
        service.register_provider(DiscoveryProvider())

        self.assertTrue(service.has_tool("echo"))
        self.assertFalse(service.has_tool("discovered"))
        self.assertEqual([d.name for d in service.descriptors()], ["echo"])
        names = [d.name for d in await service.list_for_agent(scope())]
        self.assertEqual(set(names), {"echo", "discovered"})
        await service.aclose()

    async def test_provider_lazy_load_is_executable(self):
        service = ToolsDefaultService()
        executor = EchoExecutor("p:")
        service.register_executor("echo", executor)
        service.register_provider(DiscoveryProvider())

        result = await service.execute(
            ToolCall(call_id="1", name="lazy", arguments={"text": "x"}),
            context(visible=("lazy",)),
        )
        self.assertEqual(result.data, {"text": "p:x"})
        self.assertEqual(executor.calls, 1)
        await service.aclose()

    async def test_visibility_deadline_error_and_timeout(self):
        service = ToolsDefaultService()
        executor = EchoExecutor(delay=0.2)
        service.register_executor("echo", executor)
        service.register_tool(descriptor("echo", timeout=0.02))
        call = ToolCall(call_id="1", name="echo", arguments={"text": "x"})

        denied = await service.execute(call, context(visible=()))
        self.assertEqual(denied.error.code, TOOL_DENIED)
        self.assertEqual(executor.calls, 0)

        expired = await service.execute(
            call, context(deadline=time.monotonic() - 0.001)
        )
        self.assertEqual(expired.error.code, TOOL_TIMEOUT)
        self.assertEqual(executor.calls, 0)

        timed_out = await service.execute(call, context())
        self.assertEqual(timed_out.error.code, TOOL_TIMEOUT)
        self.assertEqual(executor.calls, 1)

        failing = ToolsDefaultService()
        failing.register_executor("boom", _RaisingExecutor())
        failing.register_tool(descriptor("boom", executor="boom"))
        result = await failing.execute(call.model_copy(update={"name": "boom"}), context(visible=("boom",)))
        self.assertEqual(result.error.code, TOOL_UNAVAILABLE)
        await failing.aclose()
        await service.aclose()

    async def test_stale_registration_and_duplicates(self):
        service = ToolsDefaultService()
        first = service.register_tool(descriptor("echo"))
        with self.assertRaises(RegistrationConflictError):
            service.register_tool(descriptor("echo"))
        await first.aclose()
        second = service.register_tool(descriptor("echo"))
        await first.aclose()
        self.assertTrue(service.has_tool("echo"))
        service.register_executor("echo", EchoExecutor())
        with self.assertRaises(RegistrationConflictError):
            service.register_executor("echo", EchoExecutor())
        await second.aclose()
        await service.aclose()

    async def test_plugin_runtime_orders_default_before_consumer_and_cleans_up(self):
        class ConsumerConfig(SdkModel):
            pass

        class Consumer:
            spec = PluginSpec(
                name="test.consumer",
                version="0.1.0",
                requires=(ServiceRequirement(service=TOOLS.ref),),
            )
            config_model = ConsumerConfig

            async def setup(self, ctx, config):
                tools = ctx.require(TOOLS)
                ctx.track(tools.register_executor("echo", EchoExecutor("c:")))
                ctx.track(tools.register_tool(descriptor("echo")))

        runtime = PluginRuntime(
            {
                "version": 1,
                "plugins": [
                    {"id": "consumer", "name": "test.consumer"},
                    {"id": "tools", "name": "agent-platform.tools-default"},
                ],
            },
            catalog=MappingCatalog(
                {
                    "agent-platform.tools-default": ToolsDefaultPlugin,
                    "test.consumer": Consumer,
                }
            ),
        )
        await runtime.start()
        tools = runtime.require(TOOLS)
        catalog = runtime.require(TOOL_CATALOG)
        self.assertTrue(catalog.has_tool("echo"))
        result = await tools.execute(
            ToolCall(call_id="1", name="echo", arguments={"text": "x"}),
            context(),
        )
        self.assertEqual(result.data, {"text": "c:x"})

        await runtime.aclose()
        await runtime.aclose()


class _RaisingExecutor:
    async def execute(self, descriptor, arguments, context):
        raise RuntimeError("boom")


if __name__ == "__main__":
    unittest.main()
