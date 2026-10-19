"""GDPR account export and deletion (SEC-M1).

Owner-initiated data export and account deletion with cascading removal
of all tenant data.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ...database import async_session
from ..users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["account"])


async def _collect_tenant_data(db: AsyncSession, tenant_id: str, user: User) -> dict:
    """Collect all data for a tenant into a serializable dict for export."""
    from ..analytics.models import ReviewInsight
    from ..channels.leads import Lead
    from ..channels.meta.models import MetaAsset, MetaWebhookEvent
    from ..channels.models import Channel, ChannelMessage, ContactProfile, ReviewIssue, ReviewReply
    from ..channels.publish.router import (  # noqa: F401
        _get_publish_job,
    )
    from ..jobs.models import Job
    from ..llm.models import LLMUsageEvent
    from ..localith.models import LocalithConnection
    from ..notifications.models import Notification
    from ..outbox.models import EventOutbox

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "business_name": user.business_name,
            "business_type": user.business_type,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
    }

    # Channels
    channels = (await db.execute(
        select(Channel).where(Channel.user_id == tenant_id)
    )).scalars().all()
    data["channels"] = [
        {"id": c.id, "platform": c.platform, "display_name": c.display_name,
         "status": c.status, "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in channels
    ]

    channel_ids = [c.id for c in channels]

    # Messages
    if channel_ids:
        msgs = (await db.execute(
            select(ChannelMessage).where(ChannelMessage.channel_id.in_(channel_ids))
        )).scalars().all()
        data["messages"] = [
            {"id": m.id, "channel_id": m.channel_id, "direction": m.direction,
             "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in msgs
        ]

    # Leads
    leads = (await db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id)
    )).scalars().all()
    data["leads"] = [
        {"id": l.id, "contact_id": l.contact_id, "stage": l.stage,
         "intent": l.intent, "created_at": l.created_at.isoformat() if l.created_at else None}
        for l in leads
    ]

    # Review issues
    issues = (await db.execute(
        select(ReviewIssue).where(ReviewIssue.tenant_id == tenant_id)
    )).scalars().all()
    data["review_issues"] = [
        {"id": i.id, "review_id": i.review_id, "rating": i.rating,
         "primary_category": i.primary_category, "status": i.status,
         "created_at": i.created_at.isoformat() if i.created_at else None}
        for i in issues
    ]

    # Notifications
    notifs = (await db.execute(
        select(Notification).where(Notification.user_id == tenant_id)
    )).scalars().all()
    data["notifications"] = [
        {"id": n.id, "type": n.type, "title": n.title,
         "created_at": n.created_at.isoformat() if n.created_at else None}
        for n in notifs
    ]

    # LLM usage
    usage = (await db.execute(
        select(LLMUsageEvent).where(LLMUsageEvent.tenant_id == tenant_id)
    )).scalars().all()
    data["llm_usage"] = [
        {"id": u.id, "model_id": u.model_id, "total_tokens": u.total_tokens,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in usage
    ]

    # Analytics insights
    insights = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.tenant_id == tenant_id)
    )).scalars().all()
    data["review_insights"] = [
        {"id": i.id, "review_id": i.review_id, "rating": i.rating,
         "sentiment": i.sentiment, "created_at": i.created_at.isoformat() if i.created_at else None}
        for i in insights
    ]

    # Localith connections
    conns = (await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == tenant_id)
    )).scalars().all()
    data["localith_connections"] = [
        {"id": c.id, "listing_id": c.listing_id, "listing_name": c.listing_name}
        for c in conns
    ]

    # Meta assets
    assets = (await db.execute(
        select(MetaAsset).where(MetaAsset.tenant_id == tenant_id)
    )).scalars().all()
    data["meta_assets"] = [
        {"id": a.id, "provider": a.provider, "external_asset_id": a.external_asset_id,
         "active": a.active}
        for a in assets
    ]

    # Webhook events
    webhooks = (await db.execute(
        select(MetaWebhookEvent).where(MetaWebhookEvent.tenant_id == tenant_id)
    )).scalars().all()
    data["webhook_events"] = [
        {"id": w.id, "provider": w.provider, "event_type": w.event_type,
         "created_at": w.created_at.isoformat() if w.created_at else None}
        for w in webhooks
    ]

    # Jobs
    jobs = (await db.execute(
        select(Job).where(Job.tenant_id == tenant_id)
    )).scalars().all()
    data["jobs"] = [
        {"id": j.id, "job_type": j.job_type, "status": j.status,
         "created_at": j.created_at.isoformat() if j.created_at else None}
        for j in jobs
    ]

    return data


@router.get("/export")
async def export_account_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all tenant data as JSON (GDPR Article 20 — data portability)."""
    tenant_id = user.id
    data = await _collect_tenant_data(db, tenant_id, user)
    filename = f"sayvors-export-{tenant_id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the account and all associated data (GDPR Article 17 — right to erasure).

    Cascades through all tenant tables in dependency order, then deletes
    the user row. Refresh tokens are revoked first.
    """
    tenant_id = user.id

    # 1. Revoke all refresh tokens
    from ..auth.models import RefreshToken
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == tenant_id))

    # 2. Delete child tables (by tenant_id or channel_id)
    from ..analytics.models import ReviewInsight
    from ..channels.leads import Lead
    from ..channels.meta.models import MetaAsset, MetaWebhookEvent
    from ..channels.models import Channel, ChannelMessage, ContactProfile, ReviewIssue, ReviewReply
    from ..jobs.models import Job
    from ..llm.models import LLMUsageEvent
    from ..localith.models import LocalithConnection
    from ..notifications.models import Notification
    from ..outbox.models import EventOutbox
    from ..team.models import TeamMember

    channel_ids_subq = select(Channel.id).where(Channel.user_id == tenant_id)

    # Child tables referencing channels
    await db.execute(delete(ChannelMessage).where(ChannelMessage.channel_id.in_(channel_ids_subq)))
    await db.execute(delete(ReviewReply).where(ReviewReply.channel_id.in_(channel_ids_subq)))
    await db.execute(delete(ReviewIssue).where(ReviewIssue.tenant_id == tenant_id))
    await db.execute(delete(ContactProfile).where(ContactProfile.tenant_id == tenant_id))

    # Tenant-scoped tables
    await db.execute(delete(Lead).where(Lead.tenant_id == tenant_id))
    await db.execute(delete(Notification).where(Notification.user_id == tenant_id))
    await db.execute(delete(LLMUsageEvent).where(LLMUsageEvent.tenant_id == tenant_id))
    await db.execute(delete(ReviewInsight).where(ReviewInsight.tenant_id == tenant_id))
    await db.execute(delete(LocalithConnection).where(LocalithConnection.user_id == tenant_id))
    await db.execute(delete(MetaAsset).where(MetaAsset.tenant_id == tenant_id))
    await db.execute(delete(MetaWebhookEvent).where(MetaWebhookEvent.tenant_id == tenant_id))
    await db.execute(delete(Job).where(Job.tenant_id == tenant_id))
    # EventOutbox has no tenant_id column; filter by payload in Python.
    outbox_rows = (await db.execute(select(EventOutbox))).scalars().all()
    for row in outbox_rows:
        if isinstance(row.payload, dict) and row.payload.get("tenant_id") == tenant_id:
            await db.delete(row)

    # Team
    await db.execute(delete(TeamMember).where(TeamMember.tenant_id == tenant_id))
    await db.execute(delete(TeamMember).where(TeamMember.user_id == tenant_id))

    # Channels (cascade to messages, but we already deleted those)
    await db.execute(delete(Channel).where(Channel.user_id == tenant_id))

    # User row (cascades auth tokens, profile, billing, etc.)
    await db.execute(delete(User).where(User.id == tenant_id))

    await db.commit()
    logger.info("Account deleted: tenant=%s", tenant_id[:8])