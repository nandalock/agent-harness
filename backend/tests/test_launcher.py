"""Local launch environment and process lifecycle, with no live services."""
import argparse
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import minidsh as harness


class LauncherTests(unittest.TestCase):
    def args(self, **values):
        return argparse.Namespace(action="dev", env_file=".env.local", backend_port=18000,
                                  frontend_port=14000, backend_only=False, **values)

    def test_local_env_does_not_read_docker_secrets_and_shell_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("JWT_SECRET=docker-only\n", encoding="utf-8")
            (root / ".env.local").write_text("DATABASE_URL=from-file\n", encoding="utf-8")
            with patch.object(harness, "ROOT", root), patch.object(Path, "home", return_value=root), patch.dict(os.environ, {"DATABASE_URL": "from-shell"}, clear=True):
                env = harness.environment(self.args())
            self.assertEqual(env["DATABASE_URL"], "from-shell")
            self.assertNotIn("JWT_SECRET", env)
            self.assertEqual(env["BACKEND_URL"], "http://127.0.0.1:18000")
            self.assertEqual(env["BUILTIN_MCP_PORT"], "19001")
            self.assertIn("14000", env["CORS_ORIGINS"])
            self.assertEqual(env["NEXT_DIST_DIR"], ".next-local")

    def test_busy_port_is_detected_without_stopping_existing_service(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            args = self.args()
            args.backend_port = sock.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "occupied or reserved"):
                harness.check_ports(args, {"BUILTIN_MCP_PORT": "19001", "PAPER_MCP_PORT": "19002"})

    def test_duplicate_ports_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "distinct"):
            harness.check_ports(self.args(), {"BUILTIN_MCP_PORT": "18000", "PAPER_MCP_PORT": "19002"})

    def test_minidsh_home_controls_workspace_skills_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text("", encoding="utf-8")
            data_home = root / "custom-data"
            with patch.object(harness, "ROOT", root), patch.dict(os.environ, {"MINIDSH_HOME": str(data_home)}, clear=True), patch.object(Path, "home", return_value=root):
                env = harness.environment(self.args())
            self.assertEqual(env["SANDBOX_WORKSPACE_ROOT"], str(data_home / "workspaces"))
            self.assertEqual(env["SKILL_INSTALL_ROOT"], str(data_home / "skills"))
            self.assertEqual(env["PAPER_CACHE_DIR"], str(data_home / "cache" / "paper-mcp"))

    def test_command_accepts_component_working_directory(self):
        with patch.object(harness.subprocess, "run") as run:
            harness.command(["node", "build"], cwd="frontend")
        self.assertEqual(run.call_args.kwargs["cwd"], "frontend")

    def test_exited_children_are_not_signalled(self):
        child = Mock()
        child.poll.return_value = 0
        harness.stop(child)
        child.send_signal.assert_not_called()

    def test_local_mcp_mapping_is_in_memory_and_optional_servers_can_be_disabled(self):
        from backend.plugin_host import _mcp_plugin_entries
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {"id": 1, "name": "本地 MCP", "transport": "http", "url": "http://localhost:9001/mcp"},
            {"id": 2, "name": "论文 MCP", "transport": "http", "url": "http://localhost:9002/mcp"},
            {"id": 3, "name": "overleaf", "transport": "stdio", "command": "/container/python"},
        ]
        with patch("backend.core.connection.get_conn", return_value=connection), patch.dict(os.environ, {
            "BUILTIN_MCP_PORT": "19001", "PAPER_MCP_PORT": "19002", "OVERLEAF_ENABLED": "false", "PLUGIN_MCP_AUTO": "true",
        }):
            entries = _mcp_plugin_entries()
        self.assertEqual(entries, [])  # managed services never become duplicate auto clients
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertTrue(cursor.execute.call_args.args[0].startswith("SELECT"))


if __name__ == "__main__":
    unittest.main()
