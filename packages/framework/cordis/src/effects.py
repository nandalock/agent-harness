"""Reversible registrations owned by one activation."""

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Protocol

Cleanup = Callable[[], Awaitable[None] | None]


class Closeable(Protocol):
    async def aclose(self) -> None: ...


class Registration:
    def __init__(self, cleanup: Cleanup, label: str | None = None) -> None:
        self._cleanup: Cleanup | None = cleanup
        self._label = label

    @property
    def closed(self) -> bool:
        return self._cleanup is None

    def _release(self) -> Awaitable[None] | None:
        cleanup, self._cleanup = self._cleanup, None
        if cleanup is not None:
            return cleanup()
        return None

    async def aclose(self) -> None:
        try:
            result = self._release()
            if isawaitable(result):
                await result
        except BaseException as exc:
            if self._label is not None:
                exc.add_note(f"plugin cleanup callback {self._label!r} failed")
            raise


async def unwind(registrations: list[Registration]) -> list[BaseException]:
    errors = []
    while registrations:
        try:
            await registrations.pop().aclose()
        except BaseException as error:
            errors.append(error)
    return errors
