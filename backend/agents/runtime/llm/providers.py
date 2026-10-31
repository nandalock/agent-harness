"""Backend import shim for the provider-neutral registry.

The actual registry lives in ``packages/llm/core`` so provider plugins can
import it without depending on the backend. DeepSeek is a plugin
(``packages/llm/deepseek``) registered at plugin-host startup.
"""
from agent_platform_llm import (
    DEFAULT_PROVIDER,
    ModelConfig,
    ProviderRegistration,
    ProviderResolver,
    openai_base_url,
    register_provider,
    resolve_model_config,
)

__all__ = [
    "DEFAULT_PROVIDER",
    "ModelConfig",
    "ProviderRegistration",
    "ProviderResolver",
    "openai_base_url",
    "register_provider",
    "resolve_model_config",
]
