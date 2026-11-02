"""The assistant's fixed sticker pack and acknowledgement reactions.

The model never draws or generates art. When a sticker says it better than
words it appends a hidden marker (``[[sticker:ok]]``); the pipeline strips the
marker and uploads the matching bundled WebP. Bare acknowledgements ("thanks",
"ok", "done") get an emoji reaction instead of a paragraph — but only when the
last thing the business said was not a question, because "ok" is a real answer
to "shall I book it?".

The pack is original and deterministic: regenerate it with
``python services/api/scripts/generate_sticker_pack.py``.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from .models import ChannelMessage
from .service import (
    decrypt_message_content,
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)

logger = logging.getLogger(__name__)

STICKER_DIR = Path(__file__).parent / "meta" / "assets" / "stickers"


@dataclass(frozen=True)
class Sticker:
    key: str
    label: str
    filename: str
    fallback: str


PACK: dict[str, Sticker] = {
    "ok": Sticker("ok", "OK", "ok.webp", "OK 👍"),
    "thanks": Sticker("thanks", "Thanks", "thanks.webp", "Thanks! 🙏"),
    "done": Sticker("done", "Done", "done.webp", "Done ✅"),
}

_MARKER_RE = re.compile(r"\[\[\s*sticker\s*:\s*(ok|thanks|done)\s*\]\]", re.IGNORECASE)

# WhatsApp reactions accept one emoji. What each acknowledgement means is
# deliberately fixed, so the same message always gets the same reaction.
_OK_REACTIONS = {"👍", "👌", "🆗"}
_THANKS_REACTIONS = {"🙏", "❤️", "❤", "💜", "🤍"}
_DONE_REACTIONS = {"✅", "☑️", "✔️", "✔"}

_OK_WORDS = {
    "ok", "okay", "okey", "k", "kk", "alright", "all right", "fine",
    "got it", "gotcha", "noted", "understood", "sure", "yes", "yeah", "yep",
    "yup", "haan", "han", "theek hai", "thik hai", "اوکے", "ٹھیک", "ٹھیک ہے",
}
_THANKS_WORDS = {
    "thanks", "thank you", "thank u", "thanks a lot", "thank you so much",
    "thx", "ty", "shukriya", "shukria", "jazakallah", "jazak allah",
    "jazak allah khair", "جزاک اللہ", "جزاک اللہ خیر", "شکریہ", "بہت شکریہ",
    "شكرا", "شكراً", "جزاك الله", "جزاك الله خير",
}
_DONE_WORDS = {
    "done", "finished", "complete", "completed", "all done", "ho gaya",
    "hogaya", "ہو گیا", "ہوگیا", "خلص", "انتهى",
}

_PUNCTUATION = "!.?,،؛…\"'`~*_"


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").strip().lower()
    # Arabic/Urdu harakat and Latin accents are decoration: "شُكْرًا" must
    # match the same acknowledgement as "شكرا".
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.translate(str.maketrans("", "", _PUNCTUATION))
    return re.sub(r"\s+", " ", value)


def reaction_for_ack(text: str | None) -> str | None:
    """The reaction for a bare acknowledgement, or None.

    Only short, content-free messages qualify. A sentence that happens to
    contain "thanks" is a real message and goes to the assistant.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if raw in _OK_REACTIONS:
        return "👍"
    if raw in _THANKS_REACTIONS:
        return "❤️"
    if raw in _DONE_REACTIONS:
        return "✅"

    value = _normalize(raw)
    if not value or len(value.split()) > 4:
        return None
    if value in _OK_WORDS:
        return "👍"
    if value in _THANKS_WORDS:
        return "❤️"
    if value in _DONE_WORDS:
        return "✅"
    return None


def split_sticker_marker(reply: str) -> tuple[str, str | None]:
    """Strip every sticker marker and return the first requested key."""
    keys = [match.group(1).lower() for match in _MARKER_RE.finditer(reply or "")]
    clean = _MARKER_RE.sub("", reply or "")
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, (keys[0] if keys else None)


def sticker_fallback_text(key: str | None) -> str | None:
    spec = PACK.get(key or "")
    return spec.fallback if spec else None


def load_sticker(key: str) -> tuple[Sticker, bytes]:
    spec = PACK.get(key)
    if spec is None:
        raise ValueError(f"Unknown sticker: {key}")
    data = (STICKER_DIR / spec.filename).read_bytes()
    if not data:
        raise ValueError(f"Sticker asset is empty: {spec.filename}")
    return spec, data


async def should_react_instead_of_reply(
    db, channel_id: str, contact_phone: str
) -> bool:
    """True when the customer is closing the loop, not answering a question.

    "Thanks" after a completed answer deserves a reaction. "OK" after "Shall I
    book the Makkah branch?" is an answer and must reach the assistant, so the
    last delivered outbound text decides.
    """
    row = (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.direction == "outbound",
                ChannelMessage.contact_phone_hash == hash_contact_phone(
                    contact_phone
                ),
                ChannelMessage.status.in_(("sent", "delivered")),
                ChannelMessage.deleted_at.is_(None),
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        return False
    text = (decrypt_message_content(row.content) or "").strip()
    return not text.endswith(("?", "؟"))


async def send_ai_reaction(
    db,
    *,
    channel,
    contact_phone: str,
    target_message_id: str,
    emoji: str,
    phone_number_id: str,
    token: str,
    adapter,
) -> ChannelMessage | None:
    """React to the customer's message; a failure is logged, never raised.

    A reaction is a courtesy on top of the conversation. Losing one must not
    turn into a failed inbound reply or a retry storm.
    """
    if not target_message_id:
        return None
    row = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        direction="outbound",
        content=encrypt_message_content(emoji),
        content_type="reaction",
        status="sent",
        contact_phone=encrypt_contact_phone(contact_phone or None),
        contact_phone_hash=hash_contact_phone(contact_phone or None),
        is_ai=True,
        handled_by="ai",
        reply_to_message_id=target_message_id[:200],
    )
    try:
        provider_id = await adapter.send_reaction(
            phone_number_id, token, contact_phone, target_message_id, emoji
        )
    except Exception as exc:  # noqa: BLE001 - courtesy, not a delivery
        logger.warning(
            "AI reaction failed channel=%s emoji=%s: %s: %s",
            channel.id, emoji, type(exc).__name__, str(exc)[:200],
        )
        return None
    row.platform_message_id = (provider_id or "")[:200] or None
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _publish_row(channel, row)
    return row


async def send_pack_sticker(
    db,
    *,
    channel,
    tenant_id: str,
    contact_phone: str,
    key: str,
    phone_number_id: str,
    token: str,
    adapter,
    reply_to: str | None = None,
    fallback_text: str | None = None,
) -> ChannelMessage:
    """Store, upload and send one bundled sticker.

    ``fallback_text`` is used when the sticker itself cannot be sent and the
    model had no other words for the customer — silence is the one outcome we
    refuse. When the reply already carried text, no fallback is needed.
    """
    spec, data = load_sticker(key)
    storage_key = f"{uuid.uuid4().hex}.webp"
    row = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        direction="outbound",
        content=encrypt_message_content(f"Sticker: {spec.label}"),
        content_type="sticker",
        status="sent",
        contact_phone=encrypt_contact_phone(contact_phone or None),
        contact_phone_hash=hash_contact_phone(contact_phone or None),
        media_key=storage_key,
        media_mime_type="image/webp",
        media_filename=spec.filename,
        is_ai=True,
        handled_by="ai",
        reply_to_message_id=(reply_to or "")[:200] or None,
    )

    # The inbox copy is a convenience; the customer's sticker is not. A
    # storage failure hides the preview but must not cancel the send.
    try:
        from ...core.storage import put_doc

        put_doc(f"inbox-{tenant_id}", storage_key, data)
    except Exception as exc:  # noqa: BLE001 - send continues without a preview
        logger.warning(
            "AI sticker store failed channel=%s key=%s: %s: %s",
            channel.id, key, type(exc).__name__, str(exc)[:200],
        )
        row.media_key = None

    try:
        media_id = await adapter.upload_media(
            phone_number_id, token, data, "image/webp",
            filename=spec.filename,
        )
        if not media_id:
            raise RuntimeError("WhatsApp returned no media id for the sticker")
        provider_id = await adapter.send_sticker(
            phone_number_id, token, contact_phone, media_id
        )
    except Exception as exc:  # noqa: BLE001 - fallback handled below
        logger.warning(
            "AI sticker send failed channel=%s key=%s: %s: %s",
            channel.id, key, type(exc).__name__, str(exc)[:200],
        )
        if fallback_text:
            return await _send_text_fallback(
                db,
                channel=channel,
                contact_phone=contact_phone,
                text=fallback_text,
                phone_number_id=phone_number_id,
                token=token,
                adapter=adapter,
                reply_to=reply_to,
                error=str(exc)[:500],
            )
        row.status = "failed"
        row.error = str(exc)[:500]
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    row.platform_message_id = (provider_id or "")[:200] or None
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _publish_row(channel, row)
    return row


async def _send_text_fallback(
    db,
    *,
    channel,
    contact_phone: str,
    text: str,
    phone_number_id: str,
    token: str,
    adapter,
    reply_to: str | None,
    error: str,
) -> ChannelMessage:
    """One plain-text line when a sticker-only reply could not be delivered."""
    row = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel.id,
        direction="outbound",
        content=encrypt_message_content(text),
        content_type="text",
        status="sent",
        contact_phone=encrypt_contact_phone(contact_phone or None),
        contact_phone_hash=hash_contact_phone(contact_phone or None),
        is_ai=True,
        handled_by="ai",
        reply_to_message_id=(reply_to or "")[:200] or None,
    )
    try:
        provider_id = await adapter.send_text_message(
            phone_number_id, token, contact_phone, text,
            context_message_id=reply_to,
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the row
        row.status = "failed"
        row.error = f"sticker failed ({error}); text fallback failed: {exc}"[:500]
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
    row.platform_message_id = (provider_id or "")[:200] or None
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _publish_row(channel, row)
    return row


async def _publish_row(channel, row: ChannelMessage) -> None:
    from .realtime import publish_inbox_event

    await publish_inbox_event(channel.user_id, {
        "type": "message",
        "id": row.id,
        "channel_id": channel.id,
        "platform": channel.platform,
        "direction": "outbound",
        "content": decrypt_message_content(row.content),
        "content_type": row.content_type,
        "status": row.status,
        "contact_phone": contact_phone_for(row),
        "created_at": row.created_at,
    })


def contact_phone_for(row: ChannelMessage) -> str | None:
    from .service import decrypt_contact_phone

    return decrypt_contact_phone(row.contact_phone)
