"""Real installed entry points, provider ownership and conversation integration."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from minidsh_cordis_plugin_loader import Loader
from agent_platform_plugin_sdk import (
    AGENTS, AGENT_EXTENSIONS, TOOLS, AgentRunContext, AgentRunContribution,
    ExecutionScope, ToolCall, ToolContext, ServiceClosedError,
)
from agent_platform_skills import SKILLS, SkillRegistry, SkillScope, SkillSource, SkillError
from agent_platform_skills_filesystem import FilesystemSkillProvider
from agent_platform_agent_runtime import AgentExtensionRegistry
from agent_platform_session import Session


class Agents:
    async def get_config(self, key):
        return {}


class SkillPluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "custom"
        self.directory.mkdir()
        self.write("demo", "Original instructions")
        self.env = patch.dict("os.environ", {
            "SKILL_SOURCES": "[]", "SKILL_INSTALL_ROOT": str(self.root / "installed"),
        })
        self.env.start()
        self.extensions = AgentExtensionRegistry()
        self.runtimes = []
        self.scope = SkillScope(7, "assistant", frozenset({"skill"}))

    async def asyncTearDown(self):
        for runtime in reversed(self.runtimes):
            await runtime.aclose()
        self.env.stop()
        self.temp.cleanup()

    def write(self, name, body):
        (self.directory / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Demo\n---\n{body}", encoding="utf-8",
        )

    async def start(self, *, files=True, consumer=True, disabled=False, extensions=None):
        # Intentionally reversed: dependencies, rather than YAML order, govern setup.
        entries = []
        if consumer:
            entries.append({"id": "skill-tools", "name": "agent-platform.skill-tools", "use": "agent_platform_skill_tools:SkillToolsPlugin", "disabled": disabled})
        if files:
            entries.append({"id": "files", "name": "agent-platform.skills-filesystem", "use": "agent_platform_skills_filesystem:SkillsFilesystemPlugin", "config": {
                "builtin": False, "include_installed": False,
                "sources": [{"name": "custom", "path": str(self.directory), "tenant_ids": [7], "agent_keys": ["assistant"]}],
            }})
        entries.extend([
            {"id": "skills", "name": "agent-platform.skills-default", "use": "agent_platform_skills_default:SkillsDefaultPlugin"},
            {"id": "tools", "name": "agent-platform.tools-default", "use": "agent_platform_tools_default:ToolsDefaultPlugin"},
        ])
        runtime = Loader({"plugins": entries}, host_services={
            AGENTS: Agents(), AGENT_EXTENSIONS: extensions or self.extensions,
        })
        self.runtimes.append(runtime)
        await runtime.start()
        return runtime

    async def prepare(self, config=None):
        return await self.extensions.prepare(AgentRunContext(7, "assistant", config or {}, []))

    async def test_three_installed_plugins_load_and_tool_reads_updated_document(self):
        runtime = await self.start()
        service = runtime.require(SKILLS)
        self.assertEqual([skill.key for skill in service.list(self.scope)], ["custom:demo"])
        self.assertEqual(service.list(replace(self.scope, tenant_id=8)), [])
        self.assertEqual(service.list(replace(self.scope, agent_key="other")), [])
        self.assertEqual(service.list(replace(self.scope, enabled_names=())), [])
        tools = runtime.require(TOOLS)
        contribution = await self.prepare({"skill_install_enabled": False})
        visible = frozenset(t["function"]["name"] for t in contribution.tool_schemas)
        self.assertEqual(visible, {"skill"})
        context = ToolContext(scope=ExecutionScope(tenant_id=7, agent_key="assistant"), visible_tool_names=visible)
        result = await tools.execute(ToolCall(call_id="load", name="skill", arguments={"name": "demo"}), context)
        self.assertIn("Original instructions", result.data["rows"][0]["text"])
        self.write("demo", "Updated instructions")
        self.assertIn("Updated instructions", service.load("demo", self.scope)["text"])
        with self.assertRaises(SkillError):
            service.load("demo", replace(self.scope, tenant_id=8))

    async def test_registry_runs_without_tools_agents_or_filesystem(self):
        runtime = Loader({"plugins": [{"id": "skills", "name": "agent-platform.skills-default", "use": "agent_platform_skills_default:SkillsDefaultPlugin"}]})
        self.runtimes.append(runtime)
        await runtime.start()
        self.assertEqual(runtime.require(SKILLS).list(self.scope), [])

    async def test_filesystem_produces_no_tools(self):
        runtime = await self.start(consumer=False)
        self.assertEqual(await runtime.require(TOOLS).list_for_agent(ExecutionScope(tenant_id=7, agent_key="assistant")), ())
        self.assertEqual(len(runtime.require(SKILLS).list(self.scope)), 1)
        self.assertIsNone((await self.prepare()).pre_step)

    async def test_disabled_consumer_adds_no_schemas_hooks_or_tools(self):
        runtime = await self.start(disabled=True)
        contribution = await self.prepare()
        self.assertEqual(contribution.tool_schemas, [])
        self.assertIsNone(contribution.pre_step)
        self.assertEqual(len(runtime.require(SKILLS).list(self.scope)), 1)
        self.assertEqual(await runtime.require(TOOLS).list_for_agent(ExecutionScope(tenant_id=7, agent_key="assistant")), ())

    async def test_no_filesystem_plugin_means_no_implicit_builtin_discovery(self):
        runtime = await self.start(files=False)
        self.assertEqual(runtime.require(SKILLS).list(self.scope), [])
        contribution = await self.prepare({"skill_install_enabled": False})
        self.assertEqual(contribution.tool_schemas, [])
        self.assertEqual(await contribution.pre_step(Session(), []), [])

    async def test_whitelist_and_disable_remove_even_previously_bound_skill_tools(self):
        await self.start()
        bound = [{"type": "function", "function": {"name": name}} for name in ("skill", "skill_install")]
        contribution = await self.extensions.prepare(AgentRunContext(7, "assistant", {"skills_enabled": False}, bound))
        self.assertEqual(contribution.tool_schemas, [])
        contribution = await self.prepare({"enabled_skills": []})
        self.assertEqual(contribution.tool_schemas, [])

    async def test_catalog_hook_is_plugin_owned_and_stops_after_unload(self):
        runtime = await self.start()
        contribution = await self.prepare()
        session = Session()
        injections = await contribution.pre_step(session, [])
        self.assertEqual(injections[0]["source"]["entries"][0]["name"], "demo")
        tools, skills = runtime.require(TOOLS), runtime.require(SKILLS)
        await runtime.aclose()
        self.assertEqual(await contribution.pre_step(session, []), [])
        self.assertEqual((await self.prepare()).tool_schemas, [])
        self.assertEqual(await tools.list_for_agent(ExecutionScope(tenant_id=7, agent_key="assistant")), ())
        with self.assertRaises(ServiceClosedError):
            skills.list(self.scope)

    async def test_provider_disposal_and_separate_runtime_isolation(self):
        first = await self.start(consumer=False)
        second = await self.start(files=False, consumer=False)
        self.assertEqual(second.require(SKILLS).list(self.scope), [])
        await first.aclose()
        self.assertEqual(second.require(SKILLS).list(self.scope), [])
        registry = SkillRegistry()
        sources = [SkillSource("local", self.directory)]
        registration = registry.register_provider(FilesystemSkillProvider(sources))
        self.assertEqual(len(registry.list(self.scope)), 1)
        await registration.aclose()
        self.assertEqual(registry.list(self.scope), [])
        replacement = registry.register_provider(FilesystemSkillProvider(sources))
        await registration.aclose()  # An old disposer must not remove its replacement.
        self.assertEqual(len(registry.list(self.scope)), 1)
        await replacement.aclose()
        self.assertEqual(registry.list(self.scope), [])

    async def test_failed_consumer_setup_rolls_back_tools_and_providers(self):
        class BrokenExtensions:
            def register(self, *args):
                raise RuntimeError("registration failed")
        with self.assertRaisesRegex(RuntimeError, "registration failed"):
            await self.start(extensions=BrokenExtensions())
        self.assertEqual(self.runtimes[-1].plugins, ())
        # A clean retry gets fresh services and registrations, without global state.
        runtime = await self.start()
        self.assertEqual(len(runtime.require(SKILLS).list(self.scope)), 1)


class GenericExtensionTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_extensions_compose_and_unregister_independently(self):
        registry = AgentExtensionRegistry()
        async def first(context):
            async def hook(session, messages):
                return [{"content": "first"}]
            return AgentRunContribution(context.tool_schemas, hook)
        async def second(context):
            async def hook(session, messages):
                return [{"content": "second"}]
            return AgentRunContribution(context.tool_schemas, hook)
        one, two = registry.register("first", first), registry.register("second", second)
        prepared = await registry.prepare(AgentRunContext(1, "a", {}, []))
        self.assertEqual(await prepared.pre_step(None, []), [{"content": "first"}, {"content": "second"}])
        await one.aclose()
        self.assertEqual(await prepared.pre_step(None, []), [{"content": "second"}])
        await two.aclose()
        self.assertIsNone((await registry.prepare(AgentRunContext(1, "a", {}, []))).pre_step)


if __name__ == "__main__":
    unittest.main()
