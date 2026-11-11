import unittest

from agent_platform_faq import FAQ, FAQService, FaqPlugin
from minidsh_cordis_plugin_loader import MappingCatalog, Loader
from agent_platform_plugin_sdk import DATABASE


class FakeDatabase:
    def get_conn(self):
        raise AssertionError("plugin setup must not open a connection")


class FaqPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_provides_service(self):
        runtime = Loader(
            {"plugins": [{"id": "faq", "name": "agent-platform.faq"}]},
            catalog=MappingCatalog({"agent-platform.faq": FaqPlugin}),
            host_services={DATABASE: FakeDatabase()},
        )
        try:
            await runtime.start()
            self.assertIsInstance(runtime.require(FAQ), FAQService)
        finally:
            await runtime.aclose()

    def test_csv_import_rejects_missing_columns_before_db_access(self):
        service = FAQService(FakeDatabase())
        result = service.import_csv(1, b"foo,bar\n1,2")
        self.assertEqual(result.total, 0)
        self.assertIn("question, answer", result.errors[0])
