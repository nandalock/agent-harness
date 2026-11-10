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
    SdkModel,
)

from .cache.config import CacheConfig
from .cache.semantic import SemanticCache
from .cache.store import RedisCacheStore
from .contracts import WORKFLOW, WORKFLOW_NODES
from .nodes import BUILTIN_NODES
from .registry import WorkflowNodeRegistry
from .service import WorkflowService
from minidsh_cordis import Context, Plugin


class WorkflowConfig(SdkModel):
    redis_url: str | None = None
    cache_enabled: bool = Field(default=True, alias="cacheEnabled")


class WorkflowPlugin(Plugin[WorkflowConfig]):
    name = "agent-platform.workflow"
    web_package = __package__
    version = "0.1.0"
    provides = (WORKFLOW_NODES, WORKFLOW)
    requires = (DATABASE, AGENT_ENTRY, AGENTS, LLM)
    config_model = WorkflowConfig

    async def setup(self, ctx: Context, config: WorkflowConfig) -> None:
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
