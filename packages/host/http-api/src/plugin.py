"""HTTP/API plugin: owns the FastAPI application, not the agent runtime."""
from agent_platform_agent_entry import AGENT_ENTRY
from agent_platform_chat import CHAT
from agent_platform_memory import MEMORY
from agent_platform_user_approval import APPROVAL_INBOX
from agent_platform_plugin_sdk import (
    AGENTS,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from agent_platform_rpc_connection import CONNECTION

from .app import create_app
from .services import HTTP_APP


class HttpConfig(SdkModel):
    pass


class HttpApiPlugin:
    spec = PluginSpec(
        name="agent-platform.http-api",
        version="0.1.0",
        provides=(HTTP_APP.ref,),
        requires=(
            *(ServiceRequirement(service=key.ref) for key in (CONNECTION, AGENT_ENTRY, CHAT, AGENTS)),
            ServiceRequirement(service=APPROVAL_INBOX.ref, optional=True),
            ServiceRequirement(service=MEMORY.ref, optional=True),
        ),
    )
    config_model = HttpConfig

    async def setup(self, ctx: PluginContext, config: HttpConfig) -> None:
        ctx.provide(HTTP_APP, create_app(
            ctx.require(CONNECTION), entry=ctx.require(AGENT_ENTRY),
            chat=ctx.require(CHAT), approval=ctx.get(APPROVAL_INBOX), agent_config=ctx.require(AGENTS),
            memory=ctx.get(MEMORY),
        ))
