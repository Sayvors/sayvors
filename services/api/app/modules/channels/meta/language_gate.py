"""First-contact language choice.

A brand-new WhatsApp conversation opens with three reply buttons — English,
العربية, اردو — and the answer is the note that everything (text and voice)
will be in the selected language. The choice is stored per thread and then
enforced: the model is told to write only that language, and the voice-note
path speaks it, even if the customer later writes in another one.

Rules that keep this from being annoying:
  * the prompt is sent only when this contact has never had an outbound
    message on this channel (so it is genuinely the first reply);
  * if the customer ignores it, the next message is answered normally — the
    gate never blocks a conversation waiting for a tap;
  * a tap (the label arrives as ordinary text) is recognised in English and
    native script.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# (label shown on the button, BCP-47 code). Order is the button order.
LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("English", "en"),
    ("العربية", "ar"),
    ("اردو", "ur"),
)

LANGUAGE_NAMES: dict[str, str] = {"en": "English", "ar": "Arabic", "ur": "Urdu"}

PROMPT_BODY = (
    "Welcome! Choose the language for this conversation — text and voice "
    "notes will be in the language you pick.\n\n"
    "أهلاً بك! اختر لغة المحادثة — ستكون الرسائل النصية والرسائل الصوتية "
    "باللغة التي تختارها.\n\n"
    "خوش آمدید! اس گفتگو کی زبان منتخب کریں — پیغامات اور وائس نوٹس اسی "
    "زبان میں ہوں گے۔"
)

CONFIRMATION: dict[str, str] = {
    "en": "Great — we'll continue in English. How can I help?",
    "ar": "رائع — سنكمل بالعربية. كيف يمكنني مساعدتك؟",
    "ur": "بہت خوب — ہم اردو میں بات کریں گے۔ میں آپ کی کیا مدد کر سکتا ہوں؟",
}

# What a customer might type/tap instead of the exact button label.
_LABEL_ALIASES: dict[str, str] = {
    "english": "en",
    "eng": "en",
    "en": "en",
    "arabic": "ar",
    "ar": "ar",
    "العربية": "ar",
    "عربي": "ar",
    "عربى": "ar",
    "urdu": "ur",
    "ur": "ur",
    "اردو": "ur",
}


def language_from_label(text: str | None) -> str | None:
    """The language a reply label/alias refers to, else None."""
    if not text:
        return None
    cleaned = text.strip().strip(".!؟?،,").strip().lower()
    return _LABEL_ALIASES.get(cleaned)


def language_block(preferred: str | None) -> str:
    """Prompt block that pins the reply language. "" when no choice is set."""
    if not preferred:
        return ""
    name = LANGUAGE_NAMES.get(preferred)
    if not name:
        return ""
    return (
        f"LANGUAGE LOCK: the customer chose {name} at the start of this "
        f"conversation. Write EVERY reply in {name} only — this overrides the "
        f"'reply in the language the customer wrote in' rule. If they write "
        f"in another language, still answer in {name}."
    )


async def prompt_once(db, channel_id: str, contact_phone: str) -> bool:
    """True when this contact has never received an outbound message here.

    The language prompt is a reply to a brand-new conversation, not a
    greeting bolted onto an existing one. Counting outbound rows is the
    durable signal: a failed earlier prompt wrote no row, so it retries,
    while any human/AI reply means the conversation already started.
    """
    from sqlalchemy import func, select

    from ...channels.service import hash_contact_phone
    from ..models import ChannelMessage

    count = (
        await db.execute(
            select(func.count())
            .select_from(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.direction == "outbound",
                ChannelMessage.contact_phone_hash == hash_contact_phone(contact_phone),
            )
        )
    ).scalar() or 0
    return count == 0
