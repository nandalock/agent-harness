"""技能行为测试：权限、参数、运行中输入、恢复与展示。"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from backend.agents.runtime.llm import LoopHooks
from backend.agents.runtime.llm.types import LlmResponse
from backend.agents.runtime.loop.agent_loop import AgentLoop
from backend.agents.runtime.loop.inbox import new_message
from backend.agents.runtime.session import Session
from backend.agents.runtime.session.projections import TrajectoryProjection
from backend.skills.registry import SkillError, SkillRegistry, SkillScope, SkillSource, get_skill_registry
from backend.skills.runtime import SkillPreStep, catalog_entries, load_model_skill, render_skill


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
        registry = SkillRegistry([*self.registry.sources, SkillSource("second", other)])
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
        loop = AgentLoop(key="test", llm=llm, model="test", tenant_id=1, session=session,
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

    def test_bundled_overleaf_commands_have_correct_dependencies(self):
        scope = replace(self.scope, tool_names=frozenset({"overleaf_list_hosts", "overleaf_list_projects"}))
        registry = get_skill_registry()
        command = registry.get("overleaf-login", scope)
        self.assertFalse(command.model_invocable)
        self.assertIsNone(command.unavailable_reason(scope))
        self.assertIn("login --url <URL>", render_skill(command, "https://www.overleaf.com"))
        self.assertEqual(len(registry.list(scope)), 7)


if __name__ == "__main__":
    unittest.main()
