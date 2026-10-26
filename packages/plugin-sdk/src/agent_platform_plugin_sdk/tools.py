"""Version 1 of the provider-neutral tools capability.

The scheduler owns concurrency and ordered Session recording. This service owns
lookup, call-time visibility checks, dispatch and deadline enforcement. Neither
providers nor executors may record Session events or grant additional authority.
"""
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import Field, StrictFloat, model_validator

from .lifecycle import Registration, ServiceKey
from .models import ExecutionScope, JsonObject, JsonValue, NonEmptyString, SdkModel, ServiceRef

TOOL_NOT_FOUND = "tool.not_found"
TOOL_DENIED = "tool.denied"
TOOL_TIMEOUT = "tool.timeout"
TOOL_UNAVAILABLE = "tool.unavailable"
TOOL_INVALID_ARGUMENTS = "tool.invalid_arguments"


def _default_input_schema() -> JsonObject:
    return {"type": "object", "properties": {}}


class ToolDescriptor(SdkModel):
    """Model schema plus execution metadata; transport details stay in providers.

    input_schema describes an object. The runtime validates arguments against
    it. JSON is shallow-frozen: snapshot before dispatch; never store credentials.
    """

    name: NonEmptyString
    executor: NonEmptyString
    description: NonEmptyString
    input_schema: JsonObject = Field(default_factory=_default_input_schema)
    execution_mode: Literal["parallel", "exclusive"] = "parallel"
    timeout_seconds: Annotated[StrictFloat, Field(gt=0)] | None = None
    usage_guidance: str | None = None
    plugin_id: NonEmptyString | None = None
    plugin_name: NonEmptyString | None = None

    @model_validator(mode="after")
    def object_schema(self) -> Self:
        if self.input_schema.get("type") != "object":
            raise ValueError("tool input_schema must declare type: object")
        return self


class ToolCall(SdkModel):
    call_id: NonEmptyString
    name: NonEmptyString
    arguments: JsonObject = Field(default_factory=dict)


class ToolContext(SdkModel):
    """Host-issued call authority; never reconstructed from model arguments.

    An empty visible_tool_names denies all tools. deadline is an absolute
    time.monotonic() value in this process; None adds no caller deadline.
    host_context is an opaque, non-serialized payload for native capabilities
    (sandbox policy, approval channel, event sink). It must never come from
    model arguments; plugin tools should ignore it and use this contract only.
    Sandbox policy and approval need their own future contracts; a host must
    not drop existing enforcement while bridging through host_context.
    """

    scope: ExecutionScope
    visible_tool_names: frozenset[NonEmptyString]
    deadline: Annotated[StrictFloat, Field(gt=0)] | None = None
    host_context: Any = Field(default=None, exclude=True)


class ToolError(SdkModel):
    code: NonEmptyString
    message: NonEmptyString
    details: JsonObject = Field(default_factory=dict)


class ToolResult(SdkModel):
    """Return known execution failures; propagate cancellation.

    The service normalizes ordinary infrastructure failures to error results.
    It must not retry a possibly completed mutation automatically. data may
    accompany an error to retain partial results; details must exclude secrets.
    """

    status: Literal["success", "error"] = "success"
    data: JsonValue = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if (self.status == "error") != (self.error is not None):
            raise ValueError("error status requires ToolError; success status must not contain one")
        return self


class ToolExecutor(Protocol):
    async def execute(self, descriptor: ToolDescriptor, arguments: JsonObject, context: ToolContext) -> ToolResult:
        """Execute once; retain trusted context and propagate CancelledError."""
        ...


class ToolProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def discover(self, scope: ExecutionScope) -> Sequence[ToolDescriptor]:
        """Return eligible descriptors for this scope without executing tools."""
        ...

    async def lazy_load(self, name: str, scope: ExecutionScope) -> ToolDescriptor | None:
        """Resolve on demand using the same scope; None means absent."""
        ...


class ToolsService(Protocol):
    """Replaceable tools.v1 service. Mutations return caller-owned handles.

    Duplicate registrations fail with RegistrationConflictError. A runtime
    must reject provider name collisions deterministically, never overwrite.
    Registration alone grants no Agent binding or permission. execute checks
    host-issued visibility before lookup and checks provider scope at dispatch.
    Closed services return tool.unavailable and reject new registrations with
    ServiceClosedError. aclose is idempotent and drains owned in-flight work.
    """

    def register_tool(self, descriptor: ToolDescriptor) -> Registration: ...

    def register_executor(self, name: str, executor: ToolExecutor) -> Registration: ...

    def register_provider(self, provider: ToolProvider) -> Registration: ...

    async def list_for_agent(self, scope: ExecutionScope) -> Sequence[ToolDescriptor]: ...

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        """Use the earlier caller/tool deadline; expiry returns tool.timeout.

        Denied calls return tool.denied without dispatch. An authorized absent
        name returns tool.not_found. Schema errors use tool.invalid_arguments.
        A call whose deadline already passed must not reach its executor.
        The service never retries and must await cancelled executor cleanup.
        """
        ...

    async def aclose(self) -> None: ...


TOOLS: ServiceKey[ToolsService] = ServiceKey(ServiceRef(name="tools", api_version=1))
