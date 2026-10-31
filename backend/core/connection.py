import os
import re
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

_DEFAULT_DATABASE_URL = "postgresql://saas:saas@127.0.0.1:5432/saas"


def normalize_database_url(url: str) -> str:
    """Pin loopback hosts to IPv4.

    On Windows ``localhost`` resolves to ``::1`` first and the IPv6 connection is
    usually refused/dropped, so every *new* pooled connection waits ~2s before
    falling back to ``127.0.0.1``.  The pool starts with two connections; a page
    that fires four or more API calls at once therefore used to stall for seconds
    (history, recovery, file listing), while a single warm request stayed fast.
    """
    return re.sub(r"@(?:localhost|\[::1\])(?=[:/]|$)", "@127.0.0.1", url, flags=re.IGNORECASE)


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
)

_pool: ThreadedConnectionPool | None = None
# 前端页面加载会并行打十几个请求（agents/config/mcp 列表/tools），
# 池满时 psycopg2 直接抛 PoolError 不排队，容量开大 + 短重试兜底
_MAX_CONNECTIONS = 50
_GETCONN_RETRIES = 5


def _get_pool():
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
        except psycopg2.pool.PoolError as e:
            last_err = e
            time.sleep(0.1 * (attempt + 1))  # 突发并发时等一个连接释放
    if conn is None:
        raise last_err
    conn.cursor_factory = RealDictCursor
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
