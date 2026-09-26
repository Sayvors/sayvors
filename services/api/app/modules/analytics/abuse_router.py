from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from .models import ReviewInsight
from .schemas import AbuseFlagBody, AbuseVerdictBody, ReviewInsightItem

router = APIRouter(prefix="/api/v1/analytics", tags=["abuse"])


# -- Abusive review reporting -------------------------------------
# Google's Business Profile API cannot file a policy report: `reviews`
# supports list/get/update/delete (delete removes YOUR reply) and
# `reviewReply`, and there is no report method. So Sayvors records the
# decision, hands the merchant a deep link to the exact review, and tracks
# that they did it. The model triages; a human decides.


async def _owned_insight(db: AsyncSession, insight_id: str, user: User) -> ReviewInsight:
    insight = (
        await db.execute(
            select(ReviewInsight).where(ReviewInsight.id == insight_id)
        )
    ).scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="Review insight not found")
    if insight.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your review")
    return insight


@router.post("/reviews/insights/{insight_id}/flag-abuse", response_model=ReviewInsightItem)
async def flag_abusive_review(
    insight_id: str,
    body: AbuseFlagBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flag a review as abusive and score it.

    The score is advisory. Nothing is sent to Google and no reply is published;
    the merchant files the report themselves from the link we return.
    """
    insight = await _owned_insight(db, insight_id, user)
    insight.abuse_flagged = True
    if body.note:
        insight.abuse_note = body.note[:2000]
    # Re-triage clears the previous human decision: the merchant raising the
    # flag again means they want it looked at again.
    insight.abuse_verdict = None
    insight.abuse_reviewed_at = None

    from .abuse_triage import assess_review

    assessment = await assess_review(
        text=insight.review_text,
        rating=insight.rating,
        reviewer_name=insight.reviewer_name,
        tenant_id=user.id,
    )
    if assessment is not None:
        insight.abuse_score = assessment.score
        insight.abuse_labels = assessment.labels
    else:
        # Unknown, not clean. Leaving the old score would be misleading.
        insight.abuse_score = None
        insight.abuse_labels = []

    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return ReviewInsightItem.model_validate(insight)


@router.post("/reviews/insights/{insight_id}/abuse-verdict", response_model=ReviewInsightItem)
async def set_abuse_verdict(
    insight_id: str,
    body: AbuseVerdictBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the human decision: confirmed (a real violation) or dismissed."""
    insight = await _owned_insight(db, insight_id, user)
    insight.abuse_verdict = body.verdict
    insight.abuse_reviewed_at = datetime.now(timezone.utc)
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return ReviewInsightItem.model_validate(insight)


@router.post("/reviews/insights/{insight_id}/abuse-reported", response_model=ReviewInsightItem)
async def mark_abuse_reported(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm the merchant filed the report in the Google Business Profile."""
    insight = await _owned_insight(db, insight_id, user)
    insight.abuse_reported_at = datetime.now(timezone.utc)
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return ReviewInsightItem.model_validate(insight)


@router.post("/reviews/insights/{insight_id}/clear-abuse", response_model=ReviewInsightItem)
async def clear_abuse_flag(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw the flag - the merchant decided this review is fine after all."""
    insight = await _owned_insight(db, insight_id, user)
    insight.abuse_flagged = False
    insight.abuse_verdict = None
    insight.abuse_reviewed_at = None
    insight.abuse_score = None
    insight.abuse_labels = []
    insight.abuse_reported_at = None
    db.add(insight)
    await db.commit()
    await db.refresh(insight)
    return ReviewInsightItem.model_validate(insight)
