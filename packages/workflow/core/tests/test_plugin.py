import unittest

from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_llm import LLM
from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import (
    AGENTS,
    DATABASE,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

from agent_platform_workflow import (
    WORKFLOW,
    WORKFLOW_NODES,
    NodeContext,
    NodeDefinition,
    WorkflowPlugin,
    WorkflowService,
)


class FakeDatabase:
    def get_conn(self):
        raise AssertionError("plugin setup must not open a connection")


class FakeAgents:
    async def get_definition(self, agent_key: str):
        return {}


class FakeAgentEntry:
    async def chat(self, context, question):
        raise AssertionError("plugin setup must not call the agent")


class FakeLLM:
    async def embed(self, text: str, model: str = "bge-m3"):
        return None


class NodeContributor:
    spec = PluginSpec(
        name="test.workflow-node",
        version="0.1.0",
        requires=(ServiceRequirement(service=WORKFLOW_NODES.ref),),
    )
    config_model = SdkModel

    def __init__(self):
        self.registered = []

    async def setup(self, ctx, config):
        registry = ctx.require(WORKFLOW_NODES)

        async def factory(context: NodeContext) -> NodeDefinition:
            async def handler(state):
                return {"node_results": {context.node_id: "custom"}}

            return NodeDefinition(handler=handler)

        ctx.track(registry.register("custom", factory))
        self.registered.append("custom")


class WorkflowPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_provides_service_and_accepts_node_extensions(self):
        contributor = NodeContributor()
        runtime = PluginRuntime(
            {"plugins": [
                {"id": "workflow", "name": "agent-platform.workflow"},
                {"id": "contributor", "name": "test.workflow-node"},
            ]},
            catalog=MappingCatalog({
                "agent-platform.workflow": WorkflowPlugin,
                "test.workflow-node": lambda: contributor,
            }),
            host_services={
                DATABASE: FakeDatabase(),
                AGENTS: FakeAgents(),
                AGENT_ENTRY: FakeAgentEntry(),
                LLM: FakeLLM(),
            },
        )
        try:
            await runtime.start()
            service = runtime.require(WORKFLOW)
            self.assertIsInstance(service, WorkflowService)
            kinds = runtime.require(WORKFLOW_NODES).kinds()
            self.assertTrue({"start", "end", "agent", "condition", "router", "custom"} <= set(kinds))
            self.assertEqual(contributor.registered, ["custom"])
        finally:
            await runtime.aclose()
