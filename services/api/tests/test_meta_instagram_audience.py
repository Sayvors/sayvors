"""Instagram audience: engaged people + aggregate demographics.

Meta does not expose follower/following lists, so this endpoint must never
invent one. It merges two real sources - commenters read live from Graph and
DM contacts from our own inbox - and both carry usernames, which is what makes
a working instagram.com link possible. Demographics are aggregate only, and the
common failures (missing insights scope, under 100 followers) must come back as
a reason rather than an empty panel.
"""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

TENANT = "test-user-0000-0000-0000-000000000001"
IG = "17841405822304930"

_MEDIA = {
    "data": [
        {
            "id": "m1",
            "permalink": "https://instagram.com/p/abc/",
            "comments": {
                "data": [
                    {
                        "id": "c1",
                        "text": "Great service!",
                        "timestamp": "2026-02-02T10:00:00+0000",
                        "username": "layla",
                        "like_count": 4,
                        "from": {"id": "IGSID-1"},
                    },
                    {
                        "id": "c2",
                        "text": "How much is it?",
                        "timestamp": "2026-02-03T10:00:00+0000",
                        "username": "omar",
                        "like_count": 0,
                        "from": {"id": "IGSID-2"},
                    },
                ]
            },
        }
    ]
}

_DEMOGRAPHICS = {
    "id": IG,
    "insights": {
        "data": [
            {
                "metric": "follower_demographics",
                "values": [
                    {
                        # Real Meta payloads name the dimension on the value.
                        "metric": "age",
                        "breakdowns": [
                            {"dim_keys": ["age"], "dimension_values": [{"display_value": "18-24", "value": 420}]},
                            {"dim_keys": ["age"], "dimension_values": [{"display_value": "25-34", "value": 610}]},
                        ],
                    },
                    {
                        "metric": "gender",
                        "breakdowns": [
                            {"dim_keys": ["gender"], "dimension_values": [{"display_value": "female", "value": 700}]},
                            {"dim_keys": ["gender"], "dimension_values": [{"display_value": "male", "value": 330}]},
                        ],
                    },
                ],
            }
        ]
    },
}

# Some responses omit the value-level metric; the breakdown's dim_keys must
# still resolve the dimension rather than dumping everything in one bucket.
_DEMOGRAPHICS_NO_VALUE_METRIC = {
    "id": IG,
    "insights": {
        "data": [
            {
                "metric": "follower_demographics",
                "values": [
                    {
                        "breakdowns": [
                            {"dim_keys": ["cities"], "dimension_values": [{"display_value": "Makkah", "value": 91}]},
                        ]
                    }
                ],
            }
        ]
    },
}


def _graph(payload, seen=None):
    async def _inner(self, method, path, token, **kwargs):
        if seen is not None:
            seen.append((path, kwargs.get("params", {})))
        return httpx.Response(200, json=payload)

    return _inner


async def _seed(db):
    conn = MetaConnection(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        provider="instagram",
        access_token_encrypted=encrypt_credential("page-token"),
        status="active",
    )
    db.add(conn)
    await db.flush()
    asset = MetaAsset(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        connection_id=conn.id,
        provider="instagram",
        asset_type="ig_account",
        external_asset_id=IG,
        name="sayvors",
        active=True,
    )
    db.add(asset)
    await db.commit()
    return asset


async def _seed_contact(db, username, name, contact_id):
    from app.modules.channels.models import ContactProfile

    db.add(
        ContactProfile(
            tenant_id=TENANT, platform="instagram", contact_id=contact_id,
            username=username, name=name,
        )
    )
    await db.commit()


# ── adapter ───────────────────────────────────────────────────────────


async def test_commenters_are_flattened_with_profile_links(monkeypatch):
    monkeypatch.setattr(InstagramAdapter, "_graph", _graph(_MEDOGRAPHICS if False else _MEDIA))

    out = await InstagramAdapter().get_recent_commenters(IG, "t")

    assert [c["username"] for c in out] == ["omar", "layla"]  # newest first
    assert out[0]["profile_url"] == "https://instagram.com/omar"
    assert out[0]["text"] == "How much is it?"
    assert out[0]["permalink"] == "https://instagram.com/p/abc/"
    assert out[1]["like_count"] == 4


async def test_commenters_survive_a_missing_scope(monkeypatch):
    async def _denied(self, method, path, token, **kwargs):
        raise MetaAPIError("(#10) This API call is not allowed", 403)

    monkeypatch.setattr(InstagramAdapter, "_graph", _denied)

    assert await InstagramAdapter().get_recent_commenters(IG, "t") == []


async def test_demographics_are_split_by_metric(monkeypatch):
    monkeypatch.setattr(InstagramAdapter, "_graph", _graph(_DEMOGRAPHICS))

    out = await InstagramAdapter().get_follower_demographics(IG, "t")

    assert out["age"] == [
        {"label": "18-24", "value": 420},
        {"label": "25-34", "value": 610},
    ]
    assert [g["label"] for g in out["gender"]] == ["female", "male"]
    assert out["cities"] == []


async def test_demographics_fall_back_to_dim_keys(monkeypatch):
    monkeypatch.setattr(InstagramAdapter, "_graph", _graph(_DEMOGRAPHICS_NO_VALUE_METRIC))

    out = await InstagramAdapter().get_follower_demographics(IG, "t")

    assert out["cities"] == [{"label": "Makkah", "value": 91}]
    assert out["age"] == []


# ── endpoint ──────────────────────────────────────────────────────────


async def test_audience_merges_dm_contacts_and_commenters(client, db, monkeypatch):
    await _seed(db)
    await _seed_contact(db, "reem", "Reem", "IGSID-9")

    async def _fake(self, ig_id, token, **kwargs):
        if "media" in kwargs or True:
            pass

    async def _commenters(self, ig_id, token, media_limit=10):
        return [
            {
                "source": "comment", "ig_id": "IGSID-1", "username": "layla", "name": "layla",
                "text": "Great service!", "like_count": 4, "occurred_at": "2026-02-02T10:00:00+0000",
                "media_id": "m1", "permalink": "https://instagram.com/p/abc/",
                "profile_url": "https://instagram.com/layla",
            }
        ]

    async def _demo(self, ig_id, token):
        return {"age": [{"label": "18-24", "value": 420}], "gender": [], "cities": [], "countries": []}

    monkeypatch.setattr(InstagramAdapter, "get_recent_commenters", _commenters)
    monkeypatch.setattr(InstagramAdapter, "get_follower_demographics", _demo)

    res = client.get(f"/api/v1/meta/instagram/{IG}/audience")

    assert res.status_code == 200
    body = res.json()
    sources = {p["source"] for p in body["people"]}
    assert sources == {"dm", "comment"}
    assert body["demographics"]["available"] is True
    # Every person has a real profile link.
    assert all(p["profile_url"] for p in body["people"])


async def test_audience_reports_why_demographics_are_missing(client, db, monkeypatch):
    await _seed(db)

    async def _none(self, ig_id, token, media_limit=10):
        return []

    async def _denied(self, ig_id, token):
        raise MetaAPIError("(#10) metric 'follower_demographics' is not supported", 400)

    monkeypatch.setattr(InstagramAdapter, "get_recent_commenters", _none)
    monkeypatch.setattr(InstagramAdapter, "get_follower_demographics", _denied)

    body = client.get(f"/api/v1/meta/instagram/{IG}/audience").json()

    demo = body["demographics"]
    assert demo["available"] is False
    assert "100 followers" in demo["reason"]
    # The people half still works - a demographics failure must not blank it.
    assert demo["age"] == []


async def test_audience_without_token_still_lists_dm_contacts(client, db):
    from app.modules.channels.meta.models import MetaConnection

    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=TENANT, provider="instagram",
        access_token_encrypted=None, status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(
        MetaAsset(
            id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=conn.id,
            provider="instagram", asset_type="ig_account", external_asset_id=IG, active=True,
        )
    )
    await db.commit()
    await _seed_contact(db, "reem", "Reem", "IGSID-9")

    body = client.get(f"/api/v1/meta/instagram/{IG}/audience").json()

    assert [p["username"] for p in body["people"]] == ["reem"]
    assert body["comments_unavailable"]


async def test_audience_unknown_account_is_404(client, db):
    assert client.get("/api/v1/meta/instagram/nope/audience").status_code == 404


async def test_audience_is_never_a_follower_list(client, db, monkeypatch):
    """Guard rail: the payload must not claim to expose followers."""
    await _seed(db)

    async def _none(self, ig_id, token, media_limit=10):
        return []

    async def _demo(self, ig_id, token):
        return {"age": [], "gender": [], "cities": [], "countries": []}

    monkeypatch.setattr(InstagramAdapter, "get_recent_commenters", _none)
    monkeypatch.setattr(InstagramAdapter, "get_follower_demographics", _demo)

    res = client.get(f"/api/v1/meta/instagram/{IG}/audience")

    assert res.status_code == 200
    text = res.text.lower()
    assert "follower_list" not in text
    # Only dm/comment sources exist.
    assert {p["source"] for p in res.json()["people"]} <= {"dm", "comment"}