import asyncio
import unittest

from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import PluginSpec, SdkModel


class QuiesceTests(unittest.IsolatedAsyncioTestCase):
    def make_runtime(self, *, fail_setup=False, fail_stop=False):
        order = []

        class Driver:
            spec = PluginSpec(name="test.driver", version="0.1.0")
            config_model = SdkModel

            async def setup(self, ctx, config):
                async def stop():
                    await asyncio.sleep(0)
                    order.append("driver stopped")
                    if fail_stop:
                        raise ValueError("stop failed")
                ctx.on_quiesce(stop, label="stop driver")
                ctx.on_dispose(lambda: order.append("driver disposed"), label="driver effects")

        class LaterProvider:
            spec = PluginSpec(name="test.provider", version="0.1.0")
            config_model = SdkModel

            async def setup(self, ctx, config):
                ctx.on_dispose(lambda: order.append("provider disposed"), label="provider effects")
                if fail_setup:
                    raise ValueError("setup failed")
        runtime = PluginRuntime({"plugins": [
            {"id": "driver", "name": "test.driver"},
            {"id": "provider", "name": "test.provider"},
        ]}, catalog=MappingCatalog({"test.driver": Driver, "test.provider": LaterProvider}))
        return runtime, order

    async def test_all_work_drains_before_any_effect_is_removed(self):
        runtime, order = self.make_runtime()
        await runtime.start()
        await runtime.aclose()
        await runtime.aclose()
        self.assertEqual(order, ["driver stopped", "provider disposed", "driver disposed"])

    async def test_setup_rollback_also_quiesces_before_disposal(self):
        runtime, order = self.make_runtime(fail_setup=True)
        with self.assertRaisesRegex(ValueError, "setup failed"):
            await runtime.start()
        self.assertEqual(order, ["driver stopped", "provider disposed", "driver disposed"])

    async def test_quiesce_failure_still_disposes_every_plugin(self):
        runtime, order = self.make_runtime(fail_stop=True)
        await runtime.start()
        with self.assertRaises(BaseExceptionGroup):
            await runtime.aclose()
        self.assertEqual(order, ["driver stopped", "provider disposed", "driver disposed"])


if __name__ == "__main__":
    unittest.main()
