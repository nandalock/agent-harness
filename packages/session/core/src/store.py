"""In-memory registry of live sessions.

The store owns *live* Session objects only. Durable history is a separate
service (``agent.session-persistence``); this class never reads or writes it.
"""
from __future__ import annotations

from .session import Session


class SessionStore:
    """session_id → live Session (process-local hot set)."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, *, init_messages: list[dict] | None = None) -> Session:
        session = Session(init_messages=init_messages)
        self._sessions[session.header.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def put(self, session: Session) -> None:
        self._sessions[session.header.id] = session

    def list(self) -> list[str]:
        return list(self._sessions)

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        return True
