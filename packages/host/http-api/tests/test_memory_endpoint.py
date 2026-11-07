import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from agent_platform_chat import CHAT
from agent_platform_http_api import create_app
from agent_platform_memory import MEMORY
from agent_platform_plugin_runtime import PluginRuntime
from agent_platform_plugin_sdk import AGENTS, DATABASE, ServiceClosedError


class MemoryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database = MagicMock()
        conn = database.get_conn.return_value.__enter__.return_value
        self.cursor = conn.cursor.return_value.__enter__.return_value
        self.agents = SimpleNamespace(get_config=AsyncMock(return_value={
            "api_key": "test", "model": "selected-model",
        }))
        self.chat = MagicMock()
        self.runtime = PluginRuntime(
            {"plugins": [{"id": "memory", "name": "agent-platform.memory"}]},
            host_services={DATABASE: database, AGENTS: self.agents, CHAT: SimpleNamespace(store=self.chat)},
        )
        await self.runtime.start()
        self.addAsyncCleanup(self.runtime.aclose)
        self.memory = self.runtime.require(MEMORY)

    async def test_debug_preserves_preview_and_uses_injected_services(self):
        self.chat.get_conversation.return_value = SimpleNamespace(id=12)
        self.chat.list_messages.return_value = [
            SimpleNamespace(role="customer", content="earlier details " * 500),
            SimpleNamespace(role="agent", content="recent reply"),
        ]
        self.cursor.fetchone.side_effect = [
            {"config": {"max_tokens": 100}},
            {"user_id": "u", "facts": ["prefers Markdown"], "updated_at": None},
        ]
        llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
            SimpleNamespace(content="compressed summary"),
            SimpleNamespace(content='{"facts": ["new preview fact"]}'),
        ]))
        async with AsyncClient(
            transport=ASGITransport(app=create_app(memory=self.memory)), base_url="http://test",
        ) as http:
            with patch("agent_platform_memory.service.ChatOpenAI", return_value=llm) as build_model:
                response = await http.post(
                    "/api/memory/debug/run",
                    json={"conversation_id": 12, "agent_key": "a", "user_id": "u"},
                    headers={"X-Tenant-ID": "7"},
                )
        assert response.status_code == 200 and response.json()["ok"]
        result = response.json()["result"]
        assert result["summary"] == "compressed summary"
        assert "prefers Markdown" in result["profile"]
        assert result["intermediate"]["profile_facts"] == ["new preview fact"]
        assert "recent reply" in result["recent"]
        assert build_model.call_args.kwargs["model"] == "selected-model"
        self.chat.get_conversation.assert_called_once_with(7, 12)
        self.agents.get_config.assert_awaited_once_with("a")
        assert len(self.cursor.execute.call_args_list) == 2
        assert all(call.args[0].startswith("SELECT") for call in self.cursor.execute.call_args_list)

    async def test_profile_routes_keep_tenant_scope_and_can_be_disabled(self):
        row = {"user_id": "u", "facts": ["prefers Markdown"], "updated_at": None}
        self.cursor.fetchall.return_value = [row]
        self.cursor.fetchone.side_effect = [row, None]
        async with AsyncClient(
            transport=ASGITransport(app=create_app(memory=self.memory)), base_url="http://test",
            headers={"X-Tenant-ID": "7"},
        ) as http:
            listing = await http.get("/api/memory/users")
            assert listing.json()[0]["facts_count"] == 1
            detail = await http.get("/api/memory/users/u")
            assert detail.json() == row
            missing = await http.get("/api/memory/users/u", headers={"X-Tenant-ID": "8"})
            assert missing.status_code == 404
            assert self.cursor.execute.call_args.args[1] == (8, "u")

        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test",
        ) as http:
            assert (await http.get("/api/memory/users", headers={"X-Tenant-ID": "7"})).status_code == 404

    async def test_runtime_close_cancels_background_extraction(self):
        started = asyncio.Event()

        async def invoke(messages):
            started.set()
            await asyncio.Future()

        first = self.memory.create_context()
        second = self.memory.create_context()
        assert first is not second
        llm = SimpleNamespace(ainvoke=invoke)
        messages = [{"role": "customer", "content": "Please use Markdown"}]
        task = first.summarizer.schedule(llm, messages, 7, "u")
        await asyncio.wait_for(started.wait(), timeout=2)
        await self.runtime.aclose()
        assert task.cancelled()
        with self.assertRaises(ServiceClosedError):
            second.summarizer.schedule(llm, messages, 7, "u")
