"""Session-title plugin: one service instance per runtime, dependencies injected."""
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel, ServiceRequirement

from agent_platform_session import SESSIONS
from agent_platform_session_persistence import SESSION_PERSISTENCE

from .service import SessionTitleService
from .services import SESSION_TITLE


class TitleConfig(SdkModel):
    pass


class SessionTitlePlugin:
    spec = PluginSpec(
        name="agent-platform.session-title",
        version="0.1.0",
        provides=(SESSION_TITLE.ref,),
        requires=(
            ServiceRequirement(service=SESSIONS.ref),
            ServiceRequirement(service=SESSION_PERSISTENCE.ref),
            ServiceRequirement(service=LLM.ref),
        ),
    )
    config_model = TitleConfig

    async def setup(self, ctx: PluginContext, config: TitleConfig) -> None:
        service = SessionTitleService(
            ctx.require(SESSIONS),
            ctx.require(SESSION_PERSISTENCE),
            ctx.require(LLM),
        )
        ctx.provide(SESSION_TITLE, service)
        ctx.on_quiesce(service.aclose, label="stop session titles")
