"""Scheduler defaults bound to the single-track tool host."""
from agent_platform_tool_system.scheduler import (  # noqa: F401
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
    configure_defaults,
)

from .unified_state import get_unified_tools


def _runtime_factory():
    return get_unified_tools()


def _mode_resolver(tool_name: str) -> str:
    return get_unified_tools().execution_mode_of(tool_name)


configure_defaults(_runtime_factory, _mode_resolver)

# Backward-compatible name used by older tests/embedders.
_registry_mode_resolver = _mode_resolver
