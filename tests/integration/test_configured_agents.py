"""Agent bootstrapping is data-driven; legacy retirement preserves user data."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_platform_agent_entry import AgentGateway, AgentNotFound, RequestContext
from agent_platform_agent_runtime import AgentReply
from agent_platform_database_postgres.legacy_agents import retire_examples


class ConfiguredAgentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_is_resolved_for_each_request(self):
        configs = SimpleNamespace(get_definition=AsyncMock(return_value=None))
        runtime = SimpleNamespace(reply=AsyncMock(return_value=AgentReply(answer="hello")))
        entry = AgentGateway(configs, runtime, None, None, None)
        try:
            with self.assertRaises(AgentNotFound):
                await entry.resolve("my_researcher")
            definition = {"agent_key": "my_researcher", "name": "Researcher"}
            configs.get_definition.return_value = definition
            reply = await entry.chat(RequestContext(1, "my_researcher"), "hi")
            self.assertEqual(reply.answer, "hello")
            self.assertEqual(runtime.reply.await_args.args[:4], ("my_researcher", definition, 1, "hi"))
        finally:
            await entry.aclose()

    async def test_configured_router_keeps_l1_behavior(self):
        configs = SimpleNamespace(
            get_definition=AsyncMock(return_value={"agent_key": "router", "agent_type": "router"}),
            get_config=AsyncMock(return_value={}),
            list_l1_keywords=AsyncMock(return_value=[{"keywords": ["论文"], "target": "paper"}]),
        )
        entry = AgentGateway(configs, None, None, None, None)
        try:
            reply = await entry.chat(RequestContext(1, "router"), "查论文")
            self.assertEqual(json.loads(reply.answer)["agent_key"], "paper")
            self.assertEqual(reply.trace["route_level"], "L1")
        finally:
            await entry.aclose()

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
