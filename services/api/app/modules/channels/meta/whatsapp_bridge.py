"""Instagram -> WhatsApp bridge.

The constraint that shapes this module: WhatsApp forbids a business from
messaging a number it picked up elsewhere until the customer writes first.
So the move is customer-initiated — the DM hands over a ``wa.me`` link that
carries a short token, the customer taps and sends, and that first inbound is
matched back to the Instagram lead.

Identity is resolved two ways, cheapest first:

1. the phone the customer typed in the DM (``phone_e164``), which needs no
   cooperation from the message text;
2. the token, which survives them writing from a different phone.

A bridge is single-use: consuming it sets ``used_at``, so a forwarded link
cannot pull a stranger into a lead. A token alone is never enough to read the
Instagram conversation — it only merges the two identity rows the tenant
already owns.
"""
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..models import ChannelBridge, ConversationContext, Lead

logger = logging.getLogger(__name__)

# No 0/O or 1/I: the token is read off a screen and sometimes typed by hand.
# The alphabet is shared with review handoff codes (core.short_codes).
TOKEN_LENGTH = 6
TOKEN_PREFIX = "SV-"
# Long enough that a customer can come back to the chat days later, short
# enough that a leaked link is not a permanent handle.
BRIDGE_TTL_DAYS = 7
# Matches "SV-ABC123", "SV ABC123", "svabc123" — customers retype these.
_TOKEN_RE = re.compile(r"\bSV[\s\-]*([A-Za-z0-9]{6})\b", re.IGNORECASE)
_MINT_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone(raw: str | None) -> str | None:
    """Digits with a leading +, no country guessing.

    The DM side already validated with ``lead_engine.validate_phone``, which
    refuses to assume a region; this only normalises the shape Meta sends
    (usually digits without the +).
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    return f"+{digits}"


def _wa_number(raw: str | None) -> str:
    """wa.me wants bare digits."""
    return re.sub(r"\D", "", raw or "")


def token_label(token: str) -> str:
    return f"{TOKEN_PREFIX}{token}"


def wa_link(whatsapp_number: str, token: str) -> str:
    """The link the customer taps. Points at OUR number, never theirs."""
    return (
        f"https://wa.me/{_wa_number(whatsapp_number)}"
        f"?text={quote(token_label(token))}"
    )


def dm_text(token: str, whatsapp_number: str) -> str:
    return (
        "Here's the WhatsApp link — tap it and send the message that opens:\n"
        f"{wa_link(whatsapp_number, token)}\n"
        "You'll be talking to the same team, with this conversation already "
        "in front of them."
    )


def _random_token() -> str:
    # secrets, not random: a guessable token would let someone merge a
    # stranger's Instagram lead into their own WhatsApp thread.
    from ....core.short_codes import CODE_ALPHABET

    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(TOKEN_LENGTH))


async def active_whatsapp_asset(db, tenant_id: str):
    """The tenant's first active WhatsApp number, or None.

    Deterministic order so two workers build the same link for the same tenant
    instead of racing between two numbers.
    """
    from .models import MetaAsset

    return (
        await db.execute(
            select(MetaAsset)
            .where(
                MetaAsset.tenant_id == tenant_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "phone_number",
                MetaAsset.active.is_(True),
                MetaAsset.phone.isnot(None),
            )
            .order_by(MetaAsset.created_at.asc())
            .limit(1)
        )
    ).scalars().first()


async def pending_bridge(
    db,
    *,
    tenant_id: str,
    channel_id: str,
    contact_id: str,
    phone: str,
    target_asset_id: str | None,
) -> ChannelBridge | None:
    """A bridge that still needs its DM sent, or None when there is nothing to do.

    Returns None when this thread already got a link for this number: repeating
    it every turn would nag the customer. A link that failed to send keeps
    ``sent_at`` NULL, so the next turn retries it.
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    now = _now()
    existing = (
        await db.execute(
            select(ChannelBridge)
            .where(
                ChannelBridge.channel_id == channel_id,
                ChannelBridge.contact_id == contact_id,
                ChannelBridge.phone_e164 == normalized,
                ChannelBridge.used_at.is_(None),
                ChannelBridge.expires_at > now,
            )
            .order_by(ChannelBridge.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if existing is not None:
        return None if existing.sent_at is not None else existing

    for _ in range(_MINT_ATTEMPTS):
        bridge = ChannelBridge(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel_id=channel_id,
            contact_id=contact_id,
            phone_e164=normalized,
            token=_random_token(),
            target_asset_id=target_asset_id,
            expires_at=now + timedelta(days=BRIDGE_TTL_DAYS),
        )
        try:
            async with db.begin_nested():
                db.add(bridge)
                await db.flush()
        except IntegrityError:
            # Token collision — astronomically rare, but the unique index is
            # the authority, not the odds.
            logger.warning("bridge token collision — retrying")
            continue
        return bridge
    logger.error(
        "could not mint a bridge token after %d attempts channel=%s",
        _MINT_ATTEMPTS, channel_id,
    )
    return None


async def mark_sent(db, bridge: ChannelBridge) -> None:
    bridge.sent_at = _now()
    await db.commit()


async def find_bridge(db, *, tenant_id: str, text: str | None,
                      phone: str | None) -> ChannelBridge | None:
    """The unused, unexpired bridge this inbound is answering, if any.

    Token first: it is deliberate, and it works when the customer writes from
    a number they did not type in the DM. Phone second, because most customers
    simply tap and send from the number they gave us.
    """
    now = _now()
    match = _TOKEN_RE.search(text or "")
    if match:
        token = match.group(1).upper()
        bridge = (
            await db.execute(
                select(ChannelBridge).where(
                    ChannelBridge.tenant_id == tenant_id,
                    ChannelBridge.token == token,
                    ChannelBridge.used_at.is_(None),
                    ChannelBridge.expires_at > now,
                )
            )
        ).scalars().first()
        if bridge is not None:
            return bridge

    normalized = normalize_phone(phone)
    if not normalized:
        return None
    return (
        await db.execute(
            select(ChannelBridge)
            .where(
                ChannelBridge.tenant_id == tenant_id,
                ChannelBridge.phone_e164 == normalized,
                ChannelBridge.used_at.is_(None),
                ChannelBridge.expires_at > now,
            )
            .order_by(ChannelBridge.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _ig_lead(db, bridge: ChannelBridge) -> Lead | None:
    return (
        await db.execute(
            select(Lead)
            .where(
                Lead.channel_id == bridge.channel_id,
                Lead.contact_id == bridge.contact_id,
            )
            .order_by(Lead.created_at.asc())
            .limit(1)
        )
    ).scalars().first()


def _fill(target, key: str, value) -> None:
    """Copy only into an empty field — same rule as capture_lead's merge."""
    if value and not getattr(target, key, None):
        setattr(target, key, value)


def _merge_lead(target: Lead, source: Lead, phone: str) -> None:
    _fill(target, "contact_name", source.contact_name)
    _fill(target, "contact_username", source.contact_username)
    _fill(target, "intent", source.intent)
    _fill(target, "request", source.request)
    _fill(target, "summary", source.summary)
    _fill(target, "phone_number", source.phone_number or phone)
    # The WhatsApp lead's language is unknown until it says something; the
    # Instagram conversation already established one.
    if (target.language or "en") == "en" and (source.language or "en") != "en":
        target.language = source.language
    # A lead that already progressed on Instagram should not restart at "new"
    # just because the channel changed.
    if (target.stage or "new") == "new" and (source.stage or "new") != "new":
        target.stage = source.stage


async def _carry_context(db, bridge: ChannelBridge, ig_lead: Lead | None,
                         target: Lead) -> None:
    """Give the WhatsApp thread a first summary built from the Instagram side.

    A short Instagram chat may have no stored context row (those need a few
    messages), so the lead's captured facts are always part of the note — the
    whole point is that the customer does not repeat themselves at the handoff.
    """
    from ..conversation_context import latest
    from ..service import (
        decrypt_message_content,
        encrypt_message_content,
        hash_contact_phone,
    )

    lines = ["From an Instagram conversation (the customer moved here from a DM):"]
    if ig_lead is not None:
        who = ig_lead.contact_name or ""
        if ig_lead.contact_username:
            who = f"{who} (@{ig_lead.contact_username})".strip()
        if who:
            lines.append(f"Customer: {who}")
        asked = ig_lead.request or ig_lead.summary
        if asked:
            lines.append(f"Asked: {asked}")
        if ig_lead.intent:
            lines.append(f"Intent: {ig_lead.intent}")
        if ig_lead.stage and ig_lead.stage != "new":
            lines.append(f"Stage: {ig_lead.stage}")
    stored = await latest(
        db, channel_id=bridge.channel_id, contact_phone=bridge.contact_id
    )
    if stored is not None:
        text = decrypt_message_content(stored.summary) or ""
        if text.strip():
            lines.append("")
            lines.append(text.strip())

    summary = "\n".join(lines)
    db.add(ConversationContext(
        id=str(uuid.uuid4()),
        tenant_id=bridge.tenant_id,
        channel_id=target.channel_id,
        contact_phone=encrypt_message_content(target.contact_id),
        contact_phone_hash=hash_contact_phone(target.contact_id),
        summary=encrypt_message_content(summary),
        message_count=int(stored.message_count or 0) if stored is not None else 0,
        reason="cross_channel",
        model=None,
    ))


async def link_bridge(db, *, bridge: ChannelBridge, lead: Lead,
                      contact_phone: str) -> bool:
    """Consume the bridge: merge the two leads and carry the context over.

    The WhatsApp lead wins because it is the live channel; the Instagram lead
    keeps its row (its thread and messages are real history) and is pointed at
    the survivor with ``merged_into_id``. Returns True when the bridge was
    consumed.
    """
    if bridge.used_at is not None:
        return False

    ig_lead = await _ig_lead(db, bridge)
    if ig_lead is not None and ig_lead.id != lead.id:
        _merge_lead(lead, ig_lead, bridge.phone_e164)
        ig_lead.merged_into_id = lead.id
        # The merged row must not keep escalating or reminding: the live lead
        # is the survivor and carries its own state.
        ig_lead.priority = "normal"
        ig_lead.ai_miss_count = 0
        ig_lead.priority_since = None
        ig_lead.escalated_at = None
        ig_lead.escalation_reminder_at = None
        ig_lead.handover_sent_at = None

    await _carry_context(db, bridge, ig_lead, lead)

    # Tapping the WhatsApp link and writing to us is the customer's explicit
    # choice to be messaged on WhatsApp — that is the consent basis Meta asks
    # for before any template. Recorded once; the first evidence wins.
    from ...whatsapp_templates.service import record_opt_in

    await record_opt_in(db, lead, source="instagram_bridge", message_id=None)

    bridge.used_at = _now()
    bridge.used_by_lead_id = lead.id
    logger.info(
        "bridge consumed channel=%s contact=%s into lead=%s phone=+%s",
        bridge.channel_id, bridge.contact_id[-6:], lead.id,
        (contact_phone or "")[-6:],
    )
    return True
