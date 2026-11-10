"""Root context, plugin-owned contexts and serialized lifecycle transitions."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextvars import ContextVar
from inspect import isawaitable
from typing import Any, cast

from .effects import Cleanup, Closeable, Registration, unwind
from .errors import RegistrationConflictError, ServiceClosedError, ServiceUnavailableError, UndeclaredServiceError
from .events import EventKey, Handler, Listener
from .fiber import Fiber, FiberState, Plugin
from .graph import plan
from .services import ServiceKey


class Context:
    def __init__(
        self, *, host_services: Mapping[ServiceKey[Any], Any] | None = None,
        lifecycle_in_caller: bool = False, _runtime: "_Runtime | None" = None, _fiber: Fiber | None = None,
    ) -> None:
        self._runtime = _Runtime(host_services or {}, lifecycle_in_caller) if _runtime is None else _runtime
        self._fiber = _fiber
        self._provided: dict[ServiceKey[Any], tuple[Fiber, object]] = {}
        self._effects: list[Registration] = []
        self._quiesce: list[Registration] = []
        self._closed = False

    @property
    def fibers(self) -> tuple[Fiber, ...]:
        return tuple(self._runtime.fibers.values())

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
        return await self._runtime.mount(plugin, id, config)

    async def start(self, entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        """Order and start a composition with whole-graph rollback."""
        self._ensure_root()
        await self._runtime.start(entries)

    async def replace(self, remove: set[str], entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        """Apply a dependency-ordered replacement, restoring the old entries on failure."""
        self._ensure_root()
        await self._runtime.replace(remove, entries)

    @property
    def closed(self) -> bool:
        return self._closed or self._runtime.closed

    async def aclose(self) -> None:
        self._ensure_root()
        await self._runtime.close()

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
        fiber = self._fiber
        if fiber is not None and key not in fiber._plugin.dependencies:
            raise UndeclaredServiceError(f"{fiber.id!r} did not declare {key}")
        registered = self._runtime.services.get(key)
        if registered is not None:
            provider, service = registered
            if fiber is not None or provider is None or provider.state is FiberState.ACTIVE:
                return cast(T, service)
        if fiber is not None and key in fiber._plugin.requires:
            raise ServiceUnavailableError(key)
        return None

    def provide[T](self, key: ServiceKey[T], service: T) -> Registration:
        fiber = self._owner()
        if key not in fiber._plugin.provides:
            raise UndeclaredServiceError(f"{fiber.id!r} did not declare {key}")
        if fiber.state is not FiberState.STARTING:
            raise RegistrationConflictError(f"{fiber.id!r} can only publish services during setup: {key}")
        if service is None:
            raise ValueError(f"service {key} must not be None")
        if key in self._provided:
            raise RegistrationConflictError(f"{fiber.id!r} already provided {key}")
        binding = (fiber, service)
        self._provided[key] = binding

        async def withdraw() -> None:
            if self._provided.get(key) is binding:
                del self._provided[key]
            elif fiber.state is FiberState.ACTIVE and self._runtime.services.get(key) is binding:
                await self._runtime.withdraw(key, binding)

        return Registration(withdraw)

    def track[T: Closeable](self, registration: T) -> T:
        self.on_dispose(registration.aclose)
        return registration

    def on_dispose(self, cleanup: Cleanup, *, label: str | None = None) -> Registration:
        self._owner()
        registration = Registration(cleanup, label)
        self._effects.append(registration)
        return registration

    def on_quiesce(self, cleanup: Cleanup, *, label: str | None = None) -> Registration:
        self._owner()
        registration = Registration(cleanup, label)
        self._quiesce.append(registration)
        return registration

    def on[T](self, event: EventKey[T], handler: Handler[T]) -> Registration:
        listener = Listener(self._owner(), handler)
        listeners = self._runtime.listeners.setdefault(event, [])
        listeners.append(listener)

        def remove() -> None:
            listener.active = False
            listeners.remove(listener)
            if not listeners:
                del self._runtime.listeners[event]

        registration = Registration(remove)
        self._effects.append(registration)
        return registration

    async def waterfall[T](self, event: EventKey[T], value: T) -> T:
        self._ensure_open()
        listeners = self._runtime.listeners.get(event, ())
        for listener in tuple(listeners):
            self._ensure_open()
            fiber = listener.fiber
            if not listener.active or fiber.state is not FiberState.ACTIVE:
                continue
            token = self._runtime.in_callback.set(True)
            fiber._enter_call()
            try:
                result = listener.handler(value)
                value = await result if isawaitable(result) else result
            finally:
                fiber._leave_call()
                self._runtime.in_callback.reset(token)
        return value


class _Runtime:
    def __init__(self, host_services: Mapping[ServiceKey[Any], Any], lifecycle_in_caller: bool) -> None:
        self.fibers: dict[str, Fiber] = {}
        self.providers: dict[ServiceKey[Any], str] = {}
        self.services: dict[ServiceKey[Any], tuple[Fiber | None, object]] = {
            key: (None, value) for key, value in host_services.items()
        }
        self.active: list[Fiber] = []
        self.listeners: dict[EventKey[Any], list[Listener]] = {}
        self.closed = False
        self.in_callback = ContextVar("minidsh_cordis_in_callback", default=False)
        self._lock = asyncio.Lock()
        self._lifecycle_in_caller = lifecycle_in_caller

    def _order(self) -> tuple[str, ...]:
        return tuple(instance for instance, _, _ in plan(
            ((fiber.id, fiber._plugin, fiber._config) for fiber in self.fibers.values()),
            (key for key, (fiber, _) in self.services.items() if fiber is None),
            allow_pending=True,
        ).entries)

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
            fiber = self._register(instance_id, plugin, config)
            try:
                order = self._order()
            except ValueError:
                self._forget(fiber)
                raise
            for candidate_id in order:
                candidate = self.fibers[candidate_id]
                if candidate.state is FiberState.PENDING and not candidate.waiting_for:
                    try:
                        await self._activate(candidate)
                    except BaseException as error:
                        self._note_rollback(error, await self._stop([candidate]))
                        candidate._state = FiberState.FAILED
                        candidate._error = error
                        if not isinstance(error, Exception):
                            raise
            return fiber

        return await self._change(operation)

    def _register(self, instance_id: str, plugin: Plugin[Any], config: Any) -> Fiber:
        if self.closed:
            raise RuntimeError("context is closed")
        if not instance_id.strip() or instance_id in self.fibers:
            raise ValueError(f"invalid or duplicate plugin id {instance_id!r}")
        if len(set(plugin.provides)) != len(plugin.provides):
            raise ValueError("a plugin must declare each provided service once")
        for key in plugin.provides:
            if key in self.providers or key in self.services:
                raise ValueError(f"{key} is already reserved by {self.providers.get(key, '<host>')!r}")
        fiber = Fiber(self, instance_id, plugin, config)
        self.fibers[instance_id] = fiber
        self.providers.update(dict.fromkeys(plugin.provides, instance_id))
        return fiber

    async def start(self, entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        async def operation() -> None:
            if self.closed or self.fibers:
                raise RuntimeError("composition startup requires a fresh context")
            await self._start_entries(entries)

        await self._change(operation)

    async def _start_entries(self, entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        registered: list[Fiber] = []
        try:
            for instance_id, plugin, config in plan(entries, self.services).entries:
                fiber = self._register(instance_id, plugin, config)
                registered.append(fiber)
                if fiber.waiting_for:
                    raise LookupError(f"{fiber.id!r} is waiting for {fiber.waiting_for}")
                await self._activate(fiber)
        except BaseException as error:
            self._note_rollback(error, await self._stop([fiber for fiber in reversed(registered) if fiber.ctx is not None]))
            for fiber in registered:
                self._forget(fiber)
            raise

    async def replace(self, remove: set[str], entries: Iterable[tuple[str, Plugin[Any], Any]]) -> None:
        async def operation() -> None:
            if self.closed:
                raise RuntimeError("context is closed")
            old = [fiber for fiber in self.active if fiber.id in remove]
            if {fiber.id for fiber in old} != remove:
                raise ValueError("only active fibers can be replaced")
            keys = {key for fiber in old for key in fiber._plugin.provides}
            if self._affected(keys) - remove:
                raise ValueError("replacement must include all dependent fibers")
            errors = await self._stop(list(reversed(old)))
            for fiber in old:
                self._forget(fiber)
            try:
                if errors:
                    raise BaseExceptionGroup("plugin replacement teardown failed", errors)
                await self._start_entries(entries)
            except BaseException as error:
                try:
                    await self._start_entries((fiber.id, fiber._plugin, fiber._config) for fiber in old)
                except BaseException as rollback:
                    self._note_rollback(error, [rollback])
                raise

        await self._change(operation)

    @staticmethod
    def _note_rollback(error: BaseException, failures: list[BaseException]) -> None:
        for failure in failures:
            error.add_note(f"plugin rollback also failed: {failure!r}")

    async def _activate(self, fiber: Fiber) -> None:
        ctx = Context(_runtime=self, _fiber=fiber)
        fiber._ctx = ctx
        fiber._state = FiberState.STARTING
        fiber._error = None
        result = fiber._plugin.setup(ctx, fiber._config)
        if isawaitable(result):
            await result
        missing = set(fiber._plugin.provides) - ctx._provided.keys()
        if missing:
            raise ValueError("setup did not provide " + ", ".join(sorted(map(str, missing))))
        self.services.update(ctx._provided)
        ctx._provided.clear()
        fiber._state = FiberState.ACTIVE
        self.active.append(fiber)

    async def _stop(self, fibers: list[Fiber]) -> list[BaseException]:
        errors: list[BaseException] = []
        for fiber in fibers:
            fiber._state = FiberState.STOPPING
        for fiber in fibers:
            ctx = fiber.ctx
            assert ctx is not None
            errors.extend(await unwind(ctx._quiesce))
        for fiber in fibers:
            await fiber._idle.wait()
            ctx = fiber.ctx
            assert ctx is not None
            errors.extend(await unwind(ctx._effects))
            ctx._provided.clear()
            ctx._closed = True
            for key in fiber._plugin.provides:
                self.services.pop(key, None)
        self.active = [fiber for fiber in self.active if fiber.state is FiberState.ACTIVE]
        return errors

    def _forget(self, fiber: Fiber) -> None:
        del self.fibers[fiber.id]
        for key in fiber._plugin.provides:
            del self.providers[key]
        fiber._state = FiberState.DISPOSED

    async def remove(self, fiber: Fiber) -> None:
        async def operation() -> None:
            if self.fibers.get(fiber.id) is not fiber:
                return
            affected = self._affected(set(fiber._plugin.provides)) | {fiber.id}
            errors = await self._suspend(affected)
            self._forget(fiber)
            if errors:
                raise BaseExceptionGroup(f"failed to stop {fiber.id!r}", errors)

        await self._change(operation)

    def _affected(self, keys: set[ServiceKey[Any]]) -> set[str]:
        affected = set()
        for instance_id in self._order():
            plugin = self.fibers[instance_id]._plugin
            if keys.intersection(plugin.dependencies):
                affected.add(instance_id)
                keys.update(plugin.provides)
        return affected

    async def _suspend(self, affected: set[str]) -> list[BaseException]:
        errors = await self._stop([fiber for fiber in reversed(self.active) if fiber.id in affected])
        for instance_id in affected:
            fiber = self.fibers[instance_id]
            fiber._state = FiberState.PENDING
            fiber._ctx = None
            fiber._error = None
        return errors

    async def withdraw(self, key: ServiceKey[Any], binding: tuple[Fiber, object]) -> None:
        async def operation() -> None:
            if self.services.get(key) is not binding:
                return
            errors = await self._suspend(self._affected({key}))
            del self.services[key]
            if errors:
                raise BaseExceptionGroup(f"failed to withdraw {key}", errors)

        await self._change(operation)

    async def close(self) -> None:
        async def operation() -> None:
            errors = await self._stop(list(reversed(self.active)))
            for fiber in tuple(self.fibers.values()):
                self._forget(fiber)
            self.services.clear()
            self.closed = True
            if errors:
                raise BaseExceptionGroup("plugin shutdown failed", errors)

        await self._change(operation)
