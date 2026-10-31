"""tools.v1 descriptors wrapping the sandbox runtime's tool schemas."""
from typing import Literal, cast
import os

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


def native_descriptors(*, image: str | None = None, backend: str = "docker") -> dict[str, NativeToolDescriptor]:
    """Native descriptors consumed by ``SandboxExecutor``."""
    from agent_platform_sandbox.backends.docker import DEFAULT_SANDBOX_IMAGE

    img = image or DEFAULT_SANDBOX_IMAGE
    specs = (
        ("bash", "shell", _BASH_SCHEMA, _BASH_GUIDANCE),
        ("python", "python", _PYTHON_SCHEMA, _PYTHON_GUIDANCE),
    )
    if backend == "local" and os.name == "nt":
        bash_schema = {**_BASH_SCHEMA, "description": "在宿主机 Bash 中执行命令，使用会话工作目录和当前沙箱策略；Windows 常规操作优先使用 powershell。"}
        specs = (("bash", "shell", bash_schema, "仅对 Bash 脚本使用 bash；Windows 路径和系统操作优先使用 powershell。"), specs[1])
        schema = {**_BASH_SCHEMA, "name": "powershell", "description": "在宿主机 PowerShell 执行命令，使用当前会话目录和沙箱策略。受限模式使用操作系统权限限制；全权限模式直接执行。"}
        specs += (("powershell", "powershell", schema, "Windows 文件和进程操作优先使用 PowerShell；路径使用宿主机绝对路径。"),)
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
