from agent_platform_agent_runtime import AGENT_RUNTIME
from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS, DATABASE, PluginContext, PluginSpec, SdkModel, ServiceKey, ServiceRef, ServiceRequirement,
)

from .service import AgentGateway

AGENT_ENTRY = ServiceKey[AgentGateway](ServiceRef(name="agent.entry", api_version=1))


class AgentEntryPlugin:
    spec = PluginSpec(
        name="agent-platform.agent-entry", version="0.1.0",
        provides=(AGENT_ENTRY.ref,),
        requires=tuple(ServiceRequirement(service=key.ref) for key in (AGENTS, AGENT_RUNTIME, AGENT_RUNS, DATABASE, LLM)),
    )
    config_model = SdkModel

    async def setup(self, ctx: PluginContext, config: SdkModel) -> None:
        service = AgentGateway(
            ctx.require(AGENTS), ctx.require(AGENT_RUNTIME), ctx.require(AGENT_RUNS),
            ctx.require(DATABASE), ctx.require(LLM),
        )
        ctx.provide(AGENT_ENTRY, service)
        ctx.on_quiesce(service.aclose, label="stop agent entry")
