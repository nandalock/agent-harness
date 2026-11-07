import unittest

from agent_platform_plugin_sdk import RegistrationConflictError, ServiceClosedError

from agent_platform_workflow import (
    NodeContext,
    NodeDefinition,
    WorkflowNodeRegistry,
    WorkflowValidationError,
)


async def echo_factory(context: NodeContext) -> NodeDefinition:
    async def handler(state: dict) -> dict:
        return {"node_results": {context.node_id: "ok"}}

    return NodeDefinition(handler=handler)


class NodeRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_build_and_duplicate(self):
        registry = WorkflowNodeRegistry()
        registration = registry.register("echo", echo_factory)
        self.assertEqual(registry.kinds(), ("echo",))
        definition = await registry.build(
            "echo",
            NodeContext("n1", {}, object(), object()),
        )
        self.assertEqual(await definition.handler({"input": "x"}), {"node_results": {"n1": "ok"}})

        with self.assertRaises(RegistrationConflictError):
            registry.register("echo", echo_factory)

        await registration.aclose()
        self.assertEqual(registry.kinds(), ())
        await registry.aclose()

    async def test_unknown_kind_names_registered_kinds(self):
        registry = WorkflowNodeRegistry()
        registry.register("echo", echo_factory)
        with self.assertRaisesRegex(WorkflowValidationError, "echo"):
            await registry.build("missing", NodeContext("n1", {}, object(), object()))

    async def test_closed_registry_rejects_build(self):
        registry = WorkflowNodeRegistry()
        await registry.aclose()
        with self.assertRaises(ServiceClosedError):
            await registry.build("echo", NodeContext("n1", {}, object(), object()))
