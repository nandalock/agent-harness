from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel
from .service import AGENT_RUNS, AgentService


class AgentsConfig(SdkModel):
    pass


class AgentsPlugin:
    spec = PluginSpec(name="agent-platform.agents", version="0.1.0", provides=(AGENT_RUNS.ref,))
    config_model = AgentsConfig

    async def setup(self, ctx: PluginContext, config: AgentsConfig) -> None:
        service = AgentService()
        ctx.provide(AGENT_RUNS, service)
        ctx.on_quiesce(service.aclose, label="stop agent runs")
        ctx.on_dispose(service.aclose, label="agent runs")
