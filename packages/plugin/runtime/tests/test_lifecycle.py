import asyncio
import unittest

from agent_platform_plugin_sdk import (
    RegistrationConflictError,
    ServiceClosedError,
    ServiceKey,
    TOOLS,
)

from agent_platform_plugin_runtime import (
    LifecycleError,
    MappingCatalog,
    PluginLoader,
    LoaderState,
    UndeclaredServiceError,
)
from support import (
    EmptyConfig,
    plugin_class,
    service_key,
)
from minidsh_cordis import Plugin


def runtime_for(entries, catalog, host_services=None):
    return PluginLoader(
        {"version": 1, "plugins": entries},
        catalog=MappingCatalog(catalog),
        host_services=host_services,
    )


def flatten(group):
    messages = []
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            messages.extend(flatten(exc))
        else:
            messages.append(str(exc))
    return messages


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_failure_rolls_back_started_plugins_in_reverse_order(self):
        log = []
        provider = plugin_class(
            "test.provider", provides=(service_key("test.service"),), log=log
        )
        failing = plugin_class(
            "test.failing",
            requires=(service_key("test.service"),),
            log=log,
            fail=RuntimeError("boom"),
        )
        runtime = runtime_for(
            [
                {"id": "failing", "name": "test.failing"},
                {"id": "provider", "name": "test.provider"},
            ],
            {"test.failing": failing, "test.provider": provider},
        )
        with self.assertRaisesRegex(RuntimeError, "boom"):
            await runtime.start()
        self.assertEqual(
            log,
            [
                "setup:test.provider",
                "setup:test.failing",
                "close:test.failing",
                "close:test.provider",
            ],
        )
        self.assertEqual(runtime.state, LoaderState.NEW)
        self.assertEqual(runtime.plugins, ())
        await runtime.aclose()
        self.assertEqual(runtime.state, LoaderState.CLOSED)

    async def test_cleanup_failure_is_attached_to_the_original_startup_error(self):
        log = []

        class Partial(Plugin[EmptyConfig]):
            name = "test.partial"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                def fail():
                    raise RuntimeError("cleanup exploded")

                ctx.on_dispose(fail, label="fail")
                ctx.on_dispose(lambda: log.append("cleanup"), label="cleanup")
                raise RuntimeError("setup failed")

        runtime = runtime_for(
            [{"id": "partial", "name": "test.partial"}],
            {"test.partial": Partial},
        )
        with self.assertRaisesRegex(RuntimeError, "setup failed") as raised:
            await runtime.start()
        self.assertEqual(log, ["cleanup"])
        notes = getattr(raised.exception, "__notes__", [])
        self.assertTrue(any("rollback also failed" in note for note in notes))

    async def test_close_attempts_every_cleanup_and_aggregates_failures(self):
        log = []

        class Cleanup(Plugin[EmptyConfig]):
            name = "test.cleanup"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                def fail():
                    raise RuntimeError("cleanup exploded")

                ctx.on_dispose(lambda: log.append("first"), label="first")
                ctx.on_dispose(lambda: log.append("second"), label="second")
                ctx.on_dispose(fail, label="fail")

        runtime = runtime_for(
            [{"id": "cleanup", "name": "test.cleanup"}],
            {"test.cleanup": Cleanup},
        )
        await runtime.start()
        with self.assertRaises(BaseExceptionGroup) as raised:
            await runtime.aclose()
        self.assertEqual(log, ["second", "first"])
        self.assertTrue(
            any("cleanup exploded" in message for message in flatten(raised.exception))
        )
        self.assertEqual(runtime.state, LoaderState.CLOSED)
        await runtime.aclose()

    async def test_registration_conflict_fails_setup_and_rolls_back(self):
        ref = service_key("test.conflict")

        class Conflicting(Plugin[EmptyConfig]):
            name = "test.conflict"
            version = "0.1.0"
            provides = (ref,)
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                key = ref
                ctx.provide(key, "first")
                ctx.provide(key, "second")

        runtime = runtime_for(
            [{"id": "conflict", "name": "test.conflict"}],
            {"test.conflict": Conflicting},
        )
        with self.assertRaises(RegistrationConflictError):
            await runtime.start()
        self.assertEqual(runtime.state, LoaderState.NEW)

    async def test_stale_registration_does_not_remove_its_replacement(self):
        ref = service_key("test.stale")
        key = ref

        class Stale(Plugin[EmptyConfig]):
            name = "test.stale"
            version = "0.1.0"
            provides = (ref,)
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                first = ctx.provide(key, "first")
                await first.aclose()
                ctx.provide(key, "second")
                await first.aclose()

        runtime = runtime_for(
            [{"id": "stale", "name": "test.stale"}], {"test.stale": Stale}
        )
        await runtime.start()
        self.assertEqual(runtime.require(key), "second")
        await runtime.aclose()

    async def test_tracked_handles_and_dispose_callbacks_close_once_in_reverse_order(self):
        log = []

        class External:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True
                log.append("external")

        external = External()

        class Owner(Plugin[EmptyConfig]):
            name = "test.owner"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                ctx.track(external)
                ctx.on_dispose(lambda: log.append("sync"), label="sync")

                async def async_cleanup():
                    log.append("async")

                ctx.on_dispose(async_cleanup, label="async")

        runtime = runtime_for(
            [{"id": "owner", "name": "test.owner"}], {"test.owner": Owner}
        )
        await runtime.start()
        self.assertFalse(external.closed)
        await runtime.aclose()
        self.assertTrue(external.closed)
        self.assertEqual(log, ["async", "sync", "external"])
        await runtime.aclose()
        self.assertEqual(log, ["async", "sync", "external"])

    async def test_undeclared_service_access_is_rejected(self):
        class Undeclared(Plugin[EmptyConfig]):
            name = "test.undeclared"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                ctx.require(TOOLS)

        runtime = runtime_for(
            [{"id": "undeclared", "name": "test.undeclared"}],
            {"test.undeclared": Undeclared},
        )
        with self.assertRaises(UndeclaredServiceError):
            await runtime.start()

    async def test_undeclared_service_publication_is_rejected(self):
        class Undeclared(Plugin[EmptyConfig]):
            name = "test.undeclared"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                ctx.provide(TOOLS, object())

        runtime = runtime_for(
            [{"id": "undeclared", "name": "test.undeclared"}],
            {"test.undeclared": Undeclared},
        )
        with self.assertRaises(UndeclaredServiceError):
            await runtime.start()

    async def test_closed_context_rejects_new_work(self):
        captured = []

        class Capture(Plugin[EmptyConfig]):
            name = "test.capture"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                captured.append(ctx)

        runtime = runtime_for(
            [{"id": "capture", "name": "test.capture"}], {"test.capture": Capture}
        )
        await runtime.start()
        await runtime.aclose()
        ctx = captured[0]
        key = service_key("test.anything")

        class Handle:
            async def aclose(self):
                pass

        for operation in (
            lambda: ctx.require(key),
            lambda: ctx.get(key),
            lambda: ctx.provide(key, object()),
            lambda: ctx.track(Handle()),
            lambda: ctx.on_dispose(lambda: None, label="late"),
        ):
            with self.subTest(operation=operation), self.assertRaises(ServiceClosedError):
                operation()

    async def test_cancelled_start_rolls_back_and_propagates_cancellation(self):
        started = asyncio.Event()
        cleaned = []

        class Slow(Plugin[EmptyConfig]):
            name = "test.slow"
            version = "0.1.0"
            config_model = EmptyConfig

            async def setup(self, ctx, config):
                ctx.on_dispose(lambda: cleaned.append("closed"), label="closed")
                started.set()
                await asyncio.Event().wait()

        runtime = runtime_for(
            [{"id": "slow", "name": "test.slow"}], {"test.slow": Slow}
        )
        task = asyncio.create_task(runtime.start())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(cleaned, ["closed"])
        self.assertEqual(runtime.state, LoaderState.NEW)
        await runtime.aclose()

    async def test_runtime_state_transitions(self):
        runtime = runtime_for([], {})
        with self.assertRaises(LifecycleError):
            runtime.require(service_key("test.anything"))

        await runtime.start()
        with self.assertRaises(LifecycleError):
            await runtime.start()
        self.assertEqual(runtime.state, LoaderState.RUNNING)

        await runtime.aclose()
        await runtime.aclose()
        self.assertEqual(runtime.state, LoaderState.CLOSED)
        with self.assertRaises(ServiceClosedError):
            await runtime.start()
        with self.assertRaises(LifecycleError):
            runtime.require(service_key("test.anything"))

    async def test_host_services_remain_owned_by_the_host(self):
        class HostService:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True

        hosted = HostService()
        runtime = runtime_for(
            [],
            {},
            host_services={service_key("test.host"): hosted},
        )
        await runtime.start()
        self.assertIs(runtime.require(service_key("test.host")), hosted)
        await runtime.aclose()
        self.assertFalse(hosted.closed)


if __name__ == "__main__":
    unittest.main()
