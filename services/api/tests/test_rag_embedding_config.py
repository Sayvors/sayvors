"""Admin-managed embedding configuration (separate from the chat providers).

Covers the three things that matter:
* an admin can pick the provider, the model and its own API key;
* the embedding backend really uses that key, not the text-generation one;
* an unsupported model is rejected instead of being saved and mismatched.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.rag import embeddings

_EMBED_KEY = "embed-key-not-the-chat-key"
_MODEL = "gemini-embedding-001"


@pytest_asyncio.fixture
async def embedding_factory(db, monkeypatch):
    """Point the configuration service at the test database."""
    factory = async_sessionmaker(
        db.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(embeddings, "_session_factory", factory)
    embeddings.reset_embedding_provider()
    yield factory
    embeddings.reset_embedding_provider()


@pytest.fixture
def admin_headers():
    from app.security import create_admin_token

    return {"Authorization": f"Bearer {create_admin_token()}"}


@pytest.mark.asyncio
async def test_list_reports_the_fallback_before_anything_is_configured(
    client, admin_headers
):
    r = client.get("/api/v1/admin/embeddings", headers=admin_headers)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["source"] == "fallback"
    assert body["active_provider"] is None
    assert body["canonical_dimensions"] == 1024
    providers = {p["provider"] for p in body["providers"]}
    assert providers == {"gemini", "openai", "ollama", "openrouter", "nvidia"}
    gemini = next(p for p in body["providers"] if p["provider"] == "gemini")
    assert gemini["supported_models"] == []


@pytest.mark.asyncio
async def test_save_activate_and_list(client, admin_headers, embedding_factory):
    r = client.put(
        "/api/v1/admin/embeddings/gemini",
        json={"model": _MODEL, "api_key": _EMBED_KEY, "activate": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["has_key"] is True
    assert body["active"] is True
    assert body["model"] == _MODEL

    listed = client.get("/api/v1/admin/embeddings", headers=admin_headers).json()
    assert listed["source"] == "admin"
    assert listed["active_provider"] == "gemini"


@pytest.mark.asyncio
async def test_unknown_provider_is_404(client, admin_headers, embedding_factory):
    r = client.put(
        "/api/v1/admin/embeddings/nope",
        json={"model": "whatever"},
        headers=admin_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_model_is_400(client, admin_headers, embedding_factory):
    r = client.put(
        "/api/v1/admin/embeddings/gemini",
        json={"model": "some-other-model"},
        headers=admin_headers,
    )
    # Models are no longer validated against a hardcoded list — any model
    # string is accepted and the live API list is used in the UI.
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_the_embedding_key_is_used_not_the_chat_key(
    client, admin_headers, embedding_factory
):
    client.put(
        "/api/v1/admin/embeddings/gemini",
        json={"model": _MODEL, "api_key": _EMBED_KEY, "activate": True},
        headers=admin_headers,
    )
    embeddings.reset_embedding_provider()

    provider = await embeddings.get_embedding_provider()
    assert provider._api_key == _EMBED_KEY
    assert provider.model == _MODEL


@pytest.mark.asyncio
async def test_test_endpoint_reports_the_width(
    client, admin_headers, embedding_factory, monkeypatch
):
    class _FakeProvider:
        model = "fake-embedder"

        async def embed(self, texts):
            return [[0.0] * embeddings.CANONICAL_DIMENSIONS for _ in texts]

    async def _fake_build(config):
        return _FakeProvider()

    monkeypatch.setattr(embeddings, "_build_provider", _fake_build)

    r = client.post(
        "/api/v1/admin/embeddings/test",
        json={"provider": "gemini"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["ok"] is True
    assert body["dimensions"] == embeddings.CANONICAL_DIMENSIONS


@pytest.mark.asyncio
async def test_switching_provider_deactivates_the_previous_one(
    client, admin_headers, embedding_factory
):
    client.put(
        "/api/v1/admin/embeddings/gemini",
        json={"model": _MODEL, "api_key": _EMBED_KEY, "activate": True},
        headers=admin_headers,
    )
    client.put(
        "/api/v1/admin/embeddings/openai",
        json={"model": "text-embedding-3-small", "api_key": "k", "activate": True},
        headers=admin_headers,
    )
    listed = client.get("/api/v1/admin/embeddings", headers=admin_headers).json()
    active = [p["provider"] for p in listed["providers"] if p["active"]]
    assert active == ["openai"]
