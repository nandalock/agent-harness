"""Host agent interface; reply values are shared with runtime plugins."""
from agent_platform_agent_runtime import AgentReply


class BaseAgent:
    """所有 Agent 的抽象基类"""

    key: str = ""
    name: str = ""
    desc: str = ""
    status: str = "active"  # "active" | "draft"

    async def reply(self, tenant_id: int, question: str, context: dict | None = None, session_id: str | None = None) -> AgentReply:
        raise NotImplementedError
