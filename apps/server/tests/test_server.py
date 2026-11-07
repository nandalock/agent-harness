import unittest

from agent_platform_server import RuntimeASGIApp, app


class ServerEntryTests(unittest.TestCase):
    def test_asgi_entry_exposes_the_carrier(self):
        self.assertIsInstance(app, RuntimeASGIApp)
        self.assertTrue(callable(app))
