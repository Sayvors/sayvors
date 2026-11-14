"""Staff mention persistence + per-employee aggregation.

The mention pass runs wherever meaning extraction runs (the analytics
consumer and the 90-day backfill). Contract:

- Idempotent per (review, normalized name): a re-run upserts instead of
  duplicating, and rows for names the LLM no longer reports are deleted, so
  the table always mirrors the latest extraction.
- Matching is deterministic (staff_match): a mention naming a registered
  employee links to them; anything else lands in the unassigned bucket
  (staff_member_id NULL) and stays visible until the owner resolves it.
- Aggregation is bounded: summary queries filter by tenant + window and never
  scan without an index.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ReviewStaffMention, StaffMember
from .staff_match import match_staff_names, normalize_staff_name

logger = logging.getLogger(__name__)


async def listing_id_for_channel(db: AsyncSession, channel_id: str) -> str | None:
    """The Google location (branch) id for a channel, or None when unknown.

    Used to scope employee matching to the review's branch so a same-named
    employee at another branch cannot capture the mention. Resolution order
    mirrors the locations service: stored metadata location_id, listing_key,
    then the platform user id (account id).
    """
    import json as _json

    from ..channels.models import Channel

    channel = await db.get(Channel, channel_id)
    if channel is None:
        return None
    try:
        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    return (
        str(meta.get("location_id") or "").strip()
        or channel.listing_key
        or channel.platform_user_id
        or None
    )


async def _employees_for(db: AsyncSession, user_id: str, listing_id: str | None) -> list:
    """The tenant's active employees, optionally narrowed to one branch.

    An employee registered under a specific branch matches mentions from that
    branch's reviews. Mentions from a review whose channel maps to a different
    listing should not silently attach cross-branch, so when the caller knows
    the listing it filters; when it does not, matching stays tenant-wide (the
    common single-branch case must not lose mentions to a missing mapping).
    """
    stmt = select(StaffMember).where(
        StaffMember.user_id == user_id,
        StaffMember.active.is_(True),
    )
    if listing_id:
        stmt = stmt.where(StaffMember.listing_id == listing_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def record_mentions(
    db: AsyncSession,
    *,
    user_id: str,
    channel_id: str,
    review_id: str,
    rating: int,
    review_created_at: datetime | None,
    staff_entities: list[dict] | None,
    listing_id: str | None = None,
) -> int:
    """Sync the mention rows for one review to its extracted staff list.

    Returns the number of rows now attached to the review. Fail-soft by
    design: callers wrap this so an error never costs the review its reply.
    """
    cleaned = match_staff_names(
        staff_entities or [],
        await _employees_for(db, user_id, listing_id),
    )
    existing = (
        await db.execute(
            select(ReviewStaffMention).where(
                ReviewStaffMention.user_id == user_id,
                ReviewStaffMention.channel_id == channel_id,
                ReviewStaffMention.review_id == review_id,
            )
        )
    ).scalars().all()
    by_name = {m.name_normalized: m for m in existing}
    seen_keys: set[str] = set()

    for item in cleaned:
        key = item["name_normalized"]
        if not key or key in seen_keys:
            # The same normalized name twice in one review is one mention.
            continue
        seen_keys.add(key)
        row = by_name.pop(key, None)
        if row is None:
            row = ReviewStaffMention(
                user_id=user_id,
                channel_id=channel_id,
                review_id=review_id,
                name_normalized=key,
            )
        row.staff_member_id = item["staff_member_id"]
        row.name_display = item["name"]
        row.sentiment = item["sentiment"]
        row.rating = rating
        row.review_created_at = review_created_at
        db.add(row)

    # Names the latest extraction no longer reports are stale: drop them so
    # the table mirrors the review, not its history.
    for stale in by_name.values():
        await db.delete(stale)
    await db.flush()
    return len(seen_keys)


async def link_unassigned_mentions(
    db: AsyncSession,
    *,
    user_id: str,
    name_normalized: str,
    staff_member_id: str,
) -> int:
    """Retro-link every unmatched mention of one name to an employee.

    This is the "assign" action from the unassigned-names panel: the owner
    says "albakhair is actually Al Bakhair", and history updates in place.
    Returns the number of rows re-linked.
    """
    result = await db.execute(
        select(ReviewStaffMention).where(
            ReviewStaffMention.user_id == user_id,
            ReviewStaffMention.name_normalized == name_normalized,
            ReviewStaffMention.staff_member_id.is_(None),
        )
    )
    rows = result.scalars().all()
    for row in rows:
        row.staff_member_id = staff_member_id
        db.add(row)
    await db.flush()
    return len(rows)


async def unmatched_names(
    db: AsyncSession, *, user_id: str, limit: int = 50
) -> list[dict]:
    """Grouped unknown names: what the owner is asked to resolve.

    Each entry carries the display form seen most recently, the mention count
    and the newest date — ordered most-mention-first so the common names are
    on top.
    """
    result = await db.execute(
        select(
            ReviewStaffMention.name_normalized,
            func.max(ReviewStaffMention.name_display).label("display"),
            func.count().label("mentions"),
            func.max(ReviewStaffMention.review_created_at).label("latest"),
        )
        .where(
            ReviewStaffMention.user_id == user_id,
            ReviewStaffMention.staff_member_id.is_(None),
        )
        .group_by(ReviewStaffMention.name_normalized)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return [
        {
            "name_normalized": name,
            "name_display": display,
            "mentions": int(mentions),
            "latest": latest.isoformat() if latest else None,
        }
        for name, display, mentions, latest in result.all()
    ]


async def backfill_staff_mentions(
    db: AsyncSession,
    *,
    user_id: str,
    days: int = 90,
    limit: int = 300,
    reextract: bool = False,
) -> dict:
    """One-time pass: build mentions from reviews already enriched.

    Walks the tenant's non-removed insights inside the window, newest first,
    and derives mentions from the stored meaning's staff entities — no LLM
    calls when ``reextract`` is False, so this is cheap and safe to re-run.
    Old v2 meanings carry staff as plain strings; the matcher treats them as
    neutral, which is honest (the sentiment model was not run on them).

    Reviews that already have mention rows are skipped, so re-running
    progresses past the first ``limit`` rows toward the older ones instead of
    rescanning the same newest reviews forever. Only reviews with no staff
    entities at all never produce a row and are rescanned each run — that is
    cheap (no writes) and unavoidable without a separate processed marker.

    ``reextract=True`` additionally re-runs meaning extraction (LLM) for rows
    whose meaning is stale (version < current, never human-corrected). The
    row cap bounds the cost; re-running the endpoint continues where this
    pass stopped because completed rows no longer qualify.
    """
    from sqlalchemy import select

    from .enrichment import MEANING_VERSION, extract_meaning, is_human_corrected
    from .models import ReviewInsight

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    already_processed = (
        select(ReviewStaffMention.id)
        .where(
            ReviewStaffMention.user_id == user_id,
            ReviewStaffMention.channel_id == ReviewInsight.channel_id,
            ReviewStaffMention.review_id == ReviewInsight.review_id,
        )
        .exists()
    )
    rows = (
        await db.execute(
            select(ReviewInsight)
            .where(
                ReviewInsight.user_id == user_id,
                ReviewInsight.removed_at.is_(None),
                ReviewInsight.review_text.isnot(None),
                ~already_processed,
                func.coalesce(
                    ReviewInsight.review_updated_at, ReviewInsight.created_at
                )
                >= cutoff,
            )
            .order_by(
                func.coalesce(
                    ReviewInsight.review_updated_at, ReviewInsight.created_at
                ).desc()
            )
            .limit(limit)
        )
    ).scalars().all()

    # Branch scoping: resolve the Google location for each scanned channel in
    # one query so the matcher never cross-attaches a same-named employee
    # between branches.
    from ..channels.models import Channel

    channel_ids = {r.channel_id for r in rows if r.channel_id}
    listing_by_channel: dict[str, str | None] = {}
    if channel_ids:
        channels = (
            await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
        ).scalars().all()
        for c in channels:
            listing_by_channel[c.id] = await listing_id_for_channel(db, c.id)

    scanned = 0
    mentions = 0
    reextracted = 0
    for insight in rows:
        scanned += 1
        meaning = insight.meaning if isinstance(insight.meaning, dict) else {}
        stale = int(meaning.get("version") or 0) < MEANING_VERSION
        if reextract and stale and not is_human_corrected(meaning):
            try:
                insight.meaning = await extract_meaning(
                    text=insight.review_text,
                    rating=insight.rating,
                    reviewer_name=insight.reviewer_name,
                    tenant_id=insight.user_id,
                )
                reextracted += 1
            except Exception as e:  # noqa: BLE001 — use whatever we already had
                logger.warning(
                    "backfill meaning re-extract failed for %s: %s",
                    insight.review_id, e,
                )
        meaning = insight.meaning if isinstance(insight.meaning, dict) else {}
        staff_entities = (meaning.get("entities") or {}).get("staff") or []
        if not staff_entities:
            continue
        mentions += await record_mentions(
            db,
            user_id=user_id,
            channel_id=insight.channel_id,
            review_id=insight.review_id,
            rating=insight.rating,
            review_created_at=(
                insight.review_updated_at or insight.created_at
            ),
            staff_entities=staff_entities,
            listing_id=listing_by_channel.get(insight.channel_id),
        )
    await db.commit()
    return {
        "scanned": scanned,
        "mentions": mentions,
        "reextracted": reextracted,
    }


async def staff_summary(
    db: AsyncSession,
    *,
    user_id: str,
    listing_id: str | None = None,
    days: int = 30,
) -> list[dict]:
    """Per-employee performance in one read: counts, sentiment split, the
    average rating of reviews naming them, and the trend vs the prior window.

    Employees with no mentions in the window still appear (zeroed) so a new
    hire does not vanish from the owner's view.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    prior_start = window_start - timedelta(days=days)

    emp_stmt = select(StaffMember).where(
        StaffMember.user_id == user_id,
        StaffMember.active.is_(True),
    )
    if listing_id:
        emp_stmt = emp_stmt.where(StaffMember.listing_id == listing_id)
    employees = (await db.execute(emp_stmt)).scalars().all()

    rating_avg = func.avg(ReviewStaffMention.rating)
    pos = func.sum(case((ReviewStaffMention.sentiment == "positive", 1), else_=0))
    neu = func.sum(case((ReviewStaffMention.sentiment == "neutral", 1), else_=0))
    neg = func.sum(case((ReviewStaffMention.sentiment == "negative", 1), else_=0))
    base = [
        ReviewStaffMention.user_id == user_id,
        ReviewStaffMention.staff_member_id.isnot(None),
    ]
    if listing_id:
        # Mentions follow the review's channel; when the caller scopes to a
        # branch we match employees of that branch and keep the aggregation
        # tenant-wide for their ids (a mention has no listing column).
        emp_ids = {e.id for e in employees}
        if not emp_ids:
            return []
        base.append(ReviewStaffMention.staff_member_id.in_(emp_ids))

    current = (
        await db.execute(
            select(
                ReviewStaffMention.staff_member_id,
                func.count().label("mentions"),
                pos, neu, neg, rating_avg,
            )
            .where(*base, ReviewStaffMention.review_created_at >= window_start)
            .group_by(ReviewStaffMention.staff_member_id)
        )
    ).all()
    prior = (
        await db.execute(
            select(
                ReviewStaffMention.staff_member_id,
                func.count().label("mentions"),
            )
            .where(
                *base,
                ReviewStaffMention.review_created_at >= prior_start,
                ReviewStaffMention.review_created_at < window_start,
            )
            .group_by(ReviewStaffMention.staff_member_id)
        )
    ).all()

    current_by_id = {row[0]: row for row in current}
    prior_by_id = {row[0]: int(row[1]) for row in prior}

    out = []
    for emp in employees:
        row = current_by_id.get(emp.id)
        mentions = int(row[1]) if row else 0
        before = prior_by_id.get(emp.id, 0)
        avg = float(row[5]) if row and row[5] is not None else None
        out.append({
            "staff_member_id": emp.id,
            "name": emp.name,
            "listing_id": emp.listing_id,
            "mentions": mentions,
            "positive": int(row[2] or 0) if row else 0,
            "neutral": int(row[3] or 0) if row else 0,
            "negative": int(row[4] or 0) if row else 0,
            "avg_rating": round(avg, 2) if avg is not None else None,
            "prior_mentions": before,
            "trend": (
                "up" if mentions > before
                else "down" if mentions < before
                else "flat"
            ),
        })
    # Most-mentioned first so the owner sees the active staff on top.
    out.sort(key=lambda e: (-e["mentions"], e["name"]))
    return out
