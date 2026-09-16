"""Unit tests for the full Localith read sync (no network, no DB).

Covers the adapter mapping helpers in integrations/channels/embedsocial.py,
the snapshot helpers in app/modules/localith/service.py and the background
auto-sync pass in app/modules/localith/worker.py against the live payload
shapes observed on 2026-09-09.
"""
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

# integrations/ lives at the repo root, not on the test path.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from integrations.channels import embedsocial
from app.modules.localith import service
from app.modules.localith import worker as localith_worker


def _listing_payload():
    return {
        "id": "abc123",
        "googleId": "ChIJEXAMPLE",
        "name": "Sayvors-Al Malqa",
        "storeCode": "10535417752639520230",
        "url": "https://maps.google.com/maps?cid=123",
        "isVerified": True,
        "isDisabled": False,
        "isSuspended": False,
        "phoneNumber": None,
        "address": "RIYADH Al Malqa Dist.",
        "websiteUrl": "http://sayvors.com/",
        "totalReviews": 0,
        "averageRating": 0.0,
        "lastReviewOn": None,
        "lastReplyOn": None,
    }


def test_normalize_listing_camel_case():
    norm = embedsocial.normalize_listing(_listing_payload())
    assert norm["listing_id"] == "abc123"
    assert norm["google_id"] == "ChIJEXAMPLE"
    assert norm["name"] == "Sayvors-Al Malqa"
    assert norm["maps_url"] == "https://maps.google.com/maps?cid=123"
    assert norm["is_verified"] is True
    assert norm["address"] == "RIYADH Al Malqa Dist."
    assert norm["total_reviews"] == 0
    assert norm["average_rating"] == 0.0


def test_normalize_listing_snake_case_fallback():
    norm = embedsocial.normalize_listing(
        {"id": "x", "google_id": "g1", "name": "N", "is_verified": False}
    )
    assert norm["google_id"] == "g1"
    assert norm["is_verified"] is False


def test_ddmmyyyy_formats():
    assert embedsocial._ddmmyyyy(date(2026, 9, 9)) == "09-09-2026"
    assert embedsocial._ddmmyyyy(datetime(2026, 8, 10, 12, 0)) == "10-08-2026"
    assert embedsocial._ddmmyyyy("2026-01-05T00:00:00Z") == "05-01-2026"


def test_to_internal_review_embedsocial_variants():
    review = embedsocial.to_internal_review(
        {
            "id": "r1",
            "starRating": 4,
            "reviewText": "Great service",
            "reviewer": {"displayName": "Sara"},
            "originalCreatedOn": "2026-09-01T10:00:00Z",
        }
    )
    assert review.rating == 4
    assert review.text == "Great service"
    assert review.reviewer == "Sara"
    assert review.published_at == "2026-09-01T10:00:00Z"


def test_to_internal_review_live_item_shape():
    """Exact field names Localith returns for Google reviews (2026-09-09)."""
    review = embedsocial.to_internal_review(
        {
            "id": "382bc749c36232128622f7c5a86130a0",
            "authorName": "Syed Syab Ahmad Shah",
            "rating": 4,
            "captionText": "I am still using that AI, that's is greatttt.",
            "sourceName": "Sayvors Company-Al Malqa",
            "sourceId": "a690420582bc3b00b307737132e5df8b",
            "reviewLink": "https://search.google.com/local/reviews?placeid=ChIJEXAMPLE",
            "originalCreatedOn": "2026-09-09 06:18:46",
            "replies": [],
        }
    )
    assert review.external_id == "382bc749c36232128622f7c5a86130a0"
    assert review.text == "I am still using that AI, that's is greatttt."
    assert review.reviewer == "Syed Syab Ahmad Shah"
    assert review.rating == 4
    assert review.review_url == "https://search.google.com/local/reviews?placeid=ChIJEXAMPLE"
    assert review.has_replies is False


def test_to_internal_review_with_replies_flagged():
    review = embedsocial.to_internal_review(
        {"id": "r9", "captionText": "ok", "replies": [{"text": "thanks"}]}
    )
    assert review.has_replies is True


def test_to_internal_review_flat_reviewer_fallback():
    review = embedsocial.to_internal_review(
        {"uid": "r2", "stars": "5", "body": "Nice", "author_name": "Omar"}
    )
    assert review.external_id == "r2"
    assert review.rating == 5
    assert review.reviewer == "Omar"


def test_apply_listing_snapshot_copies_everything():
    conn = SimpleNamespace(listing_name="old", listing_google_id=None)
    service.apply_listing_snapshot(conn, _listing_payload())
    assert conn.listing_name == "Sayvors-Al Malqa"
    assert conn.listing_google_id == "ChIJEXAMPLE"
    assert conn.address == "RIYADH Al Malqa Dist."
    assert conn.website_url == "http://sayvors.com/"
    assert conn.is_verified is True
    assert conn.is_disabled is False
    assert conn.total_reviews == 0
    assert conn.average_rating == 0.0
    assert conn.last_review_on is None
    assert conn.raw_listing_json["id"] == "abc123"
    assert conn.profile_synced_at is not None


def test_parse_dt_edge_cases():
    assert service._parse_dt(None) is None
    assert service._parse_dt("") is None
    assert service._parse_dt("not-a-date") is None
    dt = service._parse_dt("2026-09-09T12:00:00Z")
    assert dt is not None and dt.tzinfo is not None


def test_scalar_coercions():
    assert service._as_int("3.9") == 3
    assert service._as_int(None) == 0
    assert service._as_float("4.5") == 4.5
    assert service._as_float(None) == 0.0
    assert service._as_bool(True) is True
    assert service._as_bool("false") is False
    assert service._as_bool(None) is None


def test_adapter_rejects_non_http_base(monkeypatch):
    monkeypatch.setenv("LOCALITH_API_KEY", "k")
    monkeypatch.setenv("LOCALITH_BASE_URL", "file:///etc/")
    monkeypatch.setenv("LOCALITH_ITEMS_PATH", "rest/v1/items")
    with pytest.raises(ValueError):
        embedsocial.fetch_listings()


def test_adapter_get_uses_httpx_with_auth(monkeypatch):
    monkeypatch.setenv("LOCALITH_API_KEY", "k")
    monkeypatch.delenv("LOCALITH_BASE_URL", raising=False)
    monkeypatch.setenv("LOCALITH_ITEMS_PATH", "rest/v1/items")
    seen = {}

    class _FakeResp:
        def raise_for_status(self):
            seen["raised"] = True

        def json(self):
            return [{"id": "r1"}]

    def _fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return _FakeResp()

    monkeypatch.setattr(embedsocial.httpx, "get", _fake_get)
    out = embedsocial.fetch_items(limit=1)
    assert out == [{"id": "r1"}]
    assert seen["url"].startswith("https://")
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["params"]["page"] == 1
    assert seen["raised"] is True


def test_build_update_body_mapping():
    body = embedsocial.build_update_body(
        {
            "name": "Sayvors-Al Malqa",
            "phone_number": "+966 55 000 0000",
            "website_url": "https://sayvors.com/",
            "description": "  ",
            "unknown_field": "x",
        }
    )
    assert body == {
        "name": "Sayvors-Al Malqa",
        "phoneNumber": "+966 55 000 0000",
        "websiteUrl": "https://sayvors.com/",
    }


def test_build_update_body_address_split():
    body = embedsocial.build_update_body(
        {"city": "Riyadh", "country": "SA", "street": "Al Dahnaa"}
    )
    assert body == {
        "address.city": "Riyadh",
        "address.country": "SA",
        "address.streetLines[0]": "Al Dahnaa",
    }


def test_update_listing_rejects_empty(monkeypatch):
    def _fail(*a, **k):
        raise AssertionError("must not hit network")

    monkeypatch.setattr(embedsocial, "_patch", _fail)
    try:
        embedsocial.update_listing("abc", {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty fields")


def test_update_listing_sends_patch(monkeypatch):
    seen = {}

    def _fake_patch(path, body, timeout=30):
        seen["path"] = path
        seen["body"] = body
        return {"ok": True}

    monkeypatch.setattr(embedsocial, "_patch", _fake_patch)
    res = embedsocial.update_listing("abc 123", {"name": "New Name"})
    assert res == {"ok": True}
    assert seen["path"] == "rest/v1/listings/abc%20123"
    assert seen["body"] == {"name": "New Name"}


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalars(self._items)


class _FakeSession:
    """Minimal async-session double: execute() lists connections, get() users."""

    def __init__(self, connections, users):
        self._connections = connections
        self._users = users

    async def execute(self, stmt):
        return _FakeResult(self._connections)

    async def get(self, model, pk):
        return self._users.get(pk)

    async def rollback(self):
        pass


def _make_factory(connections, users):
    @asynccontextmanager
    async def _factory():
        yield _FakeSession(connections, users)

    return _factory


@pytest.mark.asyncio
async def test_sync_all_once_skips_without_key(monkeypatch):
    monkeypatch.setattr(service, "_key_present", lambda: False)
    totals = await localith_worker.sync_all_once(
        session_factory=_make_factory([SimpleNamespace(user_id="u1")], {})
    )
    assert totals == {"connections": 0, "fetched": 0, "new_reviews": 0, "errors": 0}


@pytest.mark.asyncio
async def test_sync_all_once_counts_and_isolates_failures(monkeypatch):
    monkeypatch.setattr(service, "_key_present", lambda: True)
    calls = []

    async def _fake_sync(user, db, listing_id=None):
        calls.append(user.id)
        if user.id == "bad":
            raise RuntimeError("boom")
        return {"fetched": 3, "new_reviews": 2}

    monkeypatch.setattr(service, "sync_connection", _fake_sync)
    conns = [SimpleNamespace(user_id="u1"), SimpleNamespace(user_id="bad")]
    users = {"u1": SimpleNamespace(id="u1"), "bad": SimpleNamespace(id="bad")}
    totals = await localith_worker.sync_all_once(
        session_factory=_make_factory(conns, users)
    )
    assert totals == {"connections": 2, "fetched": 3, "new_reviews": 2, "errors": 1}
    assert calls == ["u1", "bad"]


@pytest.mark.asyncio
async def test_sync_all_once_skips_missing_user(monkeypatch):
    monkeypatch.setattr(service, "_key_present", lambda: True)
    calls = []

    async def _fake_sync(user, db):
        calls.append(user.id)
        return {"fetched": 0, "new_reviews": 0}

    monkeypatch.setattr(service, "sync_connection", _fake_sync)
    totals = await localith_worker.sync_all_once(
        session_factory=_make_factory([SimpleNamespace(user_id="ghost")], {})
    )
    assert totals["connections"] == 0
    assert calls == []

@pytest.mark.asyncio
async def test_autopilot_auto_posts_high_and_queues_low(db, user_id, channel_id, monkeypatch):
    """Auto Pilot: auto mode + rating >= min_rating_auto posts live via Localith
    immediately; lower ratings (or approval mode) still queue for approval."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.modules.channels.models import AutoReplyConfig
    from app.modules.localith.models import LocalithConnection
    from app.modules.channels.models import ReviewReply

    db.add(LocalithConnection(
        id="lc-auto-1", user_id=user_id, listing_id="demo-loc-456",
        listing_name="Auto Listing",
    ))
    db.add(AutoReplyConfig(
        id="cfg-auto-1", channel_id=channel_id, enabled=True,
        approval_mode="auto", min_rating_auto=4,
    ))
    await db.commit()

    items = [
        {"id": "hi5", "rating": 5, "captionText": "Great product", "authorName": "Adeel"},
        {"id": "lo2", "rating": 2, "captionText": "Late delivery", "authorName": "Sara"},
    ]
    monkeypatch.setattr(service.settings, "GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(service, "_key_present", lambda: True)

    async def _detail(listing_id):
        return {}

    monkeypatch.setattr(service, "get_listing_detail", _detail)
    monkeypatch.setattr(embedsocial, "fetch_all_items", lambda listing_id: items)
    monkeypatch.setattr(embedsocial, "fetch_listing_metrics", lambda *a, **k: {})
    monkeypatch.setattr(embedsocial, "fetch_item_metrics", lambda *a, **k: {})

    async def _gen(config, channel, rating, text, reviewer, db_,
                   review_id=None, attempt=1, previous_draft=None):
        return "engine draft"

    monkeypatch.setattr(service, "generate_auto_reply", _gen)

    posted = []

    async def _post(item_id, text):
        posted.append((item_id, text))
        return {"ok": True}

    monkeypatch.setattr(service, "post_reply", _post)

    # enqueue_event writes to the REAL Postgres outbox via its own global
    # session (not the test engine) — keep the test hermetic.
    events = []

    async def _fake_enqueue(event_type, payload, topic="review-events"):
        events.append((event_type, payload.get("review_id")))
        return "evt"

    monkeypatch.setattr(service, "enqueue_event", _fake_enqueue)

    totals = await service.sync_connection(SimpleNamespace(id=user_id), db)

    assert posted == [("hi5", "engine draft")]
    assert sorted(events) == [
        ("review.discovered", "localith:hi5"),
        ("review.discovered", "localith:lo2"),
    ]
    rows = {
        r.review_id: r
        for r in (await db.execute(select(ReviewReply))).scalars().all()
    }
    assert rows["localith:hi5"].status == "posted"
    assert rows["localith:hi5"].error is None
    assert rows["localith:lo2"].status == "pending_approval"

@pytest.mark.asyncio
async def test_get_connection_selects_branch(db, user_id):
    """Two branches coexist; lookup selects by listing, default is first."""
    from app.modules.localith.models import LocalithConnection

    db.add(LocalithConnection(
        id="lc-b1", user_id=user_id, listing_id="list-one", listing_name="Branch One",
    ))
    db.add(LocalithConnection(
        id="lc-b2", user_id=user_id, listing_id="list-two", listing_name="Branch Two",
    ))
    await db.commit()

    assert (await service.get_connection(db, user_id, "list-two")).listing_name == "Branch Two"
    assert (await service.get_connection(db, user_id, "list-one")).listing_name == "Branch One"
    assert (await service.get_connection(db, user_id)).listing_name == "Branch One"
    assert await service.get_connection(db, user_id, "nope") is None
    assert len(await service.list_connections(db, user_id)) == 2


@pytest.mark.asyncio
async def test_sync_connection_loops_all_branches(db, user_id, monkeypatch):
    """No listing_id -> every branch syncs, totals aggregate, none skipped."""
    from types import SimpleNamespace

    from app.modules.localith.models import LocalithConnection

    db.add(LocalithConnection(
        id="lc-c1", user_id=user_id, listing_id="list-a", listing_name="A",
    ))
    db.add(LocalithConnection(
        id="lc-c2", user_id=user_id, listing_id="list-b", listing_name="B",
    ))
    await db.commit()

    seen = []

    async def _fake_single(user, db_, connection, days_back=30):
        seen.append(connection.listing_id)
        return {"fetched": 1, "new_reviews": 2}

    monkeypatch.setattr(service, "_sync_single_connection", _fake_single)

    totals = await service.sync_connection(SimpleNamespace(id=user_id), db)

    assert sorted(seen) == ["list-a", "list-b"]
    assert totals["fetched"] == 2
    assert totals["new_reviews"] == 4
    assert totals["branches"] == 2
