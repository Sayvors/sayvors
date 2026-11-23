"""gosom adapter: CSV field mapping, review dedupe, bounded results, job lifecycle.

No live scraping — every test drives the adapter against a mocked
``httpx.AsyncClient`` that routes POST (job create), GET (poll / download) and
DELETE (cleanup) calls by URL, exactly like ``test_benchmark_places.py``.
"""
import csv
import io
import json

import httpx
import pytest

from app.config import settings
from app.modules.benchmark import gosom

FIELDNAMES = [
    "place_id", "title", "address", "review_rating", "review_count",
    "latitude", "longitude", "category", "user_reviews",
    "user_reviews_extended", "reviews_per_rating",
]


def _make_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _recent_iso(days_ago: int = 1) -> str:
    """An RFC3339 timestamp ``days_ago`` days in the past.

    Reviews are windowed to the last 30 days by default, so fixtures use recent
    dates rather than a fixed calendar date that would silently fall out of the
    window over time.
    """
    from datetime import datetime, timedelta, timezone

    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.isoformat()


def _review(**overrides):
    base = {
        "review_id": "rev-1",
        "name": "Alice",
        "rating": 5,
        "description": "Great",
        "published_at": _recent_iso(1),
        "profile_picture": "http://pic/1.jpg",
        "reply_text": "Thanks",
    }
    base.update(overrides)
    return base


class _Response:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _Client:
    """Mock httpx.AsyncClient routing calls by URL pattern."""

    def __init__(self, create=None, poll=None, download=None, create_error=None):
        self.create = create if create is not None else _Response(payload={"id": "job-1"})
        self.poll = poll if poll is not None else _Response(payload={"status": "ok"})
        self.download = download if download is not None else _Response(text="")
        self.create_error = create_error
        self.calls = []
        self.deleted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.create_error is not None:
            raise self.create_error
        return self.create

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/download"):
            return self.download
        return self.poll

    async def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        self.deleted.append(url)
        return _Response()


@pytest.fixture
def scraper(monkeypatch):
    """Point the adapter at a fake sidecar and keep polling instantaneous."""
    monkeypatch.setattr(settings, "GOSOM_SCRAPER_URL", "http://gosom:8080")
    monkeypatch.setattr(gosom, "POLL_INTERVAL_SECONDS", 0)


def _install(monkeypatch, client):
    monkeypatch.setattr(gosom.httpx, "AsyncClient", lambda **kw: client)


async def test_get_place_maps_reviews_and_metadata(monkeypatch, scraper):
    r1 = _review()
    r2 = _review(review_id="rev-2", name="Bob", rating=4, description="Nice",
                 published_at=_recent_iso(2), profile_picture="", reply_text="")
    row = {
        "place_id": "gid-123",
        "title": "Riyadh Cafe",
        "address": "Malaz, Riyadh",
        "review_rating": 4.5,
        "review_count": 120,
        "latitude": 24.68,
        "longitude": 46.68,
        "category": "cafe",
        # rev-1 appears in both columns; it must survive only once.
        "user_reviews": json.dumps([r1]),
        "user_reviews_extended": json.dumps([r1, r2]),
        "reviews_per_rating": json.dumps({"1": 2, "5": 10}),
    }
    client = _Client(download=_Response(text=_make_csv([row])))
    _install(monkeypatch, client)

    place = await gosom.get_place("gid-123")

    assert place["place_id"] == "gid-123"
    assert place["name"] == "Riyadh Cafe"
    assert place["address"] == "Malaz, Riyadh"
    assert place["rating"] == 4.5
    assert place["review_count"] == 120
    assert place["types"] == ["cafe"]
    assert place["latitude"] == 24.68
    assert place["longitude"] == 46.68
    assert place["source"] == "gosom"
    assert place["reviews_per_score"] == {"1": 2, "5": 10}

    assert len(place["reviews"]) == 2  # rev-1 deduped against the extended copy
    first = place["reviews"][0]
    assert first["rating"] == 5
    assert first["text"] == "Great"
    assert first["author"] == "Alice"
    # publish_time is the recent fixture date (within the 30-day window).
    assert first["publish_time"] is not None
    assert first["author_photo"] == "http://pic/1.jpg"
    assert first["owner_answer"] == "Thanks"


async def test_get_place_caps_reviews_limit(monkeypatch, scraper):
    extended = [_review(review_id=f"rev-{i}", name=f"U{i}") for i in range(600)]
    row = {
        "place_id": "gid-999",
        "title": "Big Place",
        "address": "Somewhere",
        "review_rating": 4.0,
        "review_count": 600,
        "latitude": 0,
        "longitude": 0,
        "category": "cafe",
        "user_reviews": json.dumps([]),
        "user_reviews_extended": json.dumps(extended),
        "reviews_per_rating": json.dumps({}),
    }
    client = _Client(download=_Response(text=_make_csv([row])))
    _install(monkeypatch, client)

    place = await gosom.get_place("gid-999", reviews_limit=100)

    assert len(place["reviews"]) == 100


async def test_get_place_missing_config(monkeypatch):
    monkeypatch.setattr(settings, "GOSOM_SCRAPER_URL", "")
    with pytest.raises(gosom.GosomError) as exc:
        await gosom.get_place("gid-123")
    assert exc.value.status_code == 503


async def test_get_place_not_found(monkeypatch, scraper):
    client = _Client(download=_Response(text=""))
    _install(monkeypatch, client)

    with pytest.raises(gosom.GosomError) as exc:
        await gosom.get_place("missing")
    assert exc.value.status_code == 404


async def test_get_place_job_failed(monkeypatch, scraper):
    client = _Client(poll=_Response(payload={"status": "failed", "error": "captcha wall"}))
    _install(monkeypatch, client)

    with pytest.raises(gosom.GosomError) as exc:
        await gosom.get_place("gid-123")
    assert "captcha wall" in str(exc.value)


async def test_poll_reads_capitalised_status_key(monkeypatch, scraper):
    """gosom's web.Job has no json tags -> it marshals "Status", not "status".

    Regression: reading only lowercase made every real poll miss "ok" and time
    out at 504 even though the job completed server-side.
    """
    row = {
        "place_id": "gid-1", "title": "Cafe", "address": "Riyadh",
        "review_rating": 4.0, "review_count": 5, "latitude": 0, "longitude": 0,
        "category": "cafe", "user_reviews": json.dumps([]),
        "user_reviews_extended": json.dumps([]), "reviews_per_rating": json.dumps({}),
    }
    client = _Client(
        poll=_Response(payload={"ID": "job-1", "Status": "ok"}),
        download=_Response(text=_make_csv([row])),
    )
    _install(monkeypatch, client)

    place = await gosom.get_place("gid-1")
    assert place["place_id"] == "gid-1"


async def test_get_place_job_timeout(monkeypatch, scraper):
    monkeypatch.setattr(gosom, "JOB_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(gosom, "POLL_INTERVAL_SECONDS", 0.1)
    client = _Client(poll=_Response(payload={"status": "working"}))
    _install(monkeypatch, client)

    with pytest.raises(gosom.GosomError) as exc:
        await gosom.get_place("gid-123")
    assert exc.value.status_code == 504


async def test_get_place_transport_error(monkeypatch, scraper):
    client = _Client(create_error=httpx.ConnectError("connection refused"))
    _install(monkeypatch, client)

    with pytest.raises(gosom.GosomError):
        await gosom.get_place("gid-123")


async def test_get_place_cleans_up_job(monkeypatch, scraper):
    deleted = []

    async def _fake_delete(client, job_id):
        deleted.append(job_id)

    monkeypatch.setattr(gosom, "_delete_job", _fake_delete)
    # Poll fails -> _poll_job raises, but the finally block must still delete.
    client = _Client(poll=_Response(payload={"status": "failed", "error": "boom"}))
    _install(monkeypatch, client)

    with pytest.raises(gosom.GosomError):
        await gosom.get_place("gid-123")

    assert deleted == ["job-1"]


def test_parse_reviews_dedupes():
    r1 = _review()
    # Bob is explicitly older so the newest-first sort is deterministic.
    r2 = _review(review_id="rev-2", name="Bob", published_at=_recent_iso(3))
    row = {
        "user_reviews": json.dumps([r1]),
        "user_reviews_extended": json.dumps([r1, r2]),
    }
    reviews = gosom._parse_reviews(row)
    assert len(reviews) == 2
    assert [r["author"] for r in reviews] == ["Alice", "Bob"]


def test_parse_reviews_handles_relative_dates():
    row = {"user_reviews": json.dumps([_review(published_at="2 months ago")])}
    reviews = gosom._parse_reviews(row)
    assert reviews[0]["publish_time"] is None


def test_filter_recent_drops_old_reviews():
    """The 30-day window drops reviews older than the window, keeps recent."""
    recent = {"rating": 5, "publish_time": _recent_iso(5)}
    old = {"rating": 1, "publish_time": _recent_iso(120)}
    undated = {"rating": 3, "publish_time": None}
    kept = gosom._filter_recent([recent, old, undated], 30)
    assert recent in kept
    assert old not in kept
    assert undated not in kept


def test_filter_recent_disabled_when_days_none():
    reviews = [{"rating": 5, "publish_time": _recent_iso(400)}]
    assert gosom._filter_recent(reviews, None) == reviews


async def test_get_place_with_maps_url(monkeypatch, scraper):
    row = {
        "place_id": "gid-123",
        "title": "Cafe",
        "address": "Riyadh",
        "review_rating": 4.0,
        "review_count": 5,
        "latitude": 0,
        "longitude": 0,
        "category": "cafe",
        "user_reviews": json.dumps([]),
        "user_reviews_extended": json.dumps([]),
        "reviews_per_rating": json.dumps({}),
    }
    client = _Client(download=_Response(text=_make_csv([row])))
    _install(monkeypatch, client)

    await gosom.get_place("ignored", maps_url="https://maps.google.com/?cid=123")

    post = next(call for call in client.calls if call[0] == "POST")
    assert post[2]["json"]["keywords"][0] == "https://maps.google.com/?cid=123"


async def test_get_place_requests_reviews(monkeypatch, scraper):
    """A single-place scrape must ask gosom for reviews (extra_reviews=True)."""
    row = {
        "place_id": "gid-1", "title": "Cafe", "address": "Riyadh",
        "review_rating": 4.0, "review_count": 5, "latitude": 0, "longitude": 0,
        "category": "cafe", "user_reviews": json.dumps([]),
        "user_reviews_extended": json.dumps([]), "reviews_per_rating": json.dumps({}),
    }
    client = _Client(download=_Response(text=_make_csv([row])))
    _install(monkeypatch, client)

    await gosom.get_place("gid-1")

    post = next(call for call in client.calls if call[0] == "POST")
    assert post[2]["json"]["extra_reviews"] is True


async def test_search_does_not_request_reviews(monkeypatch, scraper):
    """Search must NOT scrape reviews — listings only, deferred to save time.

    Locks in the fix for the slow search: gosom ORs its config flag with the
    job flag, so a search job has to explicitly send extra_reviews=False and
    the sidecar must not force it on.
    """
    row = {
        "place_id": "gid-1", "title": "Cafe", "address": "Riyadh",
        "review_rating": 4.0, "review_count": 5, "latitude": 0, "longitude": 0,
        "category": "cafe",
        # Even if the CSV carries reviews, search must return them empty.
        "user_reviews": json.dumps([_review()]),
        "user_reviews_extended": json.dumps([]), "reviews_per_rating": json.dumps({}),
    }
    client = _Client(download=_Response(text=_make_csv([row])))
    _install(monkeypatch, client)

    results = await gosom.search_places("cafe in riyadh")

    post = next(call for call in client.calls if call[0] == "POST")
    assert post[2]["json"]["extra_reviews"] is False
    assert results[0]["reviews"] == []