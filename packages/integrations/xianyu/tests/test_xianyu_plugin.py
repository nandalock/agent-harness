import unittest

from agent_platform_chat import CHAT
from minidsh_cordis_plugin_loader import MappingCatalog, Loader
from agent_platform_xianyu import XIANYU, XianyuManager, XianyuPlugin


class FakeStore:
    def list_conversations_with_summary(self, *args, **kwargs):
        return []

    def get_messages_by_channel_cid(self, *args, **kwargs):
        return []


class FakeChat:
    def __init__(self):
        self.store = FakeStore()


class XianyuPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_provides_offline_manager(self):
        runtime = Loader(
            {"plugins": [{"id": "xianyu", "name": "agent-platform.xianyu"}]},
            catalog=MappingCatalog({"agent-platform.xianyu": XianyuPlugin}),
            host_services={CHAT: FakeChat()},
        )
        try:
            await runtime.start()
            manager = runtime.require(XIANYU)
            self.assertIsInstance(manager, XianyuManager)
            self.assertFalse(manager.get_status()["is_online"])
            self.assertEqual(manager.get_conversations(), [])
            self.assertEqual(manager.get_messages("cid"), [])
        finally:
            await runtime.aclose()
