import unittest

from minidsh_cordis import Plugin

from minidsh_cordis_plugin_loader import DiscoveryError, MappingCatalog, load_module_plugin
from support import EchoPlugin


class CatalogTests(unittest.TestCase):
    def test_static_catalog_instantiates_each_entry(self):
        catalog = MappingCatalog({"test.echo": EchoPlugin})
        first, second = catalog.load("test.echo"), catalog.load("test.echo")
        self.assertIsInstance(first, Plugin)
        self.assertIsNot(first, second)

    def test_static_catalog_reports_missing_and_failed_factories(self):
        def broken():
            raise RuntimeError("broken constructor")

        catalog = MappingCatalog({"test.broken": broken})
        with self.assertRaisesRegex(DiscoveryError, "broken constructor"):
            catalog.load("test.broken")
        with self.assertRaisesRegex(DiscoveryError, "test.missing"):
            catalog.load("test.missing")

    def test_explicit_class_export_resolves_a_native_plugin(self):
        self.assertIsInstance(load_module_plugin("support:EchoPlugin"), EchoPlugin)

    def test_explicit_export_rejects_missing_or_non_plugin_objects(self):
        for target in ("missing_minidsh_module:plugin", "support:missing", "support:EchoConfig"):
            with self.subTest(target=target), self.assertRaisesRegex(DiscoveryError, target):
                load_module_plugin(target)
