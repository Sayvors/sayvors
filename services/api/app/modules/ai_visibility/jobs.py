"""Durable grounded-research pipeline."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import sentry_sdk

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..locations.models import LocationProfile
from . import decisions, research, search, sources, validation
from .models import AiVisibilityRun

logger = logging.getLogger(__name__)
MIN_SOURCES_FOR_BRIEF = 2
MIN_VALIDATED_CLAIMS = 1


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
            "label": f"S{position + 1}",
            "title": row.title or row.url,
            "url": row.canonical_url or row.url,
            "excerpt": row.excerpt or "",
        }
        for position, row in enumerate(rows)
    ]


async def _status(db: AsyncSession, run: AiVisibilityRun, status: str) -> None:
    run.status = status
    run.updated_at = _now()
    if status == "searching" and run.started_at is None:
        run.started_at = _now()
    await db.commit()


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
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == job.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("run_not_found")
    started = time.monotonic()
    if run.status == "completed":
        return _finish(run, started, "completed")

    try:
        await _status(db, run, "searching")
        results = await search.search_public_web(run.tenant_id, run.prompt_snapshot)
        await _status(db, run, "fetching")
        snapshots = await sources.fetch_sources(db, run.id, results)
        usable = [row for row in snapshots if row.excerpt]
        if len(usable) < MIN_SOURCES_FOR_BRIEF:
            run.status = "insufficient_evidence"
            run.failure_code = "insufficient_sources"
            run.completed_at = _now()
            await db.commit()
            return _finish(run, started, run.status)

        await _status(db, run, "reading")
        branch = await load_branch_facts(db, run.tenant_id, run.channel_id)
        source_payload = _source_payload(usable)
        await _status(db, run, "writing")
        model, payload = await research.complete_research(
            db,
            tenant_id=run.tenant_id,
            channel_id=run.channel_id,
            branch=branch,
            prompt=run.prompt_snapshot,
            locale=run.locale,
            sources=source_payload,
        )
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
        run.validation_status = (
            "partial" if unsupported_claims else "passed"
        )
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
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            run = await db.get(AiVisibilityRun, run.id)
            run.status = "ambiguous"
            run.failure_code = "post_llm_persistence_failed"
            await db.commit()
            return _finish(run, started, "ambiguous")
        return {"status": run.status, "run_id": run.id}
    except BudgetExhausted:
        await db.rollback()
        run = await db.get(AiVisibilityRun, run.id)
        run.status, run.failure_code = "failed", "budget_exhausted"
        run.error = "AI credits are exhausted."
        run.completed_at = _now()
        await db.commit()
    except (
        search.SearchRateLimited,
        search.SearchUnavailable,
        research.ResearchValidationError,
        validation.CitationValidationError,
    ) as exc:
        await db.rollback()
        run = await db.get(AiVisibilityRun, run.id)
        run.status, run.failure_code = "failed", type(exc).__name__
        run.error = str(exc)[:2000]
        run.completed_at = _now()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        run = await db.get(AiVisibilityRun, run.id)
        run.status, run.failure_code = "failed", "research_failed"
        run.error = str(exc)[:2000]
        run.completed_at = _now()
        await db.commit()
    return _finish(run, started, "failed")
