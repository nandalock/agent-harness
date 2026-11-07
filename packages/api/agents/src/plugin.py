"""Agent controller plugin: agent RPC methods over AGENTS/LLM services."""
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS,
    DATABASE,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from agent_platform_rpc_gateway import RPC_GATEWAY, RpcMethodContract

from .models import (
    AgentConfigResult,
    AgentCreateParams,
    AgentCreateResult,
    AgentGetConfigParams,
    AgentListParams,
    AgentListResult,
    AgentSaveConfigParams,
    AgentSaveConfigResult,
    AgentSummary,
)
from .service import AgentApiService
from .services import AGENT_API

METHODS = (
    RpcMethodContract("agent.list", AgentListParams, AgentListResult),
    RpcMethodContract("agent.create", AgentCreateParams, AgentCreateResult),
    RpcMethodContract("agent.getConfig", AgentGetConfigParams, AgentConfigResult),
    RpcMethodContract("agent.saveConfig", AgentSaveConfigParams, AgentSaveConfigResult),
)


class AgentsApiConfig(SdkModel):
    pass


class AgentApiPlugin:
    spec = PluginSpec(
        name="agent-platform.api-agents",
        web_package=__package__,
        version="0.1.0",
        provides=(AGENT_API.ref,),
        requires=(
            ServiceRequirement(service=RPC_GATEWAY.ref),
            ServiceRequirement(service=AGENTS.ref),
            ServiceRequirement(service=LLM.ref),
            ServiceRequirement(service=DATABASE.ref),
        ),
    )
    config_model = AgentsApiConfig

    async def setup(self, ctx: PluginContext, config: AgentsApiConfig) -> None:
        service = AgentApiService(
            ctx.require(AGENTS), ctx.require(LLM), ctx.require(DATABASE),
        )
        ctx.provide(AGENT_API, service)
        gateway = ctx.require(RPC_GATEWAY)
        contracts = {contract.method: contract for contract in METHODS}

        async def list_agents(params, context):
            return AgentListResult(items=[AgentSummary(**item) for item in await service.list()])

        async def create_agent(params, context):
            return AgentCreateResult(agent=AgentSummary(**await service.create(params)))

        async def get_config(params, context):
            config, cache_policy, model = await service.get_config(params.agent_key)
            return AgentConfigResult(
                agent_key=params.agent_key,
                config=config,
                cache_policy=cache_policy,
                model_info=model,
            )

        async def save_config(params, context):
            saved, cache_policy = await service.save_config(
                params.agent_key, params.config,
            )
            return AgentSaveConfigResult(
                agent_key=params.agent_key, config=saved, cache_policy=cache_policy,
            )

        for method, handler in {
            "agent.list": list_agents,
            "agent.create": create_agent,
            "agent.getConfig": get_config,
            "agent.saveConfig": save_config,
        }.items():
            ctx.track(gateway.register(contracts[method], handler))


plugin = AgentApiPlugin()
