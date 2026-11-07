"""Agent RPC contracts."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSummary(_Model):
    key: str
    name: str
    desc: str = ""
    status: str = "active"
    agent_type: str = "agent"
    cache_policy: dict[str, Any] | None = None
    routable: list[str] | None = None


class AgentListParams(_Model):
    pass


class AgentListResult(_Model):
    items: list[AgentSummary]


class AgentCreateParams(_Model):
    key: str
    name: str
    desc: str = ""
    agent_type: str = "agent"
    provider: str = "deepseek"
    system_prompt: str = ""
    fallback_reply: str = "抱歉，我暂时无法处理。"
    max_steps: int = 5
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class AgentCreateResult(_Model):
    agent: AgentSummary


class AgentGetConfigParams(_Model):
    agent_key: str


class AgentConfigResult(_Model):
    agent_key: str
    config: dict[str, Any]
    cache_policy: dict[str, Any] | None = None
    model_info: dict[str, Any]


class AgentSaveConfigParams(_Model):
    agent_key: str
    config: dict[str, Any]


class AgentSaveConfigResult(_Model):
    agent_key: str
    config: dict[str, Any]
    cache_policy: dict[str, Any] | None = None
