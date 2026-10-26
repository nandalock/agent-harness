"""Owned embedded HTTP servers; the outer API server owns OS signals."""
import asyncio
from contextlib import nullcontext

import uvicorn


class EmbeddedServer(uvicorn.Server):
    def capture_signals(self):
        return nullcontext()

    def install_signal_handlers(self):
        # Compatibility with uvicorn releases before capture_signals().
        pass


async def start_server(app, port):
    server = EmbeddedServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError(f"Embedded MCP server failed on port {port}")
                await asyncio.sleep(0.05)
    except BaseException:
        server.should_exit = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    return server, task


async def close_servers(servers):
    for server, task in reversed(servers):
        server.should_exit = True
        try:
            async with asyncio.timeout(10):
                await asyncio.shield(task)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
