"""Root context, plugin-owned contexts and serialized lifecycle transitions."""

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from graphlib import TopologicalSorter
from inspect import isawaitable
from typing import Any, cast

from .effects import Cleanup, Registration, unwind
from .events import EventKey, Handler, Listener
from .fiber import Fiber, FiberState, Plugin
from .services import ServiceKey


class Context:
    def __init__(self, *, _runtime: "_Runtime | None" = None, _fiber: Fiber | None = None) -> None:
        self._runtime = _Runtime() if _runtime is None else _runtime
        self._fiber = _fiber
        self._provided: dict[ServiceKey[Any], object] = {}
        self._effects: list[Registration] = []
        self._quiesce: list[Registration] = []
        self._closed = False

    @property
    def fibers(self) -> tuple[Fiber, ...]:
        return tuple(self._runtime.fibers.values())

    async def plugin[Config](self, plugin: Plugin[Config], *, id: str, config: Config) -> Fiber:
        self._ensure_root()
        return await self._runtime.mount(plugin, id, config)

    async def aclose(self) -> None:
        self._ensure_root()
        await self._runtime.close()

    def _ensure_root(self) -> None:
        if self._fiber is not None:
            raise RuntimeError("only the root context can change the plugin graph")

    def _ensure_open(self) -> None:
        if self._closed or self._runtime.closed:
            raise RuntimeError("context is closed")

    def _owner(self) -> Fiber:
        self._ensure_open()
        fiber = self._fiber
        if fiber is None or fiber.state not in (FiberState.STARTING, FiberState.ACTIVE):
            raise RuntimeError("registration requires a starting or active plugin")
        return fiber

    def require[T](self, key: ServiceKey[T]) -> T:
        self._ensure_open()
        fiber = self._fiber
        if fiber is not None and key not in fiber._plugin.requires:
            raise LookupError(f"{fiber.id!r} did not declare {key}")
        registered = self._runtime.services.get(key)
        if registered is not None:
            provider, service = registered
            if fiber is not None or provider.state is FiberState.ACTIVE:
                return cast(T, service)
        raise LookupError(f"service {key} is unavailable")

    def provide[T](self, key: ServiceKey[T], service: T) -> None:
        fiber = self._owner()
        if fiber.state is not FiberState.STARTING or key not in fiber._plugin.provides:
            raise ValueError(f"{fiber.id!r} can only provide declared services during setup: {key}")
        if key in self._provided:
            raise ValueError(f"{fiber.id!r} already provided {key}")
        self._provided[key] = service

    def on_dispose(self, cleanup: Cleanup) -> None:
        self._owner()
        self._effects.append(Registration(cleanup))

    def on_quiesce(self, cleanup: Cleanup) -> None:
        self._owner()
        self._quiesce.append(Registration(cleanup))

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
    def __init__(self) -> None:
        self.fibers: dict[str, Fiber] = {}
        self.providers: dict[ServiceKey[Any], str] = {}
        self.services: dict[ServiceKey[Any], tuple[Fiber, object]] = {}
        self.listeners: dict[EventKey[Any], list[Listener]] = {}
        self.closed = False
        self.in_callback = ContextVar("minidsh_cordis_in_callback", default=False)
        self._lock = asyncio.Lock()

    def _order(self) -> tuple[str, ...]:
        graph = {
            instance_id: tuple(self.providers[key] for key in fiber._plugin.requires if key in self.providers)
            for instance_id, fiber in self.fibers.items()
        }
        return tuple(TopologicalSorter(graph).static_order())

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
            if self.closed:
                raise RuntimeError("context is closed")
            if not instance_id.strip() or instance_id in self.fibers:
                raise ValueError(f"invalid or duplicate plugin id {instance_id!r}")
            if len(set(plugin.provides)) != len(plugin.provides):
                raise ValueError("a plugin must declare each provided service once")
            for key in plugin.provides:
                if key in self.providers:
                    raise ValueError(f"{key} is already reserved by {self.providers[key]!r}")

            fiber = Fiber(self, instance_id, plugin, config)
            self.fibers[instance_id] = fiber
            self.providers.update(dict.fromkeys(plugin.provides, instance_id))
            try:
                order = self._order()
            except ValueError:
                self._forget(fiber)
                raise
            for candidate_id in order:
                candidate = self.fibers[candidate_id]
                if candidate.state is FiberState.PENDING and not candidate.waiting_for:
                    await self._start(candidate)
            return fiber

        return await self._change(operation)

    async def _start(self, fiber: Fiber) -> None:
        ctx = Context(_runtime=self, _fiber=fiber)
        fiber._ctx = ctx
        fiber._state = FiberState.STARTING
        fiber._error = None
        try:
            result = fiber._plugin.setup(ctx, fiber._config)
            if isawaitable(result):
                await result
            missing = set(fiber._plugin.provides) - ctx._provided.keys()
            if missing:
                raise ValueError("setup did not provide " + ", ".join(sorted(map(str, missing))))
        except BaseException as error:
            fiber._state = FiberState.STOPPING
            errors = await self._stop([fiber])
            for cleanup_error in errors:
                error.add_note(f"setup rollback also failed: {cleanup_error!r}")
            fiber._state = FiberState.FAILED
            fiber._error = error
            if not isinstance(error, Exception):
                raise
        else:
            self.services.update({key: (fiber, value) for key, value in ctx._provided.items()})
            ctx._provided.clear()
            fiber._state = FiberState.ACTIVE

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
            affected = {fiber.id}
            order = self._order()
            for instance_id in order:
                requirements = self.fibers[instance_id]._plugin.requires
                if any(self.providers.get(key) in affected for key in requirements):
                    affected.add(instance_id)
            dependents = [self.fibers[instance_id] for instance_id in reversed(order) if instance_id in affected]
            errors = await self._stop([item for item in dependents if item.state is FiberState.ACTIVE])
            self._forget(fiber)
            for item in dependents:
                if item is not fiber:
                    item._state = FiberState.PENDING
                    item._ctx = None
                    item._error = None
            if errors:
                raise BaseExceptionGroup(f"failed to stop {fiber.id!r}", errors)

        await self._change(operation)

    async def close(self) -> None:
        async def operation() -> None:
            fibers = [self.fibers[instance_id] for instance_id in reversed(self._order())]
            errors = await self._stop([fiber for fiber in fibers if fiber.state is FiberState.ACTIVE])
            for fiber in fibers:
                self._forget(fiber)
            self.closed = True
            if errors:
                raise BaseExceptionGroup("plugin shutdown failed", errors)

        await self._change(operation)
