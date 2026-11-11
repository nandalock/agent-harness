"""Plugin declarations and the lifecycle of a single instance."""

from asyncio import CancelledError, Event
from collections.abc import Awaitable, Callable
from enum import StrEnum
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from .effects import Registration, unwind
from .services import ServiceKey

if TYPE_CHECKING:
    from .context import Context
    from .reflect import Binding
    from .registry import RegistryService


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
    def __init__(self, registry: "RegistryService", instance_id: str, plugin: Plugin[Any], config: Any) -> None:
        self._registry = registry
        self._id = instance_id
        self._plugin = plugin
        self._config = config
        self._state = FiberState.PENDING
        self._ctx: Context | None = None
        self._error: BaseException | None = None
        self._bindings: dict[ServiceKey[Any], Binding] = {}
        self._effects: list[Registration] = []
        self._quiesce_effects: list[Registration] = []
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
        return tuple(key for key in self._plugin.requires if key not in self._registry.reflect)

    def _can_activate(self, batch: set["Fiber"]) -> bool:
        if self._state not in (FiberState.PENDING, FiberState.FAILED) or self.waiting_for:
            return False
        reflect = self._registry.reflect
        return not any(
            provider in batch and provider.state in (FiberState.PENDING, FiberState.FAILED)
            for key in self._plugin.optional
            if key not in reflect and (provider := reflect.provider(key)) is not None
        )

    async def _refresh(self) -> dict["Fiber", None]:
        from .context import Context

        ctx = Context(_registry=self._registry, _fiber=self)
        self._ctx = ctx
        self._bindings = self._registry.reflect.bindings(self)
        self._state = FiberState.STARTING
        self._error = None
        result = self._plugin.setup(ctx, self._config)
        if isawaitable(result):
            await result
        notified = self._registry.reflect.publish(self)
        self._state = FiberState.ACTIVE
        return notified

    def _begin_stop(self) -> None:
        self._state = FiberState.STOPPING

    async def _quiesce(self) -> list[BaseException]:
        return await unwind(self._quiesce_effects)

    async def _unload(self) -> list[BaseException]:
        errors: list[BaseException] = []
        while not self._idle.is_set():
            try:
                await self._idle.wait()
            except CancelledError as error:
                # Keep draining on the same task that owns the plugin resources.
                errors.append(error)
        ctx = self._ctx
        assert ctx is not None
        errors.extend(await unwind(self._effects))
        ctx._closed = True
        self._registry.reflect.revoke(self)
        self._bindings.clear()
        return errors

    def _fail(self, error: BaseException) -> None:
        self._state = FiberState.FAILED
        self._error = error

    def _reset(self) -> None:
        self._state = FiberState.PENDING
        self._ctx = None
        self._error = None

    def _dispose(self) -> None:
        self._state = FiberState.DISPOSED

    def _enter_call(self) -> None:
        self._calls += 1
        self._idle.clear()

    def _leave_call(self) -> None:
        self._calls -= 1
        if not self._calls:
            self._idle.set()

    async def aclose(self) -> None:
        await self._registry.remove(self)
