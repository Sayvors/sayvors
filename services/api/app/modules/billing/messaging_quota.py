"""The WhatsApp message-allowance gate shared by every outbound path.

The plan's numeric message allowance is WhatsApp-only. Instagram, Facebook and
every other channel still pass the plan's `messaging` feature check, but they
must neither consume nor be blocked by the WhatsApp allowance.

Kept outside the channels router so the template-send endpoint can use the
exact same gate instead of re-implementing it.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..team.context import TenantContext


async def ensure_messaging_quota(
    ctx: TenantContext, db: AsyncSession, channel_id: str
) -> None:
    """Raise 403/429 when the tenant may not send this outbound message.

    The caller must already have checked edit access to `channel_id`; the
    tenant filter below is defence in depth so a quota decision can never be
    driven by another tenant's channel.
    """
    from ..team.context import tenant_id_of
    from .entitlements import (
        ENTITLEMENT_DENIED_HEADER,
        count_messages_this_month,
        entitlement_403,
        get_entitlements,
    )

    tid = tenant_id_of(ctx.user)
    ent = await get_entitlements(tid, db)
    if not ent.has_feature("messaging"):
        raise entitlement_403("Messaging is not included in your plan.", "messaging")

    platform = (
        await db.execute(
            select(Channel.platform).where(
                Channel.id == channel_id, Channel.user_id == tid
            )
        )
    ).scalar_one_or_none()
    if platform != "whatsapp":
        return

    used = await count_messages_this_month(tid, db)
    if not ent.message_quota_ok(used):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly WhatsApp message limit reached for plan "
                f"'{ent.plan_slug}'. Upgrade to send more."
            ),
            headers={ENTITLEMENT_DENIED_HEADER: "quota"},
        )
    # The send is about to add a row; drop the cached count so the next
    # inbound check (AI reply gate) sees it immediately.
    try:
        from .quotas import invalidate_message_usage

        await invalidate_message_usage(tid)
    except Exception:
        pass
