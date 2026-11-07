"""Boot real entry points; observe model input and lifecycle without a backend."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from agent_platform_agent_runtime import AGENT_RUNTIME, AgentRuntimePlugin
from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import (
    CHUNK_FINISH, CHUNK_TEXT, LLM, LlmResponse, ModelConfig,
    StreamChunk, make_retry_policy,
)
from agent_platform_plugin_runtime import PluginRuntime, EntryPointCatalog
from agent_platform_plugin_sdk import AGENTS, AGENT_EXTENSIONS, APPROVAL, AgentRunContribution, ServiceClosedError
from agent_platform_sandbox.services import AGENT_SANDBOX
from agent_platform_session import Session
from agent_platform_session_recovery import SESSION_RECOVERY
from agent_platform_system_prompt import RUNTIME_PROMPTS, PreparedPrompt


class Client:
    configured = True
    retry_policy = staticmethod(make_retry_policy(0))

    def __init__(self, *, load_skill=False, slow=False):
        self.requests = []
        self.load_skill = load_skill
        self.slow = slow
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
        if self.load_skill and len(self.requests) == 1:
            return LlmResponse(message={"role": "assistant", "tool_calls": [{
                "id": "load-skill", "type": "function", "function": {"name": "skill", "arguments": '{"name":"demo"}'},
            }]}, finish_reason="tool_calls")
        return LlmResponse(message={"role": "assistant", "content": "done"}, finish_reason="stop")

    async def stream(self, request):
        response = await self.complete(request)
        yield StreamChunk(kind=CHUNK_TEXT, delta=response.message["content"])
        yield StreamChunk(kind=CHUNK_FINISH, finish_reason=response.finish_reason)


class Sessions:
    def __init__(self):
        self.sessions = {}
        self.busy = set()
        self.fail_commit = False
        self.settled = []

    @asynccontextmanager
    async def prepare(self, session_id, **options):
        session = self.sessions.get(session_id) or Session()
        self.sessions[session.header.id] = session
        self.busy.add(session.header.id)
        owner = self
        class Checkpoint:
            enabled = False
            failed = False
            async def flush(self, reason):
                if reason == "turn_end" and owner.fail_commit:
                    raise RuntimeError("commit failed")
            async def before_tool(self, call):
                pass
        try:
            yield session, Checkpoint(), None
        finally:
            self.busy.remove(session.header.id)

    def settle_title(self, session):
        self.settled.append(session.header.id)

    def schedule_title(self, session, config):
        pass


class RuntimePluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "demo.md").write_text("---\nname: demo\ndescription: Demo summary\n---\nPRIVATE SKILL INSTRUCTIONS", encoding="utf-8")
        self.runtimes = []

    async def asyncTearDown(self):
        for runtime in reversed(self.runtimes):
            await runtime.aclose()
        self.temp.cleanup()

    async def start(self, *, skills=False, client=None):
        client = client or Client()
        sessions = Sessions()
        config = {"provider": "test", "model": "test", "session_title_enabled": False}
        async def get_config(key):
            return dict(config)
        async def assemble(**options):
            return PreparedPrompt("Test system prompt", [])
        entries = [
            {"id": "runtime", "name": "agent-platform.agent-runtime"},
            {"id": "loop", "name": "agent-platform.agent-loop"},
            {"id": "agents", "name": "agent-platform.agents"},
            {"id": "tools", "name": "agent-platform.tools-default"},
        ]
        if skills:
            entries.extend([
                {"id": "skill-tools", "name": "agent-platform.skill-tools"},
                {"id": "filesystem", "name": "agent-platform.skills-filesystem", "config": {
                    "builtin": False, "include_installed": False,
                    "sources": [{"name": "custom", "path": str(self.root), "tenant_ids": [1]}],
                }},
                {"id": "skills", "name": "agent-platform.skills-default"},
            ])
        runtime = PluginRuntime({"plugins": entries}, host_services={
            AGENTS: SimpleNamespace(get_config=get_config),
            APPROVAL: SimpleNamespace(available=False),
            RUNTIME_PROMPTS: SimpleNamespace(assemble=assemble),
            SESSION_RECOVERY: sessions,
            LLM: SimpleNamespace(
                resolve=lambda config: ModelConfig(
                    "test", "test", "http://fake", "k", "provider",
                ),
                create_client=lambda model, **options: client,
            ),
            AGENT_SANDBOX: SimpleNamespace(policy=lambda session: None),
        })
        self.runtimes.append(runtime)
        await runtime.start()
        return runtime, client, sessions

    async def test_entry_point_and_skill_plugin_reach_the_real_loop(self):
        self.assertIsInstance(EntryPointCatalog().load("agent-platform.agent-runtime"), AgentRuntimePlugin)
        runtime, client, sessions = await self.start(skills=True)
        reply = await runtime.require(AGENT_RUNTIME).reply("test", {"name": "Test"}, 1, "/demo")
        self.assertEqual(reply.answer, "done")
        messages = client.requests[0].messages
        self.assertEqual(messages[0], {"role": "system", "content": "Test system prompt"})
        content = "\n".join(message.get("content", "") for message in messages)
        self.assertIn("<available_skills>", content)
        self.assertIn("PRIVATE SKILL INSTRUCTIONS", content)
        self.assertEqual(sessions.busy, set())
        self.assertEqual(runtime.require(AGENT_RUNS).active(), [])

    async def test_model_loads_skill_after_receiving_only_the_summary(self):
        runtime, client, _ = await self.start(skills=True, client=Client(load_skill=True))
        reply = await runtime.require(AGENT_RUNTIME).reply("test", {}, 1, "Use the demo skill")
        self.assertEqual(reply.answer, "done")
        self.assertEqual(len(client.requests), 2)
        first = str(client.requests[0].messages)
        second = str(client.requests[1].messages)
        self.assertIn("Demo summary", first)
        self.assertNotIn("PRIVATE SKILL INSTRUCTIONS", first)
        self.assertIn("PRIVATE SKILL INSTRUCTIONS", second)

    async def test_done_is_emitted_after_session_release_and_failed_commit_never_emits_done(self):
        runtime, _, sessions = await self.start()
        emitted = []
        async def emit(event):
            if event["type"] == "done":
                self.assertEqual(sessions.busy, set())
            emitted.append(event)
        service = runtime.require(AGENT_RUNTIME)
        await service.reply("test", {}, 1, "hello", on_event=emit)
        self.assertEqual(emitted[-1]["type"], "done")
        emitted.clear()
        sessions.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            await service.reply("test", {}, 1, "hello", on_event=emit)
        self.assertNotIn("done", [event["type"] for event in emitted])
        self.assertEqual(sessions.busy, set())

    async def test_unload_cancels_active_reply_and_drains_session_cleanup(self):
        runtime, client, sessions = await self.start(client=Client(slow=True))
        service = runtime.require(AGENT_RUNTIME)
        extensions = runtime.require(AGENT_EXTENSIONS)
        task = asyncio.create_task(service.reply("test", {}, 1, "hello"))
        await asyncio.wait_for(client.started.wait(), 3)
        await asyncio.wait_for(runtime.aclose(), 3)
        self.assertTrue(client.stopped.is_set())
        self.assertTrue(task.done())
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(sessions.busy, set())
        with self.assertRaises(ServiceClosedError):
            await service.reply("test", {}, 1, "hello")
        with self.assertRaises(ServiceClosedError):
            extensions.register("late", lambda context: None)

    async def test_extension_registries_are_isolated_and_registration_disposal_is_observed(self):
        first, first_client, _ = await self.start()
        second, second_client, _ = await self.start()
        async def extension(context):
            async def hook(session, messages):
                return [{"content": "FIRST RUNTIME ONLY", "source": {"kind": "test"}}]
            return AgentRunContribution(context.tool_schemas, pre_step=hook)
        registration = first.require(AGENT_EXTENSIONS).register("example", extension)
        await first.require(AGENT_RUNTIME).reply("test", {}, 1, "hello")
        await second.require(AGENT_RUNTIME).reply("test", {}, 1, "hello")
        self.assertIn("FIRST RUNTIME ONLY", str(first_client.requests[0].messages))
        self.assertNotIn("FIRST RUNTIME ONLY", str(second_client.requests[0].messages))
        await registration.aclose()
        await first.require(AGENT_RUNTIME).reply("test", {}, 1, "hello")
        self.assertNotIn("FIRST RUNTIME ONLY", str(first_client.requests[1].messages))

    async def test_runtime_package_imports_without_backend(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, "-c", (
            "import sys; import agent_platform_agent_runtime; "
            "assert not any(n == 'backend' or n.startswith('backend.') for n in sys.modules); "
            "assert 'fastapi' not in sys.modules"
        )], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
