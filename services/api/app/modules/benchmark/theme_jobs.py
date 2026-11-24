"""Durable benchmark.theme_extract worker logic.

The handler freezes a bounded review sample, marks it running before any model
call, and re-checks the job/hash before persistence so a slow worker cannot
overwrite a newer analysis. Provider/model/output failures use local extraction;
database failures propagate to the job runner.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.gateway import LLMMessage, complete, resolve_tenant_model
from .models import BenchmarkThemeAnalysis
from .theme_extraction import extract_local_themes, validate_llm_themes
from .theme_service import MAX_REVIEW_TEXT, MAX_SAMPLE_REVIEWS, hash_sample, normalize_reviews

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 1200

SYSTEM_PROMPT = """You extract repeated review themes for business benchmarking.
Return strict JSON only, with no markdown or commentary:
{"themes":[{"label":"short theme phrase","mentions":2,"review_indices":[0,1]}]}
Use only the supplied review indices. Every index must be unique, mentions must
equal the number of indices, and a theme needs at least two distinct reviews.
Labels must be short phrases supported by those reviews. Return at most 12 themes.
Never invent reviews, counts, quotes, ratings, or sentiment."""


def _parse_content(content: str | None) -> Any:
    text = str(content or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _prompt_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "rating": review.get("rating"),
            "sentiment": review.get("sentiment"),
            "text": str(review.get("text") or "")[:MAX_REVIEW_TEXT],
        }
        for index, review in enumerate(reviews[:MAX_SAMPLE_REVIEWS])
    ]


async def _guarded_analysis(
    db: AsyncSession, job: Any, payload: dict[str, Any], *, refresh: bool = False
) -> BenchmarkThemeAnalysis | None:
    analysis_id = payload.get("analysis_id")
    sample_hash = payload.get("sample_hash")
    if not analysis_id or not sample_hash:
        return None
    stmt = select(BenchmarkThemeAnalysis).where(
        BenchmarkThemeAnalysis.id == str(analysis_id),
        BenchmarkThemeAnalysis.tenant_id == job.tenant_id,
        BenchmarkThemeAnalysis.job_id == job.id,
        BenchmarkThemeAnalysis.sample_hash == str(sample_hash),
    )
    if refresh:
        stmt = stmt.execution_options(populate_existing=True)
    return (await db.execute(stmt.with_for_update())).scalar_one_or_none()


async def _persist_failure(db: AsyncSession, job: Any, payload: dict[str, Any], error: Exception) -> None:
    analysis = await _guarded_analysis(db, job, payload, refresh=True)
    if analysis is None:
        await db.commit()
        return
    analysis.status = "failed"
    analysis.error = str(error)[:2000] or type(error).__name__
    analysis.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def _local_themes_or_fail(
    db: AsyncSession, job: Any, payload: dict[str, Any], reviews: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        return extract_local_themes(reviews)
    except SQLAlchemyError:
        raise
    except Exception as exc:
        await _persist_failure(db, job, payload, exc)
        raise


async def handle_benchmark_theme_extract(job: Any, db: AsyncSession) -> dict[str, Any]:
    """Validate ownership/version, run one bounded extraction, persist atomically."""
    payload = job.payload or {}
    if getattr(job, "job_type", "benchmark.theme_extract") != "benchmark.theme_extract":
        return {"status": "skipped", "reason": "job_type"}
    analysis = await _guarded_analysis(db, job, payload)
    if analysis is None:
        return {"status": "skipped", "reason": "analysis not found"}
    if analysis.status == "ready":
        return {"status": "already_ready", "analysis_id": analysis.id}

    raw_reviews = analysis.sample_json if isinstance(analysis.sample_json, list) else []
    reviews = normalize_reviews(raw_reviews)
    if hash_sample(reviews) != analysis.sample_hash:
        error = ValueError("Stored theme sample failed bounded validation")
        await _persist_failure(db, job, payload, error)
        raise error

    analysis.status = "running"
    analysis.error = None
    analysis.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if len(reviews) < 2:
        themes = await _local_themes_or_fail(db, job, payload, reviews)
        source = "local"
        model = None
    else:
        source = "local"
        model = None
        try:
            model = await resolve_tenant_model(db)
            # Model resolution is a read; release its transaction before the
            # external call so a slow provider never holds a DB connection.
            await db.commit()
            response = await complete(
                model=model,
                messages=[LLMMessage(
                    role="user",
                    content=json.dumps({"reviews": _prompt_reviews(reviews)}, ensure_ascii=False),
                )],
                system_prompt=SYSTEM_PROMPT,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                tenant_id=job.tenant_id,
                purpose="benchmark.theme_extract",
            )
            validated = validate_llm_themes(_parse_content(response.content), reviews)
            if validated is None:
                raise ValueError("LLM theme payload failed evidence validation")
            themes = validated
            source = "llm"
        except SQLAlchemyError:
            raise
        except Exception as exc:
            logger.warning(
                "Benchmark theme LLM fell back to local (tenant=%s analysis=%s): %s",
                job.tenant_id, analysis.id, exc,
            )
            themes = await _local_themes_or_fail(db, job, payload, reviews)

    try:
        current = await _guarded_analysis(db, job, payload, refresh=True)
        if current is None:
            await db.commit()
            return {"status": "skipped", "reason": "stale analysis"}
        current.themes = themes
        current.status = "ready"
        current.source = source
        current.model = model
        current.error = None
        current.updated_at = datetime.now(timezone.utc)
        await db.commit()
    except SQLAlchemyError:
        raise
    except Exception as exc:
        await _persist_failure(db, job, payload, exc)
        raise
    return {"status": "ready", "analysis_id": current.id, "source": source}
