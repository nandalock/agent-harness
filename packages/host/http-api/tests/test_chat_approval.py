import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from httpx import ASGITransport, AsyncClient

from agent_platform_agent_entry import AgentGateway
from agent_platform_agent_runtime import AgentReply
from agent_platform_chat import ChatService
from agent_platform_http_api import create_app
from agent_platform_plugin_runtime import PluginLoader
from agent_platform_plugin_sdk import APPROVAL, ApprovalRequest
from agent_platform_user_approval import APPROVAL_INBOX


class ChatApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_sse_stores_reply_before_emitting_done(self):
        entry = AgentGateway(
            SimpleNamespace(get_definition=AsyncMock(return_value={"name": "Test"})),
            SimpleNamespace(reply=AsyncMock(return_value=AgentReply("answer", tier="test"))),
            None, None, None,
        )
        store = Mock()
        store.create_conversation.return_value = SimpleNamespace(id=7, session_id=None)
        chat = ChatService(entry, store)
        self.addAsyncCleanup(entry.aclose)
        self.addAsyncCleanup(chat.aclose)
        async with AsyncClient(
            transport=ASGITransport(app=create_app(entry=entry, chat=chat)), base_url="http://test",
        ) as client:
            result = await client.post("/api/agents/a/chat/stream", json={"question": "hello"},
                                       headers={"X-Tenant-ID": "1"})
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("text/event-stream")
        done = json.loads(result.text.removeprefix("data: "))
        assert done["type"] == "done" and done["conversation_id"] == 7
        assert done["answer"] == store.save_reply.call_args.args[3].content
        assert chat.attach(1, "a", "conversation:7") is None

    async def test_first_turn_can_reconnect_under_its_durable_session_id(self):
        ready = asyncio.Event()

        async def reply(key, definition, tenant_id, question, **options):
            await options["on_session_ready"]("durable")
            await options["on_event"]({"type": "session/ready", "session_id": "durable"})
            ready.set()
            await options["cancel"].wait()
            return AgentReply("partial", session_id="durable")

        entry = AgentGateway(
            SimpleNamespace(get_definition=AsyncMock(return_value={"name": "Test"})),
            SimpleNamespace(reply=reply), None, None, None,
        )
        store = Mock()
        store.create_conversation.return_value = SimpleNamespace(id=7, session_id=None)
        chat = ChatService(entry, store)
        self.addAsyncCleanup(entry.aclose)
        self.addAsyncCleanup(chat.aclose)
        first = await chat.start_stream(1, "a", "hello")
        await asyncio.wait_for(ready.wait(), 2)
        first.detach()
        assert chat.attach(2, "a", "durable", 7) is None
        view = chat.attach(1, "a", "durable", 7)
        assert view is not None and view.snapshot["session_id"] == "durable"
        assert chat.cancel(1, "a", "durable")
        done = await asyncio.wait_for(view.events.get(), 2)
        assert done["type"] == "done" and done["answer"] == "partial"
        store.save_reply.assert_called_once()
        assert chat.attach(1, "a", "conversation:7") is None
        assert chat.attach(1, "a", "durable") is None

    async def test_approval_http_uses_the_same_inbox_as_tools_and_close_releases_waiters(self):
        runtime = PluginLoader({"plugins": [{"id": "approval", "name": "agent-platform.user-approval", "use": "agent_platform_user_approval:UserApprovalPlugin"}]})
        await runtime.start()
        self.addAsyncCleanup(runtime.aclose)
        approval = runtime.require(APPROVAL)
        inbox = runtime.require(APPROVAL_INBOX)
        self.assertIs(approval, inbox)
        pending = asyncio.create_task(approval.request(ApprovalRequest("ask", "test")))
        await asyncio.sleep(0)
        async with AsyncClient(
            transport=ASGITransport(app=create_app(approval=inbox)), base_url="http://test",
        ) as client:
            result = await client.get("/api/agents/approvals")
            assert [item["approval_id"] for item in result.json()] == ["ask"]
            result = await client.post("/api/agents/approvals/ask", json={"decision": "allow-once"})
            assert result.status_code == 200 and await pending == "allowed-once"
            result = await client.post("/api/agents/approvals/ask", json={"decision": "allow-once"})
            assert result.status_code == 404

        unresolved = asyncio.create_task(approval.request(ApprovalRequest("shutdown", "test")))
        await asyncio.sleep(0)
        await runtime.aclose()
        assert await asyncio.wait_for(unresolved, 2) == "unavailable"
        assert inbox.pending() == []
