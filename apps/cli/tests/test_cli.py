import subprocess
import sys
import unittest


class CliEntryTests(unittest.TestCase):
    def test_help_lists_run_and_serve(self):
        result = subprocess.run(
            [sys.executable, "-m", "agent_platform_cli", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run", result.stdout)
        self.assertIn("serve", result.stdout)
