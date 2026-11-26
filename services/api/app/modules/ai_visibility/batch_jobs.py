"""Durable handlers for business-aware query-set generation."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from ..jobs.models import Job
from . import profile, questions, service
from .models import (
    AiVisibilityPrompt,
    AiVisibilityQuestion,
    AiVisibilityQuerySet,
    AiVisibilityRun,
)
from .taxonomy import classify_industry

logger = logging.getLogger(__name__)
GENERATOR_VERSION = "deterministic-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_query_set(db: AsyncSession, job: Job) -> AiVisibilityQuerySet:
    payload = job.payload if isinstance(job.payload, dict) else {}
    query_set_id = str(payload.get("query_set_id") or "")
    query_set = (
        await db.execute(
            select(AiVisibilityQuerySet).where(
                AiVisibilityQuerySet.id == query_set_id,
                AiVisibilityQuerySet.tenant_id == job.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if query_set is None or query_set.job_id != job.id or job.subject_id != query_set.id:
        raise ValueError("query_set_job_mismatch")
    if job.status != "running" or (
        job.lease_expires_at is not None and job.lease_expires_at <= _now()
    ):
        raise RuntimeError("query_set_job_lease_lost")
    return query_set


def _classification(profile_data: dict) -> dict:
    stored = profile_data.get("classification")
    if isinstance(stored, dict) and stored:
        return stored
    match = classify_industry(profile_data)
    return {
        "industry": match.industry,
        "business_type": match.business_type,
        "subcategories": list(match.subcategories),
        "confidence": match.confidence,
        "matched_signals": list(match.matched_signals),
        "uncertainties": list(match.uncertainties),
    }


def _source_snapshot(profile_data: dict) -> dict:
    keys = (
        "name",
        "categories",
        "description",
        "services",
        "declared_services",
        "products",
        "locality",
        "country",
        "service_area",
        "review_themes",
        "customer_questions",
        "customer_intents",
        "not_offered",
        "public_context",
        "source_fields",
    )
    return {key: profile_data.get(key) for key in keys if profile_data.get(key) not in (None, "", [], {})}


async def _persist_questions(
    db: AsyncSession,
    query_set: AiVisibilityQuerySet,
    generated: list[questions.GeneratedQuestion],
) -> list[AiVisibilityQuestion]:
    existing = list(
        (
            await db.execute(
                select(AiVisibilityQuestion)
                .where(AiVisibilityQuestion.query_set_id == query_set.id)
                .order_by(AiVisibilityQuestion.position)
            )
        ).scalars().all()
    )
    if existing:
        return existing
    question_hashes = set(
        (
            await db.execute(
                select(AiVisibilityQuestion.normalized_question_hash).where(
                    AiVisibilityQuestion.tenant_id == query_set.tenant_id,
                    AiVisibilityQuestion.channel_id == query_set.channel_id,
                )
            )
        ).scalars().all()
    )
    prompt_hashes = set(
        (
            await db.execute(
                select(AiVisibilityPrompt.normalized_prompt_hash).where(
                    AiVisibilityPrompt.tenant_id == query_set.tenant_id,
                    AiVisibilityPrompt.channel_id == query_set.channel_id,
                )
            )
        ).scalars().all()
    )
    active_count = int(
        (
            await db.execute(
                select(func.count(AiVisibilityPrompt.id)).where(
                    AiVisibilityPrompt.tenant_id == query_set.tenant_id,
                    AiVisibilityPrompt.channel_id == query_set.channel_id,
                    AiVisibilityPrompt.is_active.is_(True),
                )
            )
        ).scalar()
        or 0
    )
    rows: list[AiVisibilityQuestion] = []
    for item in generated:
        digest = service.prompt_hash(item.question_text)
        if digest in question_hashes or digest in prompt_hashes:
            continue
        if active_count >= service.MAX_ACTIVE_PROMPTS_PER_BRANCH:
            raise service.PromptLimitReached("active_prompt_limit")
        prompt = AiVisibilityPrompt(
            tenant_id=query_set.tenant_id,
            channel_id=query_set.channel_id,
            title=f"{item.intent} · {item.language}"[:200],
            prompt_text=item.question_text,
            normalized_prompt_hash=digest,
            intent=item.intent,
            created_by=query_set.tenant_id,
        )
        db.add(prompt)
        await db.flush()
        row = AiVisibilityQuestion(
            query_set_id=query_set.id,
            tenant_id=query_set.tenant_id,
            channel_id=query_set.channel_id,
            question_key=f"q{len(rows) + 1:03d}",
            question_text=item.question_text,
            normalized_question_hash=digest,
            language=item.language,
            customer_intent=item.intent,
            industry_relevance=item.industry_relevance,
            service_relevance=item.service_relevance,
            geographic_context=item.geographic_context,
            business_relevance_score=item.business_relevance_score,
            research_priority=item.priority,
            origin="initial",
            prompt_id=prompt.id,
            position=len(rows),
        )
        db.add(row)
        rows.append(row)
        question_hashes.add(digest)
        prompt_hashes.add(digest)
        active_count += 1
    await db.commit()
    return rows


async def _start_question_run(
    db: AsyncSession,
    query_set: AiVisibilityQuerySet,
    question: AiVisibilityQuestion,
) -> AiVisibilityRun | None:
    if question.run_id or question.prompt_id is None:
        return None
    run = await service.create_run_with_quota(
        db,
        query_set.tenant_id,
        query_set.channel_id,
        question.prompt_id,
        locale="ar" if question.language == "ar" else "en",
        depth=query_set.depth,
        query_set_id=query_set.id,
        question_id=question.id,
    )
    question.run_id = run.id
    question.status = "queued"
    if run.job_id:
        child = await db.get(Job, run.job_id)
        if child is not None:
            child.ui_title = f"Researching: {question.question_text[:80]}"
            child.ui_kind = "ai_visibility"
            child.ui_visible = True
            child.progress = 0
            child.progress_label = "Queued"
    await db.commit()
    return run


async def handle_query_set(job: Job, db: AsyncSession) -> dict:
    """Generate one versioned question set and start its first child run."""
    query_set = await _load_query_set(db, job)
    if query_set.status in {"completed", "failed", "partial"}:
        return {"status": query_set.status, "query_set_id": query_set.id}
    rows = list(
        (
            await db.execute(
                select(AiVisibilityQuestion)
                .where(AiVisibilityQuestion.query_set_id == query_set.id)
                .order_by(AiVisibilityQuestion.position)
            )
        ).scalars().all()
    )
    if not rows:
        query_set.phase = "loading_profile"
        await db.commit()
        profile_data = await profile.load_business_profile(
            db, query_set.tenant_id, query_set.channel_id
        )
        generated = await questions.generate_questions(
            profile_data, limit=questions.MAX_INITIAL_QUESTIONS
        )
        query_set = await _load_query_set(db, job)
        query_set.classification_json = _classification(profile_data)
        query_set.source_snapshot_json = _source_snapshot(profile_data)
        query_set.generation_meta_json = {
            "generator": GENERATOR_VERSION,
            "languages": sorted({item.language for item in generated}),
            "uncertainties": profile_data.get("uncertainties") or [],
        }
        if not generated:
            query_set.status = "failed"
            query_set.failure_code = "no_questions_generated"
            query_set.error = "No business-relevant customer questions could be generated."
            query_set.completed_at = _now()
            await db.commit()
            return {"status": "failed", "query_set_id": query_set.id}
        try:
            rows = await _persist_questions(db, query_set, generated)
        except service.PromptLimitReached:
            query_set.status = "failed"
            query_set.failure_code = "active_prompt_limit"
            query_set.error = "The branch reached its active research-question limit."
            query_set.completed_at = _now()
            await db.commit()
            return {"status": "failed", "query_set_id": query_set.id}
        except IntegrityError:
            await db.rollback()
            query_set = await db.get(AiVisibilityQuerySet, query_set.id)
            if query_set is not None:
                query_set.status = "failed"
                query_set.failure_code = "question_persistence_failed"
                query_set.error = "The generated question set could not be saved."
                query_set.completed_at = _now()
                await db.commit()
            return {"status": "failed", "query_set_id": query_set.id if query_set else None}
    query_set.total_questions = len(rows)
    next_question = next((row for row in rows if not row.run_id), None)
    if next_question is not None:
        await _start_question_run(db, query_set, next_question)
    query_set.status = "running"
    query_set.phase = "researching"
    job.progress = 10
    job.progress_label = f"Researching {len(rows)} customer questions"
    await db.commit()
    return {
        "status": "running",
        "query_set_id": query_set.id,
        "question_count": len(rows),
    }


TERMINAL_RUN_STATUSES = {"completed", "failed", "ambiguous", "insufficient_evidence"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "dead", "cancelled"}


async def _finalize_one(db: AsyncSession, query_set_id: str) -> bool:
    query_set = (
        await db.execute(
            select(AiVisibilityQuerySet)
            .where(AiVisibilityQuerySet.id == query_set_id)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if query_set is None or query_set.status != "running":
        return False
    rows = list(
        (
            await db.execute(
                select(AiVisibilityQuestion)
                .where(AiVisibilityQuestion.query_set_id == query_set.id)
                .order_by(AiVisibilityQuestion.position)
            )
        ).scalars().all()
    )
    if not rows:
        query_set.status = "failed"
        query_set.failure_code = "empty_query_set"
        query_set.completed_at = _now()
        await db.commit()
        return True
    run_ids = [row.run_id for row in rows if row.run_id]
    runs = {
        run.id: run
        for run in (
            await db.execute(
                select(AiVisibilityRun).where(AiVisibilityRun.id.in_(run_ids))
            )
        ).scalars().all()
    }
    jobs = {
        job.id: job
        for job in (
            await db.execute(
                select(Job).where(Job.id.in_([run.job_id for run in runs.values() if run.job_id]))
            )
        ).scalars().all()
    }
    for row in rows:
        run = runs.get(row.run_id) if row.run_id else None
        if row.run_id and run is None:
            row.status = "failed"
            continue
        if run is None:
            continue
        if run.status not in TERMINAL_RUN_STATUSES:
            row.status = run.status
            job = jobs.get(run.job_id)
            if job is not None and job.status in TERMINAL_JOB_STATUSES:
                run.status = "failed"
                run.failure_code = "child_job_terminal"
                run.error = "The research job stopped before completing this question."
                run.completed_at = _now()
        if run.status in TERMINAL_RUN_STATUSES:
            row.status = run.status
    completed = sum(row.status in {"completed", "insufficient_evidence"} for row in rows)
    failed = sum(row.status in {"failed", "ambiguous"} for row in rows)
    query_set.completed_questions = completed
    query_set.failed_questions = failed
    active = next((row for row in rows if row.status not in TERMINAL_RUN_STATUSES and row.status != "pending"), None)
    if active is not None:
        query_set.phase = active.status
        await db.commit()
        return True
    for row in rows:
        if row.status != "pending":
            continue
        try:
            await _start_question_run(db, query_set, row)
        except service.ResearchQuotaExceeded:
            query_set.status = "partial"
            query_set.failure_code = "research_quota_exhausted"
            query_set.error = "Monthly research quota reached; remaining questions were not run."
            query_set.completed_at = _now()
            await db.commit()
            return True
        except service.PromptInactive:
            row.status = "failed"
            continue
        query_set.phase = "researching"
        await db.commit()
        return True
    query_set.status = "completed" if failed == 0 else ("partial" if completed else "failed")
    query_set.phase = "complete"
    query_set.completed_at = _now()
    await db.commit()
    return True


async def finalize_due_query_sets(db: AsyncSession, *, limit: int = 20) -> int:
    """Advance a bounded batch of running query sets; safe for multiple workers."""
    ids = list(
        (
            await db.execute(
                select(AiVisibilityQuerySet.id)
                .where(AiVisibilityQuerySet.status == "running")
                .order_by(AiVisibilityQuerySet.updated_at)
                .limit(max(1, min(limit, 100)))
            )
        ).scalars().all()
    )
    processed = 0
    for query_set_id in ids:
        if await _finalize_one(db, query_set_id):
            processed += 1
    return processed


FINALIZER_INTERVAL_SECONDS = 5


async def run_query_set_finalizer() -> None:
    """Periodically advance background question queues across workers."""
    while True:
        try:
            async with async_session() as db:
                processed = await finalize_due_query_sets(db)
                if processed:
                    logger.info(
                        "ai_visibility_query_sets_advanced",
                        extra={"count": processed},
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai_visibility_query_set_finalizer_failed")
        await asyncio.sleep(FINALIZER_INTERVAL_SECONDS)
