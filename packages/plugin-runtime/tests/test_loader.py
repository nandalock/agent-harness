import unittest

from agent_platform_plugin_sdk import (
    PluginCompatibilityError,
    PluginSpec,
    SdkModel,
)

from agent_platform_plugin_runtime import (
    ConfigurationError,
    DiscoveryError,
    MappingCatalog,
    PluginRuntime,
    RuntimeState,
)
from support import EmptyConfig, plugin_class


def runtime_for(entries, catalog):
    return PluginRuntime(
        {"version": 1, "plugins": entries},
        catalog=MappingCatalog(catalog),
    )


class LoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_entries_are_not_discovered(self):
        runtime = runtime_for(
            [
                {"id": "off", "name": "test.missing", "disabled": True},
                {"id": "on", "name": "test.ok"},
            ],
            {"test.ok": plugin_class("test.ok")},
        )
        await runtime.start()
        self.assertEqual([plugin.instance_id for plugin in runtime.plugins], ["on"])
        await runtime.aclose()

    async def test_missing_entry_point_fails_before_any_setup(self):
        log = []
        runtime = runtime_for(
            [{"id": "missing", "name": "test.missing"}], {}
        )
        with self.assertRaises(DiscoveryError):
            await runtime.start()
        self.assertEqual(runtime.state, RuntimeState.NEW)
        self.assertEqual(log, [])

    async def test_entry_point_name_must_match_spec_name(self):
        runtime = runtime_for(
            [{"id": "entry", "name": "test.entry"}],
            {"test.entry": plugin_class("test.other")},
        )
        with self.assertRaises(DiscoveryError) as raised:
            await runtime.start()
        self.assertIn("test.other", str(raised.exception))

    async def test_incompatible_sdk_is_rejected_before_setup(self):
        class FuturePlugin:
            spec = PluginSpec(
                name="test.future", version="0.1.0", sdk_api_version=2
            )
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                raise AssertionError("must not run")

        runtime = runtime_for(
            [{"id": "future", "name": "test.future"}],
            {"test.future": FuturePlugin},
        )
        with self.assertRaises(PluginCompatibilityError):
            await runtime.start()
        self.assertEqual(runtime.state, RuntimeState.NEW)

    async def test_plugin_config_is_validated_before_setup(self):
        class RequiredConfig(SdkModel):
            value: int

        class Configured:
            spec = PluginSpec(name="test.required", version="0.1.0")
            config_model = RequiredConfig

            async def setup(self, ctx, config):
                raise AssertionError("must not run")

        runtime = runtime_for(
            [{"id": "required", "name": "test.required", "config": {}}],
            {"test.required": Configured},
        )
        with self.assertRaises(ConfigurationError) as raised:
            await runtime.start()
        self.assertIn("test.required", str(raised.exception))

    async def test_bad_spec_type_is_rejected(self):
        class BadSpec:
            spec = object()
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                pass

        runtime = runtime_for(
            [{"id": "bad", "name": "test.bad"}], {"test.bad": BadSpec}
        )
        with self.assertRaises(DiscoveryError):
            await runtime.start()

    async def test_config_model_must_be_a_pydantic_model(self):
        class BadConfig:
            spec = PluginSpec(name="test.bad-config", version="0.1.0")
            config_model = dict

            async def setup(self, ctx, config):
                pass

        runtime = runtime_for(
            [{"id": "bad", "name": "test.bad-config"}],
            {"test.bad-config": BadConfig},
        )
        with self.assertRaises(DiscoveryError):
            await runtime.start()

    async def test_setup_must_be_async(self):
        class SyncSetup:
            spec = PluginSpec(name="test.sync", version="0.1.0")
            config_model = EmptyConfig

            def setup(self, ctx, config):
                pass

        runtime = runtime_for(
            [{"id": "sync", "name": "test.sync"}], {"test.sync": SyncSetup}
        )
        with self.assertRaises(DiscoveryError):
            await runtime.start()

    async def test_catalog_must_return_instances_not_classes(self):
        class Valid:
            spec = PluginSpec(name="test.valid", version="0.1.0")
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                pass

        runtime = runtime_for(
            [{"id": "valid", "name": "test.valid"}],
            {"test.valid": lambda: Valid},
        )
        with self.assertRaises(DiscoveryError):
            await runtime.start()

    async def test_same_implementation_can_serve_two_instances_with_different_config(self):
        class ValueConfig(SdkModel):
            value: str

        seen = []

        class Configured:
            spec = PluginSpec(name="test.configured", version="0.1.0")
            config_model = ValueConfig

            async def setup(self, ctx, config):
                seen.append(config.value)

        runtime = runtime_for(
            [
                {"id": "first", "name": "test.configured", "config": {"value": "one"}},
                {"id": "second", "name": "test.configured", "config": {"value": "two"}},
            ],
            {"test.configured": Configured},
        )
        await runtime.start()
        self.assertEqual(seen, ["one", "two"])
        self.assertEqual(
            [plugin.instance_id for plugin in runtime.plugins], ["first", "second"]
        )
        await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
