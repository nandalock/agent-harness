"""Real plugin assembly, driver replacement and ordered lifecycle regression tests."""
import asyncio
import subprocess
import sys
import unittest
from unittest.mock import patch

from agent_platform_agents import AGENT_RUNS, AgentsPlugin, RunConflict
from agent_platform_agent_loop import AgentLoopPlugin
from agent_platform_agent_loop.plugin import LoopConfig, LoopFactory
from agent_platform_llm import LlmResponse, make_retry_policy
from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import (
    APPROVAL, TOOLS, PluginSpec, SdkModel, ServiceClosedError, ServiceRequirement,
    ServiceUnavailableError, ToolDescriptor, ToolResult,
)
from agent_platform_session import Session
from agent_platform_tools_default import ToolsDefaultPlugin


class Approval:
    available = False

    async def request(self, req):
        return "unavailable"


class Client:
    configured = True
    retry_policy = staticmethod(make_retry_policy(0))

    def __init__(self, *, tools=False, slow=False):
        self.tools = tools
        self.slow = slow
        self.requests = []
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def complete(self, request):
        self.requests.append(request)
        self.started.set()
        if self.slow:
            try:
                await asyncio.Event().wait()
            finally:
                self.stopped.set()
        if self.tools and len(self.requests) == 1:
            return LlmResponse(message={"role": "assistant", "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "echo", "arguments": '{"text":"hello"}'},
            }]}, finish_reason="tool_calls")
        return LlmResponse(message={"role": "assistant", "content": "done"}, finish_reason="stop")


class EchoExecutor:
    def __init__(self, calls):
        self.calls = calls

    async def execute(self, descriptor, arguments, context):
        self.calls.append((descriptor, context))
        return ToolResult(data={"text": arguments["text"]})


def options(session=None, client=None, **extra):
    return dict(key="test", session=session or Session(), llm=client or Client(), model="fake",
                llm_params={"max_steps": 4, "max_wall_time": 10, "max_tool_calls": 10,
                            "max_tokens": 128, "temperature": 0},
                tenant_id=1, tool_schemas=[], **extra)


async def drive(runs, opts, text="hello"):
    async with runs.open(**opts) as agent:
        agent.followup(text)
        await agent.when_idle()
        return agent.answer_text()


def runtime(*, extra=(), catalog_extra=None, loop=True):
    entries = [
        {"id": "loop", "name": "agent-platform.agent-loop"},
        {"id": "agents", "name": "agent-platform.agents"},
        {"id": "tools", "name": "agent-platform.tools-default"},
    ]
    if not loop:
        entries.pop(0)
    return PluginRuntime({"plugins": entries + list(extra)}, catalog=MappingCatalog({
        "agent-platform.agent-loop": AgentLoopPlugin,
        "agent-platform.agents": AgentsPlugin,
        "agent-platform.tools-default": ToolsDefaultPlugin,
        **(catalog_extra or {}),
    }), host_services={APPROVAL: Approval()})


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime()
        await self.runtime.start()

    async def asyncTearDown(self):
        await self.runtime.aclose()

    def loop_plugin_context(self):
        return next(ctx for record, ctx in self.runtime._contexts if record.entry.id == "loop")

    async def test_entry_points_are_discoverable(self):
        from agent_platform_plugin_runtime import EntryPointCatalog
        catalog = EntryPointCatalog()
        self.assertIsInstance(catalog.load("agent-platform.agent-loop"), AgentLoopPlugin)
        self.assertIsInstance(catalog.load("agent-platform.agents"), AgentsPlugin)

    async def test_loop_runs_through_the_service(self):
        runs = self.runtime.require(AGENT_RUNS)
        session = Session()
        self.assertEqual(await drive(runs, options(session)), "done")
        self.assertEqual(runs.active(), [])
        self.assertEqual(session.events[-1].type, "turn/end")

    async def test_tools_execute_without_any_backend_or_global_tool_host(self):
        calls = []
        tools = self.runtime.require(TOOLS)
        tools.register_executor("echo", EchoExecutor(calls))
        descriptor = ToolDescriptor(name="echo", executor="echo", description="Echo",
                                    input_schema={"type": "object", "properties": {"text": {"type": "string"}}})
        tools.register_tool(descriptor)
        opts = options(client=Client(tools=True))
        opts["tool_schemas"] = [{"type": "function", "function": {
            "name": "echo", "description": "Echo", "parameters": descriptor.input_schema,
        }}]
        self.assertEqual(await drive(self.runtime.require(AGENT_RUNS), opts), "done")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].scope.tenant_id, 1)
        self.assertEqual(calls[0][1].host_context.session_id, opts["session"].header.id)
        self.assertIs(calls[0][1].host_context.approval, self.runtime._host_services[APPROVAL])
        events = [event.type for event in opts["session"].events]
        self.assertEqual(events.count("tool/call"), 1)
        self.assertEqual(events.count("tool/result"), 1)

    async def test_same_session_is_single_flight_and_released_after_failure(self):
        runs = self.runtime.require(AGENT_RUNS)
        opts = options()
        with self.assertRaisesRegex(ValueError, "host failed"):
            async with runs.open(**opts):
                with self.assertRaises(RunConflict):
                    async with runs.open(**opts):
                        self.fail("duplicate session was accepted")
                raise ValueError("host failed")
        self.assertEqual(await drive(runs, opts), "done")

    async def test_registry_is_isolated_between_runtimes(self):
        other = runtime()
        await other.start()
        try:
            opts = options()
            async with self.runtime.require(AGENT_RUNS).open(**opts):
                self.assertEqual(await drive(other.require(AGENT_RUNS), options(opts["session"])), "done")
                self.assertEqual(other.require(AGENT_RUNS).active(), [])
        finally:
            await other.aclose()

    async def test_unload_cancels_driver_and_waits_for_host_cleanup(self):
        runs = self.runtime.require(AGENT_RUNS)
        client = Client(slow=True)
        opts = options(client=client)
        host_cleaned = asyncio.Event()

        async def request():
            async with runs.open(**opts) as agent:
                try:
                    agent.followup("hello")
                    await agent.when_idle()
                finally:
                    await asyncio.sleep(0)
                    host_cleaned.set()
        task = asyncio.create_task(request())
        await asyncio.wait_for(client.started.wait(), 2)
        await asyncio.wait_for(self.runtime.aclose(), 2)
        await task
        self.assertTrue(client.stopped.is_set())
        self.assertTrue(host_cleaned.is_set())
        self.assertEqual(runs.active(), [])
        self.assertEqual(opts["session"].events[-1].data["stop_reason"], "cancelled")
        with self.assertRaises(ServiceClosedError):
            async with runs.open(**options()):
                pass

    async def test_hard_cancellation_settles_and_releases_session(self):
        client = Client(slow=True)
        runs = self.runtime.require(AGENT_RUNS)
        task = asyncio.create_task(drive(runs, options(client=client)))
        await asyncio.wait_for(client.started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(runs.active(), [])
        self.assertTrue(client.stopped.is_set())

    async def test_unload_drains_tool_and_host_before_later_provider_is_disposed(self):
        order = []
        entered = asyncio.Event()

        class Executor:
            async def execute(self, descriptor, arguments, context):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    order.append("tool drained")

        class Provider:
            spec = PluginSpec(name="test.provider", version="0.1.0",
                              requires=(ServiceRequirement(service=TOOLS.ref),))
            config_model = SdkModel

            async def setup(self, ctx, config):
                tools = ctx.require(TOOLS)
                ctx.track(tools.register_executor("echo", Executor()))
                ctx.track(tools.register_tool(ToolDescriptor(
                    name="echo", executor="echo", description="Echo",
                    input_schema={"type": "object"},
                )))
                ctx.on_dispose(lambda: order.append("provider disposed"), label="provider")

        other = runtime(extra=[{"id": "provider", "name": "test.provider"}],
                        catalog_extra={"test.provider": Provider})
        await other.start()
        opts = options(client=Client(tools=True))
        opts["tool_schemas"] = [{"type": "function", "function": {
            "name": "echo", "parameters": {"type": "object"},
        }}]

        async def request():
            async with other.require(AGENT_RUNS).open(**opts) as agent:
                try:
                    agent.followup("hello")
                    await agent.when_idle()
                finally:
                    order.append("host flushed")
        task = asyncio.create_task(request())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(other.aclose(), 2)
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await other.aclose()
        self.assertEqual(order, ["tool drained", "host flushed", "provider disposed"])
        types = [event.type for event in opts["session"].events]
        self.assertEqual(types.count("tool/call"), types.count("tool/result"))

    async def test_disabled_loop_has_no_native_fallback(self):
        other = runtime(loop=False)
        await other.start()
        try:
            with self.assertRaises(ServiceUnavailableError):
                await drive(other.require(AGENT_RUNS), options())
        finally:
            await other.aclose()

    async def test_custom_loop_plugin_can_replace_the_default(self):
        class CustomAgent:
            followup = steer = inject = lambda self, text: "id"
            cancel = lambda self, *args, **kwargs: None

            async def when_idle(self):
                pass

            def answer_text(self):
                return "custom driver"

        class CustomPlugin:
            spec = PluginSpec(name="test.custom-loop", version="0.1.0",
                              requires=(ServiceRequirement(service=AGENT_RUNS.ref),))
            config_model = SdkModel

            async def setup(self, ctx, config):
                class Factory:
                    create = lambda self, **kwargs: CustomAgent()
                registration = ctx.require(AGENT_RUNS).register_factory(Factory())
                ctx.on_quiesce(registration.aclose, label="custom loop")
                ctx.track(registration)
        other = runtime(loop=False, extra=[{"id": "custom", "name": "test.custom-loop"}],
                        catalog_extra={"test.custom-loop": CustomPlugin})
        await other.start()
        try:
            self.assertEqual(await drive(other.require(AGENT_RUNS), options()), "custom driver")
        finally:
            await other.aclose()

    async def test_scoped_handle_rejects_input_after_dispose(self):
        async with self.runtime.require(AGENT_RUNS).open(**options()) as agent:
            pass
        for method in (agent.followup, agent.steer, agent.inject):
            with self.assertRaises(ServiceClosedError):
                method("late input")

    async def test_loop_config_applies_unless_agent_overrides_it(self):
        factory = LoopFactory(self.loop_plugin_context(), LoopConfig(max_parallel_tools=2))
        opts = options()
        self.assertEqual(factory.create(**opts)._scheduler._max_parallel, 2)
        self.assertNotIn("max_parallel_tools", opts["llm_params"])
        opts["llm_params"]["max_parallel_tools"] = 3
        self.assertEqual(factory.create(**opts)._scheduler._max_parallel, 3)

    async def test_factory_binds_the_original_plugin_context_to_the_loop(self):
        ctx = self.loop_plugin_context()
        opts = options()
        loop = LoopFactory(ctx, LoopConfig()).create(**opts)
        self.assertIs(loop.loop_ctx.plugin_ctx, ctx)
        self.assertIs(loop.loop_ctx.tools, self.runtime.require(TOOLS))
        self.assertIs(loop.loop_ctx.llm, opts["llm"])
        self.assertIs(loop._scheduler.loop_ctx, loop.loop_ctx)

    async def test_dispatch_resolves_tools_from_loop_context_after_creation(self):
        ctx = self.loop_plugin_context()
        tools = self.runtime.require(TOOLS)
        opts = options(client=Client(tools=True))
        opts["tool_schemas"] = [{"type": "function", "function": {
            "name": "echo", "parameters": {"type": "object"},
        }}]
        calls = []
        with (
            patch.object(ctx, "require", wraps=ctx.require) as resolve,
            patch.object(ctx, "get", wraps=ctx.get) as optional,
        ):
            loop = LoopFactory(ctx, LoopConfig()).create(**opts)
            self.assertFalse(resolve.called)
            # The same service table is read at dispatch, so registrations made
            # after the loop was constructed are immediately available.
            tools.register_executor("echo", EchoExecutor(calls))
            tools.register_tool(ToolDescriptor(name="echo", executor="echo", description="Echo",
                                               input_schema={"type": "object"}))
            loop.followup("hello")
            await loop.when_idle()
        self.assertEqual(loop.answer_text(), "done")
        self.assertEqual(len(calls), 1)
        self.assertIn(unittest.mock.call(TOOLS), resolve.call_args_list)
        self.assertIn(unittest.mock.call(APPROVAL), optional.call_args_list)

    async def test_run_contexts_share_services_but_isolate_clients_and_policies(self):
        factory = LoopFactory(self.loop_plugin_context(), LoopConfig())
        mode = {"value": "read-only"}
        opts = options(sandbox_policy=lambda: mode["value"])
        first = factory.create(**opts)
        second = factory.create(**options(sandbox_policy=lambda: "full-access"))
        self.assertIsNot(first.loop_ctx, second.loop_ctx)
        self.assertIs(first.loop_ctx.tools, second.loop_ctx.tools)
        self.assertIsNot(first.loop_ctx.llm, second.loop_ctx.llm)
        self.assertEqual(first._tool_context("call-1").sandbox_policy, "read-only")
        mode["value"] = "workspace-write"
        self.assertEqual(first._tool_context("call-2").sandbox_policy, "workspace-write")
        self.assertEqual(second._tool_context("call-3").sandbox_policy, "full-access")

    async def test_saved_loop_context_cannot_resolve_services_after_plugin_disposal(self):
        loop = LoopFactory(self.loop_plugin_context(), LoopConfig()).create(**options())
        await self.runtime.aclose()
        with self.assertRaises(ServiceClosedError):
            _ = loop.loop_ctx.tools

    async def test_real_imports_do_not_reach_into_backend(self):
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", """
import sys
import agent_platform_agent_loop, agent_platform_agents, agent_platform_session, agent_platform_llm
assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)
"""], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == "__main__":
    unittest.main()
