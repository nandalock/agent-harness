"""Provider-neutral LLM connection registry shared by the backend and provider plugins."""
from .providers import (
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
