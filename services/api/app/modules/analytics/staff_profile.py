"""Per-employee profile: credit aggregate, AI review analysis, credited reviews.

The staff registry (§33) already stores one mention row per review that names
an employee, with the sentiment the review AI assigned to that person. This
module turns those rows into the read model behind the profile page:

- aggregate credit: mention count, sentiment split, average star rating and the
  first/last time the employee was named;
- the AI's own read of each review, joined from ``review_insights`` (the
  meaning record: intent, subject, problem, verbatim evidence, confidence);
- only the reviews the employee was credited in — never the whole branch's
  review list.

Aggregation is bounded: the count/average query is a single indexed read, and
the review list is capped. Nothing here writes or calls an LLM; the analysis is
derived from the per-review enrichment that already ran.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ReviewInsight, ReviewStaffMention, StaffMember

# A profile page is not a data export: the latest mentions answer the question
# ("what are customers saying about this person?"). The aggregate above is
# computed over every mention, not just this page.
REVIEW_LIMIT = 200
_THEME_LIMIT = 8
_QUOTE_LIMIT = 3
_QUOTE_CHARS = 240


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def serialize_employee(member: StaffMember) -> dict:
    """The employee shape returned by every staff endpoint."""
    return {
        "id": member.id,
        "listing_id": member.listing_id,
        "name": member.name,
        "aliases": member.aliases or [],
        "active": bool(member.active),
        "normalized_name": member.normalized_name,
        "avatar_url": member.avatar_url,
        "phone": member.phone,
        "email": member.email,
        "job_title": member.job_title,
        "bio": member.bio,
    }


def _clean_list(value) -> list:
    return value if isinstance(value, list) else []


def _meaning(insight: ReviewInsight | None) -> dict:
    if insight is None or not isinstance(insight.meaning, dict):
        return {}
    return insight.meaning


def _ai_out(insight: ReviewInsight | None) -> dict | None:
    """The AI's per-review read, exactly as enrichment stored it.

    ``None`` means the review has no insight row yet (the mention pass can run
    before enrichment finishes), which the UI shows as "analysis pending"
    rather than as an empty interpretation.
    """
    if insight is None:
        return None
    meaning = _meaning(insight)
    return {
        "intent": meaning.get("intent"),
        "subject": meaning.get("subject"),
        "problem": meaning.get("problem"),
        "asks": _clean_list(meaning.get("asks")),
        "evidence": _clean_list(meaning.get("evidence")),
        "confidence": meaning.get("confidence"),
        "needs_human": bool(meaning.get("needs_human")),
        "version": meaning.get("version"),
    }


def _review_out(mention: ReviewStaffMention, insight: ReviewInsight | None) -> dict:
    return {
        "review_id": mention.review_id,
        "channel_id": mention.channel_id,
        "rating": mention.rating,
        "sentiment": mention.sentiment,
        "review_created_at": _iso(mention.review_created_at),
        "matched_name": mention.name_display,
        "reviewer_name": insight.reviewer_name if insight else None,
        "reviewer_photo_url": insight.reviewer_photo_url if insight else None,
        "review_text": insight.review_text if insight else None,
        "review_url": insight.review_url if insight else None,
        "ai": _ai_out(insight),
    }


def _themes(rows: list[tuple[ReviewStaffMention, ReviewInsight | None]]) -> list[dict]:
    """Topics the AI found in this employee's reviews, most-mentioned first.

    ``review_insights.topics`` is the review-level topic list; counting it only
    over reviews that name the employee keeps the profile about them, not about
    the branch.
    """
    counts: dict[str, dict] = {}
    for _, insight in rows:
        if insight is None:
            continue
        for topic in _clean_list(insight.topics):
            if not isinstance(topic, dict):
                continue
            name = str(topic.get("name") or "").strip()
            if not name:
                continue
            entry = counts.setdefault(
                name.lower(),
                {"name": name, "mentions": 0, "positive": 0, "neutral": 0, "negative": 0},
            )
            entry["mentions"] += 1
            sentiment = str(topic.get("sentiment") or "neutral").lower()
            if sentiment in ("positive", "neutral", "negative"):
                entry[sentiment] += 1
    ordered = sorted(
        counts.values(), key=lambda t: (-t["mentions"], t["name"].lower())
    )
    return ordered[:_THEME_LIMIT]


def _quote(text: str | None) -> str:
    body = (text or "").strip()
    if len(body) <= _QUOTE_CHARS:
        return body
    return body[: _QUOTE_CHARS - 1].rstrip() + "…"


def _quotes(
    rows: list[tuple[ReviewStaffMention, ReviewInsight | None]], sentiment: str
) -> list[dict]:
    out: list[dict] = []
    for mention, insight in rows:
        if mention.sentiment != sentiment:
            continue
        text = insight.review_text if insight else None
        if not (text or "").strip():
            continue
        out.append(
            {
                "review_id": mention.review_id,
                "quote": _quote(text),
                "rating": mention.rating,
                "reviewer_name": insight.reviewer_name if insight else None,
                "review_created_at": _iso(mention.review_created_at),
            }
        )
        if len(out) >= _QUOTE_LIMIT:
            break
    return out


def _summary(
    *,
    name: str,
    total: int,
    avg_rating: float | None,
    positive: int,
    neutral: int,
    negative: int,
    themes: list[dict],
) -> str:
    """A plain-language verdict from the counts and the AI's topics.

    Deterministic on purpose: this is the same read every time the page loads,
    it costs nothing, and it cannot drift from the numbers shown beside it.
    """
    if total == 0:
        return (
            f"No reviews mention {name} yet. Once customers name them, their "
            "rating and the AI's read of those reviews will appear here."
        )
    parts = [
        f"{name} is named in {total} review{'s' if total != 1 else ''} "
        f"with an average rating of {avg_rating:.1f}/5."
        if avg_rating is not None
        else f"{name} is named in {total} review{'s' if total != 1 else ''}."
    ]
    parts.append(
        f"{positive} positive, {neutral} neutral and {negative} negative."
    )
    if themes:
        top = ", ".join(t["name"] for t in themes[:3])
        parts.append(f"Customers most often mention {top} in those reviews.")
    if negative and positive >= negative:
        parts.append(
            "Most mentions are positive, but the negative reviews below are worth a look."
        )
    elif negative > positive:
        parts.append(
            "The negative mentions outweigh the positive ones — check the quotes "
            "below before the next shift."
        )
    return " ".join(parts)


async def staff_profile(
    db: AsyncSession,
    *,
    user_id: str,
    member_id: str,
    days: int | None = None,
    review_limit: int = REVIEW_LIMIT,
) -> dict | None:
    """Build the profile read model for one employee.

    ``days`` narrows the window (all-time when ``None``). The employee must
    belong to ``user_id``; a mismatch returns ``None`` so the router can answer
    404 rather than leaking another tenant's row.
    """
    member = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == member_id, StaffMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        return None

    base = [
        ReviewStaffMention.user_id == user_id,
        ReviewStaffMention.staff_member_id == member_id,
    ]
    cutoff: datetime | None = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        base.append(ReviewStaffMention.review_created_at >= cutoff)

    count = func.count()
    pos = func.sum(case((ReviewStaffMention.sentiment == "positive", 1), else_=0))
    neu = func.sum(case((ReviewStaffMention.sentiment == "neutral", 1), else_=0))
    neg = func.sum(case((ReviewStaffMention.sentiment == "negative", 1), else_=0))
    stats_row = (
        await db.execute(
            select(
                count,
                pos,
                neu,
                neg,
                func.avg(ReviewStaffMention.rating),
                func.min(ReviewStaffMention.review_created_at),
                func.max(ReviewStaffMention.review_created_at),
            ).where(*base)
        )
    ).one()

    total = int(stats_row[0] or 0)
    positive = int(stats_row[1] or 0)
    neutral = int(stats_row[2] or 0)
    negative = int(stats_row[3] or 0)
    avg_rating = float(stats_row[4]) if stats_row[4] is not None else None
    first_at = stats_row[5]
    last_at = stats_row[6]

    rows = (
        await db.execute(
            select(ReviewStaffMention, ReviewInsight)
            .outerjoin(
                ReviewInsight,
                and_(
                    ReviewStaffMention.user_id == ReviewInsight.user_id,
                    ReviewStaffMention.channel_id == ReviewInsight.channel_id,
                    ReviewStaffMention.review_id == ReviewInsight.review_id,
                ),
            )
            .where(*base)
            .order_by(
                func.coalesce(
                    ReviewStaffMention.review_created_at,
                    ReviewInsight.review_updated_at,
                    ReviewInsight.created_at,
                ).desc()
            )
            .limit(max(1, min(int(review_limit), 500)))
        )
    ).all()

    themes = _themes(rows)
    reviews = [_review_out(mention, insight) for mention, insight in rows]
    meaning_versions = [
        int(_meaning(insight).get("version") or 0)
        for _, insight in rows
        if insight is not None
    ]
    needs_human = sum(
        1 for _, insight in rows if insight is not None and _meaning(insight).get("needs_human")
    )

    return {
        "employee": serialize_employee(member),
        "window_days": days,
        "stats": {
            "mentions": total,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "positive_pct": round(positive / total * 100) if total else None,
            "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
            "first_mention_at": _iso(first_at),
            "last_mention_at": _iso(last_at),
        },
        "analysis": {
            # The profile's read comes from the review AI that already ran per
            # review; the aggregation itself is deterministic.
            "source": "review_ai",
            "meaning_version": max(meaning_versions) if meaning_versions else None,
            "summary": _summary(
                name=member.name,
                total=total,
                avg_rating=avg_rating,
                positive=positive,
                neutral=neutral,
                negative=negative,
                themes=themes,
            ),
            "top_themes": themes,
            "highlights": _quotes(rows, "positive"),
            "concerns": _quotes(rows, "negative"),
            "needs_human": needs_human,
        },
        "reviews": reviews,
    }