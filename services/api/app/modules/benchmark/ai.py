"""AI takeaway over the benchmark comparison numbers.

Builds a compact numeric payload from the same pure functions the compare
endpoint caches (``north_star`` rank/gaps + ``distribution`` best/worst per
metric) plus each subject's headline numbers, and asks the tenant's enabled
text model for a 1-2 sentence summary.

Privacy invariant: review text never leaves the database. The LLM payload is
names and numbers only — every field traced back to ``summary`` helpers, so
adding a metric here cannot leak prose.

Fail-open by design: any LLM failure, timeout, or absence of an enabled model
returns a rule-based template built from the same numbers with HTTP 200 and
``source: "template"``. The compare page must always render a takeaway, and a
broken provider is not the user's problem to see as an error banner.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.gateway import LLMMessage, complete, resolve_tenant_model
from . import compare
from . import summary as summary_metrics
from .summary import METRIC_SPECS, north_star
from .summary import distribution as metric_distribution

logger = logging.getLogger(__name__)

# A slow provider must not hold the compare page open. 8s covers a small
# completion comfortably; past that the template is better than waiting.
LLM_TIMEOUT_SECONDS = 8.0
# The card shows 1-2 sentences; hard-cap whatever the model returns.
SUMMARY_MAX_CHARS = 300
# Two short sentences fit well inside 100 tokens, and the cap bounds cost.
SUMMARY_MAX_TOKENS = 100

SYSTEM_PROMPT = """You are a business benchmarking assistant. Given JSON numbers comparing the user's business against competitors, write 1-2 short sentences on where the user stands and the single biggest gap to close. Plain text only. No markdown, no lists, no greetings, max 50 words. Never use em dashes or en dashes. Use commas or full stops instead."""

# Human labels for the gap sentence; keyed by the summary.METRIC_SPECS ids.
_METRIC_LABELS = {
    "avg_rating": "rating",
    "reviews_per_month": "review velocity",
    "total_reviews": "review volume",
    "positive_pct": "positive review share",
}


def _headline_metrics(subject: dict[str, Any]) -> dict[str, float | None]:
    """The four headline numbers for one subject (or nulls when unknown).

    Reads through ``summary._value`` so the payload matches the distribution
    and north-star numbers exactly (velocity derivation, sentiment container,
    total_ratings fallback) instead of drifting into its own semantics.
    """
    return {
        metric: summary_metrics._value(subject, metric)
        for metric in METRIC_SPECS
    }


def build_numeric_payload(
    subject_records: list[dict[str, Any]], own_keys: list[str]
) -> dict[str, Any]:
    """The ONLY data sent to the LLM: rank, gaps, distribution and headlines.

    Mirrors the compare endpoint's cached aggregate so the narrative always
    describes exactly what the page shows.
    """
    available = [s for s in subject_records if s.get("available")]
    own_keys = [k.strip() for k in own_keys]
    return {
        "north_star": north_star(subject_records, own_keys),
        "distribution": metric_distribution(subject_records),
        "subjects": [
            {
                "name": s.get("name"),
                "own": (s.get("key") or "").strip() in set(own_keys),
                "metrics": _headline_metrics(s),
            }
            for s in available
        ],
    }


def template_summary(payload: dict[str, Any]) -> str:
    """Rule-based (en) fallback from rank, leader and the worst gap."""
    ns = payload.get("north_star")
    if ns:
        own_name = (ns.get("own") or {}).get("name") or "Your location"
        leader_name = (ns.get("leader") or {}).get("name")
        rank, of = ns.get("rank"), ns.get("of")
        if rank == 1:
            lines = [f"{own_name} leads the bench ({rank} of {of})."]
        else:
            behind = f", behind {leader_name}" if leader_name else ""
            lines = [f"{own_name} ranks {rank} of {of}{behind}."]
        # The ranking metric is avg_rating, so prefer its gap; the first
        # non-null gap in spec order keeps the sentence deterministic.
        gaps = ns.get("gaps") or {}
        for metric in METRIC_SPECS:
            gap = gaps.get(metric)
            if gap:
                label = _METRIC_LABELS[metric]
                lines.append(
                    f"Closing the {label} gap ({gap}) is the biggest lever."
                )
                break
        return " ".join(lines)[:SUMMARY_MAX_CHARS]

    dist = payload.get("distribution") or {}
    rating = dist.get("avg_rating")
    if rating:
        best, worst = rating.get("best") or {}, rating.get("worst") or {}
        return (
            f"Across this bench, {best.get('name')} leads on rating at "
            f"{best.get('value')} while {worst.get('name')} trails at "
            f"{worst.get('value')}."
        )[:SUMMARY_MAX_CHARS]

    return (
        "Not enough comparison data yet: add your location and save "
        "competitors to the bench to see where you stand."
    )


async def _llm_summary(
    payload: dict[str, Any], tenant_id: str, db: AsyncSession
) -> str:
    model = await resolve_tenant_model(db)
    resp = await asyncio.wait_for(
        complete(
            model=model,
            messages=[LLMMessage(role="user", content=json.dumps(payload))],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=SUMMARY_MAX_TOKENS,
            tenant_id=tenant_id,
            purpose="benchmark.ai_summary",
        ),
        timeout=LLM_TIMEOUT_SECONDS,
    )
    text = (resp.content or "").strip()[:SUMMARY_MAX_CHARS]
    if not text:
        # An empty completion would blank the card; treat it as a failure so
        # the caller falls back to the template.
        raise ValueError("LLM returned an empty summary")
    return text


async def ai_summary(
    db: AsyncSession, tenant_id: str, subjects: list[str]
) -> dict[str, str]:
    """Contract shape for POST /benchmark/ai-summary (cache handled upstream)."""
    subject_records = await compare.compare_subjects(db, tenant_id, subjects)
    own_keys = [s.strip() for s in subjects if s.strip().startswith("own:")]
    payload = build_numeric_payload(subject_records, own_keys)

    # Nothing available means nothing to narrate: skip the paid call entirely.
    if not payload["subjects"]:
        return {"summary": template_summary(payload), "source": "template"}

    try:
        text = await _llm_summary(payload, tenant_id, db)
        return {"summary": text, "source": "ai"}
    except Exception as exc:
        logger.warning(
            "Benchmark AI summary fell back to template (tenant=%s): %s",
            tenant_id, exc,
        )
        return {"summary": template_summary(payload), "source": "template"}
