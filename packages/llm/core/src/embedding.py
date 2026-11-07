"""RAG 基础设施：Ollama bge-m3 embedding"""
import os
import logging

import aiohttp

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")

logger = logging.getLogger(__name__)


# ═══ Embedding（Ollama bge-m3）═══

async def embed(get_http_session, text: str, model: str = "bge-m3") -> list[float] | None:
    try:
        session = await get_http_session()
        async with session.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": model, "input": text},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            result = await resp.json()
            embeddings = result.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception as e:
        logger.warning(f"Embedding 失败: url={OLLAMA_URL}/api/embed model={model} error={e}")
    return None
