import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from minidsh_cordis_plugin_hmr import Hmr


class HmrTests(IsolatedAsyncioTestCase):
    async def test_applies_changes_in_order_on_the_lifecycle_task(self):
        stop = asyncio.Event()
        lifecycle = asyncio.current_task()
        load = Mock(side_effect=["initial", "first", "first", "second"])
        applied = []

        async def apply(value):
            self.assertIs(asyncio.current_task(), lifecycle)
            applied.append(value)
            if value == "second":
                stop.set()
            return (value,)

        hmr = Hmr(load, apply, interval=0.001)
        async with asyncio.timeout(2):
            await hmr.watch_config(initial="initial", stop=stop)

        self.assertEqual(applied, ["first", "second"])

    async def test_invalid_config_and_failed_apply_do_not_stop_watching(self):
        stop = asyncio.Event()
        load = Mock(side_effect=[ValueError("invalid YAML"), "broken", "broken", "fixed"])
        applied = []

        async def apply(value):
            applied.append(value)
            if value == "broken":
                raise RuntimeError("setup failed")
            stop.set()
            return ("plugin",)

        hmr = Hmr(load, apply, interval=0.001)
        with self.assertLogs("minidsh_cordis_plugin_hmr", level="WARNING") as logs:
            async with asyncio.timeout(2):
                await hmr.watch_config(initial="initial", stop=stop)

        self.assertEqual(applied, ["broken", "fixed"])
        self.assertIn("invalid YAML", logs.output[0])
        self.assertIn("setup failed", logs.output[1])
