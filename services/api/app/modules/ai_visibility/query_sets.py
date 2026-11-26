"""Versioned query-set lifecycle and background research orchestration."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..jobs.service import submit_job
from .models import AiVisibilityQuerySet

ACTIVE_QUERY_SET_STATUSES = ("generating", "running")
QUERY_SET_JOB_TYPE = "ai_visibility.query_set"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def start_query_set(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    *,
    depth: str = "quick",
) -> AiVisibilityQuerySet:
    """Create one durable generation job, or return the active set.

    The channel row lock serializes concurrent clicks across workers. The
    request commits only the query set and parent job; all profile loading,
    question generation, and research happen after the API returns.
    """
    if depth not in {"quick", "deep"}:
        raise ValueError("invalid_research_depth")
    channel = (
        await db.execute(
            select(Channel)
            .where(Channel.id == channel_id, Channel.user_id == tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("channel_not_owned")
    existing = (
        await db.execute(
            select(AiVisibilityQuerySet)
            .where(
                AiVisibilityQuerySet.tenant_id == tenant_id,
                AiVisibilityQuerySet.channel_id == channel_id,
                AiVisibilityQuerySet.status.in_(ACTIVE_QUERY_SET_STATUSES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    version = int(
        (
            await db.execute(
                select(func.max(AiVisibilityQuerySet.version)).where(
                    AiVisibilityQuerySet.tenant_id == tenant_id,
                    AiVisibilityQuerySet.channel_id == channel_id,
                )
            )
        ).scalar()
        or 0
    ) + 1
    query_set = AiVisibilityQuerySet(
        tenant_id=tenant_id,
        channel_id=channel_id,
        version=version,
        status="generating",
        phase="queued",
        depth=depth,
        started_at=_now(),
    )
    db.add(query_set)
    await db.flush()
    job = await submit_job(
        db,
        tenant_id=tenant_id,
        job_type=QUERY_SET_JOB_TYPE,
        payload={"query_set_id": query_set.id},
        idempotency_key=f"ai-visibility-query-set:{query_set.id}",
        subject_type="ai_visibility_query_set",
        subject_id=query_set.id,
        lane_key=f"ai-visibility-query-set:{channel_id}",
    )
    job.ui_title = f"Researching {channel.display_name}"
    job.ui_kind = "ai_visibility"
    job.ui_visible = True
    job.progress = 0
    job.progress_label = "Preparing business research"
    query_set.job_id = job.id
    await db.commit()
    return query_set
