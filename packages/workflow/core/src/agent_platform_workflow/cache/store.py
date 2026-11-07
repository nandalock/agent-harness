"""Lazy Redis connection owned by the workflow plugin."""
from __future__ import annotations

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCacheStore:
    """One lazy Redis client per plugin instance; closed with the plugin."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._pool: redis.ConnectionPool | None = None
        self._client: redis.Redis | None = None

    async def get(self) -> redis.Redis:
        if self._client is None:
            self._pool = redis.ConnectionPool.from_url(
                self._url,
                max_connections=50,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=3,
                retry_on_timeout=True,
                protocol=2,
            )
            self._client = redis.Redis(connection_pool=self._pool)
            try:
                await self._client.ping()
                logger.info("Redis 连接成功: %s", self._url)
            except Exception as exc:
                logger.error("Redis 连接失败: %s", exc)
                raise
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        pool, self._pool = self._pool, None
        if client is not None:
            await client.close()
        if pool is not None:
            await pool.disconnect()
        logger.info("Redis 连接已关闭")
