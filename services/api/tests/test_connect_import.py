"""First-connect Google import session lifecycle."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.analytics.models import ReviewInsight
from app.modules.channels import connect_import as ci
from app.modules.channels import router as channels_router
from app.modules.channels.google_reviews import GoogleReview
from app.modules.channels.models import (
    Channel,
    ConnectImportItem,
    ConnectImportSession,
    ReviewReply,
)


class _Ctx:
    def __init__(self, user_id):
        self.user = type("User", (), {"id": user_id, "tenant_id": None})()


def _review(review_id: str, *, rating: int = 5, text: str = "Great") -> GoogleReview:
    return GoogleReview(
        review_id=review_id,
        rating=rating,
        text=text,
        reviewer_name="Tester",
        updated_at=datetime.now(timezone.utc) - timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_fetch_phase_counts_all_and_marks_existing_replies(
    db, user_id, channel_id, monkeypatch
):
    existing_id = "accounts/a/locations/l/reviews/existing"
    new_id = "accounts/a/locations/l/reviews/new"
    from app.modules.channels.service import encrypt_token

    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("token")
    db.add(
        ReviewReply(
            channel_id=channel_id,
            review_id=existing_id,
            rating=5,
            review_text="Great",
            reviewer_name="Tester",
            reply_text="Thanks",
            status="pending_approval",
        )
    )
    await db.commit()

    async def _fake_fetch(channel):
        return channel, [_review(existing_id), _review(new_id, rating=4)], None

    monkeypatch.setattr(ci, "_fetch_channel_reviews", _fake_fetch)
    session = await ci.create_session(db, user_id)
    await ci._fetch_phase(db, session)
    await db.refresh(session)

    assert session.status == "awaiting_scope"
    assert session.total_locations == 1
    assert session.fetched_locations == 1
    assert session.total_reviews == 2
    assert session.fetched_reviews == 2

    items = (
        await db.execute(
            select(ConnectImportItem).where(ConnectImportItem.session_id == session.id)
        )
    ).scalars().all()
    by_review = {item.review_id: item for item in items}
    assert by_review[existing_id].status == "already_replied"
    assert by_review[new_id].status == "pending"
    assert await db.execute(
        select(ReviewInsight).where(ReviewInsight.channel_id == channel_id)
    ) is not None


@pytest.mark.asyncio
async def test_start_generation_applies_scope_only_to_pending_items(db, user_id, channel_id):
    session = ConnectImportSession(
        user_id=user_id, status="awaiting_scope", scope_days=180,
        total_locations=1, fetched_locations=1, total_reviews=2, fetched_reviews=2,
    )
    db.add(session)
    await db.flush()
    recent = ConnectImportItem(
        session_id=session.id, channel_id=channel_id,
        review_id="recent", rating=5, status="pending",
        review_time=datetime.now(timezone.utc) - timedelta(days=10),
    )
    old = ConnectImportItem(
        session_id=session.id, channel_id=channel_id,
        review_id="old", rating=5, status="pending",
        review_time=datetime.now(timezone.utc) - timedelta(days=100),
    )
    db.add_all([recent, old])
    await db.commit()

    await ci.start_generation(db, session, 30)
    await db.refresh(session)
    await db.refresh(recent)
    await db.refresh(old)

    assert session.status == "generating"
    assert session.scope_days == 30
    assert recent.status == "pending"
    assert old.status == "outside_scope"


@pytest.mark.asyncio
async def test_publish_selection_marks_only_selected_drafts(db, user_id, channel_id):
    session = ConnectImportSession(user_id=user_id, status="ready")
    db.add(session)
    await db.flush()
    first = ConnectImportItem(
        session_id=session.id, channel_id=channel_id, review_id="r1",
        rating=5, status="draft_ready",
    )
    second = ConnectImportItem(
        session_id=session.id, channel_id=channel_id, review_id="r2",
        rating=5, status="draft_ready",
    )
    db.add_all([first, second])
    await db.commit()

    await ci.request_publish(db, session, item_ids=[first.id], publish_all=False)
    await db.refresh(session)
    await db.refresh(first)
    await db.refresh(second)

    assert session.status == "publishing"
    assert first.selected is True
    assert second.selected is False

    events = await ci.session_events(db, session.id)
    assert any("Posting your replies" in event.message for event in events)

    with pytest.raises(ValueError):
        await ci.request_publish(db, session, item_ids=[], publish_all=False)


@pytest.mark.asyncio
async def test_generate_one_creates_pending_draft(db, user_id, channel_id, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session = ConnectImportSession(
        user_id=user_id, status="generating", scope_days=180,
        total_locations=1, fetched_locations=1, total_reviews=1, fetched_reviews=1,
        total_drafts=1,
    )
    db.add(session)
    await db.flush()
    item = ConnectImportItem(
        session_id=session.id, channel_id=channel_id,
        review_id="accounts/a/locations/l/reviews/g", rating=5,
        reviewer_name="Tester", review_text="Great", status="pending",
        review_time=datetime.now(timezone.utc),
    )
    db.add(item)
    await db.commit()

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    async def _fake_generate(*args, **kwargs):
        return "Thanks for visiting!", False

    monkeypatch.setattr(ci, "generate_auto_reply", _fake_generate)
    await ci._generate_one(session.id, item.id, asyncio.Semaphore(1))

    await db.refresh(item)
    await db.refresh(session)
    assert item.status == "draft_ready"
    assert item.reply_id is not None
    assert session.drafts_ready == 1
    reply = await db.get(ReviewReply, item.reply_id)
    assert reply is not None
    assert reply.status == "pending_approval"
    assert reply.reply_text == "Thanks for visiting!"


@pytest.mark.asyncio
async def test_publish_one_posts_only_the_selected_draft(db, user_id, channel_id, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    reply = ReviewReply(
        channel_id=channel_id, review_id="accounts/a/locations/l/reviews/p",
        rating=5, review_text="Great", reviewer_name="Tester",
        reply_text="Thanks!", status="pending_approval",
    )
    db.add(reply)
    await db.flush()
    session = ConnectImportSession(user_id=user_id, status="publishing")
    db.add(session)
    await db.flush()
    item = ConnectImportItem(
        session_id=session.id, channel_id=channel_id,
        review_id=reply.review_id, rating=5, status="draft_ready",
        reply_id=reply.id, selected=True,
    )
    db.add(item)
    await db.commit()

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def set_known_expiry(self, value):
            pass

        async def refresh_access_token(self):
            return "token"

        async def reply_to_review(self, review_id, text):
            return None

        async def confirm_reply_live(self, review_id, attempts=3):
            return True

        async def close(self):
            pass

    monkeypatch.setattr(ci, "GoogleReviewsClient", _FakeClient)
    await ci._publish_one(session.id, item.id, asyncio.Semaphore(1))

    await db.refresh(item)
    await db.refresh(reply)
    assert item.status == "published"
    assert reply.status == "posted"
    events = await ci.session_events(db, session.id)
    assert any(
        event.level == "success" and "is live on Google" in event.message
        for event in events
    )


@pytest.mark.asyncio
async def test_manual_generation_reopens_an_out_of_scope_item(db, user_id, channel_id):
    session = ConnectImportSession(user_id=user_id, status="ready", total_drafts=0)
    db.add(session)
    await db.flush()
    item = ConnectImportItem(
        session_id=session.id, channel_id=channel_id, review_id="r-old",
        rating=5, status="outside_scope",
    )
    db.add(item)
    await db.commit()

    await ci.request_item_generation(db, session, item.id)
    await db.refresh(session)
    await db.refresh(item)
    assert item.status == "pending"
    assert session.status == "generating"
    assert session.total_drafts == 1


@pytest.mark.asyncio
async def test_import_endpoint_is_tenant_scoped_and_returns_locations(
    db, user_id, channel_id
):
    session = await ci.create_session(db, user_id)
    db.add(
        ConnectImportItem(
            session_id=session.id,
            channel_id=channel_id,
            review_id="accounts/a/locations/l/reviews/1",
            location_name="Test Burgers",
            reviewer_name="Tester",
            rating=5,
            review_text="Great",
            status="already_replied",
            review_time=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    out = await channels_router.get_google_import_session(
        session.id, ctx=_Ctx(user_id), db=db
    )
    assert out.id == session.id
    assert out.progress.total_locations == 0
    assert len(out.locations) == 1
    assert out.locations[0].items[0].status == "already_replied"
    assert any(
        event["message"] == "Google is connected. We're getting your reviews ready."
        for event in out.events
    )

    with pytest.raises(channels_router.HTTPException):
        await channels_router.get_google_import_session(
            session.id, ctx=_Ctx("another-user"), db=db
        )
