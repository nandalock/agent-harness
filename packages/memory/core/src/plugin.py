import os
from pathlib import Path

from pydantic import Field

from agent_platform_chat import CHAT
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS, AGENT_EXTENSIONS, DATABASE, SdkModel, ServiceKey,
)
from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .admission import MemoryAdmission
from .notes import MemoryNotes
from .service import MemoryService
from minidsh_cordis import Context, Plugin

MEMORY = ServiceKey[MemoryService]("memory")


class MemoryPluginConfig(SdkModel):
    context_window: int = Field(default=32768, ge=2048)
    compact_ratio: float = Field(default=0.8, gt=0, lt=1)
    keep_recent_turns: int = Field(default=2, ge=0)
    summary_tokens: int = Field(default=768, ge=128, le=2048)


class MemoryPlugin(Plugin[MemoryPluginConfig]):
    name = "agent-platform.memory"
    web_package = __package__
    version = "0.1.0"
    provides = (MEMORY,)
    requires = (DATABASE, AGENTS, CHAT)
    optional = (AGENT_EXTENSIONS, SESSIONS, SESSION_PERSISTENCE, LLM)
    config_model = MemoryPluginConfig

    async def setup(self, ctx: Context, config: MemoryPluginConfig) -> None:
        notes = MemoryNotes(Path(os.environ.get("MINIDSH_MEMORY_DIR", ".data/memory")).expanduser())
        service = MemoryService(
            ctx.require(DATABASE), ctx.require(AGENTS), ctx.require(CHAT).store,
            notes=notes, sessions=ctx.get(SESSIONS), persistence=ctx.get(SESSION_PERSISTENCE), llm=ctx.get(LLM),
        )
        ctx.provide(MEMORY, service)
        extensions = ctx.get(AGENT_EXTENSIONS)
        if extensions is not None:
            ctx.track(extensions.register("memory", MemoryAdmission(notes, config).extension))
        ctx.on_quiesce(service.aclose, label="stop memory extraction")
