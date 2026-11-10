from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_plugin_sdk import (
    DATABASE, SdkModel, ServiceKey,
)
from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .service import ChatService
from .store import ChatStore
from minidsh_cordis import Context, Plugin

CHAT = ServiceKey[ChatService]("chat")


class ChatPlugin(Plugin[SdkModel]):
    name = "agent-platform.chat"
    web_package = __package__
    version = "0.1.0"
    provides = (CHAT,)
    requires = (AGENT_ENTRY, DATABASE, SESSIONS, SESSION_PERSISTENCE)
    config_model = SdkModel

    async def setup(self, ctx: Context, config: SdkModel) -> None:
        store = ChatStore(ctx.require(DATABASE), ctx.require(SESSIONS), ctx.require(SESSION_PERSISTENCE))
        chat = ChatService(ctx.require(AGENT_ENTRY), store)
        ctx.provide(CHAT, chat)
        ctx.on_quiesce(chat.aclose, label="stop chat runs")
