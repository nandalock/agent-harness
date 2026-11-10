from agent_platform_agents import AGENT_RUNS
from agent_platform_llm import LLM
from agent_platform_plugin_sdk import (
    AGENTS,
    AGENT_EXTENSIONS,
    SdkModel,
)
from agent_platform_sandbox.services import AGENT_SANDBOX
from agent_platform_session_recovery import SESSION_RECOVERY
from agent_platform_session_title import SESSION_TITLE
from agent_platform_system_prompt import RUNTIME_PROMPTS

from .contracts import AGENT_RUNTIME
from .extensions import AgentExtensionRegistry
from .service import RuntimeService
from minidsh_cordis import Context, Plugin


class RuntimeConfig(SdkModel):
    pass


class AgentRuntimePlugin(Plugin[RuntimeConfig]):
    name = "agent-platform.agent-runtime"
    version = "0.1.0"
    provides = (AGENT_RUNTIME, AGENT_EXTENSIONS)
    requires = (
        AGENTS, AGENT_RUNS, RUNTIME_PROMPTS, LLM, AGENT_SANDBOX,
        SESSION_RECOVERY,
    )
    optional = (SESSION_TITLE,)
    config_model = RuntimeConfig

    async def setup(self, ctx: Context, config: RuntimeConfig) -> None:
        extensions = AgentExtensionRegistry()
        ctx.provide(AGENT_EXTENSIONS, extensions)
        ctx.on_dispose(extensions.aclose, label="agent extensions")
        service = RuntimeService(ctx, extensions)
        ctx.provide(AGENT_RUNTIME, service)
        ctx.on_quiesce(service.aclose, label="stop agent runtime")
        ctx.on_dispose(service.aclose, label="agent runtime")
