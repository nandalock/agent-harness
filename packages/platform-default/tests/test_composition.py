import unittest

from agent_platform_default import compose
from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import (
    ExecutionScope, PluginConfiguration, PluginSpec, RegistrationConflictError,
    SdkModel, ServiceKey, ServiceRef, ServiceRequirement, TOOLS,
    ToolCall, ToolContext, ToolDescriptor, ToolResult,
)
from agent_platform_tools_default import ToolsDefaultService


PREFIX = ServiceKey[str](ServiceRef(name="example.prefix"))


class EmptyConfig(SdkModel):
    pass


class PrefixPlugin:
    """A service-only package: no tools and no dependency on tools.v1."""
    spec = PluginSpec(name="example.prefix", version="0.1.0", provides=(PREFIX.ref,))
    config_model = EmptyConfig

    async def setup(self, ctx, config):
        ctx.provide(PREFIX, "package:")


class TextExecutor:
    def __init__(self, prefix):
        self.prefix = prefix

    async def execute(self, descriptor, arguments, context):
        text = arguments["text"]
        output = text.upper() if descriptor.name.endswith("upper") else text.lower()
        return ToolResult(data=self.prefix + output)


class TextPlugin:
    """One feature package, one executor, two tools per configured instance."""
    spec = PluginSpec(
        name="example.text", version="0.1.0",
        requires=(ServiceRequirement(service=TOOLS.ref), ServiceRequirement(service=PREFIX.ref)),
    )
    config_model = EmptyConfig

    async def setup(self, ctx, config):
        tools = ctx.require(TOOLS)
        executor = ctx.instance_id + ".text"
        ctx.track(tools.register_executor(executor, TextExecutor(ctx.require(PREFIX))))
        for operation in ("upper", "lower"):
            ctx.track(tools.register_tool(ToolDescriptor(
                name=ctx.instance_id + "." + operation,
                executor=executor,
                description="Transform text",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            )))


class CompositionTests(unittest.TestCase):
    def test_default_packages_and_explicit_disable(self):
        config = compose(PluginConfiguration())
        self.assertEqual(len(config.plugins), 4)
        override = PluginConfiguration.model_validate({"plugins": [
            {"id": "custom-tools", "name": "agent-platform.tools-default", "disabled": True},
            {"id": "sandbox-tools", "name": "example.replacement"},
        ]})
        result = compose(override)
        self.assertEqual(result.plugins[:2], override.plugins)
        self.assertNotIn("agent-platform.sandbox-tools", [p.name for p in result.plugins])
        self.assertEqual(sum(p.name == "agent-platform.tools-default" for p in result.plugins), 1)


class PackageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_plugin_runs_without_any_tool_service(self):
        runtime = PluginRuntime({"plugins": [
            {"id": "prefix", "name": "example.prefix"},
        ]}, catalog=MappingCatalog({"example.prefix": PrefixPlugin}))
        try:
            await runtime.start()
            self.assertEqual(runtime.require(PREFIX), "package:")
        finally:
            await runtime.aclose()

    async def test_zero_tool_service_and_multiple_multi_tool_instances(self):
        tools = ToolsDefaultService()
        scope = ExecutionScope(tenant_id=1, agent_key="test")
        runtime = PluginRuntime({"plugins": [
            {"id": "first", "name": "example.text"},
            {"id": "second", "name": "example.text"},
            {"id": "prefix", "name": "example.prefix"},
        ]}, catalog=MappingCatalog({"example.text": TextPlugin, "example.prefix": PrefixPlugin}),
            host_services={TOOLS: tools})
        try:
            await runtime.start()
            names = frozenset(d.name for d in await tools.list_for_agent(scope))
            self.assertEqual(names, {"first.upper", "first.lower", "second.upper", "second.lower"})
            for name in names:
                result = await tools.execute(ToolCall(call_id=name, name=name, arguments={"text": "Ab"}),
                    ToolContext(scope=scope, visible_tool_names=names))
                self.assertEqual(result.data, "package:" + ("AB" if name.endswith("upper") else "ab"))
            self.assertEqual(len(runtime.plugins), 3)
            await runtime.aclose()
            self.assertEqual(tuple(await tools.list_for_agent(scope)), ())
            # Executors and all tools are released together with their owner.
            registration = tools.register_executor("first.text", TextExecutor(""))
            await registration.aclose()
        finally:
            await runtime.aclose()
            await tools.aclose()

    async def test_partial_multi_tool_setup_rolls_back_the_whole_package(self):
        tools = ToolsDefaultService()
        scope = ExecutionScope(tenant_id=1, agent_key="test")
        existing = tools.register_tool(ToolDescriptor(
            name="first.lower", executor="external", description="Pre-existing tool"))
        runtime = PluginRuntime({"plugins": [
            {"id": "first", "name": "example.text"},
            {"id": "prefix", "name": "example.prefix"},
        ]}, catalog=MappingCatalog({"example.text": TextPlugin, "example.prefix": PrefixPlugin}),
            host_services={TOOLS: tools})
        try:
            with self.assertRaises(RegistrationConflictError):
                await runtime.start()
            self.assertEqual([d.name for d in await tools.list_for_agent(scope)], ["first.lower"])
            registration = tools.register_executor("first.text", TextExecutor(""))
            await registration.aclose()
        finally:
            await runtime.aclose()
            await existing.aclose()
            await tools.aclose()


if __name__ == "__main__":
    unittest.main()
