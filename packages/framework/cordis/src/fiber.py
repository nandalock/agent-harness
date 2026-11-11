"""Plugin declarations and the state of an individual mounted instance."""

from asyncio import Event
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .services import ServiceKey

if TYPE_CHECKING:
    from .context import Context, _Runtime


class Plugin[Config]:
    """One plugin definition. Subclasses can declare metadata and implement setup."""

    name: str = ""
    version: str = ""
    web_package: str | None = None
    config_model: type[Config] | None = None
    requires: tuple[ServiceKey[Any], ...] = ()
    optional: tuple[ServiceKey[Any], ...] = ()
    provides: tuple[ServiceKey[Any], ...] = ()

    def __init__(
        self, setup: Callable[["Context", Config], Awaitable[None] | None] | None = None, *,
        requires: tuple[ServiceKey[Any], ...] = (),
        optional: tuple[ServiceKey[Any], ...] = (),
        provides: tuple[ServiceKey[Any], ...] = (),
    ) -> None:
        if setup is None and type(self) is Plugin:
            raise TypeError("a Cordis plugin needs a setup function")
        self._setup = setup
        if setup is not None:
            self.requires = requires
            self.optional = optional
            self.provides = provides

    def setup(self, ctx: "Context", config: Config) -> Awaitable[None] | None:
        if self._setup is None:
            raise NotImplementedError("implement setup() on the plugin")
        return self._setup(ctx, config)

    @property
    def dependencies(self) -> tuple[ServiceKey[Any], ...]:
        return self.requires + self.optional


class FiberState(StrEnum):
    PENDING = "pending"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    FAILED = "failed"
    DISPOSED = "disposed"


class Fiber:
    def __init__(self, runtime: "_Runtime", instance_id: str, plugin: Plugin[Any], config: Any) -> None:
        self._runtime = runtime
        self._id = instance_id
        self._plugin = plugin
        self._config = config
        self._state = FiberState.PENDING
        self._ctx: Context | None = None
        self._error: BaseException | None = None
        self._calls = 0
        self._idle = Event()
        self._idle.set()

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> FiberState:
        return self._state

    @property
    def ctx(self) -> "Context | None":
        return self._ctx

    @property
    def error(self) -> BaseException | None:
        return self._error

    @property
    def waiting_for(self) -> tuple[ServiceKey[Any], ...]:
        return tuple(key for key in self._plugin.requires if key not in self._runtime.services)

    def _enter_call(self) -> None:
        self._calls += 1
        self._idle.clear()

    def _leave_call(self) -> None:
        self._calls -= 1
        if not self._calls:
            self._idle.set()

    async def aclose(self) -> None:
        await self._runtime.remove(self)
