from agent_platform_agent_runtime import AGENT_RUNTIME
from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS, DATABASE, SdkModel, ServiceKey,
)

from .service import AgentGateway
from minidsh_cordis import Context, Plugin

AGENT_ENTRY = ServiceKey[AgentGateway]("agent.entry")


class AgentEntryPlugin(Plugin[SdkModel]):
    name = "agent-platform.agent-entry"
    version = "0.1.0"
    provides = (AGENT_ENTRY,)
    requires = (AGENTS, AGENT_RUNTIME, AGENT_RUNS, DATABASE, LLM)
    config_model = SdkModel

    async def setup(self, ctx: Context, config: SdkModel) -> None:
        service = AgentGateway(
            ctx.require(AGENTS), ctx.require(AGENT_RUNTIME), ctx.require(AGENT_RUNS),
            ctx.require(DATABASE), ctx.require(LLM),
        )
        ctx.provide(AGENT_ENTRY, service)
        ctx.on_quiesce(service.aclose, label="stop agent entry")
