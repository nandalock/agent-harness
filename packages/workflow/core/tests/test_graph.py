import unittest

from agent_platform_workflow import (
    BUILTIN_NODES,
    NodeContext,
    NodeDefinition,
    WorkflowNodeRegistry,
    build_workflow,
)


class FakeAgents:
    async def get_definition(self, agent_key: str):
        return {"cache_policy": {"base_score": 0.5}}


async def echo_factory(context: NodeContext) -> NodeDefinition:
    async def handler(state: dict) -> dict:
        return {
            "node_results": {context.node_id: "ok"},
            "node_timeline": [{
                "node_id": context.node_id, "label": "echo", "node_type": "echo",
                "output": "ok", "ms": 0,
            }],
        }

    return NodeDefinition(handler=handler)


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def _registry(self) -> WorkflowNodeRegistry:
        registry = WorkflowNodeRegistry()
        for kind, factory in BUILTIN_NODES.items():
            registry.register(kind, factory)
        registry.register("echo", echo_factory)
        return registry

    async def test_registered_node_kind_participates_in_conditional_routing(self):
        registry = await self._registry()
        nodes = [
            {"id": "s", "data": {"nodeType": "start"}},
            {"id": "echo", "data": {"nodeType": "echo", "config": {}}},
            {
                "id": "cond",
                "data": {
                    "nodeType": "condition",
                    "config": {
                        "field": "echo",
                        "op": "equals",
                        "value": "ok",
                        "branches": [{"label": "hit", "target": "end"}],
                    },
                },
            },
            {"id": "end", "data": {"nodeType": "end"}},
        ]
        edges = [
            {"source": "s", "target": "echo"},
            {"source": "echo", "target": "cond"},
            {"source": "cond", "target": "end"},
        ]

        def context_for(node_id: str, config: dict) -> NodeContext:
            return NodeContext(node_id, config, None, FakeAgents())

        graph = await build_workflow(
            nodes, edges, registry=registry, context_for=context_for,
        )
        result = await graph.ainvoke(
            {
                "input": "hello", "user_id": "u", "tenant_id": 1,
                "node_results": {}, "node_timeline": [], "output": "",
            },
            {"recursion_limit": 20},
        )
        self.assertEqual(result["node_results"]["echo"], "ok")
        self.assertEqual(result["node_timeline"][-1]["node_type"], "end")

    async def test_missing_start_is_rejected(self):
        registry = await self._registry()

        def context_for(node_id: str, config: dict) -> NodeContext:
            return NodeContext(node_id, config, None, FakeAgents())

        with self.assertRaisesRegex(ValueError, "start"):
            await build_workflow(
                [{"id": "end", "data": {"nodeType": "end"}}], [],
                registry=registry, context_for=context_for,
            )
