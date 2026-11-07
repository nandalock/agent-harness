"""Per-runtime HTTP connection pool owned by the LLM service plugin."""
from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)


class HttpSessionPool:
    """One lazy aiohttp pool per LLM service instance.

    The pool is never module-global: two plugin runtimes in one process must not
    share connections, and disposing a runtime closes only its own pool.
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                connector=aiohttp.TCPConnector(limit=50, ttl_dns_cache=300),
            )
            logger.info("创建 LLM aiohttp session")
        return self._session

    async def aclose(self) -> None:
        session, self._session = self._session, None
        if session is not None and not session.closed:
            await session.close()
