"""Per-conversation understanding: language, confusion, awaiting-user.

A small dedicated classifier call per inbound WhatsApp message — separate
from the reply generation on purpose: the reply LLM path is fragile (see
merge_consecutive) and must not be asked to produce structured output too.
This call reads the SAME recent thread history and tags it:

  language      — what the customer writes in ("en", "ar", "ur", "ps",
                  "hi", "bn", ...). Drives the voice-note language.
  confused      — the customer seems lost (short repeated questions,
                  "what??", misunderstanding the answer).
  awaiting_user — the ASSISTANT's latest message asked the customer
                  something they still owe an answer to (drives the
                  one-shot follow-up).

Everything degrades safely: any failure falls back to a script heuristic
for language and False for the two signals, so a classifier outage can
never block a reply — it only means "no voice, no follow-up".
"""
import json
import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

_CLASSIFY_MAX_TOKENS = 120
_CLASSIFY_TEMPERATURE = 0.0
_CLASSIFY_HISTORY = 10

# Language prefixes the voice pipeline knows how to speak. The classifier
# is told to pick from these so the tag always maps to a real voice.
_KNOWN_LANGUAGES = ("ar", "en", "ur", "ps", "hi", "bn")

_CLASSIFY_SYSTEM_PROMPT = (
    "You analyse one customer conversation on WhatsApp for a small "
    "business. Reply with ONLY a JSON object, no other text:\n"
    '{"language": "<code>", "confused": <bool>, "awaiting_user": <bool>}\n'
    "Rules:\n"
    f"- language: the language the CUSTOMER writes in, one of "
    f"{list(_KNOWN_LANGUAGES)}. Arabic script could be Arabic (ar), Urdu "
    "(ur) or Pashto (ps) — judge from the actual words, not the script "
    "alone.\n"
    "- confused: true when the customer seems lost or puzzled — repeated "
    "short questions, 'what?', mismatched answers, asking the same thing "
    "again after being answered. False otherwise.\n"
    "- awaiting_user: true when the ASSISTANT's most recent message asked "
    "the customer a question and the customer has not answered yet. False "
    "when the last message is from the customer or no question is open.\n"
)


def _script_language(text: str) -> str:
    """Cheap fallback when the classifier is unavailable."""
    for ch in text or "":
        code = ord(ch)
        if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
            return "ar"  # Arabic script — could be ar/ur/ps, safe default
        if 0x0900 <= code <= 0x097F:
            return "hi"
        if 0x0980 <= code <= 0x09FF:
            return "bn"
    return "en"


def parse_classification(raw: str | None) -> dict | None:
    """{language, confused, awaiting_user} from the outermost JSON object."""
    if not raw:
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    language = str(data.get("language") or "").strip().lower()
    # Accept regional tags ("ur-PK") by keeping the prefix.
    language = language.split("-", 1)[0]
    if language not in _KNOWN_LANGUAGES:
        return None
    return {
        "language": language,
        "confused": bool(data.get("confused")),
        "awaiting_user": bool(data.get("awaiting_user")),
    }


async def classify_thread(db, channel_id: str, contact_phone: str | None) -> dict:
    """The three conversation signals for this customer thread (never raises)."""
    from ...llm.providers.base import LLMMessage, LLMRequest
    from ...llm.providers.registry import get_provider_for_model
    from ...llm.service import _resolve_model, resolve_tenant_model

    rows = []
    parsed = None
    try:
        from sqlalchemy import func

        from ..models import ChannelMessage

        conditions = [ChannelMessage.channel_id == channel_id]
        if contact_phone:
            conditions.append(ChannelMessage.contact_phone == contact_phone)
        # Voice hysteresis: a voice note is the explanation for the confusion
        # that came before it — after one goes out, the customer's next
        # "okay, but..." is a fresh start, not ongoing confusion. Only what
        # they said AFTER the last voice note may re-trigger voice.
        last_voice_at = (
            await db.execute(
                select(func.max(ChannelMessage.created_at)).where(
                    ChannelMessage.channel_id == channel_id,
                    ChannelMessage.direction == "outbound",
                    ChannelMessage.content_type == "audio",
                    *(
                        [ChannelMessage.contact_phone == contact_phone]
                        if contact_phone
                        else []
                    ),
                )
            )
        ).scalar()
        if last_voice_at is not None:
            conditions.append(ChannelMessage.created_at > last_voice_at)
        rows = (
            await db.execute(
                select(ChannelMessage)
                .where(*conditions)
                .order_by(ChannelMessage.created_at.desc())
                .limit(_CLASSIFY_HISTORY)
            )
        ).scalars().all()
        transcript = "\n".join(
            f"{'Customer' if m.direction == 'inbound' else 'Assistant'}: {m.content}"
            for m in reversed(rows)
        )
        if transcript:
            model_id = await resolve_tenant_model(db)
            api_model, _provider_key = _resolve_model(model_id)
            provider = get_provider_for_model(model_id)
            req = LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=transcript)],
                system_prompt=_CLASSIFY_SYSTEM_PROMPT,
                temperature=_CLASSIFY_TEMPERATURE,
                max_tokens=_CLASSIFY_MAX_TOKENS,
                stream=False,
                model_id=model_id,
                purpose="whatsapp.thread_stats",
            )
            resp = await provider.complete(req)
            parsed = parse_classification(resp.content)
    except Exception as e:
        logger.info(
            "Thread classification failed channel=%s: %s: %s",
            channel_id[:8], type(e).__name__, str(e)[:150],
        )
        parsed = None

    if parsed is not None:
        return parsed
    # No model / parse failure / error: script heuristic on the last
    # customer message, both signals off.
    fallback_text = ""
    for m in reversed(rows):
        if m.direction == "inbound":
            fallback_text = m.content or ""
            break
    return {
        "language": _script_language(fallback_text),
        "confused": False,
        "awaiting_user": False,
    }
