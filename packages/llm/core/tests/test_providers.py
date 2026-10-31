"""Shared provider registry: dispatch, ownership, and URL normalization."""
import unittest

from agent_platform_llm import (
    ModelConfig,
    openai_base_url,
    register_provider,
    resolve_model_config,
)


class RegistryTests(unittest.TestCase):
    def test_unknown_provider_is_db_only(self):
        model = resolve_model_config({
            "provider": "openai",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": "db-key",
        })
        self.assertTrue(model.configured)
        self.assertEqual(model.base_url, "https://api.openai.com")
        self.assertEqual(model.source, "db")

    def test_registered_provider_dispatches_and_closes(self):
        registration = register_provider(
            "test-provider",
            lambda config: ModelConfig("test-provider", "m", "https://example.test", "k", "provider"),
        )
        try:
            model = resolve_model_config({"provider": "test-provider"})
            self.assertEqual(model.provider, "test-provider")
            self.assertEqual(model.source, "provider")
        finally:
            registration.close()
        # After close the same config falls back to DB-only (unconfigured).
        self.assertFalse(resolve_model_config({"provider": "test-provider"}).configured)

    def test_duplicate_provider_registration_is_rejected(self):
        registration = register_provider(
            "test-duplicate",
            lambda config: ModelConfig("test-duplicate", "m", "https://example.test", "k"),
        )
        try:
            with self.assertRaisesRegex(ValueError, "already registered"):
                register_provider("test-duplicate", registration.resolver)
        finally:
            registration.close()

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
