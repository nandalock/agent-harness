import asyncio
from unittest import IsolatedAsyncioTestCase

from minidsh_cordis import Context, EventKey, FiberState, Plugin

EVENT = EventKey[str]("message")


class EventsTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Context()
        self.addAsyncCleanup(self.root.aclose)

    async def mount(self, setup, instance="listener"):
        return await self.root.plugin(Plugin(setup), id=instance, config=None)

    async def test_emit_runs_in_registration_order_and_unload_unregisters(self):
        calls = []

        def first(ctx, _):
            ctx.on(EVENT, lambda value: calls.append(("first", value)))

        def second(ctx, _):
            ctx.on(EVENT, lambda value: calls.append(("second", value)))

        fiber = await self.mount(first, "first")
        await self.mount(second, "second")
        self.root.emit(EVENT, "hello")
        self.assertEqual(calls, [("first", "hello"), ("second", "hello")])
        await fiber.aclose()
        self.root.emit(EVENT, "again")
        self.assertEqual(calls[-1], ("second", "again"))
        self.assertEqual(len(calls), 3)

    async def test_once_unregisters_before_reentrant_emit_even_if_callback_fails(self):
        calls = []

        def once(value):
            calls.append(value)
            self.root.emit(EVENT, "nested")
            raise ValueError("listener failed")

        handles = []
        fiber = await self.mount(lambda ctx, _: handles.append(ctx.once(EVENT, once)))
        with self.assertRaisesRegex(ValueError, "listener failed"):
            self.root.emit(EVENT, "first")
        self.root.emit(EVENT, "second")
        self.assertEqual(calls, ["first"])
        self.assertTrue(handles[0].closed)
        self.assertEqual(fiber._effects, [])
        await handles[0].aclose()

    async def test_once_is_claimed_only_once_across_concurrent_dispatches(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def once(value):
            calls.append(value)
            entered.set()
            await release.wait()

        def setup(ctx, _):
            ctx.once(EVENT, once)

        await self.mount(setup)
        running = asyncio.create_task(self.root.parallel(EVENT, "first"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            await self.root.parallel(EVENT, "second")
        finally:
            release.set()
            await running
        self.assertEqual(calls, ["first"])

    async def test_snapshot_skips_removed_listener_and_defers_new_listener(self):
        calls = []
        handles = []

        def setup(ctx, _):
            async def first(value):
                calls.append(("first", value))
                if value == "initial":
                    await handles[0].aclose()
                    await handles[0].aclose()
                    ctx.on(EVENT, lambda item: calls.append(("new", item)))

            ctx.on(EVENT, first)
            handles.append(ctx.on(EVENT, lambda value: calls.append(("removed", value))))

        await self.mount(setup)
        await self.root.serial(EVENT, "initial")
        await self.root.serial(EVENT, "next")
        self.assertEqual(calls, [("first", "initial"), ("first", "next"), ("new", "next")])

    async def test_serial_awaits_each_listener_and_bails_on_zero(self):
        calls = []

        def setup(ctx, _):
            async def first(value):
                calls.append(("start", value))
                await asyncio.sleep(0)
                calls.append(("finish", value))
                return False

            ctx.on(EVENT, first)
            ctx.on(EVENT, lambda value: calls.append(("second", value)) or 0)
            ctx.on(EVENT, lambda value: self.fail("serial must stop on zero"))

        await self.mount(setup)
        self.assertIsNone(await self.root.serial(EventKey[str]("empty"), "x"))
        self.assertEqual(await self.root.serial(EVENT, "x"), 0)
        self.assertEqual(calls, [("start", "x"), ("finish", "x"), ("second", "x")])

    async def test_bail_skips_none_and_false_but_stops_on_empty_string(self):
        def setup(ctx, _):
            ctx.on(EVENT, lambda _: None)
            ctx.on(EVENT, lambda _: False)
            ctx.on(EVENT, lambda _: "")
            ctx.on(EVENT, lambda _: self.fail("bail must stop on an empty string"))

        await self.mount(setup)
        self.assertIsNone(self.root.bail(EventKey[str]("empty"), "x"))
        self.assertEqual(self.root.bail(EVENT, "x"), "")

    async def test_sync_dispatch_rejects_coroutines_and_serial_propagates_failure(self):
        async def broken(_):
            raise LookupError("async listener failed")

        def setup(ctx, _):
            ctx.on(EVENT, broken)
            ctx.on(EVENT, lambda _: self.fail("dispatch must stop after an exception"))

        await self.mount(setup)
        for dispatch in (self.root.emit, self.root.bail):
            with self.assertRaisesRegex(TypeError, "synchronous listeners"):
                dispatch(EVENT, "x")
        with self.assertRaisesRegex(LookupError, "async listener failed"):
            await self.root.serial(EVENT, "x")

    async def test_sync_dispatch_drains_an_already_scheduled_listener_on_unload(self):
        release = asyncio.Event()
        stopping = asyncio.Event()
        tasks = []

        def setup(ctx, _):
            def listen(_):
                task = asyncio.create_task(release.wait())
                tasks.append(task)
                return task

            ctx.on(EVENT, listen)
            ctx.on_quiesce(stopping.set)

        fiber = await self.mount(setup)
        with self.assertRaisesRegex(TypeError, "synchronous listeners"):
            self.root.emit(EVENT, "x")
        closing = asyncio.create_task(fiber.aclose())
        try:
            await asyncio.wait_for(stopping.wait(), timeout=2)
            self.assertFalse(closing.done())
        finally:
            release.set()
            await closing
            await asyncio.gather(*tasks)
        self.assertIs(fiber.state, FiberState.DISPOSED)

    async def test_parallel_runs_concurrently_and_aggregates_failures_after_all_settle(self):
        entered = [asyncio.Event() for _ in range(3)]
        release = asyncio.Event()
        settled = []

        async def listener(index):
            entered[index].set()
            await release.wait()
            settled.append(index)
            if index < 2:
                raise ValueError(f"listener {index}")

        def setup(ctx, _):
            for index in range(3):
                ctx.on(EVENT, lambda _, index=index: listener(index))

        await self.mount(setup)
        running = asyncio.create_task(self.root.parallel(EVENT, "x"))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), timeout=2)
            self.assertEqual(settled, [])
        finally:
            release.set()
            with self.assertRaises(ExceptionGroup) as raised:
                await running
        self.assertEqual({str(error) for error in raised.exception.exceptions}, {"listener 0", "listener 1"})
        self.assertCountEqual(settled, [0, 1, 2])

    async def test_parallel_tracks_inflight_listener_until_fiber_finishes_unloading(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        stopping = asyncio.Event()
        calls = []

        async def listen(value):
            calls.append(value)
            entered.set()
            await release.wait()

        def setup(ctx, _):
            ctx.on(EVENT, listen)
            ctx.on_quiesce(stopping.set)
            ctx.on_dispose(lambda: calls.append("disposed"))

        fiber = await self.mount(setup)
        running = asyncio.create_task(self.root.parallel(EVENT, "first"))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            closing = asyncio.create_task(fiber.aclose())
            await asyncio.wait_for(stopping.wait(), timeout=2)
            self.assertIs(fiber.state, FiberState.STOPPING)
            await self.root.parallel(EVENT, "ignored")
            self.assertFalse(closing.done())
        finally:
            release.set()
            await running
            if closing is not None:
                await closing
        self.assertEqual(calls, ["first", "disposed"])
        self.assertIs(fiber.state, FiberState.DISPOSED)

    async def test_legacy_waterfall_and_middleware_can_share_an_event_key(self):
        calls = []

        async def outer(value, next_step):
            calls.append("outer before")
            result = await next_step()
            calls.append("outer after")
            return f"[{result}]"

        def inner(value, next_step):
            calls.append("inner")
            return next_step()

        async def terminal(value):
            calls.append("terminal")
            return value + "!"

        def setup(ctx, _):
            ctx.on(EVENT, str.upper)
            ctx.on_middleware(EVENT, outer)
            ctx.on_middleware(EVENT, inner)

        fiber = await self.mount(setup)
        self.assertEqual(await self.root.waterfall(EVENT, "x"), "X")
        self.assertEqual(calls, [])
        self.assertEqual(await self.root.waterfall_next(EVENT, "x", terminal), "[x!]")
        self.assertEqual(calls, ["outer before", "inner", "terminal", "outer after"])
        await fiber.aclose()
        self.assertEqual(await self.root.waterfall_next(EVENT, "x", lambda value: value), "x")

    async def test_legacy_waterfall_passes_none_to_the_next_listener(self):
        event = EventKey[str | None]("optional message")

        def setup(ctx, _):
            ctx.on(event, lambda _: None)
            ctx.on(event, lambda value: "empty" if value is None else value)

        await self.mount(setup)
        self.assertEqual(await self.root.waterfall(event, "x"), "empty")

    async def test_cancelling_parallel_drains_the_listener_before_unload(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def listen(_):
            try:
                entered.set()
                await release.wait()
            finally:
                calls.append("listener exited")

        def setup(ctx, _):
            ctx.on(EVENT, listen)
            ctx.on_dispose(lambda: calls.append("disposed"))

        fiber = await self.mount(setup)
        running = asyncio.create_task(self.root.parallel(EVENT, "x"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
        finally:
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        await asyncio.wait_for(fiber.aclose(), timeout=2)
        self.assertEqual(calls, ["listener exited", "disposed"])

    async def test_middleware_can_stop_chain_and_saved_next_expires(self):
        saved = []

        def setup(ctx, _):
            def stop(value, next_step):
                saved.append(next_step)
                return value

            ctx.on_middleware(EVENT, stop)
            ctx.on_middleware(EVENT, lambda *_: self.fail("the chain was stopped"))

        await self.mount(setup)
        self.assertEqual(
            await self.root.waterfall_next(EVENT, "stop", lambda _: self.fail("terminal was stopped")), "stop",
        )
        with self.assertRaisesRegex(RuntimeError, "awaited by its middleware"):
            await saved[0]()

    async def test_middleware_cannot_advance_twice(self):
        async def twice(_, next_step):
            await next_step()
            return await next_step()

        def setup(ctx, _):
            ctx.on_middleware(EVENT, twice)

        await self.mount(setup)
        with self.assertRaisesRegex(RuntimeError, "only be called once"):
            await self.root.waterfall_next(EVENT, "x", str.upper)
