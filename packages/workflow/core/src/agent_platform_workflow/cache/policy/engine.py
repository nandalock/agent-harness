from dataclasses import dataclass, field

from .scorers import (
    AgentConfigScorer,
    EntityScorer,
    IntentScorer,
    QualityScorer,
    ScoreResult,
)
from ..config import CacheConfig


@dataclass
class CacheDecision:
    """Final cache decision."""

    should_cache: bool
    score: float
    strategy: str  # "none" | "exact" | "semantic"
    ttl: int
    factors: list[ScoreResult] = field(default_factory=list)
    summary: str = ""


_ALL_SCORERS = {
    "agent_config": AgentConfigScorer(),
    "intent": IntentScorer(),
    "entity": EntityScorer(),
    "quality": QualityScorer(),
}

_SCORER_PARAMS: dict[str, list[str]] = {
    "agent_config": ["agent_config", "cache_policy"],
    "intent": ["intent", "intent_confidence", "cache_policy"],
    "entity": ["question", "cache_policy"],
    "quality": ["answer", "fallback_reply", "tier", "has_error", "trace"],
}


class CachePolicyEngine:
    """Multi-dimension cache admission policy.

    ``cache_policy.scorer_weights`` selects and weights scorers. Without it all
    scorers run with equal weight.
    """

    def __init__(self, config: CacheConfig, agent_config: dict | None = None):
        self.config = config
        self._agent_config = agent_config or {}
        self._cache_policy = self._agent_config.get("cache_policy") if self._agent_config else None

    def evaluate(
        self,
        question: str = "",
        answer: str = "",
        intent: str = "unknown",
        intent_confidence: float = 0.5,
        fallback_reply: str = "",
        tier: str = "llm",
        has_error: bool = False,
        trace: dict | None = None,
    ) -> CacheDecision:
        ctx = {
            "agent_config": self._agent_config,
            "cache_policy": self._cache_policy,
            "intent": intent,
            "intent_confidence": intent_confidence,
            "question": question,
            "answer": answer,
            "fallback_reply": fallback_reply,
            "tier": tier,
            "has_error": has_error,
            "trace": trace,
        }

        weights = self._resolve_weights()
        factors: list[ScoreResult] = []

        for key, scorer in _ALL_SCORERS.items():
            weight = weights.get(key, 0.0)
            if weight <= 0:
                continue
            param_names = _SCORER_PARAMS.get(key, [])
            kwargs = {k: ctx[k] for k in param_names if k in ctx}
            kwargs["weight"] = weight
            factors.append(scorer.score(**kwargs))

        quality_hard_reject = any(
            f.name == "quality" and f.score == 0.0 for f in factors
        )
        total_weight = sum(f.weight for f in factors)
        composite = (
            0.0 if quality_hard_reject
            else (
                sum(f.score * f.weight for f in factors) / total_weight
                if total_weight > 0
                else 0.50
            )
        )

        hint_bonus = {"knowledge": 0.10, "operation": -0.15, "realtime": -0.25}
        if self._cache_policy and "content_hint" in self._cache_policy:
            composite = max(0.0, min(1.0, composite + hint_bonus.get(self._cache_policy["content_hint"], 0)))

        ttl = self.config.ttl
        if composite >= self.config.semantic_min_score:
            strategy = "semantic"
        elif composite >= self.config.min_score:
            strategy = "exact"
        else:
            strategy = "none"

        return CacheDecision(
            should_cache=strategy != "none",
            score=round(composite, 3),
            strategy=strategy,
            ttl=ttl,
            factors=factors,
            summary=self._build_summary(factors, strategy, composite, ttl),
        )

    def _resolve_weights(self) -> dict[str, float]:
        if self._cache_policy and "scorer_weights" in self._cache_policy:
            raw = self._cache_policy["scorer_weights"]
            if isinstance(raw, dict):
                return {k: float(v) for k, v in raw.items() if float(v) > 0}

        n = len(_ALL_SCORERS)
        return {k: 1.0 / n for k in _ALL_SCORERS}

    def _build_summary(self, factors: list[ScoreResult], strategy: str, score: float, ttl: int) -> str:
        blocked = [f for f in factors if f.suggestion == "no_cache"]
        weak = [f for f in factors if f.suggestion == "weak_cache"]

        if strategy == "semantic":
            base = f"语义缓存 (score={score:.2f}), TTL={ttl}s"
        elif strategy == "exact":
            base = f"精确缓存 (score={score:.2f}), TTL={ttl}s"
        else:
            if blocked:
                return f"不缓存 (score={score:.2f})，原因: {', '.join(f.reason for f in blocked)}"
            if weak:
                return f"不缓存 (score={score:.2f})，弱项: {', '.join(f.reason for f in weak)}"
            return f"不缓存 (score={score:.2f})"

        if blocked:
            base += f"，低分项: {', '.join(f.reason for f in blocked)}"
        return base
