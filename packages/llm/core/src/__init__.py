"""Provider-neutral LLM service, canonical wire vocabulary and adapter."""
from .providers import (
    DEFAULT_PROVIDER,
    ModelConfig,
    ProviderResolver,
    fallback_model_config,
    openai_base_url,
    resolve_model_config,
)
from .types import (CHUNK_FINISH, CHUNK_TEXT, CHUNK_THINKING, CHUNK_TOOL_CALLS, CHUNK_USAGE,
                    LlmRequest, LlmResponse, StreamChunk, TokenUsage)
from .errors import LlmError, validate_response
from .hooks import LoopHooks, RequestErrorHook, RetryDecision
from .retry import DEFAULT_MAX_LLM_RETRIES, make_retry_policy
from .client import LlmClient
from .http import HttpSessionPool
from .openai_chat import OpenAiChatClient
from .service import LLMService
from .services import LLM
from .plugin import LLMPlugin

__all__ = [
    "DEFAULT_PROVIDER", "ModelConfig", "ProviderResolver", "fallback_model_config",
    "openai_base_url", "resolve_model_config",
    "CHUNK_FINISH", "CHUNK_TEXT", "CHUNK_THINKING", "CHUNK_TOOL_CALLS", "CHUNK_USAGE",
    "LlmRequest", "LlmResponse", "StreamChunk", "TokenUsage", "LlmError", "validate_response",
    "LoopHooks", "RequestErrorHook", "RetryDecision", "DEFAULT_MAX_LLM_RETRIES",
    "make_retry_policy", "LlmClient", "HttpSessionPool", "OpenAiChatClient",
    "LLMService", "LLM", "LLMPlugin",
]
