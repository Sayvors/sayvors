"""Crawler core (§31 Phase 1): politeness, sitemap/BFS discovery, conditional GET.

Runs against a scripted FakeSite served through an injected fetcher, so no
real network is touched: robots.txt handling, ETag 304 reuse, tracking-param
normalization, same-origin filtering, and the circuit breaker are all pinned.
"""
import pytest

from app.modules.rag.crawler import (
    BREAKER_COOLDOWN_SECONDS,
    CrawlResult,
    RobotsRules,
    crawl_site,
    normalize_url,
    same_origin,
)
from app.modules.rag.models import Databank, Document


@pytest.fixture(autouse=True)
def _public_dns_for_crawler_tests(monkeypatch):
    """Every crawl entry-point validates the start URL via
    ``assert_public_http_url``, which resolves hostnames. Keep these tests
    network-free: any host resolves to one public IP (nothing is ever
    actually fetched — the FakeSite fetcher replaces the HTTP layer)."""
    monkeypatch.setattr(
        "app.core.http.resolve_public_ips", lambda host: ["93.184.216.34"]
    )


class FakeSite:
    """Minimal scripted site: robots.txt, optional sitemap, pages keyed by path."""

    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.robots = ""
        self.sitemap: str | None = None
        self.requests: list[str] = []

    def add_page(self, path: str, html: str, etag: str = 'W/"v1"'):
        self.pages[path] = {"html": html, "etag": etag}

    def __call__(self, url, *, etag=None, last_modified=None):
        self.requests.append(url)
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url)
        if parsed.path == "/robots.txt":
            return (200, {"content-type": "text/plain"}, self.robots.encode())
        if parsed.path == "/sitemap.xml" and self.sitemap is not None:
            return (200, {"content-type": "application/xml"}, self.sitemap.encode())
        page = self.pages.get(parsed.path)
        if page is None:
            return (404, {"content-type": "text/html"}, b"")
        if etag and etag == page["etag"]:
            return (304, {"etag": page["etag"]}, b"")
        return (
            200,
            {"content-type": "text/html", "etag": page["etag"]},
            page["html"].encode(),
        )


_PAGE_TMPL = """<!doctype html><html><head><title>{title}</title></head><body>
<h1>{title}</h1><p>{body}</p><a href="{link}">next</a></body></html>"""


def _site_with_home_and_services():
    site = FakeSite()
    site.add_page("/", _PAGE_TMPL.format(title="Home", body="Welcome to Acme", link="/services"))
    site.add_page("/services", _PAGE_TMPL.format(title="Services", body="We fix things", link="/about"))
    site.add_page("/about", _PAGE_TMPL.format(title="About", body="Our story", link="/"))
    return site


# ── URL normalization ──────────────────────────────────────────

def test_normalize_url_strips_fragment_tracking_and_default_port():
    assert normalize_url("https://Example.com:443/path?utm_source=x&a=1#frag") == \
        "https://example.com/path?a=1"


def test_normalize_url_requires_http_scheme():
    with pytest.raises(ValueError):
        normalize_url("ftp://example.com/file")


def test_same_origin():
    assert same_origin("https://example.com/a", "https://example.com/b")
    assert not same_origin("https://example.com/a", "https://www.example.com/b")


# ── Language-variant grouping (Phase A) ─────────────────────────

def test_variant_group_pairs_hreflang_twins():
    from app.modules.rag.crawler import variant_group

    assert variant_group("https://example.com/en/pricing") == \
        variant_group("https://example.com/ar/pricing") == "/pricing"
    assert variant_group("https://example.com/en/blog/post-1") == \
        variant_group("https://example.com/ar/blog/post-1") == "/blog/post-1"


def test_variant_group_unprefixed_and_root():
    from app.modules.rag.crawler import variant_group

    assert variant_group("https://example.com/about") == "/about"
    assert variant_group("https://example.com/") == "/"
    assert variant_group("https://example.com/en") == "/"


def test_path_lang_reads_prefix():
    from app.modules.rag.crawler import path_lang

    assert path_lang("https://example.com/en/pricing") == "en"
    assert path_lang("https://example.com/ar") == "ar"
    assert path_lang("https://example.com/about") is None


# ── Crawl behavior ─────────────────────────────────────────────

def test_crawl_site_subtree_returns_crawled_pages():
    site = _site_with_home_and_services()
    results = crawl_site("https://example.com/", scope="subtree", max_pages=10,
                         fetcher=site)
    statuses = {r.status for r in results}
    assert statuses == {"crawled"}
    by_url = {r.url: r for r in results}
    home = by_url["https://example.com/"]
    assert home.title == "Home"
    assert home.word_count > 0
    assert home.content_hash
    assert len(home.content_hash) == 64
    assert home.etag == 'W/"v1"'


def test_crawl_site_single_scope_only_fetches_start_url():
    site = _site_with_home_and_services()
    results = crawl_site("https://example.com/", scope="single", max_pages=10,
                         fetcher=site)
    assert [r.url for r in results] == ["https://example.com/"]
    # robots.txt + exactly the one page — no discovery of other pages.
    assert len(site.requests) == 2
    assert results[0].status == "crawled"


def test_crawl_site_unchanged_when_etag_reused():
    site = _site_with_home_and_services()
    first = crawl_site("https://example.com/", scope="subtree", max_pages=10,
                       fetcher=site)
    known = {r.url: (r.etag, r.last_modified) for r in first if r.status == "crawled"}
    second = crawl_site("https://example.com/", scope="subtree", max_pages=10,
                        known=known, fetcher=site)
    assert all(r.status == "unchanged" for r in second)


def test_crawl_site_respects_robots_disallow():
    site = _site_with_home_and_services()
    site.robots = "User-agent: *\nDisallow: /services\n"
    results = crawl_site("https://example.com/", scope="subtree", max_pages=10,
                         fetcher=site)
    urls = {r.url for r in results}
    assert "https://example.com/services" not in urls
    assert "https://example.com/" in urls


def test_crawl_site_uses_sitemap_discovery():
    site = FakeSite()
    site.add_page("/", _PAGE_TMPL.format(title="Home", body="Home", link="/"))
    site.add_page("/pricing", _PAGE_TMPL.format(title="Pricing", body="Prices", link="/"))
    site.sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/</loc></url>"
        "<url><loc>https://example.com/pricing?utm_source=campaign</loc></url>"
        "</urlset>"
    )
    results = crawl_site("https://example.com/", scope="top", max_pages=10,
                         fetcher=site)
    urls = {r.url for r in results}
    assert urls == {"https://example.com/", "https://example.com/pricing"}


def test_crawl_site_tracking_params_dedup():
    site = FakeSite()
    site.add_page("/", _PAGE_TMPL.format(title="Home", body="Home", link="/?utm_source=1"))
    results = crawl_site("https://example.com/", scope="subtree", max_pages=10,
                         fetcher=site)
    assert len([r for r in results if r.url == "https://example.com/"]) == 1


def test_crawl_site_circuit_breaker_pauses_failing_domain():
    site = FakeSite()
    site.add_page("/", "<html><body>x</body></html>")

    def failing_fetcher(url, *, etag=None, last_modified=None):
        site.requests.append(url)
        return (500, {"content-type": "text/html"}, b"")

    results = crawl_site("https://example.com/", scope="subtree", max_pages=50,
                         fetcher=failing_fetcher)
    assert all(r.status == "failed" for r in results)
    # The breaker kicks in after BREAKER_FAIL_THRESHOLD failures; the number of
    # attempted requests must be far below max_pages.
    assert len(site.requests) < 10


def test_crawl_result_statuses_are_stable():
    assert CrawlResult("", "crawled").status == "crawled"
    assert CrawlResult("", "unchanged").status == "unchanged"
    assert CrawlResult("", "failed", error="boom").error == "boom"


def test_robots_rules_crawl_delay_capped():
    site = FakeSite()
    site.robots = "User-agent: *\nCrawl-delay: 999\nDisallow: /private\n"
    robots = RobotsRules("https://example.com/", fetcher=site)
    assert robots.crawl_delay <= 10.0
    assert robots.allowed("https://example.com/public")
    assert not robots.allowed("https://example.com/private")


# ── Scrape-job document upsert (duplicate-document fix) ───────────

async def _seed_crawl_bank(db) -> str:
    db.add(Databank(id="crawl-upsert-bank", user_id="crawl-upsert-user", name="Upsert"))
    await db.commit()
    return "crawl-upsert-bank"


@pytest.mark.asyncio
async def test_upsert_scrape_document_creates_then_updates_in_place(db, monkeypatch):
    from sqlalchemy import select

    from app.modules.rag.jobs import _upsert_scrape_document

    async def _doc_id(session, doc_url: str) -> str:
        doc = (
            await session.execute(select(Document).where(Document.source_url == doc_url))
        ).scalars().one()
        return doc.id

    stored: list[tuple[str, str, bytes]] = []
    monkeypatch.setattr(
        "app.core.storage.put_doc",
        lambda bank, key, content: stored.append((bank, key, content)),
    )
    bank_id = await _seed_crawl_bank(db)
    url = "https://example.com/about"

    first = await _upsert_scrape_document(db, bank_id, "crawl-upsert-user", url, "# About\nWe fix things")
    assert first == (await _doc_id(db, url))  # returns the doc id on create

    again = await _upsert_scrape_document(db, bank_id, "crawl-upsert-user", url, "# About\nWe fix things")
    assert again is None  # identical content — no new row, no new store

    changed = await _upsert_scrape_document(db, bank_id, "crawl-upsert-user", url, "# About\nWe fix more now")
    assert changed == (await _doc_id(db, url))  # changed content re-queues ingest

    from sqlalchemy import select

    docs = (
        await db.execute(select(Document).where(Document.source_url == url))
    ).scalars().all()
    assert len(docs) == 1  # still one row — never duplicated
    assert docs[0].status == "pending"
    assert len(stored) == 2  # stored only on create + change, not on unchanged
