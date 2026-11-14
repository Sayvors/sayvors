"""Plan regeneration quota (§34 item 4): max_regenerations_day.

Manual review-reply regenerations are counted in the durable
`regeneration_usage` table (one row per tenant per day). The cap is checked
before generation and the counter increments only after a successful
regeneration — worker auto-replies and failed retries never consume it.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.entitlements import get_entitlements
from app.modules.billing.models import Plan
from app.modules.channels.models import ReviewReply

pytestmark = pytest.mark.asyncio

CHANNEL = "test-channel-0000-0000-0000-000000000001"  # conftest channel_id fixture value
REPLY_ID = "test-reply-0000-0000-0000-000000000001"


async def _set_free_trial_regeneration_cap(db, cap: int) -> Plan:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    plan.max_regenerations_day = cap
    await db.flush()
    return plan


async def _seed_pending_reply(db, user_id: str, channel_id: str = CHANNEL) -> str:
    db.add(ReviewReply(
        id=REPLY_ID,
        channel_id=channel_id,
        review_id="accounts/1/locations/1/reviews/r1",
        rating=3,
        review_text="Food was late but tasty.",
        reviewer_name="Ali",
        reply_text="First draft",
        status="pending_approval",
        generation_attempt=1,
    ))
    await db.commit()
    return REPLY_ID


async def _fake_generate(config, channel, rating, review_text, reviewer_name, db, *,
                         review_id=None, attempt=1, previous_draft=None):
    return f"Fresh reply (attempt {attempt})", False


async def test_entitlements_expose_regeneration_cap(db, user_id):
    await _set_free_trial_regeneration_cap(db, 5)
    ent = await get_entitlements(user_id, db)
    assert ent.max_regenerations_day == 5
    assert ent.regeneration_quota_ok(0) is True
    assert ent.regeneration_quota_ok(4) is True
    assert ent.regeneration_quota_ok(5) is False


async def test_regenerate_blocked_at_zero_cap(client, db, user_id, channel_id, monkeypatch):
    """Cap 0 denies before any generation runs (no engine call)."""
    await _set_free_trial_regeneration_cap(db, 0)
    await _seed_pending_reply(db, user_id, channel_id)

    called = False

    async def should_not_run(*a, **k):
        nonlocal called
        called = True
        return "x", False

    monkeypatch.setattr(
        "app.modules.channels.review_reply.generate_auto_reply", should_not_run
    )
    resp = client.post(f"/api/v1/channels/{CHANNEL}/reviews/{REPLY_ID}/regenerate")
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "quota"
    assert called is False


async def test_regenerate_increments_then_blocks_at_cap(client, db, user_id, channel_id, monkeypatch):
    """Cap 1: first regeneration succeeds and consumes the day's quota; the
    second is denied without running the engine again."""
    await _set_free_trial_regeneration_cap(db, 1)
    await _seed_pending_reply(db, user_id, channel_id)
    monkeypatch.setattr(
        "app.modules.channels.review_reply.generate_auto_reply", _fake_generate
    )

    first = client.post(f"/api/v1/channels/{CHANNEL}/reviews/{REPLY_ID}/regenerate")
    assert first.status_code == 200

    second = client.post(f"/api/v1/channels/{CHANNEL}/reviews/{REPLY_ID}/regenerate")
    assert second.status_code == 403
    assert second.headers.get("X-Entitlement-Denied") == "quota"


async def test_regenerate_under_cap_succeeds(client, db, user_id, channel_id, monkeypatch):
    await _set_free_trial_regeneration_cap(db, 10)
    await _seed_pending_reply(db, user_id, channel_id)
    monkeypatch.setattr(
        "app.modules.channels.review_reply.generate_auto_reply", _fake_generate
    )

    resp = client.post(f"/api/v1/channels/{CHANNEL}/reviews/{REPLY_ID}/regenerate")
    assert resp.status_code == 200
    assert "Fresh reply" in resp.json()["reply_text"]
