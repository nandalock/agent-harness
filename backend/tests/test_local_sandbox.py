"""Real native confinement tests. Never run outside writes without confinement."""
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from agent_platform_sandbox.backends.local import LocalProvider
from agent_platform_sandbox.errors import SandboxUnavailableError
from agent_platform_sandbox.executor import SandboxExecutor
from agent_platform_sandbox.plugin import SANDBOX, LocalSandboxPlugin, DockerSandboxPlugin
from agent_platform_sandbox.vocabulary import SandboxExecutionPolicy, SandboxPolicy
from agent_platform_tool_system.context import ToolContext
from agent_platform_tool_system.descriptor import ToolDescriptor, SandboxToolConfig


class NativeSandboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Some Windows AppContainer-labelled temp trees cannot be granted to a
        # low-integrity token; use the same owned data root as real sessions.
        base = Path.home() / ".minidsh" / "sandbox-tests"
        base.mkdir(parents=True, exist_ok=True)
        # mkdir inherits the user's real workspace ACL; mkdtemp's Windows
        # private DACL is intentionally not a normal session-directory ACL.
        self.directory = base / uuid.uuid4().hex
        self.directory.mkdir()
        self.root = self.directory / "workspace"
        self.root.mkdir()
        self.outside = self.directory / "outside.txt"

    def tearDown(self):
        shutil.rmtree(self.directory)

    async def execute(self, mode, code, runtime="python", timeout=10):
        descriptor = ToolDescriptor(name=runtime, type="sandbox", transport="", server_id=0, schema={},
                                    sandbox=SandboxToolConfig(runtime, "", timeout_s=timeout))
        context = ToolContext(sandbox_policy=SandboxExecutionPolicy(mode, str(self.root)))
        return await SandboxExecutor(provider=LocalProvider()).execute(
            descriptor, {"code" if runtime == "python" else "command": code}, context)

    @unittest.skipUnless(sys.platform == "win32" or shutil.which("bwrap") or sys.platform == "darwin", "Native runner not installed")
    async def test_workspace_write_and_readonly_are_enforced(self):
        result = await self.execute("workspace-write", "from pathlib import Path;Path('inside.txt').write_text('ok');print('native-ok')")
        self.assertEqual(result.get("exit_code"), 0, result)
        self.assertTrue((self.root / "inside.txt").is_file())
        result = await self.execute("workspace-write", f"from pathlib import Path;Path({str(self.outside)!r}).write_text('bad')")
        self.assertNotEqual(result.get("exit_code"), 0, result)
        self.assertFalse(self.outside.exists())
        result = await self.execute("read-only", "from pathlib import Path;Path('denied.txt').write_text('bad')")
        self.assertNotEqual(result.get("exit_code"), 0, result)
        self.assertFalse((self.root / "denied.txt").exists())

    async def test_full_access_is_direct_and_uses_host_working_directory(self):
        with patch.object(LocalProvider, "confine", side_effect=AssertionError("must not confine full access")):
            result = await self.execute("danger-full-access", f"from pathlib import Path;Path({str(self.outside)!r}).write_text('ok');print(Path.cwd())")
        self.assertEqual(result.get("exit_code"), 0, result)
        self.assertTrue(self.outside.is_file())
        self.assertIn(str(self.root), result["stdout"])

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell")
    async def test_powershell_writes_inside_native_workspace(self):
        result = await self.execute("workspace-write", "Set-Content -LiteralPath inside.txt -Value native; Get-Location", "powershell")
        self.assertEqual(result.get("exit_code"), 0, result)
        self.assertTrue((self.root / "inside.txt").is_file())

    async def test_cancellation_or_timeout_stops_process_tree(self):
        child = f"import time;from pathlib import Path;time.sleep(1);Path({str(self.outside)!r}).write_text('leaked')"
        code = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
        result = await self.execute("danger-full-access", code, timeout=.3)
        self.assertIn("超时", result.get("error", ""))
        await asyncio.sleep(1.2)
        self.assertFalse(self.outside.exists(), "Timed-out command left a live descendant")

    @unittest.skipUnless(sys.platform == "win32" or shutil.which("bwrap") or sys.platform == "darwin", "Native runner not installed")
    async def test_tools_use_the_plugin_owned_sandbox_service(self):
        from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
        from agent_platform_plugin_sdk import SETTINGS, TOOLS, ExecutionScope, ToolCall, ToolContext as SdkContext
        from agent_platform_tools_default import ToolsDefaultPlugin
        from agent_platform_sandbox_tools import SandboxToolsPlugin

        class Settings:
            async def get(self, namespace):
                return {}

            async def set(self, namespace, value):
                pass

        runtime = PluginRuntime({"plugins": [
            {"id": "tools", "name": "agent-platform.tools-default"},
            {"id": "sandbox-provider", "name": "agent-platform.sandbox-local"},
            {"id": "sandbox-tools", "name": "agent-platform.sandbox-tools"},
        ]}, catalog=MappingCatalog({
            "agent-platform.tools-default": ToolsDefaultPlugin,
            "agent-platform.sandbox-local": LocalSandboxPlugin,
            "agent-platform.sandbox-tools": SandboxToolsPlugin,
        }), host_services={SETTINGS: Settings()})
        try:
            await runtime.start()
            self.assertIsInstance(runtime.require(SANDBOX), LocalProvider)
            result = await runtime.require(TOOLS).execute(
                ToolCall(call_id="native-test", name="python", arguments={"code": "print('plugin-native-ok')"}),
                SdkContext(scope=ExecutionScope(tenant_id=1, agent_key="test"), visible_tool_names=frozenset({"python"}),
                           host_context=ToolContext(sandbox_policy=SandboxExecutionPolicy("workspace-write", str(self.root)))),
            )
            self.assertEqual(result.status, "success", result)
            self.assertEqual(result.data["exit_code"], 0, result)
            self.assertIn("plugin-native-ok", result.data["stdout"])
        finally:
            await runtime.aclose()


class BackendSelectionTests(unittest.TestCase):
    def test_init_defaults_to_native_and_does_not_probe_docker(self):
        from agent_platform_sandbox.runtime import get_sandbox_provider, init_sandbox, set_sandbox_provider
        previous = get_sandbox_provider()
        try:
            with patch.dict(os.environ, {}, clear=True), patch("agent_platform_sandbox.runtime.resolve_workspace_root", return_value=str(Path.cwd())), patch("agent_platform_sandbox.runtime.probe_workspace_root") as probe:
                self.assertIsInstance(init_sandbox(), LocalProvider)
                probe.assert_not_called()
                self.assertEqual(init_sandbox(backend="docker", probe=False).backend, "docker")
        finally:
            set_sandbox_provider(previous)

    def test_native_and_docker_publish_the_same_service(self):
        self.assertEqual(LocalSandboxPlugin.spec.provides, (SANDBOX.ref,))
        self.assertEqual(DockerSandboxPlugin.spec.provides, (SANDBOX.ref,))

    def test_linux_does_not_fall_back_to_unrestricted_spawn(self):
        with patch("sys.platform", "linux"), patch("shutil.which", return_value=None):
            with self.assertRaises(SandboxUnavailableError):
                LocalProvider().confine(["true"], SandboxPolicy("read-only", str(Path.cwd())))

    def test_linux_profiles_only_add_writable_roots_for_workspace_mode(self):
        with patch("sys.platform", "linux"), patch("shutil.which", return_value="/usr/bin/bwrap"):
            readonly = LocalProvider().confine(["true"], SandboxPolicy("read-only", str(Path.cwd())))
            writable = LocalProvider().confine(["true"], SandboxPolicy("workspace-write", str(Path.cwd())))
        self.assertIn("--ro-bind", readonly.argv)
        self.assertNotIn("--bind", readonly.argv)
        self.assertIn("--bind", writable.argv)
        self.assertIn("--tmpfs", writable.argv)

    def test_macos_profiles_deny_writes_and_explicitly_allow_workspace(self):
        with patch("sys.platform", "darwin"), patch("shutil.which", return_value="/usr/bin/sandbox-exec"):
            readonly = LocalProvider().confine(["true"], SandboxPolicy("read-only", str(Path.cwd())))
            writable = LocalProvider().confine(["true"], SandboxPolicy("workspace-write", str(Path.cwd())))
        self.assertIn("(deny file-write*)", readonly.argv[2])
        self.assertNotIn("(allow file-write*", readonly.argv[2])
        self.assertIn("(allow file-write*", writable.argv[2])


if __name__ == "__main__":
    unittest.main()
