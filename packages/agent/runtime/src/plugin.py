from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS,
    AGENT_EXTENSIONS,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)
from agent_platform_sandbox.services import AGENT_SANDBOX
from agent_platform_session_recovery import SESSION_RECOVERY
from agent_platform_session_title import SESSION_TITLE
from agent_platform_system_prompt import RUNTIME_PROMPTS

from .contracts import AGENT_RUNTIME
from .extensions import AgentExtensionRegistry
from .service import RuntimeService


class RuntimeConfig(SdkModel):
    pass


class AgentRuntimePlugin:
    spec = PluginSpec(
        name="agent-platform.agent-runtime", version="0.1.0",
        provides=(AGENT_RUNTIME.ref, AGENT_EXTENSIONS.ref),
        requires=(
            ServiceRequirement(service=AGENTS.ref),
            ServiceRequirement(service=AGENT_RUNS.ref),
            ServiceRequirement(service=RUNTIME_PROMPTS.ref),
            ServiceRequirement(service=LLM.ref),
            ServiceRequirement(service=AGENT_SANDBOX.ref),
            ServiceRequirement(service=SESSION_RECOVERY.ref),
            ServiceRequirement(service=SESSION_TITLE.ref, optional=True),
        ),
    )
    config_model = RuntimeConfig

    async def setup(self, ctx: PluginContext, config: RuntimeConfig) -> None:
        extensions = AgentExtensionRegistry()
        ctx.provide(AGENT_EXTENSIONS, extensions)
        ctx.on_dispose(extensions.aclose, label="agent extensions")
        service = RuntimeService(ctx, extensions)
        ctx.provide(AGENT_RUNTIME, service)
        ctx.on_quiesce(service.aclose, label="stop agent runtime")
        ctx.on_dispose(service.aclose, label="agent runtime")
