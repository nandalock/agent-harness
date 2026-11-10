"""Service key owned by the LLM core plugin."""
from __future__ import annotations

from agent_platform_plugin_sdk import ServiceKey

from .service import LLMService

LLM: ServiceKey[LLMService] = ServiceKey("llm")
