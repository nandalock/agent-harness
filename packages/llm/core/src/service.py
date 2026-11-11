"""Runtime-scoped LLM service: provider routing and client construction."""
from __future__ import annotations

from collections.abc import Callable

from agent_platform_llm.client import LlmClient
from agent_platform_llm.embedding import embed as _embed
from agent_platform_llm.http import HttpSessionPool
from agent_platform_llm.openai_chat import OpenAiChatClient
from agent_platform_llm.providers import (
    DEFAULT_PROVIDER,
    ModelConfig,
    ProviderResolver,
    fallback_model_config,
)


class LLMService:
    """One provider registry per Loader; no module-level instances."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderResolver] = {}
        self._http = HttpSessionPool()

    def register_provider(self, name: str, resolver: ProviderResolver) -> Callable[[], None]:
        key = (name or "").strip().lower()
        if not key:
            raise ValueError("provider name is required")
        if key in self._providers:
            raise ValueError(f"provider already registered: {key}")
        self._providers[key] = resolver

        def remove() -> None:
            if self._providers.get(key) is resolver:
                del self._providers[key]

        return remove

    def resolve(self, config: dict) -> ModelConfig:
        provider = (str(config.get("provider") or "") or DEFAULT_PROVIDER).lower()
        resolver = self._providers.get(provider)
        return resolver(config) if resolver is not None else fallback_model_config(provider, config)

    def create_client(self, model: ModelConfig, *, max_llm_retries: int) -> LlmClient:
        return OpenAiChatClient(
            api_key=model.api_key if model.configured else "",
            base_url=model.base_url if model.configured else "",
            max_llm_retries=max_llm_retries,
            http_session_factory=self._http.get,
        )

    async def embed(self, text: str, model: str = "bge-m3") -> list[float] | None:
        """Embed text through the runtime-owned HTTP pool (Ollama bge-m3)."""
        return await _embed(self._http.get, text, model)

    async def aclose(self) -> None:
        await self._http.aclose()
