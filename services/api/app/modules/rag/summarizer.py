"""LLM-polished page summaries (§31 Phase C).

Upgrades the extractive Phase B summary with an LLM one, per crawled page:

- ``meta["ai_summary"]``    — 2–3 sentences, written in the page's language
- ``meta["ai_key_points"]`` — 3–6 faithful bullets
- ``meta["enriched_at"]``   — UTC timestamp, also the idempotency marker

Hard guarantees:

- **Never breaks ingest.** Enrichment runs fire-and-forget after a scrape
  ingest job succeeds; any failure keeps the extractive summary.
- **Never re-bills for unchanged content.** ``enriched_at`` on the doc means
  skip — re-crawls of unchanged pages cost zero LLM tokens.
- **Bounded cost.** Off by default (``RAG_AI_SUMMARY_ENABLED``), concurrency
  capped (``RAG_AI_SUMMARY_CONCURRENCY``), input markdown truncated, output
  ``max_tokens`` capped, and every call goes through the budgeted, metered
  gateway (purpose ``rag.page_summary``) so tenant budgets are respected.
- **No fabrication accepted.** The model must answer with strict JSON;
  anything unparseable, empty, or type-wrong is discarded and the extractive
  summary stays.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ...config import settings
from ...database import async_session
from .models import Document

logger = logging.getLogger(__name__)

SUMMARY_PURPOSE = "rag.page_summary"

# Input bound: long pages are summarized from their opening content; crawl
# markdown is already the article body (nav chrome removed by trafilatura).
_MAX_INPUT_CHARS = 6000

# Concurrency ceiling for LLM calls from this process.
_ENRICH_SEMAPHORE = asyncio.Semaphore(max(1, settings.RAG_AI_SUMMARY_CONCURRENCY))

_SYSTEM_PROMPT = (
    "You summarize web pages for a knowledge base used by an AI assistant. "
    "Rules you must never break:\n"
    "1. Use ONLY facts present in the provided page text. Never invent facts, "
    "prices, names or claims.\n"
    "2. Write the summary and key points in the SAME language as the page "
    "text (the page language is given; when it is Arabic, answer in Arabic).\n"
    "3. Answer with STRICT JSON only — no markdown fences, no commentary:\n"
    '{"summary": "2-3 sentences", "key_points": ["point", "point", "point"]}\n'
    "summary: 2-3 sentences describing what this page offers. "
    "key_points: 3-6 short factual bullets."
)


def parse_enrichment(text: str) -> dict | None:
    """Parse the model's strict-JSON answer; None when unusable.

    Accepts fenced or bare JSON. Validates types and drops empty content so a
    chatty or broken model can never overwrite a good extractive summary.
    """
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        # Strip a ```json ... ``` fence.
        candidate = candidate.split("\n", 1)[-1]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3]
    candidate = candidate.strip()
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        # Tolerate prose around the JSON object.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(candidate[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    key_points = data.get("key_points")
    if not isinstance(summary, str) or len(summary.strip()) < 20:
        return None
    if not isinstance(key_points, list):
        key_points = []
    cleaned_points = [
        str(p).strip() for p in key_points if isinstance(p, str) and p.strip()
    ][:6]
    return {"summary": summary.strip()[:600], "key_points": cleaned_points}


async def enrich_document(doc_id: str) -> bool:
    """Enrich one scraped document with an LLM summary. Best-effort.

    Returns True when meta was updated. Never raises — a summarization
    failure must not surface anywhere; the extractive summary already stored
    in ``meta`` remains the fallback.
    """
    async with async_session() as db:
        doc = (
            await db.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one_or_none()
        if doc is None:
            return False
        meta = dict(doc.meta or {})
        if meta.get("enriched_at"):
            return False  # already enriched — never re-bill for one page
        url = doc.source_url or doc.filename
        lang = doc.lang or "en"

        try:
            # Lazy module import keeps the storage seam patchable in tests and
            # avoids binding a stale function object at module import time.
            from ...core import storage

            content = storage.get_doc(
                doc.databank_id, f"{doc.id}.{doc.file_type}"
            )
            markdown = content.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            logger.info("Enrich skipped, no stored file for doc %s", doc_id)
            return False

        if not settings.RAG_AI_SUMMARY_ENABLED:
            return False

        from ..llm.gateway import LLMMessage, complete, resolve_tenant_model

        model = await resolve_tenant_model(db)
        if not model:
            logger.info("Enrich skipped, no enabled LLM model (doc %s)", doc_id)
            return False

        page_text = markdown[:_MAX_INPUT_CHARS]
        user_payload = json.dumps({
            "url": url[:300],
            "language": lang,
            "title": (meta.get("title") or "")[:200],
            "page_text": page_text,
        }, ensure_ascii=False)

        async with _ENRICH_SEMAPHORE:
            try:
                resp = await complete(
                    model=model,
                    messages=[LLMMessage(role="user", content=user_payload)],
                    system_prompt=_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_tokens=400,
                    tenant_id=doc.user_id,
                    purpose=SUMMARY_PURPOSE,
                )
            except Exception as e:  # noqa: BLE001 — enrichment is optional
                logger.warning(
                    "Enrich failed for doc %s (%s): %s", doc_id, url[:120], e
                )
                return False

        parsed = parse_enrichment(resp.content)
        if parsed is None:
            logger.warning(
                "Enrich discarded unusable model answer for doc %s (%s)",
                doc_id, url[:120],
            )
            return False

        # Re-read inside the same session window: the doc may have been
        # re-crawled while the LLM call was in flight; prefer freshest meta.
        await db.refresh(doc)
        meta = dict(doc.meta or {})
        if meta.get("enriched_at"):
            return False
        meta["ai_summary"] = parsed["summary"]
        meta["ai_key_points"] = parsed["key_points"]
        meta["enriched_at"] = datetime.now(timezone.utc).isoformat()
        doc.meta = meta
        await db.commit()
        logger.info("Enriched doc %s (%s)", doc_id, url[:120])
        return True


# Fire-and-forget bookkeeping (asyncio requires tasks stay referenced).
_enrich_tasks: set[asyncio.Task] = set()


def maybe_enrich_document(doc_id: str) -> None:
    """Schedule enrichment when enabled; never blocks the caller.

    Called after a scrape ingest job completes successfully.
    """
    if not settings.RAG_AI_SUMMARY_ENABLED:
        return

    async def _run() -> None:
        try:
            await enrich_document(doc_id)
        except Exception:  # noqa: BLE001 — must never crash the worker loop
            logger.exception("Enrich task crashed for doc %s", doc_id)

    task = asyncio.create_task(_run())
    _enrich_tasks.add(task)
    task.add_done_callback(_enrich_tasks.discard)
