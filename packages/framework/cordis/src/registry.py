"""Register plugin instances and serialize their lifecycle transitions."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextvars import ContextVar
from itertools import count
from typing import Any

from .errors import DependencyCycleError, MissingServiceError, PinnedServiceError
from .events import EventsService
from .fiber import Fiber, FiberState, Plugin
from .reflect import Binding, ReflectService
from .services import ServiceKey

type Entry = tuple[str, Plugin[Any], Any]


class RegistryService:
    def __init__(self, host_services: Mapping[ServiceKey[Any], Any], lifecycle_in_caller: bool) -> None:
        self.fibers: dict[str, Fiber] = {}
        self._host_services = dict(host_services)
        self.reflect = ReflectService(host_services, self.withdraw)
        self.active: dict[Fiber, int] = {}
        self._activations = count()
        self.closed = False
        self.in_callback = ContextVar("minidsh_cordis_in_callback", default=False)
        self.events = EventsService(self.in_callback)
        self._lock = asyncio.Lock()
        self._lifecycle_in_caller = lifecycle_in_caller

    async def _change[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        if self.in_callback.get():
            raise RuntimeError("plugin graph cannot change from a lifecycle callback or event handler")

        async def run() -> T:
            token = self.in_callback.set(True)
            try:
                return await operation()
            finally:
                self.in_callback.reset(token)

        async with self._lock:
            if self._lifecycle_in_caller:
                # Some async resources, including AnyIO transports, must enter
                # and exit on the same task. The application owns that task.
                return await run()
            # Once a transition starts, complete it even if the requesting task
            # is cancelled. No second operation can observe a partial graph.
            task = asyncio.create_task(run())
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
                except BaseException:
                    if not cancelled:
                        raise
            if cancelled:
                cause = None if task.cancelled() else task.exception()
                raise asyncio.CancelledError from cause
            return task.result()

    async def mount(self, plugin: Plugin[Any], instance_id: str, config: Any) -> Fiber:
        async def operation() -> Fiber:
            fiber, = self._register_batch([(instance_id, plugin, config)], require_providers=False)
            await self._settle([fiber], strict=False)
            return fiber

        return await self._change(operation)

    def _register(self, instance_id: str, plugin: Plugin[Any], config: Any) -> Fiber:
        if self.closed:
            raise RuntimeError("context is closed")
        if not instance_id.strip() or instance_id in self.fibers:
            raise ValueError(f"invalid or duplicate plugin id {instance_id!r}")
        if len(set(plugin.dependencies)) != len(plugin.dependencies):
            raise ValueError(f"plugin {instance_id!r} declared a dependency more than once")
        if len(set(plugin.provides)) != len(plugin.provides):
            raise ValueError("a plugin must declare each provided service once")
        fiber = Fiber(self, instance_id, plugin, config)
        self.reflect.watch(fiber)
        self.fibers[instance_id] = fiber
        return fiber

    def _register_batch(self, entries: Iterable[Entry], *, require_providers: bool = True) -> list[Fiber]:
        registered: list[Fiber] = []
        try:
            for entry in entries:
                registered.append(self._register(*entry))
            if require_providers:
                self._check_missing(registered, self.reflect.has_provider)
            self._check_cycles(registered)
        except BaseException:
            for fiber in registered:
                self._forget(fiber)
            raise
        return registered

    @staticmethod
    def _check_missing(fibers: Iterable[Fiber], available: Callable[[ServiceKey[Any]], bool]) -> None:
        missing = [
            f"{fiber.id!r} requires {key}"
            for fiber in fibers for key in fiber._plugin.requires if not available(key)
        ]
        if missing:
            raise MissingServiceError("missing required services: " + ", ".join(missing))

    def _check_cycles(self, added: Iterable[Fiber]) -> None:
        def providers(fiber: Fiber) -> Iterable[Fiber]:
            for key in fiber._plugin.dependencies:
                if (provider := self.reflect.provider(key)) is not None:
                    yield provider

        checked: set[Fiber] = set()
        for fiber in added:
            if fiber in checked:
                continue
            path = dict.fromkeys([fiber])
            stack = [iter(providers(fiber))]
            while stack:
                dependency = next(stack[-1], None)
                if dependency is None:
                    checked.add(path.popitem()[0])
                    stack.pop()
                elif dependency in path:
                    cycle = list(path)
                    names = [item.id for item in cycle[cycle.index(dependency):]]
                    raise DependencyCycleError("dependency cycle: " + " -> ".join([*names, dependency.id]))
                elif dependency not in checked:
                    path[dependency] = None
                    stack.append(iter(providers(dependency)))

    def validate(self, entries: Iterable[Entry]) -> None:
        probe = RegistryService(self._host_services, lifecycle_in_caller=True)
        for fiber in probe._register_batch(entries):
            probe._forget(fiber)

    async def start(self, entries: Iterable[Entry]) -> None:
        async def operation() -> None:
            if self.closed or self.fibers:
                raise RuntimeError("composition startup requires a fresh context")
            registered = self._register_batch(entries)
            try:
                await self._settle(registered, strict=True)
                self._check_missing(registered, self.reflect.__contains__)
            except BaseException as error:
                self._note_rollback(error, await self._stop(registered))
                for fiber in registered:
                    self._forget(fiber)
                raise

        await self._change(operation)

    async def _settle(
        self, fibers: Iterable[Fiber], *, strict: bool, prefer: set[Fiber] | None = None,
    ) -> None:
        ready = dict.fromkeys(fibers)
        batch = prefer if prefer is not None else (set(ready) if strict else set())
        errors: list[BaseException] = []
        while ready:
            fiber = next(iter(ready))
            del ready[fiber]
            if not fiber._can_activate(batch):
                continue
            try:
                notified = await fiber._refresh()
            except BaseException as error:
                if strict:
                    raise
                self._note_rollback(error, await self._stop([fiber]))
                fiber._fail(error)
                if not isinstance(error, Exception):
                    raise
                continue
            self.active[fiber] = next(self._activations)
            invalidated = self.reflect.affected(
                (fiber for fiber in notified if fiber.state is FiberState.ACTIVE), published_only=True,
            )
            errors.extend(await self._suspend(invalidated))
            ready.update(invalidated)
            ready.update(notified)
        self._raise_cleanup_errors("failed to refresh service consumers", errors)

    async def replace(
        self, remove: set[str], entries: Iterable[Entry], *, pinned: frozenset[ServiceKey[Any]],
    ) -> tuple[str, ...]:
        async def operation() -> tuple[str, ...]:
            if self.closed:
                raise RuntimeError("context is closed")
            if remove - self.fibers.keys():
                raise ValueError("only registered fibers can be replaced")
            incoming = tuple(entries)
            retained = [
                (fiber.id, fiber._plugin, fiber._config) for fiber in self.fibers.values() if fiber.id not in remove
            ]
            self.validate([*retained, *incoming])
            old = [fiber for fiber in self.fibers.values() if fiber.id in remove]
            added_keys = tuple(key for _, plugin, _ in incoming for key in plugin.provides)
            affected = self.reflect.affected(old, added_keys)
            if pinned.intersection(added_keys) or any(pinned.intersection(fiber._plugin.provides) for fiber in affected):
                raise PinnedServiceError("plugin configuration changes a service bound to the host; restart required")
            active_ids = {fiber.id for fiber in affected if fiber.state is FiberState.ACTIVE}
            survivors = [fiber for fiber in affected if fiber.id not in remove]
            errors = await self._suspend(affected)
            for fiber in old:
                self._forget(fiber)
            added: list[Fiber] = []
            try:
                self._raise_cleanup_errors("plugin replacement teardown failed", errors)
                added = self._register_batch(incoming)
                await self._settle([*survivors, *added], strict=True)
                self._check_missing([*survivors, *added], self.reflect.__contains__)
            except BaseException as error:
                self._note_rollback(error, await self._suspend([*survivors, *added]))
                for fiber in added:
                    self._forget(fiber)
                try:
                    restored = self._register_batch(
                        ((fiber.id, fiber._plugin, fiber._config) for fiber in old), require_providers=False,
                    )
                    recover = [*survivors, *restored]
                    active = {fiber for fiber in recover if fiber.id in active_ids}
                    try:
                        await self._settle(recover, strict=True, prefer=active)
                        self._check_missing(active, self.reflect.__contains__)
                    except BaseException as rollback:
                        self._note_rollback(rollback, await self._suspend(recover))
                        raise
                except BaseException as rollback:
                    self._note_rollback(error, [rollback])
                raise
            return tuple(sorted({fiber.id for fiber in affected}.union(fiber.id for fiber in added)))

        return await self._change(operation)

    @staticmethod
    def _note_rollback(error: BaseException, failures: list[BaseException]) -> None:
        for failure in failures:
            error.add_note(f"plugin rollback also failed: {failure!r}")

    @staticmethod
    def _raise_cleanup_errors(message: str, errors: list[BaseException]) -> None:
        if len(errors) == 1 and isinstance(errors[0], asyncio.CancelledError):
            raise errors[0]
        if errors:
            raise BaseExceptionGroup(message, errors)

    async def _stop(self, fibers: Iterable[Fiber]) -> list[BaseException]:
        stopping = sorted(
            (fiber for fiber in fibers if fiber.state in (FiberState.ACTIVE, FiberState.STARTING)),
            key=lambda fiber: self.active.get(fiber, float("inf")), reverse=True,
        )
        errors: list[BaseException] = []
        for fiber in stopping:
            fiber._begin_stop()
        for fiber in stopping:
            errors.extend(await fiber._quiesce())
        for fiber in stopping:
            errors.extend(await fiber._unload())
            self.active.pop(fiber, None)
        return errors

    def _forget(self, fiber: Fiber) -> None:
        del self.fibers[fiber.id]
        self.reflect.unwatch(fiber)
        fiber._dispose()

    async def remove(self, fiber: Fiber) -> None:
        async def operation() -> None:
            if self.fibers.get(fiber.id) is not fiber:
                return
            affected = self.reflect.affected([fiber], published_only=True)
            errors = await self._suspend(affected)
            self._forget(fiber)
            del affected[fiber]
            await self._settle(affected, strict=False)
            self._raise_cleanup_errors(f"failed to stop {fiber.id!r}", errors)

        await self._change(operation)

    async def _suspend(self, affected: Iterable[Fiber]) -> list[BaseException]:
        errors = await self._stop(affected)
        for fiber in affected:
            fiber._reset()
        return errors

    async def withdraw(self, key: ServiceKey[Any], binding: Binding) -> None:
        async def operation() -> None:
            if not self.reflect.is_current(key, binding):
                return
            affected = self.reflect.affected((), [key], published_only=True)
            errors = await self._suspend(affected)
            self.reflect.withdraw(key, binding)
            await self._settle(affected, strict=False)
            self._raise_cleanup_errors(f"failed to withdraw {key}", errors)

        await self._change(operation)

    async def close(self) -> None:
        async def operation() -> None:
            errors = await self._stop(self.active)
            for fiber in tuple(self.fibers.values()):
                self._forget(fiber)
            self.reflect.clear()
            self.closed = True
            self._raise_cleanup_errors("plugin shutdown failed", errors)

        await self._change(operation)
