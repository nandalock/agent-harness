"""Test fixtures; none of this ships with the runtime package."""
from collections.abc import Callable
from typing import Any

from minidsh_cordis import Plugin, Registration, ServiceKey
from pydantic import BaseModel, ConfigDict

class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class EchoService:
    def __init__(self) -> None:
        self.handler: Callable[[str], str] | None = None
        self.closed = False

    def register(self, handler: Callable[[str], str]) -> Registration:
        self.handler = handler

        def remove() -> None:
            self.handler = None

        return Registration(remove)

    def execute(self, text: str) -> str:
        if self.handler is None:
            raise LookupError("no echo handler registered")
        return self.handler(text)

    async def aclose(self) -> None:
        self.closed = True
        self.handler = None


ECHO: ServiceKey[EchoService] = ServiceKey("test.echo-service")


class EchoConfig(EmptyConfig):
    prefix: str = ""


class EchoPlugin(Plugin[EchoConfig]):
    name = "test.echo"
    version = "0.1.0"
    requires = (ECHO,)
    config_model = EchoConfig

    async def setup(self, ctx: Any, config: EchoConfig) -> None:
        ctx.track(ctx.require(ECHO).register(lambda text: config.prefix + text))


class EchoServicePlugin(Plugin[EmptyConfig]):
    name = "test.echo-service"
    version = "0.1.0"
    provides = (ECHO,)
    config_model = EmptyConfig

    async def setup(self, ctx: Any, config: EmptyConfig) -> None:
        service = EchoService()
        ctx.provide(ECHO, service)
        ctx.on_dispose(service.aclose, label="echo service")
