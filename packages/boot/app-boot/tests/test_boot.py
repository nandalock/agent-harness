import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform_app_boot import compose_plugins, resolve_config_path
from minidsh_cordis_plugin_include import PluginConfiguration


class BootConfigTests(unittest.TestCase):
    def test_explicit_config_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.yaml"
            path.write_text("version: 1\n", encoding="utf-8")
            with patch.dict(os.environ, {"PLUGIN_CONFIG": str(path)}, clear=True):
                self.assertEqual(resolve_config_path(), path)

    def test_working_directory_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config" / "plugins.yaml"
            config.parent.mkdir()
            config.write_text("version: 1\n", encoding="utf-8")
            old = Path.cwd()
            os.chdir(root)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(resolve_config_path(), config)
            finally:
                os.chdir(old)

    def test_default_composition_has_no_host_mcp_scan(self):
        config = compose_plugins(PluginConfiguration())
        names = {entry.name for entry in config.plugins}
        self.assertEqual(len(config.plugins), 42)
        self.assertIn("agent-platform.mcp-database", names)
        self.assertIn("agent-platform.plugin-inventory", names)
        self.assertNotIn("agent-platform.mcp-client", names)


if __name__ == "__main__":
    unittest.main()
