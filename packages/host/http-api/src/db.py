"""Request-scoped access to the database.v1 service for route SQL.

The HTTP plugin receives the database service at setup. Route helpers keep
their existing synchronous SQL, while the connection is resolved from a
ContextVar bound by middleware (and by the lifespan bootstrap).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_current: ContextVar[Any | None] = ContextVar("http_database", default=None)


def set_current_database(database: Any) -> Token:
    return _current.set(database)


def reset_current_database(token: Token) -> None:
    _current.reset(token)


def current_database() -> Any | None:
    return _current.get()


@contextmanager
def get_conn():
    database = _current.get()
    if database is None:
        raise RuntimeError("database.v1 is not bound to this request")
    with database.get_conn() as conn:
        yield conn
