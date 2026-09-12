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

        from ..llm.providers.registry import resolve_provider_key

        api_key, _ = resolve_provider_key("openai")
        client = openai.AsyncOpenAI(api_key=api_key or "")
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


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Gemini embeddings (gemini-embedding-001, Matryoshka-truncated to 768d)."""

    def __init__(self):
        self.model = "gemini-embedding-001"
        self._dims = 768

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google import genai

        from ..llm.providers.registry import resolve_provider_key

        api_key, _ = resolve_provider_key("gemini")
        client = genai.Client(api_key=api_key or "")
        batch_size = 100
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await client.aio.models.embed_content(
                model=self.model,
                contents=batch,
                config={"output_dimensionality": self._dims},
            )
            all_embeddings.extend([list(e.values) for e in resp.embeddings])
        return all_embeddings


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

    from ..llm.providers.registry import resolve_provider_key

    gemini_key, _ = resolve_provider_key("gemini")
    if gemini_key:
        _provider = GeminiEmbeddingProvider()
    elif await _check_ollama():
        _provider = OllamaEmbeddingProvider()
    else:
        openai_key, _ = resolve_provider_key("openai")
        if openai_key:
            _provider = OpenAIEmbeddingProvider()
        else:
            from ..llm.providers.base import ProviderError

            raise ProviderError(
                "embeddings",
                "No embedding backend configured. Add a Gemini/OpenAI key in "
                "Admin → LLMs, or start Ollama (bge-m3) locally.",
                503,
            )

    return _provider


def reset_embedding_provider() -> None:
    """Forget the cached provider (tests / key rotation)."""
    global _provider
    _provider = None
