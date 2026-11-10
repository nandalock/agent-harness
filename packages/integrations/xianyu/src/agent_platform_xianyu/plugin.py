"""Xianyu channel plugin: connection lifecycle and chat persistence."""
from agent_platform_chat import CHAT
from agent_platform_plugin_sdk import (
    SdkModel,
)
from pydantic import Field

from .contracts import XIANYU
from .manager import XianyuManager
from minidsh_cordis import Context, Plugin


class XianyuConfig(SdkModel):
    cookie_file: str | None = None
    tenant_id: int = Field(default=1, ge=1)


class XianyuPlugin(Plugin[XianyuConfig]):
    name = "agent-platform.xianyu"
    web_package = __package__
    version = "0.1.0"
    provides = (XIANYU,)
    requires = (CHAT,)
    config_model = XianyuConfig

    async def setup(self, ctx: Context, config: XianyuConfig) -> None:
        manager = XianyuManager(
            ctx.require(CHAT).store,
            cookie_file=config.cookie_file,
            tenant_id=config.tenant_id,
        )
        ctx.provide(XIANYU, manager)
        ctx.on_dispose(manager.aclose, label="xianyu connection")


plugin = XianyuPlugin()
