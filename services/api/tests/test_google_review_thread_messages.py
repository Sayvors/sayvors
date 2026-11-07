"""Google review threads must show the merchant's public reply.

Replies posted before inbox mirroring existed live only in `review_replies`.
The thread read path synthesizes the outbound bubble instead of requiring a
backfill on every environment.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    ReviewReply,
)
from app.modules.channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
    list_thread_messages,
)
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

REVIEW_ID = "accounts/a/locations/l/reviews/r-1"
CONTACT = "google:thread-key"
CHANNEL_ID = "google-thread-channel-0000000001"


async def _seed(db, user_id: str) -> None:
    db.add(User(
        id=user_id,
        email="google-thread@example.com",
        first_name="Google",
        last_name="Owner",
        password_hash="x",
    ))
    db.add(Channel(
        id=CHANNEL_ID,
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acc",
        display_name="Branch",
        status="active",
    ))
    db.add(ChannelMessage(
        id="review-inbound-0000000000000000001",
        channel_id=CHANNEL_ID,
        platform_message_id=REVIEW_ID,
        direction="inbound",
        content=encrypt_message_content("Do you sell shawarma?"),
        content_type="review",
        status="read",
        contact_name="saeed alzahrani",
        contact_phone=encrypt_contact_phone(CONTACT),
        contact_phone_hash=hash_contact_phone(CONTACT),
    ))
    db.add(ReviewReply(
        id="reply-00000000000000000000000001",
        channel_id=CHANNEL_ID,
        review_id=REVIEW_ID,
        rating=5,
        review_text="Do you sell shawarma?",
        reviewer_name="saeed alzahrani",
        reply_text="Yes, we do — come by any evening.",
        status="posted",
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()


async def test_thread_includes_a_posted_reply_without_a_mirror_row(db, user_id):
    await _seed(db, user_id)
    user = await db.get(User, user_id)

    messages = await list_thread_messages(user, db, CHANNEL_ID, CONTACT)

    assert [m.content_type for m in messages] == ["review", "review_reply"]
    reply = messages[-1]
    assert reply.direction == "outbound"
    assert reply.platform_message_id == "google-reply:reply-00000000000000000000000001"


async def test_pending_reply_is_not_shown_as_sent(db, user_id):
    await _seed(db, user_id)
    user = await db.get(User, user_id)
    reply = await db.get(ReviewReply, "reply-00000000000000000000000001")
    reply.status = "pending_approval"
    await db.commit()

    messages = await list_thread_messages(user, db, CHANNEL_ID, CONTACT)

    assert [m.content_type for m in messages] == ["review"]


async def test_mark_thread_read_clears_the_server_counter(db, user_id):
    """Opening a conversation must clear the badge, not wait for a reply."""
    from app.modules.channels.models import ChannelThread
    from app.modules.channels.router import mark_thread_read

    await _seed(db, user_id)
    existing = (
        await db.execute(
            select(ChannelThread).where(
                ChannelThread.channel_id == CHANNEL_ID,
                ChannelThread.contact_phone_hash == hash_contact_phone(CONTACT),
            )
        )
    ).scalar_one()
    existing.unread_count = 3
    await db.commit()

    class _Ctx:
        def channel_level(self, _channel_id: str) -> str:
            return "view"

    result = await mark_thread_read(
        channel_id=CHANNEL_ID,
        contact_phone=CONTACT,
        ctx=_Ctx(),
        db=db,
    )

    assert result == {"unread": 0}
    row = await db.get(ChannelThread, existing.id)
    await db.refresh(row)
    assert row.unread_count == 0
