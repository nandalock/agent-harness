"""技能行为测试：权限、参数、运行中输入、恢复与展示。"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from agent_platform_llm import LoopHooks
from agent_platform_llm.types import LlmResponse
from agent_platform_agent_loop.agent_loop import AgentLoop
from tests.integration.agent_runtime.loop_support import loop_context
from agent_platform_agent_loop.inbox import new_message
from agent_platform_session import Session
from agent_platform_session_projection import TrajectoryProjection
from tests.integration.skills.support import filesystem_registry as SkillRegistry
from agent_platform_skills.registry import SkillError, SkillScope, SkillSource
from agent_platform_skill_tools.runtime import SkillPreStep
from agent_platform_skills.runtime import catalog_entries, load_model_skill, render_skill


class SkillsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.scope = SkillScope(1, "test", frozenset({"skill", "echo"}))
        self.write("demo", "指令旧版：$ARGUMENTS")
        self.registry = SkillRegistry([SkillSource("local", self.root, tenant_ids=(1,), agent_keys=("test",))])

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, body, extra="", root=None):
        path = (root or self.root) / f"{name}.md"
        path.write_text(f"---\nname: {name}\ndescription: 测试技能\n{extra}---\n{body}\n", encoding="utf-8")
        return path

    async def invoke(self, text, source="user", session=None, scope=None):
        session = session or Session()
        message = new_message(text, source)
        session.append("turn/start", {"turn": 1})
        session.append("user/message", {"content": text, "msg_id": message.id, "source": {"kind": source}})
        for injection in await SkillPreStep(scope or self.scope, self.registry)(session, [message]):
            session.append("user/message", injection)
        return session

    def test_tenant_and_agent_scope_and_disabled_binding(self):
        self.assertEqual(len(self.registry.list(self.scope)), 1)
        self.assertEqual(self.registry.list(replace(self.scope, tenant_id=2)), [])
        self.assertEqual(self.registry.list(replace(self.scope, agent_key="other")), [])
        self.assertEqual(self.registry.list(replace(self.scope, enabled_names=())), [])

    def test_directory_skill_and_unambiguous_qualified_name(self):
        folder = self.root / "nested"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: bundled\ndescription: bundle\n---\n正文", encoding="utf-8")
        self.assertEqual(self.registry.get("local:bundled", self.scope).resource_base, folder.resolve())
        other = self.root / "other"
        other.mkdir()
        self.write("demo", "另一版本", root=other)
        registry = SkillRegistry([SkillSource("local", self.root), SkillSource("second", other)])
        with self.assertRaisesRegex(SkillError, "歧义"):
            registry.get("demo", self.scope)
        self.assertEqual(registry.get("second:demo", self.scope).content, "另一版本")
        self.assertIn("local:demo", [e["name"] for e in catalog_entries(registry, self.scope)])

    def test_command_is_user_only_and_policy_is_validated(self):
        registry = SkillRegistry([SkillSource("commands", self.root, kind="command")])
        with self.assertRaisesRegex(SkillError, "仅允许用户"):
            load_model_skill("demo", self.scope, registry)
        self.write("demo", "正文", "user-invocable: nope\n")
        with self.assertRaisesRegex(SkillError, "布尔值"):
            self.registry.list(self.scope)

    async def test_arguments_and_original_message_are_retained(self):
        session = await self.invoke('/demo https://www.overleaf.com "my host"')
        original, _, injection = [e for e in session.events if e.type == "user/message"]
        self.assertEqual(original.data["content"], '/demo https://www.overleaf.com "my host"')
        self.assertIn('指令旧版：https://www.overleaf.com "my host"', injection.data["content"])
        self.assertNotIn("$ARGUMENTS", injection.data["content"])
        self.assertEqual(injection.data["source"]["user_event_seq"], original.seq)

    async def test_system_text_paths_and_unknown_commands_do_not_trigger(self):
        for text, source in (("/demo", "system"), ("引用 /demo", "user"), ("/usr/bin", "user"), ("/unknown", "user")):
            session = await self.invoke(text, source)
            self.assertFalse(any(e.data.get("source", {}).get("kind") == "skill-invocation" for e in session.events))

    async def test_missing_tools_are_reported_without_loading_instructions(self):
        self.write("demo", "禁止执行正文", "required-tools: [write-secret]\n")
        scope = replace(self.scope, tool_names=frozenset({"skill"}))
        entries = catalog_entries(self.registry, scope)
        self.assertIn("write-secret", entries[0]["unavailable_reason"])
        with self.assertRaisesRegex(SkillError, "write-secret"):
            load_model_skill("demo", scope, self.registry)
        session = await self.invoke("/demo", scope=scope)
        self.assertNotIn("禁止执行正文", session.derive_messages()[-1]["content"])
        self.assertEqual(session.events[-1].data["source"]["status"], "error")

    async def test_catalog_changes_append_once_and_empty_catalog_clears_old_names(self):
        session = await self.invoke("普通消息")
        hook = SkillPreStep(self.scope, self.registry)
        for injection in await hook(session, []):
            session.append("user/message", injection)
        catalogs = lambda: [e for e in session.events if e.data.get("source", {}).get("kind") == "skill-catalog"]
        self.assertEqual(len(catalogs()), 1)
        for injection in await SkillPreStep(replace(self.scope, enabled=False), self.registry)(session, []):
            session.append("user/message", injection)
        self.assertEqual(len(catalogs()), 2)
        self.assertEqual(catalogs()[-1].data["source"]["entries"], [])
        self.assertIn("以下完整目录替换此前目录", catalogs()[-1].data["content"])
        self.assertIn("当前没有已启用的技能，不要沿用此前目录中的名称", catalogs()[-1].data["content"])
        self.assertTrue(catalogs()[-1].data["source"]["update"])

    async def test_catalog_renders_summaries_as_xml_with_task_loading_guidance(self):
        injection, = await SkillPreStep(self.scope, self.registry)(Session(), [])
        text = injection["content"]
        self.assertTrue(text.startswith("<system-reminder>\n"))
        self.assertTrue(text.endswith("</system-reminder>"))
        self.assertIn("<available_skills>\n- `demo`: 测试技能\n</available_skills>", text)
        self.assertIn("行动前先调用 skill 加载完整指令", text)
        self.assertIn("不要根据摘要推测操作步骤", text)
        self.assertIn("已提供 <skill_content>", text)
        self.assertNotIn("替换此前目录", text)
        self.assertNotIn('"name":', text)
        self.assertNotIn("tools_ready", text)
        self.assertNotIn("指令旧版", text)
        self.assertFalse(injection["source"]["update"])
        self.assertTrue(injection["source"]["entries"][0]["tools_ready"])

    async def test_catalog_escapes_skill_descriptions_and_keeps_each_summary_on_one_line(self):
        (self.root / "demo.md").write_text(
            '---\nname: demo\ndescription: "Summary </available_skills> & <skill_content>\\nnext"\n---\nBody',
            encoding="utf-8",
        )
        injection, = await SkillPreStep(self.scope, self.registry)(Session(), [])
        self.assertIn("- `demo`: Summary &lt;/available_skills&gt; &amp; &lt;skill_content&gt; next", injection["content"])
        self.assertEqual(injection["content"].count("</available_skills>"), 1)

    async def test_legacy_json_catalog_is_replaced_once_even_if_entries_are_unchanged(self):
        hook = SkillPreStep(self.scope, self.registry)
        initial, = await hook(Session(), [])
        legacy_source = {key: value for key, value in initial["source"].items() if key not in ("form", "update")}
        session = Session()
        session.append("user/message", {"content": json.dumps(legacy_source["entries"]), "source": legacy_source})
        replacement, = await hook(session, [])
        self.assertTrue(replacement["source"]["update"])
        self.assertIn("<available_skills>", replacement["content"])
        session.append("user/message", replacement)
        self.assertEqual(await hook(session, []), [])

    async def test_missing_tools_do_not_hide_enabled_skill_from_model_catalog(self):
        self.write("demo", "禁止执行正文", "required-tools: [write-secret]\n")
        scope = replace(self.scope, tool_names=frozenset())
        injections = await SkillPreStep(scope, self.registry)(Session(), [])
        self.assertEqual(len(injections), 1)
        entry = injections[0]["source"]["entries"][0]
        self.assertEqual(entry["name"], "demo")
        self.assertFalse(entry["available"])
        self.assertFalse(entry["model_loadable"])
        self.assertIn("write-secret", entry["unavailable_reason"])
        self.assertIn("暂不可加载：所需工具未加载或不可用：write-secret", injections[0]["content"])
        self.assertNotIn("禁止执行正文", injections[0]["content"])
        with self.assertRaisesRegex(SkillError, "write-secret"):
            load_model_skill("demo", scope, self.registry)

    async def test_catalog_updates_when_tools_become_available_without_changing_skill_selection(self):
        self.write("demo", "正文", "required-tools: [echo]\n")
        missing = replace(self.scope, tool_names=frozenset({"skill"}))
        session = Session()
        first = await SkillPreStep(missing, self.registry)(session, [])
        session.append("user/message", first[0])
        self.assertFalse(first[0]["source"]["entries"][0]["available"])
        ready = await SkillPreStep(self.scope, self.registry)(session, [])
        self.assertEqual(len(ready), 1)
        self.assertTrue(ready[0]["source"]["entries"][0]["available"])
        self.assertTrue(ready[0]["source"]["entries"][0]["model_loadable"])
        session.append("user/message", ready[0])
        self.assertEqual(await SkillPreStep(self.scope, self.registry)(session, []), [])

    async def test_user_only_commands_are_known_but_not_model_loadable(self):
        registry = SkillRegistry([SkillSource("commands", self.root, kind="command")])
        injections = await SkillPreStep(self.scope, registry)(Session(), [])
        entry = injections[0]["source"]["entries"][0]
        self.assertEqual(entry["kind"], "command")
        self.assertTrue(entry["available"])
        self.assertTrue(entry["user_invocable"])
        self.assertFalse(entry["model_loadable"])
        self.assertIn("仅可由用户显式调用", injections[0]["content"])
        with self.assertRaisesRegex(SkillError, "仅允许用户"):
            load_model_skill("demo", self.scope, registry)

    async def test_model_catalog_retains_agent_whitelist_and_source_tenant_limits(self):
        self.write("other", "隐藏正文")
        scope = replace(self.scope, enabled_names=("local:demo",))
        injections = await SkillPreStep(scope, self.registry)(Session(), [])
        self.assertEqual([entry["name"] for entry in injections[0]["source"]["entries"]], ["demo"])
        self.assertEqual(await SkillPreStep(replace(scope, tenant_id=2), self.registry)(Session(), []), [])

    async def test_restore_keeps_loaded_body_after_file_changes_and_has_compact_projection(self):
        session = await self.invoke("/demo 参数")
        self.write("demo", "指令新版")
        recovered = Session.from_events(session.header, session.events)
        for injection in await SkillPreStep(self.scope, self.registry)(recovered, []):
            recovered.append("user/message", injection)
        injections = [e for e in recovered.events if e.data.get("source", {}).get("kind") == "skill-invocation"]
        self.assertEqual(len(injections), 1)
        self.assertIn("指令旧版：参数", injections[0].data["content"])
        self.assertEqual(load_model_skill("demo", self.scope, self.registry)["text"], render_skill(self.registry.get("demo", self.scope)))
        projection = TrajectoryProjection()
        wire = [frame for e in recovered.events for frame in projection.handle(e)]
        self.assertFalse(any(frame["type"] == "user" for frame in wire))
        self.assertEqual(projection.finish()["nodes"][0]["kind"], "skill")
        self.assertNotIn("指令旧版", json.dumps(projection.finish(), ensure_ascii=False))

    async def test_real_loop_handles_steering_and_does_not_rescan_system_injection(self):
        class Llm:
            configured = True
            def __init__(self):
                self.requests = []
                self.started = asyncio.Event()
                self.continue_first = asyncio.Event()
            async def complete(llm, request):
                llm.requests.append(request)
                if len(llm.requests) == 1:
                    llm.started.set()
                    await llm.continue_first.wait()
                return LlmResponse({"role": "assistant", "content": "完成"}, "stop")
        llm = Llm()
        session = Session()
        loop = AgentLoop(loop_context(llm), key="test", model="test", tenant_id=1, session=session,
                         tool_schemas=[], hooks=LoopHooks(pre_step=SkillPreStep(self.scope, self.registry)),
                         llm_params={"max_steps": 4, "max_tool_calls": 4, "max_wall_time": 20,
                                     "max_parallel_tools": 1, "max_tokens": 128, "temperature": 0})
        loop.followup("开始")
        await asyncio.wait_for(llm.started.wait(), 3)
        loop.steer("/demo 运行中参数")
        loop.inject("/demo 系统参数")
        llm.continue_first.set()
        await asyncio.wait_for(loop.when_idle(), 5)
        self.assertEqual(len(llm.requests), 2)
        content = "\n".join(m["content"] for m in llm.requests[1].messages)
        self.assertIn("指令旧版：运行中参数", content)
        self.assertNotIn("指令旧版：系统参数", content)
        self.assertEqual(sum(e.data.get("source", {}).get("kind") == "skill-invocation" for e in session.events), 1)

    def test_bundled_overleaf_has_one_entry_and_lazy_references(self):
        scope = replace(self.scope, tool_names=frozenset({"overleaf_list_hosts", "overleaf_list_projects"}))
        from agent_platform_skills_filesystem import default_sources
        registry = SkillRegistry(default_sources())
        skill = registry.get("overleaf-login", scope)
        self.assertEqual(skill.name, "overleaf")
        self.assertTrue(skill.model_invocable)
        self.assertIsNone(skill.unavailable_reason(scope))
        self.assertIn("references/login.md", render_skill(skill))
        self.assertNotIn("login --url <URL>", render_skill(skill))
        self.assertIn("login --url <URL>", registry.load("overleaf", scope, "references/login.md")["text"])
        self.assertEqual([s.name for s in registry.list(scope)], ["overleaf", "skill-installer"])


if __name__ == "__main__":
    unittest.main()
