"""Tracked issues: the thing "Fix this" should have pointed at.

The dashboard's "Fix this" card named the dimension costing the most stars and
linked to the review list, so it promised a fix and delivered reading. These
pin the properties that make the replacement trustworthy:

  * an issue can only be built from meaning the report would also count
  * a category outside the closed vocabulary is refused, in code and in SQL
  * praise never becomes an issue
  * refresh never touches status, notes, or resolutions
  * the counts here and the counts in the report are the same numbers
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import TEST_ENGINE
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics import issues as S


def _test_session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


def _row(*, channel_id, review_id, rating, subject, evidence, text="x",
         needs_human=False, replied=False, meaning=True):
    """A loaded review row, shaped like `_load_reviews` produces."""
    return {
        "review_id": review_id,
        "channel_id": channel_id,
        "rating": rating,
        "text": text,
        "replied": replied,
        "problems": [],
        "meaning": (
            {
                "subject": subject,
                "evidence": evidence,
                "confidence": 0.9,
                "needs_human": needs_human,
                "source": "llm",
                "language": "en",
                "problem": "",
                "intent": "complaining",
                "asks": [],
                "entities": {},
                "negated": False,
                "intensity": 0.5,
                "reason": None,
            }
            if meaning else None
        ),
    }


# ── The vocabulary is the contract ───────────────────────────────

def test_every_engine_issue_key_is_accounted_for():
    """A key that silently maps nowhere is a key that becomes a new category.

    `cancel` maps to None on purpose: the vocabulary has no cancellation
    category, and quietly filing it under something adjacent is how an
    invented category gets in.
    """
    from app.modules.review_engine.issues import ISSUE_SEMANTICS

    for key in ISSUE_SEMANTICS:
        if key == "product_reference":  # a noun, not a complaint
            continue
        assert key in S.ISSUE_KEY_TO_SUBJECT, f"{key} has no mapping"


def test_mapped_subjects_are_real_subjects():
    from app.modules.analytics.subjects import SUBJECT_KEYS

    for key, subject in S.ISSUE_KEY_TO_SUBJECT.items():
        if subject is None:
            continue
        assert subject in SUBJECT_KEYS, f"{key} maps to unknown subject {subject}"


def test_every_subject_has_a_fix():
    from app.modules.analytics.subjects import SUBJECT_KEYS

    for subject in SUBJECT_KEYS:
        title, _ = S._playbook(subject)
        assert title, f"{subject} has no playbook entry"


# ── Building issues ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_is_created_from_a_negative_review(db, user_id, channel_id):
    rows = [
        _row(channel_id=channel_id, review_id="r1", rating=2,
             subject="cleanliness", evidence=["dirty bathroom"]),
    ]
    out = await S.refresh_issues(db, user_id, rows)

    assert out["created"] == 1
    issue = (await S.list_issues(db, user_id))[0]
    assert issue.subject == "cleanliness"
    assert issue.negative_count == 1
    assert issue.avg_rating == 2.0
    assert issue.status == "open"
    assert "cleaning" in issue.title.lower()
    assert issue.evidence[0]["quote"] == "dirty bathroom"


@pytest.mark.asyncio
async def test_praise_never_becomes_an_issue(db, user_id, channel_id):
    """A subject that only appears in praise is a strength, not a problem."""
    rows = [
        _row(channel_id=channel_id, review_id="r1", rating=5,
             subject="staff_service", evidence=["lovely staff"]),
    ]
    out = await S.refresh_issues(db, user_id, rows)
    assert out["created"] == 0
    assert await S.list_issues(db, user_id) == []


@pytest.mark.asyncio
async def test_unread_reviews_never_become_issues(db, user_id, channel_id):
    rows = [
        _row(channel_id=channel_id, review_id="r1", rating=1,
             subject="other", evidence=["bad"], needs_human=True),
        _row(channel_id=channel_id, review_id="r2", rating=1,
             subject="other", evidence=[], meaning=False),
    ]
    out = await S.refresh_issues(db, user_id, rows)
    assert out["created"] == 0
    # But the gap is reported rather than hidden.
    assert out["held_out"]["total"] == 2


@pytest.mark.asyncio
async def test_issue_counts_match_the_intelligence_report(db, user_id, channel_id):
    """The two surfaces must not tell different stories about the same data."""
    from app.modules.analytics.intelligence_ai import (
        _meaning_groups, _themes_from_groups,
    )

    rows = [
        _row(channel_id=channel_id, review_id=f"r{i}", rating=1,
             subject="facility_premises", evidence=["the building"])
        for i in range(3)
    ] + [
        _row(channel_id=channel_id, review_id="p1", rating=5,
             subject="staff_service", evidence=["great"])
    ]
    await S.refresh_issues(db, user_id, rows)

    theme = next(
        t for t in _themes_from_groups(_meaning_groups(rows))
        if t.name == "Facility & premises"
    )
    issue = (await S.list_issues(db, user_id))[0]
    assert issue.subject == "facility_premises"
    assert issue.review_count == theme.mentions
    assert issue.negative_count == 3


# ── The merchant owns the outcome ───────────────────────────────

@pytest.mark.asyncio
async def test_refresh_never_resurrects_a_resolved_issue(db, user_id, channel_id):
    rows = [_row(channel_id=channel_id, review_id="r1", rating=2,
                 subject="cleanliness", evidence=["dirty"])]
    await S.refresh_issues(db, user_id, rows)
    issue = (await S.list_issues(db, user_id))[0]

    await S.update_issue(db, user_id, issue.id, status="done",
                         resolution_note="Deep clean scheduled")
    done = await S.update_issue(db, user_id, issue.id)
    assert done.status == "done"
    assert done.resolution_note == "Deep clean scheduled"
    assert done.resolved_at is not None

    # New complaints arrive. The issue must NOT reopen itself, and the note the
    # merchant wrote must survive.
    rows2 = rows + [
        _row(channel_id=channel_id, review_id="r2", rating=1,
             subject="cleanliness", evidence=["still dirty"])
    ]
    await S.refresh_issues(db, user_id, rows2)
    after = await S.update_issue(db, user_id, issue.id)
    assert after.status == "done"
    assert after.resolution_note == "Deep clean scheduled"
    # ...but the evidence and counts did move, and last_seen_at says when.
    assert after.negative_count == 2
    assert after.last_seen_at >= done.last_seen_at


@pytest.mark.asyncio
async def test_reopening_clears_the_resolution_stamp(db, user_id, channel_id):
    """Otherwise the before/after comparison is anchored to the wrong date."""
    rows = [_row(channel_id=channel_id, review_id="r1", rating=2,
                 subject="cleanliness", evidence=["dirty"])]
    await S.refresh_issues(db, user_id, rows)
    issue = (await S.list_issues(db, user_id))[0]
    await S.update_issue(db, user_id, issue.id, status="done")
    reopened = await S.update_issue(db, user_id, issue.id, status="in_progress")
    assert reopened.resolved_at is None


@pytest.mark.asyncio
async def test_cannot_touch_another_tenants_issue(db, user_id, channel_id):
    rows = [_row(channel_id=channel_id, review_id="r1", rating=2,
                 subject="cleanliness", evidence=["dirty"])]
    await S.refresh_issues(db, user_id, rows)
    issue = (await S.list_issues(db, user_id))[0]
    assert await S.update_issue(db, "someone-else", issue.id, status="done") is None


@pytest.mark.asyncio
async def test_unknown_status_is_refused(db, user_id, channel_id):
    rows = [_row(channel_id=channel_id, review_id="r1", rating=2,
                 subject="cleanliness", evidence=["dirty"])]
    await S.refresh_issues(db, user_id, rows)
    issue = (await S.list_issues(db, user_id))[0]
    with pytest.raises(ValueError):
        await S.update_issue(db, user_id, issue.id, status="fixed-ish")


@pytest.mark.asyncio
async def test_issues_are_tracked_per_location(db, user_id, channel_id):
    from app.modules.channels.models import Channel

    other = Channel(
        id="99999999-9999-9999-9999-999999999999", user_id=user_id,
        platform="google_reviews", platform_user_id="acc-2",
        display_name="Second branch",
        listing_key="k2", status="connected",
    )
    db.add(other)
    await db.commit()

    rows = [
        _row(channel_id=channel_id, review_id="r1", rating=1,
             subject="cleanliness", evidence=["dirty"]),
        _row(channel_id=other.id, review_id="r1", rating=1,
             subject="cleanliness", evidence=["dirty"]),
    ]
    await S.refresh_issues(db, user_id, rows)

    assert len(await S.list_issues(db, user_id)) == 2
    assert len(await S.list_issues(db, user_id, channel_id=channel_id)) == 1


@pytest.mark.asyncio
async def test_evidence_is_capped_and_deduplicated(db, user_id, channel_id):
    rows = [
        _row(channel_id=channel_id, review_id=f"r{i}", rating=1,
             subject="cleanliness", evidence=["dirty", "dirty"])
        for i in range(20)
    ]
    await S.refresh_issues(db, user_id, rows)
    issue = (await S.list_issues(db, user_id))[0]
    assert len(issue.evidence) <= 12
    quotes = [(e["review_id"], e["quote"]) for e in issue.evidence]
    assert len(quotes) == len(set(quotes))


# ── API ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_list_api(client, user_id, channel_id):
    rows = [_row(channel_id=channel_id, review_id="r1", rating=2,
                 subject="cleanliness", evidence=["dirty bathroom"])]
    async with async_sessionmaker(
        TEST_ENGINE, class_=AsyncSession, expire_on_commit=False
    )() as s:
        await S.refresh_issues(s, user_id, rows)

    r = client.get("/api/v1/analytics/issues")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["open"] == 1
    assert body["items"][0]["subject_label"] == "Cleanliness"
    assert body["items"][0]["channel_name"]
    assert body["items"][0]["evidence"][0]["quote"] == "dirty bathroom"


@pytest.mark.asyncio
async def test_issue_patch_api_rejects_a_bad_status(client):
    # Unknown status fails schema validation before the lookup even happens.
    r = client.patch(
        "/api/v1/analytics/issues/00000000-0000-0000-0000-000000000000",
        json={"status": "fixed-ish"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_issue_patch_404s_for_a_missing_issue(client, user_id):
    r = client.patch(
        "/api/v1/analytics/issues/00000000-0000-0000-0000-000000000000",
        json={"status": "done"},
    )
    assert r.status_code == 404
