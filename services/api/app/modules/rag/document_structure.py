"""Structured document extraction (§31 Phase B).

Turns raw crawl markdown into an organized, machine-readable summary that is
stored on ``Document.meta`` and powers both the UI and AI search:

- ``summary``   — first meaningful paragraph, extractive (no LLM cost)
- ``intent``    — page classification from URL/title keywords (blog, pricing,
                  product, policy, docs, contact, faq, about, careers, general)
- ``sections``  — heading outline with sizes, for navigation and QA
- ``entities``  — bounded contact/commercial facts (emails, phones, prices)

Everything here is deterministic regex/parsing: crawls run in bulk, so an LLM
call per page is a Phase C option, not a dependency.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Intent classification: ordered keyword -> label. URL path wins over title.
_INTENT_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("blog", "blog"),
    ("post", "blog"),
    ("news", "blog"),
    ("pricing", "pricing"),
    ("plans", "pricing"),
    ("product", "product"),
    ("shop", "product"),
    ("store", "product"),
    ("services", "product"),
    ("solutions", "product"),
    ("features", "product"),
    ("privacy", "policy"),
    ("terms", "policy"),
    ("legal", "policy"),
    ("policy", "policy"),
    ("docs", "docs"),
    ("documentation", "docs"),
    ("api", "docs"),
    ("guide", "docs"),
    ("help", "support"),
    ("support", "support"),
    ("faq", "faq"),
    ("contact", "contact"),
    ("about", "about"),
    ("team", "about"),
    ("careers", "careers"),
    ("jobs", "careers"),
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}[\s.-]?\d{3,4}[\s.-]?\d{3,4}"
)
_PRICE_RE = re.compile(
    r"(?:USD|EUR|GBP|AED|SAR|KWD|QAR|\$|€|£)\s?\d[\d,.]*(?:\s?(?:K|M|k|m))?"
)

# Hard bounds keep meta payloads small no matter what a page contains.
_MAX_ENTITIES = 10
_MAX_SECTIONS = 40
_MAX_SUMMARY_CHARS = 320

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
_MD_NOISE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[(^[^\]]*)\]\([^)]*\)|[*_`>#]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _plain_text(markdown: str, limit: int) -> str:
    """Markdown -> readable text, capped at ``limit`` characters."""
    text = _MD_NOISE_RE.sub(" ", markdown)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:limit]


def classify_intent(url: str, title: str | None) -> str:
    """Classify a page from its URL path, falling back to the title."""
    path = (urlparse(url).path or "").lower()
    for keyword, label in _INTENT_KEYWORDS:
        if keyword in path:
            return label
    title_lower = (title or "").lower()
    for keyword, label in _INTENT_KEYWORDS:
        if keyword in title_lower:
            return label
    return "general"


def extract_summary(markdown: str, max_chars: int = _MAX_SUMMARY_CHARS) -> str:
    """First meaningful paragraph, cut at a sentence boundary.

    Heading lines, nav fragments and one-liners are skipped so the summary
    reads like an abstract instead of a menu. Headings are removed per line
    BEFORE the word-count check: sites often glue a heading and its intro
    into one block, and the heading text must not leak into the summary.
    """
    for block in markdown.split("\n\n"):
        body_lines = [
            line for line in block.splitlines()
            if line.strip() and not _HEADING_RE.match(line.strip())
        ]
        candidate = _plain_text("\n".join(body_lines), max_chars * 2).strip()
        # Skip nav crumbs and one-or-two-word blocks.
        if len(candidate.split()) < 6:
            continue
        if len(candidate) <= max_chars:
            return candidate
        cut = candidate[:max_chars]
        sentence_end = max(cut.rfind(". "), cut.rfind("."))
        if sentence_end > max_chars // 2:
            return cut[: sentence_end + 1]
        return cut.rstrip() + "…"
    return ""


def extract_sections(markdown: str) -> list[dict]:
    """Heading outline: [{heading, level, chars}] capped at _MAX_SECTIONS.

    ``chars`` counts the plain text under the heading until the next heading
    of any level, giving the UI (and QA) a sense of section weight.
    """
    headings = list(_HEADING_RE.finditer(markdown))
    if not headings:
        text = _plain_text(markdown, 400)
        return [{"heading": "(no headings)", "level": 0, "chars": len(text)}] if text else []

    sections: list[dict] = []
    for i, match in enumerate(headings):
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        body = _plain_text(markdown[start:end], 10_000)
        sections.append({
            "heading": _plain_text(match.group(2), 120),
            "level": len(match.group(1)),
            "chars": len(body),
        })
        if len(sections) >= _MAX_SECTIONS:
            break
    return sections


def extract_entities(markdown: str) -> dict[str, list[str]]:
    """Bounded contact/commercial facts found on the page."""
    text = _plain_text(markdown, 200_000)

    emails: list[str] = []
    for email in _EMAIL_RE.findall(text):
        email = email.lower().rstrip(".")
        if email not in emails:
            emails.append(email)
        if len(emails) >= _MAX_ENTITIES:
            break

    prices: list[str] = []
    for price in _PRICE_RE.findall(text):
        price = price.strip()
        if price not in prices:
            prices.append(price)
        if len(prices) >= _MAX_ENTITIES:
            break

    phones: list[str] = []
    for phone in _PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", phone)
        # Local short codes and dates produce many false positives; require
        # a plausible phone length before surfacing one.
        if not 7 <= len(digits) <= 15:
            continue
        phone = phone.strip()
        if phone not in phones:
            phones.append(phone)
        if len(phones) >= _MAX_ENTITIES:
            break

    return {"emails": emails, "phones": phones, "prices": prices}


def build_structured_doc(
    url: str, title: str | None, markdown: str, lang: str | None
) -> dict:
    """Assemble the payload stored on ``Document.meta``."""
    return {
        "title": (title or "")[:200],
        "lang": lang,
        "intent": classify_intent(url, title),
        "summary": extract_summary(markdown),
        "sections": extract_sections(markdown),
        "entities": extract_entities(markdown),
        "word_count": len(_plain_text(markdown, 1_000_000).split()),
    }
