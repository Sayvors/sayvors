"""Per-post Google metrics: matching, insight parsing, the sync flow.

Google's localPosts:reportInsights is the only per-post metrics source
(Localith exposes none), so the sync is exercised against a fake client
with the exact response shapes the v4 reference documents.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels import google_reviews as gr
from app.modules.channels import service as channels_service
from app.modules.channels.models import Channel
from app.modules.localith.models import LocalithConnection
from app.modules.posts import service as posts
from app.modules.posts.models import LocationPost


def _gp(name="accounts/a/locations/g1/localPosts/7", summary="Weekend deal",
        created=None, **over):
    """One Google LocalPost, shaped like the v4 list response."""
    when = (created or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    post = {"name": name, "summary": summary, "createTime": when, "state": "LIVE"}
    post.update(over)
    return post


def _row(db, user_id, row_id="r1", description="Weekend deal",
         published_min_ago=10, **over):
    data = dict(
        id=row_id, user_id=user_id, listing_id="loc-1", business_name="B",
        title="T", description=description, status="published",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=published_min_ago),
    )
    data.update(over)
    row = LocationPost(**data)
    db.add(row)
    return row


async def _connection(db, user_id, google_id="g1"):
    db.add(LocalithConnection(
        id="conn-metrics", user_id=user_id, listing_id="loc-1",
        listing_name="Test Place", listing_google_id=google_id,
    ))


async def _oauth_channel(db, user_id):
    db.add(Channel(
        id="ch-metrics", user_id=user_id, platform="google_reviews",
        platform_user_id="acct-1", status="active",
        access_token="enc-access", refresh_token="enc-refresh",
    ))


# ── matching ─────────────────────────────────────────────────────

def _published_row_stub(row_id, description, published_min_ago):
    return LocationPost(
        id=row_id, user_id="u", listing_id="loc-1", business_name="B",
        title="T", description=description, status="published",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=published_min_ago),
    )


def test_match_prefers_caption_then_time():
    now = datetime.now(timezone.utc)
    gposts = [
        _gp(name="p7", summary="Weekend deal"),
        # No caption on Google: only the publish time can identify it.
        _gp(name="p8", summary="", created=now - timedelta(minutes=61)),
    ]
    rows = [
        _published_row_stub("r1", "WEEKEND   deal", 10),  # whitespace/case-insensitive
        _published_row_stub("r2", "Untotalled text", 60),
    ]
    pairs = posts.match_google_posts(rows, gposts)
    assert pairs["r1"]["name"] == "p7"
    assert pairs["r2"]["name"] == "p8"


def test_match_never_reuses_a_google_post():
    now = datetime.now(timezone.utc)
    gposts = [_gp(name="p7", summary="Same text", created=now)]
    rows = [
        _published_row_stub("r1", "Same text", 5),
        # Same caption and time — one Google post, one match only.
        _published_row_stub("r2", "Same text", 6),
    ]
    pairs = posts.match_google_posts(rows, gposts)
    assert set(pairs) == {"r1"}


def test_match_ignores_rows_published_far_from_create_time():
    now = datetime.now(timezone.utc)
    gposts = [_gp(name="p7", summary="", created=now - timedelta(hours=6))]
    rows = [_published_row_stub("r1", "No caption anywhere", 5)]
    assert posts.match_google_posts(rows, gposts) == {}


# ── insight parsing ──────────────────────────────────────────────

def test_insight_totals_parses_and_defaults_missing():
    resp = {
        "localPostMetrics": [
            {
                "localPostName": "accounts/a/locations/g1/localPosts/7",
                "metricValues": [
                    {"metric": "LOCAL_POST_VIEWS_SEARCH",
                     "totalValue": {"value": "123"}},
                    {"metric": "LOCAL_POST_ACTIONS_CALL_TO_ACTION"},
                ],
            },
        ],
    }
    totals = posts._insight_totals(resp)
    assert totals == {
        "accounts/a/locations/g1/localPosts/7": {
            "LOCAL_POST_VIEWS_SEARCH": 123,
            "LOCAL_POST_ACTIONS_CALL_TO_ACTION": 0,
        },
    }
    assert posts._insight_totals({}) == {}


# ── the sync flow ────────────────────────────────────────────────

class _FakeClient:
    """GoogleReviewsClient stand-in with canned v4 payloads."""

    last = None

    def __init__(self, access_token, refresh_token=None):
        self.access_token = access_token
        self.closed = False
        _FakeClient.last = self

    def set_token_persister(self, persister):
        self.persister = persister

    def set_known_expiry(self, expires_at):
        self.expiry = expires_at

    async def list_accounts(self):
        return [{"name": "accounts/acct-1"}]

    async def list_local_posts(self, account_id, location_id):
        assert (account_id, location_id) == ("acct-1", "g1")
        return [self.gp] if hasattr(self, "gp") else []

    async def report_local_post_insights(self, account_id, location_id, names, start, end):
        self.insight_names = list(names)
        return self.insights

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_sync_stores_views_and_clicks(monkeypatch, db, user_id):
    await _connection(db, user_id)
    await _oauth_channel(db, user_id)
    row = _row(db, user_id)
    await db.commit()

    gp = _gp(summary="Weekend deal")
    fake = _FakeClient
    fake.insights = {
        "localPostMetrics": [{
            "localPostName": gp["name"],
            "metricValues": [
                {"metric": "LOCAL_POST_VIEWS_SEARCH", "totalValue": {"value": "12"}},
                {"metric": "LOCAL_POST_ACTIONS_CALL_TO_ACTION",
                 "totalValue": {"value": "3"}},
            ],
        }],
    }

    def _fake_client_cls(access_token, refresh_token=None):
        inst = _FakeClient(access_token, refresh_token)
        inst.gp = gp
        inst.insights = _FakeClient.insights
        return inst

    monkeypatch.setattr(gr, "GoogleReviewsClient", _fake_client_cls)
    monkeypatch.setattr(channels_service, "decrypt_token", lambda v: "tok")
    monkeypatch.setattr(channels_service, "encrypt_token", lambda v: f"enc:{v}")

    result = await posts.sync_post_metrics(db, user_id, "loc-1")

    assert result["checked"] == 1
    assert result["matched"] == 1
    assert result["synced"] == 1
    assert result["posts"][0]["views"] == 12
    assert result["posts"][0]["cta_clicks"] == 3
    await db.refresh(row)
    assert row.views == 12
    assert row.cta_clicks == 3
    assert row.metrics_synced_at is not None
    assert _FakeClient.last.closed is True


@pytest.mark.asyncio
async def test_sync_without_oauth_channel_returns_note(monkeypatch, db, user_id):
    await _connection(db, user_id)
    _row(db, user_id)
    await db.commit()

    result = await posts.sync_post_metrics(db, user_id, "loc-1")
    assert result["checked"] == 1
    assert result["matched"] == 0
    assert result["posts"] == []
    assert "native" in (result["note"] or "")


@pytest.mark.asyncio
async def test_sync_without_google_location_id_notes(monkeypatch, db, user_id):
    await _connection(db, user_id, google_id=None)
    await _oauth_channel(db, user_id)
    _row(db, user_id)
    await db.commit()

    monkeypatch.setattr(gr, "GoogleReviewsClient", _FakeClient)
    monkeypatch.setattr(channels_service, "decrypt_token", lambda v: "tok")
    result = await posts.sync_post_metrics(db, user_id, "loc-1")
    assert result["matched"] == 0
    assert "location id" in (result["note"] or "")


@pytest.mark.asyncio
async def test_sync_unmatched_rows_stay_null(monkeypatch, db, user_id):
    """A post Google no longer lists (taken down) keeps its last numbers."""
    await _connection(db, user_id)
    await _oauth_channel(db, user_id)
    row = _row(db, user_id, description="Taken down long ago")
    await db.commit()

    monkeypatch.setattr(gr, "GoogleReviewsClient", _FakeClient)
    monkeypatch.setattr(channels_service, "decrypt_token", lambda v: "tok")

    result = await posts.sync_post_metrics(db, user_id, "loc-1")
    assert result["matched"] == 0
    await db.refresh(row)
    assert row.views is None
    assert row.cta_clicks is None
