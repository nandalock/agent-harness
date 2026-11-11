"""Typed events and dispatch for one Cordis root."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from inspect import isawaitable, iscoroutine
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from .effects import Registration
from .fiber import Fiber, FiberState

if TYPE_CHECKING:
    from .context import Context

T = TypeVar("T")
_SKIPPED = object()


@dataclass(frozen=True)
class EventKey(Generic[T]):
    name: str


type Handler[T] = Callable[[T], Awaitable[T] | T]
type Middleware[T, R] = Callable[[T, Callable[[], Awaitable[R]]], Awaitable[R] | R]


@dataclass(eq=False, slots=True)
class Listener:
    fiber: Fiber
    handler: Callable[..., object]
    active: bool = True
    once: bool = False
    middleware: bool = False
    _registration: Registration | None = None


class EventsService:
    def __init__(self, in_callback: ContextVar[bool]) -> None:
        self._listeners: dict[EventKey[Any], list[Listener]] = {}
        self._in_callback = in_callback

    def on[T](self, fiber: Fiber, event: EventKey[T], handler: Callable[[T], object]) -> Registration:
        return self._register(event, Listener(fiber, handler))

    def once[T](self, fiber: Fiber, event: EventKey[T], handler: Callable[[T], object]) -> Registration:
        return self._register(event, Listener(fiber, handler, once=True))

    def on_middleware[T, R](
        self, fiber: Fiber, event: EventKey[T], handler: Middleware[T, R],
    ) -> Registration:
        return self._register(event, Listener(fiber, handler, middleware=True))

    def _register(self, event: EventKey[Any], listener: Listener) -> Registration:
        fiber = listener.fiber
        if fiber._registry.events is not self or fiber.state not in (FiberState.STARTING, FiberState.ACTIVE):
            raise RuntimeError("listener registration requires a starting or active plugin in this context")
        listeners = self._listeners.setdefault(event, [])

        def remove() -> None:
            listener.active = False
            listeners.remove(listener)
            if not listeners:
                del self._listeners[event]
            effects = fiber._effects
            if registration in effects:
                effects.remove(registration)

        registration = Registration(remove)
        listener._registration = registration
        listeners.append(listener)
        fiber._effects.append(registration)
        return registration

    def _snapshot(
        self, ctx: "Context", event: EventKey[Any], *, middleware: bool = False,
    ) -> tuple[Listener, ...]:
        ctx._ensure_open()
        return tuple(listener for listener in self._listeners.get(event, ()) if listener.middleware == middleware)

    def _claim(self, ctx: "Context", listener: Listener) -> bool:
        ctx._ensure_open()
        if not listener.active or listener.fiber.state is not FiberState.ACTIVE:
            return False
        if listener.once:
            assert listener._registration is not None
            listener._registration._release()
        return True

    @contextmanager
    def _calling(self, fiber: Fiber) -> Iterator[None]:
        token = self._in_callback.set(True)
        fiber._enter_call()
        try:
            yield
        finally:
            fiber._leave_call()
            self._in_callback.reset(token)

    def _invoke_sync(self, ctx: "Context", listener: Listener, value: object) -> object:
        if not self._claim(ctx, listener):
            return _SKIPPED
        with self._calling(listener.fiber):
            result = listener.handler(value)
            if isawaitable(result):
                if iscoroutine(result):
                    result.close()
                elif isinstance(result, asyncio.Future) and not result.done():
                    fiber = listener.fiber
                    fiber._enter_call()
                    result.add_done_callback(lambda _: fiber._leave_call())
                raise TypeError("emit() and bail() require synchronous listeners; use parallel() or serial()")
            return result

    async def _invoke(self, ctx: "Context", listener: Listener, *args: object) -> object:
        if not self._claim(ctx, listener):
            return _SKIPPED
        with self._calling(listener.fiber):
            result = listener.handler(*args)
            return await result if isawaitable(result) else result

    def emit[T](self, ctx: "Context", event: EventKey[T], value: T) -> None:
        for listener in self._snapshot(ctx, event):
            self._invoke_sync(ctx, listener, value)

    async def parallel[T](self, ctx: "Context", event: EventKey[T], value: T) -> None:
        async def notify(listener: Listener) -> None:
            await self._invoke(ctx, listener, value)

        results = await asyncio.gather(
            *(notify(listener) for listener in self._snapshot(ctx, event)), return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise BaseExceptionGroup(f"event {event.name!r} failed", errors)

    async def serial[T](self, ctx: "Context", event: EventKey[T], value: T) -> object:
        for listener in self._snapshot(ctx, event):
            result = await self._invoke(ctx, listener, value)
            if result is not _SKIPPED and result is not None and result is not False:
                return result
        return None

    def bail[T](self, ctx: "Context", event: EventKey[T], value: T) -> object:
        for listener in self._snapshot(ctx, event):
            result = self._invoke_sync(ctx, listener, value)
            if result is not _SKIPPED and result is not None and result is not False:
                return result
        return None

    async def waterfall[T](self, ctx: "Context", event: EventKey[T], value: T) -> T:
        for listener in self._snapshot(ctx, event):
            result = await self._invoke(ctx, listener, value)
            if result is not _SKIPPED:
                value = cast(T, result)
        return value

    async def waterfall_next[T, R](
        self, ctx: "Context", event: EventKey[T], value: T, terminal: Callable[[T], Awaitable[R] | R],
    ) -> R:
        listeners = self._snapshot(ctx, event, middleware=True)
        owner = asyncio.current_task()

        async def run(index: int) -> R:
            while index < len(listeners):
                listener = listeners[index]
                index += 1
                called = False
                active = True

                async def next_step() -> R:
                    nonlocal called
                    if not active or asyncio.current_task() is not owner:
                        raise RuntimeError("next() must be awaited by its middleware")
                    if called:
                        raise RuntimeError("next() may only be called once per middleware")
                    called = True
                    return await run(index)

                try:
                    result = await self._invoke(ctx, listener, value, next_step)
                finally:
                    active = False
                if result is not _SKIPPED:
                    return cast(R, result)
            ctx._ensure_open()
            final = terminal(value)
            return await final if isawaitable(final) else final

        return await run(0)
