"""Test fixtures; none of this ships with the runtime package."""
from collections.abc import Callable
from typing import Any

from minidsh_cordis import Plugin

from agent_platform_plugin_sdk import (
    ExecutionScope,
    SdkModel,
    ServiceKey,
    TOOLS,
    ToolContext,
    ToolDescriptor,
    ToolError,
    ToolResult,
)


class EmptyConfig(SdkModel):
    pass


def service_key(name: str) -> ServiceKey[object]:
    return ServiceKey(name)


def plugin_class(
    name: str,
    *,
    provides: tuple[ServiceKey, ...] = (),
    requires: tuple[ServiceKey, ...] = (),
    optional: tuple[ServiceKey, ...] = (),
    log: list[str] | None = None,
    on_setup: Callable[[Any], None] | None = None,
    fail: BaseException | None = None,
    cleanup: bool = True,
) -> type[object]:
    """Build a plugin that records setup/close and exercises declared services."""

    class TestPlugin(Plugin[EmptyConfig]):
        config_model = EmptyConfig

        async def setup(self, ctx: Any, config: EmptyConfig) -> None:
            if log is not None:
                log.append(f"setup:{name}")
            for key in requires:
                ctx.require(key)
            for key in optional:
                ctx.get(key)
            for key in provides:
                ctx.provide(key, object())
            if cleanup and log is not None:
                ctx.on_dispose(
                    lambda: log.append(f"close:{name}"), label=f"close {name}"
                )
            if on_setup is not None:
                on_setup(ctx)
            if fail is not None:
                raise fail

    TestPlugin.name = name
    TestPlugin.version = "0.1.0"
    TestPlugin.provides = provides
    TestPlugin.requires = requires
    TestPlugin.optional = optional
    return TestPlugin


class FakeHandle:
    def __init__(self, remove: Callable[[], None]) -> None:
        self._remove = remove
        self.closed = False

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._remove()


class FakeTools:
    """A small tools.v1 stand-in; behavior is covered by the SDK contract suite."""

    def __init__(self) -> None:
        self.tools: dict[str, tuple[object, ToolDescriptor]] = {}
        self.executors: dict[str, tuple[object, object]] = {}
        self.closed = False

    def _register(self, table: dict[str, tuple[object, object]], name: str, value: object) -> FakeHandle:
        if self.closed:
            raise RuntimeError("service is closed")
        if name in table:
            raise ValueError(f"duplicate registration {name!r}")
        token = object()
        table[name] = (token, value)

        def remove() -> None:
            if name in table and table[name][0] is token:
                del table[name]

        return FakeHandle(remove)

    def register_tool(self, descriptor: ToolDescriptor) -> FakeHandle:
        return self._register(self.tools, descriptor.name, descriptor)

    def register_executor(self, name: str, executor: object) -> FakeHandle:
        return self._register(self.executors, name, executor)

    def register_provider(self, provider: object) -> FakeHandle:
        raise NotImplementedError("providers are not part of this fixture")

    async def list_for_agent(self, scope: ExecutionScope) -> list[ToolDescriptor]:
        return [value for _, value in self.tools.values()]

    async def execute(self, call: Any, context: ToolContext) -> ToolResult:
        if self.closed:
            return ToolResult(
                status="error",
                error=ToolError(code="tool.unavailable", message="closed"),
            )
        if call.name not in context.visible_tool_names:
            return ToolResult(
                status="error", error=ToolError(code="tool.denied", message="denied")
            )
        entry = self.tools.get(call.name)
        if entry is None:
            return ToolResult(
                status="error", error=ToolError(code="tool.not_found", message="missing")
            )
        descriptor = entry[1]
        executor = self.executors[descriptor.executor][1]
        return await executor.execute(descriptor, call.arguments, context)  # type: ignore[union-attr]

    async def aclose(self) -> None:
        self.closed = True
        self.tools.clear()
        self.executors.clear()


class EchoConfig(SdkModel):
    prefix: str = ""


class EchoExecutor:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def execute(
        self, descriptor: ToolDescriptor, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        return ToolResult(data={"text": self.prefix + str(arguments.get("text", ""))})


class EchoPlugin(Plugin[EchoConfig]):
    name = "test.echo"
    version = "0.1.0"
    requires = (TOOLS,)
    config_model = EchoConfig

    async def setup(self, ctx: Any, config: EchoConfig) -> None:
        tools = ctx.require(TOOLS)
        ctx.track(tools.register_executor("echo", EchoExecutor(config.prefix)))
        ctx.track(
            tools.register_tool(
                ToolDescriptor(
                    name="echo",
                    executor="echo",
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


class ToolsPlugin(Plugin[EmptyConfig]):
    name = "test.tools"
    version = "0.1.0"
    provides = (TOOLS,)
    config_model = EmptyConfig

    async def setup(self, ctx: Any, config: EmptyConfig) -> None:
        self.tools = FakeTools()
        ctx.provide(TOOLS, self.tools)
        ctx.on_dispose(self.tools.aclose, label="fake tools")
