"""Plugin entry: publish bash/python as sandbox-backed tools.v1 tools."""
from agent_platform_plugin_sdk import (
    APPROVAL,
    Plugin,
    PluginContext,
    PluginSpec,
    ServiceRequirement,
    SETTINGS,
    SdkModel,
    TOOLS,
)

from agent_platform_sandbox.executor import SandboxExecutor
from agent_platform_sandbox.plugin import SANDBOX

from .control import SandboxToolControl, set_sandbox_control
from .descriptors import native_descriptors, sdk_descriptor
from .executor import SandboxToolExecutor


class SandboxToolsConfig(SdkModel):
    pass


class SandboxToolsPlugin:
    spec = PluginSpec(
        name="agent-platform.sandbox-tools",
        version="0.1.0",
        requires=(
            ServiceRequirement(service=TOOLS.ref),
            ServiceRequirement(service=SETTINGS.ref),
            ServiceRequirement(service=SANDBOX.ref),
            ServiceRequirement(service=APPROVAL.ref, optional=True),
        ),
    )
    config_model = SandboxToolsConfig

    async def setup(self, ctx: PluginContext, config: SandboxToolsConfig) -> None:
        tools = ctx.require(TOOLS)
        settings = ctx.require(SETTINGS)
        approval = ctx.get(APPROVAL)
        sandbox = ctx.require(SANDBOX)

        natives = native_descriptors(backend=getattr(sandbox, "backend", "docker"))
        descriptors = {
            name: sdk_descriptor(native).model_copy(update={
                "plugin_id": ctx.instance_id, "plugin_name": ctx.spec.name,
            }) for name, native in natives.items()
        }
        ctx.track(
            tools.register_executor(
                "sandbox", SandboxToolExecutor(natives, SandboxExecutor(provider=sandbox, approval=approval))
            )
        )
        control = SandboxToolControl(tools, settings, descriptors, ctx.track)
        ctx.on_dispose(control.aclose, label="sandbox-tools control")
        set_sandbox_control(control)
        await control.load()


plugin: Plugin[SandboxToolsConfig] = SandboxToolsPlugin()
