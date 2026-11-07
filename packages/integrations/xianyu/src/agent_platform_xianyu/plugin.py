"""Xianyu channel plugin: connection lifecycle and chat persistence."""
from agent_platform_chat import CHAT
from agent_platform_plugin_sdk import (
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from pydantic import Field

from .contracts import XIANYU
from .manager import XianyuManager


class XianyuConfig(SdkModel):
    cookie_file: str | None = None
    tenant_id: int = Field(default=1, ge=1)


class XianyuPlugin:
    spec = PluginSpec(
        name="agent-platform.xianyu",
        version="0.1.0",
        provides=(XIANYU.ref,),
        requires=(ServiceRequirement(service=CHAT.ref),),
    )
    config_model = XianyuConfig

    async def setup(self, ctx: PluginContext, config: XianyuConfig) -> None:
        manager = XianyuManager(
            ctx.require(CHAT).store,
            cookie_file=config.cookie_file,
            tenant_id=config.tenant_id,
        )
        ctx.provide(XIANYU, manager)
        ctx.on_dispose(manager.aclose, label="xianyu connection")


plugin = XianyuPlugin()
