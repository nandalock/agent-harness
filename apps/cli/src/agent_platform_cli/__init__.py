"""Command-line entry: headless agent turns and the local server."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from agent_platform_agent_entry import AGENT_ENTRY, RequestContext
from agent_platform_app_boot import load_config
from agent_platform_plugin_runtime import PluginRuntime
from agent_platform_plugin_sdk import PluginConfiguration


def _load_local_env() -> None:
    path = Path(os.environ.get("AGENT_PLATFORM_ENV", Path.cwd() / "config" / "local.env"))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def run_agent(agent_key: str, question: str, tenant_id: int) -> str:
    config = load_config()
    interactive = {"agent-platform.http-api", "agent-platform.user-approval"}
    plugins = tuple(entry for entry in config.plugins if entry.name not in interactive)
    runtime = PluginRuntime(PluginConfiguration(plugins=plugins))
    await runtime.start()
    try:
        reply = await runtime.require(AGENT_ENTRY).chat(
            RequestContext(tenant_id=tenant_id, agent_key=agent_key, channel="headless"),
            question,
        )
        return reply.answer
    finally:
        await runtime.aclose()


def serve() -> int:
    import uvicorn

    uvicorn.run(
        "agent_platform_server:app",
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8000")),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    run_parser = sub.add_parser("run", help="run one agent turn")
    run_parser.add_argument("question", nargs="?", default="你好")
    run_parser.add_argument("--agent", default="default")
    run_parser.add_argument("--tenant-id", type=int, default=1)
    serve_parser = sub.add_parser("serve", help="run the HTTP server")
    serve_parser.set_defaults(command="serve")
    parser.add_argument("question", nargs="?", default="你好")
    parser.add_argument("--agent", default="default")
    parser.add_argument("--tenant-id", type=int, default=1)
    args = parser.parse_args()

    if args.command == "serve":
        return serve()

    _load_local_env()
    answer = asyncio.run(run_agent(args.agent, args.question, args.tenant_id))
    print(answer)
    return 0
