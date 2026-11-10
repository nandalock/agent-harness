"""FAQ plugin: DB-backed CRUD, matching and vectorization."""
from agent_platform_plugin_sdk import (
    DATABASE,
    SdkModel,
)

from .contracts import FAQ
from .service import FAQService
from minidsh_cordis import Context, Plugin


class FaqConfig(SdkModel):
    pass


class FaqPlugin(Plugin[FaqConfig]):
    name = "agent-platform.faq"
    web_package = __package__
    version = "0.1.0"
    provides = (FAQ,)
    requires = (DATABASE,)
    config_model = FaqConfig

    async def setup(self, ctx: Context, config: FaqConfig) -> None:
        ctx.provide(FAQ, FAQService(ctx.require(DATABASE)))


plugin = FaqPlugin()
