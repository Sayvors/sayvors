"""Durable grounded-research pipeline."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import sentry_sdk

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..jobs.models import Job
from ..locations.models import LocationProfile
from . import decisions, research, search, sources, validation
from .models import AiVisibilityRun, AiVisibilitySource
from .service import ACTIVE_RUN_STATUSES

logger = logging.getLogger(__name__)
MIN_SOURCES_FOR_BRIEF = 2
MIN_VALIDATED_CLAIMS = 1
LLM_PENDING_FAILURE_CODE = "llm_call_in_progress"
LLM_OUTCOME_UNKNOWN_FAILURE_CODE = "llm_outcome_unknown"
# Search and fetch are bounded to about a minute; allow enough lease for a
# slow provider response without letting an abandoned run block its prompt.
RESEARCH_LEASE_SECONDS = 15 * 60
USER_ERROR_MESSAGES = {
    "invalid_research_json": "The research model returned an unreadable brief. Please retry.",
    "no_llm_model_configured": "No research model is configured. Contact your workspace admin.",
    "search_unavailable": "Public web search is unavailable. Please retry shortly.",
    "search_blocked": "Public web search is temporarily paused. Please retry later.",
    "tenant_search_rate_limited": "This workspace reached its research limit. Wait a minute and retry.",
    "search_rate_limited": "Public web search is busy. Please retry shortly.",
    "uncited_answer_sentence": "The brief needs clearer citations. Please retry.",
    "unfetched_answer_url": "The brief included an unsupported link. Please retry.",
    "ungrounded_answer_sentence": "The brief could not be verified against its sources. Please retry.",
    "fabricated_answer_citation": "The brief included an unsupported citation. Please retry.",
}


def _client_error(exc: Exception) -> str:
    code = str(exc)
    return USER_ERROR_MESSAGES.get(
        code,
        USER_ERROR_MESSAGES.get(
            type(exc).__name__, "Research could not be completed. Please retry."
        ),
    )


class RunCancelled(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_branch_facts(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict:
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
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (TypeError, ValueError):
        meta = {}
    listing_id = str(meta.get("location_id") or channel.listing_key or "")
    profile = (
        await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == tenant_id,
                LocationProfile.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    return {
        "name": channel.display_name,
        "address": meta.get("address") or meta.get("locality"),
        "phone": meta.get("phone"),
        "website": meta.get("website"),
        "maps_url": meta.get("maps_url"),
        "categories": profile.categories if profile else {},
        "hours": profile.hours if profile else {},
        "description": profile.description if profile else None,
    }


def _source_payload(rows) -> list[dict]:
    return [
        {
            "id": row.id,
            "label": f"S{row.position + 1}",
            "title": row.title or row.url,
            "url": row.canonical_url or row.url,
            "excerpt": row.excerpt or "",
        }
        for row in rows
    ]


async def _status(db: AsyncSession, run: AiVisibilityRun, status: str) -> None:
    run.status = status
    run.updated_at = _now()
    if status == "searching" and run.started_at is None:
        run.started_at = _now()
    await db.commit()


async def _ensure_active(
    db: AsyncSession,
    run_id: str,
    tenant_id: str,
    *,
    job_id: str,
    lease_owner: str | None,
) -> None:
    """Reject deleted, terminal, cancelled, or reclaimed runs before external work."""
    row = (
        await db.execute(
            select(AiVisibilityRun.id, AiVisibilityRun.status, AiVisibilityRun.job_id).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).one_or_none()
    if row is None or row.status not in ACTIVE_RUN_STATUSES or row.job_id != job_id:
        raise RunCancelled("run_cancelled")
    current_job = (
        await db.execute(
            select(Job.id).where(
                Job.id == job_id,
                Job.tenant_id == tenant_id,
                Job.subject_id == run_id,
                Job.status == "running",
                Job.lease_owner == lease_owner,
                Job.lease_expires_at > _now(),
            )
        )
    ).scalar_one_or_none()
    if current_job is None:
        raise RunCancelled("run_cancelled")


async def _set_terminal(
    db: AsyncSession,
    run_id: str,
    tenant_id: str,
    *,
    job,
    status: str,
    failure_code: str,
    error: str,
) -> AiVisibilityRun | None:
    """Persist a terminal state in a fresh transaction after any failed write."""
    await db.rollback()
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        # The runner still owns this ORM object after the handler returns.
        # Rollback expired it, so reload before handing control back.
        await db.refresh(job)
        return None
    run.status = status
    run.failure_code = failure_code
    run.error = error
    run.updated_at = _now()
    run.completed_at = _now()
    await db.commit()
    await db.refresh(job)
    return run


def _finish(run: AiVisibilityRun, started: float, status: str) -> dict:
    logger.info(
        "ai_visibility_research_finished",
        extra={
            "run_id": run.id,
            "tenant_id": run.tenant_id,
            "status": status,
            "duration_seconds": round(time.monotonic() - started, 3),
            "source_count": run.source_count,
            "model": run.model,
            "failure_code": run.failure_code,
        },
    )
    if status in {"ambiguous", "insufficient_evidence"}:
        sentry_sdk.capture_message(
            f"AI visibility research {status}",
            level="warning",
            extras={
                "run_id": run.id,
                "tenant_id": run.tenant_id,
                "failure_code": run.failure_code,
            },
        )
    return {"status": status, "run_id": run.id}


async def handle_research(job, db: AsyncSession) -> dict:
    from ..billing.budget import BudgetExhausted

    run_id = str((job.payload or {}).get("run_id") or "")
    tenant_id = job.tenant_id
    job_id = job.id
    lease_owner = job.lease_owner
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("run_not_found")
    started = time.monotonic()
    if run.status == "completed":
        return _finish(run, started, "completed")

    async def ensure_active() -> None:
        await _ensure_active(
            db,
            run_id,
            tenant_id,
            job_id=job_id,
            lease_owner=lease_owner,
        )

    llm_attempted = False
    try:
        await ensure_active()
        if run.failure_code == LLM_PENDING_FAILURE_CODE:
            # A previous worker committed the intent to call the provider but
            # did not durably record the outcome. Repeating it could bill twice.
            run = await _set_terminal(
                db,
                run_id,
                tenant_id,
                job=job,
                status="ambiguous",
                failure_code=LLM_OUTCOME_UNKNOWN_FAILURE_CODE,
                error=(
                    "The research provider may have completed, but its result "
                    "could not be verified."
                ),
            )
            if run is None:
                return {"status": "cancelled", "run_id": run_id}
            return _finish(run, started, "ambiguous")

        snapshots = list(
            (
                await db.execute(
                    select(AiVisibilitySource)
                    .where(AiVisibilitySource.run_id == run_id)
                    .order_by(AiVisibilitySource.position)
                )
            ).scalars().all()
        )
        if not snapshots:
            await _status(db, run, "searching")
            await ensure_active()
            results = await search.search_public_web(tenant_id, run.prompt_snapshot)
            await ensure_active()
            await _status(db, run, "fetching")
            snapshots = await sources.fetch_sources(db, run_id, results)
            await ensure_active()
        usable = [row for row in snapshots if row.excerpt]
        if len(usable) < MIN_SOURCES_FOR_BRIEF:
            run = await _set_terminal(
                db,
                run_id,
                tenant_id,
                job=job,
                status="insufficient_evidence",
                failure_code="insufficient_sources",
                error="Not enough usable public sources were found for this question.",
            )
            if run is None:
                return {"status": "cancelled", "run_id": run_id}
            return _finish(run, started, run.status)

        await _status(db, run, "reading")
        await ensure_active()
        branch = await load_branch_facts(db, tenant_id, run.channel_id)
        source_payload = _source_payload(usable)
        await _status(db, run, "writing")
        await ensure_active()
        extended = await db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.tenant_id == tenant_id,
                Job.status == "running",
                Job.lease_owner == lease_owner,
            )
            .values(lease_expires_at=_now() + timedelta(seconds=RESEARCH_LEASE_SECONDS))
        )
        if extended.rowcount != 1:
            raise RunCancelled("run_cancelled")
        run.failure_code = LLM_PENDING_FAILURE_CODE
        await db.commit()
        await ensure_active()
        llm_attempted = True
        model, payload = await research.complete_research(
            db,
            tenant_id=tenant_id,
            channel_id=run.channel_id,
            branch=branch,
            prompt=run.prompt_snapshot,
            locale=run.locale,
            sources=source_payload,
        )
        await ensure_active()
        await _status(db, run, "validating")
        payload = validation.validate(payload, source_payload, branch)
        validated_claims = sum(
            row.status == "supported" for row in payload.claims
        )
        unsupported_claims = sum(
            row.status == "unsupported" for row in payload.claims
        )
        if validated_claims < MIN_VALIDATED_CLAIMS:
            run.status = "insufficient_evidence"
            run.failure_code = "insufficient_validated_claims"
        else:
            run.status = "completed"
            run.failure_code = None

        run.model = model
        run.answer_text = payload.answer
        run.mentioned = payload.mentioned
        run.cited = payload.cited
        run.recommended = payload.recommended
        run.incorrect = payload.incorrect
        run.validation_status = "partial" if unsupported_claims else "passed"
        run.evidence_coverage = {
            "source_count": len(usable),
            "validated_claim_count": validated_claims,
            "unsupported_claim_count": unsupported_claims,
        }
        run.source_count = len(usable)
        run.validated_claim_count = validated_claims
        run.unsupported_claim_count = unsupported_claims
        run.competitor_mentions = [
            row.model_dump() for row in payload.competitors
        ]
        run.claims_json = [row.model_dump() for row in payload.claims]
        run.actions_json = decisions.build_actions(payload, branch=branch)
        run.completed_at = _now()
        await db.commit()
        return {"status": run.status, "run_id": run_id}
    except RunCancelled:
        return {"status": "cancelled", "run_id": run_id}
    except BudgetExhausted:
        logger.warning(
            "ai_visibility_budget_exhausted",
            extra={"run_id": run_id, "tenant_id": tenant_id},
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code="budget_exhausted",
            error="AI credits are exhausted.",
        )
    except search.SearchRateLimited as exc:
        if not isinstance(exc, search.TenantSearchRateLimited) and (
            int(job.attempts or 0) + 1 < int(job.max_attempts or 1)
        ):
            # Shared provider quota is temporary. Let the durable runner defer
            # this attempt instead of failing one tenant because another is busy.
            logger.info(
                "ai_visibility_search_deferred",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            raise
        logger.warning(
            "ai_visibility_research_rejected",
            extra={
                "run_id": run_id,
                "tenant_id": tenant_id,
                "failure_code": type(exc).__name__,
            },
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code=type(exc).__name__,
            error=_client_error(exc),
        )
    except (
        search.SearchUnavailable,
        research.ResearchValidationError,
        validation.CitationValidationError,
    ) as exc:
        logger.warning(
            "ai_visibility_research_rejected",
            extra={
                "run_id": run_id,
                "tenant_id": tenant_id,
                "failure_code": type(exc).__name__,
            },
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code=type(exc).__name__,
            error=_client_error(exc),
        )
    except Exception as exc:
        if llm_attempted:
            # Once the provider call may have succeeded, a local failure is not
            # proof that no spend occurred. Surface it instead of auto-repeating.
            logger.exception(
                "ai_visibility_post_llm_failure",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            status = "ambiguous"
            failure_code = "post_llm_persistence_failed"
            error = (
                "The research provider completed, but its result could not be "
                "saved safely. Please verify before retrying."
            )
        else:
            logger.exception(
                "ai_visibility_research_failed",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            status = "failed"
            failure_code = "research_failed"
            error = "Research could not be completed. Please retry."
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status=status,
            failure_code=failure_code,
            error=error,
        )
    if run is None:
        return {"status": "cancelled", "run_id": run_id}
    return _finish(run, started, run.status)
