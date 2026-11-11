"""Public plugin context and its scope."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from .effects import Cleanup, Closeable, Registration
from .errors import ServiceClosedError, ServiceUnavailableError
from .events import EventKey, Middleware
from .fiber import Fiber, FiberState, Plugin
from .registry import RegistryService
from .services import ServiceKey


class Context:
    def __init__(
        self, *, host_services: Mapping[ServiceKey[Any], Any] | None = None,
        lifecycle_in_caller: bool = False, _registry: RegistryService | None = None,
        _fiber: Fiber | None = None,
    ) -> None:
        self._registry = _registry if _registry is not None else RegistryService(host_services or {}, lifecycle_in_caller)
        self._fiber = _fiber
        self._closed = False

    @property
    def fibers(self) -> tuple[Fiber, ...]:
        return tuple(self._registry.fibers.values())

    @property
    def active_fibers(self) -> tuple[Fiber, ...]:
        return tuple(fiber for fiber in self._registry.active if fiber.state is FiberState.ACTIVE)

    @property
    def instance_id(self) -> str:
        if self._fiber is None:
            raise RuntimeError("the root context has no plugin instance")
        return self._fiber.id

    @property
    def plugin_name(self) -> str:
        if self._fiber is None:
            raise RuntimeError("the root context has no plugin instance")
        return self._fiber._plugin.name

    async def plugin[Config](self, plugin: Plugin[Config], *, id: str, config: Config) -> Fiber:
        self._ensure_root()
        return await self._registry.mount(plugin, id, config)

    async def start(self, entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        """Start a batch with rollback if any required service or setup fails."""
        self._ensure_root()
        await self._registry.start(entries)

    def validate(self, entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        """Check service declarations without starting plugins."""
        self._ensure_root()
        self._registry.validate(entries)

    async def replace(self, remove: set[str], entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        """Replace registered instances and refresh their service consumers."""
        await self.reconfigure(remove, entries)

    async def reconfigure(
        self, remove: set[str], entries: Iterable[tuple[str, Plugin[Any], Any]], *,
        pinned: frozenset[ServiceKey[Any]] = frozenset(),
    ) -> tuple[str, ...]:
        """Apply a replacement and return all changed or refreshed instance IDs."""
        self._ensure_root()
        return await self._registry.replace(remove, entries, pinned=pinned)

    @property
    def closed(self) -> bool:
        return self._closed or self._registry.closed

    async def aclose(self) -> None:
        self._ensure_root()
        await self._registry.close()

    def _ensure_root(self) -> None:
        if self._fiber is not None:
            raise RuntimeError("only the root context can change the plugin graph")

    def _ensure_open(self) -> None:
        if self.closed:
            raise ServiceClosedError("context is closed")

    def _owner(self) -> Fiber:
        self._ensure_open()
        fiber = self._fiber
        if fiber is None or fiber.state not in (FiberState.STARTING, FiberState.ACTIVE):
            raise RuntimeError("registration requires a starting or active plugin")
        return fiber

    def require[T](self, key: ServiceKey[T]) -> T:
        value = self.get(key)
        if value is None:
            raise ServiceUnavailableError(key)
        return value

    def get[T](self, key: ServiceKey[T]) -> T | None:
        self._ensure_open()
        return self._registry.reflect.get(self._fiber, key)

    def provide[T](self, key: ServiceKey[T], service: T) -> Registration:
        return self._registry.reflect.provide(self._owner(), key, service)

    def track[T: Closeable](self, registration: T) -> T:
        self.on_dispose(registration.aclose)
        return registration

    def on_dispose(self, cleanup: Cleanup, *, label: str | None = None) -> Registration:
        fiber = self._owner()
        registration = Registration(cleanup, label)
        fiber._effects.append(registration)
        return registration

    def on_quiesce(self, cleanup: Cleanup, *, label: str | None = None) -> Registration:
        fiber = self._owner()
        registration = Registration(cleanup, label)
        fiber._quiesce_effects.append(registration)
        return registration

    def on[T](self, event: EventKey[T], handler: Callable[[T], object]) -> Registration:
        return self._registry.events.on(self._owner(), event, handler)

    def once[T](self, event: EventKey[T], handler: Callable[[T], object]) -> Registration:
        return self._registry.events.once(self._owner(), event, handler)

    def emit[T](self, event: EventKey[T], value: T) -> None:
        self._registry.events.emit(self, event, value)

    async def parallel[T](self, event: EventKey[T], value: T) -> None:
        await self._registry.events.parallel(self, event, value)

    async def serial[T](self, event: EventKey[T], value: T) -> object:
        return await self._registry.events.serial(self, event, value)

    def bail[T](self, event: EventKey[T], value: T) -> object:
        return self._registry.events.bail(self, event, value)

    async def waterfall[T](self, event: EventKey[T], value: T) -> T:
        return await self._registry.events.waterfall(self, event, value)

    def on_middleware[T, R](self, event: EventKey[T], handler: Middleware[T, R]) -> Registration:
        return self._registry.events.on_middleware(self._owner(), event, handler)

    async def waterfall_next[T, R](
        self, event: EventKey[T], value: T, terminal: Callable[[T], Awaitable[R] | R],
    ) -> R:
        return await self._registry.events.waterfall_next(self, event, value, terminal)
