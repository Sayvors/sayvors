"""The tenant's public facts, as one prompt block.

The assistant is the shopfront: customers ask for the address, the website,
what the business does and does not offer, and when it is physically open.
All of that is already stored — split across the owner's profile, the
WhatsApp business profile (address/websites), the channel services list and
the location hours — but the prompt only saw fragments of it.

This module gathers the public, owner-configured facts into one block and
labels them ground truth. The databank (RAG) stays the source for everything
not listed here, and the model is told to defer rather than invent.

Important distinction baked into the block: **opening hours are the physical
visiting hours, not the assistant's availability.** The AI answers 24/7.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def _whatsapp_profile(db, tenant_id: str, channel_id: str) -> dict:
    """The stored WhatsApp business profile for this channel, if any.

    Read from our own metadata instead of Graph: the assistant must answer
    even when Meta is unreachable, and the value was synced on the settings
    screen already.
    """
    try:
        from ..channels.models import Channel
        from ..channels.meta.models import MetaAsset

        channel = await db.get(Channel, channel_id)
        if channel is None or channel.platform != "whatsapp":
            return {}
        asset = (
            await db.execute(
                select(MetaAsset).where(
                    MetaAsset.tenant_id == tenant_id,
                    MetaAsset.provider == "whatsapp",
                    MetaAsset.external_asset_id == channel.platform_user_id,
                )
            )
        ).scalar_one_or_none()
        if asset is None:
            return {}
        return dict((asset.asset_metadata or {}).get("business_profile") or {})
    except Exception as e:  # noqa: BLE001 - facts are an enhancement
        logger.warning("WhatsApp profile facts lookup failed channel=%s: %s", channel_id, e)
        return {}


async def _services(db, channel_id: str) -> tuple[list[str], list[str]]:
    """(offered, not offered) service names for this channel."""
    try:
        from ..channels.models import BusinessService

        rows = (
            await db.execute(
                select(BusinessService)
                .where(BusinessService.channel_id == channel_id)
                .order_by(BusinessService.name)
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("service facts lookup failed channel=%s: %s", channel_id, e)
        return [], []
    offered = [r.name.strip() for r in rows if r.is_offered and (r.name or "").strip()]
    not_offered = [r.name.strip() for r in rows if not r.is_offered and (r.name or "").strip()]
    return offered[:40], not_offered[:20]


def _websites(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(w).strip() for w in raw if str(w or "").strip()][:3]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


async def public_facts_block(
    db,
    *,
    tenant_id: str,
    channel_id: str,
    user,
    timezone_name: str = "UTC",
    listing_id: str | None = None,
) -> str:
    """Prompt block of owner-configured public facts. "" when nothing is known."""
    from ..locations.ai_hours import opening_hours_block

    profile = await _whatsapp_profile(db, tenant_id, channel_id)
    offered, not_offered = await _services(db, channel_id)
    hours = await opening_hours_block(
        db, tenant_id, listing_id=listing_id, timezone_name=timezone_name
    )

    lines: list[str] = [
        "PUBLIC BUSINESS FACTS (owner-configured; treat as ground truth and "
        "answer from these before saying you do not know):",
    ]
    name = (getattr(user, "business_name", None) or "").strip()
    btype = (getattr(user, "business_type", None) or "").strip()
    if name and btype:
        lines.append(f"- Business: {name} ({btype})")
    elif name:
        lines.append(f"- Business: {name}")
    elif btype:
        lines.append(f"- Business type: {btype}")

    description = (getattr(user, "business_description", None) or "").strip()
    if description:
        lines.append(f"- About: {description[:600]}")
    sells = (getattr(user, "business_sells", None) or "").strip()
    if sells:
        lines.append(f"- Sells / offers: {sells[:600]}")
    doesnt = (getattr(user, "business_doesnt_sell", None) or "").strip()
    if doesnt:
        lines.append(f"- Does NOT offer: {doesnt[:400]}")

    websites = _websites(profile.get("websites"))
    if websites:
        lines.append(f"- Website: {', '.join(websites)}")
    address = str(profile.get("address") or "").strip()
    if address:
        lines.append(f"- Address: {address[:300]}")
    email = str(profile.get("email") or "").strip()
    if email:
        lines.append(f"- Email: {email[:200]}")

    if offered:
        lines.append(f"- Services offered: {', '.join(offered)}")
    if not_offered:
        lines.append(f"- Services NOT offered: {', '.join(not_offered)}")

    if hours:
        lines.append("")
        lines.append(hours)

    if len(lines) <= 1:
        return ""

    lines.append("")
    lines.append(
        "For anything not listed above, use the DATABANK passages when they "
        "are present. If neither covers the question, say you will confirm "
        "with the team — never guess an address, a service, a price or a link."
    )
    return "\n".join(lines)
