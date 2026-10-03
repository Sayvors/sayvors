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

TOPIC = "meta-events"
GROUP_ID = "meta-events-replier"

# WhatsApp replies: short, human, no markdown scaffolding.
_REPLY_MAX_TOKENS = 600
_REPLY_TEMPERATURE = 0.5
_HISTORY_MESSAGES = 10


async def _resolve_asset(db, external_asset_id: str) -> MetaAsset | None:
    """Authoritative asset for an event. Kafka payloads are untrusted —
    anyone with topic access can forge tenant_id, so consumers re-resolve
    ownership from the DB and ignore the payload claim."""
    return (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.provider == "whatsapp",
                MetaAsset.external_asset_id == (external_asset_id or ""),
            )
        )
    ).scalar_one_or_none()


def _system_prompt(user) -> str:
    """WhatsApp assistant prompt grounded in the tenant's business profile."""
    name = (user.business_name or f"{user.first_name} {user.last_name}").strip()
    lines = [
        f"You are the AI customer assistant for {name}, replying on WhatsApp.",
    ]
    if user.business_description:
        lines.append(f"About the business: {user.business_description}")
    if user.business_sells:
        lines.append(f"What we sell: {user.business_sells}")
    if user.business_doesnt_sell:
        lines.append(f"We do NOT sell: {user.business_doesnt_sell}")
    lines += [
        "Style: concise and human — 1 to 4 short sentences, plain text "
        "(WhatsApp), no markdown formatting, at most one question.",
        "Language: reply in the language the customer wrote in "
        "(Arabic or English; match their script exactly).",
        "Never invent prices, stock, opening hours or policies you were "
        "not given — say you will confirm and offer to connect the team.",
        "Do not mention that you are an AI unless the customer asks directly.",
    ]
    return "\n".join(lines)


async def _generate_reply(db, channel, tenant_id: str, text: str) -> str:
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
        system_prompt=_system_prompt(user)
        + (f"\n\n{business_card}" if business_card else ""),
        temperature=_REPLY_TEMPERATURE,
        max_tokens=_REPLY_MAX_TOKENS,
        stream=False,
        tenant_id=tenant_id,
        model_id=model_id,
        purpose="whatsapp.auto_reply",
        channel_id=channel.id,
    )
    resp = await provider.complete(req)
    return (resp.content or "").strip()


async def _channel_for(db, tenant_id: str, phone_number_id: str, display_name):
    """Get-or-create the channels row for this WhatsApp number."""
    from ..models import Channel

    channel = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == "whatsapp",
                Channel.platform_user_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        channel = Channel(
            id=str(uuid.uuid4()),
            user_id=tenant_id,
            platform="whatsapp",
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
        db.add(
            ChannelMessage(
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
        )
        await db.commit()

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

        # get_adapter returns a process-level singleton shared with the HTTP
        # routers — used in place, never closed (its httpx client lives as
        # long as the app).
        adapter = get_adapter("whatsapp")
        try:
            provider_msg_id = await adapter.send_text_message(
                phone_number_id, token, from_wa, reply
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
                    content=reply,
                    status="failed",
                    error=str(e)[:500],
                    contact_phone=from_wa or None,
                )
            )
            await db.commit()
            return

        db.add(
            ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                platform_message_id=provider_msg_id[:200] or None,
                direction="outbound",
                content=reply,
                status="sent",
                contact_phone=from_wa or None,
            )
        )
        await db.commit()
        logger.info(
            "WhatsApp AI reply sent to=+%s wamid=%s provider_msg=%s",
            from_wa[-6:], wamid[:32], provider_msg_id[:32],
        )


async def _handle_message_history(event: dict, data: dict) -> None:
    """Persist historical messages from SMB App Data sync (no AI reply)."""
    from ..models import ChannelMessage

    phone_number_id = event.get("external_asset_id") or ""
    wamid = event.get("external_event_id") or ""
    from_wa = data.get("from") or ""
    text = data.get("text")
    msg_type = data.get("msg_type") or "text"
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
        db.add(ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            platform_message_id=wamid[:200] or None,
            direction="inbound",
            content=text if text else f"[{msg_type} message]",
            content_type=msg_type,
            status="delivered",
            contact_phone=from_wa or None,
            contact_name=data.get("profile_name") or None,
        ))
        await db.commit()


async def _handle_message_echo(event: dict, data: dict) -> None:
    """Persist Business app echo messages as outbound (no AI reply)."""
    from ..models import ChannelMessage

    phone_number_id = event.get("external_asset_id") or ""
    wamid = event.get("external_event_id") or ""
    text = data.get("text")
    msg_type = data.get("msg_type") or "text"
    to_wa = data.get("to") or ""
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
        db.add(ChannelMessage(
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
        ))
        await db.commit()


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
        if event.get("provider") != "whatsapp":
            logger.debug("Ignoring non-whatsapp meta event %r", event_type)
        elif event_type == "message.received":
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