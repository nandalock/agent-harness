import tempfile
import unittest
from pathlib import Path

from minidsh_cordis_plugin_include import ConfigurationError, Include, parse_config
from minidsh_cordis_plugin_loader import LifecycleError, Loader, MappingCatalog, MissingServiceError

from support import EmptyConfig, service_key
from minidsh_cordis import Plugin


PREFIX = service_key("test.prefix")


class ProviderConfig(EmptyConfig):
    prefix: str


class Provider(Plugin[ProviderConfig]):
    name = "test.provider"
    version = "0.1.0"
    provides = (PREFIX,)
    config_model = ProviderConfig

    async def setup(self, ctx, config):
        if config.prefix == "broken":
            raise ValueError("invalid provider setup")
        ctx.provide(PREFIX, config.prefix)


class ReconfigureTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_provider_changes_reactivate_consumer_on_the_same_context(self):
        seen = []

        class Consumer(Plugin[EmptyConfig]):
            name = "test.consumer"
            version = "0.1.0"
            optional = (PREFIX,)
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                seen.append(ctx.get(PREFIX))

        def configuration(disabled):
            return parse_config({"plugins": [
                {"id": "consumer", "name": "test.consumer"},
                {"id": "provider", "name": "test.provider", "disabled": disabled, "config": {"prefix": "new"}},
            ]})

        loader = Loader(configuration(True), catalog=MappingCatalog({
            "test.provider": Provider, "test.consumer": Consumer,
        }))
        await loader.start()
        self.addAsyncCleanup(loader.aclose)
        root = loader.ctx
        self.assertEqual(await loader.reconfigure(configuration(False)), ("consumer", "provider"))
        self.assertEqual(await loader.reconfigure(configuration(True)), ("consumer", "provider"))
        self.assertEqual(seen, [None, "new", None])
        self.assertIs(loader.ctx, root)

    async def test_replacement_restarts_dependents_and_restores_old_configuration(self):
        seen = []
        output = service_key("test.output")

        class Consumer(Plugin[EmptyConfig]):
            name = "test.consumer"
            version = "0.1.0"
            requires = (PREFIX,)
            provides = (output,)
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                seen.append(ctx.require(PREFIX))
                ctx.provide(output, seen[-1])

        def configuration(prefix):
            return parse_config({"plugins": [
                {"id": "consumer", "name": "test.consumer"},
                {"id": "provider", "name": "test.provider", "config": {"prefix": prefix}},
            ]})

        runtime = Loader(configuration("old"), catalog=MappingCatalog({
            "test.provider": Provider, "test.consumer": Consumer,
        }))
        await runtime.start()
        self.addAsyncCleanup(runtime.aclose)
        consumer = next(fiber for fiber in runtime.ctx.fibers if fiber.id == "consumer")
        context = consumer.ctx
        with self.assertRaisesRegex(LifecycleError, "restart required"):
            await runtime.reconfigure(configuration("new"), pinned=frozenset({output}))
        missing = parse_config({"plugins": [{"id": "consumer", "name": "test.consumer"}]})
        with self.assertRaises(MissingServiceError):
            await runtime.reconfigure(missing)
        self.assertIs(consumer.ctx, context)
        self.assertEqual(seen, ["old"])
        self.assertEqual(await runtime.reconfigure(configuration("new")), ("consumer", "provider"))
        self.assertIn(consumer, runtime.ctx.fibers)
        self.assertIsNot(consumer.ctx, context)
        with self.assertRaisesRegex(ValueError, "invalid provider setup"):
            await runtime.reconfigure(configuration("broken"))
        self.assertEqual(seen, ["old", "new", "new"])
        self.assertEqual(runtime.require(PREFIX), "new")
        self.assertEqual(runtime.config, configuration("new"))

    async def test_relative_include_explicit_export_patch_and_group(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "provider.yaml").write_text(f"""plugins:
  - id: provider
    name: test.provider
    use: {__name__}:Provider
    group: extras
    config: {{prefix: base}}
""", encoding="utf-8")
            profile = folder / "plugins.yaml"
            profile.write_text("""includes: [provider.yaml]
patches:
  - id: provider
    config: {prefix: patched}
""", encoding="utf-8")
            runtime = Loader.from_yaml(profile, catalog=MappingCatalog({}))
            await runtime.start()
            self.addAsyncCleanup(runtime.aclose)
            self.assertEqual(runtime.require(PREFIX), "patched")
            (folder / "provider.yaml").write_text((folder / "provider.yaml").read_text(encoding="utf-8") +
                "patches: [{id: provider, config: {prefix: lower-patch}}]\n", encoding="utf-8")
            profile.write_text(f"""includes: [provider.yaml]
plugins:
  - id: provider
    name: test.provider
    use: {__name__}:Provider
    group: extras
    config: {{prefix: higher-entry}}
""", encoding="utf-8")
            await runtime.reconfigure(Include(profile).read())
            self.assertEqual(runtime.require(PREFIX), "higher-entry")
            profile.write_text("includes: [provider.yaml]\ngroups: {extras: {disabled: true}}\n", encoding="utf-8")
            self.assertEqual(await runtime.reconfigure(Include(profile).read()), ("provider",))
            self.assertEqual(runtime.plugins, ())
            profile.write_text("includes: [plugins.yaml]\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "include cycle"):
                Include(profile).read()
