"""Legacy embedding adapter for FAQ and cache."""
from agent_platform_llm.embedding import embed as _embed

from backend.core.http import get_http_session


async def embed(text: str, model: str = "bge-m3") -> list[float] | None:
    return await _embed(get_http_session, text, model)
