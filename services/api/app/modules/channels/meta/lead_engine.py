"""Lead capture and follow-up scheduling: deterministic, zero-LLM logic.

Extraction rides the reply call the messaging loop already makes: the
model may append one final ``LEAD: {json}`` line when the customer
volunteered something worth keeping; the reply itself is split off before
the customer ever sees it. Everything else here — validation, stage
transitions, scheduling, quiet hours, nudge text — is plain application
logic. The dispatcher worker NEVER calls an LLM: nudges come from
localized templates over stored fields.

Cost law: no LLM for scheduling, timers, lead-state transitions, retry
decisions, phone validation, or follow-up eligibility. A scheduling bug
must be debuggable in a database row, not in a prompt.
"""
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ...channels.service import hash_contact_phone
from ..models import ChannelMessage, Lead, LeadAction

logger = logging.getLogger(__name__)

LEAD_LINE_PREFIX = "LEAD:"

# Appended to the reply system prompt. The model is asked to SILENTLY tag
# the reply; parsing/validation/scheduling all happen in this module.
LEAD_PROMPT_BLOCK = (
    "LEAD CAPTURE (silent, never mention it): if the customer expressed "
    "buying or booking interest, asked for pricing, described what they "
    "need, or shared their name or phone number, END YOUR REPLY with ONE "
    "final line exactly like:\n"
    'LEAD: {"category": "wholesale|retail|booking|quote|support|info", '
    '"intent": "buying|booking|quote|info", "request": "<what they need, '
    'in their words>", "summary": "<one short sentence: what THIS customer '
    'wants so far>", "name": "<name if they gave it>", "phone": "<phone '
    'only if the customer typed it>", "confidence": <0.0-1.0>}\n'
    "category is the ONE label a human should see: wholesale = buying in "
    "bulk to resell or for a business, retail = one person buying for "
    "themselves, booking = an appointment or reservation, quote = asked "
    "for a price but not yet clearly retail or wholesale, support = an "
    "existing customer needs help or complains, info = just asking or "
    "exploring. Keep summary current with the WHOLE conversation, not just "
    "this message, and include it whenever the chat has any substance. Omit "
    "any other field you were not given. Omit the whole line when there "
    "is nothing to record. Never invent facts. Never mention this line."
)

_LEAD_ALLOWED_INTENTS = ("buying", "booking", "quote", "info")

# One canonical taxonomy for every surface. `intent` could not express
# wholesale, so the UI grew ad-hoc labels; these values are stored once and
# rendered verbatim by the inbox, lead card, digest and escalation email.
LEAD_CATEGORIES = ("wholesale", "retail", "booking", "quote", "support", "info")
LEAD_CATEGORY_LABELS = {
    "wholesale": "Wholesale",
    "retail": "Retail",
    "booking": "Booking",
    "quote": "Quote",
    "support": "Support",
    "info": "Info",
}
# Categories that count as a sales opportunity by default. info and support
# are tracked but stay `new`: a question and a complaint are not a deal.
DEFAULT_QUALIFIED_CATEGORIES = ("retail", "wholesale", "booking", "quote")
_LEAD_ALLOWED_CATEGORIES = frozenset(LEAD_CATEGORIES)


def category_label(category: str | None) -> str | None:
    """Display form of a stored category; None when unset or unknown."""
    return LEAD_CATEGORY_LABELS.get((category or "").strip().lower())

# ── tenant settings ──────────────────────────────────────────────────
# Conservative defaults per the brief: first nudge inside 5-15 minutes,
# second ~24h, final ~72h, hard attempt cap, quiet hours late night.
SETTINGS_DEFAULTS = {
    "enabled": True,
    "first_nudge_minutes": 8,
    "second_followup_hours": 24,
    "final_followup_hours": 72,
    "max_attempts": 3,
    "quiet_start_hour": 22,
    "quiet_end_hour": 8,
    "timezone": "UTC",
    # ── Escalation ────────────────────────────────────────────────────
    # Per-tenant, so an owner can tune how quickly a struggling thread is
    # pulled off the AI and how long it stays muted before being handed back.
    # 0 = never escalate on the counter. The counter only moves when the
    # customer comes back confused, so a normal question-and-answer thread
    # never escalates; an explicitly urgent message always does.
    "escalation_threshold": 0,
    "escalation_resume_hours": 24,
    "escalation_reminder_hours": 4,
    # Empty = escalate to the tenant owner's own signup email.
    "escalation_emails": [],
    # Pending-leads digest. Off by default: a summary nobody asked for is
    # worse than none, and it is a new outbound email to a tenant's inbox.
    # Opt-in per tenant, then at most one per local day.
    "digest_enabled": False,
    # Local hour the digest goes out. Paired with the tenant's own timezone so
    # it lands in the morning rather than at 03:00 UTC.
    "digest_hour": 8,
    # How many leads one digest may list, so a large tenant gets a summary
    # rather than a wall of names.
    "digest_max_leads": 20,
    # Categories that auto-qualify a captured lead. This is the per-tenant
    # stage rule: a tenant that only sells wholesale can drop retail/booking
    # from the set without renaming a single label.
    "qualified_categories": list(DEFAULT_QUALIFIED_CATEGORIES),
    "review_issue_subcategories": [],
}

_INT_KEYS = (
    "first_nudge_minutes",
    "second_followup_hours",
    "final_followup_hours",
    "max_attempts",
    "quiet_start_hour",
    "quiet_end_hour",
    "escalation_threshold",
    "escalation_resume_hours",
    "escalation_reminder_hours",
    "digest_hour",
    "digest_max_leads",
)
# Sanity clamps: a tenant can delay or soften nudges, never spam (max 4
# attempts) or disable the safety properties. max_attempts=0 turns the
# whole sequence off — an explicit, validated choice.
_INT_CLAMP = {
    "first_nudge_minutes": (5, 60),
    "second_followup_hours": (2, 168),
    "final_followup_hours": (12, 336),
    "max_attempts": (0, 4),
    "quiet_start_hour": (0, 23),
    "quiet_end_hour": (0, 23),
    # Escalation floor of 0: 0 disables the confusion counter entirely, which
    # is the default. A tenant that wants the safety net sets 1-10. The
    # counter moved to "customer came back confused" so a healthy
    # question-and-answer thread never trips it.
    "escalation_threshold": (0, 10),
    # A resume window of 0 would mute the thread and hand it straight back,
    # making the handover pointless.
    "escalation_resume_hours": (1, 336),
    "escalation_reminder_hours": (1, 72),
    # Local hour the digest goes out, in the tenant's own timezone.
    "digest_hour": (0, 23),
    # The digest is a rollup, so a cap keeps the email readable rather than
    # letting a busy tenant's inbox decide the length.
    "digest_max_leads": (1, 100),
}


def normalize_lead_settings(raw: dict | None) -> dict:
    """Whitelist + clamp tenant input. Never raises; junk -> defaults.

    Only these knobs exist — arbitrary prompts, expressions, or content
    are not settings, so they are simply dropped here.
    """
    settings = dict(SETTINGS_DEFAULTS)
    # The default list is shared by every call; copy it so a caller that
    # mutates the returned settings cannot change the module defaults.
    settings["qualified_categories"] = list(DEFAULT_QUALIFIED_CATEGORIES)
    if not isinstance(raw, dict):
        return settings
    settings["enabled"] = bool(raw.get("enabled", True))
    # Opt-in, and absent must mean off: a deploy that turned this on by
    # default would start mailing every tenant who never asked.
    settings["digest_enabled"] = bool(raw.get("digest_enabled", False))
    for key in _INT_KEYS:
        try:
            value = int(raw.get(key, settings[key]))
        except (TypeError, ValueError):
            continue
        lo, hi = _INT_CLAMP[key]
        settings[key] = max(lo, min(hi, value))
    tz = str(raw.get("timezone") or "UTC")
    try:
        ZoneInfo(tz)
        settings["timezone"] = tz
    except Exception:
        pass
    # Review-issue subcategories the tenant cares about (used to classify
    # Google reviews and to scope WhatsApp handoff context). Stick to a small
    # list and deduplicate so a tenant cannot bloat storage indefinitely.
    raw_subs = raw.get("review_issue_subcategories")
    if isinstance(raw_subs, list):
        cleaned_subs = []
        seen = set()
        for e in raw_subs:
            if isinstance(e, str) and e.strip():
                k = e.strip().lower()
                if k not in seen:
                    seen.add(k)
                    cleaned_subs.append(k)
        settings["review_issue_subcategories"] = cleaned_subs[:40]
    raw_emails = raw.get("escalation_emails")
    if isinstance(raw_emails, list):
        cleaned = [
            e.strip().lower()
            for e in raw_emails
            if isinstance(e, str) and e.strip()
        ]
        # Sorted + de-duplicated so two runs with the same input send the same
        # mail, and capped so a tenant cannot mail a whole address book.
        settings["escalation_emails"] = sorted(set(cleaned))[:10]
    raw_qualified = raw.get("qualified_categories")
    if isinstance(raw_qualified, list):
        cleaned_categories: list[str] = []
        seen_categories: set[str] = set()
        for value in raw_qualified:
            if not isinstance(value, str):
                continue
            key = value.strip().lower()
            if key in _LEAD_ALLOWED_CATEGORIES and key not in seen_categories:
                seen_categories.add(key)
                cleaned_categories.append(key)
        # An empty or wholly invalid list is a misconfiguration, not a
        # request to stop qualifying every lead. Falling back to the defaults
        # keeps one bad save from silently disabling the whole lead pipeline.
        settings["qualified_categories"] = (
            cleaned_categories or list(DEFAULT_QUALIFIED_CATEGORIES)
        )
    return settings


# ── extraction parsing (the deterministic half of the reply call) ────

def split_reply_and_lead(raw: str | None) -> tuple[str, dict | None]:
    """Split the model's reply from a trailing LEAD extraction line.

    The customer-visible reply stays byte-identical when the model emits
    no LEAD line (or a malformed one): malformed lines are ignored, never
    fatal, and a mid-reply "LEAD:" that doesn't end in valid JSON passes
    through untouched.
    """
    if not raw:
        return "", None
    text = raw.strip()
    idx = text.rfind(LEAD_LINE_PREFIX)
    if idx == -1:
        return text, None
    delta = _parse_lead_delta(text[idx + len(LEAD_LINE_PREFIX):].strip())
    if delta is None:
        return text, None
    return text[:idx].strip(), delta


def _parse_lead_delta(tail: str | None) -> dict | None:
    """Whitelisted {category, intent, request, name, phone, confidence} or None.

    Everything else the model may have put in the JSON is dropped on the
    floor: model output is data, never configuration.
    """
    if not tail:
        return None
    start, end = tail.find("{"), tail.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(tail[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    delta: dict = {}
    category = str(data.get("category") or "").strip().lower()
    if category in _LEAD_ALLOWED_CATEGORIES:
        delta["category"] = category
    intent = str(data.get("intent") or "").strip().lower()
    if intent in _LEAD_ALLOWED_INTENTS:
        delta["intent"] = intent
    request = str(data.get("request") or "").strip()
    if request:
        delta["request"] = request[:500]
    summary = str(data.get("summary") or "").strip()
    if summary:
        delta["summary"] = summary[:300]
    name = str(data.get("name") or "").strip()
    if name:
        delta["name"] = name[:120]
    phone = validate_phone(str(data.get("phone") or "").strip())
    if phone:
        delta["phone"] = phone
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    delta["confidence"] = max(0.0, min(1.0, confidence))
    # confidence alone carries no information — nothing was captured.
    return delta if len(delta) > 1 else None


# ── phone validation (never guess a country) ─────────────────────────

try:
    import phonenumbers as _pn
except ImportError:  # pragma: no cover - the dep ships in pyproject
    _pn = None

# Fallback only fires if the library is somehow missing: a strict,
# international-shape check that still refuses to guess a region.
_PHONE_FALLBACK_RE = re.compile(r"^\+[0-9][0-9 \-()\.]{5,20}[0-9]$")


def validate_phone(raw: str | None) -> str | None:
    """E.164 or None. NEVER guesses a country: phonenumbers parses with
    ``region=None``, so only an unambiguous international form passes —
    a bare local number stays None rather than silently becoming some
    default country's number."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if _pn is not None:
        try:
            parsed = _pn.parse(raw, None)
        except _pn.NumberParseException:
            return None
        if not _pn.is_possible_number(parsed) or not _pn.is_valid_number(parsed):
            return None
        return _pn.format_number(parsed, _pn.PhoneNumberFormat.E164)
    if not _PHONE_FALLBACK_RE.match(raw):
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    return f"+{digits}" if 7 <= len(digits) <= 15 else None


# A phone-looking token inside free text — candidate only; validate_phone
# still has to pass it before anything is stored.
_PHONE_IN_TEXT_RE = re.compile(r"\+?[0-9][0-9 \-()\.]{6,18}[0-9]")


def _extract_phone_candidate(text: str | None) -> str | None:
    if not text:
        return None
    match = _PHONE_IN_TEXT_RE.search(text)
    return match.group(0).strip() if match else None


# ── deterministic signals (the no-LLM fallback path) ─────────────────

_INTENT_RE = re.compile(
    r"\b(price|pricing|cost|how much|quote|order|buy|purchase|book|booking|"
    r"appointment|available|availability|discount|website|web ?site|"
    r"e-?commerce|web ?store|online store|landing page|shop|store|app|sell)\b|"
    r"(سعر|أسعار|حجز|موعد|طلب|شراء|عرض سعر|موقع|متجر)",
    re.IGNORECASE,
)

# ── canonical category signals (deterministic, no LLM) ───────────────
#
# Order matters in detect_category: a complaint about an order is support
# even though "order" reads as buying; "50 boxes" is wholesale even when the
# same message asks for a price. Each pattern is deliberately narrow — a bare
# "help" or "late" would misfile ordinary questions as support.

_WHOLESALE_RE = re.compile(
    r"\b(wholesale|bulk(?: order| purchase)?|resell(?:er|ing)?|distributor|"
    r"dealer|trade (?:price|account)|b2b|cartons?|pallets?|dozens?|"
    r"per unit|unit price)\b"
    r"|\b\d{2,}\s*(?:pcs|pieces|units|items|boxes|cartons?|pallets?|kg|tons?)\b|"
    r"(بالجملة|الجملة|موزع|وكيل|كمية كبيرة|كرتون|كراتين|بالة|طن)",
    re.IGNORECASE,
)

_RETAIL_RE = re.compile(
    r"\b(retail|single (?:piece|item|unit)|just one|one piece|for myself|"
    r"personal use)\b|(تجزئة|قطعة واحدة|للاستخدام الشخصي)",
    re.IGNORECASE,
)

_BOOKING_RE = re.compile(
    r"\b(book\s+(?:a|an|the|my|us)\b|booking\b|appointment|reserve|"
    r"reservation|schedule (?:a|an|my)|slot|table for|room for)\b|"
    r"(حجز|احجز|موعد|طاولة|غرفة)",
    re.IGNORECASE,
)

_SUPPORT_RE = re.compile(
    r"\b(complaint|complain|refund|warranty|broken|damaged|defective|faulty|"
    r"not working|doesn'?t work|wrong (?:order|item)|missing (?:order|item)|"
    r"problem with|issue with|cancel my order|"
    r"my (?:order|delivery|shipment) (?:is )?(?:late|delayed|missing))\b|"
    r"(شكوى|اشتكي|استرجاع|مرتجع|ضمان|عطل|تالف|مشكلة|تأخير)",
    re.IGNORECASE,
)

_QUOTE_RE = re.compile(
    r"\b(price|pricing|cost|how much|quote|quotation|estimate|rate|"
    r"discount|special offer)\b|(سعر|أسعار|تسعير|عرض سعر|كم|خصم|عرض)",
    re.IGNORECASE,
)

_BUY_SIGNAL_RE = re.compile(
    r"\b(i (?:want|need|would like|'d like)|we (?:want|need|would like)|"
    r"looking (?:for|to buy)|interested in|can you (?:make|build|supply|provide)|"
    r"do you (?:make|build|supply|provide|sell))\b|"
    r"(أريد|اريد|أحتاج|احتاج|محتاج|نريد|مهتم)",
    re.IGNORECASE,
)

_INFO_RE = re.compile(
    r"\b(hours?|open(?:ing)?|location|address|where are you|directions|"
    r"deliver(?:y)?|shipping|website|about|information|info|"
    r"what do you (?:do|sell)|do you (?:sell|offer|deliver))\b|"
    r"(ساعات|مفتوح|موقع|عنوان|توصيل|شحن|معلومات|ماذا تبيعون)",
    re.IGNORECASE,
)

_INTENT_CATEGORY = {
    "buying": "retail",
    "booking": "booking",
    "quote": "quote",
    "info": "info",
}

# How specific a label is. A higher rank may replace a lower one even at a
# lower confidence ("actually I need 500 units" upgrades retail -> wholesale);
# a same-rank change still obeys the confidence rule, so noise cannot flip
# retail <-> booking on every message.
_CATEGORY_RANK = {
    "info": 0,
    "quote": 1,
    "support": 1,
    "retail": 2,
    "booking": 2,
    "wholesale": 3,
}


def detect_category(text: str | None, intent: str | None = None) -> str | None:
    """Canonical lead label for a message, without an LLM round-trip.

    This is the fallback for a reply that captured a request but omitted the
    category, and the only classifier on the no-extraction path. It never
    invents a segment: when no signal matches, the raw intent is the best
    available answer, and `capture_lead` defaults an unlabelled lead to info
    (which never auto-qualifies).
    """
    if not text:
        return _INTENT_CATEGORY.get((intent or "").strip().lower())
    if _SUPPORT_RE.search(text):
        return "support"
    if _WHOLESALE_RE.search(text):
        return "wholesale"
    if _BOOKING_RE.search(text):
        return "booking"
    if _RETAIL_RE.search(text):
        return "retail"
    if _QUOTE_RE.search(text):
        return "quote"
    if (
        _BUY_SIGNAL_RE.search(text)
        and (intent or "").strip().lower() == "buying"
    ):
        return "retail"
    if _INFO_RE.search(text):
        return "info"
    return _INTENT_CATEGORY.get((intent or "").strip().lower())

_OPT_OUT_RE = re.compile(
    r"\b(stop|unsubscribe|opt ?out|remove (my|us)|do not (contact|message|text)|"
    r"don't (contact|message|text))\b|"
    r"(توقف|الغاء الاشتراك|إلغاء الاشتراك|لا تراسل)",
    re.IGNORECASE,
)


def detect_intent(text: str | None) -> str | None:
    """Cheap buying-intent signal for messages without an extraction."""
    if not text:
        return None
    return "buying" if _INTENT_RE.search(text) else None


# Intents that describe a person who wants something from the business. "info"
# is deliberately absent: a question answered by the assistant ("what are your
# hours?") is a conversation, not a lead, and putting it in the CRM fills the
# pipeline with noise. An existing lead that later asks an info question is
# still updated -- this only gates CREATING a new row.
_LEAD_INTENTS = ("buying", "booking", "quote")


def has_lead_substance(text: str | None, delta: dict | None = None) -> bool:
    """True when this message shows someone the team should sell to (or help).

    A support complaint is stored too: it is a real customer issue, it gets
    the canonical `support` label, and it stays out of the qualified pipeline.
    """
    if delta:
        intent = str(delta.get("intent") or "").strip().lower()
        if intent in _LEAD_INTENTS:
            return True
        if str(delta.get("request") or "").strip():
            return True
    category = detect_category(text, detect_intent(text))
    return detect_intent(text) == "buying" or category in (
        "wholesale",
        "retail",
        "booking",
        "quote",
        "support",
    )


def detect_opt_out(text: str | None) -> bool:
    return bool(text) and bool(_OPT_OUT_RE.search(text))


def is_open_question(text: str | None) -> bool:
    """The reply genuinely asks the customer something (Latin ? or Arabic ؟)."""
    return bool(text) and text.rstrip().endswith(("?", "؟"))


async def _qualified_categories(db, tenant_id: str) -> tuple[str, ...]:
    """The tenant's auto-qualify set. Never raises; defaults on a read error.

    Called only when a `new` lead has enough substance to move, so the common
    already-qualified path costs no settings query.
    """
    from ...users.models import User

    try:
        raw = (
            await db.execute(
                select(User.lead_settings).where(User.id == tenant_id)
            )
        ).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001 - a read failure must not drop a lead
        logger.warning("lead settings read failed for %s: %s", tenant_id, e)
        raw = None
    return tuple(normalize_lead_settings(raw)["qualified_categories"])


# ── capture: create/merge the lead ───────────────────────────────────

async def capture_lead(
    db,
    *,
    tenant_id: str,
    channel_id: str,
    platform: str,
    contact_id: str,
    contact_name: str | None = None,
    username: str | None = None,
    message_id: str | None = None,
    inbound_text: str | None = None,
    delta: dict | None = None,
    occurred_at: datetime | None = None,
    require_intent: bool = False,
) -> Lead | None:
    """Create or merge the tenant's lead for this conversation.

    Idempotent by construction (the caller runs once per unique inbound)
    and merge-safe: empty/invalid values never erase known fields, and a
    lower-confidence value never replaces a higher one. Never raises —
    a capture problem must never cost the customer their reply.

    ``require_intent`` skips CREATING a row when the message shows no lead
    substance: a pure information request stays an inbox conversation instead
    of becoming a CRM entry. A lead that already exists is always returned and
    kept up to date, so a returning customer is never demoted to a stranger.

    A lead becomes `qualified` only when its canonical category is in the
    tenant's `qualified_categories` (default: wholesale, retail, booking,
    quote). Before HAND-5 any captured request moved the stage, so "where are
    you located?" and a complaint both read as sales-qualified; that is what
    made the board and reports coarse.
    """
    try:
        lead = (await db.execute(
            select(Lead).where(
                Lead.channel_id == channel_id,
                Lead.contact_id == contact_id,
            )
        )).scalar_one_or_none()
        if lead is None and require_intent and not has_lead_substance(inbound_text, delta):
            return None
        now = occurred_at or datetime.now(timezone.utc)
        if lead is None:
            lead = Lead(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                channel_id=channel_id,
                platform=platform,
                contact_id=contact_id,
                # Explicit (column defaults only apply at flush — the
                # stage logic below reads the attribute right away).
                stage="new",
                language="en",
                opt_out=False,
                thread_key=contact_id,
                source_message_id=(message_id or None),
            )
            db.add(lead)
        prov = dict(lead.field_provenance or {})
        confidence = float((delta or {}).get("confidence") or (0.6 if delta else 0.4))
        source = message_id or None
        previous_stage = lead.stage

        def _merge(field: str, column: str, value, source_conf: float) -> bool:
            # The core merge rule: nothing empty, nothing downgraded.
            # Returns whether the value was actually written.
            if value in (None, "", False):
                return False
            prev = prov.get(field) or {}
            if prev.get("value") not in (None, "") and source_conf < float(
                prev.get("confidence") or 0.0
            ):
                return False
            prov[field] = {
                "value": value,
                "confidence": round(source_conf, 2),
                "source_message_id": source,
                "at": now.isoformat(),
            }
            setattr(lead, column, value)
            return True

        def _merge_category(value: str | None, source_conf: float) -> bool:
            """Merge a category with specificity as well as confidence.

            The plain `_merge` treats every label as equal, so a deterministic
            "50 boxes" hit at 0.5 could never correct an earlier retail guess
            at 0.9. A strictly more specific label may upgrade; a sideways move
            (retail <-> booking) still needs at least the old confidence.
            """
            if value not in _LEAD_ALLOWED_CATEGORIES:
                return False
            prev = prov.get("category") or {}
            prev_value = lead.category
            prev_conf = float(prev.get("confidence") or 0.0)
            # A human correction is final until a human changes it. Without
            # this, the specificity rule below would let a deterministic
            # "wholesale" hit overwrite an operator's "support" label.
            if prev_conf >= 1.0:
                return False
            if prev_value and prev_value != value:
                new_rank = _CATEGORY_RANK.get(value, 0)
                prev_rank = _CATEGORY_RANK.get(prev_value, 0)
                if new_rank < prev_rank:
                    return False
                if new_rank == prev_rank and source_conf < prev_conf:
                    return False
            elif prev_value == value and source_conf < prev_conf:
                return False
            prov["category"] = {
                "value": value,
                "confidence": round(source_conf, 2),
                "source_message_id": source,
                "at": now.isoformat(),
            }
            lead.category = value
            return True

        # Platform ground truth: on WhatsApp the sender address IS a phone
        # number Meta has verified — store it (status "verified") unless the
        # customer later states a specific number with higher confidence.
        if platform == "whatsapp" and contact_id and contact_id.lstrip("+").isdigit():
            verified = validate_phone(f"+{contact_id.lstrip('+')}")
            if verified and _merge("phone", "phone_number", verified, 0.9):
                prov["phone"]["status"] = "verified"

        if delta:
            _merge("name", "contact_name", delta.get("name"), confidence)
            _merge("intent", "intent", delta.get("intent"), confidence)
            _merge_category(delta.get("category"), confidence)
            _merge("request", "request", delta.get("request"), confidence)
            if delta.get("phone") and _merge(
                "phone", "phone_number", delta["phone"], confidence
            ):
                prov["phone"]["status"] = "stated"
            # A digest, not a fact: the newest summary replaces the old one
            # (confidence rules don't apply — it must track the conversation
            # as it grows, while facts like name/phone never downgrade).
            new_summary = (delta.get("summary") or "").strip()
            if new_summary:
                lead.summary = new_summary[:300]
        else:
            # No extraction line: cheap deterministic signals only.
            _merge("intent", "intent", detect_intent(inbound_text), 0.4)
            candidate = validate_phone(_extract_phone_candidate(inbound_text))
            if candidate and _merge("phone", "phone_number", candidate, 0.4):
                prov["phone"]["status"] = "stated"

        # The model may capture a request but omit the label, and the
        # no-extraction path has no label at all. Deterministic classification
        # fills it; `info` is the honest default for "captured, not yet
        # classifiable", and it never auto-qualifies.
        effective_intent = lead.intent or detect_intent(inbound_text)
        detected_category = detect_category(inbound_text, effective_intent)
        if detected_category:
            _merge_category(
                detected_category,
                0.5 if detected_category != "info" else 0.3,
            )
        if lead.category is None:
            _merge_category("info", 0.2)

        if contact_name and not lead.contact_name:
            lead.contact_name = contact_name[:120]
        if username and not lead.contact_username:
            lead.contact_username = username[:120]
        if not lead.summary:
            base = (delta or {}).get("request") or inbound_text
            if base:
                lead.summary = base.strip()[:300]

        # Deterministic stage transitions only. `qualified` now means "a
        # sellable category was captured", not "the AI stored any sentence".
        if lead.stage == "new" and (lead.intent or lead.request):
            qualified_categories = await _qualified_categories(db, tenant_id)
            if lead.category in qualified_categories:
                lead.stage = "qualified"

        # Opt-out: customer said stop — flip the flag and kill the queue.
        if detect_opt_out(inbound_text) and not lead.opt_out:
            lead.opt_out = True
            lead.opt_out_at = now
            await cancel_pending_actions(db, channel_id, contact_id, reason="opt_out")

        if message_id:
            lead.last_inbound_message_id = message_id[:200]
        lead.last_message_at = now
        # Write the merged provenance back — downgrade protection on the
        # next capture reads exactly this.
        lead.field_provenance = prov
        db.add(lead)
        # The honest handoff: when a lead gains substance, the team is
        # actually TOLD (once per transition) — no "connecting you" theater.
        # Gated by the tenant's notification settings like every other pop.
        if lead.stage == "qualified" and previous_stage != "qualified":
            from ...notifications.service import normalize_notification_settings, notify
            from ...users.models import User

            prefs = (
                await db.execute(
                    select(User.notification_settings).where(User.id == tenant_id)
                )
            ).scalar_one_or_none()
            if normalize_notification_settings(prefs)["leads"]:
                await notify(
                    db,
                    tenant_id,
                    "lead",
                    f"New lead on {platform}",
                    f"{lead.contact_name or contact_id}: "
                    f"{lead.summary or lead.request or ''}".strip()[:300],
                    data={"lead_id": lead.id, "platform": platform},
                )
        await db.commit()
        return lead
    except Exception as e:
        # Logged, never silent-and-lost: the reply already went out; only
        # the CRM side of this message failed.
        logger.warning(
            "Lead capture failed channel=%s contact=…%s: %s: %s",
            channel_id[:8], contact_id[-6:], type(e).__name__, str(e)[:150],
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return None


# ── scheduling: durable, idempotent, quiet-hours aware ───────────────

def _followup_gaps(settings: dict) -> list[timedelta]:
    """Delay before each attempt n (1-based → gaps[n-1])."""
    return [
        timedelta(minutes=settings["first_nudge_minutes"]),
        timedelta(hours=settings["second_followup_hours"]),
        timedelta(hours=settings["final_followup_hours"]),
    ][: max(0, int(settings["max_attempts"]))]


def _shift_out_of_quiet_hours(due: datetime, settings: dict) -> datetime:
    """Nudges land inside the tenant's waking hours or not at all: a
    quiet-hour due time slides forward to the next quiet-end."""
    try:
        tz = ZoneInfo(settings["timezone"])
    except Exception:
        tz = ZoneInfo("UTC")
    local = due.astimezone(tz)
    start, end = int(settings["quiet_start_hour"]), int(settings["quiet_end_hour"])
    if start == end:
        return due  # no quiet window configured
    hour = local.hour
    in_quiet = (hour >= start or hour < end) if start > end else (start <= hour < end)
    if not in_quiet:
        return due
    target = local.replace(hour=end % 24, minute=0, second=0, microsecond=0)
    if start > end and hour >= start:
        target += timedelta(days=1)  # late night (23:00) → tomorrow morning
    return target.astimezone(timezone.utc)


async def cancel_pending_actions(
    db, channel_id: str, contact_id: str, *, reason: str
) -> int:
    """Every pending/claimed action for this thread dies — the customer
    spoke, converted, or opted out. Claimed rows are included: the lease
    holder re-checks state after its claim and finds them closed."""
    rows = (await db.execute(
        select(LeadAction).where(
            LeadAction.channel_id == channel_id,
            LeadAction.contact_id == contact_id,
            LeadAction.status.in_(("pending", "claimed")),
        )
    )).scalars().all()
    for action in rows:
        action.status = "cancelled"
        action.ineligible_reason = reason
        db.add(action)
    if rows:
        logger.info(
            "Lead actions cancelled (%d) channel=%s contact=…%s reason=%s",
            len(rows), channel_id[:8], contact_id[-6:], reason,
        )
    return len(rows)


async def schedule_followup(
    db,
    *,
    lead: Lead,
    channel_id: str,
    contact_id: str,
    platform: str,
    guard_message_id: str | None,
    question: str | None,
    settings: dict,
) -> LeadAction | None:
    """Arm the next follow-up attempt for this lead. Deterministic; the
    unique (lead, guard, attempt) constraint makes double-arming
    structurally impossible even across racing workers. Never raises —
    a scheduling failure must not break the reply that just went out."""
    try:
        settings = normalize_lead_settings(settings)
        if (
            not settings["enabled"]
            or settings["max_attempts"] < 1
            or lead.opt_out
            or lead.stage in ("converted", "lost")
            # Qualification gate. capture_lead creates a Lead for EVERY inbound
            # DM, so without this an unqualified conversation ("hello") gets the
            # full sales sequence the moment the AI's reply ends in a "?" —
            # is_open_question was the only gate, and it says nothing about
            # intent. stage=="qualified" is set by the buying-word regex or the
            # LLM's LEAD extraction.
            #
            # "follow_up" also passes: it only ever means "was qualified, then
            # got a sequence armed". capture_lead transitions new->qualified
            # once and never rewrites a later stage, so requiring "qualified"
            # exactly would permanently block every follow-up for any lead that
            # had already progressed past its first arm.
            or lead.stage not in ("qualified", "follow_up")
        ):
            return None
        gaps = _followup_gaps(settings)
        if not gaps:
            return None
        existing = (await db.execute(
            select(LeadAction.attempt).where(
                LeadAction.lead_id == lead.id,
                LeadAction.guard_message_id == (guard_message_id or None),
            )
        )).scalars().all()
        attempt = next((n for n in range(1, len(gaps) + 1) if n not in set(existing)), None)
        if attempt is None:
            return None
        action = LeadAction(
            id=str(uuid.uuid4()),
            tenant_id=lead.tenant_id,
            lead_id=lead.id,
            channel_id=channel_id,
            contact_id=contact_id,
            platform=platform,
            attempt=attempt,
            question=(question or "").strip()[:500] or None,
            language=(lead.language or "en")[:16],
            guard_message_id=(guard_message_id or None),
            due_at=_shift_out_of_quiet_hours(
                datetime.now(timezone.utc) + gaps[attempt - 1], settings
            ),
        )
        db.add(action)
        lead.next_action_at = action.due_at
        if lead.stage in ("new", "qualified"):
            lead.stage = "follow_up"
        db.add(lead)
        await db.commit()
        return action
    except Exception as e:
        logger.warning(
            "Follow-up scheduling failed lead=%s: %s: %s",
            (getattr(lead, "id", "?") or "?")[:8], type(e).__name__, str(e)[:150],
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def latest_inbound(db, channel_id: str, contact_id: str):
    """(platform_message_id, created_at) of the thread's newest inbound,
    or None. The send-time staleness + 24h-window check reads this."""
    return (await db.execute(
        select(ChannelMessage.platform_message_id, ChannelMessage.created_at)
        .where(
            ChannelMessage.channel_id == channel_id,
            ChannelMessage.contact_phone_hash == hash_contact_phone(contact_id),
            ChannelMessage.direction == "inbound",
        )
        .order_by(ChannelMessage.created_at.desc())
        .limit(1)
    )).first()


# ── Meta messaging window (centralized, send-layer enforcement) ──────

_WINDOW = timedelta(hours=24)


def window_open(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    """Meta's free-form messaging window (WA + IG): 24h from the
    customer's last message. Every scheduled send funnels through this —
    there is no second, weaker check anywhere."""
    if last_inbound_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=timezone.utc)
    return (now - last_inbound_at) < _WINDOW


# ── nudge text: deterministic templates, no LLM at send time ─────────

def nudge_text(question: str | None, language: str | None) -> str:
    """An honest nudge: restate the open question we're waiting on. No
    invented urgency, discounts, or fake human review."""
    ask = (question or "").strip() or "do you still need help with this?"
    if not ask.endswith(("?", "؟")):
        ask = f"{ask}?"
    lang = (language or "en").split("-")[0]
    if lang == "ar":
        return f"مجرد متابعة — {ask}"
    return f"Just checking in — {ask}"
