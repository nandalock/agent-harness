"""Build a LangGraph workflow from nodes, edges and the node registry."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from langgraph.graph import END, StateGraph

from .contracts import NodeContext, WorkflowNodeRegistry
from .state import WorkflowState

logger = logging.getLogger(__name__)

MAX_TOTAL_STEPS = 20


def _node_type(node: dict[str, Any]) -> str:
    return node.get("data", {}).get("nodeType", "")


async def build_workflow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    registry: WorkflowNodeRegistry,
    context_for: Any,
) -> Any:
    """Compile one workflow graph.

    ``context_for(node_id, config)`` produces the NodeContext for a node.
    """
    start_nodes = [node for node in nodes if _node_type(node) == "start"]
    end_nodes = [node for node in nodes if _node_type(node) == "end"]
    if not start_nodes:
        raise ValueError("工作流缺少 start 节点")
    if not end_nodes:
        raise ValueError("工作流缺少 end 节点")

    by_id = {node["id"]: node for node in nodes}

    def find_node(node_id: str) -> dict[str, Any] | None:
        return by_id.get(node_id)

    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["source"]].append(edge["target"])

    graph = StateGraph(WorkflowState)
    definitions = {}

    for node in nodes:
        node_id = node["id"]
        node_kind = _node_type(node)
        config = node.get("data", {}).get("config", {}) or {}
        context: NodeContext = context_for(node_id, config)
        definition = await registry.build(node_kind, context)
        definitions[node_id] = (definition, context)
        graph.add_node(node_id, definition.handler)

    for source_id, targets in outgoing.items():
        source = definitions.get(source_id)
        if source is None:
            continue
        definition, context = source
        plan = definition.route(context, tuple(targets), find_node) if definition.route else None
        if plan is not None:
            graph.add_conditional_edges(
                source_id, plan.router, {**plan.path_map, "__end__": END},
            )
        else:
            for target in targets:
                graph.add_edge(source_id, target)

    graph.set_entry_point(start_nodes[0]["id"])
    graph.set_finish_point(end_nodes[0]["id"])
    return graph.compile()
