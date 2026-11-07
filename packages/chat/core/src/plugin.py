from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_plugin_sdk import (
    DATABASE, PluginContext, PluginSpec, SdkModel, ServiceKey, ServiceRef, ServiceRequirement,
)
from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .service import ChatService
from .store import ChatStore

CHAT = ServiceKey[ChatService](ServiceRef(name="chat", api_version=1))


class ChatPlugin:
    spec = PluginSpec(
        name="agent-platform.chat",
        web_package=__package__, version="0.1.0",
        provides=(CHAT.ref,),
        requires=tuple(ServiceRequirement(service=key.ref) for key in (AGENT_ENTRY, DATABASE, SESSIONS, SESSION_PERSISTENCE)),
    )
    config_model = SdkModel

    async def setup(self, ctx: PluginContext, config: SdkModel) -> None:
        store = ChatStore(ctx.require(DATABASE), ctx.require(SESSIONS), ctx.require(SESSION_PERSISTENCE))
        chat = ChatService(ctx.require(AGENT_ENTRY), store)
        ctx.provide(CHAT, chat)
        ctx.on_quiesce(chat.aclose, label="stop chat runs")
