"""Watch configuration and apply changes on the caller's lifecycle task."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__package__)


class Hmr[T]:
    """Poll a configuration source and apply changes on the caller's task."""

    def __init__(
        self,
        load: Callable[[], T],
        apply: Callable[[T], Awaitable[tuple[str, ...]]],
        *,
        interval: float = 1.0,
    ) -> None:
        self._load = load
        self._apply = apply
        self._interval = interval

    async def watch_config(self, *, initial: T, stop: asyncio.Event) -> None:
        previous = initial
        last_error: str | None = None
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
                return
            except TimeoutError:
                pass
            try:
                candidate = await asyncio.to_thread(self._load)
            except Exception as exc:
                if str(exc) != last_error:
                    logger.warning("Plugin configuration update rejected: %s", exc)
                    last_error = str(exc)
                continue
            last_error = None
            if stop.is_set() or candidate == previous:
                continue
            previous = candidate
            try:
                changed = await self._apply(candidate)
            except Exception:
                logger.exception("Plugin configuration update failed")
            else:
                logger.info("Plugin configuration reloaded: %s", ", ".join(changed) or "no plugin changes")
