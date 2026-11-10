from agent_platform_plugin_sdk import SdkModel
from .service import AGENT_RUNS, AgentService
from minidsh_cordis import Context, Plugin


class AgentsConfig(SdkModel):
    pass


class AgentsPlugin(Plugin[AgentsConfig]):
    name = "agent-platform.agents"
    version = "0.1.0"
    provides = (AGENT_RUNS,)
    config_model = AgentsConfig

    async def setup(self, ctx: Context, config: AgentsConfig) -> None:
        service = AgentService()
        ctx.provide(AGENT_RUNS, service)
        ctx.on_quiesce(service.aclose, label="stop agent runs")
        ctx.on_dispose(service.aclose, label="agent runs")
