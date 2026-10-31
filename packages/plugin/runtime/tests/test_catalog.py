import unittest
from unittest.mock import patch

from agent_platform_plugin_runtime import (
    DiscoveryError,
    EntryPointCatalog,
    MappingCatalog,
)


class Marker:
    pass


class FakeEntryPoint:
    def __init__(self, name, value, error=None):
        self.name = name
        self._value = value
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._value


class CatalogTests(unittest.TestCase):
    def test_unknown_entry_point_is_reported_without_python_imports(self):
        catalog = EntryPointCatalog(group="agent_platform.plugins.tests.none")
        with self.assertRaises(DiscoveryError) as raised:
            catalog.load("test.missing")
        self.assertEqual(raised.exception.code, "plugin_runtime.discovery")

    def test_mapping_catalog_calls_the_factory_for_every_load(self):
        catalog = MappingCatalog({"test.marker": Marker})
        first = catalog.load("test.marker")
        second = catalog.load("test.marker")
        self.assertIsInstance(first, Marker)
        self.assertIsNot(first, second)

    def test_mapping_catalog_wraps_factory_failures(self):
        def broken():
            raise RuntimeError("cannot construct")

        catalog = MappingCatalog({"test.broken": broken})
        with self.assertRaises(DiscoveryError) as raised:
            catalog.load("test.broken")
        self.assertIn("cannot construct", str(raised.exception))

    def test_missing_mapping_entry_is_reported(self):
        with self.assertRaises(DiscoveryError):
            MappingCatalog({}).load("test.missing")

    def test_entry_point_catalog_instantiates_each_entry(self):
        entry = FakeEntryPoint("test.marker", Marker)
        with patch(
            "agent_platform_plugin_runtime.catalog.entry_points", return_value=[entry]
        ):
            catalog = EntryPointCatalog()
            first = catalog.load("test.marker")
            second = catalog.load("test.marker")
        self.assertIsInstance(first, Marker)
        self.assertIsNot(first, second)

    def test_duplicate_entry_point_names_are_rejected(self):
        entry = FakeEntryPoint("test.marker", Marker)
        with patch(
            "agent_platform_plugin_runtime.catalog.entry_points",
            return_value=[entry, entry],
        ):
            with self.assertRaises(DiscoveryError) as raised:
                EntryPointCatalog().load("test.marker")
        self.assertIn("duplicate", str(raised.exception))

    def test_entry_point_import_and_shape_failures_are_reported(self):
        with patch(
            "agent_platform_plugin_runtime.catalog.entry_points",
            return_value=[FakeEntryPoint("test.bad", None, RuntimeError("import failed"))],
        ):
            with self.assertRaises(DiscoveryError) as raised:
                EntryPointCatalog().load("test.bad")
        self.assertIn("import failed", str(raised.exception))

        with patch(
            "agent_platform_plugin_runtime.catalog.entry_points",
            return_value=[FakeEntryPoint("test.bad", object())],
        ):
            with self.assertRaises(DiscoveryError):
                EntryPointCatalog().load("test.bad")


if __name__ == "__main__":
    unittest.main()
