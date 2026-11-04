"""Optional single-track runtime singleton.

This module deliberately imports no plugin SDK, so fallback paths can ask
"is the unified runtime assembled?" even when the plugin packages are absent.
"""
from typing import Any

_unified: Any | None = None


def set_unified_tools(runtime: Any) -> None:
    global _unified
    _unified = runtime


def get_unified_tools_optional() -> Any | None:
    return _unified


def get_unified_tools() -> Any:
    if _unified is None:
        raise RuntimeError("单轨工具运行时未装配")
    return _unified


async def close_unified_tools() -> None:
    global _unified
    runtime, _unified = _unified, None
    if runtime is not None:
        await runtime.aclose()
