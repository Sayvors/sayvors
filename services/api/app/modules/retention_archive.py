"""Cold-storage archive for retention rows, in a training-ready shape.

The operational database must stay small; the review-generation trace is still
worth keeping because it records *how* an answer was made — the tool call, the
selected strategy, the retrieved offer and the generated text. That is the
format a tool-using model needs if we ever fine-tune one.

Archive objects are private: a dedicated S3_ARCHIVE_BUCKET, never the public
media bucket. Reviewer names are dropped (personal data); review text is kept
because it is the model's input. Failures are loud — the caller must not delete
rows it failed to archive.
"""
from __future__ import annotations

import gzip
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from .admin.models import RetentionRun

logger = logging.getLogger(__name__)

# Fields that can identify a person directly. Review text is deliberately NOT
# in this list: it is the input the model answered, and removing it would make
# the archive useless for its stated purpose.
_PII_FIELDS = frozenset({
    "reviewer_name", "created_by", "reviewed_by", "email", "phone",
    "contact_phone", "customer_name",
})

# Preserve the full tool-call trajectory. These are not noise to be trimmed —
# they are the reason we archive instead of simply deleting.
_REVIEW_LOG_FIELDS = (
    "id", "tenant_id", "channel_id", "review_id", "review_text", "rating",
    "channel", "analysis", "selected_strategies", "tool_calls",
    "retrieved_offers", "generated_response", "validation_result", "status",
    "model", "token_input", "token_output", "latency_ms", "created_at",
)
_CONNECT_EVENT_FIELDS = ("id", "session_id", "level", "message", "created_at")


def _clean(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _PII_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _record(kind: str, row: Any) -> dict[str, Any]:
    fields = _REVIEW_LOG_FIELDS if kind == "review_generation" else _CONNECT_EVENT_FIELDS
    raw = {field: getattr(row, field, None) for field in fields}
    # One explicit pass over the dict removes top-level PII too; nested tool
    # payloads are handled recursively by _clean.
    raw = {k: v for k, v in raw.items() if k not in _PII_FIELDS}
    return _clean(raw)


def format_archive(kind: str, rows: Iterable[Any]) -> tuple[bytes, int]:
    """Return (gzip bytes, row count) for one categorised JSONL archive."""
    records = [_record(kind, row) for row in rows]
    body = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records)
    return gzip.compress(body.encode("utf-8")), len(records)


def archive_key(kind: str, *, now: datetime | None = None) -> str:
    """Categorised, collision-free key: retention/<kind>/<year>/<month>/..."""
    stamp = now or datetime.now(timezone.utc)
    return (
        f"retention/{kind}/{stamp.year:04d}/{stamp.month:02d}/"
        f"{stamp.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    )


async def archive_rows(
    db: AsyncSession,
    *,
    kind: str,
    rows: list[Any],
    trigger: str,
    s3_put,
) -> RetentionRun:
    """Upload one batch, record the run, return it. Raises on S3 failure."""
    data, count = format_archive(kind, rows)
    key = archive_key(kind)
    started = datetime.now(timezone.utc)
    run = RetentionRun(
        id=str(uuid.uuid4()), kind=kind, action="backup", s3_key=key,
        rows=count, size_bytes=len(data), status="running",
        trigger_type=trigger, started_at=started,
    )
    db.add(run)
    try:
        s3_put("archive", key, data, "application/gzip")
    except Exception as e:  # noqa: BLE001 - surface it so the caller won't delete
        run.status = "failed"
        run.error = str(e)[:500]
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        logger.error("Retention archive failed kind=%s key=%s: %s", kind, key, e)
        raise
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Retention archive kind=%s rows=%d key=%s", kind, count, key)
    return run
