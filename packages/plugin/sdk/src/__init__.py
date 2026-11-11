"""Public SDK API; independent of the minidsh backend and plugin runtime."""
from .agents import AGENT_EXTENSIONS, AgentRunContext, AgentRunContribution, AgentExtensionsService
from minidsh_cordis import Closeable as Registration
from minidsh_cordis import (
    RegistrationConflictError, ServiceClosedError, ServiceKey, ServiceUnavailableError,
)
from .host import (
    AGENTS,
    ALLOWED,
    APPROVAL,
    SETTINGS,
    TOOL_BINDINGS,
    DATABASE,
    AgentConfigService,
    ApprovalChannel,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalService,
    Database,
    SettingsService,
    ToolBindingsService,
    new_approval_id,
)
from .models import (
    ExecutionScope, JsonObject, JsonValue, SdkModel,
)
from .tools import (
    TOOLS, TOOL_DENIED, TOOL_INVALID_ARGUMENTS, TOOL_NOT_FOUND, TOOL_TIMEOUT, TOOL_UNAVAILABLE,
    ToolCall, ToolContext, ToolDescriptor, ToolError, ToolExecutor, ToolProvider, ToolResult, ToolsService,
)

__version__ = "0.1.0"

__all__ = [
    "AGENT_EXTENSIONS", "AgentRunContext", "AgentRunContribution", "AgentExtensionsService",
    "AGENTS", "ALLOWED", "APPROVAL", "SETTINGS", "TOOL_BINDINGS", "DATABASE",
    "AgentConfigService", "ApprovalChannel",
    "ApprovalOutcome", "ApprovalRequest", "ApprovalService", "Database", "SettingsService",
    "ToolBindingsService", "new_approval_id",
    "ExecutionScope", "JsonObject", "JsonValue",
    "Registration", "RegistrationConflictError", "SdkModel", "ServiceClosedError", "ServiceKey",
    "ServiceUnavailableError", "TOOLS", "TOOL_DENIED", "TOOL_INVALID_ARGUMENTS", "TOOL_NOT_FOUND", "TOOL_TIMEOUT", "TOOL_UNAVAILABLE",
    "ToolCall", "ToolContext", "ToolDescriptor", "ToolError", "ToolExecutor", "ToolProvider", "ToolResult",
    "ToolsService",
]
