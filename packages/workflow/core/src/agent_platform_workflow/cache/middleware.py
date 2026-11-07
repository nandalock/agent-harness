"""Cache middleware for agent-backed workflow nodes."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .semantic import SemanticCache

logger = logging.getLogger(__name__)


def _timeline_entry(
    node_id: str,
    label: str,
    node_type: str,
    output: str,
    ms: int,
    cache: dict | None = None,
) -> list:
    entry = {"node_id": node_id, "label": label, "node_type": node_type, "output": output, "ms": ms}
    if cache is not None:
        entry["cache"] = cache
    return [entry]


class CacheMiddleware:
    """Look up before the agent call; write after a successful answer."""

    def __init__(self, node_id: str, cache: SemanticCache):
        self.node_id = node_id
        self.cache = cache

    async def process(self, state: dict, node_id: str, next_handler: Callable) -> dict:
        question = state.get("input", "")

        started = time.time()
        hit, answer, tier, score = await self.cache.lookup(question)
        elapsed_ms = int((time.time() - started) * 1000)

        if hit:
            return {
                "node_results": {node_id: answer},
                "node_timeline": _timeline_entry(
                    node_id, f"缓存命中 ({tier})", "agent", str(answer)[:200], elapsed_ms,
                    cache={"hit": True, "tier": tier, "score": score},
                ),
            }

        pre_eval = self.cache.policy.evaluate(
            question=question,
            answer="",
            intent="unknown",
            intent_confidence=0.5,
        )
        cache_info: dict[str, Any] = {
            "hit": False,
            "tier": "miss",
            "score": pre_eval.score,
            "factors": [
                {"name": f.name, "score": f.score, "weight": f.weight, "reason": f.reason, "suggestion": f.suggestion}
                for f in pre_eval.factors
            ],
            "summary": pre_eval.summary,
        }

        result = await next_handler(state)

        answer_text = ""
        node_results = result.get("node_results", {})
        if isinstance(node_results, dict):
            answer_text = str(node_results.get(node_id, ""))

        if answer_text:
            actual = await self.cache.store(question=question, answer=answer_text)
            if actual is not None:
                cache_info = {
                    "hit": False,
                    "tier": "miss",
                    "score": actual.score,
                    "factors": [
                        {"name": f.name, "score": f.score, "weight": f.weight, "reason": f.reason, "suggestion": f.suggestion}
                        for f in actual.factors
                    ],
                    "summary": actual.summary,
                }

        miss_entry = _timeline_entry(
            node_id, "缓存未命中 → 调用 Agent", "cache", "", elapsed_ms, cache=cache_info,
        )
        result["node_timeline"] = miss_entry + result.get("node_timeline", [])
        return result
