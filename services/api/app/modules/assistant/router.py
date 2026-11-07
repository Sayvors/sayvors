"""Ask Sayvors: chat endpoint grounding answers in live business data.

Context layers, cheapest first:
  1. Structured snapshot — native Google locations, review stats, attention
     counts, reply activity (today / last 7 days).
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
from ...core.upstream_errors import upstream_http_error
from ..auth.rate_limit import rate_limit
from ..analytics.models import ReviewInsight
from ..channels.models import AutoReplyConfig, Channel, ReviewReply
from ..users.models import User
from ..team.context import tenant_id_of, require_perm, TenantContext, require_perm
from .charts import ChartPlan, chart_summary_for_prompt, plan_charts, wants_chart
from . import memory as chat_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

MAX_HISTORY = 12
MAX_TURNS_MEMORY = 20
CHART_PLAN_TIMEOUT_SECONDS = 25
RAG_TIMEOUT_SECONDS = 20


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    # Browser chat id. Enables server-side follow-up memory (last datasets,
    # prior charts, recent turns). Optional for older clients.
    session_id: str | None = Field(default=None, max_length=80)


class AssistantChatResponse(BaseModel):
    reply: str
    grounded_in_rag: bool = False
    citations: list[dict] = Field(default_factory=list)
    charts: list[dict] = Field(default_factory=list)
    model: str


async def _resolve_model(db: AsyncSession, user_id: str) -> str:
    """Tenant's configured reply model when still enabled, else the
    tenant's first enabled model. Raises when nothing is enabled — no
    hardcoded default, the database is the only source of truth."""
    from ..llm.gateway import resolve_tenant_model

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
    from ..locations.service import channel_meta, native_channels

    owner_name = " ".join(
        p for p in [user.first_name, user.last_name] if p
    ).strip() or None

    native = await native_channels(
        db, tenant_id_of(user), statuses=("active", "expired")
    )
    locations = []
    for c in native:
        meta = channel_meta(c)
        locations.append({
            "name": c.display_name,
            "address": meta.get("address"),
            "phone": meta.get("phone"),
            "website": meta.get("website"),
            "maps_url": meta.get("maps_url"),
            "category": meta.get("category"),
            "hours": meta.get("hours"),
            "status": c.status,
        })

    channels = (
        await db.execute(
            select(Channel).where(Channel.user_id == tenant_id_of(user))
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
    from ..analytics.models import LocationDailyMetric

    window_start = (datetime.now(timezone.utc) - timedelta(days=30)).date()
    metric_rows = (
        await db.execute(
            select(LocationDailyMetric).where(
                LocationDailyMetric.user_id == tenant_id_of(user),
                LocationDailyMetric.channel_id.in_(channel_ids),
                LocationDailyMetric.date >= window_start,
            )
        )
    ).scalars().all()
    by_channel: dict[str, dict] = {}
    for row in metric_rows:
        slot = by_channel.setdefault(row.channel_id, {
            "found_via_google_search": 0,
            "found_via_google_maps": 0,
            "direction_requests": 0,
            "call_clicks": 0,
            "website_clicks": 0,
        })
        extra = row.extra if isinstance(row.extra, dict) else {}
        slot["found_via_google_search"] += int(extra.get("impressions_search", 0) or 0)
        slot["found_via_google_maps"] += int(row.impressions_maps_desktop or 0) + int(
            row.impressions_maps_mobile or 0
        )
        slot["direction_requests"] += int(row.direction_requests or 0)
        slot["call_clicks"] += int(row.call_clicks or 0)
        slot["website_clicks"] += int(row.website_clicks or 0)
    for channel in channels:
        if channel.id not in by_channel:
            continue
        visibility[channel.display_name or channel.id] = {
            "window": f"{window_start.isoformat()} to {datetime.now(timezone.utc).date().isoformat()}",
            **by_channel[channel.id],
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
    hit = _snapshot_cache.get(tenant_id_of(user))
    if hit is not None and (now - hit[0]) < SNAPSHOT_TTL_SECONDS:
        return hit[1]
    snapshot = await _business_snapshot(db, user)
    if len(_snapshot_cache) >= _SNAPSHOT_CACHE_MAX:
        _snapshot_cache.clear()
    _snapshot_cache[tenant_id_of(user)] = (now, snapshot)
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


def _fallback_answer(snapshot: dict, user_message: str) -> str:
    """Answer from the live snapshot when the LLM writer comes back empty.

    Some providers return a 1-token empty completion for certain histories.
    Failing the whole chat for that is worse than answering from the data we
    already checked — counts plus the latest reviews, worded as a summary.
    """
    reviews = snapshot.get("reviews") or {}
    business = snapshot.get("business") or {}
    total = reviews.get("reviews_indexed")
    avg = reviews.get("average_rating")
    all_reviews = reviews.get("all_reviews") or []
    locations = (business.get("locations") or [])
    bits = ["I checked your live data."]
    if total is not None:
        bit = f"You have {_plural(int(total), 'review')}"
        if avg is not None:
            bit += f" with an average rating of {avg}"
        bits.append(bit + ".")
    if locations:
        names = [loc.get("name") for loc in locations if loc.get("name")]
        if names:
            bits.append(f"Connected locations: {', '.join(names[:6])}.")
    if all_reviews:
        latest = all_reviews[:4]
        lines = ["Here are your latest reviews:"]
        for r in latest:
            who = r.get("reviewer") or "Guest"
            stars = r.get("rating")
            loc = r.get("location")
            text = (r.get("text") or "").strip()[:160]
            replied = " (replied)" if r.get("replied") else " (not replied yet)"
            head = f"- **{who}**"
            if stars is not None:
                head += f" ({stars} stars)"
            if loc:
                head += f" — {loc}"
            head += replied
            lines.append(head)
            if text:
                lines.append(f"  > {text}")
        bits.append("\n".join(lines))
    else:
        bits.append("No reviews are synced yet. Connect Google Business Profile to pull them in.")
    return "\n\n".join(bits)


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
            await db.execute(select(Databank.id).where(Databank.user_id == tenant_id_of(user)).limit(1))
        ).scalar_one_or_none()
        if not bank_id:
            return "", [], False, "no_databank"
        result = await asyncio.wait_for(
            ask_question(
                bank_id, message, user, db, top_k=5, max_steps=4, model=model
            ),
            timeout=RAG_TIMEOUT_SECONDS,
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
    charts: list[dict] | None = None,
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

    chart_block = ""
    if charts:
        chart_block = (
            "\n\nCHARTS ALREADY RENDERED IN THIS REPLY:\n"
            f"{chart_summary_for_prompt(charts)}\n"
            "Mention the chart(s) naturally in one short line when the owner asked "
            "for a visual. Do not repeat every plotted value, do not describe a "
            "chart that is not in this list, and do not invent a new chart."
        )
    return (
        "You are Sayvors' business assistant, chatting with the business owner "
        "inside their dashboard.\n\n"
        f"LIVE BUSINESS DATA:\n{context}"
        f"{rag_block}\n\n"
        f"{chart_block}\n\n"
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
        "- You may give brief, actionable advice about handling reviews.\n"
        "- NEVER draw a chart in text: no ASCII bars (▇█), no emoji bars, no "
        "text tables used as a chart, no hand-drawn axes. Charts are rendered "
        "by the UI as interactive components. If a chart is already in this "
        "reply, refer to it in one short line. If the owner asked for a visual "
        "and none is listed above, say the chart could not be built from the "
        "synced data and point them to Analytics — do not draw one."
    )


async def _memory_and_history(
    body: AssistantChatRequest, tenant_id: str
) -> tuple[dict, list[ChatMessage]]:
    """Server memory wins when it knows more; the client is the bootstrap."""
    memory = await chat_memory.load_memory(tenant_id, body.session_id)
    client_history = list(body.history[-MAX_HISTORY:])
    stored = [
        ChatMessage(role=str(t.get("role")), content=str(t.get("content") or ""))
        for t in (memory.get("turns") or [])
        if t.get("role") in ("user", "assistant") and t.get("content")
    ]
    if len(client_history) >= len(stored):
        history = client_history
        if body.session_id:
            memory["turns"] = [
                {"role": m.role, "content": m.content[:4000]}
                for m in client_history[-MAX_TURNS_MEMORY:]
            ]
    else:
        history = stored
    return memory, history


async def _save_chat_turn(
    tenant_id: str,
    session_id: str | None,
    memory: dict,
    user_text: str,
    assistant_text: str | None,
) -> None:
    if not session_id:
        return
    chat_memory.append_turn(memory, "user", user_text)
    if assistant_text:
        chat_memory.append_turn(memory, "assistant", assistant_text)
    await chat_memory.save_memory(tenant_id, session_id, memory)


def _chart_business_context(snapshot: dict) -> str:
    business = snapshot.get("business") or {}
    reviews = snapshot.get("reviews") or {}
    locations = [
        str(loc.get("name") or "").strip()
        for loc in (business.get("locations") or [])
        if loc.get("name")
    ]
    platforms = sorted({
        str(c.get("platform"))
        for c in (business.get("channels") or [])
        if c.get("platform")
    })
    bits = []
    if locations:
        bits.append("Locations: " + ", ".join(locations[:6]))
    if platforms:
        bits.append("Connected platforms: " + ", ".join(platforms))
    if reviews.get("reviews_indexed") is not None:
        bits.append(f"Indexed reviews: {reviews.get('reviews_indexed')}")
    if reviews.get("average_rating") is not None:
        bits.append(f"Average rating: {reviews.get('average_rating')}")
    return "; ".join(bits)[:1200]


async def _plan_chart_reply(
    *,
    db: AsyncSession,
    user: User,
    tenant_id: str,
    model: str,
    body: AssistantChatRequest,
    history: list[ChatMessage],
    memory: dict,
    snapshot: dict,
) -> ChartPlan:
    """Chart planning is optional; a planner failure never costs the answer."""
    if settings.TESTING:
        return ChartPlan()
    from ..llm.gateway import LLMMessage

    try:
        return await asyncio.wait_for(
            plan_charts(
                db=db,
                user=user,
                tenant_id=tenant_id,
                model=model,
                message=body.message,
                history=[LLMMessage(role=m.role, content=m.content) for m in history],
                memory=memory,
                business_context=_chart_business_context(snapshot),
            ),
            timeout=CHART_PLAN_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("Assistant chart planning timed out")
        return ChartPlan()
    except Exception as e:
        logger.warning("Assistant chart planning skipped: %s", e)
        return ChartPlan()


async def _llm_reply(
    model: str,
    system_prompt: str,
    history: list[ChatMessage],
    message: str,
    user: User,
) -> str:
    from ..llm.gateway import LLMMessage, complete

    msgs = [
        LLMMessage(role=m.role, content=m.content)
        for m in history[-MAX_HISTORY:]
    ]
    msgs.append(LLMMessage(role="user", content=message))
    resp = await complete(
        model=model,
        messages=msgs,
        system_prompt=system_prompt,
        temperature=0.4,
        max_tokens=500,
        tenant_id=tenant_id_of(user),
        purpose="assistant.chat",
    )
    return resp.content.strip()


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    body: AssistantChatRequest,
    ctx: TenantContext = Depends(require_perm("ai.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.TESTING and not await rate_limit(f"assistant:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many messages — wait a moment.")

    tid = tenant_id_of(user)
    memory, history = await _memory_and_history(body, tid)
    snapshot = await _snapshot_for_user(db, user)
    model = await _resolve_model(db, tid)
    chart_plan = await _plan_chart_reply(
        db=db, user=user, tenant_id=tid, model=model,
        body=body, history=history, memory=memory, snapshot=snapshot,
    )
    rag_answer, citations, grounded, rag_status = await _rag_answer(db, user, body.message, model)
    prompt_snapshot, detail_omitted = _prune_snapshot(snapshot, body.message)
    system_prompt = _system_prompt(
        prompt_snapshot, rag_answer, citations, detail_omitted, rag_status,
        charts=chart_plan.charts,
    )
    model = await _resolve_model(db, tid)

    try:
        reply = await _llm_reply(model, system_prompt, history, body.message, user)
    except Exception as e:
        logger.warning("Assistant LLM failed (%s); answering from snapshot only", e)
        raise upstream_http_error(
            e,
            context="Assistant LLM failed",
            detail="Assistant is unavailable right now. Try again shortly.",
        ) from None

    if not reply:
        reply = _fallback_answer(prompt_snapshot, body.message)
    await _save_chat_turn(tid, body.session_id, memory, body.message, reply)
    return AssistantChatResponse(
        reply=reply,
        grounded_in_rag=grounded,
        citations=citations,
        charts=chart_plan.charts,
        model=model,
    )


# ── Streaming variant: real progress steps + token-by-token answer ──────────

# Short, human labels for the retrieval tools. The UI shows these verbatim,
# so they stay short — details live in the answer, not the trail.
TOOL_LABELS = {
    "vector_search": "Checking your documents",
    "keyword_search": "Looking up exact terms",
    "read_around": "Reading surrounding text",
    "db_schema": "Inspecting your database",
    "db_query": "Querying your database",
    "get_document": "Opening a document",
}


def _plural(n: int, word: str) -> str:
    """Count + noun, with the English irregulars this UI actually prints.

    The naive `word + "s"` shipped "6 posted replys" to production.
    """
    if n == 1:
        return f"1 {word}"
    irregular = {
        "reply": "replies",
        "posted reply": "posted replies",
        "entry": "entries",
        "query": "queries",
        "summary": "summaries",
    }
    return f"{n} {irregular.get(word, word + 's')}"


@router.post("/chat/stream")
async def chat_stream(
    body: AssistantChatRequest,
    ctx: TenantContext = Depends(require_perm("ai.view")),
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

        answer_parts: list[str] = []
        saved = False
        # Live step ids shared with the client, so a repeated step updates its
        # own row instead of appending a new one.
        try:
            # 1. Live business data, stage by stage.
            yield sse({"type": "step", "id": "data-locations", "label": "Checking your locations"})
            yield sse({"type": "step", "id": "data-reviews", "label": "Checking reviews"})
            yield sse({"type": "step", "id": "data-replies", "label": "Checking replies"})
            snapshot = await _snapshot_for_user(db, user)
            reviews_meta = snapshot.get("reviews", {}) or {}
            business_meta = snapshot.get("business", {}) or {}
            locations = (business_meta.get("locations", []) or [])
            n_reviews = int(reviews_meta.get("reviews_indexed") or 0)
            avg_rating = reviews_meta.get("average_rating")
            n_posted = int(reviews_meta.get("replies_posted_total") or 0)
            n_pending = int(reviews_meta.get("replies_pending_approval") or 0)
            yield sse({
                "type": "step",
                "id": "data-locations",
                "label": "Checked your locations",
                "detail": f"{_plural(len(locations), 'location')}",
            })
            reviews_detail = f"{_plural(n_reviews, 'review')}"
            if avg_rating is not None:
                reviews_detail += f" · avg {avg_rating}"
            yield sse({
                "type": "step",
                "id": "data-reviews",
                "label": "Checked reviews",
                "detail": reviews_detail,
            })
            yield sse({
                "type": "step",
                "id": "data-replies",
                "label": "Checked replies",
                "detail": f"{_plural(n_posted, 'posted reply')}" + (f" · {n_pending} pending" if n_pending else ""),
            })

            tid = tenant_id_of(user)
            yield sse({"type": "step", "id": "memory", "label": "Loading chat history"})
            memory, history = await _memory_and_history(body, tid)
            yield sse({
                "type": "step",
                "id": "memory",
                "label": "Loaded chat history",
                "detail": f"{_plural(len(history), 'message')}",
            })

            # 2. Databank / RAG retrieval (tool calls stream as they happen).
            #    Retrieval reasons with the tenant's own model — the same one
            #    that writes the answer — so databank search works on whatever
            #    provider the tenant actually has.
            from ..rag.models import Databank

            model = await _resolve_model(db, tid)
            bank_id = (
                await db.execute(
                    select(Databank.id).where(Databank.user_id == tid).limit(1)
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

                yield sse({"type": "step", "id": "rag", "label": "Checking your databank"})

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
                    rag_deadline = asyncio.get_event_loop().time() + RAG_TIMEOUT_SECONDS
                    while not task.done():
                        if asyncio.get_event_loop().time() > rag_deadline:
                            task.cancel()
                            raise TimeoutError("databank search timed out")
                        await asyncio.sleep(0.12)
                        for step_id, label, detail in list(pending):
                            yield sse({"type": "step", "id": step_id, "label": label, "detail": detail})
                        pending.clear()
                    if task.cancelled():
                        raise TimeoutError("databank search timed out")
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
                        rag_label = f"Checked databank — {_plural(len(citations), 'source')}"
                    elif grounded:
                        # Retrieval ran but cited nothing — don't claim it
                        # "matched" nothing while still answering from it.
                        rag_label = "Checked databank — no sources cited"
                    else:
                        rag_label = "Checked databank — no matches"
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

            # 3. Optional chart planning — steps only exist while this runs.
            chart_plan = ChartPlan()
            if wants_chart(body.message, bool(memory.get("charts"))):
                yield sse({"type": "step", "id": "charts", "label": "Planning your charts"})
                chart_pending: list[dict] = []
                chart_sent: set[str] = set()

                def _on_chart_step(step: dict) -> None:
                    chart_pending.append(step)

                try:
                    chart_task = asyncio.create_task(
                        plan_charts(
                            db=db, user=user, tenant_id=tid, model=model,
                            message=body.message,
                            history=[
                                LLMMessage(role=m.role, content=m.content)
                                for m in history
                            ],
                            memory=memory,
                            business_context=_chart_business_context(snapshot),
                            on_step=_on_chart_step,
                        )
                    )
                    chart_deadline = asyncio.get_event_loop().time() + CHART_PLAN_TIMEOUT_SECONDS
                    while not chart_task.done():
                        if asyncio.get_event_loop().time() > chart_deadline:
                            chart_task.cancel()
                            break
                        await asyncio.sleep(0.12)
                        for step in list(chart_pending):
                            sid = str(step.get("id") or "")
                            yield sse({"type": "step", **step})
                            if sid:
                                chart_sent.add(sid)
                        chart_pending.clear()
                    for step in list(chart_pending):
                        sid = str(step.get("id") or "")
                        yield sse({"type": "step", **step})
                        if sid:
                            chart_sent.add(sid)
                    chart_pending.clear()
                    if not chart_task.cancelled():
                        chart_plan = chart_task.result()
                except Exception as e:
                    logger.warning("Assistant chart planning skipped: %s", e)
                    chart_plan = ChartPlan()
                for step in chart_plan.steps:
                    if str(step.get("id") or "") in chart_sent:
                        continue
                    yield sse({"type": "step", **step})
                for chart in chart_plan.charts:
                    yield sse({"type": "chart", "chart": chart})
                charts_label = (
                    f"Charts ready — {_plural(len(chart_plan.charts), 'chart')}"
                    if chart_plan.charts
                    else "Charts checked — none needed"
                )
                yield sse({
                    "type": "step",
                    "id": "charts",
                    "label": charts_label,
                })

            prompt_snapshot, detail_omitted = _prune_snapshot(snapshot, body.message)
            yield sse({"type": "step", "id": "think", "label": "Writing your answer"})
            system_prompt = _system_prompt(
                prompt_snapshot, rag_answer, citations, detail_omitted, rag_status,
                charts=chart_plan.charts,
            )

            from ..llm.gateway import LLMMessage, stream as llm_stream

            msgs = [LLMMessage(role=m.role, content=m.content) for m in history[-MAX_HISTORY:]]
            msgs.append(LLMMessage(role="user", content=body.message))

            empty = True
            async for chunk in llm_stream(
                model=model,
                messages=msgs,
                system_prompt=system_prompt,
                temperature=0.4,
                max_tokens=500,
                tenant_id=tid,
                purpose="assistant.chat",
            ):
                if not chunk:
                    continue
                if empty:
                    empty = False
                    yield sse({"type": "step", "id": "think", "label": "Writing your answer"})
                answer_parts.append(chunk)
                yield sse({"type": "delta", "text": chunk})

            if empty:
                logger.warning("Assistant stream empty; answering from snapshot")
                yield sse({"type": "step", "id": "think", "label": "Writing your answer", "detail": "summary from live data"})
                fallback = _fallback_answer(prompt_snapshot, body.message)
                if chart_plan.charts:
                    fallback += f"\n\nI prepared {_plural(len(chart_plan.charts), 'chart')} — see above."
                answer_parts.append(fallback)
                yield sse({"type": "delta", "text": fallback})
            yield sse({"type": "step", "id": "finalize", "label": "Finalizing your answer"})
            answer_text = "".join(answer_parts)
            await _save_chat_turn(tid, body.session_id, memory, body.message, answer_text)
            saved = True
            yield sse({
                "type": "step",
                "id": "finalize",
                "label": "Done — saved to this chat",
            })
            yield sse({
                "type": "done",
                "grounded_in_rag": grounded,
                "citations": citations[:5],
                "charts": chart_plan.charts,
                "model": model,
            })
        except Exception as e:  # surface as an event so the UI can render it
            logger.warning("Assistant stream failed: %s", e)
            yield sse({"type": "error", "message": f"Assistant is unavailable right now: {e}"[:300]})
        finally:
            if not saved and body.session_id:
                try:
                    await _save_chat_turn(
                        tenant_id_of(user),
                        body.session_id,
                        locals().get("memory") or chat_memory.empty_memory(),
                        body.message,
                        "".join(answer_parts) or None,
                    )
                except Exception:
                    logger.debug("Could not persist assistant turn", exc_info=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
