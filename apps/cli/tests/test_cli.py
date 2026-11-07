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


def test_headless_entry_keeps_the_question_and_agent(monkeypatch):
    from unittest.mock import AsyncMock

    import agent_platform_cli

    mock = AsyncMock(return_value="ok")
    monkeypatch.setattr(agent_platform_cli, "run_agent", mock)
    for prefix in ([], ["run"]):
        assert agent_platform_cli.main([*prefix, "--agent", "example", "--tenant-id", "7", "hi"]) == 0
        mock.assert_awaited_with("example", "hi", 7)
