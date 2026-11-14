"""Plan ticket-assignment gate (§34 item 12): the `ticket_assignment` feature key.

Both ticket surfaces — inbox thread assignment and review-issue assignment —
are gated on the write path. Reads (the assignees picker) stay open.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.billing.models import Plan
from app.modules.channels.models import ReviewIssue
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

CHANNEL = "test-channel-0000-0000-0000-000000000001"  # conftest channel_id fixture value
ISSUE_ID = "test-issue-0000-0000-0000-000000000001"


async def _set_free_trial_ticket_assignment(db, enabled: bool) -> None:
    plan = (
        await db.execute(select(Plan).where(Plan.slug == "free-trial"))
    ).scalar_one()
    features = dict(plan.features or {})
    features["ticket_assignment"] = enabled
    plan.features = features
    await db.flush()


async def _seed_issue(db, user_id: str, channel_id: str = CHANNEL) -> str:
    db.add(ReviewIssue(
        id=ISSUE_ID,
        tenant_id=user_id,
        channel_id=channel_id,
        review_id="accounts/1/locations/1/reviews/r1",
        rating=2,
        reviewer_name="Ali",
    ))
    await db.commit()
    return ISSUE_ID


async def test_inbox_assignment_denied_without_feature(client, db, channel_id):
    await _set_free_trial_ticket_assignment(db, False)
    resp = client.patch(
        f"/api/v1/inbox/threads/{CHANNEL}/+966500000000/assignee",
        json={"assigned_to": None},
    )
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "ticket_assignment"


async def test_review_issue_assignment_denied_without_feature(client, db, user_id, channel_id):
    await _set_free_trial_ticket_assignment(db, False)
    await _seed_issue(db, user_id, channel_id)
    resp = client.patch(
        f"/api/v1/reviews/issues/{ISSUE_ID}",
        json={"assigned_to": "some-user"},
    )
    assert resp.status_code == 403
    assert resp.headers.get("X-Entitlement-Denied") == "ticket_assignment"


async def test_review_issue_update_without_assignment_not_gated(client, db, user_id, channel_id):
    """Editing status/priority is not an assignment; it must keep working."""
    await _set_free_trial_ticket_assignment(db, False)
    await _seed_issue(db, user_id, channel_id)
    resp = client.patch(
        f"/api/v1/reviews/issues/{ISSUE_ID}",
        json={"priority": "high"},
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == "high"


async def test_inbox_assignees_read_open(client, db, monkeypatch):
    await _set_free_trial_ticket_assignment(db, False)

    async def fake_assignable(db, tenant_id, channel_id):
        return []

    monkeypatch.setattr(
        "app.modules.channels.assignment.assignable_users", fake_assignable
    )
    resp = client.get(f"/api/v1/inbox/assignees?channel_id={'ch' + '1' * 34}")
    assert resp.status_code == 200
    assert resp.json()["assignees"] == []
