# agent-platform.workflow

Workflow CRUD, execution and an extensible node-kind registry.

## Services

| Key | Purpose |
| --- | --- |
| `workflow.v1` | tenant-scoped list/create/get/save/delete/run |
| `workflow.nodes.v1` | node-kind registry (`register`, `build`, `kinds`) |

The plugin registers the built-in kinds `start`, `end`, `agent`, `condition`
and `router`. A `NodeFactory` receives a `NodeContext` with the agent entry,
agent config and node cache, and returns a `NodeDefinition`:

```python
from agent_platform_workflow.contracts import NodeContext, NodeDefinition, WORKFLOW_NODES

class KnowledgeNodePlugin:
    spec = PluginSpec(
        name="example.knowledge-node",
        version="0.1.0",
        requires=(ServiceRequirement(service=WORKFLOW_NODES.ref),),
    )
    config_model = SdkModel

    async def setup(self, ctx, config):
        registry = ctx.require(WORKFLOW_NODES)

        async def factory(context: NodeContext) -> NodeDefinition:
            async def handler(state):
                return {"node_results": {context.node_id: "..."}}

            return NodeDefinition(handler=handler)

        ctx.track(registry.register("knowledge", factory))
```

A node kind may also return a `RoutePlan` from `NodeDefinition.route` to own
its conditional edges (see `condition` and `router`).

The HTTP plugin resolves `workflow.v1` optionally and only mounts
`/api/workflows` when the provider is present, so disabling this plugin removes
the API together with the frontend bundle.
