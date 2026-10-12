"""Real PostgreSQL writes and killed-process recovery in an isolated test schema.

Set CHECKPOINT_TEST_DSN to an explicitly selected test server. No application
tables are modified; each fixture owns and drops a generated private schema.
"""
import asyncio
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import pytest

from backend.agents.runtime.session.checkpoint import SessionCheckpoint
from backend.agents.runtime.session.events import TOOL_CALL, TOOL_RESULT, TURN_END
from backend.agents.runtime.session.persistence import postgres as postgres_module
from backend.agents.runtime.session.persistence.postgres import PostgresSessionPersistence
from backend.agents.runtime.session.recovery import prepare_session
from backend.agents.runtime.session.session import Session
from backend.agents.runtime.loop.registry import RunConflict
from backend.core.schema import TABLES_DDL


@pytest.fixture
def database(monkeypatch):
    dsn = os.getenv("CHECKPOINT_TEST_DSN")
    if not dsn:
        pytest.skip("CHECKPOINT_TEST_DSN must select an isolated PostgreSQL test server")
    schema = "checkpoint_tests_" + uuid.uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    @contextmanager
    def connection():
        conn = psycopg2.connect(dsn, options=f"-c search_path={schema}", cursor_factory=RealDictCursor)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    with connection() as conn:
        with conn.cursor() as cursor:
            for table in ("session_headers", "session_events", "conversations", "messages"):
                cursor.execute(TABLES_DDL[table])
            cursor.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT")
    monkeypatch.setattr(postgres_module, "get_conn", connection)
    try:
        yield dsn, schema, connection
    finally:
        assert re.fullmatch(r"checkpoint_tests_[0-9a-f]{32}", schema)
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def test_committed_prefix_and_incremental_append(database):
    async def run():
        persistence = PostgresSessionPersistence()
        async with prepare_session(persistence, None, enabled=True, agent_key="a") as (session, checkpoint, _):
            session.append("user/message", {"content": "任务"})
            await checkpoint.flush("before_model")
            first = persistence.load(session.header.id)[1]
            assert len(first) == 1
            await checkpoint.flush("repeated")
            session.append("assistant/message", {"content": "完成"})
            await checkpoint.flush("after_step")
            loaded = persistence.load(session.header.id)[1]
            assert [e.seq for e in loaded] == [1, 2]
            assert loaded[0] == first[0]
    asyncio.run(run())


def test_conflicting_sequence_rolls_back_and_keeps_original(database):
    persistence = PostgresSessionPersistence()
    session = Session()
    persistence.create(session.header.id, session.header)
    session.append("user/message", {"content": "original"})
    persistence.append_events(session.header.id, session.events)
    persistence.flush(session.header.id)
    other = PostgresSessionPersistence()
    conflicting = Session(header=session.header)
    conflicting.append("user/message", {"content": "different"})
    other.append_events(session.header.id, conflicting.events)
    with pytest.raises(ValueError, match="Conflicting session event"):
        other.flush(session.header.id)
    assert persistence.load(session.header.id)[1][0].data["content"] == "original"
    assert other._pending[session.header.id]


def test_two_providers_cannot_hold_the_same_session(database):
    first, second = PostgresSessionPersistence(), PostgresSessionPersistence()
    sid = uuid.uuid4().hex
    with first.write_owner(sid):
        assert second.is_busy(sid)
        with pytest.raises(RunConflict):
            with second.write_owner(sid):
                pytest.fail("Concurrent database writer entered")
    assert not second.is_busy(sid)
    with second.write_owner(sid):
        pass


def test_conflicting_pending_event_is_not_silently_dropped(database):
    import copy
    persistence = PostgresSessionPersistence()
    session = Session()
    persistence.create(session.header.id, session.header)
    session.append("user/message", {"content": "original"})
    persistence.append_events(session.header.id, session.events)
    conflicting = copy.deepcopy(session.events)
    conflicting[0].data["content"] = "different"
    with pytest.raises(ValueError, match="Conflicting pending"):
        persistence.append_events(session.header.id, conflicting)
    persistence.flush(session.header.id)
    assert persistence.load(session.header.id)[1][0].data["content"] == "original"


@pytest.mark.parametrize("mode", ["request", "tool", "result"])
def test_killed_process_preserves_checkpoints_and_releases_ownership(database, tmp_path, mode):
    dsn, schema, _ = database
    sid = uuid.uuid4().hex
    marker, effect = tmp_path / "ready", tmp_path / "effect"
    env = {**os.environ, "DATABASE_URL": dsn, "PGOPTIONS": f"-c search_path={schema}"}
    process = subprocess.Popen(
        [sys.executable, "-m", "backend.agents.runtime.session.tests.checkpoint_crash_child",
         mode, sid, str(marker), str(effect)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        if not marker.exists():
            process.kill()
            _, error = process.communicate(timeout=5)
            pytest.fail("Child failed before crash marker: " + error.decode(errors="replace")[-1500:])
        persistence = PostgresSessionPersistence()
        assert persistence.is_busy(sid)
        process.kill()
        process.communicate(timeout=5)
        deadline = time.monotonic() + 3
        while persistence.is_busy(sid) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not persistence.is_busy(sid)

        async def recover():
            async with prepare_session(persistence, sid, enabled=True, agent_key="a", resume_from=1) as (session, _, _):
                stored = persistence.load(sid)[1]
                assert stored[-1].type == TURN_END
                assert stored[-1].data["stop_reason"] == "interrupted"
                assert any(e.type == "request/header" for e in stored)
                results = [e for e in stored if e.type == TOOL_RESULT]
                if mode == "tool":
                    assert any(e.type == TOOL_CALL for e in stored)
                    assert len(results) == 1 and "TOOL_OUTCOME_UNKNOWN" in results[0].data["content"]
                elif mode == "result":
                    assert len(results) == 1 and '"ok": true' in results[0].data["content"]
                else:
                    assert not results
                assert [e.seq for e in stored] == sorted({e.seq for e in stored})
                if mode == "tool":
                    # A scripted model verifies the file before selecting the next action.
                    from backend.agents.runtime.llm.types import LlmResponse
                    from backend.agents.runtime.loop.agent_loop import AgentLoop
                    from backend.agents.runtime.session.recovery import CONTINUE_TASK
                    class Model:
                        configured = True
                        retry_policy = None
                        requests = 0
                        async def complete(self, request):
                            self.requests += 1
                            if self.requests == 1:
                                assert any(m.get("role") == "tool" and "TOOL_OUTCOME_UNKNOWN" in m.get("content", "") for m in request.messages)
                                name = "read_file"
                            elif self.requests == 2:
                                assert any("changed" in m.get("content", "") for m in request.messages if m.get("role") == "tool")
                                name = "run_tests"
                            else:
                                return LlmResponse({"role": "assistant", "content": "测试通过"}, finish_reason="stop")
                            return LlmResponse({"role": "assistant", "content": "", "tool_calls": [
                                {"id": f"resume-{self.requests}", "type": "function", "function": {"name": name, "arguments": "{}"}},
                            ]}, finish_reason="stop")
                    calls = []
                    class Runtime:
                        async def execute(self, name, args, context):
                            calls.append(name)
                            return {"content": effect.read_text()} if name == "read_file" else {"passed": True}
                    loop = AgentLoop(key="a", llm=Model(), llm_params={"max_steps": 3, "max_tool_calls": 30,
                                     "max_wall_time": 30, "max_tokens": 100, "temperature": 0}, model="test",
                                     tool_schemas=[{"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {}}}}
                                                   for name in ("read_file", "run_tests")],
                                     tenant_id=1, session=session, checkpoint=SessionCheckpoint(session, persistence), resumed_from=1)
                    loop._scheduler._runtime = Runtime()
                    loop._scheduler._mode_resolver = lambda name: "parallel"
                    loop.followup(CONTINUE_TASK)
                    await loop.when_idle()
                    await loop._checkpoint.flush("turn_end")
                    assert calls == ["read_file", "run_tests"]
                    assert loop.answer_text() == "测试通过"
        asyncio.run(recover())
        assert effect.read_text().splitlines() == ["changed"] if mode != "request" else not effect.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_chat_stream_binds_first_session_before_model_and_saves_completion(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import agents as api
    from backend.services.chat import service as chat
    from backend.gateway import get_gateway
    from backend.agents.runtime.session.persistence.base import set_session_persistence, get_session_persistence
    from backend.agents.runtime.session.tests.test_checkpoint import Client, answer, runtime
    _, _, connection = database
    monkeypatch.setattr(api, "get_conn", connection)
    monkeypatch.setattr(chat, "get_conn", connection)
    persistence = PostgresSessionPersistence()
    previous = get_session_persistence()
    client = Client([answer("完成")])
    agent = runtime(monkeypatch, persistence, client)
    original_complete = client.complete

    async def complete(request):
        conversations = chat.list_conversations_with_summary(1)
        assert len(conversations) == 1
        sid = conversations[0]["session_id"]
        assert sid and persistence.exists(sid)
        assert any(e.type == "request/header" for e in persistence.load(sid)[1])
        return await original_complete(request)
    monkeypatch.setattr(client, "complete", complete)
    monkeypatch.setattr(get_gateway(), "resolve", lambda key: agent)
    app = FastAPI()
    app.include_router(api.router)
    try:
        with TestClient(app) as http:
            response = http.post("/api/agents/a/chat/stream", json={"question": "任务"}, headers={"X-Tenant-ID": "1"})
            assert response.status_code == 200
            import json
            frames = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
            ready = next(e for e in frames if e["type"] == "session/ready")
            assert frames[-1]["type"] == "done"
            assert any(e.type == TURN_END and e.data["stop_reason"] == "completed"
                       for e in persistence.load(ready["session_id"])[1])
            forbidden = http.get(f'/api/agents/sessions/{ready["session_id"]}/recovery', headers={"X-Tenant-ID": "2"})
            assert forbidden.status_code == 404
    finally:
        set_session_persistence(previous)


def test_read_trajectory_then_resume_repairs_once_and_rejects_repeat(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import agents as api
    from backend.services.chat import service as chat
    from backend.gateway import get_gateway
    from backend.agents.runtime.session.persistence.base import set_session_persistence, get_session_persistence
    from backend.agents.runtime.session.tests.test_checkpoint import Client, answer, interrupted, runtime
    from backend.agents.runtime.session.store import get_session_store
    _, _, connection = database
    monkeypatch.setattr(api, "get_conn", connection)
    monkeypatch.setattr(chat, "get_conn", connection)
    persistence = PostgresSessionPersistence()
    source = interrupted(persistence)
    conversation = chat.create_conversation(1, chat.ConversationCreate(channel="agent:a"))
    chat.save_conversation_session_id(1, conversation.id, source.header.id)
    previous = get_session_persistence()
    client = Client([answer("已核实文件并继续测试")])
    agent = runtime(monkeypatch, persistence, client)
    monkeypatch.setattr(get_gateway(), "resolve", lambda key: agent)
    app = FastAPI()
    app.include_router(api.router)
    try:
        with TestClient(app) as http:
            response = http.get(f"/api/agents/sessions/{source.header.id}/trajectory")
            assert response.status_code == 200
            assert get_session_store().get(source.header.id) is None
            before = persistence.load(source.header.id)[1]
            state = http.get(f"/api/agents/sessions/{source.header.id}/recovery", headers={"X-Tenant-ID": "1"}).json()
            assert state["can_resume"] and state["source_turn_start_seq"] == 1
            assert persistence.load(source.header.id)[1] == before
            payload = {"conversation_id": conversation.id, "session_id": source.header.id, "source_turn_start_seq": 1}
            response = http.post("/api/agents/a/chat/resume/stream", json=payload, headers={"X-Tenant-ID": "1"})
            assert '"type": "done"' in response.text
            assert any(m.get("role") == "tool" and "TOOL_OUTCOME_UNKNOWN" in m.get("content", "") for m in client.requests[0].messages)
            duplicate = http.post("/api/agents/a/chat/resume/stream", json=payload, headers={"X-Tenant-ID": "1"})
            assert 'session/recovery-conflict' in duplicate.text
            assert len(client.requests) == 1
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT count(*) AS count FROM messages WHERE conversation_id = %s AND role = 'customer'",
                                   (conversation.id,))
                    assert cursor.fetchone()["count"] == 1
    finally:
        set_session_persistence(previous)
