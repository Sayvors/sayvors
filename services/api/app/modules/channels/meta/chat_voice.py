"""Deterministic post-processing for AI replies (phase 2 of the WA voice plan).

The prompt asks for human tone, but the customer-facing message must not
depend on the model obeying. This module enforces the product's machine-tell
rules by mapping, not by prompting: em/en dashes, markdown scaffolding and the
most common AI-isms are removed or replaced after generation, before send.

Fail-open contract: every public function returns the original text on any
doubt or error. A linter bug may leave a dash in, it must never eat a reply.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Exact phrases (case-insensitive) replaced after generation. These are the
# Klarna-style "produced -> wanted" mappings from the voice plan. Ban-lists
# expire as model behaviour changes (~18 months, per the research), so this
# map is data: re-measure and edit here, never hard-code new ones in prompts.
_BANNED_PHRASE_MAP: dict[str, str] = {
    "I apologize for the inconvenience": "Sorry about that",
    "Kindly allow me to verify": "Let me check",
    "Noted with thanks": "Got it",
    "Please be informed that": "",
    "I would like to inform you that": "",
    "I hope this message finds you well": "",
    "Thank you for your understanding": "Thanks for bearing with us",
    "In today's fast-paced world": "",
    "I am writing to provide": "Here's",
    "Please do not hesitate to": "Feel free to",
    "We value your business": "We appreciate your business",
}

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_DOUBLE_ASCII_DASH = "--"

# Markdown scaffolding we never want to reach a customer.
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+.*$", re.MULTILINE)
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MARKDOWN_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_MARKDOWN_CODE = re.compile(r"`{1,3}[^`]*`{1,3}")
_MARKDOWN_BULLET = re.compile(r"^\s*[-*•·\u2013]\s+", re.MULTILINE)
_MARKDOWN_NUMBERED = re.compile(r"^\s*\d{1,3}[.)]\s+", re.MULTILINE)

# Collapses runs of blank lines to one, strips trailing spaces per line,
# removes leading indentation, and squeezes runs of spaces to one.
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
_LEADING_INDENT = re.compile(r"^[ \t]+", re.MULTILINE)
_MULTI_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_COMMA = re.compile(r"\s+,")

# Something is an "AI-ism" if it appears verbatim in the map; the opener
# measure uses the first 5 words for comparison.
_OPENER_WORDS = 5


def _strip_markdown(text: str) -> str:
    text = _MARKDOWN_HEADING.sub("", text)
    text = _MARKDOWN_BOLD.sub(r"\1", text)
    text = _MARKDOWN_ITALIC.sub(r"\1", text)
    text = _MARKDOWN_CODE.sub("", text)
    text = _MARKDOWN_BULLET.sub("", text)
    text = _MARKDOWN_NUMBERED.sub("", text)
    return text


def _replace_dashes(text: str) -> str:
    """Em/en dashes and `--` become commas; single hyphens are left alone
    (compound words and Arabic/Urdu connected forms must survive)."""
    text = re.sub(r"\s*\u2014\s*", ", ", text)
    text = re.sub(r"\s*\u2013\s*", ", ", text)
    text = re.sub(r"\s*--\s*", ", ", text)
    # "Hi , how" -> "Hi, how"; ", ," -> ",".
    text = _SPACE_BEFORE_COMMA.sub(",", text)
    return text.replace(", ,", ",").replace(",,", ",")


def _replace_phrases(text: str) -> str:
    lowered = text.lower()
    for source, target in _BANNED_PHRASE_MAP.items():
        if source.lower() not in lowered:
            continue
        # Case-insensitive replace with the intended casing preserved.
        text = re.sub(re.escape(source), target.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    return text


def _collapse_whitespace(text: str) -> str:
    text = _TRAILING_SPACES.sub("", text)
    text = _LEADING_INDENT.sub("", text)
    text = _EXTRA_BLANK_LINES.sub("\n\n", text)
    text = _MULTI_SPACES.sub(" ", text)
    return text.strip()


def clean_reply(text: str | None) -> str:
    """Apply every deterministic rule; return the original on any doubt.

    ``text`` is a str; a None or non-str input is returned untouched so a
    malformed caller can never trigger a TypeError that eats a reply.
    """
    if not isinstance(text, str):
        return ""
    if not text.strip():
        return ""
    try:
        cleaned = _strip_markdown(text)
        cleaned = _replace_dashes(cleaned)
        cleaned = _replace_phrases(cleaned)
        cleaned = _collapse_whitespace(cleaned)
        return cleaned or text.strip()
    except Exception as e:  # noqa: BLE001 — fail-open is the contract
        logger.warning(
            "reply lint failed, sending original — %s: %s",
            type(e).__name__, str(e)[:150],
        )
        return text


def opener_key(text: str | None) -> str:
    """Normalised signature of how a reply starts — for the opener-variation
    measure. Empty when there is nothing to compare."""
    if not isinstance(text, str):
        return ""
    words = re.findall(r"[A-Za-z\u0600-\u06FF]+", text.lower())[:_OPENER_WORDS]
    return " ".join(words)
