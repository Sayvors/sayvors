"""AI-detected complaint themes (free-text problems) tracked as issues.

The review intelligence sees free-text problems ("lack of respect for
customers") that the closed-vocabulary issues never file. These tests pin the
path that turns those problems into tracked, merchant-owned issues, and that
feeds resolved ones into the AI's grounding.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics import issues as S
from app.modules.analytics.models import ReviewInsight


async def _seed(db, user_id, channel_id):
    db.add_all([
        ReviewInsight(
            user_id=user_id, channel_id=channel_id, review_id="pr-1", rating=1,
            review_text="The staff had no respect for customers at all.",
            reviewer_name="Ali",
            problems=[{"name": "lack of respect for customers", "severity": "high"}],
        ),
        ReviewInsight(
            user_id=user_id, channel_id=channel_id, review_id="pr-2", rating=2,
            review_text="They ignored us and were rude.",
            problems=[{"name": "lack of respect for customers", "severity": "medium"}],
        ),
        ReviewInsight(
            user_id=user_id, channel_id=channel_id, review_id="pr-3", rating=5,
            review_text="Amazing experience!",
            problems=[{"name": "great experience", "severity": "low"}],
        ),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_sync_creates_problem_issue_for_negative_mentions(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)
    out = await S.sync_problem_issues(db, user_id)
    assert out["created"] == 1
    assert out["updated"] == 0

    issues = await S.list_problem_issues(db, user_id)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.problem == "lack of respect for customers"
    assert issue.severity == "high"
    assert issue.mentions_last == 2
    assert issue.negative_count == 2
    assert issue.avg_rating == 1.5
    assert issue.status == "open"
    assert len(issue.evidence) == 2


@pytest.mark.asyncio
async def test_sync_never_overwrites_merchant_status(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)
    await S.sync_problem_issues(db, user_id)
    issue = (await S.list_problem_issues(db, user_id))[0]

    updated = await S.update_problem_issue(db, user_id, issue.id, status="done")
    assert updated.status == "done"
    assert updated.resolved_at is not None
    assert updated.mentions_at_resolve == 2

    # Refresh after the merchant marked it done: status survives.
    out = await S.sync_problem_issues(db, user_id)
    assert out["updated"] == 1
    again = (await S.list_problem_issues(db, user_id))[0]
    assert again.status == "done"
    assert again.resolved_at == updated.resolved_at


@pytest.mark.asyncio
async def test_done_reopens_when_problem_resurfaces_beyond_fix_level(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)
    await S.sync_problem_issues(db, user_id)
    issue = (await S.list_problem_issues(db, user_id))[0]
    await S.update_problem_issue(db, user_id, issue.id, status="done")

    # A third complaint arrives after the fix -> mentions 3 > 2 at resolve.
    db.add(ReviewInsight(
        user_id=user_id, channel_id=channel_id, review_id="pr-4", rating=1,
        review_text="Still no respect for customers.",
        problems=[{"name": "lack of respect for customers", "severity": "high"}],
    ))
    await db.commit()

    out = await S.sync_problem_issues(db, user_id)
    assert out["reopened"] == 1
    again = (await S.list_problem_issues(db, user_id))[0]
    assert again.status == "open"
    assert again.resolved_at is None


@pytest.mark.asyncio
async def test_praise_only_never_becomes_an_issue(db, user_id, channel_id):
    db.add(ReviewInsight(
        user_id=user_id, channel_id=channel_id, review_id="pr-5", rating=5,
        review_text="Great service, will come again.",
        problems=[{"name": "great service", "severity": "low"}],
    ))
    await db.commit()
    out = await S.sync_problem_issues(db, user_id)
    assert out["created"] == 0
    assert await S.list_problem_issues(db, user_id) == []


@pytest.mark.asyncio
async def test_resolved_problems_ground_the_ai(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)
    await S.sync_problem_issues(db, user_id)
    issue = (await S.list_problem_issues(db, user_id))[0]
    await S.update_problem_issue(db, user_id, issue.id, status="done")

    from app.modules.profile.facts_store import build_facts
    from app.modules.users.models import User

    db.add(User(
        id=user_id, email=f"{user_id}@test.dev", first_name="T", last_name="U",
        password_hash="x", onboarded=True,
    ))
    await db.commit()

    facts = await build_facts(db, user_id)
    assert "lack of respect for customers" in facts["business"]["addressed_complaints"]
