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
from pathlib import Path
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import AutoReplyConfig, Channel, ChannelMessage
from app.modules.channels.schemas import ChannelCreate
from app.modules.channels.service import (
    channel_listing_key,
    create_channel,
    find_channel_by_key,
    parse_channel_metadata,
)
from app.modules.users.models import User

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dedupe_channels import _merge_one  # noqa: E402  (ops script, same merge as the migration)


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


def _insight(uid: str, channel_id: str, review_id: str, **kw) -> ReviewInsight:
    base = dict(
        id=f"ri-{channel_id[-4:]}-{review_id}",
        user_id=uid,
        channel_id=channel_id,
        review_id=review_id,
        rating=5,
    )
    base.update(kw)
    return ReviewInsight(**base)


@pytest.mark.asyncio
async def test_merge_twins_with_identical_reviews(db, user_id):
    """Replay of the staging crash (c4d5e6f7a8b9 upgrade):

    twin channels hold the SAME review_ids, so a blind re-point dies on
    uq_review_insights_channel_review. The merge must fold instead:
    survivor wins, gaps filled, dupe rows gone, nothing lost.
    """
    db.add(_user(user_id))
    await db.commit()
    surv = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="google_reviews",
        platform_user_id="p", display_name="Shop", status="active", listing_key="kA",
    )
    dupe = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="google_reviews",
        platform_user_id="p", display_name="Shop", status="active", listing_key="kB",
    )
    db.add_all([surv, dupe])
    await db.commit()
    # Same review on both: survivor bare, dupe enriched.
    db.add(_insight(user_id, surv.id, "localith:r1"))
    db.add(
        _insight(
            user_id, dupe.id, "localith:r1",
            review_text="Great!", reviewer_name="Sara",
            replied=True, enrichment_status="done",
            sentiment="positive", topics=[{"name": "service"}],
        )
    )
    # Review only on the dupe: must move over.
    db.add(_insight(user_id, dupe.id, "localith:r2", review_text="Ok"))
    db.add(
        ChannelMessage(
            id=str(uuid.uuid4()), channel_id=dupe.id,
            direction="inbound", content="hi",
        )
    )
    db.add(AutoReplyConfig(channel_id=surv.id, enabled=True))
    db.add(AutoReplyConfig(channel_id=dupe.id, enabled=False))
    await db.commit()

    await _merge_one(db, surv.id, dupe.id)
    await db.commit()

    rows = (
        await db.execute(
            select(ReviewInsight).where(ReviewInsight.channel_id == surv.id)
        )
    ).scalars().all()
    by_review = {r.review_id: r for r in rows}
    assert set(by_review) == {"localith:r1", "localith:r2"}
    r1 = by_review["localith:r1"]
    assert r1.review_text == "Great!"
    assert r1.reviewer_name == "Sara"
    assert r1.replied is True
    assert r1.enrichment_status == "done"
    assert r1.sentiment == "positive"
    leftover = (
        await db.execute(
            select(ReviewInsight).where(ReviewInsight.channel_id == dupe.id)
        )
    ).scalars().all()
    assert leftover == []
    msgs = (
        await db.execute(
            select(ChannelMessage).where(ChannelMessage.channel_id == surv.id)
        )
    ).scalars().all()
    assert len(msgs) == 1
    cfgs = (
        await db.execute(
            select(AutoReplyConfig).where(AutoReplyConfig.channel_id == surv.id)
        )
    ).scalars().all()
    assert len(cfgs) == 1 and cfgs[0].enabled is True
    assert (
        await db.execute(
            select(AutoReplyConfig).where(AutoReplyConfig.channel_id == dupe.id)
        )
    ).scalars().all() == []
