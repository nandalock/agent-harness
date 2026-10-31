"""Host bridge from a host ToolContext to the plugin-owned tools.v1 service."""
from .unified import (
    AgentToolDescriptor,
    NATIVE_EXECUTOR,
    NativeToolExecutor,
    UnifiedToolsRuntime,
)
from .unified_state import (
    close_unified_tools,
    get_unified_tools,
    get_unified_tools_optional,
    set_unified_tools,
)

__version__ = "0.1.0"

__all__ = [
    "NATIVE_EXECUTOR",
    "AgentToolDescriptor",
    "NativeToolExecutor",
    "UnifiedToolsRuntime",
    "close_unified_tools",
    "get_unified_tools",
    "get_unified_tools_optional",
    "set_unified_tools",
]

from .scheduler import (  # noqa: E402,F401
    ABORTED_MESSAGE,
    ABORTED_STARTED_MESSAGE,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DISPATCH,
    SKIP,
    SKIP_MAX_TOOL_CALLS,
    SKIP_MESSAGES,
    SKIP_REPEAT_TOOL,
    PlannedCall,
    ToolCallOutcome,
    ToolCallRecorder,
    ToolScheduler,
)
