"""Process-level plugin runtime owner.

The runtime itself provides the native plugin catalog; this module only loads
the composition, starts the runtime and exposes it to the app entry points.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from agent_platform_plugin_sdk import ServiceKey
from minidsh_cordis_plugin_loader import Loader, PluginCatalog

from .config import load_config
from .lifecycle import run_lifecycle

logger = logging.getLogger(__name__)


@dataclass
class PluginHost:
    runtime: Loader
    tools: object
    _stop: asyncio.Event
    _lifecycle: asyncio.Task[None]

    @property
    def plugins(self):
        return self.runtime.plugins

    @property
    def unified(self):
        from agent_platform_tool_host import UNIFIED_TOOLS

        return self.runtime.require(UNIFIED_TOOLS)

    async def aclose(self) -> None:
        self._stop.set()
        await asyncio.shield(self._lifecycle)


_host: PluginHost | None = None


def get_plugin_host() -> PluginHost | None:
    return _host


async def init_plugin_host(
    catalog: PluginCatalog | None = None, *, pinned: frozenset[ServiceKey[Any]] = frozenset(),
) -> PluginHost:
    """Start the composed runtime once per process."""
    global _host
    if _host is not None:
        return _host

    config = load_config()
    runtime = Loader(config, catalog=catalog)
    stop = asyncio.Event()
    ready: asyncio.Future[object] = asyncio.get_running_loop().create_future()

    task = asyncio.create_task(
        run_lifecycle(runtime, ready, stop, pinned=pinned),
        name="minidsh-plugin-lifecycle",
    )
    try:
        tools = await asyncio.shield(ready)
    except BaseException:
        stop.set()
        if not ready.done():
            ready.cancel()
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise

    _host = PluginHost(runtime, tools, stop, task)
    logger.info(
        "插件运行时已启动，插件: %s",
        [(plugin.instance_id, plugin.name) for plugin in runtime.plugins],
    )
    return _host


async def close_plugin_host() -> None:
    global _host
    host, _host = _host, None
    if host is not None:
        await host.aclose()
