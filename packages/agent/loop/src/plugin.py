from pydantic import Field
from agent_platform_agents import AGENT_RUNS
from agent_platform_plugin_sdk import APPROVAL, TOOLS, SdkModel
from agent_platform_tool_system.scheduler import DEFAULT_MAX_PARALLEL_TOOLS
from agent_platform_tools_default import TOOL_CATALOG
from .agent_loop import AgentLoop
from .context import LoopContext
from minidsh_cordis import Context, Plugin


class LoopConfig(SdkModel):
    max_parallel_tools: int = Field(default=DEFAULT_MAX_PARALLEL_TOOLS, ge=1)


class LoopFactory:
    def __init__(self, ctx: Context, config: LoopConfig):
        self.ctx = ctx
        self.config = config

    def create(self, **options) -> AgentLoop:
        options["llm_params"] = dict(options["llm_params"])
        options["llm_params"].setdefault("max_parallel_tools", self.config.max_parallel_tools)
        loop_ctx = LoopContext(
            plugin_ctx=self.ctx,
            llm=options.pop("llm"),
            sandbox_policy_factory=options.pop("sandbox_policy", None),
        )
        return AgentLoop(loop_ctx, **options)


class AgentLoopPlugin(Plugin[LoopConfig]):
    name = "agent-platform.agent-loop"
    version = "0.1.0"
    requires = (AGENT_RUNS, TOOLS, TOOL_CATALOG)
    optional = (APPROVAL,)
    config_model = LoopConfig

    async def setup(self, ctx: Context, config: LoopConfig) -> None:
        runs = ctx.require(AGENT_RUNS)
        registration = runs.register_factory(LoopFactory(ctx, config))
        ctx.on_quiesce(registration.aclose, label="stop agent loop")
        ctx.track(registration)
