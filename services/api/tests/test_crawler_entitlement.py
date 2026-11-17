"""Website crawling is Enterprise-only.

The UI hides the card, but the API is the real gate. These tests prove a
free-trial tenant cannot discover or create a crawl source, and that a denial
carries the machine-readable upgrade header.
"""
from app.modules.billing.features import FEATURE_KEYS, default_features


def test_crawler_is_a_catalog_feature_off_by_default():
    assert "crawler" in FEATURE_KEYS
    assert default_features()["crawler"] is False


async def test_free_trial_cannot_preview_a_website(client):
    resp = client.get(
        "/api/v1/rag/databanks/any-databank/crawl/preview",
        params={"url": "https://example.com"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.headers.get("X-Entitlement-Denied") == "crawler"


async def test_free_trial_cannot_create_a_crawl_source(client):
    resp = client.post(
        "/api/v1/rag/databanks/any-databank/crawl/sources",
        json={"url": "https://example.com", "scope": "subtree", "max_pages": 10},
    )
    assert resp.status_code == 403, resp.text
    # The databank gate is evaluated first for a free-trial tenant; either
    # denial is correct here. The preview test above isolates the crawler key.
    assert resp.headers.get("X-Entitlement-Denied") in ("crawler", "databank")


async def test_reading_existing_crawl_sources_stays_open(client):
    # A tenant who loses the entitlement must still be able to inspect and
    # clean up what they already crawled.
    resp = client.get("/api/v1/rag/databanks/any-databank/crawl/sources")
    assert resp.status_code != 403
