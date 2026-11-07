"""Sandbox policy plugin: requires the selected provider, provides agent.sandbox.v1."""
from agent_platform_plugin_sdk import PluginContext, PluginSpec, SdkModel, ServiceRequirement
from agent_platform_sandbox.services import AGENT_SANDBOX, SANDBOX

from .service import SandboxPolicyService


class PolicyConfig(SdkModel):
    pass


class SandboxPolicyPlugin:
    spec = PluginSpec(
        name="agent-platform.sandbox-policy",
        version="0.1.0",
        provides=(AGENT_SANDBOX.ref,),
        requires=(ServiceRequirement(service=SANDBOX.ref),),
    )
    config_model = PolicyConfig

    async def setup(self, ctx: PluginContext, config: PolicyConfig) -> None:
        ctx.provide(AGENT_SANDBOX, SandboxPolicyService(ctx.require(SANDBOX)))
