import asyncio
from graphlib import CycleError
from unittest import IsolatedAsyncioTestCase

from minidsh_cordis import Context, EventKey, FiberState, Plugin, ServiceKey

PREFIX = ServiceKey[str]("prefix")
LABEL = ServiceKey[str]("label")
RENDER = EventKey[str]("render")


def provide_prefix(ctx, config):
    ctx.provide(PREFIX, config)


class LifecycleTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Context()
        self.addAsyncCleanup(self.root.aclose)

    async def test_pending_chain_is_reactivated_after_provider_replacement(self):
        timeline = []

        def label_provider(ctx, _):
            ctx.provide(LABEL, ctx.require(PREFIX) + "label")
            ctx.on_dispose(lambda: timeline.append(("label", ctx.require(PREFIX))))

        def consumer(ctx, _):
            label = ctx.require(LABEL)
            ctx.on(RENDER, lambda text: f"{label}: {text}")
            ctx.on_quiesce(lambda: timeline.append(("stop consumer", ctx.require(LABEL))))
            ctx.on_dispose(lambda: timeline.append(("dispose consumer", ctx.require(LABEL))))

        async def provider(ctx, prefix):
            provide_prefix(ctx, prefix)
            ctx.on_quiesce(lambda: timeline.append(("stop provider", prefix)))
            ctx.on_dispose(lambda: timeline.append(("dispose provider", prefix)))

        use = await self.root.plugin(Plugin(consumer, requires=(LABEL,)), id="use", config=None)
        middle = await self.root.plugin(Plugin(label_provider, requires=(PREFIX,), provides=(LABEL,)),
                                        id="label", config=None)
        self.assertIs(use.state, FiberState.PENDING)
        self.assertEqual(use.waiting_for, (LABEL,))
        self.assertIs(middle.state, FiberState.PENDING)
        spec = Plugin(provider, provides=(PREFIX,))
        old = await self.root.plugin(spec, id="source", config="old ")
        old_context = use.ctx
        self.assertIs(use.state, FiberState.ACTIVE)
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "old label: text")

        await old.aclose()
        self.assertEqual(timeline, [
            ("stop consumer", "old label"), ("stop provider", "old "),
            ("dispose consumer", "old label"), ("label", "old "), ("dispose provider", "old "),
        ])
        self.assertIs(use.state, FiberState.PENDING)
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "text")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            old_context.require(LABEL)

        new = await self.root.plugin(spec, id="source", config="new ")
        await old.aclose()
        self.assertIs(new.state, FiberState.ACTIVE)
        self.assertIsNot(use.ctx, old_context)
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "new label: text")

    async def test_failed_setup_withdraws_staged_service_and_listener(self):
        started = asyncio.Event()
        finish = asyncio.Event()
        cleanup = []

        async def broken(ctx, _):
            ctx.provide(PREFIX, "partial")
            ctx.on(RENDER, lambda text: "leaked")
            ctx.on_dispose(lambda: cleanup.append("disposed"))
            started.set()
            await finish.wait()
            raise RuntimeError("setup failed")

        task = asyncio.create_task(self.root.plugin(Plugin(broken, provides=(PREFIX,)), id="broken", config=None))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            with self.assertRaises(LookupError):
                self.root.require(PREFIX)
            self.assertEqual(await self.root.waterfall(RENDER, "text"), "text")
        finally:
            finish.set()
            fiber = await task
        self.assertIs(fiber.state, FiberState.FAILED)
        self.assertEqual(str(fiber.error), "setup failed")
        self.assertEqual(cleanup, ["disposed"])
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "text")

    async def test_disposal_drains_callbacks_even_if_request_is_cancelled(self):
        entered = asyncio.Event()
        leave = asyncio.Event()
        quiesced = asyncio.Event()

        async def render(text):
            entered.set()
            await leave.wait()
            return text + "!"

        def consumer(ctx, _):
            ctx.on(RENDER, render)
            ctx.on_quiesce(quiesced.set)

        fiber = await self.root.plugin(Plugin(consumer), id="consumer", config=None)
        running = asyncio.create_task(self.root.waterfall(RENDER, "first"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        close = asyncio.create_task(fiber.aclose())
        try:
            await asyncio.wait_for(quiesced.wait(), timeout=2)
            self.assertIs(fiber.state, FiberState.STOPPING)
            self.assertEqual(await self.root.waterfall(RENDER, "next"), "next")
            close.cancel()
        finally:
            leave.set()
        self.assertEqual(await running, "first!")
        with self.assertRaises(asyncio.CancelledError):
            await close
        self.assertIs(fiber.state, FiberState.DISPOSED)

    async def test_cycle_and_conflicting_provider_do_not_change_registered_graph(self):
        def consumer(ctx, _):
            ctx.provide(LABEL, ctx.require(PREFIX))

        use = await self.root.plugin(Plugin(consumer, requires=(PREFIX,), provides=(LABEL,)), id="use", config=None)
        with self.assertRaises(CycleError):
            await self.root.plugin(Plugin(provide_prefix, requires=(LABEL,), provides=(PREFIX,)), id="bad", config="a")
        self.assertEqual(self.root.fibers, (use,))
        await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="source", config="a")
        with self.assertRaisesRegex(ValueError, "already reserved"):
            await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="extra", config="b")
        self.assertEqual(self.root.require(LABEL), "a")

    async def test_cleanup_attempts_all_callbacks_and_withdraws_service_on_error(self):
        cleaned = []

        def fail():
            raise ValueError("cleanup error")

        def provider(ctx, value):
            ctx.provide(PREFIX, value)
            ctx.on_dispose(lambda: cleaned.append("first"))
            ctx.on_dispose(fail)
            ctx.on_dispose(lambda: cleaned.append("last"))

        fiber = await self.root.plugin(Plugin(provider, provides=(PREFIX,)), id="source", config="test")
        with self.assertRaises(ExceptionGroup):
            await fiber.aclose()
        self.assertEqual(cleaned, ["last", "first"])
        self.assertIs(fiber.state, FiberState.DISPOSED)
        with self.assertRaises(LookupError):
            self.root.require(PREFIX)

    async def test_service_versions_and_root_contexts_are_independent(self):
        v2 = ServiceKey[str]("prefix", version=2)
        other = Context()
        self.addAsyncCleanup(other.aclose)

        def provider(ctx, config):
            ctx.provide(v2, config)

        await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="v1", config="one")
        await self.root.plugin(Plugin(provider, provides=(v2,)), id="v2", config="two")
        self.assertEqual(self.root.require(PREFIX), "one")
        self.assertEqual(self.root.require(v2), "two")
        with self.assertRaises(LookupError):
            other.require(PREFIX)

    async def test_waterfall_composes_in_order_and_can_remove_one_listener(self):
        handles = []

        def first(ctx, _):
            handles.append(ctx.on(RENDER, str.upper))

        async def second(ctx, _):
            ctx.on(RENDER, lambda text: f"[{text}]")

        await self.root.plugin(Plugin(first), id="first", config=None)
        await self.root.plugin(Plugin(second), id="second", config=None)
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "[TEXT]")
        await handles[0].aclose()
        self.assertTrue(handles[0].closed)
        self.assertEqual(await self.root.waterfall(RENDER, "text"), "[text]")
