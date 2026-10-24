"""Conversation insights mining worker.

Mines inbound ChannelMessage + ChannelComment content per tenant over a
rolling window, uses the LLM to extract top questions/intents/topics, and
persists the result to the `conversation_insights` table. Endpoints read
stored rows only — no LLM calls on the request path (architecture rule).

Runs on a daily cadence (CONVERSATION_INSIGHTS_INTERVAL_SECONDS). One pass
per tenant; failures are isolated per tenant.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from ...config import settings
from ...database import async_session
from ..channels.models import Channel, ChannelComment, ChannelMessage
from ..llm.gateway import complete, LLMMessage
from .models import ConversationInsight

logger = logging.getLogger(__name__)

# How many inbound messages to sample per tenant per pass. Caps LLM cost
# and keeps the prompt within context limits.
_SAMPLE_CAP = 200
# Rolling window for mining.
_WINDOW_DAYS = 30


async def mine_tenant(db, tenant_id: str) -> dict:
    """Mine one tenant's conversations and persist insights. Returns stats."""
    stats = {"messages": 0, "insights": 0, "error": None}

    window_end = datetime.now(timezone.utc).date()
    window_start = window_end - timedelta(days=_WINDOW_DAYS)

    # Fetch inbound messages + comments for this tenant's channels.
    channels = (
        await db.execute(
            select(Channel.id).where(Channel.user_id == tenant_id, Channel.status == "active")
        )
    ).scalars().all()
    if not channels:
        return stats

    # Collect inbound text content, capped.
    texts: list[str] = []
    msg_count = 0
    for ch_id in channels:
        # Messages
        msgs = (
            await db.execute(
                select(ChannelMessage.content)
                .where(
                    ChannelMessage.channel_id == ch_id,
                    ChannelMessage.direction == "inbound",
                    ChannelMessage.created_at >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc),
                )
                .order_by(ChannelMessage.created_at.desc())
                .limit(_SAMPLE_CAP)
            )
        ).scalars().all()
        for content in msgs:
            # Content is encrypted; decrypt for mining.
            try:
                from ..channels.service import decrypt_message_content
                text = decrypt_message_content(content)
            except Exception:
                text = content
            if text and len(text.strip()) > 3:
                texts.append(text.strip()[:500])
                msg_count += 1
            if len(texts) >= _SAMPLE_CAP:
                break
        if len(texts) >= _SAMPLE_CAP:
            break

        # Comments
        comments = (
            await db.execute(
                select(ChannelComment.content)
                .where(
                    ChannelComment.channel_id == ch_id,
                    ChannelComment.direction == "inbound",
                    ChannelComment.created_at >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc),
                )
                .order_by(ChannelComment.created_at.desc())
                .limit(_SAMPLE_CAP - len(texts))
            )
        ).scalars().all()
        for content in comments:
            if content and len(content.strip()) > 3:
                texts.append(content.strip()[:500])
                msg_count += 1
            if len(texts) >= _SAMPLE_CAP:
                break

    stats["messages"] = msg_count
    if not texts:
        # No data — persist empty insights so the UI shows honest empty state.
        await _upsert_insights(db, tenant_id, window_start, window_end, {}, 0)
        return stats

    # LLM mining pass.
    sample = texts[:_SAMPLE_CAP]
    prompt = (
        "You are analyzing customer messages for a small business. "
        "Given the following inbound messages/comments, extract:\n"
        "1. Top 5 questions customers ask (with approximate count)\n"
        "2. Top 5 intents (e.g. booking, pricing, complaint, compliment)\n"
        "3. Top 5 topics mentioned\n\n"
        "Return ONLY valid JSON in this format:\n"
        '{"top_questions": [{"question": "...", "count": N}], '
        '"intents": [{"intent": "...", "count": N}], '
        '"topics": [{"topic": "...", "count": N}]}\n\n'
        "Messages:\n" + "\n".join(f"- {t}" for t in sample)
    )

    try:
        resp = await complete(
            model="groq:oss-20b",
            messages=[LLMMessage(role="user", content=prompt)],
            system_prompt="You extract structured insights from customer messages. Return only valid JSON.",
            temperature=0.1,
            max_tokens=1024,
            tenant_id=None,
            purpose="analytics.mine_conversations",
        )
        raw = (resp.content or "").strip()
        # Try to parse JSON from the response.
        insights = {}
        try:
            # Handle markdown code blocks
            if "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            insights = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse insights JSON for tenant %s: %s", tenant_id, raw[:200])
            insights = {"raw": raw[:500]}
        stats["insights"] = len(insights.get("top_questions", []))
    except Exception as e:
        logger.error("LLM mining failed for tenant %s: %s", tenant_id, e)
        stats["error"] = str(e)[:200]
        insights = {}

    await _upsert_insights(db, tenant_id, window_start, window_end, insights, msg_count)
    return stats


async def _upsert_insights(db, tenant_id, window_start, window_end, insights, message_count):
    """Upsert a conversation_insights row (idempotent per tenant + window)."""
    from sqlalchemy import select
    from .models import ConversationInsight

    existing = (
        await db.execute(
            select(ConversationInsight).where(
                ConversationInsight.tenant_id == tenant_id,
                ConversationInsight.window_start == window_start,
                ConversationInsight.window_end == window_end,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.insights = insights
        existing.message_count = message_count
        existing.computed_at = datetime.now(timezone.utc)
    else:
        row = ConversationInsight(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
            insights=insights,
            message_count=message_count,
            computed_at=datetime.now(timezone.utc),
        )
        db.add(row)
    await db.commit()


async def mine_all_once(session_factory=None) -> dict:
    """One pass over every tenant. Returns totals."""
    from ...database import async_session
    from ..users.models import User

    totals = {"tenants": 0, "messages": 0, "errors": 0}
    factory = session_factory or async_session
    async with factory() as db:
        try:
            tenants = (await db.execute(select(User.id))).scalars().all()
        except Exception as e:
            logger.error("Conversation insights: could not list tenants: %s", e)
            totals["errors"] += 1
            return totals

    for tenant_id in tenants:
        async with factory() as db:
            try:
                stats = await mine_tenant(db, tenant_id)
                totals["tenants"] += 1
                totals["messages"] += stats["messages"]
                if stats.get("error"):
                    totals["errors"] += 1
            except Exception as e:
                logger.error("Conversation insights failed for tenant %s: %s", tenant_id, e)
                totals["errors"] += 1

    return totals


async def run_conversation_insights_worker() -> None:
    """Background loop. Runs mine_all_once on a daily cadence."""
    interval = getattr(settings, "CONVERSATION_INSIGHTS_INTERVAL_SECONDS", 86400)
    logger.info("Conversation insights worker started (interval=%ds)", interval)
    while True:
        try:
            totals = await mine_all_once()
            logger.info("Conversation insights pass: %s", totals)
        except Exception as e:
            logger.error("Conversation insights worker error: %s", e)
        await asyncio.sleep(interval)