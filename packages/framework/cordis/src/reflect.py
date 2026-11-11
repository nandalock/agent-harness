"""Stage, publish, and resolve services shared by one root context."""

from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, cast

from .effects import Registration
from .errors import RegistrationConflictError, ServiceConflictError, ServiceUnavailableError, UndeclaredServiceError
from .fiber import Fiber, FiberState
from .services import ServiceKey

type Binding = tuple[Fiber | None, object]


class ReflectService:
    def __init__(
        self,
        host_services: Mapping[ServiceKey[Any], Any],
        suspend_dependents: Callable[[ServiceKey[Any], Binding], Awaitable[None]],
    ) -> None:
        self._services: dict[ServiceKey[Any], Binding] = {
            key: (None, value) for key, value in host_services.items()
        }
        self._pending: dict[Fiber, dict[ServiceKey[Any], Binding]] = {}
        self._providers: dict[ServiceKey[Any], Fiber] = {}
        self._subscribers: dict[ServiceKey[Any], dict[Fiber, None]] = {}
        self._suspend_dependents = suspend_dependents

    def __contains__(self, key: ServiceKey[Any]) -> bool:
        binding = self._services.get(key)
        return binding is not None and (binding[0] is None or binding[0].state is FiberState.ACTIVE)

    def watch(self, fiber: Fiber) -> None:
        for key in fiber._plugin.provides:
            if self.has_provider(key):
                owner = self._providers.get(key)
                name = owner.id if owner is not None else "<host>"
                raise ServiceConflictError(f"{key} is already reserved by {name!r}")
        for key in fiber._plugin.provides:
            self._providers[key] = fiber
        for key in fiber._plugin.dependencies:
            self._subscribers.setdefault(key, {})[fiber] = None

    def unwatch(self, fiber: Fiber) -> None:
        for key in fiber._plugin.provides:
            del self._providers[key]
        for key in fiber._plugin.dependencies:
            subscribers = self._subscribers[key]
            del subscribers[fiber]
            if not subscribers:
                del self._subscribers[key]

    def provider(self, key: ServiceKey[Any]) -> Fiber | None:
        return self._providers.get(key)

    def has_provider(self, key: ServiceKey[Any]) -> bool:
        return key in self._providers or key in self._services

    def subscribers(self, keys: Iterable[ServiceKey[Any]]) -> dict[Fiber, None]:
        return dict.fromkeys(fiber for key in keys for fiber in self._subscribers.get(key, ()))

    def affected(
        self, fibers: Iterable[Fiber], keys: Iterable[ServiceKey[Any]] = (), *, published_only: bool = False,
    ) -> dict[Fiber, None]:
        """Follow subscriptions from changed bindings to downstream consumers."""
        affected = dict.fromkeys(fibers)
        affected.update(self.subscribers(keys))
        queue = deque(affected)
        while queue:
            fiber = queue.popleft()
            provided = (key for key in fiber._plugin.provides if not published_only or key in self)
            for consumer in self.subscribers(provided):
                if consumer not in affected:
                    affected[consumer] = None
                    queue.append(consumer)
        return affected

    def bindings(self, fiber: Fiber) -> dict[ServiceKey[Any], Binding]:
        return {key: self._services[key] for key in fiber._plugin.dependencies if key in self}

    def get[T](self, fiber: Fiber | None, key: ServiceKey[T]) -> T | None:
        if fiber is not None and key not in fiber._plugin.dependencies:
            raise UndeclaredServiceError(f"{fiber.id!r} did not declare {key}")
        registered = self._services.get(key) if fiber is None else fiber._bindings.get(key)
        if registered is not None:
            provider, service = registered
            if fiber is not None or provider is None or provider.state is FiberState.ACTIVE:
                return cast(T, service)
        if fiber is not None and key in fiber._plugin.requires:
            raise ServiceUnavailableError(key)
        return None

    def provide[T](self, fiber: Fiber, key: ServiceKey[T], service: T) -> Registration:
        if key not in fiber._plugin.provides:
            raise UndeclaredServiceError(f"{fiber.id!r} did not declare {key}")
        if fiber.state is not FiberState.STARTING:
            raise RegistrationConflictError(f"{fiber.id!r} can only publish services during setup: {key}")
        if service is None:
            raise ValueError(f"service {key} must not be None")
        pending = self._pending.setdefault(fiber, {})
        if key in pending:
            raise RegistrationConflictError(f"{fiber.id!r} already provided {key}")
        binding = (fiber, service)
        pending[key] = binding

        async def withdraw() -> None:
            if pending.get(key) is binding:
                del pending[key]
            elif fiber.state is FiberState.ACTIVE and self.is_current(key, binding):
                await self._suspend_dependents(key, binding)

        return Registration(withdraw)

    def publish(self, fiber: Fiber) -> dict[Fiber, None]:
        pending = self._pending.get(fiber, {})
        missing = set(fiber._plugin.provides) - pending.keys()
        if missing:
            raise ValueError("setup did not provide " + ", ".join(sorted(map(str, missing))))
        self._services.update(pending)
        self._clear_pending(fiber)
        return self.subscribers(fiber._plugin.provides)

    def _clear_pending(self, fiber: Fiber) -> None:
        pending = self._pending.pop(fiber, None)
        if pending is not None:
            pending.clear()

    def revoke(self, fiber: Fiber) -> None:
        self._clear_pending(fiber)
        for key in fiber._plugin.provides:
            self._services.pop(key, None)

    def is_current(self, key: ServiceKey[Any], binding: Binding) -> bool:
        return self._services.get(key) is binding

    def withdraw(self, key: ServiceKey[Any], binding: Binding) -> None:
        if self.is_current(key, binding):
            del self._services[key]

    def clear(self) -> None:
        self._services.clear()
