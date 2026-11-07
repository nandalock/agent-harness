"""Workflow plugin: persistence, execution and the node extension registry."""
from __future__ import annotations

import os
from typing import Any

from pydantic import Field

from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS,
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

from .cache.config import CacheConfig
from .cache.semantic import SemanticCache
from .cache.store import RedisCacheStore
from .contracts import WORKFLOW, WORKFLOW_NODES
from .nodes import BUILTIN_NODES
from .registry import WorkflowNodeRegistry
from .service import WorkflowService


class WorkflowConfig(SdkModel):
    redis_url: str | None = None
    cache_enabled: bool = Field(default=True, alias="cacheEnabled")


class WorkflowPlugin:
    spec = PluginSpec(
        name="agent-platform.workflow",
        web_package=__package__,
        version="0.1.0",
        provides=(WORKFLOW_NODES.ref, WORKFLOW.ref),
        requires=(
            ServiceRequirement(service=DATABASE.ref),
            ServiceRequirement(service=AGENT_ENTRY.ref),
            ServiceRequirement(service=AGENTS.ref),
            ServiceRequirement(service=LLM.ref),
        ),
    )
    config_model = WorkflowConfig

    async def setup(self, ctx: PluginContext, config: WorkflowConfig) -> None:
        registry = WorkflowNodeRegistry()
        for kind, factory in BUILTIN_NODES.items():
            ctx.track(registry.register(kind, factory))

        store = RedisCacheStore(
            config.redis_url or os.environ.get("REDIS_URL", "redis://redis:6379/0")
        )
        llm = ctx.require(LLM)

        def cache_factory(
            node_id: str,
            cache_config: dict[str, Any],
            cache_policy: dict[str, Any] | None,
        ) -> SemanticCache | None:
            if not config.cache_enabled:
                return None
            node_cache = CacheConfig.from_node_config(cache_config)
            if not node_cache.enabled:
                return None
            agent_config = {"cache_policy": cache_policy} if cache_policy else None
            return SemanticCache(
                node_cache, node_id, agent_config,
                get_redis=store.get, embed=llm.embed,
            )

        service = WorkflowService(
            ctx.require(DATABASE),
            ctx.require(AGENT_ENTRY),
            ctx.require(AGENTS),
            registry,
            cache_factory,
        )
        ctx.provide(WORKFLOW_NODES, registry)
        ctx.provide(WORKFLOW, service)
        ctx.on_dispose(registry.aclose, label="workflow node registry")
        ctx.on_dispose(store.aclose, label="workflow redis cache")


plugin = WorkflowPlugin()
