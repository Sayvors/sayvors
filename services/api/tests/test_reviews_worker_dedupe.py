"""The review mirror must respect the global platform_message_id index.

The same Google review can be polled under two channel rows (the same location
connected twice, or two tenants connecting it). The existence check used to be
scoped by channel_id while the unique index is global, so the second insert
raised UniqueViolation and poisoned the whole poll session.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.reviews_worker import _store_inbound_review

pytestmark = pytest.mark.asyncio

REVIEW_ID = "accounts/a/locations/l/reviews/duplicate-1"


async def _seed(db, user_id: str) -> None:
    db.add_all(
        [
            Channel(
                id="dedupe-channel-a",
                user_id=user_id,
                platform="google_reviews",
                platform_user_id="acc",
                display_name="Branch A",
                status="active",
            ),
            Channel(
                id="dedupe-channel-b",
                user_id=user_id,
                platform="google_reviews",
                platform_user_id="acc",
                display_name="Branch B",
                status="active",
            ),
        ]
    )
    await db.commit()


def _review():
    return SimpleNamespace(
        review_id=REVIEW_ID,
        text="Great service",
        rating=5,
        reviewer_name="Saeed",
    )


async def test_same_review_on_two_channels_is_mirrored_once(db, user_id):
    await _seed(db, user_id)

    await _store_inbound_review(db, "dedupe-channel-a", _review())
    # Must not raise, and must not create a second row.
    await _store_inbound_review(db, "dedupe-channel-b", _review())

    count = (
        await db.execute(
            select(func.count())
            .select_from(ChannelMessage)
            .where(ChannelMessage.platform_message_id == REVIEW_ID)
        )
    ).scalar_one()
    assert count == 1
