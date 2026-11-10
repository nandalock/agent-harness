"""Two PluginLoaders in one process must not share service instances."""
import asyncio
import unittest

from agent_platform_plugin_runtime import MappingCatalog, PluginLoader
from agent_platform_plugin_sdk import DATABASE
from agent_platform_session import SESSIONS, SessionPlugin
from agent_platform_llm import LLM, LLMPlugin
from agent_platform_session_persistence import SESSION_PERSISTENCE
from agent_platform_session_persistence_postgres import PostgresPersistencePlugin


class _Database:
    def get_conn(self):
        raise AssertionError("no database access expected")


def _runtime() -> PluginLoader:
    return PluginLoader(
        {"plugins": [
            {"id": "session", "name": "agent-platform.session"},
            {"id": "llm", "name": "agent-platform.llm"},
            {"id": "persistence", "name": "agent-platform.session-persistence-postgres"},
        ]},
        catalog=MappingCatalog({
            "agent-platform.session": SessionPlugin,
            "agent-platform.llm": LLMPlugin,
            "agent-platform.session-persistence-postgres": PostgresPersistencePlugin,
        }),
        host_services={DATABASE: _Database()},
    )


class IsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_runtimes_own_distinct_instances(self):
        first, second = _runtime(), _runtime()
        await first.start()
        await second.start()
        try:
            self.assertIsNot(first.require(SESSIONS), second.require(SESSIONS))
            self.assertIsNot(first.require(LLM), second.require(LLM))
            self.assertIsNot(
                first.require(SESSION_PERSISTENCE),
                second.require(SESSION_PERSISTENCE),
            )
            first.require(SESSIONS).create()
            self.assertEqual(second.require(SESSIONS).list(), [])
        finally:
            await first.aclose()
            await second.aclose()
            self.assertEqual(first.state.value, "closed")
            self.assertEqual(second.state.value, "closed")


if __name__ == "__main__":
    unittest.main()
