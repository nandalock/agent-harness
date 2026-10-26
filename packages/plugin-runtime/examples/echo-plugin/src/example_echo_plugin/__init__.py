"""An independently packaged plugin: one echo tool fed by the tools.v1 service."""
from agent_platform_plugin_sdk import (
    JsonObject,
    Plugin,
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
    TOOLS,
    ToolContext,
    ToolDescriptor,
    ToolResult,
)


class EchoConfig(SdkModel):
    prefix: str = ""


class EchoExecutor:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def execute(
        self,
        descriptor: ToolDescriptor,
        arguments: JsonObject,
        context: ToolContext,
    ) -> ToolResult:
        return ToolResult(data={"text": self.prefix + str(arguments.get("text", ""))})


class EchoPlugin:
    spec = PluginSpec(
        name="example.echo",
        version="0.1.0",
        requires=(ServiceRequirement(service=TOOLS.ref),),
    )
    config_model = EchoConfig

    async def setup(self, ctx: PluginContext, config: EchoConfig) -> None:
        tools = ctx.require(TOOLS)
        ctx.track(tools.register_executor("example.echo", EchoExecutor(config.prefix)))
        ctx.track(
            tools.register_tool(
                ToolDescriptor(
                    name="echo",
                    executor="example.echo",
                    description="Echo a text argument",
                    input_schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                )
            )
        )


plugin: Plugin[EchoConfig] = EchoPlugin()
