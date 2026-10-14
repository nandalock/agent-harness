"""有状态 stdio 服务由独立任务持有；同租户、会话和配置内复用进程。"""
import asyncio
import hashlib
import json
import os

from backend.tool_system.adapters.mcp import McpClient

_sessions = {}


class StdioSession:
    """连接的建立、调用与关闭均在同一任务中，保持 SDK 上下文的任务归属。"""

    def __init__(self, config, idle_seconds):
        self.config = config
        self.idle_seconds = idle_seconds
        self.queue = asyncio.Queue()
        self.task = asyncio.create_task(self._serve())

    async def call(self, name, args):
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((name, args, future))
        try:
            return await future
        except asyncio.CancelledError:
            # 超时或取消必须终止在途操作；不能重试可能已经产生副作用的调用。
            await self.close()
            raise

    async def _serve(self):
        client = McpClient(transport="stdio", command=self.config["command"],
                           args=self.config.get("args", []), env=self.config.get("env", {}))
        active = None
        failure = RuntimeError("MCP 会话连接已关闭，请重新执行读取步骤")
        try:
            await client.connect()
            while True:
                try:
                    name, args, active = await asyncio.wait_for(self.queue.get(), self.idle_seconds)
                except asyncio.TimeoutError:
                    break
                if active.cancelled():
                    active = None
                    continue
                result = await client.call(name, args)
                if not active.done():
                    active.set_result(result)
                active = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
        finally:
            if active is not None and not active.done():
                active.set_exception(failure)
            while not self.queue.empty():
                _, _, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(failure)
            await client.disconnect()

    async def close(self):
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def call_stdio_session(config, context, name, args):
    if context is None or context.tenant_id is None or not context.session_id:
        raise ValueError("有状态 MCP 调用需要租户和会话上下文")
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    key = (id(asyncio.get_running_loop()), context.tenant_id, context.session_id, fingerprint)
    session = _sessions.get(key)
    if session is None or session.task.done():
        idle = float(os.environ.get("MCP_SESSION_IDLE_SECONDS", "1800"))
        if idle <= 0:
            raise ValueError("MCP_SESSION_IDLE_SECONDS 必须大于零")
        session = StdioSession(config, idle)
        _sessions[key] = session
        session.task.add_done_callback(lambda task: _sessions.pop(key, None) if _sessions.get(key) is session else None)
    return await session.call(name, args)


async def close_stdio_sessions():
    sessions = list(_sessions.values())
    _sessions.clear()
    await asyncio.gather(*(session.close() for session in sessions))
