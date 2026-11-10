"""LLM core plugin: one provider registry and HTTP pool per runtime."""
from agent_platform_plugin_sdk import SdkModel

from .service import LLMService
from .services import LLM
from minidsh_cordis import Context, Plugin


class LLMConfig(SdkModel):
    pass


class LLMPlugin(Plugin[LLMConfig]):
    name = "agent-platform.llm"
    version = "0.1.0"
    provides = (LLM,)
    config_model = LLMConfig

    async def setup(self, ctx: Context, config: LLMConfig) -> None:
        service = LLMService()
        ctx.provide(LLM, service)
        ctx.on_dispose(service.aclose, label="llm http pool")
