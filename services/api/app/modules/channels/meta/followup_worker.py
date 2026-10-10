"""One-shot WhatsApp follow-up worker.

When the AI's reply asked a customer something, the thread state arms a
60-second window. If no message arrives from the customer in that window,
the AI sends EXACTLY ONE gentle nudge — in the customer's language, shaped
by the tenant's response style — and never nudges again until the customer
writes back (a new question re-arms the window).

DB-backed rather than an in-memory timer on purpose: worker restarts must
not lose the "did we already nudge?" fact, and the guarantee is per thread
(`followup_sent`), not per process.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ....database import async_session
from ...users.models import User
from ..models import Channel, ChannelMessage
from ..models import WhatsAppThreadState
from .models import MetaAsset
from .thread_state import _as_aware, mark_followup_sent

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15
# The spec: one minute of silence after the AI's question → one nudge.
FOLLOWUP_DELAY_SECONDS = 60
# Past this, chasing is rude — close the window without nudging.
FOLLOWUP_GIVEUP_SECONDS = 600
_MAX_BATCH = 50

_NUDGE_MAX_TOKENS = 90
_NUDGE_TEMPERATURE = 0.4

_LANG_NAMES = {
    "ar": "Arabic",
    "en": "English",
    "ur": "Urdu",
    "ps": "Pashto",
    "hi": "Hindi",
    "bn": "Bengali",
}

_NUDGE_SYSTEM_PROMPT = (
    "You write WhatsApp follow-ups for a small business. The assistant asked "
    "the customer a question about a minute ago and they haven't replied. "
    "Write ONE short gentle nudge: restate the open question in fewer words, "
    "friendly and zero pressure. Plain text, no markdown, at most one "
    "sentence, no greeting. Write it in {language} "
    "(match how the customer writes it). Reply with the message text only."
)


async def _thread_last_inbound_at(
    db, channel_id: str, contact_phone: str
) -> datetime | None:
    return (
        await db.execute(
            select(func.max(ChannelMessage.created_at)).where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.contact_phone == contact_phone,
                ChannelMessage.direction == "inbound",
            )
        )
    ).scalar()


async def _credentials_for(db, channel: Channel) -> tuple[str, str] | None:
    """(phone_number_id, token) for the channel's number — the consumer's
    ownership rules: re-resolve the asset row, never trust stale handles."""
    from .credentials import decrypt_connection_token

    phone_number_id = channel.platform_user_id
    if not phone_number_id:
        return None
    asset = (
        await db.execute(
            select(MetaAsset)
            .options(selectinload(MetaAsset.connection))
            .where(
                MetaAsset.tenant_id == channel.user_id,
                MetaAsset.provider == "whatsapp",
                MetaAsset.external_asset_id == phone_number_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None or not asset.active:
        return None
    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        return None
    return phone_number_id, token


async def _generate_nudge(
    db, channel: Channel, contact_phone: str, language: str
) -> str:
    """One gentle line restating the open question (raises on LLM failure)."""
    from ...llm.providers.base import LLMMessage, LLMRequest
    from ...llm.providers.registry import get_provider_for_model
    from ...llm.service import _resolve_model, resolve_tenant_model

    rows = (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.contact_phone == contact_phone,
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    transcript = "\n".join(
        f"{'Customer' if m.direction == 'inbound' else 'Assistant'}: {m.content}"
        for m in reversed(rows)
    )
    model_id = await resolve_tenant_model(db)
    api_model, _provider_key = _resolve_model(model_id)
    provider = get_provider_for_model(model_id)
    req = LLMRequest(
        model=api_model,
        messages=[LLMMessage(role="user", content=transcript or "…")],
        system_prompt=_NUDGE_SYSTEM_PROMPT.format(
            language=_LANG_NAMES.get(language, language)
        ),
        temperature=_NUDGE_TEMPERATURE,
        max_tokens=_NUDGE_MAX_TOKENS,
        stream=False,
        model_id=model_id,
        purpose="whatsapp.followup",
        channel_id=channel.id,
    )
    resp = await provider.complete(req)
    return (resp.content or "").strip()


async def _close_window(db, state: WhatsAppThreadState) -> None:
    """No nudge will be sent for this window — mark it so it never retries."""
    state.awaiting_since = None
    state.followup_sent = True
    db.add(state)
    await db.commit()


async def _send_followup(db, state: WhatsAppThreadState, channel: Channel) -> int:
    from .providers.whatsapp import WhatsAppAdapter
    from .response_style import normalize_response_style, render_response

    # Re-check silence after the (slow) batch work above: an inbound that
    # landed meanwhile cancels the nudge.
    last_inbound = await _thread_last_inbound_at(
        db, state.channel_id, state.contact_phone
    )
    if last_inbound and _as_aware(last_inbound) > _as_aware(state.awaiting_since):
        state.awaiting_since = None
        state.followup_sent = False
        db.add(state)
        await db.commit()
        return 0

    creds = await _credentials_for(db, channel)
    if creds is None:
        logger.info(
            "Follow-up skipped (no usable WhatsApp credentials) channel=%s",
            channel.id[:8],
        )
        await _close_window(db, state)
        return 0
    phone_number_id, token = creds

    try:
        nudge = await _generate_nudge(
            db, channel, state.contact_phone, state.language
        )
    except Exception as e:
        logger.info(
            "Follow-up generation failed channel=%s: %s: %s",
            channel.id[:8], type(e).__name__, str(e)[:120],
        )
        # A missed nudge is acceptable; hammering a failing LLM every poll
        # is not — the window closes either way.
        await _close_window(db, state)
        return 0
    if not nudge:
        await _close_window(db, state)
        return 0

    user = (
        await db.execute(select(User).where(User.id == channel.user_id))
    ).scalar_one_or_none()
    style = normalize_response_style(user.response_style if user else None)
    parts = await render_response(style, nudge, channel.user_id, db) or [nudge]

    adapter = WhatsAppAdapter()
    sent_any = False
    for index, part in enumerate(parts):
        try:
            await adapter.send_text_message(
                phone_number_id, token, state.contact_phone, part
            )
        except Exception as e:  # noqa: BLE001 — MetaAPIError, httpx, anything
            # A network blip must not leave the window armed — the nudge is
            # one-shot even when the send fails.
            logger.warning(
                "Follow-up send failed contact=+%s: %s %s",
                state.contact_phone[-6:], type(e).__name__, str(e)[:150],
            )
            break
        row = ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                direction="outbound",
                content=part,
                status="sent",
                contact_phone=state.contact_phone,
            )
        db.add(row)
        await db.commit()
        try:
            from ...channels.realtime import publish_inbox_event

            await publish_inbox_event(channel.user_id, {
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
        except Exception:
            pass
        sent_any = True
        if index < len(parts) - 1:
            await asyncio.sleep(0.8)

    await mark_followup_sent(db, state)
    if sent_any:
        logger.info(
            "WhatsApp follow-up sent channel=%s contact=+%s language=%s",
            channel.id[:8], state.contact_phone[-6:], state.language,
        )
    return 1 if sent_any else 0


async def process_due_followups() -> int:
    """Nudge every thread whose 60s window closed. Returns how many sent."""
    now = datetime.now(timezone.utc)
    sent = 0
    async with async_session() as db:
        rows = (
            await db.execute(
                select(WhatsAppThreadState, Channel, User)
                .join(Channel, Channel.id == WhatsAppThreadState.channel_id)
                .join(User, User.id == Channel.user_id)
                .where(
                    WhatsAppThreadState.awaiting_since.is_not(None),
                    WhatsAppThreadState.followup_sent.is_(False),
                )
                .limit(_MAX_BATCH)
            )
        ).all()

        due: list[tuple[WhatsAppThreadState, Channel]] = []
        for state, channel, _user in rows:
            awaiting = _as_aware(state.awaiting_since)
            if awaiting is None:
                continue
            age = (now - awaiting).total_seconds()
            if age < FOLLOWUP_DELAY_SECONDS:
                continue
            # The customer may have answered between the event that armed
            # this and this poll — their reply always wins.
            last_inbound = await _thread_last_inbound_at(
                db, state.channel_id, state.contact_phone
            )
            if last_inbound and _as_aware(last_inbound) > awaiting:
                state.awaiting_since = None
                db.add(state)
                continue
            if age > FOLLOWUP_GIVEUP_SECONDS:
                # Silence for ten minutes: close the window, no nudge.
                await _close_window(db, state)
                continue
            due.append((state, channel))
        await db.commit()

        for state, channel in due:
            try:
                sent += await _send_followup(db, state, channel)
            except Exception as e:
                logger.warning(
                    "Follow-up failed channel=%s contact=%s: %s: %s",
                    channel.id[:8], state.contact_phone[-6:],
                    type(e).__name__, str(e)[:150],
                )
    return sent


async def run_followup_worker() -> None:
    while True:
        try:
            await process_due_followups()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Follow-up worker cycle failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
