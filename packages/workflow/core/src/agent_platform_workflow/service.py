"""Workflow persistence and execution service."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import psycopg2.errors

from agent_platform_agent_entry import AgentGateway
from agent_platform_plugin_sdk import AgentConfigService, Database

from .contracts import CacheFactory, NodeContext, WorkflowNodeRegistry
from .errors import WorkflowNameConflict, WorkflowNotFound, WorkflowValidationError
from .graph import MAX_TOTAL_STEPS, build_workflow
from .state import WorkflowState

logger = logging.getLogger(__name__)

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _safe_dumps(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False)
    return _SURROGATE_RE.sub("", raw)


class WorkflowService:
    """Tenant-scoped workflow CRUD plus graph execution."""

    def __init__(
        self,
        database: Database,
        agent_entry: AgentGateway,
        agents: AgentConfigService,
        nodes: WorkflowNodeRegistry,
        cache_factory: CacheFactory | None = None,
    ) -> None:
        self._database = database
        self._agent_entry = agent_entry
        self._agents = agents
        self._nodes = nodes
        self._cache_factory = cache_factory

    # ── CRUD ──

    async def list(self, tenant_id: int) -> list[dict[str, Any]]:
        def query() -> list[dict[str, Any]]:
            with self._database.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT id, name, status, jsonb_array_length(nodes) as node_count,
                                  created_at, updated_at
                           FROM workflows WHERE tenant_id = %s ORDER BY updated_at DESC""",
                        (tenant_id,),
                    )
                    return list(cur.fetchall())

        return await asyncio.to_thread(query)

    async def create(
        self,
        tenant_id: int,
        name: str,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        def insert() -> dict[str, Any]:
            try:
                with self._database.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO workflows (tenant_id, name, nodes, edges)
                               VALUES (%s, %s, %s::jsonb, %s::jsonb) RETURNING id""",
                            (
                                tenant_id, name,
                                _safe_dumps(nodes) if nodes else "[]",
                                _safe_dumps(edges) if edges else "[]",
                            ),
                        )
                        return {"id": cur.fetchone()["id"]}
            except psycopg2.errors.UniqueViolation as exc:
                raise WorkflowNameConflict("工作流名称已存在") from exc

        return await asyncio.to_thread(insert)

    async def get(self, workflow_id: int) -> dict[str, Any]:
        def query() -> dict[str, Any] | None:
            with self._database.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM workflows WHERE id = %s", (workflow_id,))
                    return cur.fetchone()

        row = await asyncio.to_thread(query)
        if row is None:
            raise WorkflowNotFound("工作流不存在")
        return row

    async def save(
        self,
        workflow_id: int,
        *,
        name: str | None = None,
        status: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        if nodes is not None:
            sets.append("nodes = %s::jsonb")
            params.append(_safe_dumps(nodes))
        if edges is not None:
            sets.append("edges = %s::jsonb")
            params.append(_safe_dumps(edges))
        if not sets:
            raise WorkflowValidationError("没有要更新的字段")
        sets.append("updated_at = now()")
        params.append(workflow_id)

        def update() -> None:
            try:
                with self._database.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE workflows SET {', '.join(sets)} WHERE id = %s",
                            params,
                        )
            except psycopg2.errors.UniqueViolation as exc:
                raise WorkflowNameConflict("工作流名称已存在") from exc

        await asyncio.to_thread(update)

    async def delete(self, workflow_id: int) -> None:
        def remove() -> None:
            with self._database.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM workflows WHERE id = %s", (workflow_id,))

        await asyncio.to_thread(remove)

    # ── execution ──

    async def run(
        self, workflow_id: int, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            workflow = await self.get(workflow_id)
        except WorkflowNotFound as exc:
            yield {"type": "error", "message": str(exc)}
            return

        nodes = workflow.get("nodes") or []
        edges = workflow.get("edges") or []
        if not nodes:
            yield {"type": "error", "message": "工作流没有节点"}
            return

        def context_for(node_id: str, config: dict[str, Any]) -> NodeContext:
            return NodeContext(
                node_id=node_id,
                config=config,
                agent_entry=self._agent_entry,
                agents=self._agents,
                cache_factory=self._cache_factory,
            )

        try:
            graph = await build_workflow(
                nodes, edges, registry=self._nodes, context_for=context_for,
            )
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "message": f"构建工作流失败: {exc}"}
            return

        initial_state: WorkflowState = {
            "input": payload.get("input", ""),
            "user_id": payload.get("user_id", ""),
            "tenant_id": workflow["tenant_id"],
            "node_results": {},
            "node_timeline": [],
            "output": "",
        }

        logger.info(
            "[workflow] start id=%s nodes=%s edges=%s",
            workflow_id, len(nodes), len(edges),
        )
        final_output = ""
        try:
            async for chunk in graph.astream(initial_state, {"recursion_limit": MAX_TOTAL_STEPS}):
                for value in chunk.values():
                    for entry in value.get("node_timeline") or []:
                        yield {"type": "node_done", **entry}
                    output = value.get("output")
                    if output:
                        final_output = str(output)
            yield {"type": "workflow_done", "output": final_output}
        except Exception as exc:  # noqa: BLE001
            logger.error("[workflow] execution failed: %s", exc)
            yield {"type": "error", "message": f"执行异常: {exc}"}
