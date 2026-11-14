"""Staff mentions: matching, persistence, aggregation, unassigned bucket.

Covers §33 (employee mentions & per-employee reviews): the deterministic
name matcher, the idempotent mention pass, retro-linking, summary math, and
the API surface.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.staff_match import (
    match_staff_names,
    normalize_staff_name,
)
from app.modules.analytics.staff_mentions import (
    backfill_staff_mentions,
    link_unassigned_mentions,
    record_mentions,
    staff_summary,
    unmatched_names,
)
from app.modules.analytics.models import ReviewInsight, ReviewStaffMention, StaffMember
from app.modules.channels.models import Channel


# ── normalization ──

def test_normalize_staff_name_collapses_variants():
    # Arabic variants collapse (diacritics, hamza forms, ta marbuta):
    assert normalize_staff_name("أَحْمَد") == normalize_staff_name("احمد")
    assert normalize_staff_name("أحمد") == normalize_staff_name("احمد")
    assert normalize_staff_name("فاطمة") == normalize_staff_name("فاطمه")
    # Case/whitespace-insensitive (Latin):
    assert normalize_staff_name("  AL Bakhair ") == normalize_staff_name("al bakhair")
    # Honorifics drop:
    assert normalize_staff_name("Mr Ahmad") == normalize_staff_name("ahmad")
    assert normalize_staff_name("الأستاذ أحمد") == normalize_staff_name("احمد")
    assert normalize_staff_name("") == ""
    assert normalize_staff_name(None) == ""


# ── matching ──

class _Emp:
    def __init__(self, id, name, aliases=None, normalized_name=None):
        self.id = id
        self.name = name
        self.aliases = aliases or []
        self.normalized_name = normalized_name or normalize_staff_name(name)


def test_match_by_name_and_alias():
    # "Ahmed" is a spelling variant carried as an alias, not inferred.
    emps = [_Emp("s1", "Ahmad", aliases=["Ahmed"]),
            _Emp("s2", "Al Bakhair", aliases=["albakhair"])]
    out = match_staff_names(
        [{"name": "Ahmed", "sentiment": "positive"},
         {"name": "albakhair", "sentiment": "positive"}],
        emps,
    )
    assert out[0]["staff_member_id"] == "s1"
    assert out[1]["staff_member_id"] == "s2"
    assert all(o["staff_member_id"] is not None for o in out)


def test_unmatched_keeps_row_with_null_id():
    out = match_staff_names([{"name": "Mystery Person", "sentiment": "negative"}], [])
    assert out[0]["staff_member_id"] is None
    assert out[0]["name_normalized"] == normalize_staff_name("Mystery Person")
    assert out[0]["sentiment"] == "negative"


def test_empty_extraction_returns_nothing():
    assert match_staff_names([], [_Emp("s1", "Ahmad")]) == []
    assert match_staff_names(None, [_Emp("s1", "Ahmad")]) == []


# ── persistence (needs the app DB fixtures) ──

@pytest.fixture
async def _employee(db, user_id):
    member = StaffMember(
        user_id=user_id, listing_id="listing-1", name="Ahmad",
        normalized_name=normalize_staff_name("Ahmad"), aliases=["Ahmed"],
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
async def test_record_mentions_matches_and_persists(db, user_id, _employee):
    n = await record_mentions(
        db, user_id=user_id, channel_id="ch1", review_id="rev-1",
        rating=5, review_created_at=None,
        staff_entities=[{"name": "Ahmed", "sentiment": "positive"}],
    )
    assert n == 1
    rows = (await db.execute(
        ReviewStaffMention.__table__.select()
    )).mappings().all()
    assert rows[0]["staff_member_id"] == _employee.id


@pytest.mark.asyncio
async def test_record_mentions_is_idempotent(db, user_id):
    for _ in range(2):
        await record_mentions(
            db, user_id=user_id, channel_id="ch1", review_id="rev-2",
            rating=4, review_created_at=None,
            staff_entities=[{"name": "Sara", "sentiment": "neutral"}],
        )
    rows = (await db.execute(
        ReviewStaffMention.__table__.select()
    )).mappings().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unmatched_bucket_then_retro_link(db, user_id, _employee):
    from app.modules.analytics.staff_match import normalize_staff_name as norm

    # A name that matches nothing lands in the unassigned bucket.
    await record_mentions(
        db, user_id=user_id, channel_id="ch1", review_id="rev-3",
        rating=5, review_created_at=None,
        staff_entities=[{"name": "albakhair", "sentiment": "positive"}],
    )
    names = await unmatched_names(db, user_id=user_id)
    assert len(names) == 1
    assert names[0]["name_normalized"] == norm("albakhair")
    assert names[0]["mentions"] == 1

    # Retro-link after adding/choosing an employee.
    linked = await link_unassigned_mentions(
        db, user_id=user_id, name_normalized=norm("albakhair"),
        staff_member_id=_employee.id,
    )
    assert linked == 1
    assert await unmatched_names(db, user_id=user_id) == []


@pytest.mark.asyncio
async def test_summary_counts_and_trend(db, user_id, _employee):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    await record_mentions(
        db, user_id=user_id, channel_id="ch1", review_id="recent-1",
        rating=5, review_created_at=now - timedelta(days=2),
        staff_entities=[{"name": "Ahmad", "sentiment": "positive"}],
    )
    await record_mentions(
        db, user_id=user_id, channel_id="ch1", review_id="old-1",
        rating=2, review_created_at=now - timedelta(days=45),
        staff_entities=[{"name": "Ahmad", "sentiment": "negative"}],
    )
    summary = await staff_summary(db, user_id=user_id, days=30)
    assert len(summary) == 1

    row = summary[0]
    assert row["staff_member_id"] == _employee.id
    assert row["mentions"] == 1
    assert row["positive"] == 1
    assert row["negative"] == 0
    assert row["avg_rating"] == 5.0
    assert row["prior_mentions"] == 1
    assert row["trend"] == "flat"


@pytest.mark.asyncio
async def test_backfill_progresses_past_already_processed_reviews(db, user_id, channel_id):
    """Re-running backfill must move on to older reviews instead of rescanning
    the same newest ones (regression: the window+limit query re-selected the
    same rows every run, so tenants with >limit reviews never got older
    mentions)."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    db.add_all([
        ReviewInsight(
            user_id=user_id, channel_id=channel_id, review_id="bf-new",
            rating=5, review_text="Ahmad was great",
            meaning={"version": 99, "entities": {"staff": [
                {"name": "Ahmad", "sentiment": "positive"},
            ]}},
            created_at=now, review_updated_at=now,
        ),
        ReviewInsight(
            user_id=user_id, channel_id=channel_id, review_id="bf-old",
            rating=4, review_text="Sara helped me",
            meaning={"version": 99, "entities": {"staff": ["Sara"]}},
            created_at=now - timedelta(days=30),
            review_updated_at=now - timedelta(days=30),
        ),
    ])
    await db.commit()

    first = await backfill_staff_mentions(db, user_id=user_id, days=90, limit=1)
    assert first["scanned"] == 1
    assert first["mentions"] == 1

    second = await backfill_staff_mentions(db, user_id=user_id, days=90, limit=1)
    assert second["scanned"] == 1
    assert second["mentions"] == 1

    rows = (await db.execute(select(ReviewStaffMention))).scalars().all()
    assert {r.review_id for r in rows} == {"bf-new", "bf-old"}


@pytest.mark.asyncio
async def test_assign_unmatched_adds_the_spelling_as_an_alias(client, db, user_id, channel_id):
    """Assigning an unknown spelling must record it as an alias so future
    reviews using that spelling keep matching (retro-link alone only fixes
    history)."""
    emp = client.post(
        "/api/v1/staff",
        json={"name": "Al Bakhair", "listing_id": "loc-1"},
    ).json()
    key = normalize_staff_name("albakhair")
    db.add_all([
        ReviewStaffMention(
            user_id=user_id, channel_id=channel_id, review_id=f"am-{i}",
            name_normalized=key, name_display="albakhair",
            sentiment="neutral", rating=5, review_created_at=None,
        )
        for i in range(2)
    ])
    await db.commit()

    resp = client.post(
        "/api/v1/staff/unmatched/assign",
        json={"name_normalized": key, "staff_member_id": emp["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["linked"] == 2

    updated = client.get("/api/v1/staff").json()["employees"]
    emp_row = next(e for e in updated if e["id"] == emp["id"])
    assert "albakhair" in emp_row["aliases"]


@pytest.mark.asyncio
async def test_record_mentions_scopes_to_listing(db, user_id):
    """Same-named employees on different branches: a review from branch A
    must attach to A's employee, never B's."""
    a = StaffMember(
        user_id=user_id, listing_id="loc-a", name="Ahmad",
        normalized_name=normalize_staff_name("Ahmad"),
    )
    b = StaffMember(
        user_id=user_id, listing_id="loc-b", name="Ahmad",
        normalized_name=normalize_staff_name("Ahmad"),
    )
    db.add_all([a, b])
    await db.commit()

    n = await record_mentions(
        db, user_id=user_id, channel_id="ch-a", review_id="r-a",
        rating=5, review_created_at=None,
        staff_entities=[{"name": "Ahmad", "sentiment": "positive"}],
        listing_id="loc-a",
    )
    assert n == 1
    rows = (await db.execute(select(ReviewStaffMention))).scalars().all()
    assert len(rows) == 1
    assert rows[0].staff_member_id == a.id


@pytest.mark.asyncio
async def test_backfill_lists_per_branch(db, user_id):
    """The backfill resolves each review's branch before matching."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    ch_a = Channel(id="ch-a", user_id=user_id, platform="google_reviews",
                   platform_user_id="acc-a", listing_key="loc-a", status="active")
    ch_b = Channel(id="ch-b", user_id=user_id, platform="google_reviews",
                   platform_user_id="acc-b", listing_key="loc-b", status="active")
    db.add_all([ch_a, ch_b])
    a = StaffMember(
        user_id=user_id, listing_id="loc-a", name="Ahmad",
        normalized_name=normalize_staff_name("Ahmad"),
    )
    b = StaffMember(
        user_id=user_id, listing_id="loc-b", name="Ahmad",
        normalized_name=normalize_staff_name("Ahmad"),
    )
    db.add_all([a, b])
    db.add_all([
        ReviewInsight(
            user_id=user_id, channel_id="ch-a", review_id="bf-a",
            rating=5, review_text="Ahmad was great at branch A",
            meaning={"version": 99, "entities": {"staff": [
                {"name": "Ahmad", "sentiment": "positive"},
            ]}},
            created_at=now, review_updated_at=now,
        ),
        ReviewInsight(
            user_id=user_id, channel_id="ch-b", review_id="bf-b",
            rating=4, review_text="Ahmad helped at branch B",
            meaning={"version": 99, "entities": {"staff": [
                {"name": "Ahmad", "sentiment": "positive"},
            ]}},
            created_at=now - timedelta(days=1),
            review_updated_at=now - timedelta(days=1),
        ),
    ])
    await db.commit()

    result = await backfill_staff_mentions(db, user_id=user_id, days=90, limit=2)
    assert result["scanned"] == 2
    assert result["mentions"] == 2

    rows = (await db.execute(select(ReviewStaffMention))).scalars().all()
    by_review = {r.review_id: r.staff_member_id for r in rows}
    assert by_review == {"bf-a": a.id, "bf-b": b.id}
