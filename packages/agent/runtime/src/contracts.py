"""Runtime-facing values and the agent-runtime service key.

Prompt, LLM, session and sandbox capabilities are provided by their own plugins;
their service keys live with the contracts they belong to.
"""
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_platform_plugin_sdk import ServiceKey


@dataclass
class AgentReply:
    answer: str
    sources: list[dict] = field(default_factory=list)
    tier: str = ""
    trace: dict = field(default_factory=dict)
    session_id: str | None = None


class AgentRuntimeService(Protocol):
    async def reply(self, key: str, definition: dict, *args: Any, **options: Any) -> AgentReply: ...
    async def plain(self, key: str, messages: list[dict], config: dict) -> tuple[str, bool]: ...


AGENT_RUNTIME: ServiceKey[AgentRuntimeService] = ServiceKey("agent.runtime")
