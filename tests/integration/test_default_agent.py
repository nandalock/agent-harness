"""Default agent seeding: one insert, bindings only on first creation."""
import json
import unittest

from agent_platform_database_postgres.default_agent import (
    DEFAULT_AGENT_CONFIG,
    DEFAULT_AGENT_KEY,
    DEFAULT_AGENT_NAME,
    DEFAULT_AGENT_TOOLS,
    seed_default_agent,
)


class FakeCursor:
    def __init__(self, inserted: bool):
        self.inserted = inserted
        self.calls: list[tuple[str, object]] = []
        self.batches: list[tuple[str, object]] = []
        self._returned = False

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        # The first fetch is the INSERT ... RETURNING result.
        if self._returned:
            return None
        self._returned = True
        return (DEFAULT_AGENT_KEY,) if self.inserted else None

    def executemany(self, sql: str, params):
        self.batches.append((sql, params))


class DefaultAgentSeedTests(unittest.TestCase):
    def test_first_seed_inserts_agent_and_bindings(self):
        cursor = FakeCursor(inserted=True)
        self.assertTrue(seed_default_agent(cursor))

        self.assertEqual(len(cursor.calls), 1)
        sql, params = cursor.calls[0]
        self.assertIn("INSERT INTO agent_definitions", sql)
        self.assertIn("ON CONFLICT (agent_key) DO NOTHING", sql)
        self.assertEqual(params[0], DEFAULT_AGENT_KEY)
        self.assertEqual(params[1], DEFAULT_AGENT_NAME)
        config = json.loads(params[3])
        self.assertEqual(config, DEFAULT_AGENT_CONFIG)
        self.assertEqual(config["provider"], "deepseek")

        self.assertEqual(len(cursor.batches), 1)
        binding_sql, binding_params = cursor.batches[0]
        self.assertIn("INSERT INTO agent_tool_bindings", binding_sql)
        self.assertEqual(binding_params, [(DEFAULT_AGENT_KEY, t) for t in DEFAULT_AGENT_TOOLS])

    def test_existing_agent_is_left_untouched(self):
        cursor = FakeCursor(inserted=False)
        self.assertFalse(seed_default_agent(cursor))
        self.assertEqual(len(cursor.calls), 1)
        self.assertEqual(cursor.batches, [])

    def test_default_config_has_no_credentials(self):
        for field in ("api_key", "base_url", "model"):
            self.assertNotIn(field, DEFAULT_AGENT_CONFIG)
        self.assertEqual(DEFAULT_AGENT_CONFIG["provider"], "deepseek")


if __name__ == "__main__":
    unittest.main()
