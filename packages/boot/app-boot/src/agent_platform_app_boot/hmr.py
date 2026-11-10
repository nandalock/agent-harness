"""Watch the composed profile configuration on the lifecycle task."""

import asyncio
import logging

from agent_platform_plugin_runtime import PluginLoader
from agent_platform_plugin_sdk import ServiceKey

from .config import load_config

logger = logging.getLogger(__name__)


async def watch_config(runtime: PluginLoader, stop: asyncio.Event, pinned: frozenset[ServiceKey]) -> None:
    previous = runtime.config
    last_error: str | None = None
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
            return
        except TimeoutError:
            pass
        try:
            candidate = await asyncio.to_thread(load_config)
        except Exception as exc:
            if str(exc) != last_error:
                logger.warning("Plugin configuration update rejected: %s", exc)
                last_error = str(exc)
            continue
        last_error = None
        if candidate == previous:
            continue
        previous = candidate
        try:
            changed = await runtime.reconfigure(candidate, pinned=pinned)
        except Exception:
            logger.exception("Plugin configuration update failed")
        else:
            logger.info("Plugin configuration reloaded: %s", ", ".join(changed) or "no plugin changes")
