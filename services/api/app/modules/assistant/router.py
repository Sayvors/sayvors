"""Ask Sayvors: chat endpoint grounding answers in live business data.

Context layers, cheapest first:
  1. Structured snapshot — Localith profile, review stats, attention counts,
     reply activity (today / last 7 days).
  2. Agentic RAG over the tenant's Databank (documents + live connected
     databases) via rag.agent.ask_question — degraded gracefully when no
     Databank exists or the RAG provider is unavailable.
  3. LLM synthesis merges both layers with the conversation history.
"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _iso(dt) -> str | None:
    try:
        return dt.isoformat(timespec="minutes") if dt else None
    except Exception:
        return None


async def _business_snapshot(db: AsyncSession, user: User) -> dict:
    """Complete live facts: every location, every review, every reply.

    Lists are newest-first and capped (see MAX_LISTED_ITEMS); totals always
    reflect the full database and `truncated` flags tell the model when the
    visible list is partial — so it can say "I can't see it" instead of
    inventing reviews, users, dates, or reply text.
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
                .limit(MAX_LISTED_ITEMS)
            )
        ).scalars().all()
        all_replies = (
            await db.execute(
                select(ReviewReply)
                .where(ReviewReply.channel_id.in_(channel_ids))
                .order_by(ReviewReply.created_at.desc())
                .limit(MAX_LISTED_ITEMS)
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
            "all_replies": [
                {
                    "location": channel_names.get(r.channel_id),
                    "reviewer": r.reviewer_name,
                    "rating": r.rating,
                    "review_text": r.review_text or "(star rating only)",
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


async def _rag_answer(db: AsyncSession, user: User, message: str) -> tuple[str, list[dict], bool]:
    """Ground the question in the Databank (documents + live DBs). Degrades softly."""
    try:
        from ..rag.models import Databank
        from ..rag.agent import ask_question

        bank_id = (
            await db.execute(select(Databank.id).where(Databank.user_id == user.id).limit(1))
        ).scalar_one_or_none()
        if not bank_id:
            return "", [], False
        result = await ask_question(bank_id, message, user, db, top_k=5, max_steps=4)
        answer = (result.get("answer") or "").strip()
        return answer, result.get("citations", []) or [], bool(answer)
    except Exception as e:
        logger.warning("Assistant RAG grounding unavailable: %s", e)
        return "", [], False


def _system_prompt(snapshot: dict, rag_answer: str, rag_citations: list[dict]) -> str:
    import json

    now = datetime.now(timezone.utc)
    context = json.dumps(
        {**snapshot, "current_time_utc": now.isoformat(timespec="minutes")},
        ensure_ascii=False,
        default=str,
    )
    rag_block = ""
    if rag_answer:
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
    return (
        "You are Sayvors' business assistant, chatting with the business owner "
        "inside their dashboard.\n\n"
        f"LIVE BUSINESS DATA:\n{context}"
        f"{rag_block}\n\n"
        "Rules:\n"
        "- Answer ONLY from the data above. Every location is listed under "
        "business.locations; every review under reviews.all_reviews (with "
        "reviewer, rating, full text, sentiment, topics, and timestamps); "
        "every reply under reviews.all_replies (with full text, status, and "
        "timestamps).\n"
        "- NEVER invent reviewer names, ratings, dates, review text, reply "
        "text, or numbers. If the owner asks about a review, reply, user, or "
        "date that is not in the lists above, say plainly that you cannot "
        "find it in the synced data — do not guess. If all_reviews_truncated "
        "is true, mention the visible list may be partial.\n"
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
    if not sys.modules.get("pytest") and not await rate_limit(f"assistant:{user.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many messages — wait a moment.")

    snapshot = await _business_snapshot(db, user)
    rag_answer, citations, grounded = await _rag_answer(db, user, body.message)
    system_prompt = _system_prompt(snapshot, rag_answer, citations)
    model = await _resolve_model(db, user.id)

    try:
        reply = await _llm_reply(model, system_prompt, body.history, body.message, user)
    except Exception as e:
        logger.warning("Assistant LLM failed (%s); answering from snapshot only", e)
        raise HTTPException(status_code=502, detail=f"Assistant is unavailable right now: {e}")

    if not reply:
        raise HTTPException(status_code=502, detail="Assistant returned an empty reply")
    return AssistantChatResponse(reply=reply, grounded_in_rag=grounded, citations=citations, model=model)
