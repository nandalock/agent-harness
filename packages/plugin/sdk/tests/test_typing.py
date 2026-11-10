"""Ensure the shipped typed key rejects an incompatible service implementation."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipIf(importlib.util.find_spec("mypy") is None, "install plugin-sdk[dev] for static contract checks")
class TypingTests(unittest.TestCase):
    def test_service_key_prevents_widening_to_object(self):
        source = """
from agent_platform_plugin_sdk import TOOLS
from minidsh_cordis import Context

def wrong_service(ctx: Context) -> None:
    ctx.provide(TOOLS, object())
"""
        with tempfile.TemporaryDirectory() as directory:
            # Static analyzers do not execute PEP 660 editable import hooks.
            # Materialize the imported SDK under its real import name, as in a
            # regular wheel install, so this tests the typed API in both layouts.
            for package in ("agent_platform_plugin_sdk", "minidsh_cordis"):
                spec = importlib.util.find_spec(package)
                assert spec is not None and spec.submodule_search_locations
                shutil.copytree(
                    next(iter(spec.submodule_search_locations)),
                    Path(directory) / package,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            path = Path(directory) / "wrong_service.py"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "mypy", "--strict", str(path)],
                                    cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("provide", result.stdout)
        self.assertNotIn("Cannot find implementation", result.stdout)


if __name__ == "__main__":
    unittest.main()
