"""Versioned query-set lifecycle and background research orchestration."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..jobs.service import submit_job
from .models import AiVisibilityQuerySet, AiVisibilityQuestion, AiVisibilityRun

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


def query_set_payload(query_set: AiVisibilityQuerySet) -> dict:
    return {
        "id": query_set.id,
        "channel_id": query_set.channel_id,
        "version": query_set.version,
        "parent_query_set_id": query_set.parent_query_set_id,
        "status": query_set.status,
        "phase": query_set.phase,
        "depth": query_set.depth,
        "job_id": query_set.job_id,
        "classification": query_set.classification_json or {},
        "total_questions": query_set.total_questions,
        "completed_questions": query_set.completed_questions,
        "failed_questions": query_set.failed_questions,
        "failure_code": query_set.failure_code,
        "error": query_set.error,
        "started_at": query_set.started_at.isoformat() if query_set.started_at else None,
        "completed_at": query_set.completed_at.isoformat() if query_set.completed_at else None,
        "created_at": query_set.created_at.isoformat(),
        "updated_at": query_set.updated_at.isoformat(),
    }


async def latest_query_set(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict | None:
    """Return the latest research cycle, its version chain, and real outcomes."""
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.user_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("channel_not_owned")
    latest = (
        await db.execute(
            select(AiVisibilityQuerySet)
            .where(
                AiVisibilityQuerySet.tenant_id == tenant_id,
                AiVisibilityQuerySet.channel_id == channel_id,
            )
            .order_by(AiVisibilityQuerySet.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return None
    chain = [latest]
    seen = {latest.id}
    parent_id = latest.parent_query_set_id
    while parent_id and parent_id not in seen:
        parent = await db.get(AiVisibilityQuerySet, parent_id)
        if parent is None or parent.tenant_id != tenant_id or parent.channel_id != channel_id:
            break
        chain.append(parent)
        seen.add(parent.id)
        parent_id = parent.parent_query_set_id
    chain.reverse()
    set_ids = [item.id for item in chain]
    version_by_id = {item.id: item.version for item in chain}
    rows = list(
        (
            await db.execute(
                select(AiVisibilityQuestion)
                .where(AiVisibilityQuestion.query_set_id.in_(set_ids))
                .order_by(AiVisibilityQuestion.query_set_id, AiVisibilityQuestion.position)
            )
        ).scalars().all()
    )
    run_ids = [row.run_id for row in rows if row.run_id]
    runs = {
        run.id: run
        for run in (
            await db.execute(
                select(AiVisibilityRun).where(AiVisibilityRun.id.in_(run_ids))
            )
        ).scalars().all()
    }
    question_payloads = []
    for row in rows:
        run = runs.get(row.run_id) if row.run_id else None
        question_payloads.append(
            {
                "id": row.id,
                "query_set_id": row.query_set_id,
                "version": version_by_id[row.query_set_id],
                "question_key": row.question_key,
                "question_text": row.question_text,
                "language": row.language,
                "customer_intent": row.customer_intent,
                "industry_relevance": row.industry_relevance,
                "service_relevance": row.service_relevance,
                "geographic_context": row.geographic_context,
                "business_relevance_score": row.business_relevance_score,
                "research_priority": row.research_priority,
                "origin": row.origin,
                "status": row.status,
                "run_id": row.run_id,
                "mentioned": run.mentioned if run else None,
                "cited": run.cited if run else None,
                "recommended": run.recommended if run else None,
                "incorrect": run.incorrect if run else None,
            }
        )
    completed_runs = [run for run in runs.values() if run.status == "completed"]

    def _rate(field: str) -> float | None:
        if not completed_runs:
            return None
        return round(
            sum(getattr(run, field) is True for run in completed_runs)
            / len(completed_runs)
            * 100,
            1,
        )

    independent = 0
    owned = 0
    validated = 0
    sources = 0
    platforms_found = 0
    for run in runs.values():
        coverage = run.evidence_coverage or {}
        independent += int(coverage.get("third_party_source_count") or 0)
        owned += int(coverage.get("owned_source_count") or 0)
        validated += int(run.validated_claim_count or 0)
        sources += int(run.source_count or 0)
        metrics = coverage.get("metrics") or {}
        platforms_found = max(platforms_found, int(metrics.get("platforms_found") or 0))
    return {
        "query_set": query_set_payload(latest),
        "questions": question_payloads,
        "versions": [
            {
                "id": item.id,
                "version": item.version,
                "status": item.status,
                "total_questions": item.total_questions,
                "completed_questions": item.completed_questions,
                "failed_questions": item.failed_questions,
                "created_at": item.created_at.isoformat(),
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in chain
        ],
        "metrics": {
            "completed_runs": len(completed_runs),
            "mention_rate": _rate("mentioned"),
            "citation_rate": _rate("cited"),
            "recommendation_rate": _rate("recommended"),
            "source_count": sources,
            "validated_claim_count": validated,
        },
        "coverage": {
            "third_party_source_count": independent,
            "owned_source_count": owned,
            "validated_claim_count": validated,
            "metrics": {"platforms_found": platforms_found},
        },
    }
