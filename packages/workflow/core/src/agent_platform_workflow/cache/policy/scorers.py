import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    """One scoring dimension."""

    name: str
    score: float
    weight: float
    reason: str
    suggestion: str


class AgentConfigScorer:
    """Score from cache_policy.base_score; absent means neutral 0.50."""

    def score(self, agent_config: dict, cache_policy: dict | None = None,
              weight: float = 0.0) -> ScoreResult:
        if cache_policy and "base_score" in cache_policy:
            score = float(cache_policy["base_score"])
            reason = f"base_score={score}"
        else:
            score = 0.50
            reason = "未配置 base_score，中性分"

        suggestion = "strong_cache" if score > 0.7 else ("weak_cache" if score > 0.3 else "no_cache")
        return ScoreResult(
            name="agent_config", score=score, weight=weight,
            reason=reason, suggestion=suggestion,
        )


class IntentScorer:
    """cache_policy.cacheable_intents is a whitelist."""

    def score(self, intent: str = "unknown", intent_confidence: float = 0.5,
              cache_policy: dict | None = None, weight: float = 0.0) -> ScoreResult:
        if cache_policy and "cacheable_intents" in cache_policy:
            cacheable = cache_policy.get("cacheable_intents", [])
            if cacheable:
                if intent in cacheable:
                    base = 0.90
                    reason = f"intent={intent} ∈ cacheable_intents"
                else:
                    base = 0.05
                    reason = f"intent={intent} ∉ cacheable_intents"
            else:
                base = 0.50
                reason = f"intent={intent}（cacheable_intents 为空，中性）"
        else:
            base = 0.50
            reason = f"intent={intent}（未配置 cacheable_intents，中性）"

        score = base * intent_confidence
        suggestion = "strong_cache" if score > 0.7 else ("weak_cache" if score > 0.3 else "no_cache")
        return ScoreResult(
            name="intent", score=round(score, 3), weight=weight,
            reason=f"{reason}, confidence={intent_confidence:.2f}", suggestion=suggestion,
        )


class EntityScorer:
    """Reject or penalize questions matching cache_policy.block_entities."""

    def score(self, question: str = "", cache_policy: dict | None = None,
              weight: float = 0.0) -> ScoreResult:
        entities = cache_policy.get("block_entities", []) if cache_policy else []
        if not entities:
            return ScoreResult(
                name="entity", score=1.0, weight=weight,
                reason="未配置 block_entities，不封杀", suggestion="strong_cache",
            )

        lowest_score = 1.0
        matched: list[str] = []
        for entry in entities:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "?")
            pattern = entry.get("pattern", "")
            penalty = float(entry.get("penalty", 0.0))
            if not pattern:
                continue
            try:
                if re.search(pattern, question):
                    matched.append(name)
                    lowest_score = min(lowest_score, penalty)
            except re.error:
                logger.warning("[EntityScorer] invalid regex for %s: %s", name, pattern)

        if not matched:
            return ScoreResult(
                name="entity", score=1.0, weight=weight,
                reason=f"无命中 (封杀列表: {', '.join(e.get('name', '?') for e in entities if isinstance(e, dict))})",
                suggestion="strong_cache",
            )

        return ScoreResult(
            name="entity", score=lowest_score, weight=weight,
            reason=f"命中: {', '.join(matched)}", suggestion="no_cache",
        )


class QualityScorer:
    """Global answer-quality rules; independent of external configuration."""

    def score(
        self, answer: str = "", fallback_reply: str = "",
        tier: str = "llm", has_error: bool = False,
        trace: dict | None = None, cache_policy: dict | None = None,
        weight: float = 0.0,
    ) -> ScoreResult:
        if has_error:
            return ScoreResult(
                name="quality", score=0.0, weight=weight, reason="LLM 调用异常", suggestion="no_cache",
            )
        if fallback_reply and answer == fallback_reply:
            return ScoreResult(
                name="quality", score=0.0, weight=weight, reason="返回了兜底回复", suggestion="no_cache",
            )
        if not answer:
            return ScoreResult(
                name="quality", score=0.5, weight=weight, reason="答案尚未生成（预评估）", suggestion="weak_cache",
            )
        if tier == "handoff":
            return ScoreResult(
                name="quality", score=0.0, weight=weight, reason="转人工，未生成有效答案", suggestion="no_cache",
            )
        if len(answer) < 50:
            return ScoreResult(
                name="quality", score=0.3, weight=weight,
                reason=f"答案太短 ({len(answer)} 字符)", suggestion="weak_cache",
            )

        trace = trace or {}
        has_sources = bool(trace.get("sources") or trace.get("citations"))
        score = 0.9 if has_sources else 0.7
        return ScoreResult(
            name="quality", score=score, weight=weight,
            reason="正常回复" + ("，包含引用来源" if has_sources else ""), suggestion="strong_cache",
        )
