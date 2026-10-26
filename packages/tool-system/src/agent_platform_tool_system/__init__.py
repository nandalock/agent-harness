"""Host-independent native tool descriptor, registry, scheduler, and runtime."""
from .context import ToolContext
from .descriptor import (
    EXCLUSIVE,
    PARALLEL,
    SandboxToolConfig,
    ToolDescriptor,
    validate_execution_mode,
)
from .events import (
    APPROVAL_REQUEST,
    SANDBOX_ESCALATION,
    TOOL_COMPLETED,
    TOOL_FAILED,
    TOOL_PROGRESS,
    TOOL_STARTED,
    ToolEvent,
    ToolEventSink,
)
from .providers import BuiltinToolProvider, ToolProvider
from .registry import (
    ToolRegistry,
    _sanitize_schema,
    _to_openai_function,
    configure_bindings,
    get_registry,
    init_registry,
    set_registry,
)
from .runtime import ToolExecutor, ToolRuntime
from .scheduler import (
    DEFAULT_MAX_PARALLEL_TOOLS,
    DISPATCH,
    SKIP,
    PlannedCall,
    ToolCallOutcome,
    ToolCallRecorder,
    ToolScheduler,
    configure_defaults,
)

__version__ = "0.1.0"

__all__ = [
    "APPROVAL_REQUEST",
    "BuiltinToolProvider",
    "DEFAULT_MAX_PARALLEL_TOOLS",
    "DISPATCH",
    "EXCLUSIVE",
    "PARALLEL",
    "PlannedCall",
    "SANDBOX_ESCALATION",
    "SKIP",
    "SandboxToolConfig",
    "TOOL_COMPLETED",
    "TOOL_FAILED",
    "TOOL_PROGRESS",
    "TOOL_STARTED",
    "ToolCallOutcome",
    "ToolCallRecorder",
    "ToolContext",
    "ToolDescriptor",
    "ToolEvent",
    "ToolEventSink",
    "ToolExecutor",
    "ToolProvider",
    "ToolRegistry",
    "ToolRuntime",
    "ToolScheduler",
    "configure_bindings",
    "configure_defaults",
    "get_registry",
    "init_registry",
    "set_registry",
    "validate_execution_mode",
]
