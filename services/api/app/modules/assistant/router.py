"""Ask Sayvors: chat endpoint grounding answers in live business data.

Context layers, cheapest first:
  1. Structured snapshot — Localith profile, review stats, attention counts,
     reply activity (today / last 7 days).
  2. Agentic RAG over the tenant's Databank (documents + live connected
     databases) via rag.agent.ask_question — reasoned by the tenant's own
     configured model, and degraded gracefully when no Databank exists or
     no usable model is enabled.
  3. LLM synthesis merges both layers with the conversation history.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.deps import get_current_user, get_db
from ..auth.rate_limit import rate_limit
from ..analytics.models import ReviewInsight
from ..channels.models import AutoReplyConfig, Channel, ReviewReply
from ..users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

MAX_HISTORY = 12


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class AssistantChatResponse(BaseModel):
    reply: str
    grounded_in_rag: bool = False
    citations: list[dict] = Field(default_factory=list)
    model: str


async def _resolve_model(db: AsyncSession, user_id: str) -> str:
    """Tenant's configured reply model when still enabled, else the
    tenant's first enabled model. Raises when nothing is enabled — no
    hardcoded default, the database is the only source of truth."""
    from ..llm.service import resolve_tenant_model

    cfg = (
        await db.execute(
            select(AutoReplyConfig.model)
            .join(Channel, Channel.id == AutoReplyConfig.channel_id)
            .where(Channel.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return await resolve_tenant_model(db, preferred=cfg)


MAX_LISTED_ITEMS = 200

# How many individual reviews/replies travel in the prompt. Totals always
# reflect the whole database (reviews_indexed, replies_posted_total); this
# only caps the verbatim rows. It is the single biggest lever on time-to-
# first-token: full review + reply text is expensive to prefill, and an
# aggregate question ("how many reviews?") never reads it.
DETAIL_LIMIT = 20

# Rapid-fire questions in the same conversation rebuild an identical
# snapshot. Reuse it briefly instead of re-running a dozen aggregate
# queries per message.
SNAPSHOT_TTL_SECONDS = 30


def _iso(dt) -> str | None:
    try:
        return dt.isoformat(timespec="minutes") if dt else None
    except Exception:
        return None


async def _business_snapshot(db: AsyncSession, user: User, limit: int = DETAIL_LIMIT) -> dict:
    """Complete live facts: every location, every review, every reply.

    Aggregate counts always reflect the full database; `all_reviews` /
    `all_replies` carry the `limit` most recent rows verbatim and
    `truncated` tells the model when the visible list is partial — so it can
    say "I can't see it" instead of inventing reviews, users, dates, or
    reply text.
    """
    from ..localith.models import LocalithConnection

    owner_name = " ".join(
        p for p in [user.first_name, user.last_name] if p
    ).strip() or None

    conns = (
        await db.execute(
            select(LocalithConnection).where(LocalithConnection.user_id == user.id)
        )
    ).scalars().all()
    locations = [
        {
            "name": c.listing_name,
            "address": c.address,
            "phone": c.phone_number,
            "website": c.website_url,
            "maps_url": c.maps_url,
            "verified": c.is_verified,
            "total_reviews_on_google": c.total_reviews,
            "average_rating_on_google": c.average_rating,
            "last_review_on": _iso(c.last_review_on),
            "last_reply_on": _iso(c.last_reply_on),
        }
        for c in conns
    ]

    channels = (
        await db.execute(
            select(Channel).where(Channel.user_id == user.id)
        )
    ).scalars().all()
    channel_ids = [c.id for c in channels]
    channel_names = {c.id: (c.display_name or c.id) for c in channels}

    business: dict = {
        "owner": {"name": owner_name, "email": user.email},
        "locations": locations,
        "channels": [
            {"name": c.display_name, "platform": c.platform, "status": c.status}
            for c in channels
        ],
    }
    visibility: dict = {}
    for c in conns:
        raw = c.raw_metrics_json or {}
        listings = raw.get("listings") if isinstance(raw, dict) else None
        if not listings:
            continue
        window = (raw.get("dateRange") or {}) if isinstance(raw, dict) else {}
        for listing in listings:
            search_imp = int(listing.get("googleSearchDesktop", 0) or 0) + int(
                listing.get("googleSearchMobile", 0) or 0)
            maps_imp = int(listing.get("googleMapsDesktop", 0) or 0) + int(
                listing.get("googleMapsMobile", 0) or 0)
            visibility[c.listing_name or c.listing_id] = {
                "window": f"{window.get('startDate')} to {window.get('endDate')}",
                "found_via_google_search": search_imp,
                "found_via_google_maps": maps_imp,
                "direction_requests": int(listing.get("directions", 0) or 0),
                "call_clicks": int(listing.get("callClicks", 0) or 0),
                "website_clicks": int(listing.get("websiteClicks", 0) or 0),
                "messages": int(listing.get("messages", 0) or 0),
                "bookings": int(listing.get("bookings", 0) or 0),
                "review_response_percentage": listing.get("reviewResponsePercentage"),
            }
    stats: dict = {
        "connected_locations": [c.display_name or c.id for c in channels if c.status == "active"],
        "visibility": visibility,
    }
    if channel_ids:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        total = (
            await db.execute(
                select(func.count(ReviewInsight.id)).where(
                    ReviewInsight.channel_id.in_(channel_ids)
                )
            )
        ).scalar_one()
        avg = (
            await db.execute(
                select(func.avg(ReviewInsight.rating)).where(
                    ReviewInsight.channel_id.in_(channel_ids)
                )
            )
        ).scalar_one()
        dist_rows = (
            await db.execute(
                select(ReviewInsight.rating, func.count(ReviewInsight.id))
                .where(ReviewInsight.channel_id.in_(channel_ids))
                .group_by(ReviewInsight.rating)
            )
        ).all()
        async def _posted_count(since: datetime | None) -> int:
            stmt = select(func.count(ReviewReply.id)).where(
                ReviewReply.channel_id.in_(channel_ids),
                ReviewReply.status == "posted",
            )
            if since is not None:
                stmt = stmt.where(ReviewReply.created_at >= since)
            return (await db.execute(stmt)).scalar_one()

        posted_total = await _posted_count(None)
        posted_today = await _posted_count(today_start)
        posted_week = await _posted_count(week_start)
        pending = (
            await db.execute(
                select(func.count(ReviewReply.id)).where(
                    ReviewReply.channel_id.in_(channel_ids),
                    ReviewReply.status == "pending_approval",
                )
            )
        ).scalar_one()
        failed = (
            await db.execute(
                select(func.count(ReviewReply.id)).where(
                    ReviewReply.channel_id.in_(channel_ids),
                    ReviewReply.status == "failed",
                )
            )
        ).scalar_one()
        all_reviews = (
            await db.execute(
                select(ReviewInsight)
                .where(ReviewInsight.channel_id.in_(channel_ids))
                .order_by(ReviewInsight.review_updated_at.desc().nullslast())
                .limit(limit)
            )
        ).scalars().all()
        all_replies = (
            await db.execute(
                select(ReviewReply)
                .where(ReviewReply.channel_id.in_(channel_ids))
                .order_by(ReviewReply.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        stats.update({
            "reviews_indexed": total,
            "average_rating": round(float(avg), 2) if avg is not None else None,
            "rating_distribution": {str(r): n for r, n in dist_rows},
            "replies_posted_total": posted_total,
            "replies_posted_today_utc": posted_today,
            "replies_posted_last_7_days_utc": posted_week,
            "replies_pending_approval": pending,
            "replies_failed": failed,
            "all_reviews": [
                {
                    "location": channel_names.get(r.channel_id),
                    "reviewer": r.reviewer_name,
                    "rating": r.rating,
                    "text": r.review_text or "(star rating only)",
                    "sentiment": r.sentiment,
                    "topics": r.topics or [],
                    "products": r.products or [],
                    "problems": r.problems or [],
                    "replied": bool(r.replied),
                    "replied_at": _iso(r.replied_at),
                    "review_url": r.review_url,
                    "review_date_utc": _iso(r.review_updated_at),
                    "indexed_at_utc": _iso(r.created_at),
                }
                for r in all_reviews
            ],
            "all_reviews_truncated": total > len(all_reviews),
            "all_replies_listed": len(all_replies),
            "all_replies": [
                {
                    "location": channel_names.get(r.channel_id),
                    "reviewer": r.reviewer_name,
                    "rating": r.rating,
                    # Short preview, not the full review text: that text is
                    # already in all_reviews, and shipping it twice doubled the
                    # prompt for no extra grounding.
                    "review_excerpt": (r.review_text or "")[:120] or "(star rating only)",
                    "reply_text": r.reply_text,
                    "status": r.status,
                    "generation_attempt": r.generation_attempt,
                    "replied_at_utc": _iso(r.created_at),
                    "publish_error": (r.error or "")[:300] if r.status == "failed" else None,
                }
                for r in all_replies
            ],
        })
    return {"business": business, "reviews": stats}


# Snapshot cache: key = user id, value = (monotonic timestamp, snapshot).
# Short TTL so a follow-up question in the same breath skips the aggregate
# queries, while a question asked a minute later still sees fresh numbers.
_snapshot_cache: dict[str, tuple[float, dict]] = {}
_SNAPSHOT_CACHE_MAX = 512


async def _snapshot_for_user(db: AsyncSession, user: User) -> dict:
    now = time.monotonic()
    hit = _snapshot_cache.get(user.id)
    if hit is not None and (now - hit[0]) < SNAPSHOT_TTL_SECONDS:
        return hit[1]
    snapshot = await _business_snapshot(db, user)
    if len(_snapshot_cache) >= _SNAPSHOT_CACHE_MAX:
        _snapshot_cache.clear()
    _snapshot_cache[user.id] = (now, snapshot)
    return snapshot


# ── Context pruning ────────────────────────────────────────────────────────
# "How many reviews do I have?" is answered entirely by the aggregate fields,
# yet it shipped every review and reply body to the model: ~4k tokens of
# prefill (seconds of waiting) to read back a number we already hold. These
# patterns decide when the verbatim rows can be dropped.
#
# Deliberately conservative: an unrecognised question keeps the full detail.
# A false negative only costs latency; a false positive would cost accuracy.
_AGGREGATE_RE = re.compile(
    r"\b(how many|how much|number of|count of|how many times|total|totals|"
    r"average|avg|mean|rating|response rate|reply rate|summary|overview|"
    r"how am i doing|performance|score|breakdown|stats|statistics)\b",
    re.I,
)
_DETAIL_RE = re.compile(
    r"\b(who|whom|whose|which|what did|what was|quote|exact|verbatim|"
    r"complain|complaint|mention|said|says|wrote|write|reply to|respond|"
    r"list all|show all|show me all|read|reads|posted|post|latest|last|"
    r"recent|newest|oldest|earliest|yesterday|today|this week)\b",
    re.I,
)
_LONG_QUESTION_CHARS = 200


def _wants_only_aggregates(message: str) -> bool:
    """True when the question is answerable from the aggregate fields alone."""
    text = (message or "").strip()
    if not text or len(text) > _LONG_QUESTION_CHARS:
        return False
    return bool(_AGGREGATE_RE.search(text)) and not _DETAIL_RE.search(text)


def _prune_snapshot(snapshot: dict, message: str) -> tuple[dict, bool]:
    """Drop the verbatim review/reply rows when the question can't need them.

    Returns the (possibly pruned) snapshot and whether rows were omitted. The
    system prompt tells the model the rows are absent, so it says so instead
    of claiming there is nothing to see.
    """
    if not _wants_only_aggregates(message):
        return snapshot, False
    reviews = snapshot.get("reviews") or {}
    if not (reviews.get("all_reviews") or reviews.get("all_replies")):
        return snapshot, False
    pruned_reviews = {
        k: v for k, v in reviews.items() if k not in ("all_reviews", "all_replies")
    }
    pruned_reviews["detail_rows_omitted"] = True
    return {**snapshot, "reviews": pruned_reviews}, True


async def _rag_answer(
    db: AsyncSession,
    user: User,
    message: str,
    model: str | None = None,
) -> tuple[str, list[dict], bool, str]:
    """Ground the question in the Databank (documents + live DBs). Degrades softly.

    `model` is the tenant's configured model, so retrieval reasons with the
    same model that writes the answer instead of a hardcoded one.

    Returns (answer, citations, grounded, status) where status is one of
    answered | no_results | no_databank | unavailable — the caller puts it in
    the prompt so the model reports the real reason instead of guessing.
    """
    try:
        from ..rag.models import Databank
        from ..rag.agent import ask_question

        bank_id = (
            await db.execute(select(Databank.id).where(Databank.user_id == user.id).limit(1))
        ).scalar_one_or_none()
        if not bank_id:
            return "", [], False, "no_databank"
        result = await ask_question(
            bank_id, message, user, db, top_k=5, max_steps=4, model=model
        )
        answer = (result.get("answer") or "").strip()
        citations = result.get("citations", []) or []
        # The agent returns a fixed "found nothing" line when retrieval came up
        # empty. That is a non-answer: reporting it as grounding would let the
        # final model talk over it with a confident invention.
        from ..rag.agent import NO_EVIDENCE_ANSWER

        if not answer or answer == NO_EVIDENCE_ANSWER:
            return "", citations, False, "no_results"
        return answer, citations, True, "answered"
    except Exception as e:
        logger.warning("Assistant RAG grounding unavailable: %s", e)
        return "", [], False, "unavailable"


def _system_prompt(
    snapshot: dict,
    rag_answer: str,
    rag_citations: list[dict],
    detail_omitted: bool = False,
    rag_status: str = "answered",
) -> str:
    import json

    now = datetime.now(timezone.utc)
    context = json.dumps(
        {**snapshot, "current_time_utc": now.isoformat(timespec="minutes")},
        ensure_ascii=False,
        default=str,
    )
    # The databank block is ALWAYS present, including when retrieval found
    # nothing. Leaving it out made the model assume no databank existed and
    # invent reasons ("I can't see your bank data") for questions the databank
    # was simply empty about.
    if rag_status == "answered":
        rag_block = (
            "\n\nDATABANK GROUNDING (agentic search over the business's stored "
            f"documents and connected databases):\n{rag_answer[:2500]}"
            + (
                "\nSources: " + "; ".join(
                    str(c.get("source") or c.get("title") or c.get("url") or "")
                    for c in rag_citations[:5]
                    if (c.get("source") or c.get("title") or c.get("url"))
                )
                if rag_citations
                else ""
            )
        )
    elif rag_status == "no_results":
        rag_block = (
            "\n\nDATABANK GROUNDING:\nThe business HAS a databank connected and it "
            "was searched for this question, but it returned NO matching documents "
            "or rows. So the answer is not in the databank. Say exactly that: the "
            "databank has nothing about this yet, and the owner can add a file "
            "(CSV/PDF) or connect a database to cover it. Do NOT speculate about "
            "payments, banking, or other systems."
        )
    elif rag_status == "unavailable":
        rag_block = (
            "\n\nDATABANK GROUNDING:\nDatabank search could not run right now (no "
            "usable AI model is configured for it). The databank may still hold "
            "the answer. Say the databank could not be searched at the moment — "
            "do NOT claim you have no access to the business's data, and do NOT "
            "invent other systems (banking, payment processors) as the reason."
        )
    else:  # no_databank
        rag_block = (
            "\n\nDATABANK GROUNDING:\nThis business has NO databank connected yet, "
            "so there are no stored documents or connected databases to search. If "
            "the question is about stored documents, spreadsheets, or connected "
            "databases, say the databank is not connected yet and offer to help "
            "them connect one. Do NOT invent other data sources."
        )
    return (
        "You are Sayvors' business assistant, chatting with the business owner "
        "inside their dashboard.\n\n"
        f"LIVE BUSINESS DATA:\n{context}"
        f"{rag_block}\n\n"
        "Rules:\n"
        + (
            "- This question is about totals, so individual review and reply "
            "text was left out of the context on purpose. Answer from the "
            "aggregate fields. If the owner then asks about a specific review "
            "or reply, say you can pull that detail up next.\n"
            if detail_omitted
            else ""
        ) +
        "- Answer ONLY from the data above. Every location is listed under "
        "business.locations. Reviews appear under reviews.all_reviews and "
        "replies under reviews.all_replies — these are the MOST RECENT ones "
        "(reviewer, rating, full text, sentiment, topics, timestamps).\n"
        "- For totals and counts use the aggregate fields (reviews_indexed, "
        "average_rating, rating_distribution, replies_posted_total, "
        "replies_pending_approval, replies_failed, response rates) — they "
        "cover the whole business, not just the listed rows.\n"
        "- NEVER invent reviewer names, ratings, dates, review text, reply "
        "text, or numbers. If the owner asks about a review, reply, user, or "
        "date that is not in the lists above, say plainly that you cannot "
        "find it in the synced data — do not guess. If all_reviews_truncated "
        "is true, the listed reviews are only the most recent ones, so say "
        "the detail is limited to recent reviews.\n"
        "- When quoting dates, use the timestamps given (review_date_utc, "
        "replied_at_utc). Today is current_time_utc. Present dates and times "
        "in short friendly form (e.g. 'Sept 16, 3:34 PM') — never raw ISO "
        "timestamps, seconds, or +00:00 suffixes.\n"
        "- 'How are people finding us' questions: answer ONLY from "
        "reviews.visibility (found_via_google_search vs found_via_google_maps "
        "impressions, direction requests, call and website clicks, within the "
        "stated window). Never infer a discovery source beyond what those "
        "numbers show.\n"
        "- Be concise (max ~120 words) and concrete; quote real numbers when relevant.\n"
        "- Reply in the same language the owner writes in (Arabic stays Arabic).\n"
        "- If the data does not contain the answer, say so plainly and suggest "
        "what to connect or sync to get it.\n"
        "- Never invent a REASON for not knowing. Only two things exist here: "
        "LIVE BUSINESS DATA and DATABANK GROUNDING. Do not claim you lack "
        "access to banking, payments, orders, or other systems that were never "
        "part of this product. The DATABANK GROUNDING block states exactly what "
        "the databank search did — follow it.\n"
        "- You may give brief, actionable advice about handling reviews."
    )


async def _llm_reply(
    model: str,
    system_prompt: str,
    history: list[ChatMessage],
    message: str,
    user: User,
) -> str:
    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)
    msgs = [
        LLMMessage(role=m.role, content=m.content)
        for m in history[-MAX_HISTORY:]
    ]
    msgs.append(LLMMessage(role="user", content=message))
    resp = await provider.complete(LLMRequest(
        model=api_model,
        messages=msgs,
        system_prompt=system_prompt,
        temperature=0.4,
        max_tokens=500,
        stream=False,
        tenant_id=user.id,
        model_id=model,
        purpose="assistant.chat",
    ))
    return resp.content.strip()


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    body: AssistantChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.TESTING and not await rate_limit(f"assistant:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many messages — wait a moment.")

    snapshot = await _snapshot_for_user(db, user)
    model = await _resolve_model(db, user.id)
    rag_answer, citations, grounded, rag_status = await _rag_answer(db, user, body.message, model)
    prompt_snapshot, detail_omitted = _prune_snapshot(snapshot, body.message)
    system_prompt = _system_prompt(
        prompt_snapshot, rag_answer, citations, detail_omitted, rag_status
    )
    model = await _resolve_model(db, user.id)

    try:
        reply = await _llm_reply(model, system_prompt, body.history, body.message, user)
    except Exception as e:
        logger.warning("Assistant LLM failed (%s); answering from snapshot only", e)
        raise HTTPException(status_code=502, detail=f"Assistant is unavailable right now: {e}")

    if not reply:
        raise HTTPException(status_code=502, detail="Assistant returned an empty reply")
    return AssistantChatResponse(reply=reply, grounded_in_rag=grounded, citations=citations, model=model)


# ── Streaming variant: real progress steps + token-by-token answer ──────────

# Short, human labels for the retrieval tools. The UI shows these verbatim,
# so they stay short — details live in the answer, not the trail.
TOOL_LABELS = {
    "vector_search": "Searching your documents",
    "keyword_search": "Looking up exact terms",
    "read_around": "Reading surrounding text",
    "db_schema": "Inspecting your database",
    "db_query": "Querying your database",
    "get_document": "Opening a document",
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@router.post("/chat/stream")
async def chat_stream(
    body: AssistantChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask Sayvors with live progress + streamed answer.

    Events (SSE `data:` payloads):
      - {"type": "step",  "id": str, "label": str, "detail": str | None}
      - {"type": "delta", "text": str}
      - {"type": "done",  "grounded_in_rag": bool, "citations": [...], "model": str}
      - {"type": "error", "message": str}

    Steps are short and deduped by `id` so a repeated tool call does not
    repeat a row in the UI.
    """
    if not settings.TESTING and not await rate_limit(f"assistant:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many messages — wait a moment.")

    async def event_stream() -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, default=str)}\n\n"

        try:
            # 1. Live business data
            yield sse({"type": "step", "id": "data", "label": "Reading your business data"})
            snapshot = await _snapshot_for_user(db, user)
            reviews_meta = snapshot.get("reviews", {}) or {}
            locations = (snapshot.get("business", {}) or {}).get("locations", []) or []
            n_reviews = int(reviews_meta.get("reviews_indexed") or 0)
            yield sse({
                "type": "step",
                "id": "data",
                "label": "Reading your business data",
                "detail": f"{_plural(len(locations), 'location')} · {_plural(n_reviews, 'review')}",
            })

            # 2. Databank / RAG retrieval (tool calls stream as they happen).
            #    Retrieval reasons with the tenant's own model — the same one
            #    that writes the answer — so databank search works on whatever
            #    provider the tenant actually has.
            from ..rag.models import Databank

            model = await _resolve_model(db, user.id)
            bank_id = (
                await db.execute(
                    select(Databank.id).where(Databank.user_id == user.id).limit(1)
                )
            ).scalar_one_or_none()
            skip_reason: str | None = None
            rag_status = "no_databank"
            if bank_id:
                # Pre-flight: if no configured model can run the retrieval,
                # skip it rather than pay a failed round trip on every message.
                try:
                    from ..rag.agent import _resolve_agent_model

                    await _resolve_agent_model(db, model)
                    rag_status = "answered"  # provisional; refined after search
                except Exception as e:
                    logger.info("Assistant skipping databank search: %s", e)
                    skip_reason = "Databank search unavailable"
                    rag_status = "unavailable"
                    bank_id = None
            else:
                skip_reason = "No databank connected yet"

            rag_answer, citations, grounded = "", [], False
            if bank_id:
                from ..rag.agent import ask_question

                yield sse({"type": "step", "id": "rag", "label": "Searching your databank"})

                # ask_question is a single await, so tool progress is collected
                # into `pending` by a sync callback and drained here while the
                # task runs. Each tool is reported once (deduped by id).
                pending: list[tuple[str, str, str | None]] = []
                seen_tools: set[str] = set()

                def _on_tool(tool: str, info: dict) -> None:
                    if tool in seen_tools:
                        return
                    seen_tools.add(tool)
                    passages = int(info.get("passages") or 0)
                    pending.append((
                        f"rag:{tool}",
                        TOOL_LABELS.get(tool, "Searching your databank"),
                        _plural(passages, "passage") if passages else None,
                    ))

                try:
                    task = asyncio.create_task(
                        ask_question(
                            bank_id, body.message, user, db,
                            top_k=5, max_steps=4, on_tool=_on_tool,
                            model=model,
                        )
                    )
                    while not task.done():
                        await asyncio.sleep(0.12)
                        for step_id, label, detail in list(pending):
                            yield sse({"type": "step", "id": step_id, "label": label, "detail": detail})
                        pending.clear()
                    result = task.result()
                    for step_id, label, detail in pending:
                        yield sse({"type": "step", "id": step_id, "label": label, "detail": detail})
                    from ..rag.agent import NO_EVIDENCE_ANSWER

                    answer = (result.get("answer") or "").strip()
                    citations = result.get("citations", []) or []
                    # The agent's fixed "found nothing" line is a non-answer,
                    # not grounding (mirrors _rag_answer).
                    if not answer or answer == NO_EVIDENCE_ANSWER:
                        answer = ""
                        grounded = False
                        rag_status = "no_results"
                    else:
                        grounded = True
                    if citations:
                        rag_label = f"Read {_plural(len(citations), 'source')}"
                    elif grounded:
                        # Retrieval ran but cited nothing — don't claim it
                        # "matched" nothing while still answering from it.
                        rag_label = "Databank search cited no sources"
                    else:
                        rag_label = "No databank documents matched"
                    yield sse({
                        "type": "step",
                        "id": "rag",
                        "label": rag_label,
                    })
                except Exception as e:
                    # Databank grounding is optional: a missing provider key or a
                    # failed retrieval must not cost the owner their answer — the
                    # LLM still has the full live snapshot in its prompt.
                    logger.warning("Assistant RAG grounding unavailable: %s", e)
                    rag_status = "unavailable"
                    yield sse({"type": "step", "id": "rag", "label": "Databank unavailable"})
            else:
                yield sse({"type": "step", "id": "rag", "label": skip_reason or "Databank unavailable"})

            # 3. Think + stream the answer token by token
            prompt_snapshot, detail_omitted = _prune_snapshot(snapshot, body.message)
            yield sse({"type": "step", "id": "think", "label": "Thinking"})
            system_prompt = _system_prompt(
                prompt_snapshot, rag_answer, citations, detail_omitted, rag_status
            )

            from ..llm.providers.base import LLMMessage, LLMRequest
            from ..llm.providers.registry import get_provider_for_model
            # Aliased: a bare `_resolve_model` import would shadow the
            # module-level _resolve_model(db, user_id) used just above.
            from ..llm.service import _resolve_model as resolve_api_model

            provider = get_provider_for_model(model)
            api_model, _ = resolve_api_model(model)
            msgs = [LLMMessage(role=m.role, content=m.content) for m in body.history[-MAX_HISTORY:]]
            msgs.append(LLMMessage(role="user", content=body.message))

            empty = True
            async for chunk in provider.stream(LLMRequest(
                model=api_model,
                messages=msgs,
                system_prompt=system_prompt,
                temperature=0.4,
                max_tokens=500,
                stream=True,
                tenant_id=user.id,
                model_id=model,
                purpose="assistant.chat",
            )):
                if not chunk:
                    continue
                if empty:
                    empty = False
                    yield sse({"type": "step", "id": "think", "label": "Answering"})
                yield sse({"type": "delta", "text": chunk})

            if empty:
                raise RuntimeError("Assistant returned an empty reply")
            yield sse({
                "type": "done",
                "grounded_in_rag": grounded,
                "citations": citations[:5],
                "model": model,
            })
        except Exception as e:  # surface as an event so the UI can render it
            logger.warning("Assistant stream failed: %s", e)
            yield sse({"type": "error", "message": f"Assistant is unavailable right now: {e}"[:300]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
