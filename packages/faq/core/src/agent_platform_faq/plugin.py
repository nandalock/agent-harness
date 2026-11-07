"""FAQ plugin: DB-backed CRUD, matching and vectorization."""
from agent_platform_plugin_sdk import (
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

from .contracts import FAQ
from .service import FAQService


class FaqConfig(SdkModel):
    pass


class FaqPlugin:
    spec = PluginSpec(
        name="agent-platform.faq",
        version="0.1.0",
        provides=(FAQ.ref,),
        requires=(ServiceRequirement(service=DATABASE.ref),),
    )
    config_model = FaqConfig

    async def setup(self, ctx: PluginContext, config: FaqConfig) -> None:
        ctx.provide(FAQ, FAQService(ctx.require(DATABASE)))


plugin = FaqPlugin()
