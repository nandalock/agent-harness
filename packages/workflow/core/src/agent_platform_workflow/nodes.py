"""Built-in workflow node kinds.

Each factory returns a NodeDefinition. New node kinds register the same shape
through the workflow.nodes.v1 service.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from agent_platform_agent_entry import RequestContext

from .cache.middleware import CacheMiddleware
from .contracts import FindNode, NodeContext, NodeDefinition, RoutePlan
from .state import WorkflowState

logger = logging.getLogger(__name__)


def _timeline_entry(
    node_id: str, label: str, node_type: str, output: str, ms: int
) -> list[dict[str, Any]]:
    return [{
        "node_id": node_id, "label": label, "node_type": node_type,
        "output": output, "ms": ms,
    }]


def _build_context(state: WorkflowState) -> dict[str, Any]:
    """Build upstream context from node_results + node_timeline."""
    timeline = state.get("node_timeline") or []
    node_results = state.get("node_results") or {}

    node_info: dict[str, dict[str, str]] = {}
    for entry in timeline:
        node_id = entry["node_id"]
        if node_id not in node_info:
            node_info[node_id] = {
                "label": entry.get("label", node_id),
                "type": entry.get("node_type", "unknown"),
            }

    result: dict[str, Any] = {}
    for node_id, output in node_results.items():
        info = node_info.get(node_id, {})
        key = info.get("label", node_id)
        result[key] = {"output": output, "type": info.get("type", "unknown")}
    return result


async def start_node(context: NodeContext) -> NodeDefinition:
    async def handler(state: WorkflowState) -> dict[str, Any]:
        return {
            "node_timeline": _timeline_entry("start", "开始", "start", state["input"], 0),
        }

    return NodeDefinition(handler=handler)


async def end_node(context: NodeContext) -> NodeDefinition:
    async def handler(state: WorkflowState) -> dict[str, Any]:
        last = state["input"]
        timeline = state.get("node_timeline") or []
        if timeline:
            last = str(timeline[-1].get("output", last))
        return {
            "output": last,
            "node_timeline": _timeline_entry("end", "结束", "end", last, 0),
        }

    return NodeDefinition(handler=handler)


_CACHE_POLICY_FIELDS = (
    "base_score", "cacheable_intents", "block_entities", "content_hint", "scorer_weights",
)


async def agent_node(context: NodeContext) -> NodeDefinition:
    agent_key = str(context.config.get("agent_key") or "")
    if not agent_key:
        raise ValueError(f"Agent 节点 {context.node_id} 缺少 agent_key")

    cache_config = context.config.get("cache") or {}
    cache = None
    if cache_config.get("enabled") and context.cache_factory is not None:
        definition = await context.agents.get_definition(agent_key) or {}
        base_policy = definition.get("cache_policy") or {
            "base_score": 0.50, "cacheable_intents": [], "block_entities": [],
        }
        overrides = {
            field: cache_config[field]
            for field in _CACHE_POLICY_FIELDS
            if field in cache_config
        }
        cache = context.cache_factory(
            context.node_id, cache_config, {**base_policy, **overrides},
        )

    async def core(state: WorkflowState) -> dict[str, Any]:
        upstream = _build_context(state)
        started = time.time()
        try:
            reply = await context.agent_entry.chat(
                RequestContext(
                    tenant_id=state.get("tenant_id"),
                    agent_key=agent_key,
                    channel="workflow",
                    visitor_id=state.get("user_id") or None,
                    context=upstream,
                ),
                state["input"],
            )
            answer = reply.answer
        except Exception as exc:  # noqa: BLE001
            logger.error("[workflow] agent %s error: %s", agent_key, exc)
            answer = f"Agent 调用失败: {exc}"

        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "node_results": {context.node_id: answer},
            "node_timeline": _timeline_entry(
                context.node_id, agent_key, "agent", answer, elapsed_ms,
            ),
        }

    handler = core
    if cache is not None:
        middleware = CacheMiddleware(context.node_id, cache)

        async def cached(state: WorkflowState) -> dict[str, Any]:
            return await middleware.process(state, context.node_id, core)

        handler = cached

    return NodeDefinition(handler=handler)


async def condition_node(context: NodeContext) -> NodeDefinition:
    async def handler(state: WorkflowState) -> dict[str, Any]:
        return {
            "node_timeline": _timeline_entry(context.node_id, "条件判断", "condition", "", 0),
        }

    def route(node_ctx: NodeContext, targets: tuple[str, ...], find_node: FindNode) -> RoutePlan:
        branches = node_ctx.config.get("branches", [])
        path_map: dict[str, str] = {b["label"]: b["target"] for b in branches}
        if not path_map and targets:
            path_map = {target: target for target in targets}

        def router(state: WorkflowState) -> str:
            field = node_ctx.config.get("field", "")
            raw: Any = state.get("node_results", {})
            for part in field.split("."):
                if isinstance(raw, dict) and part in raw:
                    raw = raw[part]
                elif isinstance(raw, str):
                    break
                else:
                    raw = ""
                    break
            raw = str(raw)

            op = node_ctx.config.get("op", "contains")
            expected = node_ctx.config.get("value", "")
            matched = (
                (op == "equals" and raw == expected)
                or (op == "contains" and expected in raw)
                or (op == "startsWith" and raw.startswith(expected))
            )
            if matched and branches:
                label = branches[0]["label"]
            elif branches:
                label = branches[-1]["label"]
            else:
                return list(path_map.keys())[-1] if path_map else "__end__"
            return label if label in path_map else (
                list(path_map.keys())[-1] if path_map else "__end__"
            )

        return RoutePlan(router=router, path_map=path_map)

    return NodeDefinition(handler=handler, route=route)


async def router_node(context: NodeContext) -> NodeDefinition:
    agent_key = str(context.config.get("agent_key") or "router")

    async def handler(state: WorkflowState) -> dict[str, Any]:
        upstream = _build_context(state)
        started = time.time()
        try:
            reply = await context.agent_entry.chat(
                RequestContext(
                    tenant_id=state.get("tenant_id"),
                    agent_key=agent_key,
                    channel="workflow",
                    visitor_id=state.get("user_id") or None,
                    context=upstream,
                ),
                state["input"],
            )
            raw = reply.answer
            trace = reply.trace or {}
            level = trace.get("route_level", "?")
            confidence = trace.get("confidence", 0)
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else {}
                intent = parsed.get("agent_key", raw)
                level = parsed.get("route_level", level)
                confidence = parsed.get("confidence", confidence)
                clarify_message = parsed.get("message", "")
            except (json.JSONDecodeError, TypeError):
                intent = raw if isinstance(raw, str) else "human_handoff"
                clarify_message = ""
        except Exception as exc:  # noqa: BLE001
            logger.error("[workflow] router %s error: %s", agent_key, exc)
            intent = "human_handoff"
            level = "error"
            confidence = 0
            clarify_message = ""

        elapsed_ms = int((time.time() - started) * 1000)
        if intent is None:
            return {
                "node_results": {context.node_id: "__clarify__"},
                "node_timeline": _timeline_entry(
                    context.node_id, "路由拦截", "router", clarify_message, elapsed_ms,
                ),
            }
        return {
            "node_results": {context.node_id: intent},
            "node_timeline": _timeline_entry(
                context.node_id, f"路由 → {intent}", "router",
                f"[{level}] {intent} ({confidence:.0%})", elapsed_ms,
            ),
        }

    def route(node_ctx: NodeContext, targets: tuple[str, ...], find_node: FindNode) -> RoutePlan:
        path_map: dict[str, str] = {}
        for target in targets:
            target_node = find_node(target)
            target_key = ""
            if target_node:
                target_key = (
                    target_node.get("data", {}).get("config", {}) or {}
                ).get("agent_key", "")
            path_map[target_key or target] = target
        if not path_map:
            path_map = {target: target for target in targets}

        def router(state: WorkflowState) -> str:
            intent = state.get("node_results", {}).get(node_ctx.node_id)
            if intent is None:
                return list(path_map.keys())[0] if path_map else "__end__"
            if intent == "__clarify__":
                return "__end__"
            intent_text = str(intent)
            if intent_text in path_map:
                return intent_text
            return list(path_map.keys())[0] if path_map else "__end__"

        return RoutePlan(router=router, path_map=path_map)

    return NodeDefinition(handler=handler, route=route)


BUILTIN_NODES = {
    "start": start_node,
    "end": end_node,
    "agent": agent_node,
    "condition": condition_node,
    "router": router_node,
}
