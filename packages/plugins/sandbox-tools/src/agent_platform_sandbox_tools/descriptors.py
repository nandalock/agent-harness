"""tools.v1 descriptors wrapping the sandbox runtime's tool schemas."""
from typing import Literal, cast

from agent_platform_plugin_sdk import ToolDescriptor as SdkToolDescriptor
from agent_platform_tool_system.descriptor import EXCLUSIVE, SandboxToolConfig
from agent_platform_tool_system.descriptor import ToolDescriptor as NativeToolDescriptor

from agent_platform_sandbox.runtime import (
    _BASH_GUIDANCE,
    _BASH_SCHEMA,
    _PYTHON_GUIDANCE,
    _PYTHON_SCHEMA,
    _with_escalation,
)

#: Timeout for one sandbox command.
TOOL_TIMEOUT_SECONDS = 60.0


def native_descriptors(*, image: str | None = None) -> dict[str, NativeToolDescriptor]:
    """Native descriptors consumed by ``SandboxExecutor``."""
    from agent_platform_sandbox.backends.docker import DEFAULT_SANDBOX_IMAGE

    img = image or DEFAULT_SANDBOX_IMAGE
    specs = (
        ("bash", "shell", _BASH_SCHEMA, _BASH_GUIDANCE),
        ("python", "python", _PYTHON_SCHEMA, _PYTHON_GUIDANCE),
    )
    result: dict[str, NativeToolDescriptor] = {}
    for name, runtime, schema, guidance in specs:
        result[name] = NativeToolDescriptor(
            name=name,
            type="sandbox",
            transport="",
            server_id=0,
            schema=_with_escalation(schema),
            timeout=TOOL_TIMEOUT_SECONDS,
            sandbox=SandboxToolConfig(
                runtime=runtime,
                image=img,
                timeout_s=TOOL_TIMEOUT_SECONDS,
            ),
            usage_guidance=guidance,
            execution_mode=EXCLUSIVE,
        )
    return result


def sdk_descriptor(native: NativeToolDescriptor) -> SdkToolDescriptor:
    schema = native.schema
    return SdkToolDescriptor(
        name=native.name,
        executor="sandbox",
        description=schema.get("description") or native.name,
        input_schema=schema["inputSchema"],
        execution_mode=cast(
            Literal["parallel", "exclusive"], native.execution_mode
        ),
        timeout_seconds=native.timeout,
        usage_guidance=native.usage_guidance,
    )
