"""Sandbox service providers, independent from model-facing tool plugins."""
import os

from agent_platform_plugin_sdk import PluginSpec, SdkModel

from .provider import SandboxProvider
from .runtime import create_provider
from .services import SANDBOX


class SandboxConfig(SdkModel):
    pass


class LocalSandboxPlugin:
    spec = PluginSpec(name="agent-platform.sandbox-local", version="0.1.0", provides=(SANDBOX.ref,))
    config_model = SandboxConfig
    backend = "local"

    async def setup(self, ctx, config):
        # Root preparation is lazy for embedded hosts; the application launcher
        # supplies SANDBOX_WORKSPACE_ROOT before creating sessions.
        provider: SandboxProvider = create_provider(
            backend=self.backend,
            initialize_root=bool(os.environ.get("SANDBOX_WORKSPACE_ROOT")),
        )
        ctx.provide(SANDBOX, provider)


class DockerSandboxPlugin(LocalSandboxPlugin):
    spec = PluginSpec(name="agent-platform.sandbox-docker", version="0.1.0", provides=(SANDBOX.ref,))
    backend = "docker"
