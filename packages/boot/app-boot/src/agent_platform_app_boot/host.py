"""Process-level plugin runtime owner.

The runtime itself provides the native plugin catalog; this module only loads
the composition, starts the runtime and exposes it to the app entry points.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from agent_platform_plugin_runtime import PluginLoader
from agent_platform_plugin_sdk import TOOLS, ServiceKey

from .config import load_config
from .hmr import watch_config

logger = logging.getLogger(__name__)


@dataclass
class PluginHost:
    runtime: PluginLoader
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
    catalog: object | None = None, *, pinned: frozenset[ServiceKey] = frozenset(),
) -> PluginHost:
    """Start the composed runtime once per process."""
    global _host
    if _host is not None:
        return _host

    config = load_config()
    runtime = PluginLoader(config, catalog=catalog)
    stop = asyncio.Event()
    ready: asyncio.Future[object] = asyncio.get_running_loop().create_future()

    async def lifecycle() -> None:
        try:
            await runtime.start()
            ready.set_result(runtime.require(TOOLS))
            if os.environ.get("MINIDSH_CONFIG_RELOAD", "true").lower() in ("false", "0", "no"):
                await stop.wait()
            else:
                await watch_config(runtime, stop, pinned | {TOOLS})
        except BaseException as error:
            if not ready.done():
                ready.set_exception(error)
            raise
        finally:
            await runtime.aclose()

    task = asyncio.create_task(lifecycle(), name="minidsh-plugin-lifecycle")
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
