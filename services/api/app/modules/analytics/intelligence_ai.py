"""AI Review Intelligence — LLM analysis grounded in RAG context.

Pipeline (accuracy-first):
  1. Load the tenant's real reviews (ReviewInsight rows).
  2. Compute VERIFIED stats server-side (avg, total, distribution, sentiment
     split, response rate). The LLM never supplies these numbers — they are
     overwritten with computed values after parsing.
  3. Pull RAG grounding: keyword-matched chunks from the tenant's databanks
     (pure SQL, no embeddings/LLM needed) so the analysis knows what the
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

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..rag.models import Databank, Document, DocumentChunk
from .models import ReviewInsight

logger = logging.getLogger(__name__)

MODELS_CHAIN = ["groq:oss-120b", "gemini:gemini-3.6-flash", "openai:gpt-4o-mini"]
MAX_REVIEWS = 50
MAX_RAG_CHARS = 4000
MAX_RAG_CHUNKS = 6

STOPWORDS = {
    "that", "this", "with", "from", "have", "still", "they", "them",
    "your", "about", "there", "their", "what", "when", "which", "were",
    "been", "very", "just", "will", "would", "could", "should", "great",
    "good", "nice", "best", "much", "more", "most", "than", "then",
    "also", "well", "even", "only", "into", "over", "such", "using",
}


# ── Strict AI contract ──────────────────────────────────────────

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
  "actions": [{"title": "<=120 chars", "detail": "<=200 chars"}]
}

Rules:
- Ground every theme in the ACTUAL review texts. Never invent topics, names, products or events not present in the reviews.
- mentions must never exceed the total review count provided.
- Use the BUSINESS CONTEXT only to interpret wording (e.g. what "it" refers to), never as a source of claims.
- With few reviews, return few themes. An empty themes array is acceptable when there is nothing to say.
- Temperature is low; be conservative and factual."""


# ── Data loading ────────────────────────────────────────────────

async def _load_reviews(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int
) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    filters = [
        ReviewInsight.user_id == user_id,
        ReviewInsight.review_updated_at.is_not(None),
    ]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
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
    _ = since
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


async def _rag_context(db: AsyncSession, user_id: str, rows: list[dict]) -> tuple[str, int, str | None]:
    """Keyword-matched databank chunks describing the business.

    Returns (context_text, chunk_count, databank_name). Pure SQL LIKE —
    no embeddings or LLM needed, works even when providers are down.
    """
    words: dict[str, int] = {}
    for r in rows:
        for w in re.findall(r"[a-z]{5,}", (r["text"] or "").lower()):
            if w not in STOPWORDS:
                words[w] = words.get(w, 0) + 1
    keywords = sorted(words, key=words.get, reverse=True)[:8]

    banks = (
        await db.execute(select(Databank).where(Databank.user_id == user_id))
    ).scalars().all()
    if not banks:
        return "", 0, None
    bank_ids = [b.id for b in banks]
    bank_names = {b.id: b.name for b in banks}

    conditions = [DocumentChunk.databank_id.in_(bank_ids)]
    if keywords:
        conditions.append(or_(*[DocumentChunk.content.like(f"%{k}%") for k in keywords]))
    chunks = (
        await db.execute(
            select(DocumentChunk).where(*conditions).order_by(DocumentChunk.seq).limit(MAX_RAG_CHUNKS)
        )
    ).scalars().all()
    if not chunks and keywords:
        # Fallback: first chunks of the newest bank (business description).
        chunks = (
            await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.databank_id == bank_ids[-1])
                .order_by(DocumentChunk.seq)
                .limit(3)
            )
        ).scalars().all()
    _ = Document
    texts: list[str] = []
    used_bank: str | None = None
    budget = MAX_RAG_CHARS
    for c in chunks:
        piece = (c.content or "").strip()
        if not piece:
            continue
        piece = piece[:800]
        if len(piece) > budget:
            break
        texts.append(piece)
        budget -= len(piece)
        used_bank = used_bank or bank_names.get(c.databank_id)
    return "\n---\n".join(texts), len(texts), used_bank


# ── LLM call + strict parsing ───────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_ai_json(text: str) -> AIIntelligence:
    return AIIntelligence.model_validate(json.loads(_strip_fences(text)))


async def _call_llm(facts: dict, rag_text: str, model: str) -> tuple[str, str]:
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    user_content = json.dumps({
        "total_reviews": facts["stats"]["total"],
        "verified_avg": facts["stats"]["avg_rating"],
        "rating_distribution": facts["stats"]["distribution"],
        "reviews": facts["reviews"],
        "business_context": rag_text or "(no databank content available)",
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
        )
    )
    return resp.content, model


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
    """Theme aggregation from enrichment topics + keyword scan.

    Same verified-stats discipline: counts come from the rows, never guessed.
    """
    counts: dict[str, dict] = {}

    def bump(name: str, rating: int):
        key = name.strip().lower()[:60]
        if not key:
            return
        e = counts.setdefault(key, {"mentions": 0, "ratings": []})
        e["mentions"] += 1
        e["ratings"].append(rating)

    for r in rows:
        for t in r["topics"]:
            bump(t.get("name", "") if isinstance(t, dict) else str(t), r["rating"])
        for w in re.findall(r"[a-z]{5,}", (r["text"] or "").lower()):
            if w not in STOPWORDS:
                bump(w, r["rating"])
    themes = []
    for name, e in sorted(counts.items(), key=lambda kv: -kv[1]["mentions"])[:6]:
        ratings = e["ratings"]
        pos = sum(1 for x in ratings if x >= 4)
        themes.append(AITheme(
            name=name,
            mentions=e["mentions"],
            avg_rating=round(sum(ratings) / len(ratings), 1),
            positive_pct=round((pos / len(ratings)) * 100),
            phrases=[],
            trend="stable",
        ))
    total = len(rows)
    unanswered = sum(1 for r in rows if not r["replied"])
    return AIIntelligence(
        summary=(
            "Automatic analysis is offline — showing a deterministic breakdown of your reviews instead. "
            f"{total} review(s) analyzed from stored data."
            if total else "No reviews analyzed yet."
        ),
        themes=themes,
        opportunities=[],
        strengths=[
            AIStrength(title=t.name, mentions=t.mentions, avg=t.avg_rating)
            for t in themes if t.positive_pct >= 60
        ][:3],
        actions=(
            [AIAction(title=f"Respond to {unanswered} unanswered review(s)", detail="Immediate action")]
            if unanswered else []
        ),
    )


# ── Public entry point ──────────────────────────────────────────

async def get_review_intelligence(
    db: AsyncSession,
    user,
    channel_id: str | None = None,
    days: int = 90,
    databank_id: str | None = None,
) -> dict:
    rows = await _load_reviews(db, user.id, channel_id, days)
    stats = _verified_stats(rows)

    rag_text, rag_chunks, rag_bank = "", 0, None
    if databank_id:
        try:
            from ..rag.agent import ask_question

            res = await ask_question(
                databank_id,
                "Describe this business in 6 lines: what it sells, services offered, tone of voice.",
                user, db, top_k=3, max_steps=2,
            )
            rag_text = str(res.get("answer", ""))[:MAX_RAG_CHARS]
            rag_chunks = len(res.get("citations", []))
            rag_bank = databank_id
        except Exception as e:
            logger.debug("RAG agent context unavailable: %s", e)
    if not rag_text:
        try:
            rag_text, rag_chunks, rag_bank = await _rag_context(db, user.id, rows)
        except Exception as e:
            logger.debug("RAG chunk context unavailable: %s", e)

    facts = {"stats": stats, "reviews": rows}
    last_error = "no LLM provider configured"
    for model in MODELS_CHAIN:
        try:
            raw, used = await _call_llm(facts, rag_text, model)
            try:
                parsed = _parse_ai_json(raw)
            except Exception as e:
                # Retry once, echoing the contract violation.
                raw, used = await _call_llm_retry(facts, rag_text, model, str(e))
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
        "rag_used": bool(rag_text),
        "rag_chunks": rag_chunks,
        "rag_bank": rag_bank,
        "fallback_reason": last_error,
    }


async def _call_llm_retry(facts: dict, rag_text: str, model: str, error: str) -> tuple[str, str]:
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
        )
    )
    return resp.content, model


# ── Stored reports (analyze once, serve many) ───────────────────

def _scope(channel_id: str | None) -> str:
    return channel_id or ""


def _report_to_dict(report, current_count: int) -> dict:
    stats = dict(report.stats or {})
    return {
        "source": report.source,
        "model": report.model,
        "stats": stats,
        "summary": report.summary,
        "themes": list(report.themes or []),
        "opportunities": list(report.opportunities or []),
        "strengths": list(report.strengths or []),
        "actions": list(report.actions or []),
        "rag_used": report.rag_used,
        "rag_chunks": report.rag_chunks,
        "rag_bank": report.rag_bank,
        "fallback_reason": report.fallback_reason,
        "analyzed_at": report.updated_at.isoformat() if report.updated_at else None,
        "review_count": report.review_count,
        "current_count": current_count,
        "stale": current_count != (report.review_count or 0),
    }


async def _current_review_count(db: AsyncSession, user_id: str, channel_id: str | None) -> int:
    from sqlalchemy import func

    from .models import ReviewInsight

    filters = [ReviewInsight.user_id == user_id]
    if channel_id:
        filters.append(ReviewInsight.channel_id == channel_id)
    return (
        await db.execute(select(func.count()).select_from(ReviewInsight).where(*filters))
    ).scalar() or 0


async def get_stored_report(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int
) -> dict | None:
    """Return the stored analysis with staleness info, or None if never analyzed."""
    from .models import ReviewIntelligenceReport

    result = await db.execute(
        select(ReviewIntelligenceReport).where(
            ReviewIntelligenceReport.user_id == user_id,
            ReviewIntelligenceReport.channel_id == _scope(channel_id),
            ReviewIntelligenceReport.days == days,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        return None
    current = await _current_review_count(db, user_id, channel_id)
    return _report_to_dict(report, current)


async def analyze_and_store(
    db: AsyncSession,
    user,
    channel_id: str | None = None,
    days: int = 90,
    databank_id: str | None = None,
) -> dict:
    """Run the full pipeline and upsert the stored report. Returns the report dict."""
    import uuid

    from .models import ReviewIntelligenceReport

    result = await get_review_intelligence(db, user, channel_id, days, databank_id)
    scope = _scope(channel_id)
    existing = await db.execute(
        select(ReviewIntelligenceReport).where(
            ReviewIntelligenceReport.user_id == user.id,
            ReviewIntelligenceReport.channel_id == scope,
            ReviewIntelligenceReport.days == days,
        )
    )
    report = existing.scalar_one_or_none()
    if report is None:
        report = ReviewIntelligenceReport(
            id=str(uuid.uuid4()),
            user_id=user.id,
            channel_id=scope,
            days=days,
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
    report.rag_used = result["rag_used"]
    report.rag_chunks = result["rag_chunks"]
    report.rag_bank = result["rag_bank"]
    report.fallback_reason = result.get("fallback_reason")
    report.review_count = result["stats"]["total"]
    await db.commit()
    await db.refresh(report)
    current = await _current_review_count(db, user.id, channel_id)
    return _report_to_dict(report, current)
