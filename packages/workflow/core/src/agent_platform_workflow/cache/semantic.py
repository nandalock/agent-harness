"""Semantic response cache backed by Redis and an injected embedding function."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .config import CacheConfig
from .policy.engine import CacheDecision, CachePolicyEngine

logger = logging.getLogger(__name__)

INDEX_NAME = "idx:cache:sem"

GetRedis = Callable[[], Awaitable[Any]]
Embed = Callable[[str], Awaitable[list[float] | None]]


class SemanticCache:
    """L1 exact + L2 semantic cache for one workflow node."""

    def __init__(
        self,
        config: CacheConfig,
        node_id: str,
        agent_config: dict | None = None,
        *,
        get_redis: GetRedis,
        embed: Embed,
    ) -> None:
        self.config = config
        self.node_id = node_id
        self.policy = CachePolicyEngine(config, agent_config)
        self._get_redis = get_redis
        self._embed = embed
        self._index_ready = False

    async def lookup(self, question: str) -> tuple[bool, str | None, str, float | None]:
        if not self.config.enabled:
            return False, None, "miss", None
        try:
            r = await self._get_redis()

            exact_key = _exact_key(self.node_id, question)
            cached = await r.get(exact_key)
            if cached:
                return True, cached, "exact", 1.0

            if self.config.strategy != "semantic":
                return False, None, "miss", None

            vector = await self._embed(question)
            if vector is None:
                logger.warning("[cache] L2 lookup skipped: node=%s embedding returned None", self.node_id)
                return False, None, "miss", None

            await self._ensure_index(r)
            result = await r.execute_command(
                "FT.SEARCH", INDEX_NAME,
                f"@node_id:{{{self.node_id}}} =>[KNN 3 @embedding $vec AS similarity]",
                "PARAMS", "2", "vec", _vec_to_bytes(vector),
                "SORTBY", "similarity",
                "DIALECT", "2",
                "RETURN", "3", "answer", "similarity", "question",
            )
            for index in range(1, len(result), 2):
                fields = _parse_fields(result[index + 1])
                similarity = float(fields.get("similarity", 0))
                if similarity >= self.config.threshold:
                    return True, fields.get("answer", ""), "semantic", similarity
            return False, None, "miss", None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cache] lookup degraded to miss: node=%s error=%s", self.node_id, exc)
            return False, None, "miss", None

    async def store(
        self,
        question: str,
        answer: str,
        intent: str = "unknown",
        intent_confidence: float = 0.5,
        fallback_reply: str = "",
        tier: str = "llm",
        has_error: bool = False,
        trace: dict | None = None,
    ) -> CacheDecision | None:
        if not self.config.enabled:
            return None

        decision = self.policy.evaluate(
            question=question,
            answer=answer,
            intent=intent,
            intent_confidence=intent_confidence,
            fallback_reply=fallback_reply,
            tier=tier,
            has_error=has_error,
            trace=trace,
        )
        if not decision.should_cache:
            logger.info("[cache] store rejected: node=%s %s", self.node_id, decision.summary)
            return decision

        try:
            r = await self._get_redis()
            await r.set(_exact_key(self.node_id, question), answer, ex=decision.ttl)

            if decision.strategy == "semantic":
                vector = await self._embed(question)
                if vector is None:
                    logger.warning("[cache] L2 skipped: node=%s embedding returned None", self.node_id)
                else:
                    await self._ensure_index(r)
                    key = _semantic_key()
                    await r.hset(
                        key,
                        mapping={
                            "embedding": _vec_to_bytes(vector),
                            "question": question,
                            "answer": answer,
                            "node_id": self.node_id,
                            "created_at": int(time.time()),
                        },
                    )
                    await r.expire(key, decision.ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cache] store failed: node=%s error=%s", self.node_id, exc)
        return decision

    async def _ensure_index(self, r: Any) -> None:
        if self._index_ready:
            return
        try:
            await r.execute_command("FT.INFO", INDEX_NAME)
        except Exception:  # noqa: BLE001
            logger.info("[cache] creating RediSearch index: %s", INDEX_NAME)
            await r.execute_command(
                "FT.CREATE", INDEX_NAME,
                "ON", "HASH", "PREFIX", "1", "cache:sem:",
                "SCHEMA",
                "embedding", "VECTOR", "HNSW", "6",
                "DIM", "1024", "TYPE", "FLOAT32", "DISTANCE_METRIC", "COSINE",
                "question", "TEXT",
                "answer", "TEXT",
                "node_id", "TAG",
                "created_at", "NUMERIC", "SORTABLE",
            )
        self._index_ready = True


def _exact_key(node_id: str, question: str) -> str:
    digest = hashlib.md5(question.strip().lower().encode()).hexdigest()
    return f"cache:exact:{node_id}:{digest}"


def _semantic_key() -> str:
    return f"cache:sem:{uuid.uuid4().hex[:12]}"


def _vec_to_bytes(vector: list[float]) -> bytes:
    import numpy as np

    return np.array(vector, dtype=np.float32).tobytes()


def _parse_fields(fields: list) -> dict:
    result = {}
    for index in range(0, len(fields), 2):
        key = fields[index] if isinstance(fields[index], str) else fields[index].decode()
        value = fields[index + 1]
        result[key] = value if isinstance(value, str) else value.decode()
    return result
