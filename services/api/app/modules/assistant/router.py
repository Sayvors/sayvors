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

DEFAULT_MODEL = "groq:openai/gpt-oss-120b"
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
    """Tenant's configured reply model (hidden from end users), else default."""
    cfg = (
        await db.execute(
            select(AutoReplyConfig.model)
            .join(Channel, Channel.id == AutoReplyConfig.channel_id)
            .where(Channel.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return cfg or DEFAULT_MODEL


async def _business_snapshot(db: AsyncSession, user: User) -> dict:
    """Live structured facts: profile, channels, review stats, attention."""
    from ..localith.models import LocalithConnection

    conn = (
        await db.execute(
            select(LocalithConnection).where(LocalithConnection.user_id == user.id)
        )
    ).scalar_one_or_none()

    business: dict = {}
    if conn:
        business = {
            "name": conn.listing_name,
            "address": conn.address,
            "phone": conn.phone_number,
            "website": conn.website_url,
            "total_reviews_on_google": conn.total_reviews,
            "average_rating_on_google": conn.average_rating,
        }

    channels = (
        await db.execute(
            select(Channel.id, Channel.display_name).where(
                Channel.user_id == user.id, Channel.status == "active"
            )
        )
    ).all()
    channel_ids = [c.id for c in channels]

    stats: dict = {"connected_locations": [c.display_name or c.id for c in channels]}
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
        recent = (
            await db.execute(
                select(ReviewInsight)
                .where(ReviewInsight.channel_id.in_(channel_ids))
                .order_by(ReviewInsight.review_updated_at.desc().nullslast())
                .limit(8)
            )
        ).scalars().all()

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
        stats.update({
            "reviews_indexed": total,
            "average_rating": round(float(avg), 2) if avg is not None else None,
            "rating_distribution": {str(r): n for r, n in dist_rows},
            "replies_posted_total": posted_total,
            "replies_posted_today_utc": posted_today,
            "replies_posted_last_7_days_utc": posted_week,
            "replies_pending_approval": pending,
            "replies_failed": failed,
            "recent_reviews": [
                {
                    "rating": r.rating,
                    "text": (r.review_text or "")[:200] or "(star rating only)",
                    "reviewer": r.reviewer_name,
                    "replied": bool(r.replied),
                }
                for r in recent
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
        "inside their dashboard. Answer their question using ONLY the live data "
        "below and the databank grounding — never invent numbers or facts.\n\n"
        f"LIVE BUSINESS DATA:\n{context}"
        f"{rag_block}\n\n"
        "Rules:\n"
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
