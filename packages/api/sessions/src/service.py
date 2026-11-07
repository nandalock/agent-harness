"""Session business operations used by both RPC and legacy REST."""
from __future__ import annotations

import asyncio

from agent_platform_rpc_gateway import RpcError
from agent_platform_sandbox.policy import FALLBACK_MODE, validate_mode
from agent_platform_sandbox.runtime import session_default_mode
from agent_platform_session.events import SANDBOX_MODE
from agent_platform_session_projection import project_sandbox_mode, project_trajectory


class SessionApiService:
    def __init__(self, database, sessions, persistence, recovery) -> None:
        self._database = database
        self._sessions = sessions
        self._persistence = persistence
        self._recovery = recovery

    def _owned(self, session_id: str, tenant_id: int) -> bool:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM conversations WHERE tenant_id = %s AND session_id = %s",
                    (tenant_id, session_id),
                )
                return cur.fetchone() is not None

    async def _assert_visible(self, session_id: str, tenant_id: int) -> None:
        if not await asyncio.to_thread(self._owned, session_id, tenant_id):
            raise RpcError("session/not-found", f"会话不存在: {session_id}")

    async def _session_or_404(self, session_id: str):
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        loaded = await asyncio.to_thread(self._persistence.load, session_id)
        if loaded is None:
            raise RpcError("session/not-found", f"会话不存在: {session_id}")
        from agent_platform_session import Session

        return Session.from_events(*loaded)

    async def recovery(self, tenant_id: int, session_id: str):
        await self._assert_visible(session_id, tenant_id)
        if not self._persistence.durable:
            return {
                "session_id": session_id, "status": "temporary",
                "last_durable_seq": 0, "source_turn_start_seq": None,
                "can_resume": False, "unknown_tool_calls": [],
            }
        loaded = await asyncio.to_thread(self._persistence.load_recovery, session_id)
        if loaded is None:
            raise RpcError("session/not-found", "执行记录不存在")
        events, last_durable_seq = loaded
        busy = await asyncio.to_thread(self._persistence.is_busy, session_id)
        return {"session_id": session_id, **self._recovery.status(
            events, busy=busy, last_durable_seq=last_durable_seq,
        )}

    async def trajectory(self, tenant_id: int, session_id: str):
        await self._assert_visible(session_id, tenant_id)
        session = await self._session_or_404(session_id)
        return {"session_id": session_id, "trajectory": project_trajectory(session.events)}

    async def sandbox_mode(self, tenant_id: int, session_id: str):
        await self._assert_visible(session_id, tenant_id)
        session = await self._session_or_404(session_id)
        override = project_sandbox_mode(session.events)
        default = session_default_mode(session.header.cwd)
        return {
            "session_id": session_id,
            "override": override,
            "default": default,
            "effective": override or default or FALLBACK_MODE,
        }

    async def set_sandbox_mode(self, tenant_id: int, session_id: str, mode: str):
        await self._assert_visible(session_id, tenant_id)
        try:
            mode = validate_mode(mode)
        except ValueError as exc:
            raise RpcError("session/invalid-mode", str(exc)) from None
        async with self._recovery.prepare(
            session_id, enabled=True, agent_key="",
        ) as (session, checkpoint, _):
            session.append(SANDBOX_MODE, {"mode": mode})
            await checkpoint.flush("sandbox_mode")
        return {"session_id": session_id, "override": mode}
