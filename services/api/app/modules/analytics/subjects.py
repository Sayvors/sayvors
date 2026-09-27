"""Closed subject vocabulary and the validators that make meaning checkable.

This module is the enforcement layer for review meaning. A language model will
happily invent a plausible complaint that no customer ever made — it did
exactly that, turning the Arabic "you need to fix your building" into "bank
account corrections" and then propagating the error through a theme, an
opportunity and a business action. Telling the model not to do that in the
prompt did not help; it did it anyway.

So the rules live in code instead:

  * `SUBJECTS` is a **closed vocabulary**. A subject that is not in this set
    cannot be stored. "Account Issues" is not a subject, so it cannot be
    produced, regardless of what the model feels like returning.
  * Evidence must be **verbatim**. Every span the model cites has to appear in
    the review text after normalisation. A complaint with no supporting span is
    rejected rather than believed.
  * **Abstaining is a first-class outcome.** A record that cannot be grounded
    is marked `needs_human` and surfaced for review instead of being forced
    into a theme.

Arabic normalisation matters here: review text is routinely written with
optional diacritics and with several interchangeable letter forms
(أ/إ/آ → ا, ى → ي, ة → ه). Without folding those, a perfectly good verbatim
quote fails the substring check and a correct extraction gets thrown away.
"""
from __future__ import annotations

import re
import unicodedata

# ── Closed vocabulary ────────────────────────────────────────────
# The keys are stored; the labels are what the merchant reads. The list reuses
# the six themes the dashboard already showed (quality, staff, cleanliness,
# speed, value, communication) and adds the ones a software business with a
# physical branch actually needs.

SUBJECTS: dict[str, str] = {
    "product_quality": "Product quality",
    "features_updates": "Features & updates",
    "staff_service": "Staff & service",
    "cleanliness": "Cleanliness",
    "speed_waiting": "Speed & waiting",
    "value_pricing": "Value & pricing",
    "communication_response": "Communication & response",
    "facility_premises": "Facility & premises",
    "location_access": "Location & access",
    "delivery": "Delivery",
    "billing_payments": "Billing & payments",
    "account_access": "Account & access",
    "other": "Other",
}

SUBJECT_KEYS = frozenset(SUBJECTS)

# The entity buckets a meaning record carries. Exposed so callers can build a
# complete record without reaching into a private name.
ENTITY_KEYS = ("product", "location", "staff", "dates")

# Below this confidence an extraction is not trusted on its own; it is kept but
# queued for a human. Tuned so a clear, specific, well-evidenced complaint
# passes and a vague or ambiguous one does not.
AUTO_ACCEPT_CONFIDENCE = 0.6

# ── Language detection ──────────────────────────────────────────
# Coarse script buckets. Only used to decide whether a heuristic fallback can
# operate, and to label the UI. Not a substitute for real language ID.
_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RANGE = re.compile(r"[A-Za-z]")


def detect_language(text: str | None) -> str:
    if not text:
        return "und"
    if _ARABIC_RANGE.search(text):
        return "ar"
    if _LATIN_RANGE.search(text):
        return "en"
    return "und"


def is_non_latin(text: str | None) -> bool:
    """True when the text is not Latin-script.

    Used to stop the English-only keyword fallback from pretending it
    understood an Arabic review: for those we abstain rather than return empty
    lists that look like a successful analysis.
    """
    return detect_language(text) not in ("en", "und")


# ── Normalisation ───────────────────────────────────────────────
# Arabic-Indic and Extended Arabic-Indic digits fold to ASCII so a number
# quoted from the review still matches after the provider reformats it.
_DIGIT_MAP = {ord(c): ord(str(i)) for i, c in enumerate("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669")}
_DIGIT_MAP.update({ord(c): ord(str(i)) for i, c in enumerate("\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9")})

# Harakat, superscript alef, tatweel, and the Quranic annotation marks: all
# optional decoration that reviewers routinely omit, so a quote containing them
# would otherwise fail to match the review it came from.
_ARABIC_MARKS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")

# Letter-form folding.
_ARABIC_FOLD = str.maketrans({
    "\u0622": "\u0627", "\u0623": "\u0627", "\u0625": "\u0627", "\u0671": "\u0627",  # آ أ إ ٱ -> ا
    "\u0624": "\u0648",  # ؤ -> و
    "\u0626": "\u064A",  # ئ -> ي
    "\u0649": "\u064A",  # ى -> ي
    "\u0629": "\u0647",  # ة -> ه
    "\u06A9": "\u0643",  # ک -> ك
    "\u06AF": "\u063A",  # گ -> غ
    "\u06CC": "\u064A",  # ی -> ي
    "\u0640": "",        # tatweel
})

_ARABIC_TATWEEL = "\u0640"

# Latin: strip accents so "café" matches "cafe".
_LATIN_FOLD = "NFKD"


def normalise(text: str) -> str:
    """Fold a string to a comparison form.

    Not a display transform: this exists so that a verbatim quote can be
    located inside review text that spells the same word differently.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFKC", text)
    out = _ARABIC_MARKS.sub("", out)
    out = out.replace(_ARABIC_TATWEEL, "")
    out = out.translate(_ARABIC_FOLD)
    out = out.translate(_DIGIT_MAP)
    out = unicodedata.normalize(_LATIN_FOLD, out)
    # Combining marks left over from NFKD decomposition.
    out = "".join(ch for ch in out if not unicodedata.combining(ch))
    out = out.lower()
    # Collapse all whitespace runs so line breaks and double spaces do not
    # defeat a substring check.
    return re.sub(r"\s+", " ", out).strip()


def evidence_is_verbatim(evidence: str | None, review_text: str | None) -> bool:
    """True when `evidence` actually occurs in the review.

    This is the single most important check in the meaning layer. A complaint
    the model asserts without a matching span in the review is a fabrication,
    whatever else it is dressed up as.
    """
    span = normalise(evidence)
    if len(span) < 2:
        return False
    return span in normalise(review_text)


def filter_evidence(
    evidence: list | None, review_text: str | None, *, limit: int = 6
) -> list[str]:
    """Keep only the spans that are genuinely in the review.

    Returns the *original* (un-normalised) spans so the UI can highlight them
    in the text the merchant actually reads.
    """
    kept: list[str] = []
    seen: set[str] = set()
    for item in evidence or []:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if not trimmed or not evidence_is_verbatim(trimmed, review_text):
            continue
        key = normalise(trimmed)
        if key in seen:
            continue
        seen.add(key)
        kept.append(trimmed[:200])
        if len(kept) >= limit:
            break
    return kept


# ── Negation ────────────────────────────────────────────────────
# The model reports negation because it understands it far better than a
# regex does. These markers are a cross-check: when the model's answer and the
# text disagree, confidence drops, so a likely misread is surfaced rather than
# trusted. "No problems" and "there is a problem" differ by a few characters in
# both English and Arabic, and a naive keyword pass reads the positive token.

NEGATION_MARKERS: dict[str, tuple[str, ...]] = {
    "en": (
        "not", "no", "never", "none", "nothing", "nobody", "without", "cannot",
        "cant", "wont", "dont", "doesnt", "didnt", "isnt", "wasnt", "arent",
        "werent", "hasnt", "havent", "wouldnt", "shouldnt", "couldnt", "aint",
    ),
    "ar": (
        "\u0644\u0627", "\u0644\u0645", "\u0644\u0646", "\u0633\u0648\u0628",  # لا لم لن سوف
        "\u0645\u0627 \u0641\u064a", "\u0645\u0627\u0641\u064a",                # ما في / مافي
        "\u0645\u0627\u0643\u0648", "\u0645\u0627\u0643\u0648\u0627",           # ماكو / ماكولا
        "\u0645\u0627 \u0623", "\u0645\u0627 \u0627",                        # ما أ / ما ا
        "\u0628\u062f\u0648\u0646", "\u063a\u064a\u0631",                       # بدون غير
        "\u0648\u0644\u0645",                                                 # ولم
    ),
}

_NEGATION_RE = {
    lang: re.compile(r"(?:^|[\s,.:;!؟(\[{])" + "|".join(re.escape(w) for w in words) + r"(?:$|[\s,.:;!؟)\]}])")
    for lang, words in NEGATION_MARKERS.items()
}


def has_negation(text: str | None) -> bool:
    """Heuristic negation signal, used only to cross-check the model."""
    if not text:
        return False
    norm = normalise(text)
    for lang, pattern in _NEGATION_RE.items():
        if pattern.search(norm):
            return True
    return False


# ── Validation helpers ──────────────────────────────────────────

def coerce_subject(value: object) -> str | None:
    """Return a legal subject key, or None if the model invented one.

    The single enforcement point for the closed vocabulary. Accepts a little
    sloppiness (spaces instead of underscores, different case) because that is
    cheap to forgive, but never a value outside SUBJECTS.
    """
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    key = re.sub(r"_+", "_", key).strip("_")
    if key in SUBJECT_KEYS:
        return key
    # Common near-misses from the same idea, so a reasonable model is not
    # punished for phrasing. Everything else is rejected.
    aliases = {
        "facility": "facility_premises",
        "premises": "facility_premises",
        "building": "facility_premises",
        "maintenance": "facility_premises",
        "support": "communication_response",
        "response": "communication_response",
        "pricing": "value_pricing",
        "price": "value_pricing",
        "cost": "value_pricing",
        "quality": "product_quality",
        "product": "product_quality",
        "features": "features_updates",
        "product_features": "features_updates",
        "billing": "billing_payments",
        "payment": "billing_payments",
        "payments": "billing_payments",
        "account": "account_access",
        "login": "account_access",
        "access": "location_access",
        "location": "location_access",
        "wait": "speed_waiting",
        "waiting": "speed_waiting",
        "delay": "speed_waiting",
        "staff": "staff_service",
        "service": "staff_service",
    }
    return aliases.get(key)


def coerce_confidence(value: object) -> float:
    """Confidence in 0..1. Out-of-range or unreadable means "no confidence".

    Deliberately not clamped: clamping a 1.7 into 1.0 invents certainty the
    model did not express.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v < 0.0 or v > 1.0:  # NaN or out of range
        return 0.0
    return round(v, 3)
