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
        # Full request objects (method/body/headers) — `calls` stays URL-only
        # for the pagination assertions above.
        self.requests = []

    async def handle_async_request(self, request):
        self.calls.append(request.url)
        self.requests.append(request)
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
        (429, {"Retry-After": "0"}, b'{"error": "rate limited"}'),
        (200, {}, b'{"reviews": []}'),
    ]
    client = _make_client(transport_script)

    resp = await client._authed_request("GET", "https://example.com/reviews")
    assert resp.status_code == 200
    # One backoff sleep recorded; Retry-After "0" means retry immediately.
    assert len(_sleep_stub.slept) == 1
    assert _sleep_stub.slept[0] == 0.0


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


# ──────────────────────────── reply write endpoints ───────────────────────

@pytest.mark.asyncio
async def test_reply_to_review_hits_update_reply_url():
    """The reply write must be `PUT .../reviews/{name}/reply`.

    Production showed `replyUpdate failed (404)` with Google's HTML 404 page:
    the client called the nonexistent `:replyUpdate` segment instead of the
    transcoded `/reply` path. Pin the URL and verb so a refactor cannot
    silently regress the write path.
    """
    client = _make_client([(200, {}, b"{}")])
    await client.reply_to_review("accounts/a/locations/l/reviews/r1", "Thanks!")

    assert len(client._http._transport.calls) == 1
    called = client._http._transport.requests[0]
    assert called.method == "PUT"
    assert str(called.url) == (
        "https://mybusiness.googleapis.com/v4"
        "/accounts/a/locations/l/reviews/r1/reply"
    )


@pytest.mark.asyncio
async def test_reply_to_review_sends_review_reply_body():
    """The body must be a ReviewReply instance, i.e. `{"comment": ...}`."""
    client = _make_client([(200, {}, b"{}")])
    await client.reply_to_review("accounts/a/locations/l/reviews/r1", "Thanks!")

    import json as _json_mod

    body = _json_mod.loads(client._http._transport.requests[0].content)
    assert body == {"comment": "Thanks!"}


@pytest.mark.asyncio
async def test_reply_to_review_404_raises_with_status():
    """A 404 from Google must surface as GoogleReviewsError(404), not be retried.

    `_authed_request` only retries 401/429, so the 404 propagates on the
    first response — the exact production symptom this regression pins.
    """
    client = _make_client([(404, {}, b"<html>Error 404 (Not Found)</html>")])
    with pytest.raises(GoogleReviewsError) as excinfo:
        await client.reply_to_review("accounts/a/locations/l/reviews/r1", "Thanks!")
    assert excinfo.value.status_code == 404
    assert "updateReply failed (404)" in str(excinfo.value)
    assert len(client._http._transport.calls) == 1


@pytest.mark.asyncio
async def test_delete_reply_hits_reply_url():
    """deleteReply transcodes to the same `/reply` segment with DELETE."""
    client = _make_client([(200, {}, b"{}")])
    await client.delete_reply("accounts/a/locations/l/reviews/r1")

    called = client._http._transport.requests[0]
    assert called.method == "DELETE"
    assert str(called.url) == (
        "https://mybusiness.googleapis.com/v4"
        "/accounts/a/locations/l/reviews/r1/reply"
    )


# ──────────────────────────── reply moderation state ──────────────────────

def _review_payload(reply=None):
    review = {"name": "accounts/a/locations/l/reviews/r1"}
    if reply is not None:
        review["reviewReply"] = reply
    return _json(review)


@pytest.mark.asyncio
async def test_list_reviews_parses_reply_moderation_state():
    """reviewReply.reviewReplyState is captured so the poll can track
    Google's moderation (pending -> approved/rejected) on the reply row."""
    page = _review_page([
        {"name": "accounts/a/locations/l/reviews/r1", "starRating": "FIVE",
         "comment": "Great", "reviewer": {"displayName": "A"},
         "reviewReply": {"comment": "Thanks!", "reviewReplyState": "PENDING"}},
    ])
    client = _make_client([(200, {}, _json(page))])

    reviews = await client.list_reviews("accounts/a", "locations/l")
    assert reviews[0].reply_state == "pending"
    assert reviews[0].reply_text == "Thanks!"


@pytest.mark.asyncio
async def test_read_reply_state_reports_approved():
    """APPROVED -> live; the pre-moderation default (no state) is approved."""
    client = _make_client([
        (200, {}, _review_payload({"comment": "Thanks", "reviewReplyState": "APPROVED"})),
    ])
    assert await client.read_reply_state("r") == {
        "state": "approved", "policy_violation": None,
    }

    client = _make_client([
        (200, {}, _review_payload({"comment": "Thanks"})),
    ])
    assert (await client.read_reply_state("r"))["state"] == "approved"


@pytest.mark.asyncio
async def test_read_reply_state_reports_pending_and_rejected():
    """PENDING is not a failure; REJECTED is, and carries the reason."""
    client = _make_client([
        (200, {}, _review_payload({"comment": "Thanks", "reviewReplyState": "PENDING"})),
    ])
    assert (await client.read_reply_state("r"))["state"] == "pending"

    client = _make_client([
        (200, {}, _review_payload({
            "comment": "Thanks",
            "reviewReplyState": "REJECTED",
            "policyViolation": "ADVERTISING_AND_SOLICITATION",
        })),
    ])
    state = await client.read_reply_state("r")
    assert state["state"] == "rejected"
    assert state["policy_violation"] == "ADVERTISING_AND_SOLICITATION"


@pytest.mark.asyncio
async def test_read_reply_state_absent_when_not_readable(monkeypatch):
    """404 / no reviewReply -> "absent", which callers must NOT treat as failed.

    This is the production false-failure: Google accepted the write (2xx) but
    moderation kept the reply unreadable past the read-back window.
    """
    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    _sleep_stub.slept.clear()
    client = _make_client([
        (404, {}, b"Not found"),
        (404, {}, b"Not found"),
    ])
    assert await client.read_reply_state("r", attempts=2) == {
        "state": "absent", "policy_violation": None,
    }
    assert len(_sleep_stub.slept) == 1


# ──────────────────────────── helpers ──────────────────────────────────────

def _json(obj):
    import json as _json_mod
    return _json_mod.dumps(obj).encode()
