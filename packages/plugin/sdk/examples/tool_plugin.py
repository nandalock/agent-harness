"""A typed plugin entry point; import has no registration or execution effects."""
from agent_platform_plugin_sdk import (
    TOOLS, JsonObject, SdkModel,
    ToolContext, ToolDescriptor, ToolResult,
)
from minidsh_cordis import Context, Plugin


class EchoConfig(SdkModel):
    prefix: str = ""


class EchoExecutor:
    def __init__(self, prefix: str):
        self.prefix = prefix

    async def execute(self, descriptor: ToolDescriptor, arguments: JsonObject, context: ToolContext) -> ToolResult:
        return ToolResult(data={"text": self.prefix + str(arguments.get("text", ""))})


class EchoPlugin(Plugin[EchoConfig]):
    name = "example.echo"
    version = "0.1.0"
    requires = (TOOLS,)
    config_model = EchoConfig

    async def setup(self, ctx: Context, config: EchoConfig) -> None:
        tools = ctx.require(TOOLS)
        ctx.track(tools.register_executor("example.echo", EchoExecutor(config.prefix)))
        ctx.track(tools.register_tool(ToolDescriptor(
            name="echo", executor="example.echo", description="Echo a text argument",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}},
                          "required": ["text"], "additionalProperties": False},
        )))


# Static compatibility check; no concrete runtime is imported.
plugin: Plugin[EchoConfig] = EchoPlugin()
