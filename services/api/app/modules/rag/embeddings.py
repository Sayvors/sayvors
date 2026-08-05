import asyncio
import hashlib
import json
from abc import ABC, abstractmethod

import httpx

from ...config import settings

EMBED_CACHE_TTL = 86400 * 30


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def dimensions(self) -> int:
        ...


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.model = "bge-m3"
        self._dims = 1024
        self.base_url = "http://localhost:11434"

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        batch_size = 32
        all_embeddings: list[list[float]] = []

        async with httpx.AsyncClient(timeout=120) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                resp = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                )
                resp.raise_for_status()
                data = resp.json()
                all_embeddings.extend(data["embeddings"])

        return all_embeddings


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.model = "text-embedding-3-small"
        self._dims = 1024

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import openai

        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        batch_size = 2048
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self._dims,
            )
            all_embeddings.extend([e.embedding for e in resp.data])

        return all_embeddings


_provider: EmbeddingProvider | None = None


async def _check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def get_embedding_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider

    if await _check_ollama():
        _provider = OllamaEmbeddingProvider()
    elif settings.OPENAI_API_KEY:
        _provider = OpenAIEmbeddingProvider()
    else:
        _provider = OllamaEmbeddingProvider()

    return _provider
