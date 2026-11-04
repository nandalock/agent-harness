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

from .types import (CHUNK_FINISH, CHUNK_TEXT, CHUNK_THINKING, CHUNK_TOOL_CALLS, CHUNK_USAGE,
                    LlmRequest, LlmResponse, StreamChunk, TokenUsage)
from .errors import LlmError, validate_response
from .hooks import LoopHooks, RequestErrorHook, RetryDecision
from .retry import DEFAULT_MAX_LLM_RETRIES, make_retry_policy
from .client import LlmClient
__all__ += ["CHUNK_FINISH", "CHUNK_TEXT", "CHUNK_THINKING", "CHUNK_TOOL_CALLS", "CHUNK_USAGE",
            "LlmRequest", "LlmResponse", "StreamChunk", "TokenUsage", "LlmError", "validate_response",
            "LoopHooks", "RequestErrorHook", "RetryDecision", "DEFAULT_MAX_LLM_RETRIES",
            "make_retry_policy", "LlmClient"]
