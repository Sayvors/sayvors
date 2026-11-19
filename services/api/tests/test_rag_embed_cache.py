"""The shared query-embedding cache is model-aware and actually used.

Before P3, rag/cache.py defined get/set_cached_embedding and nothing called
them: every "price?" re-embedded on every message. The cache is keyed by the
embedding model as well as the text, because a vector from model A must never
be paired with chunks tagged model B.
"""
import pytest

from app.modules.rag import cache, embeddings


class _FakeProvider:
    def __init__(self, model="test:embedder"):
        self.model_tag = model
        self.calls = 0

    async def embed(self, texts, **kwargs):
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture
def fake_cache(monkeypatch):
    """In-process stand-in for Redis, preserving the model-aware key logic."""
    store: dict[str, object] = {}
    counters: dict[str, int] = {"hits": 0, "misses": 0}

    async def _get(text, *, model=None):
        return store.get(cache._embedding_cache_key(text, model))

    async def _set(text, vector, *, model=None):
        store[cache._embedding_cache_key(text, model)] = vector

    async def _note(*, hit):
        counters["hits" if hit else "misses"] += 1

    monkeypatch.setattr(cache, "get_cached_embedding", _get)
    monkeypatch.setattr(cache, "set_cached_embedding", _set)
    monkeypatch.setattr(cache, "note_embed_cache_result", _note)
    return store, counters


@pytest.mark.asyncio
async def test_repeated_question_embeds_once(monkeypatch, fake_cache):
    provider = _FakeProvider()

    async def _provider():
        return provider

    monkeypatch.setattr(embeddings, "get_embedding_provider", _provider)

    first = await embeddings.embed_query("how much is the 1kg?")
    second = await embeddings.embed_query("how much is the 1kg?")

    assert first == second == ([0.1, 0.2, 0.3], "test:embedder")
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_a_model_switch_is_a_cache_miss(monkeypatch, fake_cache):
    provider = _FakeProvider()

    async def _provider():
        return provider

    monkeypatch.setattr(embeddings, "get_embedding_provider", _provider)
    await embeddings.embed_query("price?")

    provider.model_tag = "other:embedder"
    vector, model = await embeddings.embed_query("price?")

    assert model == "other:embedder"
    assert provider.calls == 2, "stale vectors from another model must not be reused"


@pytest.mark.asyncio
async def test_hits_and_misses_are_counted(monkeypatch, fake_cache):
    store, counters = fake_cache
    provider = _FakeProvider()

    async def _provider():
        return provider

    monkeypatch.setattr(embeddings, "get_embedding_provider", _provider)
    await embeddings.embed_query("price?")
    await embeddings.embed_query("price?")
    assert counters == {"hits": 1, "misses": 1}


@pytest.mark.asyncio
async def test_corrupt_cache_entry_is_a_miss(monkeypatch):
    """A bad value must not silence retrieval — delete it and re-embed."""
    deleted: list[str] = []

    class _Redis:
        async def get(self, key):
            return b'{"not": "a vector"}'

        async def delete(self, key):
            deleted.append(key)

    async def _redis():
        return _Redis()

    monkeypatch.setattr(cache, "get_redis", _redis)
    assert await cache.get_cached_embedding("price?", model="m") is None
    assert deleted
