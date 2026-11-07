"""Agent definitions/configs and tool bindings backed by database.v1."""
from __future__ import annotations

import asyncio
import json
from typing import Any


class AgentConfigService:
    def __init__(self, database) -> None:
        self._database = database

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    def _get_definition_sync(self, agent_key: str) -> dict | None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT agent_key, name, description, config, status, agent_type, cache_policy "
                    "FROM agent_definitions WHERE agent_key = %s",
                    (agent_key,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def _list_definitions_sync(self) -> list[dict]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT agent_key, name, description, config, status, agent_type, cache_policy "
                    "FROM agent_definitions WHERE status IS DISTINCT FROM 'archived' ORDER BY agent_key"
                )
                return [dict(row) for row in cur.fetchall()]

    def _get_config_sync(self, agent_key: str) -> dict | None:
        definition = self._get_definition_sync(agent_key)
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT config FROM agent_configs WHERE agent_key = %s", (agent_key,))
                row = cur.fetchone()
        if definition is None and row is None:
            return None
        base = (definition or {}).get("config") or {}
        override = dict(row["config"]) if row else {}
        return {**base, **override}

    def _save_config_sync(self, agent_key: str, config: dict) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_configs (agent_key, config, updated_at)
                       VALUES (%s, %s::jsonb, now())
                       ON CONFLICT (agent_key)
                       DO UPDATE SET config = EXCLUDED.config, updated_at = now()
                       RETURNING config""",
                    (agent_key, json.dumps(config)),
                )
                return dict(cur.fetchone()["config"])

    async def get_config(self, agent_key: str) -> dict | None:
        return await self._run(self._get_config_sync, agent_key)

    async def get_definition(self, agent_key: str) -> dict | None:
        return await self._run(self._get_definition_sync, agent_key)

    async def list_definitions(self) -> list[dict]:
        return await self._run(self._list_definitions_sync)

    async def save_config(self, agent_key: str, config: dict) -> dict:
        return await self._run(self._save_config_sync, agent_key, config)

    def _create_definition_sync(
        self, agent_key: str, name: str, description: str, config: dict,
        agent_type: str, cache_policy: dict | None,
    ) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO agent_definitions
                           (agent_key, name, description, config, status, agent_type, cache_policy)
                       VALUES (%s, %s, %s, %s::jsonb, 'active', %s, %s::jsonb)
                       ON CONFLICT (agent_key) DO UPDATE
                       SET name = EXCLUDED.name, description = EXCLUDED.description,
                           config = EXCLUDED.config, agent_type = EXCLUDED.agent_type,
                           status = 'active',
                           cache_policy = COALESCE(agent_definitions.cache_policy, EXCLUDED.cache_policy)
                       RETURNING agent_key, name, description, config, status, agent_type, cache_policy""",
                    (
                        agent_key, name, description, json.dumps(config), agent_type,
                        json.dumps(cache_policy) if cache_policy is not None else None,
                    ),
                )
                return dict(cur.fetchone())

    async def create_definition(
        self, agent_key: str, name: str, description: str, config: dict,
        agent_type: str, cache_policy: dict | None = None,
    ) -> dict:
        return await self._run(
            self._create_definition_sync, agent_key, name, description, config,
            agent_type, cache_policy,
        )

    def _update_cache_policy_sync(self, agent_key: str, cache_policy: dict) -> None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_definitions SET cache_policy = %s::jsonb, updated_at = now() "
                    "WHERE agent_key = %s",
                    (json.dumps(cache_policy), agent_key),
                )

    async def update_cache_policy(self, agent_key: str, cache_policy: dict) -> None:
        await self._run(self._update_cache_policy_sync, agent_key, cache_policy)

    # ── router L1 keywords ──

    def _list_keywords_sync(self, router_key: str) -> list[dict]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, router_key, keywords, target, created_at "
                    "FROM router_l1_keywords WHERE router_key = %s ORDER BY id",
                    (router_key,),
                )
                return [dict(row) for row in cur.fetchall()]

    def _create_keyword_sync(self, router_key: str, keywords: list[str], target: str) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO router_l1_keywords (router_key, keywords, target) "
                    "VALUES (%s, %s, %s) RETURNING id, router_key, keywords, target, created_at",
                    (router_key, keywords, target),
                )
                return dict(cur.fetchone())

    def _update_keyword_sync(self, rule_id: int, router_key: str, keywords: list[str], target: str) -> dict | None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE router_l1_keywords SET keywords = %s, target = %s "
                    "WHERE id = %s AND router_key = %s "
                    "RETURNING id, router_key, keywords, target, created_at",
                    (keywords, target, rule_id, router_key),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def _delete_keyword_sync(self, rule_id: int, router_key: str) -> bool:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM router_l1_keywords WHERE id = %s AND router_key = %s",
                    (rule_id, router_key),
                )
                return cur.rowcount > 0

    async def list_l1_keywords(self, router_key: str) -> list[dict]:
        return await self._run(self._list_keywords_sync, router_key)

    async def create_l1_keyword(self, router_key: str, keywords: list[str], target: str) -> dict:
        return await self._run(self._create_keyword_sync, router_key, keywords, target)

    async def update_l1_keyword(self, rule_id: int, router_key: str, keywords: list[str], target: str) -> dict | None:
        return await self._run(self._update_keyword_sync, rule_id, router_key, keywords, target)

    async def delete_l1_keyword(self, rule_id: int, router_key: str) -> bool:
        return await self._run(self._delete_keyword_sync, rule_id, router_key)


class ToolBindingsService:
    """Synchronous reader required by ToolRegistry (called during agent runs)."""

    def __init__(self, database) -> None:
        self._database = database

    def get_bindings(self, agent_key: str) -> list[str]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tool_name FROM agent_tool_bindings WHERE agent_key = %s",
                    (agent_key,),
                )
                return [row["tool_name"] for row in cur.fetchall()]
