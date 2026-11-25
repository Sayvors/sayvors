"""Tenant-scoped prompt library persistence.

Channel ownership is checked on every operation. Creates and reactivations
lock the owning channel so the active-prompt cap cannot be bypassed by
concurrent requests.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import AiVisibilityPrompt, AiVisibilityRun
from .schemas import PromptPatch

MAX_ACTIVE_PROMPTS_PER_BRANCH = 100
MAX_PROMPT_LIST = 200


class OwnedChannelRequired(ValueError):
    pass


class PromptLimitReached(ValueError):
    pass


class DuplicatePrompt(ValueError):
    pass


def prompt_hash(text: str) -> str:
    """Hash the case- and whitespace-insensitive prompt identity."""
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def _owned_channel(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    *,
    lock: bool = False,
) -> Channel:
    stmt = select(Channel).where(
        Channel.id == channel_id,
        Channel.user_id == tenant_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    channel = (await db.execute(stmt)).scalar_one_or_none()
    if channel is None:
        raise OwnedChannelRequired("channel_not_owned")
    return channel


async def _active_count(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> int:
    return int(
        (
            await db.execute(
                select(func.count(AiVisibilityPrompt.id)).where(
                    AiVisibilityPrompt.tenant_id == tenant_id,
                    AiVisibilityPrompt.channel_id == channel_id,
                    AiVisibilityPrompt.is_active.is_(True),
                )
            )
        ).scalar_one()
    )


async def _duplicate_exists(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    normalized_hash: str,
    *,
    exclude_prompt_id: str | None = None,
) -> bool:
    stmt = select(AiVisibilityPrompt.id).where(
        AiVisibilityPrompt.tenant_id == tenant_id,
        AiVisibilityPrompt.channel_id == channel_id,
        AiVisibilityPrompt.normalized_prompt_hash == normalized_hash,
    )
    if exclude_prompt_id is not None:
        stmt = stmt.where(AiVisibilityPrompt.id != exclude_prompt_id)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none() is not None


async def create_prompt(
    db: AsyncSession,
    tenant_id: str,
    *,
    channel_id: str,
    title: str,
    prompt_text: str,
    intent: str,
    created_by: str,
) -> AiVisibilityPrompt:
    """Create one active prompt after ownership and branch-cap checks."""
    await _owned_channel(db, tenant_id, channel_id, lock=True)
    if (
        await _active_count(db, tenant_id, channel_id)
        >= MAX_ACTIVE_PROMPTS_PER_BRANCH
    ):
        raise PromptLimitReached("active_prompt_limit")

    clean_text = prompt_text.strip()
    normalized_hash = prompt_hash(clean_text)
    row = AiVisibilityPrompt(
        tenant_id=tenant_id,
        channel_id=channel_id,
        title=title.strip(),
        prompt_text=clean_text,
        normalized_prompt_hash=normalized_hash,
        intent=intent.strip(),
        created_by=created_by,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if await _duplicate_exists(db, tenant_id, channel_id, normalized_hash):
            raise DuplicatePrompt("duplicate_prompt") from exc
        raise
    await db.refresh(row)
    return row


async def list_prompts(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    include_archived: bool = False,
) -> list[AiVisibilityPrompt]:
    """List a bounded newest-first page for one owned channel."""
    await _owned_channel(db, tenant_id, channel_id)
    stmt = select(AiVisibilityPrompt).where(
        AiVisibilityPrompt.tenant_id == tenant_id,
        AiVisibilityPrompt.channel_id == channel_id,
    )
    if not include_archived:
        stmt = stmt.where(AiVisibilityPrompt.is_active.is_(True))
    return list(
        (
            await db.execute(
                stmt.order_by(
                    AiVisibilityPrompt.updated_at.desc(),
                    AiVisibilityPrompt.id.desc(),
                ).limit(MAX_PROMPT_LIST)
            )
        ).scalars().all()
    )


async def update_prompt(
    db: AsyncSession,
    tenant_id: str,
    prompt_id: str,
    patch: PromptPatch,
) -> AiVisibilityPrompt | None:
    """Patch an owned prompt, including an atomic reactivation-cap check."""
    existing = (
        await db.execute(
            select(AiVisibilityPrompt).where(
                AiVisibilityPrompt.id == prompt_id,
                AiVisibilityPrompt.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None

    channel_id = existing.channel_id
    await _owned_channel(db, tenant_id, channel_id, lock=True)
    row = (
        await db.execute(
            select(AiVisibilityPrompt)
            .where(
                AiVisibilityPrompt.id == prompt_id,
                AiVisibilityPrompt.tenant_id == tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    values = patch.model_dump(exclude_unset=True)
    activating = values.get("is_active") is True and not row.is_active
    if (
        activating
        and await _active_count(db, tenant_id, channel_id)
        >= MAX_ACTIVE_PROMPTS_PER_BRANCH
    ):
        raise PromptLimitReached("active_prompt_limit")

    normalized_hash = None
    if "prompt_text" in values:
        values["prompt_text"] = values["prompt_text"].strip()
        normalized_hash = prompt_hash(values["prompt_text"])
        values["normalized_prompt_hash"] = normalized_hash
    for key, value in values.items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if normalized_hash is not None and await _duplicate_exists(
            db,
            tenant_id,
            channel_id,
            normalized_hash,
            exclude_prompt_id=prompt_id,
        ):
            raise DuplicatePrompt("duplicate_prompt") from exc
        raise
    await db.refresh(row)
    return row


async def delete_prompt(
    db: AsyncSession, tenant_id: str, prompt_id: str
) -> bool:
    """Delete an unused prompt; preserve run history by archiving used ones."""
    row = (
        await db.execute(
            select(AiVisibilityPrompt)
            .where(
                AiVisibilityPrompt.id == prompt_id,
                AiVisibilityPrompt.tenant_id == tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    has_runs = (
        await db.execute(
            select(AiVisibilityRun.id)
            .where(AiVisibilityRun.prompt_id == prompt_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_runs is not None:
        row.is_active = False
    else:
        await db.delete(row)
    await db.commit()
    return True
