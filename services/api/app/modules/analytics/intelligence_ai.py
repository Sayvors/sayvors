"""AI Review Intelligence — LLM analysis grounded in Retrieval Layer context.

Pipeline (accuracy-first):
  1. Load the tenant's real reviews (ReviewInsight rows).
  2. Compute VERIFIED stats server-side (avg, total, distribution, sentiment
     split, response rate). The LLM never supplies these numbers — they are
     overwritten with computed values after parsing.
  3. Pull business-overview evidence from the Retrieval Layer (single need,
     all mechanisms, minimized facts) so the analysis knows what the
     business actually sells and sounds like.
  4. Ask the LLM for an EXACT JSON shape (low temperature). Strip code
     fences, json-parse, Pydantic-validate. One retry with the validation
     errors echoed back.
  5. VERIFY the parsed payload: clamp mentions/percentages/ratings into
     sane ranges, drop empty themes, cap list lengths. Numbers the LLM got
     wrong are replaced, never trusted.
  6. If the LLM is unreachable twice, fall back to deterministic themes
     built from enrichment topics + review text (flagged `source:
     "fallback"` so the UI can say so honestly).

Model chain: Gemini Flash first (key present in .env), then GPT-4o Mini.
Missing keys fail fast (503) straight into the fallback.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dimensions import score_dimensions
from .models import ReviewInsight

logger = logging.getLogger(__name__)

MODELS_CHAIN = ["groq:qwen3.8-27b", "gemini:gemini-3.6-flash", "openai:gpt-4o-mini"]
MAX_REVIEWS = 50
MAX_RAG_CHARS = 4000

STOPWORDS = {
    "that", "this", "with", "from", "have", "still", "they", "them",
    "your", "about", "there", "their", "what", "when", "which", "were",
    "been", "very", "just", "will", "would", "could", "should", "great",
    "good", "nice", "best", "much", "more", "most", "than", "then",
    "also", "well", "even", "only", "into", "over", "such", "using",
    # Retrieval-query hygiene: chatty filler that dominated topic queries.
    "really", "things", "thing", "stuff", "thanks", "thank", "version",
    "always", "never", "every", "after", "before", "again", "still",
    "definitely", "absolutely", "literally", "actually", "basically",
    "definitely", "recommend", "recommended", "place", "visited", "visit",
    "ordered", "order", "went", "come", "came", "get", "got", "make",
    "made", "time", "times", "day", "days", "night", "people", "person",
}


# ── Strict AI contract ──────────────────────────────────────────

class AIEvidence(BaseModel):
    """A verbatim-ish fragment of a review backing a dimension claim."""

    quote: str = Field(..., min_length=2, max_length=200)
    rating: int = Field(..., ge=1, le=5)


class AIDimension(BaseModel):
    """One business dimension judged from the reviews in the interval.

    Bidirectional: praise and complaints land on the SAME dimension, split into
    `positive` / `negative`. `standard=False` marks a dimension the model
    discovered in the reviews that is not part of the fixed set.
    """

    key: str = Field(..., min_length=2, max_length=40)
    label: str = Field(..., min_length=2, max_length=60)
    standard: bool = True
    mentions: int = Field(..., ge=0)
    positive: int = Field(..., ge=0)
    negative: int = Field(..., ge=0)
    avg_rating: float = Field(..., ge=1.0, le=5.0)
    verdict: str = Field(..., min_length=2, max_length=240)
    evidence: list[AIEvidence] = Field(default_factory=list, max_length=3)


class AICompetitive(BaseModel):
    """Where this business leads / trails, against the anonymised cohort."""

    wins: list[str] = Field(default_factory=list, max_length=4)
    gaps: list[str] = Field(default_factory=list, max_length=4)

class AITheme(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    mentions: int = Field(..., ge=0)
    avg_rating: float = Field(..., ge=1.0, le=5.0)
    positive_pct: int = Field(..., ge=0, le=100)
    phrases: list[str] = Field(default_factory=list, max_length=3)
    trend: str = Field(default="stable", pattern="^(up|down|stable)$")


class AIOpportunity(BaseModel):
    level: str = Field(..., pattern="^(HIGH|MEDIUM|MAINTAIN)$")
    title: str = Field(..., min_length=1, max_length=120)
    detail: str = Field(..., min_length=1, max_length=300)
    impact: str = Field(..., min_length=1, max_length=20)


class AIStrength(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    mentions: int = Field(..., ge=0)
    avg: float = Field(..., ge=1.0, le=5.0)


class AIAction(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    detail: str = Field(..., min_length=1, max_length=200)


class AIIntelligence(BaseModel):
    summary: str = Field(..., min_length=10, max_length=600)
    themes: list[AITheme] = Field(default_factory=list, max_length=8)
    opportunities: list[AIOpportunity] = Field(default_factory=list, max_length=4)
    strengths: list[AIStrength] = Field(default_factory=list, max_length=4)
    actions: list[AIAction] = Field(default_factory=list, max_length=5)
    # Business Health Scorecard: standard dimensions + at most 4 discovered ones.
    dimensions: list[AIDimension] = Field(default_factory=list, max_length=10)
    competitive: AICompetitive = Field(default_factory=AICompetitive)

    @field_validator("summary", mode="before")
    @classmethod
    def _strip_summary(cls, v):
        return str(v).strip()[:600] if v else v


SYSTEM_PROMPT = """You are a local-business review analyst. Analyze the customer reviews and return EXACTLY the JSON object described below — no markdown, no code fences, no commentary, no extra keys.

Schema:
{
  "summary": "2-3 sentence executive summary: overall sentiment, what customers praise most, biggest drag. Max 600 chars.",
  "themes": [{"name": "short theme label", "mentions": <int: reviews mentioning it>, "avg_rating": <1-5 float>, "positive_pct": <0-100 int>, "phrases": ["up to 3 short verbatim-feel phrases"], "trend": "up|down|stable"}],
  "opportunities": [{"level": "HIGH|MEDIUM|MAINTAIN", "title": "<=120 chars", "detail": "<=300 chars with counts", "impact": "HIGH|MEDIUM|GUARD"}],
  "strengths": [{"title": "<=120 chars", "mentions": <int>, "avg": <1-5 float>}],
  "actions": [{"title": "<=120 chars", "detail": "<=200 chars"}],
  "dimensions": [{"key": "<standard key or short slug>", "label": "<=60 chars", "standard": true|false, "mentions": <int>, "positive": <int>, "negative": <int>, "avg_rating": <1-5 float>, "verdict": "<=240 chars, plain language, must cite the counts>", "evidence": [{"quote": "<=200 chars, taken from a review>", "rating": <1-5 int>}]}],
  "competitive": {"wins": ["<string with a number>"], "gaps": ["<string with a number>"]}
}

BUSINESS DIMENSIONS — always evaluate these six, using these exact keys and labels:
  credibility = "Credibility & Trust"
  support     = "Customer Support & Staff"
  speed       = "Responsiveness & Speed"
  quality     = "Product/Service Quality"
  value       = "Value for Money"
  environment = "Cleanliness & Environment"

Dimension rules:
- "standard": true for the six above. Set "standard": false ONLY for a topic the reviews raise that genuinely does NOT fit any of the six (e.g. parking, delivery, atmosphere-only, menu variety, accessibility). Maximum 4 non-standard dimensions.
- If a finding could belong to one of the six, put it there. Do NOT create "Waiter Ethics" or "Tasty Food" as new dimensions — that is Customer Support and Product/Service Quality.
- OMIT any of the six that no review touches. Never emit a dimension with mentions = 0. A missing dimension is the honest answer; the UI hides empty ones anyway.
- Dimensions are BIDIRECTIONAL: praise AND complaints count toward the same dimension, split into "positive" (4-5★ reviews) and "negative" (1-2★ reviews). A dimension can come out entirely negative — that is valuable, report it honestly.
- "mentions" must equal the number of DISTINCT reviews that touch the dimension and must never exceed the total review count. "positive" + "negative" must be <= "mentions" (3★ reviews are neither).
- Every dimension needs at least 1 "evidence" quote copied from a review, with that review's rating. No evidence means the dimension gets dropped — do not invent quotes.
- "verdict" is one plain sentence for a business owner, e.g. "Strong: 3 reviews praise the staff by name; 1 complains about weekend waits." Reference the counts you report.

Competitive rules:
- Use ONLY the "competitive_facts" block provided in the user message. If it is empty or says insufficient data, return empty wins and gaps.
- Every claim must carry its number and name the comparison ("4.6★ vs 4.1★ cohort average"). Never invent competitors, names, or numbers.
- "wins" = where this business leads the cohort. "gaps" = where it trails, phrased as the concrete thing to fix. If the cohort has no complaints about something this business is also praised for, that is a win worth stating.

General rules:
- Ground every theme in the ACTUAL review texts. Never invent topics, names, products or events not present in the reviews.
- mentions must never exceed the total review count provided.
- Use the BUSINESS CONTEXT only to interpret wording (e.g. what "it" refers to), never as a source of claims.
- With few reviews, return few themes. An empty themes array is acceptable when there is nothing to say.
- Temperature is low; be conservative and factual."""


# ── Data loading ────────────────────────────────────────────────

async def _load_reviews(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None,
    days: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    """Load reviews for the requested interval.

    Presets pass `days` (rolling window from now); the month picker passes an
    explicit `date_from`/`date_to` range. Both are applied to the review date —
    previously `since` was computed and thrown away, so "September" analysis
    silently returned all-time data.
    """
    filters = [
        ReviewInsight.user_id == user_id,
        ReviewInsight.review_updated_at.is_not(None),
    ]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
    if date_from is not None:
        filters.append(ReviewInsight.review_updated_at >= date_from)
    if date_to is not None:
        filters.append(ReviewInsight.review_updated_at < date_to)
    elif days:
        filters.append(
            ReviewInsight.review_updated_at
            >= datetime.now(timezone.utc) - timedelta(days=max(1, days))
        )
    rows = (
        await db.execute(
            select(ReviewInsight)
            .where(*filters)
            .order_by(ReviewInsight.review_updated_at.desc())
            .limit(MAX_REVIEWS)
        )
    ).scalars().all()
    out = []
    for r in rows:
        out.append({
            "rating": r.rating,
            "text": r.review_text or "",
            "reviewer": r.reviewer_name or "Customer",
            "date": r.review_updated_at.date().isoformat() if r.review_updated_at else "",
            "sentiment": r.sentiment,
            "topics": [t.get("name") for t in (r.topics or []) if isinstance(t, dict) and t.get("name")],
            "replied": r.replied,
        })
    return out


def _verified_stats(rows: list[dict]) -> dict:
    total = len(rows)
    dist = {s: sum(1 for r in rows if r["rating"] == s) for s in (5, 4, 3, 2, 1)}
    avg = round(sum(r["rating"] for r in rows) / total, 2) if total else 0.0
    pos = sum(1 for r in rows if r["rating"] >= 4)
    neu = sum(1 for r in rows if r["rating"] == 3)
    neg = sum(1 for r in rows if r["rating"] <= 2)
    replied = sum(1 for r in rows if r["replied"])
    return {
        "total": total,
        "avg_rating": avg,
        "distribution": dist,
        "positive": pos,
        "neutral": neu,
        "negative": neg,
        "replied": replied,
        "unanswered": total - replied,
        "response_rate": round((replied / total) * 100) if total else 0,
    }


def _overview_query(rows: list[dict]) -> str:
    """Query formulation for the business-overview evidence need.

    Top review-topic words focus retrieval on what customers actually talk
    about. This is just a query string — storage access lives in the
    Retrieval Layer.
    """
    words: dict[str, int] = {}
    for r in rows:
        for w in re.findall(r"[a-z]{5,}", (r["text"] or "").lower()):
            if w not in STOPWORDS:
                words[w] = words.get(w, 0) + 1
    keywords = sorted(words, key=words.get, reverse=True)[:8]
    base = "business description products services offered"
    return f"{base} {' '.join(keywords)}".strip()


# ── LLM call + strict parsing ───────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_ai_json(text: str) -> AIIntelligence:
    return AIIntelligence.model_validate(json.loads(_strip_fences(text)))


async def _competitive_facts(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int, stats: dict
) -> dict:
    """Comparison inputs for the LLM's competitive section.

    The cohort is the anonymised set of other tenants on the platform in the
    same interval — NOT named competitors (no competitor tracking exists yet).
    Returns {} when there is nothing comparable, so the model is told to stay
    silent rather than to speculate.
    """
    try:
        from sqlalchemy import case, func

        from ..channels.models import Channel

        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        filters = [ReviewInsight.user_id != user_id,
                   ReviewInsight.review_updated_at.is_not(None),
                   ReviewInsight.review_updated_at >= since]
        if channel_id:
            # Same-category peers only when the caller scopes to one location.
            cat = select(ReviewInsight.channel_id).where(
                ReviewInsight.user_id == user_id,
                ReviewInsight.channel_id == channel_id,
            ).scalar_subquery()
            filters.append(ReviewInsight.channel_id.in_(select(Channel.id).where(Channel.user_id.in_(
                select(func.distinct(ReviewInsight.user_id)).where(
                    ReviewInsight.channel_id.in_(cat)
                )
            ))))
        row = (await db.execute(
            select(
                func.avg(ReviewInsight.rating),
                func.count(),
                func.avg(case((ReviewInsight.replied.is_(True), 1.0), else_=0.0)),
            ).where(*filters)
        )).one()
        cohort_avg, cohort_n, cohort_reply = float(row[0] or 0), int(row[1] or 0), row[2]
    except Exception as e:
        logger.debug("Cohort comparison unavailable: %s", e)
        return {}
    if cohort_n < 3 or not cohort_avg or not stats.get("total"):
        return {}

    facts: dict = {
        "scope": "other businesses on Sayvors (anonymised cohort)",
        "interval_days": days,
        "my_avg_rating": stats.get("avg_rating"),
        "my_response_rate": stats.get("response_rate"),
        "cohort_avg_rating": round(cohort_avg, 2),
        "cohort_reviews": cohort_n,
        "cohort_response_rate": round((cohort_reply or 0) * 100, 1),
    }
    return facts


async def _call_llm(facts: dict, rag_text: str, model: str, tenant_id: str | None = None) -> tuple[str, str]:
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    user_content = json.dumps({
        "total_reviews": facts["stats"]["total"],
        "verified_avg": facts["stats"]["avg_rating"],
        "rating_distribution": facts["stats"]["distribution"],
        "reviews": facts["reviews"],
        "business_context": rag_text or "(no databank content available)",
        "competitive_facts": facts.get("competitive") or
            "unavailable — return empty wins and gaps",
    })
    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)
    resp = await provider.complete(
        LLMRequest(
            model=api_model,
            messages=[LLMMessage(role="user", content=user_content)],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=1500,
            stream=False,
            tenant_id=tenant_id,
            model_id=model,
            purpose="analytics.intelligence",
        )
    )
    return resp.content, model


def _verify_dimensions(
    parsed: list[AIDimension], stats: dict, heuristic: list[dict]
) -> list[dict]:
    """Clamp dimension claims against verified stats and the heuristic count.

    The LLM is good at verdicts and quotes, unreliable at counts. Anything the
    deterministic classifier counted is authoritative for `mentions`; a
    dimension the reviews do not actually support is dropped rather than shown
    as a hallucinated insight.
    """
    total = stats["total"]
    from .dimensions import DIMENSION_BY_KEY

    truth = {d["key"]: d for d in heuristic}
    out: list[dict] = []
    for d in parsed:
        key = d.key.strip().lower()
        if key in truth:
            real = truth[key]
            label = real["label"]
            mentions = real["mentions"]
            positive = min(real["positive"], total)
            negative = min(real["negative"], total)
            avg = real["avg_rating"]
            verdict = d.verdict
            standard = True
            evidence = [e.model_dump() for e in d.evidence][:3]
        else:
            # Discovered dimension: trust the model only if it cites evidence.
            evidence = [e.model_dump() for e in d.evidence][:3]
            if not d.standard or not evidence:
                continue
            label = d.label
            mentions = min(d.mentions, total)
            if mentions <= 0:
                continue
            positive = min(d.positive, mentions)
            negative = min(d.negative, mentions - positive if mentions - positive >= 0 else 0)
            avg = max(1.0, min(5.0, round(d.avg_rating, 1)))
            verdict = d.verdict
            standard = False
        judged = positive + negative
        pct = round((positive / judged) * 100) if judged else 0
        out.append({
            "key": key,
            "label": label,
            "standard": standard,
            "mentions": mentions,
            "positive": positive,
            "negative": negative,
            "avg_rating": avg,
            "positive_pct": pct,
            "signal": "strong" if pct >= 70 else "weak" if pct <= 30 else "mixed",
            "confidence": "high" if mentions >= 5 else "medium" if mentions >= 3 else "low",
            "verdict": verdict,
            "evidence": evidence,
        })
    # Standard set first in its canonical order, then discoveries by weight.
    order = list(DIMENSION_BY_KEY)
    out.sort(key=lambda d: (order.index(d["key"]) if d["key"] in order else 99, -d["mentions"]))
    return out


def _verify(parsed: AIIntelligence, stats: dict) -> AIIntelligence:
    """Clamp the AI payload against verified stats. Numbers never lie."""
    total = stats["total"]
    themes = [t for t in parsed.themes if t.mentions > 0][:8]
    for t in themes:
        t.mentions = min(t.mentions, total)
        t.avg_rating = max(1.0, min(5.0, round(t.avg_rating, 1)))
        t.positive_pct = max(0, min(100, t.positive_pct))
        t.phrases = [str(p)[:120] for p in t.phrases[:3]]
    strengths = parsed.strengths[:4]
    for s in strengths:
        s.mentions = min(s.mentions, total)
        s.avg = max(1.0, min(5.0, round(s.avg, 1)))
    return AIIntelligence(
        summary=parsed.summary,
        themes=themes,
        opportunities=parsed.opportunities[:4],
        strengths=strengths,
        actions=parsed.actions[:5],
    )


# ── Deterministic fallback (honest, data-grounded) ──────────────

def _fallback_from_rows(rows: list[dict]) -> AIIntelligence:
    """Deterministic scorecard over the standard business dimensions.

    Same discipline as the AI path: every number comes from the rows. Themes
    used to be raw word-frequency (`version`, `things`, `really`) filtered by a
    thin stopword list, which surfaced as meaningless "insights" to owners.
    Now it scores the fixed dimension set, and a dimension nobody mentioned is
    simply absent.
    """
    dims = score_dimensions(rows)
    total = len(rows)
    unanswered = sum(1 for r in rows if not r["replied"])
    themes = [
        AITheme(
            name=d["label"],
            mentions=d["mentions"],
            avg_rating=d["avg_rating"],
            positive_pct=d["positive_pct"],
            phrases=[e["quote"][:60] for e in d["evidence"][:2]],
            trend="stable",
        )
        for d in dims
    ][:8]
    return AIIntelligence(
        summary=(
            "Automatic analysis is offline — showing a deterministic breakdown "
            f"of your {total} review(s) across the standard business dimensions instead."
            if total else "No reviews analyzed yet."
        ),
        themes=themes,
        opportunities=[],
        strengths=[
            AIStrength(title=d["label"], mentions=d["mentions"], avg=d["avg_rating"])
            for d in dims if d["positive"] > d["negative"]
        ][:3],
        actions=(
            [AIAction(title=f"Respond to {unanswered} unanswered review(s)", detail="Immediate action")]
            if unanswered else []
        ),
        dimensions=[],
        competitive=AICompetitive(),
    )


# ── Public entry point ──────────────────────────────────────────

async def get_review_intelligence(
    db: AsyncSession,
    user,
    channel_id: str | None = None,
    days: int = 90,
    databank_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    rows = await _load_reviews(db, user.id, channel_id, days, date_from, date_to)
    stats = _verified_stats(rows)

    # Business overview comes from the Retrieval Layer — one need, all
    # mechanisms, minimized facts. No agent call, no SQL here, no fallback
    # to arbitrary chunks: empty means honestly empty.
    rag_text, rag_chunks, rag_bank = "", 0, databank_id
    try:
        from ..retrieval.evidence import EvidenceNeed
        from ..retrieval.layer import retrieve_evidence

        res = await retrieve_evidence(
            [EvidenceNeed(kind="business_overview", query=_overview_query(rows))],
            tenant_id=user.id, db=db, bank_id=databank_id,
        )
        overview = res.get("business_overview")
        if overview and overview.has_data:
            rag_text = overview.rendered[:MAX_RAG_CHARS]
            rag_chunks = len(overview.items)
    except Exception as e:
        logger.debug("Retrieval Layer overview unavailable: %s", e)

    facts = {"stats": stats, "reviews": rows}
    heuristic_dims = score_dimensions(rows)
    competitive = await _competitive_facts(db, user.id, channel_id, days or 90, stats)
    facts["competitive"] = competitive
    last_error = "no LLM provider configured"
    for model in MODELS_CHAIN:
        try:
            raw, used = await _call_llm(facts, rag_text, model, user.id)
            try:
                parsed = _parse_ai_json(raw)
            except Exception as e:
                # Retry once, echoing the contract violation.
                raw, used = await _call_llm_retry(facts, rag_text, model, str(e), user.id)
                parsed = _parse_ai_json(raw)
            verified = _verify(parsed, stats)
            return {
                "source": "ai",
                "model": used,
                "stats": stats,
                "summary": verified.summary,
                "themes": [t.model_dump() for t in verified.themes],
                "opportunities": [o.model_dump() for o in verified.opportunities],
                "strengths": [s.model_dump() for s in verified.strengths],
                "actions": [a.model_dump() for a in verified.actions],
                "dimensions": _verify_dimensions(verified.dimensions, stats, heuristic_dims),
                "competitive": {
                    "wins": [w[:200] for w in verified.competitive.wins[:4]],
                    "gaps": [g[:200] for g in verified.competitive.gaps[:4]],
                    "scope": competitive.get("scope") if competitive else None,
                } if competitive else {"wins": [], "gaps": [], "scope": None},
                "rag_used": bool(rag_text),
                "rag_chunks": rag_chunks,
                "rag_bank": rag_bank,
            }
        except Exception as e:
            last_error = f"{model}: {type(e).__name__}: {str(e)[:160]}"
            logger.debug("Intelligence LLM attempt failed (%s)", last_error)
            continue  # next model in chain
    logger.info("Review intelligence using deterministic fallback: %s", last_error)
    fb = _verify(_fallback_from_rows(rows), stats)
    return {
        "source": "fallback",
        "model": None,
        "stats": stats,
        "summary": fb.summary,
        "themes": [t.model_dump() for t in fb.themes],
        "opportunities": [o.model_dump() for o in fb.opportunities],
        "strengths": [s.model_dump() for s in fb.strengths],
        "actions": [a.model_dump() for a in fb.actions],
        "dimensions": heuristic_dims,
        "competitive": {"wins": [], "gaps": [], "scope": None},
        "rag_used": bool(rag_text),
        "rag_chunks": rag_chunks,
        "rag_bank": rag_bank,
        "fallback_reason": last_error,
    }


async def _call_llm_retry(facts: dict, rag_text: str, model: str, error: str, tenant_id: str | None = None) -> tuple[str, str]:
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)
    resp = await provider.complete(
        LLMRequest(
            model=api_model,
            messages=[LLMMessage(
                role="user",
                content=json.dumps({"total_reviews": facts["stats"]["total"], "reviews": facts["reviews"]})
                + f"\nYour previous output failed validation ({error}). Output ONLY the valid JSON object, nothing else.",
            )],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=1500,
            stream=False,
            tenant_id=tenant_id,
            model_id=model,
            purpose="analytics.intelligence",
        )
    )
    return resp.content, model


# ── Stored reports (analyze once, serve many) ───────────────────

def _scope(channel_id: str | None) -> str:
    return channel_id or ""


def _scope_key(
    days: int | None, date_from: datetime | None, date_to: datetime | None
) -> str:
    """Cache slot for an analysis interval.

    Presets (rolling windows) keep the existing integer `days` column so every
    already-stored report stays reachable. An explicit month range gets its own
    slot keyed by the exact dates, so re-selecting September serves the cached
    September report instead of re-billing the LLM.
    """
    if date_from or date_to:
        f = date_from.date().isoformat() if date_from else "start"
        t = date_to.date().isoformat() if date_to else "now"
        return f"{f}..{t}"
    return str(int(days or 90))


def _report_to_dict(report, current_count: int, scope_key: str = "") -> dict:
    stats = dict(report.stats or {})
    return {
        "source": report.source,
        "model": report.model,
        "scope_key": scope_key or (report.scope_key or str(report.days or 90)),
        "stats": stats,
        "summary": report.summary,
        "themes": list(report.themes or []),
        "opportunities": list(report.opportunities or []),
        "strengths": list(report.strengths or []),
        "actions": list(report.actions or []),
        "dimensions": list(report.dimensions or []),
        "competitive": dict(report.competitive or {}),
        "rag_used": report.rag_used,
        "rag_chunks": report.rag_chunks,
        "rag_bank": report.rag_bank,
        "fallback_reason": report.fallback_reason,
        "analyzed_at": report.updated_at.isoformat() if report.updated_at else None,
        "review_count": report.review_count,
        "current_count": current_count,
        "stale": current_count != (report.review_count or 0),
    }


async def _current_review_count(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    """How many reviews the interval holds *now* — the staleness signal.

    Scoped to the same interval as the stored report, so "2 new reviews" means
    2 new reviews in the window the owner is looking at, not all-time.
    """
    from sqlalchemy import func

    from .models import ReviewInsight

    filters = [ReviewInsight.user_id == user_id]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
    if date_from is not None:
        filters.append(ReviewInsight.review_updated_at >= date_from)
    if date_to is not None:
        filters.append(ReviewInsight.review_updated_at < date_to)
    return (
        await db.execute(select(func.count()).select_from(ReviewInsight).where(*filters))
    ).scalar() or 0


async def get_stored_report(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None,
    days: int = 90,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict | None:
    """Return the stored analysis for an interval, with staleness info.

    Returns None when this interval has never been analyzed — the UI then shows
    the instant heuristic view until the owner presses Analyze.
    """
    from .models import ReviewIntelligenceReport

    key = _scope_key(days, date_from, date_to)
    result = await db.execute(
        select(ReviewIntelligenceReport).where(
            ReviewIntelligenceReport.user_id == user_id,
            ReviewIntelligenceReport.channel_id == _scope(channel_id),
            ReviewIntelligenceReport.scope_key == key,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        return None
    current = await _current_review_count(db, user_id, channel_id, date_from, date_to)
    return _report_to_dict(report, current, key)


async def analyze_and_store(
    db: AsyncSession,
    user,
    channel_id: str | None = None,
    days: int = 90,
    databank_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Run the full pipeline for an interval and upsert the stored report."""
    import uuid

    from .models import ReviewIntelligenceReport

    result = await get_review_intelligence(
        db, user, channel_id, days, databank_id, date_from, date_to
    )
    scope = _scope(channel_id)
    key = _scope_key(days, date_from, date_to)
    window_days = 0 if (date_from or date_to) else int(days or 90)
    existing = await db.execute(
        select(ReviewIntelligenceReport).where(
            ReviewIntelligenceReport.user_id == user.id,
            ReviewIntelligenceReport.channel_id == scope,
            ReviewIntelligenceReport.scope_key == key,
        )
    )
    report = existing.scalar_one_or_none()
    if report is None:
        report = ReviewIntelligenceReport(
            id=str(uuid.uuid4()),
            user_id=user.id,
            channel_id=scope,
            days=window_days,
            scope_key=key,
        )
        db.add(report)
    report.source = result["source"]
    report.model = result["model"]
    report.summary = result["summary"]
    report.themes = result["themes"]
    report.opportunities = result["opportunities"]
    report.strengths = result["strengths"]
    report.actions = result["actions"]
    report.stats = result["stats"]
    report.dimensions = result.get("dimensions") or []
    report.competitive = result.get("competitive") or {}
    report.rag_used = result["rag_used"]
    report.rag_chunks = result["rag_chunks"]
    report.rag_bank = result["rag_bank"]
    report.fallback_reason = result.get("fallback_reason")
    report.review_count = result["stats"]["total"]
    await db.commit()
    await db.refresh(report)
    current = await _current_review_count(
        db, user.id, channel_id, date_from, date_to
    )
    return _report_to_dict(report, current, key)
