from agent_platform_chat import CHAT
from agent_platform_plugin_sdk import (
    AGENTS, DATABASE, PluginContext, PluginSpec, SdkModel, ServiceKey, ServiceRef, ServiceRequirement,
)

from .service import MemoryService

MEMORY = ServiceKey[MemoryService](ServiceRef(name="memory", api_version=1))


class MemoryPlugin:
    spec = PluginSpec(
        name="agent-platform.memory",
        version="0.1.0",
        provides=(MEMORY.ref,),
        requires=tuple(ServiceRequirement(service=key.ref) for key in (DATABASE, AGENTS, CHAT)),
    )
    config_model = SdkModel

    async def setup(self, ctx: PluginContext, config: SdkModel) -> None:
        service = MemoryService(ctx.require(DATABASE), ctx.require(AGENTS), ctx.require(CHAT).store)
        ctx.provide(MEMORY, service)
        ctx.on_quiesce(service.aclose, label="stop memory extraction")
