"""LLM core plugin: one provider registry and HTTP pool per runtime."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel

from .service import LLMService
from .services import LLM


class LLMConfig(SdkModel):
    pass


class LLMPlugin:
    spec = PluginSpec(
        name="agent-platform.llm",
        version="0.1.0",
        provides=(LLM.ref,),
    )
    config_model = LLMConfig

    async def setup(self, ctx: PluginContext, config: LLMConfig) -> None:
        service = LLMService()
        ctx.provide(LLM, service)
        ctx.on_dispose(service.aclose, label="llm http pool")
