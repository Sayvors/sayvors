"""Customer aggregation for the dashboard's "customers" page.

A customer is a thread — the same grouping the inbox already uses — so this
module reuses `list_inbox_threads_page` rather than re-implementing the
grouping, the filtering or the pagination. The work here is the augmentation
(lead and review data) and the profile assembly.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import Channel, ChannelMessage, ContactProfile
from .service import (
    decrypt_message_content,
    hash_contact_phone,
    is_important,
    list_inbox_threads_page,
    tenant_id_of,
)
from .models import Lead
from .models import ReviewReply


async def _lead_for(
    db: AsyncSession, tenant_id: str, channel_id: str, contact_phone: str | None
) -> Lead | None:
    """The lead row for a (channel, contact) pair, if the capture engine
    turned this conversation into one."""
    if not contact_phone:
        return None
    result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.channel_id == channel_id,
            Lead.contact_id == contact_phone,
        )
    )
    return result.scalar_one_or_none()


async def _reviews_for(
    db: AsyncSession, channel_id: str, contact_phone: str | None
) -> list[dict[str, Any]]:
    """Review replies belonging to a Google reviewer's thread.

    A review reply is keyed by (channel_id, review_id); the review id is
    the thread's message platform_message_id. The thread's `contact_phone`
    is the synthetic `google:<digest>` key, so we match via the messages
    instead: load the thread's review ids and look up their replies.
    """
    if not contact_phone or not contact_phone.startswith("google:"):
        return []
    from .service import hash_contact_phone

    msg_ids = (
        await db.execute(
            select(ChannelMessage.platform_message_id).where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.contact_phone_hash == hash_contact_phone(contact_phone),
            )
        )
    ).scalars().all()
    review_ids = {m for m in msg_ids if m}
    if not review_ids:
        return []
    rows = (
        await db.execute(
            select(ReviewReply).where(
                ReviewReply.channel_id == channel_id,
                ReviewReply.review_id.in_(list(review_ids)),
            )
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "review_id": r.review_id,
            "rating": r.rating,
            "review_text": r.review_text,
            "reviewer_name": r.reviewer_name,
            "reply_text": r.reply_text,
            "status": r.status,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "replied_at": r.replied_at.isoformat() if r.replied_at else None,
        }
        for r in rows
    ]


async def list_customers(
    db: AsyncSession,
    user: User,
    *,
    search: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    important: bool | None = None,
    limit: int = 100,
    cursor: str | None = None,
    visible_channel_ids: set[str] | None = None,
    sort: str = "important",
) -> tuple[list[dict[str, Any]], int, str | None]:
    """One filtered, RBAC-scoped page of customers, newest/important first.

    The inbox thread page does the expensive work in SQL. This function only
    augments the returned page with lead data and whether a Google review is
    attached — two bulk lookups, not one per Google thread.
    """
    page, total, next_cursor = await list_inbox_threads_page(
        user,
        db,
        search=search,
        limit=limit,
        cursor=cursor,
        category=category,
        priority=priority,
        important=important,
        platform=platform,
        visible_channel_ids=visible_channel_ids,
        sort=sort,
    )
    if not page:
        return [], total, next_cursor

    tenant_id = tenant_id_of(user)
    lead_pairs = {
        (row["channel_id"], row["contact_phone"])
        for row in page
        if row.get("contact_phone")
    }
    leads_by_key: dict[tuple[str, str], Lead] = {}
    if lead_pairs:
        leads = (
            await db.execute(
                select(Lead).where(
                    Lead.tenant_id == tenant_id,
                    tuple_(Lead.channel_id, Lead.contact_id).in_(list(lead_pairs)),
                )
            )
        ).scalars().all()
        leads_by_key = {(lead.channel_id, lead.contact_id): lead for lead in leads}

    # Google threads are keyed by the synthetic google:<digest> contact; a
    # review reply is keyed by (channel_id, review_id), and the review id is
    # the thread's platform_message_id. Two bulk queries for the whole page.
    google_pairs = {
        (row["channel_id"], hash_contact_phone(row["contact_phone"]))
        for row in page
        if row.get("platform") == "google_reviews"
        and row.get("contact_phone")
        and row["contact_phone"].startswith("google:")
    }
    reviewed_threads: set[tuple[str, str]] = set()
    if google_pairs:
        message_rows = (
            await db.execute(
                select(
                    ChannelMessage.channel_id,
                    ChannelMessage.contact_phone_hash,
                    ChannelMessage.platform_message_id,
                ).where(
                    tuple_(
                        ChannelMessage.channel_id,
                        ChannelMessage.contact_phone_hash,
                    ).in_(list(google_pairs)),
                    ChannelMessage.platform_message_id.is_not(None),
                )
            )
        ).all()
        review_pairs = {
            (channel_id, platform_message_id)
            for channel_id, _contact_hash, platform_message_id in message_rows
            if platform_message_id
        }
        if review_pairs:
            reply_rows = (
                await db.execute(
                    select(ReviewReply.channel_id, ReviewReply.review_id).where(
                        tuple_(
                            ReviewReply.channel_id, ReviewReply.review_id
                        ).in_(list(review_pairs))
                    )
                )
            ).all()
            replied = {(channel_id, review_id) for channel_id, review_id in reply_rows}
            reviewed_threads = {
                (channel_id, contact_hash)
                for channel_id, contact_hash, platform_message_id in message_rows
                if (channel_id, platform_message_id) in replied
            }

    for row in page:
        lead = leads_by_key.get((row["channel_id"], row.get("contact_phone")))
        row["lead_stage"] = lead.stage if lead else None
        if lead and lead.category:
            row["lead_category"] = lead.category
        row["intent"] = lead.intent if lead else None
        phone = row.get("contact_phone")
        row["has_review"] = bool(
            phone
            and phone.startswith("google:")
            and (row["channel_id"], hash_contact_phone(phone)) in reviewed_threads
        )

    return page, total, next_cursor


async def get_customer_profile(
    db: AsyncSession,
    user: User,
    channel_id: str,
    contact_key: str,
) -> dict[str, Any] | None:
    """The complete profile for one customer.

    Returns None when the channel is not owned by the tenant or the
    contact does not exist. The caller turns that into a 404.
    """
    tenant_id = tenant_id_of(user)
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id, Channel.user_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        return None

    # Resolve the thread. The contact_key is the phone (or "unknown" /
    # a "google:<digest>" key). `list_thread_messages` handles the
    # "unknown" catch-all; for a real key it filters by the hash.
    from .service import list_thread_messages

    messages = await list_thread_messages(
        user, db, channel_id, None if contact_key == "unknown" else contact_key, limit=500
    )
    if not messages and contact_key != "unknown":
        # No messages means no such thread.
        return None

    # Identity comes from the newest message plus the cached profile.
    newest = messages[0] if messages else None
    contact_phone = (
        None if contact_key == "unknown" else contact_key
    )
    contact_profile = None
    google_name = None
    google_avatar = None
    if contact_phone and contact_phone.startswith("google:"):
        # Google reviewers have no ContactProfile row. Resolve the reviewer
        # from the review insight attached to the newest message.
        from ..analytics.models import ReviewInsight

        if newest is not None and newest.platform_message_id:
            insight = (
                await db.execute(
                    select(ReviewInsight).where(
                        ReviewInsight.channel_id == channel_id,
                        ReviewInsight.review_id == newest.platform_message_id,
                    )
                )
            ).scalar_one_or_none()
            if insight is not None:
                google_name = insight.reviewer_name
                google_avatar = insight.reviewer_photo_url
    else:
        from .models import ContactProfile

        result = await db.execute(
            select(ContactProfile).where(
                ContactProfile.tenant_id == tenant_id,
                ContactProfile.platform == channel.platform,
                ContactProfile.contact_id == contact_phone,
            )
        )
        contact_profile = result.scalar_one_or_none()

    # Lead lookup — Google reviews never create a Lead, so this is None
    # for them.
    lead = await _lead_for(db, tenant_id, channel_id, contact_phone)

    # Reviews for a Google reviewer's thread.
    reviews = await _reviews_for(db, channel_id, contact_phone)

    # Categorization from the newest message.
    category = newest.category if newest is not None else None
    priority = newest.priority if newest is not None else None

    def _iso(dt):
        return dt.isoformat() if dt else None

    return {
        "identity": {
            "name": (
                (contact_profile.name if contact_profile else None)
                or google_name
                or (newest.contact_name if newest else None)
                or contact_phone
            ),
            "username": contact_profile.username if contact_profile else None,
            "avatar_url": (
                (contact_profile.avatar_url if contact_profile else None)
                or google_avatar
            ),
            "contact_phone": contact_phone,
            "platform": channel.platform,
            "channel_id": channel_id,
            "channel_name": channel.display_name,
            "profile_fetched_at": (
                contact_profile.profile_fetched_at.isoformat()
                if contact_profile and contact_profile.profile_fetched_at
                else None
            ),
        },
        "category": category,
        "priority": priority,
        "important": is_important(priority, category),
        "can_reply": channel.platform != "google_reviews" and contact_phone is not None,
        "lead": (
            {
                "id": lead.id,
                "stage": lead.stage,
                "category": lead.category,
                "intent": lead.intent,
                "request": lead.request,
                "summary": lead.summary,
                "contact_name": lead.contact_name,
                "contact_username": lead.contact_username,
                "language": lead.language,
                "phone_number": lead.phone_number,
                "phone_status": lead.phone_status,
                "opt_out": lead.opt_out,
                "field_provenance": lead.field_provenance,
                "last_message_at": _iso(lead.last_message_at),
                "next_action_at": _iso(lead.next_action_at),
                "priority": lead.priority,
                "ai_miss_count": lead.ai_miss_count,
                "created_at": _iso(lead.created_at),
                "updated_at": _iso(lead.updated_at),
            }
            if lead
            else None
        ),
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "content": decrypt_message_content(m.content) or "",
                "content_type": m.content_type,
                "status": m.status,
                "error": m.error,
                "contact_name": m.contact_name,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
        "reviews": reviews,
    }
