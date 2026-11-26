"""Tenant-scoped prompt library persistence.

Channel ownership is checked on every operation. Creates and reactivations
lock the owning channel so the active-prompt cap cannot be bypassed by
concurrent requests.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, distinct, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..billing.entitlements import get_entitlements
from ..jobs.service import submit_job
from .models import (
    AiVisibilityAttempt,
    AiVisibilityPrompt,
    AiVisibilityRun,
    AiVisibilitySource,
)
from .schemas import PromptPatch

MAX_ACTIVE_PROMPTS_PER_BRANCH = 100
MAX_PROMPT_LIST = 200
MAX_RUN_ATTEMPTS = 20
ATTEMPT_WINDOW_SECONDS = 60 * 60
RETRY_COOLDOWN_SECONDS = 5
ACTIVE_RUN_STATUSES = (
    "queued",
    "searching",
    "fetching",
    "reading",
    "validating",
    "writing",
)


class OwnedChannelRequired(ValueError):
    pass


class PromptLimitReached(ValueError):
    pass


class DuplicatePrompt(ValueError):
    pass


class PromptNotOwned(ValueError):
    pass


class PromptInactive(ValueError):
    pass


class PromptTextLocked(ValueError):
    pass


class RetryCooldown(ValueError):
    pass


class RetryLimitReached(ValueError):
    pass


class ResearchQuotaExceeded(ValueError):
    pass


class ActiveRunDeletion(ValueError):
    pass


class QuerySetRunDeletion(ValueError):
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


async def get_prompt(
    db: AsyncSession, tenant_id: str, prompt_id: str
) -> AiVisibilityPrompt | None:
    return (
        await db.execute(
            select(AiVisibilityPrompt).where(
                AiVisibilityPrompt.id == prompt_id,
                AiVisibilityPrompt.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


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
        if normalized_hash != row.normalized_prompt_hash:
            has_attempts = (
                await db.execute(
                    select(AiVisibilityAttempt.id)
                    .where(AiVisibilityAttempt.prompt_id == prompt_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            has_runs = (
                await db.execute(
                    select(AiVisibilityRun.id)
                    .where(
                        AiVisibilityRun.prompt_id == prompt_id,
                        AiVisibilityRun.tenant_id == tenant_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if has_attempts is not None or has_runs is not None:
                raise PromptTextLocked("prompt_text_locked")
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
    """Archive a prompt while retaining its durable research-attempt policy."""
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
    row.is_active = False
    await db.commit()
    return True


async def get_active_run(
    db: AsyncSession, tenant_id: str, prompt_id: str, channel_id: str
) -> AiVisibilityRun | None:
    """Return the durable active run used to make repeated creates idempotent."""
    return (
        await db.execute(
            select(AiVisibilityRun)
            .where(
                AiVisibilityRun.tenant_id == tenant_id,
                AiVisibilityRun.prompt_id == prompt_id,
                AiVisibilityRun.channel_id == channel_id,
                AiVisibilityRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(AiVisibilityRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_run(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    prompt_id: str,
    *,
    locale: str,
    depth: str = "quick",
    query_set_id: str | None = None,
    question_id: str | None = None,
) -> AiVisibilityRun:
    """Create one durable run under the prompt's durable attempt policy."""
    await _owned_channel(db, tenant_id, channel_id, lock=True)
    prompt = (
        await db.execute(
            select(AiVisibilityPrompt)
            .where(
                AiVisibilityPrompt.id == prompt_id,
                AiVisibilityPrompt.tenant_id == tenant_id,
                AiVisibilityPrompt.channel_id == channel_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if prompt is None:
        raise PromptNotOwned("prompt_not_found")
    if not prompt.is_active:
        raise PromptInactive("prompt_inactive")

    existing = await get_active_run(db, tenant_id, prompt_id, channel_id)
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ATTEMPT_WINDOW_SECONDS)
    recent_attempts = (
        await db.execute(
            select(
                func.count(AiVisibilityAttempt.id),
                func.max(AiVisibilityAttempt.attempted_at),
            ).where(
                AiVisibilityAttempt.tenant_id == tenant_id,
                AiVisibilityAttempt.prompt_id == prompt_id,
                AiVisibilityAttempt.attempted_at >= cutoff,
            )
        )
    ).one()
    if int(recent_attempts[0] or 0) >= MAX_RUN_ATTEMPTS:
        raise RetryLimitReached("retry_limit_reached")
    latest_finished = recent_attempts[1]
    if latest_finished is None:
        # Compatibility for terminal runs created before the ledger migration.
        latest_finished = (
            await db.execute(
                select(func.max(AiVisibilityRun.completed_at)).where(
                    AiVisibilityRun.tenant_id == tenant_id,
                    AiVisibilityRun.prompt_id == prompt_id,
                )
            )
        ).scalar_one()
    if latest_finished and now - _aware(latest_finished) < timedelta(
        seconds=RETRY_COOLDOWN_SECONDS
    ):
        raise RetryCooldown("retry_cooldown")

    run = AiVisibilityRun(
        tenant_id=tenant_id,
        channel_id=channel_id,
        prompt_id=prompt_id,
        prompt_snapshot=prompt.prompt_text,
        locale=locale,
        research_depth=depth,
        query_set_id=query_set_id,
        question_id=question_id,
        status="queued",
    )
    db.add(run)
    try:
        await db.flush()
        db.add(
            AiVisibilityAttempt(
                tenant_id=tenant_id,
                prompt_id=prompt_id,
                run_id=run.id,
                attempted_at=now,
            )
        )
        job = await submit_job(
            db,
            tenant_id=tenant_id,
            job_type="ai_visibility.research",
            payload={"run_id": run.id},
            idempotency_key=f"ai-visibility:{run.id}",
            subject_type="ai_visibility_run",
            subject_id=run.id,
            lane_key=f"ai-visibility:{prompt_id}",
        )
        run.job_id = job.id
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_active_run(db, tenant_id, prompt_id, channel_id)
        if existing is not None:
            return existing
        raise
    await db.refresh(run)
    return run


MAX_RUN_LIST = 100


def _rate(hits: int, total: int) -> float | None:
    return round(hits * 100.0 / total, 1) if total else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def monthly_research_count(
    db: AsyncSession, tenant_id: str, depth: str
) -> int:
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return int(
        (
            await db.execute(
                select(func.count(AiVisibilityRun.id)).where(
                    AiVisibilityRun.tenant_id == tenant_id,
                    AiVisibilityRun.research_depth == depth,
                    AiVisibilityRun.created_at >= month_start,
                )
            )
        ).scalar_one()
    )


async def overview(
    db: AsyncSession, tenant_id: str, channel_id: str, days: int
) -> dict:
    await _owned_channel(db, tenant_id, channel_id)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    base = [
        AiVisibilityRun.tenant_id == tenant_id,
        AiVisibilityRun.channel_id == channel_id,
    ]
    if since:
        base.append(AiVisibilityRun.created_at >= since)

    totals = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case((AiVisibilityRun.mentioned.is_(True), 1), else_=0)
                ).label("mentioned"),
                func.sum(
                    case((AiVisibilityRun.cited.is_(True), 1), else_=0)
                ).label("cited"),
                func.sum(
                    case(
                        (AiVisibilityRun.recommended.is_(True), 1), else_=0
                    )
                ).label("recommended"),
                func.sum(AiVisibilityRun.source_count).label("sources"),
                func.sum(AiVisibilityRun.validated_claim_count).label("claims"),
            ).where(*base, AiVisibilityRun.status == "completed")
        )
    ).one()
    active_prompts = (
        await db.execute(
            select(func.count(AiVisibilityPrompt.id)).where(
                AiVisibilityPrompt.tenant_id == tenant_id,
                AiVisibilityPrompt.channel_id == channel_id,
                AiVisibilityPrompt.is_active.is_(True),
            )
        )
    ).scalar_one()
    covered_prompts = (
        await db.execute(
            select(func.count(distinct(AiVisibilityRun.prompt_id))).where(
                *base, AiVisibilityRun.status == "completed"
            )
        )
    ).scalar_one()
    failed = (
        await db.execute(
            select(func.count()).where(
                *base,
                AiVisibilityRun.status.in_(("failed", "ambiguous")),
            )
        )
    ).scalar_one()
    insufficient = (
        await db.execute(
            select(func.count()).where(
                *base, AiVisibilityRun.status == "insufficient_evidence"
            )
        )
    ).scalar_one()
    return {
        "completed_runs": totals.total,
        "mention_rate": _rate(totals.mentioned or 0, totals.total),
        "citation_rate": _rate(totals.cited or 0, totals.total),
        "recommendation_rate": _rate(totals.recommended or 0, totals.total),
        "active_prompts": active_prompts,
        "covered_prompts": covered_prompts,
        "prompt_coverage": _rate(covered_prompts, active_prompts),
        "failed_runs": failed,
        "insufficient_runs": insufficient,
        "source_count": totals.sources or 0,
        "validated_claim_count": totals.claims or 0,
    }


async def list_runs(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    *,
    status: str | None = None,
    prompt_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    await _owned_channel(db, tenant_id, channel_id)
    filters = [
        AiVisibilityRun.tenant_id == tenant_id,
        AiVisibilityRun.channel_id == channel_id,
    ]
    if status:
        filters.append(AiVisibilityRun.status == status)
    if prompt_id:
        filters.append(AiVisibilityRun.prompt_id == prompt_id)
    total = (
        await db.execute(
            select(func.count()).select_from(AiVisibilityRun).where(*filters)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(AiVisibilityRun, AiVisibilityPrompt.title)
            .join(AiVisibilityPrompt, AiVisibilityPrompt.id == AiVisibilityRun.prompt_id)
            .where(*filters)
            .order_by(AiVisibilityRun.created_at.desc())
            .limit(min(limit, MAX_RUN_LIST))
            .offset(max(0, offset))
        )
    ).all()
    return rows, total


async def get_run(db: AsyncSession, tenant_id: str, run_id: str):
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return None, []
    source_rows = (
        await db.execute(
            select(AiVisibilitySource)
            .where(AiVisibilitySource.run_id == run.id)
            .order_by(AiVisibilitySource.position)
        )
    ).scalars().all()
    return run, source_rows


async def create_run_with_quota(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    prompt_id: str,
    *,
    locale: str,
    depth: str = "quick",
    query_set_id: str | None = None,
    question_id: str | None = None,
) -> AiVisibilityRun:
    """Create a child run with an atomic tenant/month quota check.

    Router preflight is only a fast fail. Background workers can race across
    channels, so PostgreSQL callers serialize on a transaction advisory lock
    before counting and inserting the run.
    """
    now = datetime.now(timezone.utc)
    if db.bind.dialect.name == "postgresql":
        key = f"ai-visibility-quota:{tenant_id}:{depth}:{now:%Y-%m}"
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": key},
        )
    ent = await get_entitlements(tenant_id, db)
    limit = (
        ent.max_deep_research_month
        if depth == "deep"
        else ent.max_quick_research_month
    )
    if limit is not None:
        used = await monthly_research_count(db, tenant_id, depth)
        if used >= limit:
            raise ResearchQuotaExceeded(
                f"Monthly {depth} research limit reached ({used}/{limit})."
            )
    return await create_run(
        db,
        tenant_id,
        channel_id,
        prompt_id,
        locale=locale,
        depth=depth,
        query_set_id=query_set_id,
        question_id=question_id,
    )


async def retry_run(
    db: AsyncSession, tenant_id: str, run_id: str, *, locale: str
):
    run, _ = await get_run(db, tenant_id, run_id)
    if run is None:
        return None
    if run.status in ACTIVE_RUN_STATUSES or run.status == "completed":
        return run
    # Creation owns the shared channel/prompt lock, cooldown, and durable
    # attempt budget so POST /runs and POST /runs/{id}/retry cannot diverge.
    return await create_run_with_quota(
        db,
        tenant_id,
        run.channel_id,
        run.prompt_id,
        locale=locale,
        depth=run.research_depth or "quick",
    )


async def clear_terminal_runs(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> int:
    """Archive-free bulk cleanup of completed/failed research history."""
    await _owned_channel(db, tenant_id, channel_id)
    result = await db.execute(
        delete(AiVisibilityRun).where(
            AiVisibilityRun.tenant_id == tenant_id,
            AiVisibilityRun.channel_id == channel_id,
            AiVisibilityRun.status.not_in(ACTIVE_RUN_STATUSES),
            AiVisibilityRun.query_set_id.is_(None),
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def delete_run(db: AsyncSession, tenant_id: str, run_id: str) -> bool:
    run = (
        await db.execute(
            select(AiVisibilityRun)
            .where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    if run.status in ACTIVE_RUN_STATUSES:
        raise ActiveRunDeletion("active_run_delete_forbidden")
    if run.query_set_id is not None:
        raise QuerySetRunDeletion("query_set_run_delete_forbidden")
    await db.delete(run)
    await db.commit()
    return True
