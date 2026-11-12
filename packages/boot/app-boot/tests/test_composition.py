import unittest

from agent_platform_app_boot import create_runtime
from agent_platform_app_boot.bundles import compose, read_bundle
from minidsh_cordis_plugin_loader import PLUGIN_CATALOG, MappingCatalog, Loader
from agent_platform_plugin_sdk import (
    ExecutionScope, RegistrationConflictError,
    SdkModel, ServiceKey, TOOLS,
    ToolCall, ToolContext, ToolDescriptor, ToolResult,
)
from minidsh_cordis_plugin_include import PluginConfiguration
from agent_platform_tools_default import ToolsDefaultService
from minidsh_cordis import Plugin


PREFIX = ServiceKey[str]("example.prefix")


class EmptyConfig(SdkModel):
    pass


class PrefixPlugin(Plugin[EmptyConfig]):
    """A service-only package: no tools and no dependency on tools.v1."""
    name = "example.prefix"
    version = "0.1.0"
    provides = (PREFIX,)
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


class TextPlugin(Plugin[EmptyConfig]):
    """One feature package, one executor, two tools per configured instance."""
    name = "example.text"
    version = "0.1.0"
    requires = (TOOLS, PREFIX)
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
    def test_installed_bundle_resources_keep_web_plugins_in_the_web_layer(self):
        base = read_bundle("agent_platform_bundle_base")
        web = read_bundle("agent_platform_bundle_web_app")
        self.assertEqual(len(base.plugins), 35)
        self.assertEqual(len(web.plugins), 7)
        self.assertTrue(all(row.group == "web" for row in web.plugins))
        self.assertFalse({row.id for row in base.plugins} & {row.id for row in web.plugins})

    def test_docker_can_replace_the_default_native_service(self):
        config = compose(PluginConfiguration(), sandbox_backend="docker")
        names = {entry.name for entry in config.plugins}
        self.assertIn("agent-platform.sandbox-docker", names)
        self.assertNotIn("agent-platform.sandbox-local", names)

    def test_default_packages_and_explicit_disable(self):
        config = compose(PluginConfiguration())
        self.assertEqual(len(config.plugins), 42)
        self.assertIn("agent-platform.memory", {p.name for p in config.plugins})
        self.assertIn("agent-platform.workflow", {p.name for p in config.plugins})
        self.assertIn("agent-platform.faq", {p.name for p in config.plugins})
        self.assertIn("agent-platform.xianyu", {p.name for p in config.plugins})
        self.assertIn("agent-platform.mcp-database", {p.name for p in config.plugins})
        self.assertIn("agent-platform.plugin-inventory", {p.name for p in config.plugins})
        self.assertTrue({"agent-platform.agent-entry", "agent-platform.chat", "agent-platform.user-approval"}
                        <= {entry.name for entry in config.plugins})
        self.assertIn("agent-platform.agent-runtime", {p.name for p in config.plugins})
        self.assertIn("agent-platform.database-postgres", {p.name for p in config.plugins})
        self.assertIn("agent-platform.agent-config", {p.name for p in config.plugins})
        self.assertIn("agent-platform.llm", {p.name for p in config.plugins})
        self.assertIn("agent-platform.tool-host", {p.name for p in config.plugins})
        self.assertIn("agent-platform.system-prompt", {p.name for p in config.plugins})
        self.assertIn("agent-platform.sandbox-policy", {p.name for p in config.plugins})
        self.assertIn("agent-platform.http-api", {p.name for p in config.plugins})
        self.assertIn("agent-platform.rpc-gateway", {p.name for p in config.plugins})
        self.assertIn("agent-platform.rpc-connection", {p.name for p in config.plugins})
        self.assertIn("agent-platform.api-workspace", {p.name for p in config.plugins})
        self.assertIn("agent-platform.api-agents", {p.name for p in config.plugins})
        self.assertIn("agent-platform.api-sessions", {p.name for p in config.plugins})
        self.assertIn("agent-platform.session", {p.name for p in config.plugins})
        self.assertIn("agent-platform.session-persistence-postgres", {p.name for p in config.plugins})
        self.assertIn("agent-platform.session-title", {p.name for p in config.plugins})
        self.assertIn("agent-platform.session-recovery", {p.name for p in config.plugins})
        self.assertIn("agent-platform.session-projection", {p.name for p in config.plugins})
        self.assertIn("agent-platform.llm-deepseek", {p.name for p in config.plugins})
        override = PluginConfiguration.model_validate({"plugins": [
            {"id": "custom-tools", "name": "agent-platform.tools-default", "disabled": True},
            {"id": "sandbox-tools", "name": "example.replacement"},
        ]})
        result = compose(override)
        self.assertEqual(result.plugins[:2], (
            override.plugins[0].model_copy(update={"use": "agent_platform_tools_default:ToolsDefaultPlugin"}),
            override.plugins[1],
        ))
        self.assertNotIn("agent-platform.sandbox-tools", [p.name for p in result.plugins])
        self.assertEqual(sum(p.name == "agent-platform.tools-default" for p in result.plugins), 1)


class PackageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_plugin_runs_without_any_tool_service(self):
        runtime = Loader({"plugins": [
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
        runtime = Loader({"plugins": [
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
        runtime = Loader({"plugins": [
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


class RuntimeBootTests(unittest.IsolatedAsyncioTestCase):
    async def test_boot_mounts_loader_and_application_plugins_in_one_root(self):
        config = PluginConfiguration.model_validate({
            "plugins": [{"id": "prefix", "name": PrefixPlugin.name}],
        })
        runtime = create_runtime(config, catalog=MappingCatalog({PrefixPlugin.name: PrefixPlugin}))
        self.addAsyncCleanup(runtime.aclose)

        runtime.validate()
        await runtime.start()

        root = runtime.ctx
        self.assertEqual([fiber.id for fiber in root.active_fibers], ["minidsh.loader", "prefix"])
        self.assertEqual(root.require(PREFIX), "package:")
        self.assertEqual([row["id"] for row in root.require(PLUGIN_CATALOG).list()], ["prefix"])

        await runtime.aclose()
        self.assertTrue(root.closed)
