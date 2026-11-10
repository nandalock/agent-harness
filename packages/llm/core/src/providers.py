"""Provider-neutral model configuration vocabulary.

The routing table itself lives in :class:`agent_platform_llm.service.LLMService`
(one instance per PluginLoader). This module only owns pure types and the
DB-only fallback used when no provider plugin registered the requested route.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: App policy: an agent config without ``provider`` uses the built-in DeepSeek route.
DEFAULT_PROVIDER = "deepseek"


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    #: db = all three from agent config; provider = none did (env/plugin defaults);
    #: mixed = some did.
    source: str = "db"

    @property
    def configured(self) -> bool:
        return bool(self.model and self.base_url and self.api_key)

    def public(self) -> dict:
        """Safe view for config APIs — never includes the credential."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "configured": self.configured,
            "api_key_set": bool(self.api_key),
            "source": self.source,
        }


ProviderResolver = Callable[[dict], ModelConfig]


def openai_base_url(value: str) -> str:
    """Normalize an endpoint to the root the OpenAI client expects.

    The wire client appends ``/v1/chat/completions`` itself, so a supplied
    ``/v1`` or DeepSeek's ``/anthropic`` suffix is stripped (repeatedly, for
    forms such as ``/anthropic/v1/``).
    """
    url = (value or "").strip().rstrip("/")
    changed = True
    while changed and url:
        changed = False
        for suffix in ("/anthropic", "/v1"):
            if url.endswith(suffix):
                url = url[: -len(suffix)].rstrip("/")
                changed = True
    return url


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def fallback_model_config(provider: str, config: dict) -> ModelConfig:
    """DB-only fields; an unregistered provider never borrows another route."""
    model = _text(config.get("model"))
    base_url = openai_base_url(_text(config.get("base_url")))
    api_key = _text(config.get("api_key"))
    source = "db" if (model and base_url and api_key) else "none"
    return ModelConfig(provider, model, base_url, api_key, source)


def resolve_model_config(config: dict) -> ModelConfig:
    """Backward-compatible pure fallback (no provider plugin dispatch).

    Runtime code must call ``ctx.require(LLM).resolve(config)`` so provider
    plugins participate; this function only exists for pure helpers and tests.
    """
    provider = (_text(config.get("provider")) or DEFAULT_PROVIDER).lower()
    return fallback_model_config(provider, config)
