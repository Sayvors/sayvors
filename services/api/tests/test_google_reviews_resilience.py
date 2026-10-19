"""Dedicated tests for Google Reviews client resilience:

- 429 rate-limit backoff with Retry-After honouring and jitter
- 401 refresh-then-retry combined with 429
- Giving up after MAX_REQUEST_ATTEMPTS
- list_reviews pagination across nextPageToken pages
- list_reviews safety cap and updated_after filtering

These tests mock the HTTP layer (httpx.MockTransport) and asyncio.sleep so
they run in milliseconds with no network and no live Google credentials.
Run only this file:  pytest services/api/tests/test_google_reviews_resilience.py
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.modules.channels.google_reviews import (
    GoogleReviewsClient,
    GoogleReviewsError,
    MAX_REQUEST_ATTEMPTS,
    MAX_REVIEW_PAGES,
)


# ──────────────────────────── fake HTTP transport ──────────────────────────

class _FakeTransport:
    """httpx.MockTransport-alike built from a scripted list of responses.

    Each entry is (status, headers, body) or an exception to raise.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def handle_async_request(self, request):
        self.calls.append(request.url)
        if not self.script:
            raise AssertionError("no more scripted responses")
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, headers, body = entry
        return httpx.Response(status, headers=headers, content=body)


def _make_client(transport_script):
    client = GoogleReviewsClient("access-token", "refresh-token")
    client._http = httpx.AsyncClient(transport=_FakeTransport(transport_script))
    return client


async def _sleep_stub(_seconds):
    """Replace asyncio.sleep so 429 backoff tests run instantly."""
    _sleep_stub.slept.append(float(_seconds))


_sleep_stub.slept = []


# ──────────────────────────── 429 backoff tests ────────────────────────────

@pytest.mark.asyncio
async def test_429_retries_with_exponential_backoff(monkeypatch):
    """429 → backoff → retry → 200. Sleeps grow exponentially with jitter."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    transport_script = [
        (429, {}, b'{"error": "rate limited"}'),
        (200, {}, b'{"reviews": []}'),
    ]
    client = _make_client(transport_script)

    resp = await client._authed_request("GET", "https://example.com/reviews")
    assert resp.status_code == 200
    # One backoff sleep was recorded (jittered, so just check it's > 0)
    assert len(_sleep_stub.slept) == 1
    assert _sleep_stub.slept[0] > 0


@pytest.mark.asyncio
async def test_429_honours_retry_after_header(monkeypatch):
    """Retry-After header value is used verbatim as the backoff seconds."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    transport_script = [
        (429, {"Retry-After": "7"}, b'{"error": "rate limited"}'),
        (200, {}, b'{"reviews": []}'),
    ]
    client = _make_client(transport_script)

    await client._authed_request("GET", "https://example.com/reviews")
    assert _sleep_stub.slept == [7.0]


@pytest.mark.asyncio
async def test_429_gives_up_after_max_attempts(monkeypatch):
    """Exhausting all attempts raises GoogleReviewsError with status 429."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    transport_script = [
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
    ]
    client = _make_client(transport_script)

    with pytest.raises(GoogleReviewsError) as excinfo:
        await client._authed_request("GET", "https://example.com/reviews")
    assert excinfo.value.status_code == 429
    assert "429" in str(excinfo.value)
    # MAX_REQUEST_ATTEMPTS = 6 → 5 backoff sleeps
    assert len(_sleep_stub.slept) == MAX_REQUEST_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_401_refresh_then_429_then_success(monkeypatch):
    """401 triggers token refresh, then 429 triggers backoff, then 200."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    refresh_calls = []

    async def _refresh():
        refresh_calls.append(1)

    client = _make_client([
        (401, {}, b'{"error": "invalid token"}'),
        (429, {"Retry-After": "0"}, b'{"error": "rate limited"}'),
        (200, {}, b'{"reviews": []}'),
    ])
    client.refresh_access_token = _refresh

    resp = await client._authed_request("GET", "https://example.com/reviews")
    assert resp.status_code == 200
    assert refresh_calls == [1]
    assert len(_sleep_stub.slept) == 1


@pytest.mark.asyncio
async def test_200_returns_immediately_no_backoff(monkeypatch):
    """A plain 200 does not sleep at all."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    client = _make_client([(200, {}, b'{"reviews": []}')])
    resp = await client._authed_request("GET", "https://example.com/reviews")
    assert resp.status_code == 200
    assert _sleep_stub.slept == []


# ──────────────────────────── list_reviews pagination ──────────────────────

def _review_page(reviews, next_token=None):
    page = {"reviews": reviews}
    if next_token:
        page["nextPageToken"] = next_token
    return page


@pytest.mark.asyncio
async def test_list_reviews_follows_next_page_token():
    """Multiple pages are followed until nextPageToken is absent."""
    page1 = _review_page(
        [{"name": "accounts/a/locations/l/reviews/r1", "rating": "FIVE",
          "comment": "Great", "reviewer": {"displayName": "A"}}],
        next_token="page-2",
    )
    page2 = _review_page(
        [{"name": "accounts/a/locations/l/reviews/r2", "rating": "ONE",
          "comment": "Bad", "reviewer": {"displayName": "B"}}],
    )
    client = _make_client([
        (200, {}, _json(page1)),
        (200, {}, _json(page2)),
    ])

    reviews = await client.list_reviews("accounts/a", "locations/l")
    assert [r.review_id for r in reviews] == [
        "accounts/a/locations/l/reviews/r1",
        "accounts/a/locations/l/reviews/r2",
    ]
    assert reviews[0].rating == 5
    assert reviews[1].rating == 1


@pytest.mark.asyncio
async def test_list_reviews_stops_at_safety_cap(monkeypatch):
    """More than MAX_REVIEW_PAGES of pages stops — no infinite loop."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    pages = []
    for i in range(MAX_REVIEW_PAGES + 3):
        pages.append((200, {}, _json(_review_page([], next_token=f"t{i}"))))
    client = _make_client(pages)

    reviews = await client.list_reviews("accounts/a", "locations/l")
    assert reviews == []
    # Exactly MAX_REVIEW_PAGES requests were made (safety cap tripped)
    assert len(client._http._transport.calls) == MAX_REVIEW_PAGES


@pytest.mark.asyncio
async def test_list_reviews_filters_by_updated_after():
    """Reviews older than updated_after are dropped client-side."""
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 10, 19, tzinfo=timezone.utc)
    page = _review_page([
        {"name": "r/old", "rating": "FIVE", "comment": "old",
         "reviewer": {"displayName": "A"},
         "updateTime": "2026-01-01T00:00:00Z"},
        {"name": "r/new", "rating": "FIVE", "comment": "new",
         "reviewer": {"displayName": "B"},
         "updateTime": "2026-10-19T12:00:00Z"},
    ])
    client = _make_client([(200, {}, _json(page))])

    reviews = await client.list_reviews(
        "accounts/a", "locations/l", updated_after=old
    )
    assert [r.review_id for r in reviews] == ["r/new"]


@pytest.mark.asyncio
async def test_list_reviews_propagates_429_after_exhaustion(monkeypatch):
    """If every page request hits 429 and exhausts retries, the error propagates."""
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()

    client = _make_client([
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
        (429, {}, b'{"error": "rate limited"}'),
    ])

    with pytest.raises(GoogleReviewsError) as excinfo:
        await client.list_reviews("accounts/a", "locations/l")
    assert excinfo.value.status_code == 429


# ──────────────────────────── helpers ──────────────────────────────────────

def _json(obj):
    import json as _json_mod
    return _json_mod.dumps(obj).encode()
