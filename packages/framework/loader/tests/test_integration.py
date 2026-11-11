import tempfile
import unittest
from pathlib import Path

from minidsh_cordis_plugin_loader import MappingCatalog, Loader
from support import ECHO, EchoPlugin, EchoService, EchoServicePlugin


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_provided_service_is_resolved_and_closed(self):
        runtime = Loader(
            {
                "version": 1,
                "plugins": [
                    {"id": "echo", "name": "test.echo", "config": {"prefix": "收到："}},
                    {"id": "service", "name": "test.echo-service"},
                ],
            },
            catalog=MappingCatalog(
                {"test.echo": EchoPlugin, "test.echo-service": EchoServicePlugin}
            ),
        )
        await runtime.start()
        self.assertEqual(
            [plugin.instance_id for plugin in runtime.plugins], ["service", "echo"]
        )
        service = runtime.require(ECHO)
        self.assertEqual(service.execute("hello"), "收到：hello")
        await runtime.aclose()
        self.assertTrue(service.closed)

    async def test_host_provided_service_is_borrowed_not_closed(self):
        hosted = EchoService()
        runtime = Loader(
            {
                "version": 1,
                "plugins": [
                    {"id": "echo", "name": "test.echo", "config": {"prefix": ">"}},
                ],
            },
            catalog=MappingCatalog({"test.echo": EchoPlugin}),
            host_services={ECHO: hosted},
        )
        await runtime.start()
        self.assertEqual(hosted.execute("hi"), ">hi")
        await runtime.aclose()
        self.assertFalse(hosted.closed)
        self.assertIsNone(hosted.handler)

    async def test_yaml_file_drives_the_same_lifecycle(self):
        document = """
version: 1
plugins:
  - id: echo
    name: test.echo
    config:
      prefix: "echo: "
  - id: service
    name: test.echo-service
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plugins.yaml"
            path.write_text(document, encoding="utf-8")
            runtime = Loader.from_yaml(
                path,
                catalog=MappingCatalog(
                    {"test.echo": EchoPlugin, "test.echo-service": EchoServicePlugin}
                ),
            )
            await runtime.start()
            service = runtime.require(ECHO)
            self.assertEqual(service.execute("hello"), "echo: hello")
            self.assertEqual(
                [(plugin.instance_id, plugin.version) for plugin in runtime.plugins],
                [("service", "0.1.0"), ("echo", "0.1.0")],
            )
            await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
