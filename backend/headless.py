"""No-HTTP entry point: run one agent turn through the plugin runtime.

Usage:
    python -m backend.headless "你好"
    python -m backend.headless --agent default "你好"
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from agent_platform_agent_entry import AGENT_ENTRY, RequestContext
from agent_platform_plugin_runtime import PluginRuntime, load_yaml_config
from agent_platform_plugin_sdk import PluginConfiguration

from backend.plugin_host import _compose_plugins, _resolve_config_path


def _load_local_env() -> None:
    path = Path(__file__).resolve().parent.parent / "config" / "local.env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def run(agent_key: str, question: str, tenant_id: int) -> str:
    path = _resolve_config_path()
    config = load_yaml_config(path) if path is not None else PluginConfiguration()
    config = _compose_plugins(config)
    # Deliberately exclude the HTTP/API plugin: this entry owns no web server.
    interactive_plugins = {"agent-platform.http-api", "agent-platform.user-approval"}
    plugins = tuple(entry for entry in config.plugins if entry.name not in interactive_plugins)
    runtime = PluginRuntime(PluginConfiguration(plugins=plugins))
    await runtime.start()
    try:
        reply = await runtime.require(AGENT_ENTRY).chat(
            RequestContext(tenant_id=tenant_id, agent_key=agent_key, channel="headless"), question,
        )
        return reply.answer
    finally:
        await runtime.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="你好")
    parser.add_argument("--agent", default="default")
    parser.add_argument("--tenant-id", type=int, default=1)
    args = parser.parse_args()
    _load_local_env()
    answer = asyncio.run(run(args.agent, args.question, args.tenant_id))
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
