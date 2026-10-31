"""Provider-neutral model connection registry.

The agent loop only sees a resolved :class:`ModelConfig`. Provider packages
(``agent-platform-llm-deepseek`` etc.) register a resolver here; the registry
does not know environment variables or credentials itself.

This is the same seam DSH uses: an LLM service core plus independent provider
adapters. A provider resolver is a pure callable ``(agent config) -> ModelConfig``;
the registry only dispatches by ``provider``.
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


@dataclass(frozen=True)
class ProviderRegistration:
    """The provider package's owned registration; close it on plugin disposal."""

    name: str
    resolver: ProviderResolver

    def close(self) -> None:
        if _PROVIDERS.get(self.name) is self.resolver:
            del _PROVIDERS[self.name]


_PROVIDERS: dict[str, ProviderResolver] = {}


def register_provider(name: str, resolver: ProviderResolver) -> ProviderRegistration:
    """Register one provider route; duplicates are a composition error."""
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("provider name is required")
    if key in _PROVIDERS:
        raise ValueError(f"provider already registered: {key}")
    _PROVIDERS[key] = resolver
    return ProviderRegistration(key, resolver)


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


def _db_only(provider: str, config: dict) -> ModelConfig:
    model = _text(config.get("model"))
    base_url = openai_base_url(_text(config.get("base_url")))
    api_key = _text(config.get("api_key"))
    source = "db" if (model and base_url and api_key) else "none"
    return ModelConfig(provider, model, base_url, api_key, source)


def resolve_model_config(config: dict) -> ModelConfig:
    """Dispatch to the registered provider, or use DB-only fields.

    An unknown/unmounted provider never borrows another provider's credentials.
    """
    provider = (_text(config.get("provider")) or DEFAULT_PROVIDER).lower()
    resolver = _PROVIDERS.get(provider)
    if resolver is not None:
        return resolver(config)
    return _db_only(provider, config)
