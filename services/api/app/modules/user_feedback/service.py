from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserFeedback
from .schemas import FeedbackCreate

# One feedback per user per cooldown window — prevents spam.
FEEDBACK_COOLDOWN_HOURS = 24


class FeedbackCooldownError(Exception):
    """Raised when a user tries to submit feedback more than once per cooldown."""


async def get_feedback_status(user_id: str, db: AsyncSession) -> dict:
    latest = (
        await db.execute(
            select(UserFeedback)
            .where(UserFeedback.user_id == user_id)
            .order_by(UserFeedback.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not latest or not latest.created_at:
        return {"can_submit": True, "last_submitted_at": None, "cooldown_hours": FEEDBACK_COOLDOWN_HOURS}
    elapsed = datetime.now(timezone.utc) - latest.created_at
    can_submit = elapsed >= timedelta(hours=FEEDBACK_COOLDOWN_HOURS)
    return {
        "can_submit": can_submit,
        "last_submitted_at": latest.created_at.isoformat(),
        "cooldown_hours": FEEDBACK_COOLDOWN_HOURS,
    }


async def create_feedback(user_id: str, body: FeedbackCreate, db: AsyncSession) -> dict:
    status = await get_feedback_status(user_id, db)
    if not status["can_submit"]:
        raise FeedbackCooldownError(
            f"You already submitted feedback recently. Try again in {FEEDBACK_COOLDOWN_HOURS} hours."
        )
    row = UserFeedback(
        user_id=user_id,
        emoji_rating=body.emoji_rating,
        message=body.message,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "emoji_rating": row.emoji_rating,
        "message": row.message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_feedback(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    total = (await db.execute(select(func.count()).select_from(UserFeedback))).scalar() or 0
    rows = (
        await db.execute(
            select(UserFeedback).order_by(UserFeedback.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    items = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "emoji_rating": r.emoji_rating,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return items, total
