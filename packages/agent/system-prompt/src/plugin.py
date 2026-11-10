"""System-prompt plugin: one registry per runtime, bound to tools/tool-host."""
from agent_platform_plugin_sdk import SdkModel
from agent_platform_tool_host import UNIFIED_TOOLS

from .assembler import AssembleContext, render_system_prompt
from .platform_sections import register_platform_sections, unified_tool_provider
from .services import RUNTIME_PROMPTS, PreparedPrompt
from .system_prompt import SystemPrompt
from minidsh_cordis import Context, Plugin


class PromptConfig(SdkModel):
    pass


class SystemPromptService:
    """Runtime-scoped prompt registry exposed through RUNTIME_PROMPTS."""

    def __init__(self, sp: SystemPrompt) -> None:
        self._sp = sp
        self.sp = sp

    async def assemble(self, **options) -> PreparedPrompt:
        assembly = await self._sp.assemble(AssembleContext(**options))
        return PreparedPrompt(
            render_system_prompt(assembly),
            [tool.to_openai() for tool in assembly.tools],
        )

    async def preview(self, **options):
        """Debug view of the full assembly (sections/contexts/tools/variables)."""
        return await self._sp.assemble(AssembleContext(**options))


class SystemPromptPlugin(Plugin[PromptConfig]):
    name = "agent-platform.system-prompt"
    version = "0.1.0"
    provides = (RUNTIME_PROMPTS,)
    requires = (UNIFIED_TOOLS,)
    config_model = PromptConfig

    async def setup(self, ctx: Context, config: PromptConfig) -> None:
        sp = SystemPrompt()
        register_platform_sections(sp, unified_tool_provider(ctx.require(UNIFIED_TOOLS)))
        ctx.provide(RUNTIME_PROMPTS, SystemPromptService(sp))
