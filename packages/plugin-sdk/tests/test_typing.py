"""Ensure the shipped typed key rejects an incompatible service implementation."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipIf(importlib.util.find_spec("mypy") is None, "install plugin-sdk[dev] for static contract checks")
class TypingTests(unittest.TestCase):
    def test_service_key_prevents_widening_to_object(self):
        source = """
from agent_platform_plugin_sdk import TOOLS, PluginContext

def wrong_service(ctx: PluginContext) -> None:
    ctx.provide(TOOLS, object())
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong_service.py"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "mypy", "--strict", str(path)],
                                    cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("provide", result.stdout)
        self.assertNotIn("Cannot find implementation", result.stdout)


if __name__ == "__main__":
    unittest.main()
