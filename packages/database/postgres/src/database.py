"""Pooled PostgreSQL database owned by one Loader."""
from __future__ import annotations

import re
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

DEFAULT_DATABASE_URL = "postgresql://saas:saas@127.0.0.1:5432/saas"


def normalize_database_url(url: str) -> str:
    """Pin loopback hosts to IPv4 (Windows resolves localhost to ::1 first)."""
    return re.sub(r"@(?:localhost|\[::1\])(?=[:/]|$)", "@127.0.0.1", url, flags=re.IGNORECASE)


class PostgresDatabase:
    """Instance-local connection pool; dispose closes every connection."""

    def __init__(self, dsn: str, *, max_connections: int = 50) -> None:
        self._dsn = normalize_database_url(dsn or DEFAULT_DATABASE_URL)
        self._max = max_connections
        self._pool: ThreadedConnectionPool | None = None

    def _get_pool(self) -> ThreadedConnectionPool:
        if self._pool is None:
            self._pool = ThreadedConnectionPool(2, self._max, dsn=self._dsn)
        return self._pool

    @contextmanager
    def get_conn(self):
        pool = self._get_pool()
        conn = None
        last_err = None
        for attempt in range(5):
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

    def aclose(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.closeall()
