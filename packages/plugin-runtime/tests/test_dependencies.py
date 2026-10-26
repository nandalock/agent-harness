import unittest

from agent_platform_plugin_runtime import (
    DependencyCycleError,
    MissingServiceError,
    MappingCatalog,
    PluginRuntime,
    ServiceConflictError,
)
from support import plugin_class, requirement, service_key, service_ref


def runtime_for(entries, catalog, host_services=None):
    return PluginRuntime(
        {"version": 1, "plugins": entries},
        catalog=MappingCatalog(catalog),
        host_services=host_services,
    )


class DependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_starts_before_consumer_regardless_of_config_order(self):
        log = []
        ref = service_ref("test.service")
        consumer = plugin_class(
            "test.consumer", requires=(requirement("test.service"),), log=log
        )
        provider = plugin_class("test.provider", provides=(ref,), log=log)
        runtime = runtime_for(
            [
                {"id": "consumer", "name": "test.consumer"},
                {"id": "provider", "name": "test.provider"},
            ],
            {"test.consumer": consumer, "test.provider": provider},
        )
        await runtime.start()
        self.assertEqual(log, ["setup:test.provider", "setup:test.consumer"])
        await runtime.aclose()
        self.assertEqual(
            log,
            [
                "setup:test.provider",
                "setup:test.consumer",
                "close:test.consumer",
                "close:test.provider",
            ],
        )

    async def test_missing_required_service_is_reported_before_setup(self):
        log = []
        consumer = plugin_class(
            "test.consumer", requires=(requirement("test.absent"),), log=log
        )
        runtime = runtime_for(
            [{"id": "consumer", "name": "test.consumer"}],
            {"test.consumer": consumer},
        )
        with self.assertRaises(MissingServiceError) as raised:
            await runtime.start()
        message = str(raised.exception)
        self.assertIn("consumer", message)
        self.assertIn("test.absent.v1", message)
        self.assertEqual(log, [])

    async def test_missing_optional_service_is_allowed(self):
        log = []
        consumer = plugin_class(
            "test.consumer",
            requires=(requirement("test.absent", optional=True),),
            log=log,
        )
        runtime = runtime_for(
            [{"id": "consumer", "name": "test.consumer"}],
            {"test.consumer": consumer},
        )
        await runtime.start()
        self.assertEqual(log, ["setup:test.consumer"])
        await runtime.aclose()

    async def test_two_plugins_cannot_provide_the_same_service(self):
        ref = service_ref("test.service")
        first = plugin_class("test.first", provides=(ref,))
        second = plugin_class("test.second", provides=(ref,))
        runtime = runtime_for(
            [
                {"id": "first", "name": "test.first"},
                {"id": "second", "name": "test.second"},
            ],
            {"test.first": first, "test.second": second},
        )
        with self.assertRaises(ServiceConflictError) as raised:
            await runtime.start()
        self.assertIn("test.service.v1", str(raised.exception))

    async def test_plugin_cannot_shadow_a_host_service(self):
        consumer = plugin_class("test.hosted", provides=(service_ref("test.service"),))
        runtime = runtime_for(
            [{"id": "hosted", "name": "test.hosted"}],
            {"test.hosted": consumer},
            host_services={service_key("test.service"): object()},
        )
        with self.assertRaises(ServiceConflictError):
            await runtime.start()

    async def test_host_service_satisfies_a_requirement_without_a_plugin_provider(self):
        hosted = object()
        log = []
        consumer = plugin_class(
            "test.consumer", requires=(requirement("test.service"),), log=log
        )
        runtime = runtime_for(
            [{"id": "consumer", "name": "test.consumer"}],
            {"test.consumer": consumer},
            host_services={service_key("test.service"): hosted},
        )
        await runtime.start()
        self.assertEqual(log, ["setup:test.consumer"])
        self.assertIs(runtime.require(service_key("test.service")), hosted)
        await runtime.aclose()

    async def test_required_cycle_is_rejected(self):
        first = plugin_class(
            "test.first",
            provides=(service_ref("test.a"),),
            requires=(requirement("test.b"),),
        )
        second = plugin_class(
            "test.second",
            provides=(service_ref("test.b"),),
            requires=(requirement("test.a"),),
        )
        runtime = runtime_for(
            [
                {"id": "first", "name": "test.first"},
                {"id": "second", "name": "test.second"},
            ],
            {"test.first": first, "test.second": second},
        )
        with self.assertRaises(DependencyCycleError) as raised:
            await runtime.start()
        self.assertIn("->", str(raised.exception))

    async def test_optional_edges_still_order_and_can_form_a_cycle(self):
        log = []
        provider = plugin_class(
            "test.provider", provides=(service_ref("test.b"),), log=log
        )
        consumer = plugin_class(
            "test.consumer",
            provides=(service_ref("test.a"),),
            requires=(requirement("test.b", optional=True),),
            log=log,
        )
        runtime = runtime_for(
            [
                {"id": "consumer", "name": "test.consumer"},
                {"id": "provider", "name": "test.provider"},
            ],
            {"test.consumer": consumer, "test.provider": provider},
        )
        await runtime.start()
        self.assertEqual(log, ["setup:test.provider", "setup:test.consumer"])
        await runtime.aclose()

        first = plugin_class(
            "test.one",
            provides=(service_ref("test.c"),),
            requires=(requirement("test.d", optional=True),),
        )
        second = plugin_class(
            "test.two",
            provides=(service_ref("test.d"),),
            requires=(requirement("test.c", optional=True),),
        )
        cyclic = runtime_for(
            [
                {"id": "one", "name": "test.one"},
                {"id": "two", "name": "test.two"},
            ],
            {"test.one": first, "test.two": second},
        )
        with self.assertRaises(DependencyCycleError):
            await cyclic.start()

    async def test_self_requirement_is_rejected(self):
        plugin = plugin_class(
            "test.self",
            provides=(service_ref("test.self-service"),),
            requires=(requirement("test.self-service"),),
        )
        runtime = runtime_for(
            [{"id": "self", "name": "test.self"}], {"test.self": plugin}
        )
        with self.assertRaises(DependencyCycleError):
            await runtime.start()

    async def test_disabled_provider_cannot_satisfy_a_requirement(self):
        consumer = plugin_class(
            "test.consumer", requires=(requirement("test.service"),)
        )
        runtime = runtime_for(
            [
                {"id": "provider", "name": "test.provider", "disabled": True},
                {"id": "consumer", "name": "test.consumer"},
            ],
            {"test.consumer": consumer, "test.provider": plugin_class("test.provider")},
        )
        with self.assertRaises(MissingServiceError):
            await runtime.start()


if __name__ == "__main__":
    unittest.main()
