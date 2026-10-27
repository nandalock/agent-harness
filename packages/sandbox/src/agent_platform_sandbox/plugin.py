"""Sandbox service providers, independent from model-facing tool plugins."""
import os

from agent_platform_plugin_sdk import PluginSpec, SdkModel, ServiceKey, ServiceRef

from .provider import SandboxProvider
from .runtime import get_sandbox_provider, init_sandbox, set_sandbox_provider

SANDBOX: ServiceKey[SandboxProvider] = ServiceKey(ServiceRef(name="sandbox", api_version=1))


class SandboxConfig(SdkModel):
    pass


class LocalSandboxPlugin:
    spec = PluginSpec(name="agent-platform.sandbox-local", version="0.1.0", provides=(SANDBOX.ref,))
    config_model = SandboxConfig
    backend = "local"

    async def setup(self, ctx, config):
        # Root preparation is lazy for embedded hosts; the application launcher
        # supplies SANDBOX_WORKSPACE_ROOT before creating sessions.
        if os.environ.get("SANDBOX_WORKSPACE_ROOT"):
            provider = init_sandbox(backend=self.backend)
        else:
            from .backends.local import LocalProvider
            from .backends.docker import DockerProvider
            provider = LocalProvider() if self.backend == "local" else DockerProvider()
            set_sandbox_provider(provider)
        ctx.provide(SANDBOX, provider)

        def clear():
            if get_sandbox_provider() is provider:
                set_sandbox_provider(None)
        ctx.on_dispose(clear, label="sandbox provider")


class DockerSandboxPlugin(LocalSandboxPlugin):
    spec = PluginSpec(name="agent-platform.sandbox-docker", version="0.1.0", provides=(SANDBOX.ref,))
    backend = "docker"
