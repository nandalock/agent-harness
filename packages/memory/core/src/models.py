from typing import Optional

from pydantic import BaseModel, Field


class DebugMessage(BaseModel):
    role: str       # customer | agent | system | tool
    content: str


class DebugRunRequest(BaseModel):
    messages: list[DebugMessage] = Field(default_factory=list)
    conversation_id: Optional[int] = None
    system_prompt: str = ""
    user_id: str = "debug_user"
    llm_override: Optional[dict] = None
    agent_key: Optional[str] = None
