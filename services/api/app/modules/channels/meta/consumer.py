"""Meta events consumer: inbound WhatsApp messages -> AI reply -> Cloud API send.

Phase 2 of the WhatsApp pipeline. The webhook ingress (fast path) resolves
the tenant via meta_assets and enqueues normalized events to Kafka
"meta-events" through the transactional outbox; this consumer turns
message.received events into conversations: history persisted in
channel_messages, an AI reply generated with the tenant's enabled LLM, and
the reply sent back through the WhatsApp Cloud API (24h session window).

Sending requires the connection's access token (Embedded Signup token or a
system-user token). Without one the inbound message is still stored — only
the reply step is skipped, so history accrues while credentials are pending.

Kafka outages degrade gracefully (outbox fallback), same as the analytics
consumer. Kafka payloads are untrusted: the asset row re-resolved from the
DB decides the tenant, never the payload claim.
"""
import asyncio
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ....database import async_session
from ...kafka.client import create_consumer
from .models import MetaAsset

logger = logging.getLogger(__name__)


async def _upsert_whatsapp_profile_name(
    db, tenant_id: str, phone: str, name: str | None
) -> None:
    """Cache the free profile name every WhatsApp webhook carries."""
    from datetime import datetime, timezone

    from ..models import ContactProfile

    if not phone or not name:
        return
    row = (
        await db.execute(
            select(ContactProfile).where(
                ContactProfile.tenant_id == tenant_id,
                ContactProfile.platform == "whatsapp",
                ContactProfile.contact_id == phone,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(ContactProfile(
            tenant_id=tenant_id,
            platform="whatsapp",
            contact_id=phone,
            name=name[:120],
            profile_fetched_at=datetime.now(timezone.utc),
        ))
    elif row.name != name[:120]:
        row.name = name[:120]
        db.add(row)


async def _refresh_instagram_profile(
    db, tenant_id: str, adapter, page_token: str, igsid: str
) -> str | None:
    """Upsert the Instagram contact cache; Graph read only when stale.

    Avatar URLs are temporary CDN links (they expire), so the profile is
    re-fetched once a week on inbound traffic. Returns the best display
    name (name, then username) or None.
    """
    from datetime import datetime, timedelta, timezone

    from ..models import ContactProfile

    row = (
        await db.execute(
            select(ContactProfile).where(
                ContactProfile.tenant_id == tenant_id,
                ContactProfile.platform == "instagram",
                ContactProfile.contact_id == igsid,
            )
        )
    ).scalar_one_or_none()
    fetched_at = row.profile_fetched_at if row else None
    stale = (
        fetched_at is None
        or fetched_at < datetime.now(timezone.utc) - timedelta(days=7)
    )
    if stale:
        fetched = await adapter.get_contact_profile(page_token, igsid)
        if row is None:
            row = ContactProfile(
                tenant_id=tenant_id,
                platform="instagram",
                contact_id=igsid,
            )
            db.add(row)
        if fetched.get("name"):
            row.name = fetched["name"][:120]
        if fetched.get("username"):
            row.username = fetched["username"][:120]
        if fetched.get("profile_pic"):
            row.avatar_url = fetched["profile_pic"][:1024]
        row.profile_fetched_at = datetime.now(timezone.utc)
        db.add(row)
    if row is None:
        return None
    return row.name or row.username

TOPIC = "meta-events"
GROUP_ID = "meta-events-replier"

# WhatsApp replies: short, human, no markdown scaffolding.
_REPLY_MAX_TOKENS = 600
_REPLY_TEMPERATURE = 0.5
_HISTORY_MESSAGES = 10
# Pace between human-style message parts so they arrive in order and read
# like a person typing, without noticeably delaying the reply.
_MESSAGE_GAP_SECONDS = 0.8


async def _resolve_asset(
    db, external_asset_id: str, provider: str = "whatsapp"
) -> MetaAsset | None:
    """Authoritative asset for an event. Kafka payloads are untrusted —
    anyone with topic access can forge tenant_id, so consumers re-resolve
    ownership from the DB and ignore the payload claim."""
    return (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.provider == provider,
                MetaAsset.external_asset_id == (external_asset_id or ""),
            )
        )
    ).scalar_one_or_none()


def _system_prompt(user, platform: str = "WhatsApp") -> str:
    """Assistant prompt grounded in the tenant's business profile."""
    name = (user.business_name or f"{user.first_name} {user.last_name}").strip()
    lines = [
        f"You are the AI customer assistant for {name}, replying on {platform}.",
    ]
    if user.business_description:
        lines.append(f"About the business: {user.business_description}")
    if user.business_sells:
        lines.append(f"What we sell: {user.business_sells}")
    if user.business_doesnt_sell:
        lines.append(f"We do NOT sell: {user.business_doesnt_sell}")
    lines += [
        "Style: you are a real human agent chatting on WhatsApp — warm, "
        "brief, 1 to 3 short sentences, plain text, no markdown. Vary your "
        "wording; never repeat the same explanation twice.",
        "Every reply moves the chat forward: after answering, ask ONE short "
        "question that helps the customer — e.g. 'What are you looking to "
        "build?', 'Shall I connect you with the team?', 'Anything else I "
        "can help you with?'. A flat statement with no question feels like "
        "a bot.",
        "If the request is outside what we offer: acknowledge it kindly in "
        "one short sentence, then pivot to what we CAN do and ask what "
        "they need. Do not lecture about what the company is.",
        "If the customer seems frustrated or confused: acknowledge it, "
        "simplify, and offer to explain by voice note or connect the team.",
        "When a customer shows interest in the services, get their details: "
        "ask their name and what they need, so the team can follow up.",
        "If the customer is clearly saying goodbye, a short warm sign-off "
        "is fine without a question.",
        "Language: reply in the language the customer wrote in "
        "(Arabic or English; match their script exactly).",
        "Never invent prices, stock, opening hours or policies you were "
        "not given — say you will confirm and offer to connect the team.",
        "Do not mention that you are an AI unless the customer asks directly.",
    ]
    return "\n".join(lines)


async def _generate_reply(
    db, channel, tenant_id: str, text: str, platform: str = "WhatsApp"
) -> str:
    """Generate an AI reply from recent conversation history + business profile.

    Raises ValueError (no model enabled) / ProviderError — callers decide how
    to surface the failure; nothing is sent on error.
    """
    from ..models import ChannelMessage
    from ...llm.providers.base import LLMMessage, LLMRequest, merge_consecutive
    from ...llm.providers.registry import get_provider_for_model
    from ...llm.service import _resolve_model, resolve_tenant_model

    model_id = await resolve_tenant_model(db)  # ValueError when nothing enabled

    rows = (
        await db.execute(
            select(ChannelMessage)
            .where(ChannelMessage.channel_id == channel.id)
            .order_by(ChannelMessage.created_at.desc())
            .limit(_HISTORY_MESSAGES)
        )
    ).scalars().all()
    # Customers fire "Hi / Hi / hello" before any reply lands — consecutive
    # same-role turns must be folded or qwen3 returns an empty completion.
    history = merge_consecutive([
        LLMMessage(
            role="user" if m.direction == "inbound" else "assistant",
            content=m.content,
        )
        for m in reversed(rows)
    ])

    from ...users.models import User

    user = (await db.execute(select(User).where(User.id == tenant_id))).scalar_one()

    # Business card (distilled from the tenant's databank) — lets the
    # assistant answer "what can you do for me?" without searching the
    # databank. Never raises; "" when no card exists yet.
    from ...profile.business_profile import prompt_block

    business_card = await prompt_block(tenant_id, db)

    api_model, _provider_key = _resolve_model(model_id)
    provider = get_provider_for_model(model_id)
    req = LLMRequest(
        model=api_model,
        messages=history,
        system_prompt=_system_prompt(user, platform=platform)
        + (f"\n\n{business_card}" if business_card else ""),
        temperature=_REPLY_TEMPERATURE,
        max_tokens=_REPLY_MAX_TOKENS,
        stream=False,
        tenant_id=tenant_id,
        model_id=model_id,
        purpose=f"{platform.lower()}.auto_reply",
        channel_id=channel.id,
    )
    resp = await provider.complete(req)
    return (resp.content or "").strip()


async def _channel_for(
    db, tenant_id: str, phone_number_id: str, display_name,
    platform: str = "whatsapp",
):
    """Get-or-create the channels row for this Meta asset (WhatsApp number
    or Instagram business account)."""
    from ..models import Channel

    channel = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == platform,
                Channel.platform_user_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        channel = Channel(
            id=str(uuid.uuid4()),
            user_id=tenant_id,
            platform=platform,
            platform_user_id=phone_number_id,
            display_name=display_name,
            status="active",
        )
        db.add(channel)
        await db.flush()
    return channel


async def _handle_message_received(event: dict, data: dict) -> None:
    """Persist the inbound message, then AI-reply + send when possible."""
    from ..models import ChannelMessage
    from .credentials import decrypt_connection_token
    from .providers.base import MetaAPIError
    from .service import get_adapter

    phone_number_id = event.get("external_asset_id") or ""
    wamid = event.get("external_event_id") or ""
    from_wa = data.get("from") or ""
    text = data.get("text")
    msg_type = data.get("msg_type") or "text"
    if msg_type == "reaction":
        text = (data.get("reaction") or {}).get("emoji") or text
    if not from_wa or not phone_number_id:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, phone_number_id)
        if asset is None:
            logger.warning(
                "Dropping whatsapp message %s for unknown asset %s",
                wamid[:32], phone_number_id,
            )
            return
        tenant_id = asset.tenant_id
        connection_id = asset.connection_id

        # Idempotent replay: Kafka redelivery must not twin the row.
        existing = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == wamid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        channel = await _channel_for(
            db, tenant_id, phone_number_id, asset.phone
        )
        row = ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                platform_message_id=wamid[:200] or None,
                direction="inbound",
                content=text if text else f"[{msg_type} message]",
                content_type=msg_type,
                status="delivered",
                contact_phone=from_wa or None,
                contact_name=data.get("profile_name") or None,
            )
        db.add(row)
        # Cache the free profile name for the inbox/contacts lists.
        await _upsert_whatsapp_profile_name(
            db, tenant_id, from_wa, data.get("profile_name")
        )
        # The customer wrote again: any pending one-shot follow-up closes —
        # nothing is owed anymore.
        from .thread_state import clear_awaiting

        await clear_awaiting(db, channel.id, from_wa)
        await db.commit()

        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(tenant_id, {
            "type": "message",
            "id": row.id,
            "channel_id": channel.id,
            "platform": "whatsapp",
            "direction": "inbound",
            "content": row.content,
            "content_type": row.content_type,
            "status": row.status,
            "contact_phone": row.contact_phone,
            "contact_name": row.contact_name,
            "created_at": row.created_at,
        })

        token = decrypt_connection_token(asset.connection) if asset.connection else None
        if not token:
            logger.info(
                "WhatsApp AI reply skipped (no access token on connection %s) "
                "wamid=%s from=+%s", connection_id, wamid[:32], from_wa[-6:],
            )
            return
        if not text or msg_type != "text":
            logger.info(
                "WhatsApp AI reply skipped for non-text message type=%s wamid=%s",
                msg_type, wamid[:32],
            )
            return

        # get_adapter returns a process-level singleton shared with the HTTP
        # routers — used in place, never closed (its httpx client lives as
        # long as the app).
        adapter = get_adapter("whatsapp")

        # Mark the inbound message read and show the typing dots while the
        # reply is prepared (classification + generation take seconds). The
        # Cloud API has no "recording audio" variant — text dots are what
        # exists. Best-effort: failure here changes nothing downstream.
        await adapter.send_typing_indicator(phone_number_id, token, wamid)

        # Conversation stats BEFORE the reply: language + confusion decide
        # whether this reply goes out as a voice note. Failure degrades to
        # the script heuristic — the text reply always still goes.
        from .thread_stats import classify_thread
        from .thread_state import apply_classification, clear_confusion

        stats = await classify_thread(db, channel.id, from_wa)
        await apply_classification(db, channel.id, from_wa, stats)
        await db.commit()
        # Rollout diagnosis: makes "why did/didn't voice fire?" answerable
        # from the logs alone (tier, and what the classifier decided).
        logger.info(
            "WhatsApp thread classified wamid=%s language=%s confused=%s "
            "awaiting=%s", wamid[:32], stats.get("language"),
            stats.get("confused"), stats.get("awaiting_user"),
        )

        try:
            reply = await _generate_reply(db, channel, tenant_id, text)
        except Exception as e:
            logger.warning(
                "WhatsApp AI reply generation failed wamid=%s: %s: %s",
                wamid[:32], type(e).__name__, str(e)[:200],
            )
            return

        if not reply:
            logger.warning(
                "WhatsApp AI reply was empty — skipping send wamid=%s from=+%s",
                wamid[:32], from_wa[-6:],
            )
            return

        # Tenant delivery config — one indexed read for both knobs: response
        # style (text shape) and voice replies tier (voice notes when the
        # customer seems confused). Missing rows/columns degrade to defaults.
        from ...users.models import User
        from .response_style import normalize_response_style, render_response
        from .voice import as_voice_note, normalize_voice_tier, synthesize_voice_note

        style_row = (
            await db.execute(
                select(User.response_style, User.voice_replies).where(
                    User.id == tenant_id
                )
            )
        ).first()
        response_style = normalize_response_style(
            style_row.response_style if style_row else None
        )
        voice_tier = normalize_voice_tier(
            style_row.voice_replies if style_row else None
        )

        # Voice escape hatch: a confused customer gets the reply as a voice
        # note in their own language. Any problem (no engine for the tier,
        # unsupported language, Meta rejection) falls back to the text path —
        # a voice failure may never cost the customer their reply.
        voice_sent = False
        confused = bool(stats.get("confused"))
        if confused and voice_tier == "off":
            # Rollout diagnosis: this is the "customer clearly confused but
            # no voice" case — the tier knob is the usual culprit.
            logger.info(
                "Voice skipped — tenant tier is OFF from=+%s wamid=%s "
                "(set it in WhatsApp channel settings)", from_wa[-6:], wamid[:32],
            )
        if voice_tier != "off" and confused:
            voice = await synthesize_voice_note(
                db, voice_tier, stats.get("language") or "en", reply,
                tenant_id=tenant_id,
            )
            if voice is not None:
                audio_bytes, mime_type = voice
                try:
                    # Meta renders only Ogg/Opus as a real voice note (mic
                    # bubble + waveform); other audio arrives as a media
                    # file. Convert when we can, send anyway when we can't.
                    audio_bytes, mime_type, is_voice = await as_voice_note(
                        audio_bytes, mime_type
                    )
                    media_id = await adapter.upload_media(
                        phone_number_id, token, audio_bytes, mime_type
                    )
                    provider_msg_id = await adapter.send_voice_note(
                        phone_number_id, token, from_wa, media_id,
                        voice=is_voice,
                    )
                except Exception as e:  # noqa: BLE001 — MetaAPIError, httpx, anything
                    # Network blips raise httpx.HTTPError, not MetaAPIError —
                    # catch everything: a voice problem may never cost the
                    # customer their reply.
                    logger.error(
                        "WhatsApp voice send failed from=+%s: %s %s — "
                        "falling back to text",
                        from_wa[-6:], type(e).__name__, str(e)[:200],
                    )
                else:
                    row = ChannelMessage(
                            id=str(uuid.uuid4()),
                            channel_id=channel.id,
                            platform_message_id=provider_msg_id[:200] or None,
                            direction="outbound",
                            content=reply,  # transcript of what was spoken
                            content_type="audio",
                            status="sent",
                            contact_phone=from_wa or None,
                        )
                    db.add(row)
                    # The voice note is the remedy for the confusion that
                    # triggered it — once delivered, the AI goes back to
                    # text mode. Fresh confusion (after this note) starts
                    # the cycle again; classify_thread also ignores history
                    # older than this note for the same reason.
                    await clear_confusion(db, channel.id, from_wa)
                    await db.commit()
                    from ...channels.realtime import publish_inbox_event as _pub

                    await _pub(tenant_id, {
                        "type": "message",
                        "id": row.id,
                        "channel_id": channel.id,
                        "platform": "whatsapp",
                        "direction": "outbound",
                        "content": row.content,
                        "content_type": row.content_type,
                        "status": "sent",
                        "contact_phone": row.contact_phone,
                        "created_at": row.created_at,
                    })
                    logger.info(
                        "WhatsApp AI voice note sent to=+%s wamid=%s "
                        "language=%s provider_msg=%s",
                        from_wa[-6:], wamid[:32], stats.get("language"),
                        provider_msg_id[:32],
                    )
                    voice_sent = True
            else:
                logger.info(
                    "Voice unavailable for tier=%s language=%s — replying "
                    "as text", voice_tier, stats.get("language"),
                )

        messages: list[str] = []
        if not voice_sent:
            # Tenant response style decides text delivery — one message, or
            # a short natural sequence. Rendering happens after reasoning
            # and never touches it: same agent, same reply, different shape.
            messages = await render_response(
                response_style, reply, tenant_id, db
            )
            if not messages:
                logger.warning(
                    "WhatsApp AI reply rendered to zero messages — skipping "
                    "send wamid=%s from=+%s", wamid[:32], from_wa[-6:],
                )
                return

            for index, part in enumerate(messages):
                try:
                    provider_msg_id = await adapter.send_text_message(
                        phone_number_id, token, from_wa, part
                    )
                except MetaAPIError as e:
                    logger.error(
                        "WhatsApp send failed from=+%s: %s %s",
                        from_wa[-6:], e.status_code, str(e)[:200],
                    )
                    db.add(
                        ChannelMessage(
                            id=str(uuid.uuid4()),
                            channel_id=channel.id,
                            direction="outbound",
                            content=part,
                            status="failed",
                            error=str(e)[:500],
                            contact_phone=from_wa or None,
                        )
                    )
                    await db.commit()
                    # Later parts would land without their context — stop.
                    return
                row = ChannelMessage(
                        id=str(uuid.uuid4()),
                        channel_id=channel.id,
                        platform_message_id=provider_msg_id[:200] or None,
                        direction="outbound",
                        content=part,
                        status="sent",
                        contact_phone=from_wa or None,
                    )
                db.add(row)
                await db.commit()
                from ...channels.realtime import publish_inbox_event as _pub2

                await _pub2(tenant_id, {
                    "type": "message",
                    "id": row.id,
                    "channel_id": channel.id,
                    "platform": "whatsapp",
                    "direction": "outbound",
                    "content": row.content,
                    "content_type": "text",
                    "status": "sent",
                    "contact_phone": row.contact_phone,
                    "created_at": row.created_at,
                })
                if index < len(messages) - 1:
                    await asyncio.sleep(_MESSAGE_GAP_SECONDS)

        # One-shot follow-up: when the reply ends by asking the customer
        # something, open the 60s window for exactly one gentle nudge
        # (armed now, closed by their next message, never sent twice).
        from .thread_state import arm_followup

        final_text = reply if voice_sent else messages[-1]
        if final_text.rstrip().endswith(("?", "؟", "?")):
            await arm_followup(db, channel.id, from_wa)
            await db.commit()

        logger.info(
            "WhatsApp AI reply sent to=+%s wamid=%s provider_msg=%s parts=%d%s",
            from_wa[-6:], wamid[:32], provider_msg_id[:32],
            1 if voice_sent else len(messages),
            " (voice)" if voice_sent else "",
        )


async def _handle_message_history(event: dict, data: dict) -> None:
    """Persist historical messages from SMB App Data sync (no AI reply)."""
    from ..models import ChannelMessage

    phone_number_id = event.get("external_asset_id") or ""
    wamid = event.get("external_event_id") or ""
    from_wa = data.get("from") or ""
    text = data.get("text")
    msg_type = data.get("msg_type") or "text"
    if msg_type == "reaction":
        text = (data.get("reaction") or {}).get("emoji") or text
    if not from_wa or not phone_number_id:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, phone_number_id)
        if asset is None:
            return
        tenant_id = asset.tenant_id

        # Idempotent: skip if already stored
        existing = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == wamid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        channel = await _channel_for(db, tenant_id, phone_number_id, asset.phone)
        row = ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            platform_message_id=wamid[:200] or None,
            direction="inbound",
            content=text if text else f"[{msg_type} message]",
            content_type=msg_type,
            status="delivered",
            contact_phone=from_wa or None,
            contact_name=data.get("profile_name") or None,
        )
        db.add(row)
        # History-synced contacts feed the inbox lists like live ones do.
        await _upsert_whatsapp_profile_name(
            db, tenant_id, from_wa, data.get("profile_name")
        )
        await db.commit()
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(tenant_id, {
            "type": "message",
            "id": row.id,
            "channel_id": channel.id,
            "platform": "whatsapp",
            "direction": "inbound",
            "content": row.content,
            "content_type": row.content_type,
            "status": "delivered",
            "contact_phone": row.contact_phone,
            "contact_name": row.contact_name,
            "created_at": row.created_at,
        })


async def _handle_message_echo(event: dict, data: dict) -> None:
    """Persist Business app echo messages as outbound (no AI reply)."""
    from ..models import ChannelMessage

    phone_number_id = event.get("external_asset_id") or ""
    wamid = event.get("external_event_id") or ""
    text = data.get("text")
    msg_type = data.get("msg_type") or "text"
    to_wa = data.get("to") or ""
    if msg_type == "reaction":
        text = (data.get("reaction") or {}).get("emoji") or text
    if not phone_number_id:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, phone_number_id)
        if asset is None:
            return
        tenant_id = asset.tenant_id

        existing = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == wamid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        channel = await _channel_for(db, tenant_id, phone_number_id, asset.phone)
        row = ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            platform_message_id=wamid[:200] or None,
            direction="outbound",
            content=text if text else f"[{msg_type} message]",
            content_type=msg_type,
            status="delivered",
            # An echo is a message the business sent from the WhatsApp app, so
            # `to` is the customer — the same contact the thread is keyed on.
            contact_phone=to_wa or None,
        )
        db.add(row)
        await db.commit()
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(tenant_id, {
            "type": "message",
            "id": row.id,
            "channel_id": channel.id,
            "platform": "whatsapp",
            "direction": "outbound",
            "content": row.content,
            "content_type": row.content_type,
            "status": row.status,
            "contact_phone": row.contact_phone,
            "created_at": row.created_at,
        })


async def _handle_smb_contacts(event: dict, data: dict) -> None:
    """Receive SMB contacts sync data. Store for future use."""
    phone_number_id = event.get("external_asset_id") or ""
    contacts = data.get("contacts", [])
    if not phone_number_id:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, phone_number_id)
        if asset is None:
            return
        # Append contacts to asset metadata (capped to avoid unbounded growth)
        existing_contacts = (asset.asset_metadata or {}).get("smb_contacts", [])
        merged = existing_contacts + contacts
        # Keep last 10000 contacts to bound JSON column size
        if len(merged) > 10000:
            merged = merged[-10000:]
        asset.asset_metadata = {
            **(asset.asset_metadata or {}),
            "smb_contacts": merged,
        }
        db.add(asset)
        # Update connection sync status
        conn = asset.connection
        if conn:
            meta = dict(conn.connection_metadata or {})
            meta["smb_sync_status"] = "contacts_received"
            conn.connection_metadata = meta
            db.add(conn)
        await db.commit()
        logger.info(
            "SMB contacts synced phone=%s count=%d",
            phone_number_id, len(contacts),
        )


async def _handle_connection_disconnect(event: dict, data: dict) -> None:
    """Handle PARTNER_REMOVED: revoke the coexistence connection."""
    phone_number_id = event.get("external_asset_id") or ""
    if not phone_number_id:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, phone_number_id)
        if asset is None:
            return
        tenant_id = asset.tenant_id
        # Delegate to the existing disconnect service
        from .service import disconnect as meta_disconnect
        await meta_disconnect(db, tenant_id, "whatsapp", revoke=False)
        logger.info(
            "WhatsApp coexistence disconnected (PARTNER_REMOVED) tenant=%s",
            tenant_id,
        )


async def _handle_message_status(event: dict, data: dict) -> None:
    """Mirror Cloud API delivery/read/failure states onto outbound rows."""
    from ..models import ChannelMessage

    provider_msg_id = event.get("external_event_id") or ""
    status = data.get("status") or ""
    if not provider_msg_id or status not in ("delivered", "read", "failed"):
        return
    async with async_session() as db:
        row = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == provider_msg_id,
                    ChannelMessage.direction == "outbound",
                )
            )
        ).scalar_one_or_none()
        if row is None or row.status in ("read", "failed"):
            return
        row.status = status
        errors = data.get("errors")
        if status == "failed" and errors:
            row.error = json.dumps(errors)[:500]
        db.add(row)
        await db.commit()
        from ...channels.realtime import publish_inbox_event

        from ..models import Channel as _Ch

        ch = await db.get(_Ch, row.channel_id)
        if ch is not None:
            await publish_inbox_event(ch.user_id, {
                "type": "status",
                "message_id": row.id,
                "channel_id": row.channel_id,
                "contact_phone": row.contact_phone,
                "status": row.status,
                "error": row.error,
            })


async def _handle_instagram_echo(event: dict, data: dict) -> None:
    """Merchant-sent DM (Meta inbox / IG app) → outbound row, no AI reply.

    Meta never echoes an app's own API sends back to it, so is_echo means
    a human replied on another surface — history, not a trigger.
    """
    from ..models import ChannelMessage

    raw = data.get("raw") or {}
    mid = event.get("external_event_id") or ""
    ig_account_id = event.get("external_asset_id") or ""
    to_contact = (raw.get("recipient") or {}).get("id") or ""
    text = (raw.get("message") or {}).get("text")
    if not ig_account_id or not to_contact:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, ig_account_id, provider="instagram")
        if asset is None:
            return
        existing = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == mid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        channel = await _channel_for(
            db, asset.tenant_id, ig_account_id, asset.username,
            platform="instagram",
        )
        db.add(ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            platform_message_id=mid[:200] or None,
            direction="outbound",
            content=text if text else "[non-text message]",
            content_type="text",
            status="sent",
            contact_phone=to_contact or None,
        ))
        await db.commit()


async def _handle_instagram_message(event: dict, data: dict) -> None:
    """Instagram DM in → persist, then AI-reply + send via the parent Page.

    Mirrors the WhatsApp handler minus voice / classification / follow-ups.
    The send rides the parent Facebook Page's token — the IG connection
    holds no usable messaging credential of its own.
    """
    from ..models import ChannelMessage
    from .providers.base import MetaAPIError
    from .providers.instagram import InstagramAdapter
    from .service import get_instagram_page_credentials

    ig_account_id = event.get("external_asset_id") or ""
    mid = event.get("external_event_id") or ""
    raw = data.get("raw") or {}
    message = raw.get("message") or {}
    text = message.get("text")
    igsid = (raw.get("sender") or {}).get("id") or ""
    # Only the messages field carries DMs to answer — messaging_handovers
    # (a human took over) and standby (a human agent owns the thread)
    # share the sender/message shape and must never trigger the AI.
    if data.get("field") != "messages":
        return
    if not ig_account_id or not igsid:
        return

    async with async_session() as db:
        asset = await _resolve_asset(db, ig_account_id, provider="instagram")
        if asset is None:
            logger.warning(
                "Dropping instagram message %s for unknown asset %s",
                mid[:32], ig_account_id,
            )
            return
        tenant_id = asset.tenant_id

        # Idempotent replay: Kafka redelivery must not twin the row.
        existing = (
            await db.execute(
                select(ChannelMessage).where(
                    ChannelMessage.platform_message_id == mid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        channel = await _channel_for(
            db, tenant_id, ig_account_id, asset.username,
            platform="instagram",
        )
        row = ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            platform_message_id=mid[:200] or None,
            direction="inbound",
            content=text if text else "[non-text message]",
            content_type="text",
            status="delivered",
            contact_phone=igsid or None,
        )
        db.add(row)
        await db.commit()
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(tenant_id, {
            "type": "message",
            "id": row.id,
            "channel_id": channel.id,
            "platform": "instagram",
            "direction": "inbound",
            "content": row.content,
            "content_type": row.content_type,
            "status": row.status,
            "contact_phone": row.contact_phone,
            "created_at": row.created_at,
        })

        page_id, page_token = await get_instagram_page_credentials(db, asset)
        if not page_id or not page_token:
            logger.info(
                "Instagram AI reply skipped (no parent Page token on asset %s) "
                "mid=%s from=+%s", ig_account_id, mid[:32], igsid[-6:],
            )
            return

        adapter = InstagramAdapter()

        # Typing dots while the reply is prepared — best-effort, exactly
        # like WhatsApp: failure here changes nothing downstream.
        await adapter.send_typing_indicator(page_id, page_token, igsid)

        # Best-effort contact profile so the inbox shows a person with a
        # face, not a bare IGSID. Cached in contact_profiles; the Graph
        # read happens only when the row is missing or stale (avatar URLs
        # are temporary CDN links — refreshed weekly on inbound traffic).
        if text:
            name = await _refresh_instagram_profile(
                db, tenant_id, adapter, page_token, igsid
            )
            row = (
                await db.execute(
                    select(ChannelMessage).where(
                        ChannelMessage.platform_message_id == mid,
                    )
                )
            ).scalar_one_or_none()
            if row is not None and not row.contact_name and name:
                row.contact_name = name[:120]
                db.add(row)
            await db.commit()

        try:
            reply = await _generate_reply(
                db, channel, tenant_id, text or "", platform="Instagram"
            )
        except Exception as e:
            logger.warning(
                "Instagram AI reply generation failed mid=%s: %s: %s",
                mid[:32], type(e).__name__, str(e)[:200],
            )
            return

        if not reply:
            logger.warning(
                "Instagram AI reply was empty — skipping send mid=%s", mid[:32],
            )
            return

        # Same response-style rendering as WhatsApp: default "concise" is a
        # single DM; multi-part styles double as defense against Meta's
        # 1000-byte per-message cap.
        from ...users.models import User
        from .response_style import normalize_response_style, render_response

        style_row = (
            await db.execute(
                select(User.response_style).where(User.id == tenant_id)
            )
        ).first()
        response_style = normalize_response_style(
            style_row.response_style if style_row else None
        )
        messages = await render_response(response_style, reply, tenant_id, db)
        if not messages:
            logger.warning(
                "Instagram AI reply rendered to zero messages — skipping "
                "send mid=%s from=+%s", mid[:32], igsid[-6:],
            )
            return

        for index, part in enumerate(messages):
            try:
                provider_msg_id = await adapter.send_text_message(
                    page_id, page_token, igsid, part
                )
            except MetaAPIError as e:
                logger.error(
                    "Instagram send failed from=+%s: %s %s",
                    igsid[-6:], e.status_code, str(e)[:200],
                )
                db.add(ChannelMessage(
                    id=str(uuid.uuid4()),
                    channel_id=channel.id,
                    direction="outbound",
                    content=part,
                    status="failed",
                    error=str(e)[:500],
                    contact_phone=igsid or None,
                ))
                await db.commit()
                # Later parts would land without their context — stop.
                return
            row = ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                platform_message_id=provider_msg_id[:200] or None,
                direction="outbound",
                content=part,
                status="sent",
                contact_phone=igsid or None,
            )
            db.add(row)
            await db.commit()
            try:
                from ...channels.realtime import publish_inbox_event as _pub3

                await _pub3(tenant_id, {
                    "type": "message",
                    "id": row.id,
                    "channel_id": channel.id,
                    "platform": "instagram",
                    "direction": "outbound",
                    "content": row.content,
                    "content_type": "text",
                    "status": "sent",
                    "contact_phone": row.contact_phone,
                    "created_at": row.created_at,
                })
            except Exception:
                pass
            if index < len(messages) - 1:
                await asyncio.sleep(_MESSAGE_GAP_SECONDS)

        logger.info(
            "Instagram AI reply sent to=+%s mid=%s parts=%d",
            igsid[-6:], mid[:32], len(messages),
        )


async def _process_message(value: bytes | None) -> None:
    if value is None:
        return
    try:
        event = json.loads(value.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Discarding malformed meta event: %s", e)
        return

    # The outbox worker sends the normalized envelope raw; accept the wrapped
    # {"event_type": "meta...", "payload": envelope} shape defensively too.
    if event.get("event_type", "").startswith("meta."):
        event = event.get("payload") or {}
    event_type = event.get("event_type", "")
    payload = event.get("payload") or {}

    try:
        provider = event.get("provider")
        if provider == "whatsapp":
            if event_type == "message.received":
                await _handle_message_received(event, payload)
            elif event_type == "message.status":
                await _handle_message_status(event, payload)
            elif event_type == "message.history":
                await _handle_message_history(event, payload)
            elif event_type == "message.echo":
                await _handle_message_echo(event, payload)
            elif event_type == "smb.contacts":
                await _handle_smb_contacts(event, payload)
            elif event_type == "connection.disconnect":
                await _handle_connection_disconnect(event, payload)
            else:
                logger.debug("Ignoring meta event type %r on %s", event_type, TOPIC)
        elif provider == "instagram":
            if event_type == "message.received":
                # Merchant replies from Meta's inbox / the IG app arrive as
                # is_echo — history, not something to auto-answer.
                if ((payload.get("raw") or {}).get("message") or {}).get("is_echo"):
                    await _handle_instagram_echo(event, payload)
                else:
                    await _handle_instagram_message(event, payload)
            else:
                logger.debug(
                    "Ignoring instagram event type %r on %s", event_type, TOPIC
                )
        else:
            # Messenger (object=page) stays parsed + ledgered, unanswered —
            # its own 24h-window/handover semantics are a later phase.
            logger.debug("Ignoring non-whatsapp meta event %r", event_type)
    except Exception as e:
        logger.exception("Failed processing %s event: %s", event_type, e)


async def _drain_outbox_events() -> int:
    """Process meta events directly from the outbox (Kafka-down fallback).

    Handlers are idempotent (platform_message_id dedupe), so events the
    outbox worker also delivers to Kafka later are safe to process twice.
    """
    from ...outbox.models import EventOutbox
    from ...outbox.service import mark_failed, mark_sent

    async with async_session() as db:
        events = (
            await db.execute(
                select(EventOutbox)
                .where(
                    EventOutbox.topic == TOPIC,
                    EventOutbox.status.in_(["pending", "failed"]),
                    EventOutbox.attempts < 10,
                )
                .order_by(EventOutbox.created_at)
                .limit(100)
            )
        ).scalars().all()
        db.expunge_all()

    sent_ids: list[str] = []
    for event in events:
        try:
            # Kafka carries event.payload (the envelope) raw — same here.
            await _process_message(json.dumps(event.payload).encode("utf-8"))
            sent_ids.append(event.id)
        except Exception as e:
            logger.warning("Outbox event %s failed: %s", event.id, e)
            await mark_failed(event.id, str(e))
    if sent_ids:
        await mark_sent(sent_ids)
    return len(sent_ids)


async def run_meta_events_consumer() -> None:
    """Background loop started from app lifespan. Kafka-first with DB-outbox
    fallback and automatic recovery, mirroring the analytics consumer."""
    from ...kafka import client as kafka_client

    fallback_logged = False
    while True:
        consumer = None
        try:
            if not kafka_client._kafka_available:
                if not fallback_logged:
                    logger.info(
                        "Kafka unavailable — meta consumer draining events from the DB outbox"
                    )
                    fallback_logged = True
                await _drain_outbox_events()
                await asyncio.sleep(3)
                continue

            fallback_logged = False
            consumer = await create_consumer(group_id=GROUP_ID, topics=[TOPIC])
            logger.info("Meta events consumer listening on %s", TOPIC)
            async for msg in consumer:
                await _process_message(msg.value)
        except asyncio.CancelledError:
            if consumer:
                await consumer.stop()
            raise
        except Exception:
            if not fallback_logged:
                logger.warning("Kafka connection failed — meta consumer switching to outbox fallback")
                fallback_logged = True
            kafka_client.mark_kafka_unavailable()
            if consumer:
                try:
                    await consumer.stop()
                except Exception:
                    pass
            await asyncio.sleep(5)