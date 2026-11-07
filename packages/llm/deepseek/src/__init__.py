"""DeepSeek provider plugin.

One composition row owns the route's connection facts:

    - id: llm-deepseek
      name: agent-platform.llm-deepseek
      config:
        apiKeyEnv: DEEPSEEK_API_KEY   # credential reference, resolved per call
        baseURL: https://api.deepseek.com
        model: deepseek-flash

``apiKeyEnv`` defaults to ``DEEPSEEK_API_KEY`` and is read on each resolve.
``baseURL`` falls back to ``DEEPSEEK_OPENAI_BASE_URL`` / ``DEEPSEEK_BASE_URL``
then the official root; ``model`` falls back to ``DEEPSEEK_MODEL`` then
``deepseek-flash``. Per-agent DB values still win field by field.
"""
from __future__ import annotations

import os

from pydantic import ConfigDict, Field

from agent_platform_llm import LLM, ModelConfig, openai_base_url
from agent_platform_plugin_sdk import (
    PluginContext,
    PluginSpec,
    SdkModel,
    ServiceRequirement,
)

DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _env(name: str) -> str:
    return _text(os.environ.get(name)) if name else ""


class DeepSeekConfig(SdkModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, validate_default=True,
    )

    provider: str = "deepseek"
    api_key_env: str = Field(default=DEFAULT_API_KEY_ENV, alias="apiKeyEnv")
    base_url: str | None = Field(default=None, alias="baseURL")
    model: str | None = None


class DeepSeekResolver:
    """Resolve a DeepSeek route from DB overrides + plugin config + launch env."""

    def __init__(self, config: DeepSeekConfig) -> None:
        self._config = config

    def __call__(self, agent_config: dict) -> ModelConfig:
        db_model = _text(agent_config.get("model"))
        db_base = openai_base_url(_text(agent_config.get("base_url")))
        db_key = _text(agent_config.get("api_key"))

        provider_base = openai_base_url(
            _text(self._config.base_url)
            or _env("DEEPSEEK_OPENAI_BASE_URL")
            or _env("DEEPSEEK_BASE_URL")
            or DEFAULT_BASE_URL
        )
        provider_model = _text(self._config.model) or _env("DEEPSEEK_MODEL") or DEFAULT_MODEL
        provider_key = _env(self._config.api_key_env) or _env("DEEPSEEK_KEY")

        model = db_model or provider_model
        base_url = db_base or provider_base
        api_key = db_key or provider_key
        if db_model and db_base and db_key:
            source = "db"
        elif not (db_model or db_base or db_key):
            source = "provider"
        else:
            source = "mixed"
        return ModelConfig(self._config.provider, model, base_url, api_key, source)


class DeepSeekProviderPlugin:
    spec = PluginSpec(
        name="agent-platform.llm-deepseek",
        version="0.1.0",
        requires=(ServiceRequirement(service=LLM.ref),),
    )
    config_model = DeepSeekConfig

    async def setup(self, ctx: PluginContext, config: DeepSeekConfig) -> None:
        registration = ctx.require(LLM).register_provider(
            config.provider, DeepSeekResolver(config)
        )
        ctx.on_dispose(registration, label=f"provider route {config.provider}")
