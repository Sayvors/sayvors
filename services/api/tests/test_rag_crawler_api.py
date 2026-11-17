"""Crawl source API (§31 Phase 1): preview, create-with-selection, list, pages,
update, delete — all tenant-scoped and gated by the databank plan feature.
"""
import pytest
from sqlalchemy import select

from app.main import app as fastapi_app
from app.modules.rag.models import CrawlPage, CrawlSource, Databank
from app.modules.rag.router import require_crawler_feature, require_databank_feature

_BANK = "crawl-api-bank-0001"
_USER = "test-user-0000-0000-0000-000000000001"


async def _seed_bank(db, user_id=_USER) -> str:
    db.add(Databank(id=_BANK, user_id=user_id, name="Crawl API Bank"))
    await db.commit()
    return _BANK


@pytest.fixture
def allow_databank_gate(client):
    # Depends on `client` so this override lands AFTER the client fixture
    # cleared the app's dependency overrides. Crawler is now Enterprise-only,
    # so these tests must also allow that gate to exercise the real endpoints.
    async def _allow():
        return None

    for gate in (require_databank_feature, require_crawler_feature):
        fastapi_app.dependency_overrides[gate] = _allow
    yield
    for gate in (require_databank_feature, require_crawler_feature):
        fastapi_app.dependency_overrides.pop(gate, None)


@pytest.fixture
def allow_crawler(client, monkeypatch):
    """The preview endpoints call check_feature directly (no dependency)."""
    async def _allow(*args, **kwargs):
        return None

    monkeypatch.setattr("app.modules.billing.entitlements.check_feature", _allow)
    yield


@pytest.mark.asyncio
async def test_preview_lists_candidates_without_writes(client, allow_crawler, db, monkeypatch):
    await _seed_bank(db)

    def _fake(url, scope="subtree", max_pages=100, fetcher=None):
        return [
            type("C", (), {"url": "https://example.com/", "title": "Home", "status": "discovered"})(),
            type("C", (), {"url": "https://example.com/services", "title": "Services", "status": "discovered"})(),
        ]

    monkeypatch.setattr("app.modules.rag.router.preview_candidates", _fake)
    res = client.get(
        f"/api/v1/rag/databanks/{_BANK}/crawl/preview",
        params={"url": "https://example.com", "scope": "subtree", "max_pages": 50},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["candidates"]) == 2
    assert body["candidates"][0]["url"] == "https://example.com/"
    # Preview must not persist anything.
    assert (await db.execute(select(CrawlSource))).scalars().all() == []


@pytest.mark.asyncio
async def test_standalone_preview_requires_no_databank(client, allow_crawler, db, user_id, monkeypatch):
    """The wizard previews before the bank exists — /crawl/preview is auth-only."""
    from app.core.deps import get_current_user
    from app.modules.rag import router as rag_router

    def _fake(url, scope="subtree", max_pages=100, fetcher=None):
        return [
            type("C", (), {"url": "https://example.com/", "title": "Home", "status": "discovered"})(),
        ]

    monkeypatch.setattr("app.modules.rag.router.preview_candidates", _fake)
    # The standalone preview authenticates without a long-lived DB session,
    # so it has its own dependency — override it the same way as get_current_user.
    from app.modules.users.models import User as _User

    async def _override_preview_auth():
        return _User(
            id=user_id,
            email="test@sayvors.com",
            first_name="Test",
            last_name="User",
            password_hash="x",
            onboarded=True,
        )

    fastapi_app.dependency_overrides[rag_router._authenticate_preview_user] = _override_preview_auth
    try:
        res = client.get(
            "/api/v1/rag/crawl/preview",
            params={"url": "https://example.com", "scope": "subtree", "max_pages": 50},
        )
    finally:
        fastapi_app.dependency_overrides.pop(rag_router._authenticate_preview_user, None)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["candidates"][0]["url"] == "https://example.com/"
    # No databank was created by this.
    assert (await db.execute(select(Databank))).scalars().all() == []


@pytest.mark.asyncio
async def test_create_source_with_selected_pages(client, db, allow_databank_gate):
    from sqlalchemy import select

    await _seed_bank(db)
    res = client.post(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources",
        json={
            "url": "https://example.com",
            "scope": "subtree",
            "max_pages": 50,
            "urls": [
                "https://example.com/",
                "https://example.com/services?utm_source=x",
                "https://other.com/not-same-origin",
                "https://example.com/services?utm_source=x",  # duplicate of #2
            ],
            "sync_enabled": False,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["page_count"] == 2  # deduped + cross-origin dropped, both normalized
    source_id = body["id"]

    pages = (await db.execute(
        select(CrawlPage).where(CrawlPage.source_id == source_id)
    )).scalars().all()
    urls = {p.url for p in pages}
    assert urls == {"https://example.com/", "https://example.com/services"}
    assert all(p.status == "discovered" for p in pages)
    # Phase A: hreflang grouping computed at selection time. These URLs have
    # no /en|/ar prefix, so lang stays None until the crawl detects script.
    assert all(p.variant_group == "/services" for p in pages if p.url.endswith("/services"))
    assert all(p.lang is None for p in pages if p.url.endswith("/services"))


@pytest.mark.asyncio
async def test_list_sources_with_page_counts(client, db, allow_databank_gate):
    await _seed_bank(db)
    created = client.post(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources",
        json={"url": "https://example.com", "urls": ["https://example.com/"]},
    )
    assert created.status_code == 201, created.text

    res = client.get(f"/api/v1/rag/databanks/{_BANK}/crawl/sources")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["sources"][0]["page_count"] == 1
    assert body["sources"][0]["start_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_source_pages_endpoint_returns_selection(client, db, allow_databank_gate):
    await _seed_bank(db)
    created = client.post(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources",
        json={
            "url": "https://example.com",
            "urls": ["https://example.com/", "https://example.com/about"],
        },
    )
    source_id = created.json()["id"]

    res = client.get(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources/{source_id}/pages"
    )
    assert res.status_code == 200, res.text
    urls = [p["url"] for p in res.json()]
    assert urls == ["https://example.com/", "https://example.com/about"]


@pytest.mark.asyncio
async def test_update_source_enables_sync(client, db, allow_databank_gate):
    await _seed_bank(db)
    created = client.post(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources",
        json={"url": "https://example.com", "urls": ["https://example.com/"]},
    )
    source_id = created.json()["id"]

    res = client.patch(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources/{source_id}",
        json={"sync_enabled": True, "sync_interval_minutes": 120},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sync_enabled"] is True
    assert body["sync_interval_minutes"] == 120
    assert body["next_sync_at"] is not None


@pytest.mark.asyncio
async def test_delete_source_removes_pages(client, db, allow_databank_gate):
    from sqlalchemy import select

    await _seed_bank(db)
    created = client.post(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources",
        json={"url": "https://example.com", "urls": ["https://example.com/"]},
    )
    source_id = created.json()["id"]

    res = client.delete(
        f"/api/v1/rag/databanks/{_BANK}/crawl/sources/{source_id}"
    )
    assert res.status_code == 204, res.text
    assert (await db.execute(
        select(CrawlSource).where(CrawlSource.id == source_id)
    )).scalars().all() == []
    assert (await db.execute(
        select(CrawlPage).where(CrawlPage.source_id == source_id)
    )).scalars().all() == []


@pytest.mark.asyncio
async def test_source_is_tenant_scoped(client, db, allow_databank_gate, other_user_id):
    from app.modules.users.models import User

    await _seed_bank(db)
    # A different user's databank must be invisible to the test user.
    other_bank = "crawl-api-bank-other"
    db.add(Databank(id=other_bank, user_id=other_user_id, name="Other"))
    await db.commit()

    res = client.post(
        f"/api/v1/rag/databanks/{other_bank}/crawl/sources",
        json={"url": "https://other.com", "urls": ["https://other.com/"]},
    )
    assert res.status_code == 404
