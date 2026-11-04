"""Database access for the built-in MCP server (environment-driven)."""
import os
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://saas:saas@localhost:5432/saas"
)

_pool: ThreadedConnectionPool | None = None
_MAX_CONNECTIONS = 20
_GETCONN_RETRIES = 5


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(2, _MAX_CONNECTIONS, dsn=DATABASE_URL)
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = None
    last_err = None
    for attempt in range(_GETCONN_RETRIES):
        try:
            conn = pool.getconn()
            break
        except psycopg2.pool.PoolError as exc:
            last_err = exc
            time.sleep(0.1 * (attempt + 1))
    if conn is None:
        raise last_err
    conn.cursor_factory = RealDictCursor
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
