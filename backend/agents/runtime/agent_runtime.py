"""Database-backed agent view; execution is delegated to agent.runtime.v1."""
from backend.agents.base import BaseAgent, AgentReply
from backend.agents.config_service import get_agent_definition, get_agent_config
from backend.agents.runtime.services import get_runtime_service


class AgentRuntime(BaseAgent):
    def __init__(self, key: str, definition: dict | None = None):
        if definition is None:
            definition = get_agent_definition(key) or {}
        self.key = key
        self.name = definition.get("name", key)
        self.desc = definition.get("description", "")
        self.status = definition.get("status", "active")
        self._definition = definition

    def _cfg(self) -> dict:
        base = self._definition.get("config", {}) if self._definition else {}
        return {**base, **(get_agent_config(self.key) or {})}

    async def reply(self, tenant_id: int, question: str, *args, **options) -> AgentReply:
        return await get_runtime_service().reply(self.key, self._definition, tenant_id, question, *args, **options)
