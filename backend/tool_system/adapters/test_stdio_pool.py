"""有状态 MCP 连接复用、作用域隔离与取消测试。"""
import asyncio
import sys
from dataclasses import replace
import unittest
from unittest.mock import patch

from backend.tool_system.adapters import stdio_pool as pool
from backend.tool_system.adapters.mcp import McpClient as RealClient
from backend.tool_system.context import ToolContext


class FakeClient:
    instances = []
    def __init__(self, **config):
        self.read = False
        self.closed = False
        self.instances.append(self)
    async def connect(self):
        await asyncio.sleep(0)
    async def disconnect(self):
        self.closed = True
    async def call(self, name, args):
        if name == "read":
            self.read = True
        if name == "wait":
            await asyncio.Event().wait()
        return [{"read_before_edit": self.read}]


class StdioPoolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeClient.instances = []
        self.mock = patch.object(pool, "McpClient", FakeClient)
        self.mock.start()
        self.config = {"command": "test", "args": [], "env": {}}
        self.context = ToolContext(session_id="one", tenant_id=1)

    async def asyncTearDown(self):
        await pool.close_stdio_sessions()
        self.mock.stop()

    async def test_read_then_edit_preserves_state_and_shutdown_closes(self):
        await pool.call_stdio_session(self.config, self.context, "read", {})
        result = await pool.call_stdio_session(self.config, self.context, "edit", {})
        self.assertTrue(result[0]["read_before_edit"])
        self.assertEqual(len(FakeClient.instances), 1)
        await pool.close_stdio_sessions()
        self.assertTrue(FakeClient.instances[0].closed)

    async def test_tenant_session_and_config_are_isolated(self):
        await pool.call_stdio_session(self.config, self.context, "read", {})
        for context, config in ((replace(self.context, tenant_id=2), self.config),
                                (replace(self.context, session_id="two"), self.config),
                                (self.context, {**self.config, "args": ["changed"]})):
            result = await pool.call_stdio_session(config, context, "edit", {})
            self.assertFalse(result[0]["read_before_edit"])

    async def test_cancel_terminates_process_and_fails_queued_work(self):
        call = asyncio.create_task(pool.call_stdio_session(self.config, self.context, "wait", {}))
        await asyncio.sleep(0.02)
        queued = asyncio.create_task(pool.call_stdio_session(self.config, self.context, "edit", {}))
        await asyncio.sleep(0)
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        with self.assertRaisesRegex(RuntimeError, "关闭"):
            await queued
        self.assertTrue(FakeClient.instances[0].closed)
        await asyncio.sleep(0)
        result = await pool.call_stdio_session(self.config, self.context, "edit", {})
        self.assertFalse(result[0]["read_before_edit"])

    async def test_stateful_calls_require_scope(self):
        with self.assertRaises(ValueError):
            await pool.call_stdio_session(self.config, None, "read", {})

    async def test_real_mcp_process_keeps_state_and_closes_in_owner_task(self):
        config = {"command": sys.executable, "args": ["-m", "backend.tool_system.adapters.stdio_test_server"], "env": {}}
        with patch.object(pool, "McpClient", RealClient):
            await pool.call_stdio_session(config, self.context, "remember", {"value": "same-process"})
            result = await pool.call_stdio_session(config, self.context, "recall", {})
            self.assertEqual(result, [{"value": "same-process"}])
            other = await pool.call_stdio_session(config, replace(self.context, session_id="other"), "recall", {})
            self.assertEqual(other, [{"value": None}])
            await pool.close_stdio_sessions()


if __name__ == "__main__":
    unittest.main()
