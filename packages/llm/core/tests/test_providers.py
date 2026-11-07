"""Runtime-scoped provider registry: dispatch, ownership, and URL normalization."""
import unittest

from agent_platform_llm import LLMService, ModelConfig, fallback_model_config, openai_base_url


class RegistryTests(unittest.TestCase):
    def test_unknown_provider_is_db_only(self):
        model = fallback_model_config("openai", {
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": "db-key",
        })
        self.assertTrue(model.configured)
        self.assertEqual(model.base_url, "https://api.openai.com")
        self.assertEqual(model.source, "db")

    def test_registered_provider_dispatches_and_closes(self):
        service = LLMService()
        remove = service.register_provider(
            "test-provider",
            lambda config: ModelConfig("test-provider", "m", "https://example.test", "k", "provider"),
        )
        try:
            model = service.resolve({"provider": "test-provider"})
            self.assertEqual(model.provider, "test-provider")
            self.assertEqual(model.source, "provider")
        finally:
            remove()
        # After close the same config falls back to DB-only (unconfigured).
        self.assertFalse(service.resolve({"provider": "test-provider"}).configured)

    def test_two_services_do_not_share_providers(self):
        first, second = LLMService(), LLMService()
        first.register_provider(
            "scoped", lambda config: ModelConfig("scoped", "m", "https://example.test", "k")
        )
        self.assertEqual(first.resolve({"provider": "scoped"}).provider, "scoped")
        self.assertEqual(second.resolve({"provider": "scoped"}).source, "none")

    def test_duplicate_provider_registration_is_rejected(self):
        service = LLMService()
        remove = service.register_provider(
            "test-duplicate",
            lambda config: ModelConfig("test-duplicate", "m", "https://example.test", "k"),
        )
        try:
            with self.assertRaisesRegex(ValueError, "already registered"):
                service.register_provider("test-duplicate", remove)
        finally:
            remove()

    def test_public_view_hides_the_credential(self):
        model = ModelConfig("deepseek", "deepseek-flash", "https://api.deepseek.com", "secret")
        public = model.public()
        self.assertTrue(public["configured"])
        self.assertTrue(public["api_key_set"])
        self.assertNotIn("api_key", public)


class BaseUrlTests(unittest.TestCase):
    def test_normalizes_known_suffixes(self):
        self.assertEqual(openai_base_url("https://api.deepseek.com/anthropic/"), "https://api.deepseek.com")
        self.assertEqual(openai_base_url("https://api.deepseek.com/v1"), "https://api.deepseek.com")
        self.assertEqual(openai_base_url("https://gateway.test/openai/v1/"), "https://gateway.test/openai")


if __name__ == "__main__":
    unittest.main()
