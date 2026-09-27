"""Tracked, evidence-backed issues per location.

The dashboard's "Fix this" link used to point at the review list: it named a
problem and handed back reading material instead of anything to act on. This
module is the thing it should have pointed at.

The design rule throughout is that an issue may only exist if it can be
checked. It is built from the same checked meaning layer the intelligence
report uses, so the two can never disagree about how many reviews complained
about cleanliness. Reviews the meaning layer refused to categorise are held
out, exactly as they are in the report, and the count is returned so the gap
stays visible instead of quietly shrinking the list.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LocationIssue
from .subjects import SUBJECT_KEYS

logger = logging.getLogger(__name__)

# Statuses the merchant may set. `dismissed` is distinct from `done`: "this is
# not a real problem" is a different statement from "I fixed it", and merging
# them would lose the ability to tell a dismissed complaint from a resolved one.
OPEN_STATUSES = ("open", "in_progress")
ALL_STATUSES = ("open", "in_progress", "done", "dismissed")


def now() -> datetime:
    return datetime.now(timezone.utc)

# The review engine's issue vocabulary mapped onto the meaning layer's closed
# subjects. The engine's keys are regex-derived and stay as they are — they
# drive which reply strategy gets selected, which is a different job. This map
# exists so a reply and a tracked issue can be talked about in one language.
#
# `cancel` maps to None deliberately. Cancelling is not a category the
# vocabulary has, and quietly filing it under something adjacent is how an
# invented category gets in. None means "no equivalent — needs a person".
ISSUE_KEY_TO_SUBJECT: dict[str, str | None] = {
    "cleanliness": "cleanliness",
    "delivery": "delivery",
    "facility_premises": "facility_premises",
    "billing": "billing_payments",
    "pricing": "value_pricing",
    "staff_behavior": "staff_service",
    "wait_time": "speed_waiting",
    "food_quality": "product_quality",
    "food_temperature": "product_quality",
    "ambience": "facility_premises",
    "product_dissatisfaction": "product_quality",
    "product_quality": "product_quality",
    "service_quality": "staff_service",
    "cancel": None,
}


def _playbook(subject: str) -> tuple[str, str]:
    """The fix for a subject, from the deterministic playbook.

    Imported rather than duplicated so the issues page and the report can
    never quote different advice for the same problem.
    """
    from .intelligence_ai import _SUBJECT_PLAYBOOK

    return _SUBJECT_PLAYBOOK.get(subject, ("Review this directly", ""))


def _evidence_for(rows: list[dict], limit: int = 12) -> list[dict]:
    """Verbatim spans behind an issue, newest-heaviest, capped.

    These are quotes the meaning layer already checked appear in the source
    review, so the merchant can open the review and see the same words. Only
    negative reviews contribute: an issue built from praise is noise.
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if r["rating"] > 2:
            continue
        meaning = r.get("meaning") or {}
        for quote in (meaning.get("evidence") or [])[:2]:
            key = (r["review_id"], quote)
            if not quote or key in seen:
                continue
            seen.add(key)
            out.append({
                "review_id": r["review_id"],
                "quote": quote[:200],
                "rating": r["rating"],
            })
            if len(out) >= limit:
                return out
    return out


async def refresh_issues(
    db: AsyncSession,
    user_id: str,
    rows: list[dict],
) -> dict:
    """Recompute issues from loaded meaning rows. Never touches `status`.

    `rows` are the same dictionaries `_load_reviews` produces for the
    intelligence report, so the counts here and the counts in the report are
    the same numbers by construction.

    Returns a small summary for the caller to surface.
    """
    from .intelligence_ai import _held_out_counts, _meaning_groups

    groups = _meaning_groups(rows)
    now = datetime.now(timezone.utc)
    created = updated = 0

    for subject, group in groups.items():
        if subject not in SUBJECT_KEYS:
            continue
        negative = [r for r in group if r["rating"] <= 2]
        # An issue needs something to fix. A subject that only ever appears in
        # praise is a strength, not a problem, and filing it as an issue would
        # bury the real ones.
        if not negative:
            continue

        channel_ids = {r["channel_id"] for r in group if r.get("channel_id")}
        # A group can span channels when the report is account-wide. Issues are
        # tracked per location, so fall back to the group as one unit rather
        # than silently attributing it to whichever location sorted first.
        for channel_id in channel_ids or {""}:
            per_channel = [r for r in group if r.get("channel_id") == channel_id]
            if not per_channel:
                continue
            negatives = [r for r in per_channel if r["rating"] <= 2]
            if not negatives:
                continue
            ratings = [r["rating"] for r in per_channel]
            title, detail = _playbook(subject)

            existing = (
                await db.execute(
                    select(LocationIssue).where(
                        LocationIssue.user_id == user_id,
                        LocationIssue.channel_id == channel_id,
                        LocationIssue.subject == subject,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                db.add(LocationIssue(
                    user_id=user_id,
                    channel_id=channel_id,
                    subject=subject,
                    review_count=len(per_channel),
                    negative_count=len(negatives),
                    avg_rating=round(sum(ratings) / len(ratings), 2),
                    evidence=_evidence_for(per_channel),
                    title=title[:120],
                    detail=detail[:300],
                    status="open",
                    first_seen_at=now,
                    last_seen_at=now,
                ))
                created += 1
            else:
                # Status, resolution_note and resolved_at are intentionally not
                # written here. The merchant owns the outcome; refresh only
                # updates what the reviews currently say.
                existing.review_count = len(per_channel)
                existing.negative_count = len(negatives)
                existing.avg_rating = round(sum(ratings) / len(ratings), 2)
                existing.evidence = _evidence_for(per_channel)
                existing.title = title[:120]
                existing.detail = detail[:300]
                existing.last_seen_at = now
                updated += 1

    await db.commit()
    held = _held_out_counts(rows)
    return {
        "created": created,
        "updated": updated,
        "held_out": held,
    }


async def list_issues(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None = None,
    status: str | None = None,
) -> list[LocationIssue]:
    stmt = select(LocationIssue).where(LocationIssue.user_id == user_id)
    if channel_id:
        stmt = stmt.where(LocationIssue.channel_id == channel_id)
    if status:
        if status not in ALL_STATUSES:
            raise ValueError(f"unknown status: {status}")
        stmt = stmt.where(LocationIssue.status == status)
    stmt = stmt.order_by(
        LocationIssue.negative_count.desc(),
        LocationIssue.last_seen_at.desc(),
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_issue(
    db: AsyncSession,
    user_id: str,
    issue_id: str,
    status: str | None = None,
    resolution_note: str | None = None,
) -> LocationIssue | None:
    """Move an issue along. Returns None if it is not this tenant's."""
    if status is not None and status not in ALL_STATUSES:
        raise ValueError(f"unknown status: {status}")

    issue = (
        await db.execute(
            select(LocationIssue).where(
                LocationIssue.id == issue_id,
                LocationIssue.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if issue is None:
        return None

    if status is not None and status != issue.status:
        issue.status = status
        # Stamped on close, cleared on reopen, so the before/after comparison
        # stays honest if someone reopens an issue they fixed in a hurry.
        issue.resolved_at = now() if status in ("done", "dismissed") else None
    if resolution_note is not None:
        issue.resolution_note = resolution_note[:2000] or None
    await db.commit()
    await db.refresh(issue)
    return issue
