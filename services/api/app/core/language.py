"""Language identification for review text.

This module is the single source of truth for "what language is this review
written in". It is deliberately *not* a Unicode-script check: Arabic and Urdu
share the Arabic script, so script alone cannot tell them apart. We combine
script detection with character-level markers and function-word frequency.

Design rules:
- The detector is a fast, deterministic signal. It never calls the network.
- It returns a confidence; callers (the LLM analysis) may override when the
  detector is unsure.
- It never mutates or normalizes the input text; it only classifies.
- It supports Arabic-script languages (ar, ur, fa, ps) and Latin-script
  languages (en, Roman Urdu, and any other Latin language via the fallback).
- It is language-agnostic in the sense that an unknown language still gets a
  script + ISO-ish code; the LLM refines the exact label.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageVerdict:
    code: str          # ISO 639-1-ish code, e.g. "ar", "ur", "ur-Latn", "en"
    script: str        # "arabic", "latin", "cjk", "other"
    confidence: float  # 0.0 - 1.0
    is_rtl: bool

    @property
    def confident(self) -> bool:
        return self.confidence >= 0.6


# ---------------------------------------------------------------------------
# Character-level markers
# ---------------------------------------------------------------------------

# Characters that are specific to Urdu (not used in Arabic or Persian).
_URDU_SPECIFIC = frozenset("ٹڈڑںھےکگچپژ")
# Characters that are specific to Arabic (rare in Urdu).
_ARABIC_SPECIFIC = frozenset("ةىؤإأآ")
# Persian-specific markers.
_PERSIAN_SPECIFIC = frozenset("پچگژ")  # overlaps Urdu; refined by function words

_ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def has_arabic_script(text: str | None) -> bool:
    """Whether the text contains any Arabic-script character."""
    if not text:
        return False
    return bool(_ARABIC_SCRIPT_RE.search(text))
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF]")

# Function words / common markers (lowercased, normalized).
_ARABIC_FUNCTION_WORDS = frozenset({
    "هل", "في", "من", "على", "هذا", "هذه", "كان", "لم", "لن", "ما", "لا",
    "التي", "الذي", "أن", "إن", "قد", "أو", "و", "لكن", "كما", "عن", "إلى",
    "مع", "حتى", "بعد", "قبل", "لأن", "لذلك", "هنا", "هناك", "هناك",
})
_URDU_FUNCTION_WORDS = frozenset({
    "کیا", "ہے", "ہیں", "ہو", "میں", "سے", "کو", "کا", "کی", "کے", "نہیں",
    "اور", "بہت", "اچھا", "اچھی", "اچھے", "تھا", "تھی", "تھے", "کر", "رہا",
    "رہی", "رہے", "ہوں", "ہم", "آپ", "تم", "یہ", "وہ", "جو", "تو", "بھی",
    "نہ", "کب", "کہاں", "کیسے", "کون", "کیوں", "کتنا", "کتنے",
})
_PERSIAN_FUNCTION_WORDS = frozenset({
    "که", "با", "از", "در", "برای", "است", "هست", "بود", "نمی", "می", "را",
    "این", "آن", "یا", "اما", "که", "چه", "کجا", "چرا", "چطور", "کی",
})
_ROMAN_URDU_FUNCTION_WORDS = frozenset({
    "kya", "hai", "hain", "ho", "mein", "se", "ko", "ka", "ki", "ke", "nahi",
    "aur", "bohat", "acha", "achi", "achay", "tha", "thi", "they", "kar", "raha",
    "rahi", "rahe", "hun", "hum", "aap", "tum", "ye", "wo", "jo", "tu", "bhi",
    "na", "kab", "kahan", "kaise", "kaun", "kyun", "kitna", "kitne",
})


def _tokenize(text: str) -> list[str]:
    # Whitespace + punctuation split; keep Arabic/Urdu/Latin word chars.
    return [t for t in re.split(r"[\s\.,!?;:،۔؟«»\"'()\[\]{}]+", text) if t]


def _count_markers(text: str, markers: frozenset[str]) -> int:
    tokens = _tokenize(text)
    return sum(1 for t in tokens if t in markers)


def _arabic_script_language(text: str) -> tuple[str, float]:
    """Distinguish ar/ur/fa/ps among Arabic-script text."""
    tokens = _tokenize(text)
    total = max(len(tokens), 1)
    urdu_chars = sum(1 for ch in text if ch in _URDU_SPECIFIC)
    arabic_chars = sum(1 for ch in text if ch in _ARABIC_SPECIFIC)
    persian_chars = sum(1 for ch in text if ch in _PERSIAN_SPECIFIC)

    urdu_fw = _count_markers(text, _URDU_FUNCTION_WORDS)
    arabic_fw = _count_markers(text, _ARABIC_FUNCTION_WORDS)
    persian_fw = _count_markers(text, _PERSIAN_FUNCTION_WORDS)

    # Score each language.
    scores = {
        "ur": urdu_chars * 3 + urdu_fw * 4,
        "ar": arabic_chars * 3 + arabic_fw * 4,
        "fa": persian_chars * 2 + persian_fw * 4,
    }
    # If there are no markers at all, default to Arabic (most common).
    if sum(scores.values()) == 0:
        return "ar", 0.4

    best = max(scores, key=lambda k: scores[k])
    second = sorted(scores.values(), reverse=True)[1]
    margin = scores[best] - second
    confidence = min(0.95, 0.5 + 0.1 * margin + 0.05 * scores[best])
    # If the margin is tiny, lower confidence.
    if margin < 2:
        confidence = min(confidence, 0.55)
    return best, round(confidence, 2)


def _latin_language(text: str) -> tuple[str, float]:
    """Distinguish en vs Roman Urdu (and other Latin languages) via function words."""
    tokens = [t.lower() for t in _tokenize(text)]
    total = max(len(tokens), 1)
    roman_urdu_fw = sum(1 for t in tokens if t in _ROMAN_URDU_FUNCTION_WORDS)
    # English function words (a small set of common ones).
    english_fw = sum(1 for t in tokens if t in {
        "the", "is", "are", "was", "were", "have", "has", "had", "do", "does",
        "did", "can", "could", "will", "would", "should", "what", "where",
        "when", "why", "who", "how", "and", "but", "or", "not", "this", "that",
        "it", "you", "we", "they", "i", "me", "my", "your", "our",
    })
    if roman_urdu_fw == 0 and english_fw == 0:
        return "en", 0.4
    if roman_urdu_fw > english_fw * 1.5 and roman_urdu_fw >= 2:
        conf = min(0.9, 0.5 + 0.1 * roman_urdu_fw)
        return "ur-Latn", round(conf, 2)
    if english_fw > 0:
        conf = min(0.9, 0.5 + 0.05 * english_fw)
        return "en", round(conf, 2)
    return "en", 0.4


def detect_language(text: str | None) -> LanguageVerdict:
    """Classify the language of a review text.

    Returns a verdict with a confidence score. Callers should treat low
    confidence as "the LLM decides"; high confidence as authoritative for the
    Arabic-script family (where the LLM is most likely to mislabel Urdu as ar).
    """
    text = (text or "").strip()
    if not text:
        return LanguageVerdict(code="en", script="latin", confidence=0.0, is_rtl=False)

    has_arabic_script = bool(_ARABIC_SCRIPT_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    has_cjk = bool(_CJK_RE.search(text))

    if has_arabic_script and not has_latin:
        code, conf = _arabic_script_language(text)
        return LanguageVerdict(code=code, script="arabic", confidence=conf, is_rtl=True)

    if has_arabic_script and has_latin:
        # Mixed script: classify the dominant script.
        ar_count = len(_ARABIC_SCRIPT_RE.findall(text))
        lat_count = len(_LATIN_RE.findall(text))
        if ar_count >= lat_count:
            code, conf = _arabic_script_language(text)
            return LanguageVerdict(code=code, script="arabic", confidence=conf * 0.9, is_rtl=True)
        code, conf = _latin_language(text)
        return LanguageVerdict(code=code, script="latin", confidence=conf * 0.9, is_rtl=False)

    if has_cjk:
        # Best-effort CJK detection; the LLM refines.
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
            return LanguageVerdict(code="ja", script="cjk", confidence=0.5, is_rtl=False)
        if re.search(r"[\uAC00-\uD7AF]", text):
            return LanguageVerdict(code="ko", script="cjk", confidence=0.5, is_rtl=False)
        return LanguageVerdict(code="zh", script="cjk", confidence=0.5, is_rtl=False)

    if has_latin:
        code, conf = _latin_language(text)
        return LanguageVerdict(code=code, script="latin", confidence=conf, is_rtl=False)

    return LanguageVerdict(code="en", script="other", confidence=0.0, is_rtl=False)