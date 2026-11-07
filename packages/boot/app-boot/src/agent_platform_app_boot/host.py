"""Process-level plugin runtime owner.

The runtime itself provides the native plugin catalog; this module only loads
the composition, starts the runtime and exposes it to the app entry points.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_platform_plugin_runtime import PluginRuntime
from agent_platform_plugin_sdk import TOOLS

from .config import load_config

logger = logging.getLogger(__name__)


@dataclass
class PluginHost:
    runtime: PluginRuntime
    tools: object

    @property
    def plugins(self):
        return self.runtime.plugins

    @property
    def unified(self):
        from agent_platform_tool_host import UNIFIED_TOOLS

        return self.runtime.require(UNIFIED_TOOLS)

    async def aclose(self) -> None:
        await self.runtime.aclose()


_host: PluginHost | None = None


def get_plugin_host() -> PluginHost | None:
    return _host


async def init_plugin_host(catalog: object | None = None) -> PluginHost:
    """Start the composed runtime once per process."""
    global _host
    if _host is not None:
        return _host

    config = load_config()
    runtime = PluginRuntime(config, catalog=catalog)
    try:
        await runtime.start()
        tools = runtime.require(TOOLS)
    except BaseException:
        await runtime.aclose()
        raise

    _host = PluginHost(runtime=runtime, tools=tools)
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
