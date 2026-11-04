"""Google listing Q&A: worker sync and the draft → approve flow."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.analytics.qa_router import router as _qa_router  # noqa: F401
from app.modules.analytics.models import GoogleQuestionAnswer
from app.modules.channels.models import Channel
from app.modules.channels.reviews_worker import (
    _mark_qa_polled,
    _qa_due,
    _store_question_answer,
)
from app.modules.channels.service import encrypt_token


def _question(
    qid: str = "q1",
    text: str = "Do you deliver to Al Malqa?",
    *,
    merchant_answer: str | None = "Yes, we deliver there.",
) -> dict:
    answers = []
    if merchant_answer:
        answers.append({
            "name": f"accounts/a/locations/l/questions/{qid}/answers/a1",
            "text": merchant_answer,
            "author": {"displayName": "Owner", "type": "MERCHANT"},
            "createTime": "2026-11-01T10:00:00Z",
            "upvoteCount": 2,
        })
    answers.append({
        "name": f"accounts/a/locations/l/questions/{qid}/answers/a2",
        "text": "A customer answer",
        "author": {"displayName": "Sara", "type": "REGULAR_USER"},
    })
    return {
        "name": f"accounts/a/locations/l/questions/{qid}",
        "text": text,
        "author": {
            "displayName": "Sara",
            "type": "REGULAR_USER",
            "profilePhotoUrl": "https://example.com/sara.png",
        },
        "createTime": "2026-11-01T09:00:00Z",
        "upvoteCount": 4,
        "topAnswers": answers,
    }


async def _channel(db, user_id: str) -> Channel:
    ch = Channel(
        id="google-chan",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acct-1",
        display_name="Test business",
        status="active",
        access_token=encrypt_token("access-token"),
        refresh_token=encrypt_token("refresh-token"),
    )
    db.add(ch)
    await db.commit()
    return ch


def test_qa_poll_is_throttled_to_its_own_interval(user_id):
    from datetime import timedelta

    from app.modules.channels.models import Channel

    channel = Channel(
        id="qa-throttle",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="acct-1",
        display_name="Test",
        status="active",
        metadata_json="{}",
    )
    now = datetime.now(timezone.utc)
    assert _qa_due(channel, now) is True

    _mark_qa_polled(channel, now - timedelta(minutes=30))
    assert _qa_due(channel, now) is False

    _mark_qa_polled(channel, now - timedelta(minutes=61))
    assert _qa_due(channel, now) is True


@pytest.mark.asyncio
async def test_worker_keeps_merchant_answer_not_customer_answer(db, user_id):
    channel = await _channel(db, user_id)
    await _store_question_answer(db, channel, _question())
    await db.commit()

    row = (
        await db.execute(
            select(GoogleQuestionAnswer).where(
                GoogleQuestionAnswer.channel_id == channel.id
            )
        )
    ).scalar_one()
    assert row.question_text == "Do you deliver to Al Malqa?"
    assert row.answer_text == "Yes, we deliver there."
    assert row.answer_type == "MERCHANT"
    assert row.is_answered is True
    assert row.draft_status == "posted"
    assert row.upvote_count == 4
    assert row.asker_name == "Sara"


@pytest.mark.asyncio
async def test_worker_upsert_is_idempotent_and_updates_merchant_answer(db, user_id):
    channel = await _channel(db, user_id)
    await _store_question_answer(db, channel, _question())
    await db.commit()
    await _store_question_answer(
        db, channel, _question(text="Updated question", merchant_answer="Updated answer")
    )
    await db.commit()

    rows = (
        await db.execute(
            select(GoogleQuestionAnswer).where(
                GoogleQuestionAnswer.channel_id == channel.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].question_text == "Updated question"
    assert rows[0].answer_text == "Updated answer"
    assert rows[0].last_synced_at is not None


@pytest.mark.asyncio
async def test_list_questions_returns_unanswered_count(client, db, user_id):
    channel = await _channel(db, user_id)
    db.add_all([
        GoogleQuestionAnswer(
            id="qa-1",
            user_id=user_id,
            channel_id=channel.id,
            question_id="accounts/a/locations/l/questions/q1",
            question_text="Unanswered question",
            is_answered=False,
            created_at=datetime.now(timezone.utc),
        ),
        GoogleQuestionAnswer(
            id="qa-2",
            user_id=user_id,
            channel_id=channel.id,
            question_id="accounts/a/locations/l/questions/q2",
            question_text="Answered question",
            is_answered=True,
            answer_text="Yes",
            created_at=datetime.now(timezone.utc),
        ),
    ])
    await db.commit()

    resp = client.get("/api/v1/analytics/questions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["unanswered_count"] == 1
    assert {i["id"] for i in body["items"]} == {"qa-1", "qa-2"}


@pytest.mark.asyncio
async def test_approve_is_gone_after_google_retired_the_qa_api(
    client, db, user_id
):
    """Google discontinued the Q&A API on 2025-11-03; publishing fails
    closed with a clear 410 instead of attempting a dead endpoint."""
    channel = await _channel(db, user_id)
    row = GoogleQuestionAnswer(
        id="qa-3",
        user_id=user_id,
        channel_id=channel.id,
        question_id="accounts/a/locations/l/questions/q3",
        question_text="Do you have parking?",
        is_answered=False,
        draft_status="none",
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()

    draft = client.post(
        "/api/v1/analytics/questions/qa-3/draft",
        json={"answer_text": "Yes, free parking is available."},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["draft_status"] == "pending_approval"

    approved = client.post("/api/v1/analytics/questions/qa-3/approve")
    assert approved.status_code == 410, approved.text
    assert "retired" in approved.json()["detail"].lower()


@pytest.mark.asyncio
async def test_draft_reject_and_ignore(client, db, user_id):
    channel = await _channel(db, user_id)
    db.add(GoogleQuestionAnswer(
        id="qa-4",
        user_id=user_id,
        channel_id=channel.id,
        question_id="accounts/a/locations/l/questions/q4",
        question_text="Any vegan options?",
        is_answered=False,
        draft_status="none",
        created_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    drafted = client.post(
        "/api/v1/analytics/questions/qa-4/draft",
        json={"answer_text": "We have several vegan dishes."},
    )
    assert drafted.status_code == 200, drafted.text

    rejected = client.post("/api/v1/analytics/questions/qa-4/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["draft_status"] == "rejected"
    assert rejected.json()["draft_answer_text"] is None

    ignored = client.post("/api/v1/analytics/questions/qa-4/ignore")
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["is_ignored"] is True

    restored = client.post("/api/v1/analytics/questions/qa-4/unignore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_ignored"] is False
