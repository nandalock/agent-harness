"""Service key owned by the LLM core plugin."""
from __future__ import annotations

from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .service import LLMService

LLM: ServiceKey[LLMService] = ServiceKey(ServiceRef(name="llm", api_version=1))
