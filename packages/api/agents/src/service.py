"""Agent configuration business operations over plugin services."""
from __future__ import annotations

import json
from typing import Any

from agent_platform_rpc_gateway import RpcError

_DEFAULT_CACHE_POLICY = {
    "base_score": 0.50,
    "cacheable_intents": [],
    "block_entities": [
        {"name": "手机号", "pattern": r"\b1[3-9]\d{9}\b", "penalty": 0.0},
        {"name": "身份证", "pattern": r"\b\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b", "penalty": 0.0},
        {"name": "订单号", "pattern": r"\b\d{15,20}\b", "penalty": 0.0},
        {"name": "日期", "pattern": r"\b\d{4}-\d{2}-\d{2}\b", "penalty": 0.2},
        {"name": "金额", "pattern": r"\d+\.?\d*\s*元", "penalty": 0.2},
    ],
}


class AgentApiService:
    def __init__(self, agents, llm, database) -> None:
        self._agents = agents
        self._llm = llm
        self._database = database

    async def list(self):
        definitions = await self._agents.list_definitions()
        items = []
        for row in definitions:
            agent_type = row.get("agent_type") or "agent"
            item = {
                "key": row["agent_key"],
                "name": row.get("name") or row["agent_key"],
                "desc": row.get("description") or "",
                "status": row.get("status") or "active",
                "agent_type": agent_type,
                "cache_policy": row.get("cache_policy") or _DEFAULT_CACHE_POLICY,
            }
            if agent_type == "router":
                item["routable"] = await self._router_targets(row["agent_key"])
            items.append(item)
        return items

    async def _router_targets(self, agent_key: str) -> list[str]:
        targets: list[str] = []

        def add(value: object) -> None:
            key = str(value or "").strip()
            if key and key not in targets:
                targets.append(key)

        config = await self._agents.get_config(agent_key) or {}
        for entry in config.get("routable_agents") or []:
            if isinstance(entry, dict):
                add(entry.get("key"))
        try:
            for rule in await self._agents.list_l1_keywords(agent_key):
                add(rule.get("target"))
        except Exception:  # noqa: BLE001 — router metadata must not break the list
            pass
        add((config.get("l3_llm") or {}).get("fallback_agent"))
        return targets

    async def get_config(self, agent_key: str):
        definition = await self._agents.get_definition(agent_key)
        if definition is None:
            raise RpcError("agent/not-found", f"Agent 不存在: {agent_key}")
        config = await self._agents.get_config(agent_key) or {}
        cache_policy = definition.get("cache_policy") or _DEFAULT_CACHE_POLICY
        model = self._llm.resolve(config).public()
        return config, cache_policy, model

    async def create(self, params) -> dict:
        key = params.key.strip()
        name = params.name.strip()
        if not key or not name:
            raise RpcError("agent/invalid-request", "key 和 name 不能为空")
        if params.agent_type not in ("agent", "router"):
            raise RpcError("agent/invalid-request", "agent_type 必须为 agent 或 router")
        if await self._agents.get_definition(key) is not None:
            raise RpcError("agent/exists", f"Agent [{key}] 已存在")
        if params.agent_type == "router":
            config = {
                "l1_enabled": True,
                "l2_embedding": {
                    "enabled": True, "model": "bge-m3", "threshold": 0.85,
                    "history_enabled": True, "description_enabled": True,
                    "strategy": "cascade", "top_k": 3,
                },
                "l3_llm": {
                    "enabled": True, "model": params.model,
                    "api_key": params.api_key, "base_url": params.base_url,
                    "system_prompt_extra": "", "fallback_agent": "",
                },
                "routable_agents": [],
            }
        else:
            config = {
                "provider": (params.provider or "deepseek").strip(),
                "system_prompt": params.system_prompt,
                "fallback_reply": params.fallback_reply,
                "max_steps": params.max_steps,
                "api_key": params.api_key,
                "base_url": params.base_url,
                "model": params.model,
            }
        row = await self._agents.create_definition(
            key, name, params.desc, config, params.agent_type, _DEFAULT_CACHE_POLICY,
        )
        return {
            "key": row["agent_key"],
            "name": row["name"],
            "desc": row.get("description") or "",
            "status": row.get("status") or "active",
            "agent_type": row.get("agent_type") or params.agent_type,
            "cache_policy": row.get("cache_policy") or _DEFAULT_CACHE_POLICY,
        }

    async def save_config(self, agent_key: str, config: dict[str, Any]):
        if await self._agents.get_definition(agent_key) is None:
            raise RpcError("agent/not-found", f"Agent 不存在: {agent_key}")
        body = dict(config)
        cache_policy = body.pop("cache_policy", None)
        saved = await self._agents.save_config(agent_key, body) if body else {}
        if cache_policy is not None:
            await self._agents.update_cache_policy(agent_key, cache_policy)
        return saved, cache_policy
