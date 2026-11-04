"""Loop-owned dispatch through the same context received by AgentLoop."""
from agent_platform_tool_host.execution import ToolsExecutionAdapter
from agent_platform_tool_system.context import ToolContext
from agent_platform_tool_system.scheduler import ToolScheduler

from .context import LoopContext


class LoopToolScheduler(ToolScheduler):
    def __init__(self, ctx: LoopContext, **options):
        self.loop_ctx = ctx
        super().__init__(runtime=self, mode_resolver=self.execution_mode, **options)

    async def execute(self, tool_name: str, args: dict, context: ToolContext) -> dict:
        # Read tools.v1 through loop_ctx for each dispatch, rather than capturing
        # a backend runtime or a copy of the plugin's service at construction.
        return await ToolsExecutionAdapter(self.loop_ctx.tools).execute(tool_name, args, context)

    def execution_mode(self, name: str) -> str:
        for descriptor in self.loop_ctx.tool_catalog.descriptors():
            if descriptor.name == name:
                return descriptor.execution_mode
        return "exclusive"
