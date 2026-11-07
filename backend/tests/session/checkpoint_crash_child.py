"""Hard-crash fixture: publish a marker only after the selected real database barrier."""
import asyncio
import sys
from pathlib import Path

from agent_platform_llm.types import LlmResponse
from agent_platform_agent_loop.agent_loop import AgentLoop
from backend.agents.runtime.tests.loop_support import loop_context
from backend.core.connection import get_conn
from agent_platform_session import SessionStore
from agent_platform_session_recovery import SessionCheckpoint, prepare_session
from agent_platform_session_persistence_postgres import PostgresSessionPersistence


async def main():
    mode, sid, marker_path, effect_path = sys.argv[1:]
    marker, effect = Path(marker_path), Path(effect_path)
    persistence = PostgresSessionPersistence(get_conn)

    async def halt():
        marker.write_text("ready", encoding="utf-8")
        await asyncio.Event().wait()

    class Client:
        configured = True
        retry_policy = None

        async def complete(self, request):
            if mode == "request":
                await halt()
            return LlmResponse({"role": "assistant", "content": "", "tool_calls": [
                {"id": "crash-call", "type": "function", "function": {"name": "write", "arguments": "{}"}},
            ]}, finish_reason="stop")

    class Checkpoint(SessionCheckpoint):
        async def flush(self, reason):
            await super().flush(reason)
            if mode == "result" and reason == "after_step":
                await halt()

    class Runtime:
        async def execute(self, name, args, context):
            with effect.open("a", encoding="utf-8") as output:
                output.write("changed\n")
            if mode == "tool":
                await halt()
            return {"ok": True}

    async with prepare_session(store=SessionStore(), persistence=persistence, session_id=sid,
                               enabled=True, agent_key="a") as (session, _, _):
        checkpoint = Checkpoint(session, persistence)
        loop = AgentLoop(loop_context(Client()), key="a", llm_params={"max_steps": 3, "max_tool_calls": 30,
                         "max_wall_time": 60, "max_tokens": 100, "temperature": 0}, model="test",
                         tool_schemas=[{"type": "function", "function": {"name": "write", "parameters": {"type": "object", "properties": {}}}}],
                         tenant_id=1, session=session, checkpoint=checkpoint)
        loop._scheduler._runtime = Runtime()
        loop._scheduler._mode_resolver = lambda name: "parallel"
        loop.followup("修改文件，然后跑测试")
        await loop.when_idle()


if __name__ == "__main__":
    asyncio.run(main())
