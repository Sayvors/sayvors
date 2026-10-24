"""Embedding providers and the admin-managed embedding configuration.

The embedding backend is configured **apart** from the text-generation
providers: an admin picks the provider, the model and (optionally) its own
API key. That matters because the two are bought and rotated separately, and
because with pgvector the embedding model is load-bearing — vectors from
different models are not comparable, so the configured model decides which
stored chunks the vector search may score.

Without an active embedding configuration the code falls back to the
text-generation keys (Gemini → local Ollama → OpenAI), so an installation
that has not configured embeddings on purpose keeps working. The fallback is
logged, never silent.
"""
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMBED_CACHE_TTL = 86400 * 30

# Every provider is normalised to the same width. A pgvector column holds one
# dimension, and the previous mixed widths (1024 here, 768 for Gemini) is
# exactly what made the old JSON column skip chunks instead of searching
# them.
CANONICAL_DIMENSIONS = 1024

# The embedding models this codebase knows how to call, and that can be
# normalised to the canonical width. An admin picks from this list; a model
# outside it is rejected instead of being saved and silently mismatched.
EMBEDDING_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-embedding-001",),
    "openai": ("text-embedding-3-small", "text-embedding-3-large"),
    "ollama": ("bge-m3",),
    "openrouter": (
        "openai/text-embedding-3-small",
        "openai/text-embedding-3-large",
        "thenlper/gte-large",
    ),
    "nvidia": (
        "nvidia/nv-embed-v2",
        "nvidia/nv-embedqa-e5-v5",
        "nvidia/nv-embedqa-mistral-7b-v2",
    ),
}

# How long a built provider is reused before the configuration is re-read.
# Mirrors the LLM provider overlay: an admin save reaches one worker
# immediately, the others pick it up within the TTL.
PROVIDER_CACHE_SECONDS = 15.0

# Overridable in tests (defaults to the production session factory).
_session_factory = None

_provider: "EmbeddingProvider | None" = None
_provider_signature: str = ""
_provider_loaded_at: float = 0.0


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def dimensions(self) -> int:
        ...

    @property
    def model_tag(self) -> str:
        """Identity of the model that produced a vector.

        Vectors from different models are not comparable, so a chunk is only
        vector-searchable against a query built with the same model. The tag
        is stored on the chunk row and used as a filter.
        """
        return f"{self.__class__.__name__}:{self.model}"


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.model = model or EMBEDDING_MODELS["ollama"][0]
        self._dims = CANONICAL_DIMENSIONS
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        # Ollama needs no key; a configured one is accepted and ignored.
        self._api_key = api_key

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
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.model = model or EMBEDDING_MODELS["openai"][0]
        self._dims = CANONICAL_DIMENSIONS
        self._api_key = api_key

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        from ..llm.providers.registry import resolve_provider_key

        api_key = self._api_key or (resolve_provider_key("openai")[0] or "")
        if not api_key:
            raise RuntimeError(
                "No OpenAI embedding key configured. Add one under "
                "Admin → Embeddings, or in Admin → LLMs."
            )
        client = AsyncOpenAI(api_key=api_key)
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


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Gemini embeddings (gemini-embedding-001, truncated to the canonical width)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.model = model or EMBEDDING_MODELS["gemini"][0]
        self._dims = CANONICAL_DIMENSIONS
        self._api_key = api_key

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google import genai

        from ..llm.providers.registry import resolve_provider_key

        api_key = self._api_key or (resolve_provider_key("gemini")[0] or "")
        if not api_key:
            raise RuntimeError(
                "No Gemini embedding key configured. Add one under "
                "Admin → Embeddings, or in Admin → LLMs."
            )
        client = genai.Client(api_key=api_key)
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


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding provider (OpenRouter, NVIDIA Build, etc.).

    Reuses the OpenAI SDK with a custom base URL. The API key is resolved
    from the admin config or the LLM provider registry.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        default_model: str = "",
        default_base_url: str = "",
    ):
        self.model = model or default_model
        self._dims = CANONICAL_DIMENSIONS
        self._api_key = api_key
        self._base_url = base_url or default_base_url

    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        from ..llm.providers.registry import resolve_provider_key

        api_key = self._api_key
        if not api_key:
            # Try to resolve from LLM registry
            for provider_name in ("openrouter", "nvidia", "openai"):
                try:
                    key, _ = resolve_provider_key(provider_name)
                    if key:
                        api_key = key
                        break
                except Exception:
                    pass
        if not api_key:
            raise RuntimeError(
                "No API key configured. Add one under Admin → Embeddings."
            )

        client = AsyncOpenAI(api_key=api_key, base_url=self._base_url)
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


class OpenRouterEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    """OpenRouter embeddings (OpenAI-compatible)."""

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            default_model=EMBEDDING_MODELS["openrouter"][0],
            default_base_url="https://openrouter.ai/api/v1",
        )


class NvidiaEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    """NVIDIA Build embeddings (OpenAI-compatible, free tier available)."""

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            default_model=EMBEDDING_MODELS["nvidia"][0],
            default_base_url="https://integrate.api.nvidia.com/v1",
        )


# ── Configuration (admin-managed) ─────────────────────────────────────


@asynccontextmanager
async def _session():
    """A database session for the configuration reads.

    The caller may pass its own session (the admin endpoints do); this is
    the fallback for the search path, which has no session of its own.
    """
    if _session_factory is not None:
        async with _session_factory() as session:
            yield session
        return
    from ...database import async_session

    async with async_session() as session:
        yield session


def _decrypt(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        from ..channels.service import decrypt_token

        return decrypt_token(encrypted)
    except Exception:
        logger.warning("Embedding provider key could not be decrypted")
        return None


def _row_to_config(row) -> dict[str, Any]:
    """Public shape of a configuration row (never carries the key)."""
    return {
        "provider": row.provider,
        "model": row.model,
        "has_key": bool(row.key_encrypted),
        "enabled": bool(row.enabled),
        "active": bool(row.active),
        "base_url": row.base_url,
    }


def _row_to_internal(row) -> dict[str, Any]:
    return {**_row_to_config(row), "key": _decrypt(row.key_encrypted)}


async def _read_configs(db) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from .models import EmbeddingProviderConfig

    rows = (await db.execute(select(EmbeddingProviderConfig))).scalars().all()
    return [_row_to_config(row) for row in rows]


async def _read_active(db) -> dict[str, Any] | None:
    from sqlalchemy import select

    from .models import EmbeddingProviderConfig

    row = (
        (
            await db.execute(
                select(EmbeddingProviderConfig).where(
                    EmbeddingProviderConfig.active.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    return _row_to_internal(row) if row is not None else None


async def _read_one(db, provider: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from .models import EmbeddingProviderConfig

    row = (
        (
            await db.execute(
                select(EmbeddingProviderConfig).where(
                    EmbeddingProviderConfig.provider == provider
                )
            )
        )
        .scalars()
        .first()
    )
    return _row_to_internal(row) if row is not None else None


async def list_embedding_configs(db=None) -> list[dict[str, Any]]:
    """Every configured embedding provider (admin view, no key material)."""
    if db is not None:
        return await _read_configs(db)
    async with _session() as session:
        return await _read_configs(session)


async def get_active_embedding_config(db=None) -> dict[str, Any] | None:
    """The active embedding provider (with its decrypted key), or None."""
    if db is not None:
        return await _read_active(db)
    async with _session() as session:
        return await _read_active(session)


async def save_embedding_config(
    provider: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    enabled: bool | None = None,
    activate: bool = False,
    db=None,
) -> dict[str, Any]:
    """Store an embedding provider configuration.

    ``api_key`` of None keeps the stored key, an empty string clears it.
    """
    KNOWN_PROVIDERS = set(EMBEDDING_MODELS) | {"openrouter", "nvidia"}
    if provider not in KNOWN_PROVIDERS:
        raise ValueError(f"Unknown embedding provider: {provider}. Known: {', '.join(sorted(KNOWN_PROVIDERS))}")
    # Model is free-form: the admin picks from a live list fetched from the
    # provider's API, so we no longer hardcode or validate model names.

    from sqlalchemy import select

    from .models import EmbeddingProviderConfig

    async def _save(session) -> dict[str, Any]:
        row = (
            (
                await session.execute(
                    select(EmbeddingProviderConfig).where(
                        EmbeddingProviderConfig.provider == provider
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = EmbeddingProviderConfig(provider=provider, enabled=True, active=False)
            session.add(row)
        if model is not None:
            row.model = model
        if api_key is not None:
            if api_key:
                from ..channels.service import encrypt_token

                row.key_encrypted = encrypt_token(api_key)
            else:
                row.key_encrypted = None
        if base_url is not None:
            row.base_url = base_url or None
        if enabled is not None:
            row.enabled = enabled
        if activate:
            # Exactly one active provider: vectors from two models cannot be
            # compared, so a half-switched state would silently drop results.
            for other in (
                (await session.execute(select(EmbeddingProviderConfig)))
                .scalars()
                .all()
            ):
                if other.provider != provider:
                    other.active = False
            row.active = True
        await session.commit()
        return _row_to_config(row)

    if db is not None:
        result = await _save(db)
    else:
        async with _session() as session:
            result = await _save(session)
    reset_embedding_provider()
    return result


async def corpus_stats(db=None) -> dict[str, int]:
    """How many chunks exist and how many of them carry a vector."""
    from sqlalchemy import func, select

    from .models import DocumentChunk

    async def _stats(session) -> dict[str, int]:
        total = int(
            (
                await session.execute(
                    select(func.count()).select_from(DocumentChunk)
                )
            ).scalar_one()
            or 0
        )
        with_vector = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.embedding_vector.is_not(None))
                )
            ).scalar_one()
            or 0
        )
        return {"chunks_total": total, "chunks_with_vector": with_vector}

    if db is not None:
        return await _stats(db)
    async with _session() as session:
        return await _stats(session)


# ── Provider selection ────────────────────────────────────────────────


async def _check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _config_signature(config: dict[str, Any] | None) -> str:
    if not config:
        return "fallback"
    key = config.get("key") or ""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else "none"
    return (
        f"{config.get('provider')}:{config.get('model')}:{digest}:{config.get('base_url')}"
    )


async def _build_provider(config: dict[str, Any] | None) -> EmbeddingProvider:
    """Build the provider for a configuration row (or the legacy fallback)."""
    if not config:
        from ..llm.providers.registry import resolve_provider_key

        gemini_key, _ = resolve_provider_key("gemini")
        if gemini_key:
            logger.warning(
                "No embedding provider configured separately; falling back to "
                "the text-generation Gemini key. Configure one under "
                "Admin → Embeddings."
            )
            return GeminiEmbeddingProvider()
        if await _check_ollama():
            logger.warning(
                "No embedding provider configured separately; falling back to "
                "the local Ollama embedding model. Configure one under "
                "Admin → Embeddings."
            )
            return OllamaEmbeddingProvider()
        openai_key, _ = resolve_provider_key("openai")
        if openai_key:
            logger.warning(
                "No embedding provider configured separately; falling back to "
                "the text-generation OpenAI key. Configure one under "
                "Admin → Embeddings."
            )
            return OpenAIEmbeddingProvider()
        return OllamaEmbeddingProvider()

    provider = config["provider"]
    model = config.get("model")
    key = config.get("key")
    base_url = config.get("base_url")
    if provider == "gemini":
        return GeminiEmbeddingProvider(api_key=key, model=model)
    if provider == "openai":
        return OpenAIEmbeddingProvider(api_key=key, model=model)
    if provider == "ollama":
        return OllamaEmbeddingProvider(api_key=key, base_url=base_url, model=model)
    if provider == "openrouter":
        return OpenRouterEmbeddingProvider(api_key=key, base_url=base_url, model=model)
    if provider == "nvidia":
        return NvidiaEmbeddingProvider(api_key=key, base_url=base_url, model=model)
    raise ValueError(f"Unknown embedding provider: {provider}")


async def get_embedding_provider() -> EmbeddingProvider:
    """The provider the search path uses.

    Reads the active embedding configuration (cached for a few seconds) and
    builds the matching provider. A configured provider without its own key
    falls back to the text-generation key of the same provider, so an
    operator can start with a model only and add the dedicated key later.
    """
    global _provider, _provider_signature, _provider_loaded_at

    now = time.monotonic()
    if (
        _provider is not None
        and (now - _provider_loaded_at) < PROVIDER_CACHE_SECONDS
    ):
        return _provider

    config = await get_active_embedding_config()
    if (
        config
        and not config.get("key")
        and config.get("provider") != "ollama"
    ):
        from ..llm.providers.registry import resolve_provider_key

        chat_key, _ = resolve_provider_key(config["provider"])
        if chat_key:
            logger.warning(
                "Embedding provider %s has no dedicated key; using the "
                "text-generation key of the same provider.",
                config["provider"],
            )
            config = {**config, "key": chat_key}

    signature = _config_signature(config)
    if _provider is None or signature != _provider_signature:
        _provider = await _build_provider(config)
        _provider_signature = signature
    _provider_loaded_at = now
    return _provider


async def list_available_models(provider: str, api_key: str | None = None, base_url: str | None = None) -> list[str]:
    """Fetch available embedding models from a provider's API.

    Used by the admin UI to populate a model dropdown. Falls back to the
    known model list if the API is unreachable.
    """
    import httpx

    if provider == "ollama":
        url = (base_url or "http://localhost:11434").rstrip("/") + "/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                embed = [m for m in models if "embed" in m.lower() or "bge" in m.lower() or "e5" in m.lower()]
                return embed if embed else models
        except Exception:
            return list(EMBEDDING_MODELS.get(provider, ()))

    if provider in ("openai", "openrouter", "nvidia"):
        url_map = {
            "openai": "https://api.openai.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "nvidia": "https://integrate.api.nvidia.com/v1",
        }
        base = (base_url or url_map.get(provider, "")).rstrip("/")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{base}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                embed = [m for m in models if "embed" in m.lower() or "bge" in m.lower() or "e5" in m.lower()]
                return embed if embed else models[:20]
        except Exception:
            return list(EMBEDDING_MODELS.get(provider, ()))

    if provider == "gemini":
        try:
            from google import genai

            client = genai.Client(api_key=api_key or "")
            models = []
            for m in client.models.list():
                name = getattr(m, "name", "") or ""
                if "embed" in name.lower():
                    models.append(name)
            return models if models else list(EMBEDDING_MODELS.get(provider, ()))
        except Exception:
            return list(EMBEDDING_MODELS.get(provider, ()))

    return list(EMBEDDING_MODELS.get(provider, ()))



async def test_embedding_provider(
    provider: str | None = None, db=None
) -> dict[str, Any]:
    """Embed a sample string and report what came back."""
    started = time.perf_counter()

    async def _run(session) -> dict[str, Any]:
        if provider:
            if provider not in EMBEDDING_MODELS:
                raise ValueError(f"Unknown embedding provider: {provider}")
            config = await _read_one(session, provider)
            if config is None:
                config = {
                    "provider": provider,
                    "model": EMBEDDING_MODELS[provider][0],
                    "has_key": False,
                    "enabled": True,
                    "active": False,
                    "base_url": None,
                    "key": None,
                }
        else:
            config = await _read_active(session)

        try:
            embedding_provider = await _build_provider(config)
            vectors = await embedding_provider.embed(
                ["Sayvors embedding health check"]
            )
            dimensions = len(vectors[0]) if vectors else 0
            latency_ms = int((time.perf_counter() - started) * 1000)
            ok = dimensions == CANONICAL_DIMENSIONS
            return {
                "ok": ok,
                "provider": (config or {}).get("provider"),
                "model": embedding_provider.model,
                "dimensions": dimensions,
                "latency_ms": latency_ms,
                "detail": (
                    "Embedding API answered with the canonical width."
                    if ok
                    else f"Expected {CANONICAL_DIMENSIONS} dimensions, "
                    f"got {dimensions}."
                ),
            }
        except Exception as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "provider": (config or {}).get("provider"),
                "model": (config or {}).get("model"),
                "dimensions": 0,
                "latency_ms": latency_ms,
                "detail": str(e)[:300],
            }

    if db is not None:
        return await _run(db)
    async with _session() as session:
        return await _run(session)


def reset_embedding_provider() -> None:
    """Forget the cached provider (tests / key rotation)."""
    global _provider, _provider_signature, _provider_loaded_at
    _provider = None
    _provider_signature = ""
    _provider_loaded_at = 0.0


def canonical_vector(values: list[float] | None) -> list[float] | None:
    """Return the vector only when it has the canonical width.

    A provider that answers with a different width would produce vectors the
    pgvector column cannot hold. Dropping them keeps the corpus consistent:
    the chunk stays searchable by keyword instead of failing the write.
    """
    if not values:
        return None
    if len(values) != CANONICAL_DIMENSIONS:
        logger.warning(
            "Embedding width %s is not the canonical %s; storing the chunk "
            "without a vector",
            len(values),
            CANONICAL_DIMENSIONS,
        )
        return None
    return [float(value) for value in values]
