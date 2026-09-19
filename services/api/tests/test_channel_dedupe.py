"""One listing = one channel row, at any worker count.

Covers the twin-row prevention stack:
- channel_listing_key: identity comes from the stable API IDs
  (Localith listing_id, Google location_id) — never the display name.
- Unique index (user_id, platform, listing_key): the second insert for one
  key fails, on sqlite (tests) exactly as on Postgres (prod).
- find_channel_by_key + create_channel: losers reuse the winner's row
  (create_channel raises ValueError -> HTTP 409).
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.channels.models import Channel
from app.modules.channels.schemas import ChannelCreate
from app.modules.channels.service import (
    channel_listing_key,
    create_channel,
    find_channel_by_key,
    parse_channel_metadata,
)
from app.modules.users.models import User


def _user(uid: str) -> User:
    return User(
        id=uid,
        first_name="T",
        last_name="U",
        email=f"{uid}@example.com",
        password_hash="x",
    )


# ── key derivation: IDs in, names never ──────────────────────────────


def test_localith_key_uses_listing_id():
    key = channel_listing_key(
        "google_reviews",
        {"provider": "localith", "listing_id": "abc123", "location_id": "ChIJX"},
    )
    assert key == "abc123"


def test_native_key_uses_location_id():
    key = channel_listing_key(
        "google_reviews", {"location_id": "locations/456", "account_name": "A"}
    )
    assert key == "locations/456"


def test_same_name_different_ids_are_different_listings():
    # Two branches sharing a display name must NEVER collapse.
    a = channel_listing_key("google_reviews", {"listing_id": "branch-1"})
    b = channel_listing_key("google_reviews", {"listing_id": "branch-2"})
    assert a != b


def test_key_none_without_identity():
    assert channel_listing_key("google_reviews", {}) is None
    assert channel_listing_key("google_reviews", {"provider": "localith"}) is None
    assert channel_listing_key("facebook", {"listing_id": "x"}) is None


def test_parse_metadata_never_raises():
    assert parse_channel_metadata(None) == {}
    assert parse_channel_metadata("not-json{{{") == {}
    assert parse_channel_metadata("[1,2]") == {}
    assert parse_channel_metadata('{"listing_id": "a"}') == {"listing_id": "a"}


# ── database: twins rejected, winner reused ──────────────────────────


@pytest.mark.asyncio
async def test_unique_index_rejects_twin_row(db, user_id):
    db.add(_user(user_id))
    await db.commit()
    db.add(
        Channel(
            id=str(uuid.uuid4()), user_id=user_id, platform="google_reviews",
            platform_user_id="p", display_name="Same Branch",
            status="active", listing_key="abc123",
        )
    )
    await db.commit()
    db.add(
        Channel(
            id=str(uuid.uuid4()), user_id=user_id, platform="google_reviews",
            platform_user_id="p", display_name="Same Branch",
            status="active", listing_key="abc123",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_null_keys_never_conflict(db, user_id):
    db.add(_user(user_id))
    await db.commit()
    for _ in range(2):
        db.add(
            Channel(
                id=str(uuid.uuid4()), user_id=user_id, platform="facebook",
                platform_user_id="p", display_name="FB", status="active",
                listing_key=None,
            )
        )
    await db.commit()  # must not raise


@pytest.mark.asyncio
async def test_find_channel_by_key(db, user_id):
    db.add(_user(user_id))
    await db.commit()
    ch = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="google_reviews",
        platform_user_id="p", display_name="B", status="active", listing_key="k1",
    )
    db.add(ch)
    await db.commit()
    found = await find_channel_by_key(db, user_id, "google_reviews", "k1")
    assert found is not None and found.id == ch.id
    assert await find_channel_by_key(db, user_id, "google_reviews", "nope") is None


@pytest.mark.asyncio
async def test_create_channel_second_call_conflicts(db):
    uid = f"u-{uuid.uuid4().hex[:8]}"
    user = _user(uid)
    db.add(user)
    await db.commit()
    body = ChannelCreate(
        platform="google_reviews", display_name="Shop", location_id="loc-9"
    )
    first = await create_channel(body, user, db)
    assert first.listing_key == "loc-9"
    with pytest.raises(ValueError, match="already connected"):
        await create_channel(body, user, db)
    rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == uid, Channel.listing_key == "loc-9"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
