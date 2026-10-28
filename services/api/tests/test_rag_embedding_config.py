"""Admin-managed embedding configuration (separate from the chat providers).

Covers the three things that matter:
* an admin can pick the provider, the model and its own API key;
* the embedding backend really uses that key, not the text-generation one;
* model names are never hardcoded — the provider's live list is the only
  source, and a provider with no saved model fails closed.
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
    # No model list is shipped with the code: the dropdown is filled from the
    # provider's API, so an unconfigured provider has no models to report.
    assert "supported_models" not in gemini


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
async def test_free_form_model_is_accepted(client, admin_headers, embedding_factory):
    r = client.put(
        "/api/v1/admin/embeddings/gemini",
        json={"model": "some-other-model"},
        headers=admin_headers,
    )
    # Models are never validated against a hardcoded list — the admin picks
    # from the provider's live list (or types a name it added recently), and
    # the provider rejects genuinely invalid names.
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


@pytest.mark.asyncio
async def test_provider_without_a_saved_model_fails_closed(embedding_factory):
    """No hardcoded default may stand in for the admin's choice."""
    with pytest.raises(RuntimeError, match="No embedding model configured"):
        await embeddings._build_provider(
            {"provider": "gemini", "model": None, "key": "k", "base_url": None}
        )


@pytest.mark.asyncio
async def test_test_endpoint_reports_an_unconfigured_provider(
    client, admin_headers, embedding_factory
):
    r = client.post(
        "/api/v1/admin/embeddings/test",
        json={"provider": "gemini"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["ok"] is False
    assert "No embedding model configured" in body["detail"]


@pytest.mark.asyncio
async def test_model_list_surfaces_provider_errors(
    client, admin_headers, monkeypatch
):
    """A failed fetch must not look like a provider with zero models."""

    async def _boom(provider, api_key=None, base_url=None):
        raise RuntimeError("provider rejected the key")

    monkeypatch.setattr(embeddings, "list_available_models", _boom)

    r = client.get(
        "/api/v1/admin/embeddings/models?provider=openai", headers=admin_headers
    )
    assert r.status_code == 502
    assert "provider rejected the key" in r.json()["detail"]


@pytest.mark.asyncio
async def test_model_list_rejects_an_unknown_provider(client, admin_headers):
    r = client.get(
        "/api/v1/admin/embeddings/models?provider=nope", headers=admin_headers
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_model_list_uses_the_saved_key(
    client, admin_headers, embedding_factory, monkeypatch
):
    """Refreshing must work without re-pasting a stored key.

    This is the regression that left the dropdown empty: the endpoint used to
    forward only the query-string key, so every refresh of a configured
    provider was sent unauthenticated.
    """
    client.put(
        "/api/v1/admin/embeddings/openai",
        json={
            "model": "text-embedding-3-small",
            "api_key": "stored-embed-key",
            "base_url": "https://proxy.example/v1",
        },
        headers=admin_headers,
    )
    seen: dict = {}

    async def _capture(provider, api_key=None, base_url=None):
        seen.update(provider=provider, api_key=api_key, base_url=base_url)
        return ["text-embedding-3-small"]

    monkeypatch.setattr(embeddings, "list_available_models", _capture)

    r = client.get(
        "/api/v1/admin/embeddings/models?provider=openai", headers=admin_headers
    )
    assert r.status_code == 200, r.text[:300]
    assert seen == {
        "provider": "openai",
        "api_key": "stored-embed-key",
        "base_url": "https://proxy.example/v1",
    }
