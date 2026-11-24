"""Cache-only review sampling and durable benchmark theme analyses."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..channels.models import Channel
from ..jobs.models import Job, JobStatus
from ..jobs.service import submit_job
from ..jobs.types import JobType
from . import compare, service
from .models import BenchmarkThemeAnalysis
from .theme_extraction import THEME_EXTRACTOR_VERSION, extract_local_themes, group_theme_comparison, normalize_theme_key

MAX_SAMPLE_REVIEWS = 50
MAX_REVIEW_TEXT = 600
VALID_SENTIMENTS = {"positive", "neutral", "negative"}
RETRY_COOLDOWN_SECONDS = 300
ACTIVE_JOB_STATUSES = {
    JobStatus.accepted.value,
    JobStatus.queued.value,
    JobStatus.running.value,
    JobStatus.retrying.value,
    JobStatus.blocked.value,
}


def _bounded(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def _rating(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 5:
        return None
    return int(number) if number.is_integer() else number


def _timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    return _bounded(value, 64)

def _sentiment(stored: Any, rating: int | float | None) -> str:
    value = str(stored or "").lower()
    if value in VALID_SENTIMENTS:
        return value
    if rating is None:
        return "neutral"
    if rating >= 4:
        return "positive"
    if rating == 3:
        return "neutral"
    return "negative"


def normalize_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound provider/analytics rows and synthesize stable ids when absent."""
    normalized: list[dict[str, Any]] = []
    duplicate_counts: dict[str, int] = {}
    for raw in reviews:
        if not isinstance(raw, dict):
            continue
        text = _bounded(raw.get("text", raw.get("review_text")), MAX_REVIEW_TEXT)
        if not text:
            continue
        rating = _rating(raw.get("rating"))
        author = _bounded(raw.get("author", raw.get("reviewer_name")), 255)
        photo = _bounded(raw.get("author_photo", raw.get("reviewer_photo_url")), 1024)
        reviewed_at = _timestamp(
            raw.get("reviewed_at", raw.get("publish_time", raw.get("time", raw.get("created_at"))))
        )
        review_url = _bounded(raw.get("review_url", raw.get("url")), 1024)
        review_id = _bounded(raw.get("review_id"), 255)
        if review_id is None:
            identity = json.dumps(
                [text, rating, author, photo, reviewed_at, review_url],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
            occurrence = duplicate_counts.get(digest, 0)
            duplicate_counts[digest] = occurrence + 1
            review_id = f"synthetic:{digest}" + (f":{occurrence}" if occurrence else "")
        normalized.append({
            "review_id": review_id,
            "review_url": review_url,
            "text": text,
            "rating": rating,
            "sentiment": _sentiment(raw.get("sentiment"), rating),
            "author": author,
            "author_photo": photo,
            "reviewed_at": reviewed_at,
        })
        if len(normalized) >= MAX_SAMPLE_REVIEWS:
            break
    return normalized


def hash_sample(reviews: list[dict[str, Any]]) -> str:
    """Content hash of the exact normalized evidence in newest-first order."""
    canonical = json.dumps(
        {"version": THEME_EXTRACTOR_VERSION, "reviews": reviews},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def build_subject_sample(
    db: AsyncSession, tenant_id: str, raw_subject: str
) -> dict[str, Any] | None:
    """Resolve one subject from tenant-scoped caches; never call a provider."""
    try:
        kind, external_id = compare.parse_subject(raw_subject)
    except compare.CompareError:
        return None

    if kind == "saved":
        saved = await service.get_saved(db, tenant_id, external_id)
        if saved is None:
            return None
        reviews = normalize_reviews(list(saved.reviews or []))
        return {
            "key": str(raw_subject),
            "kind": kind,
            "subject_id": saved.id,
            "name": saved.name or saved.label or saved.place_id,
            "reviews": reviews,
            "sample_hash": hash_sample(reviews),
        }

    channel = (
        await db.execute(
            select(Channel).where(Channel.id == external_id, Channel.user_id == tenant_id)
        )
    ).scalar_one_or_none()
    if channel is None or channel.platform != "google_reviews":
        return None
    published = func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at).label("published")
    rows = (
        await db.execute(
            select(
                ReviewInsight.review_id,
                ReviewInsight.review_text,
                ReviewInsight.rating,
                ReviewInsight.sentiment,
                ReviewInsight.reviewer_name,
                ReviewInsight.reviewer_photo_url,
                ReviewInsight.review_url,
                published,
            ).where(
                ReviewInsight.user_id == tenant_id,
                ReviewInsight.channel_id == external_id,
                ReviewInsight.removed_at.is_(None),
            ).order_by(published.desc(), ReviewInsight.id.desc()).limit(MAX_SAMPLE_REVIEWS)
        )
    ).all()
    reviews = normalize_reviews([
        {
            "review_id": row.review_id,
            "text": row.review_text,
            "rating": row.rating,
            "sentiment": row.sentiment,
            "author": row.reviewer_name,
            "author_photo": row.reviewer_photo_url,
            "review_url": row.review_url,
            "reviewed_at": row.published,
        }
        for row in rows
    ])
    return {
        "key": str(raw_subject),
        "kind": kind,
        "subject_id": channel.id,
        "name": channel.display_name or channel.id,
        "reviews": reviews,
        "sample_hash": hash_sample(reviews),
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _analysis_for_update(
    db: AsyncSession, tenant_id: str, subject_type: str, subject_id: str
) -> BenchmarkThemeAnalysis | None:
    return (
        await db.execute(
            select(BenchmarkThemeAnalysis)
            .where(
                BenchmarkThemeAnalysis.tenant_id == tenant_id,
                BenchmarkThemeAnalysis.subject_type == subject_type,
                BenchmarkThemeAnalysis.subject_id == subject_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


async def ensure_theme_analysis(
    db: AsyncSession,
    tenant_id: str,
    raw_subject: str,
    *,
    retry: bool = False,
    sample: dict[str, Any] | None = None,
) -> BenchmarkThemeAnalysis | None:
    """Atomically ensure one analysis row and its durable bulk job.

    The unique subject row is the concurrency boundary. A savepoint absorbs a
    concurrent insert conflict, then the winner is locked and re-evaluated.
    Retry keys include the previous job id (the retry generation), so a dead
    job is never returned by ``submit_job`` idempotency.
    """
    sample = sample or await build_subject_sample(db, tenant_id, raw_subject)
    if sample is None:
        await db.commit()
        return None

    analysis = await _analysis_for_update(
        db, tenant_id, sample["kind"], sample["subject_id"]
    )
    is_new = analysis is None
    if analysis is None:
        try:
            async with db.begin_nested():
                analysis = BenchmarkThemeAnalysis(
                    tenant_id=tenant_id,
                    subject_type=sample["kind"],
                    subject_id=sample["subject_id"],
                    sample_hash=sample["sample_hash"],
                    sample_json=sample["reviews"],
                    status="pending",
                )
                db.add(analysis)
                await db.flush()
        except IntegrityError:
            analysis = await _analysis_for_update(
                db, tenant_id, sample["kind"], sample["subject_id"]
            )
            if analysis is None:
                raise
            is_new = False

    same_hash = analysis.sample_hash == sample["sample_hash"]
    if same_hash and analysis.status == "ready":
        await db.commit()
        return analysis

    if same_hash and analysis.status in {"pending", "running"}:
        job = await db.get(Job, analysis.job_id) if analysis.job_id else None
        if job is not None and job.tenant_id == tenant_id and job.status in ACTIVE_JOB_STATUSES:
            await db.commit()
            return analysis

    # A normal GET reports a terminal error; only the explicit retry endpoint
    # re-runs it. Stale ready samples rebuild immediately on the next GET so a
    # deployed extractor-version change cannot leave noisy cached themes.
    if analysis.status == "failed" and not retry:
        await db.commit()
        return analysis

    if not is_new and analysis.status != "ready":
        updated_at = _aware(analysis.updated_at)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age < RETRY_COOLDOWN_SECONDS:
            await db.commit()
            return analysis

    previous_job_id = analysis.job_id or "initial"
    analysis.sample_hash = sample["sample_hash"]
    analysis.sample_json = sample["reviews"]
    analysis.themes = []
    analysis.status = "pending"
    analysis.source = None
    analysis.model = None
    analysis.error = None
    analysis.updated_at = datetime.now(timezone.utc)
    job = await submit_job(
        db,
        tenant_id=tenant_id,
        job_type=JobType.benchmark_theme_extract.value,
        payload={
            "analysis_id": analysis.id,
            "subject_type": analysis.subject_type,
            "subject_id": analysis.subject_id,
            "sample_hash": analysis.sample_hash,
        },
        idempotency_key=(
            f"benchmark.theme_extract:{analysis.id}:"
            f"{previous_job_id}:{analysis.sample_hash}"
        ),
        subject_type="benchmark_theme_analysis",
        subject_id=analysis.id,
        lane_key=f"benchmark-theme:{analysis.id}",
    )
    analysis.job_id = job.id
    await db.commit()
    return analysis


def _surface_token(value: str) -> str:
    normalized = normalize_theme_key(value)
    if len(normalized) > 3 and normalized.startswith("ال"):
        normalized = normalized[2:]
    return normalized


def _verbatim_quote(text: str, label: str) -> str:
    """Recover an exact source span for the theme, never generate prose."""
    if not text:
        return ""
    direct = text.casefold().find(label.casefold())
    if direct >= 0:
        return text[direct : direct + len(label)]

    tokens = list(re.finditer(r"[^\W_]+", text, flags=re.UNICODE))
    label_tokens = [_surface_token(token) for token in re.findall(r"[^\W_]+", label, flags=re.UNICODE)]
    label_tokens = [token for token in label_tokens if token]
    if label_tokens:
        width = len(label_tokens)
        for start in range(len(tokens) - width + 1):
            window = tokens[start : start + width]
            candidate = [_surface_token(match.group()) for match in window]
            if candidate == label_tokens or sorted(candidate) == sorted(label_tokens):
                return text[window[0].start() : window[-1].end()]
        for match in tokens:
            if _surface_token(match.group()) in label_tokens:
                return match.group()
    return text


def _row_sentiment(cells: dict[str, dict[str, Any]]) -> str | None:
    mentions = sum(int(cell.get("mentions") or 0) for cell in cells.values())
    positive = sum(int(cell.get("positive") or 0) for cell in cells.values())
    negative = sum(int(cell.get("negative") or 0) for cell in cells.values())
    if positive + negative == 0 or mentions <= 0:
        return None
    if (
        positive > 0
        and negative > 0
        and positive / mentions < 0.6
        and negative / mentions < 0.6
    ):
        return "mixed"
    return "positive" if positive >= negative else "negative"


def _quote(theme: dict[str, Any], example: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    source = review or example
    text = str(source.get("text") or "")[:MAX_REVIEW_TEXT]
    return {
        "review_id": source.get("review_id"),
        "quote": _verbatim_quote(text, str(theme.get("label") or "")),
        "review_text": text,
        "rating": source.get("rating"),
        "author": source.get("author"),
        "author_photo": source.get("author_photo"),
        "reviewed_at": source.get("reviewed_at", source.get("time")),
        "review_url": source.get("review_url"),
    }


def _cell(theme: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    quotes = []
    for example in (theme.get("examples") or [])[:2]:
        if not isinstance(example, dict):
            continue
        review = reviews.get(str(example.get("review_id") or ""))
        quote = _quote(theme, example, review)
        if quote["review_text"]:
            quotes.append(quote)
    return {
        "mentions": int(theme.get("mentions") or 0),
        "sample_size": int(theme.get("sample_size") or 0),
        "percentage": theme.get("pct", 0.0),
        "positive": int(theme.get("positive_mentions") or 0),
        "negative": int(theme.get("negative_mentions") or 0),
        "quotes": quotes,
    }


def assemble_theme_response(
    records: list[dict[str, Any]],
    *,
    own_key: str | None = None,
) -> dict[str, Any]:
    """Map persisted themes through the shared grouper into the API contract."""
    subjects = []
    ready = []
    for record in records:
        subject = {
            key: record.get(key)
            for key in (
                "key", "name", "kind", "status", "sample_size", "sample_hash",
                "analyzed_at", "source", "error_code", "error_message",
            )
        }
        subjects.append(subject)
        if record.get("status") == "ready" or record.get("themes"):
            ready.append({"key": record["key"], "themes": record.get("themes") or []})

    own_key = own_key or next(
        (record["key"] for record in records if record.get("kind") == "own"), None
    )
    records_by_key = {record["key"]: record for record in records}
    rows = []
    for grouped in group_theme_comparison(ready, own_key=own_key):
        cells = {
            key: _cell(theme, {
                str(review.get("review_id") or ""): review
                for review in records_by_key[key]["reviews"]
            })
            for key, theme in grouped["cells"].items()
        }
        sentiment = _row_sentiment(cells)
        if sentiment is None:
            continue
        rows.append({
            "key": grouped["key"],
            "label": grouped["label"],
            "sentiment": sentiment,
            "cells": cells,
            "own_pct": grouped["own_pct"],
            "peer_median_pct": grouped["peer_median_pct"],
            "gap_pct": grouped["gap_pct"],
            "max_mentions": grouped["max_mentions"],
        })
    return {"subjects": subjects, "rows": rows}


async def theme_response(
    db: AsyncSession,
    tenant_id: str,
    raw_subjects: list[str],
    *,
    retry: bool = False,
    main_key: str | None = None,
) -> dict[str, Any]:
    """Read/enqueue up to six subjects and assemble only persisted results."""
    if not 1 <= len(raw_subjects) <= compare.MAX_SUBJECTS:
        raise compare.CompareError(f"Ask for themes of one to {compare.MAX_SUBJECTS} subjects.")
    records = []
    for raw in raw_subjects:
        key = str(raw)
        sample = await build_subject_sample(db, tenant_id, key)
        if sample is None:
            try:
                kind, _ident = compare.parse_subject(key)
            except compare.CompareError:
                kind = "unknown"
            records.append({
                "key": key,
                "name": key,
                "kind": kind,
                "status": "unavailable",
                "sample_size": 0,
                "sample_hash": None,
                "analyzed_at": None,
                "error_code": "unavailable",
                "error_message": "This subject is not available in your workspace.",
                "reviews": [],
                "themes": [],
            })
            continue

        analysis = await ensure_theme_analysis(
            db, tenant_id, key, retry=retry, sample=sample
        )
        # Re-read under the same row lock the worker uses before adding instant
        # local evidence. A worker that finished while ensure_theme_analysis
        # returned must not have its LLM themes overwritten by the fallback.
        analysis = await _analysis_for_update(
            db, tenant_id, analysis.subject_type, analysis.subject_id
        ) or analysis
        status = {"pending": "pending", "running": "pending", "ready": "ready", "failed": "error"}.get(
            analysis.status, "error"
        )
        if status == "pending" and not analysis.themes:
            # Local extraction is deterministic and fast (~30ms for 50 reviews).
            # Show useful evidence immediately while the LLM refinement runs in
            # the background; the worker replaces these themes when it finishes.
            analysis.themes = extract_local_themes(analysis.sample_json or [])
            analysis.source = "local"
            analysis.updated_at = datetime.now(timezone.utc)
            await db.commit()
        record = {
            "key": key,
            "name": sample["name"],
            "kind": sample["kind"],
            "status": status,
            "sample_size": len(analysis.sample_json or []),
            "sample_hash": analysis.sample_hash,
            "analyzed_at": _aware(analysis.updated_at).isoformat() if status in {"ready", "error"} else None,
            "reviews": analysis.sample_json or [],
            "themes": analysis.themes or [],
        }
        if status == "ready":
            record["source"] = analysis.source
        elif status == "error":
            record["error_code"] = "analysis_failed"
            record["error_message"] = analysis.error or "Theme analysis failed."
        records.append(record)
    return assemble_theme_response(records, own_key=main_key)
