import asyncio
from unittest import IsolatedAsyncioTestCase

from minidsh_cordis import Context, DependencyCycleError, EventKey, FiberState, Plugin, ServiceKey

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
        with self.assertRaises(DependencyCycleError):
            await self.root.plugin(Plugin(provide_prefix, requires=(LABEL,), provides=(PREFIX,)), id="bad", config="a")
        self.assertEqual(self.root.fibers, (use,))
        await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="source", config="a")
        with self.assertRaisesRegex(ValueError, "already reserved"):
            await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="extra", config="b")
        self.assertEqual(self.root.require(LABEL), "a")

    async def test_cancellation_on_the_lifecycle_task_still_drains_and_unloads(self):
        root = Context(lifecycle_in_caller=True)
        self.addAsyncCleanup(root.aclose)
        entered = asyncio.Event()
        release = asyncio.Event()
        quiesced = asyncio.Event()
        cleaned = []

        async def render(value):
            entered.set()
            await release.wait()
            return value

        def setup(ctx, _):
            ctx.on(RENDER, render)
            ctx.on_quiesce(quiesced.set)
            ctx.on_dispose(lambda: cleaned.append(asyncio.current_task()))

        fiber = await root.plugin(Plugin(setup), id="consumer", config=None)
        running = asyncio.create_task(root.waterfall(RENDER, "in flight"))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            closing = asyncio.create_task(root.aclose())
            await asyncio.wait_for(quiesced.wait(), timeout=2)
            closing.cancel()
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
        finally:
            release.set()
            await running
            if closing is not None:
                with self.assertRaises(asyncio.CancelledError):
                    await closing
        self.assertEqual(cleaned, [closing])
        self.assertIs(fiber.state, FiberState.DISPOSED)
        self.assertTrue(root.closed)

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

    async def test_batch_rollback_drains_before_cleanup_on_the_caller_task(self):
        root = Context(host_services={PREFIX: "host"}, lifecycle_in_caller=True)
        self.addAsyncCleanup(root.aclose)
        caller = asyncio.current_task()
        timeline = []

        def driver(ctx, _):
            self.assertIs(asyncio.current_task(), caller)
            self.assertEqual(ctx.require(PREFIX), "host")
            ctx.on_quiesce(lambda: timeline.append("quiesce"))
            ctx.on_dispose(lambda: timeline.append("close driver"))

        def failure(ctx, _):
            def cleanup():
                self.assertIs(asyncio.current_task(), caller)
                timeline.append("close partial")

            ctx.on_dispose(cleanup)
            raise ValueError("invalid setup")

        with self.assertRaisesRegex(ValueError, "invalid setup"):
            await root.start([("driver", Plugin(driver, requires=(PREFIX,)), None),
                              ("failure", Plugin(failure), None)])
        self.assertEqual(timeline, ["quiesce", "close partial", "close driver"])
        self.assertEqual(root.fibers, ())
        self.assertEqual(root.require(PREFIX), "host")

    async def test_withdrawal_suspends_consumers_before_the_binding_is_removed(self):
        registrations = []
        disposed = []

        def provider(ctx, config):
            registrations.append(ctx.provide(PREFIX, config))

        def consumer(ctx, _):
            ctx.on_dispose(lambda: disposed.append(ctx.require(PREFIX)))

        provider_fiber = await self.root.plugin(Plugin(provider, provides=(PREFIX,)), id="source", config="prefix")
        consumer_fiber = await self.root.plugin(Plugin(consumer, requires=(PREFIX,)), id="use", config=None)
        await registrations[0].aclose()
        self.assertIs(provider_fiber.state, FiberState.ACTIVE)
        self.assertIs(consumer_fiber.state, FiberState.PENDING)
        self.assertEqual(disposed, ["prefix"])
        with self.assertRaises(LookupError):
            self.root.require(PREFIX)

    async def test_optional_consumer_refreshes_on_binding_changes_only(self):
        observed = []

        def consumer(ctx, _):
            observed.append(("start", ctx.get(PREFIX)))
            ctx.on_dispose(lambda: observed.append(("stop", ctx.get(PREFIX))))

        use = await self.root.plugin(Plugin(consumer, optional=(PREFIX,)), id="use", config=None)
        unavailable = await self.root.plugin(
            Plugin(provide_prefix, requires=(LABEL,), provides=(PREFIX,)), id="source", config="unavailable",
        )
        self.assertIs(unavailable.state, FiberState.PENDING)
        await unavailable.aclose()
        self.assertEqual(observed, [("start", None)])

        provider = await self.root.plugin(Plugin(provide_prefix, provides=(PREFIX,)), id="source", config="available")
        self.assertIs(use.state, FiberState.ACTIVE)
        await provider.aclose()
        self.assertIs(use.state, FiberState.ACTIVE)
        self.assertEqual(observed, [
            ("start", None), ("stop", None), ("start", "available"), ("stop", "available"), ("start", None),
        ])

    async def test_diamond_refreshes_the_shared_consumer_once(self):
        right = ServiceKey[str]("right")
        observed = []

        def middle(key):
            def setup(ctx, _):
                ctx.provide(key, ctx.require(PREFIX))
            return Plugin(setup, requires=(PREFIX,), provides=(key,))

        def consumer(ctx, _):
            observed.append(("start", ctx.require(LABEL), ctx.require(right)))
            ctx.on_dispose(lambda: observed.append(("stop", ctx.require(LABEL), ctx.require(right))))

        await self.root.plugin(middle(LABEL), id="left", config=None)
        await self.root.plugin(middle(right), id="right", config=None)
        use = await self.root.plugin(Plugin(consumer, requires=(LABEL, right)), id="use", config=None)
        spec = Plugin(provide_prefix, provides=(PREFIX,))
        first = await self.root.plugin(spec, id="source", config="first")
        await first.aclose()
        self.assertIs(use.state, FiberState.PENDING)
        await self.root.plugin(spec, id="source", config="second")
        self.assertEqual(observed, [
            ("start", "first", "first"), ("stop", "first", "first"), ("start", "second", "second"),
        ])
