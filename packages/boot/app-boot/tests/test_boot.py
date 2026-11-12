import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform_app_boot import compose_plugins, load_config, resolve_config_path
from minidsh_cordis_plugin_include import PluginConfiguration


class BootConfigTests(unittest.TestCase):
    def test_explicit_config_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.yaml"
            path.write_text("version: 1\n", encoding="utf-8")
            with patch.dict(os.environ, {"PLUGIN_CONFIG": str(path)}, clear=True):
                self.assertEqual(resolve_config_path(), path)

    def test_unconfigured_boot_ignores_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config" / "plugins.yaml"
            config.parent.mkdir()
            config.write_text("version: 1\n", encoding="utf-8")
            old = Path.cwd()
            os.chdir(root)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    self.assertIsNone(resolve_config_path())
            finally:
                os.chdir(old)

    def test_profile_layers_apply_defaults_includes_and_ordered_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cordis.yml"
            profile_patch = root.with_name("cordis.patch.yml")
            launch_patch = root.with_name("launch.yml")
            root.with_name("included.yml").write_text(
                "patches: [{id: memory, config: {included: true, order: include}}]\n", encoding="utf-8",
            )
            root.write_text(
                "includes: [included.yml]\npatches: [{id: memory, config: {order: root}}]\n", encoding="utf-8",
            )
            profile_patch.write_text("- id: memory\n  config: {order: profile}\n", encoding="utf-8")
            launch_patch.write_text("patches: [{id: memory, config: {order: launch}}]\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "MINIDSH_PROFILE_CONFIG": str(root), "MINIDSH_PROFILE_PATCH": str(profile_patch),
                "MINIDSH_PLUGIN_PATCH": str(launch_patch),
            }, clear=True):
                def memory():
                    return next(row for row in load_config().plugins if row.id == "memory")

                self.assertEqual(memory().config["order"], "launch")
                self.assertTrue(memory().config["included"])
                os.environ.pop("MINIDSH_PLUGIN_PATCH")
                self.assertEqual(memory().config["order"], "profile")
                profile_patch.unlink()
                self.assertEqual(memory().config["order"], "root")

    def test_legacy_profile_root_is_read_until_the_canonical_root_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cordis.yml"
            legacy = root.with_name("plugins.yaml")
            legacy.write_text("version: 1\n", encoding="utf-8")
            with patch.dict(os.environ, {"MINIDSH_PROFILE_CONFIG": str(root)}, clear=True):
                self.assertEqual(resolve_config_path(), legacy)
                root.write_text("version: 1\n", encoding="utf-8")
                self.assertEqual(resolve_config_path(), root)

    def test_default_composition_has_no_host_mcp_scan(self):
        config = compose_plugins(PluginConfiguration())
        names = {entry.name for entry in config.plugins}
        self.assertEqual(len(config.plugins), 42)
        self.assertIn("agent-platform.mcp-database", names)
        self.assertIn("agent-platform.plugin-inventory", names)
        self.assertNotIn("agent-platform.mcp-client", names)


if __name__ == "__main__":
    unittest.main()
