"""Configuration catalogs stay editable while runtime skill access stays scoped."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from agent_platform_plugin_sdk import AGENTS, TOOLS, ExecutionScope, ToolCall, ToolContext, ToolDescriptor
from agent_platform_skills import SKILLS, SkillSource
from agent_platform_skills_filesystem import FilesystemSkillProvider
from agent_platform_http_api.routes import agents as agents_api
from agent_platform_http_api.routes import skills as skills_api, tools as tools_api
from agent_platform_plugin_sdk import AgentRunContext, ToolResult
from backend.skills.support import installed_skill_runtime


class SkillBindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict("os.environ", {"SKILL_SOURCES": "[]", "SKILL_INSTALL_ROOT": self.temp}))
        self.configs = {"alpha": {"enabled_skills": [], "provider": "custom"}, "beta": {}}
        self.bindings = {"alpha": [], "beta": []}
        self.context = installed_skill_runtime()
        self.runtime, self.extensions = await self.context.__aenter__()
        self.stack.enter_context(patch("backend.host_services.read_tool_bindings", side_effect=lambda key: self.bindings[key]))
        self.stack.enter_context(patch("agent_platform_http_api.routes.skills._bindings", side_effect=lambda key: self.bindings[key]))
        self.stack.enter_context(patch("backend.plugin_host.get_plugin_host", return_value=SimpleNamespace(runtime=self.runtime)))
        self.stack.enter_context(patch("backend.agents.runtime.extensions.get_agent_extensions", return_value=self.extensions))
        async def get_config(key):
            return dict(self.configs[key])
        self.stack.enter_context(patch.object(self.runtime.require(AGENTS), "get_config", side_effect=get_config))
        async def get_definition(key):
            return {"agent_key": key} if key in self.configs else None
        self.stack.enter_context(patch.object(
            self.runtime.require(AGENTS), "get_definition", side_effect=get_definition, create=True,
        ))
        self.entry = Mock()
        def save(key, config):
            self.configs[key] = dict(config)
            return dict(config)
        self.save = Mock(side_effect=save)
        save_mock = self.save
        class _AgentApi:
            async def save_config(self, key, config):
                return save_mock(key, config), None
        self.stack.enter_context(patch(
            "agent_platform_http_api.routes.agents.plugin_services.agent_api", return_value=_AgentApi(),
        ))

    async def _save_config(self, key, config):
        return await agents_api.agent_save_config(key, config, entry=self.entry)

    async def asyncTearDown(self):
        await self.context.__aexit__(None, None, None)
        self.stack.close()

    async def test_configuration_lists_unselected_skills_without_changing_runtime_policy(self):
        before = dict(self.configs["alpha"])
        for disabled in (False, True):
            self.configs["alpha"]["skills_enabled"] = not disabled
            catalog = await skills_api.list_skill_catalog("alpha", x_tenant_id=7)
            self.assertTrue(catalog["available"])
            self.assertEqual(len(catalog["skills"]), 2)
            self.assertTrue(all("content" not in item and "path" not in item for item in catalog["skills"]))
            self.assertEqual(await skills_api.list_skills("alpha", x_tenant_id=7), {"skills": []})
            self.assertEqual(self.configs["alpha"]["enabled_skills"], before["enabled_skills"])
        self.save.assert_not_called()

    async def test_saved_selection_controls_real_tool_execution_and_is_agent_specific(self):
        config = {"skills_enabled": True, "enabled_skills": ["platform:skill-installer"], "provider": "custom"}
        await self._save_config("alpha", config)
        catalog = await skills_api.list_skills("alpha", x_tenant_id=7)
        self.assertEqual([item["key"] for item in catalog["skills"]], ["platform:skill-installer"])
        tools = self.runtime.require(TOOLS)
        context = ToolContext(scope=ExecutionScope(tenant_id=7, agent_key="alpha"), visible_tool_names=frozenset({"skill", "skill_install"}))
        result = await tools.execute(ToolCall(call_id="allowed", name="skill", arguments={"name": "platform:skill-installer"}), context)
        self.assertEqual(result.status, "success")
        await self._save_config("alpha", {**config, "enabled_skills": []})
        result = await tools.execute(ToolCall(call_id="denied", name="skill", arguments={"name": "platform:skill-installer"}), context)
        self.assertEqual(result.status, "error")
        self.assertEqual(self.configs["beta"], {})
        self.assertEqual(self.configs["alpha"]["provider"], "custom")
        self.assertEqual(len((await skills_api.list_skill_catalog("alpha", x_tenant_id=7))["skills"]), 2)

    async def test_catalog_keeps_tenant_and_agent_source_boundaries(self):
        root = Path(self.temp) / "private"
        root.mkdir()
        (root / "private.md").write_text("---\nname: private\ndescription: Private\n---\nPrivate instructions", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("private", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="private"))
        for key, tenant, expected in (("alpha", 7, True), ("alpha", 8, False), ("beta", 7, False)):
            catalog = await skills_api.list_skill_catalog(key, x_tenant_id=tenant)
            self.assertEqual("private:private" in {item["key"] for item in catalog["skills"]}, expected)

    async def test_stale_bindings_do_not_hide_missing_tool_dependencies(self):
        self.bindings["alpha"] = ["overleaf_read_doc", "overleaf_edit_doc"]
        catalog = await skills_api.list_skill_catalog("alpha", x_tenant_id=7)
        entry = next(item for item in catalog["skills"] if item["key"] == "overleaf-rt:overleaf")
        self.assertFalse(entry["tools_ready"])
        self.assertIsNone(entry["unavailable_reason"])  # Setup instructions remain readable.
        self.assertIn("overleaf_read_doc", entry["tools"])
        self.assertIn("overleaf_edit_doc", entry["tools"])

    async def test_missing_plugin_service_is_reported_without_unfiltered_fallback(self):
        with patch("backend.plugin_host.get_plugin_host", return_value=None):
            self.assertEqual(await skills_api.list_skill_catalog("alpha", x_tenant_id=7), {"skills": [], "available": False})

    async def test_invalid_skill_settings_are_rejected_before_persistence(self):
        for body in ({"skills_enabled": "false"}, {"skills_enabled": 0}, {"skill_install_enabled": "yes"},
                     {"enabled_skills": "weekly"}, {"enabled_skills": [1]}, {"enabled_skills": [""]}):
            with self.subTest(body=body), self.assertRaises(HTTPException) as error:
                await self._save_config("alpha", body)
            self.assertEqual(error.exception.status_code, 422)
        self.save.assert_not_called()

    async def test_all_and_empty_selections_have_distinct_runtime_meanings(self):
        for selection, expected in (([], 0), (None, 2)):
            await self._save_config("alpha", {"skills_enabled": True, "enabled_skills": selection})
            self.assertEqual(len((await skills_api.list_skills("alpha", x_tenant_id=7))["skills"]), expected)

    async def test_overleaf_catalog_exposes_one_real_skill(self):
        catalog = await skills_api.list_skill_catalog("alpha", x_tenant_id=7)
        members = [entry for entry in catalog["skills"] if entry["source"] == "overleaf-rt"]
        self.assertEqual([entry["key"] for entry in members], ["overleaf-rt:overleaf"])
        self.assertEqual({entry["binding_key"] for entry in members}, {"@package/overleaf-rt"})
        self.assertEqual({entry["package_name"] for entry in members}, {"overleaf"})
        self.assertEqual({entry["kind"] for entry in members}, {"skill"})
        self.assertEqual(len({entry["binding_key"] for entry in catalog["skills"]}), 2)

    async def test_saved_package_binding_loads_entry_then_requested_reference(self):
        await self._save_config("alpha", {"enabled_skills": ["@package/overleaf-rt"]})
        catalog = await skills_api.list_skills("alpha", x_tenant_id=7)
        self.assertEqual(len(catalog["skills"]), 1)
        self.assertTrue(all(entry["source"] == "overleaf-rt" for entry in catalog["skills"]))
        tools = self.runtime.require(TOOLS)
        tools.register_tool(ToolDescriptor(name="overleaf_list_comments", executor="example",
                                           description="List comments", input_schema={"type": "object"}))
        context = ToolContext(scope=ExecutionScope(tenant_id=7, agent_key="alpha"),
                              visible_tool_names=frozenset({"skill", "overleaf_list_comments"}))
        result = await tools.execute(ToolCall(call_id="load-comments", name="skill",
                                             arguments={"name": "overleaf-rt:overleaf-comments"}), context)
        self.assertEqual(result.status, "success")
        self.assertIn("references/comments.md", result.data["rows"][0]["text"])
        self.assertNotIn("# Overleaf comments", result.data["rows"][0]["text"])
        reference = await tools.execute(ToolCall(call_id="read-reference", name="skill", arguments={
            "name": "overleaf", "resource": "references/comments.md",
        }), context)
        self.assertEqual(reference.status, "success")
        self.assertIn("Overleaf comments", reference.data["rows"][0]["text"])
        self.assertEqual(self.bindings["alpha"], [])  # Automatic grants never change manual bindings.
        await self._save_config("alpha", {"enabled_skills": []})
        result = await tools.execute(ToolCall(call_id="denied", name="skill",
                                             arguments={"name": "overleaf-rt:overleaf-comments"}), context)
        self.assertEqual(result.status, "error")

    async def test_package_binding_includes_new_members_but_keeps_source_scope(self):
        await self._save_config("alpha", {"enabled_skills": ["@package/overleaf-rt"]})
        root = Path(self.temp) / "new-member"
        root.mkdir()
        (root / "future.md").write_text("---\nname: future\ndescription: Future\n---\nFuture instructions", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("future", root, tenant_ids=(7,), agent_keys=("alpha",),
                        package_key="overleaf-rt", package_name="overleaf"),
        ], name="future"))
        self.assertIn("future:future", {entry["key"] for entry in (await skills_api.list_skills("alpha", x_tenant_id=7))["skills"]})
        for key, tenant in (("alpha", 8), ("beta", 7)):
            catalog = await skills_api.list_skill_catalog(key, x_tenant_id=tenant)
            self.assertNotIn("future:future", {entry["key"] for entry in catalog["skills"]})

    async def test_independent_downloads_in_one_source_are_not_merged(self):
        root = Path(self.temp) / "downloads"
        root.mkdir()
        for name in ("first", "second"):
            (root / f"{name}.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\nInstructions", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("downloads", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="downloads"))
        catalog = await skills_api.list_skill_catalog("alpha", x_tenant_id=7)
        entries = [entry for entry in catalog["skills"] if entry["source"] == "downloads"]
        self.assertEqual({entry["binding_key"] for entry in entries}, {"downloads:first", "downloads:second"})

    async def test_legacy_binding_resolves_to_canonical_entry(self):
        await self._save_config("alpha", {"enabled_skills": ["overleaf-rt:overleaf-comments"]})
        catalog = await skills_api.list_skills("alpha", x_tenant_id=7)
        self.assertEqual([entry["key"] for entry in catalog["skills"]], ["overleaf-rt:overleaf"])
        self.assertEqual(catalog["skills"][0]["binding_key"], "@package/overleaf-rt")

    async def test_skill_binding_adds_tools_and_disabling_it_keeps_manual_bindings(self):
        tools = self.runtime.require(TOOLS)
        for name in ("overleaf_list_comments", "overleaf_add_comment"):
            tools.register_tool(ToolDescriptor(name=name, executor="example", description=name,
                                               input_schema={"type": "object"}))
        self.bindings["alpha"] = ["overleaf_list_comments", "manual_only"]
        await self._save_config("alpha", {"enabled_skills": ["overleaf-rt:overleaf-comments"]})
        details = await tools_api.api_binding_details("alpha", x_tenant_id=7)
        self.assertEqual(details["automatic_tools"]["overleaf_add_comment"], ("overleaf",))
        self.assertIn("overleaf_reply_comment", details["automatic_tools"])
        self.assertEqual(details["manual_tools"], ["overleaf_list_comments", "manual_only"])
        self.assertIn("overleaf_add_comment", details["tools"])
        contribution = await self.extensions.prepare(AgentRunContext(7, "alpha", self.configs["alpha"], []))
        schemas = {tool["function"]["name"] for tool in contribution.tool_schemas}
        self.assertIn("overleaf_add_comment", schemas)
        self.assertNotIn("overleaf_reply_comment", schemas)  # Unloaded tools never reach the model.
        self.assertIsNone((await skills_api.list_skills("alpha", x_tenant_id=7))["skills"][0]["unavailable_reason"])
        await self._save_config("alpha", {"skills_enabled": False, "enabled_skills": ["overleaf-rt:overleaf-comments"]})
        details = await tools_api.api_binding_details("alpha", x_tenant_id=7)
        self.assertEqual(details["automatic_tools"], {})
        self.assertEqual(set(details["tools"]), {"overleaf_list_comments", "manual_only"})
        self.assertEqual(self.bindings["alpha"], ["overleaf_list_comments", "manual_only"])

    async def test_shared_automatic_tools_remain_until_last_skill_is_removed(self):
        root = Path(self.temp) / "shared"
        root.mkdir()
        for name in ("first", "second"):
            (root / f"{name}.md").write_text(f"---\nname: {name}\ndescription: {name}\nrequired-tools: [echo]\n---\nInstructions", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("shared", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="shared"))
        for selection, expected in ((["shared:first", "shared:second"], ("first", "second")),
                                    (["shared:second"], ("second",)), ([], None)):
            await self._save_config("alpha", {"enabled_skills": selection})
            details = await tools_api.api_binding_details("alpha", x_tenant_id=7)
            self.assertEqual(details["automatic_tools"].get("echo"), expected)
        # Selecting an unavailable skill does not fabricate its executor.
        self.assertEqual(self.bindings["alpha"], [])

    async def test_model_can_execute_automatically_bound_tool_without_manual_table_entry(self):
        from agent_platform_agent_loop import AgentLoop
        from agent_platform_llm import LlmResponse
        from agent_platform_session import Session
        from backend.agents.runtime.tests.loop_support import loop_context
        root = Path(self.temp) / "run"
        root.mkdir()
        (root / "demo.md").write_text("---\nname: demo\ndescription: Demo\nrequired-tools: [echo]\n---\nUse echo", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("run", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="run"))
        calls = []
        class Executor:
            async def execute(self, descriptor, arguments, context):
                calls.append(context.scope)
                return ToolResult(data={"ok": True})
        tools = self.runtime.require(TOOLS)
        tools.register_executor("echo", Executor())
        tools.register_tool(ToolDescriptor(name="echo", executor="echo", description="Echo", input_schema={"type": "object"}))
        await self._save_config("alpha", {"enabled_skills": ["run:demo"]})
        contribution = await self.extensions.prepare(AgentRunContext(7, "alpha", self.configs["alpha"], []))
        class Client:
            configured = True
            requests = 0
            async def complete(self, request):
                self.requests += 1
                if self.requests == 1:
                    return LlmResponse({"role": "assistant", "tool_calls": [{"id": "echo-1", "type": "function",
                        "function": {"name": "echo", "arguments": "{}"}}]}, finish_reason="tool_calls")
                return LlmResponse({"role": "assistant", "content": "done"}, finish_reason="stop")
        loop = AgentLoop(loop_context(Client(), tools=tools), key="alpha", tenant_id=7, session=Session(), model="fake",
                         tool_schemas=contribution.tool_schemas,
                         llm_params={"max_steps": 3, "max_tool_calls": 5, "max_wall_time": 10, "max_tokens": 64, "temperature": 0})
        loop.followup("run demo")
        await loop.when_idle()
        self.assertEqual(loop.answer_text(), "done")
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0].tenant_id, calls[0].agent_key), (7, "alpha"))
        self.assertEqual(self.bindings["alpha"], [])

    async def test_automatic_tools_keep_source_tenant_and_agent_boundaries(self):
        root = Path(self.temp) / "scoped-tool"
        root.mkdir()
        (root / "demo.md").write_text("---\nname: scoped\ndescription: Scoped\nrequired-tools: [secret]\n---\nInstructions", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("scoped", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="scoped-tool"))
        for key in self.configs:
            await self._save_config(key, {"enabled_skills": ["scoped:scoped"]})
        self.assertIn("secret", (await tools_api.api_binding_details("alpha", x_tenant_id=7))["automatic_tools"])
        self.assertNotIn("secret", (await tools_api.api_binding_details("alpha", x_tenant_id=8))["automatic_tools"])
        self.assertNotIn("secret", (await tools_api.api_binding_details("beta", x_tenant_id=7))["automatic_tools"])

    async def test_optional_tools_are_declared_not_inferred_and_installer_disable_is_respected(self):
        root = Path(self.temp) / "optional-tools"
        root.mkdir()
        (root / "demo.md").write_text("---\nname: optional\ndescription: Optional\ntools: [echo, skill_install]\n---\nAlso mentions delete_all, which is not a tool declaration.", encoding="utf-8")
        self.runtime.require(SKILLS).register_provider(FilesystemSkillProvider([
            SkillSource("optional", root, tenant_ids=(7,), agent_keys=("alpha",)),
        ], name="optional-tools"))
        tools = self.runtime.require(TOOLS)
        for name in ("echo", "delete_all"):
            tools.register_tool(ToolDescriptor(name=name, executor="example", description=name, input_schema={"type": "object"}))
        config = {"enabled_skills": ["optional:optional"], "skill_install_enabled": False}
        contribution = await self.extensions.prepare(AgentRunContext(7, "alpha", config, []))
        names = {tool["function"]["name"] for tool in contribution.tool_schemas}
        self.assertIn("echo", names)
        self.assertNotIn("delete_all", names)
        self.assertNotIn("skill_install", names)
        self.assertNotIn("skill_install", contribution.automatic_tools)

    async def test_next_model_request_sees_only_entry_summaries_and_current_readiness(self):
        from agent_platform_agent_loop import AgentLoop
        from agent_platform_llm import LlmResponse, LoopHooks
        from agent_platform_session import Session
        from backend.agents.runtime.tests.loop_support import loop_context
        config = {"enabled_skills": None}
        contribution = await self.extensions.prepare(AgentRunContext(7, "alpha", config, []))
        session = Session()
        session.append("user/message", {"content": "旧目录只有 skill-installer", "source": {
            "kind": "skill-catalog", "digest": "old-installer-only", "entries": [{"name": "skill-installer"}],
        }})
        class Client:
            configured = True
            requests = []
            async def complete(self, request):
                self.requests.append(request)
                return LlmResponse({"role": "assistant", "content": "done"}, finish_reason="stop")
        client = Client()
        loop = AgentLoop(loop_context(client, tools=self.runtime.require(TOOLS)), key="alpha", tenant_id=7,
                         session=session, model="fake", tool_schemas=contribution.tool_schemas,
                         hooks=LoopHooks(pre_step=contribution.pre_step),
                         llm_params={"max_steps": 3, "max_tool_calls": 5, "max_wall_time": 10,
                                     "max_tokens": 64, "temperature": 0})
        loop.followup("你现在有什么 skill")
        await loop.when_idle()
        catalogs = [event.data for event in session.events if event.data.get("source", {}).get("kind") == "skill-catalog"]
        self.assertEqual(len(catalogs), 2)
        entries = catalogs[-1]["source"]["entries"]
        self.assertEqual(len(entries), 2)
        overleaf = next(entry for entry in entries if entry["name"] == "overleaf")
        installer = next(entry for entry in entries if entry["name"] == "skill-installer")
        self.assertEqual(overleaf["package"], "overleaf")
        self.assertTrue(overleaf["available"])
        self.assertTrue(overleaf["model_loadable"])
        self.assertFalse(overleaf["tools_ready"])
        self.assertIsNone(overleaf["unavailable_reason"])
        self.assertTrue(installer["available"])
        self.assertTrue(installer["model_loadable"])
        sent = "\n".join(message.get("content", "") for message in client.requests[0].messages)
        self.assertIn(catalogs[-1]["content"], sent)
        self.assertIn("<available_skills>", sent)
        self.assertIn("- `overleaf`:", sent)
        self.assertIn("执行工具未全部就绪", sent)
        self.assertNotIn('"tools_ready":', sent)
        self.assertNotIn("<skill_content name=", sent)
        self.assertNotIn("<skill_instructions>", sent)
        self.assertNotIn("references/comments.md", sent)
        self.assertNotIn("overleaf-comments", sent)
        self.assertNotIn("overleaf_list_comments", {tool["function"]["name"] for tool in client.requests[0].tools})


if __name__ == "__main__":
    unittest.main()
