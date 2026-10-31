"""DeepSeek provider: env defaults, plugin config, and DB precedence."""
import os
import unittest
from unittest.mock import patch

from agent_platform_llm_deepseek import DeepSeekConfig, DeepSeekResolver


class DeepSeekResolverTests(unittest.TestCase):
    def test_environment_defaults(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "env-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/anthropic",
        }, clear=True):
            model = DeepSeekResolver(DeepSeekConfig())({})
        self.assertEqual(model.provider, "deepseek")
        self.assertEqual(model.model, "deepseek-flash")
        self.assertEqual(model.base_url, "https://api.deepseek.com")
        self.assertEqual(model.api_key, "env-key")
        self.assertEqual(model.source, "provider")
        self.assertTrue(model.configured)

    def test_plugin_config_beats_environment(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "env-key",
            "DEEPSEEK_BASE_URL": "https://env.example/anthropic",
            "DEEPSEEK_MODEL": "env-model",
        }, clear=True):
            config = DeepSeekConfig.model_validate({
                "apiKeyEnv": "DEEPSEEK_API_KEY",
                "baseURL": "https://config.example/v1",
                "model": "config-model",
            })
            model = DeepSeekResolver(config)({})
        self.assertEqual(model.base_url, "https://config.example")
        self.assertEqual(model.model, "config-model")
        self.assertEqual(model.api_key, "env-key")

    def test_db_values_win_field_by_field(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "env-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        }, clear=True):
            model = DeepSeekResolver(DeepSeekConfig())({
                "model": "db-model",
                "base_url": "https://db.example/v1",
                "api_key": "db-key",
            })
        self.assertEqual(model.model, "db-model")
        self.assertEqual(model.base_url, "https://db.example")
        self.assertEqual(model.api_key, "db-key")
        self.assertEqual(model.source, "db")

    def test_partial_db_uses_env_for_missing_fields(self):
        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "env-key",
        }, clear=True):
            model = DeepSeekResolver(DeepSeekConfig())({"model": "db-model"})
        self.assertEqual(model.model, "db-model")
        self.assertEqual(model.api_key, "env-key")
        self.assertEqual(model.source, "mixed")

    def test_missing_key_is_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            model = DeepSeekResolver(DeepSeekConfig())({})
        self.assertFalse(model.configured)
        self.assertFalse(model.public()["api_key_set"])

    def test_empty_env_name_is_safe(self):
        with patch.dict(os.environ, {"DEEPSEEK_KEY": "fallback"}, clear=True):
            model = DeepSeekResolver(DeepSeekConfig(apiKeyEnv=""))({})
        self.assertEqual(model.api_key, "fallback")


if __name__ == "__main__":
    unittest.main()
