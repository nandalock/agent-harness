"""Agent bootstrapping is data-driven; legacy retirement preserves user data."""
import unittest
from unittest.mock import Mock, patch

from backend import agents
from backend.core.legacy_agents import retire_examples


class ConfiguredAgentsTests(unittest.TestCase):
    def setUp(self):
        self.before = dict(agents._agents)
        agents._agents.clear()

    def tearDown(self):
        agents._agents.clear()
        agents._agents.update(self.before)

    def test_empty_database_produces_no_agents(self):
        with patch("backend.agents.config_service.list_agent_definitions", return_value=[]):
            agents.load_configured_agents()
        self.assertEqual(agents.list_agents(), [])

    def test_arbitrary_definition_uses_generic_runtime(self):
        definition = {"agent_key": "my_researcher", "name": "Researcher", "config": {"system_prompt": "Custom"}}
        with patch("backend.agents.config_service.list_agent_definitions", return_value=[definition]):
            agents.load_configured_agents()
        agent = agents.get_agent("my_researcher")
        self.assertEqual(type(agent).__name__, "AgentRuntime")
        self.assertEqual(agent.name, "Researcher")
        self.assertEqual([row["key"] for row in agents.list_agents()], ["my_researcher"])

    def test_router_is_a_generic_configured_type(self):
        agent = agents.create_agent({"agent_key": "my_router", "name": "Routing", "agent_type": "router", "config": {}})
        self.assertEqual(type(agent).__name__, "RouterRuntime")
        self.assertEqual(agent.key, "my_router")

    def test_retirement_archives_without_deleting_config_or_history(self):
        cursor = Mock()
        cursor.fetchone.return_value = None
        retire_examples(cursor)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("status = 'archived'" in statement for statement in sql))
        self.assertFalse(any("DELETE" in statement or "DROP" in statement for statement in sql))
        self.assertFalse(any("agent_configs" in statement or "conversations" in statement for statement in sql))

    def test_retirement_only_runs_once(self):
        cursor = Mock()
        cursor.fetchone.return_value = {"exists": 1}
        retire_examples(cursor)
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
