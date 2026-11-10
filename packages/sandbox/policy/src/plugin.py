"""Sandbox policy plugin: requires the selected provider, provides agent.sandbox.v1."""
from agent_platform_plugin_sdk import SdkModel
from agent_platform_sandbox.services import AGENT_SANDBOX, SANDBOX

from .service import SandboxPolicyService
from minidsh_cordis import Context, Plugin


class PolicyConfig(SdkModel):
    pass


class SandboxPolicyPlugin(Plugin[PolicyConfig]):
    name = "agent-platform.sandbox-policy"
    version = "0.1.0"
    provides = (AGENT_SANDBOX,)
    requires = (SANDBOX,)
    config_model = PolicyConfig

    async def setup(self, ctx: Context, config: PolicyConfig) -> None:
        ctx.provide(AGENT_SANDBOX, SandboxPolicyService(ctx.require(SANDBOX)))
