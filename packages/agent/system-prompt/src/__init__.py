"""System prompt registry — sections, dynamic contexts, variables and tools.

The registry is instantiated by the `agent-platform.system-prompt` plugin.
Importing this package has no side effects.
"""
from agent_platform_system_prompt.assembler import (
    AssembleContext,
    AssembledContext,
    AssembledSection,
    PromptAssembly,
    interpolate,
    render_context_snapshot,
    render_prompt,
    render_system_prompt,
)
from agent_platform_system_prompt.context import PromptContext
from agent_platform_system_prompt.section import PromptSection
from agent_platform_system_prompt.system_prompt import (
    CONTEXT_ORDERS,
    SECTION_ORDERS,
    SystemPrompt,
)
from agent_platform_system_prompt.tool import (
    ToolProvider,
    ToolProviderResult,
    ToolSchema,
)
from agent_platform_system_prompt.variable import (
    VARIABLE_NAME,
    PromptVariable,
    VariableProvider,
)
from agent_platform_system_prompt.platform_sections import (
    register_platform_sections,
    unified_tool_provider,
)
from agent_platform_system_prompt.services import (
    RUNTIME_PROMPTS,
    PreparedPrompt,
    RuntimePrompts,
)
from agent_platform_system_prompt.plugin import SystemPromptPlugin, SystemPromptService

__all__ = [
    "PromptSection",
    "PromptContext",
    "PromptVariable",
    "ToolSchema",
    "ToolProviderResult",
    "ToolProvider",
    "VariableProvider",
    "VARIABLE_NAME",
    "SystemPrompt",
    "SECTION_ORDERS",
    "CONTEXT_ORDERS",
    "AssembleContext",
    "AssembledSection",
    "AssembledContext",
    "PromptAssembly",
    "render_prompt",
    "render_context_snapshot",
    "render_system_prompt",
    "interpolate",
    "register_platform_sections",
    "unified_tool_provider",
    "RUNTIME_PROMPTS",
    "PreparedPrompt",
    "RuntimePrompts",
    "SystemPromptPlugin",
    "SystemPromptService",
]
