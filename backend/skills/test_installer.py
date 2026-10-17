"""安装行为回归：完整包、路径边界、租户隔离和真实聊天工具循环。"""
import asyncio
from dataclasses import replace
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from backend.skills import installer
from backend.skills.registry import SkillError, SkillRegistry, SkillScope, default_sources
from backend.skills.runtime import SkillPreStep, load_model_skill
from backend.skills.tool import SkillInstallExecutor, skill_descriptor, skill_install_descriptor
from backend.tool_system.context import ToolContext

COMMIT = "a" * 40
SOURCE = "https://github.com/example/skills/tree/main/skills/demo"
INSTRUCTIONS = "---\nname: demo\ndescription: A demo skill\n---\nRead references/guide.md and run scripts/check.py.\n"


def archive(files=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, content in (files or {
            "repo/skills/demo/SKILL.md": INSTRUCTIONS,
            "repo/skills/demo/scripts/check.py": "raise RuntimeError('must not execute during installation')",
            "repo/skills/demo/references/guide.md": "Reference content",
            "repo/skills/demo/assets/image.bin": b"\x00\xff\x01",
            "repo/skills/other/SKILL.md": "not part of this skill",
        }).items():
            package.writestr(name, content)
    return data.getvalue()


class InstallerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"SKILL_INSTALL_ROOT": self.directory.name, "SKILL_SOURCES": "[]"})
        self.env.start()
        self.scope = SkillScope(7, "assistant", frozenset({"skill", "skill_install"}))
        self.download = AsyncMock(side_effect=[json.dumps({"sha": COMMIT}).encode(), archive()])
        self.network = patch.object(installer, "_download", self.download)
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.env.stop()
        self.directory.cleanup()

    async def test_complete_package_is_immediately_discovered_and_isolated(self):
        registry = SkillRegistry([], include_installed=True)  # 在安装前创建的注册表也能看到新包
        self.assertEqual(registry.list(self.scope), [])
        result = await installer.install_skill(SOURCE, self.scope)
        self.assertEqual((result["key"], result["commit"], result["files"]), ("installed:demo", COMMIT, 4))
        skill = registry.get("installed:demo", self.scope)
        self.assertTrue((skill.resource_base / "scripts/check.py").is_file())
        self.assertEqual((skill.resource_base / "assets/image.bin").read_bytes(), b"\x00\xff\x01")
        self.assertEqual(load_model_skill("demo", self.scope, registry, "references/guide.md")["text"], "Reference content")
        self.assertFalse((skill.resource_base.parent / "other").exists())
        self.assertEqual(registry.list(replace(self.scope, tenant_id=8)), [])
        self.assertEqual(registry.list(replace(self.scope, agent_key="another")), [])
        self.assertEqual(registry.list(replace(self.scope, enabled_names=())), [])
        metadata = json.loads((skill.resource_base / ".installation.json").read_text())
        self.assertEqual(metadata["commit"], COMMIT)
        self.assertTrue(self.download.await_args_list[-1].args[0].endswith("/zip/" + COMMIT))

    async def test_duplicate_install_does_not_overwrite(self):
        await installer.install_skill(SOURCE, self.scope)
        self.download.side_effect = [json.dumps({"sha": COMMIT}).encode(), archive({"repo/skills/demo/SKILL.md": INSTRUCTIONS.replace("Read", "Changed")})]
        with self.assertRaisesRegex(SkillError, "已安装"):
            await installer.install_skill(SOURCE, self.scope)
        skill = SkillRegistry([], include_installed=True).get("demo", self.scope)
        self.assertTrue(skill.content.startswith("Read"))

    def test_supported_sources_and_branch_names(self):
        self.assertEqual(installer.parse_source("demo").path, "skills/.curated/demo")
        self.assertEqual(installer.parse_source(SOURCE.replace("/tree/", "/blob/") + "/SKILL.md").path, "skills/demo")
        parsed = installer.parse_source(SOURCE.replace("main", "feature/topic"), "feature/topic")
        self.assertEqual((parsed.ref, parsed.path), ("feature/topic", "skills/demo"))
        self.assertEqual(installer.parse_source("https://github.com/example/skill").ref, "HEAD")
        for source in ("http://github.com/a/b", "https://github.com.evil/a/b", "https://github.com@evil/a/b",
                       "https://github.com/a/b/tree/main/../secret", "https://github.com/a/b/tree/main/%2e%2e/x",
                       "https://github.com/a/b/tree/main/C:%5csecret", "https://github.com/a/b/tree/main/..%20/x"):
            with self.subTest(source=source), self.assertRaises(SkillError):
                installer.parse_source(source)

    def test_rejects_unsafe_archives_without_publishing(self):
        cases = [archive({"repo/skills/demo/../../escape": "bad"}),
                 archive({"repo/skills/demo/.. /escape": "bad"}),
                 archive({"repo/skills/demo/README.md": "missing instruction"}),
                 archive({"repo/skills/demo/SKILL.md": "bad metadata"}),
                 archive({"repo/skills/demo/SKILL.md": INSTRUCTIONS, "repo/skills/demo/skill.md": "duplicate"})]
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as package:
            package.writestr("repo/skills/demo/SKILL.md", INSTRUCTIONS)
            link = zipfile.ZipInfo("repo/skills/demo/scripts/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(link, "/etc/passwd")
        cases.append(data.getvalue())
        for payload in cases:
            with self.subTest(size=len(payload)), self.assertRaises((SkillError, ValueError)):
                installer._publish(payload, installer.parse_source(SOURCE), COMMIT, self.scope)
            self.assertEqual(SkillRegistry([], include_installed=True).list(self.scope), [])

    def test_unpacked_size_and_file_count_are_bounded(self):
        for setting in ("MAX_PACKAGE_BYTES", "MAX_PACKAGE_FILES"):
            with patch.object(installer, setting, 1), self.assertRaisesRegex(SkillError, "超过限制"):
                installer._publish(archive(), installer.parse_source(SOURCE), COMMIT, self.scope)
        self.assertEqual(SkillRegistry([], include_installed=True).list(self.scope), [])

    async def test_listing_reports_existing_installations(self):
        await installer.install_skill(SOURCE, self.scope)
        self.download.side_effect = None
        self.download.return_value = json.dumps([{"name": "demo", "type": "dir"}, {"name": "other", "type": "dir"},
                                                {"name": "README.md", "type": "file"}]).encode()
        rows = await installer.list_available(self.scope)
        self.assertEqual([(r["name"], r["installed"]) for r in rows], [("demo", True), ("other", False)])

    async def test_install_preserves_whitelist_and_reports_missing_tools(self):
        self.download.side_effect = [json.dumps({"sha": COMMIT}).encode(), archive({
            "repo/skills/demo/SKILL.md": INSTRUCTIONS.replace("description: A demo skill", "description: A demo skill\nrequired-tools: [missing-tool]")})]
        restricted = replace(self.scope, enabled_names=("platform:skill-installer",))
        result = await installer.install_skill(SOURCE, restricted)
        self.assertFalse(result["visible"])
        self.assertIn("missing-tool", result["unavailable_reason"])
        self.assertEqual(SkillRegistry([], include_installed=True).list(restricted), [])

    async def test_cancelled_download_does_not_leave_an_installation(self):
        started = asyncio.Event()
        async def waiting(*args):
            started.set()
            await asyncio.Event().wait()
        self.download.side_effect = waiting
        task = asyncio.create_task(installer.install_skill(SOURCE, self.scope))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(SkillRegistry([], include_installed=True).list(self.scope), [])

    async def test_api_catalog_exposes_installer_without_manual_bindings(self):
        from backend.agents.runtime import AgentRuntime
        from backend.api.skills import list_skills
        agent = AgentRuntime("assistant", {"config": {}})
        registry = type("Tools", (), {"get_bindings": lambda _, key: []})()
        with patch("backend.api.skills.get_agent", return_value=agent), \
                patch("backend.api.skills.get_registry", return_value=registry), \
                patch.object(agent, "_cfg", return_value={}):
            result = await list_skills("assistant", x_tenant_id=7)
        entry = next(row for row in result["skills"] if row["key"] == "platform:skill-installer")
        self.assertIsNone(entry["unavailable_reason"])

    async def test_executor_requires_context_and_honors_disable_and_whitelist(self):
        executor = SkillInstallExecutor()
        descriptor = skill_install_descriptor()
        self.assertIn("error", await executor.execute(descriptor, {"action": "install", "source": SOURCE}))
        context = ToolContext(tenant_id=7, agent_id="assistant", visible_tool_names=self.scope.tool_names)
        agent = type("Agent", (), {"_cfg": lambda _: {"skill_install_enabled": False}})()
        with patch("backend.agents.get_agent", return_value=agent):
            self.assertIn("停用", (await executor.execute(descriptor, {"action": "install", "source": SOURCE}, context))["error"])
        self.assertFalse(installer.install_enabled({"enabled_skills": []}))
        self.assertFalse(installer.install_enabled({"skills_enabled": False}))
        self.download.assert_not_awaited()
        agent._cfg = lambda: {}
        with patch("backend.agents.get_agent", return_value=agent):
            result = await executor.execute(descriptor, {"action": "install", "source": SOURCE, "tenant_id": 999}, context)
        self.assertEqual(result["rows"][0]["status"], "installed")
        self.assertEqual(SkillRegistry([], include_installed=True).list(replace(self.scope, tenant_id=999)), [])

    async def test_chat_loop_installs_and_loads_skill_in_the_same_turn(self):
        from backend.agents.runtime.llm import LoopHooks
        from backend.agents.runtime.llm.types import LlmResponse
        from backend.agents.runtime.loop.agent_loop import AgentLoop
        from backend.agents.runtime.session import Session
        from backend.tool_system.registry.registry import ToolRegistry, _to_openai_function
        from backend.tool_system.runtime.runtime import ToolRuntime

        descriptors = [skill_descriptor(), skill_install_descriptor()]
        tools = ToolRegistry()
        for descriptor in descriptors:
            tools.register_builtin(descriptor)
        runtime = ToolRuntime(tools)
        registry = SkillRegistry(default_sources(), include_installed=True)
        requests = []

        class Llm:
            configured = True
            async def complete(self, request):
                requests.append(request)
                if len(requests) <= 2:
                    name, args = (("skill_install", {"action": "install", "source": SOURCE}) if len(requests) == 1
                                  else ("skill", {"name": "installed:demo"}))
                    return LlmResponse({"role": "assistant", "content": "", "tool_calls": [{
                        "id": f"call-{len(requests)}", "type": "function", "function": {
                            "name": name, "arguments": json.dumps(args)}}]}, "tool_calls")
                return LlmResponse({"role": "assistant", "content": "安装完成"}, "stop")

        session = Session()
        loop = AgentLoop(key="assistant", llm=Llm(), model="test", tenant_id=7, session=session,
                         tool_schemas=[_to_openai_function(d.schema) for d in descriptors],
                         hooks=LoopHooks(pre_step=SkillPreStep(self.scope, registry)),
                         llm_params={"max_steps": 5, "max_tool_calls": 5, "max_wall_time": 20,
                                     "max_parallel_tools": 1, "max_tokens": 128, "temperature": 0})
        agent = type("Agent", (), {"_cfg": lambda _: {}})()
        with patch("backend.agents.get_agent", return_value=agent), \
                patch("backend.tool_system.runtime.scheduler.get_tool_runtime", return_value=runtime):
            loop.followup("$skill-installer " + SOURCE)
            await asyncio.wait_for(loop.when_idle(), 10)
        self.assertEqual(len(requests), 3)
        invocations = [e for e in session.events if e.data.get("source", {}).get("kind") == "skill-invocation"]
        self.assertEqual(invocations[0].data["source"]["name"], "platform:skill-installer")
        catalogs = [e for e in session.events if e.data.get("source", {}).get("kind") == "skill-catalog"]
        self.assertIn("demo", [e["name"] for e in catalogs[-1].data["source"]["entries"]])
        results = [e.data for e in session.events if e.type == "tool/result"]
        self.assertEqual(len(results), 2)
        self.assertIn("Read references/guide.md", json.dumps(results[-1]))


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirects_and_oversize_responses_are_rejected(self):
        class Response:
            status = 200
            content_length = None
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def iter_chunked(self, size):
                yield b"123"
                yield b"456"
        response = Response()
        response.content = response
        options = []
        class Session:
            def get(self, url, **kwargs):
                options.append(kwargs)
                return response
        with patch("backend.skills.installer.get_http_session", AsyncMock(return_value=Session())):
            for status, length in ((302, None), (200, 100), (200, None)):
                response.status, response.content_length = status, length
                with self.subTest(status=status, length=length), self.assertRaises(SkillError):
                    await installer._download("https://api.github.com/repos/a/b", limit=5)
        self.assertTrue(all(option["allow_redirects"] is False for option in options))


if __name__ == "__main__":
    unittest.main()
