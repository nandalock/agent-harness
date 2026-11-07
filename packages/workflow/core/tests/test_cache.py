import unittest

from agent_platform_workflow.cache import CacheConfig
from agent_platform_workflow.cache.policy import CachePolicyEngine


class CachePolicyTests(unittest.TestCase):
    def test_fallback_answer_is_rejected(self):
        decision = CachePolicyEngine(CacheConfig(enabled=True)).evaluate(
            question="q", answer="fallback", fallback_reply="fallback",
        )
        self.assertFalse(decision.should_cache)
        self.assertEqual(decision.strategy, "none")

    def test_quality_answer_with_sources_becomes_semantic(self):
        decision = CachePolicyEngine(
            CacheConfig(enabled=True), {"cache_policy": {"base_score": 0.9}},
        ).evaluate(
            question="如何退货",
            answer="请先进入订单页，选择退货并填写原因。" * 3,
            trace={"sources": ["faq:1"]},
        )
        self.assertTrue(decision.should_cache)
        self.assertEqual(decision.strategy, "semantic")

    def test_explicit_weights_disable_unlisted_scorers(self):
        engine = CachePolicyEngine(
            CacheConfig(enabled=True),
            {"cache_policy": {"scorer_weights": {"agent_config": 1.0}}},
        )
        decision = engine.evaluate(question="q", answer="short")
        self.assertEqual([factor.name for factor in decision.factors], ["agent_config"])
