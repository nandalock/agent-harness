"""Public SDK API; independent of the minidsh backend and plugin runtime."""
from .errors import (
    PluginCompatibilityError, PluginSdkError, RegistrationConflictError,
    ServiceClosedError, ServiceUnavailableError, ensure_sdk_compatible,
)
from .host import (
    AGENTS,
    ALLOWED,
    APPROVAL,
    SETTINGS,
    AgentConfigService,
    ApprovalChannel,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalService,
    SettingsService,
    new_approval_id,
)
from .lifecycle import CleanupCallback, Plugin, PluginContext, Registration, ServiceKey
from .models import (
    PLUGIN_ENTRY_POINT_GROUP, SDK_API_VERSION, ExecutionScope, JsonObject, JsonValue,
    PluginConfiguration, PluginEntry, PluginSpec, SdkModel, ServiceRef, ServiceRequirement,
)
from .tools import (
    TOOLS, TOOL_DENIED, TOOL_INVALID_ARGUMENTS, TOOL_NOT_FOUND, TOOL_TIMEOUT, TOOL_UNAVAILABLE,
    ToolCall, ToolContext, ToolDescriptor, ToolError, ToolExecutor, ToolProvider, ToolResult, ToolsService,
)

__version__ = "0.1.0"

__all__ = [
    "AGENTS", "ALLOWED", "APPROVAL", "SETTINGS", "AgentConfigService", "ApprovalChannel",
    "ApprovalOutcome", "ApprovalRequest", "ApprovalService", "SettingsService", "new_approval_id",
    "CleanupCallback", "ExecutionScope", "JsonObject", "JsonValue", "PLUGIN_ENTRY_POINT_GROUP",
    "Plugin", "PluginCompatibilityError", "PluginConfiguration", "PluginContext", "PluginEntry",
    "PluginSdkError", "PluginSpec", "Registration", "RegistrationConflictError", "SDK_API_VERSION",
    "SdkModel", "ServiceClosedError", "ServiceKey", "ServiceRef", "ServiceRequirement",
    "ServiceUnavailableError", "TOOLS", "TOOL_DENIED", "TOOL_INVALID_ARGUMENTS", "TOOL_NOT_FOUND", "TOOL_TIMEOUT", "TOOL_UNAVAILABLE",
    "ToolCall", "ToolContext", "ToolDescriptor", "ToolError", "ToolExecutor", "ToolProvider", "ToolResult",
    "ToolsService", "ensure_sdk_compatible",
]
