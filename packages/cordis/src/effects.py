"""Reversible registrations owned by one activation."""

from collections.abc import Awaitable, Callable
from inspect import isawaitable

Cleanup = Callable[[], Awaitable[None] | None]


class Registration:
    def __init__(self, cleanup: Cleanup) -> None:
        self._cleanup: Cleanup | None = cleanup

    @property
    def closed(self) -> bool:
        return self._cleanup is None

    async def aclose(self) -> None:
        cleanup, self._cleanup = self._cleanup, None
        if cleanup is not None:
            result = cleanup()
            if isawaitable(result):
                await result


async def unwind(registrations: list[Registration]) -> list[BaseException]:
    errors = []
    while registrations:
        try:
            await registrations.pop().aclose()
        except BaseException as error:
            errors.append(error)
    return errors
