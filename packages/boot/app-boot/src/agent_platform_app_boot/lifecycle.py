"""Run Cordis startup, configuration reload, and shutdown on one task."""

import asyncio
import os
from functools import partial
from typing import Any

from agent_platform_plugin_sdk import TOOLS, ServiceKey
from minidsh_cordis_plugin_hmr import Hmr
from minidsh_cordis_plugin_loader import Loader

from .config import load_config


async def run_lifecycle(
    runtime: Loader,
    ready: asyncio.Future[object],
    stop: asyncio.Event,
    *,
    pinned: frozenset[ServiceKey[Any]],
) -> None:
    try:
        await runtime.start()
        ready.set_result(runtime.require(TOOLS))
        if os.environ.get("MINIDSH_CONFIG_RELOAD", "true").lower() in ("false", "0", "no"):
            await stop.wait()
        else:
            hmr = Hmr(load_config, partial(runtime.reconfigure, pinned=pinned | {TOOLS}))
            await hmr.watch_config(initial=runtime.config, stop=stop)
    except BaseException as error:
        if not ready.done():
            ready.set_exception(error)
        raise
    finally:
        await runtime.aclose()
