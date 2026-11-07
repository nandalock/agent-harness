"""Own reply tasks through checkpoint cleanup; never fall back to a host runner."""
import asyncio
from agent_platform_plugin_sdk import ServiceClosedError
from .runtime import RuntimeAgent


class RuntimeService:
    def __init__(self, ctx, extensions):
        self.ctx = ctx
        self.extensions = extensions
        self._tasks = set()
        self._closed = False
        self._closing = None

    async def _run(self, operation):
        if self._closed:
            raise ServiceClosedError("agent runtime is closed")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            return await operation()
        finally:
            self._tasks.discard(task)

    async def reply(self, key, definition, *args, **options):
        return await self._run(lambda: RuntimeAgent(self.ctx, self.extensions, key, definition).reply(*args, **options))

    async def plain(self, key, messages, config):
        return await self._run(lambda: RuntimeAgent(self.ctx, self.extensions, key, {})._call_llm_plain(messages, config))

    async def aclose(self):
        if self._closing is None:
            self._closed = True
            tasks = tuple(task for task in self._tasks if task is not asyncio.current_task())
            async def close():
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            self._closing = asyncio.create_task(close())
        cancelled = False
        while not self._closing.done():
            try:
                await asyncio.shield(self._closing)
            except asyncio.CancelledError:
                cancelled = True
        self._closing.result()
        if cancelled:
            raise asyncio.CancelledError()
