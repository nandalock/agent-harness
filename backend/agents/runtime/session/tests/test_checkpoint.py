"""Durability gates, cancellation, and recovery without network or model APIs."""
import asyncio
import copy
import threading

import pytest

from backend.agents.runtime.agent_runtime import AgentRuntime
from backend.agents.runtime.llm.types import LlmResponse, StreamChunk
from backend.agents.runtime.loop.agent_loop import AgentLoop
from backend.agents.runtime.loop.registry import RunConflict
from backend.agents.runtime.session.checkpoint import CheckpointError, SessionCheckpoint
from backend.agents.runtime.session.events import TURN_START, TURN_END, TOOL_CALL, TOOL_RESULT
from backend.agents.runtime.session.persistence.base import SessionPersistence, set_session_persistence
from backend.agents.runtime.session.recovery import RecoveryError, prepare_session, recovery_status
from backend.agents.runtime.session.session import Session
from backend.agents.runtime.session import store as store_module


class MemoryPersistence(SessionPersistence):
    durable = True

    def __init__(self):
        self.headers, self.logs, self.pending = {}, {}, {}
        self.fail_type = None
        self.gate_type = None
        self.waiting = threading.Event()
        self.release = threading.Event()

    def create(self, sid, header):
        self.headers.setdefault(sid, copy.deepcopy(header))
        self.logs.setdefault(sid, [])

    def append_events(self, sid, events):
        floor = self.logs[sid][-1].seq if self.logs[sid] else 0
        self.pending[sid] = copy.deepcopy([e for e in events if e.seq > floor])

    def flush(self, session_id=None):
        for sid in [session_id] if session_id else list(self.pending):
            events = self.pending.get(sid, [])
            if any(e.type == self.fail_type for e in events):
                raise OSError("simulated unavailable storage")
            if any(e.type == self.gate_type for e in events):
                self.waiting.set()
                if not self.release.wait(3):
                    raise TimeoutError("test barrier was not released")
                self.gate_type = None
            self.logs[sid].extend(events)
            self.pending.pop(sid, None)

    def load(self, sid):
        if sid not in self.headers:
            return None
        return copy.deepcopy((self.headers[sid], self.logs[sid]))

    def reset_pending(self, sid):
        self.pending.pop(sid, None)

    def exists(self, sid):
        return sid in self.headers

    def list(self):
        return list(self.headers)


@pytest.fixture(autouse=True)
def isolate_sessions():
    from backend.agents.runtime.session.persistence.base import get_session_persistence
    previous = get_session_persistence()
    previous_store = store_module._store
    store_module._store = store_module.SessionStore()
    yield
    set_session_persistence(previous)
    store_module._store = previous_store


class Client:
    configured = True
    retry_policy = None

    def __init__(self, messages, persistence=None):
        self.messages = iter(messages)
        self.requests = []
        self.persistence = persistence

    async def complete(self, request):
        if self.persistence:
            assert any(e.type == "request/header" for log in self.persistence.logs.values() for e in log)
        self.requests.append(request)
        return LlmResponse(next(self.messages), finish_reason="stop")

    async def stream(self, request):
        response = await self.complete(request)
        yield StreamChunk(kind="text", delta=response.message.get("content", ""))
        yield StreamChunk(kind="finish", finish_reason="stop")


def answer(text="完成"):
    return {"role": "assistant", "content": text}


def call():
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write", "arguments": "{}"}},
    ]}


def build_loop(persistence, messages):
    session = Session()
    persistence.create(session.header.id, session.header)
    client = Client(messages, persistence)
    checkpoint = SessionCheckpoint(session, persistence)
    loop = AgentLoop(key="a", llm=client, llm_params={"max_steps": 3, "max_tool_calls": 30,
                     "max_wall_time": 30, "max_tokens": 1024, "temperature": .1,
                     "max_llm_retries": 0}, model="test",
                     tool_schemas=[{"type": "function", "function": {"name": "write", "parameters": {"type": "object", "properties": {}}}}],
                     tenant_id=1, session=session, checkpoint=checkpoint)
    calls = []

    class Runtime:
        async def execute(self, name, args, context):
            assert any(e.type == TOOL_CALL for e in persistence.logs[session.header.id])
            calls.append(name)
            return {"ok": True}

    loop._scheduler._runtime = Runtime()
    loop._scheduler._mode_resolver = lambda name: "parallel"
    return loop, checkpoint, client, calls


async def wait_gate(persistence):
    for _ in range(400):
        if persistence.waiting.is_set():
            return
        await asyncio.sleep(.005)
    raise AssertionError("checkpoint barrier was not reached")


def test_model_waits_for_committed_request():
    async def run():
        persistence = MemoryPersistence()
        persistence.gate_type = "request/header"
        loop, _, client, _ = build_loop(persistence, [answer()])
        loop.followup("任务")
        await wait_gate(persistence)
        assert client.requests == []
        persistence.release.set()
        await loop.when_idle()
        assert len(client.requests) == 1
    asyncio.run(run())


def test_tool_waits_for_committed_intent():
    async def run():
        persistence = MemoryPersistence()
        persistence.gate_type = TOOL_CALL
        loop, _, _, calls = build_loop(persistence, [call(), answer()])
        loop.followup("修改文件")
        await wait_gate(persistence)
        assert calls == []
        persistence.release.set()
        await loop.when_idle()
        assert calls == ["write"]
        assert any(e.type == TOOL_RESULT for e in persistence.logs[loop.session.header.id])
    asyncio.run(run())


@pytest.mark.parametrize("failed_type", ["request/header", TOOL_CALL])
def test_checkpoint_failure_reaches_caller_and_blocks_tools(failed_type):
    async def run():
        persistence = MemoryPersistence()
        persistence.fail_type = failed_type
        loop, checkpoint, client, calls = build_loop(persistence, [call(), answer()])
        loop.followup("修改文件")
        with pytest.raises(CheckpointError):
            await loop.when_idle()
        assert calls == []
        assert checkpoint.failed
        assert len(client.requests) == (0 if failed_type == "request/header" else 1)
        assert loop.session.events[-1].data["stop_reason"] == "persistence_error"
    asyncio.run(run())


def test_cancel_during_tool_checkpoint_never_enters_body():
    async def run():
        persistence = MemoryPersistence()
        persistence.gate_type = TOOL_CALL
        loop, _, _, calls = build_loop(persistence, [call(), answer()])
        loop.followup("修改文件")
        await wait_gate(persistence)
        loop.cancel()
        persistence.release.set()
        await loop.when_idle()
        assert calls == []
        results = [e for e in loop.session.events if e.type == TOOL_RESULT]
        assert results and "ABORTED_BEFORE_DISPATCH" in results[0].data["content"]
    asyncio.run(run())


def test_failed_parallel_checkpoint_cannot_be_retried_by_another_waiting_tool():
    class FlakyPersistence(MemoryPersistence):
        failures = 0
        def flush(self, session_id=None):
            if not self.failures and any(e.type == TOOL_CALL for e in self.pending.get(session_id, [])):
                self.failures += 1
                raise OSError("one transient failure")
            super().flush(session_id)
    async def run():
        persistence = FlakyPersistence()
        request = call()
        another = copy.deepcopy(request["tool_calls"][0])
        another["id"] = "c2"
        request["tool_calls"].append(another)
        loop, _, _, calls = build_loop(persistence, [request, answer()])
        loop.followup("修改文件")
        with pytest.raises(CheckpointError):
            await loop.when_idle()
        assert calls == []
        assert persistence.failures == 1
        assert all("ABORTED_BEFORE_DISPATCH" in e.data["content"]
                   for e in loop.session.events if e.type == TOOL_RESULT)
    asyncio.run(run())


def interrupted(persistence, *, semantic=True, started=True):
    session = Session()
    session.append(TURN_START, {"agent": "a", "turn": 1,
                               "durability_policy": "semantic-v1" if semantic else "legacy"})
    session.append("user/message", {"content": "修改文件，然后跑测试"})
    session.append("step/start", {"step": 1})
    session.append("assistant/message", call())
    if started:
        session.append(TOOL_CALL, {"tool": "write", "tool_call_id": "c1", "args": {}})
    persistence.create(session.header.id, session.header)
    persistence.append_events(session.header.id, session.events)
    persistence.flush(session.header.id)
    return session


@pytest.mark.parametrize("semantic,started,code", [(True, True, "TOOL_OUTCOME_UNKNOWN"),
    (True, False, "TOOL_NOT_STARTED"), (False, False, "TOOL_OUTCOME_UNKNOWN")])
def test_repair_commits_before_session_is_published(semantic, started, code):
    async def run():
        persistence = MemoryPersistence()
        source = interrupted(persistence, semantic=semantic, started=started)
        # A previous read populated an unprepared object in the old hot cache.
        store_module.get_session_store().put(source)
        async with prepare_session(persistence, source.header.id, enabled=True,
                                   agent_key="a", resume_from=1) as (session, _, _):
            assert session is not source
            stored = persistence.load(source.header.id)[1]
            result = next(e for e in stored if e.type == TOOL_RESULT)
            assert code in result.data["content"]
            assert stored[-1].type == TURN_END
            assert bool(recovery_status(stored)["unknown_tool_calls"]) == (code == "TOOL_OUTCOME_UNKNOWN")
    asyncio.run(run())


def test_failed_repair_does_not_publish_unbalanced_session():
    async def run():
        persistence = MemoryPersistence()
        source = interrupted(persistence)
        persistence.fail_type = TOOL_RESULT
        with pytest.raises(CheckpointError):
            async with prepare_session(persistence, source.header.id, enabled=True,
                                       agent_key="a", resume_from=1):
                pytest.fail("Failed repair was published")
        assert persistence.load(source.header.id)[1][-1].type == TOOL_CALL
        assert not persistence.is_busy(source.header.id)
    asyncio.run(run())


def test_only_one_recovery_owner_can_prepare_a_session():
    async def run():
        persistence = MemoryPersistence()
        source = interrupted(persistence)
        async with prepare_session(persistence, source.header.id, enabled=True, agent_key="a"):
            with pytest.raises(RunConflict):
                async with prepare_session(persistence, source.header.id, enabled=True, agent_key="a"):
                    pytest.fail("Second owner entered")
        assert not persistence.is_busy(source.header.id)
    asyncio.run(run())


def runtime(monkeypatch, persistence, client):
    from backend.agents.runtime import agent_runtime
    monkeypatch.setattr(agent_runtime, "get_agent_config", lambda key: {})
    set_session_persistence(persistence)
    agent = AgentRuntime("a", {"name": "测试", "config": {"model": "test", "session_title_enabled": False}})
    monkeypatch.setattr(agent, "_llm_client", lambda config: client)
    return agent


def test_resume_uses_saved_history_and_rejects_duplicate_source(monkeypatch):
    async def run():
        persistence = MemoryPersistence()
        source = interrupted(persistence)
        client = Client([answer("测试通过")], persistence)
        agent = runtime(monkeypatch, persistence, client)
        reply = await agent.reply(1, "", session_id=source.header.id, resume_from=1)
        assert reply.answer == "测试通过"
        messages = client.requests[0].messages
        assert any(m.get("role") == "tool" and "TOOL_OUTCOME_UNKNOWN" in m.get("content", "") for m in messages)
        assert any("修改文件，然后跑测试" in str(m.get("content")) for m in messages)
        with pytest.raises(RecoveryError):
            await agent.reply(1, "", session_id=source.header.id, resume_from=1)
        assert len(client.requests) == 1
        stored = persistence.load(source.header.id)[1]
        assert sum(e.type == TURN_START and e.data.get("resumed_from") == 1 for e in stored) == 1
    asyncio.run(run())


def test_final_commit_failure_never_emits_success_done(monkeypatch):
    async def run():
        persistence = MemoryPersistence()
        persistence.fail_type = TURN_END
        agent = runtime(monkeypatch, persistence, Client([answer()], persistence))
        emitted = []
        async def event(value):
            emitted.append(value)
        with pytest.raises(CheckpointError):
            await agent.reply(1, "任务", on_event=event)
        assert any(e["type"] == "session/ready" for e in emitted)
        assert not any(e["type"] == "done" for e in emitted)
    asyncio.run(run())


def test_done_is_sent_after_ownership_is_released(monkeypatch):
    async def run():
        persistence = MemoryPersistence()
        agent = runtime(monkeypatch, persistence, Client([answer()], persistence))
        emitted = []
        async def event(value):
            if value["type"] == "done":
                assert not persistence.is_busy(value["session_id"])
            emitted.append(value)
        await agent.reply(1, "任务", on_event=event)
        assert emitted[-1]["type"] == "done"
    asyncio.run(run())


def test_resume_restores_saved_task_context_without_credentials(monkeypatch):
    async def run():
        from backend.agents.runtime.session.recovery import saved_task_context
        persistence = MemoryPersistence()
        source = interrupted(persistence)
        context = {"order_id": "order-123", "api_key": "private", "nested": {"password": "private", "item": "book"}}
        source.append("task/input", {"context": saved_task_context(context)})
        persistence.append_events(source.header.id, source.events)
        persistence.flush(source.header.id)
        client = Client([answer()], persistence)
        agent = runtime(monkeypatch, persistence, client)
        await agent.reply(1, "", session_id=source.header.id, resume_from=1)
        assert "order-123" in client.requests[0].messages[0]["content"]
        assert "private" not in client.requests[0].messages[0]["content"]
        inputs = [e for e in persistence.load(source.header.id)[1] if e.type == "task/input"]
        assert inputs[-1].data["context"] == {"order_id": "order-123", "nested": {"item": "book"}}
    asyncio.run(run())


def test_repeated_cancellation_waits_for_storage_to_finish():
    async def run():
        persistence = MemoryPersistence()
        session = Session()
        persistence.create(session.header.id, session.header)
        session.append("user/message", {"content": "任务"})
        persistence.gate_type = "user/message"
        checkpoint = SessionCheckpoint(session, persistence)
        work = asyncio.create_task(checkpoint.flush("before_model"))
        await wait_gate(persistence)
        work.cancel()
        await asyncio.sleep(.01)
        work.cancel()
        await asyncio.sleep(.01)
        assert not work.done()
        persistence.release.set()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert persistence.load(session.header.id)[1]
    asyncio.run(run())
