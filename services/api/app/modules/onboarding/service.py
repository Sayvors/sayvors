"""Onboarding checklist persistence service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...modules.users.models import User
from .schemas import normalize_onboarding_state


async def get_state(db: AsyncSession, user_id: str) -> dict:
    row = (await db.execute(select(User.onboarding_state).where(User.id == user_id))).scalar_one_or_none()
    return normalize_onboarding_state(row)


async def update_state(db: AsyncSession, user_id: str, patch: dict) -> dict:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise ValueError("user not found")
    current = normalize_onboarding_state(user.onboarding_state)
    if "dismissed" in patch and patch["dismissed"] is not None:
        current["dismissed"] = bool(patch["dismissed"])
    if "open" in patch and patch["open"] is not None:
        current["open"] = bool(patch["open"])
    if "steps" in patch and isinstance(patch["steps"], dict):
        merged = dict(current["steps"])
        for k, v in patch["steps"].items():
            merged[str(k)] = bool(v)
        current["steps"] = merged
    user.onboarding_state = current
    await db.commit()
    await db.refresh(user)
    return normalize_onboarding_state(user.onboarding_state)
