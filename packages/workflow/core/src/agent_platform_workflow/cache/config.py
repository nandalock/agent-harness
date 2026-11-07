from dataclasses import dataclass


@dataclass
class CacheConfig:
    """Workflow node level cache configuration (workflow node data.cache)."""

    enabled: bool = False
    strategy: str = "exact"  # "none" | "exact" | "semantic"
    threshold: float = 0.90
    ttl: int = 604800
    min_score: float = 0.40
    semantic_min_score: float = 0.70
    min_answer_length: int = 50
    max_question_length: int = 10_000

    @classmethod
    def from_node_config(cls, raw: dict | None) -> "CacheConfig":
        if not raw:
            return cls()
        return cls(
            enabled=raw.get("enabled", cls.enabled),
            strategy=raw.get("strategy", cls.strategy),
            threshold=raw.get("threshold", cls.threshold),
            ttl=raw.get("ttl", cls.ttl),
            min_score=raw.get("min_score", cls.min_score),
            semantic_min_score=raw.get("semantic_min_score", cls.semantic_min_score),
            min_answer_length=raw.get("min_answer_length", cls.min_answer_length),
            max_question_length=raw.get("max_question_length", cls.max_question_length),
        )
